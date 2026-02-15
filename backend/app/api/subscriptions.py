"""
订阅管理API端点

提供创建、查询和取消关键词订阅的接口。

需求: 10.1 (创建订阅), 10.5 (取消订阅)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.schemas import CreateSubscriptionRequest, SubscriptionResponse
from backend.app.database import get_db
from backend.app.models.db_models import SubscriptionDB

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(
    request: CreateSubscriptionRequest,
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """创建关键词订阅"""
    # 验证数据源
    valid_sources = {"reddit", "youtube", "twitter"}
    for source in request.sources:
        if source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的数据源: '{source}'",
            )

    now = datetime.now(timezone.utc)
    sub_db = SubscriptionDB(
        id=str(uuid.uuid4()),
        keyword=request.keyword,
        language=request.language,
        sources=request.sources,
        interval_hours=request.interval_hours,
        alert_threshold=request.alert_threshold,
        status="active",
        created_at=now,
    )
    db.add(sub_db)
    db.commit()
    db.refresh(sub_db)

    # 注册定时任务
    from backend.app.scheduler import schedule_subscription
    try:
        schedule_subscription(sub_db.id, request.interval_hours)
    except Exception as e:
        logger.warning("注册定时任务失败: %s, 错误: %s", sub_db.id, e)

    logger.info("订阅已创建: %s, 关键词='%s'", sub_db.id, request.keyword)

    return SubscriptionResponse(
        subscription_id=sub_db.id,
        keyword=sub_db.keyword,
        language=sub_db.language,
        sources=sub_db.sources,
        interval_hours=sub_db.interval_hours,
        alert_threshold=sub_db.alert_threshold,
        status=sub_db.status,
        created_at=sub_db.created_at,
    )


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
async def list_subscriptions(
    db: Session = Depends(get_db),
) -> List[SubscriptionResponse]:
    """获取所有活跃订阅列表"""
    subs = (
        db.query(SubscriptionDB)
        .filter(SubscriptionDB.status == "active")
        .order_by(SubscriptionDB.created_at.desc())
        .all()
    )

    return [
        SubscriptionResponse(
            subscription_id=s.id,
            keyword=s.keyword,
            language=s.language,
            sources=s.sources,
            interval_hours=s.interval_hours,
            alert_threshold=s.alert_threshold,
            status=s.status,
            created_at=s.created_at,
        )
        for s in subs
    ]


@router.delete("/subscriptions/{subscription_id}")
async def cancel_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """取消订阅"""
    sub = (
        db.query(SubscriptionDB)
        .filter(SubscriptionDB.id == subscription_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    if sub.status == "cancelled":
        raise HTTPException(status_code=400, detail="订阅已取消")

    sub.status = "cancelled"
    db.commit()

    # 移除定时任务
    from backend.app.scheduler import unschedule_subscription
    try:
        unschedule_subscription(subscription_id)
    except Exception as e:
        logger.warning("移除定时任务失败: %s, 错误: %s", subscription_id, e)

    logger.info("订阅已取消: %s", subscription_id)

    return {"message": "订阅已取消", "subscription_id": subscription_id}
