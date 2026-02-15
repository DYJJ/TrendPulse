"""
观点聚类器模块

提供基于LLM的观点提取和聚类功能，包括：
- 从文本列表中提取主要争议点
- 为每个观点生成描述和支持度

需求: 7.1 (识别并提取3个主要争议点)
需求: 7.2 (为每个争议点提供描述和支持度百分比)
"""

import json
import logging
import re
from typing import Any, List

from backend.app.models.data_models import Opinion

logger = logging.getLogger(__name__)

# 固定提取的观点数量
NUM_OPINIONS = 3


class OpinionClusterer:
    """观点聚类器

    使用LLM API从文本中提取主要观点并聚类，
    确保恰好提取3个观点，每个包含描述和支持度。

    需求: 7.1, 7.2
    """

    SYSTEM_PROMPT = (
        "你是一个专业的舆情分析助手。请从以下文本中提取恰好3个主要争议点/观点。"
        "每个观点需要包含简短描述和支持度百分比（所有支持度之和应为100）。"
        "只返回JSON格式:\n"
        '{"opinions": [\n'
        '  {"description": "观点描述", "support_rate": 数字},\n'
        '  {"description": "观点描述", "support_rate": 数字},\n'
        '  {"description": "观点描述", "support_rate": 数字}\n'
        "]}"
    )

    def __init__(self, llm_client: Any) -> None:
        """初始化观点聚类器

        Args:
            llm_client: LLM API客户端，需要实现chat方法
        """
        self._llm_client = llm_client

    async def extract_opinions(
        self,
        texts: List[str],
        num_clusters: int = NUM_OPINIONS,
    ) -> List[Opinion]:
        """提取主要观点

        调用LLM API分析文本，提取恰好num_clusters个主要观点。
        如果LLM返回的观点数量不正确，会进行调整以确保恰好返回指定数量。

        Args:
            texts: 文本列表
            num_clusters: 聚类数量，默认为3

        Returns:
            观点列表，每个包含描述和支持度
        """
        if not texts:
            return self._generate_default_opinions(num_clusters)

        combined_text = "\n---\n".join(texts)

        try:
            response = await self._llm_client.chat(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=combined_text,
            )
            opinions = self._parse_opinions(response, num_clusters)
            logger.info("观点提取完成: 提取了 %d 个观点", len(opinions))
            return opinions
        except Exception as e:
            logger.error("观点提取失败: %s", e)
            return self._generate_default_opinions(num_clusters)

    def _parse_opinions(
        self, response: str, num_clusters: int
    ) -> List[Opinion]:
        """从LLM响应中解析观点列表

        Args:
            response: LLM的原始响应文本
            num_clusters: 期望的观点数量

        Returns:
            解析后的观点列表
        """
        opinions: List[Opinion] = []

        # 尝试JSON解析
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "opinions" in data:
                raw_opinions = data["opinions"]
            elif isinstance(data, list):
                raw_opinions = data
            else:
                raw_opinions = []

            for i, item in enumerate(raw_opinions):
                if isinstance(item, dict):
                    desc = str(item.get("description", f"观点 {i + 1}"))
                    rate = float(item.get("support_rate", 0))
                    rate = max(0.0, min(100.0, rate))
                    opinions.append(Opinion(
                        description=desc,
                        support_rate=rate,
                        order_index=i,
                    ))
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("无法解析LLM观点响应，尝试正则提取")
            opinions = self._extract_opinions_regex(response)

        # 调整数量以确保恰好num_clusters个
        return self._adjust_opinions_count(opinions, num_clusters)

    def _extract_opinions_regex(self, response: str) -> List[Opinion]:
        """使用正则从文本中提取观点（JSON解析失败时的备选方案）

        Args:
            response: LLM响应文本

        Returns:
            提取到的观点列表
        """
        opinions: List[Opinion] = []
        # 尝试匹配 "描述" + 数字% 的模式
        pattern = r'"description"\s*:\s*"([^"]+)".*?"support_rate"\s*:\s*(\d+(?:\.\d+)?)'
        matches = re.findall(pattern, response, re.DOTALL)

        for i, (desc, rate) in enumerate(matches):
            opinions.append(Opinion(
                description=desc,
                support_rate=max(0.0, min(100.0, float(rate))),
                order_index=i,
            ))

        return opinions

    def _adjust_opinions_count(
        self, opinions: List[Opinion], target: int
    ) -> List[Opinion]:
        """调整观点数量到目标值

        如果观点过多则截断，过少则补充默认观点。
        调整后重新计算支持度使总和为100。

        Args:
            opinions: 原始观点列表
            target: 目标数量

        Returns:
            调整后的观点列表
        """
        if len(opinions) > target:
            opinions = opinions[:target]
        elif len(opinions) < target:
            for i in range(len(opinions), target):
                opinions.append(Opinion(
                    description=f"其他观点 {i + 1}",
                    support_rate=0.0,
                    order_index=i,
                ))

        # 重新分配order_index
        for i, op in enumerate(opinions):
            op.order_index = i

        # 归一化支持度使总和为100
        total_rate = sum(op.support_rate for op in opinions)
        if total_rate > 0:
            for op in opinions:
                op.support_rate = round(op.support_rate / total_rate * 100, 1)
        else:
            # 均分
            equal_rate = round(100.0 / target, 1)
            for op in opinions:
                op.support_rate = equal_rate

        return opinions

    @staticmethod
    def _generate_default_opinions(num_clusters: int) -> List[Opinion]:
        """生成默认观点（无数据或分析失败时使用）

        Args:
            num_clusters: 观点数量

        Returns:
            默认观点列表
        """
        equal_rate = round(100.0 / num_clusters, 1)
        return [
            Opinion(
                description=f"暂无足够数据提取观点 {i + 1}",
                support_rate=equal_rate,
                order_index=i,
            )
            for i in range(num_clusters)
        ]
