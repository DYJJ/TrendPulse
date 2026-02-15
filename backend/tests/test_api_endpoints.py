"""
API端点单元测试

测试各端点的正常流程、错误处理和分页功能。
"""

import uuid
from datetime import datetime, timezone

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


def _create_task(db_session, task_id=None, keyword="测试", status="completed"):
    """在数据库中创建一个采集任务"""
    tid = task_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task = CollectionTaskDB(
        id=tid,
        keyword=keyword,
        language="zh",
        limit_per_source=50,
        sources=["reddit"],
        status=status,
        progress=100 if status == "completed" else 0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return tid


def _create_posts(db_session, task_id, count=5):
    """在数据库中创建指定数量的帖子"""
    for i in range(count):
        post = RawPostDB(
            id=str(uuid.uuid4()),
            task_id=task_id,
            source="reddit",
            title=f"帖子标题 {i}",
            content=f"帖子内容 {i}",
            author=f"作者{i}",
            url=f"https://reddit.com/post/{i}",
            timestamp=datetime.now(timezone.utc),
            likes=i * 10,
            comments=i * 5,
            shares=i * 2,
            is_spam=False,
        )
        db_session.add(post)
    db_session.commit()


def _create_analysis(db_session, task_id):
    """在数据库中创建分析结果和观点"""
    analysis_id = str(uuid.uuid4())
    analysis = AnalysisResultDB(
        id=analysis_id,
        task_id=task_id,
        sentiment_score=65.0,
        sentiment_label="neutral",
        summary="这是一段测试摘要文本。",
        heat_score=42.0,
        token_usage=500,
    )
    db_session.add(analysis)
    db_session.commit()

    for i in range(3):
        opinion = OpinionDB(
            id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            description=f"观点描述 {i}",
            support_rate=30.0 + i * 5,
            order_index=i,
        )
        db_session.add(opinion)
    db_session.commit()
    return analysis_id


# ===== 采集任务端点测试 =====


class TestCollectionsEndpoint:
    """采集任务API端点测试"""

    def test_create_collection_success(self, client):
        """正常创建采集任务"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "AI技术",
            "language": "zh",
            "limit": 50,
            "sources": ["reddit"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "task_id" in data
        assert "created_at" in data

    def test_create_collection_invalid_keyword(self, client):
        """空关键词应返回422（Pydantic min_length校验）"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "",
            "language": "en",
            "limit": 10,
            "sources": ["reddit"],
        })
        assert resp.status_code == 422

    def test_create_collection_invalid_source(self, client):
        """不支持的数据源应返回400"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "test",
            "language": "en",
            "limit": 10,
            "sources": ["invalid_source"],
        })
        assert resp.status_code == 400
        assert "不支持的数据源" in resp.json()["detail"]

    def test_create_collection_invalid_language(self, client):
        """不支持的语言应返回400"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "test",
            "language": "fr",
            "limit": 10,
            "sources": ["reddit"],
        })
        assert resp.status_code == 400

    def test_create_collection_limit_out_of_range(self, client):
        """条数限制超出范围应返回422"""
        resp = client.post("/api/v1/collections", json={
            "keyword": "test",
            "language": "en",
            "limit": 200001,
            "sources": ["reddit"],
        })
        assert resp.status_code == 422

    def test_get_collection_status_success(self, client, db_session):
        """查询已存在任务的状态"""
        task_id = _create_task(db_session, status="processing")
        resp = client.get(f"/api/v1/collections/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["status"] == "processing"

    def test_get_collection_status_not_found(self, client):
        """查询不存在的任务应返回404"""
        resp = client.get(f"/api/v1/collections/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "任务不存在" in resp.json()["detail"]


# ===== 分析结果端点测试 =====


class TestAnalysisEndpoint:
    """分析结果API端点测试"""

    def test_get_analysis_success(self, client, db_session):
        """正常获取分析结果"""
        task_id = _create_task(db_session)
        _create_analysis(db_session, task_id)

        resp = client.get(f"/api/v1/analysis/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sentiment_score"] == 65.0
        assert data["sentiment_label"] == "neutral"
        assert len(data["opinions"]) == 3
        assert data["heat_score"] == 42.0
        assert len(data["summary"]) > 0

    def test_get_analysis_task_not_found(self, client):
        """任务不存在应返回404"""
        resp = client.get(f"/api/v1/analysis/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "任务不存在" in resp.json()["detail"]

    def test_get_analysis_no_result(self, client, db_session):
        """任务存在但无分析结果应返回404"""
        task_id = _create_task(db_session)
        resp = client.get(f"/api/v1/analysis/{task_id}")
        assert resp.status_code == 404
        assert "分析结果尚未生成" in resp.json()["detail"]

    def test_get_analysis_opinions_ordered(self, client, db_session):
        """观点应按order_index排序"""
        task_id = _create_task(db_session)
        _create_analysis(db_session, task_id)

        resp = client.get(f"/api/v1/analysis/{task_id}")
        opinions = resp.json()["opinions"]
        for i in range(len(opinions) - 1):
            assert opinions[i]["support_rate"] <= opinions[i + 1]["support_rate"]


# ===== 帖子列表端点测试 =====


class TestPostsEndpoint:
    """帖子列表API端点测试"""

    def test_get_posts_success(self, client, db_session):
        """正常获取帖子列表"""
        task_id = _create_task(db_session)
        _create_posts(db_session, task_id, count=3)

        resp = client.get(f"/api/v1/posts/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["posts"]) == 3
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_get_posts_pagination(self, client, db_session):
        """分页功能测试"""
        task_id = _create_task(db_session)
        _create_posts(db_session, task_id, count=12)

        # 第一页，每页5条
        resp = client.get(f"/api/v1/posts/{task_id}?page=1&page_size=5")
        data = resp.json()
        assert data["total"] == 12
        assert len(data["posts"]) == 5
        assert data["page"] == 1

        # 第二页
        resp = client.get(f"/api/v1/posts/{task_id}?page=2&page_size=5")
        data = resp.json()
        assert len(data["posts"]) == 5

        # 第三页（剩余2条）
        resp = client.get(f"/api/v1/posts/{task_id}?page=3&page_size=5")
        data = resp.json()
        assert len(data["posts"]) == 2

    def test_get_posts_empty(self, client, db_session):
        """任务无帖子时返回空列表"""
        task_id = _create_task(db_session)
        resp = client.get(f"/api/v1/posts/{task_id}")
        data = resp.json()
        assert data["total"] == 0
        assert data["posts"] == []

    def test_get_posts_task_not_found(self, client):
        """任务不存在应返回404"""
        resp = client.get(f"/api/v1/posts/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_posts_invalid_page(self, client, db_session):
        """无效页码应返回422"""
        task_id = _create_task(db_session)
        resp = client.get(f"/api/v1/posts/{task_id}?page=0")
        assert resp.status_code == 422

    def test_get_posts_interactions(self, client, db_session):
        """帖子应包含互动数据"""
        task_id = _create_task(db_session)
        _create_posts(db_session, task_id, count=1)

        resp = client.get(f"/api/v1/posts/{task_id}")
        post = resp.json()["posts"][0]
        assert "interactions" in post
        assert "likes" in post["interactions"]
        assert "comments" in post["interactions"]
        assert "shares" in post["interactions"]


# ===== 订阅管理端点测试 =====


class TestSubscriptionsEndpoint:
    """订阅管理API端点测试"""

    def test_create_subscription_success(self, client):
        """正常创建订阅"""
        resp = client.post("/api/v1/subscriptions", json={
            "keyword": "AI",
            "language": "en",
            "sources": ["reddit", "youtube"],
            "interval_hours": 6,
            "alert_threshold": 30,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["keyword"] == "AI"
        assert data["status"] == "active"
        assert "subscription_id" in data

    def test_create_subscription_invalid_source(self, client):
        """不支持的数据源应返回400"""
        resp = client.post("/api/v1/subscriptions", json={
            "keyword": "test",
            "sources": ["invalid"],
        })
        assert resp.status_code == 400

    def test_list_subscriptions(self, client):
        """获取订阅列表"""
        client.post("/api/v1/subscriptions", json={"keyword": "AI"})
        client.post("/api/v1/subscriptions", json={"keyword": "ML"})

        resp = client.get("/api/v1/subscriptions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_cancel_subscription_success(self, client):
        """正常取消订阅"""
        create_resp = client.post("/api/v1/subscriptions", json={"keyword": "test"})
        sub_id = create_resp.json()["subscription_id"]

        resp = client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert resp.status_code == 200
        assert "已取消" in resp.json()["message"]

        # 取消后不应出现在活跃列表中
        list_resp = client.get("/api/v1/subscriptions")
        assert len(list_resp.json()) == 0

    def test_cancel_subscription_not_found(self, client):
        """取消不存在的订阅应返回404"""
        resp = client.delete(f"/api/v1/subscriptions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_cancel_subscription_already_cancelled(self, client):
        """重复取消应返回400"""
        create_resp = client.post("/api/v1/subscriptions", json={"keyword": "test"})
        sub_id = create_resp.json()["subscription_id"]

        client.delete(f"/api/v1/subscriptions/{sub_id}")
        resp = client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert resp.status_code == 400
        assert "已取消" in resp.json()["detail"]


# ===== 思维导图端点测试 =====


class TestMindmapEndpoint:
    """思维导图API端点测试"""

    def test_get_mindmap_success(self, client, db_session):
        """正常获取思维导图"""
        task_id = _create_task(db_session, keyword="AI技术")
        _create_analysis(db_session, task_id)

        resp = client.get(f"/api/v1/mindmap/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "mermaid_code" in data
        assert "mindmap" in data["mermaid_code"]
        assert "AI技术" in data["mermaid_code"]

    def test_get_mindmap_task_not_found(self, client):
        """任务不存在应返回404"""
        resp = client.get(f"/api/v1/mindmap/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_mindmap_no_analysis(self, client, db_session):
        """无分析结果应返回404"""
        task_id = _create_task(db_session)
        resp = client.get(f"/api/v1/mindmap/{task_id}")
        assert resp.status_code == 404
