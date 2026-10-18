# AstrBot 插件间调用指南（跨插件调用另一个插件的能力）

> 适用：AstrBot 4.5.x+（本文实测于 `4.5.7` 环境，源码行号以该版本为准）。
> 场景：你的插件想借用另一个插件的能力，例如把一段文本交给「AI 对话 / 搜索类插件」处理，
> 再把结果拼进自己的回复（本文以 `astrbot_plugin_aisearch` 为实例）。
> 本文所有代码都是**可直接复制到其他项目**的通用写法，不绑定具体业务。

---

## 0. 结论先行（TL;DR）

**可以。** AstrBot 把每个已加载插件的**实例**挂在全局注册表里，通过插件的 `Context` 就能取到：

```python
md = self.context.get_registered_star("astrbot_plugin_某某插件")   # → StarMetadata
if md and md.activated and md.star_cls is not None:
    inst = md.star_cls                       # ← 对方插件实例，直接调它的方法
    ok, text = await inst.某个公开方法("要处理的文本")
```

三件事必须记住：

1. **每次现取**，不要把 `inst` 存成成员变量 —— 插件热重载后实例会换。
2. **先判 `activated` 和 `star_cls is not None`** —— 插件被禁用时 `star_cls` 是 `None`。
3. **用 `asyncio.wait_for` 加超时 + 兜住所有异常** —— 跨插件调用是"尽力而为"，绝不能让对方的问题拖垮你自己的回复。

---

## 1. 原理与源码证据

| 机制 | 位置（AstrBot 源码） | 说明 |
|---|---|---|
| 全部插件元数据列表 | `astrbot/core/star/star.py:9` `star_registry: list[StarMetadata]` | 按加载顺序保存 |
| 模块路径 → 元数据 | `astrbot/core/star/star.py:10` `star_map: dict[str, StarMetadata]` | key 是 `__module__`，如 `data.plugins.xxx.main` |
| **插件实例字段** | `astrbot/core/star/star.py:42` `star_cls: Star \| None` | 注释原文："插件的类对象" |
| 官方对跨插件调用的提醒 | `astrbot/core/star/star.py:21` | "当 activated 为 False 时，star_cls 可能为 None，**请不要在插件未激活时调用 star_cls 的方法**" —— 即官方默认认可这种用法，只要求判激活 |
| 实例创建（正常加载） | `astrbot/core/star/star_manager.py:1227/1232/1236` | `metadata.star_cls = metadata.star_cls_type(context=..., config=...)` |
| 实例清空（插件被禁用） | `astrbot/core/star/star_manager.py:1245` | `metadata.star_cls = None` |
| 实例替换（热重载） | `astrbot/core/star/star_manager.py:1362` | `metadata.star_cls = obj` —— **旧实例被换掉，所以不要缓存** |
| 查询入口（插件名） | `astrbot/core/star/context.py:346` `get_registered_star(name)` | 按 `metadata.name`（= `metadata.yaml` 里的 `name:`）精确匹配 |
| 查询入口（全部） | `astrbot/core/star/context.py:352` `get_all_stars()` | 遍历诊断时很有用 |
| 插件实例自身可用能力 | `astrbot/core/star/base.py:28` | `Star.__init__` 提供 `self.context`、`self.logger` |

**版本适配**：`star_cls` / `get_registered_star` 属于 AstrBot 核心稳定结构（4.x 全程存在）。
迁移到新版本时先跑第 7 节的"探测脚本"确认，不要只看文档。

---

## 2. 四条路线的选择

调用"另一个插件/AI 能力"其实有四种做法，先选对路线再写代码：

| 路线 | 做法 | 适合 | 代价 |
|---|---|---|---|
| **A. 跨插件直调**（本文重点） | `get_registered_star(name).star_cls.方法()` | 对方插件已经封装好"给文本→返结果"的能力（如 AI 对话/搜索插件） | 依赖对方**私有方法**，对方改版会断 |
| **B. `event.request_llm()`** | 处理函数里 `yield event.request_llm(prompt=...)`，由主流水线执行 | 想用 AstrBot 自己的模型/人格，结果直接回给用户 | 需先在 WebUI 配好模型；受会话人格影响 |
| **C. `Context.llm_generate()` / `tool_loop_agent()`** | 插件内直接调模型，自己拿 `LLMResponse` 再加工 | 要完全控制提示词、二次排版、工具循环 | 同上（需模型），`llm_generate` 需 AstrBot ≥ 4.5.7 |
| **D. `@filter.llm_tool()`** | 把自己的能力注册成"模型可调用的工具" | 反过来让 AI 主动来调你 | 逻辑与 A 相反（AI 调插件） |

