# coding=utf-8
"""相似剧推荐 / 专辑 / 催更信息接口（游客态可用）。

App 端点：POST https://api5-normal-sinfonlinea.fqnovel.com/reading/distribution/book_pack_fields/inner_feed_detail/v1
gzip JSON body，x-ss-stub = md5(body).upper()。

详情页「看了又看」族：一次请求拿专辑归属（第几季/共几季）、催更数、
运营标签（op_tag）、视频标签（爆剧等）。
"""

import gzip as _gzip
import json
import random
import time

from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios, md5_hex
from utils.medusa import build_medusa
from utils.device_profile import (build_common_query, new_trace_id,
                                  new_reading_request, decode_response)

BOOK_PACK_API = ('https://api5-normal-sinfonlinea.fqnovel.com'
                 '/reading/distribution/book_pack_fields/inner_feed_detail/v1')

RECOMMEND_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
                '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
                '2026-03-03 QuicVersion:21ac1950 2025-11-18)')


def book_pack_request(identity, series_ids: list):
    """生成一次相似剧信息请求 (url, body_gz, headers)。

    :param series_ids: series_id 列表（一次最多 ~20）
    """
    payload = {
        'book_pack_channel': 'inner_feed_detail',
        'req_fields': ['ad_replace_vid_map', 'author_user_info', 'album_id',
                       'album_serial_count', 'series_in_album_order',
                       'real_album_serial_count', 'rec_tags', 'video_tag_info',
                       'main_creator_users_group', 'op_tag', 'show_urge_update',
                       'has_urge_update', 'urge_update_count'],
        'req_ids': [int(s) for s in series_ids],
    }
    raw = json.dumps(payload, separators=(',', ':')).encode()
    body = _gzip.compress(raw, mtime=0)
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    url = BOOK_PACK_API + '?' + query
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
        'user-agent': RECOMMEND_UA,
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
        headers['cookie'] = (f'passport_csrf_token_default='
                             f'0cbeb34f30a674b5a7821be5cde462f6; '
                             f'sessionid={identity.sessionid}')
    return url, body, headers


def parse_book_pack(data: dict) -> dict:
    """相似剧响应 -> {series_id: {album, urge_update, tags, ...}}。"""
    out = {}
    for sid, entry in ((data.get('data') or {}) or {}).items():
        album = entry.get('album_info') or {}
        action = entry.get('action_info') or {}
        base = entry.get('base_info') or {}
        expand = entry.get('expand_info') or {}
        tags = []
        for tag in base.get('video_tag_info') or []:
            if tag.get('text'):
                tags.append(tag['text'])
        out[str(sid)] = {
            'album_id': str(album.get('album_id') or ''),
            'album_serial_count': album.get('album_serial_count'),
            'real_album_serial_count': album.get('real_album_serial_count'),
            'season_index': album.get('series_in_album_order'),
            'urge_update_count': action.get('urge_update_count'),
            'show_urge_update': action.get('show_urge_update'),
            'has_urge_update': action.get('has_urge_update'),
            'tags': tags,
            'op_tag': base.get('op_tag'),
            'recommend': expand.get('recommend') or expand,
        }
    return out
