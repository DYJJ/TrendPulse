"""
X(Twitter) 批量采集器属性测试（新架构）

使用 Hypothesis 库对重构后的 TwitterBatchCollector 进行基于属性的测试。
通过模拟 TwscrapeProvider 输出验证采集逻辑的正确性，不实际访问外部服务。

Feature: twitter-scraping-upgrade
- Property 6: 批次大小不变量
- Property 7: 进度回调频率
- Property 8: 基于 external_id 的去重
- Property 9: 无效推文数据过滤
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings, strategies as st, HealthCheck

from backend.app.collectors.twitter_batch_collector import (
    BATCH_SIZE,
    TwitterBatchCollector,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助函数 ---


def _make_raw_post(
    index: int,
    external_id: Optional[str] = None,
    content: Optional[str] = None,
) -> RawPost:
    """创建 RawPost 对象

    Args:
        index: 索引，用于生成默认字段值
        external_id: 推文 ID，None 时使用默认值
        content: 推文内容，None 时使用默认值
    """
    return RawPost(
        id=str(uuid.uuid4()),
        source=DataSource.TWITTER,
        external_id=external_id if external_id is not None else f"tweet_{index}",
        title=None,
        content=content if content is not None else f"推文内容 {index}",
        author=f"user_{index}",
        url=f"https://x.com/user_{index}/status/tweet_{index}",
        timestamp=datetime.now(timezone.utc),
        likes=index * 10,
        comments=index * 2,
        shares=index * 5,
    )


def _make_mock_twscrape_provider(posts: List[RawPost]):
    """创建模拟的 TwscrapeProvider，其 search 方法逐条 yield 给定的 posts"""
    provider = AsyncMock()

    async def mock_search(*args, **kwargs) -> AsyncGenerator[RawPost, None]:
        for post in posts:
            yield post

    provider.search = mock_search
    provider.close = AsyncMock()
    return provider


def _run_async(coro):
    """在新的事件循环中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect_all_batches(
    collector: TwitterBatchCollector,
    keyword: str,
    limit: int,
    on_progress=None,
) -> List[List[RawPost]]:
    """收集所有批次，返回批次列表（保留批次结构）"""
    batches: List[List[RawPost]] = []
    async for batch in collector.collect(
        keyword=keyword, limit=limit, on_progress=on_progress,
    ):
        batches.append(batch)
    return batches


# --- Property 6: 批次大小不变量 ---


class TestBatchSizeInvariant:
    """Feature: twitter-scraping-upgrade, Property 6: 批次大小不变量

    *For any* 批量采集产生的数据批次序列，除最后一个批次外，
    每个批次的大小应恰好为 500 条。最后一个批次的大小应在 1 到 500 之间（含）。

    **Validates: Requirements 4.3**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(total=st.integers(min_value=1, max_value=2500))
    def test_batch_sizes_are_correct(self, total: int):
        """除最后一批外每批恰好 500 条，最后一批 1-500 条

        **Validates: Requirements 4.3**
        """
        # 生成 total 条有效且唯一的推文
        posts = [_make_raw_post(i) for i in range(total)]
        mock_provider = _make_mock_twscrape_provider(posts)

        # 使用 twscrape 账号配置使其走 twscrape 路径
        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )

        async def run():
            # 注入模拟的 provider，跳过真实初始化
            collector._twscrape_provider = mock_provider
            return await _collect_all_batches(collector, "test", total)

        batches = _run_async(run())

        if not batches:
            return

        # 除最后一批外，每批恰好 BATCH_SIZE 条
        for batch in batches[:-1]:
            assert len(batch) == BATCH_SIZE, (
                f"非最后批次大小应为 {BATCH_SIZE}，实际为 {len(batch)}"
            )

        # 最后一批大小在 1 到 BATCH_SIZE 之间
        last_batch = batches[-1]
        assert 1 <= len(last_batch) <= BATCH_SIZE, (
            f"最后批次大小应在 1-{BATCH_SIZE} 之间，实际为 {len(last_batch)}"
        )


# --- Property 7: 进度回调频率 ---


class TestProgressCallbackFrequency:
    """Feature: twitter-scraping-upgrade, Property 7: 进度回调频率

    *For any* 总采集数量 N，进度回调函数被调用的次数应至少为 N // 500 次
    （每 500 条报告一次）。

    **Validates: Requirements 4.2**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(total=st.integers(min_value=1, max_value=2500))
    def test_progress_callback_called_enough_times(self, total: int):
        """进度回调次数应至少为 N // 500

        **Validates: Requirements 4.2**
        """
        posts = [_make_raw_post(i) for i in range(total)]
        mock_provider = _make_mock_twscrape_provider(posts)

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )

        progress_calls: list[int] = []

        def on_progress(count: int):
            progress_calls.append(count)

        async def run():
            collector._twscrape_provider = mock_provider
            return await _collect_all_batches(
                collector, "test", total, on_progress=on_progress,
            )

        batches = _run_async(run())

        # 实际采集的总数
        actual_total = sum(len(b) for b in batches)

        # 进度回调次数应至少为 actual_total // BATCH_SIZE
        # （每满 500 条回调一次，剩余不足 500 条也会回调一次）
        min_expected_calls = actual_total // BATCH_SIZE
        assert len(progress_calls) >= min_expected_calls, (
            f"采集 {actual_total} 条时，进度回调应至少 {min_expected_calls} 次，"
            f"实际 {len(progress_calls)} 次"
        )