路线 A 的关键证据（都是公开 API）：

| API | 位置 |
|---|---|
| `event.request_llm(prompt=..., system_prompt=..., contexts=...)` → `ProviderRequest`，由流水线执行 | `astrbot/core/platform/astr_message_event.py:425`；消费点 `astrbot/core/pipeline/process_stage/stage.py:40` |
| `Context.llm_generate(chat_provider_id=..., prompt=..., system_prompt=...)` | `astrbot/core/star/context.py:171`（`. versionadded:: 4.5.7`） |
| `Context.tool_loop_agent(event=..., chat_provider_id=..., tools=...)` | `astrbot/core/star/context.py:215` |
| `Context.get_current_chat_provider_id(umo)` / `get_using_provider(umo)` | `context.py:329` / `:457` |
| `@filter.llm_tool(name=...)` → `register_llm_tool` | `astrbot/core/star/register/star_handler.py` |

> 选型建议：**如果对方插件已经能"吃一段文本给一段文本"，走 A 最省事**（本文实测之路）；
> 如果只是想要一次模型推理、不关心是谁提供的，走 B/C 更稳（不依赖第三方插件版本）。

---

## 3. 通用封装（可直接复制到新项目）

新建 `core/peer_plugin.py`（名字随意）：

```python
# -*- coding: utf-8 -*-
"""跨插件调用：从 AstrBot 注册表取另一个插件实例并调用其方法（尽力而为）。"""
import asyncio
import inspect
import logging

logger = logging.getLogger("astrbot")


def resolve_peer(context, plugin_name: str):
    """按插件名取对方实例。

    :return: (instance | None, 不可用原因 str)
    """
    if context is None:
        return None, "context 为空"
    get_star = getattr(context, "get_registered_star", None)
    if get_star is None:
        return None, "当前 AstrBot 版本没有 get_registered_star"
    try:
        md = get_star(plugin_name)
    except Exception as e:                      # 注册表异常也不许炸
        return None, f"查询注册表异常: {type(e).__name__}: {e}"
    if md is None:
        return None, f"未安装/未加载插件 {plugin_name}"
    if not getattr(md, "activated", True):
        return None, f"插件 {plugin_name} 处于未激活（被禁用）状态"
    inst = getattr(md, "star_cls", None)
    if inst is None:
        return None, f"插件 {plugin_name} 实例不可用（star_cls 为空）"
    return inst, ""


async def call_peer(context, plugin_name: str, method: str, *args,
                    timeout: float = 60.0, **kwargs):
    """调用另一个插件实例上的方法。

    失败（未安装/未激活/无该方法/超时/抛异常）一律返回 (None, 原因)，绝不向外抛。
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
    except Exception as e:                       # 对方的 AuthError / 业务异常一律兜住
        why = f"{type(e).__name__}: {e}"
        logger.warning(f"[peer] {plugin_name}.{method} 失败：{why}")
        return None, why
    return ret, ""
```

**用法**：

```python
ret, err = await call_peer(self.context, "astrbot_plugin_aisearch",
                           "_send_query", prompt, [], timeout=120)
if ret is not None:
    created, answer = ret                  # 具体返回值语义看对方实现
```

> 注意 `getattr(inst, method)` 取的是**私有方法**（下划线开头）。这是路线 A 的固有代价：
> 必须锁对方版本。可把"目标方法名"做成插件配置项，对方改版时改配置即可，无需改代码。

---

## 4. 实战：调用 `astrbot_plugin_aisearch`（AI 对话/联网搜索）

该插件类名 `CloakSearchPlugin`，内核是 **Playwright 驱动 DeepSeek 网页版**（需要 `auth_state.json` 登录态）。
它对外可用入口（按"省事程度"排序）：

