# coding=utf-8
"""官网扫码登录接口（纯 HTTP，无需 App 签名）。

官网端点（hongguoduanju.com，aid=513755）：
- GET /passport/web/get_qrcode/      取登录二维码（token + base64 图片）
- GET /passport/web/check_qrconnect/ 轮询扫码状态
- GET <redirect_url>                 扫码确认后拿 sessionid cookie
- GET /passport/account/info/v2/     用 sessionid 验证并取用户资料

流程：qr_login_request() 取码 -> poll_qr_status() 轮询 ->
finish_redirect() 跟跳转收 cookie -> LoginIdentity。

用法::

    from hongguo_apis.login_api import start_login, poll_login
    qr = start_login()                    # qr['image'] 是 data:image/png;base64,...
    result = poll_login(qr['token'], qr['cookies'])   # 循环调用直到 signed-in
    identity = result['identity']          # LoginIdentity（含 sessionid）
"""

import base64
import json
import time
import urllib.parse
import urllib.request

WEB_BASE = 'https://hongguoduanju.com'
WEB_QUERY = {
    'aid': '513755',
    'passport_jssdk_version': '3.4.10',
    'passport_jssdk_type': 'normal',
    'account_sdk_source': 'web',
    'is_from_ttaccountsdk': '1',
    'language': 'zh',
}
WEB_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36')

# 服务端状态有新旧两种表示，都接受
QR_STATUS_NEW = ('1', 'new')            # 待扫码
QR_STATUS_SCANNED = ('2', 'scanned')     # 已扫待确认
QR_STATUS_CONFIRMED = ('3', 'confirmed')  # 已确认（带 redirect_url）
QR_STATUS_EXPIRED = ('5', 'expired')     # 过期


def _web_headers(cookie: str = '') -> dict:
    """官网 passport 请求头（浏览器形态）。"""
    headers = {
        'User-Agent': WEB_UA,
        'Referer': f'{WEB_BASE}/',
        'Origin': WEB_BASE,
        'Accept': 'application/json, text/javascript',
    }
    if cookie:
        headers['Cookie'] = cookie
    return headers


def _web_get(pathname: str, params: dict, cookie: str = '', timeout: int = 15):
    """官网 GET：返回 (json, set_cookie_list)。"""
    query = urllib.parse.urlencode({**WEB_QUERY, **params})
    url = f'{WEB_BASE}{pathname}?{query}'
    req = urllib.request.Request(url, headers=_web_headers(cookie))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        set_cookies = r.headers.get_all('Set-Cookie') or []
    return json.loads(raw), set_cookies


def _absorb_cookies(jar: dict, set_cookies: list) -> str:
    """把 set-cookie 合进 jar，返回 cookie 头。"""
    for line in set_cookies:
        pair = line.split(';', 1)[0]
        name, _, value = pair.partition('=')
        jar[name.strip()] = value.strip()
    return _cookie_header(jar)


def _cookie_header(jar: dict) -> str:
    return '; '.join(f'{k}={v}' for k, v in jar.items() if k and v)


def has_session(jar: dict) -> bool:
    """是否已拿到登录凭证。"""
    return bool(jar.get('sessionid') or jar.get('sessionid_ss'))


def start_login() -> dict:
    """取登录二维码。

    返回 {token, image(data-uri), expires_in(秒), cookies(list[str])}。
    cookies 原样传给 poll_login 保持会话。
    """
    data, set_cookies = _web_get('/passport/web/get_qrcode/',
                                 {'next': f'{WEB_BASE}/'})
    if data.get('message') != 'success' or not (data.get('data') or {}).get('token'):
        raise RuntimeError(f'取二维码失败: {data.get("message")}')
    d = data['data']
    raw_expire = int(d.get('expire_time') or 0)
    expires_in = max(0, min(600, raw_expire - int(time.time()))) \
        if raw_expire > 1_000_000_000 else max(0, min(600, raw_expire or 180))
    source = str(d.get('qrcode') or '')
    image = source if source.startswith('data:image/') \
        else 'data:image/png;base64,' + source.split('base64,')[-1]
    return {
        'token': str(d.get('token')),
        'image': image,
        'expires_in': expires_in,
        'cookies': [c.split(';')[0] for c in set_cookies],
    }


def save_qr_image(login: dict, path: str = 'login_qr.png'):
    """把二维码图片写到磁盘（扫码用）。"""
    b64 = login['image'].split('base64,', 1)[-1]
    with open(path, 'wb') as f:
        f.write(base64.b64decode(b64))


def poll_qr_status(token: str, cookies: list) -> dict:
    """查一次扫码状态（不阻塞）。

    返回 {status(1/2/3/5), redirect_url, cookies}。
    status=3 时 redirect_url 用于 finish_redirect() 拿 sessionid。
    """
    jar = {}
    for pair in cookies:
        name, _, value = pair.partition('=')
        jar[name.strip()] = value.strip()
    data, set_cookies = _web_get('/passport/web/check_qrconnect/',
                                 {'next': f'{WEB_BASE}/', 'token': token},
                                 _cookie_header(jar))
    _absorb_cookies(jar, set_cookies)
    d = data.get('data') or {}
    return {
        'status': str(d.get('status') or ''),
        'redirect_url': d.get('redirect_url') or '',
        'cookies': [f'{k}={v}' for k, v in jar.items()],
    }