# --- Property 8: 基于 external_id 的去重 ---


class TestDeduplicationByExternalId:
    """Feature: twitter-scraping-upgrade, Property 8: 基于 external_id 的去重

    *For any* 包含重复 external_id 的推文数据列表，经过采集器处理后，
    输出的 RawPost 列表中不应存在两条具有相同 external_id 的记录。

    **Validates: Requirements 5.1**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(
        unique_count=st.integers(min_value=1, max_value=200),
        dup_factor=st.integers(min_value=2, max_value=5),
    )
    def test_no_duplicate_external_ids_in_output(
        self, unique_count: int, dup_factor: int,
    ):
        """输出中不应存在重复的 external_id

        **Validates: Requirements 5.1**
        """
        # 创建唯一推文
        unique_posts = [_make_raw_post(i) for i in range(unique_count)]

        # 通过重复来制造重复数据
        duplicated_posts = unique_posts * dup_factor
        mock_provider = _make_mock_twscrape_provider(duplicated_posts)

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )

        async def run():
            collector._twscrape_provider = mock_provider
            batches = await _collect_all_batches(
                collector, "test", unique_count * dup_factor,
            )
            return [post for batch in batches for post in batch]

        all_posts = _run_async(run())

        # 检查输出中无重复 external_id
        seen_ids = set()
        for post in all_posts:
            assert post.external_id not in seen_ids, (
                f"发现重复的 external_id: {post.external_id}"
            )
            seen_ids.add(post.external_id)

        # 去重后数量应等于唯一推文数
        assert len(all_posts) == unique_count, (
            f"去重后应有 {unique_count} 条，实际 {len(all_posts)} 条"
        )


# --- Property 9: 无效推文数据过滤 ---


class TestInvalidTweetFiltering:
    """Feature: twitter-scraping-upgrade, Property 9: 无效推文数据过滤

    *For any* 推文数据，若其 content 为空/纯空白字符，或缺少 external_id，
    则该条数据应被丢弃，不出现在输出中。

    **Validates: Requirements 5.2, 5.3**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(
        valid_count=st.integers(min_value=1, max_value=100),
        empty_content_count=st.integers(min_value=1, max_value=20),
        blank_content_count=st.integers(min_value=1, max_value=20),
        missing_id_count=st.integers(min_value=1, max_value=20),
    )
    def test_invalid_posts_are_filtered_out(
        self,
        valid_count: int,
        empty_content_count: int,
        blank_content_count: int,
        missing_id_count: int,
    ):
        """空内容或缺少 external_id 的推文应被过滤

        **Validates: Requirements 5.2, 5.3**
        """
        posts: List[RawPost] = []

        # 有效推文
        for i in range(valid_count):
            posts.append(_make_raw_post(i))

        # 空内容推文
        for i in range(empty_content_count):
            posts.append(_make_raw_post(
                valid_count + i,
                external_id=f"empty_{i}",
                content="",
            ))

        # 纯空白内容推文
        for i in range(blank_content_count):
            posts.append(_make_raw_post(
                valid_count + empty_content_count + i,
                external_id=f"blank_{i}",
                content="   \t\n  ",
            ))

        # 缺少 external_id 的推文
        for i in range(missing_id_count):
            posts.append(_make_raw_post(
                valid_count + empty_content_count + blank_content_count + i,
                external_id="",
                content=f"有 ID 缺失的推文 {i}",
            ))

        total_input = len(posts)
        mock_provider = _make_mock_twscrape_provider(posts)

        collector = TwitterBatchCollector(
            batch_delay=0,
            accounts=[{"username": "u", "password": "p", "email": "e", "email_password": "ep"}],
        )

        async def run():
            collector._twscrape_provider = mock_provider
            batches = await _collect_all_batches(
                collector, "test", total_input,
            )
            return [post for batch in batches for post in batch]

        all_posts = _run_async(run())

        # 输出中不应包含空内容或缺少 external_id 的推文
        for post in all_posts:
            assert post.content and post.content.strip(), (
                f"输出中包含空内容推文: external_id={post.external_id}"
            )
            assert post.external_id, (
                "输出中包含缺少 external_id 的推文"
            )

        # 输出数量应等于有效推文数
        assert len(all_posts) == valid_count, (
            f"过滤后应有 {valid_count} 条有效推文，实际 {len(all_posts)} 条"
        )
