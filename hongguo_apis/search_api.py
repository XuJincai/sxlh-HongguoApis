# coding=utf-8
"""搜索接口（游客态可用）。

App 端点：GET https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/search/tab/v
签名：x-gorgon 8404 + hash F13 分支 0（搜索族只接受分支 0，需对 _rticket 做微调重试）。
"""

import json
import time

from utils.hongguo_sign import (python_url_encode, sign_headers, branch_of,
                                 x_ladon, x_argus, x_gorgon, x_helios, gzip_body)

SEARCH_API = 'https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/search/tab/v'

# 搜索走 7.2.2.32 版本指纹（与播放器签名族解耦）
_SEARCH_DEVICE = {
    'ac': 'wifi', 'channel': 'update_64', 'aid': '8662', 'app_name': 'novelread',
    'version_code': '72232', 'version_name': '7.2.2.32',
    'device_platform': 'android', 'os': 'android', 'ssmix': 'a',
    'device_type': '25053RT47C', 'device_brand': 'Redmi', 'language': 'zh',
    'os_api': '36', 'os_version': '16', 'manifest_version_code': '72232',
    'resolution': '1280*2772', 'dpi': '520', 'update_version_code': '72232',
    'host_abi': 'arm64-v8a', 'dragon_device_type': 'phone', 'pv_player': '72232',
    'compliance_status': '0', 'need_personal_recommend': '1', 'player_so_load': '1',
    'is_android_pad_screen': '0',
}
SEARCH_UA = ('com.phoenix.read/72232 (Linux; U; Android 16; zh_CN; 25053RT47C; '
             'Build/BP2A.250605.031.A3)')


def search_request(identity, keyword: str, page: int = 1, cursor: dict = None):
    """生成一次搜索的 (url, headers)。

    :param identity: GuestIdentity / LoginIdentity
    :param keyword: 搜索词（最长 80 字符）
    :param page: 页码 1-50
    :param cursor: 翻页游标 {'search_id', 'passback', 'next_offset'}，来自上一页响应
    """
    keyword = str(keyword)[:80]
    if not (1 <= page <= 50):
        raise ValueError('page 取值 1-50')
    device = dict(_SEARCH_DEVICE)
    device.update({'iid': identity.iid, 'device_id': identity.device_id,
                   'cdid': identity.cdid})
    khronos = int(time.time())
    ticket_base = int(time.time() * 1000)

    base = dict(device)
    base.update({'query': keyword, 'count': '20', 'tab_type': '11',
                 'bookshelf_search_plan': '4', 'use_correct': 'true',
                 'user_is_login': '0' if not getattr(identity, 'sessionid', None) else '1'})
    if cursor:
        if cursor.get('search_id'):
            base['search_id'] = cursor['search_id']
        if cursor.get('passback'):
            base['passback'] = cursor['passback']
    next_offset = int((cursor or {}).get('next_offset') or (page - 1) * 20)
    base['offset'] = str(next_offset)

    # 搜索签名族只认 hash F13 分支 0：通过微调 _rticket 试探
    for n in range(128):
        ticket = ticket_base + n
        query = python_url_encode({**base, 'ts': str(khronos), '_rticket': str(ticket)})
        if branch_of(query.encode(), None, khronos) == 0:
            break
    else:
        raise RuntimeError('无法生成分支 0 的搜索签名')

    import random
    from utils.medusa import build_medusa
    rnd = random.getrandbits(16)
    url = f'{SEARCH_API}?{query}'
    headers = {
        'User-Agent': SEARCH_UA,
        'Accept': 'application/json; charset=utf-8,application/x-protobuf',
        'x-ss-req-ticket': str(ticket), 'x-tt-request-tag': 't=0;n=0',
        'sdk-version': '2', 'passport-sdk-version': '50561', 'x-xs-from-web': '0',
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query.encode(), None, khronos, rnd),
        'x-helios': x_helios(khronos),
        'x-medusa': build_medusa(url, None, khronos,
                                 {'device_id': identity.device_id,
                                  'version_name': _SEARCH_DEVICE['version_name']}),
        'x-tt-dt': '',
    }
    if getattr(identity, 'sessionid', None):
        headers['Cookie'] = f'sessionid={identity.sessionid}'
    return url, headers


def parse_search_response(data: dict) -> dict:
    """搜索响应 -> {books: [...], cursor: {...}, has_more: bool}。

    响应结构：search_tabs[].data[]，每个 item 的 video_data[0] 是剧集/书本信息。
    翻页用 offset 递增（服务器无游标字段，靠 offset + query 保持一致）。
    """
    out_books = []
    for tab in data.get('search_tabs') or []:
        if int(tab.get('tab_type') or 0) != 11:  # 11 = 综合结果 tab
            continue
        for item in tab.get('data') or []:
            for book in item.get('video_data') or []:
                if not (book.get('vid') or book.get('series_id')):
                    continue
                cats = []
                try:
                    for c in json.loads(book.get('category_schema') or '[]'):
                        if isinstance(c, dict) and c.get('name'):
                            cats.append(c['name'])
                except (ValueError, TypeError):
                    cats = []
                out_books.append({
                    'book_id': str(book.get('series_id') or book.get('vid')),
                    'vid': str(book.get('vid') or ''),
                    'title': book.get('raw_book_name') or book.get('title'),
                    'abstract': book.get('sub_title') or '',
                    'category': '/'.join(cats),
                    'cover': book.get('cover') or book.get('horiz_cover'),
                    'score': book.get('score'),
                    'play_count': book.get('play_cnt'),
                    'series_play_count': (book.get('video_detail') or {}).get('series_play_cnt'),
                    'episode_count': book.get('episode_cnt'),
                    'copyright': book.get('copyright'),
                    'is_finish': '完结' in ((book.get('video_detail') or {}).get('episode_right_text') or ''),
                })
    # 翻页游标：tab 11 里带 search_id/passback/next_offset（空结果也带 passback）
    cursor = {'log_id': data.get('log_id')}
    has_more = False
    for tab in data.get('search_tabs') or []:
        if int(tab.get('tab_type') or 0) != 11:
            continue
        for key in ('search_id', 'passback', 'next_offset'):
            if tab.get(key):
                cursor[key] = tab[key]
        has_more = bool(tab.get('has_more'))
    return {'books': out_books, 'cursor': cursor, 'has_more': has_more}
