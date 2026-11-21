# coding=utf-8
"""x-Medusa 签名头（搜索族必需）：TLV protobuf + xmxor 混淆 + AesV3 变体加密。

由 query/body/khronos/device 组装 protobuf 消息，hash F13 摘要内嵌，再经
keyHash 种子、xmxor 字节混淆、AesV3（AES 白盒变体）加密，最后 base64。
所有步骤本地可算，不依赖真机。

主要入口：
- `build_medusa(url, body, khronos, device)` —— 生成 x-medusa 头。
- `AesV3` —— AES 白盒变体（依赖 SBOX）。
"""

import base64
import random
import time

from utils.hongguo_sign import sm3, _u32, _rol32, _ror32, _le32, _be32, md5_raw, hash_f13

_PROCESS_NONCE = base64.urlsafe_b64encode(random.randbytes(18)).decode().rstrip('=')
_PROCESS_STARTED = int(time.time() * 1000)

_SIGN_KEY = bytes.fromhex(
    '8ebdfa3806ecc5cee79423e6029ed82540bc2218bb7eae'.ljust(48, '0') + 'f71cb691f7aa8aa2f5'
)  # 占位，实际在 build_medusa 内拼接


# ---------------------------------------------------------------------------
# protobuf 编码
# ---------------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    value = int(value)
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _zigzag(value: int) -> int:
    value = int(value)
    return (-value) * 2 - 1 if value < 0 else value * 2


def _proto_field(tag, value, kind='string'):
    """TLV 字段。kind: string|bytes|message|sint|int|float"""
    if value is None or value == '':
        return b''
    if kind in ('bytes', 'string', 'message'):
        if kind == 'bytes':
            body = bytes.fromhex(value) if isinstance(value, str) else bytes(value)
        elif kind == 'message':
            body = bytes(value)
        else:
            body = str(value).encode()
        return _varint((tag << 3) | 2) + _varint(len(body)) + body
    if kind == 'float':
        import struct
        body = struct.pack('<f', float(value))
        return _varint((tag << 3) | 5) + body
    if kind == 'sint':
        value = _zigzag(value)
    return _varint(tag << 3) + _varint(value)


def _proto(fields) -> bytes:
    return b''.join(_proto_field(t, v, k) for t, v, k in fields)


# ---------------------------------------------------------------------------
# deviceProto / env 消息
# ---------------------------------------------------------------------------

def _device_proto(device_id: str) -> bytes:
    return _proto([
        (1, 1, 'sint'), (2, 2, 'sint'), (3, '8662', 'string'),
        (4, device_id, 'string'), (5, _PROCESS_NONCE, 'string'),
        (6, '!noperm!', 'string'), (7, -888888, 'sint'), (8, -888888, 'sint'),
        (9, 3, 'sint'), (10, -888888, 'sint'), (11, '!notset!', 'string'),
        (12, 'Asia/Shanghai,8', 'string'), (13, 'zh_CN', 'string'),
        (14, 4, 'sint'), (16, 0.0, 'float'), (17, 0.0, 'float'), (18, 0.0, 'float'),
        (19, 0.0, 'float'), (20, 0.0, 'float'), (21, 0.0, 'float'),
        (22, '16', 'string'), (23, 41, 'sint'), (24, 36, 'sint'),
        (25, _PROCESS_STARTED, 'sint'), (26, _PROCESS_STARTED, 'sint'),
        (27, _PROCESS_STARTED, 'sint'), (28, _PROCESS_STARTED, 'sint'),
        (29, -1, 'sint'), (30, '25053RT47C', 'string'), (31, 'Redmi', 'string'),
        (32, '25053RT47C', 'string'), (33, '25053RT47C', 'string'),
        (34, 'Xiaomi', 'string'), (35, 'Redmi', 'string'), (36, 'Redmi', 'string'),
        (38, 31, 'sint'),
    ])


# ---------------------------------------------------------------------------
# xmxor / keyHash
# ---------------------------------------------------------------------------

