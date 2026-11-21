# coding=utf-8
"""弹幕接口（游客态可用）。

App 端点：POST https://api5-normal-sinfonlineb.fqnovel.com/novel/commentapi/comment/list/{vid}/v1/
每条弹幕带 offset_time（毫秒），按播放进度投放。签名用评论专用族
（X-Gorgon nonce 变体 / X-Ladon / X-Argus，见 utils.comment_sign）。
"""

import json
import time
import urllib.request

from utils.comment_sign import build_query, sign_comment_headers, new_nonce

BASE_URL = 'https://api5-normal-sinfonlineb.fqnovel.com'
COMMENT_UA = ('com.phoenix.read/73532 (Linux; U; Android 16; zh_CN; 25053RT47C; '
              'Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 '
              'QuicVersion:c67e9834 2025-09-08)')

PAGE_COUNT = 90
EFFECTIVE_DURATION_MS = 3600000  # 单次请求声明的剧集时长（窗口上限内取大）


def _request_body(vid: str, book_id: str, start_ms: int, duration_ms: int) -> dict:
    return {
        'comment_source': 601,
        'server_channel': 1000,
        'group_id': vid,
        'group_type': 30,
        'comment_type': 20,
        'sort': 1,
        'count': PAGE_COUNT,
        'cursor': '',
        'aid': 8662,
        'compliance_status': 0,
        'business_param': {
            'book_id': str(book_id),
            'start_offset_time': start_ms,
            'playlet_item_duration': duration_ms,
            'need_danmaku_guide_type': [1, 3, 4, 2],
        },
    }


def danmaku_request(identity, vid: str, book_id: str, start_ms: int = 0,
                    duration_ms: int = EFFECTIVE_DURATION_MS):
    """生成一次弹幕窗口请求的 (url, body, headers)。

    :param identity: GuestIdentity / LoginIdentity
    :param vid: 单集 video_id
    :param book_id: 剧集 series_id
    :param start_ms: 窗口起点（毫秒）
    :param duration_ms: 窗口长度（毫秒），上游上限 24h
    """
    stamp_ms = int(time.time() * 1000)
    stamp = stamp_ms // 1000
    nonce = new_nonce()
    raw_query = build_query(identity.device_id, identity.iid, stamp_ms)
    url = (f'{BASE_URL}/novel/commentapi/comment/list/{vid}/v1/?{raw_query}')
    headers = {
        'User-Agent': COMMENT_UA,
        'Accept': 'application/json',
        'X-XS-From-Web': '0',
        'Sdk-Version': '2',
        'Content-Type': 'application/json; charset=utf-8',
        'Comment-Source': '601',
        'Server-Channel': '1000',
        **sign_comment_headers(raw_query, stamp, nonce),
    }
    body = json.dumps(_request_body(vid, book_id, start_ms, duration_ms),
                      separators=(',', ':')).encode()
    return url, body, headers


def parse_danmaku(data: dict) -> list:
    """响应 -> [{time: 秒, text, color, mode}]。"""
    items = []
    for raw in (data.get('data') or {}).get('data_list') or []:
        comment = raw.get('comment') or {}
        common = comment.get('common') or {}
        content = common.get('content') or {}
        text = (content.get('text') or '').strip()
        if not text or len(text) > 200:
            continue
        offset = raw.get('offset_time')
        if offset is None:
            offset = comment.get('offset_time') or 0
        seconds = offset / 1000 if isinstance(offset, (int, float)) and offset > 100000 else (offset or 0)
        if not 0 <= seconds < 604800:
            continue
        color = '#FFFFFF'
        mode = 'scroll'
        for holder in (content, common, comment):
            if isinstance(holder, dict):
                c = holder.get('color') or holder.get('danmaku_color')
                if c:
                    color = c if str(c).startswith('#') else f'#{int(c):06X}'
                    break
        items.append({'time': round(seconds, 3), 'text': text,
                      'color': color, 'mode': mode})
    return items


def has_more(data: dict) -> bool:
    return bool((data.get('data') or {}).get('common_list_info', {}).get('has_more'))


def fetch_danmaku(identity, vid: str, book_id: str, max_pages: int = 40,
                   limit: int = 3000):
    """拉全量弹幕（分页聚合）。失败时抛 RuntimeError。"""
    collected = []
    start = 0
    for _ in range(max_pages):
        url, body, headers = danmaku_request(identity, vid, book_id, start)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        items = parse_danmaku(data)
        collected.extend(items)
        if not has_more(data) or len(collected) >= limit:
            break
        start += EFFECTIVE_DURATION_MS
        time.sleep(0.15)  # 相邻分页间隔，别把上游打急
    return collected[:limit]
