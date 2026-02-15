"""
帖子列表API端点

提供获取原始帖子列表的接口，支持分页功能。

需求: 9.4 (分页或无限滚动加载)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    InteractionsResponse,
    PostListResponse,
    PostResponse,
)
from backend.app.database import get_db
from backend.app.models.db_models import CollectionTaskDB, RawPostDB

router = APIRouter()
logger = logging.getLogger(__name__)



@router.get("/posts/{task_id}", response_model=PostListResponse)
async def get_posts(
    task_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    source: Optional[str] = Query(default=None, description="平台来源筛选: reddit/youtube/twitter"),
    sort_by: Optional[str] = Query(default=None, description="排序字段: timestamp/likes/comments"),
    sort_order: str = Query(default="desc", description="排序方向: asc/desc"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    db: Session = Depends(get_db),
) -> PostListResponse:
    """获取原始帖子列表（分页 + 筛选 + 排序 + 搜索）"""
    # 校验 source 参数
    valid_sources = {"reddit", "youtube", "twitter"}
    if source is not None and source not in valid_sources:
        raise HTTPException(
            status_code=422,
            detail=f"无效的 source 值: {source}，有效值为: {', '.join(sorted(valid_sources))}",
        )

    # 校验 sort_by 参数
    valid_sort_fields = {"timestamp", "likes", "comments"}
    if sort_by is not None and sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=422,
            detail=f"无效的 sort_by 值: {sort_by}，有效值为: {', '.join(sorted(valid_sort_fields))}",
        )

    # 检查任务是否存在
    task = db.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 构建基础查询
    query = db.query(RawPostDB).filter(RawPostDB.task_id == task_id)

    # 平台来源筛选
    if source:
        query = query.filter(RawPostDB.source == source)

    # 搜索关键词模糊匹配
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                RawPostDB.title.ilike(search_pattern),
                RawPostDB.content.ilike(search_pattern),
            )
        )

    # 查询总数（应用筛选和搜索条件后）
    total = query.count()

    # 排序逻辑
    sort_column_map = {
        "timestamp": RawPostDB.created_at,
        "likes": RawPostDB.likes,
        "comments": RawPostDB.comments,
    }
    sort_column = sort_column_map.get(sort_by, RawPostDB.created_at)
    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # 分页查询
    offset = (page - 1) * page_size
    posts = query.offset(offset).limit(page_size).all()

    post_responses = [
        PostResponse(
            id=p.id,
            source=p.source,
            title=p.title,
            content=p.content,
            author=p.author,
            url=p.url,
            timestamp=p.timestamp,
            interactions=InteractionsResponse(
                likes=p.likes or 0,
                comments=p.comments or 0,
                shares=p.shares or 0,
            ),
        )
        for p in posts
    ]

    return PostListResponse(
        posts=post_responses,
        total=total,
        page=page,
        page_size=page_size,
    )

