"""
AI分析器协调模块

协调所有AI分析任务，包括Token优化、情感分析、观点聚类和摘要生成。
负责整合各组件的分析结果并持久化到数据库。

需求: 6.6 (数据量超过Token限制时使用分段处理)
需求: 7.4 (优化Prompt以控制Token成本)
需求: 7.5 (将分析结果存入数据库)
需求: 13.3 (记录每次调用的Token使用量)
需求: 13.4 (Token使用量超过阈值时记录警告)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.analysis.llm_client import LLMClient
from backend.app.analysis.opinion_clusterer import OpinionClusterer
from backend.app.analysis.sentiment_analyzer import SentimentAnalyzer
from backend.app.analysis.summary_generator import SummaryGenerator
from backend.app.analysis.token_optimizer import TokenOptimizer
from backend.app.models.data_models import (
    AnalysisResult,
    Opinion,
    SentimentLabel,
)
from backend.app.models.db_models import AnalysisResultDB, OpinionDB

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """AI分析器协调类

    协调Token优化、情感分析、观点聚类和摘要生成等AI分析任务。
    集成所有分析组件，提供统一的分析入口。

    需求: 6.6, 7.4, 7.5, 13.3, 13.4
    """

    def __init__(
        self,
        llm_api_key: str,
        model: str = "gpt-3.5-turbo",
        base_url: str = "https://api.openai.com/v1",
        token_warning_threshold: int = 100000,
        api_style: str = "openai",
    ) -> None:
        """初始化AI分析器

        Args:
            llm_api_key: LLM API密钥
            model: LLM模型名称
            base_url: LLM API基础URL
            token_warning_threshold: Token使用量警告阈值
            api_style: API风格，"openai" 或 "anthropic"
        """
        self._llm_client = LLMClient(
            api_key=llm_api_key,
            model=model,
            base_url=base_url,
            token_warning_threshold=token_warning_threshold,
            api_style=api_style,
        )
        self._token_optimizer = TokenOptimizer(model=model)
        self._sentiment_analyzer = SentimentAnalyzer(self._llm_client)
        self._opinion_clusterer = OpinionClusterer(self._llm_client)
        self._summary_generator = SummaryGenerator(self._llm_client)

    @property
    def token_usage(self) -> int:
        """获取累计Token使用量"""
        return self._llm_client.total_usage.total_tokens

    async def analyze(
        self,
        posts: List[Dict[str, Any]],
        keyword: str,
        db: Optional[Session] = None,
        task_id: Optional[str] = None,
    ) -> AnalysisResult:
        """执行完整的AI分析

        协调Token优化、情感分析、观点聚类和摘要生成，
        并将结果持久化到数据库。

        Args:
            posts: 清洗后的帖子列表，每个帖子为字典
            keyword: 原始搜索关键词
            db: 数据库会话（可选，用于持久化）
            task_id: 关联的采集任务ID（可选）

        Returns:
            AnalysisResult: 包含情感分数、观点聚类和摘要
        """
        logger.info("开始AI分析: 关键词='%s', 帖子数=%d", keyword, len(posts))

        # 提取文本内容
        texts = self._extract_texts(posts)

        if not texts:
            logger.warning("无有效文本内容可供分析")
            return self._empty_result()

        # Token优化：检查是否需要分段处理
        optimized_texts = self._optimize_texts(texts)

        # 并行执行三项分析任务
        sentiment_result = await self._sentiment_analyzer.analyze_sentiment(
            optimized_texts
        )
        opinions = await self._opinion_clusterer.extract_opinions(
            optimized_texts
        )
        summary = await self._summary_generator.generate_summary(
            optimized_texts
        )

        # 计算舆情热度
        heat_score = self._calculate_heat_score(posts)

        # 构建分析结果
        result = AnalysisResult(
            sentiment_score=sentiment_result.sentiment_score,
            sentiment_label=sentiment_result.sentiment_label,
            opinions=opinions,
            summary=summary,
            heat_score=heat_score,
            created_at=datetime.now(timezone.utc),
        )

        # 记录Token使用量
        logger.info(
            "AI分析完成: 情感分数=%.1f, 标签=%s, 热度=%.1f, Token累计=%d",
            result.sentiment_score,
            result.sentiment_label.value,
            result.heat_score,
            self.token_usage,
        )

        # 持久化到数据库
        if db is not None and task_id is not None:
            self._save_to_db(db, task_id, result)

        return result

    def _extract_texts(self, posts: List[Dict[str, Any]]) -> List[str]:
        """从帖子列表中提取文本内容

        合并标题和内容字段。

        Args:
            posts: 帖子列表

        Returns:
            文本列表
        """
        texts: List[str] = []
        for post in posts:
            title = post.get("title", "") or ""
            content = post.get("content", "") or ""
            combined = f"{title} {content}".strip()
            if combined:
                texts.append(combined)
        return texts

    def _optimize_texts(self, texts: List[str]) -> List[str]:
        """优化文本以控制Token使用

        如果总Token数超过阈值，使用关键句提取减少Token数量。

        Args:
            texts: 原始文本列表

        Returns:
            优化后的文本列表
        """
        combined = "\n".join(texts)
        total_tokens = self._token_optimizer.count_tokens(combined)

        if total_tokens <= 4000:
            return texts

        logger.info(
            "文本总Token数 %d 超过4000，启用Token优化", total_tokens
        )

        # 对每个文本提取关键句
        target_per_text = max(100, 4000 // len(texts))
        optimized: List[str] = []
        for text in texts:
            if self._token_optimizer.count_tokens(text) > target_per_text:
                optimized.append(
                    self._token_optimizer.extract_key_sentences(
                        text, target_per_text
                    )
                )
            else:
                optimized.append(text)

        return optimized

    @staticmethod
    def _calculate_heat_score(posts: List[Dict[str, Any]]) -> float:
        """计算舆情热度

        使用对数缩放 + 多维度加权的方式计算热度值，
        避免大规模采集时轻易打满 100 分。

        评分维度：
        - 数据量维度 (25分): 帖子数量，对数缩放，1000条约15分，10000条约25分
        - 互动密度维度 (35分): 平均每条帖子的加权互动量，反映内容质量
        - 互动集中度维度 (20分): 高互动帖子占比，反映是否有爆款内容
        - 时效性维度 (20分): 近期帖子占比，反映话题当前热度

        Args:
            posts: 帖子列表

        Returns:
            热度值 (0-100)
        """
        import math
        from datetime import datetime, timezone, timedelta

        if not posts:
            return 0.0

        n = len(posts)

        # === 维度1: 数据量 (25分) ===
        # 对数缩放: 10条≈8分, 100条≈16分, 1000条≈21分, 10000条≈25分
        volume_score = min(math.log10(max(n, 1)) / math.log10(10000), 1.0) * 25

        # === 维度2: 互动密度 (35分) ===
        # 计算每条帖子的加权互动量，取中位数而非平均值（抗极端值）
        interactions_per_post = []
        for post in posts:
            likes = post.get("likes", 0) or 0
            comments = post.get("comments", 0) or 0
            shares = post.get("shares", 0) or 0
            weighted = likes + comments * 2 + shares * 3
            interactions_per_post.append(weighted)

        interactions_per_post.sort()
        median_idx = n // 2
        median_interaction = (
            interactions_per_post[median_idx]
            if n % 2 == 1
            else (interactions_per_post[median_idx - 1] + interactions_per_post[median_idx]) / 2
        )
        # 对数缩放: 中位互动 1≈5分, 10≈17分, 100≈26分, 1000≈35分
        density_score = (
            min(math.log10(max(median_interaction, 1)) / math.log10(1000), 1.0) * 35
        )

        # === 维度3: 互动集中度 (20分) ===
        # 高互动帖子（互动量 > 中位数*5 或 > 100）的占比
        high_threshold = max(median_interaction * 5, 100)
        high_interaction_count = sum(
            1 for v in interactions_per_post if v >= high_threshold
        )
        high_ratio = high_interaction_count / n
        # 5% 高互动帖子约 10 分，20% 约 20 分
        concentration_score = min(high_ratio / 0.2, 1.0) * 20

        # === 维度4: 时效性 (20分) ===
        # 最近7天内帖子的占比
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        recent_count = 0
        has_timestamp = 0
        for post in posts:
            ts = post.get("timestamp")
            if ts is None:
                continue
            has_timestamp += 1
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= week_ago:
                    recent_count += 1
            elif isinstance(ts, str):
                try:
                    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if parsed >= week_ago:
                        recent_count += 1
                except (ValueError, TypeError):
                    pass

        if has_timestamp > 0:
            recency_ratio = recent_count / has_timestamp
        else:
            # 无时间戳数据，给一个中等分数
            recency_ratio = 0.5
        recency_score = min(recency_ratio / 0.5, 1.0) * 20

        heat = volume_score + density_score + concentration_score + recency_score
        return round(max(0.0, min(100.0, heat)), 1)

    def _save_to_db(
        self,
        db: Session,
        task_id: str,
        result: AnalysisResult,
    ) -> None:
        """将分析结果持久化到数据库

        Args:
            db: 数据库会话
            task_id: 采集任务ID
            result: 分析结果
        """
        try:
            analysis_id = str(uuid.uuid4())

            analysis_db = AnalysisResultDB(
                id=analysis_id,
                task_id=task_id,
                sentiment_score=result.sentiment_score,
                sentiment_label=result.sentiment_label.value,
                summary=result.summary,
                heat_score=result.heat_score,
                token_usage=self.token_usage,
                created_at=result.created_at,
            )
            db.add(analysis_db)

            for opinion in result.opinions:
                opinion_db = OpinionDB(
                    id=str(uuid.uuid4()),
                    analysis_id=analysis_id,
                    description=opinion.description,
                    support_rate=opinion.support_rate,
                    order_index=opinion.order_index,
                )
                db.add(opinion_db)

            db.commit()
            logger.info("分析结果已保存到数据库: task_id=%s", task_id)
        except Exception as e:
            db.rollback()
            logger.error("保存分析结果到数据库失败: %s", e)
            raise

    @staticmethod
    def _empty_result() -> AnalysisResult:
        """生成空分析结果

        Returns:
            默认的空分析结果
        """
        return AnalysisResult(
            sentiment_score=50.0,
            sentiment_label=SentimentLabel.NEUTRAL,
            opinions=[
                Opinion(
                    description="暂无足够数据提取观点",
                    support_rate=33.3,
                    order_index=i,
                )
                for i in range(3)
            ],
            summary="暂无足够数据生成摘要。",
            heat_score=0.0,
            created_at=datetime.now(timezone.utc),
        )
