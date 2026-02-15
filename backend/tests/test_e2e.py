"""
端到端测试模块

使用 PostgreSQL 测试数据库，测试前端到后端的完整流程、
错误场景和边界情况。

优化策略：
- 禁用 startup/shutdown 事件中的调度器，避免后台任务阻塞
- 使用独立的测试数据库，与生产数据库隔离
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models.db_models import (
    AnalysisResultDB,
    CollectionTaskDB,
    OpinionDB,
    RawPostDB,
    SubscriptionDB,
)
from backend.tests.conftest import TEST_ENGINE


@pytest.fixture
def client():
    """创建测试客户端，禁用调度器避免阻塞"""
    def override_get_db():
        Session = sessionmaker(bind=TEST_ENGINE)
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # 禁用所有调度器相关调用，防止后台任务阻塞测试
    with patch("backend.app.scheduler.start_scheduler"), \
         patch("backend.app.scheduler.shutdown_scheduler"), \
         patch("backend.app.scheduler.schedule_subscription"), \
         patch("backend.app.scheduler.unschedule_subscription"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    app.dependency_overrides.clear()


# ===== 辅助函数 =====

def _seed_complete_task(db_session, keyword="端到端测试", sentiment_score=55.0):
    """在数据库中创建一个完整的任务（含帖子、分析结果和观点）"""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    label = "negative" if sentiment_score <= 30 else (
        "neutral" if sentiment_score <= 70 else "positive"
    )

    task = CollectionTaskDB(
        id=task_id, keyword=keyword, language="zh",
        limit_per_source=10, sources=["reddit", "youtube"],
        status="completed", progress=100,
        created_at=now, updated_at=now,
    )
    db_session.add(task)
    db_session.commit()

    # 添加帖子
    for i in range(5):
        db_session.add(RawPostDB(
            id=str(uuid.uuid4()), task_id=task_id, source="reddit",
            title=f"E2E帖子 {i}", content=f"端到端测试内容 {i}",
            author=f"e2e_user_{i}", url=f"https://reddit.com/e2e/{i}",
            timestamp=now, likes=i * 20, comments=i * 10, shares=i * 3,
        ))
    db_session.commit()

    # 添加分析结果
    analysis_id = str(uuid.uuid4())
    db_session.add(AnalysisResultDB(
        id=analysis_id, task_id=task_id,
        sentiment_score=sentiment_score, sentiment_label=label,
        summary="端到端测试摘要内容。" * 10,
        heat_score=35.0, token_usage=300,
    ))
    db_session.commit()

    for i in range(3):
        db_session.add(OpinionDB(
            id=str(uuid.uuid4()), analysis_id=analysis_id,
            description=f"E2E观点 {i}", support_rate=25.0 + i * 10,
            order_index=i,
        ))
    db_session.commit()

    return task_id


# ===== 1. 完整用户流程测试 =====


class TestFullUserFlow:
    """模拟用户从创建任务到查看结果的完整流程"""

    def test_create_task_then_view_all_results(self, client, db_session):
        """测试创建任务后查看分析结果、帖子和思维导图"""
        task_id = _seed_complete_task(db_session)

        # 查询任务状态
        resp = client.get(f"/api/v1/collections/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        # 查看分析结果
        resp = client.get(f"/api/v1/analysis/{task_id}")
        assert resp.status_code == 200
        analysis = resp.json()
        assert 0 <= analysis["sentiment_score"] <= 100
        assert analysis["sentiment_label"] in ["negative", "neutral", "positive"]
        assert len(analysis["opinions"]) == 3
        assert len(analysis["summary"]) > 0
        assert analysis["heat_score"] >= 0

        # 查看帖子列表
        resp = client.get(f"/api/v1/posts/{task_id}?page=1&page_size=10")
        assert resp.status_code == 200
        posts = resp.json()
        assert posts["total"] == 5
        assert len(posts["posts"]) == 5
        for post in posts["posts"]:
            assert post["source"] == "reddit"
            assert post["content"]
            assert "interactions" in post

        # 查看思维导图
        resp = client.get(f"/api/v1/mindmap/{task_id}")
        assert resp.status_code == 200
        assert "mindmap" in resp.json()["mermaid_code"]

    def test_subscription_create_and_manage(self, client):
        """测试订阅的创建、查询和取消完整流程"""
        sub_ids = []
        for kw in ["Python", "Rust", "Go"]:
            resp = client.post("/api/v1/subscriptions", json={
                "keyword": kw, "language": "en",
                "sources": ["reddit", "youtube"],
                "interval_hours": 12, "alert_threshold": 25,
            })
            assert resp.status_code == 200
            sub_ids.append(resp.json()["subscription_id"])

        # 查询所有订阅
        resp = client.get("/api/v1/subscriptions")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        # 取消一个订阅
        resp = client.delete(f"/api/v1/subscriptions/{sub_ids[1]}")
        assert resp.status_code == 200

        # 验证只剩2个活跃订阅
        resp = client.get("/api/v1/subscriptions")
        assert len(resp.json()) == 2

    def test_multiple_tasks_independent(self, client, db_session):
        """测试多个任务之间数据隔离"""
        task_id_1 = _seed_complete_task(db_session, keyword="任务A", sentiment_score=20.0)
        task_id_2 = _seed_complete_task(db_session, keyword="任务B", sentiment_score=80.0)

        resp1 = client.get(f"/api/v1/analysis/{task_id_1}")
        resp2 = client.get(f"/api/v1/analysis/{task_id_2}")
        assert resp1.json()["sentiment_score"] == 20.0
        assert resp1.json()["sentiment_label"] == "negative"
        assert resp2.json()["sentiment_score"] == 80.0
        assert resp2.json()["sentiment_label"] == "positive"

        posts1 = client.get(f"/api/v1/posts/{task_id_1}").json()
        posts2 = client.get(f"/api/v1/posts/{task_id_2}").json()
        assert posts1["total"] == 5
        assert posts2["total"] == 5


# ===== 2. 错误场景和边界情况测试 =====


class TestErrorAndEdgeCases:
    """测试错误场景和边界情况"""

    def test_create_collection_empty_keyword(self, client):
        """测试空关键词被拒绝"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "", "language": "en", "limit": 10,
            "sources": ["reddit"],
        })
        assert resp.status_code == 422

    def test_create_collection_limit_boundary(self, client):
        """测试条数限制的边界值"""
        # 下界有效
        resp = client.post("/api/v1/collections", json={
            "keyword": "边界测试", "language": "en", "limit": 1,
            "sources": ["reddit"],
        })
        assert resp.status_code == 200

        # 上界有效（升级后支持 200000）
        resp = client.post("/api/v1/collections", json={
            "keyword": "边界测试", "language": "en", "limit": 200000,
            "sources": ["reddit"],
        })
        assert resp.status_code == 200

        # 超出上界
        resp = client.post("/api/v1/collections", json={
            "keyword": "边界测试", "language": "en", "limit": 200001,
            "sources": ["reddit"],
        })
        assert resp.status_code == 422

        # 低于下界
        resp = client.post("/api/v1/collections", json={
            "keyword": "边界测试", "language": "en", "limit": 0,
            "sources": ["reddit"],
        })
        assert resp.status_code == 422

    def test_create_collection_invalid_source(self, client):
        """测试无效数据源被拒绝"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "测试", "language": "en", "limit": 10,
            "sources": ["invalid_source"],
        })
        assert resp.status_code == 400
        assert "不支持的数据源" in resp.json()["detail"]

    def test_analysis_before_completion(self, client, db_session):
        """测试任务未完成时查询分析结果返回404"""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        task = CollectionTaskDB(
            id=task_id, keyword="未完成", language="zh",
            limit_per_source=10, sources=["reddit"],
            status="processing", progress=30,
            created_at=now, updated_at=now,
        )
        db_session.add(task)
        db_session.commit()

        resp = client.get(f"/api/v1/analysis/{task_id}")
        assert resp.status_code == 404

    def test_posts_pagination_beyond_range(self, client, db_session):
        """测试分页超出范围返回空列表"""
        task_id = _seed_complete_task(db_session)

        resp = client.get(f"/api/v1/posts/{task_id}?page=100&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["posts"]) == 0

    def test_cancel_nonexistent_subscription(self, client):
        """测试取消不存在的订阅返回404"""
        resp = client.delete(f"/api/v1/subscriptions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_double_cancel_subscription(self, client):
        """测试重复取消订阅返回400"""
        resp = client.post("/api/v1/subscriptions", json={
            "keyword": "重复取消", "language": "en",
            "sources": ["reddit"], "interval_hours": 6,
            "alert_threshold": 30,
        })
        sub_id = resp.json()["subscription_id"]

        # 第一次取消
        resp = client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert resp.status_code == 200

        # 第二次取消
        resp = client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert resp.status_code == 400

    def test_mindmap_without_opinions(self, client, db_session):
        """测试无观点数据时思维导图返回404"""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        db_session.add(CollectionTaskDB(
            id=task_id, keyword="无观点", language="zh",
            limit_per_source=10, sources=["reddit"],
            status="completed", progress=100,
            created_at=now, updated_at=now,
        ))
        db_session.commit()

        db_session.add(AnalysisResultDB(
            id=str(uuid.uuid4()), task_id=task_id,
            sentiment_score=50.0, sentiment_label="neutral",
            summary="无观点测试", heat_score=10.0,
        ))
        db_session.commit()

        resp = client.get(f"/api/v1/mindmap/{task_id}")
        assert resp.status_code == 404

    def test_db_connection_works(self, db_session):
        """验证测试数据库连接正常"""
        from sqlalchemy import text
        result = db_session.execute(text("SELECT 1")).scalar()
        assert result == 1
