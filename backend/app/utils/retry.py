"""
重试装饰器模块

提供通用的异步/同步重试装饰器，支持指数退避策略。
最多重试3次，每次重试间隔按指数增长。

需求: 15.3 (API调用失败时实施重试机制，最多重试3次)
需求: 15.4 (重试失败后返回错误状态并通知用户)
"""

import asyncio
import functools
import logging
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

# 默认重试参数
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_failure(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> Callable[[F], F]:
    """重试装饰器，支持异步和同步函数

    当被装饰的函数抛出异常时，自动进行重试。
    使用指数退避策略：第 n 次重试的等待时间为 base_delay * 2^(n-1)。

    Args:
        max_retries: 最大重试次数，默认 3 次
        base_delay: 基础延迟秒数，默认 1.0 秒

    Returns:
        装饰后的函数，保留原函数签名

    Raises:
        Exception: 当所有重试均失败后，抛出最后一次的异常
    """

    def decorator(func: F) -> F:
        """内部装饰器，根据函数类型选择异步或同步包装器"""
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            """异步重试包装器，对异步函数执行带指数退避的重试逻辑"""
            last_exception: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            "%s 第 %d/%d 次尝试失败: %s，%.1f 秒后重试",
                            func.__name__,
                            attempt,
                            max_retries,
                            e,
                            wait_time,
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(
                            "%s 所有 %d 次重试均失败: %s",
                            func.__name__,
                            max_retries,
                            e,
                        )
            raise last_exception  # type: ignore[misc]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            """同步重试包装器，对同步函数执行带指数退避的重试逻辑"""
            import time

            last_exception: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            "%s 第 %d/%d 次尝试失败: %s，%.1f 秒后重试",
                            func.__name__,
                            attempt,
                            max_retries,
                            e,
                            wait_time,
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(
                            "%s 所有 %d 次重试均失败: %s",
                            func.__name__,
                            max_retries,
                            e,
                        )
            raise last_exception  # type: ignore[misc]

        # 根据函数类型选择对应的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
