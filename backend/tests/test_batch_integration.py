"""
大规模数据采集集成测试

使用 mock 模拟 PullPush/yt-dlp/snscrape 输出，
测试完整的采集 → 管道 → 存储流程、降级策略自动切换、断点续采功能。
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, bulk_insert
from backend.app.models.data_models import DataSource, RawPost
from backend.app.models.db_models import CollectionTaskDB, RawPostDB
from backend.app.processing.data_pipeline import DataPipeline, BatchStats
from backend.app.processing.data_cleaner import DataCleaner
from backend.app.batch_scheduler import BatchScheduler, TaskProgress
from backend.app.collection_monitor import CollectionMonitor
from backend.tests.conftest import TEST_ENGINE


# ===== 辅助函数 =====

def _make_raw_post(
    source: DataSource = DataSource.REDDIT,
    external_id: str = None,
    content: str = "测试内容",
    title: str = "测试标题",
) -> RawPost:
    """创建测试用 RawPost 对象"""
    return RawPost(
        id=str(uuid.uuid4()),
        source=source,
        external_id=external_id or str(uuid.uuid4()),
        title=title,
        content=content,
        author="test_author",
        url="https://example.com/test",
        timestamp=datetime.now(timezone.utc),
        likes=10,
        comments=5,
        shares=2,
    )


def _create_task_db(db_session, task_id=None, keyword="集成测试", status="processing"):
    """在数据库中创建采集任务记录"""
    tid = task_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task = CollectionTaskDB(
        id=tid,
        keyword=keyword,
        language="zh",
        limit_per_source=1000,
        sources=["reddit"],
        status=status,
        progress=0,
        collected_count=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return tid


def _make_pullpush_response(count: int, start_utc: int = 1700000000) -> dict:
    """构造模拟的 PullPush API 响应"""
    data = []
    for i in range(count):
        data.append({
            "id": f"reddit_post_{start_utc + i}",
            "title": f"Reddit 帖子标题 {i}",
            "selftext": f"Reddit 帖子内容 {i}，用于集成测试。",
            "author": f"user_{i}",
            "permalink": f"/r/test/comments/{start_utc + i}/post/",
            "created_utc": start_utc + i,
            "score": i * 10,
            "num_comments": i * 3,
            "subreddit": "test",
        })
    return {"data": data}


def _make_snscrape_output(count: int) -> list:
    """构造模拟的 snscrape 输出"""
    tweets = []
    for i in range(count):
        tweets.append({
            "id": f"tweet_{i}",
            "url": f"https://x.com/user/status/tweet_{i}",
            "rawContent": f"推文内容 {i}，用于集成测试。",
            "user": {"username": f"twitter_user_{i}"},
            "date": "2024-06-01T12:00:00+00:00",
            "likeCount": i * 5,
            "replyCount": i * 2,
            "retweetCount": i,
        })
    return tweets


# ===== 1. 采集 → 管道 → 存储 完整流程测试 =====


class TestCollectPipelineStorage:
    """测试完整的采集 → 数据管道 → 存储流程"""

    def test_reddit_collect_pipeline_store(self, db_session):
        """测试 Reddit 采集数据经过管道处理后正确存储到数据库"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        # 模拟 Reddit 采集器返回的数据
        posts = [
            _make_raw_post(DataSource.REDDIT, f"reddit_{i}", f"Reddit 内容 {i}")
            for i in range(10)
        ]

        stats = pipeline.process_batch(posts, task_id)

        # 验证统计信息一致性: total = valid + duplicate + discarded
        assert stats.total == 10
        assert stats.total == stats.valid + stats.duplicate + stats.discarded
        assert stats.valid == 10
        assert stats.duplicate == 0
        assert stats.discarded == 0

        # 验证数据库中的记录
        db_posts = db_session.query(RawPostDB).filter(
            RawPostDB.task_id == task_id
        ).all()
        assert len(db_posts) == 10

        for post in db_posts:
            assert post.source == "reddit"
            assert post.content
            assert post.task_id == task_id

    def test_youtube_collect_pipeline_store(self, db_session):
        """测试 YouTube 采集数据经过管道处理后正确存储"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        posts = [
            _make_raw_post(DataSource.YOUTUBE, f"yt_video_{i}", f"YouTube 视频描述 {i}")
            for i in range(5)
        ]

        stats = pipeline.process_batch(posts, task_id)
        assert stats.valid == 5

        db_posts = db_session.query(RawPostDB).filter(
            RawPostDB.task_id == task_id
        ).all()
        assert len(db_posts) == 5

    def test_twitter_collect_pipeline_store(self, db_session):
        """测试 Twitter 采集数据经过管道处理后正确存储"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        posts = [
            _make_raw_post(DataSource.TWITTER, f"tweet_{i}", f"推文内容 {i}")
            for i in range(8)
        ]

        stats = pipeline.process_batch(posts, task_id)
        assert stats.valid == 8

    def test_pipeline_dedup_across_batches(self, db_session):
        """测试管道跨批次去重"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        # 第一批数据
        batch1 = [
            _make_raw_post(DataSource.REDDIT, f"post_{i}", f"内容 {i}")
            for i in range(5)
        ]
        stats1 = pipeline.process_batch(batch1, task_id)
        assert stats1.valid == 5

        # 第二批数据包含重复
        batch2 = [
            _make_raw_post(DataSource.REDDIT, "post_0", "重复内容 0"),  # 重复
            _make_raw_post(DataSource.REDDIT, "post_1", "重复内容 1"),  # 重复
            _make_raw_post(DataSource.REDDIT, "post_new", "新内容"),     # 新数据
        ]
        stats2 = pipeline.process_batch(batch2, task_id)
        assert stats2.duplicate == 2
        assert stats2.valid == 1

        # 数据库中应有 6 条记录
        total = db_session.query(RawPostDB).filter(
            RawPostDB.task_id == task_id
        ).count()
        assert total == 6

    def test_pipeline_discard_empty_content(self, db_session):
        """测试管道丢弃空内容数据"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        posts = [
            _make_raw_post(DataSource.REDDIT, "valid_1", "有效内容"),
            _make_raw_post(DataSource.REDDIT, "empty_1", ""),        # 空内容
            _make_raw_post(DataSource.REDDIT, "empty_2", "   "),     # 仅空白
            _make_raw_post(DataSource.REDDIT, "valid_2", "另一条有效内容"),
        ]

        stats = pipeline.process_batch(posts, task_id)
        assert stats.total == 4
        assert stats.valid == 2
        assert stats.discarded == 2

    def test_multi_source_pipeline(self, db_session):
        """测试多数据源数据通过同一管道处理"""
        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        posts = [
            _make_raw_post(DataSource.REDDIT, "r_1", "Reddit 内容"),
            _make_raw_post(DataSource.YOUTUBE, "y_1", "YouTube 内容"),
            _make_raw_post(DataSource.TWITTER, "t_1", "Twitter 内容"),
        ]

        stats = pipeline.process_batch(posts, task_id)
        assert stats.valid == 3

        # 验证各数据源都已存储
        sources = {
            p.source
            for p in db_session.query(RawPostDB).filter(
                RawPostDB.task_id == task_id
            ).all()
        }
        assert sources == {"reddit", "youtube", "twitter"}


