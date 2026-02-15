"""
Playwright 无头浏览器采集提供者

使用 Playwright + 登录态 Cookie 从 X 平台采集推文数据。
作为 twscrape 不可用时的降级方案。

需求: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

import asyncio
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from backend.app.collectors.twitter_config import CookieManager
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# Playwright 模式单次采集上限（移除硬性限制，由滚动能力决定）
MAX_PLAYWRIGHT_LIMIT = 100000
# 最大滚动尝试次数（大幅增加以支持更多数据）
MAX_SCROLL_ATTEMPTS = 100


class PlaywrightProvider:
    """Playwright 无头浏览器采集提供者

    通过 Playwright 控制 Chromium 浏览器访问 X 搜索页面，
    注入登录态 Cookie 以获取更多搜索结果。
    """

    def __init__(self, cookie_manager: CookieManager) -> None:
        """初始化 Playwright 提供者

        Args:
            cookie_manager: Cookie 管理器实例
        """
        self._cookie_manager = cookie_manager
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        """确保浏览器实例已启动"""
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

    async def search(
        self,
        keyword: str,
        limit: int,
    ) -> AsyncGenerator[RawPost, None]:
        """通过浏览器爬虫搜索推文，逐条 yield RawPost

        Args:
            keyword: 搜索关键词
            limit: 采集上限（最大 500）
        """
        # 强制上限为 500
        effective_limit = min(limit, MAX_PLAYWRIGHT_LIMIT)
        logger.info(
            "Playwright 采集开始: keyword=%s, limit=%d (请求=%d)",
            keyword, effective_limit, limit,
        )

        await self._ensure_browser()

        # 创建浏览器上下文
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0"
            ),
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        # 注入登录态 Cookie
        cookies = self._cookie_manager.load_cookies()
        if cookies and self._cookie_manager.validate_cookies(cookies):
            await context.add_cookies(cookies)
            logger.info("Playwright: 已注入登录态 Cookie")
        else:
            logger.warning("Playwright: Cookie 无效或未配置，使用无登录态模式")

        page = await context.new_page()
        seen_ids: set = set()
        count = 0

        try:
            url = f"https://x.com/search?q={keyword}&src=typed_query&f=live"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2.0, 4.0))

            # 等待推文列表加载
            try:
                await page.wait_for_selector(
                    'article[data-testid="tweet"]', timeout=15000,
                )
            except Exception:
                logger.warning("Playwright: 推文列表加载超时")
                return

            scroll_attempts = 0
            prev_count = 0

            while count < effective_limit and scroll_attempts < MAX_SCROLL_ATTEMPTS:
                elements = await page.query_selector_all(
                    'article[data-testid="tweet"]',
                )

                for el in elements:
                    if count >= effective_limit:
                        break

                    post = await self._parse_element(el, seen_ids)
                    if post is not None:
                        seen_ids.add(post.external_id)
                        count += 1
                        yield post

                # 检测是否有新数据
                if count == prev_count:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0
                prev_count = count

                if count >= effective_limit:
                    break

                # 滚动加载更多
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(random.uniform(2.0, 4.0))

        finally:
            await context.close()

        logger.info("Playwright 采集完成: %d 条", count)

    @staticmethod
    async def _parse_element(el, seen_ids: set) -> Optional[RawPost]:
        """从页面元素解析单条推文

        复用 TwitterCollector._collect_via_scraper 的解析逻辑。

        Args:
            el: Playwright 页面元素（article）
            seen_ids: 已见过的 external_id 集合，用于去重

        Returns:
            解析后的 RawPost，无效数据返回 None
        """
        try:
            # 提取推文内容
            text_el = await el.query_selector('div[data-testid="tweetText"]')
            content = await text_el.inner_text() if text_el else ""
            if not content.strip():
                return None

            # 提取作者
            author_el = await el.query_selector(
                'div[data-testid="User-Name"] a span',
            )
            author = await author_el.inner_text() if author_el else "unknown"

            # 提取链接和 external_id
            link_el = await el.query_selector('a[href*="/status/"]')
            tweet_url = ""
            external_id = str(uuid.uuid4())
            if link_el:
                href = await link_el.get_attribute("href")
                if href and "/status/" in href:
                    tweet_url = (
                        f"https://x.com{href}"
                        if not href.startswith("http")
                        else href
                    )
                    m = re.search(r"/status/(\d+)", href)
                    if m:
                        external_id = m.group(1)

            # 去重检查
            if external_id in seen_ids:
                return None

            # 提取时间戳
            timestamp = datetime.now(timezone.utc)
            time_el = await el.query_selector("time")
            if time_el:
                dt_attr = await time_el.get_attribute("datetime")
                if dt_attr:
                    try:
                        timestamp = datetime.fromisoformat(
                            dt_attr.replace("Z", "+00:00"),
                        )
                    except ValueError:
                        pass

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.TWITTER,
                external_id=external_id,
                title=None,
                content=content.strip(),
                author=author.strip(),
                url=tweet_url,
                timestamp=timestamp,
                likes=0,
                comments=0,
                shares=0,
            )
        except Exception as e:
            logger.warning("Playwright: 解析推文元素失败: %s", e)
            return None

    async def close(self) -> None:
        """释放浏览器资源"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Playwright 提供者已关闭")
