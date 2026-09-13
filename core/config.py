"""路径、接口常量与共用异常。"""

import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 游戏标签缓存（历史日期补标签用）
TAG_CACHE_FILE = os.path.join(PLUGIN_DIR, "tag_cache.json")

# 发售日历接口（详见 DEVELOPMENT.md）
CALENDAR_API_HOST = "https://api.xiaoheihe.cn"
CALENDAR_PAGE_URL = "https://www.xiaoheihe.cn/game/publish_calendar"
GAME_DETAIL_URL_TEMPLATE = "https://www.xiaoheihe.cn/game/{appid}"


class AuthError(Exception):
    """登录凭证缺失或失效。"""
