"""
配置管理模块 - 从 .env 文件加载 API 密钥和模型设置。

存储优先级：
1. 用户主目录: ~/.math_evaluator/.env（推荐，持久化存储）
2. 项目目录:   测试工具/.env（旧版兼容）
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv, set_key

# 全局标记：是否已加载 .env，避免重复加载
_loaded = False

# 用户级配置目录（跨项目共享，一次配置永久生效）
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".math_evaluator")
USER_ENV_PATH = os.path.join(USER_CONFIG_DIR, ".env")


class ConfigError(Exception):
    """配置缺失时抛出的异常"""
    pass


@dataclass
class LLMConfig:
    """单个 LLM 服务的配置信息"""
    api_key: str                                  # API 密钥
    base_url: str                                 # API 基础地址
    model: str                                    # 模型名称
    timeout: float = 120.0                        # 请求超时（秒）
    max_retries: int = 3                          # 最大重试次数


@dataclass
class EvalConfig:
    """评测器完整配置 - 包含 Intern-S1 和 DeepSeek 两个服务的配置"""
    intern_s1: LLMConfig                          # Intern-S1 推理服务
    deepseek: LLMConfig                           # DeepSeek 评判服务


def get_user_env_path() -> str:
    """获取用户级 .env 文件路径"""
    return USER_ENV_PATH


def has_config() -> bool:
    """检查用户级配置文件是否存在"""
    return os.path.isfile(USER_ENV_PATH)


def _find_dotenv() -> str:
    """查找 .env 文件，优先使用用户级配置，回退到项目级配置"""
    # 优先：用户主目录下的配置文件
    if os.path.isfile(USER_ENV_PATH):
        return USER_ENV_PATH

    # 回退：项目目录中的旧版配置
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(current_dir), ".env"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # 默认返回用户级路径（保存时自动创建）
    return USER_ENV_PATH


def save_config(intern_s1_key: str, deepseek_key: str,
                intern_s1_url: str = None, deepseek_url: str = None,
                intern_s1_model: str = None, deepseek_model: str = None) -> str:
    """将 API 密钥保存到用户级 .env 文件，返回文件路径"""
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)

    with open(USER_ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# Math Evaluator - API Configuration\n")
        f.write("# Saved at: ~/.math_evaluator/.env\n\n")
        f.write(f"INTERN_S1_API_KEY={intern_s1_key}\n")
        f.write(f"INTERN_S1_BASE_URL={intern_s1_url or 'https://internlm-chat.intern-ai.org.cn/puyu/api/v1'}\n")
        f.write(f"INTERN_S1_MODEL={intern_s1_model or 'intern-s1'}\n\n")
        f.write(f"DEEPSEEK_API_KEY={deepseek_key}\n")
        f.write(f"DEEPSEEK_BASE_URL={deepseek_url or 'https://api.deepseek.com/v1'}\n")
        f.write(f"DEEPSEEK_MODEL={deepseek_model or 'deepseek-chat'}\n\n")
        f.write("LLM_TIMEOUT=120\n")
        f.write("LLM_MAX_RETRIES=3\n")

    # 重新加载环境变量，使新保存的配置立即生效
    global _loaded
    _loaded = False
    load_dotenv(USER_ENV_PATH, override=True)
    _loaded = True

    return USER_ENV_PATH


def load_config(dotenv_path: str = None) -> EvalConfig:
    """加载配置：先读取 .env 文件，再返回 EvalConfig 对象"""
    global _loaded
    if not _loaded:
        if dotenv_path is None:
            dotenv_path = _find_dotenv()
        load_dotenv(dotenv_path, override=True)
        _loaded = True
    return get_config()


def reset_config():
    """强制下次调用时重新加载配置"""
    global _loaded
    _loaded = False


def get_config() -> EvalConfig:
    """从环境变量中构建 EvalConfig 对象（含 Intern-S1 和 DeepSeek 配置）"""
    return EvalConfig(
        intern_s1=LLMConfig(
            api_key=os.getenv("INTERN_S1_API_KEY", ""),
            base_url=os.getenv("INTERN_S1_BASE_URL", "https://internlm-chat.intern-ai.org.cn/puyu/api/v1"),
            model=os.getenv("INTERN_S1_MODEL", "intern-s1"),
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
    """验证必要的 API 密钥是否已配置，缺少则抛出 ConfigError"""
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
