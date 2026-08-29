# -*- coding: utf-8 -*-
"""Lean 硬验证门禁（证明题专用，v2.8 扩展到全部档位）。

设计背景
========
v2.5 完整版在此前只有「软验证」：Solver 在证明题通道内调用 LeanBridge，
把 verdict 注入 revise_feedback，失败不阻断。本模块将其升级为 **deep 档的
硬验证层**：

- 对 domain ∈ {证明, 证明题} 的候选执行（v2.8 起含全部档位，受时间/预算护栏）；
- 对候选调用 :meth:`LeanBridge.verify`，把 NL 推理转 Lean 4 代码并编译；
- verdict == 'proof_valid'   → 候选计入有效（lean_valid=True）；
- verdict == 'proof_invalid' → 候选淘汰（lean_invalid=True），收集反馈供 revise；
- verdict == 'unknown'（Lean 环境缺失 / 超时 / 翻译不确定）→ 按
  ``lean_gate_strict`` 决定：False 降级放行（保守，不损失分数），True 保守拒绝。

隔离原则
========
- 独立文件，不污染 orchestrator 主流程：orchestrator 只需调用
  ``LeanGate(client, config).apply(ctx, tier, candidates)`` 一行；
- 任何异常一律吞掉并降级 unknown 放行，**绝不**因 Lean 导致评测崩溃；
- Lean 不可用时（环境缺失）仅打 warning 日志并整体降级，不阻断非证明题。

对外契约
========
``apply()`` 返回 ``(kept, feedbacks)``：
- kept: 通过 Lean 门禁（proof_valid 或 unknown 放行）的候选列表；
- feedbacks: 被淘汰候选的错误反馈列表（注入 revise 用）。
并把每候选结果写入 ctx.lean_gate 便于 trace/诊断。
"""
from __future__ import annotations

import logging
import re

from .base import Budget, TaskContext
from .lean_bridge import LeanBridge

logger = logging.getLogger("MathPilot")


