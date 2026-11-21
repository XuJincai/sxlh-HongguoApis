# coding=utf-8
"""登录态账号接口（App 签名族 + sessionid cookie）。

App 端点（api5-normal-sinfonlinea）：
- GET /reading/user/info/v                    登录后返回完整用户档案
- GET /reading/bookapi/read_history/list/v1/  账号观看历史（book_type=2）

与游客态同一签名族（7.4.5），区别只多一个 Cookie: sessionid=...。
"""

import json
import random
import time
import urllib.request

from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios
from utils.medusa import build_medusa
from utils.device_profile import (build_common_query, new_trace_id,
                                  new_reading_request, decode_response)

ACCOUNT_BASE = 'https://api5-normal-sinfonlinea.fqnovel.com'
USER_INFO_API = ACCOUNT_BASE + '/reading/user/info/v'
HISTORY_LIST_API = ACCOUNT_BASE + '/reading/bookapi/read_history/list/v1/'

ACCOUNT_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
              '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
              '2026-03-03 QuicVersion:21ac1950 2025-11-18)')


def _account_headers(identity, url, body, khronos, ticket):
    """App 签名头 + 登录 cookie。"""
    headers = {
        'cookie': (f'passport_csrf_token_default='
                   f'0cbeb34f30a674b5a7821be5cde462f6; '
                   f'sessionid={identity.sessionid}'),
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'x-ss-req-ticket': str(ticket),
        'x-reading-request': new_reading_request(ticket),
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'lc': '101',
        'sdk-version': '2',
        'passport-sdk-version': '5051452',
        'x-tt-store-region': 'cn-bj',
        'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662',
        'x-tt-trace-id': new_trace_id(),
        'user-agent': ACCOUNT_UA,
        'accept-encoding': 'gzip, deflate, br',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(None if url is None else url.encode(), body, khronos,
                             random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, body, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': '7.4.5.32'}),
    }
    if getattr(identity, 'sessionid_ss', ''):
        headers['cookie'] += f"; sessionid_ss={identity.sessionid_ss}"
    return headers


def user_info_request(identity):
    """登录态用户信息请求 (url, headers)。"""
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    url = USER_INFO_API + '?' + query
    headers = _account_headers(identity, url, None, khronos, ticket)
    return url, headers


def history_list_request(identity, offset: int = 0,
                         last_min_read_ms: int = 0, limit: int = 0):
    """账号观看历史请求 (url, headers)。

    :param offset: 翻页偏移
    :param last_min_read_ms: 上页最小 read_timestamp_ms（增量翻页）
    :param limit: 0 = 服务端默认
    """
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    extra = (f'book_type=2&offset={offset}&last_min_read_timestamp_ms='
             f'{last_min_read_ms}&full_field=true&is_first_load='
             f'{"true" if not offset else "false"}&query_soft_deleted=false')
    url = HISTORY_LIST_API + '?' + query + '&' + extra
    headers = _account_headers(identity, url, None, khronos, ticket)
    return url, headers


def _get_json(url, headers, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = decode_response(r.read(), r.headers.get('content-encoding', ''))
    return json.loads(raw)


def fetch_history_list(identity, **kwargs) -> dict:
    """拉取账号观看历史原始响应。"""
    url, headers = history_list_request(identity, **kwargs)
    return _get_json(url, headers)


def parse_history_list(data: dict) -> dict:
    """观看历史响应 -> {items, has_more, next_offset}。

    item: series_id/episode_id/vid_index/进度(秒)/时长(秒)/时间戳/总集数。
    """
    out = []
    for row in (data.get('data') or {}).get('data_list') or []:
        if row.get('is_delete'):
            continue
        def _ms(v):
            try:
                return max(0, int(v or 0))
            except (TypeError, ValueError):
                return 0
        out.append({
            'series_id': str(row.get('book_id_str') or row.get('book_id') or ''),
            'series_title': row.get('series_title') or row.get('book_name'),
            'cover': row.get('series_cover_url') or row.get('thumb_url') or '',
            'episode_id': str(row.get('vid') or row.get('item_id') or ''),
            'vid_index': row.get('vid_index') or 0,
            'current_time': _ms(row.get('current_play_position')) / 1000,
            'duration': _ms(row.get('duration')) / 1000,
            'updated_at': _ms(row.get('read_timestamp_ms')),
            'episode_cnt': row.get('episode_cnt') or row.get('episode_count') or 0,
        })
    d = data.get('data') or {}
    return {
        'items': out,
        'has_more': d.get('has_more'),
        'next_offset': d.get('offset') or (out[-1]['updated_at'] if out else 0),
    }
