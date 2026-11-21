# coding=utf-8
"""评论接口（双源，游客态可用）。

源 1 —— 官网 SSR 剧评（匿名可看，每集 15 条预览）：
    GET https://hongguoduanju.com/player/{series_id}/{video_id}
    页面内嵌 JSON 里的 episodeSocialInfo.reviews。

源 2 —— App 弹幕流（时轴弹幕，分页拉全量）：
    见 hongguo_apis.danmaku_api（X-Gorgon nonce 变体签名族）。

登录态写操作（发评论/点赞）需要 sessionid，见 utils/auth.py。
"""

import hashlib
import json
import re
import urllib.request

SITE = 'https://hongguoduanju.com'
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')


def episode_comments_request(series_id: str, video_id: str):
    """官网剧评页 (url, headers)。"""
    url = f'{SITE}/player/{series_id}/{video_id}'
    headers = {'User-Agent': _UA, 'Referer': f'{SITE}/'}
    return url, headers


def parse_episode_comments(html: str, series_id: str, video_id: str,
                           limit: int = 30) -> dict:
    """剧评页 -> {items: [{id, content, author, ...}], total, has_more}。

    官网匿名页只内嵌本集前 15 条预览，无公开翻页接口。
    """
    items = []
    total = None
    # 直接搜 reviews 数组（页面内嵌 JSON）
    for m in re.finditer(r'"reviews"\s*:\s*\[', html):
        start = m.end() - 1
        depth = 0
        for i in range(start, min(start + 100000, len(html))):
            if html[i] == '[':
                depth += 1
            elif html[i] == ']':
                depth -= 1
                if depth == 0:
                    try:
                        reviews = json.loads(html[start:i + 1])
                    except ValueError:
                        reviews = []
                    for rev in reviews[:limit]:
                        content = rev.get('content') or ''
                        if not content:
                            continue
                        author = rev.get('user_name') or rev.get('author') or ''
                        digest = hashlib.sha256(
                            json.dumps([series_id, video_id, author,
                                        rev.get('created_at'), content])
                            .encode()).hexdigest()
                        items.append({
                            'id': digest,
                            'content': content,
                            'author': author,
                            'created_at': rev.get('created_at'),
                            'likes': rev.get('like_count') or rev.get('digg_count'),
                        })
                    break
    tm = re.search(r'"total_count"\s*:\s*(\d+)', html)
    if tm:
        total = int(tm.group(1))
    return {'items': items, 'total': total, 'has_more': False,
            'source_limited': True}


def fetch_episode_comments(series_id: str, video_id: str, limit: int = 30) -> dict:
    """拉一集的官网剧评（网络 + 解析一步到位）。"""
    url, headers = episode_comments_request(series_id, video_id)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode('utf-8', errors='replace')
    return parse_episode_comments(html, series_id, video_id, limit)