# ===== 2. 降级策略自动切换测试 =====


class TestFallbackStrategy:
    """测试降级策略自动切换"""

    @pytest.mark.asyncio
    async def test_reddit_fallback_to_asyncpraw(self):
        """测试 Reddit 采集器各层失败后降级到 Playwright"""
        from backend.app.collectors.reddit_batch_collector import RedditBatchCollector

        collector = RedditBatchCollector()

        # mock 所有上层方案失败，最终降级到 Playwright
        with patch.object(
            collector, "_collect_arctic_shift",
            side_effect=Exception("Arctic Shift 不可用"),
        ), patch.object(
            collector, "_check_pullpush_freshness",
            return_value=True,
        ), patch.object(
            collector, "_collect_pullpush",
            side_effect=Exception("PullPush 不可用"),
        ) as mock_pullpush, patch.object(
            collector, "_collect_reddit_json_enhanced",
            side_effect=Exception("Reddit JSON 不可用"),
        ) as mock_json, patch.object(
            collector, "_collect_playwright",
        ) as mock_pw:
            # 设置 Playwright 返回模拟数据
            async def fake_playwright(*args, **kwargs):
                yield [_make_raw_post(DataSource.REDDIT, "pw_1", "Playwright 数据")]
            mock_pw.side_effect = fake_playwright

            batches = []
            async for batch in collector.collect("test", 10):
                batches.extend(batch)

            # 验证降级链被正确调用
            mock_pullpush.assert_called_once()
            mock_json.assert_called_once()
            mock_pw.assert_called_once()
            assert len(batches) == 1

        await collector.close()

    @pytest.mark.asyncio
    async def test_reddit_fallback_arctic_to_praw_success(self):
        """测试 Reddit 采集器 Arctic Shift 失败后 Reddit JSON Enhanced 成功"""
        from backend.app.collectors.reddit_batch_collector import RedditBatchCollector

        collector = RedditBatchCollector()

        with patch.object(
            collector, "_collect_arctic_shift",
            side_effect=Exception("Arctic Shift 不可用"),
        ), patch.object(
            collector, "_check_pullpush_freshness",
            return_value=True,
        ), patch.object(
            collector, "_collect_pullpush",
            side_effect=Exception("PullPush 不可用"),
        ), patch.object(
            collector, "_collect_reddit_json_enhanced",
        ) as mock_json, patch.object(
            collector, "_collect_playwright",
        ) as mock_pw:
            async def fake_json(*args, **kwargs):
                yield [_make_raw_post(DataSource.REDDIT, "json_1", "Reddit JSON 数据")]
            mock_json.side_effect = fake_json

            async def fake_pw(*args, **kwargs):
                return
                yield  # 使其成为空的异步生成器
            mock_pw.side_effect = fake_pw

            batches = []
            async for batch in collector.collect("test", 10):
                batches.extend(batch)

            assert len(batches) == 1
            assert batches[0].content == "Reddit JSON 数据"

        await collector.close()

    @pytest.mark.asyncio
    async def test_youtube_fallback_to_playwright(self):
        """测试 YouTube 采集器 yt-dlp 失败后降级到 Playwright"""
        from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector

        collector = YouTubeBatchCollector()

        with patch.object(
            collector, "_collect_ytdlp",
            side_effect=Exception("yt-dlp 不可用"),
        ), patch.object(
            collector, "_collect_playwright",
        ) as mock_pw:
            async def fake_pw(*args, **kwargs):
                yield [_make_raw_post(DataSource.YOUTUBE, "yt_pw_1", "Playwright YouTube 数据")]
            mock_pw.side_effect = fake_pw

            batches = []
            async for batch in collector.collect("test", 10):
                batches.extend(batch)

            assert len(batches) == 1

        await collector.close()

    @pytest.mark.asyncio
    async def test_twitter_fallback_chain(self):
        """测试 Twitter 采集器降级链: twscrape → Nitter → Playwright"""
        from unittest.mock import AsyncMock as AM
        from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector

        # 不配置账号，直接跳过 twscrape
        collector = TwitterBatchCollector(batch_delay=0, accounts=[])

        # 模拟 Nitter 提供者失败，使其降级到 Playwright
        mock_nitter = AM()
        mock_nitter.close = AM()

        async def failing_nitter_search(keyword, limit):
            raise RuntimeError("Nitter 不可用")
            yield  # noqa: E501

        mock_nitter.search = failing_nitter_search
        collector._nitter_provider = mock_nitter

        # 模拟 Playwright 提供者
        mock_pw = AM()
        mock_pw.close = AM()

        async def fake_pw_search(keyword, limit):
            yield _make_raw_post(DataSource.TWITTER, "tw_pw_1", "Playwright Twitter 数据")

        mock_pw.search = fake_pw_search
        collector._playwright_provider = mock_pw

        batches = []
        async for batch in collector.collect("test", 10):
            batches.extend(batch)

        assert len(batches) == 1
        await collector.close()

    @pytest.mark.asyncio
    async def test_twitter_twscrape_fallback_to_playwright(self):
        """测试 Twitter 采集器 twscrape 失败后降级到 Playwright"""
        from unittest.mock import AsyncMock as AM
        from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector

        accounts = [{"username": "u", "password": "p", "email": "e", "email_password": "ep"}]
        collector = TwitterBatchCollector(batch_delay=0, accounts=accounts)

        # 模拟 twscrape 失败
        mock_twscrape = AM()
        mock_twscrape.close = AM()

        async def failing_search(*args, **kwargs):
            raise RuntimeError("twscrape 不可用")
            yield  # noqa: E501

        mock_twscrape.search = failing_search
        collector._twscrape_provider = mock_twscrape

        # 模拟 Nitter 失败，使其降级到 Playwright
        mock_nitter = AM()
        mock_nitter.close = AM()

        async def failing_nitter_search(keyword, limit):
            raise RuntimeError("Nitter 不可用")
            yield  # noqa: E501

        mock_nitter.search = failing_nitter_search
        collector._nitter_provider = mock_nitter

        # 模拟 Playwright 成功
        mock_pw = AM()
        mock_pw.close = AM()

        async def fake_pw_search(keyword, limit):
            yield _make_raw_post(DataSource.TWITTER, "pw_1", "Playwright 降级数据")

        mock_pw.search = fake_pw_search
        collector._playwright_provider = mock_pw

        batches = []
        async for batch in collector.collect("test", 10):
            batches.extend(batch)

        assert len(batches) == 1
        assert batches[0].content == "Playwright 降级数据"
        await collector.close()


