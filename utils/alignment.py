# coding=utf-8
"""请求一致性工具：把生成的请求与客户端模板逐字段 diff。

原则：一个参数不能少、一个字段的长度不能减、header 顺序也要对齐。
请求成功不代表真成功 —— 缺字段短期可能照常返回，长期会累积风控。

用法：
    from utils.alignment import diff_request
    delta = diff_request('video_detail', query, headers)
    delta['missing_query']   # 模板有而请求缺的参数
    delta['extra_query']     # 请求多出的参数
    delta['order_query']     # 顺序不一致
    delta['missing_headers'] # 模板有而请求缺的头
    delta['extra_headers']   # 请求多出的头
    delta['order_headers']   # header 顺序不一致
    delta['length_delta']   # 字段长度差异
"""

import json
import os

# 公共 query 块（7.4.5.32，顺序即客户端发送顺序）。
COMMON_QUERY_ORDER = [
    'device_platform', 'os', 'ssmix', '_rticket', 'cdid', 'channel', 'aid',
    'app_name', 'version_code', 'version_name', 'manifest_version_code',
    'update_version_code', 'resolution', 'dpi', 'device_type', 'device_brand',
    'language', 'os_api', 'os_version', 'ac', 'is_64_runtime', 'is_64_device',
    'host_abi', 'dragon_device_type', 'pv_player', 'is_x86_device',
    'compliance_status', 'need_personal_recommend', 'player_so_load',
    'is_android_pad_screen', 'rom_version', 'iid', 'device_id', 'klink_egdi',
]

# 评论族公共块：aid/compliance_status 前置，compliance_status 位置不同
COMMENT_QUERY_ORDER = [
    'aid', 'compliance_status', 'device_platform', 'os', 'ssmix', '_rticket',
    'cdid', 'channel', 'app_name', 'version_code', 'version_name',
    'manifest_version_code', 'update_version_code', 'resolution', 'dpi',
    'device_type', 'device_brand', 'language', 'os_api', 'os_version', 'ac',
    'is_64_runtime', 'is_64_device', 'host_abi', 'dragon_device_type',
    'pv_player', 'is_x86_device', 'need_personal_recommend', 'player_so_load',
    'is_android_pad_screen', 'rom_version', 'iid', 'device_id', 'klink_egdi',
]

# 公共 header 顺序（h2 伪头之后的实际顺序，POST 族 video_detail 为例）
COMMON_HEADER_ORDER = [
    'cookie', 'accept', 'content-encoding', 'x-xs-from-web', 'x-ss-req-ticket',
    'x-reading-request', 'x-vc-bdturing-sdk-version', 'lc', 'sdk-version',
    'passport-sdk-version', 'content-type', 'x-ss-stub', 'x-tt-store-region',
    'x-tt-store-region-src', 'x-ss-dp', 'x-tt-trace-id', 'user-agent',
    'accept-encoding', 'x-argus', 'x-gorgon', 'x-helios', 'x-khronos',
    'x-ladon', 'x-medusa',
]

# GET 族比 POST 少 content-encoding/content-type/x-ss-stub；commentapi 族多
# comment-source/server-channel/x-tt-request-tag（按客户端实际出现的顺序）
GET_HEADER_ORDER = [
    'cookie', 'accept', 'x-xs-from-web', 'x-ss-req-ticket', 'x-reading-request',
    'x-vc-bdturing-sdk-version', 'lc', 'sdk-version', 'passport-sdk-version',
    'x-tt-store-region', 'x-tt-store-region-src', 'x-ss-dp', 'x-tt-trace-id',
    'user-agent', 'accept-encoding', 'x-argus', 'x-gorgon', 'x-helios',
    'x-khronos', 'x-ladon', 'x-medusa',
]

