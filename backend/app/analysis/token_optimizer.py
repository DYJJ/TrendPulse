"""
Token优化器模块

提供LLM API的Token使用优化功能，包括：
- Token计数
- 长文本分割
- 关键句提取
- Map-Reduce分析模式

需求: 13.1 (分段处理策略)
需求: 13.2 (提取关键句或使用Map-Reduce模式)
"""

import logging
import re
from typing import Any, Callable, List

logger = logging.getLogger(__name__)

# 默认Token上限阈值
DEFAULT_MAX_TOKENS = 4000


class TokenOptimizer:
    """Token优化器

    负责优化LLM API的Token使用，支持Token计数、文本分割、
    关键句提取和Map-Reduce分析模式。

    需求: 13.1, 13.2
    """

    def __init__(self, model: str = "gpt-3.5-turbo") -> None:
        """初始化Token优化器

        Args:
            model: 使用的LLM模型名称，用于选择对应的编码器
        """
        self._model = model
        self._encoding = None
        self._init_encoding()

    def _init_encoding(self) -> None:
        """初始化tiktoken编码器，失败时使用估算方式"""
        try:
            import tiktoken
            self._encoding = tiktoken.encoding_for_model(self._model)
        except Exception:
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                logger.warning("无法加载tiktoken编码器，将使用估算方式计算Token数量")
                self._encoding = None

    def count_tokens(self, text: str) -> int:
        """计算文本的Token数量

        使用tiktoken进行精确计数，如果tiktoken不可用则使用估算方式。
        估算规则：英文约4字符/token，中文约2字符/token。

        Args:
            text: 输入文本

        Returns:
            Token数量
        """
        if not text:
            return 0

        if self._encoding is not None:
            return len(self._encoding.encode(text))

        # 估算方式：英文约4字符/token，中文约2字符/token
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return chinese_chars // 2 + other_chars // 4 + 1

    def split_text(self, text: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> List[str]:
        """将长文本分割为多个片段

        按句子边界分割文本，确保每个片段不超过max_tokens。
        如果单个句子超过限制，则按字符强制分割。

        Args:
            text: 输入文本
            max_tokens: 每个片段的最大Token数

        Returns:
            文本片段列表
        """
        if not text:
            return []

        total_tokens = self.count_tokens(text)
        if total_tokens <= max_tokens:
            return [text]

        # 按句子边界分割
        sentences = re.split(r'(?<=[。！？.!?])\s*', text)
        sentences = [s for s in sentences if s.strip()]

        chunks: List[str] = []
        current_chunk: List[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)

            # 单个句子超过限制，强制按字符分割
            if sentence_tokens > max_tokens:
                # 先保存当前chunk
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    current_tokens = 0

                # 强制分割长句子
                words = sentence.split()
                if not words:
                    words = [sentence[i:i+100] for i in range(0, len(sentence), 100)]

                temp_chunk: List[str] = []
                temp_tokens = 0
                for word in words:
                    word_tokens = self.count_tokens(word + " ")
                    if temp_tokens + word_tokens > max_tokens and temp_chunk:
                        chunks.append(" ".join(temp_chunk))
                        temp_chunk = []
                        temp_tokens = 0
                    temp_chunk.append(word)
                    temp_tokens += word_tokens
                if temp_chunk:
                    chunks.append(" ".join(temp_chunk))
                continue

            # 正常累加
            if current_tokens + sentence_tokens > max_tokens and current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            current_chunk.append(sentence)
            current_tokens += sentence_tokens

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks if chunks else [text]

    def extract_key_sentences(self, text: str, target_tokens: int) -> str:
        """提取关键句以减少Token数量

        使用简单的启发式方法提取关键句：
        1. 按句子分割
        2. 按句子长度排序（较长的句子通常包含更多信息）
        3. 选取句子直到达到目标Token数

        Args:
            text: 输入文本
            target_tokens: 目标Token数量

        Returns:
            提取后的关键句文本
        """
        if not text:
            return ""

        if self.count_tokens(text) <= target_tokens:
            return text

        # 按句子分割
        sentences = re.split(r'(?<=[。！？.!?])\s*', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return text[:target_tokens * 4]  # 粗略截断

        # 按长度排序，较长句子优先（通常信息量更大）
        scored = [(len(s), i, s) for i, s in enumerate(sentences)]
        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[tuple] = []
        current_tokens = 0

        for length, idx, sentence in scored:
            s_tokens = self.count_tokens(sentence)
            if current_tokens + s_tokens <= target_tokens:
                selected.append((idx, sentence))
                current_tokens += s_tokens

        # 按原始顺序排列
        selected.sort(key=lambda x: x[0])
        return " ".join(s for _, s in selected)

    async def map_reduce_analysis(
        self,
        texts: List[str],
        analysis_func: Callable,
    ) -> Any:
        """使用Map-Reduce模式处理大量文本

        将大量文本分成多个批次，分别调用分析函数（Map阶段），
        然后将各批次结果合并（Reduce阶段）。

        Args:
            texts: 文本列表
            analysis_func: 异步分析函数，接受文本列表并返回分析结果

        Returns:
            合并后的分析结果
        """
        if not texts:
            return None

        # 合并所有文本
        combined = "\n".join(texts)
        total_tokens = self.count_tokens(combined)

        # 如果总Token数在限制内，直接分析
        if total_tokens <= DEFAULT_MAX_TOKENS:
            logger.info("文本总Token数 %d 在限制内，直接分析", total_tokens)
            return await analysis_func(texts)

        # Map阶段：分批处理
        logger.info("文本总Token数 %d 超过限制 %d，启用Map-Reduce模式",
                     total_tokens, DEFAULT_MAX_TOKENS)

        chunks = self.split_text(combined, DEFAULT_MAX_TOKENS)
        partial_results = []

        for i, chunk in enumerate(chunks):
            logger.debug("Map阶段: 处理第 %d/%d 个片段", i + 1, len(chunks))
            result = await analysis_func([chunk])
            partial_results.append(result)

        # Reduce阶段：合并结果
        if len(partial_results) == 1:
            return partial_results[0]

        # 将部分结果的摘要合并后再次分析
        summaries = []
        for r in partial_results:
            if isinstance(r, dict) and "summary" in r:
                summaries.append(r["summary"])
            elif isinstance(r, str):
                summaries.append(r)
            else:
                summaries.append(str(r))

        logger.debug("Reduce阶段: 合并 %d 个部分结果", len(summaries))
        return await analysis_func(summaries)
