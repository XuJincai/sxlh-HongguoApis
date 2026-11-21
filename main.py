# coding=utf-8
"""HongguoApis 命令行入口。

用法：
    python main.py search 总裁
    python main.py detail <book_id>
    python main.py play <book_id>
    python main.py comments <book_id>              # 剧评（书级）
    python main.py comments <book_id> <video_id>   # 单集评论
    python main.py newrelease                       # 近 7 天上新（真人剧）
    python main.py newrelease ai                    # 近 7 天上新（AI 剧）
    python main.py danmaku <book_id> <video_id>
    python main.py demo <关键词>     # 搜索 -> 详情 -> 播放地址 -> 评论 -> 弹幕 全链路
    python main.py login              # 官网扫码登录 -> login_identity.json
    python main.py account            # 打印已登录账号资料 + App 观看历史
"""

import json
import sys
import time
import urllib.request

from utils.auth import GuestIdentity
from utils.device_profile import decode_response
from hongguo_apis import (search_request, parse_search_response,
                          video_detail_request, parse_video_detail,
                          player_model_request, parse_video_models,
                          comment_list_request, parse_comment_list,
                          landpage_request, parse_landpage,
                          fetch_danmaku)

LOGIN_IDENTITY_FILE = 'login_identity.json'

IDENTITY_FILE = 'guest_identity.json'


def get_guest():
    import os
    if os.path.exists(IDENTITY_FILE):
        try:
            guest = GuestIdentity.from_json_file(IDENTITY_FILE)
            print(f'[+] 复用游客身份 device_id={guest.device_id}')
            return guest
        except Exception:
            pass
    guest = GuestIdentity.from_register()
    guest.save(IDENTITY_FILE)
    print(f'[+] 新注册游客身份 device_id={guest.device_id} iid={guest.iid}')
    return guest


def http_post_json(url, body, headers, tries=4):
    """POST 并解析 JSON。服务器偶尔回空 body，带重试（每次重签由调用方保证）。"""
    last = b''
    for _ in range(tries):
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=20) as r:
            last = r.read()
        if last:
            enc = r.headers.get('content-encoding', '')
            last = decode_response(last, enc)
            return json.loads(last)
        time.sleep(0.4)
    raise RuntimeError(f'服务器连续返回空 body: {url[:80]}')


def signed_post(fn, *args, **kwargs):
    """调用 *_request(identity, ...) 生成签名请求并执行。失败重签重试。"""
    last_err = None
    for _ in range(8):
        url, body, headers = fn(*args, **kwargs)
        try:
            return http_post_json(url, body, headers, tries=1)
        except (RuntimeError, json.JSONDecodeError) as ex:
            last_err = ex
            time.sleep(3)
    raise RuntimeError(f'签名请求多次失败: {last_err}')


def cmd_search(guest, keyword):
    url, headers = search_request(guest, keyword)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(decode_response(r.read(), r.headers.get('content-encoding', '')))
    result = parse_search_response(data)
    print(f"[+] 搜索「{keyword}」: {len(result['books'])} 部")
    for b in result['books']:
        print(f"  {b['book_id']}  {b['title']}  [{b['category']}] score={b['score']}")
    return result


def cmd_detail(guest, book_id):
    d = signed_post(video_detail_request, guest, book_id)
    info = parse_video_detail(d)
    print(f"[+] {info['title']} ({info['book_id']})")
    print(f"    {info['episode_text']} | 播放 {info['play_count']} | {info['category']}")
    print(f"    简介: {(info['abstract'] or '')[:80]}")
    for ep in info['episode_list'][:10]:
        print(f"    ep{ep['index']}: {ep['video_id']}  {ep['title'][:30]}")
    return info