| 入口 | 签名 | 是否需要 event | 说明 |
|---|---|---|---|
| **`_send_query`** ← 推荐 | `async (prompt: str, images: list) -> (created: bool, answer: str)` | 否 | `images=[]` 时等价于 `session.send_message(prompt)`；`created` = 是否新建了会话 |
| `_ask` | `async (event, own_text: str) -> (created, answer)` | **需要** | 会额外解析"引用消息/图片"；适合你在自己插件里也想处理引用场景 |
| `session.send_message` | `async (text) -> (created, answer)` | 否 | 更底层（`session` 是其 `DeepSeekSessionCore`），语义同上 |
| `_respond` | `async (event, created, result) -> str` | **需要** | 会给回复加"🟢已开启新会话"前缀 + 键盘按钮，**可能自己发消息**（返回空串时表示已发过）——一般不要用 |

最小可用代码：

```python
async def ask_ai(context, prompt: str, *, timeout: float = 120.0) -> str:
    """把 prompt 交给 aisearch，返回回答；失败返回空串。"""
    inst, why = resolve_peer(context, "astrbot_plugin_aisearch")
    if inst is None:
        logger.warning(f"[ai] 不可用：{why}")
        return ""
    try:
        created, answer = await asyncio.wait_for(inst._send_query(prompt, []), timeout)
    except asyncio.TimeoutError:
        logger.warning(f"[ai] 超时（>{timeout:.0f}s）")
        return ""
    except Exception as e:                     # AuthError（未登录）等
        logger.warning(f"[ai] 失败：{type(e).__name__}: {e}")
        return ""
    _arm_peer_idle_timer(inst)                 # ← 见下方"善后"
    return (answer or "").strip()


def _arm_peer_idle_timer(inst) -> None:
    """替对方重置空闲计时器（它自己的 _respond() 才会做这件事，我们绕过了它）。

    不补这一步：我们新建的会话不会被计入空闲销毁，无头浏览器可能一直挂着。
    """
    try:
        conv = getattr(getattr(inst, "session", None), "current_conversation", None)
        arm = getattr(inst, "_arm_idle_timer", None)
        local_id = getattr(conv, "local_id", None)
        if local_id is not None and callable(arm):
            arm(local_id)
    except Exception as e:
        logger.debug(f"[ai] 重置对方空闲计时器失败（忽略）：{e}")
```

**aisearch 的行为特征（实测，务必知道）**：

| 特性 | 数值/表现 |
|---|---|
| 单次耗时 | **20~60s**（浏览器自动化：启动内核 → 输入 → 等待生成 → 提取文本） |
| 并发 | 内部 `asyncio.Lock()` **串行化**（`core/session_core.py:74`），多人同时调用会排队，第二个可能撞上你的超时 |
| 空闲销毁 | `IDLE_TIMEOUT_SECONDS = 300`（5 分钟无活动销毁会话 + 关浏览器） |
| 登录态 | 依赖插件目录下 `auth_state.json`（cookies）；失效时抛 `AuthError` |
| 无会话时 | 自动新建，返回值第一个元素 `created=True` |
| 是否联网 | 是（DeepSeek 网页版自带联网），可在提示词里要求它搜索 |
| 调用后 | 建议替它 `_arm_idle_timer`（见上） |

---

## 5. 健壮性清单（照抄这 8 条，基本不会踩坑）

1. **不要缓存实例**：每次调用前 `get_registered_star` 现取（热重载会换实例，旧引用仍在但已 `terminate`）。
2. **判 `activated` 与 `star_cls`**：插件被禁用时 `star_cls is None`。
3. **判方法存在**：`getattr(inst, "xxx", None)` + `callable()`，别直接 `inst.xxx()`（版本不兼容会 `AttributeError`）。
4. **一定加超时**：`asyncio.wait_for(..., timeout)`；浏览器自动化/大模型都可能卡住。
5. **兜住所有异常**：对方的 `AuthError` / `ConversationError` / `ImagePrepareError` 都是它自己的异常类，
   **不要 `from 对方插件 import`**（会造成硬依赖），统一 `except Exception` + 记日志。
