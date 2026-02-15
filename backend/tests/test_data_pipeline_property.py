"""
数据管道属性测试

属性 8: 数据质量统计一致性
对于任意数据批次，total = valid + duplicate + discarded 恒成立。

验证需求: 7.3
"""

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.data_models import DataSource, RawPost
from backend.app.models.db_models import CollectionTaskDB
from backend.app.processing.data_pipeline import DataPipeline


# --- 策略定义 ---

source_strategy = st.sampled_from([DataSource.REDDIT, DataSource.YOUTUBE, DataSource.TWITTER])

# 可能为空的内容策略（包含空字符串、纯空白、正常文本）
content_strategy = st.one_of(
    st.just(""),
    st.just("   "),
    st.just("\n\t"),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=100,
    ),
)

external_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
).filter(lambda t: t.strip())


def _make_session():
    """创建测试数据库会话，并清理残留数据"""
    from backend.tests.conftest import TEST_ENGINE
    from backend.app.models.db_models import RawPostDB
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = sessionmaker(bind=TEST_ENGINE)()
    # 清理残留数据，避免 Hypothesis 多次迭代间的干扰
    session.query(RawPostDB).delete()
    session.query(CollectionTaskDB).delete()
    session.commit()
    return session


def _create_task(session) -> str:
    """创建测试用采集任务，返回任务 ID"""
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


def _make_raw_post(source: DataSource, external_id: str, content: str) -> RawPost:
    """构造 RawPost 实例"""
    return RawPost(
        id=f"post-{external_id}",
        source=source,
        external_id=external_id,
        title="测试标题",
        content=content,
        author="test_author",
        url="https://example.com",
        timestamp=datetime.now(timezone.utc),
    )


# 属性 8: 数据质量统计一致性
# 验证需求: 7.3

@given(
    posts_data=st.lists(
        st.tuples(source_strategy, external_id_strategy, content_strategy),
        min_size=1,
        max_size=30,
    ),
)
@settings(max_examples=100)
def test_batch_stats_consistency(posts_data):
    """
    属性 8: 对于任意数据批次，total = valid + duplicate + discarded 恒成立。

    生成包含混合内容（空内容、重复记录、正常数据）的批次，
    验证处理后的统计信息满足 total = valid + duplicate + discarded。

    **Validates: Requirements 7.3**
    """
    session = _make_session()
    try:
        task_id = _create_task(session)
        pipeline = DataPipeline(session)

        posts = [
            _make_raw_post(source, eid, content)
            for source, eid, content in posts_data
        ]

        stats = pipeline.process_batch(posts, task_id)

        # 核心属性: total = valid + duplicate + discarded
        assert stats.total == stats.valid + stats.duplicate + stats.discarded, (
            f"统计不一致: total={stats.total}, "
            f"valid={stats.valid}, duplicate={stats.duplicate}, "
            f"discarded={stats.discarded}"
        )
    finally:
        session.close()
