"""
搜索引擎间接采集提供者

依次尝试 DuckDuckGo、Google、Bing 搜索 site:x.com，
从搜索结果中提取 Twitter 用户名和推文 ID。
通过 SyndicationProvider 的 timeline-profile 端点获取用户推文列表，
再通过 tweet-result 端点补全推文详情。

使用 curl_cffi 模拟浏览器 TLS 指纹，避免被搜索引擎反爬拦截。
"""

import asyncio
import logging
import re
from typing import AsyncGenerator, Callable, List, Optional, Set, Tuple
from urllib.parse import unquote

from curl_cffi.requests import AsyncSession

from backend.app.collectors.zero_cost.constants import (
    BATCH_SIZE,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    SEARCH_DELAY_MIN,
    SEARCH_DELAY_MAX,
)
from backend.app.collectors.zero_cost.models import SearchResult
from backend.app.collectors.zero_cost.syndication_provider import SyndicationProvider
from backend.app.collectors.zero_cost.utils import (
    build_search_query,
    extract_tweet_id,
    random_delay,
    random_user_agent,
)
from backend.app.models.data_models import RawPost

logger = logging.getLogger(__name__)

# 验证码/限流检测关键词（小写匹配）
_CAPTCHA_KEYWORDS = [
    "captcha", "recaptcha", "verify you are human",
    "unusual traffic", "automated queries",
    "are you a robot", "bot detection",
]

# 限流状态码
_RATE_LIMIT_CODES = {429, 403, 503}


# 从 x.com URL 中提取用户名的正则（匹配 x.com/username 但排除 /status/ 等路径）
_XCOM_USERNAME_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})(?:/?\s|/?\"|$|/?\&)'
)

# 从 DuckDuckGo uddg 参数中提取 URL
_DDG_UDDG_PATTERN = re.compile(r'uddg=([^&"]+)')

# 匹配推文 URL（含 /status/）
_TWEET_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)'
)

# 排除的 x.com 路径（非用户页面）
_EXCLUDED_PATHS = {
    "home", "explore", "search", "notifications", "messages",
    "settings", "i", "login", "signup", "tos", "privacy",
    "help", "about", "jobs", "hashtag", "compose",
}


