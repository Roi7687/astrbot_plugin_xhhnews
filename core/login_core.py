import asyncio
import logging
import os

from cloakbrowser import launch_context_async

from .config import AUTH_STATE_FILE, COMMUNITY_URL, QR_FILE, AuthError

logger = logging.getLogger("astrbot")

# 登录页面 URL 与选择器
LOGIN_BTN_SELECTOR = "div.view-header__right.treble a.user-box__login"
QR_CODE_SELECTOR = "canvas#login-qrcode"
USER_AVATAR_SELECTOR = "a.user-box__login"  # 登录后此元素会变化


class LoginTaskState:
    """登录线程与 async 之间的信号桥"""
    def __init__(self):
        self.qr_path = None
        self.qr_ready = asyncio.Event()
        self.success = False
        self.done = asyncio.Event()
        self.error = None


class CloakAuthenticator:
    """小黑盒登录认证器"""

    async def execute_login_flow(self, task_state: LoginTaskState):
        """异步登录全流程：打开页面 → 点击登录 → 截取二维码 → 等待扫码 → 保存凭证。"""
        context = None
        try:
            logger.info("🚀 [LoginCore] 正在启动登录实例...")
            context = await launch_context_async(
                headless=True,
                humanize=True,
                viewport={"width": 1920, "height": 1080},
            )

            page = await context.new_page()
            await page.goto(COMMUNITY_URL)
            await page.wait_for_load_state("networkidle")

            # 1. 点击登录按钮
            logger.info("🔍 [LoginCore] 正在定位登录按钮...")
            login_btn = page.locator(LOGIN_BTN_SELECTOR)
            await login_btn.wait_for(state="visible", timeout=15000)
            await login_btn.click()

            # 2. 等待二维码出现并截图
            logger.info("⏳ [LoginCore] 等待二维码渲染...")
            qr_canvas = page.locator(QR_CODE_SELECTOR)
            await qr_canvas.wait_for(state="visible", timeout=10000)
            await page.wait_for_timeout(1500)  # 等待二维码完全渲染

            await qr_canvas.screenshot(path=QR_FILE)
            logger.info("📸 [LoginCore] 二维码截图成功！")

            # 信号 1：二维码就绪
            task_state.qr_path = QR_FILE
            task_state.qr_ready.set()

            # 3. 等待扫码完成（轮询检测登录状态变化）
            logger.info("⏳ [LoginCore] 等待用户扫码...")
            for _ in range(120):  # 最多等待 120 秒
                await asyncio.sleep(1)
                try:
                    # 检测登录浮窗是否消失（表示扫码成功）
                    qr_visible = await page.locator(QR_CODE_SELECTOR).is_visible()
                    if not qr_visible:
                        logger.info("✅ [LoginCore] 检测到登录成功！")
                        break
                except Exception:
                    break

            # 4. 保存登录状态
            await page.wait_for_load_state("networkidle", timeout=10000)
            await context.storage_state(path=AUTH_STATE_FILE)
            logger.info(f"💾 [LoginCore] 登录凭证已保存至 {AUTH_STATE_FILE}")

            task_state.success = True

        except Exception as e:
            logger.error(f"❌ [LoginCore] 登录流程异常: {e}")
            task_state.error = e
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            task_state.done.set()
