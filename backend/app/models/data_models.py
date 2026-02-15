"""
Python数据模型类

定义系统核心数据模型，包括枚举类型和数据类。
这些模型用于业务逻辑层的数据传递，与ORM模型分离。

需求: 14.1 (类型注解), 14.2 (docstring)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from enum import Enum


class DataSource(Enum):
    """数据源枚举

    定义系统支持的社交媒体数据源平台。
    """

    REDDIT = "reddit"
    YOUTUBE = "youtube"
    TWITTER = "twitter"


class TaskStatus(Enum):
    """任务状态枚举

    定义采集任务的生命周期状态。
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SentimentLabel(Enum):
    """情感标签枚举

    定义情感分析结果的分类标签。
    - NEGATIVE: 情感分数 0-30
    - NEUTRAL: 情感分数 31-70
    - POSITIVE: 情感分数 71-100
    """

    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


@dataclass
class ValidationResult:
    """输入验证结果

    Args:
        is_valid: 验证是否通过
        error: 验证失败时的错误描述信息，验证通过时为None
    """

    is_valid: bool
    error: Optional[str] = None


@dataclass
class CollectionParams:
    """采集任务参数

    Args:
        keyword: 搜索关键词
        language: 语言代码 (en/zh)
        limit: 每个数据源的采集条数限制 (1-1000)
        sources: 数据源列表
    """

    keyword: str
    language: str
    limit: int
    sources: List[DataSource] = field(default_factory=list)


@dataclass
class RawPost:
    """原始帖子数据

    从数据源采集的未处理内容，包含帖子的所有元数据。

    Args:
        id: 唯一标识符
        source: 数据来源平台
        external_id: 平台原始ID
        title: 帖子标题（可选）
        content: 帖子内容
        author: 作者名称
        url: 原文链接
        timestamp: 发布时间
        likes: 点赞数
        comments: 评论数
        shares: 分享/转发数
        is_spam: 是否为垃圾内容
    """

    id: str
    source: DataSource
    external_id: str
    title: Optional[str]
    content: str
    author: str
    url: str
    timestamp: datetime
    likes: int = 0
    comments: int = 0
    shares: int = 0
    is_spam: bool = False


@dataclass
class Opinion:
    """观点数据

    从观点聚类中提取的单个争议点。

    Args:
        description: 观点描述
        support_rate: 支持度百分比 (0-100)
        order_index: 排序索引
    """

    description: str
    support_rate: float
    order_index: int


@dataclass
class AnalysisResult:
    """分析结果数据

    AI分析模块生成的完整分析结果。

    Args:
        sentiment_score: 情感分数 (0-100)
        sentiment_label: 情感分类标签
        opinions: 主要观点列表（通常为3个）
        summary: 舆情摘要 (200-500字)
        heat_score: 舆情热度值
        created_at: 创建时间
    """

    sentiment_score: float
    sentiment_label: SentimentLabel
    opinions: List[Opinion]
    summary: str
    heat_score: float
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class CollectionTask:
    """采集任务数据

    表示一个完整的采集任务及其状态和结果。

    Args:
        id: 任务唯一标识符
        params: 采集参数
        status: 任务状态
        progress: 进度百分比 (0-100)
        result: 分析结果（任务完成后）
        error: 错误信息（任务失败时）
        created_at: 创建时间
        updated_at: 最后更新时间
    """

    id: str
    params: CollectionParams
    status: TaskStatus
    progress: int = 0
    result: Optional[AnalysisResult] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
