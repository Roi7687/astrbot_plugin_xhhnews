# -*- coding: utf-8 -*-
"""AI 精选：把「本周新游清单」交给 astrbot_plugin_aisearch（Playwright 驱动 DeepSeek 网页版）
做联网检索与筛选，生成一份「本周值得玩什么」的推荐列表。

链路：`format_week_digest()` 拼清单 → `build_ai_prompt()` 模板填空 →
跨插件 `_send_query(prompt, [])` → 修剪回答正文交给 `main.py` 发出去。

设计取舍（与 ASTRBOT_CROSS_PLUGIN_CALL.md 一致）：
- **提示词与调用解耦**：`AI_REVIEW_PROMPT` 是纯文本常量（用户定稿版），占位符 `{{...}}`
  由 `build_ai_prompt()` 替换 —— 换提示词不用改代码；
- **数据与提示词分离**：清单里给的字段（名称/日期/标签/平台/关注数/AppID）是客观数据，
  筛选标准与输出格式全在提示词里；
- **输出不做二次加工**：提示词已严格规定版式（禁止标题/开场白/总结语/避雷板块），
  所以 `calendar_format.format_week_review_markdown()` 原样返回模型正文；
- **失败静默**：对方未安装 / 未激活 / 未登录 / 超时 / 抛异常都只记日志并返回空串，
  `/hbnews` 由 main.py 降级为「本周完整日历 + 一句说明」，主功能永不受影响。
"""

from __future__ import annotations

import logging
import re

from .config import (
    AI_REVIEW_MAX_CHARS,
    AI_REVIEW_MAX_INPUT_CHARS,
    AI_REVIEW_METHOD,
    AI_REVIEW_PLUGIN,
    AI_REVIEW_TIMEOUT,
)
from .peer_plugin import arm_peer_idle_timer, ask_peer_text, resolve_peer

logger = logging.getLogger("astrbot")

__all__ = [
    "AI_REVIEW_PROMPT",
    "AI_DATA_PLACEHOLDER",
    "build_ai_prompt",
    "clean_answer",
    "ask_ai_review",
]

# ────────────────────────── 提示词（用户定稿版，可直接改这里，代码无需动） ──────────────────────────
#
# 说明：aisearch 用的是同一个持久化 DeepSeek 会话，可能在别的对话之后继续提问，
# 所以开头最高优先级就是「忽略此前上下文」。
AI_REVIEW_PROMPT = """\
# 任务边界（最高优先级）
这是一次独立的自动化生成任务：请忽略此前所有对话上下文，严格仅按本提示词执行。
不要向我提问、不要输出思考过程、不要任何开场白与结束语，直接联网检索并按指定格式输出最终结果。

# 角色与目标
你是眼光毒辣的资深游戏评测编辑兼核心老玩家。
请从下方小黑盒「本周发售清单」中，联网核验并挑选出**真正值得关注和游玩**的游戏（最终精选 4~8 款，宁缺毋滥）。

**核心入选标准（按优先级排序）**：
1. **质量与好评优先**：游戏本身玩法扎实、有创意或完成度高（原则上 Steam 好评率 ≥ 80% 或 MC/OC 媒体均分 ≥ 80）。
2. **重磅 3A / 知名大厂 / 经典 IP 新作**：体量大、关注度极高（小黑盒关注数通常 > 3万）的主流大作。
3. **口碑爆棚的独立佳作**：虽非大厂出品，但玩法机制独特、美术/叙事有辨识度，且玩家真实口碑极佳的独立黑马。
4. **一票否决**：粗制滥造、换皮模拟器、AI 劣质游戏，以及**虽然关注度高但首发彻底翻车（Steam 好评率 < 70% 且差评集中在恶性 Bug/优化灾难/内容极度缩水）的作品，一律直接淘汰，不要出现在最终列表中**。

# 一、 联网检索与核验规则（硬性要求）
1. **科学初筛（锁定 10~15 款候选去搜索）**：
   - 必查小黑盒关注数 **≥ 10,000** 的所有高关注游戏；
   - 精选关注数在 **4,000 ~ 10,000** 之间，但玩法标签独特或属于知名工作室/精神续作的潜力独立游戏；
   - 若遇到「知名老游戏名称 + 怪异标签 + 新 AppID」的词条，必为平台抓取错乱或碰瓷游戏，核实后直接剔除。
2. **精准搜索锚点**：
   - 依次检索 `游戏名 + Steam 好评率/评测`、`游戏名 + Metacritic / OpenCritic`。中文名搜不到或重名时，**必须使用清单中的 `Steam AppID` 或英文原名**检索。
3. **特殊身份识别**：
   - **EA 转 1.0 正式版**（特征：评测数达数千上万）：必须注明「1.0正式版」，且重点核查正式版更新后的近期口碑。
   - **重制 / 移植 / DLC**：必须注明身份，重点核查移植优化与诚意。
   - **周末刚发售/未解锁新作**（周五至周日发售，评测数 < 50）：不因评测少而漏掉好游，结合 Demo 试玩口碑、开发商履历与媒体先行分判断，并明确标注「刚解锁样本少」。
4. **数据防幻觉铁律**：
   - 严禁编造评分，严禁输出 `53%~66%` 这类模糊区间。
   - 只标注原始评分平台（Steam / MC / OC / IGN），严禁将二手资讯网（如游民星空、Game*Spark）写为数据来源。
   - 若 Steam 全球总评与简中区评价差距过大（差值 > 15%），必须同时点明简中好评率及原因（如汉化差、缺中文、定价问题）。

# 二、 输出格式（严格执行）
- **禁止**输出一级标题（`#`）、开场白、总结语、避雷板块、表格或代码块。
- 仅输出最终入选的游戏列表，按**「综合推荐度（质量+关注度）」从高到低**排列。
- 每款游戏严格包含以下四个要素：`[游戏名] + [发售日期] + [游戏类型和玩法简介] + [评价/反馈/好评]`，具体排版格式如下：

**1. 〈游戏中文名 英文原名〉｜ 发售日期：MM-DD（平台，注明首发 / 1.0正式版 / 抢先体验 / 重制版）**
- **类型与玩法**：用 1~2 句地道老玩家语言，讲清核心品类、核心玩法循环，以及它最吸引人的创新点或爽点（拒绝复制商店套话）。
- **评价与反馈**：列出硬数据（Steam 好评率 xx%［约 N 篇评测］｜ MC/OC 均分 xx［N 家媒体，无则略过］）+ 提炼玩家真实反馈（夸什么、有什么小门槛或槽点、适合哪类玩家）。

# 三、 待分析数据（本周发售清单）
{{在此处填入本周新游清单}}
"""

