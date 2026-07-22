"""
Intern-S1 推理模块（独立版）。

提供 run_inference 函数，用于调用 Intern-S1 模型解答数学题。
此模块为自包含的独立副本，不依赖测试工具下的任何模块。
后续可在此模块基础上进行推理策略优化。

用法:
    from intern_s1_optimized import run_inference
    result = await run_inference(problem)
"""

from .intern_s1 import run_inference, SYSTEM_PROMPT, parse_intern_response
from .config import get_config, load_config, validate_config, ConfigError
from .models import Problem, InferenceResult

__all__ = [
    "run_inference",
    "SYSTEM_PROMPT",
    "parse_intern_response",
    "get_config",
    "load_config",
    "validate_config",
    "ConfigError",
    "Problem",
    "InferenceResult",
]
