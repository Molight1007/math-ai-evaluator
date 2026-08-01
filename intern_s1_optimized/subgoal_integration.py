"""
增强版子目标求解器集成入口
======================

为 submit/user_agent.py 提供可选增强：
  - use_subgoal_lean: 启用含 Lean 4 验证的子目标求解模式
    需要同时设置 use_subgoal=True

用法示例:
    agent = ReasoningAgent(client, use_subgoal=True, use_subgoal_lean=True)
    result = agent.solve(problem, metadata)
"""

import logging

logger = logging.getLogger("MathPilot")


def try_import_enhanced_solver():
    """尝试导入增强版子目标求解器"""
    try:
        from intern_s1_optimized.subgoal_solver import (
            InternSubGoalSolver,
            solve_with_subgoals,
        )
        from intern_s1_optimized.llm_client import LLMClient
        from intern_s1_optimized.config import get_config as get_intern_config
        return {
            "solver_class": InternSubGoalSolver,
            "solve_fn": solve_with_subgoals,
            "LLMClient": LLMClient,
            "get_config": get_intern_config,
        }
    except ImportError as e:
        logger.warning(f"Enhanced subgoal solver not available: {e}")
        return None


def create_enhanced_subgoal_solver(client=None):
    """
    创建增强版子目标求解器实例。

    参数:
        client: 可选的 LLM 客户端（未使用，增强版自己管理客户端）

    返回:
        InternSubGoalSolver 实例，或 None（如果模块不可用）
    """
    modules = try_import_enhanced_solver()
    if modules is None:
        return None

    cfg = modules["get_config"]()
    intern_client = modules["LLMClient"](cfg.intern_s1)
    deepseek_client = modules["LLMClient"](cfg.deepseek)

    return modules["solver_class"](intern_client, deepseek_client)
