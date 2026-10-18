# -*- coding: utf-8 -*-
"""AI 精选 / 跨插件调用 / 排版 的测试公共夹具（不联网、不起浏览器）。"""

import datetime as dt
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from core.calendar_core import DayRelease, GameItem  # noqa: E402

# 2026-10-12 是周一（与真实使用时的「本周」对齐）
MONDAY = dt.date(2026, 10, 12)
SATURDAY = dt.date(2026, 10, 17)


def make_week() -> list[DayRelease]:
    """一周 7 天、共 6 款游戏的最小样本。"""
    days = [DayRelease(date=MONDAY + dt.timedelta(days=i)) for i in range(7)]
    days[0].games = [
        GameItem(name="三国志14", tags=["模拟", "策略"], platforms=["pc"],
                 steam_appid=123456, follow_num=2345),
        GameItem(name="某某小游戏", tags=[], platforms=["pc", "console"],
                 steam_appid=999, follow_num=0),
    ]
    days[1].games = [
        GameItem(name="Silksong", tags=["动作", "冒险"], platforms=["pc"],
                 steam_appid=1030300, follow_num=120000),
    ]
    days[3].games = [
        GameItem(name="主机独占", tags=["角色扮演"], platforms=[], game_type="console"),
    ]
    days[5].games = [
        GameItem(name="无标签也无平台", tags=[], platforms=[]),
    ]
    days[6].games = [
        GameItem(name="某 DLC", tags=["动作"], platforms=["pc"], steam_appid=555,
                 follow_num=80),
    ]
    return days


def count_games(days: list[DayRelease]) -> int:
    return sum(len(d.games) for d in days)
