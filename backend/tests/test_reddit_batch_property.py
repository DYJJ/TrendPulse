"""
Reddit 批量采集器属性测试

使用 Hypothesis 库对 RedditBatchCollector 进行基于属性的测试。
通过模拟 PullPush API 响应验证采集逻辑的正确性，不实际访问外部服务。

属性 1: 采集数量上限约束
属性 2: 数据字段完整性
属性 9: 降级策略可靠性

验证需求: 1.3, 1.4, 1.5
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from backend.app.collectors.reddit_batch_collector import (
    BATCH_SIZE,
    RedditBatchCollector,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助：模拟 aiohttp 响应 ---


class MockAiohttpResponse:
    """模拟 aiohttp 响应对象"""

    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    async def json(self) -> dict:
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_pullpush_item(index: int) -> dict:
    """创建模拟的 PullPush API 返回数据项"""
    return {
        "id": f"post_{index}",
        "title": f"测试标题 {index}",
        "selftext": f"测试内容 {index}",
        "author": f"author_{index}",
        "permalink": f"/r/test/comments/post_{index}/",
        "created_utc": 1700000000 + index,
        "score": index * 10,
        "num_comments": index * 5,
        "subreddit": "test",
    }


def _make_pullpush_response(count: int, start_index: int = 0) -> dict:
    """创建模拟的 PullPush API 响应"""
    return {
        "data": [_make_pullpush_item(start_index + i) for i in range(count)]
    }


def _create_mock_session(total_available: int) -> MagicMock:
    """创建模拟的 aiohttp 会话

    每次 get 请求返回最多 100 条数据，数据用完后返回空列表。
    """
    call_count = {"value": 0}

    def mock_get(url, params=None, **kwargs):
        idx = call_count["value"]
        start = idx * 100
        remaining = total_available - start
        count = min(100, max(0, remaining))
        call_count["value"] += 1

        if count > 0:
            data = _make_pullpush_response(count, start_index=start)
        else:
            data = {"data": []}

        return MockAiohttpResponse(data)

    session = MagicMock()
    session.get = mock_get
    session.closed = False
    return session


def _run_async(coro):
    """在新的事件循环中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect_all(collector, keyword, limit, **kwargs) -> List[RawPost]:
    """收集所有批次的数据到一个列表"""
    result: List[RawPost] = []
    async for batch in collector.collect(keyword=keyword, limit=limit, **kwargs):
        result.extend(batch)
    return result


# --- 属性 1: 采集数量上限约束 ---


class TestCollectionLimitConstraint:
    """采集数量上限约束属性测试

    **验证: 需求 1.4, 6.1**

    对于任意条数限制值，采集器返回的数据总条数不超过指定的限制值。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(limit=st.integers(min_value=1, max_value=1500))
    def test_total_posts_never_exceed_limit(self, limit: int):
        """采集到的帖子总数不应超过指定的限制值

        **Validates: Requirements 1.4**
        """
        collector = RedditBatchCollector()
        collector._session = _create_mock_session(limit + 500)

        async def run():
            with patch(
                "backend.app.collectors.reddit_batch_collector.async_sleep",
                new_callable=AsyncMock,
            ), patch.object(
                collector, "_check_pullpush_freshness",
                new_callable=AsyncMock, return_value=True,
            ):
                return await _collect_all(collector, keyword="test", limit=limit)

        all_posts = _run_async(run())

        assert len(all_posts) <= limit, (
            f"采集数量 {len(all_posts)} 超过限制 {limit}"
        )


# --- 属性 2: 数据字段完整性 ---


class TestDataFieldCompleteness:
    """数据字段完整性属性测试

    **验证: 需求 1.3**

    对于任意 PullPush API 返回的数据，每条记录必须包含
    非空的 content、source 和 external_id 字段。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(num_items=st.integers(min_value=1, max_value=50))
    def test_all_posts_have_required_fields(self, num_items: int):
        """每条采集到的帖子应包含所有必需字段

        **Validates: Requirements 1.3**
        """
        collector = RedditBatchCollector()
        collector._session = _create_mock_session(num_items)

        async def run():
            with patch(
                "backend.app.collectors.reddit_batch_collector.async_sleep",
                new_callable=AsyncMock,
            ), patch.object(
                collector, "_check_pullpush_freshness",
                new_callable=AsyncMock, return_value=True,
            ):
                return await _collect_all(collector, keyword="test", limit=num_items)

        all_posts = _run_async(run())

        assert len(all_posts) == num_items

        for post in all_posts:
            assert post.source == DataSource.REDDIT, "数据源应为 REDDIT"
            assert post.external_id and len(post.external_id) > 0, "external_id 不能为空"
            assert post.content and len(post.content) > 0, "content 不能为空"
            assert post.author and len(post.author) > 0, "author 不能为空"
            assert post.url is not None, "url 不能为 None"
            assert isinstance(post.timestamp, datetime), "timestamp 必须是 datetime"
            assert isinstance(post.likes, int), "likes 必须是整数"
            assert isinstance(post.comments, int), "comments 必须是整数"


