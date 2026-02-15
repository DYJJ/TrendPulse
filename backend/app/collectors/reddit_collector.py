"""
Reddit数据采集器

支持两种采集模式：
1. API模式（asyncpraw）：配置了REDDIT_CLIENT_ID/SECRET时使用，速度快，适合大规模采集
2. 爬虫模式（Playwright）：未配置API时降级使用，速度慢，适合小规模采集

需求: 2.1-2.5, 15.3
"""

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from backend.app.collectors.base import BaseCollector
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 最大重试次数
MAX_RETRIES = 3


class RedditCollector(BaseCollector):
    """Reddit数据采集器

    自动检测是否配置了Reddit API凭据：
    - 有凭据：使用asyncpraw批量拉取，支持10万+数据量
    - 无凭据：降级为Playwright爬虫，适合小规模采集
    """

    source = DataSource.REDDIT

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "TrendPulse/1.0",
    ) -> None:
        """初始化Reddit采集器

        Args:
            client_id: Reddit API客户端ID
            client_secret: Reddit API客户端密钥
            user_agent: 请求User-Agent
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._reddit = None  # asyncpraw.Reddit实例
        self._playwright = None
        self._browser = None
        self._use_api = bool(client_id and client_secret)

        if self._use_api:
            logger.info("Reddit采集器: 使用API模式（asyncpraw）")
        else:
            logger.info("Reddit采集器: 未配置API凭据，使用爬虫降级模式")

    async def _ensure_reddit_client(self):
        """确保asyncpraw客户端已初始化"""
        if self._reddit is None:
            import asyncpraw
            self._reddit = asyncpraw.Reddit(
                client_id=self._client_id,
                client_secret=self._client_secret,
                user_agent=self._user_agent,
            )
        return self._reddit

    async def _collect_via_api(
        self,
        keyword: str,
        limit: int,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """通过Reddit API批量采集

        使用asyncpraw搜索帖子，支持大规模数据量。
        Reddit API每次请求最多返回100条，自动分页拉取。

        Args:
            keyword: 搜索关键词
            limit: 采集条数限制
            language: 语言代码
            on_progress: 进度回调函数，参数为已采集条数
        """
        reddit = await self._ensure_reddit_client()
        posts: List[RawPost] = []
        batch_count = 0

        try:
            # 搜索所有subreddit
            subreddit = await reddit.subreddit("all")
            search_params = {
                "query": keyword,
                "sort": "relevance",
                "time_filter": "all",
                "limit": None,  # 不限制，由我们自己控制
            }

            async for submission in subreddit.search(**search_params):
                if len(posts) >= limit:
                    break

                post = RawPost(
                    id=str(uuid.uuid4()),
                    source=DataSource.REDDIT,
                    external_id=submission.id,
                    title=submission.title,
                    content=submission.selftext or submission.title,
                    author=str(submission.author) if submission.author else "deleted",
                    url=f"https://reddit.com{submission.permalink}",
                    timestamp=datetime.fromtimestamp(
                        submission.created_utc, tz=timezone.utc
                    ),
                    likes=submission.score,
                    comments=submission.num_comments,
                    shares=0,
                )
                posts.append(post)
                batch_count += 1

                # 每500条报告一次进度
                if on_progress and batch_count % 500 == 0:
                    on_progress(len(posts))
                    logger.info("Reddit API采集进度: %d / %d", len(posts), limit)

                # 遵守API速率限制，每100条暂停一下
                if batch_count % 100 == 0:
                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.error("Reddit API采集异常: %s，已采集 %d 条", e, len(posts))
            if not posts:
                raise

        if on_progress:
            on_progress(len(posts))
        logger.info("Reddit API采集完成: %d 条", len(posts))
        return posts

    async def _collect_via_scraper(
        self, keyword: str, limit: int, language: str = "en"
    ) -> List[RawPost]:
        """通过Playwright爬虫采集（降级方案）

        使用old.reddit.com搜索页面，逐页翻页采集。
        速度较慢，建议limit不超过1000。
        """
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        ]
        context = await self._browser.new_context(
            user_agent=random.choice(user_agents),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        posts: List[RawPost] = []

        try:
            url = f"https://old.reddit.com/search?q={keyword}&sort=relevance&t=all"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1.0, 3.0))

            while len(posts) < limit:
                elements = await page.query_selector_all("div.search-result-link")
                if not elements:
                    elements = await page.query_selector_all("div[data-fullname]")
                if not elements:
                    break

                for el in elements:
                    if len(posts) >= limit:
                        break
                    try:
                        title_el = await el.query_selector("a.search-title, a.title")
                        title = await title_el.inner_text() if title_el else ""
                        href = await title_el.get_attribute("href") if title_el else ""
                        post_url = href if href and href.startswith("http") else f"https://old.reddit.com{href}" if href else ""

                        author_el = await el.query_selector("a.author")
                        author = await author_el.inner_text() if author_el else "unknown"

                        score_el = await el.query_selector("span.search-score, span.score")
                        score_text = await score_el.inner_text() if score_el else "0"
                        likes = self._parse_count(score_text)

                        comments_el = await el.query_selector("a.search-comments, a.comments")
                        comments_text = await comments_el.inner_text() if comments_el else "0"
                        comments = self._parse_count(comments_text)

                        snippet_el = await el.query_selector("span.search-result-body")
                        content = await snippet_el.inner_text() if snippet_el else title

                        external_id = await el.get_attribute("data-fullname") or ""

                        posts.append(RawPost(
                            id=str(uuid.uuid4()),
                            source=DataSource.REDDIT,
                            external_id=external_id,
                            title=title.strip() if title else None,
                            content=content.strip() if content else "",
                            author=author.strip(),
                            url=post_url,
                            timestamp=datetime.now(timezone.utc),
                            likes=likes,
                            comments=comments,
                            shares=0,
                        ))
                    except Exception as e:
                        logger.warning("Reddit爬虫: 提取帖子失败: %s", e)
                        continue

                if len(posts) >= limit:
                    break

                # 翻页
                next_btn = await page.query_selector("span.next-result-button a, a[rel='next']")
                if next_btn:
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    await next_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                else:
                    break

        finally:
            await context.close()

        logger.info("Reddit爬虫采集完成: %d 条", len(posts))
        return posts[:limit]

    @staticmethod
    def _parse_count(text: str) -> int:
        """解析互动数文本"""
        if not text or not text.strip():
            return 0
        cleaned = text.strip().lower().split()[0].replace(",", "")
        try:
            if "k" in cleaned:
                return int(float(cleaned.replace("k", "")) * 1000)
            elif "m" in cleaned:
                return int(float(cleaned.replace("m", "")) * 1_000_000)
            num_str = "".join(c for c in cleaned if c.isdigit() or c == ".")
            return int(float(num_str)) if num_str else 0
        except (ValueError, IndexError):
            return 0

    async def collect(
        self,
        keyword: str,
        limit: int,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """采集Reddit帖子（带重试）

        自动选择API或爬虫模式。大规模采集（>1000条）强制使用API模式。

        Args:
            keyword: 搜索关键词
            limit: 采集条数限制
            language: 语言代码
            on_progress: 进度回调
        """
        # 大规模采集必须使用API
        if limit > 1000 and not self._use_api:
            logger.warning(
                "Reddit: 请求采集 %d 条但未配置API，将限制为1000条（爬虫模式上限）", limit
            )
            limit = 1000

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if self._use_api:
                    return await self._collect_via_api(
                        keyword, limit, language, on_progress
                    )
                else:
                    return await self._collect_via_scraper(keyword, limit, language)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Reddit采集器: 第 %d/%d 次尝试失败: %s",
                    attempt + 1, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep((attempt + 1) * 2.0)

        raise last_error  # type: ignore[misc]

    async def close(self) -> None:
        """释放资源"""
        if self._reddit:
            await self._reddit.close()
            self._reddit = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
