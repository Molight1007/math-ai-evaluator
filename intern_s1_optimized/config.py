"""
配置管理模块 - 从 .env 文件加载 API 密钥和模型设置。

存储优先级：
1. 用户主目录: ~/.math_evaluator/.env（推荐，持久化存储）
2. 项目目录:   测试工具/.env（旧版兼容）
"""
import os
import subprocess
from dataclasses import dataclass
from dotenv import load_dotenv

# ==================== 模块级常量 ====================

# 全局标记：是否已加载 .env，避免重复加载
_loaded = False

# 用户级配置目录（跨项目共享，一次配置永久生效）
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".math_evaluator")
USER_ENV_PATH = os.path.join(USER_CONFIG_DIR, ".env")

# 默认 LLM 超时和重试配置
_DEFAULT_LLM_TIMEOUT = 120.0           # 单次 API 请求超时（秒）
_DEFAULT_LLM_MAX_RETRIES = 3           # 最大重试次数

# 默认 Lean 配置
_DEFAULT_LEAN_EXECUTABLE = "lake"      # Lean 4 可执行文件名
_DEFAULT_LEAN_TIMEOUT = 60.0           # Lean 编译超时（秒）
_LEAN_DETECT_TIMEOUT = 10              # Lean 环境检测超时（秒）

# 默认 API 地址
_DEFAULT_INTERN_BASE_URL = "https://internlm-chat.intern-ai.org.cn/puyu/api/v1"
_DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 默认模型名称
_DEFAULT_INTERN_MODEL = "intern-s1"
_DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

# 假 API Key 前缀（用于检测未配置的情况）
_FAKE_KEY_PREFIX = "your_"


class ConfigError(Exception):
    """配置缺失时抛出的异常"""
    pass


@dataclass
class LLMConfig:
    """单个 LLM 服务的配置信息"""
    api_key: str                                  # API 密钥
    base_url: str                                 # API 基础地址
    model: str                                    # 模型名称
    timeout: float = _DEFAULT_LLM_TIMEOUT         # 请求超时（秒）
    max_retries: int = _DEFAULT_LLM_MAX_RETRIES   # 最大重试次数


@dataclass
class EvalConfig:
    """评测器完整配置 - 包含 Intern-S1、DeepSeek 和 Lean 验证的配置"""
    intern_s1: LLMConfig                          # Intern-S1 推理服务
    deepseek: LLMConfig                           # DeepSeek 评判服务
    lean_executable: str = ""                     # Lean 4 可执行文件路径（如 lake）
    lean_timeout: float = _DEFAULT_LEAN_TIMEOUT   # Lean 编译超时（秒）


def get_user_env_path() -> str:
    """获取用户级 .env 文件路径"""
    return USER_ENV_PATH


def has_config() -> bool:
    """检查用户级配置文件是否存在"""
    return os.path.isfile(USER_ENV_PATH)


def _find_dotenv() -> str:
    """
    查找 .env 文件路径。

    查找优先级：
    1. 用户主目录下的配置文件（~/.math_evaluator/.env）
    2. 当前模块目录、工作目录、上级目录中的 .env
    3. 默认返回用户级路径（供 save_config 自动创建）

    返回:
        找到的 .env 文件路径
    """
    if os.path.isfile(USER_ENV_PATH):
        return USER_ENV_PATH

    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(current_dir), ".env"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return USER_ENV_PATH


