# -*- coding: utf-8 -*-
"""4.3 Lean 逻辑判断（答案代回题目）—— 五道审核链第 3 道（2026-10-14 用户定案）。

用户口径（原话）：「第三道用 lean 进行逻辑判断，就是让答案带回题目，
看看逻辑对不对」。

实现口径（加模块优先，复用既有 Lean 通道）：
  · 后端 = `tools/lean_local/lean_gate.LeanGate.apply`（候选级 Lean 硬验证：
    把「题目 + 候选答案/推理」翻译为 Lean 命题并编译 —— 这正是「答案带回
    题目」的形式化判定），**不新写第二个 Lean 校验实现**；
  · 本模块只做：开关/适用性守卫 → 调用 → 淘汰落池 → 反馈接线 → 留痕。

判定纪律（沿用既有 Lean 门的实证口径，防误杀）：
  · 部分淘汰 ⇒ `ctx.candidates = kept`；
  · **全拒** ⇒ 记 `_gate_all_rejected` 显式留痕、**不静默清池**（Lean 在正确题
    上误报率实测 56%，仅凭 Lean 全拒清池会误杀整池；`strict_all_rejected=True`
    时才清空交给下游兜底）—— 与 3.6 既有处置逐条一致；
  · 环境不可用 / 不适用 / 时间硬顶 ⇒ 降级放行（LeanGate 内部自处理并留痕）。

观测：trace step=``lean_backcheck``，diag 键 ``lean_backcheck`` /
``lean_backcheck_events``；`ctx.lean_gate`（LeanGate.apply 既有契约）不变。

五道链位置：4.0 规范化 → 4.1 自审 → 4.2 对抗证伪 → **4.3 Lean 代回** →
④计算检测 → ⑤投票。
"""
from __future__ import annotations

try:
    from .switch_registry import get_bool as _sw_get_bool
except ImportError:  # pragma: no cover  兼容非包内导入
    from switch_registry import get_bool as _sw_get_bool


def _switch_enabled() -> bool:
    """读「五道链·第 3 道 Lean 代回」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_lean_check")
    except Exception:  # noqa: BLE001
        return True


def lean_backcheck_stage(self, ctx, tier: str) -> None:
    """4.3 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。

    注入点：``getattr(self, "lean_gate", None) or LeanGate(...)``（与旧链
    3.6/4.7 同款，便于单测注入桩）。
    """
    try:
        if not _switch_enabled():
            self.record(ctx, "lean_backcheck",
                        "4.3 Lean 代回：开关关闭（five_gate_lean_check=0）")
            return
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            self.record(ctx, "lean_backcheck", "4.3 Lean 代回：候选池为空，跳过")
            return

        # 适用性守卫（与 3.6 同口径）：选项字母/判断值/概念文字答案结构上
        # 无从形式化 ⇒ 豁免 Lean（不豁免其余四道）
        _active = getattr(self, "_lean_active", None)
        _applicable = getattr(self, "_lean_applicable", None)
        if callable(_active) and not _active():
            self.record(ctx, "lean_backcheck",
                        "4.3 Lean 代回：Lean 通道未激活（降级放行）")
            return
        if callable(_applicable) and not _applicable(ctx):
            self.record(ctx, "lean_backcheck",
                        "4.3 Lean 代回：本题不适用（答案非数学对象）⇒ 豁免")
            ctx.lean_backcheck = {"enabled": False, "skipped": "not_applicable",
                                  "n": len(cands)}
            return

        from tools.lean_local.lean_gate import LeanGate as _LG
        _gate = getattr(self, "lean_gate", None) or _LG(self.client, self.config)

        _n_in = len(cands)
        kept, fbs = _gate.apply(ctx, tier, cands)

        if kept:
            ctx.candidates = kept
            self.record(ctx, "lean_backcheck",
                        "4.3 Lean 代回：通过 %d/%d（淘汰 %d）"
                        % (len(kept), _n_in, _n_in - len(kept)))
        else:
            # 全拒不静默清池（与 3.6 既有处置一致；strict 才清）
            ctx._gate_all_rejected = True
            self.record(ctx, "lean_backcheck",
                        "4.3 Lean 代回：⚠ %d 个候选**全部未通过** ⇒ 已标记 "
                        "_gate_all_rejected（不静默清池）" % _n_in)
            if bool(getattr(self.config, "strict_all_rejected", False)):
                ctx.candidates = []
                self.record(ctx, "lean_backcheck",
                            "strict_all_rejected=True ⇒ 清空候选池交下游兜底")

        if fbs:
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", None) or []) + list(fbs)
            # 既有契约：单独留一份 Lean 反馈（revise prompt 据此区分形式化缺陷）
            ctx.lean_reject_feedback = list(
                getattr(ctx, "lean_reject_feedback", None) or []) + list(fbs)

        ctx.lean_backcheck = {
            "enabled": True,
            "n": _n_in,
            "n_kept": len(kept),
            "n_rejected": _n_in - len(kept),
            "all_rejected": not kept,
        }
        self.record(ctx, "lean_backcheck",
                    "4.3 Lean 代回：%d 候选 ⇒ 通过 %d / 淘汰 %d%s"
                    % (_n_in, len(kept), _n_in - len(kept),
                       "（全拒已标记）" if not kept else ""))

        try:
            from .orchestrator__verify import _pool_empty_fallback as _pef
            _pef(self, ctx, "4.3_lean_check")
        except Exception:  # noqa: BLE001  兜底检查失败不影响主流程
            pass
    except Exception as _e:  # noqa: BLE001  增益环节绝不阻断主链
        self.record(ctx, "lean_backcheck",
                    f"4.3 Lean 代回异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