def _xmxor(data: bytes, key: bytes) -> bytes:
    n = len(data)
    encoded = bytearray(n)
    # JS Buffer 越界读为 undefined：参与 + 运算变 NaN，NaN&255=0，
    # 最终 (~0)&255=255 —— 与按 0 处理结果不同，必须复刻 NaN 语义
    def kb(idx):
        return key[idx] if idx < len(key) else None
    for i in range(n):
        at = (i * 4) & 28
        d0 = kb(at)
        d1 = kb(at + 1)
        if d0 is None or d1 is None:
            # 任一越界 → d2 全程 NaN → 结果字节恒 255
            encoded[n - i - 1] = 255
            continue
        d2 = ((data[i] << 4) | (data[i] >> 4)) & 255
        d2 = (d2 + d0) & 0xFFFFFFFF
        d2 = (~d2) & 0xFFFFFFFF
        d2 ^= d1
        d2 &= 255
        d2 = ((d2 << 3) | (d2 >> 5)) & 255
        d2 = (d2 + d1) & 255
        d2 = (d2 ^ d0) & 255
        encoded[n - i - 1] = (~d2) & 255
    last = encoded[n - 1] ^ encoded[n - 2]
    first = encoded[0]
    encoded[0] = (~last + first) & 255
    encoded[1] = ((encoded[0] ^ encoded[n - 1] ^ 254) + encoded[1]) & 255
    encoded[2] = (encoded[2] + (((last - first) & 255) ^ (((encoded[1] << 3) | (encoded[1] >> 5)) & 255) ^ 2)) & 255
    for i in range(n - 4):
        temp = ((((encoded[i + 2] << 3) | (encoded[i + 2] >> 5)) & 255) ^ encoded[i + 1] ^ (i + 3)) & 0xFFFFFFFF
        encoded[i + 3] = (~temp + encoded[i + 3]) & 255
    encoded[n - 1] ^= encoded[n - 2]
    total = 0
    for i in range(n - 1):
        total += encoded[i + 1]
    encoded[0] = ((encoded[0] ^ encoded[1]) + total) & 255
    return bytes(encoded)


def _key_hash(sign_key: bytes, rnd: int) -> tuple:
    digest = sm3(sign_key + _le32(rnd) + sign_key)
    d1 = (rnd >> 16) & 255
    d2 = (((d1 << 11) | (rnd >> 24)) ^ (d1 >> 5) ^ d1) & 0xFFFFFFFF
    d2 = (~d2) & 0xFFFFFFFF
    return digest, _le32(d2)


# ---------------------------------------------------------------------------
# AesV3（AES 白盒变体）
# ---------------------------------------------------------------------------

