# coding=utf-8
"""设备档案与公共请求构造。

App 7.4.5.32 的公共 query 块（顺序固定）与公共 header（顺序固定）。
对齐原则：一个参数不能少、一个字段的长度不能减、header 顺序也对齐。

设备档案三档：
- XIAOMI_PAD  —— 23116PN5BC / Xiaomi（pad 档案，rom V816）
- REDMI_K70E  —— 25053RT47C / Redmi（注册档案同款）
- SAMSUNG_S10 —— SM-N9860（老参考实现同款）
同一身份必须固定用同一档（device_type/brand/rom/UA 成套）。
"""

import random
import time
import urllib.parse

DEVICE_PROFILES = {
    'xiaomi_pad': {
        'device_type': '23116PN5BC', 'device_brand': 'Xiaomi',
        'resolution': '1080*2232', 'dpi': '420',
        'rom_version': 'miui_V816_OS3.0.309.0.WNBCNXM',
        'ua': ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
               '23116PN5BC; Build/BP2A.250605.031.A3; Cronet/TTNet)'),
        'register_model': '23116PN5BC', 'register_brand': 'Xiaomi',
    },
    'redmi_k70e': {
        'device_type': '25053RT47C', 'device_brand': 'Redmi',
        'resolution': '1280*2772', 'dpi': '520',
        'rom_version': 'W528JS release-keys',
        'ua': ('com.phoenix.read/74532 (Linux; U; Android 16; zh_CN; '
               '25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNet)'),
        'register_model': '25053RT47C', 'register_brand': 'Redmi',
    },
}

APP_VERSION_CODE = '74532'
APP_VERSION_NAME = '7.4.5.32'

# 公共 query 块：顺序即发送顺序（App 7.4.5）
COMMON_QUERY = [
    ('device_platform', 'android'),
    ('os', 'android'),
    ('ssmix', 'a'),
    # _rticket 插这里
    # cdid 插这里
    ('channel', 'update'),
    ('aid', '8662'),
    ('app_name', 'novelread'),
    ('version_code', APP_VERSION_CODE),
    ('version_name', APP_VERSION_NAME),
    ('manifest_version_code', APP_VERSION_CODE),
    ('update_version_code', APP_VERSION_CODE),
    # resolution / dpi / device_type / device_brand 由档案填
    ('language', 'zh'),
    ('os_api', '36'),
    ('os_version', '16'),
    ('ac', 'wifi'),
    ('is_64_runtime', 'false'),
    ('is_64_device', 'true'),
    # host_abi 插这里
    ('dragon_device_type', 'phone'),
    ('pv_player', APP_VERSION_CODE),
    ('is_x86_device', 'false'),
    ('compliance_status', '0'),
    ('need_personal_recommend', '1'),
    ('player_so_load', '1'),
    ('is_android_pad_screen', '0'),
    # rom_version 由档案填
    # iid / device_id / klink_egdi 由身份填
]


def build_common_query(identity, stamp_ms: int) -> str:
    """客户端顺序的公共 query 串。GET/POST 族的公共部分一致。

    客户端在 is_64_device 与 host_abi 之间带一个空参数（`&&`），逐字节保留。
    """
    profile = DEVICE_PROFILES['xiaomi_pad']
    pairs = [
        ('device_platform', 'android'), ('os', 'android'), ('ssmix', 'a'),
        ('_rticket', str(stamp_ms)),
        ('cdid', identity.cdid),
        ('channel', 'update'), ('aid', '8662'), ('app_name', 'novelread'),
        ('version_code', APP_VERSION_CODE), ('version_name', APP_VERSION_NAME),
        ('manifest_version_code', APP_VERSION_CODE),
        ('update_version_code', APP_VERSION_CODE),
        ('resolution', profile['resolution']), ('dpi', profile['dpi']),
        ('device_type', profile['device_type']),
        ('device_brand', profile['device_brand']),
        ('language', 'zh'), ('os_api', '36'), ('os_version', '16'),
        ('ac', 'wifi'), ('is_64_runtime', 'false'), ('is_64_device', 'true'),
        ('', ''),  # 客户端在两参间带空参数（&&），保留
        ('host_abi', 'armeabi-v7a'), ('dragon_device_type', 'phone'),
        ('pv_player', APP_VERSION_CODE), ('is_x86_device', 'false'),
        ('compliance_status', '0'), ('need_personal_recommend', '1'),
        ('player_so_load', '1'), ('is_android_pad_screen', '0'),
        ('rom_version', profile['rom_version']),
        ('iid', identity.iid), ('device_id', identity.device_id),
    ]
    if getattr(identity, 'klink_egdi', ''):
        pairs.append(('klink_egdi', identity.klink_egdi))
    return '&'.join(f'{k}={urllib.parse.quote(str(v), safe="")}' if k
                    else ''
                    for k, v in pairs)


def new_trace_id() -> str:
    """00-{32hex}-{16hex}-01（格式与客户端一致，长度逐字段一致）。"""
    base = '%08x' % (int(time.time() * 1000) & 0xFFFFFFFF)
    host = '0db6565bd44b2ba'
    rand = '%07x' % random.getrandbits(28)
    seg1 = base + host + rand + '21d6'
    return f'00-{seg1}-{seg1[:16]}-01'


def new_reading_request(stamp_ms: int) -> str:
    """x-reading-request：{ticket+1}-{9位随机}。"""
    return f'{stamp_ms + 1}-{random.randint(100000000, 999999999)}'


def decode_response(raw: bytes, encoding: str) -> bytes:
    """按 Content-Encoding 解响应体（客户端头带 br，服务器会回 br）。"""
    if not raw:
        return raw
    try:
        if encoding == 'br':
            import brotli
            return brotli.decompress(raw)
        if encoding == 'gzip':
            import gzip
            return gzip.decompress(raw)
    except ImportError:
        pass
    return raw
