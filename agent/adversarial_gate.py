# -*- coding: utf-8 -*-
"""4.2 AI 对抗证伪 —— 五道审核链第 2 道（2026-10-14 用户定案）。

用户口径（原话）：「第二道让 ai 对还存活的答案生成对应的对抗性验证，
来验证能不能证伪，证伪就判错」。

职责：对 4.1 自审后**存活**的每个候选执行两层对抗验证，**证伪即淘汰**：
  ① **机检证伪**（`AnswerFalsifier`）：LLM 构造证伪证书（数值回带等式）→
     SymPy 精确判定拿到反例 ⇒ 淘汰（最高精度，带可机检 witness）；
  ② **LLM 对抗生成**（`AdversarialVerifier.probe`）：假设答案错误、反向寻找
     反例或第一个错误步骤；`is_actionable`（**答案错**类，带具体位置/反例）⇒ 淘汰；
     `is_soft`（跳步 / 边界未讨论 / 题意形式偏差）⇒ **不淘汰**，只留痕（2026-10-20）。

判定纪律（防误杀，与既有对抗链同口径）：
  · 机检证伪以 `res.is_incorrect` 为准（证伪器内部已做"任何不确定 ⇒ 放行"）；
  · LLM 对抗以 `result.is_actionable` 为准（低置信"找到"在 prober 内部已过滤）；
  · 跳过 / 调用失败 / 异常 ⇒ **保留**候选（记为 skipped/failed，绝不因故障淘汰）；
  · 被证伪候选同时进 `ctx.audit_reject_feedback` 与 `ctx._falsified_answers`
    （后者被终选层消费，保持既有契约）。

观测：trace step=``adversarial_gate``，diag 键 ``adversarial_gate`` /
``adversarial_gate_rejected`` / ``adversarial_gate_events``。

五道链位置：4.0 规范化 → 4.1 自审 → **4.2 对抗证伪** → ③Lean 代回 → ④计算检测
→ ⑤投票。
"""
from __future__ import annotations

from .switch_registry import get_bool as _sw_get_bool

