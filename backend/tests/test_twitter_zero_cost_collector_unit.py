"""
ZeroCostCollector 单元测试

测试 Provider 编排顺序、降级逻辑、全部失败异常、环境变量配置。
需求: 5.1, 5.3, 5.5, 7.5
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.collectors.twitter_zero_cost_collector import (
    ZeroCostCollector,
    is_zero_cost_enabled,
)
from backend.app.collectors.zero_cost.constants import BATCH_SIZE
from backend.app.models.data_models import DataSource, RawPost


# === 辅助函数 ===


def make_raw_post(prefix: str, idx: int) -> RawPost:
    """构造测试用 RawPost"""
    external_id = f"{prefix}_ext_{idx}"
    return RawPost(
        id=f"{prefix}_{external_id}",
        source=DataSource.TWITTER,
        external_id=external_id,
        title=None,
        content=f"测试内容 {idx}",
        author=f"author_{idx}",
        url=f"https://example.com/{idx}",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def make_posts_list(prefix: str, count: int, start_idx: int = 0) -> List[RawPost]:
    """构造指定数量的 RawPost 列表"""
    return [make_raw_post(prefix, start_idx + i) for i in range(count)]


def create_mock_provider_collect(posts: List[RawPost], batch_size: int = BATCH_SIZE):
    """创建模拟 Provider 的 collect 异步生成器"""
    async def mock_collect(
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> AsyncGenerator[List[RawPost], None]:
        yielded = 0
        buffer: List[RawPost] = []
        for post in posts:
            if yielded >= limit:
                break
            if post.external_id in seen_ids:
                continue
            seen_ids.add(post.external_id)
            buffer.append(post)
            yielded += 1
            if len(buffer) >= batch_size:
                yield buffer[:batch_size]
                buffer = buffer[batch_size:]
        if buffer:
            yield buffer
    return mock_collect


def create_failing_provider_collect(error_msg: str):
    """创建一个抛出异常的模拟 Provider collect"""
    async def mock_collect(
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> AsyncGenerator[List[RawPost], None]:
        raise RuntimeError(error_msg)
        # yield 使其成为异步生成器
        yield []  # pragma: no cover
    return mock_collect


def _build_collector(**overrides) -> ZeroCostCollector:
    """构造一个带 mock Provider 的 ZeroCostCollector"""
    collector = ZeroCostCollector.__new__(ZeroCostCollector)
    collector._batch_delay = 0
    collector._proxy = None
    collector._syndication = MagicMock()
    collector._search_engine = MagicMock()
    collector._bluesky = MagicMock()
    collector._rss = MagicMock()
    # 默认所有 Provider 返回空
    collector._search_engine.collect = create_mock_provider_collect([])
    collector._bluesky.collect = create_mock_provider_collect([])
    collector._rss.collect = create_mock_provider_collect([])
    for key, val in overrides.items():
        setattr(collector, key, val)
    return collector


async def _collect_all(collector: ZeroCostCollector, keyword: str = "test", limit: int = 100) -> List[List[RawPost]]:
    """收集所有 yield 的批次"""
    batches: List[List[RawPost]] = []
    async for batch in collector.collect(keyword=keyword, limit=limit):
        batches.append(batch)
    return batches


# === 测试 Provider 编排顺序 ===
# 需求 5.1: 按 SearchEngine → Bluesky → RSS 优先级执行


class TestProviderOrchestrationOrder:
    """测试 Provider 按优先级依次执行"""

    @pytest.mark.asyncio
    async def test_providers_called_in_order(self):
        """验证 Provider 按 SearchEngine → Bluesky → RSS 顺序调用"""
        call_order: List[str] = []

        def tracking_collect(name: str, posts: List[RawPost]):
            """创建记录调用顺序的 mock collect"""
            async def mock_collect(keyword, limit, seen_ids, on_progress=None, **kwargs):
                call_order.append(name)
                yielded = 0
                for post in posts:
                    if yielded >= limit:
                        break
                    if post.external_id in seen_ids:
                        continue
                    seen_ids.add(post.external_id)
                    yielded += 1
                    yield [post]
            return mock_collect

        search_posts = make_posts_list("tw", 2)
        bluesky_posts = make_posts_list("bsky", 2)
        rss_posts = make_posts_list("rss", 2)

        collector = _build_collector()
        collector._search_engine.collect = tracking_collect("SearchEngine", search_posts)
        collector._bluesky.collect = tracking_collect("Bluesky", bluesky_posts)
        collector._rss.collect = tracking_collect("RSS", rss_posts)

        await _collect_all(collector, limit=100)

        assert call_order == ["SearchEngine", "Bluesky", "RSS"]

    @pytest.mark.asyncio
    async def test_stops_when_limit_reached(self):
        """验证达到配额后不再调用后续 Provider"""
        call_order: List[str] = []

        def tracking_collect(name: str, posts: List[RawPost]):
            async def mock_collect(keyword, limit, seen_ids, on_progress=None, **kwargs):
                call_order.append(name)
                buf = []
                for post in posts:
                    if post.external_id in seen_ids:
                        continue
                    seen_ids.add(post.external_id)
                    buf.append(post)
                    if len(buf) >= limit:
                        break
                if buf:
                    yield buf
            return mock_collect

        # SearchEngine 提供 5 条，limit=5，后续 Provider 不应被调用
        search_posts = make_posts_list("tw", 5)
        collector = _build_collector()
        collector._search_engine.collect = tracking_collect("SearchEngine", search_posts)
        collector._bluesky.collect = tracking_collect("Bluesky", [])
        collector._rss.collect = tracking_collect("RSS", [])

        await _collect_all(collector, limit=5)

        assert call_order == ["SearchEngine"]


# === 测试单个 Provider 失败时的降级 ===
# 需求 5.3: 某个 Provider 失败时记录错误并继续下一个


class TestProviderDegradation:
    """测试单个 Provider 失败时自动降级到下一个"""

    @pytest.mark.asyncio
    async def test_search_engine_fails_bluesky_succeeds(self):
        """SearchEngine 失败后，Bluesky 正常采集"""
        bluesky_posts = make_posts_list("bsky", 3)

        collector = _build_collector()
        collector._search_engine.collect = create_failing_provider_collect("搜索引擎不可用")
        collector._bluesky.collect = create_mock_provider_collect(bluesky_posts)

        batches = await _collect_all(collector, limit=10)
        all_posts = [p for b in batches for p in b]

        assert len(all_posts) == 3
        assert all(p.external_id.startswith("bsky_") for p in all_posts)

    @pytest.mark.asyncio
    async def test_search_and_bluesky_fail_rss_succeeds(self):
        """SearchEngine 和 Bluesky 都失败后，RSS 正常采集"""
        rss_posts = make_posts_list("rss", 2)

        collector = _build_collector()
        collector._search_engine.collect = create_failing_provider_collect("搜索引擎不可用")
        collector._bluesky.collect = create_failing_provider_collect("Bluesky API 超时")
        collector._rss.collect = create_mock_provider_collect(rss_posts)

        batches = await _collect_all(collector, limit=10)
        all_posts = [p for b in batches for p in b]

        assert len(all_posts) == 2
        assert all(p.external_id.startswith("rss_") for p in all_posts)

    @pytest.mark.asyncio
    async def test_first_provider_partial_second_supplements(self):
        """第一个 Provider 部分成功，第二个补充剩余配额"""
        search_posts = make_posts_list("tw", 3)
        bluesky_posts = make_posts_list("bsky", 5)

        collector = _build_collector()
        collector._search_engine.collect = create_mock_provider_collect(search_posts)
        collector._bluesky.collect = create_mock_provider_collect(bluesky_posts)

        batches = await _collect_all(collector, limit=6)
        all_posts = [p for b in batches for p in b]

        assert len(all_posts) == 6
        # 前 3 条来自 SearchEngine，后 3 条来自 Bluesky
        tw_posts = [p for p in all_posts if p.external_id.startswith("tw_")]
        bsky_posts = [p for p in all_posts if p.external_id.startswith("bsky_")]
        assert len(tw_posts) == 3
        assert len(bsky_posts) == 3


# === 测试所有 Provider 失败时抛出 RuntimeError ===
# 需求 5.5: 所有 Provider 均失败且未采集到任何数据时抛出 RuntimeError


class TestAllProvidersFail:
    """测试所有 Provider 均失败时的行为"""

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_runtime_error(self):
        """所有 Provider 失败时应抛出 RuntimeError"""
        collector = _build_collector()
        collector._search_engine.collect = create_failing_provider_collect("搜索引擎不可用")
        collector._bluesky.collect = create_failing_provider_collect("Bluesky 超时")
        collector._rss.collect = create_failing_provider_collect("RSS 源不可用")

        with pytest.raises(RuntimeError, match="所有 Provider 均失败"):
            await _collect_all(collector, limit=10)

    @pytest.mark.asyncio
    async def test_error_message_contains_provider_details(self):
        """RuntimeError 错误信息应包含各 Provider 的失败原因"""
        collector = _build_collector()
        collector._search_engine.collect = create_failing_provider_collect("DuckDuckGo 验证码")
        collector._bluesky.collect = create_failing_provider_collect("API 429")
        collector._rss.collect = create_failing_provider_collect("XML 解析失败")

        with pytest.raises(RuntimeError) as exc_info:
            await _collect_all(collector, limit=10)

        error_msg = str(exc_info.value)
        assert "SearchEngine" in error_msg
        assert "Bluesky" in error_msg
        assert "RSS" in error_msg

    @pytest.mark.asyncio
    async def test_all_providers_return_empty_no_error(self):
        """所有 Provider 返回空数据（无异常）时不应抛出 RuntimeError"""
        collector = _build_collector()
        # 默认所有 Provider 返回空列表，不抛异常

        batches = await _collect_all(collector, limit=10)
        all_posts = [p for b in batches for p in b]
        assert len(all_posts) == 0


# === 测试环境变量配置 ===
# 需求 7.5: 通过 TWITTER_ZERO_COST_ENABLED 环境变量控制启用


class TestEnvironmentConfig:
    """测试 is_zero_cost_enabled 环境变量配置"""

    def test_default_enabled(self):
        """未设置环境变量时默认启用"""
        with patch.dict("os.environ", {}, clear=True):
            assert is_zero_cost_enabled() is True

    def test_explicit_true(self):
        """设置为 'true' 时启用"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "true"}):
            assert is_zero_cost_enabled() is True

    def test_explicit_True_uppercase(self):
        """设置为 'True' 时启用（大小写不敏感）"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "True"}):
            assert is_zero_cost_enabled() is True

    def test_explicit_false(self):
        """设置为 'false' 时禁用"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "false"}):
            assert is_zero_cost_enabled() is False

    def test_explicit_zero(self):
        """设置为 '0' 时禁用"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "0"}):
            assert is_zero_cost_enabled() is False

    def test_explicit_no(self):
        """设置为 'no' 时禁用"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "no"}):
            assert is_zero_cost_enabled() is False

    def test_random_value_enabled(self):
        """设置为其他值时视为启用"""
        with patch.dict("os.environ", {"TWITTER_ZERO_COST_ENABLED": "yes"}):
            assert is_zero_cost_enabled() is True
