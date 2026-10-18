# -*- coding: utf-8 -*-
"""在**真实运行的 AstrBot 实例里**发一条指令并收集机器人回复（WebChat 平台通道）。

用途：验证插件在 AstrBot 管线里的真实表现 —— 命令注册、跨插件调用、消息发送、
QQ/WebChat 两套排版回退，全都走真实代码路径，而不是离线模拟。

原理：AstrBot Dashboard 的「统一对话」WebSocket（`/api/v1/unified-chat/ws`）把消息
投进 WebChat 平台的队列，WebChat 适配器再把它当作一条普通平台消息交给管线处理；
机器人回复通过同一个 WebSocket 的 `ct=chat` 事件流返回。
Dashboard 的 JWT 用实例自己的 `dashboard.jwt_secret` 自签（本机可读，无需改配置）。

跑法（在插件目录下）：

    <instance>/venv/Scripts/python.exe research/verify_in_astrbot.py                # 默认 /hbnews
    <instance>/venv/Scripts/python.exe research/verify_in_astrbot.py /hbhelp       # 换成别的指令

注意：会真实触发一次 AI 联网核验（约 30~120 秒），期间机器人会先回一条「正在核验」提示。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import jwt
import websockets

INSTANCE = Path(r"D:\Program Files\.astrbot_launcher\instances\6954c33c-e9b3-4d77-8280-d4bbd898af87")
CONFIG = INSTANCE / "core" / "data" / "cmd_config.json"
OUT_DIR = Path(__file__).resolve().parent / "verify_output"
BASE_URL = "http://127.0.0.1:21294"          # 本地 AstrBot Dashboard
WS_PATHS = ("/api/v1/unified-chat/ws", "/api/unified_chat/ws")

COMMAND = sys.argv[1] if len(sys.argv) > 1 else "/hbnews"
TIMEOUT = 300.0


def mint_token() -> str:
    raw = CONFIG.read_text(encoding="utf-8-sig")     # AstrBot 写文件带 BOM
    cfg = json.loads(raw)
    secret = cfg["dashboard"]["jwt_secret"]
    username = cfg["dashboard"].get("username") or "astrbot"
    exp = int(time.time()) + 600
    return jwt.encode({"username": username, "exp": exp}, secret, algorithm="HS256")


def step(title: str) -> None:
    print("\n" + "=" * 14 + " " + title + " " + "=" * 14)


async def try_connect(url: str):
    try:
        ws = await websockets.connect(url, open_timeout=10, max_size=16 * 1024 * 1024)
        print(f"✅ WebSocket 已连接：{url}")
        return ws
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 连接失败 {url}：{type(exc).__name__}: {exc}")
        return None


async def main() -> int:
    step("1) 自签 Dashboard JWT 并连接 WebChat 通道")
    token = mint_token()
    ws = None
    for path in WS_PATHS:
        ws = await try_connect(f"ws://127.0.0.1:21294{path}?token={token}")
        if ws is not None:
            break
    if ws is None:
        print("❌ 无法连接 Dashboard WebSocket（AstrBot 是否在运行？端口是否 21294？）")
        return 1

    message_id = str(uuid.uuid4())
    session_id = f"dsh-probe-{uuid.uuid4().hex[:8]}"
    payload = {
        "ct": "chat",
        "t": "send",
        "message_id": message_id,
        "session_id": session_id,
        "message": [{"type": "plain", "text": COMMAND}],
    }
    print(f"→ 发送指令：{COMMAND!r}（message_id={message_id}）")

    replies: list[dict] = []
    t0 = time.time()
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        while True:
            remaining = TIMEOUT - (time.time() - t0)
            if remaining <= 0:
                print("❌ 等待回复超时")
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                print("❌ 等待回复超时")
                break
            try:
                event = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            etype = event.get("type") or event.get("t")
            if etype in (None, "user_message_saved", "message_saved", "attachment_saved",
                         "agent_stats", "session_bound", "run_started"):
                continue
            replies.append({"t": etype, "data": event.get("data"), "elapsed": round(time.time() - t0, 1)})
            print(f"\n[{time.time() - t0:5.1f}s] ← {etype}:")
            print(str(event.get("data"))[:4000])
            if etype == "end":
                break
            if etype == "error":
                break
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass

    step("2) 结果")
    cost = time.time() - t0
    if not replies:
        print("❌ 没有收到任何机器人回复")
        return 1
    print(f"共收到 {len(replies)} 条回复，总耗时 {cost:.1f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# AstrBot 真实管线验证：`{COMMAND}`", "", f"- 耗时：{cost:.1f}s",
             f"- session：{session_id}", ""]
    for item in replies:
        lines += [f"## {item['t']}（{item['elapsed']}s）", "", "```text",
                  str(item["data"]), "```", ""]
    out = OUT_DIR / "astrbot_reply.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ 已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