# ===== 3. 断点续采测试 =====


class TestResumeCollection:
    """测试断点续采功能"""

    @pytest.mark.asyncio
    async def test_resume_task_continues_from_checkpoint(self, db_session):
        """测试续采从上次进度继续"""
        task_id = _create_task_db(db_session, status="processing")

        # 模拟已采集 500 条数据
        task_db = db_session.query(CollectionTaskDB).filter(
            CollectionTaskDB.id == task_id
        ).first()
        task_db.collected_count = 500
        task_db.last_cursor = json.dumps({"reddit": "1700000500"})
        db_session.commit()

        Session = sessionmaker(bind=TEST_ENGINE)

        scheduler = BatchScheduler(
            rate_limit_delay=0,
            db_session_factory=Session,
        )

        # mock 采集器返回新数据
        mock_posts = [
            _make_raw_post(DataSource.REDDIT, f"resume_{i}", f"续采内容 {i}")
            for i in range(10)
        ]

        with patch.object(
            scheduler, "_create_collector",
        ) as mock_create:
            mock_collector = AsyncMock()

            async def fake_gen(*args, **kwargs):
                yield mock_posts
            mock_collector.collect = fake_gen
            mock_collector.close = AsyncMock()
            mock_create.return_value = mock_collector

            result_id = await scheduler.resume_task(
                task_id=task_id,
                keyword="续采测试",
                limit=1000,
                sources=["reddit"],
            )

            assert result_id == task_id

        # 验证进度已更新
        progress = scheduler.get_task_progress(task_id)
        assert progress is not None
        assert progress.total_collected >= 500

    @pytest.mark.asyncio
    async def test_resume_completed_task_skips(self, db_session):
        """测试已完成的任务不需要续采"""
        task_id = _create_task_db(db_session, status="completed")

        task_db = db_session.query(CollectionTaskDB).filter(
            CollectionTaskDB.id == task_id
        ).first()
        task_db.collected_count = 1000
        db_session.commit()

        Session = sessionmaker(bind=TEST_ENGINE)

        scheduler = BatchScheduler(
            rate_limit_delay=0,
            db_session_factory=Session,
        )

        result_id = await scheduler.resume_task(
            task_id=task_id,
            keyword="已完成",
            limit=1000,
            sources=["reddit"],
        )

        assert result_id == task_id


