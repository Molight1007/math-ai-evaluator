"""
Configuration management - loads API keys and model settings from .env file.

Storage priority:
1. User home directory: ~/.math_evaluator/.env  (recommended, persistent)
2. Project directory:   测试工具/.env              (legacy fallback)
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv, set_key

_loaded = False

# User-level config directory
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".math_evaluator")
USER_ENV_PATH = os.path.join(USER_CONFIG_DIR, ".env")


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


def get_user_env_path() -> str:
    """Return the path to user-level .env file."""
    return USER_ENV_PATH


def has_config() -> bool:
    """Check if user-level config exists."""
    return os.path.isfile(USER_ENV_PATH)


def _find_dotenv() -> str:
    """Find .env file, preferring user-level over project-level."""
    # 1. User home directory (preferred)
    if os.path.isfile(USER_ENV_PATH):
        return USER_ENV_PATH

    # 2. Legacy: project directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(current_dir), ".env"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # Default: user home (will be created on save)
    return USER_ENV_PATH


def save_config(intern_s1_key: str, deepseek_key: str,
                intern_s1_url: str = None, deepseek_url: str = None,
                intern_s1_model: str = None, deepseek_model: str = None) -> str:
    """Save API keys to user-level .env file. Returns the file path."""
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)

    with open(USER_ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# Math Evaluator - API Configuration\n")
        f.write("# Saved at: ~/.math_evaluator/.env\n\n")
        f.write(f"INTERN_S1_API_KEY={intern_s1_key}\n")
        f.write(f"INTERN_S1_BASE_URL={intern_s1_url or 'https://internlm-chat.intern-ai.org.cn/puyu/api/v1'}\n")
        f.write(f"INTERN_S1_MODEL={intern_s1_model or 'internlm3-latest'}\n\n")
        f.write(f"DEEPSEEK_API_KEY={deepseek_key}\n")
        f.write(f"DEEPSEEK_BASE_URL={deepseek_url or 'https://api.deepseek.com/v1'}\n")
        f.write(f"DEEPSEEK_MODEL={deepseek_model or 'deepseek-chat'}\n\n")
        f.write("LLM_TIMEOUT=120\n")
        f.write("LLM_MAX_RETRIES=3\n")

    # Reload env so os.getenv picks up new values
    global _loaded
    _loaded = False
    load_dotenv(USER_ENV_PATH, override=True)
    _loaded = True

    return USER_ENV_PATH


def load_config(dotenv_path: str = None) -> EvalConfig:
    global _loaded
    if not _loaded:
        if dotenv_path is None:
            dotenv_path = _find_dotenv()
        load_dotenv(dotenv_path, override=True)
        _loaded = True
    return get_config()


def reset_config():
    """Force reload config on next call."""
    global _loaded
    _loaded = False


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
            f"Please configure API keys in the settings dialog."
        )
    return cfg
