"""小黑盒「游戏发售日历」数据核心。

接口来自 APP 1.3.395（com.max.xiaoheihe）反编译：
    com.max.xiaoheihe.network.HeyBoxService
    - game/release_calendar/game_list             按日窗口（服务端固定窗口，参数被忽略）
    - game/release_calendar/game_list/single_day  单日完整列表（本月日历用这个）
    - game/release_calendar/game_count            每月每天的发售数量（整月覆盖）
    - game/release_calendar/filters               筛选项定义
    - game/get_game_detail/                       单款游戏详情（历史日期的标签只能靠它）

只有 game_list/single_day 与 game_count 是权威数据源：
    * single_day 返回该日全部游戏（实测与 game_count 的每日数量一致）；
    * game_list 只返回「明天起约一周、最多 30 款」的固定窗口，因此不用它做周期统计。

域名 https://api.xiaoheihe.cn，路径无 /bbs/app/api 前缀；
签名复用 Web 端 hkey 算法（core.xhh_api.generate_sign_params），无需 APP 与登录。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from dataclasses import dataclass, field

import httpx

from .config import CALENDAR_API_HOST, AuthError
from .tag_cache import TagCache
from .xhh_api import generate_sign_params

logger = logging.getLogger("astrbot")

API_HOST = CALENDAR_API_HOST
GAME_COUNT_PATH = "/game/release_calendar/game_count"
GAME_LIST_PATH = "/game/release_calendar/game_list"
SINGLE_DAY_PATH = "/game/release_calendar/game_list/single_day"
FILTERS_PATH = "/game/release_calendar/filters"
GAME_DETAIL_PATH = "/game/get_game_detail/"

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))

# 风控：小黑盒接口对突发请求很敏感，请求过密会被直接掐断连接（SSL EOF），
# 因此并发要低、失败要退避重试。
_CONCURRENCY = 3
_RETRY_DELAYS = (2.0, 6.0, 14.0)
_MAX_ATTEMPTS = 4

# 详情接口并发上限（补标签是批量操作，比日历接口略高一点但仍要克制）
_TAG_CONCURRENCY = 4

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 平台类标签（作为「类型」展示时不如玩法标签有信息量，直接丢弃）
_WEAK_TAGS = ("pc", "主机", "手机", "ios", "android", "客户端", "官方平台")

# 展示层的最后兜底：接口连标签都没有时，至少标出游戏平台
_FALLBACK_TAGS = {"pc": "PC", "console": "主机", "mobile": "手机"}

# 详情接口 common_tags 里的营销/状态类标签，不是游戏类型，直接丢弃。
# 注意：独立 / 抢先体验 / 单人 / 在线合作 都是 Steam 真实分类，必须保留。
_NOISE_TAGS = frozenset({
    "心愿单热门", "近期热销", "热销", "热门", "即将推出", "已发售", "预售",
    "新品", "折扣", "史低", "免费", "限时", "推荐", "独家", "特惠",
})

# 「支持中文」「支持手柄」这类平台功能标签同样不是游戏类型
_NOISE_TAG_RE = re.compile(r"^支持.{0,6}$|^兼容.{0,6}$")

# 非游戏条目（影视、周边等）常见的 type
_NON_GAME_TYPES = ("video", "movie", "tv", "anime", "hardware", "goods")


class CalendarError(Exception):
    """发售日历接口调用失败。"""


# ────────────────────────── 数据模型 ──────────────────────────


@dataclass
class GameItem:
    name: str
    tags: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    game_type: str = ""
    steam_appid: int | None = None
    follow_num: int = 0
    expect_num: int = 0

    @property
    def first_tag(self) -> str:
        return self.tags[0] if self.tags else ""

    @property
    def platform_label(self) -> str:
        """平台的中文名，作为没有玩法标签时的兜底。"""
        gt = (self.game_type or "").strip().lower()
        if gt in _FALLBACK_TAGS:
            return _FALLBACK_TAGS[gt]
        if self.platforms:
            return self.platforms[0].upper()
        return ""

    @property
    def display_tag(self) -> str:
        """用于展示的标签：优先玩法标签，其次平台。"""
        return self.first_tag or self.platform_label

    @property
    def tags_text(self) -> str:
        return " / ".join(self.tags[:3]) if self.tags else ""


@dataclass
class DayRelease:
    date: dt.date
    games: list[GameItem] = field(default_factory=list)

    @property
    def label(self) -> str:
        """如「09-14 周一」。"""
        return f"{self.date:%m-%d} {_WEEKDAY_CN[self.date.weekday()]}"

    @property
    def long_label(self) -> str:
        """如「9月14日 周一」。"""
        return f"{self.date.month}月{self.date.day}日 {_WEEKDAY_CN[self.date.weekday()]}"


# ────────────────────────── 核心 ──────────────────────────


class XhhCalendarCore:
    """发售日历抓取核心。"""

    def __init__(self, tag_cache: TagCache | None = None) -> None:
        self._sem = asyncio.Semaphore(_CONCURRENCY)
        self._tag_sem = asyncio.Semaphore(_TAG_CONCURRENCY)
        self._tag_cache = tag_cache or TagCache()

    # ---------- 基础请求 ----------

    @staticmethod
    def _signed_params(path: str, extra: dict | None = None) -> dict:
        params = generate_sign_params(path)
        if extra:
            params.update(extra)
        return params

    async def _request(
        self,
        client: httpx.AsyncClient,
        path: str,
        extra: dict | None = None,
    ) -> dict:
        """带退避重试的 GET，返回响应 JSON。"""
        last_err: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            if attempt:
                await asyncio.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
            try:
                async with self._sem:
                    resp = await client.get(
                        API_HOST + path, params=self._signed_params(path, extra)
                    )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # 网络抖动 / 风控断连 / JSON 解析
                last_err = exc
                logger.debug(
                    f"[XhhCalendar] {path} 第 {attempt + 1} 次请求失败: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            status = payload.get("status")
            if status != "ok":
                msg = payload.get("msg") or "未知错误"
                # 凭证类错误直接抛出，不必重试
                if "登录" in str(msg) or "hkey" in str(msg):
                    raise AuthError(f"小黑盒接口鉴权失败: {msg}")
                last_err = CalendarError(f"{path} 返回 status={status}: {msg}")
                logger.debug(f"[XhhCalendar] {last_err}")
                continue

            return payload.get("result") or {}

        raise CalendarError(f"发售日历接口请求失败: {path} ({last_err})")

    # ---------- 字段解析 ----------

    @staticmethod
    def _clean_tags(raw_tags: list[str]) -> list[str]:
        """过滤噪音标签、去重并保序。日历接口与详情接口共用。"""
        seen: set[str] = set()
        out: list[str] = []
        for t in raw_tags:
            if not isinstance(t, str):
                continue
            tag = t.strip()
            key = tag.lower()
            if not key or key in seen:
                continue
            if key in _WEAK_TAGS or tag in _NOISE_TAGS or _NOISE_TAG_RE.match(tag):
                continue
            seen.add(key)
            out.append(tag)
        return out

    @classmethod
    def _pick_tag(cls, game: dict) -> list[str]:
        """取日历接口给出的玩法标签：hot_tags -> genres。

        历史日期服务端不返回 hot_tags，这里会得到空列表，由 `enrich_tags()`
        走游戏详情接口补齐；展示层再用平台（PC/主机/手机）做最后兜底。
        数据层保持「真实标签」语义，否则补全逻辑会误以为已经有标签了。
        """
        raw_tags = [t.get("desc") for t in (game.get("hot_tags") or []) if t.get("desc")]
        if not raw_tags:
            raw_tags = [g for g in (game.get("genres") or []) if g]
        return cls._clean_tags(raw_tags)

    @classmethod
    def _parse_game(cls, game: dict) -> GameItem | None:
        """把一条游戏记录转为 GameItem；非游戏条目返回 None。"""
        name = (game.get("name") or "").strip()
        if not name:
            return None

        if (game.get("type") or "") in _NON_GAME_TYPES:
            return None

        appid = game.get("steam_appid")
        if not isinstance(appid, int):
            appid = None

        return GameItem(
            name=name,
            tags=cls._pick_tag(game),
            platforms=[p for p in (game.get("platforms") or []) if p],
            game_type=(game.get("game_type") or "").strip(),
            steam_appid=appid,
            follow_num=int(game.get("follow_num") or 0),
            expect_num=int(game.get("expect_num") or 0),
        )

    # ---------- 单日 / 批量 ----------

    async def fetch_day(
        self,
        client: httpx.AsyncClient,
        day: dt.date,
        filters: dict[str, str] | None = None,
    ) -> list[GameItem]:
        """抓取某一天的全部发售游戏（单日接口）。"""
        extra = {"day_timestamp": str(self._day_timestamp(day))}
        if filters:
            extra.update(filters)

        result = await self._request(client, SINGLE_DAY_PATH, extra)
        games = []
        for raw in result.get("game_list") or []:
            item = self._parse_game(raw)
            if item is not None:
                games.append(item)
        return games

    async def fetch_window(
        self,
        client: httpx.AsyncClient,
        day: dt.date,
        filters: dict[str, str] | None = None,
    ) -> dict[dt.date, list[GameItem]]:
        """批量接口：一次拿到从 day 起约一周的发售列表（APP 日历页用的就是它）。

        与单日接口的区别：批量接口的 hot_tags 最完整，因此本周视图优先用它。
        注意服务端只认「当天及以后」，传过去的日期会原样返回今天起的窗口。
        """
        extra = {"day_timestamp": str(self._day_timestamp(day))}
        if filters:
            extra.update(filters)

        result = await self._request(client, GAME_LIST_PATH, extra)
        out: dict[dt.date, list[GameItem]] = {}
        for group in result.get("grouped_game_list") or []:
            ts = group.get("day_timestamp")
            if not ts:
                continue
            games = []
            for raw in group.get("game_list") or []:
                item = self._parse_game(raw)
                if item is not None:
                    games.append(item)
            out[self._ts_to_date(int(ts))] = games
        return out

    async def fetch_month_counts(
        self, client: httpx.AsyncClient
    ) -> dict[dt.date, int]:
        """每天的发售数量（覆盖 24 个月）。"""
        result = await self._request(client, GAME_COUNT_PATH)
        counts: dict[dt.date, int] = {}
        for month in result.get("count_by_month") or []:
            for item in month.get("count_by_day") or []:
                ts = item.get("day_timestamp")
                if not ts:
                    continue
                counts[self._ts_to_date(int(ts))] = int(item.get("count") or 0)
        return counts

    async def fetch_available_filters(self, client: httpx.AsyncClient) -> dict:
        """筛选项定义（filter_hot / filter_platform）。"""
        return await self._request(client, FILTERS_PATH)

    # ---------- 时间工具 ----------

    @staticmethod
    def _day_timestamp(day: dt.date) -> int:
        """接口口径：北京时间当天 0 点。"""
        return int(dt.datetime(day.year, day.month, day.day, tzinfo=BEIJING_TZ).timestamp())

    @staticmethod
    def _ts_to_date(ts: int) -> dt.date:
        return dt.datetime.fromtimestamp(ts, BEIJING_TZ).date()

    @staticmethod
    def today() -> dt.date:
        return dt.datetime.now(BEIJING_TZ).date()

    # ---------- 对外：本周 ----------

    async def fetch_week(self) -> list[DayRelease]:
        """本周（周一起）每天的发售列表。

        数据来源与 APP 日历页一致：
            今天 ~ 本周日 —— 批量接口一次取回（标签最完整）；
            本周里已经过去的日子 —— 逐日补一次单日接口（批量接口不返回它们）。
        """
        today = self.today()
        monday = today - dt.timedelta(days=today.weekday())
        days = [monday + dt.timedelta(days=i) for i in range(7)]

        async with self._client() as client:
            # 批量窗口：以今天为起点，覆盖今天及之后
            try:
                window = await self.fetch_window(client, today)
            except AuthError:
                raise
            except Exception as exc:
                logger.warning(f"[XhhCalendar] 批量窗口抓取失败，回退逐日: {exc}")
                window = {}

            past_days = [d for d in days if d not in window]
            results = await asyncio.gather(
                *(self._safe_fetch_day(client, d) for d in past_days),
                return_exceptions=True,
            ) if past_days else []

        fetched: dict[dt.date, list[GameItem]] = dict(window)
        for day, res in zip(past_days, results):
            fetched[day] = [] if isinstance(res, BaseException) else res

        # 兜底：窗口抓取失败时空的日子，再用批量接口补一次
        missing = [d for d in days if not fetched.get(d)]
        if missing and window:
            logger.debug(f"[XhhCalendar] 以下日期无数据: {missing}")

        releases = [DayRelease(date=d, games=fetched.get(d, [])) for d in days]

        # 历史日期服务端不给 hot_tags，用详情接口补一次（走缓存）
        all_games = [g for day in releases for g in day.games]
        await self.enrich_tags(all_games, limit=40)

        return releases

    async def _safe_fetch_day(
        self, client: httpx.AsyncClient, day: dt.date
    ) -> list[GameItem]:
        try:
            return await self.fetch_day(client, day)
        except AuthError:
            raise
        except Exception as exc:
            logger.debug(f"[XhhCalendar] 单日抓取失败 {day}: {exc}")
            return []

    # ---------- 标签补全（历史日期用） ----------

    async def _fetch_detail_tag(
        self, client: httpx.AsyncClient, appid: int
    ) -> list[str]:
        """从游戏详情接口取一款游戏的玩法标签。

        详情接口的 `common_tags` 里 `type == "simple_tag"` 的 `desc`
        就是玩法标签（与日历接口的 hot_tags 同源），营销类标签会被过滤。
        """
        try:
            async with self._tag_sem:
                result = await self._request(
                    client, GAME_DETAIL_PATH, {"steam_appid": str(appid)}
                )
        except Exception as exc:
            logger.debug(f"[XhhCalendar] 详情接口取标签失败 {appid}: {exc}")
            return []

        raw = [
            t.get("desc")
            for t in (result.get("common_tags") or [])
            if t.get("type") == "simple_tag" and t.get("desc")
        ]
        return self._clean_tags(raw)

    async def enrich_tags(
        self,
        games: list[GameItem],
        limit: int = 60,
    ) -> None:
        """就地补齐缺失的游戏标签。

        只处理「日历接口没给标签、但有 steam_appid」的游戏，并优先命中本地缓存；
        仍未命中的按 `limit` 上限并发拉详情，避免一次查询打太多请求。
        """
        pending: list[GameItem] = []
        for g in games:
            if g.tags or not g.steam_appid:
                continue
            cached = self._tag_cache.get(g.steam_appid)
            if cached:
                g.tags = cached
            else:
                pending.append(g)

        if not pending:
            self._tag_cache.save()
            return

        targets = pending[:limit]
        skipped = len(pending) - len(targets)

        async with self._client() as client:
            results = await asyncio.gather(
                *(self._fetch_detail_tag(client, g.steam_appid) for g in targets),
                return_exceptions=True,
            )

        for game, tags in zip(targets, results):
            if isinstance(tags, BaseException) or not tags:
                continue
            game.tags = tags
            self._tag_cache.put(game.steam_appid, tags)

        self._tag_cache.save()

        if skipped:
            logger.info(
                f"[XhhCalendar] 标签补全达到单次上限 {limit}，"
                f"还有 {skipped} 款未补（下次查询会继续）"
            )

    # ---------- 对外：本月 ----------

    async def fetch_month(
        self, year: int | None = None, month: int | None = None
    ) -> tuple[list[DayRelease], dict[dt.date, int], int]:
        """本月每天的列表 + 完整数量表。

        Returns:
            (每天的发售列表, {日期: 数量}, 本月总数量)

        数量表来自 game_count（整月完整），列表用「批量窗口 + 逐日」组合获取：
        批量接口一次能覆盖约 8 天（且 hot_tags 最全），剩下的日子再逐日补，
        这样请求数从 31 次降到约 24 次。
        对已经过去、接口不再提供明细的日子，列表为空但数量仍在，
        由上层用数量渲染，保证「本月日历」不出现空洞。
        """
        today = self.today()
        year = year or today.year
        month = month or today.month

        first = dt.date(year, month, 1)
        next_month = dt.date(year + (month == 12), (month % 12) + 1, 1)
        day_count = (next_month - first).days
        days = [first + dt.timedelta(days=i) for i in range(day_count)]

        async with self._client() as client:
            counts_task = asyncio.create_task(self.fetch_month_counts(client))

            # 批量窗口：服务端只认「今天及以后」，所以先用今天试一次，
            # 命中本月哪些天就用哪些天，剩下的逐日补。
            fetched: dict[dt.date, list[GameItem]] = {}
            try:
                window = await self.fetch_window(client, today)
                fetched.update({d: g for d, g in window.items() if d in set(days)})
            except Exception as exc:
                logger.debug(f"[XhhCalendar] 本月批量窗口失败: {exc}")

            rest = [d for d in days if d not in fetched]
            day_results = await asyncio.gather(
                *(self._safe_fetch_day(client, d) for d in rest),
                return_exceptions=True,
            )

            try:
                counts = await counts_task
            except Exception as exc:
                logger.warning(f"[XhhCalendar] 获取每月数量失败: {exc}")
                counts = {}

        for day, res in zip(rest, day_results):
            fetched[day] = [] if isinstance(res, BaseException) else res

        releases: list[DayRelease] = []
        for day in days:
            releases.append(DayRelease(date=day, games=fetched.get(day, [])))

        month_total = sum(counts.get(d, 0) for d in days)

        # 本月里已过去的日子同样没有标签，用详情接口补（走缓存，受单次上限保护）
        all_games = [g for day in releases for g in day.games]
        await self.enrich_tags(all_games, limit=80)

        return releases, counts, month_total

    # ---------- HTTP 客户端 ----------

    @staticmethod
    def _client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.xiaoheihe.cn",
                "Referer": "https://www.xiaoheihe.cn/",
            },
            limits=httpx.Limits(max_connections=_CONCURRENCY + 2, max_keepalive_connections=_CONCURRENCY),
        )
