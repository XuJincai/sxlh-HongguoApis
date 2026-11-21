# coding=utf-8
"""上新/分类发现接口（游客态可用）。

App 端点：POST https://api5-normal-sinfonlineb.fqnovel.com/reading/distribution/category/landpage/v/
gzip 无（明文 JSON body），x-ss-stub = md5(body).hex 小写。
签名族：x-gorgon 只接受 hash F13 分支 0（与搜索族一致，需对 _rticket 微调重试）。

用途：官网搜索索引与 App 不同步时，按「线上时间倒序」补当天新剧。
筛选维度（select_items）：genre / sort / online_time / gender / category_dim_* 等。
"""

import json
import random
import time
import urllib.parse

from utils.hongguo_sign import (python_url_encode, sign_headers, branch_of,
                                 x_ladon, x_argus, x_gorgon, x_helios, md5_raw)
from utils.medusa import build_medusa

CATEGORY_API = 'https://api5-normal-sinfonlineb.fqnovel.com/reading/distribution/category/landpage/v/'

# 目录族走 7.3.5.32 版本指纹
_META_DEVICE = {
    'ac': 'wifi', 'channel': 'update_64', 'aid': '8662', 'app_name': 'novelread',
    'version_code': '73532', 'version_name': '7.3.5.32',
    'device_platform': 'android', 'os': 'android', 'ssmix': 'a',
    'device_type': '25053RT47C', 'device_brand': 'Redmi', 'language': 'zh',
    'os_api': '36', 'os_version': '16', 'manifest_version_code': '73532',
    'resolution': '1280*2772', 'dpi': '520', 'update_version_code': '73532',
    'host_abi': 'arm64-v8a', 'dragon_device_type': 'phone', 'pv_player': '73532',
    'compliance_status': '0', 'need_personal_recommend': '1', 'player_so_load': '1',
    'is_android_pad_screen': '0',
}
CATEGORY_UA = ('com.phoenix.read/73532 (Linux; U; Android 16; zh_CN; '
               '25053RT47C; Build/BP2A.250605.031.A3)')


def landpage_body(genre: str = 'short_play', req_scene: str = 'default',
                  offset: int = 0, limit: int = 50, session_id: str = '',
                  online_time: str = 'days_7') -> dict:
    """上新列表 body。

    :param genre: short_play（真人剧）/ ai_series（AI 剧）
    :param req_scene: default / ai_series
    :param offset: 翻页游标（来自上一页 next_offset）
    :param session_id: 翻页会话 id（来自上一页响应）
    :param online_time: days_7 / days_30 等时间窗
    """
    return {
        'filter_ids': '',
        'req_scene': req_scene,
        'offset': offset,
        'need_selector_panel': False,
        'limit': limit,
        'select_items': {
            'genre': [genre],
            'sort': ['online_time'],
            'category_dim_theme': [],
            'category_dim_role': [],
            'category_dim_epoch': [],
            'gender': [],
            'online_time': [online_time],
            'creation_status': [],
        },
        'session_id': session_id,
        'req_type': 'only_content' if offset else 'default',
        'client_req_type': 3,
    }


def landpage_request(identity, genre: str = 'short_play',
                     req_scene: str = 'default', offset: int = 0,
                     session_id: str = '', online_time: str = 'days_7'):
    """生成一次上新列表请求 (url, body, headers)。签名只认分支 0，微调 _rticket。"""
    payload = landpage_body(genre, req_scene, offset, 50, session_id, online_time)
    body = json.dumps(payload, separators=(',', ':')).encode()
    khronos = int(time.time())
    ticket_base = int(time.time() * 1000)

    device = dict(_META_DEVICE)
    device.update({'iid': identity.iid, 'device_id': identity.device_id,
                   'cdid': identity.cdid})
    if getattr(identity, 'klink_egdi', ''):
        device['klink_egdi'] = identity.klink_egdi

    for n in range(128):
        ticket = ticket_base + n
        query = python_url_encode({**device, 'ts': str(khronos),
                                   '_rticket': str(ticket)})
        if branch_of(query.encode(), body, khronos) == 0:
            break
    else:
        raise RuntimeError('无法生成分支 0 的目录请求签名')
    url = f'{CATEGORY_API}?{query}'
    headers = {
        'cookie': 'passport_csrf_token_default=0cbeb34f30a674b5a7821be5cde462f6',
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'x-xs-from-web': '0',
        'x-ss-req-ticket': str(ticket),
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'x-tt-request-tag': 't=0;n=0',
        'lc': '101',
        'sdk-version': '2',
        'passport-sdk-version': '5051452',
        'content-type': 'application/json; charset=utf-8',
        'x-ss-stub': md5_raw(body).hex(),
        'x-tt-store-region': 'cn',
        'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662',
        'x-tt-trace-id': '00-%032x-%016x-01' % (random.getrandbits(128),
                                                random.getrandbits(64)),
        'user-agent': CATEGORY_UA,
        'accept-encoding': 'identity',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), body, khronos, random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, body, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': _META_DEVICE['version_name']}),
        'content-length': str(len(body)),
    }
    return url, body, headers


def parse_landpage(data: dict) -> dict:
    """上新响应 -> {series: [...], next_offset, session_id, has_more}。"""
    out = []
    for row in (data.get('data') or {}).get('video_data') or []:
        sid = str(row.get('series_id') or '')
        if not sid.isdigit():
            continue
        labels = []
        tag = (row.get('tag_info') or {}).get('text') or ''
        if tag:
            labels.append(tag)
        for item in row.get('sub_title_list') or []:
            if item.get('content'):
                labels.append(item['content'])
        out.append({
            'book_id': sid,
            'title': row.get('title') or row.get('series_title') or row.get('series_name'),
            'abstract': row.get('video_desc') or row.get('series_intro'),
            'cover': row.get('cover'),
            'episode_count': row.get('episode_cnt'),
            'tags': [t for t in labels if t not in ('新剧', '今日上新')][:4],
            'released_today': '今日上新' in labels,
        })
    d = data.get('data') or {}
    return {
        'series': out,
        'next_offset': d.get('next_offset'),
        'session_id': str(d.get('session_id') or ''),
        'has_more': d.get('has_more'),
    }
