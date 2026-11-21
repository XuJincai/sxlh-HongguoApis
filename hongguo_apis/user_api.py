# coding=utf-8
"""游客态用户信息接口。

App 端点：GET https://api5-normal-sinfonlinea.fqnovel.com/reading/user/info/v
游客身份也返回匿名用户档案（user_id/偏好/设置位），登录态返回完整用户信息。
"""

import json
import random
import time
import urllib.request

from utils.hongguo_sign import x_gorgon, x_ladon, x_argus, x_helios
from utils.medusa import build_medusa
from utils.device_profile import (build_common_query, DEVICE_PROFILES,
                                  new_trace_id, new_reading_request,
                                  decode_response)

USER_INFO_API = 'https://api5-normal-sinfonlinea.fqnovel.com/reading/user/info/v'
USER_UA = ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
           '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 '
           '2026-03-03 QuicVersion:21ac1950 2025-11-18)')


def user_info_request(identity):
    """生成一次用户信息请求 (url, headers)。"""
    khronos = int(time.time())
    ticket = int(time.time() * 1000)
    query = build_common_query(identity, ticket)
    url = USER_INFO_API + '?' + query
    headers = {
        'cookie': 'passport_csrf_token_default=0cbeb34f30a674b5a7821be5cde462f6',
        'accept': 'application/json; charset=utf-8,application/x-protobuf',
        'x-xs-from-web': '0',
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
        'user-agent': USER_UA,
        'accept-encoding': 'gzip, deflate, br',
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), None, khronos, random.getrandbits(16)),
        'x-helios': x_helios(khronos),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-medusa': build_medusa(url, None, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': '7.4.5.32'}),
    }
    if getattr(identity, 'sessionid', None):
        headers['cookie'] = (f'passport_csrf_token_default='
                             f'0cbeb34f30a674b5a7821be5cde462f6; '
                             f'sessionid={identity.sessionid}')
    return url, headers


def fetch_user_info(identity, timeout: int = 20) -> dict:
    """拉取并返回用户信息 dict。"""
    url, headers = user_info_request(identity)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = decode_response(r.read(), r.headers.get('content-encoding', ''))
    return json.loads(raw)


def parse_user_info(data: dict) -> dict:
    """用户信息响应 -> {user_id, name, avatar, ...}。

    游客态返回匿名档案（user_name=「用户」+device_id 前缀）。
    """
    user = data.get('data') or {}
    return {
        'user_id': str(user.get('req_id') or user.get('user_id') or ''),
        'name': user.get('user_name'),
        'avatar': user.get('avatar_url'),
        'gender': user.get('gender'),
        'privilege': user.get('privilege'),
        'raw': data,
    }
