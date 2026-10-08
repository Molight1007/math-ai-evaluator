# -*- coding: utf-8 -*-
"""LeanGate 的 **agent-free 支持簇**（2026-10-08 拆分自 lean_gate.py）。

为什么单独成文件
================
`lean_gate.py` 曾 **871 行**（超 800 上限），而 `apply`(298) / `gate_final_answer`(162)
两个主方法的原地拆分只会**继续加长**入口文件。故把与 Lean / agent **零耦合**的
「语义等价缓存 + 诊断埋点/记忆」支持簇**逐字**搬到这里。

缩进说明（tokenize 感知去缩进）
================================
仅对**非多行字符串内部**的行去掉 4 空格缩进；多行 docstring 的续行**保持原缩进**
⇒ 字符串字面量逐字不变（`ast.dump` 逐节点一致）。

分层约束（tools/ 不得 import agent，除显式豁免清单）
====================================================
本模块**只**依赖 ``contracts.protocols.TaskContext``（零依赖层）——
**绝不** import `agent/` 或 `tools/` 内其它模块 ⇒ `tools/ → agent`（非豁免）处数不增。

绑定方式（调用点零改动，且 `is` 同一对象）
==========================================
``lean_gate.LeanGate`` 内以类属性绑定：
  · 静态方法：``_x = staticmethod(_support._x)``
  · 实例方法：``_x = _support._x``（模块级函数首参为 ``self``）
⇒ ``self._x(...)`` / ``LeanGate._x(...)`` 与搬前**同一对象**，行为逐字不变。
"""
from __future__ import annotations

import logging

from contracts.protocols import TaskContext

logger = logging.getLogger("MathPilot")


def _not_applicable(ctx: TaskContext) -> tuple[bool, str]:
    """按题 Lean 适用性豁免（2026-09-10 用户要求「所有题都要用 Lean，
        除非非常简单的题」）。

        答案不是数学对象的题（选项字母 / 判断值 / 概念文字）Lean 结构上无从
        形式化核验，按**题**豁免而不是用全局开关一刀切。判定值由
        ``orchestrator`` 在 1.1) 步骤落盘到 ``ctx.metadata["lean_applicable"]``
        （:func:`agent.question_type.lean_applicable`）——本模块只读 metadata，
        保持 ``tools/`` 单向依赖 ``agent/`` 的隔离原则。

        缺省语义：metadata 无该键（旧结果 / 手搓 ctx / 单测 fixture）→
        视为适用，既有行为完全不变。

        返回 ``(是否豁免, 原因)``。
        """
    md = getattr(ctx, "metadata", None)
    if isinstance(md, dict) and md.get("lean_applicable") is False:
        return True, str(md.get("lean_skip_reason", "") or "not_applicable")
    return False, ""


def _verify_key(problem: str, reasoning: str, answer: str, is_proof: bool):
    """**语义等价**的验证去重键 = sha1(题目, 推理, 答案, 是否证明题)。

        为什么安全：键里含 `reasoning` 的哈希 —— 只有三者**逐字相同**才算命中，
        与 `bridge.verify/verify_answer` 的实际入参一一对应 ⇒ 复用报告**不改变任何
        验证语义**。这正是它与 `lean_dedup_by_answer`（只按答案、默认关，自述"会改
        语义"）的本质区别。

        解决的浪费（确定性重复）：3.6 `apply` 已逐候选验一次，而 6.5
        `gate_final_answer` 又用**逐字相同的三元组**再验一次（orchestrator 取
        `best_reasoning` 时取的就是 `answer == final_response` 的那个候选）
        ⇒ 同一份输入被验两遍，每遍 = 1 次 LLM 翻译 + 1 次 Lean 编译。
        """
    import hashlib as _hl
    try:
        _raw = "%s\x1f%s\x1f%s\x1f%d" % (
            problem or "", reasoning or "", answer or "",
            1 if is_proof else 0)
        return _hl.sha1(_raw.encode("utf-8", "replace")).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def _cache_get(ctx, key):
    """命中返回 report，未命中/不可用返回 None（缓存挂在 ctx，每题独立）。"""
    if not key:
        return None
    try:
        _c = getattr(ctx, "_lean_verify_cache", None)
        if isinstance(_c, dict):
            return _c.get(key)
    except Exception:  # noqa: BLE001
        pass
    return None


def _cache_put(ctx, key, report):
    if not key or report is None:
        return
    try:
        _c = getattr(ctx, "_lean_verify_cache", None)
        if not isinstance(_c, dict):
            _c = {}
            ctx._lean_verify_cache = _c
        _c[key] = report
    except Exception:  # noqa: BLE001
        pass


def _record_ctx(self, ctx: TaskContext, data: dict) -> None:
    try:
        ctx.lean_gate.append(data)
    except Exception:  # noqa: BLE001
        ctx.lean_gate = [data]


def _note_self_proof_trace(self, ctx: TaskContext, report) -> None:
    """把「自证 → 形式化不充分」判定写一条 **trace**（供外部效果指标单独观测）。

        ★★ 2026-10-07（本次修复 B 项）：`lean_bridge.verify_answer` 的三类自证
        成因（数字/符号未交叉 / 闭式自证 / **恒等式自证**）此前**复用同一条失败
        分支、产出同一句 desc** ⇒ 外部**无法区分**「真的检测到恒等式」与「普通
        cross_check 失败」。效果捕捉脚本 `tools/effect_capture.py` 的 #10 判据
        （`trace` 中『恒等式』出现次数）因此**恒为 0、无法判定该机制是否生效**。
        现在 `verify_answer` 已为各成因设独立 `verdict_reason`（随 diag 落盘）；
        本函数再把**自证类**成因单独落一条 trace，使「是否拦截了恒等式自证」
        可被 trace / 效果脚本**独立计数**（`step == "lean_self_proof"`）。
        """
    try:
        reason = getattr(report, "verdict_reason", "") or ""
        if reason not in ("identity_self_proof", "ground_self_proof"):
            return
        # 同一题内同一成因只记一次（报告可能被多个候选复用）
        seen = getattr(ctx, "_self_proof_traced", None)
        if seen is None:
            seen = set()
            setattr(ctx, "_self_proof_traced", seen)
        if reason in seen:
            return
        seen.add(reason)
        label = ("恒等式自证（X = X，等号两边文本等价）"
                 if reason == "identity_self_proof"
                 else "闭式自证（含参题面 + ground 验证代码）")
        ctx.trace.append({
            "agent": self.name, "step": "lean_self_proof",
            "reason": reason,
            "content": ("Lean 验证拦截自证（%s）：%s；代码已编译通过 ⇒ "
                        "属**形式化不充分**（无法核验，非答案错）"
                        % (reason, label)),
        })
    except Exception:  # noqa: BLE001  埋点失败不影响主链
        pass


def _record_to_memory(self, ctx: TaskContext, domain: str,
                      names: list) -> None:
    """跨题定理记忆：验证通过的定理按域持久化（供同域新题复用）。"""
    try:
        if not names:
            return
        if not getattr(self.config, "theorem_memory_enable", True):
            return
        from tools.lean_local.theorem_memory import TheoremMemory
        mem = TheoremMemory(
            str(getattr(self.config, "theorem_memory_path", "")))
        for n in names:
            mem.record_hit(domain, n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[lean_gate] 定理记忆写入失败（不阻断）: %s", exc)
