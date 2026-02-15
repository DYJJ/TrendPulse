"""
帖子列表搜索不变量属性测试

使用 Hypothesis 库对 GET /posts/{task_id} 端点的搜索功能进行属性测试，
验证对于任意搜索关键词，API 返回的所有帖子的标题或内容中应包含该关键词
（不区分大小写）。

Feature: data-page-enhancement, Property 3: 后端搜索不变量
验证需求: 3.3
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


def _insert_post(db_session, task_id: str, source: str, title: str, content: str, index: int):
    """在数据库中创建一条帖子"""
    post = RawPostDB(
        id=str(uuid.uuid4()),
        task_id=task_id,
        source=source,
        external_id=f"{source}-{task_id}-{index}",
        title=title,
        content=content,
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


# 生成非空的搜索关键词策略（仅字母数字，避免 SQL 通配符干扰）
keyword_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=10,
)


# Feature: data-page-enhancement, Property 3: 后端搜索不变量
class TestSearchProperty:
    """后端搜索不变量属性测试

    **Validates: Requirements 3.3**

    对于任意搜索关键词，API 返回的所有帖子的标题或内容中应包含该关键词
    （不区分大小写）。
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        keyword=keyword_strategy,
        # 生成包含关键词的帖子数量和不包含关键词的帖子数量
        matching_count=st.integers(min_value=1, max_value=5),
        non_matching_count=st.integers(min_value=0, max_value=3),
    )
    def test_search_results_all_contain_keyword(
        self, keyword: str, matching_count: int, non_matching_count: int
    ):
        """搜索返回的所有帖子的标题或内容中应包含关键词（不区分大小写）

        **Validates: Requirements 3.3**
        """
        _setup_db()
        session = _make_session()
        client = _make_client(_SessionFactory)
        try:
            task_id = str(uuid.uuid4())
            _insert_task(session, task_id)

            idx = 0
            # 插入包含关键词的帖子（关键词可能在标题或内容中）
            for i in range(matching_count):
                if i % 2 == 0:
                    # 关键词在标题中
                    _insert_post(
                        session, task_id, "reddit",
                        title=f"前缀{keyword}后缀",
                        content="无关内容",
                        index=idx,
                    )
                else:
                    # 关键词在内容中
                    _insert_post(
                        session, task_id, "youtube",
                        title="无关标题",
                        content=f"前缀{keyword}后缀",
                        index=idx,
                    )
                idx += 1

            # 插入不包含关键词的帖子
            for _ in range(non_matching_count):
                _insert_post(
                    session, task_id, "twitter",
                    title="完全不相关的标题",
                    content="完全不相关的内容",
                    index=idx,
                )
                idx += 1
            session.commit()

            # 执行：带 search 参数请求
            resp = client.get(
                f"/api/v1/posts/{task_id}",
                params={"search": keyword, "page_size": 100},
            )
            assert resp.status_code == 200

            data = resp.json()
            posts = data["posts"]

            # 验证：所有返回帖子的标题或内容包含关键词（不区分大小写）
            keyword_lower = keyword.lower()
            for post in posts:
                title_match = keyword_lower in (post["title"] or "").lower()
                content_match = keyword_lower in (post["content"] or "").lower()
                assert title_match or content_match, (
                    f"帖子不包含关键词 '{keyword}': "
                    f"title='{post['title']}', content='{post['content']}'"
                )

            # 验证：返回数量应等于包含关键词的帖子数
            assert len(posts) == matching_count, (
                f"期望 {matching_count} 条匹配帖子，实际返回 {len(posts)} 条"
            )
        finally:
            session.query(RawPostDB).filter(RawPostDB.task_id == task_id).delete()
            session.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).delete()
            session.commit()
            session.close()
            app.dependency_overrides.clear()
            _teardown_db()
