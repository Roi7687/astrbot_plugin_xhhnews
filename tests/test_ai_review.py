# -*- coding: utf-8 -*-
"""AI 精选（core/ai_review.py）单元测试：只覆盖编排逻辑，不发网络、不起浏览器。

真实 DeepSeek 调用由 research/verify_ai_review.py 负责（端到端）。
"""

import asyncio
import unittest

from tests.fixtures import PLUGIN_DIR  # noqa: F401  （确保插件目录在 sys.path）
from core.ai_review import (
    AI_DATA_PLACEHOLDER,
    AI_REVIEW_PROMPT,
    ask_ai_review,
    build_ai_prompt,
    clean_answer,
)
from core.config import AI_REVIEW_MAX_CHARS, AI_REVIEW_MAX_INPUT_CHARS, AI_REVIEW_PLUGIN

DIGEST = "【本周范围】2026-10-12 → 2026-10-18\n1. Silksong ｜ 10-13 周二 ｜ 动作 ｜ PC ｜ AppID 1030300"


def _run(coro):
    return asyncio.run(coro)


class FakeStar:
    def __init__(self, *, answer="AI 精选正文", created=False, exc=None, delay=0.0):
        self.answer, self.created, self.exc, self.delay = answer, created, exc, delay
        self.seen = None

    async def _send_query(self, prompt, images):
        self.seen = (prompt, images)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.created, self.answer


class FakeMeta:
    def __init__(self, inst, activated=True):
        self.star_cls, self.activated, self.name = inst, activated, AI_REVIEW_PLUGIN


class FakeContext:
    def __init__(self, meta=None, exc=None):
        self.meta, self.exc = meta, exc

    def get_registered_star(self, name):
        if self.exc:
            raise self.exc
        return self.meta if name == AI_REVIEW_PLUGIN else None


