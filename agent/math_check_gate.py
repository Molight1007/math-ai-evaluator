# -*- coding: utf-8 -*-
"""4.4 数学工具计算检测 —— 五道审核链第 4 道（2026-10-14 用户定案）。

用户口径（原话）：「第四道就是利用数学工具进行计算检测，看看计算步骤有没有问题」。

实现口径（加模块优先，复用既有数学工具内核）：
  · 后端 = `agent/deterministic.DeterministicChecker.check_answer`（SymPy
    精确判定：答案可解析性 / 常量等式全量回带 / 函数方程回代 / 反例搜索
    —— 均为**可机检**判定，非 LLM 自评），**不新写第二个计算器**；
  · 输入优先取 4.0 的 `answer_norm`（规范化的意义就在于此）；无则回退原文。

判定纪律（沿用 AuditGate Level0 既有实证口径）：
  · 单候选 `verdict == "fail"` ⇒ 计算检测不通过 ⇒ **淘汰**（机器判定，非自评）；
  · `unknown`（不可解析 / 超时 / sympy 不可用）⇒ **放行**（宁 unknown 不误杀）；
  · **全拒** ⇒ 回退保留原候选池（与 `AuditGate.audit_candidates` 的
    「全部候选被否 → 回退保留（宁 unknown 不误杀）」逐字一致），显式留痕。

观测：trace step=``math_check``，diag 键 ``math_check`` / ``math_check_events``。

五道链位置：4.0 规范化 → 4.1 自审 → 4.2 对抗证伪 → 4.3 Lean 代回 →
**4.4 计算检测** → ⑤投票。
"""
from __future__ import annotations

try:
    from .switch_registry import get_bool as _sw_get_bool
except ImportError:  # pragma: no cover  兼容非包内导入
    from switch_registry import get_bool as _sw_get_bool


def _switch_enabled() -> bool:
    """读「五道链·第 4 道计算检测」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_math_check")
    except Exception:  # noqa: BLE001
        return True


def math_check_stage(self, ctx) -> None:
    """4.4 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。

    注入点：``getattr(self, "math_check_det", None) or DeterministicChecker()``
    （与 4.3/4.2 同款，便于单测注入桩）。
    """
    try:
        if not _switch_enabled():
            self.record(ctx, "math_check",
                        "4.4 计算检测：开关关闭（five_gate_math_check=0）")
            return
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            self.record(ctx, "math_check", "4.4 计算检测：候选池为空，跳过")
            return

        from .deterministic import DeterministicChecker
        _det = getattr(self, "math_check_det", None) or DeterministicChecker()
        problem = str(getattr(ctx, "problem", "") or "")
        domain = str(getattr(ctx, "domain", "") or "")

        kept, rejected, n_fail, n_unknown = [], [], 0, 0
        for c in cands:
            cid = getattr(c, "id", "?")
            kind = str(getattr(c, "answer_kind", "") or "")
            ans = str(getattr(c, "answer_norm", None)
                      or getattr(c, "answer", "") or "")
            det = {"verdict": "unknown", "evidence": "", "method": ""}
            try:
                det = _det.check_answer(ctx, problem, ans, domain or None) or det
            except Exception as _e_d:  # noqa: BLE001  异常 ⇒ 放行（不误杀）
                self.record(ctx, "math_check",
                            "cid=%s 计算检测异常（放行）: %s: %s"
                            % (cid, type(_e_d).__name__, str(_e_d)[:120]))
            _v = str(det.get("verdict") or "unknown")
            if _v == "fail":
                n_fail += 1
                rejected.append({
                    "id": cid, "kind": kind, "answer": ans[:160],
                    "method": str(det.get("method") or ""),
                    "evidence": str(det.get("evidence") or "")[:300]})
                self.record(ctx, "math_check",
                            "cid=%s **计算检测不通过**（%s）⇒ 淘汰：%s"
                            % (cid, det.get("method") or "-",
                               str(det.get("evidence") or "")[:200]))
            else:
                if _v == "unknown":
                    n_unknown += 1
                kept.append(c)
                self.record(ctx, "math_check",
                            "cid=%s 通过/放行（verdict=%s%s）"
                            % (cid, _v,
                               "、kind=%s" % kind if kind else ""))

        if rejected and not kept:
            # 全拒 ⇒ 回退保留（宁 unknown 不误杀；与 AuditGate 口径一致）
            kept = cands
            ctx.math_check = {
                "n": len(cands), "n_rejected": 0, "n_fail": n_fail,
                "n_unknown": n_unknown, "all_rejected_fallback": True,
                "would_reject_ids": [r["id"] for r in rejected],
            }
            self.record(ctx, "math_check",
                        "⚠ 4.4 计算检测：%d 个候选**全部未通过** ⇒ 回退保留"
                        "原候选池（宁 unknown 不误杀）" % len(cands))
        else:
            if rejected:
                ctx.candidates = kept
                ctx.audit_reject_feedback = list(
                    getattr(ctx, "audit_reject_feedback", None) or []) + [
                        "[计算检测] cid=%s: %s（%s）"
                        % (r["id"], r["evidence"], r["method"])
                        for r in rejected]
                ctx.math_check_rejected = list(
                    getattr(ctx, "math_check_rejected", None) or []) + rejected
            ctx.math_check = {
                "n": len(cands), "n_rejected": len(rejected), "n_fail": n_fail,
                "n_unknown": n_unknown, "all_rejected_fallback": False,
                "rejected_ids": [r["id"] for r in rejected],
            }
            self.record(ctx, "math_check",
                        "4.4 计算检测：%d 候选 ⇒ 淘汰 %d / 保留 %d"
                        "（无法判定 %d）"
                        % (len(cands), len(rejected), len(kept), n_unknown))

        try:
            from .orchestrator__verify import _pool_empty_fallback as _pef
            _pef(self, ctx, "4.4_math_check")
        except Exception:  # noqa: BLE001  兜底检查失败不影响主流程
            pass
    except Exception as _e:  # noqa: BLE001  增益环节绝不阻断主链
        self.record(ctx, "math_check",
                    f"4.4 计算检测异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
