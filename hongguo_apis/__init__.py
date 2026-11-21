# coding=utf-8
"""HongguoApis —— 红果短剧（com.phoenix.read）API 客户端。

游客态：搜索、短剧详情、剧集列表、播放地址、评论列表、弹幕。
登录态：发评论、点赞、追更、观看历史（需 sessionid，见 utils/auth.py）。
"""

from hongguo_apis.search_api import search_request, parse_search_response
from hongguo_apis.play_api import (video_detail_request, multi_video_model_request,
                                    player_model_request, single_video_model_request,
                                    parse_video_detail, parse_video_models)
from hongguo_apis.comment_api import (comment_list_request, build_comment_body,
                                       parse_comment_list)
from hongguo_apis.danmaku_api import danmaku_request, parse_danmaku, fetch_danmaku
from hongguo_apis.category_api import landpage_request, landpage_body, parse_landpage
from hongguo_apis.user_api import user_info_request, fetch_user_info, parse_user_info
from hongguo_apis.recommend_api import book_pack_request, parse_book_pack
from utils.auth import GuestIdentity, LoginIdentity

__all__ = [
    'search_request', 'parse_search_response',
    'video_detail_request', 'multi_video_model_request', 'player_model_request',
    'single_video_model_request',
    'parse_video_detail', 'parse_video_models',
    'comment_list_request', 'build_comment_body', 'parse_comment_list',
    'danmaku_request', 'parse_danmaku', 'fetch_danmaku',
    'landpage_request', 'landpage_body', 'parse_landpage',
    'user_info_request', 'fetch_user_info', 'parse_user_info',
    'book_pack_request', 'parse_book_pack',
    'GuestIdentity', 'LoginIdentity',
]
