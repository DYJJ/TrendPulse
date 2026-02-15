"""
X(Twitter) 批量采集器单元测试

测试 TwitterBatchCollector 的降级链路、错误处理和连续空批次停止逻辑。

覆盖场景:
- 降级链路: twscrape 失败 → Playwright
- 所有方案均失败时抛出 RuntimeError
- 连续空批次停止逻辑

Requirements: 2.3, 3.1, 6.1, 6.2, 6.4
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, List
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.app.collectors.twitter_batch_collector import (
    TwitterBatchCollector,
    BATCH_SIZE,
    MAX_RETRIES,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助函数 ---


def _make_raw_post(index: int) -> RawPost:
    """创建有效的 RawPost 测试对象"""
    return RawPost(
        id=str(uuid.uuid4()),
        source=DataSource.TWITTER,
        external_id=f"tweet_{index}",
        title=None,
        content=f"推文内容 {index}",
        author=f"user_{index}",
        url=f"https://x.com/user_{index}/status/tweet_{index}",
        timestamp=datetime.now(timezone.utc),
        likes=index,
        comments=0,
        shares=0,
    )


def _make_mock_provider(posts: List[RawPost]):
    """创建模拟的 Provider，其 search 方法逐条 yield 给定的 posts"""
    provider = AsyncMock()

    async def mock_search(*args, **kwargs) -> AsyncGenerator[RawPost, None]:
        for post in posts:
            yield post

    provider.search = mock_search
    provider.close = AsyncMock()
    return provider


def _make_failing_provider(error: Exception):
    """创建一个 search 时抛出异常的 Provider"""
    provider = AsyncMock()

    async def mock_search(*args, **kwargs):
        raise error
        # 需要 yield 使其成为异步生成器
        yield  # pragma: no cover

    provider.search = mock_search
    provider.close = AsyncMock()
    return provider


async def _collect_all(collector, keyword="test", limit=100):
    """收集所有批次并展平为单个列表"""
    all_posts = []
    async for batch in collector.collect(keyword=keyword, limit=limit):
        all_posts.extend(batch)
    return all_posts


# --- 测试: 降级链路 twscrape 失败 → Playwright ---


class TestFallbackToPlaywright:
    """测试降级链路: twscrape 失败后自动降级到 Playwright

    Requirements: 2.3, 3.1, 6.2
    """

    @pytest.mark.asyncio
    async def test_fallback_when_twscrape_raises(self):
        """twscrape 抛出异常时，应降级到 Nitter，Nitter 也失败后降级到 Playwright 并成功采集"""
        playwright_posts = [_make_raw_post(i) for i in range(5)]

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
            cookies_path="/fake/cookies.json",
        )

        # twscrape 失败
        collector._twscrape_provider = _make_failing_provider(
            RuntimeError("twscrape 账号被封禁"),
        )
        # twikit 也失败
        collector._twikit_provider = _make_failing_provider(
            RuntimeError("twikit 登录被 Cloudflare 拦截"),
        )
        # Nitter 也失败
        collector._nitter_provider = _make_failing_provider(
            RuntimeError("Nitter 镜像站不可用"),
        )
        # Playwright 成功
        collector._playwright_provider = _make_mock_provider(playwright_posts)

        results = await _collect_all(collector, limit=10)

        assert len(results) == 5
        for post in results:
            assert post.source == DataSource.TWITTER
            assert post.content

    @pytest.mark.asyncio
    async def test_fallback_skips_twscrape_when_no_accounts(self):
        """账号池为空时，应跳过 twscrape，尝试 Nitter，Nitter 失败后使用 Playwright"""
        playwright_posts = [_make_raw_post(i) for i in range(3)]

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[],  # 空账号池
            cookies_path="/fake/cookies.json",
        )
        # Nitter 失败
        collector._nitter_provider = _make_failing_provider(
            RuntimeError("Nitter 镜像站不可用"),
        )
        # twikit 也失败
        collector._twikit_provider = _make_failing_provider(
            RuntimeError("twikit 登录被 Cloudflare 拦截"),
        )
        collector._playwright_provider = _make_mock_provider(playwright_posts)

        results = await _collect_all(collector, limit=10)

        assert len(results) == 3


# --- 测试: 所有方案均失败时抛出 RuntimeError ---


class TestAllProvidersFail:
    """测试所有采集方案均失败时抛出 RuntimeError

    Requirements: 6.4
    """

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_all_fail(self):
        """twscrape、twikit、Nitter 和 Playwright 均失败时，应抛出 RuntimeError"""
        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
            cookies_path="/fake/cookies.json",
        )

        # 四个 Provider 都失败
        collector._twscrape_provider = _make_failing_provider(
            RuntimeError("twscrape 不可用"),
        )
        collector._twikit_provider = _make_failing_provider(
            RuntimeError("twikit 不可用"),
        )
        collector._nitter_provider = _make_failing_provider(
            RuntimeError("Nitter 不可用"),
        )
        collector._playwright_provider = _make_failing_provider(
            RuntimeError("Playwright 不可用"),
        )

        with pytest.raises(RuntimeError, match="所有采集方案均已尝试"):
            await _collect_all(collector, limit=10)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_no_accounts_playwright_fails(self):
        """无 twscrape 账号且 twikit、Nitter、Playwright 也失败时，应抛出 RuntimeError"""
        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[],
            cookies_path="/fake/cookies.json",
        )

        collector._twikit_provider = _make_failing_provider(
            RuntimeError("twikit 登录被 Cloudflare 拦截"),
        )
        collector._nitter_provider = _make_failing_provider(
            RuntimeError("Nitter 镜像站不可用"),
        )
        collector._playwright_provider = _make_failing_provider(
            RuntimeError("Playwright 浏览器启动失败"),
        )

        with pytest.raises(RuntimeError, match="所有采集方案均已尝试"):
            await _collect_all(collector, limit=10)


# --- 测试: 连续空批次停止逻辑 ---


class TestEmptyBatchStop:
    """测试连续空批次检测停止逻辑

    当 Provider 返回数据但经过去重/过滤后为空时，
    连续 3 个空批次后应停止采集。

    Requirements: 6.1
    """

    @pytest.mark.asyncio
    async def test_twscrape_success_no_empty_batch_issue(self):
        """正常采集时不应触发空批次停止"""
        posts = [_make_raw_post(i) for i in range(10)]

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )
        collector._twscrape_provider = _make_mock_provider(posts)

        results = await _collect_all(collector, limit=10)

        # 所有有效推文都应被采集到
        assert len(results) == 10


# --- 测试: 重试机制 ---


class TestRetryMechanism:
    """测试指数退避重试机制

    Requirements: 6.1, 6.2
    """

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        """前几次失败后成功时，应返回数据"""
        posts = [_make_raw_post(i) for i in range(3)]
        call_count = 0

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )

        # 创建一个前两次失败、第三次成功的 provider
        original_provider = _make_mock_provider(posts)

        async def flaky_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError(f"临时错误 #{call_count}")
            async for post in original_provider.search(*args, **kwargs):
                yield post

        flaky_provider = AsyncMock()
        flaky_provider.search = flaky_search
        flaky_provider.close = AsyncMock()

        collector._twscrape_provider = flaky_provider

        # 使用 patch 跳过 asyncio.sleep 以加速测试
        with patch("backend.app.collectors.twitter_batch_collector.asyncio.sleep", new_callable=AsyncMock):
            results = await _collect_all(collector, limit=10)

        assert len(results) == 3
        assert call_count == 3  # 前 2 次失败 + 第 3 次成功