_SBOX_B64 = (
    "+n0Ia5xZs0sEXznQOEqRmQBnpiCf9U2Ccybu3xhmgzOAAxn72f6uqqmwUsYL83klTni0NqxdGieeiNu9PGPsSRXBMB/cuFbU"
    "bM3KCUPINaPvHvSW0vwOcnuUhNHqRVpiAj/TEoE0K91+5ijypUYTATsh9mE3KSoN7Yyvv51cuyR2D3XkU4nhmI2xmmVwT1RM"
    "WKtub4sjxAcRDLrPoKSO2AU9FLLadMPX577Wf95IFj6FkKFVt3dCIsmGUC4X+WQxLJvxbRxEaOPpqJOXyzJX6+Vxaq3AzMfF"
    "/WAdoi1Hp+JRaV56zgpBtpWP97mH4DoGEIq1+FvV8LyS/3wvwugbQOwb2r26mJEMsiuDQTRn+wrYdrVGBVlhI3WQhyrjUBVM"
    "rLF5667llUcEaPCGPVGLD8qO5LlO8hKCvA7V9+8oJc9bXelqVQLhM76T5/WtnT45JKji+hdX0HoNCDDWuKON/QeaxB5uImSX"
    "0h2wv0VmP2zd2yeApxHcpsVS+MC2yFwAc2B7oBkTqsk1SEvTpM2fmfMQREBUfin0Bh+iq6EvPPavhWI2IX9e3yAas7Tm/3KE"
    "j2UmlFp36kN4x0rMLBRrxuh0U/zUHM4xcAMYjJY4MonxOl/X+alpt2M3WMI7w3HLnpIBigtNiJu7T21v4P6lSd5WFgntnMEt"
    "7oF92XzRLkJbTcGmXepE/UVOG6E/0YnhfS+q26utWcuxzpooyeD2cDlK1/8w9d28VzsRjbLuALbmGlp8+d7EzS6Au7lMpZ+E"
    "CMZvQmzwJ+eLOpxR+2chdUExp8ogQyq3v9l68rX4jCwjg0+PYKAEEzcU4wHFY2ZcdIHfWL1okD3SszT0GZMyKdZJrg1L2Aee"
    "rB4tC0C4crp2EHGo5FYdSP7lwkeR2ocmnR+Ia8CYviUJlzOjhRZef9xuVOn3qcjow3fQgivsAmKKkg4+sA8F8/GWeDiGNhg8"
    "JM8KtFPMYWWkx5TVFX5t73kiNRJqjlIGVXtGZFCV4gzt0xcDopuZ6xz8r9Rzafpf9ywev8jh8592gHFIqpStZPuJxmDDMrNN"
    "0uBE3V+oscdoIzTJbRJ/t+sVvqnReJOgDJKk10fjisJwqyZBmnmn2BSFj8BvVtCMEbkuPOKdzw7eA11GPs04Qw8zWtkaZWwi"
    "O/wwpojqN6K0jY5RnNZA7vn4hPSul+nKCkVnVwQvg1zVxcSCtqORmB9KrJaBbssbCQivGJVJfVTt+hYxOtq4ZvWl8f4QAQZ0"
    "zGPffCgl9s6yT4vlvIdpu4YhBwA25wtQWZsc6GJYGWHyvSdeuh3mmUI9DSq13Fsp8C1MU3tqc04/df9LoTUXVXI5INOw/e8C"
    "7Hd+5CvbkMEFnnrUUmskEw=="
)


SBOX = base64.b64decode(_SBOX_B64)


