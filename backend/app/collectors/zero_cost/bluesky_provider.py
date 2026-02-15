"""
Bluesky AT Protocol 采集提供者

通过 public.api.bsky.app 开放 API 采集帖子，无需认证。
策略：先用 searchActors 搜索相关用户，再用 getAuthorFeed 获取帖子。
（searchPosts 端点已被 Cloudflare 封禁，不再使用）
支持指数退避重试和批量 yield。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional, Set

import aiohttp

from backend.app.collectors.zero_cost.constants import (
    BATCH_SIZE,
    BLUESKY_DELAY_MIN,
    BLUESKY_DELAY_MAX,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)
from backend.app.collectors.zero_cost.utils import (
    generate_raw_post_id,
    random_delay,
)
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# Bluesky API 端点
BLUESKY_SEARCH_ACTORS_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors"
BLUESKY_GET_AUTHOR_FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


class BlueskyProvider:
    """Bluesky AT Protocol 采集提供者

    通过 searchActors 搜索相关用户，再通过 getAuthorFeed 获取帖子。
    支持指数退避重试和批量 yield。
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, proxy: Optional[str] = None) -> None:
        """初始化 BlueskyProvider

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

    async def _api_get(self, url: str, params: dict) -> dict:
        """通用 API GET 请求，支持指数退避重试

        Args:
            url: API 端点 URL
            params: 查询参数

        Returns:
            API 响应 JSON 字典

        Raises:
            RuntimeError: 重试耗尽后仍失败
        """
        session = await self._get_session()

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                    proxy=self._proxy,
                ) as resp:
                    if resp.status == 429:
                        wait = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "Bluesky API 限流，%.1f 秒后重试 (第 %d 次)",
                            wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status != 200:
                        wait = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "Bluesky API 返回状态码 %d，%.1f 秒后重试 (第 %d 次)",
                            resp.status, wait, attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        continue

                    return await resp.json()

            except asyncio.TimeoutError:
                logger.warning("Bluesky API 请求超时 (第 %d 次)", attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(
                    f"Bluesky API 请求超时，已重试 {MAX_RETRIES} 次"
                )
            except aiohttp.ClientError as e:
                logger.warning("Bluesky API 网络错误: %s (第 %d 次)", e, attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(
                    f"Bluesky API 网络错误，已重试 {MAX_RETRIES} 次: {e}"
                )

        raise RuntimeError(
            f"Bluesky API 在 {MAX_RETRIES} 次重试后仍失败"
        )

    async def _search_actors(self, keyword: str, limit: int = 10) -> List[str]:
        """通过 searchActors 搜索相关用户，返回 handle 列表

        Args:
            keyword: 搜索关键词
            limit: 返回用户数上限

        Returns:
            用户 handle 列表
        """
        await random_delay(BLUESKY_DELAY_MIN, BLUESKY_DELAY_MAX)
        params = {"q": keyword, "limit": min(limit, 25)}

        try:
            data = await self._api_get(BLUESKY_SEARCH_ACTORS_URL, params)
        except RuntimeError as e:
            logger.warning("Bluesky searchActors 失败: %s", e)
            return []

        actors = data.get("actors", [])
        handles = [a.get("handle", "") for a in actors if a.get("handle")]
        logger.info("Bluesky searchActors 找到 %d 个用户", len(handles))
        return handles

    async def _get_author_feed(
        self, actor: str, limit: int = 50, cursor: Optional[str] = None,
    ) -> dict:
        """获取指定用户的帖子 feed

        Args:
            actor: 用户 handle 或 DID
            limit: 单页条数（API 最大 100）
            cursor: 分页游标

        Returns:
            API 响应 JSON 字典
        """
        await random_delay(BLUESKY_DELAY_MIN, BLUESKY_DELAY_MAX)
        params: dict = {"actor": actor, "limit": min(limit, 100)}
        if cursor:
            params["cursor"] = cursor
        return await self._api_get(BLUESKY_GET_AUTHOR_FEED_URL, params)

    @staticmethod
    def parse_bluesky_post(post: dict) -> Optional[RawPost]:
        """将 Bluesky 帖子数据解析为 RawPost

        从 API 响应中的单个帖子对象提取内容、作者、互动数据等，
        转换为统一的 RawPost 对象。缺少必填字段时返回 None。

        Args:
            post: Bluesky API 返回的帖子字典（feed 项中的 post 对象）

        Returns:
            解析成功返回 RawPost 对象，数据无效时返回 None
        """
        try:
            # 提取帖子记录
            record = post.get("record", {})
            content = record.get("text", "")
            if not content:
                logger.warning("Bluesky 帖子缺少内容字段，跳过")
                return None

            # 提取作者信息
            author_info = post.get("author", {})
            author = author_info.get("handle", "")
            if not author:
                logger.warning("Bluesky 帖子缺少作者字段，跳过")
                return None

            # 提取 AT URI 作为 external_id
            uri = post.get("uri", "")
            if not uri:
                logger.warning("Bluesky 帖子缺少 URI，跳过")
                return None

            # 从 AT URI 提取 rkey（格式：at://did:plc:xxx/app.bsky.feed.post/rkey）
            uri_parts = uri.split("/")
            rkey = uri_parts[-1] if uri_parts else ""

            # 构造 Bluesky Web URL
            url = f"https://bsky.app/profile/{author}/post/{rkey}"

            # 解析发布时间
            created_at = record.get("createdAt", "")
            try:
                timestamp = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError, AttributeError):
                timestamp = datetime.now(timezone.utc)

            # 提取互动数据
            likes = int(post.get("likeCount", 0) or 0)
            reposts = int(post.get("repostCount", 0) or 0)
            replies = int(post.get("replyCount", 0) or 0)

            return RawPost(
                id=generate_raw_post_id("bsky", rkey),
                source=DataSource.TWITTER,
                external_id=uri,
                title=None,
                content=content,
                author=author,
                url=url,
                timestamp=timestamp,
                likes=likes,
                comments=replies,
                shares=reposts,
            )

        except Exception as e:
            logger.error("解析 Bluesky 帖子失败: %s", e)
            return None

    async def collect(
        self,
        keyword: str,
        limit: int,
        seen_ids: Optional[Set[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """采集 Bluesky 帖子

        策略：先用 searchActors 搜索相关用户，再用 getAuthorFeed
        获取每个用户的帖子。每 500 条 yield 一批。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 已采集的 ID 集合（用于去重）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（最多 500 条）

        Raises:
            RuntimeError: API 请求重试耗尽后仍失败
        """
        if seen_ids is None:
            seen_ids = set()

        # 第一步：搜索相关用户
        handles = await self._search_actors(keyword)
        if not handles:
            logger.info("Bluesky 未找到相关用户")
            return

        batch_buffer: List[RawPost] = []
        total_collected = 0

        # 第二步：遍历每个用户获取帖子
        for handle in handles:
            if total_collected >= limit:
                break

            cursor: Optional[str] = None
            logger.info("获取 Bluesky 用户 %s 的帖子", handle)

            # 每个用户最多翻 3 页
            for _page in range(3):
                if total_collected >= limit:
                    break

                try:
                    data = await self._get_author_feed(
                        handle, limit=50, cursor=cursor,
                    )
                except RuntimeError as e:
                    logger.warning("获取用户 %s feed 失败: %s", handle, e)
                    break

                feed = data.get("feed", [])
                if not feed:
                    break

                for item in feed:
                    if total_collected >= limit:
                        break

                    post_data = item.get("post", {})
                    raw_post = self.parse_bluesky_post(post_data)
                    if raw_post is None:
                        continue

                    if raw_post.external_id in seen_ids:
                        continue
                    seen_ids.add(raw_post.external_id)

                    batch_buffer.append(raw_post)
                    total_collected += 1

                    if len(batch_buffer) >= BATCH_SIZE:
                        yield batch_buffer[:BATCH_SIZE]
                        batch_buffer = batch_buffer[BATCH_SIZE:]
                        if on_progress:
                            on_progress(total_collected)
                        logger.info("Bluesky 采集进度: %d 条", total_collected)

                cursor = data.get("cursor")
                if not cursor:
                    break

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Bluesky 采集完成: 共 %d 条", total_collected)

    async def close(self) -> None:
        """释放 aiohttp 会话资源

        仅关闭内部创建的会话，外部传入的会话不做处理。
        """
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None