def _switch_enabled() -> bool:
    """读「五道链·第 2 道对抗证伪」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_falsify")
    except Exception:  # noqa: BLE001
        return True


def adversarial_gate_stage(self, ctx, tier: str) -> None:
    """4.2 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。

    注入点约定（与 4.7_lean 同款，便于单测注入桩）：
      · 证伪器：``getattr(self, "adv_gate_falsifier", None) or AnswerFalsifier(...)``
      · 对抗器：``getattr(self, "adv_verifier", None) or AdversarialVerifier(...)``
    """
    try:
        if not _switch_enabled():
            self.record(ctx, "adversarial_gate",
                        "4.2 对抗证伪：开关关闭（five_gate_falsify=0）")
            return
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            self.record(ctx, "adversarial_gate", "4.2 对抗证伪：候选池为空，跳过")
            return

        from .answer_falsifier import AnswerFalsifier
        from .adversarial_verifier import AdversarialVerifier

        _falsifier = getattr(self, "adv_gate_falsifier", None) or \
            AnswerFalsifier(self.client, self.config)
        _prober = getattr(self, "adv_verifier", None) or \
            AdversarialVerifier(self.client, self.config)
        prob = str(getattr(ctx, "problem", "") or "")

        kept, rejected, soft = [], [], []
        n_skipped, n_failed = 0, 0

        for c in cands:
            cid = getattr(c, "id", "?")
            # ① 机检证伪（LLM 证书 + SymPy 判定）
            _machine_rej = None
            try:
                res = _falsifier.falsify(ctx, c, problem=prob)
                if getattr(res, "is_incorrect", False):
                    _machine_rej = {
                        "by": "machine",
                        "reason": str(getattr(res, "reason", "") or "")[:200],
                        "witness": str(getattr(res, "witness", "") or "")[:200],
                        "oracle_type": str(getattr(res, "oracle_type", "") or ""),
                    }
            except Exception as _e_f:  # noqa: BLE001  故障绝不淘汰候选
                n_failed += 1
                self.record(ctx, "adversarial_gate",
                            "cid=%s 机检证伪异常（保留候选）: %s: %s"
                            % (cid, type(_e_f).__name__, str(_e_f)[:120]))

            # ② LLM 对抗生成（机检已判错则不再调用，省一次重证）
            _llm_rej = None
            if _machine_rej is None:
                try:
                    pr = _prober.probe(ctx, c, tier=tier)
                    if getattr(pr, "is_actionable", False):
                        _llm_rej = {
                            "by": "llm",
                            "error_type": str(getattr(pr, "error_type", "") or ""),
                            "confidence": float(
                                getattr(pr, "confidence", 0.0) or 0.0),
                            "feedback": str(pr.to_feedback() or "")[:600],
                        }
                    elif getattr(pr, "is_soft", False):
                        # 2026-10-20：过程性问题（跳步/边界未讨论/题意形式偏差）
                        #   不构成答案错误 ⇒ 放行 + 留痕，不进 rejected。
                        _st = str(getattr(pr, "error_type", "") or "") or "?"
                        soft.append({
                            "id": cid,
                            "error_type": _st,
                            "confidence": float(
                                getattr(pr, "confidence", 0.0) or 0.0),
                            "note": str(pr.to_feedback() or "")[:300],
                        })
                        self.record(ctx, "adversarial_gate",
                                    "cid=%s 仅过程瑕疵（%s）⇒ 不淘汰，放行"
                                    % (cid, _st))
                    elif getattr(pr, "skipped", ""):
                        n_skipped += 1
                        self.record(ctx, "adversarial_gate",
                                    "cid=%s 对抗探测跳过（保留）: %s"
                                    % (cid, pr.skipped))
                except Exception as _e_p:  # noqa: BLE001
                    n_failed += 1
                    self.record(ctx, "adversarial_gate",
                                "cid=%s 对抗探测异常（保留候选）: %s: %s"
                                % (cid, type(_e_p).__name__, str(_e_p)[:120]))

            _rej = _machine_rej or _llm_rej
            if _rej is None:
                kept.append(c)
                self.record(ctx, "adversarial_gate",
                            "cid=%s 未证实伪（放行）" % cid)
                continue

            _ans = str(getattr(c, "answer_norm", None)
                       or getattr(c, "answer", "") or "")[:160]
            rejected.append({"id": cid, "answer": _ans, **_rej})
            self.record(ctx, "adversarial_gate",
                        "cid=%s **被证伪**（%s）⇒ 判错淘汰：%s"
                        % (cid, _rej["by"],
                           (_rej.get("reason") or _rej.get("error_type") or "")[:200]))

        if rejected:
            ctx.candidates = kept
            ctx.adversarial_gate_rejected = list(
                getattr(ctx, "adversarial_gate_rejected", None) or []) + rejected
            _fb = []
            for r in rejected:
                if r["by"] == "machine":
                    _fb.append("[对抗证伪·机检] cid=%s: %s | 反例：%s"
                               % (r["id"], r.get("reason") or "", r.get("witness") or ""))
                else:
                    _fb.append("[对抗证伪·LLM] cid=%s: %s"
                               % (r["id"], r.get("feedback") or r.get("error_type") or ""))
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", None) or []) + _fb
            # 既有契约：被证伪答案进 `_falsified_answers`（终选层消费）
            try:
                _fa = list(getattr(ctx, "_falsified_answers", None) or [])
                _fa += [r["answer"] for r in rejected if r["by"] == "machine"]
                ctx._falsified_answers = _fa
                _meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
                _meta["falsified_answers"] = _fa
                ctx.metadata = _meta
            except Exception:  # noqa: BLE001  元数据写入失败不影响淘汰结果
                pass

        if soft:
            ctx.adversarial_gate_soft = list(
                getattr(ctx, "adversarial_gate_soft", None) or []) + soft
        ctx.adversarial_gate = {
            "n": len(cands),
            "n_soft": len(soft),
            "soft_ids": [s["id"] for s in soft],
            "n_rejected": len(rejected),
            "n_machine": sum(1 for r in rejected if r["by"] == "machine"),
            "n_llm": sum(1 for r in rejected if r["by"] == "llm"),
            "n_skipped": n_skipped,
            "n_failed": n_failed,
            "rejected_ids": [r["id"] for r in rejected],
        }
        self.record(
            ctx, "adversarial_gate",
            "4.2 对抗证伪：%d 候选 ⇒ 证伪淘汰 %d（机检 %d / LLM %d）"
            "（跳过 %d、故障 %d、过程瑕疵放行 %d）"
            % (len(cands), len(rejected),
               ctx.adversarial_gate["n_machine"], ctx.adversarial_gate["n_llm"],
               n_skipped, n_failed, len(soft)))

        try:
            from .orchestrator__verify import _pool_empty_fallback as _pef
            _pef(self, ctx, "4.2_falsify")
        except Exception:  # noqa: BLE001  兜底检查失败不影响主流程
            pass
    except Exception as _e:  # noqa: BLE001  增益环节绝不阻断主链
        self.record(ctx, "adversarial_gate",
                    f"4.2 对抗证伪异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
