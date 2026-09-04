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
from .lean_bridge import LeanBridge, _parse_analysis_json, _strip_code_fence

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
        """前置形式化验证 + 骨架 Lean 审核 + 失败修正循环，写
        ctx.formal_spec / ctx.preverify_trace / ctx.sketch_audit。"""
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
            # 时间护栏：紧迫则跳过（降级，不阻断主流程）。
            # 2026-09-03 审核：原来这里连写两个 is_time_critical() 分支
            # （"预算不足"在前、"时间紧张"在后），后者永远不可达——预算闸门
            # 删除时的清理遗漏。现只保留一个时间判断。
            if ctx.is_time_critical():
                final["error"] = "时间紧迫，跳过前置形式化"
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
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化通过（第 {r + 1} 轮）: "
                            f"{result['formal_spec'][:80]}")
                break  # 通过理解，进入骨架审核阶段

            if result["verdict"] == "fail":
                # 2026-09-02 老师拍板：错了就重新理解直到对才通过。
                # 反馈不只是 Lean 编译错误——加"重新审题"强指令，逼迫 LLM 重读
                # 题目原文而非重复同样的错误翻译。
                error_summary = (result.get("error") or "")[:200]
                feedback = (
                    f"上轮形式化编译失败：\n{error_summary}\n\n"
                    "**请重新审题**（不要重复上轮思路）：\n"
                    "1. 重新通读题目原文，逐条列出题目给定的数学定义/条件/所求量。\n"
                    "2. 常见错误：把英文介词（to/from/of/with/by）当函数名；"
                    "漏掉条件或边界；把'求值'译成'求证'等。\n"
                    "3. 重新写 Lean 声明，确保：每出现的符号在题目中已定义或用 Lean 标准符号。\n"
                )
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化失败（第 {r + 1} 轮），强制重新理解重试: "
                            f"{error_summary[:120]}")
                continue

            # unknown（环境缺失/转化失败/超时）→ 不重试，直接降级
            break

        # ---- 骨架阶段 Lean 语法审核（#28，默认启用，安全降级）----
        if getattr(cfg, "enable_sketch_audit", True):
            if not ctx.is_time_critical():  # 预算已无限制（9/3）
                self.generate_and_audit_sketch(ctx)

        # 2026-09-02 老师拍板：rounds 用尽仍 fail → 标记"理解未确认"（让下游 Solver
        # 知道题目理解未经 Lean 校验，谨慎推理）。不阻断主流程（避免题目难时死锁），
        # 但 final_response 仍可能错（理解错了求解也跟着错）。
        if final.get("verdict") == "fail":
            ctx.formal_spec = ""  # 清除可能部分写的 spec
            ctx._preverify_unconfirmed = True
            self.record(
                ctx, "lean_preverify",
                "preverify 多次重试仍 fail，标记理解未确认——下游推理需谨慎",
            )

        # 未通过/降级：formal_spec 可能留空，但不阻断主流程
        ctx.preverify_trace = final
        self.record(ctx, "lean_preverify",
                    f"前置形式化结束: verdict={final.get('verdict')}；"
                    f"{final.get('error', '')[:120]}")
        return ctx

    # ------------------------------------------------------------------
    # 骨架生成 + Lean 语法审核（#28）
    # ------------------------------------------------------------------
    def _generate_sketch(self, ctx: TaskContext) -> str:
        """让书生(Intern-S1)生成题目骨架/Proof Body Outline（Informal Blueprint）。

        返回自然语言骨架（编号子目标列表）；生成失败返回空串（调用方降级）。
        """
        try:
            from prompts.lean_pre_verify import LEAN_SKETCH_SYSTEM, LEAN_SKETCH_USER
        except ImportError:
            from submit.prompts.lean_pre_verify import LEAN_SKETCH_SYSTEM, LEAN_SKETCH_USER
        formal_spec_block = ""
        if ctx.formal_spec:
            formal_spec_block = ("## 题目的形式化理解（已知条件→结论）\n"
                                + ctx.formal_spec + "\n\n")
        user_msg = LEAN_SKETCH_USER.format(
            problem=ctx.problem, domain=ctx.domain or "未知",
            formal_spec=formal_spec_block)
        raw = self.llm(
            ctx,
            [
                {"role": "system", "content": LEAN_SKETCH_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.2, 32768,
        )
        if not raw:
            return ""
        parsed = _parse_analysis_json(raw)
        outline = (parsed or {}).get("outline") or raw
        return _strip_code_fence(str(outline)).strip()

    def generate_and_audit_sketch(self, ctx: TaskContext, sketch_text: str = "") -> TaskContext:
        """生成（若未提供）并用 Lean 审核题目骨架，写 ctx.sketch / ctx.sketch_audit。

        审核发现的缺口并入 ctx.formal_gaps，供子目标规划优先拆解
        （即"骨架哪一步不严谨"→ 成为要先解决/拆解的子目标）。
        """
        bridge = self._build_bridge(ctx)
        if bridge is None:
            ctx.sketch_audit = {"verdict": "unknown", "error": "LeanBridge 初始化失败", "gaps": []}
            return ctx

        timeout = float(getattr(self.config, "preverify_timeout", 60.0) or 60.0)

        # 1) 生成骨架（若未提供）
        if not sketch_text:
            if ctx.is_time_critical():
                ctx.sketch_audit = {"verdict": "unknown", "error": "预算不足，跳过骨架生成", "gaps": []}
                return ctx
            sketch_text = self._generate_sketch(ctx)
        ctx.sketch = sketch_text or ""
        if not ctx.sketch:
            ctx.sketch_audit = {"verdict": "unknown", "error": "骨架生成失败", "gaps": []}
            return ctx

        # 2) 用 Lean 审核骨架（语法/类型严谨性）
        result = bridge.audit_sketch(ctx.sketch, ctx.problem, ctx.domain or "", timeout=timeout)
        ctx.sketch_audit = result

        # 3) 骨架缺口并入 formal_gaps（去重），供子目标规划优先拆解
        sg = result.get("gaps", []) or []
        if sg:
            existing = {g.get("detail") for g in ctx.formal_gaps}
            for g in sg:
                if g.get("detail") and g.get("detail") not in existing:
                    ctx.formal_gaps.append(g)
                    existing.add(g.get("detail"))

        self.record(ctx, "lean_sketch_audit",
                    f"骨架 Lean 审核: verdict={result.get('verdict')}; 缺口 {len(sg)} 个")
        return ctx
