"""
Twitter Syndication API 提供者

通过 cdn.syndication.twimg.com/tweet-result 端点获取推文详情，无需认证。
支持单条获取和批量并发获取，内置限流保护和错误处理。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

import re

import aiohttp

from backend.app.collectors.zero_cost.constants import (
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    SYNDICATION_MAX_CONCURRENCY,
)
from backend.app.collectors.zero_cost.utils import (
    generate_raw_post_id,
    random_delay,
    random_user_agent,
)
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# Syndication API 基础 URL
SYNDICATION_BASE_URL = "https://cdn.syndication.twimg.com/tweet-result"

# Syndication timeline-profile 端点（获取用户时间线推文 ID）
TIMELINE_PROFILE_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"

# 从 timeline-profile HTML 中提取推文 ID 的正则
_TWEET_ID_FROM_TIMELINE = re.compile(r'/status/(\d+)')

# Syndication 请求间延迟范围（秒）
# 信号量已控制并发数，延迟仅用于避免突发请求
SYNDICATION_DELAY_MIN = 0.05
SYNDICATION_DELAY_MAX = 0.15


class SyndicationProvider:
    """Twitter Syndication API 提供者

    通过 cdn.syndication.twimg.com 端点获取推文详情，无需认证。
    支持单条和批量并发获取，内置信号量控制并发和随机延迟限流。
    支持从推文数据中提取 @mentions 用户名，用于雪球式用户发现。
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, proxy: Optional[str] = None) -> None:
        """初始化 SyndicationProvider

        Args:
            session: 可选的 aiohttp 会话，未提供时自动创建
            proxy: HTTP 代理地址（可选），如 http://127.0.0.1:7890
        """
        self._external_session = session is not None
        self._session = session
        self._proxy = proxy

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch_tweet(self, tweet_id: str) -> Optional[RawPost]:
        """获取单条推文详情

        通过 Syndication API 获取指定推文的完整信息，
        包含内容、作者、互动数据等。支持指数退避重试。

        Args:
            tweet_id: 推文 ID 字符串

        Returns:
            解析成功返回 RawPost 对象，失败返回 None
        """
        session = await self._get_session()
        headers = {"User-Agent": random_user_agent()}
        params = {"id": tweet_id, "token": "x"}

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    SYNDICATION_BASE_URL,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                    proxy=self._proxy,
                ) as resp:
                    if resp.status == 404:
                        logger.debug("推文 %s 不存在或已删除", tweet_id)
                        return None

                    if resp.status == 429:
                        # 限流：指数退避重试
                        wait = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "Syndication API 限流，%s 秒后重试 (第 %d 次)",
                            wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status != 200:
                        logger.warning(
                            "Syndication API 返回异常状态码 %d，推文 %s",
                            resp.status, tweet_id,
                        )
                        return None

                    data = await resp.json()
                    return self.parse_syndication_response(data, tweet_id)

            except asyncio.TimeoutError:
                logger.warning("获取推文 %s 超时 (第 %d 次)", tweet_id, attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                return None
            except aiohttp.ClientError as e:
                logger.warning("获取推文 %s 网络错误: %s", tweet_id, e)
                return None
            except Exception as e:
                logger.error("获取推文 %s 未知错误: %s", tweet_id, e)
                return None

        # 所有重试均因 429 失败
        logger.warning("推文 %s 在 %d 次重试后仍被限流", tweet_id, MAX_RETRIES)
        return None

    async def fetch_tweets_batch(
        self,
        tweet_ids: List[str],
        max_concurrency: int = SYNDICATION_MAX_CONCURRENCY,
    ) -> List[RawPost]:
        """批量并发获取推文详情

        使用 asyncio.Semaphore 控制最大并发数，
        请求间添加随机延迟以避免触发限流。

        Args:
            tweet_ids: 推文 ID 列表
            max_concurrency: 最大并发数，默认为配置值

        Returns:
            成功获取的 RawPost 列表（跳过失败的推文）
        """
        if not tweet_ids:
            return []

        semaphore = asyncio.Semaphore(max_concurrency)
        results: List[Optional[RawPost]] = []

        async def _fetch_with_semaphore(tid: str) -> Optional[RawPost]:
            """带信号量控制的单条获取"""
            async with semaphore:
                await random_delay(SYNDICATION_DELAY_MIN, SYNDICATION_DELAY_MAX)
                return await self.fetch_tweet(tid)

        tasks = [_fetch_with_semaphore(tid) for tid in tweet_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤掉 None 和异常结果
        posts: List[RawPost] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("批量获取推文 %s 异常: %s", tweet_ids[i], result)
                continue
            if result is not None:
                posts.append(result)

        logger.info(
            "批量获取完成：请求 %d 条，成功 %d 条",
            len(tweet_ids), len(posts),
        )
        return posts
    async def fetch_tweets_batch_with_mentions(
        self,
        tweet_ids: List[str],
        max_concurrency: int = SYNDICATION_MAX_CONCURRENCY,
    ) -> tuple:
        """批量并发获取推文详情，同时提取所有被提及的用户名

        与 fetch_tweets_batch 类似，但额外返回从推文中发现的用户名集合。
        用于雪球式用户发现。

        Args:
            tweet_ids: 推文 ID 列表
            max_concurrency: 最大并发数

        Returns:
            (posts, mentioned_usernames) 元组：
            - posts: 成功获取的 RawPost 列表
            - mentioned_usernames: 从推文中提取的所有被提及用户名集合
        """
        if not tweet_ids:
            return [], set()

        semaphore = asyncio.Semaphore(max_concurrency)
        all_mentioned: set = set()
        lock = asyncio.Lock()

        async def _fetch_with_mentions(tid: str) -> Optional[RawPost]:
            """带信号量控制的单条获取，同时提取 mentions"""
            async with semaphore:
                await random_delay(SYNDICATION_DELAY_MIN, SYNDICATION_DELAY_MAX)
                session = await self._get_session()
                headers = {"User-Agent": random_user_agent()}
                params = {"id": tid, "token": "x"}

                for attempt in range(MAX_RETRIES):
                    try:
                        async with session.get(
                            SYNDICATION_BASE_URL,
                            params=params,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=15),
                            proxy=self._proxy,
                        ) as resp:
                            if resp.status == 404:
                                return None
                            if resp.status == 429:
                                wait = RETRY_BASE_DELAY * (2 ** attempt)
                                await asyncio.sleep(wait)
                                continue
                            if resp.status != 200:
                                return None

                            data = await resp.json()
                            # 提取 mentions
                            mentions = self.extract_mentioned_usernames(data)
                            if mentions:
                                async with lock:
                                    all_mentioned.update(mentions)
                            return self.parse_syndication_response(data, tid)

                    except asyncio.TimeoutError:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                            continue
                        return None
                    except (aiohttp.ClientError, Exception):
                        return None
                return None

        tasks = [_fetch_with_mentions(tid) for tid in tweet_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        posts: List[RawPost] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("批量获取推文 %s 异常: %s", tweet_ids[i], result)
                continue
            if result is not None:
                posts.append(result)

        logger.info(
            "批量获取完成（含 mentions）：请求 %d 条，成功 %d 条，发现 %d 个新用户名",
            len(tweet_ids), len(posts), len(all_mentioned),
        )
        return posts, all_mentioned


    @staticmethod
    def parse_syndication_response(data: dict, tweet_id: str) -> Optional[RawPost]:
        """将 Syndication API 响应解析为 RawPost

        从 JSON 响应中提取推文内容、作者、互动数据等字段，
        转换为统一的 RawPost 对象。缺少必填字段时返回 None。

        Args:
            data: Syndication API 返回的 JSON 字典
            tweet_id: 推文 ID

        Returns:
            解析成功返回 RawPost 对象，数据无效时返回 None
        """
        try:
            # 快速跳过已删除/被封号的推文（TweetTombstone）
            typename = data.get("__typename", "")
            if typename == "TweetTombstone":
                logger.debug("推文 %s 为 Tombstone（已删除或被封号），跳过", tweet_id)
                return None

            # 提取推文文本内容
            content = data.get("text", "")
            if not content:
                logger.debug("推文 %s 缺少内容字段，跳过", tweet_id)
                return None

            # 提取作者信息
            user = data.get("user", {})
            author = user.get("screen_name") or user.get("name", "")
            if not author:
                logger.debug("推文 %s 缺少作者字段，跳过", tweet_id)
                return None

            # 解析发布时间
            created_at = data.get("created_at", "")
            try:
                timestamp = datetime.strptime(
                    created_at, "%a %b %d %H:%M:%S %z %Y"
                )
            except (ValueError, TypeError):
                # 尝试 ISO 格式
                try:
                    timestamp = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError, AttributeError):
                    timestamp = datetime.now(timezone.utc)

            # 提取互动数据
            likes = int(data.get("favorite_count", 0) or 0)
            retweets = int(data.get("retweet_count", 0) or 0)
            replies = int(data.get("reply_count", 0) or 0)

            # 构造推文 URL
            screen_name = user.get("screen_name", "unknown")
            url = f"https://x.com/{screen_name}/status/{tweet_id}"

            return RawPost(
                id=generate_raw_post_id("tw", tweet_id),
                source=DataSource.TWITTER,
                external_id=tweet_id,
                title=None,
                content=content,
                author=author,
                url=url,
                timestamp=timestamp,
                likes=likes,
                comments=replies,
                shares=retweets,
            )

        except Exception as e:
            logger.error("解析推文 %s 响应失败: %s", tweet_id, e)
            return None
    @staticmethod
    def extract_mentioned_usernames(data: dict) -> List[str]:
        """从 Syndication API 推文数据中提取所有被提及的用户名

        提取来源：
        1. entities.user_mentions[].screen_name
        2. in_reply_to_screen_name
        3. parent.user.screen_name（引用推文的原作者）
        4. quoted_tweet.user.screen_name（被引用推文的作者）
        5. 推文文本中的 @username（正则兜底）

        Args:
            data: Syndication API 返回的 JSON 字典

        Returns:
            去重后的用户名列表（小写，不含 @）
        """
        seen: set = set()
        usernames: List[str] = []

        def _add(name: str) -> None:
            """添加用户名（去重、小写化）"""
            if name:
                lower = name.lower().strip()
                if lower and lower not in seen and len(lower) <= 15:
                    seen.add(lower)
                    usernames.append(lower)

        # 1. entities.user_mentions
        entities = data.get("entities", {})
        for mention in entities.get("user_mentions", []):
            _add(mention.get("screen_name", ""))

        # 2. in_reply_to_screen_name
        _add(data.get("in_reply_to_screen_name", "") or "")

        # 3. parent.user.screen_name
        parent = data.get("parent")
        if isinstance(parent, dict):
            _add(parent.get("user", {}).get("screen_name", ""))

        # 4. quoted_tweet.user.screen_name
        quoted = data.get("quoted_tweet")
        if isinstance(quoted, dict):
            _add(quoted.get("user", {}).get("screen_name", ""))

        # 5. 文本中的 @username（正则兜底）
        text = data.get("text", "")
        for match in re.finditer(r'@([A-Za-z0-9_]{1,15})', text):
            _add(match.group(1))

        # 排除推文作者自身
        author = data.get("user", {}).get("screen_name", "")
        if author:
            author_lower = author.lower()
            usernames = [u for u in usernames if u != author_lower]

        return usernames


    async def fetch_user_timeline(self, username: str) -> List[str]:
        """通过 timeline-profile 端点获取用户时间线的推文 ID 列表

        使用 syndication.twitter.com/srv/timeline-profile/screen-name/{username}
        端点获取用户最近的推文 ID，无需认证。

        Args:
            username: Twitter 用户名（不含 @）

        Returns:
            推文 ID 字符串列表（已去重）
        """
        session = await self._get_session()
        url = TIMELINE_PROFILE_URL.format(username=username)
        headers = {"User-Agent": random_user_agent()}

        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                proxy=self._proxy,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "获取用户 %s 时间线失败，状态码 %d",
                        username, resp.status,
                    )
                    return []

                html = await resp.text()
                # 从 HTML 中提取所有推文 ID 并去重
                all_ids = _TWEET_ID_FROM_TIMELINE.findall(html)
                unique_ids = list(dict.fromkeys(all_ids))
                logger.info(
                    "用户 %s 时间线获取到 %d 个推文 ID",
                    username, len(unique_ids),
                )
                return unique_ids

        except asyncio.TimeoutError:
            logger.warning("获取用户 %s 时间线超时", username)
            return []
        except aiohttp.ClientError as e:
            logger.warning("获取用户 %s 时间线网络错误: %s", username, e)
            return []
        except Exception as e:
            logger.error("获取用户 %s 时间线未知错误: %s", username, e)
            return []

    async def close(self) -> None:
        """释放 aiohttp 会话资源

        仅关闭内部创建的会话，外部传入的会话不做处理。
        """
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None