# ===== 4. 调度器多数据源并发测试 =====


class TestSchedulerConcurrency:
    """测试调度器多数据源并发采集"""

    @pytest.mark.asyncio
    async def test_multi_source_concurrent_collection(self):
        """测试多数据源并发采集，单源失败不影响其他"""
        scheduler = BatchScheduler(rate_limit_delay=0)

        reddit_posts = [
            _make_raw_post(DataSource.REDDIT, f"r_{i}", f"Reddit {i}")
            for i in range(5)
        ]
        youtube_posts = [
            _make_raw_post(DataSource.YOUTUBE, f"y_{i}", f"YouTube {i}")
            for i in range(3)
        ]

        def create_mock_collector(source, language):
            mock = AsyncMock()
            if source == "reddit":
                async def reddit_gen(*args, **kwargs):
                    yield reddit_posts
                mock.collect = reddit_gen
            elif source == "youtube":
                async def youtube_gen(*args, **kwargs):
                    yield youtube_posts
                mock.collect = youtube_gen
            elif source == "twitter":
                # Twitter 采集失败
                async def twitter_gen(*args, **kwargs):
                    raise Exception("snscrape 不可用")
                    yield  # 使其成为异步生成器
                mock.collect = twitter_gen
            mock.close = AsyncMock()
            return mock

        with patch.object(scheduler, "_create_collector", side_effect=create_mock_collector):
            progress_updates = []

            def on_progress(tp: TaskProgress):
                progress_updates.append(tp.progress_percent)

            task_id = await scheduler.schedule_task(
                keyword="并发测试",
                limit=10,
                sources=["reddit", "youtube", "twitter"],
                on_progress=on_progress,
            )

            assert task_id is not None
            tp = scheduler.get_task_progress(task_id)
            assert tp is not None
            # 任务应完成（部分成功）
            assert tp.status == "completed"
            # Reddit 和 YouTube 成功
            assert tp.source_progress["reddit"].status == "completed"
            assert tp.source_progress["youtube"].status == "completed"
            # Twitter 失败
            assert tp.source_progress["twitter"].status == "failed"

    @pytest.mark.asyncio
    async def test_all_sources_fail(self):
        """测试所有数据源都失败时任务状态为 failed"""
        scheduler = BatchScheduler(rate_limit_delay=0)

        def create_failing_collector(source, language):
            mock = AsyncMock()

            async def fail_gen(*args, **kwargs):
                raise Exception(f"{source} 不可用")
                yield
            mock.collect = fail_gen
            mock.close = AsyncMock()
            return mock

        with patch.object(scheduler, "_create_collector", side_effect=create_failing_collector):
            task_id = await scheduler.schedule_task(
                keyword="全部失败",
                limit=10,
                sources=["reddit", "youtube"],
            )

            tp = scheduler.get_task_progress(task_id)
            assert tp.status == "failed"


