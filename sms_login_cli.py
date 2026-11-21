# coding=utf-8
"""验证码登录: python sms_login_cli.py <code> [sms_code_key]"""
import sys
from utils.auth import GuestIdentity
from hongguo_apis.login_api import send_sms_code, login_identity_from_sms

guest = GuestIdentity.from_json_file('guest_identity.json')
mobile = '15751076989'
code = sys.argv[1]
key = sys.argv[2] if len(sys.argv) > 2 else ''
try:
    identity = login_identity_from_sms(guest, mobile, code, sms_code_key=key)
    identity.save('login_identity.json')
    print('[+] LOGIN OK user_id=%s name=%s' % (identity.user_id, identity.user_name))
    print('[+] sessionid=%s...' % identity.sessionid[:24])
except RuntimeError as e:
    print('[-] %s' % e)
