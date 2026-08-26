from __future__ import annotations
"""
Lean 前置形式化验证智能体（LeanPreVerifier）
===========================================

在解题开始前，把题目转化为 Lean 4 定理声明（证明 sorry 占位），用声明模式
编译校验「题目理解是否准确」；声明 well-typed 即视为理解正确。若验证失败，
把编译错误回传书生，要求重新理解题目并修正形式化，循环至通过或达到上限。

与后置 LeanGate 的区别：
- LeanPreVerifier（前置）：验证「题目命题声明」是否 well-typed，校准题意理解；
- LeanGate（后置）：验证「解答推理」是否正确，二者互补。

安全降级：Lean 环境缺失 / 编译超时 / 转化失败 / 预算不足 → 记 trace 后跳过
前置验证（formal_spec 留空），绝不阻断主流程。

依赖：
- agent/lean_bridge.py（LeanBridge.formalize_problem 声明模式编译）
- agent/base.py（BaseAgent / TaskContext）
"""

import logging

from .base import BaseAgent, TaskContext
from .lean_bridge import LeanBridge

logger = logging.getLogger("MathPilot")


class LeanPreVerifier(BaseAgent):
    """题目前置形式化验证智能体（v2.9）。"""

    name = "LeanPreVerifier"

    def __init__(self, client, config):
        super().__init__(client, config)
        self._bridge: LeanBridge | None = None

    @property
    def _bridge_inst(self) -> LeanBridge | None:
        """懒加载 LeanBridge（budget 在 run 时才按 ctx 注入，故此处为占位）。"""
        if self._bridge is None:
            try:
                # budget 参数为 None：正式调用在 run 里按 ctx.budget 重新构造，
                # 确保前置形式化的 LLM 转化计入当前题的预算。
                self._bridge = LeanBridge(self.client, self.config, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("LeanPreVerifier: LeanBridge 初始化失败: %s", e)
                self._bridge = None
        return self._bridge

    def _build_bridge(self, ctx: TaskContext) -> LeanBridge | None:
        """构造绑定当前题预算的 LeanBridge（LLM 转化计入 ctx.budget）。"""
        try:
            return LeanBridge(self.client, self.config, ctx.budget)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanPreVerifier: LeanBridge 构造失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext) -> TaskContext:
        """前置形式化验证 + 失败修正循环，写 ctx.formal_spec / ctx.preverify_trace。"""
        cfg = self.config
        if not getattr(cfg, "enable_lean_preverify", True):
            ctx.preverify_trace = {"enabled": False}
            return ctx
        if not ctx.problem:
            ctx.preverify_trace = {"verdict": "unknown", "error": "题目为空"}
            return ctx

        bridge = self._build_bridge(ctx)
        if bridge is None:
            ctx.preverify_trace = {"verdict": "unknown", "error": "LeanBridge 初始化失败"}
            self.record(ctx, "lean_preverify", "LeanBridge 初始化失败，前置形式化降级跳过")
            return ctx

        max_rounds = max(0, int(getattr(cfg, "preverify_max_rounds", 2)))
        timeout = float(getattr(cfg, "preverify_timeout", 60.0) or 60.0)

        final = {"verdict": "unknown", "rounds": 0,
                 "lean_code": "", "formal_spec": "", "error": ""}
        feedback = ""
        for r in range(max_rounds + 1):
            final["rounds"] = r
            # 预算/时间护栏：不足则跳过（降级，不阻断主流程）
            if ctx.budget is not None and not ctx.budget.can_spend(1):
                final["error"] = "预算不足，跳过前置形式化"
                break
            if ctx.is_time_critical():
                final["error"] = "时间紧张，跳过前置形式化"
                break

            result = bridge.formalize_problem(
                ctx.problem, ctx.domain or "", timeout=timeout, feedback=feedback)
            final["verdict"] = result["verdict"]
            final["lean_code"] = result["lean_code"]
            final["formal_spec"] = result["formal_spec"]
            final["error"] = result["error"]
            # 缺口（缺失定义/引理/模块/类型）：供子目标规划优先拆解
            final["gaps"] = result.get("gaps", [])
            ctx.formal_gaps = result.get("gaps", [])

            if result["verdict"] == "ok":
                ctx.formal_spec = result["formal_spec"]
                ctx.preverify_trace = final
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化通过（第 {r + 1} 轮）: "
                            f"{result['formal_spec'][:80]}")
                return ctx

            if result["verdict"] == "fail":
                # 声明编译失败 → 带错误反馈重试修正
                feedback = result["error"]
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化失败（第 {r + 1} 轮），修正重试: "
                            f"{result['error'][:120]}")
                continue

            # unknown（环境缺失/转化失败/超时）→ 不重试，直接降级
            break

        # 未通过：降级跳过（formal_spec 留空），不阻断主流程
        ctx.preverify_trace = final
        self.record(ctx, "lean_preverify",
                    f"前置形式化未通过/降级: {final.get('error', '')[:120]}")
        return ctx
