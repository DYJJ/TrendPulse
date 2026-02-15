"""
思维导图API端点

提供获取Mermaid格式思维导图代码的接口。

需求: 11.1 (将观点聚类结果转换为Mermaid格式), 11.2 (创建思维导图结构)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.analysis.mermaid_generator import MermaidGenerator
from backend.app.api.schemas import MindmapResponse
from backend.app.database import get_db
from backend.app.models.db_models import AnalysisResultDB, CollectionTaskDB

router = APIRouter()
logger = logging.getLogger(__name__)

# 模块级别的生成器实例
_generator = MermaidGenerator()


@router.get("/mindmap/{task_id}", response_model=MindmapResponse)
async def get_mindmap(
    task_id: str,
    db: Session = Depends(get_db),
) -> MindmapResponse:
    """获取思维导图Mermaid代码"""
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

    if not analysis.opinions:
        raise HTTPException(status_code=404, detail="暂无观点数据")

    try:
        mermaid_code = _generator.generate_mindmap(task.keyword, analysis.opinions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MindmapResponse(mermaid_code=mermaid_code)
