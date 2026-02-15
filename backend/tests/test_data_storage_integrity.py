"""
数据存储完整性属性测试

属性 7: 数据存储完整性
对于任意清洗后的数据，存储到数据库后，查询该数据应该返回包含所有必需字段
（数据源、采集时间、关键词、清洗状态、内容）的完整记录。

验证需求: 5.4, 5.5, 7.5
"""

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.db_models import (
    CollectionTaskDB,
    RawPostDB,
    AnalysisResultDB,
    OpinionDB,
)


# --- 策略定义 ---

source_strategy = st.sampled_from(["reddit", "youtube", "twitter"])
language_strategy = st.sampled_from(["en", "zh"])
sentiment_label_strategy = st.sampled_from(["negative", "neutral", "positive"])

non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda t: t.strip())

keyword_strategy = st.text(
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
    session.query(OpinionDB).delete()
    session.query(AnalysisResultDB).delete()
    session.query(RawPostDB).delete()
    session.query(CollectionTaskDB).delete()
    session.commit()
    return session


# Feature: trendpulse-sentiment-analysis, Property 7: 数据存储完整性
# 验证需求: 5.4, 5.5, 7.5


@given(
    keyword=keyword_strategy,
    language=language_strategy,
    source=source_strategy,
    content=non_empty_text,
    author=non_empty_text,
    is_spam=st.booleans(),
    sentiment_score=st.floats(min_value=0, max_value=100, allow_nan=False),
    sentiment_label=sentiment_label_strategy,
    summary=non_empty_text,
    heat_score=st.floats(min_value=0, max_value=1000, allow_nan=False),
    opinion_desc=non_empty_text,
    support_rate=st.floats(min_value=0, max_value=100, allow_nan=False),
)
@settings(max_examples=100)
def test_data_storage_integrity(
    keyword,
    language,
    source,
    content,
    author,
    is_spam,
    sentiment_score,
    sentiment_label,
    summary,
    heat_score,
    opinion_desc,
    support_rate,
):
    """
    属性7: 对于任意清洗后的数据，存储到数据库后，查询该数据应该返回
    包含所有必需字段（数据源、采集时间、关键词、清洗状态、内容）的完整记录。

    **Validates: Requirements 5.4, 5.5, 7.5**
    """
    session = _make_session()
    try:
        # --- 创建采集任务 ---
        task = CollectionTaskDB(
            keyword=keyword,
            language=language,
            limit_per_source=10,
            sources=[source],
            status="completed",
        )
        session.add(task)
        session.flush()

        # --- 创建原始帖子（模拟清洗后的数据） ---
        post = RawPostDB(
            task_id=task.id,
            source=source,
            external_id="ext_123",
            title="测试标题",
            content=content,
            author=author,
            url="https://example.com/post",
            timestamp=datetime.now(timezone.utc),
            likes=10,
            comments=5,
            shares=2,
            is_spam=is_spam,
        )
        session.add(post)
        session.flush()

        # --- 创建分析结果 ---
        analysis = AnalysisResultDB(
            task_id=task.id,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            summary=summary,
            heat_score=heat_score,
        )
        session.add(analysis)
        session.flush()

        # --- 创建观点 ---
        opinion = OpinionDB(
            analysis_id=analysis.id,
            description=opinion_desc,
            support_rate=support_rate,
            order_index=0,
        )
        session.add(opinion)
        session.commit()

        # --- 验证: 查询并检查所有必需字段完整性 ---

        # 验证采集任务字段完整性
        queried_task = session.query(CollectionTaskDB).filter_by(id=task.id).first()
        assert queried_task is not None
        assert queried_task.keyword == keyword  # 关键词
        assert queried_task.language == language
        assert queried_task.sources == [source]  # 数据源
        assert queried_task.created_at is not None  # 采集时间

        # 验证原始帖子字段完整性（需求5.4, 5.5）
        queried_post = session.query(RawPostDB).filter_by(id=post.id).first()
        assert queried_post is not None
        assert queried_post.source == source  # 数据源
        assert queried_post.content == content  # 内容
        assert queried_post.author == author
        assert queried_post.is_spam == is_spam  # 清洗状态
        assert queried_post.task_id == task.id
        assert queried_post.created_at is not None  # 采集时间

        # 验证分析结果字段完整性（需求7.5）
        queried_analysis = session.query(AnalysisResultDB).filter_by(id=analysis.id).first()
        assert queried_analysis is not None
        assert queried_analysis.sentiment_score == sentiment_score
        assert queried_analysis.sentiment_label == sentiment_label
        assert queried_analysis.summary == summary
        assert queried_analysis.heat_score == heat_score
        assert queried_analysis.task_id == task.id
        assert queried_analysis.created_at is not None

        # 验证观点字段完整性
        queried_opinion = session.query(OpinionDB).filter_by(id=opinion.id).first()
        assert queried_opinion is not None
        assert queried_opinion.description == opinion_desc
        assert queried_opinion.support_rate == support_rate
        assert queried_opinion.analysis_id == analysis.id
    finally:
        session.close()
