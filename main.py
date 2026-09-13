import asyncio
import logging
import os

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .core.config import QR_FILE, AuthError
from .core.scraper_core import XhhScraperCore
from .core.login_core import CloakAuthenticator, LoginTaskState
from .core.calendar_core import CalendarError, CoverCollage, XhhCalendarCore
from .core.calendar_format import format_month_markdown, format_week_markdown

logger = logging.getLogger("astrbot")


@register("xhhnews", "You", "小黑盒社区热帖抓取与推送插件", "1.0.0")
class XhhNewsPlugin(Star):

    def __init__(self, context: Context):
        super().__init__(context)
        self.scraper = XhhScraperCore()
        self.calendar = XhhCalendarCore()

    async def _try_send_with_keyboard(
        self, event: AstrMessageEvent, text: str, keyboard: dict
    ) -> bool:
        """尝试在 QQ 官方平台发送带键盘按钮的 Markdown 消息，成功返回 True。"""
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
            logger.warning(f"[XhhNews] 键盘消息发送失败，回退普通消息: {e}")
        return False

    @filter.command("hb", alias={"heybox"})
    async def fetch_command(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """抓取主页热帖 TOP 5。"""
        try:
            posts = await self.scraper.fetch_posts(scroll_times=6)

            # 1. 下载封面并拼接为一张图，发送图片
            merged_path = await self.scraper.merge_covers(posts, top_n=5)
            if merged_path:
                try:
                    yield event.image_result(merged_path)
                finally:
                    if os.path.exists(merged_path):
                        os.remove(merged_path)

            # 2. 构建 Markdown 文本
            md_text = self.scraper.format_top_posts_markdown(posts, top_n=5)

            # 3. 构建键盘按钮
            keyboard = self.scraper.build_keyboard(
                ("🔄 刷新热帖", "/hb"),
                ("❓ 帮助", "/hbhelp"),
            )

            # 4. 尝试发送带键盘的 Markdown 消息（仅 QQ 官方平台生效）
            if not await self._try_send_with_keyboard(event, md_text, keyboard):
                # 非 QQ 平台回退为普通 Markdown 消息
                chain = [Comp.Plain(md_text)]
                result = event.chain_result(chain)
                result.use_markdown(True)
                yield result

        except AuthError:
            yield event.plain_result(
                "⚠️ 未检测到登录凭证，或凭证已失效。\n"
                "👉 请发送 /hblogin 进行扫码登录。"
            )
        except Exception as e:
            yield event.plain_result(f"❌ 抓取失败: {e}")

    @filter.command("hblogin")
    async def login_command(self, event: AstrMessageEvent):
        """扫码登录小黑盒。"""

        yield event.plain_result("🚀 正在生成二维码，请稍候...")

        task_state = LoginTaskState()
        authenticator = CloakAuthenticator()

        # 启动登录任务
        login_task = asyncio.ensure_future(authenticator.execute_login_flow(task_state))

        try:
            # 阶段 1：等待二维码就绪
            try:
                await asyncio.wait_for(task_state.qr_ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                yield event.plain_result("❌ 获取二维码超时，请重试。")
                return

            if task_state.error or not task_state.qr_path:
                yield event.plain_result(f"❌ 获取二维码失败: {task_state.error}")
                return

            yield event.image_result(task_state.qr_path)
            yield event.plain_result("👆 请在 2 分钟内扫码完成登录。")

            # 阶段 2：等待扫码完成
            try:
                await asyncio.wait_for(task_state.done.wait(), timeout=130)
            except asyncio.TimeoutError:
                yield event.plain_result("❌ 登录超时，请重新执行指令。")
                return

            if task_state.success:
                yield event.plain_result(
                    "✅ 扫码成功！凭证已保存。\n"
                    "👉 现在可以发送 /hb 抓取帖子了。"
                )
            else:
                yield event.plain_result("❌ 登录失败，请重新执行指令。")

        except Exception as e:
            yield event.plain_result(f"❌ 登录流程异常: {e}")
        finally:
            login_task.cancel()
            if os.path.exists(QR_FILE):
                os.remove(QR_FILE)

    @filter.command("hbweek")
    async def week_calendar_command(self, event: AstrMessageEvent):
        """本周游戏发售日历（含封面总览图）。"""
        try:
            days = await self.calendar.fetch_week()
            today = self.calendar.today()

            # 1. 封面总览图（按文本中的顺序排列，每行 3 款）
            seen, games = set(), []
            for day in days:
                for g in day.games:
                    key = g.steam_appid or g.name
                    if key not in seen:
                        seen.add(key)
                        games.append(g)

            if games:
                png = await CoverCollage().build(games)
                tmp_path = self._write_temp_png(png) if png else None
                if tmp_path:
                    try:
                        yield event.image_result(tmp_path)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

            # 2. 文字列表
            md_text = format_week_markdown(days, today)
            keyboard = self.scraper.build_keyboard(
                ("🔄 刷新本周", "/hbweek"),
                ("🗓️ 本月日历", "/hbmonth"),
                ("❓ 帮助", "/hbhelp"),
            )

            if not await self._try_send_with_keyboard(event, md_text, keyboard):
                result = event.chain_result([Comp.Plain(md_text)])
                result.use_markdown(True)
                yield result

        except CalendarError as e:
            yield event.plain_result(f"❌ 发售日历抓取失败: {e}")
        except Exception as e:
            logger.exception("[XhhNews] 本周日历异常")
            yield event.plain_result(f"❌ 抓取失败: {e}")

    @filter.command("hbmonth")
    async def month_calendar_command(self, event: AstrMessageEvent, month: str = ""):
        """本月游戏发售日历（名称 + 首个标签，不含封面图）。"""
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
            md_text = format_month_markdown(
                releases, counts, total,
                releases[0].date.year, releases[0].date.month,
                self.calendar.today(),
            )

            keyboard = self.scraper.build_keyboard(
                ("🔄 刷新本月", f"/hbmonth {releases[0].date:%Y-%m}"),
                ("📅 本周日历", "/hbweek"),
                ("❓ 帮助", "/hbhelp"),
            )

            if not await self._try_send_with_keyboard(event, md_text, keyboard):
                result = event.chain_result([Comp.Plain(md_text)])
                result.use_markdown(True)
                yield result

        except CalendarError as e:
            yield event.plain_result(f"❌ 发售日历抓取失败: {e}")
        except Exception as e:
            logger.exception("[XhhNews] 本月日历异常")
            yield event.plain_result(f"❌ 抓取失败: {e}")

    # ── 内部工具 ──

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

    @staticmethod
    def _write_temp_png(data: bytes) -> str | None:
        """把 PNG 字节写入临时文件，返回路径。"""
        import tempfile

        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix="xhhcalendar_"
            )
            tmp.write(data)
            tmp.close()
            return tmp.name
        except Exception as e:
            logger.warning(f"[XhhNews] 写入临时图片失败: {e}")
            return None

    @filter.command("hbhelp")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息。"""

        help_text = (
            "📰 小黑盒热帖插件\n\n"
            "📋 命令列表：\n"
            "• /hb — 抓取主页热帖 TOP 5\n"
            "• /hbpush — 从订阅社区抓取热帖 TOP 8\n"
            "• /hbsub <ID> — 订阅社区（自动获取名称）\n"
            "• /hbunsub <ID> — 取消订阅\n"
            "• /hbsublist — 查看订阅\n"
            "• /hbweek — 本周游戏发售日历（含封面图）\n"
            "• /hbmonth — 本月游戏发售日历\n"
            "• /hbmonth 2026-10 — 指定月份\n"
            "• /hblogin — 扫码登录\n"
            "• /hbhelp — 帮助\n\n"
            "📌 社区ID：社区链接中 /link/ 后的数字\n"
            "例：xiaoheihe.cn/app/topic/link/18745 → 18745\n"
            "📌 发售日历无需登录，数据来自小黑盒 APP 同款接口"
        )
        yield event.plain_result(help_text)

    @filter.command("hbsub")
    async def subscribe_command(self, event: AstrMessageEvent, topic_id: str = ""):
        """订阅指定社区。支持输入社区ID或社区名称搜索。"""

        if not topic_id.strip():
            yield event.plain_result(
                "❌ 请提供社区ID或名称。\n"
                "用法：/hbsub 18745 或 /hbsub 数码硬件"
            )
            return

        query = topic_id.strip()
        group_id = str(event.get_group_id() or event.get_sender_id())

        # 判断是纯数字 ID 还是名称搜索
        if query.isdigit():
            # 直接用 ID 订阅
            topic_name = ""
            try:
                topic_name = await self.scraper.fetch_topic_name(query)
            except Exception:
                pass
            _, msg = self.scraper.add_subscription(group_id, query, topic_name)
            yield event.plain_result(msg)
        else:
            # 按名称搜索社区
            try:
                result = await self.scraper.search_topic(query)
                if result is None:
                    yield event.plain_result(f"❌ 未找到社区「{query}」，请换个关键词试试。")
                    return

                topic_id_found, topic_name = result
                _, msg = self.scraper.add_subscription(group_id, topic_id_found, topic_name)
                yield event.plain_result(msg)
            except AuthError:
                yield event.plain_result("⚠️ 未登录，请先发送 /hblogin 扫码登录。")
            except Exception as e:
                yield event.plain_result(f"❌ 搜索失败: {e}")

    @filter.command("hbunsub")
    async def unsubscribe_command(self, event: AstrMessageEvent, topic_id: str = ""):
        """取消订阅指定社区。"""

        if not topic_id.strip():
            yield event.plain_result("❌ 请提供社区ID。\n用法：/hbunsub 18745")
            return

        topic_id = topic_id.strip()
        group_id = str(event.get_group_id() or event.get_sender_id())
        success, msg = self.scraper.remove_subscription(group_id, topic_id)
        yield event.plain_result(msg)

    @filter.command("hbsublist")
    async def list_subscriptions_command(self, event: AstrMessageEvent):
        """查看当前群的订阅列表。"""

        group_id = str(event.get_group_id() or event.get_sender_id())
        subs = self.scraper.get_subscriptions(group_id)

        if not subs:
            yield event.plain_result("📭 当前没有订阅。\n使用 /hbsub <社区ID> 添加订阅。")
            return

        lines = ["📋 当前订阅的社区：\n"]
        for i, (tid, tname) in enumerate(subs.items(), 1):
            name_display = f" {tname}" if tname else ""
            lines.append(f"{i}.{name_display} (ID: {tid})")
            lines.append(f"   🔗 https://www.xiaoheihe.cn/app/topic/link/{tid}\n")
        lines.append(f"共 {len(subs)} 个订阅")
        yield event.plain_result("\n".join(lines))

    @filter.command("hbpush")
    async def push_command(self, event: AstrMessageEvent):
        """从订阅社区抓取热帖并推送 TOP 8。"""
        group_id = str(event.get_group_id() or event.get_sender_id())
        subs = self.scraper.get_subscriptions(group_id)

        if not subs:
            yield event.plain_result("📭 当前没有订阅。\n使用 /hbsub <社区ID> 添加订阅。")
            return

        try:
            posts = await self.scraper.fetch_subscribed_posts(group_id)

            if not posts:
                yield event.plain_result("😅 订阅社区暂无帖子。")
                return

            # 1. 下载封面并拼接为一张图
            merged_path = await self.scraper.merge_covers(posts, top_n=8)
            if merged_path:
                try:
                    yield event.image_result(merged_path)
                finally:
                    if os.path.exists(merged_path):
                        os.remove(merged_path)

            # 2. 构建 Markdown 文本
            md_text = self.scraper.format_top_posts_markdown(posts, top_n=8)

            # 3. 构建键盘按钮
            keyboard = self.scraper.build_keyboard(
                ("🔄 刷新推送", "/hbpush"),
                ("📋 订阅列表", "/hbsublist"),
                ("❓ 帮助", "/hbhelp"),
            )

            # 4. 尝试发送带键盘的 Markdown 消息
            if not await self._try_send_with_keyboard(event, md_text, keyboard):
                chain = [Comp.Plain(md_text)]
                result = event.chain_result(chain)
                result.use_markdown(True)
                yield result

        except AuthError:
            yield event.plain_result(
                "⚠️ 未检测到登录凭证，或凭证已失效。\n"
                "👉 请发送 /hblogin 进行扫码登录。"
            )
        except Exception as e:
            yield event.plain_result(f"❌ 抓取失败: {e}")

    async def terminate(self):
        """插件卸载/停用时调用。"""
        pass
