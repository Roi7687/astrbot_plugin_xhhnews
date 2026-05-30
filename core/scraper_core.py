import asyncio
import logging
import os
import tempfile
from io import BytesIO

import httpx
from PIL import Image as PILImage

from cloakbrowser import launch_context_async

from .config import AUTH_STATE_FILE, COMMUNITY_URL, TOPIC_URL_TEMPLATE, AuthError, load_subscriptions, save_subscriptions

logger = logging.getLogger("astrbot")

EXTRACT_POSTS_JS = """
() => {
    const items = document.querySelectorAll('a.bbs-home__content-item');
    return Array.from(items).map(item => {
        const title = item.querySelector('.bbs-content__title')?.innerText?.trim() || '';
        const summary = item.querySelector('.bbs-content__content')?.innerText?.trim() || '';

        const coverImgs = item.querySelectorAll('.bbs-content__imgs-wrapper .hb-cpt__image-elem');
        const covers = Array.from(coverImgs).map(img => img.src).filter(src => src);

        const tagText = item.querySelector('.content-tag-text')?.innerText?.trim() || '';
        const tagSuffix = item.querySelector('.static-color-suffix-tag span')?.innerText?.trim() || '';
        const tag = tagSuffix ? tagText + tagSuffix : tagText;

        const comments = item.querySelector('.content-list__comment-cnt')?.innerText?.trim() || '0';
        const likes = item.querySelector('.content-list__like-cnt')?.innerText?.trim() || '0';

        const href = item.getAttribute('href') || '';
        const link = href.startsWith('http') ? href : 'https://www.xiaoheihe.cn' + href;

        return { title, summary, covers, tag, comments, likes, link };
    });
}
"""


