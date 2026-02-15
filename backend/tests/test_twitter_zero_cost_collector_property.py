"""
ZeroCostCollector 的属性测试

使用 Hypothesis 验证 ZeroCostCollector 的正确性属性：
- Property 3: 批次大小不变量
- Property 6: 去重不变量
- Property 7: 配额与合并一致性
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional, Set
from unittest.mock import AsyncMock, patch, MagicMock

from hypothesis import given, strategies as st, settings

from backend.app.collectors.zero_cost.constants import BATCH_SIZE
from backend.app.collectors.twitter_zero_cost_collector import ZeroCostCollector
from backend.app.models.data_models import DataSource, RawPost


# === 辅助函数 ===


def make_raw_post(prefix: str, idx: int) -> RawPost:
    """构造一个测试用 RawPost 对象

    Args:
        prefix: ID 前缀（tw/bsky/rss）
        idx: 唯一索引号
    """
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
        likes=0,
        comments=0,
        shares=0,
    )


def make_posts_list(prefix: str, count: int, start_idx: int = 0) -> List[RawPost]:
    """构造指定数量的 RawPost 列表"""
    return [make_raw_post(prefix, start_idx + i) for i in range(count)]


async def collect_all_batches(collector: ZeroCostCollector, keyword: str, limit: int) -> List[List[RawPost]]:
    """收集所有 yield 的批次"""
    batches: List[List[RawPost]] = []
    async for batch in collector.collect(keyword=keyword, limit=limit):
        batches.append(batch)
    return batches


def create_mock_provider_collect(posts: List[RawPost], batch_size: int = BATCH_SIZE):
    """创建一个模拟 Provider 的 collect 异步生成器工厂

    按 batch_size 分批 yield posts，模拟真实 Provider 行为。
    """
    async def mock_collect(
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> AsyncGenerator[List[RawPost], None]:
        # 过滤已见过的和超出 limit 的
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


# === Property 3: 批次大小不变量 ===
# Validates: Requirements 1.7, 3.6, 7.2


@settings(max_examples=100)
@given(
    total_count=st.integers(min_value=1, max_value=2500),
)
def test_property3_batch_size_invariant(total_count: int):
    """Property 3: 除最后一个批次外，每个批次大小应恰好为 500 条；
    最后一个批次大小应在 1 到 500 之间（含）。

    通过模拟 SearchEngineProvider 产出指定数量的 RawPost，
    验证 ZeroCostCollector yield 的批次满足大小约束。

    **Validates: Requirements 1.7, 3.6, 7.2**
    """
    # 构造测试数据：所有数据来自 SearchEngine
    posts = make_posts_list("tw", total_count)
    limit = total_count  # 配额等于数据量，确保全部采集

    loop = asyncio.new_event_loop()
    try:
        collector = ZeroCostCollector.__new__(ZeroCostCollector)
        collector._batch_delay = 0
        collector._proxy = None

        # 模拟 Provider
        collector._syndication = MagicMock()
        collector._search_engine = MagicMock()
        collector._bluesky = MagicMock()
        collector._rss = MagicMock()

        # SearchEngine 产出所有数据
        collector._search_engine.collect = create_mock_provider_collect(posts)
        # 其他 Provider 不产出数据
        collector._bluesky.collect = create_mock_provider_collect([])
        collector._rss.collect = create_mock_provider_collect([])

        batches = loop.run_until_complete(
            collect_all_batches(collector, "test", limit)
        )

        assert len(batches) > 0, "应至少产出一个批次"

        # 验证非最后批次大小恰好为 BATCH_SIZE
        for i, batch in enumerate(batches[:-1]):
            assert len(batch) == BATCH_SIZE, (
                f"第 {i} 个批次大小应为 {BATCH_SIZE}，实际: {len(batch)}"
            )

        # 验证最后一个批次大小在 [1, BATCH_SIZE]
        last_batch = batches[-1]
        assert 1 <= len(last_batch) <= BATCH_SIZE, (
            f"最后一个批次大小应在 [1, {BATCH_SIZE}]，实际: {len(last_batch)}"
        )

        # 验证总数等于预期
        total = sum(len(b) for b in batches)
        assert total == total_count, (
            f"总采集数应为 {total_count}，实际: {total}"
        )
    finally:
        loop.close()


# === Property 6: 去重不变量 ===
# Validates: Requirements 5.6


@settings(max_examples=100)
@given(
    search_count=st.integers(min_value=0, max_value=50),
    bluesky_count=st.integers(min_value=0, max_value=50),
    rss_count=st.integers(min_value=0, max_value=50),
    overlap_count=st.integers(min_value=0, max_value=20),
)
def test_property6_deduplication_invariant(
    search_count: int,
    bluesky_count: int,
    rss_count: int,
    overlap_count: int,
):
    """Property 6: 经过 seen_ids 去重后，输出中不应存在两个具有相同 external_id 的 RawPost。

    构造三个 Provider 的数据，其中部分 external_id 重叠，
    验证 ZeroCostCollector 输出无重复。

    **Validates: Requirements 5.6**
    """
    # 确保 overlap 不超过各 Provider 的数据量
    actual_overlap = min(overlap_count, search_count, bluesky_count)

    # SearchEngine 数据
    search_posts = make_posts_list("tw", search_count, start_idx=0)

    # Bluesky 数据：前 actual_overlap 条与 SearchEngine 使用相同 external_id
    bluesky_posts = []
    for i in range(bluesky_count):
        if i < actual_overlap:
            # 复用 SearchEngine 的 external_id 制造重复
            dup_post = make_raw_post("tw", i)
            dup_post.id = f"bsky_dup_{i}"  # 不同 id 但相同 external_id
            bluesky_posts.append(dup_post)
        else:
            bluesky_posts.append(make_raw_post("bsky", i))

    # RSS 数据
    rss_posts = make_posts_list("rss", rss_count, start_idx=0)

    total_limit = search_count + bluesky_count + rss_count + 100  # 足够大的配额

    loop = asyncio.new_event_loop()
    try:
        collector = ZeroCostCollector.__new__(ZeroCostCollector)
        collector._batch_delay = 0
        collector._proxy = None
        collector._syndication = MagicMock()
        collector._search_engine = MagicMock()
        collector._bluesky = MagicMock()
        collector._rss = MagicMock()

        collector._search_engine.collect = create_mock_provider_collect(search_posts)
        collector._bluesky.collect = create_mock_provider_collect(bluesky_posts)
        collector._rss.collect = create_mock_provider_collect(rss_posts)

        batches = loop.run_until_complete(
            collect_all_batches(collector, "test", total_limit)
        )

        # 收集所有输出的 external_id
        all_external_ids = []
        for batch in batches:
            for post in batch:
                all_external_ids.append(post.external_id)

        # 验证无重复
        assert len(all_external_ids) == len(set(all_external_ids)), (
            f"输出中存在重复的 external_id: "
            f"总数 {len(all_external_ids)} vs 去重后 {len(set(all_external_ids))}"
        )
    finally:
        loop.close()


# === Property 7: 配额与合并一致性 ===
# Validates: Requirements 5.2, 5.4


@settings(max_examples=100)
@given(
    limit=st.integers(min_value=1, max_value=200),
    search_available=st.integers(min_value=0, max_value=150),
    bluesky_available=st.integers(min_value=0, max_value=150),
    rss_available=st.integers(min_value=0, max_value=150),
)
def test_property7_quota_and_merge_consistency(
    limit: int,
    search_available: int,
    bluesky_available: int,
    rss_available: int,
):
    """Property 7: ZeroCostCollector 输出的总条数应不超过 limit，
    且每个后续 Provider 收到的 remaining 配额应等于 limit 减去前面所有 Provider 的累计采集量。

    **Validates: Requirements 5.2, 5.4**
    """
    search_posts = make_posts_list("tw", search_available, start_idx=0)
    bluesky_posts = make_posts_list("bsky", bluesky_available, start_idx=0)
    rss_posts = make_posts_list("rss", rss_available, start_idx=0)

    # 记录每个 Provider 实际收到的 limit 参数
    received_limits: List[int] = []

    def create_tracking_collect(posts: List[RawPost]):
        """创建一个记录 limit 参数的模拟 collect"""
        async def mock_collect(
            keyword: str,
            limit: int,
            seen_ids: Set[str],
            on_progress: Optional[Callable[[int], None]] = None,
            **kwargs,
        ) -> AsyncGenerator[List[RawPost], None]:
            received_limits.append(limit)
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
                if len(buffer) >= BATCH_SIZE:
                    yield buffer[:BATCH_SIZE]
                    buffer = buffer[BATCH_SIZE:]
            if buffer:
                yield buffer
        return mock_collect

    loop = asyncio.new_event_loop()
    try:
        collector = ZeroCostCollector.__new__(ZeroCostCollector)
        collector._batch_delay = 0
        collector._proxy = None
        collector._syndication = MagicMock()
        collector._search_engine = MagicMock()
        collector._bluesky = MagicMock()
        collector._rss = MagicMock()

        collector._search_engine.collect = create_tracking_collect(search_posts)
        collector._bluesky.collect = create_tracking_collect(bluesky_posts)
        collector._rss.collect = create_tracking_collect(rss_posts)

        batches = loop.run_until_complete(
            collect_all_batches(collector, "test", limit)
        )

        total_collected = sum(len(b) for b in batches)

        # 验证总数不超过 limit
        assert total_collected <= limit, (
            f"总采集数 {total_collected} 超过 limit {limit}"
        )

        # 验证配额传递：每个 Provider 收到的 limit 应递减
        # 第一个 Provider 收到完整 limit
        if received_limits:
            assert received_limits[0] == limit, (
                f"第一个 Provider 应收到 limit={limit}，实际: {received_limits[0]}"
            )

        # 后续 Provider 收到的 limit 应等于 limit - 前面累计采集量
        cumulative = 0
        provider_idx = 0
        for batch_list_idx, provider_limit in enumerate(received_limits):
            if batch_list_idx == 0:
                assert provider_limit == limit
            else:
                expected_remaining = limit - cumulative
                assert provider_limit == expected_remaining, (
                    f"第 {batch_list_idx} 个 Provider 应收到 remaining={expected_remaining}，"
                    f"实际: {provider_limit}"
                )
            # 计算该 Provider 实际采集了多少
            # 通过 Provider 的可用数据和 limit 推算
            if batch_list_idx == 0:
                actual = min(search_available, provider_limit)
            elif batch_list_idx == 1:
                actual = min(bluesky_available, provider_limit)
            else:
                actual = min(rss_available, provider_limit)
            cumulative += actual
    finally:
        loop.close()
