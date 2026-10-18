"""发售日历的文本格式化（Markdown）。

排版口径：
    本周 —— 每天列出「游戏名 + 类型标签」；
    本月 —— 每天只列「游戏名 + 第一个标签」；
    AI 精选 —— 喂给模型的紧凑清单（`format_week_digest`，多给 AppID/关注数等
              玩家可见文本里没有的锚点）+ AI 返回正文的最终排版
              （`format_week_review_markdown`）。
"""

from __future__ import annotations

import datetime as dt

from .calendar_core import BEIJING_TZ, DayRelease, GameItem

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 接口给的平台标识（多为英文小写）→ 给 AI/用户看的规范名。
# 日历接口目前几乎都返回 steam，规范成 PC 避免清单里一列全是 "STEAM"。
_PLATFORM_ALIASES = {
    "steam": "PC", "pc": "PC", "windows": "PC",
    "console": "主机", "xbox": "Xbox", "xboxone": "Xbox", "xbox_series": "Xbox",
    "ps": "PlayStation", "ps4": "PlayStation", "ps5": "PlayStation",
    "playstation": "PlayStation", "switch": "Switch", "nintendo": "Switch",
    "mobile": "手机", "ios": "手机", "android": "手机",
    "mac": "Mac", "macos": "Mac", "linux": "Linux",
}


