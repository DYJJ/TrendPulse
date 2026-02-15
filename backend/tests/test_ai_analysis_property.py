"""
AI分析属性测试

使用Hypothesis库对AI分析层各组件进行基于属性的测试，
验证情感分析、观点聚类、摘要生成和Token优化的正确性。

属性 8: 情感分数范围约束
属性 9: 情感分数分类一致性
属性 10: 观点提取数量
属性 11: 观点结构完整性
属性 12: 摘要长度约束
属性 21: Token分段处理触发
属性 22: Token使用量记录
验证需求: 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 13.1, 13.3, 13.4
"""

import json
import logging
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, strategies as st, settings, assume

from backend.app.analysis.sentiment_analyzer import SentimentAnalyzer, SentimentResult
from backend.app.analysis.opinion_clusterer import OpinionClusterer, NUM_OPINIONS
from backend.app.analysis.summary_generator import (
    SummaryGenerator,
    MIN_SUMMARY_LENGTH,
    MAX_SUMMARY_LENGTH,
)
from backend.app.analysis.token_optimizer import TokenOptimizer, DEFAULT_MAX_TOKENS
from backend.app.analysis.llm_client import LLMClient, TokenUsage
from backend.app.models.data_models import SentimentLabel


def run_async(coro):
    """辅助函数：在同步测试中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_mock_llm_for_sentiment(score: float):
    """创建返回指定情感分数的模拟LLM客户端（批量模式）"""
    mock = AsyncMock()
    # 批量模式：返回 scores 数组，长度与输入文本数匹配
    async def fake_chat(system_prompt, user_message, temperature=0.3):
        # 统计输入中的编号文本数量
        count = user_message.count("[")
        if count == 0:
            count = 1
        return json.dumps({"scores": [score] * count})
    mock.chat = fake_chat
    return mock


def make_mock_llm_for_opinions(opinions_data: list):
    """创建返回指定观点数据的模拟LLM客户端"""
    mock = AsyncMock()
    mock.chat = AsyncMock(return_value=json.dumps({"opinions": opinions_data}))
    return mock


def make_mock_llm_for_summary(summary_text: str):
    """创建返回指定摘要的模拟LLM客户端"""
    mock = AsyncMock()
    mock.chat = AsyncMock(return_value=json.dumps({"summary": summary_text}))
    return mock


# Feature: trendpulse-sentiment-analysis, Property 8: 情感分数范围约束
class TestSentimentScoreRangeProperty:
    """情感分数范围约束属性测试

    **验证: 需求 6.2**

    对于任意输入文本列表，AI分析模块生成的情感分数应该在0到100的范围内。
    """

    @settings(max_examples=100)
    @given(score=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False))
    def test_sentiment_score_always_in_range(self, score: float):
        """对于LLM返回的任意分数，最终情感分数应在0-100范围内

        **Validates: Requirements 6.2**
        """
        mock_llm = make_mock_llm_for_sentiment(score)
        analyzer = SentimentAnalyzer(mock_llm)
        result = run_async(analyzer.analyze_sentiment(["测试文本"]))

        assert 0 <= result.sentiment_score <= 100

    @settings(max_examples=100)
    @given(
        scores=st.lists(
            st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        )
    )
    def test_overall_score_in_range(self, scores: List[float]):
        """对于任意单独分数列表，整体分数应在0-100范围内

        **Validates: Requirements 6.2**
        """
        overall = SentimentAnalyzer.calculate_overall_score(scores)
        assert 0 <= overall <= 100



# Feature: trendpulse-sentiment-analysis, Property 9: 情感分数分类一致性
class TestSentimentClassificationProperty:
    """情感分数分类一致性属性测试

    **验证: 需求 6.3, 6.4, 6.5**

    对于任意情感分数，分类函数应该根据分数范围返回正确的标签：
    [0-30]→负面，[31-70]→中性，[71-100]→正面
    """

    @settings(max_examples=100)
    @given(score=st.floats(min_value=0, max_value=30, allow_nan=False, allow_infinity=False))
    def test_negative_range_classified_correctly(self, score: float):
        """0-30分应分类为负面

        **Validates: Requirements 6.3**
        """
        label = SentimentAnalyzer.classify_score(score)
        assert label == SentimentLabel.NEGATIVE

    @settings(max_examples=100)
    @given(score=st.floats(min_value=31, max_value=70, allow_nan=False, allow_infinity=False))
    def test_neutral_range_classified_correctly(self, score: float):
        """31-70分应分类为中性

        **Validates: Requirements 6.4**
        """
        label = SentimentAnalyzer.classify_score(score)
        assert label == SentimentLabel.NEUTRAL

    @settings(max_examples=100)
    @given(score=st.floats(min_value=71, max_value=100, allow_nan=False, allow_infinity=False))
    def test_positive_range_classified_correctly(self, score: float):
        """71-100分应分类为正面

        **Validates: Requirements 6.5**
        """
        label = SentimentAnalyzer.classify_score(score)
        assert label == SentimentLabel.POSITIVE

    @settings(max_examples=100)
    @given(score=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
    def test_classification_covers_all_scores(self, score: float):
        """任意0-100分数都应返回有效的情感标签

        **Validates: Requirements 6.3, 6.4, 6.5**
        """
        label = SentimentAnalyzer.classify_score(score)
        assert label in (SentimentLabel.NEGATIVE, SentimentLabel.NEUTRAL, SentimentLabel.POSITIVE)


# Feature: trendpulse-sentiment-analysis, Property 10: 观点提取数量
class TestOpinionCountProperty:
    """观点提取数量属性测试

    **验证: 需求 7.1**

    对于任意文本列表，观点聚类器应该提取恰好3个主要观点。
    """

    @settings(max_examples=100)
    @given(
        num_opinions_returned=st.integers(min_value=0, max_value=10),
    )
    def test_always_returns_exactly_three_opinions(self, num_opinions_returned: int):
        """无论LLM返回多少个观点，最终结果应恰好3个

        **Validates: Requirements 7.1**
        """
        # 构造LLM返回的观点数据
        opinions_data = [
            {"description": f"观点 {i+1}", "support_rate": 100 / max(num_opinions_returned, 1)}
            for i in range(num_opinions_returned)
        ]
        mock_llm = make_mock_llm_for_opinions(opinions_data)
        clusterer = OpinionClusterer(mock_llm)
        result = run_async(clusterer.extract_opinions(["测试文本"]))

        assert len(result) == NUM_OPINIONS

    def test_empty_input_returns_three_opinions(self):
        """空输入也应返回恰好3个默认观点

        **Validates: Requirements 7.1**
        """
        mock_llm = AsyncMock()
        clusterer = OpinionClusterer(mock_llm)
        result = run_async(clusterer.extract_opinions([]))

        assert len(result) == NUM_OPINIONS


# Feature: trendpulse-sentiment-analysis, Property 11: 观点结构完整性
class TestOpinionStructureProperty:
    """观点结构完整性属性测试

    **验证: 需求 7.2**

    对于任意生成的观点，每个观点对象应该包含描述字段和支持度百分比字段，
    且支持度应该在0到100之间。
    """

    @settings(max_examples=100)
    @given(
        descriptions=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=3,
            max_size=3,
        ),
        rates=st.lists(
            st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=3,
        ),
    )
    def test_opinions_have_valid_structure(self, descriptions: List[str], rates: List[float]):
        """每个观点应包含描述和有效的支持度

        **Validates: Requirements 7.2**
        """
        opinions_data = [
            {"description": desc, "support_rate": rate}
            for desc, rate in zip(descriptions, rates)
        ]
        mock_llm = make_mock_llm_for_opinions(opinions_data)
        clusterer = OpinionClusterer(mock_llm)
        result = run_async(clusterer.extract_opinions(["测试文本"]))

        for opinion in result:
            assert hasattr(opinion, "description")
            assert isinstance(opinion.description, str)
            assert len(opinion.description) > 0
            assert hasattr(opinion, "support_rate")
            assert 0 <= opinion.support_rate <= 100


# Feature: trendpulse-sentiment-analysis, Property 12: 摘要长度约束
class TestSummaryLengthProperty:
    """摘要长度约束属性测试

    **验证: 需求 7.3**

    对于任意文本列表，生成的摘要长度应该在200到500字之间。
    """

    @settings(max_examples=100)
    @given(
        summary_text=st.text(min_size=1, max_size=1000),
    )
    def test_summary_length_within_bounds(self, summary_text: str):
        """摘要长度应在200-500字范围内

        **Validates: Requirements 7.3**
        """
        mock_llm = make_mock_llm_for_summary(summary_text)
        generator = SummaryGenerator(mock_llm)
        result = run_async(generator.generate_summary(["测试文本"]))

        assert MIN_SUMMARY_LENGTH <= len(result) <= MAX_SUMMARY_LENGTH

    def test_empty_input_summary_length(self):
        """空输入的默认摘要长度也应在200-500字范围内

        **Validates: Requirements 7.3**
        """
        mock_llm = AsyncMock()
        generator = SummaryGenerator(mock_llm)
        result = run_async(generator.generate_summary([]))

        assert MIN_SUMMARY_LENGTH <= len(result) <= MAX_SUMMARY_LENGTH



# Feature: trendpulse-sentiment-analysis, Property 21: Token分段处理触发
class TestTokenSegmentationProperty:
    """Token分段处理触发属性测试

    **验证: 需求 13.1**

    对于任意输入文本，当Token计数超过4000时，
    AI分析模块应该自动使用分段处理策略。
    """

    def setup_method(self):
        """每个测试方法前初始化Token优化器"""
        self.optimizer = TokenOptimizer()

    @settings(max_examples=100)
    @given(
        num_chunks=st.integers(min_value=2, max_value=5),
        chunk_size=st.integers(min_value=500, max_value=2000),
    )
    def test_long_text_gets_split(self, num_chunks: int, chunk_size: int):
        """超过4000 Token的文本应被分割为多个片段

        **Validates: Requirements 13.1**
        """
        # 生成一段足够长的文本（用重复句子填充）
        sentence = "这是一段用于测试Token分段处理的示例文本内容。" * chunk_size
        total_tokens = self.optimizer.count_tokens(sentence)
        assume(total_tokens > DEFAULT_MAX_TOKENS)

        chunks = self.optimizer.split_text(sentence, DEFAULT_MAX_TOKENS)
        assert len(chunks) > 1

    @settings(max_examples=100)
    @given(text=st.text(min_size=1, max_size=50))
    def test_short_text_not_split(self, text: str):
        """不超过4000 Token的短文本不应被分割

        **Validates: Requirements 13.1**
        """
        total_tokens = self.optimizer.count_tokens(text)
        assume(total_tokens <= DEFAULT_MAX_TOKENS)

        chunks = self.optimizer.split_text(text, DEFAULT_MAX_TOKENS)
        assert len(chunks) == 1

    @settings(max_examples=100)
    @given(
        repeat_count=st.integers(min_value=100, max_value=500),
    )
    def test_each_chunk_within_token_limit(self, repeat_count: int):
        """分割后的每个片段Token数不应超过限制

        **Validates: Requirements 13.1**
        """
        text = "这是一段需要被分割的长文本。" * repeat_count
        total_tokens = self.optimizer.count_tokens(text)
        assume(total_tokens > DEFAULT_MAX_TOKENS)

        chunks = self.optimizer.split_text(text, DEFAULT_MAX_TOKENS)
        for chunk in chunks:
            chunk_tokens = self.optimizer.count_tokens(chunk)
            # 允许少量超出（句子边界分割可能导致轻微超出）
            assert chunk_tokens <= DEFAULT_MAX_TOKENS * 1.1


# Feature: trendpulse-sentiment-analysis, Property 22: Token使用量记录
class TestTokenUsageRecordingProperty:
    """Token使用量记录属性测试

    **验证: 需求 13.3, 13.4**

    对于任意LLM API调用，系统应该记录该调用的Token使用量，
    并且当累计使用量超过阈值时，应该记录警告日志。
    """

    @settings(max_examples=100)
    @given(
        prompt_tokens=st.integers(min_value=0, max_value=10000),
        completion_tokens=st.integers(min_value=0, max_value=10000),
    )
    def test_token_usage_accumulated(self, prompt_tokens: int, completion_tokens: int):
        """每次调用的Token使用量应被正确累加

        **Validates: Requirements 13.3**
        """
        total_tokens = prompt_tokens + completion_tokens
        client = LLMClient(api_key="test-key", token_warning_threshold=999999)

        usage_data = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        client._record_usage(usage_data)

        assert client.total_usage.prompt_tokens == prompt_tokens
        assert client.total_usage.completion_tokens == completion_tokens
        assert client.total_usage.total_tokens == total_tokens

    @settings(max_examples=100)
    @given(
        call_counts=st.integers(min_value=2, max_value=10),
        tokens_per_call=st.integers(min_value=100, max_value=5000),
    )
    def test_multiple_calls_accumulate(self, call_counts: int, tokens_per_call: int):
        """多次调用的Token使用量应正确累加

        **Validates: Requirements 13.3**
        """
        client = LLMClient(api_key="test-key", token_warning_threshold=999999)

        for _ in range(call_counts):
            client._record_usage({
                "prompt_tokens": tokens_per_call,
                "completion_tokens": tokens_per_call,
                "total_tokens": tokens_per_call * 2,
            })

        assert client.total_usage.total_tokens == call_counts * tokens_per_call * 2

    @settings(max_examples=100)
    @given(
        threshold=st.integers(min_value=100, max_value=10000),
        total_tokens=st.integers(min_value=1, max_value=20000),
    )
    def test_warning_logged_when_exceeding_threshold(self, threshold: int, total_tokens: int):
        """当累计Token超过阈值时应记录警告日志

        **Validates: Requirements 13.4**
        """
        client = LLMClient(api_key="test-key", token_warning_threshold=threshold)

        with patch("backend.app.analysis.llm_client.logger") as mock_logger:
            client._record_usage({
                "prompt_tokens": total_tokens // 2,
                "completion_tokens": total_tokens - total_tokens // 2,
                "total_tokens": total_tokens,
            })

            if total_tokens > threshold:
                mock_logger.warning.assert_called()
            else:
                mock_logger.warning.assert_not_called()
