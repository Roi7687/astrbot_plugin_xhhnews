# -*- coding: utf-8 -*-
"""端到端验证（真实小黑盒数据 + 真实 AI）：本周日历 → AI 精选 → 最终 QQ Markdown。

跑法（在插件目录下，用 AstrBot 的 venv Python）：

    <instance>/venv/Scripts/python.exe research/verify_ai_review.py --fetch-only  # 只验证抓数+拼清单
    <instance>/venv/Scripts/python.exe research/verify_ai_review.py               # 完整链路（真实 DeepSeek）

为什么不在 AstrBot 进程里跑：跨插件的注册表查询只能在 AstrBot 进程内验证（由插件
`@filter.on_astrbot_loaded()` 自检日志证明）。本脚本验证的是「除了注册表查询以外」的
全部真实链路：真实接口数据 → 真实提示词 → 真实 aisearch 插件实例 `_send_query()`
（Playwright 驱动 DeepSeek 网页版）→ 真实排版输出。

注意：为了不与正在运行的 AstrBot 里 aisearch 的会话/浏览器抢资源，脚本把对方的
`conversations.json` 重定向到临时目录，只在末尾关闭自己的浏览器。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

INSTANCE = Path(r"D:\Program Files\.astrbot_launcher\instances\6954c33c-e9b3-4d77-8280-d4bbd898af87")
CORE = INSTANCE / "core"
PLUGINS = CORE / "data" / "plugins"
OUT_DIR = Path(__file__).resolve().parent / "verify_output"

sys.path.insert(0, str(CORE))                            # astrbot
sys.path.insert(0, str(PLUGINS))                         # 两个插件包
sys.path.insert(0, str(CORE / "data" / "site-packages"))  # 插件第三方依赖（预留）
os.chdir(tempfile.gettempdir())                          # 避免 import astrbot 时在工作目录生成 data/

from astrbot_plugin_xhhnews.core.ai_review import build_ai_prompt  # noqa: E402
from astrbot_plugin_xhhnews.core.calendar_core import XhhCalendarCore  # noqa: E402
from astrbot_plugin_xhhnews.core.calendar_format import (  # noqa: E402
    format_week_digest,
    format_week_markdown,
    format_week_review_markdown,
)


def step(title: str) -> None:
    print("\n" + "=" * 14 + " " + title + " " + "=" * 14)


def save(name: str, text: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    print(f"  → 已写入 {path}（{len(text)} 字符）")
    return path


async def main() -> int:
    fetch_only = "--fetch-only" in sys.argv
    meta: dict = {"fetch_only": fetch_only}

    # ── 1) 真实小黑盒数据 ──
    step("1) 抓取本周真实发售日历（小黑盒接口）")
    calendar = XhhCalendarCore()
    t0 = time.time()
    days = await calendar.fetch_week()
    fetch_cost = time.time() - t0
    today = calendar.today()
    total = sum(len(d.games) for d in days)
    tagged = sum(1 for d in days for g in d.games if g.tags)
    with_appid = sum(1 for d in days for g in d.games if g.steam_appid)
    print(f"本周 {days[0].date} ~ {days[-1].date}，共 {total} 款新游"
          f"（有标签 {tagged} 款 / 有 AppID {with_appid} 款），耗时 {fetch_cost:.1f}s")
    meta.update(total=total, fetch_cost=round(fetch_cost, 1))

    week_md = format_week_markdown(days, today)
    save("week_calendar.md", week_md)

    # ── 2) 拼「喂给 AI 的清单」与提示词 ──
    step("2) 拼 AI 清单与提示词")
    digest = format_week_digest(days, today)
    prompt = build_ai_prompt(digest)
    print(f"清单 {len(digest)} 字符 / 完整提示词 {len(prompt)} 字符")
    print("清单前 3 行：")
    print("\n".join(digest.splitlines()[:3]))
    save("week_digest.txt", digest)
    save("prompt.txt", prompt)
    meta.update(digest_chars=len(digest), prompt_chars=len(prompt))

    if fetch_only:
        step("完成（--fetch-only，未调用 AI）")
        save("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    # ── 3) 真实调用 aisearch 的 _send_query（DeepSeek 网页版，浏览器自动化）──
    step("3) 真实调用 aisearch（DeepSeek + 联网搜索）")
    import astrbot_plugin_aisearch.core.session_core as ais_session_core

    tmp_dir = Path(tempfile.mkdtemp(prefix="xhhnews-ai-"))
    ais_session_core.CONVERSATIONS_FILE = str(tmp_dir / "conversations.json")
    print(f"（已把对方的 conversations.json 重定向到 {ais_session_core.CONVERSATIONS_FILE}）")

    from astrbot_plugin_aisearch.main import CloakSearchPlugin

    from astrbot_plugin_xhhnews.core.ai_review import ask_ai_review

    class _Meta:
        def __init__(self, inst):
            self.star_cls, self.activated, self.name = inst, True, "astrbot_plugin_aisearch"

    class _Context:
        """模拟 AstrBot 注册表：get_registered_star(name) → 真实的 aisearch 插件实例。"""

        def __init__(self):
            self.meta = None

        def get_registered_star(self, name):
            return self.meta if name == "astrbot_plugin_aisearch" else None

    ctx = _Context()
    inst = CloakSearchPlugin(ctx)          # 真实插件实例（构造只创建会话内核，不启浏览器）
    ctx.meta = _Meta(inst)

    t0 = time.time()
    try:
        review = await ask_ai_review(ctx, digest, timeout=300)
    finally:
        try:
            await inst.terminate()         # 关闭浏览器内核
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️ 关闭浏览器失败（忽略）：{type(exc).__name__}: {exc}")
    ai_cost = time.time() - t0
    meta.update(ai_cost=round(ai_cost, 1), ai_chars=len(review))

    if not review:
        print(f"❌ AI 没有返回内容（耗时 {ai_cost:.1f}s）——检查 aisearch 登录态/AuthError（见上方日志）")
        save("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        return 1
    print(f"✅ AI 回复 {len(review)} 字符（耗时 {ai_cost:.1f}s）")

    # ── 4) 最终回复形态（定稿提示词已规定版式，插件不再加标题/脚注）──
    step("4) 最终 QQ Markdown 形态")
    final = format_week_review_markdown(review)
    save("ai_review_raw.txt", review)
    save("final_reply.md", final)
    save("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    print("\n" + "-" * 60)
    print(final)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
