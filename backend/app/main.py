"""
FastAPI应用入口模块

初始化FastAPI应用，配置CORS中间件、全局异常处理器和日志中间件。

需求: 15.1 (异常捕获和日志记录), 15.2 (日志格式)
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from backend.app.api.routes import router as api_router
from backend.app.config import ConfigurationError, get_config
from backend.app.database import Base, engine
from backend.app.logging_config import setup_logging

# 使用统一日志配置（含日志轮转）
setup_logging()
logger = logging.getLogger(__name__)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 自动迁移：为已有的 subscriptions 表添加 limit_per_source 列
try:
    with engine.connect() as conn:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("subscriptions")]
        if "limit_per_source" not in columns:
            conn.execute(text(
                "ALTER TABLE subscriptions ADD COLUMN limit_per_source INTEGER NOT NULL DEFAULT 50"
            ))
            conn.commit()
            logging.getLogger(__name__).info("已为 subscriptions 表添加 limit_per_source 列")
except Exception:
    pass  # 表不存在时忽略

app = FastAPI(
    title="TrendPulse 舆情脉冲",
    description="多源社交媒体舆情分析系统API",
    version="1.0.0",
)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """日志中间件：记录每个请求的方法、路径和耗时

    对高频轮询接口（如采集状态查询）降低日志级别，避免刷屏。
    """
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    path = request.url.path
    method = request.method

    # 高频轮询路径：采集状态查询、OPTIONS 预检请求，降为 DEBUG 级别
    is_polling = (
        method == "OPTIONS"
        or (method == "GET" and "/collections/" in path and path.count("/") >= 4)
    )

    if not is_polling:
        logger.info("[%s] %s %s 开始处理", request_id, method, path)

    response = await call_next(request)

    duration = time.time() - start_time

    if is_polling:
        logger.debug(
            "[%s] %s %s 完成 状态=%d 耗时=%.3fs",
            request_id, method, path, response.status_code, duration,
        )
    else:
        logger.info(
            "[%s] %s %s 完成 状态=%d 耗时=%.3fs",
            request_id, method, path, response.status_code, duration,
        )

    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局异常处理器：捕获未处理的异常并返回统一错误响应"""
    logger.error(
        "未处理异常: %s, 路径: %s, 方法: %s, 时间: %s",
        exc,
        request.url.path,
        request.method,
        datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )


# 注册API路由
app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event() -> None:
    """应用启动时验证配置并初始化定时调度器"""
    # 验证配置
    try:
        config = get_config()
        config.validate()
        logger.info("配置加载成功")
    except ConfigurationError as e:
        logger.critical("配置验证失败: %s", e)
        raise

    # 初始化定时调度器
    from backend.app.scheduler import start_scheduler
    try:
        start_scheduler()
        logger.info("定时调度器已在应用启动时初始化")
    except Exception as e:
        logger.error("定时调度器启动失败: %s", e)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """应用关闭时停止定时调度器"""
    from backend.app.scheduler import shutdown_scheduler
    shutdown_scheduler()
    logger.info("定时调度器已在应用关闭时停止")
