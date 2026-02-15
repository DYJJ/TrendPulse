"""
API请求和响应的Pydantic模型

定义所有API端点的输入验证和输出序列化模型。
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ===== 采集任务 =====

class CreateCollectionRequest(BaseModel):
    """创建采集任务请求"""
    keyword: str = Field(..., min_length=1, description="搜索关键词")
    language: str = Field(default="en", description="语言代码 (en/zh)")
    limit: int = Field(default=50, ge=1, le=200000, description="每个数据源的采集条数限制")
    sources: List[str] = Field(
        default=["reddit", "youtube", "twitter"],
        description="数据源列表",
    )
    start_date: Optional[datetime] = Field(default=None, description="起始日期（可选）")
    end_date: Optional[datetime] = Field(default=None, description="结束日期（可选）")
    subreddits: Optional[List[str]] = Field(default=None, description="指定的 subreddit 列表（可选）")


class CollectionTaskResponse(BaseModel):
    """采集任务响应"""
    task_id: str
    status: str
    created_at: datetime


class CollectionStatusResponse(BaseModel):
    """采集任务状态响应"""
    task_id: str
    status: str
    progress: int
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    collected_count: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    subreddits: Optional[List[str]] = None


# ===== 分析结果 =====

class OpinionResponse(BaseModel):
    """观点响应"""
    description: str
    support_rate: float


class AnalysisResponse(BaseModel):
    """分析结果响应"""
    sentiment_score: float
    sentiment_label: str
    opinions: List[OpinionResponse]
    summary: str
    heat_score: float
    created_at: datetime


# ===== 帖子列表 =====

class InteractionsResponse(BaseModel):
    """互动数据响应"""
    likes: int
    comments: int
    shares: int


class PostResponse(BaseModel):
    """帖子响应"""
    id: str
    source: str
    title: Optional[str] = None
    content: str
    author: Optional[str] = None
    url: Optional[str] = None
    timestamp: Optional[datetime] = None
    interactions: InteractionsResponse


class PostListResponse(BaseModel):
    """帖子列表分页响应"""
    posts: List[PostResponse]
    total: int
    page: int
    page_size: int



# ===== 订阅管理 =====

class CreateSubscriptionRequest(BaseModel):
    """创建订阅请求"""
    keyword: str = Field(..., min_length=1, description="订阅关键词")
    language: str = Field(default="en", description="语言代码 (en/zh)")
    sources: List[str] = Field(
        default=["reddit", "youtube", "twitter"],
        description="数据源列表",
    )
    interval_hours: int = Field(default=6, ge=1, description="采集间隔（小时）")
    limit_per_source: int = Field(default=50, ge=1, le=1000, description="每次采集条数")
    alert_threshold: int = Field(default=30, ge=0, le=100, description="报警阈值")


class SubscriptionResponse(BaseModel):
    """订阅响应"""
    subscription_id: str
    keyword: str
    language: str
    sources: List[str]
    interval_hours: int
    limit_per_source: int
    alert_threshold: int
    status: str
    created_at: datetime


# ===== 思维导图 =====

class MindmapResponse(BaseModel):
    """思维导图响应"""
    mermaid_code: str