class LeanGate:
    """证明题的 Lean 硬验证门禁（v2.8 扩展到全部档位）。"""

    name = "LeanGate"

    def __init__(self, client, config, budget: Budget | None = None):
        self.client = client
        self.config = config
        self.budget = budget
        self._bridge: LeanBridge | None = None

    # ------------------------------------------------------------------
    # 开关与适用性判定
    # ------------------------------------------------------------------
    def _enabled(self, tier: str, domain: str) -> bool:
        cfg = self.config
        if not getattr(cfg, "enable_lean_verify", True):
            return False
        if domain not in ("证明", "证明题"):   # 仅证明题
            return False
        # v2.8：扩展到全部证明题（含 standard 档）；旧行为（仅 deep）由
        # lean_gate_all_proofs=False 保留。
        if not getattr(cfg, "lean_gate_all_proofs", True) and tier != "deep":
            return False
        return True

    @property
    def strict(self) -> bool:
        return bool(getattr(self.config, "lean_gate_strict", False))

    @property
    def _bridge_inst(self) -> LeanBridge | None:
        if self._bridge is None:
            try:
                self._bridge = LeanBridge(self.client, self.config, self.budget)
            except Exception as e:  # noqa: BLE001
                logger.warning("LeanBridge 初始化失败，Lean 门禁整体降级: %s", e)
                self._bridge = None
        return self._bridge

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def apply(self, ctx: TaskContext, tier: str,
              candidates: list) -> tuple[list, list]:
        """对 deep 档证明题候选执行 Lean 硬验证。

        返回 ``(kept, feedbacks)``：kept 为通过门禁的候选，feedbacks 为
        被淘汰候选的错误反馈（供 revise 回环注入）。并把每候选 lean 状态
        记入 ``ctx.lean_gate``（list[dict]）。
        """
        kept = list(candidates)
        feedbacks: list[str] = []
        ctx.lean_gate = []

        if not candidates:
            return kept, feedbacks

        domain = getattr(ctx, "domain", "")
        if not self._enabled(tier, domain):
            self._record_ctx(ctx, {"enabled": False, "tier": tier,
                                   "domain": domain, "candidates": len(candidates)})
            return kept, feedbacks

        # v2.8 时间/预算护栏：应急/时间紧张/预算不足时降级放行，
        # 避免 standard 档证明题的 Lean 编译拖垮单题 20 分钟硬限。
        if getattr(ctx.state, 'emergency', False) or ctx.is_time_critical():
            self._record_ctx(ctx, {"enabled": True, "degraded": "time_critical",
                                   "tier": tier, "domain": domain})
            return kept, feedbacks
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            self._record_ctx(ctx, {"enabled": True, "degraded": "budget_exhausted",
                                   "tier": tier, "domain": domain})
            return kept, feedbacks

        bridge = self._bridge_inst
        if bridge is None:
            # 环境缺失 / 初始化失败 → 整体降级放行（绝不阻断）
            logger.warning("LeanGate: Lean 环境不可用，deep 档证明题门禁降级放行")
            self._record_ctx(ctx, {"enabled": True, "degraded": "env_unavailable",
                                   "tier": tier, "domain": domain})
            return kept, feedbacks
        if not bridge.lean_available:
            logger.warning("LeanGate: detect_lean_environment 未发现 lake/elan，"
                           "deep 档证明题门禁降级放行（可运行 deploy/setup_lean.sh）")
            self._record_ctx(ctx, {"enabled": True, "degraded": "lean_missing",
                                   "tier": tier, "domain": domain})
            return kept, feedbacks

        kept = []
        for cand in candidates:
            entry = {
                "id": cand.id,
                "verdict": "unknown",
                "lean_valid": False,
                "degraded": None,
                "error": None,
            }
            try:
                report = bridge.verify(
                    problem=ctx.problem or "",
                    reasoning=cand.reasoning or "",
                    domain=domain,
                    timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                )
                # 记录本次验证实际用到的 Mathlib 模块与声明的定理名
                # （#1/#2 证据链：AI 解答 → Lean 形式化验证用了哪些定理）
                used_names: list[str] = []
                if report is not None:
                    code = getattr(report, "lean_code", "") or ""
                    if code:
                        mods = re.findall(r"^\s*import\s+(Mathlib\.\S+)",
                                          code, re.MULTILINE)
                        thms = re.findall(
                            r"^\s*(?:theorem|lemma|example)\s+(\w+)",
                            code, re.MULTILINE)
                        used_names = mods + thms
                        self.add_used_theorems(ctx, used_names)
                if report is None:
                    entry["degraded"] = "no_report"
                    kept.append(cand)          # 无报告 → 降级放行
                elif report.verdict == "proof_valid":
                    entry["verdict"] = "proof_valid"
                    entry["lean_valid"] = True
                    self.note_compile_valid(ctx)  # 真正的形式化验证成功
                    # 跨题定理记忆：验证通过的定理 → 按域持久化，供同域新题复用
                    self._record_to_memory(ctx, domain, used_names)
                    kept.append(cand)
                elif report.verdict == "proof_invalid":
                    entry["verdict"] = "proof_invalid"
                    # 淘汰（hard gate）：不进 kept
                    # v2.7：结构化注入 Finding 精确错误定位（location/kind/desc），
                    # 而非只取 suggestion 或第一个 finding 的 desc，让 revise 拿到
                    # "第 X 步/某位置：错误描述" 的定向修正依据。
                    msg = "Lean 编译/逻辑错误"
                    try:
                        from .answer_oracle import AnswerOracle
                        structured = AnswerOracle.findings_to_feedback(
                            getattr(report, "findings", []) or [])
                        if structured:
                            msg = structured
                        elif getattr(report, "suggestion", ""):
                            msg = report.suggestion
                    except Exception:  # noqa: BLE001
                        if report.suggestion or report.findings:
                            msg = report.suggestion or report.findings[0].desc
                    feedbacks.append(
                        f"[Lean 硬验证] 候选 {cand.id} 未通过 Lean 编译验证：\n{msg}")
                else:  # unknown
                    entry["verdict"] = "unknown"
                    if self.strict:
                        entry["degraded"] = "strict_reject"
                        feedbacks.append(
                            f"[Lean 硬验证] 候选 {cand.id} Lean 验证未知（strict 保守拒绝）")
                        # strict 模式：不进 kept
                    else:
                        entry["degraded"] = "lenient_pass"
                        kept.append(cand)
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)[:200]
                entry["degraded"] = "exception_lenient"
                logger.warning("LeanGate: 候选 %s Lean 验证异常，降级放行: %s",
                               cand.id, e)
                kept.append(cand)

            self._record_ctx(ctx, entry)

        if feedbacks:
            self._record_ctx(ctx, {
                "rejected": len(feedbacks),
                "kept": len(kept),
                "feedbacks": feedbacks,
            })
        else:
            self._record_ctx(ctx, {"rejected": 0, "kept": len(kept)})
        return kept, feedbacks

    # ------------------------------------------------------------------
    # 诊断记录
    # ------------------------------------------------------------------
    def _record_ctx(self, ctx: TaskContext, data: dict) -> None:
        try:
            ctx.lean_gate.append(data)
        except Exception:  # noqa: BLE001
            ctx.lean_gate = [data]

    def _record_to_memory(self, ctx: TaskContext, domain: str,
                          names: list) -> None:
        """跨题定理记忆：验证通过的定理按域持久化（供同域新题复用）。"""
        try:
            if not names:
                return
            if not getattr(self.config, "theorem_memory_enable", True):
                return
            from .theorem_memory import TheoremMemory
            mem = TheoremMemory(
                str(getattr(self.config, "theorem_memory_path", "")))
            for n in names:
                mem.record_hit(domain, n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lean_gate] 定理记忆写入失败（不阻断）: %s", exc)
