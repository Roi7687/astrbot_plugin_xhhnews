"""路径、接口常量与共用异常。"""

import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 游戏标签缓存（历史日期补标签用）
TAG_CACHE_FILE = os.path.join(PLUGIN_DIR, "tag_cache.json")

# 发售日历接口（详见 DEVELOPMENT.md）
CALENDAR_API_HOST = "https://api.xiaoheihe.cn"
CALENDAR_PAGE_URL = "https://www.xiaoheihe.cn/game/publish_calendar"
GAME_DETAIL_URL_TEMPLATE = "https://www.xiaoheihe.cn/game/{appid}"

# ── AI 精选（跨插件调用 astrbot_plugin_aisearch，详见 ASTRBOT_CROSS_PLUGIN_CALL.md）──
# 对方插件名以 metadata.yaml 的 name 为准；改版时只需改这三项。
AI_REVIEW_ENABLED = True
AI_REVIEW_PLUGIN = "astrbot_plugin_aisearch"
AI_REVIEW_METHOD = "_send_query"      # 签名：async (prompt: str, images: list) -> (created, answer)
AI_REVIEW_TIMEOUT = 180.0             # 等对方回复的上限（秒）。浏览器自动化 + 联网搜索通常 30~90s
AI_REVIEW_MAX_CHARS = 2800            # AI 正文上限（定稿提示词要 4~8 款、每款两段，留足空间；QQ 单条消息有限）
AI_REVIEW_MAX_INPUT_CHARS = 4000      # 喂给 AI 的「本周新游清单」最大长度（超出截断）
AI_REVIEW_PROGRESS_HINT = True        # 等待期间先发一条「正在核验…」提示（避免长时间无响应）


class AuthError(Exception):
    """登录凭证缺失或失效。"""
