# coding=utf-8
"""播放/详情接口（游客态可用）。

App 端点（均 POST，gzip JSON body，x-ss-stub = md5(body).upper()）：
- /novel/player/video_detail/v1/ —— 短剧详情页（剧集列表、简介、角标）
- /novel/player/multi_video_model/v1/ —— 批量取剧集播放源（video_model 内嵌 JSON）
- /novel/player/multi_video_model/player/v1 —— 播放器场景批量取源

请求与 App 7.4.5 逐字段一致（utils/device_profile 公共块 + utils/alignment 校验）：
query 34+1 参数含 klink_egdi，header 24 个含 x-reading-request/x-tt-trace-id，
顺序均按客户端实际发送。
"""

import json
import random
import time

from utils.hongguo_sign import (x_gorgon, x_ladon, x_argus, x_helios,
                                 gzip_body, md5_hex)
from utils.medusa import build_medusa
from utils.device_profile import (build_common_query, DEVICE_PROFILES,
                                  new_trace_id, new_reading_request)

API_BASE = 'https://api5-normal-sinfonlinea.fqnovel.com'
VIDEO_DETAIL_API = API_BASE + '/novel/player/video_detail/v1/'
VIDEO_MODEL_API = API_BASE + '/novel/player/multi_video_model/v1/'
PLAYER_MODEL_API = API_BASE + '/novel/player/multi_video_model/player/v1'
SINGLE_VIDEO_MODEL_API = API_BASE + '/novel/player/video_model/v1/'

PLAY_UA = DEVICE_PROFILES['xiaomi_pad']['ua']


def _signed_post(identity, api: str, payload: dict):
    """构造一次签名 POST。query/header 与客户端逐字段一致。"""
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    body = gzip_body(json.dumps(payload, separators=(',', ':')))
    url = f'{api}?{query}'
    headers = {
        'cookie': 'passport_csrf_token_default=0cbeb34f30a674b5a7821be5cde462f6',
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'content-encoding': 'gzip',
        'x-xs-from-web': '0',
        'x-ss-req-ticket': str(ticket),
        'x-reading-request': new_reading_request(ticket),
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'lc': '101',
        'sdk-version': '2',
        'passport-sdk-version': '5051452',
        'content-type': 'application/json; charset=utf-8',
        'x-ss-stub': md5_hex(body),
        'x-tt-store-region': 'cn-bj',
        'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662',
        'x-tt-trace-id': new_trace_id(),
        'user-agent': PLAY_UA,
        'accept-encoding': 'gzip, deflate, br',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), body, khronos, random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, body, khronos,
                                  {'device_id': identity.device_id,
                                   'version_name': '7.4.5.32'}),
    }
    if getattr(identity, 'sessionid', None):
        headers['cookie'] = (f'passport_csrf_token_default='
                             '0cbeb34f30a674b5a7821be5cde462f6; '
                             f'sessionid={identity.sessionid}')
    return url, body, headers


def video_detail_request(identity, book_id: str):
    """短剧详情（剧集列表+简介）。book_id 形如 7703125506568244248。

    body 用 single_col 详情页形态（biz_param + series_id），
    image_shrink_datas_str 为 base64 的图片缩放参数（客户端原值）。
    """
    payload = {
        'biz_param': {
            'detail_page_version': 1,
            'disable_digg_stat': False,
            'disable_video_relate_book': False,
            'image_shrink_datas_str': (
                'W3siaW1hZ2VfdHlwZSI6MywiaW1hZ2Vfd2lkdGgiOjEwNzks'
                'InNocmlua190eXBlIjozfSx7ImltYWdlX3R5cGUiOjQsImlt'
                'YWdlX3dpZHRoIjo5NCwic2hyaW5rX3R5cGUiOjR9XQ==\n'),
            'need_all_video_definition': False,
            'need_mp4_align': False,
            'screen_width_px': '1079',
            'source': 5,
            'use_os_player': False,
            'use_server_dns': False,
            'video_id_type': 1,
        },
        'series_id': str(book_id),
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


def single_video_model_request(identity, video_id: str):
    """单集播放源（video_model/v1）。video_id 是单集 id。"""
    payload = {
        'biz_param': {
            'detail_page_version': 0, 'device_level': 3,
            'disable_digg_stat': False, 'disable_video_relate_book': False,
            'from_video_id': '', 'need_all_video_definition': True,
            'need_mp4_align': False, 'source': 1, 'use_os_player': False,
            'use_server_dns': False, 'video_platform': 3,
        },
        'content_type': 1004,
        'video_id': str(video_id),
    }
    return _signed_post(identity, SINGLE_VIDEO_MODEL_API, payload)


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