6. **失败要能降级**：返回值用 `(结果, 原因)` 或"空结果"，让自己的主功能照常工作 —— 跨插件能力永远是"加分项"。
7. **善后调用对方内部清理**：如 aisearch 的 `_arm_idle_timer`，否则对方资源（无头浏览器）可能不释放。
8. **只把"对方插件名 + 方法名 + 超时"做成配置**，不要写死在业务逻辑里（对方改版时改配置即可）。

**返回值语义别猜**：像 aisearch 的 `_send_query` 返回的是 `(created, answer)`，
其中 `created` 是"是否新建会话"而不是"是否成功"。**成功与否看是否抛异常**。迁移到别的插件时务必读一遍它的源码。

---

## 6. 常见坑

| 坑 | 现象 | 解法 |
|---|---|---|
| 缓存了实例 | 插件热重载后调用报错/没反应 | 每次现取 |
| 对方被禁用 | `star_cls` 为 `None` → `AttributeError` | 判 `activated` + `star_cls` |
| 对方方法签名变了 | `TypeError: 参数不匹配` | 方法名/参数做成配置；调用前 `inspect.signature()` 打日志便于排障 |
| 对方是浏览器自动化 | 单次 20~60s，多人同时用会排队 | 超时给足（120s），并在用户侧文案里说明"稍等" |
| 你我都在 QQ 被动回复窗口内 | 超时（5 分钟）后回复发不出去 | 控制等待上限 + 失败降级 |
| 对方需要 event | 传 `None` 会 `AttributeError` | 用它需要 event 的入口（如 `_ask`），把当前 `event` 传进去 |
| 对方自己会发消息 | 你的回复和对方的消息重复 | 别用"会自己发消息"的入口（如 aisearch 的 `_respond`） |
| 插件加载顺序 | 你 `__init__` 里查不到对方 | 在 `@filter.on_astrbot_loaded()` 里复查（此时代码里所有插件都已注册） |
| 把对方异常类 import 进自己代码 | 对方改包结构 → 你 `ImportError` | 只 `except Exception`，不引用对方类型 |

---

## 7. 排障与探测

**① 启动自检（推荐加进你的插件）**

```python
def _selfcheck(self, *, strict: bool) -> None:
    inst, why = resolve_peer(self.context, PEER_PLUGIN_NAME)
    if inst is None:
        (logger.warning if strict else logger.debug)(f"[peer] 不可用：{why}")
    else:
        logger.info(f"[peer] 可用：{PEER_PLUGIN_NAME} → {type(inst).__name__}")

@filter.on_astrbot_loaded()
async def _check_peer(self):
    self._selfcheck(strict=True)
```

**② 一次性探测脚本**（换项目/换版本先跑它，确认对方到底暴露了什么）

```python
# 放在插件目录下执行：python probe_peer.py
import asyncio, os, sys, tempfile
from pathlib import Path

INSTANCE = Path(r"<你的 AstrBot 实例目录>")          # 含 core/astrbot 的那一层
sys.path.insert(0, str(INSTANCE / "core"))            # astrbot 包
sys.path.insert(0, str(INSTANCE / "core" / "data" / "plugins"))
sys.path.insert(0, str(INSTANCE / "core" / "data" / "site-packages"))  # 插件第三方依赖
os.chdir(tempfile.gettempdir())                       # 避免 import astrbot 时在工作目录生成 data/

from astrbot.core.star.star import star_registry, star_map   # 全局注册表


def main():
    print("star_map keys:", list(star_map)[:10])
    for md in star_registry:
        print(f"- {md.name} v{md.version} activated={md.activated} "
              f"inst={type(md.star_cls).__name__ if md.star_cls else None}")
        if md.star_cls:
            names = [n for n in dir(md.star_cls)
                     if not n.startswith("__") and callable(getattr(md.star_cls, n, None))]
            print("  可调用成员:", ", ".join(names[:40]))


main()
```

> ⚠️ 注意：该脚本在**独立进程**里跑时，注册表通常是空的（插件没被 StarManager 加载）。
> 它的正确用途是：**在你自己的插件运行期间**（或在 AstrBot 进程内）打印诊断，
> 或者把它改成"通过 `context.get_all_stars()` 打印"放进自检里。真实链路验证请看下面第 8 节。