# --- 属性 9: 降级策略可靠性 ---


class TestFallbackReliability:
    """降级策略可靠性属性测试

    **验证: 需求 1.5**

    当 PullPush API 失败时，系统应自动切换到降级方案并继续采集。
    """

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(num_items=st.integers(min_value=1, max_value=10))
    def test_fallback_to_playwright_when_apis_unavailable(self, num_items: int):
        """PullPush 和 asyncpraw 都不可用时应降级到 Playwright

        **Validates: Requirements 1.5**
        """
        # 不提供 client_id/secret，asyncpraw 降级会直接抛 RuntimeError
        collector = RedditBatchCollector()

        # 模拟 PullPush 失败：get 返回一个会在 raise_for_status 时抛异常的响应
        class FailingResponse:
            def raise_for_status(self):
                raise ConnectionError("PullPush 不可用")
            async def json(self):
                return {}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        def mock_get_fail(url, params=None):
            return FailingResponse()

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = mock_get_fail
        collector._session = mock_session

        # 模拟 Playwright RedditCollector 返回数据
        mock_posts = [
            RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=f"pw_{i}",
                title=f"Playwright 标题 {i}",
                content=f"Playwright 内容 {i}",
                author=f"pw_author_{i}",
                url=f"https://reddit.com/r/test/{i}",
                timestamp=datetime.now(timezone.utc),
                likes=i,
                comments=i,
                shares=0,
            )
            for i in range(num_items)
        ]

        mock_reddit_collector = AsyncMock()
        mock_reddit_collector.collect = AsyncMock(return_value=mock_posts)
        mock_reddit_collector.close = AsyncMock()

        async def run():
            with patch(
                "backend.app.collectors.reddit_collector.RedditCollector",
                return_value=mock_reddit_collector,
            ), patch(
                "backend.app.collectors.reddit_batch_collector.async_sleep",
                new_callable=AsyncMock,
            ):
                return await _collect_all(collector, keyword="test", limit=num_items)

        all_posts = _run_async(run())

        assert len(all_posts) > 0, "降级到 Playwright 后应能获取数据"
        assert len(all_posts) <= num_items

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(num_items=st.integers(min_value=1, max_value=10))
    def test_fallback_preserves_data_integrity(self, num_items: int):
        """降级后获取的数据仍应满足字段完整性要求

        **Validates: Requirements 1.5**
        """
        collector = RedditBatchCollector()

        class FailingResponse:
            def raise_for_status(self):
                raise ConnectionError("PullPush 不可用")
            async def json(self):
                return {}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        def mock_get_fail(url, params=None):
            return FailingResponse()

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = mock_get_fail
        collector._session = mock_session

        mock_posts = [
            RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.REDDIT,
                external_id=f"pw_{i}",
                title=f"标题 {i}",
                content=f"内容 {i}",
                author=f"author_{i}",
                url=f"https://reddit.com/{i}",
                timestamp=datetime.now(timezone.utc),
                likes=i * 10,
                comments=i * 5,
                shares=0,
            )
            for i in range(num_items)
        ]

        mock_reddit_collector = AsyncMock()
        mock_reddit_collector.collect = AsyncMock(return_value=mock_posts)
        mock_reddit_collector.close = AsyncMock()

        async def run():
            with patch(
                "backend.app.collectors.reddit_collector.RedditCollector",
                return_value=mock_reddit_collector,
            ), patch(
                "backend.app.collectors.reddit_batch_collector.async_sleep",
                new_callable=AsyncMock,
            ):
                return await _collect_all(collector, keyword="test", limit=num_items)

        all_posts = _run_async(run())

        for post in all_posts:
            assert post.source == DataSource.REDDIT
            assert post.external_id and len(post.external_id) > 0
            assert post.content and len(post.content) > 0
            assert post.author and len(post.author) > 0
