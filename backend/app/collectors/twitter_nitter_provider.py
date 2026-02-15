"""
Nitter 镜像站采集提供者

通过 Playwright 无头浏览器访问 Nitter 镜像站采集推文数据。
Nitter 页面结构简单、无需登录，作为 twscrape 不可用时的首选降级方案。

降级链路: twscrape → Nitter(Playwright) → x.com(Playwright)
"""

import asyncio
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# Nitter 镜像站列表，按优先级排序
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.cz",
]

# 单次采集上限（移除硬性 500 限制，改为由翻页能力决定实际数量）
MAX_NITTER_LIMIT = 100000

# 最大滚动/翻页尝试次数（大幅增加以支持更多数据）
MAX_PAGE_ATTEMPTS = 200

# Cloudflare JS 挑战等待时间（秒）
CF_CHALLENGE_WAIT = 8


class NitterProvider:
    """Nitter 镜像站采集提供者

    通过 Playwright 访问 Nitter 镜像站搜索推文。
    Nitter 不需要登录，页面结构简单，解析稳定。
    Playwright 可以通过 Cloudflare JS 挑战。
    """

    def __init__(self, proxy: Optional[str] = None) -> None:
        """初始化 Nitter 提供者

        Args:
            proxy: HTTP 代理地址（可选）
        """
        self._proxy = proxy
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        """确保浏览器实例已启动"""
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            launch_args = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if self._proxy:
                launch_args["proxy"] = {"server": self._proxy}
            self._browser = await self._playwright.chromium.launch(**launch_args)

    async def _find_working_instance(self, context) -> Optional[str]:
        """探测可用的 Nitter 镜像站

        逐个尝试镜像站，返回第一个能正常访问的实例 URL。

        Args:
            context: Playwright 浏览器上下文

        Returns:
            可用的镜像站 URL，全部不可用时返回 None
        """
        for instance_url in NITTER_INSTANCES:
            page = await context.new_page()
            try:
                test_url = f"{instance_url}/search?q=test&f=tweets"
                resp = await page.goto(test_url, wait_until="domcontentloaded", timeout=15000)

                # 等待 Cloudflare JS 挑战完成
                await asyncio.sleep(CF_CHALLENGE_WAIT)

                # 检查是否还在 Cloudflare 挑战页
                title = await page.title()
                if "just a moment" in title.lower() or "attention required" in title.lower():
                    logger.warning("Nitter 镜像站 %s 被 Cloudflare 拦截", instance_url)
                    continue

                # 检查页面是否有推文内容
                content = await page.content()
                if "timeline-item" in content or "tweet-body" in content or "tweet-content" in content:
                    logger.info("Nitter 镜像站可用: %s", instance_url)
                    return instance_url

                logger.warning("Nitter 镜像站 %s 无推文内容", instance_url)
            except Exception as e:
                logger.warning("Nitter 镜像站 %s 不可用: %s", instance_url, e)
            finally:
                await page.close()

        return None

    async def search(
        self,
        keyword: str,
        limit: int,
    ) -> AsyncGenerator[RawPost, None]:
        """通过 Nitter 镜像站搜索推文，逐条 yield RawPost

        Args:
            keyword: 搜索关键词
            limit: 采集上限（最大 500）
        """
        effective_limit = min(limit, MAX_NITTER_LIMIT)
        logger.info("Nitter 采集开始: keyword=%s, limit=%d", keyword, effective_limit)

        await self._ensure_browser()

        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        try:
            # 探测可用镜像站
            instance_url = await self._find_working_instance(context)
            if not instance_url:
                raise RuntimeError("所有 Nitter 镜像站均不可用")

            # 开始采集
            count = 0
            page_num = 0
            cursor = ""
            seen_ids: set[str] = set()

            while count < effective_limit and page_num < MAX_PAGE_ATTEMPTS:
                page = await context.new_page()
                try:
                    url = f"{instance_url}/search?q={keyword}&f=tweets"
                    if cursor:
                        url += f"&cursor={cursor}"

                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(CF_CHALLENGE_WAIT if page_num == 0 else random.uniform(1.5, 3.0))

                    # 检查 Cloudflare
                    title = await page.title()
                    if "just a moment" in title.lower():
                        logger.warning("Nitter: Cloudflare 挑战未通过，等待更长时间")
                        await asyncio.sleep(CF_CHALLENGE_WAIT)

                    # 解析推文
                    items = await page.query_selector_all(".timeline-item")
                    if not items:
                        # 尝试其他选择器
                        items = await page.query_selector_all(".tweet-body")
                    if not items:
                        items = await page.query_selector_all("[class*='tweet']")

                    if not items:
                        logger.info("Nitter: 第 %d 页无推文，停止采集", page_num + 1)
                        break

                    new_count = 0
                    for item in items:
                        if count >= effective_limit:
                            break
                        post = await self._parse_nitter_item(item, instance_url, seen_ids)
                        if post is not None:
                            seen_ids.add(post.external_id)
                            count += 1
                            new_count += 1
                            yield post

                    if new_count == 0:
                        logger.info("Nitter: 第 %d 页无新推文，停止采集", page_num + 1)
                        break

                    # 获取下一页游标
                    next_cursor = await self._get_next_cursor(page)
                    if not next_cursor or next_cursor == cursor:
                        logger.info("Nitter: 无更多页面")
                        break
                    cursor = next_cursor
                    page_num += 1

                finally:
                    await page.close()

            logger.info("Nitter 采集完成: %d 条", count)

        finally:
            await context.close()

    @staticmethod
    async def _parse_nitter_item(
        item, instance_url: str, seen_ids: set[str],
    ) -> Optional[RawPost]:
        """解析 Nitter 页面中的单条推文元素

        Args:
            item: Playwright 页面元素
            instance_url: 当前使用的 Nitter 镜像站 URL
            seen_ids: 已见过的 external_id 集合

        Returns:
            解析后的 RawPost，无效数据返回 None
        """
        try:
            # 提取推文内容
            content_el = await item.query_selector(".tweet-content, .media-body")
            content = await content_el.inner_text() if content_el else ""
            if not content.strip():
                return None

            # 提取作者
            author = "unknown"
            author_el = await item.query_selector(".username, .tweet-header a")
            if author_el:
                author_text = await author_el.inner_text()
                author = author_text.strip().lstrip("@")

            # 提取链接和 external_id
            external_id = ""
            tweet_url = ""
            link_el = await item.query_selector("a.tweet-link, a[href*='/status/']")
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    m = re.search(r"/status/(\d+)", href)
                    if m:
                        external_id = m.group(1)
                    if href.startswith("/"):
                        tweet_url = f"https://x.com{href}"
                    else:
                        tweet_url = href.replace(instance_url, "https://x.com")

            if not external_id:
                # 尝试从其他属性获取 ID
                outer_html = await item.evaluate("el => el.outerHTML")
                m = re.search(r"/status/(\d+)", outer_html)
                if m:
                    external_id = m.group(1)
                else:
                    external_id = str(uuid.uuid4())

            if external_id in seen_ids:
                return None

            # 提取时间戳
            timestamp = datetime.now(timezone.utc)
            time_el = await item.query_selector("time, .tweet-date a")
            if time_el:
                title_attr = await time_el.get_attribute("title")
                if title_attr:
                    try:
                        # Nitter 时间格式: "Feb 13, 2026 · 10:30 PM UTC"
                        clean = title_attr.replace(" · ", " ").replace(" UTC", "")
                        timestamp = datetime.strptime(clean, "%b %d, %Y %I:%M %p")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass

            # 提取互动数据
            likes = await _extract_stat(item, ".icon-heart, .tweet-stat .icon-heart")
            retweets = await _extract_stat(item, ".icon-retweet, .tweet-stat .icon-retweet")
            replies = await _extract_stat(item, ".icon-comment, .tweet-stat .icon-comment")

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.TWITTER,
                external_id=external_id,
                title=None,
                content=content.strip(),
                author=author,
                url=tweet_url,
                timestamp=timestamp,
                likes=likes,
                comments=replies,
                shares=retweets,
            )
        except Exception as e:
            logger.warning("Nitter: 解析推文失败: %s", e)
            return None

    @staticmethod
    async def _get_next_cursor(page) -> Optional[str]:
        """从页面中提取下一页游标

        Args:
            page: Playwright 页面对象

        Returns:
            下一页游标字符串，无更多页面时返回 None
        """
        try:
            # Nitter 的 "Load more" 链接包含 cursor 参数
            show_more = await page.query_selector(".show-more a, a.show-more")
            if show_more:
                href = await show_more.get_attribute("href")
                if href:
                    m = re.search(r"cursor=([^&]+)", href)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return None

    async def close(self) -> None:
        """释放浏览器资源"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Nitter 提供者已关闭")


async def _extract_stat(item, selector: str) -> int:
    """从推文元素中提取互动统计数字

    Args:
        item: Playwright 页面元素
        selector: CSS 选择器

    Returns:
        统计数字，解析失败返回 0
    """
    try:
        el = await item.query_selector(selector)
        if el:
            parent = await el.evaluate_handle("el => el.parentElement")
            text = await parent.inner_text()
            text = text.strip().replace(",", "")
            if text and text.isdigit():
                return int(text)
    except Exception:
        pass
    return 0
