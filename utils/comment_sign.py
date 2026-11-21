# coding=utf-8
"""弹幕/评论接口专用签名（X-Gorgon nonce 变体 / X-Ladon / X-Argus）。

这一族与搜索/播放接口的签名不同：X-Gorgon 头部带 nonce 派生的两个字节，
X-Ladon 是 34 轮 uint64 密钥扩展 + TEA 风格变换，X-Argus 是 protobuf 组包
+ SM3 派生 72 轮变换 + AES-128-CBC。全部本地可算。

主要入口：
- `build_query(device_id, iid, stamp_ms)` —— 评论接口的排序 query 串。
- `sign_comment_headers(raw_query, stamp, nonce)` —— 生成 X-Gorgon/X-Ladon/X-Argus。
"""

import base64
import hashlib
import os
import struct
import time
import urllib.parse

_U64 = (1 << 64) - 1

from utils.hongguo_sign import sm3


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def _rotl64(x: int, n: int) -> int:
    x &= _U64
    n = ((n % 64) + 64) % 64
    return ((x << n) | (x >> ((64 - n) % 64))) & _U64


def _rotr64(x: int, n: int) -> int:
    return _rotl64(x, -n)


def _rotl8(x: int, n: int) -> int:
    x &= 0xFF
    n &= 7
    return ((x << n) | (x >> ((8 - n) & 7))) & 0xFF


def _reverse8(x: int) -> int:
    v = x & 0xFF
    v = ((v & 0xF0) >> 4) | ((v & 0x0F) << 4)
    v = ((v & 0xCC) >> 2) | ((v & 0x33) << 2)
    v = ((v & 0xAA) >> 1) | ((v & 0x55) << 1)
    return v & 0xFF


def _pad(data: bytes) -> bytes:
    padding = 16 - (len(data) % 16)
    return bytes(data) + bytes([padding] * padding)


def _uvarint(value: int) -> bytes:
    value &= _U64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def new_device_id() -> str:
    """1e18 + 随机数，19 位数字串（与官方客户端格式一致）。"""
    return str(10 ** 18 + int.from_bytes(os.urandom(8), 'big') % 8 * 10 ** 18)


_BASE_PARAMS = {
    'aid': '8662', 'app_name': 'novelread', 'version_code': '73532',
    'version_name': '7.3.5.32', 'manifest_version_code': '73532',
    'update_version_code': '73532', 'channel': 'update_64',
    'device_platform': 'android', 'os': 'android', 'ssmix': 'a',
    'device_type': '25053RT47C', 'device_brand': 'Redmi', 'language': 'zh',
    'os_api': '36', 'os_version': '16', 'resolution': '1280*2772', 'dpi': '520',
    'ac': 'wifi',
}


def _quote_plus(value: str) -> str:
    # quote_plus 会把空格转 '+'、'*' 转成 %2A —— 签名对 query 字节敏感
    return urllib.parse.quote_plus(str(value), safe='')


def build_query(device_id: str, iid: str, stamp_ms: int) -> str:
    """评论族 query：固定参数 + _rticket，键按字典序排序。"""
    params = dict(_BASE_PARAMS)
    params['device_id'] = str(device_id)
    params['iid'] = str(iid)
    params['_rticket'] = str(stamp_ms)
    return '&'.join(f"{_quote_plus(k)}={_quote_plus(v)}"
                    for k, v in sorted(params.items()))


def comment_x_gorgon(raw_query: str, stamp: int, nonce: bytes) -> str:
    head2 = ((nonce[0] % 7) + 1) << 5
    head3 = 0xE0 | (nonce[1] & 0x0F)

    seed = bytearray(20)
    digest = _md5(raw_query.encode())
    seed[0:4] = digest[0:4]
    seed[12:16] = bytes([0, 1, 7, 4])
    seed[16:20] = struct.pack('>I', stamp & 0xFFFFFFFF)

    key = bytes([0x4A, 0x00, 0x16, head3 & 0xFF, 0x47, 0x6C, 0x00, head2 & 0xFF])

    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i & 7]) & 0xFF
        box[i] = box[j]  # 算法定义为单向赋值，不是交换

    j = 0
    for offset in range(20):
        i = (offset + 1) & 0xFF
        j = (j + box[i]) & 0xFF
        box[i] = box[j]
        seed[offset] ^= box[(box[i] + box[j]) & 0xFF]

    for i in range(20):
        seed[i] = (_reverse8(_rotl8(seed[i], 4) ^ seed[(i + 1) % 20]) ^ 0xEB) & 0xFF

    head = bytes([0x84, 0x04, head2 & 0xFF, head3 & 0xFF, 0, 0])
    return (head + bytes(seed)).hex()


def comment_x_ladon(aid: str, timestamp: int, prefix: bytes) -> str:
    digest = _md5(prefix + str(aid).encode()).hex().encode()  # 小写 hex 参与
    left = int.from_bytes(digest[0:8], 'little')
    right = int.from_bytes(digest[8:16], 'little')
    queue = [int.from_bytes(digest[16:24], 'little'),
             int.from_bytes(digest[24:32], 'little')]

    keys = []
    for i in range(34):
        keys.append(left)
        mixed = (_rotr64(right, 8) + left) & _U64 ^ i
        mixed &= _U64
        queue.append(mixed)
        left = (mixed ^ _rotl64(left, 3)) & _U64
        right = queue.pop(0)

    text = f'{int(timestamp)}-1611921764-3019'.encode()
    data = bytearray(_pad(text))
    for offset in range(0, len(data), 16):
        bl = int.from_bytes(data[offset:offset + 8], 'little')
        br = int.from_bytes(data[offset + 8:offset + 16], 'little')
        for k in keys:
            br = (k ^ ((bl + _rotr64(br, 8)) & _U64)) & _U64
            bl = (br ^ _rotl64(bl, 3)) & _U64
        data[offset:offset + 8] = bl.to_bytes(8, 'little')
        data[offset + 8:offset + 16] = br.to_bytes(8, 'little')

    return base64.b64encode(bytes(prefix) + bytes(data)).decode()


