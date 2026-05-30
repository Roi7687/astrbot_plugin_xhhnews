import json
import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTH_STATE_FILE = os.path.join(PLUGIN_DIR, "auth_state.json")
QR_FILE = os.path.join(PLUGIN_DIR, "qrcode.png")
SUBSCRIBE_FILE = os.path.join(PLUGIN_DIR, "subscriptions.json")

COMMUNITY_URL = "https://www.xiaoheihe.cn/app/bbs/home"
TOPIC_URL_TEMPLATE = "https://www.xiaoheihe.cn/app/topic/link/{topic_id}"


class AuthError(Exception):
    """未找到登录凭证或凭证已失效"""
    pass


def load_subscriptions() -> dict:
    """加载订阅数据，格式：{"group_id": {"topic_id": "topic_name", ...}}"""
    if os.path.exists(SUBSCRIBE_FILE):
        with open(SUBSCRIBE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 兼容旧格式：将 list 转为 dict
            for k, v in data.items():
                if isinstance(v, list):
                    data[k] = {tid: "" for tid in v}
            return data
    return {}


def save_subscriptions(data: dict):
    """保存订阅数据"""
    with open(SUBSCRIBE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
