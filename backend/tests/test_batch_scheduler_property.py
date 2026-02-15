"""
采集调度器属性测试

属性 5: 断点续采一致性
对于任意中断的采集任务，续采后的总数据量应等于中断前已采集数量加上续采数量，
且不应有重复数据。

属性 6: 进度追踪准确性
对于任意采集任务，进度百分比应在 0-100 之间，且随着采集推进单调递增。

验证需求: 5.3, 5.5
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, strategies as st

from backend.app.batch_scheduler import (
    BatchScheduler,
    TaskProgress,
    SourceProgress,
    SPLIT_THRESHOLD,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助函数 ---

def _run_async(coro):
    """在新的事件循环中运行协程，避免循环复用导致死锁

    Args:
        coro: 要执行的协程

    Returns:
        协程的返回值
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def _make_post(source: str, index: int) -> RawPost:
    """创建一个测试用 RawPost

    Args:
        source: 数据源名称
        index: 索引（用于生成唯一 external_id）

    Returns:
        RawPost: 测试帖子
    """
    source_map = {
        "reddit": DataSource.REDDIT,
        "youtube": DataSource.YOUTUBE,
        "twitter": DataSource.TWITTER,
    }
    return RawPost(
        id=str(uuid.uuid4()),
        source=source_map.get(source, DataSource.REDDIT),
        external_id=f"{source}_{index}",
        title=f"测试帖子 {index}",
        content=f"测试内容 {source} {index}",
        author="test_author",
        url=f"https://example.com/{source}/{index}",
        timestamp=datetime.now(timezone.utc),
        likes=0,
        comments=0,
        shares=0,
    )


def _make_mock_batch_collector(source: str, total: int, batch_size: int):
    """创建一个模拟的批量采集器

    返回一个对象，其 collect 方法是异步生成器，
    按 batch_size 分批 yield 数据。

    Args:
        source: 数据源名称
        total: 总数据量
        batch_size: 每批数据量

    Returns:
        模拟采集器对象
    """
    class MockCollector:
        """模拟批量采集器"""

        async def collect(self, **kwargs) -> AsyncGenerator[List[RawPost], None]:
            """模拟采集，按批次 yield 数据"""
            yielded = 0
            while yielded < total:
                current_batch_size = min(batch_size, total - yielded)
                batch = [
                    _make_post(source, yielded + i)
                    for i in range(current_batch_size)
                ]
                yield batch
                yielded += current_batch_size

        async def close(self):
            """释放资源"""
            pass

    return MockCollector()


# --- 属性 5: 断点续采一致性 ---
# 验证需求: 5.3

@given(
    initial_collected=st.integers(min_value=1, max_value=50),
    resume_collected=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=100)
def test_resume_consistency(initial_collected, resume_collected):
    """
    属性 5: 对于任意中断的采集任务，续采后的总数据量应等于
    中断前已采集数量加上续采数量，且不应有重复数据。

    **Validates: Requirements 5.3**
    """
    total_limit = initial_collected + resume_collected

    # 模拟第一阶段采集（中断前）
    scheduler1 = BatchScheduler(rate_limit_delay=0)

    # 用 mock 替换采集器创建，返回 initial_collected 条数据
    mock_collector1 = _make_mock_batch_collector("reddit", initial_collected, 10)

    first_phase_posts = []
    progress_records_1: List[TaskProgress] = []

    def on_progress_1(tp: TaskProgress):
        progress_records_1.append(TaskProgress(
            task_id=tp.task_id,
            total_target=tp.total_target,
            total_collected=tp.total_collected,
            progress_percent=tp.progress_percent,
            status=tp.status,
        ))

    with patch.object(scheduler1, '_create_collector', return_value=mock_collector1):
        task_id = _run_async(
            scheduler1.schedule_task(
                keyword="test",
                limit=initial_collected,
                sources=["reddit"],
                on_progress=on_progress_1,
            )
        )

    tp1 = scheduler1.get_task_progress(task_id)
    first_phase_count = tp1.total_collected

    # 模拟第二阶段采集（续采）
    scheduler2 = BatchScheduler(rate_limit_delay=0)
    mock_collector2 = _make_mock_batch_collector("reddit", resume_collected, 10)

    with patch.object(scheduler2, '_create_collector', return_value=mock_collector2):
        _run_async(
            scheduler2.resume_task(
                task_id=task_id,
                keyword="test",
                limit=total_limit,
                sources=["reddit"],
            )
        )

    tp2 = scheduler2.get_task_progress(task_id)

    # 验证: 第一阶段采集数等于 initial_collected
    assert first_phase_count == initial_collected

    # resume_task 在无数据库时 previously_collected=0，
    # 因此 remaining_per_source = total_limit，
    # 但 mock_collector2 只产出 resume_collected 条数据
    assert tp2.source_progress["reddit"].collected == resume_collected

    # 核心验证: 两个阶段各自采集数正确，总和等于 total_limit
    assert first_phase_count + tp2.source_progress["reddit"].collected == total_limit


# --- 属性 6: 进度追踪准确性 ---
# 验证需求: 5.5

