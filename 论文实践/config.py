# -*- coding: utf-8 -*-
"""论文实验全局配置（零第三方依赖，纯 Python 配置模块）。

设计原则：
1. 本实验项目完全自包含在 `D:/挑战杯/论文实践` 内，**不修改主项目任何文件**。
2. 主项目只被"只读引用"：Mathlib 闭包（data/mathlib-closure）、API 密钥（.env）。
3. 改模型只需动 MODELS / DEFAULT_MODEL，无需改代码。
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "results"
CACHE_DIR = RESULTS_DIR / ".cache"

# 主项目（只读引用区，严禁写入）
MAIN_PROJECT = Path(r"D:/挑战杯")
MATHLIB_CLOSURE = MAIN_PROJECT / "data" / "mathlib-closure"
MAIN_ENV_FILE = MAIN_PROJECT / ".env"

# ---------------------------------------------------------------- Lean
# lean 可执行文件：优先环境变量，其次 PATH（elan 装在 C:/Users/<uid>/.elan/bin）
LEAN_EXE = os.environ.get("LEAN_EXE", "lean")
LEAN_FALLBACK_EXE = Path(os.path.expanduser("~")) / ".elan" / "bin" / "lean.exe"
# 单次 Lean 编译超时（秒）。Mathlib 闭包首次加载较慢，给足时间。
LEAN_TIMEOUT = int(os.environ.get("LEAN_TIMEOUT", "180"))

# ---------------------------------------------------------------- 模型
# 所有模型都是 OpenAI Chat Completions 兼容接口。
# reasoning=True 表示这是推理模型：正文在 content，思维链在 reasoning_content，
# 且 max_tokens 必须给足（思维链会吃掉大量 token，给少了会 finish_reason=length 截断）。
MODELS: dict[str, dict] = {
    "intern-s2": {
        "label": "Intern-S2-Preview-397B",
        "base_url": "https://chat.intern-ai.org.cn/api/v1",
        "model": "Intern-S2-Preview-397B",
        "api_key_env": "INTERN_API_KEY",
        "reasoning": False,
        "max_tokens": 8192,
        "temperature": 0.2,
    },
    "deepseek": {
        "label": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "reasoning": True,
        "max_tokens": 16384,
        "temperature": 0.2,
    },
}

# 默认模型。命令行 --model 可覆盖。
DEFAULT_MODEL = os.environ.get("PROBE_MODEL", "deepseek")

# ---------------------------------------------------------------- 运行
HTTP_TIMEOUT = int(os.environ.get("PROBE_HTTP_TIMEOUT", "300"))
MAX_RETRY = int(os.environ.get("PROBE_MAX_RETRY", "3"))
RETRY_SLEEP = float(os.environ.get("PROBE_RETRY_SLEEP", "5"))
# 每题重复采样次数（用于统计随机性：老师提到"大模型推理中会随机出现"）
REPEATS = int(os.environ.get("PROBE_REPEATS", "1"))


def load_main_env(override: bool = True) -> None:
    """只读加载主项目 .env 里的密钥。

    **重要（2026-09-03 实测踩坑）**：`override` 默认 True，即 .env 的值**优先于**
    已有环境变量。原因是本机 shell 里残留了一个已过期的 INTERN_API_KEY
    （同为 51 位，极易混淆），若按常规 dotenv 约定"已存在则不覆盖"，
    .env 里正确的 key 会被这个陈旧值遮住，表现为 `user token expired`。
    本项目以 .env 为权威配置源，故默认覆盖。
    需要保留外部注入时设环境变量 MATHPILOT_ENV_NO_OVERRIDE=1。
    本函数只写 os.environ，不碰主项目任何文件。
    """
    if os.environ.get("MATHPILOT_ENV_NO_OVERRIDE") == "1":
        override = False
    path = Path(os.environ.get("MATHPILOT_ENV_FILE", MAIN_ENV_FILE))
    if not path.is_file():
        return
    loaded: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and (override or k not in os.environ):
                os.environ[k] = v
                loaded.append(k)
    except Exception:  # 读不到就当没配，由调用方报"缺密钥"
        return
    if loaded:
        os.environ["_MATHPILOT_ENV_LOADED"] = ",".join(loaded)
