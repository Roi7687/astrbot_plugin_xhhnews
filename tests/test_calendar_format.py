# -*- coding: utf-8 -*-
"""AI 精选排版（core/calendar_format.py 新增函数）单元测试。"""

import unittest

from tests.fixtures import MONDAY, SATURDAY, count_games, make_week
from core.calendar_format import (
    format_week_digest,
    format_week_markdown,
    format_week_review_fallback,
    format_week_review_markdown,
)


class TestWeekDigest(unittest.TestCase):
    def setUp(self):
        self.days = make_week()
        self.digest = format_week_digest(self.days, SATURDAY)

    def test_header_has_range_today_and_total(self):
        self.assertIn("2026-10-12（周一）", self.digest)
        self.assertIn("2026-10-18（周日）", self.digest)
        self.assertIn("今天是 2026-10-17（周六）", self.digest)
        self.assertIn(f"本周共 {count_games(self.days)} 款新游", self.digest)

    def test_every_game_listed_in_order(self):
        names = ["三国志14", "某某小游戏", "Silksong", "主机独占", "无标签也无平台", "某 DLC"]
        positions = [self.digest.index(n) for n in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("6. 某 DLC", self.digest)

    def test_ai_only_fields_are_included(self):
        """AppID / 平台 / 关注数是「AI 可见、玩家可见里没有」的检索锚点。"""
        self.assertIn("AppID 1030300", self.digest)         # Silksong 的 AppID
        self.assertIn("关注 2345", self.digest)             # 关注数
        self.assertIn("PC/主机", self.digest)               # 某某小游戏的平台（已规范化）
        self.assertIn("关注 120000", self.digest)

    def test_missing_fields_degrade(self):
        self.assertIn("无标签也无平台 ｜ 10-17 周六 ｜ — ｜ —", self.digest)
        self.assertIn("主机独占 ｜ 10-15 周四 ｜ 角色扮演 ｜ 主机", self.digest)

    def test_empty_days(self):
        self.assertEqual(format_week_digest([], SATURDAY), "")


class TestReviewMarkdown(unittest.TestCase):
    def test_output_is_verbatim_model_text(self):
        """定稿提示词已规定版式：插件不再加标题/范围/脚注，原样输出。"""
        review = (
            "**1. 〈雾锁王国 Enshrouded〉｜ 发售日期：10-15（PC/PS5，1.0正式版）**\n"
            "- **类型与玩法**：体素生存建造 + 开放世界探索，抓钩滑翔手感极好。\n"
            "- **评价与反馈**：Steam 好评率 85%［约 9.5 万篇评测］｜ MC 89［9 家媒体］。"
        )
        text = format_week_review_markdown(review)
        self.assertEqual(text, review.strip())
        self.assertNotIn("# ", text)                    # 不额外加一级标题
        self.assertNotIn("AI 联网核验生成", text)        # 不额外加脚注

    def test_empty_review(self):
        self.assertEqual(format_week_review_markdown(""), "")
        self.assertEqual(format_week_review_markdown(None), "")
        self.assertEqual(format_week_review_markdown("  \r\n "), "")


class TestReviewFallback(unittest.TestCase):
    def test_fallback_contains_full_calendar_and_note(self):
        days = make_week()
        text = format_week_review_fallback(days, SATURDAY)
        self.assertEqual(text.count("本周游戏发售日历"), 1)
        self.assertIn(format_week_markdown(days, SATURDAY).strip()[:40], text)
        self.assertIn("AI 精选暂不可用", text)
        for game in ("三国志14", "Silksong", "某 DLC"):
            self.assertIn(game, text)


if __name__ == "__main__":
    unittest.main()
