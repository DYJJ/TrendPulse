"""
API路由定义模块

定义所有RESTful API端点，包括采集任务、分析结果、帖子列表、订阅管理和思维导图。
"""

from fastapi import APIRouter

from backend.app.api.collections import router as collections_router
from backend.app.api.analysis import router as analysis_router
from backend.app.api.posts import router as posts_router
from backend.app.api.subscriptions import router as subscriptions_router
from backend.app.api.mindmap import router as mindmap_router

router = APIRouter()

router.include_router(collections_router, tags=["采集任务"])
router.include_router(analysis_router, tags=["分析结果"])
router.include_router(posts_router, tags=["帖子列表"])
router.include_router(subscriptions_router, tags=["订阅管理"])
router.include_router(mindmap_router, tags=["思维导图"])
