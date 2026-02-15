"""
报警服务模块

实现舆情报警触发逻辑和通知发送功能。
当分析结果的情感分数低于订阅设定的阈值时，触发报警并生成通知记录。

需求: 10.3 (情感分数低于阈值触发报警), 10.4 (通知用户)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.db_models import AlertDB, SubscriptionDB

logger = logging.getLogger(__name__)


class AlertService:
    """报警服务类

    负责检测舆情报警条件并生成报警通知记录。

    Args:
        db: 数据库会话
    """

    def __init__(self, db: Session):
        """初始化报警服务

        Args:
            db: SQLAlchemy数据库会话
        """
        self.db = db

    def check_and_trigger_alert(
        self,
        subscription_id: str,
        task_id: str,
        sentiment_score: float,
        alert_threshold: int = 30,
    ) -> Optional[AlertDB]:
        """检查是否需要触发报警，如果需要则创建报警记录

        当情感分数低于报警阈值时，创建报警记录并发送通知。

        Args:
            subscription_id: 订阅ID
            task_id: 关联的采集任务ID
            sentiment_score: 情感分数 (0-100)
            alert_threshold: 报警阈值，默认30

        Returns:
            AlertDB: 创建的报警记录，如果未触发则返回None
        """
        if sentiment_score >= alert_threshold:
            logger.debug(
                "情感分数 %.1f >= 阈值 %d，不触发报警 (订阅: %s)",
                sentiment_score, alert_threshold, subscription_id,
            )
            return None

        # 验证订阅是否存在且活跃
        sub = self.db.query(SubscriptionDB).filter(
            SubscriptionDB.id == subscription_id,
            SubscriptionDB.status == "active",
        ).first()

        if not sub:
            logger.warning("订阅 %s 不存在或已取消，跳过报警", subscription_id)
            return None

        # 创建报警记录
        alert = AlertDB(
            id=str(uuid.uuid4()),
            subscription_id=subscription_id,
            task_id=task_id,
            sentiment_score=sentiment_score,
            triggered_at=datetime.now(timezone.utc),
            is_read=False,
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)

        logger.warning(
            "舆情报警已触发: 订阅=%s, 关键词='%s', 情感分数=%.1f, 阈值=%d",
            subscription_id, sub.keyword, sentiment_score, alert_threshold,
        )

        # 发送通知
        self._send_notification(alert, sub)

        return alert

    def _send_notification(self, alert: AlertDB, subscription: SubscriptionDB) -> None:
        """发送报警通知

        当前实现为应用内通知（记录日志）。
        后续可扩展为邮件通知、推送通知等。

        Args:
            alert: 报警记录
            subscription: 关联的订阅
        """
        # 应用内通知：记录到日志
        logger.info(
            "【舆情报警通知】关键词='%s' 的情感分数为 %.1f，低于阈值 %d。"
            "报警ID: %s, 任务ID: %s",
            subscription.keyword,
            alert.sentiment_score,
            subscription.alert_threshold,
            alert.id,
            alert.task_id,
        )

        # 预留邮件通知扩展点
        # TODO: 如需邮件通知，在此处集成SMTP或第三方邮件服务

    def get_unread_alerts(self, subscription_id: Optional[str] = None) -> list:
        """获取未读报警列表

        Args:
            subscription_id: 可选，按订阅ID过滤

        Returns:
            list: 未读报警记录列表
        """
        query = self.db.query(AlertDB).filter(AlertDB.is_read == False)
        if subscription_id:
            query = query.filter(AlertDB.subscription_id == subscription_id)
        return query.order_by(AlertDB.triggered_at.desc()).all()

    def mark_alert_read(self, alert_id: str) -> bool:
        """标记报警为已读

        Args:
            alert_id: 报警ID

        Returns:
            bool: 是否成功标记
        """
        alert = self.db.query(AlertDB).filter(AlertDB.id == alert_id).first()
        if not alert:
            return False
        alert.is_read = True
        self.db.commit()
        return True
