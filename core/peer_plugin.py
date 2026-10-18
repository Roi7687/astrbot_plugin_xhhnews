# -*- coding: utf-8 -*-
"""跨插件调用：从 AstrBot 注册表取另一个插件实例并调用其方法（尽力而为）。

设计参照 ASTRBOT_CROSS_PLUGIN_CALL.md 第 3 节，零业务耦合：

- `resolve_peer()` 按插件名取实例，不可用时返回 `(None, 原因)`，绝不抛异常；
- `call_peer()` 调用对方方法，未安装 / 未激活 / 无方法 / 超时 / 抛异常
  一律返回 `(None, 原因)`，绝不向外抛；
- `ask_peer_text()` 是「一段文本进 → 一段文本出」的便捷封装，
  由业务层传入一个把对方返回值转成文本的 `extract` 函数（不猜对方返回值语义）；
- `arm_peer_idle_timer()` 是给 aisearch 这类「有会话空闲销毁」的插件做善后
  （绕过了对方自己的 `_respond()`，不补这一步空闲计时器不会重置）。

铁律：**每次现取实例，不缓存**；对方热重载会换实例。只用公开/尽力而为的方式，
不 `from 对方插件 import` 任何异常类型 —— 对方改包结构不该让本插件 ImportError。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger("astrbot")

__all__ = [
    "resolve_peer",
    "call_peer",
    "ask_peer_text",
    "arm_peer_idle_timer",
]


def resolve_peer(context, plugin_name: str):
    """按插件名从注册表取对方实例。

    :return: `(instance | None, 不可用原因 str)`
    """
    if context is None:
        return None, "context 为空"
    get_star = getattr(context, "get_registered_star", None)
    if get_star is None:
        return None, "当前 AstrBot 版本没有 get_registered_star"
    try:
        md = get_star(plugin_name)
    except Exception as exc:  # noqa: BLE001  注册表异常也不许炸
        return None, f"查询注册表异常: {type(exc).__name__}: {exc}"
    if md is None:
        return None, f"未安装/未加载插件 {plugin_name}"
    if not getattr(md, "activated", True):
        return None, f"插件 {plugin_name} 处于未激活（被禁用）状态"
    inst = getattr(md, "star_cls", None)
    if inst is None:
        return None, f"插件 {plugin_name} 实例不可用（star_cls 为空）"
    return inst, ""


async def call_peer(
    context,
    plugin_name: str,
    method: str,
    *args,
    timeout: float = 60.0,
    **kwargs,
):
    """调用另一个插件实例上的方法。

    失败（未安装 / 未激活 / 无该方法 / 超时 / 抛异常）一律返回 `(None, 原因)`，绝不向外抛。
    """
    inst, why = resolve_peer(context, plugin_name)
    if inst is None:
        logger.warning(f"[peer] 跳过调用 {plugin_name}.{method}：{why}")
        return None, why

    fn = getattr(inst, method, None)
    if not callable(fn):
        why = f"{plugin_name} 没有方法 {method}（版本可能不兼容）"
        logger.warning(f"[peer] {why}")
        return None, why

    try:
        ret = await asyncio.wait_for(fn(*args, **kwargs), timeout)
    except asyncio.TimeoutError:
        why = f"{plugin_name}.{method} 超时（>{timeout:.0f}s）"
        logger.warning(f"[peer] {why}")
        return None, why
    except Exception as exc:  # noqa: BLE001  对方的 AuthError / ConversationError 等一律兜住
        why = f"{type(exc).__name__}: {exc}"
        logger.warning(f"[peer] {plugin_name}.{method} 失败：{why}")
        return None, why
    return ret, ""


async def ask_peer_text(
    context,
    plugin_name: str,
    method: str,
    prompt: str,
    *,
    images: list | None = None,
    timeout: float = 60.0,
    extract: Callable[[object], str] | None = None,
) -> tuple[str, str]:
    """把一段文本交给对方插件的「文本进 → 文本出」能力，返回 `(回答正文, 不可用原因)`。

    `extract` 负责把对方返回值转成文本（**不猜对方返回值语义**，由业务层传入）；
    缺省时：str 直接用，单元素序列取首元素，其余 `str(ret)`。

    对方不可用 / 超时 / 抛异常 / 返回空内容时，回答正文为空串 —— 调用方据此降级。
    """
    text = (prompt or "").strip()
    if not text:
        return "", "提示词为空"

    extractor = extract or _default_extract
    ret, why = await call_peer(
        context, plugin_name, method, text, list(images or []), timeout=timeout
    )
    if ret is None:
        return "", why

    try:
        answer = extractor(ret)
    except Exception as exc:  # noqa: BLE001
        why = f"解析对方返回值失败: {type(exc).__name__}: {exc}"
        logger.warning(f"[peer] {why}")
        return "", why

    answer = (answer or "").strip()
    if not answer:
        return "", "对方返回了空内容"
    return answer, ""


def _default_extract(ret: object) -> str:
    """缺省返回值提取：str 直接返回，序列取首元素，否则 str()。"""
    if isinstance(ret, str):
        return ret
    if isinstance(ret, (list, tuple)) and ret:
        return str(ret[0] or "")
    return str(ret or "")


def arm_peer_idle_timer(inst) -> None:
    """替对方插件重置会话空闲计时器（对 aisearch 的「最小善意调用」）。

    我们绕过了对方自己的 `_respond()`，而空闲销毁计时器是在那里重置的；
    不补这一步，我们新建/使用的会话不会被计入空闲销毁，无头浏览器可能一直挂着。
    失败只记 DEBUG（对方版本改了这个私有接口也不该影响我们）。
    """
    try:
        conv = getattr(getattr(inst, "session", None), "current_conversation", None)
        arm = getattr(inst, "_arm_idle_timer", None)
        local_id = getattr(conv, "local_id", None)
        if local_id is not None and callable(arm):
            arm(local_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[peer] 重置对方空闲计时器失败（忽略）：{type(exc).__name__}: {exc}")
