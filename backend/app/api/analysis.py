"""
分析结果API端点

提供获取AI分析结果的接口，包括情感分数、观点聚类和摘要。

需求: 6.2 (情感分数), 7.1 (观点聚类), 7.2 (观点描述和支持度), 7.3 (摘要)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.schemas import AnalysisResponse, OpinionResponse
from backend.app.database import get_db
from backend.app.models.db_models import AnalysisResultDB, CollectionTaskDB

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/analysis/{task_id}", response_model=AnalysisResponse)
async def get_analysis(
    task_id: str,
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    """获取分析结果

    返回指定任务的情感分数、观点、摘要和热度。
    """
    # 检查任务是否存在
    task = db.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取分析结果
    analysis = (
        db.query(AnalysisResultDB)
        .filter(AnalysisResultDB.task_id == task_id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="分析结果尚未生成")

    # 构建观点列表
    opinions = [
        OpinionResponse(
            description=op.description,
            support_rate=op.support_rate,
        )
        for op in sorted(analysis.opinions, key=lambda o: o.order_index)
    ]

    return AnalysisResponse(
        sentiment_score=analysis.sentiment_score,
        sentiment_label=analysis.sentiment_label,
        opinions=opinions,
        summary=analysis.summary,
        heat_score=analysis.heat_score,
        created_at=analysis.created_at,
    )
