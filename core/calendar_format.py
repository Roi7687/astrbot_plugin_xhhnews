"""发售日历的文本格式化（Markdown）。

排版口径：
    本周 —— 每天列出「游戏名 + 类型标签」，封面图另拼成一张总览图发送；
    本月 —— 每天只列「游戏名 + 第一个标签」，不发送图片。
"""

from __future__ import annotations

import datetime as dt

from .calendar_core import BEIJING_TZ, DayRelease, GameItem

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


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
