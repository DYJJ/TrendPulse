"""
BatchScheduler 集成单元测试

测试 _create_collector 方法根据环境变量 TWITTER_ZERO_COST_ENABLED
正确选择 ZeroCostCollector 或 TwitterBatchCollector。

需求: 7.4, 7.5
"""

import os
from unittest.mock import patch

import pytest

from backend.app.batch_scheduler import BatchScheduler


@pytest.fixture
def scheduler():
    """创建 BatchScheduler 实例"""
    return BatchScheduler()


class TestCreateCollectorTwitterZeroCost:
    """测试 BatchScheduler 根据环境变量选择 Twitter 采集器"""

    def test_zero_cost_enabled_by_default(self, scheduler):
        """默认情况下（未设置环境变量）应创建 ZeroCostCollector"""
        from backend.app.collectors.twitter_zero_cost_collector import ZeroCostCollector

        env = {k: v for k, v in os.environ.items() if k != "TWITTER_ZERO_COST_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            collector = scheduler._create_collector("twitter", "en")
            assert isinstance(collector, ZeroCostCollector)

    def test_zero_cost_enabled_explicit_true(self, scheduler):
        """环境变量为 'true' 时应创建 ZeroCostCollector"""
        from backend.app.collectors.twitter_zero_cost_collector import ZeroCostCollector

        with patch.dict(os.environ, {"TWITTER_ZERO_COST_ENABLED": "true"}, clear=False):
            collector = scheduler._create_collector("twitter", "en")
            assert isinstance(collector, ZeroCostCollector)

    def test_zero_cost_disabled_creates_twitter_batch(self, scheduler):
        """环境变量为 'false' 时应创建 TwitterBatchCollector"""
        from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector

        with patch.dict(os.environ, {"TWITTER_ZERO_COST_ENABLED": "false"}, clear=False):
            collector = scheduler._create_collector("twitter", "en")
            assert isinstance(collector, TwitterBatchCollector)

    def test_zero_cost_disabled_with_zero(self, scheduler):
        """环境变量为 '0' 时应创建 TwitterBatchCollector"""
        from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector

        with patch.dict(os.environ, {"TWITTER_ZERO_COST_ENABLED": "0"}, clear=False):
            collector = scheduler._create_collector("twitter", "en")
            assert isinstance(collector, TwitterBatchCollector)
