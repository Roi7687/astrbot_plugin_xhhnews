# -*- coding: utf-8 -*-
"""跨插件调用封装（core/peer_plugin.py）的单元测试：不发网络、不起浏览器。

覆盖 ASTRBOT_CROSS_PLUGIN_CALL.md 第 8 节要求的分支：
成功 / 未安装 / 未激活 / star_cls 为空 / 没有目标方法 / 对方抛异常 / 超时 /
返回空内容 / 注册表本身抛异常 / 参数确实被正确传入 / 空闲计时器善后。
"""

import asyncio
import unittest

from tests.fixtures import PLUGIN_DIR  # noqa: F401  （确保插件目录在 sys.path）
from core.peer_plugin import (
    arm_peer_idle_timer,
    ask_peer_text,
    call_peer,
    resolve_peer,
)

PEER = "astrbot_plugin_aisearch"


def _run(coro):
    return asyncio.run(coro)


class FakeStar:
    """模拟 aisearch 实例：只需要 _send_query(prompt, images) -> (created, answer)。"""

    def __init__(self, *, answer="结果", created=False, exc=None, delay=0.0):
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
        self.star_cls, self.activated, self.name = inst, activated, PEER


class FakeContext:
    def __init__(self, meta=None, exc=None):
        self.meta, self.exc = meta, exc

    def get_registered_star(self, name):
        if self.exc:
            raise self.exc
        return self.meta if name == PEER else None


class TestResolvePeer(unittest.TestCase):
    def test_success(self):
        inst = FakeStar()
        got, why = resolve_peer(FakeContext(FakeMeta(inst)), PEER)
        self.assertIs(got, inst)
        self.assertEqual(why, "")

    def test_none_context(self):
        inst, why = resolve_peer(None, PEER)
        self.assertIsNone(inst)
        self.assertIn("context", why)

    def test_context_without_registry_api(self):
        inst, why = resolve_peer(object(), PEER)
        self.assertIsNone(inst)
        self.assertIn("get_registered_star", why)

    def test_registry_raises(self):
        inst, why = resolve_peer(FakeContext(exc=RuntimeError("boom")), PEER)
        self.assertIsNone(inst)
        self.assertIn("RuntimeError", why)

    def test_not_installed(self):
        inst, why = resolve_peer(FakeContext(None), PEER)
        self.assertIsNone(inst)
        self.assertIn("未安装", why)

    def test_inactive(self):
        inst, why = resolve_peer(FakeContext(FakeMeta(FakeStar(), activated=False)), PEER)
        self.assertIsNone(inst)
        self.assertIn("未激活", why)

    def test_star_cls_none(self):
        inst, why = resolve_peer(FakeContext(FakeMeta(None)), PEER)
        self.assertIsNone(inst)
        self.assertIn("star_cls", why)


class TestCallPeer(unittest.TestCase):
    def test_success_and_args_passthrough(self):
        inst = FakeStar(answer="回答")
        ret, why = _run(call_peer(FakeContext(FakeMeta(inst)), PEER, "_send_query",
                                  "提示词", [1, 2], timeout=5))
        self.assertEqual(ret, (False, "回答"))
        self.assertEqual(why, "")
        self.assertEqual(inst.seen, ("提示词", [1, 2]))     # 参数确实被正确传入

    def test_method_missing(self):
        class Bad:
            async def other(self):
                return 1

        ret, why = _run(call_peer(FakeContext(FakeMeta(Bad())), PEER, "_send_query", "x"))
        self.assertIsNone(ret)
        self.assertIn("没有方法", why)

    def test_peer_raises(self):
        inst = FakeStar(exc=RuntimeError("AuthError: 未登录"))
        ret, why = _run(call_peer(FakeContext(FakeMeta(inst)), PEER, "_send_query", "x", []))
        self.assertIsNone(ret)
        self.assertIn("AuthError", why)

    def test_timeout(self):
        inst = FakeStar(delay=0.5)
        ret, why = _run(call_peer(FakeContext(FakeMeta(inst)), PEER, "_send_query", "x", [],
                                  timeout=0.05))
        self.assertIsNone(ret)
        self.assertIn("超时", why)

    def test_not_installed(self):
        ret, why = _run(call_peer(FakeContext(None), PEER, "_send_query", "x", []))
        self.assertIsNone(ret)
        self.assertTrue(why)


