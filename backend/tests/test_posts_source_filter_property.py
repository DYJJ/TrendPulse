"""
帖子列表 source 筛选属性测试

使用 Hypothesis 库对 GET /posts/{task_id} 端点的 source 筛选功能进行属性测试，
验证对于任意帖子数据和有效的 source 筛选值，API 返回的所有帖子的 source 字段
都应等于筛选值。

Feature: data-page-enhancement, Property 1: 后端 source 筛选不变量
验证需求: 1.6
"""

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models.db_models import CollectionTaskDB, RawPostDB
from backend.tests.conftest import TEST_DB_URL

VALID_SOURCES = ["reddit", "youtube", "twitter"]

# 测试专用引擎和会话工厂
_engine = create_engine(TEST_DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)
_SessionFactory = sessionmaker(bind=_engine)


def _make_session():
    """创建一个新的数据库会话"""
    return _SessionFactory()


def _make_client(session_factory):
    """创建测试客户端，覆盖数据库依赖"""

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _insert_task(db_session, task_id: str):
    """在数据库中创建一个采集任务"""
    now = datetime.now(timezone.utc)
    task = CollectionTaskDB(
        id=task_id,
        keyword="测试",
        language="zh",
        limit_per_source=50,
        sources=VALID_SOURCES,
        status="completed",
        progress=100,
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()


def _insert_post(db_session, task_id: str, source: str, index: int):
    """在数据库中创建一条帖子"""
    post = RawPostDB(
        id=str(uuid.uuid4()),
        task_id=task_id,
        source=source,
        external_id=f"{source}-{task_id}-{index}",
        title=f"标题 {source} {index}",
        content=f"内容 {source} {index}",
        author=f"作者{index}",
        url=f"https://example.com/{source}/{index}",
        timestamp=datetime.now(timezone.utc),
        likes=index,
        comments=index,
        shares=0,
        is_spam=False,
    )
    db_session.add(post)


def _setup_db():
    """重建表结构"""
    Base.metadata.create_all(bind=_engine)


def _teardown_db():
    """清理表结构"""
    Base.metadata.drop_all(bind=_engine)


# Feature: data-page-enhancement, Property 1: 后端 source 筛选不变量
class TestSourceFilterProperty:
    """后端 source 筛选不变量属性测试

    **Validates: Requirements 1.6**

    对于任意帖子集合和任意有效的 source 筛选值（reddit/youtube/twitter），
    API 返回的所有帖子的 source 字段都应等于筛选值。
    不传 source 参数时，应返回所有平台的帖子。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        source_counts=st.fixed_dictionaries({
            s: st.integers(min_value=0, max_value=5) for s in VALID_SOURCES
        }),
        filter_source=st.sampled_from(VALID_SOURCES),
    )
    def test_filtered_posts_all_match_source(
        self, source_counts: dict, filter_source: str
    ):
        """筛选后返回的所有帖子的 source 字段都应等于筛选值

        **Validates: Requirements 1.6**
        """
        _setup_db()
        session = _make_session()
        client = _make_client(_SessionFactory)
        try:
            # 准备：创建任务和不同平台的帖子
            task_id = str(uuid.uuid4())
            _insert_task(session, task_id)

            idx = 0
            for source, count in source_counts.items():
                for _ in range(count):
                    _insert_post(session, task_id, source, idx)
                    idx += 1
            session.commit()

            # 执行：带 source 参数请求
            resp = client.get(f"/api/v1/posts/{task_id}", params={"source": filter_source})
            assert resp.status_code == 200

            data = resp.json()
            posts = data["posts"]

            # 验证：所有返回帖子的 source 都等于筛选值
            for post in posts:
                assert post["source"] == filter_source, (
                    f"期望 source={filter_source}，实际 source={post['source']}"
                )

            # 验证：返回数量等于该平台的帖子数
            assert len(posts) == source_counts[filter_source]
        finally:
            # 清理：删除本次测试数据
            session.query(RawPostDB).filter(RawPostDB.task_id == task_id).delete()
            session.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).delete()
            session.commit()
            session.close()
            app.dependency_overrides.clear()
            _teardown_db()

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        source_counts=st.fixed_dictionaries({
            s: st.integers(min_value=0, max_value=3) for s in VALID_SOURCES
        }),
    )
    def test_no_filter_returns_all_sources(
        self, source_counts: dict
    ):
        """不传 source 参数时应返回所有平台的帖子

        **Validates: Requirements 1.6**
        """
        _setup_db()
        session = _make_session()
        client = _make_client(_SessionFactory)
        try:
            # 准备：创建任务和不同平台的帖子
            task_id = str(uuid.uuid4())
            _insert_task(session, task_id)

            total_count = 0
            idx = 0
            for source, count in source_counts.items():
                for _ in range(count):
                    _insert_post(session, task_id, source, idx)
                    idx += 1
                total_count += count
            session.commit()

            # 执行：不带 source 参数请求
            resp = client.get(f"/api/v1/posts/{task_id}", params={"page_size": 100})
            assert resp.status_code == 200

            data = resp.json()

            # 验证：返回总数等于所有平台帖子之和
            assert data["total"] == total_count
        finally:
            # 清理
            session.query(RawPostDB).filter(RawPostDB.task_id == task_id).delete()
            session.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).delete()
            session.commit()
            session.close()
            app.dependency_overrides.clear()
            _teardown_db()
