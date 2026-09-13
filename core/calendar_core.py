"""小黑盒「游戏发售日历」数据核心。

接口来自 APP 1.3.395（com.max.xiaoheihe）反编译：
    com.max.xiaoheihe.network.HeyBoxService
    - game/release_calendar/game_list             按日窗口（服务端固定窗口，参数被忽略）
    - game/release_calendar/game_list/single_day  单日完整列表（本月日历用这个）
    - game/release_calendar/game_count            每月每天的发售数量（整月覆盖）
    - game/release_calendar/filters               筛选项定义

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
from dataclasses import dataclass, field

import httpx

from .config import CALENDAR_API_HOST, AuthError
from .xhh_api import generate_sign_params

logger = logging.getLogger("astrbot")

API_HOST = CALENDAR_API_HOST
GAME_COUNT_PATH = "/game/release_calendar/game_count"
GAME_LIST_PATH = "/game/release_calendar/game_list"
SINGLE_DAY_PATH = "/game/release_calendar/game_list/single_day"
FILTERS_PATH = "/game/release_calendar/filters"

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))

# 风控：小黑盒接口对突发请求很敏感，请求过密会被直接掐断连接（SSL EOF），
# 因此并发要低、失败要退避重试。
_CONCURRENCY = 3
_RETRY_DELAYS = (2.0, 6.0, 14.0)
_MAX_ATTEMPTS = 4

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 平台类标签（作为「类型」展示时不如玩法标签有信息量，优先级最低）
_WEAK_TAGS = ("pc", "主机", "手机", "ios", "android", "客户端", "官方平台")

# game_type 回退时的中文名
_GAME_TYPE_CN = {"pc": "PC", "console": "主机", "mobile": "手机"}

# 非游戏条目（影视、周边等）常见的 type
_NON_GAME_TYPES = ("video", "movie", "tv", "anime", "hardware", "goods")


class CalendarError(Exception):
    """发售日历接口调用失败。"""


# ────────────────────────── 数据模型 ──────────────────────────


@dataclass
class GameItem:
    name: str
    tags: list[str] = field(default_factory=list)
    image: str = ""
    platforms: list[str] = field(default_factory=list)
    game_type: str = ""
    steam_appid: int | None = None
    follow_num: int = 0
    expect_num: int = 0

    @property
    def first_tag(self) -> str:
        return self.tags[0] if self.tags else ""

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

    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(_CONCURRENCY)

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
    def _pick_tag(game: dict) -> list[str]:
        """取玩法标签：hot_tags -> genres -> game_type（主机/PC/手机）。

        少量条目（多为主机独占）没有 hot_tags，此时退回 game_type，
        避免「类型」这一列整片空白。
        """
        raw_tags = [t.get("desc") for t in (game.get("hot_tags") or []) if t.get("desc")]
        if not raw_tags:
            raw_tags = [g for g in (game.get("genres") or []) if g]
        strong = [t for t in raw_tags if t.strip().lower() not in _WEAK_TAGS]
        tags = strong or raw_tags

        if not tags and game.get("game_type"):
            gt = str(game["game_type"]).strip()
            tags = [_GAME_TYPE_CN.get(gt.lower(), gt)]

        # 去重并保序
        seen: set[str] = set()
        out: list[str] = []
        for t in tags:
            key = t.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(t.strip())
        return out

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
            image=(game.get("image") or "").strip(),
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

        return [DayRelease(date=d, games=fetched.get(d, [])) for d in days]

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

    # ---------- 对外：本月 ----------

    async def fetch_month(
        self, year: int | None = None, month: int | None = None
    ) -> tuple[list[DayRelease], dict[dt.date, int], int]:
        """本月每天的列表 + 完整数量表。

        Returns:
            (每天的发售列表, {日期: 数量}, 本月总数量)

        数量表来自 game_count（整月完整），列表来自 single_day（能取到就有名称）。
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
            day_results = await asyncio.gather(
                *(self._safe_fetch_day(client, d) for d in days),
                return_exceptions=True,
            )
            try:
                counts = await counts_task
            except Exception as exc:
                logger.warning(f"[XhhCalendar] 获取每月数量失败: {exc}")
                counts = {}

        releases: list[DayRelease] = []
        for day, res in zip(days, day_results):
            games = [] if isinstance(res, BaseException) else res
            releases.append(DayRelease(date=day, games=games))

        month_total = sum(counts.get(d, 0) for d in days)
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


# ────────────────────────── 图片拼接 ──────────────────────────


class CoverCollage:
    """把多个游戏封面按顺序拼成一张总览图（不渲染文字，文字由 Markdown 承载）。"""

    def __init__(self, cols: int = 3, cell_w: int = 400, cell_h: int = 187, gap: int = 6):
        self.cols = cols
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.gap = gap

    async def build(self, games: list[GameItem]) -> bytes | None:
        """并发下载封面并拼接，返回 PNG 字节；无可下载封面时返回 None。"""
        urls = [g.image for g in games if g.image.startswith(("http://", "https://"))]
        if not urls:
            return None

        urls = urls[: self.cols * 8]  # 最多 24 张（3 列 8 行），避免图过长
        images = await asyncio.gather(*(self._download(u) for u in urls))
        images = [im for im in images if im is not None]
        if not images:
            return None

        from PIL import Image as PILImage

        cells = [self._fit(im) for im in images]
        rows = (len(cells) + self.cols - 1) // self.cols
        canvas_w = self.cols * self.cell_w + self.gap * (self.cols - 1)
        canvas_h = rows * self.cell_h + self.gap * (rows - 1)

        canvas = PILImage.new("RGB", (canvas_w, canvas_h), (28, 28, 32))
        for idx, im in enumerate(cells):
            r, c = divmod(idx, self.cols)
            canvas.paste(im, (c * (self.cell_w + self.gap), r * (self.cell_h + self.gap)))

        from io import BytesIO

        buf = BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _fit(self, img):
        """等比缩放后居中裁剪到统一格子。"""
        from PIL import Image as PILImage

        img = img.convert("RGB")
        ratio = max(self.cell_w / img.width, self.cell_h / img.height)
        new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        img = img.resize(new_size, PILImage.LANCZOS)
        left = (img.width - self.cell_w) // 2
        top = (img.height - self.cell_h) // 2
        return img.crop((left, top, left + self.cell_w, top + self.cell_h))

    @staticmethod
    async def _download(url: str):
        from io import BytesIO

        from PIL import Image as PILImage

        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                return PILImage.open(BytesIO(resp.content))
        except Exception as exc:
            logger.debug(f"[XhhCalendar] 封面下载失败 {url}: {exc}")
            return None