class TestAskPeerText(unittest.TestCase):
    def test_success_with_extract(self):
        inst = FakeStar(answer="  AI 正文  ", created=True)
        text, why = _run(ask_peer_text(
            FakeContext(FakeMeta(inst)), PEER, "_send_query", "提示词",
            extract=lambda ret: ret[1],
        ))
        self.assertEqual(text, "AI 正文")
        self.assertEqual(why, "")
        self.assertEqual(inst.seen[0], "提示词")
        self.assertEqual(inst.seen[1], [])                  # 不带图片

    def test_empty_prompt_skips(self):
        inst = FakeStar()
        text, why = _run(ask_peer_text(FakeContext(FakeMeta(inst)), PEER,
                                       "_send_query", "   "))
        self.assertEqual(text, "")
        self.assertIn("为空", why)
        self.assertIsNone(inst.seen)                        # 根本没调用对方

    def test_empty_answer(self):
        for answer in ("", "   ", None):
            inst = FakeStar(answer=answer)
            text, why = _run(ask_peer_text(FakeContext(FakeMeta(inst)), PEER,
                                           "_send_query", "提示词"))
            self.assertEqual(text, "")
            self.assertIn("空内容", why)

    def test_default_extract_handles_variants(self):
        # str 直接用
        class StrStar:
            async def _send_query(self, prompt, images):
                return "纯文本"

        text, _ = _run(ask_peer_text(FakeContext(FakeMeta(StrStar())), PEER,
                                     "_send_query", "p"))
        self.assertEqual(text, "纯文本")

        # 二元组默认取首元素（业务层应显式传 extract，这里是兜底语义）
        class TupStar:
            async def _send_query(self, prompt, images):
                return (True, "第二个")

        text, _ = _run(ask_peer_text(FakeContext(FakeMeta(TupStar())), PEER,
                                     "_send_query", "p"))
        self.assertEqual(text, "True")

    def test_extract_raises_is_swallowed(self):
        inst = FakeStar(answer="x")

        def boom(_ret):
            raise ValueError("坏返回值")

        text, why = _run(ask_peer_text(FakeContext(FakeMeta(inst)), PEER,
                                       "_send_query", "p", extract=boom))
        self.assertEqual(text, "")
        self.assertIn("解析", why)

    def test_peer_raises_returns_empty(self):
        inst = FakeStar(exc=RuntimeError("ConversationError"))
        text, why = _run(ask_peer_text(FakeContext(FakeMeta(inst)), PEER,
                                       "_send_query", "p"))
        self.assertEqual(text, "")
        self.assertIn("ConversationError", why)


class TestArmIdleTimer(unittest.TestCase):
    def test_arms_current_conversation(self):
        class Conv:
            local_id = 7

        class Session:
            current_conversation = Conv()

        class Inst:
            session = Session()
            armed = []

            def _arm_idle_timer(self, local_id):
                self.armed.append(local_id)

        inst = Inst()
        arm_peer_idle_timer(inst)
        self.assertEqual(inst.armed, [7])

    def test_absence_is_ignored(self):
        arm_peer_idle_timer(object())                      # 不该抛异常
        arm_peer_idle_timer(None)

    def test_raises_is_ignored(self):
        class Inst:
            def _arm_idle_timer(self, local_id):
                raise RuntimeError("对方内部炸了")

            @property
            def session(self):
                raise RuntimeError("session 取不到")

        arm_peer_idle_timer(Inst())


if __name__ == "__main__":
    unittest.main()
