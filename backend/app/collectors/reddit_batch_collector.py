"""
Reddit 大规模批量采集器

使用多级采集策略进行大规模 Reddit 数据采集，支持 10 万+条数据。
支持按关键词、subreddit、时间范围过滤，使用分页逻辑。
每 500 条数据 yield 一批并报告进度。

采集策略（按优先级）：
1. Arctic Shift API（免费，支持无限游标分页，数据量最大）
2. PullPush API（数据过时则跳过）
3. Reddit .json 端点（免认证，实时数据，多 subreddit 并发扩量）
4. Playwright 爬虫（最终兜底）

需求: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
"""

import asyncio
import logging
import uuid
from asyncio import sleep as async_sleep
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional, Set

import aiohttp

from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# ===== Arctic Shift API 配置 =====
# Arctic Shift 免费 API，支持按 subreddit + title/selftext 搜索，created_utc 游标分页，无硬性上限
ARCTIC_SHIFT_SEARCH_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_SHIFT_COMMENTS_URL = "https://arctic-shift.photon-reddit.com/api/comments/search"
# Arctic Shift 每页最大条数
ARCTIC_SHIFT_PAGE_SIZE = 100
# Arctic Shift 请求间延迟（秒），礼貌性限速，避免 429
ARCTIC_SHIFT_DELAY = 1.0
# 小数量采集时的请求间延迟（秒），加快响应速度
ARCTIC_SHIFT_DELAY_FAST = 0.3

# ===== PullPush API 配置 =====
PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"

# 每批 yield 的数据量
BATCH_SIZE = 500

# 每次 API 请求获取的最大条数（PullPush 支持最大 500）
PAGE_SIZE = 500

# 网络请求超时（秒）
REQUEST_TIMEOUT = 30

# 最大重试次数（含 429 限速重试）
MAX_RETRIES = 5

# PullPush 数据新鲜度阈值（天）
PULLPUSH_STALENESS_THRESHOLD_DAYS = 30

# ===== Reddit .json 端点配置 =====
REDDIT_JSON_SEARCH_URL = "https://www.reddit.com/search.json"
REDDIT_JSON_SUBREDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"
REDDIT_JSON_PAGE_SIZE = 100
REDDIT_JSON_DELAY = 1.0
REDDIT_JSON_BACKOFF_BASE = 5.0
REDDIT_JSON_SORT_MODES = ["new", "relevance", "hot", "top"]
# Reddit .json 时间过滤器（用于分片采集扩大数据量）
REDDIT_JSON_TIME_FILTERS = ["all", "year", "month", "week"]

# ===== 自动发现相关 subreddit 的默认映射 =====
# 根据关键词自动扩展到相关 subreddit，大幅增加数据池
KEYWORD_SUBREDDIT_MAP = {
    # 加密货币相关
    "btc": ["Bitcoin", "cryptocurrency", "CryptoMarkets", "BitcoinBeginners",
             "CryptoCurrency", "ethtrader", "SatoshiStreetBets", "CryptoMoonShots",
             "binance", "defi", "altcoin", "BitcoinMining", "CryptoTechnology",
             "bitcoinmarkets", "CryptoCurrencyTrading"],
    "bitcoin": ["Bitcoin", "cryptocurrency", "CryptoMarkets", "BitcoinBeginners",
                "bitcoinmarkets", "BitcoinMining", "CryptoTechnology"],
    "eth": ["ethereum", "ethtrader", "ethfinance", "cryptocurrency", "defi"],
    "crypto": ["cryptocurrency", "CryptoMarkets", "CryptoMoonShots", "defi",
               "Bitcoin", "ethereum", "altcoin", "SatoshiStreetBets"],
    # AI 相关
    "ai": ["artificial", "MachineLearning", "deeplearning", "ChatGPT",
            "OpenAI", "LocalLLaMA", "singularity", "technology"],
    "chatgpt": ["ChatGPT", "OpenAI", "artificial", "MachineLearning",
                "LocalLLaMA", "technology"],
    # 通用技术
    "tech": ["technology", "gadgets", "Futurology", "programming", "webdev"],
    "programming": ["programming", "learnprogramming", "webdev", "Python",
                    "javascript", "golang", "rust"],
}

# 通用 subreddit 列表（当关键词没有专属映射时使用）
GENERAL_SUBREDDITS = [
    "all", "popular", "AskReddit", "news", "worldnews",
    "technology", "science", "todayilearned",
]

# 多 subreddit 并发采集的最大并发数
MAX_SUBREDDIT_CONCURRENCY = 5


