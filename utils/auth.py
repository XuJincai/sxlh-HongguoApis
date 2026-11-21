# coding=utf-8
"""游客态身份与会话管理。

三层身份：
1. `GuestIdentity` —— device_register 注册得来的 device_id/iid/cdid，游客态全接口可用。
2. `LoginIdentity` —— 登录后的 sessionid/token，写操作（发评论、点赞、追更、历史）需要。
3. `local_identity()` —— 不注册的随机身份，用于完全匿名的读取接口（少量接口不校验）。
"""

import json
import os
import time


class GuestIdentity:
    """游客身份。`from_register()` 走设备注册拿真身份，`from_json()` 复用落盘档案。"""

    def __init__(self, device_id: str, iid: str, cdid: str):
        if not (device_id and device_id.isdigit() and iid and iid.isdigit()):
            raise ValueError('device_id/iid 必须是数字串')
        self.device_id = str(device_id)
        self.iid = str(iid)
        self.cdid = cdid

    @classmethod
    def from_register(cls, session=None):
        from utils.device_register import register
        info = register(session)
        identity = cls(info['device_id'], info['iid'], info['cdid'])
        identity.raw = info.get('raw', {})
        identity.registered_at = time.time()
        return identity

    @classmethod
    def from_json_file(cls, path='guest_identity.json'):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        identity = cls(data['device_id'], data['iid'], data['cdid'])
        identity.raw = data.get('raw', {})
        identity.registered_at = data.get('registered_at', 0)
        return identity

    def save(self, path='guest_identity.json'):
        payload = {'device_id': self.device_id, 'iid': self.iid, 'cdid': self.cdid,
                   'registered_at': getattr(self, 'registered_at', 0),
                   'raw': getattr(self, 'raw', {})}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

    def as_query(self) -> dict:
        """游客接口 query 里的身份参数。"""
        return {'iid': self.iid, 'device_id': self.device_id}


class LoginIdentity(GuestIdentity):
    """登录态身份：游客身份 + sessionid + 用户信息。

    `sessionid` 是登录后的核心凭证；`user_id` 用于个人信息/历史等接口。
    """

    def __init__(self, device_id, iid, cdid, sessionid: str, user_id: str = '',
                 user_name: str = ''):
        super().__init__(device_id, iid, cdid)
        if not sessionid:
            raise ValueError('登录态必须有 sessionid')
        self.sessionid = sessionid
        self.user_id = str(user_id)
        self.user_name = user_name

    @classmethod
    def from_guest(cls, guest: GuestIdentity, sessionid, user_id='', user_name=''):
        return cls(guest.device_id, guest.iid, guest.cdid, sessionid, user_id, user_name)

    @classmethod
    def from_json_file(cls, path='login_identity.json'):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return cls(data['device_id'], data['iid'], data.get('cdid', ''),
                  data['sessionid'], data.get('user_id', ''), data.get('user_name', ''))

    def save(self, path='login_identity.json'):
        payload = {'device_id': self.device_id, 'iid': self.iid, 'cdid': self.cdid,
                   'sessionid': self.sessionid, 'user_id': self.user_id,
                   'user_name': self.user_name}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

    def auth_headers(self) -> dict:
        """登录态接口需要的额外请求头。"""
        return {'x-tt-session-dtrait': getattr(self, 'session_dtrait', ''),
                'Cookie': f'sessionid={self.sessionid}'}
