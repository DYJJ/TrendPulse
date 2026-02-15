"""
SQLAlchemy ORM模型定义

定义系统所有数据库表的ORM模型，包括：
- collection_tasks: 采集任务表
- raw_posts: 原始帖子表
- analysis_results: 分析结果表
- opinions: 观点表
- subscriptions: 订阅表
- alerts: 报警记录表
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.app.database import Base


def generate_uuid() -> str:
    """生成UUID字符串"""
    return str(uuid.uuid4())


class CollectionTaskDB(Base):
    """采集任务表"""

    __tablename__ = "collection_tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    keyword = Column(String(255), nullable=False)
    language = Column(String(10), nullable=False)
    limit_per_source = Column(Integer, nullable=False)
    sources = Column(JSON, nullable=False)
    status = Column(String(50), nullable=False, default="queued")
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # 大规模采集新增字段
    collected_count = Column(Integer, default=0)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    subreddits = Column(Text, nullable=True)
    last_cursor = Column(Text, nullable=True)

    # 关系
    posts = relationship("RawPostDB", back_populates="task", cascade="all, delete-orphan")
    analysis = relationship("AnalysisResultDB", back_populates="task", uselist=False,
                            cascade="all, delete-orphan")


class RawPostDB(Base):
    """原始帖子表"""

    __tablename__ = "raw_posts"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_raw_posts_source_external_id"),
        Index("idx_raw_posts_task_id", "task_id"),
        Index("idx_raw_posts_source", "source"),
        Index("idx_raw_posts_timestamp", "timestamp"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey("collection_tasks.id"), nullable=False)
    source = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=True)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    author = Column(String(255), nullable=True)
    url = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=True)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    is_spam = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 关系
    task = relationship("CollectionTaskDB", back_populates="posts")


class AnalysisResultDB(Base):
    """分析结果表"""

    __tablename__ = "analysis_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey("collection_tasks.id"), nullable=False, unique=True)
    sentiment_score = Column(Float, nullable=False)
    sentiment_label = Column(String(50), nullable=False)
    summary = Column(Text, nullable=False)
    heat_score = Column(Float, nullable=False)
    token_usage = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 关系
    task = relationship("CollectionTaskDB", back_populates="analysis")
    opinions = relationship("OpinionDB", back_populates="analysis", cascade="all, delete-orphan")


class OpinionDB(Base):
    """观点表"""

    __tablename__ = "opinions"

    id = Column(String, primary_key=True, default=generate_uuid)
    analysis_id = Column(String, ForeignKey("analysis_results.id"), nullable=False)
    description = Column(Text, nullable=False)
    support_rate = Column(Float, nullable=False)
    order_index = Column(Integer, nullable=False)

    # 关系
    analysis = relationship("AnalysisResultDB", back_populates="opinions")


class SubscriptionDB(Base):
    """订阅表"""

    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    keyword = Column(String(255), nullable=False)
    language = Column(String(10), nullable=False)
    sources = Column(JSON, nullable=False)
    interval_hours = Column(Integer, nullable=False, default=6)
    limit_per_source = Column(Integer, nullable=False, default=50)
    alert_threshold = Column(Integer, nullable=False, default=30)
    status = Column(String(50), nullable=False, default="active")
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 关系
    alerts = relationship("AlertDB", back_populates="subscription", cascade="all, delete-orphan")


class AlertDB(Base):
    """报警记录表"""

    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=generate_uuid)
    subscription_id = Column(String, ForeignKey("subscriptions.id"), nullable=False)
    task_id = Column(String, ForeignKey("collection_tasks.id"), nullable=False)
    sentiment_score = Column(Float, nullable=False)
    triggered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_read = Column(Boolean, default=False)

    # 关系
    subscription = relationship("SubscriptionDB", back_populates="alerts")
