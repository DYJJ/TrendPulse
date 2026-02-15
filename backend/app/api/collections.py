"""
采集任务API端点

提供创建采集任务和查询任务状态的接口。

需求: 1.2 (将采集任务加入处理队列)
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    CollectionStatusResponse,
    CollectionTaskResponse,
    CreateCollectionRequest,
)
from backend.app.database import get_db
from backend.app.models.db_models import CollectionTaskDB, RawPostDB
from backend.app.models.data_models import DataSource
from backend.app.utils.validators import validate_collection_params
from backend.app.analysis.ai_analyzer import AIAnalyzer
from backend.app.config import get_config

router = APIRouter()
logger = logging.getLogger(__name__)


async def run_collection_task(task_id: str, request: CreateCollectionRequest) -> None:
    """后台执行采集、清洗和分析任务

    使用批量采集器（PullPush / yt-dlp / snscrape）进行大规模数据采集，
    通过 DataPipeline 进行验证、去重、清洗和批量入库。
    多数据源异步并发采集，单数据源失败不影响其他。

    Args:
        task_id: 任务ID
        request: 采集请求参数
    """
    from backend.app.database import SessionLocal
    from backend.app.batch_scheduler import BatchScheduler
    from backend.app.processing.data_pipeline import DataPipeline

    db = SessionLocal()
    try:
        # 更新任务状态为处理中
        task = db.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).first()
        if not task:
            logger.error("任务不存在: %s", task_id)
            return
        task.status = "processing"
        task.progress = 5
        db.commit()

        config = get_config()
        scheduler = BatchScheduler(rate_limit_delay=1.0)
        pipeline = DataPipeline(session=db)

        logger.info(
            "开始大规模采集: task_id=%s, 关键词='%s', 目标=%d条/源, 数据源=%s",
            task_id, request.keyword, request.limit, request.sources,
        )

        task.progress = 10
        db.commit()

        # 多数据源并发采集+入库
        total_valid = 0
        total_duplicate = 0
        total_discarded = 0
        source_stats = {}

        async def collect_and_store(source: str) -> dict:
            """单个数据源的采集+入库流程"""
            s_valid, s_dup, s_disc = 0, 0, 0
            try:
                # Twitter 采集开关：被 Cloudflare 拦截时可通过 .env 快速关闭
                if source == "twitter":
                    import os
                    twitter_enabled = os.environ.get("TWITTER_ENABLED", "true").lower()
                    if twitter_enabled in ("false", "0", "no", "off"):
                        logger.info("Twitter 采集已禁用（TWITTER_ENABLED=%s），跳过", twitter_enabled)
                        return {"source": source, "valid": 0, "duplicate": 0, "discarded": 0}

                collector = scheduler._create_collector(source, request.language)
                gen = BatchScheduler._get_collector_generator(
                    collector,
                    keyword=request.keyword,
                    limit=request.limit,
                    source=source,
                    language=request.language,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    subreddits=request.subreddits,
                )

                batch_count = 0
                async for batch in gen:
                    stats = pipeline.process_batch(batch, task_id)
                    s_valid += stats.valid
                    s_dup += stats.duplicate
                    s_disc += stats.discarded
                    batch_count += 1

                    logger.info(
                        "数据源 %s 第 %d 批入库: 有效=%d, 重复=%d, 丢弃=%d",
                        source, batch_count, stats.valid, stats.duplicate, stats.discarded,
                    )

                    # 速率限制：小数量采集时缩短延迟
                    rate_delay = 0.2 if request.limit <= 500 else 1.0
                    await asyncio.sleep(rate_delay)

                await BatchScheduler._close_collector(collector)
                logger.info("数据源 %s 采集完成: 有效=%d", source, s_valid)

            except Exception as e:
                logger.error("数据源 %s 采集失败: %s", source, e)

            return {"source": source, "valid": s_valid, "duplicate": s_dup, "discarded": s_disc}

        # 并发执行所有数据源
        results = await asyncio.gather(
            *[collect_and_store(s) for s in request.sources],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.error("数据源采集异常: %s", result)
                continue
            source_stats[result["source"]] = result
            total_valid += result["valid"]
            total_duplicate += result["duplicate"]
            total_discarded += result["discarded"]

        logger.info(
            "全部采集入库完成: task_id=%s, 有效=%d, 重复=%d, 丢弃=%d, 各源=%s",
            task_id, total_valid, total_duplicate, total_discarded, source_stats,
        )

        task.progress = 85
        task.collected_count = total_valid
        db.commit()

        # AI分析（有 API Key 时才执行）
        if config.llm_api_key:
            posts_db = db.query(RawPostDB).filter(
                RawPostDB.task_id == task_id,
                RawPostDB.is_spam == False,
            ).limit(2000).all()

            if posts_db:
                posts_for_analysis = [
                    {
                        "title": p.title,
                        "content": p.content,
                        "likes": p.likes,
                        "comments": p.comments,
                        "shares": p.shares,
                    }
                    for p in posts_db
                ]

                analyzer = AIAnalyzer(
                    llm_api_key=config.llm_api_key,
                    model=config.llm_model,
                    base_url=config.llm_api_base_url,
                    token_warning_threshold=config.token_warning_threshold,
                    api_style=config.llm_api_style,
                )
                await analyzer.analyze(
                    posts=posts_for_analysis,
                    keyword=request.keyword,
                    db=db,
                    task_id=task_id,
                )

        task.status = "completed"
        task.progress = 100
        db.commit()
        logger.info(
            "任务完成: %s, 入库 %d 条（重复 %d, 丢弃 %d）",
            task_id, total_valid, total_duplicate, total_discarded,
        )

    except Exception as e:
        logger.error("任务执行失败: %s, 错误: %s", task_id, e)
        task = db.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).first()
        if task:
            task.status = "failed"
            task.error = str(e)
            db.commit()
    finally:
        db.close()


@router.post("/collections", response_model=CollectionTaskResponse)
async def create_collection(
    request: CreateCollectionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> CollectionTaskResponse:
    """创建采集任务

    验证输入参数后创建任务并加入后台处理队列。
    """
    # 验证参数
    validation = validate_collection_params(
        request.keyword,
        request.language,
        request.limit,
        start_date=request.start_date,
        end_date=request.end_date,
        subreddits=request.subreddits,
    )
    if not validation.is_valid:
        raise HTTPException(status_code=400, detail=validation.error)

    # 验证数据源
    valid_sources = {"reddit", "youtube", "twitter"}
    for source in request.sources:
        if source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的数据源: '{source}'",
            )

    # 创建任务记录
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_db = CollectionTaskDB(
        id=task_id,
        keyword=request.keyword,
        language=request.language,
        limit_per_source=request.limit,
        sources=request.sources,
        status="queued",
        progress=0,
        start_date=request.start_date,
        end_date=request.end_date,
        subreddits=",".join(request.subreddits) if request.subreddits else None,
        created_at=now,
        updated_at=now,
    )
    db.add(task_db)
    db.commit()

    # 加入后台任务队列
    background_tasks.add_task(run_collection_task, task_id, request)

    logger.info("采集任务已创建: %s, 关键词='%s'", task_id, request.keyword)

    return CollectionTaskResponse(
        task_id=task_id,
        status="queued",
        created_at=now,
    )


@router.get("/collections/{task_id}", response_model=CollectionStatusResponse)
async def get_collection_status(
    task_id: str,
    db: Session = Depends(get_db),
) -> CollectionStatusResponse:
    """查询采集任务状态"""
    task = db.query(CollectionTaskDB).filter(CollectionTaskDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return CollectionStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress or 0,
        error=task.error,
        created_at=task.created_at,
        updated_at=task.updated_at,
        collected_count=task.collected_count or 0,
        start_date=task.start_date,
        end_date=task.end_date,
        subreddits=task.subreddits.split(",") if task.subreddits else None,
    )
