"""
集成测试模块

测试完整的采集→清洗→分析→存储流程、API端点与数据库交互、
以及定时任务和报警流程。

使用 PostgreSQL 测试数据库进行测试。
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models.db_models import (
    AnalysisResultDB,
    AlertDB,
    CollectionTaskDB,
    OpinionDB,
    RawPostDB,
    SubscriptionDB,
)
from backend.app.models.data_models import (
    DataSource,
    RawPost,
    SentimentLabel,
)
from backend.app.processing.data_cleaner import DataCleaner
from backend.app.analysis.ai_analyzer import AIAnalyzer
from backend.app.analysis.sentiment_analyzer import SentimentAnalyzer
from backend.app.alert_service import AlertService
from backend.app.analysis.mermaid_generator import MermaidGenerator
from backend.tests.conftest import TEST_ENGINE


@pytest.fixture
def client():
    """创建测试客户端，覆盖数据库依赖"""
    def override_get_db():
        Session = sessionmaker(bind=TEST_ENGINE)
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ===== 辅助函数 =====

def _create_task(db_session, task_id=None, keyword="集成测试", status="completed"):
    """创建采集任务记录"""
    tid = task_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task = CollectionTaskDB(
        id=tid,
        keyword=keyword,
        language="zh",
        limit_per_source=10,
        sources=["reddit"],
        status=status,
        progress=100 if status == "completed" else 0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return tid


def _create_posts(db_session, task_id, count=3):
    """创建帖子记录"""
    posts = []
    for i in range(count):
        post = RawPostDB(
            id=str(uuid.uuid4()),
            task_id=task_id,
            source="reddit",
            title=f"测试帖子标题 {i}",
            content=f"这是测试帖子内容 {i}，用于集成测试。",
            author=f"测试作者{i}",
            url=f"https://reddit.com/test/{i}",
            timestamp=datetime.now(timezone.utc),
            likes=i * 10,
            comments=i * 5,
            shares=i * 2,
            is_spam=False,
        )
        db_session.add(post)
        posts.append(post)
    db_session.commit()
    return posts


def _create_analysis(db_session, task_id, sentiment_score=65.0):
    """创建分析结果和观点记录"""
    analysis_id = str(uuid.uuid4())
    label = "negative" if sentiment_score <= 30 else ("neutral" if sentiment_score <= 70 else "positive")
    analysis = AnalysisResultDB(
        id=analysis_id,
        task_id=task_id,
        sentiment_score=sentiment_score,
        sentiment_label=label,
        summary="这是集成测试的摘要文本，用于验证完整流程。" * 5,
        heat_score=42.0,
        token_usage=500,
    )
    db_session.add(analysis)
    db_session.commit()

    for i in range(3):
        opinion = OpinionDB(
            id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            description=f"集成测试观点 {i}",
            support_rate=30.0 + i * 5,
            order_index=i,
        )
        db_session.add(opinion)
    db_session.commit()
    return analysis_id


def _create_subscription(db_session, keyword="集成测试", alert_threshold=30):
    """创建订阅记录"""
    sub_id = str(uuid.uuid4())
    sub = SubscriptionDB(
        id=sub_id,
        keyword=keyword,
        language="zh",
        sources=["reddit"],
        interval_hours=6,
        alert_threshold=alert_threshold,
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    db_session.commit()
    return sub_id


# ===== 1. 采集→清洗→分析→存储 完整流程测试 =====


class TestDataPipelineIntegration:
    """测试数据采集→清洗→分析→存储的完整流程"""

    def test_data_cleaning_and_storage(self, db_session):
        """测试数据清洗后存储到数据库的完整流程"""
        task_id = _create_task(db_session)
        cleaner = DataCleaner()

        # 模拟原始数据（含HTML标签和垃圾内容）
        raw_texts = [
            "<p>这是一条正常的讨论帖子</p>",
            "Buy now! Click here for free gift!",  # 垃圾内容
            "正常的技术讨论内容，关于Python编程",
        ]

        stored_count = 0
        spam_count = 0
        for i, text in enumerate(raw_texts):
            cleaned = cleaner.clean_text(text)
            is_spam = cleaner.filter_spam(cleaned)
            if is_spam:
                spam_count += 1

            post = RawPostDB(
                id=str(uuid.uuid4()),
                task_id=task_id,
                source="reddit",
                title=f"帖子 {i}",
                content=cleaned,
                author=f"作者{i}",
                url=f"https://reddit.com/{i}",
                timestamp=datetime.now(timezone.utc),
                likes=10,
                comments=5,
                shares=2,
                is_spam=is_spam,
            )
            db_session.add(post)
            stored_count += 1

        db_session.commit()

        # 验证存储结果
        posts = db_session.query(RawPostDB).filter(RawPostDB.task_id == task_id).all()
        assert len(posts) == stored_count
        assert spam_count >= 1  # 至少检测到一条垃圾内容

        # 验证清洗后的内容不含HTML标签
        for post in posts:
            assert "<p>" not in post.content
            assert "</p>" not in post.content

    def test_analysis_result_persistence(self, db_session):
        """测试AI分析结果持久化到数据库"""
        task_id = _create_task(db_session)
        analysis_id = _create_analysis(db_session, task_id, sentiment_score=75.0)

        # 从数据库查询分析结果
        analysis = db_session.query(AnalysisResultDB).filter(
            AnalysisResultDB.task_id == task_id
        ).first()

        assert analysis is not None
        assert analysis.sentiment_score == 75.0
        assert analysis.sentiment_label == "positive"
        assert len(analysis.opinions) == 3

        # 验证观点排序
        sorted_opinions = sorted(analysis.opinions, key=lambda o: o.order_index)
        for i, op in enumerate(sorted_opinions):
            assert op.order_index == i
            assert op.support_rate > 0

    def test_cleaning_idempotency_in_pipeline(self, db_session):
        """测试清洗操作在流水线中的幂等性"""
        cleaner = DataCleaner()
        raw_text = "<b>Hello</b>  World  &amp; 你好"

        # 第一次清洗
        cleaned_once = cleaner.clean_text(raw_text)
        # 第二次清洗
        cleaned_twice = cleaner.clean_text(cleaned_once)

        assert cleaned_once == cleaned_twice

    def test_sentiment_classification_consistency(self, db_session):
        """测试情感分数分类在存储后的一致性"""
        # 每个分数范围使用独立的task（analysis_results.task_id有唯一约束）
        test_cases = [
            (15.0, "negative"),
            (50.0, "neutral"),
            (85.0, "positive"),
        ]

        task_ids = []
        for score, expected_label in test_cases:
            tid = _create_task(db_session, keyword=f"分类测试_{score}")
            task_ids.append(tid)
            analysis = AnalysisResultDB(
                id=str(uuid.uuid4()),
                task_id=tid,
                sentiment_score=score,
                sentiment_label=expected_label,
                summary="测试摘要",
                heat_score=10.0,
            )
            db_session.add(analysis)
            db_session.commit()

        # 查询并验证
        for tid in task_ids:
            r = db_session.query(AnalysisResultDB).filter(
                AnalysisResultDB.task_id == tid
            ).first()
            assert r is not None
            if r.sentiment_score <= 30:
                assert r.sentiment_label == "negative"
            elif r.sentiment_score <= 70:
                assert r.sentiment_label == "neutral"
            else:
                assert r.sentiment_label == "positive"


# ===== 2. API端点与数据库交互测试 =====


class TestAPIDBIntegration:
    """测试API端点与数据库的交互"""

    def test_create_collection_and_query_status(self, client):
        """测试创建采集任务后查询状态"""
        # 创建任务
        resp = client.post("/api/v1/collections", json={
            "keyword": "集成测试",
            "language": "zh",
            "limit": 10,
            "sources": ["reddit"],
        })
        assert resp.status_code == 200
        data = resp.json()
        task_id = data["task_id"]
        assert data["status"] == "queued"

        # 查询状态
        resp2 = client.get(f"/api/v1/collections/{task_id}")
        assert resp2.status_code == 200
        status_data = resp2.json()
        assert status_data["task_id"] == task_id
        assert status_data["status"] in ["queued", "processing", "completed", "failed"]

    def test_analysis_endpoint_with_db_data(self, client, db_session):
        """测试分析结果API端点读取数据库数据"""
        task_id = _create_task(db_session)
        _create_analysis(db_session, task_id, sentiment_score=45.0)

        resp = client.get(f"/api/v1/analysis/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sentiment_score"] == 45.0
        assert data["sentiment_label"] == "neutral"
        assert len(data["opinions"]) == 3
        assert data["heat_score"] == 42.0

    def test_posts_endpoint_pagination_with_db(self, client, db_session):
        """测试帖子列表分页与数据库交互"""
        task_id = _create_task(db_session)
        _create_posts(db_session, task_id, count=5)

        # 第一页
        resp = client.get(f"/api/v1/posts/{task_id}?page=1&page_size=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["posts"]) == 2
        assert data["page"] == 1

        # 第二页
        resp2 = client.get(f"/api/v1/posts/{task_id}?page=2&page_size=2")
        data2 = resp2.json()
        assert len(data2["posts"]) == 2

        # 最后一页
        resp3 = client.get(f"/api/v1/posts/{task_id}?page=3&page_size=2")
        data3 = resp3.json()
        assert len(data3["posts"]) == 1

    def test_subscription_lifecycle(self, client):
        """测试订阅的完整生命周期：创建→查询→取消"""
        # 创建订阅
        resp = client.post("/api/v1/subscriptions", json={
            "keyword": "生命周期测试",
            "language": "en",
            "sources": ["reddit"],
            "interval_hours": 6,
            "alert_threshold": 30,
        })
        assert resp.status_code == 200
        sub_id = resp.json()["subscription_id"]

        # 查询订阅列表
        resp2 = client.get("/api/v1/subscriptions")
        assert resp2.status_code == 200
        subs = resp2.json()
        assert any(s["subscription_id"] == sub_id for s in subs)

        # 取消订阅
        resp3 = client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert resp3.status_code == 200

        # 确认已取消（不在活跃列表中）
        resp4 = client.get("/api/v1/subscriptions")
        subs_after = resp4.json()
        assert not any(s["subscription_id"] == sub_id for s in subs_after)

    def test_mindmap_endpoint_with_analysis(self, client, db_session):
        """测试思维导图端点与分析数据的交互"""
        task_id = _create_task(db_session, keyword="思维导图测试")
        _create_analysis(db_session, task_id)

        resp = client.get(f"/api/v1/mindmap/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        mermaid_code = data["mermaid_code"]

        # 验证Mermaid代码结构
        assert "mindmap" in mermaid_code
        assert "root" in mermaid_code
        assert "思维导图测试" in mermaid_code

    def test_nonexistent_task_returns_404(self, client):
        """测试访问不存在的任务返回404"""
        fake_id = str(uuid.uuid4())
        assert client.get(f"/api/v1/collections/{fake_id}").status_code == 404
        assert client.get(f"/api/v1/analysis/{fake_id}").status_code == 404
        assert client.get(f"/api/v1/posts/{fake_id}").status_code == 404
        assert client.get(f"/api/v1/mindmap/{fake_id}").status_code == 404


# ===== 3. 定时任务和报警流程测试 =====


class TestSchedulerAlertIntegration:
    """测试定时任务和报警的集成流程"""

    def test_alert_triggered_on_low_sentiment(self, db_session):
        """测试低情感分数触发报警"""
        task_id = _create_task(db_session)
        sub_id = _create_subscription(db_session, alert_threshold=30)

        alert_service = AlertService(db_session)
        alert = alert_service.check_and_trigger_alert(
            subscription_id=sub_id,
            task_id=task_id,
            sentiment_score=20.0,
            alert_threshold=30,
        )

        assert alert is not None
        assert alert.sentiment_score == 20.0
        assert alert.subscription_id == sub_id
        assert alert.task_id == task_id
        assert alert.is_read is False

        # 验证报警记录已持久化
        db_alert = db_session.query(AlertDB).filter(AlertDB.id == alert.id).first()
        assert db_alert is not None

    def test_no_alert_on_high_sentiment(self, db_session):
        """测试高情感分数不触发报警"""
        task_id = _create_task(db_session)
        sub_id = _create_subscription(db_session, alert_threshold=30)

        alert_service = AlertService(db_session)
        alert = alert_service.check_and_trigger_alert(
            subscription_id=sub_id,
            task_id=task_id,
            sentiment_score=65.0,
            alert_threshold=30,
        )

        assert alert is None
        alerts = db_session.query(AlertDB).all()
        assert len(alerts) == 0

    def test_alert_not_triggered_for_cancelled_subscription(self, db_session):
        """测试已取消的订阅不触发报警"""
        task_id = _create_task(db_session)
        sub_id = _create_subscription(db_session, alert_threshold=30)

        # 取消订阅
        sub = db_session.query(SubscriptionDB).filter(SubscriptionDB.id == sub_id).first()
        sub.status = "cancelled"
        db_session.commit()

        alert_service = AlertService(db_session)
        alert = alert_service.check_and_trigger_alert(
            subscription_id=sub_id,
            task_id=task_id,
            sentiment_score=10.0,
            alert_threshold=30,
        )

        assert alert is None

    def test_subscription_cancel_updates_status(self, db_session):
        """测试取消订阅后状态正确更新"""
        sub_id = _create_subscription(db_session)

        sub = db_session.query(SubscriptionDB).filter(SubscriptionDB.id == sub_id).first()
        assert sub.status == "active"

        sub.status = "cancelled"
        db_session.commit()

        sub_refreshed = db_session.query(SubscriptionDB).filter(
            SubscriptionDB.id == sub_id
        ).first()
        assert sub_refreshed.status == "cancelled"

    def test_multiple_alerts_for_same_subscription(self, db_session):
        """测试同一订阅可以触发多次报警"""
        sub_id = _create_subscription(db_session, alert_threshold=30)
        alert_service = AlertService(db_session)

        for i in range(3):
            task_id = _create_task(db_session, keyword=f"报警测试{i}")
            alert_service.check_and_trigger_alert(
                subscription_id=sub_id,
                task_id=task_id,
                sentiment_score=10.0 + i * 5,
                alert_threshold=30,
            )

        alerts = db_session.query(AlertDB).filter(
            AlertDB.subscription_id == sub_id
        ).all()
        assert len(alerts) == 3

    def test_unread_alerts_query(self, db_session):
        """测试未读报警查询"""
        task_id = _create_task(db_session)
        sub_id = _create_subscription(db_session, alert_threshold=30)

        alert_service = AlertService(db_session)
        alert = alert_service.check_and_trigger_alert(
            subscription_id=sub_id,
            task_id=task_id,
            sentiment_score=15.0,
            alert_threshold=30,
        )

        # 查询未读报警
        unread = alert_service.get_unread_alerts(sub_id)
        assert len(unread) == 1

        # 标记已读
        alert_service.mark_alert_read(alert.id)
        unread_after = alert_service.get_unread_alerts(sub_id)
        assert len(unread_after) == 0
