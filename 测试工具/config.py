"""
Configuration management - loads API keys and model settings from .env file.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

_loaded = False


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 120.0
    max_retries: int = 3


@dataclass
class EvalConfig:
    intern_s1: LLMConfig
    deepseek: LLMConfig


def load_config(dotenv_path: str = None) -> EvalConfig:
    global _loaded
    if not _loaded:
        if dotenv_path is None:
            dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
        load_dotenv(dotenv_path)
        _loaded = True
    return get_config()


def get_config() -> EvalConfig:
    return EvalConfig(
        intern_s1=LLMConfig(
            api_key=os.getenv("INTERN_S1_API_KEY", ""),
            base_url=os.getenv("INTERN_S1_BASE_URL", "https://internlm-chat.intern-ai.org.cn/puyu/api/v1"),
            model=os.getenv("INTERN_S1_MODEL", "internlm3-latest"),
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        ),
        deepseek=LLMConfig(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        ),
    )
