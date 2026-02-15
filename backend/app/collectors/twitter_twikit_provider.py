"""
Twikit 提供者 — 免费 Twitter 数据采集

使用 twikit 库（无需 API key）通过 Twitter 内部 API 采集推文。
支持搜索、翻页（无限游标分页），适合大规模数据采集。
需要一个 Twitter 账号的用户名/密码/邮箱进行登录。

登录态通过 cookies.json 文件持久化，避免频繁登录触发风控。
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 每页推文数量（twikit 内部默认约 20 条/页）
# 翻页间延迟（秒），避免触发限流
PAGE_DELAY = 2.0
# 连续空页停止阈值
MAX_EMPTY_PAGES = 3
# 登录重试次数
LOGIN_MAX_RETRIES = 2
# Cookie 文件路径
TWIKIT_COOKIES_FILE = "twikit_cookies.json"


class TwikitProvider:
    """Twikit 推文采集提供者

    使用 twikit 库通过 Twitter 内部 API 采集推文，无需官方 API key。
    支持搜索推文并通过游标实现无限翻页。

    使用前需要在 .env 中配置：
    - TWIKIT_USERNAME: Twitter 用户名
    - TWIKIT_EMAIL: Twitter 邮箱
    - TWIKIT_PASSWORD: Twitter 密码
    """

    def __init__(self, proxy: Optional[str] = None) -> None:
        """初始化 Twikit 提供者

        Args:
            proxy: HTTP 代理地址（如 http://127.0.0.1:7890）
        """
        self._proxy = proxy
        self._client = None
        self._logged_in = False

    async def _ensure_client(self) -> None:
        """确保 twikit 客户端已初始化并登录"""
        if self._client is not None and self._logged_in:
            return

        try:
            from twikit import Client
        except ImportError:
            raise RuntimeError("twikit 未安装，请运行: pip install twikit")

        # 从环境变量读取账号信息
        username = os.environ.get("TWIKIT_USERNAME", "")
        email = os.environ.get("TWIKIT_EMAIL", "")
        password = os.environ.get("TWIKIT_PASSWORD", "")

        if not username or not password:
            raise RuntimeError(
                "twikit 需要 Twitter 账号，请在 .env 中配置 "
                "TWIKIT_USERNAME、TWIKIT_EMAIL、TWIKIT_PASSWORD"
            )

        # 初始化客户端
        proxy_url = self._proxy if self._proxy else None
        self._client = Client("en-US", proxy=proxy_url)

        # 尝试从 Cookie 文件恢复登录态
        cookies_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            TWIKIT_COOKIES_FILE,
        )

        try:
            if os.path.exists(cookies_path):
                self._client.load_cookies(cookies_path)
                self._logged_in = True
                logger.info("twikit: 从 Cookie 文件恢复登录态")
                return
        except Exception as e:
            logger.warning("twikit: Cookie 文件加载失败: %s，尝试重新登录", e)

        # Cookie 不可用，执行登录
        for attempt in range(LOGIN_MAX_RETRIES):
            try:
                await self._client.login(
                    auth_info_1=username,
                    auth_info_2=email,
                    password=password,
                )
                # 保存 Cookie 以便下次复用
                self._client.save_cookies(cookies_path)
                self._logged_in = True
                logger.info("twikit: 登录成功，Cookie 已保存")
                return
            except Exception as e:
                err_str = str(e)
                # 检测 Cloudflare 拦截，快速失败不再重试
                if "403" in err_str or "Cloudflare" in err_str or "blocked" in err_str.lower():
                    # 只打印简短摘要，不打印完整 HTML
                    logger.warning(
                        "twikit: 登录被 Cloudflare 拦截 (403)，IP 可能被封禁，跳过后续重试"
                    )
                    raise RuntimeError(
                        "twikit: 登录被 Cloudflare 拦截 (403)，请更换代理 IP 或稍后重试"
                    )
                # 非 Cloudflare 错误，正常重试并截断日志
                short_err = err_str[:200] + "..." if len(err_str) > 200 else err_str
                logger.warning(
                    "twikit: 登录失败（第 %d/%d 次）: %s",
                    attempt + 1, LOGIN_MAX_RETRIES, short_err,
                )
                if attempt < LOGIN_MAX_RETRIES - 1:
                    await asyncio.sleep(3.0)

        raise RuntimeError("twikit: 登录失败，请检查账号配置")

    async def search(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        language: str = "en",
    ) -> AsyncGenerator[RawPost, None]:
        """搜索推文，支持无限翻页

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            language: 语言代码

        Yields:
            RawPost: 解析后的推文对象
        """
        await self._ensure_client()

        # 构建搜索查询（支持 Twitter 高级搜索语法）
        query = keyword
        if start_date:
            query += f" since:{start_date.strftime('%Y-%m-%d')}"
        if end_date:
            query += f" until:{end_date.strftime('%Y-%m-%d')}"

        total = 0
        empty_pages = 0
        tweets = None

        try:
            # 首次搜索
            tweets = await self._client.search_tweet(
                query, "Latest", count=40
            )

            while total < limit:
                if not tweets:
                    empty_pages += 1
                    if empty_pages >= MAX_EMPTY_PAGES:
                        logger.info(
                            "twikit: 连续 %d 页无数据，停止翻页，已采集 %d 条",
                            MAX_EMPTY_PAGES, total,
                        )
                        break
                    await asyncio.sleep(PAGE_DELAY)
                    try:
                        tweets = await tweets.next()
                    except Exception:
                        break
                    continue

                empty_pages = 0

                for tweet in tweets:
                    if total >= limit:
                        break

                    post = self._parse_tweet(tweet)
                    if post is not None:
                        total += 1
                        yield post

                # 翻页
                await asyncio.sleep(PAGE_DELAY)
                try:
                    tweets = await tweets.next()
                except Exception as e:
                    logger.info("twikit: 翻页结束: %s，已采集 %d 条", e, total)
                    break

        except Exception as e:
            logger.error("twikit: 搜索异常: %s，已采集 %d 条", e, total)

        logger.info("twikit: 搜索完成，共采集 %d 条", total)

    @staticmethod
    def _parse_tweet(tweet) -> Optional[RawPost]:
        """解析 twikit Tweet 对象为 RawPost

        Args:
            tweet: twikit Tweet 对象

        Returns:
            RawPost: 解析后的帖子对象，解析失败返回 None
        """
        try:
            tweet_id = str(tweet.id)
            text = tweet.text or ""
            if not text.strip():
                return None

            # 解析用户信息
            author = "unknown"
            if hasattr(tweet, "user") and tweet.user:
                author = tweet.user.screen_name or tweet.user.name or "unknown"

            # 解析时间
            timestamp = datetime.now(timezone.utc)
            if hasattr(tweet, "created_at") and tweet.created_at:
                try:
                    # twikit 返回的时间格式: "Wed Oct 10 20:19:24 +0000 2018"
                    timestamp = datetime.strptime(
                        tweet.created_at, "%a %b %d %H:%M:%S %z %Y"
                    )
                except (ValueError, TypeError):
                    pass
            elif hasattr(tweet, "created_at_datetime") and tweet.created_at_datetime:
                timestamp = tweet.created_at_datetime

            # 解析互动数据
            likes = 0
            if hasattr(tweet, "favorite_count"):
                likes = tweet.favorite_count or 0

            comments = 0
            if hasattr(tweet, "reply_count"):
                comments = tweet.reply_count or 0

            shares = 0
            if hasattr(tweet, "retweet_count"):
                shares = tweet.retweet_count or 0

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.TWITTER,
                external_id=tweet_id,
                title=None,
                content=text,
                author=author,
                url=f"https://x.com/{author}/status/{tweet_id}",
                timestamp=timestamp,
                likes=int(likes) if likes else 0,
                comments=int(comments) if comments else 0,
                shares=int(shares) if shares else 0,
            )
        except Exception as e:
            logger.warning("twikit: 解析推文失败: %s", e)
            return None

    async def close(self) -> None:
        """释放资源"""
        self._client = None
        self._logged_in = False
        logger.info("TwikitProvider 已关闭")
