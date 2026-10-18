import logging
import random

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

from .core.ai_review import ask_ai_review
from .core.calendar_core import CalendarError, XhhCalendarCore
from .core.calendar_format import (
    format_week_digest,
    format_week_review_fallback,
    format_week_review_markdown,
)
from .core.config import (
    AI_REVIEW_ENABLED,
    AI_REVIEW_PLUGIN,
    AI_REVIEW_PROGRESS_HINT,
    AI_REVIEW_TIMEOUT,
)
from .core.peer_plugin import resolve_peer

logger = logging.getLogger("astrbot")


@register("xhhnews", "Roi", "小黑盒新游速报", "1.4.0")
class XhhCalendarPlugin(Star):
    """小黑盒新游速报插件：/hbnews 由 AI 联网核验本周新游并精选推荐。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.calendar = XhhCalendarCore()
        self._ai_selfcheck(strict=False)     # 加载即自检一次（便于热重载后立刻排障）

    # ── 跨插件自检 ──

    def _ai_selfcheck(self, *, strict: bool) -> None:
        """检查 AI 精选的目标插件（astrbot_plugin_aisearch）是否可解析。

        strict=False（插件加载时）：解析不到只记 DEBUG（可能只是加载顺序问题）；
        strict=True（AstrBot 完全加载后）：解析不到记 WARNING。
        """
        if not AI_REVIEW_ENABLED:
            logger.info("[XhhCalendar] AI 精选已关闭（AI_REVIEW_ENABLED=False）")
            return
        try:
            inst, why = resolve_peer(self.context, AI_REVIEW_PLUGIN)
        except Exception:  # noqa: BLE001
            logger.exception("[XhhCalendar] AI 精选自检异常")
            return
        if inst is None:
            msg = f"[XhhCalendar] AI 精选不可用：{why}（新游速报将降级为本周完整日历）"
            (logger.warning if strict else logger.debug)(msg)
        else:
            logger.info(
                f"[XhhCalendar] AI 精选可用：{AI_REVIEW_PLUGIN} → {type(inst).__name__}"
                f"（超时上限 {AI_REVIEW_TIMEOUT:.0f}s；对方为浏览器自动化，"
                f"单次约 20~90s）"
            )

    @filter.on_astrbot_loaded()
    async def _check_ai_review_plugin(self):
        """AstrBot 加载完成后复查一次（此时代码里所有插件都已注册）。"""
        self._ai_selfcheck(strict=True)

    # ── 命令 ──

    @filter.command("hbnews")
    async def news_command(self, event: AstrMessageEvent):
        """AI 联网核验本周新游，精选 4~8 款值得玩的。"""
        if not AI_REVIEW_ENABLED:
            yield event.plain_result("❌ AI 精选已关闭（AI_REVIEW_ENABLED=False）。")
            return
        try:
            days = await self.calendar.fetch_week()
            today = self.calendar.today()
            total = sum(len(d.games) for d in days)
            if total == 0:
                yield event.plain_result("📭 本周暂无发售数据，稍后再试。")
                return
            digest = format_week_digest(days, today)

            # AI 链路要等 20~90 秒（浏览器自动化 + 联网搜索），先给用户一个明确反馈
            if AI_REVIEW_PROGRESS_HINT:
                await self._send_progress(
                    event,
                    f"🔎 本周共 {total} 款新游，正在联网核验口碑与评分"
                    f"（约 30~90 秒，请稍候）…",
                )

            review = await ask_ai_review(self.context, digest)
            # 提示词已规定输出格式，这里原样输出；AI 不可用时降级为完整周历
            md_text = (
                format_week_review_markdown(review)
                if review
                else format_week_review_fallback(days, today)
            )
            result = await self._reply(event, md_text, [
                ("🔄 重新核验", "/hbnews"),
                ("❓ 帮助", "/hbhelp"),
            ])
            if result is not None:
                yield result
        except CalendarError as e:
            yield event.plain_result(f"❌ 发售日历抓取失败: {e}")
        except Exception as e:
            logger.exception("[XhhCalendar] 新游速报异常")
            yield event.plain_result(f"❌ 新游速报失败: {e}")

    @filter.command("hbhelp")
    async def help_command(self, event: AstrMessageEvent):
        """显示帮助。"""
        yield event.plain_result(
            "🎮 小黑盒新游速报\n\n"
            "📋 命令列表：\n"
            "• /hbnews — AI 联网核验本周新游，精选 4~8 款值得玩的（约 30~90 秒）\n"
            "• /hbhelp — 帮助\n\n"
            "📌 数据与小黑盒 APP「游戏发售日历」同源，无需登录\n"
            "📌 偏好 3A 大作与高口碑独立游戏，筛掉首发翻车、换皮与粗制滥造，宁缺毋滥\n"
            "📌 AI 精选由 aisearch 插件联网检索生成；不可用时自动降级为本周完整日历"
        )

    # ── 内部工具 ──

    async def _send_progress(self, event: AstrMessageEvent, text: str) -> None:
        """先发一条「正在处理」提示（AI 链路要等几十秒，避免用户以为没反应）。

        用 event.send 立即发送而不是 yield（yield 的结果要等 handler 结束、
        由 RespondStage 统一发出，起不到「先告诉用户」的作用）。失败只记 DEBUG，
        绝不影响主流程。
        """
        try:
            await event.send(MessageChain().message(text))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[XhhCalendar] 进度提示发送失败（忽略）: {e}")

    async def _reply(self, event: AstrMessageEvent, md_text: str, buttons: list):
        """优先发带键盘按钮的 Markdown（QQ 官方），否则回退普通 Markdown。"""
        keyboard = _build_keyboard(*buttons)
        if await self._try_send_with_keyboard(event, md_text, keyboard):
            return None

        result = event.chain_result([Comp.Plain(md_text)])
        result.use_markdown(True)
        return result

    async def _try_send_with_keyboard(
        self, event: AstrMessageEvent, text: str, keyboard: dict
    ) -> bool:
        """尝试发送带键盘按钮的 Markdown 消息，成功返回 True。"""
        try:
            bot = getattr(event, "bot", None)
            raw = getattr(event.message_obj, "raw_message", None)
            if not bot or not raw:
                return False

            type_name = type(raw).__name__
            msg_id = event.message_obj.message_id
            # msg_seq 必须与同一 msg_id 下的其他被动回复不同（/hbnews 会先发一条进度提示），
            # AstrBot 自己的 QQ 适配器也是用随机值，这里保持一致。
            msg_seq = random.randint(1, 10000)

            if type_name == "GroupMessage":
                await bot.api.post_group_message(
                    group_openid=raw.group_openid,
                    msg_type=2,                      # Markdown 消息
                    markdown={"content": text},
                    keyboard=keyboard,
                    msg_id=msg_id,
                    msg_seq=msg_seq,
                )
                return True
            elif type_name == "C2CMessage":
                await bot.api.post_c2c_message(
                    openid=raw.author.user_openid,
                    msg_type=2,
                    markdown={"content": text},
                    keyboard=keyboard,
                    msg_id=msg_id,
                    msg_seq=msg_seq,
                )
                return True
        except Exception as e:
            logger.warning(f"[XhhCalendar] 键盘消息发送失败，回退普通消息: {e}")
        return False


def _build_keyboard(*buttons: tuple) -> dict:
    """构建 QQ 键盘按钮数据，参数为 (label, data) 元组列表。"""
    return {
        "content": {
            "rows": [{
                "buttons": [
                    {
                        "id": f"btn_{i}",
                        "render_data": {
                            "label": label,
                            "visited_label": label,
                            "style": 1,
                        },
                        "action": {
                            "type": 2,  # type=2 表示指令按钮
                            "permission": {"type": 2},
                            "data": data,
                            "at_bot_show_channel_list": False,
                        },
                    }
                    for i, (label, data) in enumerate(buttons)
                ],
            }],
        },
    }
