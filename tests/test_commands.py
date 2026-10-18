# -*- coding: utf-8 -*-
"""指令面守卫测试：插件对外只暴露 /hbnews 与 /hbhelp 两个指令。

不 import main.py（避免拉起 AstrBot 运行时），直接扫源码里的 `@filter.command(...)`：
- 恰好两个指令：hbnews、hbhelp；
- 不允许额外 alias（本轮需求是「只保留两个指令」）；
- 已下线的 hbweek / hbmonth / hbreview 不得再出现在命令与按钮里；
- 帮助文本必须同时介绍两个指令。
"""

import re
import unittest

from tests.fixtures import PLUGIN_DIR

MAIN_PY = PLUGIN_DIR / "main.py"
SOURCE = MAIN_PY.read_text(encoding="utf-8")

COMMAND_RE = re.compile(r'@filter\.command\(\s*"([^"]+)"\s*(,\s*alias\s*=\s*\{([^}]*)\})?\s*\)')
EXPECTED_COMMANDS = {"hbnews", "hbhelp"}
REMOVED_COMMANDS = ("hbweek", "hbmonth", "hbreview", "hbtop")


class TestCommandSurface(unittest.TestCase):
    def test_exactly_two_commands(self):
        commands = {m.group(1) for m in COMMAND_RE.finditer(SOURCE)}
        self.assertEqual(commands, EXPECTED_COMMANDS)

    def test_no_aliases(self):
        """只保留两个指令，不额外挂别名。"""
        for match in COMMAND_RE.finditer(SOURCE):
            self.assertIsNone(match.group(3), f"{match.group(1)} 不应有 alias")

    def test_removed_commands_are_gone(self):
        for name in REMOVED_COMMANDS:
            self.assertNotIn(f"/{name}", SOURCE, f"源码里仍残留旧指令 /{name}")
            self.assertNotIn(f'command("{name}"', SOURCE)

    def test_help_mentions_both_commands(self):
        help_block = SOURCE[SOURCE.index('def help_command'):SOURCE.index('# ── 内部工具 ──')]
        self.assertIn("/hbnews", help_block)
        self.assertIn("/hbhelp", help_block)

    def test_news_handler_uses_ai_review(self):
        news_block = SOURCE[SOURCE.index('def news_command'):SOURCE.index('def help_command')]
        self.assertIn("ask_ai_review", news_block)
        self.assertIn("format_week_review_markdown", news_block)

    def test_news_buttons_only_reference_live_commands(self):
        for btn_cmd in re.findall(r'\("([^"]*)",\s*"(/[^"]+)"\)', SOURCE):
            self.assertIn(btn_cmd[1], {"/hbnews", "/hbhelp"}, f"键盘按钮指向了无效指令 {btn_cmd}")

    def test_register_version_matches_metadata(self):
        meta = (PLUGIN_DIR / "metadata.yaml").read_text(encoding="utf-8")
        meta_version = re.search(r"^version:\s*v?([\d.]+)", meta, re.M).group(1)
        register_version = re.search(r'@register\([^)]*"([\d.]+)"\)', SOURCE).group(1)
        self.assertEqual(meta_version, register_version)


if __name__ == "__main__":
    unittest.main()
