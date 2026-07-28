"""Project configuration — no secrets or absolute paths."""

from __future__ import annotations

import os

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096

FAST_TEMPERATURE = 0.0
CREATIVE_TEMPERATURE = 0.5

MAX_MODEL_CALLS_PER_PROBLEM = 5
MAX_TRACE_CHARS_PER_STEP = 2000
MAX_FINAL_RESPONSE_CHARS = 4000

ENABLE_SYMPY = True
ENABLE_MULTI_CANDIDATE = True
ENABLE_VERIFICATION = True
ENABLE_REFLECTION = True

# 书生 ChatAPI（本地调试用；正式比赛平台会注入 official_client）
# 真实 Key 请放在 .env 或 config.local.py，勿提交仓库
INTERN_API_KEY = os.getenv("INTERN_API_KEY", "")
INTERN_API_BASE = os.getenv(
    "INTERN_API_BASE", "https://chat.intern-ai.org.cn/api/v1/"
)
INTERN_MODEL = os.getenv("INTERN_MODEL", "intern-latest")

LOCAL_MODEL_NAME_ENV = "INTERN_MODEL"

try:
    from config_local import (  # type: ignore  # noqa: F401
        INTERN_API_BASE as _LOCAL_BASE,
        INTERN_API_KEY as _LOCAL_KEY,
        INTERN_MODEL as _LOCAL_MODEL,
    )

    if _LOCAL_KEY:
        INTERN_API_KEY = _LOCAL_KEY
    if _LOCAL_BASE:
        INTERN_API_BASE = _LOCAL_BASE
    if _LOCAL_MODEL:
        INTERN_MODEL = _LOCAL_MODEL
except ImportError:
    pass
