"""
采集监控日志测试

测试 CollectionMonitor 的生命周期日志功能：
- 任务开始日志
- 批次完成日志
- 任务完成日志与统计汇总
- 连续空批次异常检测

需求: 8.1, 8.2, 8.3, 8.4
"""

import logging

from backend.app.collection_monitor import (
    CollectionMonitor,
    EMPTY_BATCH_THRESHOLD,
)


def test_task_start_logging(caplog):
    """测试任务开始时记录正确的日志信息

    验证需求: 8.1
    """
    monitor = CollectionMonitor()

    with caplog.at_level(logging.INFO):
        monitor.on_task_start(
            task_id="task-001",
            keyword="AI",
            target=10000,
            sources=["reddit", "youtube"],
        )

    assert "采集任务开始" in caplog.text
    assert "task-001" in caplog.text
    assert "AI" in caplog.text
    assert "10000" in caplog.text
    assert "reddit" in caplog.text
    assert "youtube" in caplog.text


def test_batch_complete_logging(caplog):
    """测试批次完成时记录批次编号、采集数量、耗时

    验证需求: 8.2
    """
    monitor = CollectionMonitor()
    monitor.on_task_start("task-002", "test", 5000, ["reddit"])

    with caplog.at_level(logging.INFO):
        monitor.on_batch_start("task-002", "reddit")
        monitor.on_batch_complete("task-002", "reddit", batch_index=1, batch_collected=500)

    assert "批次完成" in caplog.text
    assert "task-002" in caplog.text
    assert "reddit" in caplog.text
    # 批次编号
    assert "1" in caplog.text
    # 采集数量
    assert "500" in caplog.text


def test_task_complete_logging(caplog):
    """测试任务完成时记录总耗时、总采集数、各数据源统计

    验证需求: 8.3
    """
    monitor = CollectionMonitor()
    monitor.on_task_start("task-003", "test", 1000, ["reddit", "youtube"])

    # 模拟 reddit 采集了 2 批
    monitor.on_batch_start("task-003", "reddit")
    monitor.on_batch_complete("task-003", "reddit", 1, 500)
    monitor.on_batch_start("task-003", "reddit")
    monitor.on_batch_complete("task-003", "reddit", 2, 300)

    # 模拟 youtube 采集了 1 批
    monitor.on_batch_start("task-003", "youtube")
    monitor.on_batch_complete("task-003", "youtube", 1, 200)

    with caplog.at_level(logging.INFO):
        summary = monitor.on_task_complete("task-003")

    assert summary is not None
    assert summary["task_id"] == "task-003"
    assert summary["total_collected"] == 1000  # 500 + 300 + 200
    assert summary["source_summary"]["reddit"]["collected"] == 800
    assert summary["source_summary"]["reddit"]["batch_count"] == 2
    assert summary["source_summary"]["youtube"]["collected"] == 200
    assert summary["source_summary"]["youtube"]["batch_count"] == 1
    assert "采集任务完成" in caplog.text


def test_empty_batch_anomaly_detection(caplog):
    """测试连续空批次异常检测：连续 3 批采集为 0 时记录警告

    验证需求: 8.4
    """
    monitor = CollectionMonitor()
    monitor.on_task_start("task-004", "test", 5000, ["reddit"])

    # 前 2 批为空，不应触发警告
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        for i in range(EMPTY_BATCH_THRESHOLD - 1):
            monitor.on_batch_complete("task-004", "reddit", i + 1, 0)
        assert "异常检测" not in caplog.text

    # 第 3 批为空，应触发警告
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        monitor.on_batch_complete(
            "task-004", "reddit", EMPTY_BATCH_THRESHOLD, 0,
        )
        assert "异常检测" in caplog.text
        assert "连续" in caplog.text

    # 数据源应被标记为暂停
    assert monitor.is_source_paused("task-004", "reddit")


def test_empty_batch_counter_resets_on_nonempty():
    """测试非空批次重置连续空批次计数器"""
    monitor = CollectionMonitor()
    monitor.on_task_start("task-005", "test", 5000, ["reddit"])

    # 连续 2 批为空
    monitor.on_batch_complete("task-005", "reddit", 1, 0)
    monitor.on_batch_complete("task-005", "reddit", 2, 0)

    # 第 3 批有数据，重置计数器
    monitor.on_batch_complete("task-005", "reddit", 3, 100)

    # 再连续 2 批为空，不应触发暂停
    monitor.on_batch_complete("task-005", "reddit", 4, 0)
    monitor.on_batch_complete("task-005", "reddit", 5, 0)

    assert not monitor.is_source_paused("task-005", "reddit")


def test_source_error_logging(caplog):
    """测试数据源错误日志记录"""
    monitor = CollectionMonitor()
    monitor.on_task_start("task-006", "test", 1000, ["twitter"])

    with caplog.at_level(logging.ERROR):
        monitor.on_source_error("task-006", "twitter", "连接超时")

    assert "数据源错误" in caplog.text
    assert "twitter" in caplog.text
    assert "连接超时" in caplog.text

    # 错误应记录在统计中
    summary = monitor.on_task_complete("task-006")
    assert summary["error_count"] == 1
    assert summary["source_summary"]["twitter"]["errors"] == 1


def test_nonexistent_task_returns_none():
    """测试对不存在的任务调用方法不会崩溃"""
    monitor = CollectionMonitor()

    # 不应抛异常
    monitor.on_batch_complete("nonexistent", "reddit", 1, 100)
    monitor.on_source_error("nonexistent", "reddit", "error")
    assert monitor.on_task_complete("nonexistent") is None
    assert not monitor.is_source_paused("nonexistent", "reddit")
    assert monitor.get_task_state("nonexistent") is None