class TestPrompt(unittest.TestCase):
    """用户定稿版提示词：任务边界 / 角色目标 / 入选标准 / 联网核验规则 / 防幻觉 / 输出格式。"""

    def test_data_placeholder_is_filled(self):
        self.assertIn(AI_DATA_PLACEHOLDER, AI_REVIEW_PROMPT)
        merged = build_ai_prompt(DIGEST)
        self.assertNotIn(AI_DATA_PLACEHOLDER, merged)
        self.assertTrue(merged.rstrip().endswith(DIGEST))
        self.assertIn("待分析数据", merged)

    def test_task_boundary_is_highest_priority(self):
        """aisearch 是持久化会话，提示词最高优先级必须是忽略此前上下文、不问问题、不输出思考。"""
        self.assertIn("# 任务边界（最高优先级）", AI_REVIEW_PROMPT)
        self.assertIn("忽略此前所有对话上下文", AI_REVIEW_PROMPT)
        self.assertIn("不要向我提问、不要输出思考过程", AI_REVIEW_PROMPT)
        self.assertIn("不要任何开场白与结束语", AI_REVIEW_PROMPT)
        self.assertLess(
            AI_REVIEW_PROMPT.index("任务边界"),
            AI_REVIEW_PROMPT.index("角色与目标"),
        )

    def test_role_and_pick_count(self):
        self.assertIn("资深游戏评测编辑兼核心老玩家", AI_REVIEW_PROMPT)
        self.assertIn("最终精选 4~8 款，宁缺毋滥", AI_REVIEW_PROMPT)

    def test_selection_criteria(self):
        """质量优先 / 3A 大厂 IP / 高口碑独立 / 一票否决首发翻车。"""
        for key in ("质量与好评优先", "重磅 3A / 知名大厂 / 经典 IP 新作",
                    "小黑盒关注数通常 > 3万", "口碑爆棚的独立佳作", "一票否决",
                    "首发彻底翻车", "Steam 好评率 < 70%"):
            self.assertIn(key, AI_REVIEW_PROMPT)
        self.assertIn("Steam 好评率 ≥ 80% 或 MC/OC 媒体均分 ≥ 80", AI_REVIEW_PROMPT)

    def test_web_search_rules(self):
        self.assertIn("联网检索与核验规则（硬性要求）", AI_REVIEW_PROMPT)
        for key in ("10~15 款候选", "≥ 10,000", "4,000 ~ 10,000",
                    "Steam AppID", "英文原名", "Metacritic / OpenCritic",
                    "平台抓取错乱或碰瓷游戏"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_special_identity_rules(self):
        """EA 转 1.0 / 重制移植 DLC / 周末刚发售样本少，都要特殊标注。"""
        for key in ("EA 转 1.0 正式版", "1.0正式版", "重制 / 移植 / DLC",
                    "周末刚发售/未解锁新作", "刚解锁样本少"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_anti_hallucination_rules(self):
        self.assertIn("数据防幻觉铁律", AI_REVIEW_PROMPT)
        self.assertIn("严禁编造评分", AI_REVIEW_PROMPT)
        self.assertIn("严禁输出 `53%~66%` 这类模糊区间", AI_REVIEW_PROMPT)
        self.assertIn("只标注原始评分平台", AI_REVIEW_PROMPT)
        self.assertIn("严禁将二手资讯网", AI_REVIEW_PROMPT)
        self.assertIn("简中", AI_REVIEW_PROMPT)                 # 全球/简中评价差 >15% 要点明
        self.assertIn("15%", AI_REVIEW_PROMPT)

    def test_output_format(self):
        """禁止一级标题/开场白/总结语/避雷板块；只输出入选列表 + 四要素排版。"""
        for key in ("禁止**输出一级标题（`#`）", "仅输出最终入选的游戏列表",
                    "综合推荐度（质量+关注度）", "发售日期：MM-DD",
                    "类型与玩法", "评价与反馈", "Steam 好评率 xx%［约 N 篇评测］"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_empty_digest(self):
        self.assertNotIn(AI_DATA_PLACEHOLDER, build_ai_prompt(""))

    def test_long_digest_is_truncated(self):
        long_digest = "\n".join(f"{i}. 游戏{i}" for i in range(2000))
        self.assertGreater(len(long_digest), AI_REVIEW_MAX_INPUT_CHARS)
        merged = build_ai_prompt(long_digest)
        self.assertIn("清单过长，已截断", merged)
        self.assertNotIn(AI_DATA_PLACEHOLDER, merged)
        self.assertLess(len(merged), len(AI_REVIEW_PROMPT) + AI_REVIEW_MAX_INPUT_CHARS + 100)


class TestCleanAnswer(unittest.TestCase):
    def test_normalizes_newlines_and_blank_lines(self):
        self.assertEqual(clean_answer("  a\r\n\r\n\r\nb \r\n"), "a\n\nb")

    def test_empty(self):
        for value in ("", "   ", None, "\r\n\r\n"):
            self.assertEqual(clean_answer(value), "")

    def test_length_capped(self):
        text = clean_answer("很" * (AI_REVIEW_MAX_CHARS + 200))
        self.assertEqual(len(text), AI_REVIEW_MAX_CHARS + 1)      # 截断后带省略号


class TestAskAiReview(unittest.TestCase):
    def test_success_prompt_contains_digest_and_no_images(self):
        inst = FakeStar(answer="  推荐 Silksong  \r\n\r\n\r\n值得一玩。 ")
        text = _run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST))
        self.assertEqual(text, "推荐 Silksong\n\n值得一玩。")
        prompt, images = inst.seen
        self.assertIn(DIGEST, prompt)                       # 清单确实传过去了
        self.assertIn("资深游戏评测编辑兼核心老玩家", prompt)   # 要求在前
        self.assertLess(prompt.index("资深游戏评测编辑兼核心老玩家"), prompt.index(DIGEST))
        self.assertEqual(images, [])                        # 不带图片

    def test_created_conversation_flag_is_fine(self):
        inst = FakeStar(answer="新会话里的推荐", created=True)
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST)),
                         "新会话里的推荐")

    def test_resets_peer_idle_timer(self):
        class Conv:
            local_id = 3

        class Session:
            current_conversation = Conv()

        class Inst(FakeStar):
            def __init__(self):
                super().__init__()
                self.session = Session()
                self.armed = []

            def _arm_idle_timer(self, local_id):
                self.armed.append(local_id)

        inst = Inst()
        _run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST))
        self.assertEqual(inst.armed, [3])

    def test_idle_timer_absence_is_ignored(self):
        inst = FakeStar()
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST)),
                         "AI 精选正文")

    def test_answer_length_capped(self):
        inst = FakeStar(answer="很" * (AI_REVIEW_MAX_CHARS + 500))
        text = _run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST))
        self.assertEqual(len(text), AI_REVIEW_MAX_CHARS + 1)

    # ── 降级：任何异常都不能抛给调用方 ──

    def test_empty_digest_skips(self):
        inst = FakeStar()
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), "   ")), "")
        self.assertIsNone(inst.seen)

    def test_no_context(self):
        self.assertEqual(_run(ask_ai_review(None, DIGEST)), "")

    def test_plugin_not_installed(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(None), DIGEST)), "")

    def test_plugin_inactive(self):
        inst = FakeStar()
        self.assertEqual(
            _run(ask_ai_review(FakeContext(FakeMeta(inst, activated=False)), DIGEST)), "")

    def test_star_cls_none(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(None)), DIGEST)), "")

    def test_instance_without_send_query(self):
        class Bad:
            pass

        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(Bad())), DIGEST)), "")

    def test_registry_raises(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(exc=RuntimeError("boom")), DIGEST)), "")

    def test_peer_raises_is_swallowed(self):
        inst = FakeStar(exc=RuntimeError("AuthError: 未登录"))
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST)), "")

    def test_timeout_returns_empty(self):
        inst = FakeStar(answer="来不及了", delay=0.3)
        self.assertEqual(
            _run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST, timeout=0.05)), "")

    def test_empty_answer(self):
        for answer in ("", "   ", None):
            inst = FakeStar(answer=answer)
            self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), DIGEST)), "")

    def test_unexpected_return_type_logs_and_returns_empty(self):
        class Weird:
            async def _send_query(self, prompt, images):
                return 42

        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(Weird())), DIGEST)), "")


if __name__ == "__main__":
    unittest.main()