class SearchEngineProvider:
    """搜索引擎间接采集提供者

    依次尝试 DuckDuckGo、Google、Bing 搜索 site:x.com，
    从结果中提取 Twitter 用户名和推文 ID。
    通过 SyndicationProvider 的 timeline-profile 获取用户推文列表，
    再通过 tweet-result 补全推文详情。

    使用 curl_cffi 模拟浏览器指纹避免反爬。
    """

    def __init__(
        self,
        syndication: Optional[SyndicationProvider] = None,
        proxy: Optional[str] = None,
    ) -> None:
        """初始化 SearchEngineProvider

        Args:
            syndication: SyndicationProvider 实例，用于获取用户时间线和推文详情
            proxy: HTTP 代理地址（可选），如 http://127.0.0.1:7890
        """
        self._syndication = syndication or SyndicationProvider(proxy=proxy)
        self._proxy = proxy
        # 搜索引擎列表及对应方法，按优先级排序
        self._engines: List[Tuple[str, Callable]] = [
            ("DuckDuckGo", self._search_duckduckgo),
            ("Google", self._search_google),
            ("Bing", self._search_bing),
        ]

    @staticmethod
    def _detect_captcha(html: str) -> bool:
        """检测 HTML 响应中是否包含验证码/反爬标记

        Args:
            html: 响应 HTML 文本

        Returns:
            包含验证码标记返回 True
        """
        html_lower = html.lower()
        return any(kw in html_lower for kw in _CAPTCHA_KEYWORDS)

    @staticmethod
    def _extract_usernames_and_tweet_ids(html: str) -> Tuple[List[str], List[str]]:
        """从 HTML 中提取 Twitter 用户名和推文 ID

        同时提取直接的推文链接（/status/）和用户主页链接。

        Args:
            html: 搜索引擎返回的 HTML

        Returns:
            (用户名列表, 推文ID列表) 元组，均已去重
        """
        usernames: List[str] = []
        tweet_ids: List[str] = []
        seen_usernames: set = set()
        seen_tweet_ids: set = set()

        # 先提取推文链接（含 /status/）
        for match in _TWEET_URL_PATTERN.finditer(html):
            username = match.group(1).lower()
            tweet_id = match.group(2)
            if username not in _EXCLUDED_PATHS:
                if tweet_id not in seen_tweet_ids:
                    tweet_ids.append(tweet_id)
                    seen_tweet_ids.add(tweet_id)
                if username not in seen_usernames:
                    usernames.append(username)
                    seen_usernames.add(username)

        # 再提取用户主页链接
        for match in _XCOM_USERNAME_PATTERN.finditer(html):
            username = match.group(1).lower()
            if username not in _EXCLUDED_PATHS and username not in seen_usernames:
                usernames.append(username)
                seen_usernames.add(username)

        return usernames, tweet_ids

    @staticmethod
    def _extract_from_ddg_uddg(html: str) -> Tuple[List[str], List[str]]:
        """从 DuckDuckGo 的 uddg 重定向参数中提取用户名和推文 ID

        DuckDuckGo HTML 搜索结果中的链接通过 uddg 参数编码。

        Args:
            html: DuckDuckGo 返回的 HTML

        Returns:
            (用户名列表, 推文ID列表) 元组，均已去重
        """
        usernames: List[str] = []
        tweet_ids: List[str] = []
        seen_usernames: set = set()
        seen_tweet_ids: set = set()

        for match in _DDG_UDDG_PATTERN.finditer(html):
            decoded_url = unquote(match.group(1))

            # 检查是否是推文链接
            tweet_match = _TWEET_URL_PATTERN.search(decoded_url)
            if tweet_match:
                username = tweet_match.group(1).lower()
                tweet_id = tweet_match.group(2)
                if username not in _EXCLUDED_PATHS:
                    if tweet_id not in seen_tweet_ids:
                        tweet_ids.append(tweet_id)
                        seen_tweet_ids.add(tweet_id)
                    if username not in seen_usernames:
                        usernames.append(username)
                        seen_usernames.add(username)
                continue

            # 检查是否是用户主页链接
            user_match = _XCOM_USERNAME_PATTERN.search(decoded_url + " ")
            if user_match:
                username = user_match.group(1).lower()
                if username not in _EXCLUDED_PATHS and username not in seen_usernames:
                    usernames.append(username)
                    seen_usernames.add(username)

        return usernames, tweet_ids


    async def _fetch_with_curl_cffi(self, url: str, params: Optional[dict] = None) -> Tuple[int, str]:
        """使用 curl_cffi 发送请求，模拟 Chrome TLS 指纹

        Args:
            url: 请求 URL
            params: 查询参数

        Returns:
            (状态码, HTML 文本) 元组
        """
        await random_delay(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX)
        async with AsyncSession(impersonate="chrome") as session:
            resp = await session.get(
                url,
                params=params,
                proxy=self._proxy,
                timeout=20,
            )
            return resp.status_code, resp.text

    # ---- DuckDuckGo HTML 搜索 ----

    async def _search_duckduckgo(
        self, query: str, limit: int
    ) -> Tuple[List[str], List[str]]:
        """通过 DuckDuckGo HTML 搜索获取 Twitter 用户名和推文 ID

        Args:
            query: 搜索查询字符串（已包含 site:x.com）
            limit: 期望获取的结果数量上限

        Returns:
            (用户名列表, 推文ID列表) 元组

        Raises:
            RuntimeError: 遇到验证码或限流
        """
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}

        for attempt in range(MAX_RETRIES):
            try:
                status, html = await self._fetch_with_curl_cffi(url, params)

                if status in _RATE_LIMIT_CODES:
                    raise RuntimeError(f"DuckDuckGo 返回限流状态码 {status}")

                if self._detect_captcha(html):
                    raise RuntimeError("DuckDuckGo 返回验证码")

                # 从 uddg 参数中提取（DuckDuckGo 特有格式）
                usernames, tweet_ids = self._extract_from_ddg_uddg(html)
                # 也从 HTML 正文中提取
                u2, t2 = self._extract_usernames_and_tweet_ids(html)
                # 合并去重
                seen_u = set(usernames)
                for u in u2:
                    if u not in seen_u:
                        usernames.append(u)
                        seen_u.add(u)
                seen_t = set(tweet_ids)
                for t in t2:
                    if t not in seen_t:
                        tweet_ids.append(t)
                        seen_t.add(t)

                logger.info(
                    "DuckDuckGo 搜索完成: 获取 %d 个用户名, %d 个推文 ID",
                    len(usernames), len(tweet_ids),
                )
                return usernames, tweet_ids

            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("DuckDuckGo 搜索异常 (第 %d 次): %s", attempt + 1, e)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(f"DuckDuckGo 搜索失败: {e}")

        return [], []

    # ---- Google HTML 搜索 ----

    async def _search_google(
        self, query: str, limit: int
    ) -> Tuple[List[str], List[str]]:
        """通过 Google HTML 搜索获取 Twitter 用户名和推文 ID

        Args:
            query: 搜索查询字符串
            limit: 期望获取的结果数量上限

        Returns:
            (用户名列表, 推文ID列表) 元组

        Raises:
            RuntimeError: 遇到验证码或限流
        """
        url = "https://www.google.com/search"
        params = {"q": query, "num": str(min(limit, 100))}

        for attempt in range(MAX_RETRIES):
            try:
                status, html = await self._fetch_with_curl_cffi(url, params)

                if status in _RATE_LIMIT_CODES:
                    raise RuntimeError(f"Google 返回限流状态码 {status}")

                if self._detect_captcha(html):
                    raise RuntimeError("Google 返回验证码")

                usernames, tweet_ids = self._extract_usernames_and_tweet_ids(html)
                logger.info(
                    "Google 搜索完成: 获取 %d 个用户名, %d 个推文 ID",
                    len(usernames), len(tweet_ids),
                )
                return usernames, tweet_ids

            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("Google 搜索异常 (第 %d 次): %s", attempt + 1, e)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(f"Google 搜索失败: {e}")

        return [], []

    # ---- Bing HTML 搜索 ----

    async def _search_bing(
        self, query: str, limit: int
    ) -> Tuple[List[str], List[str]]:
        """通过 Bing HTML 搜索获取 Twitter 用户名和推文 ID

        Args:
            query: 搜索查询字符串
            limit: 期望获取的结果数量上限

        Returns:
            (用户名列表, 推文ID列表) 元组

        Raises:
            RuntimeError: 遇到验证码或限流
        """
        url = "https://www.bing.com/search"
        params = {"q": query, "count": str(min(limit, 50))}

        for attempt in range(MAX_RETRIES):
            try:
                status, html = await self._fetch_with_curl_cffi(url, params)

                if status in _RATE_LIMIT_CODES:
                    raise RuntimeError(f"Bing 返回限流状态码 {status}")

                if self._detect_captcha(html):
                    raise RuntimeError("Bing 返回验证码")

                usernames, tweet_ids = self._extract_usernames_and_tweet_ids(html)
                logger.info(
                    "Bing 搜索完成: 获取 %d 个用户名, %d 个推文 ID",
                    len(usernames), len(tweet_ids),
                )
                return usernames, tweet_ids

            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("Bing 搜索异常 (第 %d 次): %s", attempt + 1, e)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise RuntimeError(f"Bing 搜索失败: {e}")

        return [], []


    async def collect(
        self,
        keyword: str,
        limit: int,
        seen_ids: Optional[Set[str]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        max_snowball_users: int = 500,
        max_snowball_depth: int = 10,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过搜索引擎采集推文数据，支持雪球式用户发现

        采集策略：
        1. 搜索引擎提取种子用户名和推文 ID
        2. 通过 timeline-profile 获取种子用户推文 ID 列表
        3. 通过 tweet-result 补全推文详情，同时提取 @mentions 中的新用户名
        4. 对新发现的用户重复步骤 2-3（雪球扩展）
        5. 直到达到 limit 配额或无新用户可发现
        6. 每 BATCH_SIZE 条 yield 一批

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 已采集的推文 ID 集合（用于去重）
            on_progress: 进度回调函数，参数为已采集条数
            max_snowball_users: 雪球扩展最大用户数（防止无限扩展）
            max_snowball_depth: 雪球扩展最大轮次

        Yields:
            List[RawPost]: 每次 yield 一批数据（最多 BATCH_SIZE 条）

        Raises:
            RuntimeError: 所有搜索引擎均不可用
        """
        if seen_ids is None:
            seen_ids = set()

        query = build_search_query(keyword)
        seed_usernames: List[str] = []
        seed_tweet_ids: List[str] = []
        engine_errors: List[str] = []

        # === 第一阶段：搜索引擎获取种子用户 ===
        for engine_name, search_func in self._engines:
            try:
                logger.info("尝试通过 %s 搜索: %s", engine_name, query)
                usernames, tweet_ids = await search_func(query, limit)
                if usernames or tweet_ids:
                    seed_usernames.extend(usernames)
                    seed_tweet_ids.extend(tweet_ids)
                    logger.info(
                        "%s 搜索成功: %d 个用户名, %d 个推文 ID",
                        engine_name, len(usernames), len(tweet_ids),
                    )
                    break
                else:
                    msg = f"{engine_name} 未返回任何结果"
                    logger.warning(msg)
                    engine_errors.append(msg)
            except RuntimeError as e:
                msg = f"{engine_name}: {e}"
                logger.warning("搜索引擎降级 - %s", msg)
                engine_errors.append(msg)
                continue
            except Exception as e:
                msg = f"{engine_name}: 未知错误 {e}"
                logger.error("搜索引擎异常 - %s", msg)
                engine_errors.append(msg)
                continue

        if not seed_usernames and not seed_tweet_ids:
            # 搜索引擎全部失败，尝试把关键词本身当作用户名
            logger.info(
                "搜索引擎均未返回结果，尝试将关键词 '%s' 作为用户名查询 timeline-profile",
                keyword,
            )
            timeline_ids = await self._syndication.fetch_user_timeline(keyword)
            if timeline_ids:
                seed_usernames.append(keyword)
                seed_tweet_ids.extend(timeline_ids)
                logger.info(
                    "通过 timeline-profile 直接获取到 %d 个推文 ID",
                    len(timeline_ids),
                )
            else:
                error_detail = "; ".join(engine_errors)
                raise RuntimeError(f"所有搜索引擎均不可用: {error_detail}")

        # === 第二阶段：雪球式用户发现与采集 ===
        visited_users: Set[str] = set()  # 已访问过 timeline 的用户
        pending_users: List[str] = []    # 待访问的用户队列
        total_yielded = 0
        batch_buffer: List[RawPost] = []

        # 初始化待访问队列（种子用户）
        for u in seed_usernames:
            u_lower = u.lower()
            if u_lower not in visited_users:
                pending_users.append(u_lower)
                visited_users.add(u_lower)

        # 收集种子推文 ID（来自搜索引擎直接提取的）
        all_new_ids: List[str] = []
        seen_new: Set[str] = set()
        for tid in seed_tweet_ids:
            if tid not in seen_ids and tid not in seen_new:
                all_new_ids.append(tid)
                seen_new.add(tid)

        snowball_round = 0

        while snowball_round < max_snowball_depth and total_yielded < limit:
            snowball_round += 1

            # 获取待访问用户的时间线推文 ID
            # 按需获取：当已有足够的推文 ID 时，停止获取更多用户时间线
            if pending_users:
                users_this_round = pending_users[:]
                pending_users.clear()

                remaining_quota = limit - total_yielded
                # 计算本轮需要获取时间线的用户数（按需，不贪心）
                users_to_fetch: List[str] = []
                users_deferred: List[str] = []
                for username in users_this_round:
                    if len(all_new_ids) >= remaining_quota and users_to_fetch:
                        # 已有足够的推文 ID，剩余用户放回队列
                        users_deferred.append(username)
                    else:
                        users_to_fetch.append(username)

                # 将未访问的用户放回队列
                for u in users_deferred:
                    if u not in visited_users:
                        pending_users.append(u)

                # 并发获取多个用户的时间线
                if users_to_fetch:
                    timeline_tasks = [
                        self._syndication.fetch_user_timeline(u)
                        for u in users_to_fetch
                    ]
                    timeline_results = await asyncio.gather(
                        *timeline_tasks, return_exceptions=True
                    )
                    for result in timeline_results:
                        if isinstance(result, Exception):
                            continue
                        for tid in result:
                            if tid not in seen_ids and tid not in seen_new:
                                all_new_ids.append(tid)
                                seen_new.add(tid)

            if not all_new_ids:
                logger.info("雪球第 %d 轮: 无新推文 ID，停止扩展", snowball_round)
                break

            # 截取本轮要处理的推文 ID（不超过剩余配额）
            remaining = limit - total_yielded
            batch_ids = all_new_ids[:remaining]
            all_new_ids = all_new_ids[remaining:]

            # 标记为已见
            for tid in batch_ids:
                seen_ids.add(tid)

            logger.info(
                "雪球第 %d 轮: 处理 %d 个推文 ID，已访问 %d 个用户",
                snowball_round, len(batch_ids), len(visited_users),
            )

            # 批量获取推文详情，同时提取 mentions
            posts, mentioned_users = await self._syndication.fetch_tweets_batch_with_mentions(
                batch_ids
            )

            if not posts:
                logger.warning("雪球第 %d 轮: Syndication 未能补全任何推文", snowball_round)
                if not all_new_ids and not pending_users:
                    break
                continue

            # 将新发现的用户加入待访问队列
            new_users_found = 0
            for u in mentioned_users:
                if (u not in visited_users
                        and len(visited_users) < max_snowball_users):
                    pending_users.append(u)
                    visited_users.add(u)
                    new_users_found += 1

            if new_users_found > 0:
                logger.info(
                    "雪球第 %d 轮: 从推文中发现 %d 个新用户，待访问队列 %d 个",
                    snowball_round, new_users_found, len(pending_users),
                )

            # 将获取到的推文加入缓冲区并分批 yield
            for post in posts:
                batch_buffer.append(post)
                if len(batch_buffer) >= BATCH_SIZE:
                    yield batch_buffer[:BATCH_SIZE]
                    total_yielded += BATCH_SIZE
                    batch_buffer = batch_buffer[BATCH_SIZE:]
                    if on_progress:
                        on_progress(total_yielded)
                    logger.info("SearchEngine 采集进度: %d / %d 条", total_yielded, limit)

            # 如果没有更多待处理的 ID 且没有待访问用户，停止
            if not all_new_ids and not pending_users:
                logger.info("雪球第 %d 轮: 无更多用户可扩展，停止", snowball_round)
                break

        # yield 剩余缓冲区
        if batch_buffer:
            yield batch_buffer
            total_yielded += len(batch_buffer)
            if on_progress:
                on_progress(total_yielded)

        logger.info(
            "SearchEngine 雪球采集完成: 共 %d 条，访问 %d 个用户，%d 轮扩展",
            total_yielded, len(visited_users), snowball_round,
        )


    async def close(self) -> None:
        """释放资源

        curl_cffi 的 AsyncSession 在 with 块中自动管理，
        此处仅作为接口兼容保留。
        """
        pass
