# coding=utf-8
"""红果短剧签名算法纯 Python 实现。

移植自开源社区对红果 App 7.x x-Gorgon / x-Ladon / x-Argus / x-Helios / x-Medusa
签名族的还原工作（见仓库 README 致谢）。所有算法可本地复现，不依赖浏览器或真机。

主要入口：
- `sign_request(query, body, ts)` —— 生成一套完整签名头（x-gorgon/x-ladon/x-argus/x-khronos）。
- `x_gorgon(query, body, ts)` —— 单独的 x-Gorgon 签名。
- `build_medusa(url, body, khronos, device)` —— x-Medusa（TLV protobuf + AES 变体）。
"""

import base64
import hashlib
import os
import random
import struct
import time
import zlib

_U32 = 0xFFFFFFFF

PROCESS_NONCE = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip('=')

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def md5_hex(value: bytes) -> str:
    return hashlib.md5(value).hexdigest().upper()


def md5_raw(value: bytes) -> bytes:
    return hashlib.md5(value).digest()


_URI_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")


def _encode_uri_component(value) -> str:
    """encodeURIComponent 字节级一致（App 签名按这个字符集算）。"""
    out = []
    for ch in str(value):
        if ch in _URI_SAFE:
            out.append(ch)
        else:
            for byte in ch.encode('utf-8'):
                out.append('%%%02X' % byte)
    return ''.join(out)


def python_url_encode(values: dict) -> str:
    """签名的 query 串编码：键值均按 encodeURIComponent 规则（* 不转义等）。"""
    return '&'.join(f"{_encode_uri_component(k)}={_encode_uri_component(v)}"
                    for k, v in values.items())


def _rol32(v, n):
    n &= 31
    v &= _U32
    return ((v << n) | (v >> (32 - n))) & _U32


def _ror32(v, n):
    n &= 31
    v &= _U32
    return ((v >> n) | (v << (32 - n))) & _U32


def _le32(v):
    return struct.pack('<I', v & _U32)


def _be32(v):
    return struct.pack('>I', v & _U32)


def _u32(v):
    return v & _U32


def _le32_read(buf, off):
    return struct.unpack_from('<I', buf, off)[0]


# ---------------------------------------------------------------------------
# SM3（国密摘要，x-gorgon 查询串输入用）
# ---------------------------------------------------------------------------

_SM3_IV = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
           0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]


def _sm3_ff(j, x, y, z):
    if 0 <= j <= 15:
        return x ^ y ^ z
    return (x & y) | (~x & z)


def _sm3_gg(j, x, y, z):
    if 0 <= j <= 15:
        return x ^ y ^ z
    return (x & y) | (~y & z)


def _sm3_p0(x):
    return x ^ _rol32(x, 9) ^ _rol32(x, 17)


def _sm3_p1(x):
    return x ^ _rol32(x, 15) ^ _rol32(x, 23)