class AesV3:
    """AES 白盒变体（4 组 SBOX 依 khronos & 3 选择，自定义 shift/add 顺序）。"""

    def __init__(self, key: bytes, khronos: int):
        self.word_size = khronos & 3
        ws = self.word_size
        self.box = SBOX[ws * 256:(ws + 1) * 256]
        self.con = [[1, 0, 2, 3], [1, 3, 0, 2], [0, 1, 3, 2], [1, 0, 2, 3]][ws]
        self.con2 = [[1, 0, 2, 3], [2, 0, 3, 1], [0, 1, 3, 2], [1, 0, 2, 3]][ws]
        self.order = [
            [0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3],
            [0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11],
            [0, 9, 14, 7, 4, 13, 2, 11, 8, 1, 6, 3, 12, 5, 10, 15],
            [0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3],
        ][ws]
        init = [0xca025ddc, 0x823dc546, 0xc9420583, 0xc298225f][ws]
        initial = b''.join(_le32(init) for _ in range(4))
        mk = bytearray(a ^ b for a, b in zip(initial, key))
        expanded = bytearray(mk) + bytearray(32)
        rounds = 8
        for i in range(4, 12):
            at = 4 * (i - 1)
            a, b, c, d = expanded[at], expanded[at + 1], expanded[at + 2], expanded[at + 3]
            if (i & 3) == 0:
                t = (_u32(init >> (rounds & 24)) ^ self.box[b]) & 255
                b = self.box[c]
                c = self.box[d]
                d = self.box[a]
                a = t
            rounds += 2
            expanded[at + 4] = a ^ expanded[at - 12]
            expanded[at + 5] = b ^ expanded[at - 11]
            expanded[at + 6] = c ^ expanded[at - 10]
            expanded[at + 7] = d ^ expanded[at - 9]
        self.keys = [list(expanded[i * 4:i * 4 + 4]) for i in range(12)]

    @staticmethod
    def _matrix(data):
        return [list(data[i * 4:i * 4 + 4]) for i in range(4)]

    @staticmethod
    def _flat(rows):
        return bytes(v for row in rows for v in row)

    def _add(self, rows, key):
        for i in range(4):
            for j in range(4):
                rows[i][j] ^= key[i][j]

    def _add_con(self, rows, keys):
        for i in range(4):
            for j in range(4):
                rows[i][j] ^= keys[i][self.con2[j]]

    def _sub(self, rows):
        for i in range(4):
            for j in range(4):
                rows[i][j] = self.box[rows[i][j]]
        old = [row[:] for row in rows]
        for i in range(4):
            rows[i] = [old[self.con2[i]][k] for k in range(4)]

    def _shift(self, rows):
        b = self._flat(rows)
        for i in range(16):
            rows[i // 4][i % 4] = b[self.order[i]]

    def _shift_con(self, rows):
        old = [row[:] for row in rows]
        for i in range(4):
            rows[i] = [old[i][self.con2[k]] for k in range(4)]

    def _mix(self, rows):
        for i in range(4):
            t = rows[0][i] ^ rows[1][i] ^ rows[2][i] ^ rows[3][i]
            u = rows[0][i]

            def xt(x):
                return ((x << 1) ^ (0x1b if x & 128 else 0)) & 255
            rows[0][i] ^= t ^ xt(rows[0][i] ^ rows[1][i])
            rows[1][i] ^= t ^ xt(rows[1][i] ^ rows[2][i])
            rows[2][i] ^= t ^ xt(rows[2][i] ^ rows[3][i])
            rows[3][i] ^= t ^ xt(rows[3][i] ^ u)

    def _block(self, value):
        rows = self._matrix(value)
        self._add_con(rows, self.keys[0:4])
        for i in (1, 2):
            self._sub(rows)
            self._shift(rows)
            if i == 1:
                self._shift_con(rows)
                self._mix(rows)
            self._add_con(rows, self.keys[i * 4:(i + 1) * 4])
        self._add(rows, self.keys[4:8])
        return self._flat(rows)

    def encrypt(self, data: bytes, iv: bytes) -> bytes:
        source = bytearray(data)
        # JS Buffer 越界读当 0 处理（Buffer[idx] 越界为 undefined，位运算后归 0）
        def b(idx):
            return source[idx] if idx < len(source) else 0
        plaintext = bytearray(32)
        for i in range(31):
            at = i * 8
            n0 = (b(at) >> 4) & 2
            n1 = n0 | (b(at + 1) & 64)
            n2 = n1 | ((b(at + 2) >> 2) & 1)
            n3 = n2 | ((b(at + 3) << 3) & 128)
            n4 = n3 | ((b(at + 4) >> 1) & 4)
            n5 = n4 | ((b(at + 5) << 3) & 16)
            n6 = n5 | ((b(at + 6) << 5) & 32)
            plaintext[i] = (n6 | ((b(at + 7) >> 4) & 8)) & 255
        plaintext[31] = 1
        blocks = []
        previous = bytearray(iv)
        for i in range(0, 32, 16):
            chunk = bytes(a ^ b for a, b in zip(plaintext[i:i + 16], previous))
            value = self._block(chunk)
            blocks.append(value)
            previous = bytearray(value)
        key = b''.join(blocks)
        # JS out = Buffer.from(source) 越界写被丢弃，读也当 0：此处按源长扩展再截回
        orig_len = len(source)
        out = bytearray(source) + bytearray(31 * 8)
        for i in range(31):
            at = i * 8
            k = key[i]
            out[at] = (out[at] & 0xdf) | ((k << 4) & 32)
            out[at + 1] = (out[at + 1] & 0xbf) | (k & 64)
            out[at + 2] = (out[at + 2] & 0xfb) | ((k << 2) & 4)
            out[at + 3] = (out[at + 3] & 0xef) | ((k >> 3) & 16)
            out[at + 4] = (out[at + 4] & 0xf7) | ((k + k) & 8)
            out[at + 5] = (out[at + 5] & 0xfd) | ((k >> 3) & 2)
            out[at + 6] = (out[at + 6] & 0xfe) | ((k >> 5) & 1)
            out[at + 7] = (out[at + 7] & 0x7f) | ((k << 4) & 128)
        return key[-1:] + bytes(out[:orig_len])


# ---------------------------------------------------------------------------
# buildMedusa
# ---------------------------------------------------------------------------

def build_medusa(url: str, body: bytes, khronos: int, device: dict) -> str:
    """生成 x-medusa 头。device 需含 device_id / version_name。"""
    query = url.split('?', 1)[1].encode() if '?' in url else b''
    body_md5 = md5_raw(body) if body else b'\x00' * 16
    query_sm3 = sm3(query)
    ts = _le32(khronos)
    query_body_ts = hash_f13(query_sm3, body_md5, ts, khronos)

    nested = _proto([(1, 111, 'sint'), (2, 10, 'sint'),
                     (3, 694367, 'sint'), (5, 586952199, 'sint')])
    message_rand = random.getrandbits(32)
    env_launch = random.randint(100, 120)
    env_pid = random.randint(10001, 12000)
    env = _proto([
        (1, env_launch, 'sint'), (2, 146331399, 'sint'), (3, 146331396, 'sint'),
        (5, 7, 'sint'), (6, 'v04.06.04.03-bugfix', 'string'), (7, env_pid, 'sint'),
        (12, _device_proto(device['device_id']), 'message'),
        (13, _proto([(1, int(time.time()), 'sint'), (2, -2, 'sint'), (4, 200, 'sint')]), 'message'),
        (14, device['version_name'], 'string'),
    ])
    query_hash = sm3(query + body_md5 + b'none')
    message = _proto([
        (1, 'f7e85ffad7d7dc3bd62ac87057cf6118', 'bytes'),
        (2, 3, 'sint'), (3, message_rand, 'sint'), (4, '8662', 'string'),
        (5, device['device_id'], 'string'), (6, '1588093228', 'string'),
        (7, device['version_name'], 'string'), (8, 'v04.06.04-ml-android', 'string'),
        (9, 67503104, 'sint'), (10, '4001000000000000', 'bytes'),
        (12, khronos, 'sint'), (13, query_body_ts, 'bytes'),
        (14, query_sm3[:6], 'bytes'), (15, nested, 'message'),
        (16, _PROCESS_NONCE, 'string'), (17, khronos, 'sint'),
        (19, query_hash, 'bytes'), (20, 'none', 'string'), (21, 312, 'sint'),
        (23, env, 'message'),
        (24, '{"cmr":16777216,"cmr2":16777216,"un_h":1879194040,"vpn":0,"kd":0,'
             '"fkd":3672518972,"pd":-1872573247,"dyn":"","do":0,"tk":true}', 'string'),
    ])

    rnd = random.getrandbits(32)
    sign_key = bytes.fromhex('8ebdfa3806ecc5cee79423e6029ed82540bc2218bb7eae'
                             'f71cb691f7aa8aa2f5')
    hash_out, seed = _key_hash(sign_key, rnd)
    transformed = bytearray(_xmxor(message, hash_out))
    transformed = bytearray((bytes.fromhex('4001000000000000') + bytes(transformed))[::-1])
    for i in range(len(transformed)):
        transformed[i] ^= seed[(~i) & 3]
    check = ((query_sm3[0] & 63) << 14) | 0x18000001 | ((query_body_ts[0] & 63) << 8)
    xm_rand = random.getrandbits(32)
    packed = (bytes([0x35]) + _le32(xm_rand) + _le32(check) + bytes(transformed)
              + bytes([(rnd >> 16) & 255, (rnd >> 24) & 255]))
    encrypted = AesV3(bytes.fromhex('f1593376766ea98d34f31b057a9d5be4'), khronos).encrypt(
        packed, bytes.fromhex('1fe109a4125283f418de9e051a969e12'))
    version = bytes.fromhex('03000000f7e85ffad7d7dc3bd62ac87057cf6118')
    prefix = bytearray(20)
    for i in range(0, 20, 4):
        v = int.from_bytes(version[i:i + 4], 'little') ^ khronos
        prefix[i:i + 4] = (v & 0xFFFFFFFF).to_bytes(4, 'little')
    out = bytes(prefix) + bytes([rnd & 255, (rnd >> 8) & 255, 0, 1]) + encrypted
    return base64.b64encode(out).decode()
