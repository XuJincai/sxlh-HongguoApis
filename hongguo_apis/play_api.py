# coding=utf-8
"""播放/详情接口（游客态可用）。

App 端点（均 POST，gzip JSON body，x-ss-stub = md5(body).upper()）：
- /novel/player/video_detail/v1/ —— 短剧详情页（剧集列表、简介、角标）
- /novel/player/multi_video_model/v1/ —— 批量取剧集播放源（video_model 内嵌 JSON）
- /novel/player/multi_video_model/player/v1 —— 播放器场景批量取源

签名族：x-gorgon + x-khronos + x-ss-stub + x-helios + x-medusa。
7.4.5.32 指纹 + series_id 字段（payload 与 query 参数集按 App 7.4.5 版本对齐）。
"""

import json
import random
import time

from utils.hongguo_sign import (python_url_encode, x_gorgon, x_ladon,
                                 x_argus, x_helios, gzip_body, md5_hex)
from utils.medusa import build_medusa

API_BASE = 'https://api5-normal-sinfonlinea.fqnovel.com'
VIDEO_DETAIL_API = API_BASE + '/novel/player/video_detail/v1/'
VIDEO_MODEL_API = API_BASE + '/novel/player/multi_video_model/v1/'
PLAYER_MODEL_API = API_BASE + '/novel/player/multi_video_model/player/v1'

# 7.4.5.32 指纹（query 参数集按该版本客户端逐项对齐）
_PLAY_DEVICE = {
    'device_platform': 'android', 'os': 'android', 'ssmix': 'a',
    'channel': 'update', 'aid': '8662', 'app_name': 'novelread',
    'version_code': '74532', 'version_name': '7.4.5.32',
    'manifest_version_code': '74532', 'update_version_code': '74532',
    'resolution': '1080*2232', 'dpi': '420', 'device_type': '23116PN5BC',
    'device_brand': 'Xiaomi', 'language': 'zh', 'os_api': '36',
    'os_version': '16', 'ac': 'wifi', 'is_64_runtime': 'false',
    'is_64_device': 'true', 'host_abi': 'armeabi-v7a',
    'dragon_device_type': 'phone', 'pv_player': '74532',
    'is_x86_device': 'false', 'compliance_status': '0',
    'need_personal_recommend': '1', 'player_so_load': '1',
    'is_android_pad_screen': '0',
    'rom_version': 'miui_V816_OS3.0.309.0.WNBCNXM',
}
PLAY_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; 23116PN5BC; '
           'Build/BP2A.250605.031.A3; Cronet/TTNet)')


def _signed_post(identity, api: str, payload: dict):
    """构造一次签名 POST（gzip body + 全套签名头）。"""
    device = dict(_PLAY_DEVICE)
    device.update({'iid': identity.iid, 'device_id': identity.device_id,
                   'cdid': identity.cdid})
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = python_url_encode({**device, '_rticket': str(ticket)})
    body = gzip_body(json.dumps(payload, separators=(',', ':')))
    url = f'{api}?{query}'
    headers = {
        'User-Agent': PLAY_UA,
        'Accept': 'application/json; charset=utf-8,application/x-protobuf',
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Encoding': 'gzip',
        'x-ss-req-ticket': str(ticket),
        'x-reading-request': f'{ticket + 1}-{random.randint(100000000, 999999999)}',
        'x-vc-bdturing-sdk-version': '4.0.3.cn', 'lc': '101', 'sdk-version': '2',
        'passport-sdk-version': '5051452', 'x-ss-stub': md5_hex(body),
        'x-tt-store-region': 'cn-bj', 'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662', 'x-xs-from-web': '0',
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos), 'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), body, khronos, random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-medusa': build_medusa(url, body, khronos,
                                  {'device_id': identity.device_id,
                                   'version_name': '7.4.5.32'}),
    }
    if getattr(identity, 'sessionid', None):
        headers['Cookie'] = f'sessionid={identity.sessionid}'
    return url, body, headers


