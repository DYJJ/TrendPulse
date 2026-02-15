"""
采集监控日志模块

提供采集任务生命周期日志：任务开始、批次完成、任务完成、异常检测。
连续 3 批次采集为 0 时记录警告。

需求: 8.1, 8.2, 8.3, 8.4
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 连续空批次告警阈值
EMPTY_BATCH_THRESHOLD = 3


@dataclass
class SourceStats:
    """单数据源采集统计

    Args:
        source: 数据源名称
        collected: 已采集条数
        batch_count: 已完成批次数
        errors: 错误列表
    """
    source: str
    collected: int = 0
    batch_count: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class TaskMonitorState:
    """任务监控状态

    Args:
        task_id: 任务 ID
        keyword: 搜索关键词
        target: 目标采集条数
        sources: 数据源列表
        start_time: 任务开始时间戳
        source_stats: 各数据源统计
        consecutive_empty: 各数据源连续空批次计数
        paused_sources: 因异常暂停的数据源集合
    """
    task_id: str
    keyword: str
    target: int
    sources: List[str]
    start_time: float = 0.0
    source_stats: Dict[str, SourceStats] = field(default_factory=dict)
    consecutive_empty: Dict[str, int] = field(default_factory=dict)
    paused_sources: set = field(default_factory=set)


class CollectionMonitor:
    """采集任务监控器

    跟踪采集任务的完整生命周期，记录结构化日志。

    需求: 8.1, 8.2, 8.3, 8.4
    """

    def __init__(self) -> None:
        """初始化监控器"""
        self._tasks: Dict[str, TaskMonitorState] = {}
        # 各数据源的批次开始时间
        self._batch_start_times: Dict[str, float] = {}

    def on_task_start(
        self,
        task_id: str,
        keyword: str,
        target: int,
        sources: List[str],
    ) -> None:
        """记录任务开始日志

        Args:
            task_id: 任务 ID
            keyword: 搜索关键词
            target: 目标采集条数
            sources: 数据源列表
        """
        state = TaskMonitorState(
            task_id=task_id,
            keyword=keyword,
            target=target,
            sources=sources,
            start_time=time.monotonic(),
        )
        for source in sources:
            state.source_stats[source] = SourceStats(source=source)
            state.consecutive_empty[source] = 0
        self._tasks[task_id] = state

        logger.info(
            "采集任务开始 | task_id=%s | 关键词=%s | 目标数量=%d | 数据源=%s",
            task_id,
            keyword,
            target,
            ",".join(sources),
        )

    def on_batch_start(self, task_id: str, source: str) -> None:
        """记录批次开始时间

        Args:
            task_id: 任务 ID
            source: 数据源名称
        """
        key = f"{task_id}:{source}"
        self._batch_start_times[key] = time.monotonic()

    def on_batch_complete(
        self,
        task_id: str,
        source: str,
        batch_index: int,
        batch_collected: int,
    ) -> None:
        """记录批次完成日志，检测连续空批次异常

        Args:
            task_id: 任务 ID
            source: 数据源名称
            batch_index: 批次编号（从 1 开始）
            batch_collected: 本批次采集条数
        """
        state = self._tasks.get(task_id)
        if not state:
            return

        # 计算批次耗时
        key = f"{task_id}:{source}"
        batch_start = self._batch_start_times.pop(key, None)
        elapsed = time.monotonic() - batch_start if batch_start else 0.0

        # 更新数据源统计
        ss = state.source_stats.get(source)
        if ss:
            ss.collected += batch_collected
            ss.batch_count += 1

        logger.info(
            "批次完成 | task_id=%s | 数据源=%s | 批次=%d | 采集数量=%d | 耗时=%.2fs",
            task_id,
            source,
            batch_index,
            batch_collected,
            elapsed,
        )

        # 异常检测：连续空批次
        if batch_collected == 0:
            state.consecutive_empty[source] = state.consecutive_empty.get(source, 0) + 1
            if state.consecutive_empty[source] >= EMPTY_BATCH_THRESHOLD:
                state.paused_sources.add(source)
                logger.warning(
                    "异常检测 | task_id=%s | 数据源=%s | 连续 %d 批次采集为 0，暂停该数据源采集",
                    task_id,
                    source,
                    state.consecutive_empty[source],
                )
        else:
            state.consecutive_empty[source] = 0

    def on_source_error(
        self,
        task_id: str,
        source: str,
        error: str,
    ) -> None:
        """记录数据源采集错误

        Args:
            task_id: 任务 ID
            source: 数据源名称
            error: 错误信息
        """
        state = self._tasks.get(task_id)
        if not state:
            return

        ss = state.source_stats.get(source)
        if ss:
            ss.errors.append(error)

        logger.error(
            "数据源错误 | task_id=%s | 数据源=%s | 错误=%s",
            task_id,
            source,
            error,
        )

    def on_task_complete(self, task_id: str) -> Optional[Dict]:
        """记录任务完成日志，输出各数据源统计汇总

        Args:
            task_id: 任务 ID

        Returns:
            Dict: 任务统计摘要，不存在返回 None
        """
        state = self._tasks.get(task_id)
        if not state:
            return None

        elapsed = time.monotonic() - state.start_time
        total_collected = sum(ss.collected for ss in state.source_stats.values())

        # 构建各数据源统计摘要
        source_summary = {}
        for source, ss in state.source_stats.items():
            source_summary[source] = {
                "collected": ss.collected,
                "batch_count": ss.batch_count,
                "errors": len(ss.errors),
            }

        error_count = sum(len(ss.errors) for ss in state.source_stats.values())

        logger.info(
            "采集任务完成 | task_id=%s | 总耗时=%.2fs | 总采集数=%d | 各数据源=%s | 错误数=%d",
            task_id,
            elapsed,
            total_collected,
            str(source_summary),
            error_count,
        )

        summary = {
            "task_id": task_id,
            "elapsed": elapsed,
            "total_collected": total_collected,
            "source_summary": source_summary,
            "error_count": error_count,
        }

        return summary

    def is_source_paused(self, task_id: str, source: str) -> bool:
        """检查数据源是否因异常被暂停

        Args:
            task_id: 任务 ID
            source: 数据源名称

        Returns:
            bool: 是否已暂停
        """
        state = self._tasks.get(task_id)
        if not state:
            return False
        return source in state.paused_sources

    def get_task_state(self, task_id: str) -> Optional[TaskMonitorState]:
        """获取任务监控状态

        Args:
            task_id: 任务 ID

        Returns:
            TaskMonitorState: 监控状态，不存在返回 None
        """
        return self._tasks.get(task_id)