def cmd_play(guest, book_id, limit=3):
    d = signed_post(video_detail_request, guest, book_id)
    info = parse_video_detail(d)
    vids = [e['video_id'] for e in info['episode_list'][:limit]]
    m = signed_post(player_model_request, guest, vids)
    models = parse_video_models(m)
    for vid, mi in models.items():
        print(f"[+] {vid}: {mi['duration']}s, {len(mi['qualities'])} 档清晰度")
        print(f"    main_url: {mi['main_url']}")
    return models


def cmd_comments(guest, book_id, video_id=None, pages=1):
    """评论列表。无 video_id = 剧评（书级）；有 = 单集评论。"""
    total_shown = []
    cursor = ''
    for page in range(pages):
        if video_id:
            gid, gt, cs, sc, ct = video_id, 30, 4, 17, 4
        else:
            gid, gt, cs, sc, ct = book_id, 1, 1, 33, 2
        result = None
        for _ in range(4):
            d = signed_post(comment_list_request, guest, gid, gt, cs, sc, ct,
                            book_id=book_id, count=20, cursor=cursor)
            result = parse_comment_list(d)
            if result['comments'] or not result['has_more']:
                break
            # 偶发只回骨架（空 data_list + cursor），带 cursor 重试
            cursor = result['cursor'] or cursor
        if page == 0:
            label = '单集评论' if video_id else '剧评'
            print(f"[+] {label} total={result['total']}")
        for c in result['comments']:
            print(f"  [{c['user_name']}] (digg {c['digg_count']}) "
                  f"{(c['text'] or '')[:60]}")
        total_shown.extend(result['comments'])
        cursor = result['cursor'] or ''
        if not result['has_more']:
            break
        time.sleep(0.3)
    return total_shown


def cmd_newrelease(guest, ai=False, pages=2):
    """近 7 天上新列表（线上时间倒序）。ai=False 真人剧 / True AI 剧。"""
    genre = 'ai_series' if ai else 'short_play'
    scene = 'ai_series' if ai else 'default'
    offset, session_id, total = 0, '', []
    for page in range(pages):
        d = signed_post(landpage_request, guest, genre, scene, offset, session_id)
        result = parse_landpage(d)
        total.extend(result['series'])
        if not result['has_more']:
            break
        offset, session_id = result['next_offset'], result['session_id']
    print(f"[+] 近 7 天上新 {'AI 剧' if ai else '真人剧'}: {len(total)} 部")
    for s in total[:20]:
        mark = ' [今日上新]' if s['released_today'] else ''
        print(f"  {s['book_id']}  {s['title']}  ep{s['episode_count']}{mark}")
    return total


def cmd_danmaku(guest, book_id, video_id):
    items = fetch_danmaku(guest, video_id, book_id, max_pages=3)
    print(f'[+] 弹幕 {len(items)} 条')
    for it in items[:10]:
        print(f"  {it['time']:>8.2f}s  {it['text']}")
    return items


def cmd_demo(guest, keyword):
    print('=== 1. 搜索 ===')
    result = cmd_search(guest, keyword)
    if not result['books']:
        print('[-] 无结果')
        return
    book = result['books'][0]

    print('\n=== 2. 详情 ===')
    info = signed_post(video_detail_request, guest, book['book_id'])
    parsed = parse_video_detail(info)
    print(f"[+] {parsed['title']} | {parsed['episode_text']}")

    print('\n=== 3. 播放地址 ===')
    vids = [parsed['episode_list'][0]['video_id']]
    m = signed_post(player_model_request, guest, vids)
    models = parse_video_models(m)
    for vid, mi in models.items():
        print(f"[+] {vid}: {mi['duration']}s main_url:")
        print(f"    {mi['main_url']}")

    print('\n=== 4. 剧评 ===')
    cmd_comments(guest, book['book_id'], pages=1)

    print('\n=== 5. 弹幕 ===')
    cmd_danmaku(guest, book['book_id'], vids[0])