def sm3(data: bytes) -> bytes:
    """SM3 摘要（红果变体：消息扩展带 W[i-13]/W[i-6] 项）。256-bit 输出。"""
    def rol(x, n):
        return ((x << (n & 31)) | (x >> ((32 - n) & 31))) & _U32
    iv = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
          0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]
    padded = bytearray(((len(data) + 9 + 63) // 64) * 64)
    padded[:len(data)] = data
    padded[len(data)] = 0x80
    padded[-8:] = (len(data) * 8).to_bytes(8, 'big')
    state = iv[:]
    words = [0] * 68
    for off in range(0, len(padded), 64):
        for i in range(16):
            words[i] = int.from_bytes(padded[off + i * 4:off + i * 4 + 4], 'big')
        for i in range(16, 68):
            x = words[i - 16] ^ words[i - 9] ^ rol(words[i - 3], 15)
            words[i] = x ^ rol(x, 15) ^ rol(x, 23) ^ rol(words[i - 13], 7) ^ words[i - 6]
        a, b, c, d, e, f, g, h = state
        for i in range(64):
            a12 = rol(a, 12)
            t_j = 0x79CC4519 if i < 16 else 0x7A879D8A
            s1 = rol((a12 + e + rol(t_j, i)) & _U32, 7)
            s2 = s1 ^ a12
            ff = (a ^ b ^ c) if i < 16 else ((a & b) | (a & c) | (b & c))
            gg = (e ^ f ^ g) if i < 16 else ((e & f) | (~e & g))
            t1 = (ff + d + s2 + (words[i] ^ words[i + 4])) & _U32
            t2 = (gg + h + s1 + words[i]) & _U32
            d = c
            c = rol(b, 9)
            b = a
            a = t1
            h = g
            g = rol(f, 19)
            f = e
            e = t2 ^ rol(t2, 9) ^ rol(t2, 17)
            e &= _U32
        state = [(s ^ n) & _U32 for s, n in zip(state, [a, b, c, d, e, f, g, h])]
    return b''.join(v.to_bytes(4, 'big') for v in state)


# ---------------------------------------------------------------------------
# x-Gorgon 8404
# ---------------------------------------------------------------------------

def _reverse_bits(value):
    result = 0
    for _ in range(8):
        result = ((result << 1) | (value & 1)) & 0xFF
        value >>= 1
    return result


def _rc4_gorgon(data: bytes, key: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i] = s[j]  # 原实现只单向赋值，不交换
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i += 1
        x = s[i]
        j += x          # 不截断：j 是累积器，取值时才 &255
        y = s[j & 0xFF]
        s[i] = y
        out[k] = data[k] ^ s[(y + y) & 0xFF]
    return bytes(out)


def x_gorgon(query: bytes, body: bytes, timestamp: int, rnd: int) -> str:
    sdk = struct.pack('<I', 67503104)
    body_digest = md5_raw(body)[:4] if body else b'\x00' * 4
    raw_input = (md5_raw(query)[:4] + body_digest + b'\x00' * 4
                 + sdk + _be32(timestamp))
    key = bytes([0x4A, 0x40, 0x16, (rnd >> 8) & 0xFF, 0x47, 0x6C, 0x01, rnd & 0xFF])
    out = bytearray(_rc4_gorgon(raw_input, key))
    for i in range(len(out)):
        value = out[i]
        value = ((value >> 4) | (value << 4)) & 0xFF
        nxt = out[i + 1] if i + 1 < len(out) else out[0]
        out[i] = (~(_reverse_bits((nxt ^ value) & 0xFF) ^ 20)) & 0xFF
    head = bytes([0x84, 0x04, rnd & 0xFF, (rnd >> 8) & 0xFF, 0x40, 0x01])
    return (head + bytes(out)).hex()


# ---------------------------------------------------------------------------
# x-Ladon / x-Argus / x-Helios（khronos 派生的轻量头）
# ---------------------------------------------------------------------------

def x_ladon(khronos: int) -> str:
    return base64.b64encode(_be32(khronos)).decode()


def x_argus(khronos: int) -> str:
    return base64.b64encode(_le32(khronos)).decode()


def x_helios(khronos: int) -> str:
    rnd = random.getrandbits(32)
    data = _le32(rnd) + b'8662'
    digest = hashlib.md5(data).hexdigest().encode()  # 小写 hex，参与后续整数运算
    words = []
    for i in range(4):
        words.append(int.from_bytes(digest[i * 8:(i + 1) * 8], 'little'))
    table = [words[0]]
    b0 = words[0]
    b8 = words[1]
    rest = words[2:]
    for i in range(34):
        x8 = ((b8 >> 8) | (b8 << 56)) & 0xFFFFFFFFFFFFFFFF
        x8 = (x8 + b0) & 0xFFFFFFFFFFFFFFFF
        x8 ^= i
        rest.append(x8)
        x8 ^= ((b0 >> 61) | (b0 << 3)) & 0xFFFFFFFFFFFFFFFF
        table.append(x8)
        b0 = x8
        b8 = rest.pop(0)
    text = f'{khronos}-1588093228-8662'.encode()
    # PKCS7：整个 pad 缓冲先按块长补齐值填满，再拷入明文
    pad_len = ((len(text) + 1 + 15) // 16) * 16
    pad = bytearray([16 - (len(text) % 16)] * pad_len)
    pad[:len(text)] = text
    output = []
    for at in range(0, len(pad), 16):
        a = int.from_bytes(pad[at:at + 8], 'little')
        b = int.from_bytes(pad[at + 8:at + 16], 'little')
        for i in range(34):
            rb = ((b >> 8) | (b << 56)) & 0xFFFFFFFFFFFFFFFF
            b = (table[i] ^ (a + rb)) & 0xFFFFFFFFFFFFFFFF
            ra = ((a >> 61) | (a << 3)) & 0xFFFFFFFFFFFFFFFF
            a = (b ^ ra) & 0xFFFFFFFFFFFFFFFF
        output.append(a.to_bytes(8, 'little') + b.to_bytes(8, 'little'))
    return base64.b64encode(_le32(rnd) + b''.join(output)).decode()


# ---------------------------------------------------------------------------
# hash F13（x-medusa 内层 query/body/ts 摘要，分支 0 路径）
# ---------------------------------------------------------------------------

_BRANCH2_SV = [
    0xa7aefe20, 0x7149f1d6, 0x47e4ca07, 0xe9b58f67, 0x93b924de, 0xc614d0f5,
    0x38afe0ef, 0xb2bbad73, 0xe24444c3, 0x9d3aec9b, 0xdf7b37e4, 0xd8b16d40,
    0xf8ac31b8, 0x76b9a90b, 0x31d833ee, 0x953fce64, 0x353595a4, 0x4609c13b,
    0x36925008, 0x8c6d0925, 0x5df5c177, 0x1cfbf52b, 0x8a4fa7f0, 0x114ca35e,
    0x8193f984, 0x7a7a8733, 0x316ab4d5, 0x3c20cfc9, 0xa6d84453, 0x3a18500c,
    0x798ec47a, 0x97a76b28, 0x66c4ff96, 0x51716443, 0x0dd2fc3b, 0xb5696da7,
    0xbbeb3ac5, 0x5c53d204, 0xd32608ce, 0x7279b9ec, 0xf4188ecf, 0xf7d793db,
    0x332cc491, 0xab76ae15, 0x9bebe727, 0x18a01384, 0x5be9f8a7, 0x5f90a754,
    0x39b663c0, 0x36673c83, 0x7c92f514, 0x9d7d94d7, 0xe2e8d9aa, 0x5f7e9ea9,
    0x7abd4551, 0x569e05da, 0x40a25632, 0x3df5a9a5, 0xbab37d80, 0x454286dc,
    0x3f5d4e78, 0x03d7b75d, 0xb1fe4af7, 0xa5ab26a3,
]
_BRANCH2_ORDERS = bytes.fromhex(
    '0f0704000908030a060b050d0e010c020f05080c0009020103070e060b0a0d04060500070c'
    '000a04080f010b0d09020e060b02050403080101070a000d0c090e0d070e0f0b0208030c'
    '0509010004060a0d0902060f0b0a040807000c0503010e0c090f07060f030e020d0405010b'
    '0a000c050a090e0802040407030f01060b000b0f0408020a0700090d06010e03050c0b060a'
    '0508020c03070f0e090d0001040906080f050800040a0b030d01020c0e090d0c0604070a03'
    '030f00080105020e01000d0f090a0b0e0402080703060c0501080a0c0f0905060b00030402'
    '0e070d04080f000c0f0e0d0a01060207090503040205080d0b0a0606000e0f070c09030a08'
    '040f000b01060d0c0709030e05020a070b050f00020e0108030d0c0609040d070f08050f06'
    '040b0a0e0c090002030d0c020704010b0e0e08060f09050003'
)


def _get_iv(iv, data: bytes) -> int:
    value = _u32(iv)
    for i, byte in enumerate(data):
        if (i & 1) == 0:
            value = _u32((value >> 4) ^ value ^ (value << 6) ^ byte)
        else:
            value = _u32(~((value >> 7) ^ value ^ (byte | (value << 12))))
    return value


def _sum_md5(data: bytes) -> int:
    check = 0x20220420
    for i in range(12):
        byte = data[i] if i < len(data) else 0  # JS 短输入按 0 处理
        temp = (check >> 3) ^ check if (i & 1) == 0 else (check >> 5) ^ check
        if (i & 1) == 0:
            check = _u32(byte ^ (check << 7))
        else:
            check = _u32(byte | (check << 11))
            check = _u32(~check)
        check = _u32(check ^ temp)
    return _u32((check | 4) ^ 0x1000000)


def _md5_v3_step(kind, a, b, c, d, m, shift, constant):
    if kind == 0:
        f = (b & c) | ((~b) & d)
    elif kind == 1:
        f = (b & d) | (c & (~d))
    elif kind == 2:
        f = b ^ c ^ d
    else:
        f = c ^ (b | (~d))
    return _u32(b + _rol32(_u32(a + (f & _U32) + m + constant), shift))


def _md5_sum_v3(message: bytes, count_v2: int, orders: bytes, count_v1: int) -> bytes:
    sv = [_ror32(v, count_v1) for v in _BRANCH2_SV]
    start = [_ror32(0x79e0f2fb, count_v2), _ror32(0xc8b52570, count_v2),
             _ror32(0xebc2f8cd, count_v2), _ror32(0x7c104d93, count_v2)]
    end_count = (count_v2 + 6) & 0xFF
    end = [_ror32(0x19be4866, end_count), _ror32(0xe85986b4, end_count),
           _ror32(0xe19b326e, end_count), _ror32(0x71d1d7d4, end_count)]
    m = [struct.unpack_from('<I', message, i * 4)[0] for i in range(16)]
    a, b, c, d = start

    def run(kind, shifts, offset):
        nonlocal a, b, c, d
        for i in range(16):
            phase = i & 3
            word = m[orders[offset + i]]
            if phase == 0:
                a = _md5_v3_step(kind, a, b, c, d, word, shifts[i], sv[offset + i])
            elif phase == 1:
                d = _md5_v3_step(kind, d, a, b, c, word, shifts[i], sv[offset + i])
            elif phase == 2:
                c = _md5_v3_step(kind, c, d, a, b, word, shifts[i], sv[offset + i])
            else:
                b = _md5_v3_step(kind, b, c, d, a, word, shifts[i], sv[offset + i])

    run(0, [7, 12, 17, 22] * 4, 0)
    run(1, [5, 9, 14, 20] * 4, 16)
    run(2, [4, 11, 16, 23] * 4, 32)
    run(3, [6, 10, 15, 21] * 4, 48)
    ret = bytearray(16)
    for i, v in enumerate([_u32((start[i] + x) ^ end[i]) for i, x in enumerate((a, b, c, d))]):
        struct.pack_into('<I', ret, i * 4, v)
    ret = bytes(ret)
    return ret + _le32(_sum_md5(ret))


def hash_f13(query_sm3: bytes, body_md5: bytes, ts_bytes: bytes, khronos: int) -> bytes:
    """hash F13 —— x-medusa 的内层摘要。含分支 0/2 两条路径。"""
    iv = _get_iv(_get_iv(_get_iv(0x20230928, query_sm3), body_md5), ts_bytes)
    low = iv & 15
    iv_v0 = (low * 171) >> 9
    branch = low - iv_v0 * 3
    if branch == 2:
        return _branch2_f13(iv, query_sm3, body_md5, ts_bytes, khronos)
    if branch != 0:
        return query_sm3[:16] + body_md5 + _le32(_sum_md5(query_sm3 + body_md5))
    return _branch0_f13(iv, iv_v0, query_sm3, body_md5, ts_bytes, khronos)


def _branch2_f13(iv, query_sm3, body_md5, ts_bytes, khronos):
    v = (iv & 13) * 86
    iv_v0 = ((v >> 15) & 0xFF) + ((v >> 8) & 0xFF)
    n1 = [0x8980f29b, 0xeb549c7f, 0xb08726db, 0xd40cb5e6, 0xe8f559e4][iv_v0]
    count_v1 = (n1 + khronos + 1) & 0xFF
    count_v2 = _u32(n1 + khronos)
    shift = (count_v2 + 5) & 7
    seed = [0x84, 0x96, 0x77, 0x9d, 0xd4, 0x15, 0x0b, 0xf8]
    pad = bytes(((val | (val << 8)) >> shift) & 0xFF for val in seed)
    input_data = query_sm3 + body_md5 + ts_bytes + pad + bytes.fromhex('a0010000')
    return _md5_sum_v3(input_data, count_v2,
                       _BRANCH2_ORDERS[(iv_v0 << 6):((iv_v0 + 1) << 6)], count_v1)


_BRANCH0_TT = [
    0xebb64faf, 0x7aadcc2, 0xcf3187bf, 0xe01138ff, 0x6d0bfcff, 0x5a30a3be,
    0xb41ad638, 0x34180eb8, 0xf233eb6f, 0xb1a584cc, 0xccc30dc7, 0x47d1db51,
    0xd55653de, 0x70a84fa1, 0x57473c12, 0xf76f0288, 0x2c077f0a, 0xda0dcad0,
    0xfbb86f6c, 0xfdc4cf00, 0x688a020d, 0xe676c6a6, 0x8cd6338b, 0x1a3c8d0e,
    0xcce8b06b, 0x6ad0ed0b, 0xa0522717, 0xdc71ac83, 0x2285db71, 0xd5b4dda6,
    0x736f8650, 0x6560306c, 0x617ce2a6, 0xe423417e, 0x0a40e143, 0x544e4032,
    0x88dffb2a, 0x716c1ae0, 0x4c467a88, 0x05b23bb3, 0xe1d0b866, 0xbaa3dcb8,
    0xae3374d3, 0xc3381a50, 0x1702f75b, 0xfe6da368, 0xf0b4cf48, 0x4e0ffbb8,
    0x72aad10d, 0x26c53a3d, 0xf2bce0f6, 0xb4557581, 0x4a257fdd, 0x8c3182a2,
    0xab0b3b86, 0x3d5dfb14, 0x4f103634, 0xd37b52d7, 0x444eff16, 0xeb0a33d1,
    0x6ca86f6e, 0x00284ba7, 0x08387cfa, 0x5fb37586,
]
_BRANCH0_IV1 = [0xc4a78580, 0xb3c0fd39, 0xc58c5686, 0xc9aa3ba7, 0xf5a7adf2, 0x963c2ed1]


def _branch0_f13(iv, iv_v0, query_sm3, body_md5, ts_bytes, khronos):
    iv_v1 = _BRANCH0_IV1[iv_v0]
    count_v1 = (iv_v1 + khronos + 1) & 0xFF
    count_v2 = _u32(iv_v1 + khronos)
    tt = [_ror32(v, count_v1) for v in _BRANCH0_TT]
    n0 = (count_v2 + 2) & 7
    seed = [0xfa, 0x45, 0x61, 0xd7]
    pad = bytes(((val | (val << 8)) >> n0) & 0xFF for val in seed)
    data = query_sm3 + body_md5 + ts_bytes + pad + bytes.fromhex('00000000000001a0')
    di = [int.from_bytes(data[i:i + 4], 'big') for i in range(0, len(data), 4)]
    di0 = di[0]
    for i in range(112):
        di1 = di[i + 1]
        di14 = di[i + 14]
        r1 = _rol32(di1, 14) ^ _rol32(di1, 25) ^ (di1 >> 3)
        r2 = _rol32(di14, 13) ^ _rol32(di14, 15) ^ (di14 >> 10)
        di.append(_u32(di0 + di[i + 9] + r1 + r2))
        di0 = di1
    init = [_ror32(v, count_v2 & 31) for v in
            [0x7aba4fc8, 0x67166507, 0x6403fa00, 0x340f512f,
             984304912, 3005047866, 2874125293, 2152413264]]
    chosen = [
        [101, 5, 7, 6, 3, 2, 1, 0, 5, 4, 3],
        [96, 0, 6, 7, 5, 3, 2, 1, 5, 4, 4],
        [96, 7, 6, 2, 1, 4, 0, 5, 4, 3, 5],
        [99, 3, 6, 2, 4, 5, 1, 0, 0, 7, 6],
        [96, 0, 5, 6, 7, 3, 1, 2, 5, 4, 4],
        [100, 2, 0, 3, 5, 4, 6, 7, 2, 1, 5],
    ][iv_v0]
    d = init[:]
    for i in range(chosen[0]):
        base = iv_v1 + i
        n0v = di[base & 127]
        n1 = (d[chosen[3]] ^ d[chosen[4]]) & d[chosen[1]] ^ d[chosen[3]]
        n2 = _rol32(d[chosen[1]], 26) ^ _rol32(d[chosen[1]], 21) ^ _rol32(d[chosen[1]], 7)
        n4 = _u32(n0v + n1 + n2 + tt[base & 63] + d[chosen[5]])
        n5 = _rol32(d[chosen[2]], 30) ^ _rol32(d[chosen[2]], 19) ^ _rol32(d[chosen[2]], 10)
        n6 = (d[chosen[2]] & d[chosen[6]]) | ((d[chosen[2]] | d[chosen[6]]) & d[chosen[7]])
        n7 = _u32(n5 + n6)
        old = d[chosen[9]]
        d.insert(0, d.pop())
        d[chosen[10]] = _u32(n7 + n4)
        d[chosen[8]] = _u32(old + n4)
    ret = bytearray(32)
    for i in range(8):
        struct.pack_into('>I', ret, i * 4, _u32(d[i] + init[i]))
    folded = bytes(a ^ b for a, b in zip(ret[:16], ret[16:32]))
    ret[:16] = folded
    return bytes(ret[:16]) + _le32(_sum_md5(bytes(ret[:16])))


def branch_of(query: bytes, body: bytes, khronos: int) -> int:
    """预判 hash F13 的分支，搜索接口需要固定分支 0。"""
    body_md5 = md5_raw(body) if body else b'\x00' * 16
    q = sm3(query)
    iv = _get_iv(_get_iv(_get_iv(0x20230928, q), body_md5), _le32(khronos))
    low = iv & 15
    return low - (((low * 171) >> 9) * 3)


# ---------------------------------------------------------------------------
# 完整签名组装
# ---------------------------------------------------------------------------

def sign_headers(query: bytes, body: bytes, khronos: int, ticket: int,
                 ua: str = None) -> dict:
    """生成一套签名请求头。query 是 '?' 之后的字节串。"""
    rnd = random.getrandbits(16)
    headers = {
        'x-ss-req-ticket': str(ticket),
        'x-khronos': str(khronos),
        'x-ladon': x_ladon(khronos),
        'x-argus': x_argus(khronos),
        'x-gorgon': x_gorgon(query, body, khronos, rnd),
        'x-helios': x_helios(khronos),
    }
    if ua:
        headers['User-Agent'] = ua
    return headers


def gzip_body(payload) -> bytes:
    """请求体按 App 习惯 gzip 压缩，Content-Encoding: gzip。"""
    if isinstance(payload, str):
        payload = payload.encode()
    co = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)  # gzip
    return co.compress(payload) + co.flush()
