"""游戏标签缓存。

日历接口对**已过去**的日期返回 `hot_tags: null`，这些日期的标签只能靠
`/game/get_game_detail/` 的 `common_tags` 补齐。该接口一次只能查一款游戏，
所以必须缓存，避免每次查询都重复请求。

缓存文件：`tag_cache.json`（默认与插件同目录，可用环境变量覆盖）
格式：`{"<steam_appid>": {"tags": ["模拟", "管理"], "ts": 1789000000}}`
"""

from __future__ import annotations

import json
import logging
import os
import time

from .config import TAG_CACHE_FILE

logger = logging.getLogger("astrbot")

DEFAULT_TTL = 7 * 24 * 3600  # 7 天：发售前后标签基本稳定


def _default_path() -> str:
    # 优先用环境变量，便于容器/测试环境重定向
    return os.environ.get("XHH_TAG_CACHE") or TAG_CACHE_FILE


class TagCache:
    """steam_appid -> 标签列表 的持久化缓存。"""

    def __init__(self, path: str | None = None, ttl: int = DEFAULT_TTL):
        self.path = path or _default_path()
        self.ttl = ttl
        self._data: dict[str, dict] = {}
        self._dirty = False
        self._load()

    # ---------- 读写 ----------

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = raw
        except FileNotFoundError:
            self._data = {}
        except Exception as exc:
            logger.warning(f"[XhhCalendar] 读取标签缓存失败，忽略: {exc}")
            self._data = {}

    def save(self) -> None:
        """写回磁盘；失败只记日志，不影响主流程。"""
        if not self._dirty:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
        except Exception as exc:
            logger.warning(f"[XhhCalendar] 写入标签缓存失败: {exc}")

    # ---------- 查询 ----------

    def get(self, appid: int | None) -> list[str] | None:
        """命中且未过期时返回标签列表，否则 None。"""
        if not appid:
            return None
        rec = self._data.get(str(appid))
        if not isinstance(rec, dict):
            return None
        if time.time() - float(rec.get("ts") or 0) > self.ttl:
            return None
        tags = rec.get("tags")
        return list(tags) if isinstance(tags, list) and tags else None

    def put(self, appid: int | None, tags: list[str]) -> None:
        if not appid or not tags:
            return
        self._data[str(appid)] = {"tags": tags, "ts": int(time.time())}
        self._dirty = True

    def missing(self, appids: list[int]) -> list[int]:
        """返回其中没有有效缓存的 appid。"""
        return [a for a in appids if self.get(a) is None]

    def dump(self) -> dict:
        return dict(self._data)
