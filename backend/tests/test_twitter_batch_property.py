"""
X(Twitter) 批量采集器属性测试（旧版兼容）

使用 Hypothesis 库对 TwitterBatchCollector 进行基于属性的测试。
通过模拟 twscrape 和 Playwright 输出验证采集逻辑的正确性，不实际访问外部服务。

属性 1: 采集数量上限约束
属性 2: 数据字段完整性
属性 9: 降级策略可靠性

验证需求: 1.3, 3.5, 4.3, 5.1
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from backend.app.collectors.twitter_batch_collector import (
    BATCH_SIZE,
    TwitterBatchCollector,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助函数 ---


def _make_raw_post(index: int) -> RawPost:
    """创建模拟的 RawPost 对象"""
    return RawPost(
        id=str(uuid.uuid4()),
        source=DataSource.TWITTER,
        external_id=f"tw_{index}",
        title=None,
        content=f"这是测试推文内容 {index}，包含关键词 test",
        author=f"user_{index}",
        url=f"https://x.com/user_{index}/status/tw_{index}",
        timestamp=datetime.now(timezone.utc),
        likes=index * 10,
        comments=index * 2,
        shares=index * 5,
    )


def _make_mock_twscrape_provider(total_available: int):
    """创建模拟的 TwscrapeProvider

    返回一个 mock 对象，其 search 方法为异步生成器，逐条 yield RawPost。

    Args:
        total_available: 可用的推文总数
    """
    provider = AsyncMock()
    provider.close = AsyncMock()

    async def mock_search(
        keyword, limit, start_date=None, end_date=None, language="en",
    ):
        count = min(limit, total_available)
        for i in range(count):
            yield _make_raw_post(i)

    provider.search = mock_search
    return provider


def _make_mock_playwright_provider(total_available: int):
    """创建模拟的 PlaywrightProvider

    Args:
        total_available: 可用的推文总数
    """
    provider = AsyncMock()
    provider.close = AsyncMock()

    async def mock_search(keyword, limit):
        count = min(limit, total_available)
        for i in range(count):
            yield _make_raw_post(i + 10000)  # 偏移避免与 twscrape 重复

    provider.search = mock_search
    return provider


def _make_mock_failing_nitter_provider():
    """创建模拟的失败 NitterProvider，使降级链跳过 Nitter"""
    provider = AsyncMock()
    provider.close = AsyncMock()

    async def failing_search(keyword, limit):
        raise RuntimeError("Nitter 不可用")
        yield  # noqa: E501 使其成为 async generator

    provider.search = failing_search
    return provider


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

    **验证: 需求 4.3, 5.1**

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

        **Validates: Requirements 4.3**
        """
        accounts = [{"username": "u", "password": "p", "email": "e", "email_password": "ep"}]
        collector = TwitterBatchCollector(batch_delay=0, accounts=accounts)
        mock_provider = _make_mock_twscrape_provider(limit + 500)

        async def run():
            collector._twscrape_provider = mock_provider
            return await _collect_all(collector, keyword="test", limit=limit)

        all_posts = _run_async(run())

        assert len(all_posts) <= limit, (
            f"采集数量 {len(all_posts)} 超过限制 {limit}"
        )


# --- 属性 2: 数据字段完整性 ---


class TestDataFieldCompleteness:
    """数据字段完整性属性测试

    **验证: 需求 1.3**

    对于任意 twscrape 返回的数据，每条记录必须包含
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
        accounts = [{"username": "u", "password": "p", "email": "e", "email_password": "ep"}]
        collector = TwitterBatchCollector(batch_delay=0, accounts=accounts)
        mock_provider = _make_mock_twscrape_provider(num_items)

        async def run():
            collector._twscrape_provider = mock_provider
            return await _collect_all(collector, keyword="test", limit=num_items)

        all_posts = _run_async(run())

        assert len(all_posts) == num_items, (
            f"期望 {num_items} 条，实际 {len(all_posts)} 条"
        )

        for post in all_posts:
            assert post.source == DataSource.TWITTER, "数据源应为 TWITTER"
            assert post.external_id and len(post.external_id) > 0, "external_id 不能为空"
            assert post.content and len(post.content) > 0, "content 不能为空"
            assert post.author and len(post.author) > 0, "author 不能为空"
            assert post.url is not None, "url 不能为 None"
            assert isinstance(post.timestamp, datetime), "timestamp 必须是 datetime"
            assert isinstance(post.likes, int), "likes 必须是整数"
            assert isinstance(post.comments, int), "comments 必须是整数"
            assert isinstance(post.shares, int), "shares 必须是整数"


# --- 属性 9: 降级策略可靠性 ---


class TestFallbackReliability:
    """降级策略可靠性属性测试

    **验证: 需求 3.5**

    当 twscrape 失败时，系统应自动切换到 Playwright 降级方案并继续采集。
    """

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(num_items=st.integers(min_value=1, max_value=10))
    def test_fallback_to_playwright_when_all_unavailable(self, num_items: int):
        """twscrape 不可用时应降级到 Playwright

        **Validates: Requirements 3.5**
        """
        # 不配置账号，直接走 Playwright 降级
        collector = TwitterBatchCollector(batch_delay=0, accounts=[])
        mock_pw_provider = _make_mock_playwright_provider(num_items)

        async def run():
            collector._nitter_provider = _make_mock_failing_nitter_provider()
            collector._playwright_provider = mock_pw_provider
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

        **Validates: Requirements 3.5**
        """
        # twscrape 配置了但会失败，应降级到 Playwright
        accounts = [{"username": "u", "password": "p", "email": "e", "email_password": "ep"}]
        collector = TwitterBatchCollector(batch_delay=0, accounts=accounts)

        # 模拟 twscrape 失败
        failing_provider = AsyncMock()
        failing_provider.close = AsyncMock()

        async def failing_search(*args, **kwargs):
            raise RuntimeError("twscrape 不可用")
            yield  # noqa: E501 使其成为 async generator

        failing_provider.search = failing_search

        mock_pw_provider = _make_mock_playwright_provider(num_items)

        async def run():
            collector._twscrape_provider = failing_provider
            collector._nitter_provider = _make_mock_failing_nitter_provider()
            collector._playwright_provider = mock_pw_provider
            return await _collect_all(collector, keyword="test", limit=num_items)

        # patch asyncio.sleep 跳过重试等待，避免测试超时
        with patch("backend.app.collectors.twitter_batch_collector.asyncio.sleep", new_callable=AsyncMock):
            all_posts = _run_async(run())

        for post in all_posts:
            assert post.source == DataSource.TWITTER
            assert post.external_id and len(post.external_id) > 0
            assert post.content and len(post.content) > 0
            assert post.author and len(post.author) > 0