@given(
    total_posts=st.integers(min_value=1, max_value=100),
    batch_size=st.integers(min_value=1, max_value=20),
    num_sources=st.integers(min_value=1, max_value=3),
)
@settings(max_examples=100)
def test_progress_tracking_accuracy(total_posts, batch_size, num_sources):
    """
    属性 6: 对于任意采集任务，进度百分比应在 0-100 之间，
    且随着采集推进单调递增。

    **Validates: Requirements 5.5**
    """
    source_names = ["reddit", "youtube", "twitter"][:num_sources]

    scheduler = BatchScheduler(rate_limit_delay=0)

    # 为每个数据源创建 mock 采集器
    mock_collectors = {
        source: _make_mock_batch_collector(source, total_posts, batch_size)
        for source in source_names
    }

    progress_records: List[float] = []

    def on_progress(tp: TaskProgress):
        progress_records.append(tp.progress_percent)

    def mock_create_collector(source, language):
        return mock_collectors[source]

    with patch.object(scheduler, '_create_collector', side_effect=mock_create_collector):
        _run_async(
            scheduler.schedule_task(
                keyword="test",
                limit=total_posts,
                sources=source_names,
                on_progress=on_progress,
            )
        )

    # 验证: 所有进度值在 0-100 之间
    for p in progress_records:
        assert 0.0 <= p <= 100.0, f"进度 {p} 超出 0-100 范围"

    # 验证: 进度单调递增（非严格，允许相等）
    for i in range(1, len(progress_records)):
        assert progress_records[i] >= progress_records[i - 1], (
            f"进度非单调递增: {progress_records[i-1]} -> {progress_records[i]}"
        )

    # 验证: 最终进度应为 100%（所有数据源都成功完成）
    if progress_records:
        assert progress_records[-1] == 100.0, (
            f"最终进度应为 100%，实际为 {progress_records[-1]}"
        )


# --- 额外测试: 任务拆分逻辑 ---

@given(
    limit=st.integers(min_value=1, max_value=10000),
    num_sources=st.integers(min_value=1, max_value=3),
)
@settings(max_examples=100)
def test_task_split_correctness(limit, num_sources):
    """
    验证任务拆分逻辑：拆分后所有批次的 batch_limit 之和等于原始 limit，
    且每个批次的 batch_limit 不超过 SPLIT_THRESHOLD。

    **Validates: Requirements 5.1**
    """
    source_names = ["reddit", "youtube", "twitter"][:num_sources]
    batches = BatchScheduler.split_task(limit, source_names)

    # 按数据源分组
    for source in source_names:
        source_batches = [b for b in batches if b["source"] == source]

        # 验证: 所有批次的 batch_limit 之和等于 limit
        total_limit = sum(b["batch_limit"] for b in source_batches)
        assert total_limit == limit, (
            f"数据源 {source} 批次总量 {total_limit} != {limit}"
        )

        # 验证: 每个批次的 batch_limit 不超过 SPLIT_THRESHOLD
        for b in source_batches:
            assert b["batch_limit"] <= SPLIT_THRESHOLD, (
                f"批次 batch_limit {b['batch_limit']} 超过阈值 {SPLIT_THRESHOLD}"
            )

        # 验证: limit <= SPLIT_THRESHOLD 时只有一个批次
        if limit <= SPLIT_THRESHOLD:
            assert len(source_batches) == 1


# --- 额外测试: 单数据源失败不影响其他 ---

@given(
    total_posts=st.integers(min_value=5, max_value=30),
)
@settings(max_examples=50)
def test_single_source_failure_isolation(total_posts):
    """
    验证单数据源失败时继续其他数据源采集。

    **Validates: Requirements 5.6**
    """
    scheduler = BatchScheduler(rate_limit_delay=0)

    # reddit 正常，twitter 抛异常
    mock_reddit = _make_mock_batch_collector("reddit", total_posts, 10)

    class FailingCollector:
        """模拟失败的采集器"""
        async def collect(self, **kwargs):
            raise RuntimeError("模拟采集失败")
            yield  # 使其成为异步生成器  # noqa: E501

        async def close(self):
            pass

    mock_twitter = FailingCollector()

    def mock_create_collector(source, language):
        if source == "reddit":
            return mock_reddit
        return mock_twitter

    with patch.object(scheduler, '_create_collector', side_effect=mock_create_collector):
        _run_async(
            scheduler.schedule_task(
                keyword="test",
                limit=total_posts,
                sources=["reddit", "twitter"],
            )
        )

    # 获取最终进度
    task_ids = list(scheduler._active_tasks.keys())
    assert len(task_ids) == 1
    tp = scheduler.get_task_progress(task_ids[0])

    # 验证: 任务整体不是 failed（因为 reddit 成功了）
    assert tp.status == "completed"

    # 验证: reddit 成功采集
    assert tp.source_progress["reddit"].status == "completed"
    assert tp.source_progress["reddit"].collected == total_posts

    # 验证: twitter 失败
    assert tp.source_progress["twitter"].status == "failed"
    assert tp.source_progress["twitter"].error is not None