**③ 真实链路验证脚本**（不经过 AstrBot，直接驱动对方内核，用于确认"对方现在能不能用"）

```python
from astrbot_plugin_aisearch.core.session_core import DeepSeekSessionCore   # 仅验证用；生产代码不要这样 import！

async def main():
    s = DeepSeekSessionCore()
    try:
        created, answer = await s.send_message("你好，请用一句话回答：1+1=？")
        print(created, answer)
    finally:
        await s.close()
```

---

## 8. 测试策略（无网络也能测）

跨插件调用必须能**在没有对方插件、没有网络**的情况下被单测覆盖 —— 用桩对象即可：

```python
class FakeStar:                        # 模拟对方实例
    def __init__(self, answer="结果", created=False, exc=None, delay=0.0):
        self.answer, self.created, self.exc, self.delay = answer, created, exc, delay
        self.seen = None
    async def _send_query(self, prompt, images):
        self.seen = (prompt, images)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.created, self.answer

class FakeMeta:                        # 模拟 StarMetadata
    def __init__(self, inst, activated=True):
        self.star_cls, self.activated = inst, activated

class FakeContext:                     # 模拟 Context.get_registered_star
    def __init__(self, meta=None, exc=None):
        self.meta, self.exc = meta, exc
    def get_registered_star(self, name):
        if self.exc:
            raise self.exc
        return self.meta
```

必测分支（缺一不可）：**成功 / 未安装 / 未激活 / `star_cls` 为空 / 没有目标方法 /
对方抛异常 / 超时 / 返回空内容 / 注册表本身抛异常 / 参数确实被正确传入**。

---

## 9. 迁移到新项目的步骤

1. 复制第 3 节的 `core/peer_plugin.py`（通用封装，零业务耦合）。
2. 在配置里加三项：`PEER_PLUGIN_NAME`（对方插件名，见其 `metadata.yaml` 的 `name:`）、
   `PEER_METHOD`（要调的方法名）、`PEER_TIMEOUT`。
3. 加启动自检（第 7 节 ①），确认日志里出现"可用：xxx → 对方类名"。
4. 业务侧只依赖"输入文本 → 输出文本"的抽象，**不要直接把对方返回值结构写进业务逻辑**（在封装层剥掉）。
5. 加降级：对方不可用/超时 → 输出里少一段，其余功能照常。
6. 补单测（第 8 节桩对象，覆盖 10 个分支）。
7. 上线前跑一次真实链路（第 7 节 ③ 或直接在你插件里手动触发），量一下**真实耗时**再定超时值。

---

## 10. 附：本仓库的实际实现（可对照阅读）

| 文件 | 作用 |
|---|---|
| `core/ai_review.py` | `AI_REVIEW_PROMPT`（提示词）+ `build_ai_prompt()`（填数据）+ `resolve_peer` 逻辑 + `ask_ai_review()`（带超时/降级/善后） |
| `core/formatter.py` → `ai_panel_text()` | 把"玩家可见文本里没有、但提示词需要"的字段拼成补充面板，**只喂 AI** |
| `main.py` | 在 `/wot <昵称>` 组装完正文后调用 `ask_ai_review()`，成功则以 `**AI评价：**` 追加 |
| `core/config.py` | `AI_REVIEW_ENABLED / AI_REVIEW_PLUGIN / AI_REVIEW_TIMEOUT / AI_REVIEW_MAX_CHARS / AI_REVIEW_PANEL` |
| `tests/test_ai_review.py` | 桩对象测试（23 项：成功/各类降级/超时/空回复/参数透传/提示词结构） |
| `research/verify_ai_review.py`、`research/verify_user_prompt.py` | 真实链路验证脚本（不联网不入库，本地用） |

关键取舍（可直接搬到别的项目）：

- **提示词与调用解耦**：`AI_REVIEW_PROMPT` 是纯文本常量，占位符 `{{...}}` 由 `build_ai_prompt()` 替换 —— 换提示词不用改代码。
- **"AI 可见 ≠ 玩家可见"**：给 AI 的输入可以是玩家回复的超集（补充面板），但**输出只追加一段**，避免刷屏。
- **失败静默**：`ask_ai_review()` 任何失败都返回空串，`main.py` 只在非空时追加 —— 主功能永不受影响。
