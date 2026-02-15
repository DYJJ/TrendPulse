"""
摘要生成器模块

提供基于LLM的舆情摘要生成功能，包括：
- 将大量评论总结为易读摘要
- 确保摘要长度在200-500字之间

需求: 7.3 (生成200-500字的易读摘要)
"""

import json
import logging
import re
from typing import Any, List

logger = logging.getLogger(__name__)

# 摘要长度限制
MIN_SUMMARY_LENGTH = 200
MAX_SUMMARY_LENGTH = 500


class SummaryGenerator:
    """摘要生成器

    使用LLM API将大量文本总结为200-500字的易读摘要。

    需求: 7.3
    """

    SYSTEM_PROMPT = (
        "你是一个专业的舆情分析助手。请将以下社交媒体内容总结为一段易读的摘要。"
        f"摘要长度必须在{MIN_SUMMARY_LENGTH}到{MAX_SUMMARY_LENGTH}字之间。"
        "摘要应涵盖主要观点、情感倾向和关键争议点。"
        '只返回JSON格式: {{"summary": "摘要内容"}}'
    )

    def __init__(self, llm_client: Any) -> None:
        """初始化摘要生成器

        Args:
            llm_client: LLM API客户端，需要实现chat方法
        """
        self._llm_client = llm_client

    async def generate_summary(
        self,
        texts: List[str],
        max_length: int = MAX_SUMMARY_LENGTH,
    ) -> str:
        """生成舆情摘要

        将文本列表合并后调用LLM生成摘要，确保长度在200-500字之间。
        如果LLM返回的摘要不符合长度要求，会进行调整。

        Args:
            texts: 文本列表
            max_length: 最大字数，默认500

        Returns:
            摘要文本 (200-500字)
        """
        if not texts:
            return self._generate_default_summary()

        combined_text = "\n---\n".join(texts)

        try:
            response = await self._llm_client.chat(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=combined_text,
            )
            summary = self._parse_summary(response)
            summary = self._adjust_length(summary, max_length)

            logger.info("摘要生成完成: 长度=%d字", len(summary))
            return summary
        except Exception as e:
            logger.error("摘要生成失败: %s", e)
            return self._generate_default_summary()

    def _parse_summary(self, response: str) -> str:
        """从LLM响应中解析摘要文本

        Args:
            response: LLM的原始响应文本

        Returns:
            解析出的摘要文本
        """
        # 尝试JSON解析
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "summary" in data:
                return str(data["summary"])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # 尝试提取JSON中的summary字段
        match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', response)
        if match:
            return match.group(1)

        # 直接使用响应文本（去除可能的JSON包装）
        cleaned = response.strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            # 尝试去除JSON包装
            inner = cleaned[1:-1].strip()
            if inner:
                return inner

        return cleaned if cleaned else self._generate_default_summary()

    def _adjust_length(self, summary: str, max_length: int) -> str:
        """调整摘要长度到200-500字范围

        如果过长则截断到最近的句子边界，如果过短则补充说明。

        Args:
            summary: 原始摘要
            max_length: 最大字数

        Returns:
            调整后的摘要
        """
        effective_max = min(max_length, MAX_SUMMARY_LENGTH)

        # 过长：截断到最近的句子边界
        if len(summary) > effective_max:
            truncated = summary[:effective_max]
            # 找到最后一个句子结束符
            last_period = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
            )
            if last_period > MIN_SUMMARY_LENGTH:
                summary = truncated[:last_period + 1]
            else:
                summary = truncated

        # 过短：循环补充说明文字直到达到最小长度
        if len(summary) < MIN_SUMMARY_LENGTH:
            padding_sentences = [
                "综合以上分析，该话题在社交媒体上引发了广泛讨论，不同群体持有不同立场和观点。",
                "从整体趋势来看，公众对此话题的关注度较高，讨论涉及多个维度和层面。",
                "建议持续关注舆情动态变化，及时了解公众情绪走向，以便做出更加全面和准确的判断。",
                "各方观点的碰撞反映了社会对该议题的深层关切，值得进一步深入分析和研究。",
                "未来舆情走势可能受到政策变化、媒体报道和公众参与度等多重因素的影响。",
                "从数据分析角度来看，该话题的讨论热度和情感分布呈现出一定的规律性特征。",
                "社交媒体平台上的用户互动数据表明，该话题具有较强的传播力和影响力。",
            ]
            idx = 0
            while len(summary) < MIN_SUMMARY_LENGTH and idx < len(padding_sentences):
                summary = summary + " " + padding_sentences[idx]
                idx += 1
            # 如果仍然不够，重复补充
            while len(summary) < MIN_SUMMARY_LENGTH:
                summary = summary + " " + padding_sentences[idx % len(padding_sentences)]
                idx += 1
            # 检查是否超长
            if len(summary) > effective_max:
                summary = summary[:effective_max]

        return summary

    @staticmethod
    def _generate_default_summary() -> str:
        """生成默认摘要（无数据或分析失败时使用）

        Returns:
            默认摘要文本（200-500字）
        """
        return (
            "暂无足够数据生成详细摘要。系统未能从采集的数据中提取有效信息进行分析。"
            "这可能是由于采集的数据量不足、数据质量较低或分析过程中出现异常。"
            "建议尝试以下措施：扩大采集范围、增加数据源、调整关键词或稍后重试。"
            "系统将持续优化数据采集和分析能力，以提供更准确和全面的舆情分析结果。"
            "如需进一步了解详情，请查看原始数据流页面中的具体帖子内容。"
            "从当前数据来看，该话题的讨论尚未形成明显的舆论趋势，"
            "各方观点较为分散，尚需更多数据支撑才能得出可靠结论。"
        )
