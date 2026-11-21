# coding=utf-8
"""评论接口（游客态可用）。

App 端点：POST https://api5-normal-sinfonlinea.fqnovel.com/novel/commentapi/comment/list/{group_id}/v1
gzip JSON body，x-ss-stub = md5(body).upper()。

两类列表：
- 剧评（group_type=1, group_id=series_id, comment_source=1, server_channel=33）
- 单集评论（group_type=30, group_id=video_id, comment_source=4, server_channel=17）

body / query / header 与客户端 7.4.5 一致（utils/alignment 校验）。
"""

import gzip as _gzip
import json
import random
import time
import urllib.parse

from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios, md5_hex
from utils.medusa import build_medusa
from utils.device_profile import DEVICE_PROFILES, new_trace_id

COMMENT_LIST_API = 'https://api5-normal-sinfonlinea.fqnovel.com/novel/commentapi/comment/list/{group_id}/v1'

COMMENT_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
              '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
              '2026-03-03 QuicVersion:21ac1950 2025-11-18)')


def _business_param(book_id: str) -> dict:
    """评论列表 body 的 business_param 公共块。"""
    return {
        'book_id': str(book_id),
        'comment_sort_debug': False,
        'end_offset_time': 0,
        'hit_interaction_data_migration_ab': False,
        'is_last_episode': False,
        'item_count': 0,
        'max_item_count': 0,
        'need_count': True,
        'need_danmaku_occlusion_face_data': True,
        'outflow_comment_count': 0,
        'para_index': 0,
        'playlet_consume_duration_ms': 0,
        'playlet_item_consume_duration_ms': 0,
        'read_item_count': 0,
        'related_album_id': 0,
        'req_type': 0,
        'start_offset_time': 0,
        'playlet_item_duration': 0,
    }


def build_comment_body(group_id: str, group_type: int, comment_source: int,
                       server_channel: int, comment_type: int,
                       book_id: str = '', count: int = 20, cursor: str = '',
                       sort: int = 1) -> dict:
    """评论列表请求 body。

    :param group_id: 剧评=series_id；单集评论=video_id
    :param group_type: 剧评=1；单集=30
    :param comment_source: 剧评=1；单集=4
    :param server_channel: 剧评=33；单集=17
    :param comment_type: 剧评=2；单集=4
    """
    body = {
        'business_param': _business_param(book_id or group_id),
        'comment_source': comment_source,
        'comment_type': comment_type,
        'count': count,
        'group_id': str(group_id),
        'group_type': group_type,
        'server_channel': server_channel,
        'sort': sort,
    }
    if cursor:
        body['cursor'] = cursor
    return body


def _comment_query(identity, stamp_ms: int) -> str:
    """评论族 query（客户端形态：aid/compliance_status 前置的公共块）。"""
    profile = DEVICE_PROFILES['xiaomi_pad']
    pairs = [
        ('aid', '8662'), ('compliance_status', '0'),
        ('device_platform', 'android'), ('os', 'android'), ('ssmix', 'a'),
        ('_rticket', str(stamp_ms)), ('cdid', identity.cdid),
        ('channel', 'update'), ('app_name', 'novelread'),
        ('version_code', '74532'), ('version_name', '7.4.5.32'),
        ('manifest_version_code', '74532'), ('update_version_code', '74532'),
        ('resolution', profile['resolution']), ('dpi', profile['dpi']),
        ('device_type', profile['device_type']),
        ('device_brand', profile['device_brand']),
        ('language', 'zh'), ('os_api', '36'), ('os_version', '16'),
        ('ac', 'wifi'), ('is_64_runtime', 'false'), ('is_64_device', 'true'),
        ('', ''),
        ('host_abi', 'armeabi-v7a'), ('dragon_device_type', 'phone'),
        ('pv_player', '74532'), ('is_x86_device', 'false'),
        ('need_personal_recommend', '1'), ('player_so_load', '1'),
        ('is_android_pad_screen', '0'),
        ('rom_version', profile['rom_version']),
        ('iid', identity.iid), ('device_id', identity.device_id),
    ]
    if getattr(identity, 'klink_egdi', ''):
        pairs.append(('klink_egdi', identity.klink_egdi))
    return '&'.join(f'{k}={urllib.parse.quote(str(v), safe="")}' if k else ''
                    for k, v in pairs)


def comment_list_request(identity, group_id: str, group_type: int = 1,
                         comment_source: int = 1, server_channel: int = 33,
                         comment_type: int = 2, book_id: str = '',
                         count: int = 20, cursor: str = ''):
    """生成一次评论列表请求 (url, body_gz, headers)。

    剧评：group_type=1, comment_source=1, server_channel=33, comment_type=2,
          group_id/book_id 都是 series_id。
    单集评论：group_type=30, comment_source=4, server_channel=17,
              comment_type=4, group_id=video_id, book_id=series_id。
    """
    payload = build_comment_body(group_id, group_type, comment_source,
                                 server_channel, comment_type, book_id,
                                 count, cursor)
    raw = json.dumps(payload, separators=(',', ':')).encode()
    body = _gzip.compress(raw, mtime=0)
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = _comment_query(identity, ticket)
    url = COMMENT_LIST_API.format(group_id=group_id) + '?' + query
    headers = {
        'cookie': 'passport_csrf_token_default=0cbeb34f30a674b5a7821be5cde462f6',
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'content-encoding': 'gzip',
        'x-xs-from-web': '0',
        'x-ss-req-ticket': str(ticket),
        'x-reading-request': f'{ticket}-{random.randint(100000000, 999999999)}',
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'comment-source': str(comment_source),
        'server-channel': str(server_channel),
        'x-tt-request-tag': 'novel_preload=0',
        'lc': '101',
        'sdk-version': '2',
        'passport-sdk-version': '5051452',
        'content-type': 'application/json; charset=utf-8',
        'x-ss-stub': md5_hex(body),
        'x-tt-store-region': 'cn-bj',
        'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662',
        'x-tt-trace-id': new_trace_id(),
        'user-agent': COMMENT_UA,
        'accept-encoding': 'gzip, deflate, br',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), body, khronos, random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, body, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': '7.4.5.32'}),
        'content-length': str(len(body)),
    }
    if getattr(identity, 'sessionid', None):
        headers['cookie'] = ('passport_csrf_token_default='
                             '0cbeb34f30a674b5a7821be5cde462f6; '
                             f'sessionid={identity.sessionid}')
    return url, body, headers


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def parse_comment_list(data: dict) -> dict:
    """评论列表响应 -> {comments, total, cursor, has_more}。"""
    out = []
    for item in (data.get('data') or {}).get('data_list') or []:
        c = item.get('comment') or {}
        common = c.get('common') or {}
        user = ((common.get('user_info') or {}).get('base_info') or {})
        stat = c.get('stat') or {}
        out.append({
            'comment_id': c.get('comment_id'),
            'text': (common.get('content') or {}).get('text'),
            'create_time': common.get('create_timestamp'),
            'user_id': user.get('user_id'),
            'user_name': user.get('user_name'),
            'avatar': user.get('user_avatar'),
            'digg_count': stat.get('digg_count'),
            'reply_count': stat.get('reply_count'),
            'status': common.get('status'),
        })
    info = ((data.get('data') or {}).get('common_list_info') or {})
    return {
        'comments': out,
        'total': info.get('total'),
        'cursor': info.get('cursor'),
        'has_more': info.get('has_more'),
    }
