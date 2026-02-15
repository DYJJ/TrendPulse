"""
错误处理属性测试

使用Hypothesis库对异常捕获/日志记录和API重试机制进行基于属性的测试。

属性 23: 异常捕获和日志记录
属性 24: API重试机制
验证需求: 15.1, 15.2, 15.3, 15.4
"""

import asyncio
import logging

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from backend.app.utils.retry import retry_on_failure

# 重试模块的logger名称
RETRY_LOGGER_NAME = "backend.app.utils.retry"


# Feature: trendpulse-sentiment-analysis, Property 23: 异常捕获和日志记录
class TestExceptionCaptureAndLogging:
    """异常捕获和日志记录属性测试

    **验证: 需求 15.1, 15.2**

    对于任意可能抛出异常的操作，系统应该捕获异常并记录包含
    时间戳、日志级别、模块名称和错误详情的日志条目。
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        error_msg=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    )
    def test_retry_logs_warning_on_each_failed_attempt(self, error_msg: str, caplog):
        """重试过程中每次失败都应记录WARNING级别日志，包含函数名和错误详情

        **Validates: Requirements 15.1, 15.2**
        """
        caplog.clear()

        @retry_on_failure(max_retries=3, base_delay=0.0)
        def always_fail():
            raise ValueError(error_msg)

        with caplog.at_level(logging.WARNING, logger=RETRY_LOGGER_NAME):
            with pytest.raises(ValueError):
                always_fail()

        # 前2次失败应记录WARNING（第3次记录ERROR后抛出异常）
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 2
        for record in warning_records:
            assert "always_fail" in record.message
            assert error_msg in record.message

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        error_msg=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    )
    def test_retry_logs_error_on_final_failure(self, error_msg: str, caplog):
        """所有重试耗尽后应记录ERROR级别日志，包含函数名和错误详情

        **Validates: Requirements 15.1, 15.2**
        """
        caplog.clear()

        @retry_on_failure(max_retries=3, base_delay=0.0)
        def always_fail():
            raise RuntimeError(error_msg)

        with caplog.at_level(logging.ERROR, logger=RETRY_LOGGER_NAME):
            with pytest.raises(RuntimeError):
                always_fail()

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        last_error = error_records[-1]
        assert "always_fail" in last_error.message
        assert error_msg in last_error.message

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        error_msg=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    )
    def test_async_retry_logs_warning_on_each_failed_attempt(self, error_msg: str, caplog):
        """异步函数重试过程中每次失败都应记录WARNING级别日志

        **Validates: Requirements 15.1, 15.2**
        """
        caplog.clear()

        @retry_on_failure(max_retries=3, base_delay=0.0)
        async def async_always_fail():
            raise ValueError(error_msg)

        loop = asyncio.new_event_loop()
        try:
            with caplog.at_level(logging.WARNING, logger=RETRY_LOGGER_NAME):
                with pytest.raises(ValueError):
                    loop.run_until_complete(async_always_fail())
        finally:
            loop.close()

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 2
        for record in warning_records:
            assert "async_always_fail" in record.message
            assert error_msg in record.message

    def test_log_format_contains_required_fields(self, caplog):
        """日志格式应包含时间戳、级别、模块名称和消息

        **Validates: Requirements 15.2**
        """

        @retry_on_failure(max_retries=2, base_delay=0.0)
        def fail_once():
            raise RuntimeError("测试错误")

        with caplog.at_level(logging.WARNING, logger=RETRY_LOGGER_NAME):
            with pytest.raises(RuntimeError):
                fail_once()

        assert len(caplog.records) >= 1
        record = caplog.records[0]
        # 验证日志记录包含所有必需字段
        assert record.levelname in ("WARNING", "ERROR")
        assert record.name  # 模块名称
        assert record.message  # 消息内容
        assert record.created  # 时间戳（Unix时间）


# Feature: trendpulse-sentiment-analysis, Property 24: API重试机制
class TestRetryMechanism:
    """API重试机制属性测试

    **验证: 需求 15.3, 15.4**

    对于任意失败的API调用，系统应该最多重试3次，
    如果3次重试后仍然失败，应该返回错误状态。
    """

    @settings(max_examples=100)
    @given(max_retries=st.integers(min_value=1, max_value=5))
    def test_sync_retries_exact_count_then_raises(self, max_retries: int):
        """同步函数应恰好重试指定次数后抛出异常

        **Validates: Requirements 15.3, 15.4**
        """
        call_count = 0

        @retry_on_failure(max_retries=max_retries, base_delay=0.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("连接失败")

        with pytest.raises(ConnectionError):
            always_fail()

        assert call_count == max_retries

    @settings(max_examples=100)
    @given(max_retries=st.integers(min_value=1, max_value=5))
    def test_async_retries_exact_count_then_raises(self, max_retries: int):
        """异步函数应恰好重试指定次数后抛出异常

        **Validates: Requirements 15.3, 15.4**
        """
        call_count = 0

        @retry_on_failure(max_retries=max_retries, base_delay=0.0)
        async def async_always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("连接失败")

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(ConnectionError):
                loop.run_until_complete(async_always_fail())
        finally:
            loop.close()

        assert call_count == max_retries

    @settings(max_examples=100)
    @given(succeed_on=st.integers(min_value=1, max_value=3))
    def test_sync_succeeds_after_transient_failures(self, succeed_on: int):
        """同步函数在第N次尝试成功时应返回结果而不抛出异常

        **Validates: Requirements 15.3**
        """
        call_count = 0

        @retry_on_failure(max_retries=3, base_delay=0.0)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < succeed_on:
                raise ConnectionError("暂时失败")
            return "成功"

        result = fail_then_succeed()
        assert result == "成功"
        assert call_count == succeed_on

    @settings(max_examples=100)
    @given(succeed_on=st.integers(min_value=1, max_value=3))
    def test_async_succeeds_after_transient_failures(self, succeed_on: int):
        """异步函数在第N次尝试成功时应返回结果而不抛出异常

        **Validates: Requirements 15.3**
        """
        call_count = 0

        @retry_on_failure(max_retries=3, base_delay=0.0)
        async def async_fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < succeed_on:
                raise ConnectionError("暂时失败")
            return "成功"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(async_fail_then_succeed())
        finally:
            loop.close()
        assert result == "成功"
        assert call_count == succeed_on

    @settings(max_examples=100)
    @given(
        exception_type=st.sampled_from([
            ValueError, RuntimeError, ConnectionError, TimeoutError, IOError,
        ]),
    )
    def test_original_exception_preserved_after_all_retries(self, exception_type):
        """所有重试失败后应抛出原始异常类型

        **Validates: Requirements 15.4**
        """

        @retry_on_failure(max_retries=3, base_delay=0.0)
        def always_fail():
            raise exception_type("测试异常")

        with pytest.raises(exception_type, match="测试异常"):
            always_fail()

    def test_default_max_retries_is_three(self):
        """默认最大重试次数应为3次

        **Validates: Requirements 15.3**
        """
        call_count = 0

        @retry_on_failure(base_delay=0.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("失败")

        with pytest.raises(RuntimeError):
            always_fail()

        assert call_count == 3

    @settings(max_examples=100)
    @given(return_val=st.integers(min_value=-1000, max_value=1000))
    def test_successful_call_returns_immediately(self, return_val: int):
        """首次调用成功时应直接返回结果，不进行重试

        **Validates: Requirements 15.3**
        """
        call_count = 0

        @retry_on_failure(max_retries=3, base_delay=0.0)
        def succeed_immediately():
            nonlocal call_count
            call_count += 1
            return return_val

        result = succeed_immediately()
        assert result == return_val
        assert call_count == 1