def save_config(
    intern_s1_key: str,
    deepseek_key: str,
    intern_s1_url: str = None,
    deepseek_url: str = None,
    intern_s1_model: str = None,
    deepseek_model: str = None,
) -> str:
    """
    将 API 密钥保存到用户级 .env 文件。

    参数:
        intern_s1_key: Intern-S1 API 密钥
        deepseek_key: DeepSeek API 密钥
        intern_s1_url: Intern-S1 API 地址（可选，使用默认值）
        deepseek_url: DeepSeek API 地址（可选，使用默认值）
        intern_s1_model: Intern-S1 模型名（可选）
        deepseek_model: DeepSeek 模型名（可选）

    返回:
        保存的 .env 文件路径
    """
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)

    intern_url = intern_s1_url or _DEFAULT_INTERN_BASE_URL
    intern_model = intern_s1_model or _DEFAULT_INTERN_MODEL
    deepseek_url = deepseek_url or _DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model = deepseek_model or _DEFAULT_DEEPSEEK_MODEL

    with open(USER_ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# Math Evaluator - API Configuration\n")
        f.write("# Saved at: ~/.math_evaluator/.env\n\n")
        f.write(f"INTERN_S1_API_KEY={intern_s1_key}\n")
        f.write(f"INTERN_S1_BASE_URL={intern_url}\n")
        f.write(f"INTERN_S1_MODEL={intern_model}\n\n")
        f.write(f"DEEPSEEK_API_KEY={deepseek_key}\n")
        f.write(f"DEEPSEEK_BASE_URL={deepseek_url}\n")
        f.write(f"DEEPSEEK_MODEL={deepseek_model}\n\n")
        f.write(f"LLM_TIMEOUT={int(_DEFAULT_LLM_TIMEOUT)}\n")
        f.write(f"LLM_MAX_RETRIES={_DEFAULT_LLM_MAX_RETRIES}\n\n")
        f.write("# Lean 4 形式化验证配置\n")
        f.write(f"LEAN_EXECUTABLE={_DEFAULT_LEAN_EXECUTABLE}\n")
        f.write(f"LEAN_TIMEOUT={int(_DEFAULT_LEAN_TIMEOUT)}\n")

    # 重新加载环境变量，使新保存的配置立即生效
    global _loaded
    _loaded = False
    load_dotenv(USER_ENV_PATH, override=True)
    _loaded = True

    return USER_ENV_PATH


def load_config(dotenv_path: str = None) -> EvalConfig:
    """
    加载配置：先读取 .env 文件，再返回 EvalConfig 对象。

    参数:
        dotenv_path: 指定的 .env 文件路径（可选，默认自动查找）

    返回:
        构建好的 EvalConfig 对象
    """
    global _loaded
    if not _loaded:
        if dotenv_path is None:
            dotenv_path = _find_dotenv()
        load_dotenv(dotenv_path, override=True)
        _loaded = True
    return get_config()


def reset_config() -> None:
    """强制下次调用时重新加载配置"""
    global _loaded
    _loaded = False


def get_config() -> EvalConfig:
    """从环境变量中构建 EvalConfig 对象（含 Intern-S1 和 DeepSeek 配置）"""
    return EvalConfig(
        intern_s1=LLMConfig(
            api_key=os.getenv("INTERN_S1_API_KEY", ""),
            base_url=os.getenv(
                "INTERN_S1_BASE_URL", _DEFAULT_INTERN_BASE_URL
            ),
            model=os.getenv("INTERN_S1_MODEL", _DEFAULT_INTERN_MODEL),
            timeout=float(
                os.getenv("LLM_TIMEOUT", str(int(_DEFAULT_LLM_TIMEOUT)))
            ),
            max_retries=int(
                os.getenv("LLM_MAX_RETRIES", str(_DEFAULT_LLM_MAX_RETRIES))
            ),
        ),
        deepseek=LLMConfig(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL", _DEFAULT_DEEPSEEK_BASE_URL
            ),
            model=os.getenv("DEEPSEEK_MODEL", _DEFAULT_DEEPSEEK_MODEL),
            timeout=float(
                os.getenv("LLM_TIMEOUT", str(int(_DEFAULT_LLM_TIMEOUT)))
            ),
            max_retries=int(
                os.getenv("LLM_MAX_RETRIES", str(_DEFAULT_LLM_MAX_RETRIES))
            ),
        ),
        lean_executable=os.getenv(
            "LEAN_EXECUTABLE", _DEFAULT_LEAN_EXECUTABLE
        ),
        lean_timeout=float(
            os.getenv("LEAN_TIMEOUT", str(int(_DEFAULT_LEAN_TIMEOUT)))
        ),
    )


def detect_lean_environment(lean_executable: str = _DEFAULT_LEAN_EXECUTABLE) -> dict:
    """
    检测 Lean 4 环境是否可用。

    通过调用 lean_executable --version 来检测，如果命令存在且
    返回码为 0，则认为环境可用。

    参数:
        lean_executable: Lean 可执行文件名或路径（默认 "lake"）

    返回:
        {"available": bool, "version": str, "error": str}
    """
    try:
        result = subprocess.run(
            [lean_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=_LEAN_DETECT_TIMEOUT,
        )
        if result.returncode == 0:
            version = (
                result.stdout.strip().split("\n")[0]
                if result.stdout else "unknown"
            )
            return {"available": True, "version": version, "error": ""}
        return {
            "available": False,
            "version": "",
            "error": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {
            "available": False,
            "version": "",
            "error": f"Lean executable not found: {lean_executable}",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "version": "",
            "error": f"Lean detection timed out ({_LEAN_DETECT_TIMEOUT}s)",
        }
    except Exception as e:
        return {"available": False, "version": "", "error": str(e)}


def validate_config(cfg: EvalConfig = None) -> EvalConfig:
    """
    验证必要的 API 密钥是否已配置。

    检查 Intern-S1 和 DeepSeek 的 API Key 是否有效（非空且不是占位符）。

    参数:
        cfg: 待验证的配置对象（默认从环境变量获取）

    返回:
        验证通过的配置对象

    异常:
        ConfigError: 缺少必要的 API Key 时抛出
    """
    if cfg is None:
        cfg = get_config()
    missing = []
    if not cfg.intern_s1.api_key or cfg.intern_s1.api_key.startswith(_FAKE_KEY_PREFIX):
        missing.append("INTERN_S1_API_KEY")
    if not cfg.deepseek.api_key or cfg.deepseek.api_key.startswith(_FAKE_KEY_PREFIX):
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        raise ConfigError(
            f"Missing API keys: {', '.join(missing)}.\n"
            "Please configure API keys in the settings dialog."
        )
    return cfg
