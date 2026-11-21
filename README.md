# HongguoApis

红果短剧（com.phoenix.read，字节系免费短剧 App）API 客户端。纯 Python 实现，签名本地可算，不依赖真机、浏览器或抓包代理。

## 能力

游客态（匿名 device_id 即可，无需注册账号）：

- **搜索**：`reading/bookapi/search/tab/v`，关键词搜短剧，翻页游标（search_id/passback/next_offset）完整
- **详情**：`novel/player/video_detail/v1`，剧集列表（95+ 集）+ 简介 + 分类 + 播放计数
- **播放地址**：`novel/player/multi_video_model/player/v1`，5 档清晰度（360p~1080p）可下载 MP4 源
- **上新发现**：`/reading/distribution/category/landpage/v`（App 端点，游客可用）
  - 真人剧 genre=short_play / AI 剧 genre=ai_series，按线上时间倒序
  - 近 7 天上新（含「今日上新」标记），翻页 next_offset+session_id
- **评论**：`novel/commentapi/comment/list/{group_id}/v1`（App 端点，游客可用）
  - 剧评：group_id=series_id, group_type=1, comment_source=1, server_channel=33
  - 单集评论：group_id=video_id, group_type=30, comment_source=4, server_channel=17
  - 支持翻页（cursor）、点赞数/回复数/作者信息
- **弹幕**：`novel/commentapi/comment/list/{vid}/v1`，时轴弹幕分页拉全量

- **相似剧/专辑**：`reading/distribution/book_pack_fields/inner_feed_detail/v1`（季数/催更数/爆剧标签）
- **观看进度上报**：`reading/bookapi/read_history/update/v`（游客态写匿名档案，登录态写账号）

登录态（sessionid，见下）：

- **官网扫码登录** —— `passport/web/get_qrcode/` + `check_qrconnect/` 纯 HTTP 取 sessionid
- **账号资料** —— `passport/account/info/v2/`
- **发评论 / 点赞 / 追更** —— 写接口需要登录 cookie

## 签名体系

红果是字节 TTNet 栈，核心签名头一族：

| Header | 说明 | 实现 |
|---|---|---|
| `x-gorgon` | 8404 变体（RC4 单向赋值 KSA + 位混淆），输入 = query md5 前 4B + body md5 前 4B + ts | `utils/hongguo_sign.py` |
| `x-ladon` / `x-argus` | khronos 派生轻量头 | 同上 |
| `x-helios` | MD5 小写 hex 驱动的 34 轮 uint64 分组密码 | 同上 |
| `x-khronos` | 请求时间戳（秒） | — |
| `x-ss-stub` | gzip(body) 的 MD5 大写 | 同上 |
| `x-medusa` | TLV protobuf + hash F13 摘要 + AesV3 白盒变体 | `utils/medusa.py` |

搜索接口签名族只接受 hash F13 **分支 0**，需对 `_rticket` 做微调重试（`branch_of` 预判）；播放族 7.4.5 参数无此限制。

弹幕接口走另一族专用签名（X-Gorgon 带 nonce 派生头部、X-Ladon 34 轮 TEA、X-Argus protobuf + SM3 72 轮 + AES-128-CBC），见 `utils/comment_sign.py`。

## 用法

```bash
pip install pycryptodome
```

```python
from utils.auth import GuestIdentity
from hongguo_apis import (search_request, parse_search_response,
                          video_detail_request, parse_video_detail,
                          player_model_request, parse_video_models,
                          comment_list_request, parse_comment_list,
                          fetch_danmaku)
import requests, json

s = requests.Session()

# 1. 游客身份（device_register，一次注册长期复用；落盘见 guest_identity.json）
guest = GuestIdentity.from_register(s)

# 2. 搜索
url, headers = search_request(guest, '总裁')
data = s.get(url, headers=headers, timeout=15).json()
result = parse_search_response(data)
print([b['title'] for b in result['books'][:5]])

# 3. 详情（拿剧集列表）
url, body, headers = video_detail_request(guest, result['books'][0]['book_id'])
data = s.post(url, data=body, headers=headers, timeout=15).json()
detail = parse_video_detail(data)
print(detail['title'], len(detail['episode_list']), '集')

# 4. 播放地址（多清晰度）
vid = detail['episode_list'][0]['video_id']
url, body, headers = player_model_request(guest, [vid])
data = s.post(url, data=body, headers=headers, timeout=15).json()
models = parse_video_models(data)
print(models[vid]['main_url'])          # 1080p MP4 直链
print([q['definition'] for q in models[vid]['qualities']])

# 5. 剧评（App 端点，书级评论列表 + 翻页）
sid = result['books'][0]['book_id']
url, body, headers = comment_list_request(guest, sid, 1, 1, 33, 2, book_id=sid, count=20)
data = s.post(url, data=body, headers=headers, timeout=15).json()
res = parse_comment_list(data)
print(res['total'], [c['text'][:20] for c in res['comments'][:3]])
# 单集评论：group_id=vid, group_type=30, comment_source=4, server_channel=17

# 6. 弹幕（时轴）
danmaku = fetch_danmaku(guest, vid, result['books'][0]['book_id'])
print(danmaku[0])                       # {'time': 0.3, 'text': '...', ...}
```

命令行一键全链路：

```bash
python main.py demo 总裁     # 搜索 -> 详情 -> 播放地址 -> 剧评 -> 弹幕
python main.py search 总裁
python main.py detail <book_id>
python main.py play <book_id>
python main.py comments <book_id> <video_id>
python main.py danmaku <book_id> <video_id>
```

登录态：官网扫码即可，无需 App 抓包——

```bash
python main.py login      # 生成 login_qr.png，用红果 App 扫码确认
python main.py account     # 验证登录态，打印账号资料
```

```python
from hongguo_apis.login_api import start_login, wait_login
qr = start_login()                        # qr['image'] 是 data:image/png;base64,...
result = wait_login(guest, qr['token'], qr['cookies'], timeout=300)
identity = result['identity']             # LoginIdentity（sessionid 已收好）
```

`login` 落盘 `login_identity.json`，之后所有请求自动带 sessionid cookie；
上游参考 `LoginIdentity.from_guest(guest, sessionid='...')` 也保留可用。

## 目录结构

```
hongguo_apis/
  search_api.py      搜索（分支 0 签名 + 翻页游标）
  play_api.py        详情 / 播放地址（7.4.5 参数族）
  comment_api.py     官网 SSR 剧评
  danmaku_api.py     App 弹幕流（comment 专用签名族）
  login_api.py       官网扫码登录（get_qrcode -> sessionid -> LoginIdentity）
utils/
  hongguo_sign.py    x-gorgon / x-ladon / x-argus / x-helios / hash F13
  medusa.py          x-medusa（TLV + AesV3）
  comment_sign.py    弹幕/评论族 X-Gorgon / X-Ladon / X-Argus
  device_register.py 游客 device_id 注册
  auth.py            GuestIdentity / LoginIdentity
tests/               离线黄金向量回归（无需网络）
main.py              命令行入口
```

## 致谢

签名还原参考了开源社区的既有工作（woshishiq1/drpys、tsukiyo-zero/hongguoTV、N3urda/hongguoTV、dawei233/hongguo-drama 等），本项目做了 Python 移植与 7.4.5 参数对齐。
