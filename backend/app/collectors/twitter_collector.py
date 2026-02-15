"""
X(Twitter) 数据采集器

支持三级降级策略：
1. API 模式（Tweepy + Twitter API v2）：配置了 TWITTER_BEARER_TOKEN 时使用
2. twscrape 模式：配置了账号池时使用
3. Playwright 爬虫模式：前两者均不可用时降级使用

保持 BaseCollector 接口不变，兼容 CollectionEngine。

需求: 1.1, 3.1, 6.1, 6.2
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from backend.app.collectors.base import BaseCollector
from backend.app.collectors.twitter_config import CookieManager
from backend.app.collectors.twitter_playwright_provider import PlaywrightProvider
from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 最大重试次数
MAX_RETRIES = 3

# 重试间隔（秒），指数退避
RETRY_DELAYS = [1.0, 3.0, 9.0]


class TwitterCollector(BaseCollector):
    """X(Twitter) 数据采集器

    三级降级策略：
    1. Twitter API v2（需要 bearer_token）
    2. twscrape 账号池（需要账号配置）
    3. Playwright 爬虫 + Cookie 登录态

    保持 BaseCollector 接口不变，兼容 CollectionEngine。
    """

    source = DataSource.TWITTER

    def __init__(
        self,
        bearer_token: str = "",
        accounts: Optional[list[dict]] = None,
        cookies_path: Optional[str] = None,
    ) -> None:
        """初始化 X 采集器

        Args:
            bearer_token: Twitter API v2 Bearer Token
            accounts: twscrape 账号列表
            cookies_path: Playwright Cookie 文件路径
        """
        self._bearer_token = bearer_token
        self._accounts = accounts or []
        self._cookies_path = cookies_path
        self._twscrape_provider: Optional[TwscrapeProvider] = None
        self._playwright_provider: Optional[PlaywrightProvider] = None

        # 记录可用方案
        available = []
        if bearer_token:
            available.append("API v2")
        if self._accounts:
            available.append("twscrape")
        available.append("Playwright")
        logger.info("X 采集器初始化，可用方案: %s", " → ".join(available))

    async def _collect_via_api(
        self,
        keyword: str,
        limit: int,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """通过 Twitter API v2 批量采集

        使用 tweepy.Client 的 search_recent_tweets，每次最多 100 条，自动翻页。
        注意：Basic 级别 API 只能搜索最近 7 天的推文。
        """
        import tweepy

        client = tweepy.Client(
            bearer_token=self._bearer_token, wait_on_rate_limit=True,
        )
        posts: List[RawPost] = []
        next_token = None
        loop = asyncio.get_event_loop()

        while len(posts) < limit:
            max_results = min(100, limit - len(posts))
            if max_results < 10:
                max_results = 10  # API 最小值

            # 在线程池中执行同步 API 调用
            response = await loop.run_in_executor(
                None,
                lambda: client.search_recent_tweets(
                    query=f"{keyword} lang:{language} -is:retweet",
                    max_results=max_results,
                    next_token=next_token,
                    tweet_fields=["created_at", "public_metrics", "author_id"],
                    user_fields=["username"],
                    expansions=["author_id"],
                ),
            )

            if not response.data:
                break

            # 构建 author_id -> username 映射
            users_map = {}
            if response.includes and "users" in response.includes:
                for user in response.includes["users"]:
                    users_map[user.id] = user.username

            for tweet in response.data:
                if len(posts) >= limit:
                    break
                metrics = tweet.public_metrics or {}
                author = users_map.get(tweet.author_id, "unknown")
                timestamp = tweet.created_at or datetime.now(timezone.utc)

                posts.append(RawPost(
                    id=str(uuid.uuid4()),
                    source=DataSource.TWITTER,
                    external_id=str(tweet.id),
                    title=None,
                    content=tweet.text,
                    author=author,
                    url=f"https://x.com/i/status/{tweet.id}",
                    timestamp=timestamp,
                    likes=metrics.get("like_count", 0),
                    comments=metrics.get("reply_count", 0),
                    shares=metrics.get("retweet_count", 0),
                ))

            if on_progress:
                on_progress(len(posts))

            # 翻页
            meta = response.meta or {}
            next_token = meta.get("next_token")
            if not next_token:
                break
            await asyncio.sleep(0.3)

        if on_progress:
            on_progress(len(posts))
        logger.info("X API v2 采集完成: %d 条", len(posts))
        return posts

    async def _collect_via_twscrape(
        self,
        keyword: str,
        limit: int,
        language: str = "en",
    ) -> List[RawPost]:
        """通过 twscrape 账号池采集

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            language: 语言代码
        """
        if self._twscrape_provider is None:
            self._twscrape_provider = TwscrapeProvider(self._accounts)

        posts: List[RawPost] = []
        async for post in self._twscrape_provider.search(
            keyword, limit, language=language,
        ):
            posts.append(post)
            if len(posts) >= limit:
                break

        logger.info("twscrape 采集完成: %d 条", len(posts))
        return posts

    async def _collect_via_playwright(
        self,
        keyword: str,
        limit: int,
    ) -> List[RawPost]:
        """通过 Playwright 爬虫采集（最终降级方案）

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限（Playwright 模式上限 500）
        """
        if self._playwright_provider is None:
            cookie_manager = CookieManager(self._cookies_path)
            self._playwright_provider = PlaywrightProvider(cookie_manager)

        posts: List[RawPost] = []
        async for post in self._playwright_provider.search(keyword, limit):
            posts.append(post)
            if len(posts) >= limit:
                break

        logger.info("Playwright 采集完成: %d 条", len(posts))
        return posts

    async def _try_collect(
        self,
        collect_func,
        provider_name: str,
        *args,
    ) -> Optional[List[RawPost]]:
        """带指数退避重试的采集尝试

        Args:
            collect_func: 采集函数
            provider_name: 方案名称（用于日志）
            *args: 传递给采集函数的参数

        Returns:
            采集结果列表，所有重试均失败时返回 None
        """
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return await collect_func(*args)
            except Exception as e:
                last_error = e
                logger.warning(
                    "X 采集器 [%s]: 第 %d/%d 次失败: %s",
                    provider_name, attempt + 1, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])

        logger.error("X 采集器 [%s]: 所有重试均失败", provider_name)
        return None

    async def collect(
        self,
        keyword: str,
        limit: int,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """采集 X 推文

        三级降级策略：API v2 → twscrape → Playwright
        每级方案均带指数退避重试（最多 3 次）。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            language: 语言代码
            on_progress: 进度回调函数

        Returns:
            采集到的 RawPost 列表

        Raises:
            RuntimeError: 所有采集方案均失败
        """
        errors: list[str] = []

        # 方案 1: Twitter API v2
        if self._bearer_token:
            result = await self._try_collect(
                self._collect_via_api, "API v2",
                keyword, limit, language, on_progress,
            )
            if result is not None:
                return result
            errors.append("API v2")
            logger.warning("API v2 不可用，尝试降级到 twscrape")

        # 方案 2: twscrape
        if self._accounts:
            result = await self._try_collect(
                self._collect_via_twscrape, "twscrape",
                keyword, limit, language,
            )
            if result is not None:
                if on_progress:
                    on_progress(len(result))
                return result
            errors.append("twscrape")
            logger.warning("twscrape 不可用，尝试降级到 Playwright")
        else:
            logger.info("twscrape 账号池未配置，跳过")

        # 方案 3: Playwright（最终降级）
        if limit > 500:
            logger.warning(
                "Playwright 模式下请求 %d 条，限制为 500 条", limit,
            )
            limit = 500

        result = await self._try_collect(
            self._collect_via_playwright, "Playwright",
            keyword, limit,
        )
        if result is not None:
            if on_progress:
                on_progress(len(result))
            return result
        errors.append("Playwright")

        # 所有方案均失败
        raise RuntimeError(
            f"所有采集方案均已尝试但均失败: {', '.join(errors)} 均不可用"
        )

    async def close(self) -> None:
        """释放所有资源"""
        if self._twscrape_provider:
            await self._twscrape_provider.close()
            self._twscrape_provider = None
        if self._playwright_provider:
            await self._playwright_provider.close()
            self._playwright_provider = None
        logger.info("TwitterCollector 已关闭")
