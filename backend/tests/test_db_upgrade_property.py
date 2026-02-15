"""
数据库升级属性测试

属性 3: 数据去重正确性
对于任意包含重复记录（相同 source + external_id）的数据批次，
去重后不应存在重复记录，且去重数量等于原始数量减去唯一记录数。

属性 4: 批量插入原子性
对于任意批量插入操作，插入后数据库中的记录数应等于
插入前记录数加上本次有效插入数。

验证需求: 4.3, 4.5
"""

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, bulk_insert
from backend.app.models.db_models import CollectionTaskDB, RawPostDB, generate_uuid


# --- 策略定义 ---

source_strategy = st.sampled_from(["reddit", "youtube", "twitter"])

non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda t: t.strip())

external_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda t: t.strip())


def _make_session():
    """创建测试数据库会话，并清理残留数据"""
    from backend.tests.conftest import TEST_ENGINE
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = sessionmaker(bind=TEST_ENGINE)()
    # 清理残留数据，避免 Hypothesis 多次迭代间的干扰
    session.query(RawPostDB).delete()
    session.query(CollectionTaskDB).delete()
    session.commit()
    return session


def _create_task(session) -> str:
    """创建一个测试用采集任务，返回任务 ID"""
    task = CollectionTaskDB(
        keyword="test",
        language="en",
        limit_per_source=1000,
        sources=["reddit"],
        status="processing",
    )
    session.add(task)
    session.commit()
    return task.id


def _make_post(task_id: str, source: str, external_id: str, content: str) -> RawPostDB:
    """创建一个 RawPostDB 实例"""
    return RawPostDB(
        id=generate_uuid(),
        task_id=task_id,
        source=source,
        external_id=external_id,
        content=content,
        author="test_author",
        url="https://example.com",
        timestamp=datetime.now(timezone.utc),
    )


# 属性 3: 数据去重正确性
# 验证需求: 4.5

@given(
    source=source_strategy,
    external_ids=st.lists(external_id_strategy, min_size=1, max_size=20),
    content=non_empty_text,
)
@settings(max_examples=100)
def test_deduplication_correctness(source, external_ids, content):
    """
    属性 3: 对于任意包含重复记录（相同 source + external_id）的数据批次，
    批量插入后数据库中不应存在重复的 (source, external_id) 组合，
    且成功插入数等于唯一 external_id 的数量。

    **Validates: Requirements 4.5**
    """
    session = _make_session()
    try:
        task_id = _create_task(session)

        # 构造包含重复记录的数据批次
        posts = [_make_post(task_id, source, eid, content) for eid in external_ids]

        unique_count = len(set(external_ids))
        inserted = bulk_insert(session, posts, batch_size=5)

        # 验证: 成功插入数等于唯一记录数
        assert inserted == unique_count

        # 验证: 数据库中无重复 (source, external_id) 组合
        db_posts = session.query(RawPostDB).filter_by(task_id=task_id).all()
        db_pairs = [(p.source, p.external_id) for p in db_posts]
        assert len(db_pairs) == len(set(db_pairs))
    finally:
        session.close()


# 属性 4: 批量插入原子性
# 验证需求: 4.3

@given(
    sources_and_ids=st.lists(
        st.tuples(source_strategy, external_id_strategy),
        min_size=1,
        max_size=30,
        unique=True,
    ),
    content=non_empty_text,
    batch_size=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=100)
def test_bulk_insert_atomicity(sources_and_ids, content, batch_size):
    """
    属性 4: 对于任意批量插入操作，插入后数据库中的记录数应等于
    插入前记录数加上本次有效插入数。

    **Validates: Requirements 4.3**
    """
    session = _make_session()
    try:
        task_id = _create_task(session)

        # 记录插入前的记录数
        count_before = session.query(RawPostDB).count()

        # 构造唯一记录的数据批次
        posts = [
            _make_post(task_id, src, eid, content)
            for src, eid in sources_and_ids
        ]

        inserted = bulk_insert(session, posts, batch_size=batch_size)

        # 记录插入后的记录数
        count_after = session.query(RawPostDB).count()

        # 验证: 插入后记录数 = 插入前记录数 + 实际插入数
        assert count_after == count_before + inserted

        # 验证: 所有记录都是唯一的，实际插入数等于输入数
        assert inserted == len(sources_and_ids)
    finally:
        session.close()
