"""
Configuration management - loads API keys and model settings from .env file.

Priority for finding .env:
1. Explicit dotenv_path argument
2. Same directory as this file (测试工具/.env)
3. Current working directory (.env)
4. Project root (.env)
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

_loaded = False


class ConfigError(Exception):
    """Raised when configuration is missing required values."""
    pass


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


def _find_dotenv() -> str:
    """Find .env file by checking multiple common locations."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    candidates = [
        os.path.join(current_dir, ".env"),        # 测试工具/.env
        os.path.join(os.getcwd(), ".env"),         # cwd/.env
        os.path.join(project_root, ".env"),        # 项目根/.env
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]  # default: 测试工具/.env


def load_config(dotenv_path: str = None) -> EvalConfig:
    global _loaded
    if not _loaded:
        if dotenv_path is None:
            dotenv_path = _find_dotenv()
        loaded = load_dotenv(dotenv_path)
        if not loaded and not os.path.isfile(dotenv_path):
            print(f"[WARNING] .env file not found at: {dotenv_path}")
            print(f"  Copy .env.example to .env and fill in your API keys.")
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


def validate_config(cfg: EvalConfig = None) -> EvalConfig:
    """Validate that required API keys are set. Raises ConfigError if not."""
    if cfg is None:
        cfg = get_config()
    missing = []
    if not cfg.intern_s1.api_key or cfg.intern_s1.api_key.startswith("your_"):
        missing.append("INTERN_S1_API_KEY")
    if not cfg.deepseek.api_key or cfg.deepseek.api_key.startswith("your_"):
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        raise ConfigError(
            f"Missing API keys: {', '.join(missing)}.\n"
            f"Please copy .env.example to .env and fill in your API keys."
        )
    return cfg