_ARGUS_KEY = bytes.fromhex(
    'ac1adaae95a7af94a5114ab3b3a97dd80050aa0a39314c40528caec95256c28c')


def _bytes_field(parts: list, field: int, value: bytes):
    parts.append(_uvarint(field * 8 + 2))
    parts.append(_uvarint(len(value)))
    parts.append(bytes(value))


def _varint_field(parts: list, field: int, value: int):
    parts.append(_uvarint(field * 8))
    parts.append(_uvarint(value))


def comment_x_argus(raw_query: str, timestamp: int, nonce: bytes) -> str:
    key = _ARGUS_KEY
    parts = []
    _varint_field(parts, 1, 0x20200929 * 2)
    _varint_field(parts, 2, 2)
    _varint_field(parts, 3, struct.unpack('<I', nonce[6:10])[0])
    _bytes_field(parts, 4, b'3019')
    _bytes_field(parts, 6, b'1611921764')
    _bytes_field(parts, 7, b'6.8.1.32')
    _bytes_field(parts, 8, b'v04.07.01-ml-android')
    _varint_field(parts, 9, 135135744)
    _bytes_field(parts, 10, bytes(8))
    _varint_field(parts, 12, (int(timestamp) * 2) & _U64)

    body_hash = sm3(bytes(16))
    query_hash = sm3(raw_query.encode())
    _bytes_field(parts, 13, body_hash[:6])
    _bytes_field(parts, 14, query_hash[:6])

    nested = [0x08, (2 + (nonce[10] % 49) * 2) & 0xFF]
    for field in (2, 3, 4):
        nested += list(_uvarint(field * 8))
        nested += list(_uvarint(1388734))
    _bytes_field(parts, 15, bytes(nested))
    _bytes_field(parts, 20, b'none')
    _varint_field(parts, 21, 738)

    data = bytearray(_pad(b''.join(bytes(p) for p in parts)))

    derived = sm3(key + bytes([0x3C, 0xCC, 0x56, 0x7B]) + key)

    rounds = [0] * 72
    for i in range(4):
        rounds[i] = int.from_bytes(derived[i * 8:i * 8 + 8], 'little')
    for i in range(4, 72):
        mixed = (_rotr64(rounds[i - 1], 3) ^ rounds[i - 3]) & _U64
        mixed = (mixed ^ _rotr64(mixed, 1)) & _U64
        rounds[i] = ((~rounds[i - 4]) & _U64) ^ mixed \
            ^ (((0x3DC94C3A046D678B >> ((i - 4) % 62)) & 1)) ^ 3
        rounds[i] &= _U64

    for offset in range(0, len(data), 16):
        left = int.from_bytes(data[offset:offset + 8], 'little')
        right = int.from_bytes(data[offset + 8:offset + 16], 'little')
        for r in rounds:
            nxt = (left ^ _rotl64(right, 1) & _rotl64(right, 8)
                   ^ _rotl64(right, 2) ^ r) & _U64
            left = right
            right = nxt
        data[offset:offset + 8] = left.to_bytes(8, 'little')
        data[offset + 8:offset + 16] = right.to_bytes(8, 'little')

    xor = bytes([0xD0, 0x4F, 0xFD, 0xFF, 0xD0, 0x4F, 0xFD, 0xFF])
    for i in range(len(data)):
        data[i] ^= xor[i % 8]
    reversed_buf = (xor + bytes(data))[::-1]

    container = _pad(bytes([0xA6, 0xE7, 0x83, 0xEE, 0x70, 0x01, 0x10, 0x09, 0x18])
                     + reversed_buf + bytes([0x56, 0x7B]))

    iv = _md5(key[16:])
    cipher_key = _md5(key[:16])
    from Crypto.Cipher import AES  # noqa: pycryptodome
    aes = AES.new(cipher_key, AES.MODE_CBC, iv)
    encrypted = aes.encrypt(container)

    return base64.b64encode(bytes([0x3C, 0xCC]) + encrypted).decode()


NONCE_BYTES = 11


def sign_comment_headers(raw_query: str, stamp: int, nonce: bytes,
                         aid: str = '8662') -> dict:
    """评论族签名头。nonce 必须 11 字节。"""
    return {
        'X-Gorgon': comment_x_gorgon(raw_query, stamp, nonce),
        'X-Khronos': str(int(stamp)),
        'X-SS-Req-Ticket': str(int(stamp) * 1000),
        'X-SS-STUB': '',
        'X-Argus': comment_x_argus(raw_query, stamp, nonce),
        'X-Ladon': comment_x_ladon(aid, stamp, nonce[2:6]),
    }


def new_nonce() -> bytes:
    return os.urandom(NONCE_BYTES)