def cmd_login(guest):
    """官网扫码登录：展示二维码 -> 轮询 -> 存 login_identity.json。"""
    from hongguo_apis.login_api import (start_login, save_qr_image,
                                        poll_qr_status, finish_redirect,
                                        login_identity_from_cookies,
                                        has_session, QR_STATUS_EXPIRED)
    qr = start_login()
    save_qr_image(qr, 'login_qr.png')
    print(f"[+] 二维码已存 login_qr.png（{qr['expires_in']}s 内有效），请用红果 App 扫码")
    token, cookies = qr['token'], qr['cookies']
    deadline = time.time() + 300
    while time.time() < deadline:
        result = poll_qr_status(token, cookies)
        cookies = result['cookies']
        st = result['status']
        if st in QR_STATUS_EXPIRED:
            print('[-] 二维码已过期，请重新 login')
            return
        if st in ('2', 'scanned'):
            print('[+] 已扫码，等待 App 端确认…')
        if st in ('3', 'confirmed') and result['redirect_url']:
            cookies = finish_redirect(result['redirect_url'], cookies)
            jar = dict(p.partition('=')[::2] for p in cookies)
            if not has_session(jar):
                print('[-] 确认成功但未拿到 sessionid')
                return
            identity = login_identity_from_cookies(guest, cookies)
            identity.save(LOGIN_IDENTITY_FILE)
            print(f"[+] 登录成功 user_id={identity.user_id} "
                  f"name={identity.user_name} -> {LOGIN_IDENTITY_FILE}")
            return
        time.sleep(3)
    print('[-] 超时未扫码')


def cmd_account():
    """打印登录账号资料 + App 观看历史。"""
    from utils.auth import LoginIdentity
    from hongguo_apis.login_api import fetch_account_info
    from hongguo_apis.account_api import (user_info_request, fetch_history_list,
                                          parse_history_list)
    identity = LoginIdentity.from_json_file(LOGIN_IDENTITY_FILE)
    info = fetch_account_info(identity.sessionid)
    print(f"[+] 官网资料 user_id={info['user_id']} name={info['name']}")
    print(f"[+] avatar={info['avatar'][:80]}")

    url, headers = user_info_request(identity)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = decode_response(r.read(), r.headers.get('content-encoding', ''))
    app_user = json.loads(raw).get('data') or {}
    print(f"[+] App 档案 user_id={app_user.get('req_id') or app_user.get('user_id')} "
          f"name={app_user.get('user_name')}")

    history = parse_history_list(fetch_history_list(identity))
    print(f"[+] 观看历史 {len(history['items'])} 条")
    for row in history['items'][:10]:
        print(f"    {row['series_title']} 第{row['vid_index']}集 "
              f"{int(row['current_time'])}/{int(row['duration'])}s")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    guest = get_guest()
    if cmd == 'search' and len(sys.argv) >= 3:
        cmd_search(guest, sys.argv[2])
    elif cmd == 'detail' and len(sys.argv) >= 3:
        cmd_detail(guest, sys.argv[2])
    elif cmd == 'play' and len(sys.argv) >= 3:
        cmd_play(guest, sys.argv[2])
    elif cmd == 'comments' and len(sys.argv) >= 3:
        vid = sys.argv[3] if len(sys.argv) >= 4 else None
        cmd_comments(guest, sys.argv[2], vid)
    elif cmd == 'newrelease' and len(sys.argv) >= 2:
        cmd_newrelease(guest, ai=(len(sys.argv) >= 3 and sys.argv[2] == 'ai'))
    elif cmd == 'danmaku' and len(sys.argv) >= 4:
        cmd_danmaku(guest, sys.argv[2], sys.argv[3])
    elif cmd == 'demo' and len(sys.argv) >= 3:
        cmd_demo(guest, sys.argv[2])
    elif cmd == 'login' and len(sys.argv) >= 2:
        cmd_login(guest)
    elif cmd == 'account' and len(sys.argv) >= 2:
        cmd_account()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