class XhhScraperCore:
    """小黑盒社区帖子抓取核心，每次调用启动独立浏览器实例。"""

    async def fetch_posts(self, scroll_times: int = 3) -> list[dict]:
        """抓取小黑盒社区帖子列表。"""

        if not os.path.exists(AUTH_STATE_FILE):
            raise AuthError("未找到登录凭证，请先执行登录。")

        context = await launch_context_async(
            headless=True,
            humanize=True,
            storage_state=AUTH_STATE_FILE,
        )

        try:
            page = await context.new_page()
            page.set_default_timeout(120000)      # 全局默认超时 2 分钟
            page.set_default_navigation_timeout(120000)  # 导航超时 2 分钟

            await page.goto(COMMUNITY_URL)
            await page.wait_for_load_state("networkidle", timeout=90000)

            # 等待帖子列表加载
            await page.wait_for_selector("a.bbs-home__content-item", timeout=90000)

            # 滚动加载更多
            for i in range(scroll_times):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            posts = await page.evaluate(EXTRACT_POSTS_JS)
            return posts

        finally:
            await context.close()

    @staticmethod
    def pick_top_posts(posts: list[dict], top_n: int = 3) -> list[dict]:
        """按点赞+评论综合热度排序，取前 N 条。"""

        def _parse_int(s: str) -> int:
            s = s.strip().replace(",", "")
            if s.endswith("万"):
                return int(float(s[:-1]) * 10000)
            try:
                return int(s)
            except ValueError:
                return 0

        scored = []
        for p in posts:
            likes = _parse_int(p.get("likes", "0"))
            comments = _parse_int(p.get("comments", "0"))
            scored.append((likes + comments, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_n]]

    @staticmethod
    async def _download_image(url: str) -> PILImage.Image | None:
        """下载单张图片并返回 PIL Image 对象。"""
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return PILImage.open(BytesIO(resp.content)).convert("RGB")
        except Exception as e:
            logger.warning(f"[ScraperCore] 下载图片失败: {url} - {e}")
            return None

    @staticmethod
    async def merge_covers(posts: list[dict], top_n: int = 3) -> str | None:
        """下载前 N 条帖子的封面图，按 2 行 4 列网格拼接为一张，返回临时文件路径。"""

        top = XhhScraperCore.pick_top_posts(posts, top_n)

        # 收集每条帖子的第一张有效封面 URL
        cover_urls = []
        for post in top:
            for cover in post.get("covers", []):
                if cover and isinstance(cover, str) and cover.startswith(("http://", "https://")):
                    cover_urls.append(cover)
                    break

        if not cover_urls:
            return None

        # 并发下载所有图片
        images = await asyncio.gather(*[XhhScraperCore._download_image(url) for url in cover_urls])
        images = [img for img in images if img is not None]

        if not images:
            return None

        # 网格参数：2 行 4 列
        cols = 4
        rows = 2
        cell_w = 240  # 每格宽度
        cell_h = 135  # 每格高度
        gap = 4

        # 将每张图裁剪为等比例居中后缩放到统一格子大小
        resized = []
        for img in images[: cols * rows]:
            # 按比例缩放再居中裁剪
            ratio = max(cell_w / img.width, cell_h / img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), PILImage.LANCZOS)
            # 居中裁剪
            left = (new_w - cell_w) // 2
            top_px = (new_h - cell_h) // 2
            img = img.crop((left, top_px, left + cell_w, top_px + cell_h))
            resized.append(img)

        actual_rows = (len(resized) + cols - 1) // cols
        canvas_w = cols * cell_w + gap * (cols - 1)
        canvas_h = actual_rows * cell_h + gap * (actual_rows - 1)
        merged = PILImage.new("RGB", (canvas_w, canvas_h), (245, 245, 245))

        for idx, img in enumerate(resized):
            r = idx // cols
            c = idx % cols
            x = c * (cell_w + gap)
            y = r * (cell_h + gap)
            merged.paste(img, (x, y))

        # 保存到临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="xhhnews_")
        merged.save(tmp, format="PNG")
        tmp.close()
        return tmp.name

    @staticmethod
    def format_top_posts_markdown(posts: list[dict], top_n: int = 3) -> str:
        """按热度排序取前 N 条，格式化为 QQ Markdown 文本。"""

        top = XhhScraperCore.pick_top_posts(posts, top_n)
        if not top:
            return "暂无抓取到的帖子。"

        lines = ["# 📰 小黑盒热帖 TOP {}\n".format(len(top))]

        for i, post in enumerate(top, 1):
            lines.append("---\n")
            lines.append(f"## 【{i}】{post['title']}\n")

            if post.get("summary"):
                summary = post["summary"]
                if len(summary) > 120:
                    summary = summary[:120] + "..."
                lines.append(f"> {summary}\n")

            tags = []
            if post.get("tag"):
                tags.append(f"📌 {post['tag']}")
            tags.append(f"💬 {post.get('comments', '0')}")
            tags.append(f"👍 {post.get('likes', '0')}")
            lines.append("  |  ".join(tags) + "\n")

            link = post.get("link", "")
            if link:
                lines.append(f"[🔗 查看原帖]({link})\n")

        return "".join(lines)

    @staticmethod
    def build_keyboard(*buttons: tuple) -> dict:
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

    # ── 订阅管理 ──

    @staticmethod
    def add_subscription(group_id: str, topic_id: str, topic_name: str = "") -> tuple[bool, str]:
        """添加订阅，返回 (是否成功, 提示信息)。"""
        subs = load_subscriptions()
        group_subs = subs.get(group_id, {})

        if topic_id in group_subs:
            return False, f"社区 {topic_id} 已经订阅过了。"

        group_subs[topic_id] = topic_name
        subs[group_id] = group_subs
        save_subscriptions(subs)
        return True, f"✅ 已订阅社区 {topic_name or topic_id}。"

    @staticmethod
    def remove_subscription(group_id: str, topic_id: str) -> tuple[bool, str]:
        """取消订阅，返回 (是否成功, 提示信息)。"""
        subs = load_subscriptions()
        group_subs = subs.get(group_id, {})

        if topic_id not in group_subs:
            return False, f"社区 {topic_id} 未在订阅列表中。"

        name = group_subs.pop(topic_id)
        subs[group_id] = group_subs
        save_subscriptions(subs)
        return True, f"✅ 已取消订阅社区 {name or topic_id}。"

    @staticmethod
    def get_subscriptions(group_id: str) -> dict:
        """获取指定群的订阅列表，返回 {topic_id: topic_name}。"""
        subs = load_subscriptions()
        return subs.get(group_id, {})

    async def fetch_topic_name(self, topic_id: str) -> str:
        """从社区页面抓取社区名称。"""
        url = TOPIC_URL_TEMPLATE.format(topic_id=topic_id)
        context = await launch_context_async(
            headless=True,
            humanize=True,
            storage_state=AUTH_STATE_FILE if os.path.exists(AUTH_STATE_FILE) else None,
        )

        try:
            page = await context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(30000)

            await page.goto(url)
            await page.wait_for_load_state("networkidle", timeout=20000)

            title = await page.title()
            name = title.replace(" - 小黑盒", "").replace(" - 小⿊盒", "").strip()
            return name

        except Exception:
            return ""
        finally:
            await context.close()

    async def search_topic(self, keyword: str) -> tuple[str, str] | None:
        """通过搜索框搜索社区，返回 (topic_id, topic_name) 或 None。"""
        if not os.path.exists(AUTH_STATE_FILE):
            raise AuthError("未找到登录凭证，请先执行登录。")

        context = await launch_context_async(
            headless=True,
            humanize=True,
            storage_state=AUTH_STATE_FILE,
        )

        try:
            page = await context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(30000)

            await page.goto(COMMUNITY_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # 1. 输入关键词并搜索
            search_input = page.locator(".search__input-item")
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.click()
            await search_input.fill(keyword)
            await search_input.press("Enter")
            await page.wait_for_timeout(5000)

            # 2. 点击第一个社区结果
            topic_el = page.locator(".search-result__topic").first
            if not await topic_el.count():
                return None

            await topic_el.click()
            await page.wait_for_timeout(3000)

            # 3. 从跳转后的 URL 提取 topic ID
            import re
            current_url = page.url
            match = re.search(r"/topic/link/(\d+)", current_url)
            if not match:
                logger.warning(f"[ScraperCore] 无法从 URL 提取社区 ID: {current_url}")
                return None

            topic_id = match.group(1)

            # 4. 从页面标题获取社区名
            title = await page.title()
            topic_name = title.replace(" - 小黑盒", "").replace(" - 小⿊盒", "").strip()

            return topic_id, topic_name

        except Exception:
            return None
        finally:
            await context.close()

    async def fetch_topic_posts(self, topic_id: str, scroll_times: int = 2) -> list[dict]:
        """从指定社区抓取帖子列表。"""

        if not os.path.exists(AUTH_STATE_FILE):
            raise AuthError("未找到登录凭证，请先执行登录。")

        url = TOPIC_URL_TEMPLATE.format(topic_id=topic_id)
        context = await launch_context_async(
            headless=True,
            humanize=True,
            storage_state=AUTH_STATE_FILE,
        )

        try:
            page = await context.new_page()
            page.set_default_timeout(120000)
            page.set_default_navigation_timeout(120000)

            await page.goto(url)
            await page.wait_for_load_state("networkidle", timeout=90000)
            await page.wait_for_selector("a.bbs-home__content-item", timeout=90000)

            # 滚动加载更多
            for i in range(scroll_times):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            posts = await page.evaluate(EXTRACT_POSTS_JS)
            return posts

        finally:
            await context.close()

    async def fetch_subscribed_posts(self, group_id: str, scroll_times: int = 2) -> list[dict]:
        """从所有订阅社区抓取帖子，合并返回。"""
        topic_subs = self.get_subscriptions(group_id)
        if not topic_subs:
            return []

        all_posts = []
        for topic_id in topic_subs:
            try:
                posts = await self.fetch_topic_posts(topic_id, scroll_times)
                all_posts.extend(posts)
            except Exception as e:
                logger.warning(f"[ScraperCore] 抓取社区 {topic_id} 失败: {e}")
                continue

        return all_posts