class RedditBatchCollector:
    """Reddit 大规模批量采集器

    使用多级采集策略批量采集 Reddit 数据，支持 10 万+条。
    Arctic Shift API 作为首选方案，支持无限游标分页。
    自动发现相关 subreddit 并发采集，大幅扩大数据池。

    需求: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "TrendPulse/1.0",
        proxy: Optional[str] = None,
    ) -> None:
        """初始化 Reddit 批量采集器

        Args:
            client_id: Reddit API 客户端 ID（用于 asyncpraw 降级）
            client_secret: Reddit API 客户端密钥（用于 asyncpraw 降级）
            user_agent: 请求 User-Agent
            proxy: HTTP 代理地址（如 http://127.0.0.1:7890）
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._proxy = proxy
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """确保 aiohttp 会话已初始化"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"User-Agent": self._user_agent},
            )
        return self._session

    def _discover_subreddits(self, keyword: str, limit: int = 10000) -> List[str]:
        """根据关键词自动发现相关 subreddit 列表

        优先使用预定义映射，否则使用通用列表。
        根据采集目标数量动态调整 subreddit 数量，
        小数量采集时减少 subreddit 避免无效请求。

        Args:
            keyword: 搜索关键词
            limit: 采集目标数量，用于动态调整列表大小

        Returns:
            List[str]: 相关 subreddit 列表（去重）
        """
        kw_lower = keyword.lower().strip()
        result_subs: List[str] = []

        # 精确匹配
        if kw_lower in KEYWORD_SUBREDDIT_MAP:
            result_subs = list(KEYWORD_SUBREDDIT_MAP[kw_lower])
        else:
            # 部分匹配
            for key, subs in KEYWORD_SUBREDDIT_MAP.items():
                if key in kw_lower or kw_lower in key:
                    result_subs = list(subs)
                    break

        if not result_subs:
            result_subs = list(GENERAL_SUBREDDITS)

        # 根据采集目标动态决定是否追加通用 subreddit
        # 小数量采集（<= 500）时不追加，避免大量无效请求
        if limit > 500:
            extra_subs = [
                "all", "AskReddit", "news", "worldnews", "technology",
                "Futurology", "Economics", "finance", "investing",
                "stocks", "wallstreetbets", "personalfinance",
            ]
            for sub in extra_subs:
                if sub not in result_subs:
                    result_subs.append(sub)

        # 根据采集目标动态限制 subreddit 数量
        if limit <= 100:
            max_subs = 3
        elif limit <= 500:
            max_subs = 8
        elif limit <= 5000:
            max_subs = 15
        else:
            max_subs = 25

        return result_subs[:max_subs]

    async def collect(
        self,
        keyword: str,
        limit: int,
        subreddit: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """批量采集 Reddit 数据

        使用四级采集策略，优先使用数据量最大的方案：
        1. Arctic Shift API（首选，免费无限分页）
        2. PullPush API（数据过时则跳过）
        3. Reddit .json 端点（多 subreddit 并发 + 时间分片扩量）
        4. Playwright 爬虫（最终兜底）

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限（最大 200000）
            subreddit: 指定 subreddit（可选）
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（500 条）
        """
        total_collected = 0
        seen_ids: Set[str] = set()

        # === 第 1 层：Arctic Shift API（多 subreddit 并发采集） ===
        try:
            arctic_count = 0
            async for batch in self._collect_arctic_shift(
                keyword, limit, subreddit, start_date, end_date, seen_ids, on_progress
            ):
                arctic_count += len(batch)
                total_collected += len(batch)
                yield batch
            logger.info("Arctic Shift 采集完成: %d 条", arctic_count)
            if total_collected >= limit:
                return
        except Exception as e:
            logger.warning("Arctic Shift API 不可用: %s，尝试 PullPush", e)

        remaining = limit - total_collected

        # === 第 2 层：PullPush API ===
        pullpush_usable = False
        try:
            pullpush_usable = await self._check_pullpush_freshness(keyword, subreddit)
        except Exception as e:
            logger.warning("PullPush 新鲜度探测失败: %s", e)

        if pullpush_usable:
            try:
                pp_count = 0
                async for batch in self._collect_pullpush(
                    keyword, remaining, subreddit, start_date, end_date,
                    seen_ids, on_progress,
                ):
                    pp_count += len(batch)
                    total_collected += len(batch)
                    yield batch
                logger.info("PullPush 补充采集: %d 条", pp_count)
                if total_collected >= limit:
                    return
            except Exception as e:
                logger.warning("PullPush API 采集失败: %s", e)
        else:
            logger.warning(
                "PullPush 数据过时（超过 %d 天未更新），跳过",
                PULLPUSH_STALENESS_THRESHOLD_DAYS,
            )

        remaining = limit - total_collected

        # === 第 3 层：Reddit .json 端点（多 subreddit 并发 + 时间分片） ===
        try:
            json_count = 0
            async for batch in self._collect_reddit_json_enhanced(
                keyword, remaining, subreddit, start_date, end_date,
                seen_ids, on_progress,
            ):
                json_count += len(batch)
                total_collected += len(batch)
                yield batch
            logger.info("Reddit JSON 增强采集: %d 条", json_count)
            if total_collected >= limit:
                return
        except Exception as e:
            logger.warning("Reddit JSON 端点不可用: %s", e)

        remaining = limit - total_collected

        # === 第 4 层：Playwright 爬虫（兜底） ===
        if remaining > 0:
            async for batch in self._collect_playwright(keyword, remaining, on_progress):
                total_collected += len(batch)
                yield batch

        logger.info("Reddit 全部采集完成: 总计 %d 条", total_collected)


    # ===================================================================
    # Arctic Shift API 采集（首选方案，免费无限分页）
    # ===================================================================

    async def _collect_arctic_shift(
        self,
        keyword: str,
        limit: int,
        subreddit: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        global_seen_ids: Optional[Set[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 Arctic Shift API 采集 Reddit 数据

        Arctic Shift 是免费的 Reddit 数据归档 API，支持按 subreddit + title/selftext 搜索，
        使用 before 参数（created_utc 时间戳）实现游标分页，无硬性上限。
        自动发现相关 subreddit 并发采集，大幅扩大数据池。
        同时采集帖子（posts）和评论（comments），进一步扩大数据量。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            subreddit: 指定 subreddit（可选，为空时自动发现相关 subreddit）
            start_date: 起始日期
            end_date: 结束日期
            global_seen_ids: 全局去重集合
            on_progress: 进度回调
        """
        if global_seen_ids is None:
            global_seen_ids = set()

        # 确定要采集的 subreddit 列表
        if subreddit:
            subreddit_list = [subreddit]
        else:
            subreddit_list = self._discover_subreddits(keyword, limit)

        logger.info(
            "Arctic Shift 开始采集: keyword='%s', subreddits=%s, limit=%d",
            keyword, subreddit_list, limit,
        )

        total_collected = 0
        batch_buffer: List[RawPost] = []

        # === 第一阶段：采集帖子（title 搜索 + selftext 搜索） ===
        # 小数量采集时只用 title 搜索，减少请求次数
        if limit <= 500:
            search_modes = [("title", keyword)]
        else:
            search_modes = [
                ("title", keyword),
                ("selftext", keyword),
            ]

        for search_field, search_value in search_modes:
            if total_collected >= limit:
                break

            for sub in subreddit_list:
                if total_collected >= limit:
                    break

                sub_count = 0
                sub_limit = limit - total_collected

                try:
                    async for batch_chunk in self._arctic_shift_paginate(
                        search_field, search_value, sub, sub_limit,
                        start_date, end_date, global_seen_ids,
                    ):
                        batch_buffer.extend(batch_chunk)
                        sub_count += len(batch_chunk)
                        total_collected += len(batch_chunk)

                        while len(batch_buffer) >= BATCH_SIZE:
                            yield batch_buffer[:BATCH_SIZE]
                            batch_buffer = batch_buffer[BATCH_SIZE:]
                            if on_progress:
                                on_progress(total_collected)
                            logger.info(
                                "Arctic Shift 帖子采集进度: %d / %d (r/%s %s搜索: %d 条)",
                                total_collected, limit, sub, search_field, sub_count,
                            )

                        if total_collected >= limit:
                            break

                except Exception as e:
                    logger.warning(
                        "Arctic Shift r/%s %s搜索失败: %s，跳过",
                        sub, search_field, e,
                    )
                    continue

                if sub_count > 0:
                    logger.info(
                        "Arctic Shift r/%s %s搜索完成: %d 条",
                        sub, search_field, sub_count,
                    )

        # === 第二阶段：采集评论（扩大数据量） ===
        # 小数量采集时跳过评论采集，避免无效请求
        if total_collected < limit and limit > 200:
            comments_limit = limit - total_collected
            logger.info("Arctic Shift 开始评论采集，目标 %d 条", comments_limit)

            for sub in subreddit_list:
                if total_collected >= limit:
                    break

                comment_count = 0
                try:
                    async for batch_chunk in self._arctic_shift_comments_paginate(
                        keyword, sub, min(comments_limit, limit - total_collected),
                        start_date, end_date, global_seen_ids,
                    ):
                        batch_buffer.extend(batch_chunk)
                        comment_count += len(batch_chunk)
                        total_collected += len(batch_chunk)

                        while len(batch_buffer) >= BATCH_SIZE:
                            yield batch_buffer[:BATCH_SIZE]
                            batch_buffer = batch_buffer[BATCH_SIZE:]
                            if on_progress:
                                on_progress(total_collected)
                            logger.info(
                                "Arctic Shift 评论采集进度: %d / %d (r/%s: %d 条)",
                                total_collected, limit, sub, comment_count,
                            )

                        if total_collected >= limit:
                            break

                except Exception as e:
                    logger.warning("Arctic Shift r/%s 评论采集失败: %s", sub, e)
                    continue

                if comment_count > 0:
                    logger.info("Arctic Shift r/%s 评论采集完成: %d 条", sub, comment_count)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Arctic Shift 全部采集完成: %d 条", total_collected)

    async def _arctic_shift_paginate(
        self,
        search_field: str,
        search_value: str,
        subreddit: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        seen_ids: Set[str],
    ) -> AsyncGenerator[List[RawPost], None]:
        """Arctic Shift API 游标分页采集单个 subreddit

        使用 before 参数（created_utc 时间戳）实现向前翻页。

        Args:
            search_field: 搜索字段名（title 或 selftext）
            search_value: 搜索关键词
            subreddit: subreddit 名称
            limit: 采集上限
            start_date: 起始日期
            end_date: 结束日期
            seen_ids: 全局去重集合

        Yields:
            List[RawPost]: 解析后的帖子列表
        """
        session = await self._ensure_session()
        collected = 0
        cursor_before: Optional[int] = None
        if end_date:
            cursor_before = int(end_date.timestamp())
        consecutive_empty = 0

        while collected < limit:
            params: dict = {
                search_field: search_value,
                "subreddit": subreddit,
                "limit": ARCTIC_SHIFT_PAGE_SIZE,
                "sort": "desc",
                "sort_type": "created_utc",
            }
            if cursor_before:
                params["before"] = cursor_before
            if start_date:
                params["after"] = int(start_date.timestamp())

            try:
                data = await self._request_with_retry(
                    session, ARCTIC_SHIFT_SEARCH_URL, params
                )
            except Exception as e:
                logger.warning("Arctic Shift r/%s 请求失败: %s", subreddit, e)
                break

            items = data.get("data", [])
            if not items:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                delay = ARCTIC_SHIFT_DELAY_FAST if limit <= 500 else ARCTIC_SHIFT_DELAY
                await async_sleep(delay)
                continue

            consecutive_empty = 0
            page_posts: List[RawPost] = []

            for item in items:
                if collected >= limit:
                    break
                ext_id = item.get("id", "")
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                post = self._parse_arctic_shift_item(item)
                if post is not None:
                    page_posts.append(post)
                    collected += 1

            if page_posts:
                yield page_posts

            # 更新游标
            last_item = items[-1]
            new_cursor = last_item.get("created_utc", 0)
            if not new_cursor:
                break
            if cursor_before is not None and new_cursor >= cursor_before:
                break
            cursor_before = int(new_cursor)

            # 本页无新数据则停止
            if not page_posts:
                break

            # 小数量采集时缩短延迟，加快响应
            delay = ARCTIC_SHIFT_DELAY_FAST if limit <= 500 else ARCTIC_SHIFT_DELAY
            await async_sleep(delay)

    @staticmethod
    def _parse_arctic_shift_item(item: dict) -> Optional[RawPost]:
        """解析 Arctic Shift API 返回的单条数据

        Args:
            item: API 返回的 JSON 对象

        Returns:
            RawPost: 解析后的帖子对象，解析失败返回 None
        """
        try:
            external_id = item.get("id", "")
            title = item.get("title", "")
            selftext = item.get("selftext", "")
            content = selftext if selftext and selftext.strip() else title
            author = item.get("author", "deleted")
            permalink = item.get("permalink", "")
            url = f"https://reddit.com{permalink}" if permalink else ""
            created_utc = item.get("created_utc", 0)
            timestamp = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_utc
                else datetime.now(timezone.utc)
            )
            score = item.get("score", 0)
            num_comments = item.get("num_comments", 0)

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=external_id,
                title=title,
                content=content,
                author=author if author else "deleted",
                url=url,
                timestamp=timestamp,
                likes=score if isinstance(score, int) else 0,
                comments=num_comments if isinstance(num_comments, int) else 0,
                shares=0,
            )
        except Exception as e:
            logger.warning("解析 Arctic Shift 数据失败: %s", e)
            return None

    async def _arctic_shift_comments_paginate(
        self,
        keyword: str,
        subreddit: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        seen_ids: Set[str],
    ) -> AsyncGenerator[List[RawPost], None]:
        """Arctic Shift 评论 API 游标分页采集

        通过评论搜索进一步扩大数据量，评论数据通常远多于帖子。

        Args:
            keyword: 搜索关键词
            subreddit: subreddit 名称
            limit: 采集上限
            start_date: 起始日期
            end_date: 结束日期
            seen_ids: 全局去重集合

        Yields:
            List[RawPost]: 解析后的评论列表
        """
        session = await self._ensure_session()
        collected = 0
        cursor_before: Optional[int] = None
        if end_date:
            cursor_before = int(end_date.timestamp())
        consecutive_empty = 0

        while collected < limit:
            params: dict = {
                "body": keyword,
                "subreddit": subreddit,
                "limit": ARCTIC_SHIFT_PAGE_SIZE,
                "sort": "desc",
                "sort_type": "created_utc",
            }
            if cursor_before:
                params["before"] = cursor_before
            if start_date:
                params["after"] = int(start_date.timestamp())

            try:
                data = await self._request_with_retry(
                    session, ARCTIC_SHIFT_COMMENTS_URL, params
                )
            except Exception as e:
                logger.warning("Arctic Shift r/%s 评论请求失败: %s", subreddit, e)
                break

            items = data.get("data", [])
            if not items:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                delay = ARCTIC_SHIFT_DELAY_FAST if limit <= 500 else ARCTIC_SHIFT_DELAY
                await async_sleep(delay)
                continue

            consecutive_empty = 0
            page_posts: List[RawPost] = []

            for item in items:
                if collected >= limit:
                    break
                ext_id = "c_" + item.get("id", "")
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                post = self._parse_arctic_shift_comment(item)
                if post is not None:
                    page_posts.append(post)
                    collected += 1

            if page_posts:
                yield page_posts

            # 更新游标
            last_item = items[-1]
            new_cursor = last_item.get("created_utc", 0)
            if not new_cursor:
                break
            if cursor_before is not None and new_cursor >= cursor_before:
                break
            cursor_before = int(new_cursor)

            if not page_posts:
                break

            delay = ARCTIC_SHIFT_DELAY_FAST if limit <= 500 else ARCTIC_SHIFT_DELAY
            await async_sleep(delay)

    @staticmethod
    def _parse_arctic_shift_comment(item: dict) -> Optional[RawPost]:
        """解析 Arctic Shift 评论 API 返回的单条数据

        Args:
            item: API 返回的评论 JSON 对象

        Returns:
            RawPost: 解析后的帖子对象，解析失败返回 None
        """
        try:
            external_id = "c_" + item.get("id", "")
            body = item.get("body", "")
            if not body or not body.strip() or body == "[deleted]" or body == "[removed]":
                return None

            author = item.get("author", "deleted")
            permalink = item.get("permalink", "")
            url = f"https://reddit.com{permalink}" if permalink else ""
            created_utc = item.get("created_utc", 0)
            timestamp = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_utc
                else datetime.now(timezone.utc)
            )
            score = item.get("score", 0)

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=external_id,
                title=None,
                content=body,
                author=author if author else "deleted",
                url=url,
                timestamp=timestamp,
                likes=score if isinstance(score, int) else 0,
                comments=0,
                shares=0,
            )
        except Exception as e:
            logger.warning("解析 Arctic Shift 评论失败: %s", e)
            return None


    # ===================================================================
    # PullPush API 采集
    # ===================================================================

    async def _check_pullpush_freshness(
        self,
        keyword: str,
        subreddit: Optional[str] = None,
    ) -> bool:
        """探测 PullPush API 数据新鲜度

        Args:
            keyword: 搜索关键词
            subreddit: 指定 subreddit

        Returns:
            bool: True 表示数据足够新鲜可以使用
        """
        session = await self._ensure_session()
        params: dict = {
            "q": keyword,
            "size": 1,
            "sort": "desc",
            "sort_type": "created_utc",
        }
        if subreddit:
            params["subreddit"] = subreddit

        data = await self._request_with_retry(session, PULLPUSH_SUBMISSION_URL, params)
        items = data.get("data", [])
        if not items:
            logger.info("PullPush 探测无数据，视为不可用")
            return False

        latest_utc = items[0].get("created_utc", 0)
        if not latest_utc:
            return False

        latest_time = datetime.fromtimestamp(latest_utc, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        age_days = (now - latest_time).days

        logger.info(
            "PullPush 最新数据时间: %s（距今 %d 天）",
            latest_time.isoformat(), age_days,
        )
        return age_days <= PULLPUSH_STALENESS_THRESHOLD_DAYS

    async def _collect_pullpush(
        self,
        keyword: str,
        limit: int,
        subreddit: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        global_seen_ids: Optional[Set[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 PullPush API 采集 Reddit 数据

        使用 created_utc 游标分页。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            subreddit: 指定 subreddit
            start_date: 起始日期
            end_date: 结束日期
            global_seen_ids: 全局去重集合
            on_progress: 进度回调
        """
        if global_seen_ids is None:
            global_seen_ids = set()

        session = await self._ensure_session()
        total_collected = 0
        batch_buffer: List[RawPost] = []
        cursor_before: Optional[int] = None
        if end_date:
            cursor_before = int(end_date.timestamp())

        while total_collected < limit:
            params = self._build_pullpush_params(
                keyword, subreddit, start_date, cursor_before
            )
            data = await self._request_with_retry(session, PULLPUSH_SUBMISSION_URL, params)

            items = data.get("data", [])
            if not items:
                logger.info("PullPush API 无更多数据，已采集 %d 条", total_collected)
                break

            new_in_page = 0
            for item in items:
                if total_collected >= limit:
                    break
                ext_id = item.get("id", "")
                if ext_id in global_seen_ids:
                    continue
                global_seen_ids.add(ext_id)
                post = self._parse_pullpush_item(item)
                if post is not None:
                    batch_buffer.append(post)
                    total_collected += 1
                    new_in_page += 1

            last_item = items[-1]
            new_cursor = last_item.get("created_utc", 0)
            if not new_cursor or (cursor_before is not None and new_cursor >= cursor_before):
                break
            cursor_before = int(new_cursor)

            if new_in_page == 0:
                logger.info("PullPush 本页全部重复，停止翻页，已采集 %d 条", total_collected)
                break

            while len(batch_buffer) >= BATCH_SIZE:
                yield batch_buffer[:BATCH_SIZE]
                batch_buffer = batch_buffer[BATCH_SIZE:]
                if on_progress:
                    on_progress(total_collected)
                logger.info("Reddit PullPush 采集进度: %d / %d", total_collected, limit)

            await async_sleep(1.0)

        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Reddit PullPush 采集完成: %d 条", total_collected)

    def _build_pullpush_params(
        self,
        keyword: str,
        subreddit: Optional[str],
        start_date: Optional[datetime],
        cursor_before: Optional[int],
    ) -> dict:
        """构建 PullPush API 请求参数"""
        params: dict = {
            "q": keyword,
            "size": PAGE_SIZE,
            "sort": "desc",
            "sort_type": "created_utc",
        }
        if subreddit:
            params["subreddit"] = subreddit
        if start_date:
            params["after"] = int(start_date.timestamp())
        if cursor_before:
            params["before"] = cursor_before
        return params

    @staticmethod
    def _parse_pullpush_item(item: dict) -> Optional[RawPost]:
        """解析 PullPush API 返回的单条数据"""
        try:
            external_id = item.get("id", "")
            title = item.get("title", "")
            selftext = item.get("selftext", "")
            content = selftext if selftext else title
            author = item.get("author", "deleted")
            permalink = item.get("permalink", "")
            url = f"https://reddit.com{permalink}" if permalink else ""
            created_utc = item.get("created_utc", 0)
            timestamp = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_utc
                else datetime.now(timezone.utc)
            )
            score = item.get("score", 0)
            num_comments = item.get("num_comments", 0)

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=external_id,
                title=title,
                content=content,
                author=author,
                url=url,
                timestamp=timestamp,
                likes=score if isinstance(score, int) else 0,
                comments=num_comments if isinstance(num_comments, int) else 0,
                shares=0,
            )
        except Exception as e:
            logger.warning("解析 PullPush 数据失败: %s", e)
            return None


    # ===================================================================
    # Reddit .json 端点增强采集（多 subreddit 并发 + 时间分片）
    # ===================================================================

    async def _collect_reddit_json_enhanced(
        self,
        keyword: str,
        limit: int,
        subreddit: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        global_seen_ids: Optional[Set[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """增强版 Reddit .json 端点采集

        通过多 subreddit 并发 + 多排序方式 + 时间分片大幅扩大数据量。
        单个 subreddit + 排序方式约 250 条，通过组合可达数万条。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            subreddit: 指定 subreddit（可选）
            start_date: 起始日期
            end_date: 结束日期
            global_seen_ids: 全局去重集合
            on_progress: 进度回调
        """
        if global_seen_ids is None:
            global_seen_ids = set()

        # 确定要采集的 subreddit 列表
        if subreddit:
            subreddit_list = [subreddit]
        else:
            # 自动发现相关 subreddit + 全局搜索
            discovered = self._discover_subreddits(keyword, limit)
            subreddit_list = [None] + discovered  # None 表示全局搜索

        total_collected = 0
        batch_buffer: List[RawPost] = []

        for sub in subreddit_list:
            if total_collected >= limit:
                break

            sub_name = sub if sub else "全局"
            sub_collected = 0

            # 小数量采集时减少排序/时间组合，避免大量无效请求
            if limit <= 500:
                sort_modes = ["relevance", "new"]
                time_filters = ["all"]
            else:
                sort_modes = REDDIT_JSON_SORT_MODES
                time_filters = REDDIT_JSON_TIME_FILTERS

            # 对每个 subreddit，用多种排序方式 + 时间过滤器组合采集
            for sort_mode in sort_modes:
                if total_collected >= limit:
                    break

                for time_filter in time_filters:
                    if total_collected >= limit:
                        break

                    try:
                        async for posts in self._reddit_json_paginate(
                            keyword, sub, sort_mode, time_filter,
                            limit - total_collected, start_date, end_date,
                            global_seen_ids,
                        ):
                            batch_buffer.extend(posts)
                            sub_collected += len(posts)
                            total_collected += len(posts)

                            while len(batch_buffer) >= BATCH_SIZE:
                                yield batch_buffer[:BATCH_SIZE]
                                batch_buffer = batch_buffer[BATCH_SIZE:]
                                if on_progress:
                                    on_progress(total_collected)
                                logger.info(
                                    "Reddit JSON 增强采集进度: %d / %d (r/%s sort=%s t=%s)",
                                    total_collected, limit, sub_name, sort_mode, time_filter,
                                )
                    except Exception as e:
                        logger.warning(
                            "Reddit JSON r/%s sort=%s t=%s 失败: %s",
                            sub_name, sort_mode, time_filter, e,
                        )
                        continue

            if sub_collected > 0:
                logger.info("Reddit JSON r/%s 采集完成: %d 条", sub_name, sub_collected)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Reddit JSON 增强采集完成: %d 条（去重后）", total_collected)

    async def _reddit_json_paginate(
        self,
        keyword: str,
        subreddit: Optional[str],
        sort_mode: str,
        time_filter: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        seen_ids: Set[str],
    ) -> AsyncGenerator[List[RawPost], None]:
        """Reddit .json 端点单次分页采集

        Args:
            keyword: 搜索关键词
            subreddit: subreddit 名称（None 表示全局搜索）
            sort_mode: 排序方式
            time_filter: 时间过滤器
            limit: 采集上限
            start_date: 起始日期
            end_date: 结束日期
            seen_ids: 去重集合

        Yields:
            List[RawPost]: 解析后的帖子列表
        """
        session = await self._ensure_session()
        collected = 0
        after_cursor: Optional[str] = None
        empty_streak = 0

        if subreddit:
            base_url = REDDIT_JSON_SUBREDDIT_SEARCH_URL.format(subreddit=subreddit)
        else:
            base_url = REDDIT_JSON_SEARCH_URL

        while collected < limit:
            params: dict = {
                "q": keyword,
                "sort": sort_mode,
                "t": time_filter,
                "limit": min(REDDIT_JSON_PAGE_SIZE, limit - collected),
                "raw_json": 1,
            }
            if subreddit:
                params["restrict_sr"] = "on"
            if after_cursor:
                params["after"] = after_cursor

            try:
                data = await self._request_reddit_json_with_backoff(
                    session, base_url, params
                )
            except Exception as e:
                if collected > 0:
                    break
                raise

            listing_data = data.get("data", {})
            children = listing_data.get("children", [])

            if not children:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                await async_sleep(REDDIT_JSON_DELAY)
                continue

            empty_streak = 0
            page_posts: List[RawPost] = []

            for child in children:
                if collected >= limit:
                    break
                if child.get("kind") != "t3":
                    continue

                item = child.get("data", {})
                ext_id = item.get("id", "")
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                # 时间范围过滤
                created_utc = item.get("created_utc", 0)
                if created_utc:
                    post_time = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                    if start_date and post_time < start_date:
                        continue
                    if end_date and post_time > end_date:
                        continue

                post = self._parse_reddit_json_item(item)
                if post is not None:
                    page_posts.append(post)
                    collected += 1

            if page_posts:
                yield page_posts

            after_cursor = listing_data.get("after")
            if not after_cursor:
                break

            if not page_posts:
                break

            await async_sleep(REDDIT_JSON_DELAY)

    async def _request_reddit_json_with_backoff(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict,
    ) -> dict:
        """Reddit JSON 请求，遇到 429 自动退避重试"""
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(url, params=params, proxy=self._proxy) as resp:
                    if resp.status == 429:
                        wait = REDDIT_JSON_BACKOFF_BASE * (attempt + 1)
                        logger.warning("Reddit JSON 429 限流，等待 %.1f 秒后重试", wait)
                        await async_sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
            except aiohttp.ClientResponseError:
                raise
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    await async_sleep((attempt + 1) * 2.0)
                    continue
                raise
        raise RuntimeError("Reddit JSON 请求重试次数耗尽")

    @staticmethod
    def _parse_reddit_json_item(item: dict) -> Optional[RawPost]:
        """解析 Reddit .json 端点返回的单条帖子数据"""
        try:
            external_id = item.get("id", "")
            title = item.get("title", "")
            selftext = item.get("selftext", "")
            content = selftext if selftext else title
            author = item.get("author", "deleted")
            permalink = item.get("permalink", "")
            url = f"https://reddit.com{permalink}" if permalink else ""
            created_utc = item.get("created_utc", 0)
            timestamp = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_utc
                else datetime.now(timezone.utc)
            )
            score = item.get("score", 0)
            num_comments = item.get("num_comments", 0)

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=external_id,
                title=title,
                content=content,
                author=author,
                url=url,
                timestamp=timestamp,
                likes=score if isinstance(score, int) else 0,
                comments=num_comments if isinstance(num_comments, int) else 0,
                shares=0,
            )
        except Exception as e:
            logger.warning("解析 Reddit JSON 数据失败: %s", e)
            return None


    # ===================================================================
    # 通用工具方法
    # ===================================================================

    async def _request_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict,
    ) -> dict:
        """带重试的 HTTP GET 请求

        对 Arctic Shift 的 422/429 错误做特殊处理。

        Args:
            session: aiohttp 会话
            url: 请求 URL
            params: 请求参数

        Returns:
            dict: JSON 响应数据
        """
        is_arctic = "arctic-shift" in url
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                # Arctic Shift API 不需要代理
                use_proxy = self._proxy if not is_arctic else None
                async with session.get(url, params=params, proxy=use_proxy) as response:
                    # Arctic Shift 422 通常是 before 参数越界，返回空数据即可
                    if response.status == 422 and is_arctic:
                        logger.debug(
                            "Arctic Shift 422（参数越界），返回空数据: %s",
                            params.get("before", ""),
                        )
                        return {"data": []}
                    # 429 限速：等待后重试
                    if response.status == 429:
                        wait_time = (attempt + 1) * 5.0
                        logger.warning(
                            "429 限速，等待 %.1fs 后重试（第 %d/%d 次）: %s",
                            wait_time, attempt + 1, MAX_RETRIES, url,
                        )
                        await async_sleep(wait_time)
                        continue
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                last_error = e
                logger.warning(
                    "请求失败（第 %d/%d 次）: %s %s",
                    attempt + 1, MAX_RETRIES, url, e,
                )
                if attempt < MAX_RETRIES - 1:
                    await async_sleep((attempt + 1) * 2.0)
        raise last_error  # type: ignore[misc]

    async def _collect_playwright(
        self,
        keyword: str,
        limit: int,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 Playwright 爬虫采集 Reddit 数据（最终兜底方案）

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限（爬虫模式建议不超过 1000）
            on_progress: 进度回调
        """
        from backend.app.collectors.reddit_collector import RedditCollector

        effective_limit = min(limit, 1000)
        if limit > 1000:
            logger.warning(
                "Playwright 爬虫模式上限 1000 条，请求 %d 条将被截断", limit
            )

        collector = RedditCollector()
        try:
            posts = await collector.collect(keyword, effective_limit, "en", on_progress)

            for i in range(0, len(posts), BATCH_SIZE):
                batch = posts[i:i + BATCH_SIZE]
                yield batch
                if on_progress:
                    on_progress(min(i + BATCH_SIZE, len(posts)))

            logger.info("Reddit Playwright 采集完成: %d 条", len(posts))
        finally:
            await collector.close()

    async def close(self) -> None:
        """释放资源"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
