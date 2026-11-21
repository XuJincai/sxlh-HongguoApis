# coding=utf-8
"""HongguoApis —— 红果短剧（com.phoenix.read）API 客户端。

游客态：搜索、短剧详情、剧集列表、播放地址、评论列表、弹幕。
登录态：发评论、点赞、追更、观看历史（需 sessionid，见 utils/auth.py）。
"""

from hongguo_apis.search_api import search_request, parse_search_response
from hongguo_apis.play_api import (video_detail_request, multi_video_model_request,
                                    player_model_request, parse_video_detail,
                                    parse_video_models)
from hongguo_apis.comment_api import (episode_comments_request,
                                       parse_episode_comments,
                                       fetch_episode_comments)
from hongguo_apis.danmaku_api import danmaku_request, parse_danmaku, fetch_danmaku
from utils.auth import GuestIdentity, LoginIdentity

__all__ = [
    'search_request', 'parse_search_response',
    'video_detail_request', 'multi_video_model_request', 'player_model_request',
    'parse_video_detail', 'parse_video_models',
    'episode_comments_request', 'parse_episode_comments', 'fetch_episode_comments',
    'danmaku_request', 'parse_danmaku', 'fetch_danmaku',
    'GuestIdentity', 'LoginIdentity',
]