# ===== 5. 完整端到端流程：采集 → 管道 → 存储 =====


class TestEndToEndBatchFlow:
    """测试从采集器到管道到数据库的完整流程"""

    @pytest.mark.asyncio
    async def test_reddit_pullpush_to_db(self, db_session):
        """测试 PullPush 模拟数据经过管道写入数据库"""
        from backend.app.collectors.reddit_batch_collector import RedditBatchCollector

        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        # 模拟 PullPush API 响应
        mock_response = _make_pullpush_response(15)

        collector = RedditBatchCollector()

        with patch.object(collector, "_ensure_session") as mock_session_fn:
            mock_session = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=mock_resp)
            mock_session_fn.return_value = mock_session

            # 第一次返回数据，第二次返回空（结束采集）
            call_count = 0
            original_json = mock_resp.json

            async def json_with_pagination():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_response
                return {"data": []}

            mock_resp.json = json_with_pagination

            total_stats = BatchStats()
            async for batch in collector._collect_pullpush("test", 15):
                stats = pipeline.process_batch(batch, task_id)
                total_stats.total += stats.total
                total_stats.valid += stats.valid

        # 验证数据已写入数据库
        db_count = db_session.query(RawPostDB).filter(
            RawPostDB.task_id == task_id
        ).count()
        assert db_count == total_stats.valid
        assert db_count > 0

        await collector.close()

    def test_snscrape_mock_to_pipeline(self, db_session):
        """测试 twscrape 模拟数据经过管道处理"""
        from unittest.mock import MagicMock
        from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider

        task_id = _create_task_db(db_session)
        pipeline = DataPipeline(db_session)

        # 模拟 twscrape Tweet 对象并解析
        posts = []
        for i in range(10):
            tweet = MagicMock()
            tweet.id = i + 1000
            tweet.rawContent = f"推文内容 {i}，用于集成测试。"
            tweet.user = MagicMock()
            tweet.user.username = f"twitter_user_{i}"
            tweet.date = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
            tweet.likeCount = i * 5
            tweet.replyCount = i * 2
            tweet.retweetCount = i

            post = TwscrapeProvider._parse_tweet(tweet)
            if post:
                posts.append(post)

        stats = pipeline.process_batch(posts, task_id)
        assert stats.valid == 10
        assert stats.discarded == 0

        # 验证数据库
        db_count = db_session.query(RawPostDB).filter(
            RawPostDB.task_id == task_id
        ).count()
        assert db_count == 10