def _platform_name(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _PLATFORM_ALIASES.get(key) or (raw or "").strip().upper()


def _platform_text(game: GameItem) -> str:
    """平台文本：优先接口给的 platforms，其次 game_type 兜底。"""
    if game.platforms:
        names = [_platform_name(p) for p in game.platforms if p]
        if names:
            return "/".join(dict.fromkeys(names))     # 去重且保序
    return game.platform_label or "—"


def _tag_suffix(game: GameItem) -> str:
    """统一的标签后缀：`标签`（没有标签时为空）。"""
    tag = game.display_tag
    return f"　`{tag}`" if tag else ""


def _join_games(games: list[GameItem], *, with_tags: bool = True) -> str:
    """把游戏列表拼成一行行「名称+标签」。"""
    parts = []
    for g in games:
        tag = g.display_tag if with_tags else ""
        parts.append(f"{g.name} `{tag}`" if tag else g.name)
    return "、".join(parts)


def format_week_markdown(days: list[DayRelease], today: dt.date | None = None) -> str:
    """本周发售日历。"""
    if not days:
        return "📅 暂无本周发售数据。"

    today = today or dt.datetime.now(BEIJING_TZ).date()
    first, last = days[0].date, days[-1].date
    total = sum(len(d.games) for d in days)

    lines = [f"# 🎮 本周游戏发售日历（{first:%m-%d} ~ {last:%m-%d}）\n"]
    lines.append(f"> 共 **{total}** 款新游 · 数据来自小黑盒\n")

    for day in days:
        header = f"## {day.long_label}"
        if day.date == today:
            header += "　**今天**"
        lines.append(header + "\n")

        if not day.games:
            lines.append("_暂无发售_\n")
            continue

        for g in day.games:
            lines.append(f"- {g.name}{_tag_suffix(g)}\n")
        lines.append("")

    return "".join(lines)


def format_month_markdown(
    days: list[DayRelease],
    counts: dict[dt.date, int],
    total: int,
    year: int,
    month: int,
    today: dt.date | None = None,
) -> str:
    """本月发售日历（简表：名称 + 第一个标签）。"""
    today = today or dt.datetime.now(BEIJING_TZ).date()

    lines = [f"# 🗓️ {year}年{month}月游戏发售日历\n"]
    lines.append(f"> 本月共 **{total}** 款新游 · 数据来自小黑盒\n")

    # 概览：按周分组，标出每天几款
    lines.append("## 📊 本月概览\n")
    week_line: list[str] = []
    for day in days:
        n = counts.get(day.date, 0)
        cell = f"{day.date.day}日:{n}" if n else f"{day.date.day}日-"
        week_line.append(cell)
        if len(week_line) == 7 or day is days[-1]:
            lines.append("　".join(week_line) + "\n")
            week_line = []
    lines.append("")

    # 明细：有名称就列名称（+ 首个标签），只有数量就退化为数量
    detailed = [d for d in days if d.games]
    if detailed:
        lines.append("## 🎮 每日发售\n")
        for day in detailed:
            mark = "　**今天**" if day.date == today else ""
            lines.append(f"### {day.long_label}（{len(day.games)}款）{mark}\n")
            lines.append(_join_games(day.games, with_tags=True) + "\n\n")

    # 接口对已过去的日期不再提供明细，只给数量
    counted_only = [
        d for d in days
        if not d.games and counts.get(d.date, 0) > 0 and d.date < today
    ]
    if counted_only:
        lines.append("## 📌 本月早些时候（仅统计）\n")
        lines.append(
            "、".join(f"{d.date.day}日 {counts[d.date]}款" for d in counted_only) + "\n"
        )

    no_data = [d for d in days if not d.games and counts.get(d.date, 0) == 0]
    if len(no_data) == len(days):
        lines.append("\n_本月暂无发售数据。_")

    return "".join(lines)


# ────────────────────────── AI 精选 ──────────────────────────


def format_week_digest(days: list[DayRelease], today: dt.date | None = None) -> str:
    """把本周发售列表拼成喂给 AI 的紧凑清单（「AI 可见」的超集）。

    比玩家看到的周历多给三类信息，都是帮模型联网检索的锚点：
        - **Steam AppID**：中文译名搜不到时最可靠的定位方式；
        - **平台**：区分 PC / 主机 / 手机，避免推荐错平台；
        - **小黑盒关注数**：本周热度先验，用来决定优先核验哪几款。
    """
    if not days:
        return ""

    today = today or dt.datetime.now(BEIJING_TZ).date()
    first, last = days[0].date, days[-1].date
    total = sum(len(d.games) for d in days)

    lines = [
        f"【本周范围】{first:%Y-%m-%d}（周一）→ {last:%Y-%m-%d}（周日），"
        f"今天是 {today:%Y-%m-%d}（{_WEEKDAY_CN[today.weekday()]}）",
        f"【统计】本周共 {total} 款新游，按发售日排列",
        "【清单】（格式：序号. 名称 ｜ 发售日 ｜ 玩法标签 ｜ 平台 ｜ 小黑盒关注数 ｜ Steam AppID）",
    ]

    index = 0
    for day in days:
        for game in day.games:
            index += 1
            cols = [
                game.name,
                f"{day.date:%m-%d} {_WEEKDAY_CN[day.date.weekday()]}",
                game.tags_text or "—",
                _platform_text(game),
            ]
            if game.follow_num > 0:
                cols.append(f"关注 {game.follow_num}")
            if game.steam_appid:
                cols.append(f"AppID {game.steam_appid}")
            lines.append(f"{index}. " + " ｜ ".join(cols))

    return "\n".join(lines)


def format_week_review_markdown(review: str) -> str:
    """AI 精选结果排版：**原样输出**模型正文。

    提示词（用户定稿版）已严格规定输出格式：只输出入选游戏列表，禁止一级标题、
    开场白、总结语、避雷板块。这里**不再加标题、范围行与脚注**，保证版式完全按
    提示词走；想改观感只改提示词，不用动代码。
    """
    return (review or "").strip()


def format_week_review_fallback(
    days: list[DayRelease],
    today: dt.date | None = None,
) -> str:
    """AI 不可用时的降级输出：完整周历 + 一句原因说明（主功能不受影响）。"""
    text = format_week_markdown(days, today)
    return (
        text
        + "\n> ⚠️ AI 精选暂不可用（联网核验插件未就绪或超时），"
        "以上为本周完整日历。\n"
    )