def finish_redirect(redirect_url: str, cookies: list,
                    max_hops: int = 5) -> list:
    """跟扫码确认跳转，收集登录 cookie。

    返回完整 cookie 对（含 sessionid）。非 hongguoduanju.com 域拒绝。
    """
    jar = {}
    for pair in cookies:
        name, _, value = pair.partition('=')
        jar[name.strip()] = value.strip()
    url = urllib.parse.urljoin(WEB_BASE, redirect_url)
    for _ in range(max_hops):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or not (
                parsed.hostname == 'hongguoduanju.com'
                or parsed.hostname.endswith('.hongguoduanju.com')):
            raise RuntimeError(f'登录跳转到不支持的站点: {parsed.hostname}')
        req = urllib.request.Request(url, headers=_web_headers(_cookie_header(jar)))
        opener = urllib.request.build_opener(NoRedirect())
        resp = opener.open(req, timeout=15)
        _absorb_cookies(jar, resp.headers.get_all('Set-Cookie') or [])
        if resp.status in (301, 302, 303, 307, 308) and resp.headers.get('Location'):
            url = urllib.parse.urljoin(url, resp.headers['Location'])
            resp.close()
            continue
        resp.close()
        if resp.status != 200:
            raise RuntimeError(f'登录确认失败: HTTP {resp.status}')
        break
    return [f'{k}={v}' for k, v in jar.items()]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟 3xx 的 opener（要手动收 set-cookie）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_account_info(sessionid: str, cookie_pairs: list = None,
                       timeout: int = 15) -> dict:
    """用 sessionid 调 /passport/account/info/v2/ 取用户资料。

    返回 {user_id, name, avatar, raw}。失败抛异常（会话无效等）。
    """
    jar = {'sessionid': sessionid}
    for pair in cookie_pairs or []:
        name, _, value = pair.partition('=')
        if name.strip() != 'sessionid':
            jar[name.strip()] = value.strip()
    data, _ = _web_get('/passport/account/info/v2/', {},
                       _cookie_header(jar), timeout)
    if str(data.get('code') or 0) != '0' or not (data.get('data') or {}):
        raise RuntimeError(f'账号资料验证失败: {data.get("message")}')
    d = data['data']
    return {
        'user_id': str(d.get('user_id_str') or d.get('user_id') or ''),
        'name': d.get('name') or d.get('screen_name') or d.get('username') or '',
        'avatar': d.get('avatar_url') or '',
        'raw': d,
    }


def login_identity_from_cookies(guest, cookies: list):
    """cookies（含 sessionid）+ 游客身份 -> LoginIdentity。"""
    from utils.auth import LoginIdentity
    jar = {}
    for pair in cookies:
        name, _, value = pair.partition('=')
        jar[name.strip()] = value.strip()
    sessionid = jar.get('sessionid') or jar.get('sessionid_ss') or ''
    if not sessionid:
        raise RuntimeError('cookie 里没有 sessionid，扫码未完成')
    profile = fetch_account_info(sessionid, [f'{k}={v}' for k, v in jar.items()
                                             if k != 'sessionid_ss'])
    identity = LoginIdentity.from_guest(guest, sessionid,
                                         profile['user_id'], profile['name'])
    identity.sessionid_ss = jar.get('sessionid_ss', '')
    return identity


def poll_login(token: str, cookies: list):
    """查一次扫码状态；确认则完成跳转与账号验证。

    返回 {signed_in(bool), status, cookies}；
    signed_in=True 时附 identity(LoginIdentity)。
    """
    result = poll_qr_status(token, cookies)
    if result['status'] in QR_STATUS_CONFIRMED and result['redirect_url']:
        cookies = finish_redirect(result['redirect_url'], result['cookies'])
        result['cookies'] = cookies
        result['signed_in'] = has_session(
            dict(p.partition('=')[::2] for p in cookies))
    else:
        result['signed_in'] = False
    if result['status'] in QR_STATUS_EXPIRED:
        result['signed_in'] = False
    return result


def wait_login(guest, token: str, cookies: list, interval: int = 3,
               timeout: int = 300):
    """阻塞轮询直到登录成功/过期。

    返回 {signed_in, status, cookies, identity?}。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = poll_login(token, cookies)
        if result['signed_in']:
            result['identity'] = login_identity_from_cookies(
                guest, result['cookies'])
            return result
        if result['status'] in QR_STATUS_EXPIRED:
            return result
        cookies = result['cookies']
        time.sleep(interval)
    return {'signed_in': False, 'status': 'timeout', 'cookies': cookies}
