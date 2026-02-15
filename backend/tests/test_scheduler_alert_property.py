"""
定时任务和报警属性测试

属性 15: 订阅持久化
属性 16: 舆情报警触发条件
属性 17: 报警通知发送
属性 18: 订阅取消清理

验证需求: 10.1, 10.3, 10.4, 10.5
"""

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.db_models import (
    SubscriptionDB,
    AlertDB,
    CollectionTaskDB,
)
from backend.app.alert_service import AlertService


# --- 策略定义 ---

keyword_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda t: t.strip())

language_strategy = st.sampled_from(["en", "zh"])

sources_strategy = st.lists(
    st.sampled_from(["reddit", "youtube", "twitter"]),
    min_size=1,
    max_size=3,
    unique=True,
)

interval_hours_strategy = st.integers(min_value=1, max_value=168)

alert_threshold_strategy = st.integers(min_value=0, max_value=100)

sentiment_score_strategy = st.floats(
    min_value=0, max_value=100, allow_nan=False, allow_infinity=False,
)


def _make_session():
    """创建测试数据库会话，并清理残留数据"""
    from backend.tests.conftest import TEST_ENGINE
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = sessionmaker(bind=TEST_ENGINE)()
    # 清理残留数据，避免 Hypothesis 多次迭代间的干扰
    session.query(AlertDB).delete()
    session.query(SubscriptionDB).delete()
    session.query(CollectionTaskDB).delete()
    session.commit()
    return session


