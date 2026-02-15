"""
帖子列表排序不变量属性测试

使用 Hypothesis 库对 GET /posts/{task_id} 端点的排序功能进行属性测试，
验证对于任意帖子数据和有效的排序字段及方向，API 返回的帖子列表应按照
指定字段和方向严格有序。

Feature: data-page-enhancement, Property 2: 后端排序不变量
验证需求: 2.3
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models.db_models import CollectionTaskDB, RawPostDB
from backend.tests.conftest import TEST_DB_URL

VALID_SOURCES = ["reddit", "youtube", "twitter"]
VALID_SORT_FIELDS = ["timestamp", "likes", "comments"]
VALID_SORT_ORDERS = ["asc", "desc"]

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


# 帖子数据生成策略：生成 likes、comments 和时间偏移量
post_data_strategy = st.lists(
    st.fixed_dictionaries({
        "source": st.sampled_from(VALID_SOURCES),
        "likes": st.integers(min_value=0, max_value=10000),
        "comments": st.integers(min_value=0, max_value=10000),
        "time_offset_minutes": st.integers(min_value=0, max_value=100000),
    }),
    min_size=2,
    max_size=10,
)


def _insert_posts(db_session, task_id: str, posts_data: list) -> list:
    """批量插入帖子数据，返回插入的帖子列表"""
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    posts = []
    for i, pd in enumerate(posts_data):
        created = base_time + timedelta(minutes=pd["time_offset_minutes"])
        post = RawPostDB(
            id=str(uuid.uuid4()),
            task_id=task_id,
            source=pd["source"],
            external_id=f"{pd['source']}-{task_id}-{i}",
            title=f"标题 {i}",
            content=f"内容 {i}",
            author=f"作者{i}",
            url=f"https://example.com/{i}",
            timestamp=created,
            likes=pd["likes"],
            comments=pd["comments"],
            shares=0,
            is_spam=False,
            created_at=created,
        )
        db_session.add(post)
        posts.append(post)
    db_session.commit()
    return posts


def _extract_sort_values(response_posts: list, sort_by: str) -> list:
    """从 API 响应中提取排序字段的值列表"""
    if sort_by == "likes":
        return [p["interactions"]["likes"] for p in response_posts]
    elif sort_by == "comments":
        return [p["interactions"]["comments"] for p in response_posts]
    else:
        # timestamp 排序：使用返回的 timestamp 字段
        return [p["timestamp"] for p in response_posts]


def _is_sorted(values: list, order: str) -> bool:
    """检查列表是否按指定方向有序"""
    if order == "asc":
        return all(a <= b for a, b in zip(values, values[1:]))
    else:
        return all(a >= b for a, b in zip(values, values[1:]))


# Feature: data-page-enhancement, Property 2: 后端排序不变量
class TestSortProperty:
    """后端排序不变量属性测试

    **Validates: Requirements 2.3**

    对于任意帖子集合和任意有效的排序字段（timestamp/likes/comments）
    及排序方向（asc/desc），API 返回的帖子列表应按照指定字段和方向严格有序。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        posts_data=post_data_strategy,
        sort_by=st.sampled_from(VALID_SORT_FIELDS),
        sort_order=st.sampled_from(VALID_SORT_ORDERS),
    )
    def test_posts_sorted_by_field_and_order(
        self, posts_data: list, sort_by: str, sort_order: str
    ):
        """API 返回的帖子应按指定字段和方向有序

        **Validates: Requirements 2.3**
        """
        _setup_db()
        session = _make_session()
        client = _make_client(_SessionFactory)
        try:
            task_id = str(uuid.uuid4())
            _insert_task(session, task_id)
            _insert_posts(session, task_id, posts_data)

            # 请求足够大的 page_size 以获取所有帖子
            resp = client.get(
                f"/api/v1/posts/{task_id}",
                params={
                    "sort_by": sort_by,
                    "sort_order": sort_order,
                    "page_size": 100,
                },
            )
            assert resp.status_code == 200

            data = resp.json()
            posts = data["posts"]

            # 至少有 2 条帖子才能验证排序
            assert len(posts) >= 2

            # 提取排序字段值并验证有序性
            values = _extract_sort_values(posts, sort_by)
            assert _is_sorted(values, sort_order), (
                f"排序不正确: sort_by={sort_by}, sort_order={sort_order}, "
                f"values={values}"
            )
        finally:
            session.query(RawPostDB).filter(RawPostDB.task_id == task_id).delete()
            session.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).delete()
            session.commit()
            session.close()
            app.dependency_overrides.clear()
            _teardown_db()


def _setup_db():
    """重建表结构"""
    Base.metadata.create_all(bind=_engine)


def _teardown_db():
    """清理表结构"""
    Base.metadata.drop_all(bind=_engine)