def video_detail_request(identity, book_id: str):
    """短剧详情（剧集列表+简介）。book_id 形如 7703125506568244248。

    App 7.4.5 起 payload 用 series_id 字段（book_id 字段已废）。
    """
    sid = str(book_id)
    payload = {
        'series_id': sid, 'source': 2,
        'expand_info': {'page_params': [{'page_code': '0'}]},
        'passback': '', 'need_bg_cover': True,
        'expand_params': {'expand_inner_infos': {
            'single_col_detail': [{'series_id': sid}]}},
    }
    return _signed_post(identity, VIDEO_DETAIL_API, payload)


def multi_video_model_request(identity, video_ids: list, offset=0, count=20):
    """批量取剧集播放源（video_model 内嵌 JSON，含多清晰度 URL）。"""
    payload = {
        'mixed_video_id_map': {'1004': [str(v) for v in video_ids]},
        'pagination': {'offset': offset, 'count': count},
        'source': 1, 'pack_channel': 'video_playback',
    }
    return _signed_post(identity, VIDEO_MODEL_API, payload)


def player_model_request(identity, video_ids: list):
    """播放器场景批量取源。video_ids 是单集 id 列表。"""
    payload = {
        'biz_param': {
            'detail_page_version': 0, 'device_level': 3,
            'disable_digg_stat': False, 'disable_video_relate_book': False,
            'need_all_video_definition': True, 'need_mp4_align': False,
            'use_os_player': False, 'use_server_dns': False,
            'video_platform': 1024,
        },
        'dr_scene': 'player',
        'mixed_video_id_map': {'1004': [str(v) for v in video_ids]},
    }
    return _signed_post(identity, PLAYER_MODEL_API, payload)


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def parse_video_detail(data: dict) -> dict:
    """详情响应 -> {title, abstract, episode_list: [{video_id, ...}], ...}"""
    vd = (data.get('data') or {}).get('video_data') or {}
    episodes = []
    for ep in vd.get('video_list') or []:
        episodes.append({
            'video_id': str(ep.get('vid') or ''),
            'title': ep.get('title') or f"第{ep.get('vid_index', '')}集",
            'index': ep.get('vid_index'),
            'comment_count': ep.get('comment_count'),
            'digged_count': ep.get('digged_count'),
            'thumb': ep.get('cover') or ep.get('episode_cover'),
            'duration': ep.get('duration'),
        })
    cats = []
    try:
        for c in json.loads(vd.get('category_schema') or '[]'):
            if isinstance(c, dict) and c.get('name'):
                cats.append(c['name'])
    except (ValueError, TypeError):
        cats = []
    return {
        'book_id': str(vd.get('series_id_str') or vd.get('series_id') or ''),
        'title': vd.get('series_title'),
        'abstract': vd.get('series_intro'),
        'cover': vd.get('series_cover'),
        'category': '/'.join(cats),
        'episode_count': vd.get('episode_cnt'),
        'episode_text': vd.get('episode_right_text'),
        'play_count': vd.get('series_play_cnt'),
        'digg_count': vd.get('digg_cnt'),
        'followed': vd.get('followed'),
        'episode_list': episodes,
    }


def parse_video_models(data: dict) -> dict:
    """multi_video_model 响应 -> {video_id: {main_url, qualities, ...}}。

    data 值里的 video_model 是内嵌 JSON 字符串，解出 video_list 各清晰度。
    """
    out = {}
    data = data or {}
    for vid, entry in (data.get('data') or {}).items():
        try:
            model = json.loads(entry.get('video_model') or '{}')
        except (ValueError, TypeError):
            continue
        qualities = []
        for item in model.get('video_list') or []:
            meta = item.get('video_meta') or {}
            qualities.append({
                'quality_type': item.get('quality_type'),
                'main_url': item.get('main_url'),
                'backup_url': item.get('backup_url'),
                'definition': meta.get('definition'),
                'vtype': meta.get('vtype'),
                'encrypted': bool((item.get('encrypt_info') or {}).get('encrypt')),
            })
        out[str(vid)] = {
            'duration': model.get('video_duration'),
            'url_expire': model.get('url_expire'),
            'qualities': qualities,
            'main_url': (qualities[-1]['main_url'] if qualities else None),
        }
    return out
