"""
LLM API客户端模块

提供统一的LLM API调用接口，支持OpenAI和Anthropic两种API格式。
所有AI分析组件通过此客户端与LLM交互。
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp

class LLMAuthenticationError(RuntimeError):
    """LLM API认证失败异常（401/403）

    当API密钥无效或过期时抛出，调用方应立即停止重试。
    """
    pass
logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Token使用量记录

    Args:
        prompt_tokens: 提示词Token数
        completion_tokens: 生成Token数
        total_tokens: 总Token数
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMClient:
    """LLM API客户端

    支持OpenAI兼容格式和Anthropic Messages格式。
    通过api_style参数切换，记录每次调用的Token使用量。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        base_url: str = "https://api.openai.com/v1",
        token_warning_threshold: int = 100000,
        api_style: str = "openai",
    ) -> None:
        """初始化LLM客户端

        Args:
            api_key: API密钥
            model: 模型名称
            base_url: API基础URL
            token_warning_threshold: Token使用量警告阈值
            api_style: API风格，"openai" 或 "anthropic"
        """
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._token_warning_threshold = token_warning_threshold
        self._api_style = api_style
        self._total_usage = TokenUsage()

    @property
    def total_usage(self) -> TokenUsage:
        """获取累计Token使用量"""
        return self._total_usage

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """调用LLM聊天接口

        根据api_style自动选择OpenAI或Anthropic格式发送请求。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 温度参数，控制随机性

        Returns:
            LLM的响应文本
        """
        if self._api_style == "anthropic":
            return await self._chat_anthropic(
                system_prompt, user_message, temperature
            )
        return await self._chat_openai(
            system_prompt, user_message, temperature
        )

    async def _chat_openai(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """OpenAI兼容格式的聊天调用"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
        }
        url = f"{self._base_url}/chat/completions"

        data = await self._send_request(url, headers, payload)

        # 记录Token使用量
        self._record_usage(data.get("usage", {}))

        # 提取响应内容
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")

        logger.warning("LLM API返回空响应")
        return ""

    async def _chat_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Anthropic Messages格式的聊天调用"""
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
        }
        url = f"{self._base_url}/v1/messages"

        data = await self._send_request(url, headers, payload)

        # 记录Token使用量（Anthropic格式）
        usage = data.get("usage", {})
        self._record_usage({
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0),
        })

        # 提取响应内容（Anthropic格式: content[0].text）
        content = data.get("content", [])
        if content:
            return content[0].get("text", "")

        logger.warning("LLM API返回空响应")
        return ""

    async def _send_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """发送HTTP请求到LLM API

        Args:
            url: 请求URL
            headers: 请求头
            payload: 请求体

        Returns:
            API响应的JSON数据
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            "LLM API调用失败: status=%d, body=%s",
                            resp.status, error_text[:500],
                        )
                        # 认证错误不可恢复，抛出专用异常让调用方快速失败
                        if resp.status in (401, 403):
                            raise LLMAuthenticationError(
                                f"LLM API认证失败(status={resp.status})，请检查API密钥配置"
                            )
                        raise RuntimeError(
                            f"LLM API返回错误状态码: {resp.status}"
                        )
                    return await resp.json()
        except aiohttp.ClientError as e:
            logger.error("LLM API网络请求失败: %s", e)
            raise

    def _record_usage(self, usage: Dict[str, Any]) -> None:
        """记录Token使用量并检查阈值

        Args:
            usage: 标准化后的usage字段
        """
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)

        self._total_usage.prompt_tokens += prompt
        self._total_usage.completion_tokens += completion
        self._total_usage.total_tokens += total

        logger.info(
            "Token使用量: 本次=%d, 累计=%d",
            total, self._total_usage.total_tokens,
        )

        if self._total_usage.total_tokens > self._token_warning_threshold:
            logger.warning(
                "Token累计使用量 %d 已超过警告阈值 %d",
                self._total_usage.total_tokens,
                self._token_warning_threshold,
            )
