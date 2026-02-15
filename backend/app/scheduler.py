"""
定时调度器模块

使用APScheduler实现定时采集和分析任务。
订阅的关键词每隔指定时间（默认6小时）自动执行一次采集和分析。

需求: 10.2 (每6小时自动执行采集和分析)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.database import SessionLocal
from backend.app.models.db_models import SubscriptionDB, CollectionTaskDB

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """获取全局调度器实例，如果不存在则创建"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


async def run_subscription_task(subscription_id: str) -> None:
    """执行单个订阅的采集和分析任务

    Args:
        subscription_id: 订阅ID
    """
    db = SessionLocal()
    try:
        sub = db.query(SubscriptionDB).filter(
            SubscriptionDB.id == subscription_id
        ).first()

        if not sub or sub.status != "active":
            logger.info("订阅 %s 不存在或已取消，跳过执行", subscription_id)
            return

        logger.info("开始执行订阅任务: %s, 关键词='%s'", subscription_id, sub.keyword)

        # 创建采集任务
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        task_db = CollectionTaskDB(
            id=task_id,
            keyword=sub.keyword,
            language=sub.language,
            limit_per_source=50,
            sources=sub.sources,
            status="queued",
            progress=0,
            created_at=now,
            updated_at=now,
        )
        db.add(task_db)
        sub.last_run_at = now
        db.commit()

        # 执行采集和分析流程
        from backend.app.api.collections import run_collection_task
        from backend.app.api.schemas import CreateCollectionRequest

        request = CreateCollectionRequest(
            keyword=sub.keyword,
            language=sub.language,
            limit=50,
            sources=sub.sources,
        )
        await run_collection_task(task_id, request)

        # 检查分析结果，判断是否需要触发报警
        from backend.app.models.db_models import AnalysisResultDB
        analysis = db.query(AnalysisResultDB).filter(
            AnalysisResultDB.task_id == task_id
        ).first()

        if analysis and analysis.sentiment_score < sub.alert_threshold:
            from backend.app.alert_service import AlertService
            alert_service = AlertService(db)
            alert_service.check_and_trigger_alert(
                subscription_id=subscription_id,
                task_id=task_id,
                sentiment_score=analysis.sentiment_score,
                alert_threshold=sub.alert_threshold,
            )

        logger.info("订阅任务完成: %s", subscription_id)

    except Exception as e:
        logger.error("订阅任务执行失败: %s, 错误: %s", subscription_id, e)
    finally:
        db.close()


def schedule_subscription(subscription_id: str, interval_hours: int = 6) -> None:
    """为订阅添加定时任务

    Args:
        subscription_id: 订阅ID
        interval_hours: 执行间隔（小时），默认6小时
    """
    sched = get_scheduler()
    job_id = f"subscription_{subscription_id}"

    # 如果已存在同名任务，先移除
    existing_job = sched.get_job(job_id)
    if existing_job:
        sched.remove_job(job_id)

    sched.add_job(
        run_subscription_task,
        trigger=IntervalTrigger(hours=interval_hours),
        id=job_id,
        args=[subscription_id],
        name=f"订阅任务: {subscription_id}",
        replace_existing=True,
    )
    logger.info("已调度订阅任务: %s, 间隔=%d小时", subscription_id, interval_hours)


def unschedule_subscription(subscription_id: str) -> None:
    """移除订阅的定时任务

    Args:
        subscription_id: 订阅ID
    """
    sched = get_scheduler()
    job_id = f"subscription_{subscription_id}"

    existing_job = sched.get_job(job_id)
    if existing_job:
        sched.remove_job(job_id)
        logger.info("已移除订阅定时任务: %s", subscription_id)
    else:
        logger.warning("未找到订阅定时任务: %s", subscription_id)


def start_scheduler() -> None:
    """启动调度器并恢复所有活跃订阅的定时任务"""
    sched = get_scheduler()
    if sched.running:
        logger.info("调度器已在运行中")
        return

    # 恢复所有活跃订阅
    db = SessionLocal()
    try:
        active_subs = db.query(SubscriptionDB).filter(
            SubscriptionDB.status == "active"
        ).all()

        for sub in active_subs:
            schedule_subscription(sub.id, sub.interval_hours)

        logger.info("已恢复 %d 个活跃订阅的定时任务", len(active_subs))
    finally:
        db.close()

    sched.start()
    logger.info("定时调度器已启动")


def shutdown_scheduler() -> None:
    """关闭调度器"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("定时调度器已关闭")
    scheduler = None
