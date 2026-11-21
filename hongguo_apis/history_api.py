# coding=utf-8
"""观看进度上报接口（游客态也会归档到匿名档案）。

App 端点：POST https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/read_history/update/v
gzip JSON body，x-ss-stub = md5(body).upper()。

客户端每看完一段/切集就上报一次：vid/vid_index/累计播放时长等。
游客态上报写匿名档案；登录态写账号档案。
"""

import gzip as _gzip
import json
import random
import time

from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios, md5_hex
from utils.medusa import build_medusa
from utils.device_profile import (build_common_query, new_trace_id,
                                  new_reading_request, decode_response)

READ_HISTORY_API = ('https://api5-normal-sinfonlinea.fqnovel.com'
                    '/reading/bookapi/read_history/update/v')

HISTORY_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
              '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
              '2026-03-03 QuicVersion:21ac1950 2025-11-18)')


def history_update_body(book_id: str, vid: str, vid_index: int = 0,
                        book_type: int = 2, position_ms: int = 0,
                        player_total_ms: int = 0, season_index: int = 0,
                        is_delete: bool = False) -> dict:
    """观看进度 body。

    :param book_id: series_id
    :param vid: 单集 video_id
    :param vid_index: 第几集（1 起）
    :param position_ms: 当前播放位置（毫秒）
    :param player_total_ms: 累计播放时长（毫秒）
    :param is_delete: True = 软删除该记录
    """
    now = int(time.time() * 1000)
    return {
        'update_datas': [{
            'book_id': int(book_id), 'book_type': book_type,
            'chapter_index': 0,
            'current_play_position': position_ms,
            'digged_count': 0, 'duration': 0, 'episode_cnt': 0,
            'is_delete': is_delete, 'is_interactive_game': False,
            'is_listen_mode': False, 'is_multi_season': 0,
            'meet_guide_comment_tag': False, 'origin_novel_book_id': 0,
            'player_accumulate_total_time': player_total_ms,
            'read_timestamp_ms': now, 'recent_reads': 0,
            'retain_video_play_time': 0, 'season_index': season_index,
            'series_play_cnt': 0, 'tone_id': 0,
            'update_timestamp_ms': 0, 'use_soft_delete': False,
            'user_digg': False, 'user_playlet_comment_flag': False,
            'vid': int(vid), 'vid_index': vid_index,
        }],
    }


def history_update_request(identity, book_id: str, vid: str, vid_index: int = 0,
                           position_ms: int = 0, player_total_ms: int = 0,
                           season_index: int = 0, is_delete: bool = False):
    """生成一次观看进度上报 (url, body_gz, headers)。"""
    payload = history_update_body(book_id, vid, vid_index, 2, position_ms,
                                  player_total_ms, season_index, is_delete)
    raw = json.dumps(payload, separators=(',', ':')).encode()
    body = _gzip.compress(raw, mtime=0)
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    url = READ_HISTORY_API + '?' + query
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
        'user-agent': HISTORY_UA,
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
