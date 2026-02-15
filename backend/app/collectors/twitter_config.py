"""
X(Twitter) 采集配置管理模块

提供 twscrape 账号池管理和 Playwright Cookie 管理功能。

- AccountPoolManager: 解析和验证 twscrape 账号配置
- CookieManager: 加载和验证 Playwright 登录态 Cookie

需求: 2.1, 2.4, 3.2, 3.4, 7.1, 7.2
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AccountPoolManager:
    """twscrape 账号池管理器

    负责从环境变量解析账号配置，并验证配置完整性。
    """

    # 账号配置必须包含的字段
    REQUIRED_FIELDS = ("username", "password", "email", "email_password")

    @staticmethod
    def parse_accounts_from_env(env_value: str) -> list[dict]:
        """从环境变量解析账号配置

        格式: username:password:email:email_password;username2:password2:email2:email_password2

        Args:
            env_value: 环境变量值

        Returns:
            解析后的账号字典列表
        """
        if not env_value or not env_value.strip():
            return []

        accounts = []
        for entry in env_value.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) != 4:
                logger.warning("账号配置格式错误，跳过: %s", entry[:20])
                continue
            accounts.append({
                "username": parts[0].strip(),
                "password": parts[1].strip(),
                "email": parts[2].strip(),
                "email_password": parts[3].strip(),
            })

        return accounts

    @staticmethod
    def validate_account_config(account: dict) -> bool:
        """验证单个账号配置是否完整

        检查 username、password、email、email_password 四个字段均存在且非空。

        Args:
            account: 账号配置字典

        Returns:
            配置是否有效
        """
        for key in AccountPoolManager.REQUIRED_FIELDS:
            value = account.get(key)
            if not value or not isinstance(value, str) or not value.strip():
                return False
        return True


class CookieManager:
    """X 平台登录态 Cookie 管理器

    负责从 JSON 文件加载 Cookie，并验证是否包含必要的认证字段（auth_token、ct0）。

    需求: 3.2, 3.4, 7.2
    """

    # Cookie 中必须包含的认证字段名
    REQUIRED_COOKIE_NAMES = ("auth_token", "ct0")

    def __init__(self, cookies_path: Optional[str] = None) -> None:
        """初始化 Cookie 管理器

        Args:
            cookies_path: Cookie JSON 文件路径，为 None 时 load_cookies 返回空列表
        """
        self._cookies_path = cookies_path

    def load_cookies(self) -> list[dict]:
        """从文件加载 Cookie

        Returns:
            Cookie 列表（Playwright 格式）

        Raises:
            FileNotFoundError: Cookie 文件不存在
            json.JSONDecodeError: Cookie 文件格式错误
        """
        if not self._cookies_path:
            logger.warning("未配置 Cookie 文件路径")
            return []

        try:
            with open(self._cookies_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
        except FileNotFoundError:
            logger.warning("Cookie 文件不存在: %s", self._cookies_path)
            return []
        except json.JSONDecodeError as e:
            logger.error("Cookie 文件格式错误: %s", e)
            return []

        if not isinstance(cookies, list):
            logger.warning("Cookie 文件内容不是列表格式")
            return []

        return cookies

    @staticmethod
    def validate_cookies(cookies: list[dict]) -> bool:
        """验证 Cookie 是否包含必要的认证字段

        检查列表中是否同时包含 name 为 "auth_token" 和 "ct0" 的条目。

        Args:
            cookies: Cookie 列表

        Returns:
            Cookie 是否有效
        """
        if not cookies:
            return False

        cookie_names = {
            c.get("name") for c in cookies if isinstance(c, dict)
        }
        return all(
            name in cookie_names
            for name in CookieManager.REQUIRED_COOKIE_NAMES
        )
