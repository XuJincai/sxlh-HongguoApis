# coding=utf-8
"""设备注册（device_register）—— 纯 HTTP 拿 device_id / iid。

红果的游客身份来自 `log5-applog-lf.fqnovel.com/service/2/device_register/`：
请求体是 gzip(JSON) 前面拼一个 SHA-512 校验，再用 AES-128-CBC（密钥由
随机 32 字节经 KDF 派生）加密。响应里 `device_id` / `install_id` 即游客身份。

参数含义见 `register()` docstring；`device_id`/`iid` 拿到后即可调用
所有游客态接口（搜索、详情、播放、评论）。
"""

import base64
import hashlib
import json
import random
import time
import uuid
import zlib

KDF_SALT = bytes.fromhex(
    '4dd4c2e6b83162090e52b3c7a6733ba41cb2462b829ab58a196b39db57177524'
    'f49baf7f08e8d68d26a72e37c1a95a2f1f05a51892aef2949732b62a38aadd58'
)
REGISTER_URL = ('https://log5-applog-lf.fqnovel.com/service/2/device_register/'
                '?tt_data=a&cronet_version=8d40f833_2026-03-03'
                '&ttnet_version=4.2.243.31-douyin&use_store_region_cookie=1')

_APP_VERSION = '7.3.9.32'
_VERSION_CODE = 73932


def _gzip(data: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
    return co.compress(data) + co.flush()


def build_register_body(device_model='25053RT47C', device_brand='Redmi'):
    """构造注册请求的加密体。返回 (encrypted_bytes, cdid)。"""
    now = int(time.time() * 1000)
    cdid = str(uuid.uuid4())
    header = {
        'display_name': '红果免费短剧', 'update_version_code': _VERSION_CODE,
        'manifest_version_code': _VERSION_CODE, 'app_version_minor': _APP_VERSION,
        'aid': 8662, 'channel': 'update_64', 'package': 'com.phoenix.read',
        'app_version': _APP_VERSION, 'version_code': _VERSION_CODE,
        'sdk_version': '3.7.0-rc.34-fanqie-xiaoshuo', 'sdk_target_version': 29,
        'git_hash': '3a88f4e', 'os': 'Android', 'os_version': '16', 'os_api': 36,
        'device_model': device_model, 'device_brand': device_brand,
        'device_manufacturer': device_brand, 'cpu_abi': 'arm64-v8a',
        'release_build': 'b5e187f', 'density_dpi': 520, 'display_density': 'mdpi',
        'resolution': '1280x2772', 'language': 'zh', 'timezone': 8,
        'access': 'wifi', 'not_request_sender': 0, 'carrier': 'CHINA MOBILE',
        'mcc_mnc': '46000', 'rom': 'eng.root.20231116.160340',
        'rom_version': 'W528JS release-keys', 'cdid': cdid,
        'sig_hash': '56a962410c494bbaf0b58dba20cae56f',
        'openudid': random.randbytes(8).hex(),
        'clientudid': str(uuid.uuid4()), 'ipv6_list': [], 'region': 'CN',
        'tz_name': 'Asia/Shanghai', 'tz_offset': 28800, 'sim_region': 'cn',
        'sim_serial_number': [], 'oaid_may_support': False,
        'req_id': str(uuid.uuid4()), 'device_platform': 'android',
        'custom': {'account_region_src': 'fallback', 'account_region': 'cn',
                   'host_bit': 64, 'dragon_device_type': 'phone'},
        'pre_installed_channel': '', 'apk_first_install_time': now,
        'is_system_app': 0, 'sdk_flavor': 'china', 'guest_mode': 0,
    }
    compressed = _gzip(json.dumps(
        {'magic_tag': 'ss_app_log', 'header': header, '_gen_time': now},
        separators=(',', ':')).encode())
    rnd = random.randbytes(32)
    derived = hashlib.sha512(
        hashlib.sha512(rnd).digest() + KDF_SALT).digest()
    # AES-128-CBC，PKCS7 padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    cipher = Cipher(algorithms.AES(derived[:16]), modes.CBC(derived[16:32]))
    padder = PKCS7(128).padder()
    plaintext = (hashlib.sha512(compressed).digest() + compressed)
    padded = padder.update(plaintext) + padder.finalize()
    enc = cipher.encryptor()
    encrypted = enc.update(padded) + enc.finalize()
    return rnd, encrypted, cdid


def parse_register_response(raw: bytes) -> dict:
    """解注册响应：先解 AES（密钥在响应里带回），再 gunzip。"""
    return json.loads(raw)


def register(session=None, device_model='25053RT47C', device_brand='Redmi'):
    """执行一次设备注册，返回 dict(device_id, iid, cdid, ...)。

    :param session: 可选 requests.Session（用于代理/重试控制）
    """
    import hashlib as _hashlib
    import requests
    rnd, encrypted, cdid = build_register_body(device_model, device_brand)
    now = int(time.time() * 1000)
    body = bytes.fromhex('746305100000') + rnd + encrypted
    resp = (session or requests).post(
        REGISTER_URL,
        data=body,
        headers={
            'Content-Type': 'application/octet-stream;tt-data=a',
            'User-Agent': f'com.phoenix.read/72232 (Linux; U; Android 16; zh_CN; '
                          f'{device_model}; Build/BP2A.250605.031.A3)',
            'Accept': 'application/json',
            'log-encode-type': 'gzip', 'x-ss-dp': '8662',
            'x-ss-req-ticket': str(now),
            'x-vc-bdturing-sdk-version': '4.0.3.cn', 'lc': '101',
            'sdk-version': '2', 'passport-sdk-version': '5051452',
            'x-neptune': '-8|50:51:59:30:40:47:49:39',
            'x-ss-stub': _hashlib.md5(body).hexdigest().upper(),
        },
        timeout=15)
    resp.raise_for_status()
    data = resp.json()

    def _id(name):
        v = data.get(f'{name}_str') or data.get(name) or ''
        if isinstance(v, int):
            return str(v) if v > 0 else ''
        return v if (isinstance(v, str) and v.isdigit() and any(c in v for c in '123456789')) else ''

    return {
        'device_id': _id('device_id'),
        'iid': _id('install_id'),
        'cdid': cdid,
        'klink_egdi': data.get('klink_egdi') or '',
        'device_token': data.get('device_token') or '',
        'raw': data,
    }


def local_identity() -> dict:
    """进程内随机身份（不注册，用于对身份不敏感的接口）。"""
    return {
        'device_id': str(1000000000000000 + random.getrandbits(48)),
        'iid': str(1000000000000000 + random.getrandbits(48)),
        'cdid': str(uuid.uuid4()),
    }
