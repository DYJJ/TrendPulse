"""
情感分析器模块

提供基于LLM的情感分析功能，包括：
- 批量调用LLM API进行情感分析（每批20条，大幅减少Token开销）
- 计算整体情感分数
- 情感分数到标签的分类映射

需求: 6.1 (调用LLM API进行情感分析)
需求: 6.2 (生成0-100情感分数)
需求: 6.3 (0-30标记为负面)
需求: 6.4 (31-70标记为中性)
需求: 6.5 (71-100标记为正面)
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.app.models.data_models import SentimentLabel
from backend.app.analysis.llm_client import LLMAuthenticationError

logger = logging.getLogger(__name__)

# 每批分析的文本数量
BATCH_SIZE = 20
# 每条文本截断长度（字符），避免单批 prompt 过长
MAX_TEXT_LENGTH = 200


@dataclass
class SentimentResult:
    """情感分析结果

    Args:
        sentiment_score: 情感分数 (0-100)
        sentiment_label: 情感分类标签
        individual_scores: 各文本的单独情感分数
    """

    sentiment_score: float
    sentiment_label: SentimentLabel
    individual_scores: List[float]


class SentimentAnalyzer:
    """情感分析器

    使用LLM API批量分析文本的情感倾向，生成0-100的情感分数并分类。
    每批处理20条文本，系统提示词只发一次，大幅减少Token开销。

    需求: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    # 批量情感分析的系统提示词
    SYSTEM_PROMPT = (
        "你是一个专业的情感分析助手。我会给你一组编号文本，请分析每条文本的情感倾向。"
        "对每条文本返回一个0到100之间的整数分数。"
        "0表示极度负面，50表示中性，100表示极度正面。"
        '只返回JSON格式: {"scores": [分数1, 分数2, ...]}'
        "\n分数数组的长度必须与输入文本数量完全一致。"
    )

    def __init__(self, llm_client: Any) -> None:
        """初始化情感分析器

        Args:
            llm_client: LLM API客户端，需要实现chat方法
        """
        self._llm_client = llm_client

    async def analyze_sentiment(self, texts: List[str]) -> SentimentResult:
        """批量分析文本列表的情感倾向

        将文本分批（每批20条）发送给LLM，一次返回多个分数。
        相比逐条分析，Token开销降低约80%。

        Args:
            texts: 待分析的文本列表

        Returns:
            SentimentResult: 包含整体分数、标签和各文本单独分数
        """
        if not texts:
            return SentimentResult(
                sentiment_score=50.0,
                sentiment_label=SentimentLabel.NEUTRAL,
                individual_scores=[],
            )

        individual_scores: List[float] = []
        auth_failed = False

        # 分批处理
        for i in range(0, len(texts), BATCH_SIZE):
            if auth_failed:
                # 认证失败，剩余全部按中性处理
                remaining = len(texts) - len(individual_scores)
                individual_scores.extend([50.0] * remaining)
                break

            batch = texts[i:i + BATCH_SIZE]
            batch_scores = await self._analyze_batch(batch)

            if batch_scores is None:
                # 认证失败
                auth_failed = True
                remaining = len(texts) - len(individual_scores)
                logger.warning(
                    "LLM认证失败，跳过剩余 %d 条文本的情感分析", remaining
                )
                individual_scores.extend([50.0] * remaining)
                break

            individual_scores.extend(batch_scores)

        overall_score = self.calculate_overall_score(individual_scores)
        label = self.classify_score(overall_score)

        logger.info(
            "情感分析完成: 分数=%.1f, 标签=%s, 文本数=%d, 批次数=%d",
            overall_score, label.value, len(texts),
            (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE,
        )

        return SentimentResult(
            sentiment_score=overall_score,
            sentiment_label=label,
            individual_scores=individual_scores,
        )

    async def _analyze_batch(self, texts: List[str]) -> Optional[List[float]]:
        """批量分析一组文本的情感分数

        将多条文本编号后打包成一个请求，LLM 一次返回所有分数。

        Args:
            texts: 一批待分析文本（最多 BATCH_SIZE 条）

        Returns:
            情感分数列表，认证失败时返回 None
        """
        # 构建编号文本
        numbered_texts = []
        for idx, text in enumerate(texts, 1):
            # 截断过长文本
            truncated = text[:MAX_TEXT_LENGTH] if len(text) > MAX_TEXT_LENGTH else text
            numbered_texts.append(f"[{idx}] {truncated}")

        user_message = "\n".join(numbered_texts)

        try:
            response = await self._llm_client.chat(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=user_message,
            )
            scores = self._parse_batch_scores(response, len(texts))
            return scores
        except LLMAuthenticationError:
            logger.error("LLM API认证失败，停止情感分析")
            return None
        except Exception as e:
            logger.error("批量情感分析失败: %s", e)
            # 分析失败时返回中性分数
            return [50.0] * len(texts)

    def _parse_batch_scores(self, response: str, expected_count: int) -> List[float]:
        """从LLM响应中解析批量情感分数

        Args:
            response: LLM的原始响应文本
            expected_count: 期望的分数数量

        Returns:
            情感分数列表
        """
        # 尝试JSON解析
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "scores" in data:
                raw_scores = data["scores"]
                if isinstance(raw_scores, list):
                    scores = [self._clamp_score(float(s)) for s in raw_scores]
                    # 数量匹配检查
                    if len(scores) == expected_count:
                        return scores
                    # 数量不匹配，尽量使用已有的
                    logger.warning(
                        "LLM返回分数数量(%d)与期望(%d)不匹配，进行调整",
                        len(scores), expected_count,
                    )
                    return self._adjust_scores_count(scores, expected_count)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # JSON 解析失败，尝试正则提取所有数字
        numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', response)
        scores = []
        for num_str in numbers:
            num = float(num_str)
            if 0 <= num <= 100:
                scores.append(num)

        if scores:
            return self._adjust_scores_count(scores, expected_count)

        logger.warning("无法从LLM响应中解析情感分数，返回中性值: %s", response[:200])
        return [50.0] * expected_count

    @staticmethod
    def _adjust_scores_count(scores: List[float], target: int) -> List[float]:
        """调整分数列表长度到目标值

        Args:
            scores: 原始分数列表
            target: 目标长度

        Returns:
            调整后的分数列表
        """
        if len(scores) >= target:
            return scores[:target]
        # 不足的用已有分数的平均值填充
        avg = sum(scores) / len(scores) if scores else 50.0
        scores.extend([avg] * (target - len(scores)))
        return scores

    @staticmethod
    def _clamp_score(score: float) -> float:
        """将分数限制在0-100范围内"""
        return max(0.0, min(100.0, score))

    @staticmethod
    def calculate_overall_score(individual_scores: List[float]) -> float:
        """计算整体情感分数

        Args:
            individual_scores: 各文本的情感分数列表

        Returns:
            整体情感分数 (0-100)
        """
        if not individual_scores:
            return 50.0
        avg = sum(individual_scores) / len(individual_scores)
        return max(0.0, min(100.0, round(avg, 1)))

    @staticmethod
    def classify_score(score: float) -> SentimentLabel:
        """根据情感分数返回分类标签

        分类规则：
        - [0, 30]: 负面 (NEGATIVE)
        - [31, 70]: 中性 (NEUTRAL)
        - [71, 100]: 正面 (POSITIVE)
        """
        if score <= 30:
            return SentimentLabel.NEGATIVE
        elif score <= 70:
            return SentimentLabel.NEUTRAL
        else:
            return SentimentLabel.POSITIVE
