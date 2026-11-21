# coding=utf-8
"""评论写接口：发评论、点赞、取消、删除（登录态）。

全部走 api5-normal-sinfonlinea.fqnovel.com（与评论列表同族），
JSON body + gzip，请求头与评论列表完全对齐，登录态 cookie 注入。

用法（见 main.py commentadd / like 命令）：
    from utils.auth import LoginIdentity
    from hongguo_apis.comment_write_api import add_comment, do_action
    identity = LoginIdentity.from_json_file('login_identity.json')
    add_comment(identity, series_id, '好看')
    do_action(identity, series_id, comment_id, action_type=7)
"""

import gzip
import json
import random
import time
import urllib.parse
import urllib.request

from utils.device_profile import (DEVICE_PROFILES, new_trace_id,
                                  new_reading_request, decode_response)
from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios
from utils.medusa import build_medusa

COMMENT_API_BASE = 'https://api5-normal-sinfonlinea.fqnovel.com'
COMMENT_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
              '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
              '2026-03-03 QuicVersion:21ac1950 2025-11-18)')

# ---------------------------------------------------------------------------
# 枚举值（与服务端协议一致）
# ---------------------------------------------------------------------------
# UgcRelativeType: Book=1（剧评）；SeriesVideo=30（单集评论）
GROUP_TYPE_BOOK = 1
GROUP_TYPE_SERIES_VIDEO = 30
# UgcCommentCommitSourceEnum
COMMIT_SOURCE_PLAYLET_COMMENT = 12      # 短剧剧评
COMMIT_SOURCE_ITEM_COMMENT = 3          # 单集评论
COMMIT_SOURCE_ITEM_DANMAKU = 1500       # 弹幕
# UgcCommentGroupTypeOutter（data_type）
DATA_TYPE_BOOK = 2
DATA_TYPE_NEW_ITEM = 4
DATA_TYPE_DANMAKU = 20
# UgcNovelCommentType
COMMENT_TYPE_USER_ACTUAL = 0
# UgcActionType
ACTION_DIGG = 7
ACTION_UN_DIGG = 14
# UgcActionObjectType
OBJECT_TYPE_COMMENT = 2


def _query(identity, stamp_ms: int) -> str:
    """评论族 query 公共块（与评论列表请求逐字段、顺序一致）。"""
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


def _md5_hex(data: bytes) -> str:
    import hashlib
    return hashlib.md5(data).hexdigest()


def _post_comment_api(path: str, body: dict, identity, timeout: int = 15):
    """评论族 POST：gzip JSON body + 登录态 cookie，返回 (json, set_cookies)。"""
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
    body_gz = gzip.compress(raw, mtime=0)
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = _query(identity, ticket) + '&aid=8662'
    url = COMMENT_API_BASE + path + '?' + query
    headers = {
        'cookie': ('passport_csrf_token_default='
                   '0cbeb34f30a674b5a7821be5cde462f6; '
                   f'sessionid={identity.sessionid}'),
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'content-encoding': 'gzip',
        'x-xs-from-web': '0',
        'x-ss-req-ticket': str(ticket),
        'x-reading-request': new_reading_request(ticket),
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'x-tt-request-tag': 'novel_preload=0',
        'lc': '101',
        'sdk-version': '2',
        'passport-sdk-version': '5051452',
        'content-type': 'application/json; charset=utf-8',
        'x-ss-stub': _md5_hex(body_gz),
        'x-tt-store-region': 'cn-bj',
        'x-tt-store-region-src': 'did',
        'x-ss-dp': '8662',
        'x-tt-trace-id': new_trace_id(),
        'user-agent': COMMENT_UA,
        'accept-encoding': 'gzip, deflate, br',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), body_gz, khronos,
                             random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, body_gz, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': '7.4.5.32'}),
        'content-length': str(len(body_gz)),
    }
    req = urllib.request.Request(url, data=body_gz, headers=headers,
                                 method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        encoding = (r.headers.get('Content-Encoding') or '').lower()
        data = decode_response(data, encoding)
        set_cookies = r.headers.get_all('Set-Cookie') or []
    return json.loads(data.decode('utf-8', 'replace')), set_cookies


def _shark_param(comment_type: str) -> dict:
    """评论入口埋点参数（与服务端形态一致）。"""
    return {
        'enter_from': 'MainFragmentActivity',
        'previous_page': 'PlayletDetailActivity',
        'page_list': 'MainFragmentActivity,PlayletDetailActivity',
        'comment_type': comment_type,
    }


def add_comment(identity, group_id: str, text: str, group_type: int = 1,
                commit_source: int = 12, data_type: int = 2,
                book_id: str = '') -> dict:
    """发评论（登录态）。

    :param group_id: 剧评=series_id；单集评论=video_id（group_type=30）
    :param text: 评论正文
    :param group_type: 1=剧评；30=单集评论
    :param commit_source: 12=短剧剧评；3=单集评论
    :param data_type: 2=书评；4=单集
    :returns: 服务端响应（comment_info 在 data 里）
    """
    body = {
        'business_param': {
            'book_id': book_id or group_id,
            'score': 0,
            'shark_param': _shark_param('playlet_comment'),
            'text_feature': {'input_total_time': '12000',
                             'max_input_word_count': str(len(text))},
            'trans_param': {'watch_duration': '300'},
        },
        'comment_type': COMMENT_TYPE_USER_ACTUAL,
        'commit_source': commit_source,
        'data_type': data_type,
        'group_id': str(group_id),
        'group_type': group_type,
        'text': text,
    }
    return _post_comment_api('/novel/commentapi/comment/add/v1/', body,
                             identity)[0]


def do_action(identity, group_id: str, object_id: str, action_type: int = 7,
              object_type: int = 2, comment_type: int = 2,
              book_id: str = '') -> dict:
    """评论操作（登录态）：点赞 Digg=7 / 取消 UnDigg=14 / 收藏 Favorite=22。

    :param group_id: 评论所属的 series_id（或 video_id）
    :param object_id: 目标 comment_id
    :param action_type: 7=点赞；14=取消点赞
    :param object_type: 2=Comment
    :param comment_type: 与评论列表同族（书评=2；单集=4）
    """
    body = {
        'action_type': action_type,
        'business_param': {
            'book_id': book_id or group_id,
            'shark_param': _shark_param('playlet_comment'),
        },
        'comment_type': comment_type,
        'object_id': str(object_id),
        'object_type': object_type,
    }
    return _post_comment_api('/novel/commentapi/comment/do_action/v1/',
                             body, identity)[0]


def delete_comment(identity, comment_id: str, data_type: int = 30,
                   service_id: int = 4) -> dict:
    """删除自己的评论（登录态）。

    :param data_type: UgcRelativeType（单集评论=30）
    :param service_id: UgcCommentGroupTypeOutter（单集=4）
    """
    body = {
        'comment_id': str(comment_id),
        'data_type': data_type,
        'service_id': service_id,
    }
    return _post_comment_api('/novel/commentapi/comment/del/v1/', body,
                             identity)[0]