COMMENT_HEADER_ORDER = [
    'cookie', 'accept', 'content-encoding', 'x-xs-from-web', 'x-ss-req-ticket',
    'x-reading-request', 'x-vc-bdturing-sdk-version', 'comment-source',
    'server-channel', 'x-tt-request-tag', 'lc', 'sdk-version',
    'passport-sdk-version', 'content-type', 'x-ss-stub', 'x-tt-store-region',
    'x-tt-store-region-src', 'x-ss-dp', 'x-tt-trace-id', 'user-agent',
    'accept-encoding', 'x-argus', 'x-gorgon', 'x-helios', 'x-khronos',
    'x-ladon', 'x-medusa',
]

_HEADER_ORDERS = {
    'post': COMMON_HEADER_ORDER,
    'get': GET_HEADER_ORDER,
    'comment': COMMENT_HEADER_ORDER,
}


def _query_keys(query: str) -> list:
    return [p.split('=')[0] for p in query.split('&') if p]


def _norm_headers(headers: dict) -> list:
    """按实际发送序取 key（dict 保持插入序）；统一小写比较。"""
    return [k.lower() for k in headers.keys()]


def _order_mismatch(actual: list, expected: list) -> list:
    """两边都有的键里，顺序与模板不一致的键列表。"""
    act = [k for k in actual if k in expected]
    exp = [k for k in expected if k in actual]
    return [k for k in (set(act) ^ set(exp)) and []] or \
           ([k for k, e in zip(act, exp) if k != e] if act != exp else [])


def diff_request(kind: str, query: str, headers: dict,
                 header_order: list = None) -> dict:
    """一致性 diff。kind: 'post' | 'get' | 'comment' | 'comment_query'。

    :param query: '?' 之后的 query 串
    :param headers: 请求头 dict（保持插入顺序）
    """
    actual_q = _query_keys(query)
    expected_q = COMMENT_QUERY_ORDER if kind == 'comment' else COMMON_QUERY_ORDER
    # 各接口的业务参数（在公共块前或后）不在模板里，单独归组
    common_set = set(expected_q)
    actual_common = [k for k in actual_q if k in common_set]
    actual_business = [k for k in actual_q if k not in common_set]

    delta = {
        'kind': kind,
        'missing_query': [k for k in expected_q if k not in actual_q],
        'extra_query': actual_business,
        'order_query': _order_mismatch(actual_common, expected_q),
        'business_params': actual_business,
    }

    order = header_order or _HEADER_ORDERS.get(kind, COMMON_HEADER_ORDER)
    actual_h = _norm_headers(headers)
    expected_set = set(order)
    delta['missing_headers'] = [k for k in order
                                if k not in actual_h and k != 'cookie']
    delta['extra_headers'] = [k for k in actual_h if k not in expected_set
                              and not k.startswith(':')
                              and k != 'content-length']
    act_common = [k for k in actual_h if k in expected_set]
    exp_common = [k for k in order if k in act_common]
    delta['order_headers'] = (exp_common != act_common)
    delta['header_order_expected'] = order
    delta['header_order_actual'] = actual_h
    return delta


def format_delta(delta: dict) -> str:
    """渲染成可读报告。"""
    lines = [f"== alignment diff [{delta['kind']}] =="]
    if delta['missing_query']:
        lines.append(f"  query 缺参数: {delta['missing_query']}")
    if delta['order_query']:
        lines.append(f"  query 顺序不一致: {delta['order_query']}")
    if delta['missing_headers']:
        lines.append(f"  header 缺: {delta['missing_headers']}")
    if delta['extra_headers']:
        lines.append(f"  header 多: {delta['extra_headers']}")
    if delta['order_headers']:
        lines.append('  header 顺序不一致:')
        lines.append(f"    模板: {delta['header_order_expected']}")
        lines.append(f"    实际: {delta['header_order_actual']}")
    ok = not (delta['missing_query'] or delta.get('order_query')
              or delta['missing_headers'] or delta['extra_headers']
              or delta['order_headers'])
    lines.insert(1, '  FULLY ALIGNED' if ok else '  DELTAS FOUND')
    return '\n'.join(lines)
