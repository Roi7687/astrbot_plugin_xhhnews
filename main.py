import logging

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .core.calendar_core import CalendarError, XhhCalendarCore
from .core.calendar_format import format_month_markdown, format_week_markdown

logger = logging.getLogger("astrbot")


@register("xhhnews", "Roi", "小黑盒游戏发售日历", "1.1.0")
class XhhCalendarPlugin(Star):
    """小黑盒「游戏发售日历」查询插件。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.calendar = XhhCalendarCore()

    # ── 命令 ──

    @filter.command("hbweek")
    async def week_command(self, event: AstrMessageEvent):
        """本周游戏发售日历。"""
        try:
            days = await self.calendar.fetch_week()
            md_text = format_week_markdown(days, self.calendar.today())
            result = await self._reply(event, md_text, [
                ("🔄 刷新本周", "/hbweek"),
                ("🗓️ 本月日历", "/hbmonth"),
                ("❓ 帮助", "/hbhelp"),
            ])
            if result is not None:
                yield result
        except CalendarError as e:
            yield event.plain_result(f"❌ 发售日历抓取失败: {e}")
        except Exception as e:
            logger.exception("[XhhCalendar] 本周日历异常")
            yield event.plain_result(f"❌ 抓取失败: {e}")

    @filter.command("hbmonth")
    async def month_command(self, event: AstrMessageEvent, month: str = ""):
        """本月（或指定月份）游戏发售日历。"""
        try:
            year = month_num = None
            arg = (month or "").strip()
            if arg:
                parsed = self._parse_month_arg(arg)
                if parsed is None:
                    yield event.plain_result(
                        "❌ 月份格式不对。\n用法：/hbmonth 或 /hbmonth 2026-10"
                    )
                    return
                year, month_num = parsed

            releases, counts, total = await self.calendar.fetch_month(year, month_num)
            target = releases[0].date
            md_text = format_month_markdown(
                releases, counts, total, target.year, target.month,
                self.calendar.today(),
            )
            result = await self._reply(event, md_text, [
                ("🔄 刷新本月", f"/hbmonth {target:%Y-%m}"),
                ("📅 本周日历", "/hbweek"),
                ("❓ 帮助", "/hbhelp"),
            ])
            if result is not None:
                yield result
        except CalendarError as e:
            yield event.plain_result(f"❌ 发售日历抓取失败: {e}")
        except Exception as e:
            logger.exception("[XhhCalendar] 本月日历异常")
            yield event.plain_result(f"❌ 抓取失败: {e}")

    @filter.command("hbhelp")
    async def help_command(self, event: AstrMessageEvent):
        """显示帮助。"""
        yield event.plain_result(
            "🎮 小黑盒游戏发售日历\n\n"
            "📋 命令列表：\n"
            "• /hbweek — 本周发售日历\n"
            "• /hbmonth — 本月发售日历\n"
            "• /hbmonth 2026-10 — 指定月份\n"
            "• /hbhelp — 帮助\n\n"
            "📌 数据与小黑盒 APP「游戏发售日历」同源，无需登录\n"
            "📌 月份参数也支持 2026/10、2026.10、10 等写法"
        )

    # ── 内部工具 ──

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

            if type_name == "GroupMessage":
                await bot.api.post_group_message(
                    group_openid=raw.group_openid,
                    msg_type=2,                      # Markdown 消息
                    markdown={"content": text},
                    keyboard=keyboard,
                    msg_id=msg_id,
                    msg_seq=1,
                )
                return True
            elif type_name == "C2CMessage":
                await bot.api.post_c2c_message(
                    openid=raw.author.user_openid,
                    msg_type=2,
                    markdown={"content": text},
                    keyboard=keyboard,
                    msg_id=msg_id,
                    msg_seq=1,
                )
                return True
        except Exception as e:
            logger.warning(f"[XhhCalendar] 键盘消息发送失败，回退普通消息: {e}")
        return False

    @staticmethod
    def _parse_month_arg(arg: str) -> tuple[int, int] | None:
        """解析「2026-10」「2026/10」「2026.10」「10」等月份写法。"""
        arg = arg.strip().replace("/", "-").replace(".", "-")
        if arg.isdigit():
            m = int(arg)
            return (None, m) if 1 <= m <= 12 else None

        parts = arg.split("-")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            y, m = int(parts[0]), int(parts[1])
            if 1970 <= y <= 2999 and 1 <= m <= 12:
                return y, m
        return None

    async def terminate(self):
        """插件卸载/停用时调用。"""
        pass


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