AI_DATA_PLACEHOLDER = "{{在此处填入本周新游清单}}"

_TRIM_RE = re.compile(r"[ \t]+\n")


def build_ai_prompt(digest: str) -> str:
    """把「本周新游清单」填进提示词占位符。

    - 清单为空时占位符替换为空串（模板仍完整，便于排障）；
    - 清单超长时按 `AI_REVIEW_MAX_INPUT_CHARS` 截断并标注，避免输入框塞爆。
    """
    body = (digest or "").strip()
    if AI_REVIEW_MAX_INPUT_CHARS and len(body) > AI_REVIEW_MAX_INPUT_CHARS:
        body = body[: AI_REVIEW_MAX_INPUT_CHARS].rstrip() + "\n…（清单过长，已截断）"
    if AI_DATA_PLACEHOLDER in AI_REVIEW_PROMPT:
        return AI_REVIEW_PROMPT.replace(AI_DATA_PLACEHOLDER, body)
    return AI_REVIEW_PROMPT + body


def clean_answer(text: str) -> str:
    """修剪 AI 回答：归一化换行、去多余空行、限制长度（避免撑爆消息）。"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _TRIM_RE.sub("\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if AI_REVIEW_MAX_CHARS and len(s) > AI_REVIEW_MAX_CHARS:
        s = s[: AI_REVIEW_MAX_CHARS].rstrip() + "…"
    return s


def _extract_peer_answer(meta: dict):
    """建一个把 aisearch 返回值 `(created, answer)` 转成文本的提取器。

    **不猜对方语义**：`created` 只是「是否新建会话」而不是成功与否；
    成功与否看是否抛异常（由 `ask_peer_text` 统一兜住）。返回值不是二元组时退化处理，
    兼容对方未来可能的签名变化。
    """

    def _extract(ret: object) -> str:
        if isinstance(ret, (tuple, list)) and len(ret) >= 2:
            meta["created"] = bool(ret[0])
            return str(ret[1] or "")
        if isinstance(ret, str):
            return ret
        logger.warning(f"[XhhCalendar] 意外的跨插件返回值类型：{type(ret).__name__}")
        return ""

    return _extract


async def ask_ai_review(
    context,
    digest: str,
    *,
    timeout: float | None = None,
    plugin_name: str | None = None,
) -> str:
    """把「筛选要求 + 本周新游清单」交给 aisearch，返回 AI 推荐正文。

    失败（未安装/未激活/未登录/超时/异常/空回复）一律返回空串，只记日志 ——
    调用方照常发出自己的日历回复。
    """
    text = (digest or "").strip()
    if not text:
        return ""

    name = plugin_name or AI_REVIEW_PLUGIN
    limit = timeout if timeout is not None else AI_REVIEW_TIMEOUT
    prompt = build_ai_prompt(text)
    meta: dict = {}

    logger.info(
        f"[XhhCalendar] 请求 AI 精选：{name}.{AI_REVIEW_METHOD}"
        f"（提示词 {len(prompt)} 字，超时 {limit:.0f}s）"
    )
    answer, why = await ask_peer_text(
        context,
        name,
        AI_REVIEW_METHOD,
        prompt,
        images=[],
        timeout=limit,
        extract=_extract_peer_answer(meta),
    )
    if not answer:
        logger.warning(f"[XhhCalendar] AI 精选跳过：{why}")
        return ""

    cleaned = clean_answer(answer)
    if not cleaned:
        logger.warning(f"[XhhCalendar] AI 精选返回空内容（新建会话={meta.get('created')}）")
        return ""

    # 善后：替对方重置会话空闲计时器，否则我们使用的会话不会走它自己的空闲销毁
    inst, _ = resolve_peer(context, name)
    if inst is not None:
        arm_peer_idle_timer(inst)

    logger.info(
        f"[XhhCalendar] AI 精选成功：{len(cleaned)} 字符"
        f"（新建会话={meta.get('created')}，上限 {limit:.0f}s）"
    )
    return cleaned
