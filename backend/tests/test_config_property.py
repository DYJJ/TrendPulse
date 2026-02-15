"""
配置管理属性测试

使用Hypothesis库对Config类进行基于属性的测试，
验证系统能正确从环境变量读取配置，缺失必需变量时抛出清晰错误。

属性 20: 环境变量读取
验证需求: 12.1, 12.4
"""

import os
from contextlib import contextmanager

import pytest
from hypothesis import given, strategies as st, settings

from backend.app.config import Config, ConfigurationError, reset_config

# 环境变量安全文本策略：过滤掉null字节，os.environ不支持含null字节的值
safe_env_text = st.text(min_size=1, max_size=200).filter(
    lambda s: s.strip() and "\x00" not in s
)


@contextmanager
def patched_env(env_vars: dict):
    """临时设置环境变量的上下文管理器，退出时恢复原始状态"""
    old_values = {}
    for key, value in env_vars.items():
        old_values[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, old_val in old_values.items():
            if old_val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_val
        reset_config()


# Feature: trendpulse-sentiment-analysis, Property 20: 环境变量读取
class TestConfigEnvProperty:
    """环境变量读取属性测试

    **验证: 需求 12.1, 12.4**

    对于任意必需的环境变量，系统应该能够从环境中读取其值，
    如果环境变量不存在，应该在启动时抛出错误并指明缺失的变量名。
    """

    @settings(max_examples=100)
    @given(api_key=safe_env_text)
    def test_valid_api_key_read_from_env(self, api_key: str):
        """设置了有效LLM_API_KEY时，Config应成功读取并通过验证

        **Validates: Requirements 12.1**
        """
        with patched_env({"LLM_API_KEY": api_key}):
            reset_config()
            config = Config.from_env()
            config.validate()
            assert config.llm_api_key == api_key

    @settings(max_examples=100)
    @given(
        api_key=safe_env_text,
        base_url=safe_env_text,
        model=safe_env_text,
    )
    def test_optional_vars_read_from_env(self, api_key: str, base_url: str, model: str):
        """可选环境变量设置后应正确读取到Config中

        **Validates: Requirements 12.1**
        """
        with patched_env({
            "LLM_API_KEY": api_key,
            "LLM_API_BASE_URL": base_url,
            "LLM_MODEL": model,
        }):
            reset_config()
            config = Config.from_env()
            config.validate()
            assert config.llm_api_key == api_key
            assert config.llm_api_base_url == base_url
            assert config.llm_model == model

    @settings(max_examples=100)
    @given(empty_val=st.sampled_from(["", "   ", "\t", "\n"]))
    def test_missing_or_empty_api_key_raises_error(self, empty_val: str):
        """缺失或空白的LLM_API_KEY应抛出ConfigurationError并包含变量名

        **Validates: Requirements 12.4**
        """
        with patched_env({"LLM_API_KEY": empty_val}):
            reset_config()
            config = Config.from_env()
            with pytest.raises(ConfigurationError) as exc_info:
                config.validate()
            assert "LLM_API_KEY" in str(exc_info.value)

    def test_unset_api_key_raises_error(self):
        """完全未设置LLM_API_KEY时应抛出ConfigurationError并包含变量名

        **Validates: Requirements 12.4**
        """
        with patched_env({"LLM_API_KEY": None}):
            reset_config()
            config = Config.from_env()
            with pytest.raises(ConfigurationError) as exc_info:
                config.validate()
            assert "LLM_API_KEY" in str(exc_info.value)

    @settings(max_examples=100)
    @given(port=st.integers(min_value=1, max_value=65535))
    def test_valid_port_accepted(self, port: int):
        """有效端口范围(1-65535)应通过验证

        **Validates: Requirements 12.1**
        """
        with patched_env({"LLM_API_KEY": "test-key", "APP_PORT": str(port)}):
            reset_config()
            config = Config.from_env()
            config.validate()
            assert config.app_port == port

    @settings(max_examples=100)
    @given(
        port=st.one_of(
            st.integers(max_value=0),
            st.integers(min_value=65536, max_value=100000),
        )
    )
    def test_invalid_port_raises_error(self, port: int):
        """无效端口值应抛出ConfigurationError

        **Validates: Requirements 12.4**
        """
        with patched_env({"LLM_API_KEY": "test-key", "APP_PORT": str(port)}):
            reset_config()
            config = Config.from_env()
            with pytest.raises(ConfigurationError) as exc_info:
                config.validate()
            assert "APP_PORT" in str(exc_info.value)

    @settings(max_examples=100)
    @given(debug_val=st.sampled_from(["true", "1", "yes", "True", "YES"]))
    def test_debug_truthy_values(self, debug_val: str):
        """各种真值字符串应正确解析为True

        **Validates: Requirements 12.1**
        """
        with patched_env({"LLM_API_KEY": "test-key", "APP_DEBUG": debug_val}):
            reset_config()
            config = Config.from_env()
            assert config.app_debug is True

    @settings(max_examples=100)
    @given(debug_val=st.sampled_from(["false", "0", "no", "False", "NO", "random"]))
    def test_debug_falsy_values(self, debug_val: str):
        """非真值字符串应正确解析为False

        **Validates: Requirements 12.1**
        """
        with patched_env({"LLM_API_KEY": "test-key", "APP_DEBUG": debug_val}):
            reset_config()
            config = Config.from_env()
            assert config.app_debug is False
