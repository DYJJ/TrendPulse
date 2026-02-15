"""
twscrape 采集提供者

通过 twscrape 库与 X 平台交互，使用账号池执行搜索和数据提取。
支持按关键词、时间范围、语言过滤，逐条 yield RawPost。

需求: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import twscrape

from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)


class TwscrapeProvider:
    """twscrape 采集提供者

    通过 twscrape 账号池模拟 Twitter 内部 API 请求，
    无需官方 API 付费权限即可采集推文数据。
    """

    def __init__(self, accounts: list[dict], proxy: Optional[str] = None) -> None:
        """初始化 twscrape 客户端和账号池

        Args:
            accounts: 账号列表，每个元素包含 username, password, email, email_password
            proxy: HTTP/SOCKS5 代理地址，如 http://127.0.0.1:7890
        """
        self._accounts = accounts
        self._proxy = proxy
        self._pool = twscrape.AccountsPool()
        self._api = twscrape.API(pool=self._pool)
        self._initialized = False

    async def initialize(self) -> None:
        """初始化账号池，添加并登录所有账号

        会逐个添加账号并尝试登录，记录每个账号的登录结果。
        如果所有账号均登录失败，抛出 RuntimeError 并附带诊断信息。

        重试安全：先删除旧账号再重新添加，避免 'already exists' 和
        error_msg 导致 login_all 跳过已失败账号的问题。
        """
        if not self._accounts:
            raise RuntimeError("twscrape 账号列表为空，请检查 TWITTER_ACCOUNTS 环境变量配置")

        # 收集所有用户名，先删除旧记录再重新添加，确保重试时状态干净
        usernames = [acc.get("username", "") for acc in self._accounts if acc.get("username")]
        try:
            await self._pool.delete_accounts(usernames)
        except Exception:
            pass  # 首次运行时账号不存在，忽略

        for acc in self._accounts:
            username = acc.get("username", "unknown")
            try:
                await self._pool.add_account(
                    username=acc["username"],
                    password=acc["password"],
                    email=acc["email"],
                    email_password=acc["email_password"],
                    proxy=self._proxy,
                )
                logger.info("twscrape 账号已添加: %s", username)
            except Exception as e:
                logger.error("twscrape 添加账号失败 '%s': %s", username, e)

        # 尝试登录所有账号
        try:
            await self._pool.login_all()
        except Exception as e:
            logger.error("twscrape login_all 异常: %s", e)

        # 检查登录结果（accounts_info 返回 TypedDict 列表）
        try:
            accounts_info = await self._pool.accounts_info()
            active_count = 0
            for acc_info in accounts_info:
                uname = acc_info.get("username", "unknown")
                active = acc_info.get("active", False)
                error_msg = acc_info.get("error_msg")
                if active:
                    active_count += 1
                    logger.info("twscrape 账号登录成功: %s", uname)
                else:
                    logger.warning(
                        "twscrape 账号登录失败: %s, 错误: %s",
                        uname,
                        error_msg or "未知原因（可能需要手动在浏览器中登录一次以完成验证）",
                    )

            if active_count == 0:
                raise RuntimeError(
                    "twscrape 所有账号均登录失败。常见原因:\n"
                    "  1. X 账号需要先在浏览器中手动登录一次完成安全验证\n"
                    "  2. 账号开启了两步验证(2FA)，twscrape 不支持\n"
                    "  3. 账号被锁定或需要手机验证\n"
                    "  4. 密码中包含特殊字符导致解析错误\n"
                    "  请检查以上情况后重试。"
                )

            logger.info(
                "twscrape 账号池初始化完成，%d/%d 个账号可用",
                active_count,
                len(self._accounts),
            )
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("twscrape 无法获取账号状态信息: %s，继续尝试使用", e)

        self._initialized = True

    async def search(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        language: str = "en",
    ) -> AsyncGenerator[RawPost, None]:
        """搜索推文，逐条 yield RawPost

        Args:
            keyword: 搜索关键词
            limit: 采集上限
            start_date: 起始日期
            end_date: 结束日期
            language: 语言代码
        """
        if not self._initialized:
            await self.initialize()

        query = self._build_query(keyword, start_date, end_date, language)
        logger.info("twscrape 搜索查询: %s, 上限: %d", query, limit)

        count = 0
        async for tweet in self._api.search(query, limit=limit):
            post = self._parse_tweet(tweet)
            if post is not None:
                yield post
                count += 1

        logger.info("twscrape 搜索完成，共获取 %d 条推文", count)

    @staticmethod
    def _build_query(
        keyword: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        language: str = "en",
    ) -> str:
        """构建 twscrape 搜索查询字符串

        Args:
            keyword: 搜索关键词
            start_date: 起始日期
            end_date: 结束日期
            language: 语言代码

        Returns:
            搜索查询字符串
        """
        query_parts = [keyword]

        if start_date:
            query_parts.append(f"since:{start_date.strftime('%Y-%m-%d')}")
        if end_date:
            query_parts.append(f"until:{end_date.strftime('%Y-%m-%d')}")
        if language:
            query_parts.append(f"lang:{language}")

        return " ".join(query_parts)

    @staticmethod
    def _parse_tweet(tweet: twscrape.models.Tweet) -> Optional[RawPost]:
        """将 twscrape Tweet 对象转换为 RawPost

        Args:
            tweet: twscrape 返回的 Tweet 对象

        Returns:
            转换后的 RawPost，数据无效时返回 None
        """
        try:
            external_id = str(tweet.id)
            content = tweet.rawContent or ""

            # 过滤空内容
            if not content or not content.strip():
                logger.warning("推文内容为空，跳过: id=%s", external_id)
                return None

            if not external_id:
                logger.warning("推文缺少 ID，跳过")
                return None

            # 作者信息
            author = tweet.user.username if tweet.user else "unknown"

            # 构建原文链接
            url = f"https://x.com/{author}/status/{external_id}"

            # 确保时间戳为 UTC
            timestamp = tweet.date
            if timestamp and timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            elif timestamp is None:
                timestamp = datetime.now(timezone.utc)

            return RawPost(
                id=str(uuid.uuid4()),
                source=DataSource.TWITTER,
                external_id=external_id,
                title=None,
                content=content,
                author=author,
                url=url,
                timestamp=timestamp,
                likes=int(tweet.likeCount or 0),
                comments=int(tweet.replyCount or 0),
                shares=int(tweet.retweetCount or 0),
            )
        except Exception as e:
            logger.warning("解析 twscrape 推文失败: %s", e)
            return None

    async def close(self) -> None:
        """释放资源"""
        # twscrape API 无需显式关闭，但保留接口以便统一管理
        logger.info("twscrape 提供者已关闭")