def _create_subscription(session, keyword, language, sources, interval_hours, alert_threshold):
    """辅助函数：创建订阅记录"""
    sub = SubscriptionDB(
        id=str(uuid.uuid4()),
        keyword=keyword,
        language=language,
        sources=sources,
        interval_hours=interval_hours,
        alert_threshold=alert_threshold,
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    session.add(sub)
    session.flush()
    return sub


def _create_collection_task(session, keyword, language, sources):
    """辅助函数：创建采集任务记录"""
    task = CollectionTaskDB(
        id=str(uuid.uuid4()),
        keyword=keyword,
        language=language,
        limit_per_source=50,
        sources=sources,
        status="completed",
        progress=100,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(task)
    session.flush()
    return task


# Feature: trendpulse-sentiment-analysis, Property 15: 订阅持久化
# 验证需求: 10.1

@given(
    keyword=keyword_strategy,
    language=language_strategy,
    sources=sources_strategy,
    interval_hours=interval_hours_strategy,
    alert_threshold=alert_threshold_strategy,
)
@settings(max_examples=100)
def test_subscription_persistence(
    keyword, language, sources, interval_hours, alert_threshold,
):
    """
    属性15: 对于任意有效的订阅配置，创建订阅后，从数据库查询该订阅
    应该返回包含所有配置参数的记录。

    **Validates: Requirements 10.1**
    """
    session = _make_session()
    try:
        sub = _create_subscription(
            session, keyword, language, sources, interval_hours, alert_threshold,
        )
        session.commit()

        # 查询并验证所有字段
        queried = session.query(SubscriptionDB).filter_by(id=sub.id).first()
        assert queried is not None
        assert queried.keyword == keyword
        assert queried.language == language
        assert queried.sources == sources
        assert queried.interval_hours == interval_hours
        assert queried.alert_threshold == alert_threshold
        assert queried.status == "active"
        assert queried.created_at is not None
    finally:
        session.close()


# Feature: trendpulse-sentiment-analysis, Property 16: 舆情报警触发条件
# 验证需求: 10.3

@given(
    keyword=keyword_strategy,
    language=language_strategy,
    sources=sources_strategy,
    alert_threshold=alert_threshold_strategy,
    sentiment_score=sentiment_score_strategy,
)
@settings(max_examples=100)
def test_alert_trigger_condition(
    keyword, language, sources, alert_threshold, sentiment_score,
):
    """
    属性16: 对于任意分析结果，当情感分数低于阈值时，报警服务应该触发报警；
    当情感分数大于等于阈值时，不应触发报警。

    **Validates: Requirements 10.3**
    """
    session = _make_session()
    try:
        sub = _create_subscription(
            session, keyword, language, sources, 6, alert_threshold,
        )
        task = _create_collection_task(session, keyword, language, sources)
        session.commit()

        alert_service = AlertService(session)
        result = alert_service.check_and_trigger_alert(
            subscription_id=sub.id,
            task_id=task.id,
            sentiment_score=sentiment_score,
            alert_threshold=alert_threshold,
        )

        if sentiment_score < alert_threshold:
            # 应该触发报警
            assert result is not None
            assert isinstance(result, AlertDB)
        else:
            # 不应触发报警
            assert result is None
    finally:
        session.close()


# Feature: trendpulse-sentiment-analysis, Property 17: 报警通知发送
# 验证需求: 10.4

@given(
    keyword=keyword_strategy,
    language=language_strategy,
    sources=sources_strategy,
    sentiment_score=st.floats(
        min_value=0, max_value=29.99, allow_nan=False, allow_infinity=False,
    ),
)
@settings(max_examples=100)
def test_alert_notification_record(
    keyword, language, sources, sentiment_score,
):
    """
    属性17: 对于任意触发的报警，系统应该生成通知记录，并且该记录应该
    包含订阅ID、任务ID、情感分数和触发时间。

    **Validates: Requirements 10.4**
    """
    session = _make_session()
    try:
        sub = _create_subscription(
            session, keyword, language, sources, 6, 30,
        )
        task = _create_collection_task(session, keyword, language, sources)
        session.commit()

        alert_service = AlertService(session)
        alert = alert_service.check_and_trigger_alert(
            subscription_id=sub.id,
            task_id=task.id,
            sentiment_score=sentiment_score,
            alert_threshold=30,
        )

        # 验证报警记录包含所有必需字段
        assert alert is not None
        assert alert.subscription_id == sub.id
        assert alert.task_id == task.id
        assert alert.sentiment_score == sentiment_score
        assert alert.triggered_at is not None
        assert alert.is_read is False

        # 验证数据库中也能查到
        queried = session.query(AlertDB).filter_by(id=alert.id).first()
        assert queried is not None
        assert queried.subscription_id == sub.id
        assert queried.task_id == task.id
        assert queried.sentiment_score == sentiment_score
        assert queried.triggered_at is not None
    finally:
        session.close()


# Feature: trendpulse-sentiment-analysis, Property 18: 订阅取消清理
# 验证需求: 10.5

@given(
    keyword=keyword_strategy,
    language=language_strategy,
    sources=sources_strategy,
    interval_hours=interval_hours_strategy,
    alert_threshold=alert_threshold_strategy,
)
@settings(max_examples=100)
def test_subscription_cancellation_cleanup(
    keyword, language, sources, interval_hours, alert_threshold,
):
    """
    属性18: 对于任意活跃订阅，取消订阅后，该订阅的状态应该更新为非活跃，
    并且不应再触发定时任务。

    **Validates: Requirements 10.5**
    """
    session = _make_session()
    try:
        sub = _create_subscription(
            session, keyword, language, sources, interval_hours, alert_threshold,
        )
        session.commit()

        # 确认初始状态为活跃
        assert sub.status == "active"

        # 取消订阅
        sub.status = "cancelled"
        session.commit()

        # 验证状态已更新
        queried = session.query(SubscriptionDB).filter_by(id=sub.id).first()
        assert queried is not None
        assert queried.status == "cancelled"

        # 验证报警服务不会为已取消的订阅触发报警
        task = _create_collection_task(session, keyword, language, sources)
        session.commit()

        alert_service = AlertService(session)
        result = alert_service.check_and_trigger_alert(
            subscription_id=sub.id,
            task_id=task.id,
            sentiment_score=0.0,  # 极低分数，正常情况下应触发报警
            alert_threshold=alert_threshold if alert_threshold > 0 else 30,
        )

        # 已取消的订阅不应触发报警
        assert result is None
    finally:
        session.close()
