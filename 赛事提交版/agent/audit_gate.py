# -*- coding: utf-8 -*-
"""AuditGate —— 答案审核闸门（取代 Lean 系在检测链中的全部作用）。

设计背景
========
平台无 Lean 可执行文件（历史归因实证），lean_gate / lean_pre_verifier /
answer_oracle.verify_proof 在平台上全部 unknown 空转：只付时间不审核，
最终答案闸门形同虚设。本模块把"客观审核"从 Lean 迁移到：

  Level 0  程序硬核验（0 LLM）  DeterministicChecker.check_answer
                                  （答案代回题干数值回验 / SymPy 判定）
  Level 1  程序反例证伪（0 LLM） search_counterexample
                                  （对非数值答案做数值采样反例挑战）
  Level 2  LLM rubric 判分       verifier._vote_rubric / 证明步骤审核
                                  （JSON prefill 秒级，错因定位驱动 revise）
  Level 3  独立重算一致性        verifier._playoff_recheck（低温重解对比）

职责边界（只审不答）
====================
- 审：对候选解答与最终答案产出裁决（verdict/feedback/evidence）；
- 不答：不生成答案、不改写题目、不做规划/子目标、不产出 Lean 代码。

硬否决优先、宁 unknown 不误杀：
- Level0 fail / Level1 hard_fail → 客观证据，硬否决（可触发换候选/重做）；
- Level2 rubric B（LLM 同源，可能误伤）→ 仅当置信度高才采纳，否则放行；
- 全部候选被否 → 回退保留原候选（保证有输出，不损失分数，镜像 LeanGate 降级）。

对外契约
========
- ``confirm_understanding(ctx) -> dict``   题前理解确认（默认跳过省时）
- ``audit_candidates(ctx, tier, candidates) -> (kept, feedbacks)``
- ``gate_final_answer(ctx, tier, answer, reasoning) -> bool``

2026-09-06 依据《检测链重构_去Lean化_三方案_0905.md》方案二实现。
"""
from __future__ import annotations

import logging

from .base import BaseAgent, TaskContext
from .deterministic import DeterministicChecker

logger = logging.getLogger("MathPilot.AuditGate")


class AuditGate(BaseAgent):
    """答案审核闸门：Level0-3 多级瀑布，只审不答。"""

    name = "AuditGate"

    def __init__(self, client, config, budget=None):
        super().__init__(client, config)
        self.budget = budget
        self._verifier = None

    # ------------------------------------------------------------------
    # 内部：懒加载复用 VerifierAgent（rubric/挑战/playoff/证明步骤验证）
    # ------------------------------------------------------------------
    @property
    def _verifier_inst(self):
        if self._verifier is None:
            from .verifier import VerifierAgent
            self._verifier = VerifierAgent(self.client, self.config)
        return self._verifier

    # ------------------------------------------------------------------
    # 公共：轨迹记录
    # ------------------------------------------------------------------
    def _record_ctx(self, ctx: TaskContext, data: dict) -> None:
        try:
            ctx.audit_gate.append(data)
        except Exception:  # noqa: BLE001
            try:
                ctx.audit_gate = [data]
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 主入口（满足 BaseAgent 抽象接口；按需分发到三个审核位）
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext, stage: str = "final",
            candidates: list | None = None) -> dict:
        """统一入口。``stage``: ``candidates``(3.6) / ``final``(6.5) /
        ``understanding``(2.6)；orchestrator 亦可直接调专用方法。
        """
        if stage == "candidates":
            kept, fb = self.audit_candidates(
                ctx, getattr(ctx, "tier", "standard") or "standard",
                candidates or [])
            return {"kept": kept, "feedbacks": fb}
        if stage == "understanding":
            return self.confirm_understanding(ctx)
        ok = self.gate_final_answer(
            ctx, getattr(ctx, "tier", "standard") or "standard",
            getattr(ctx, "final_response", "") or "")
        return {"ok": ok}

    # ------------------------------------------------------------------
    # 2.6 位：题前理解确认（默认跳过；开启时 LLM 题意复核，不阻断）
    # ------------------------------------------------------------------
    def confirm_understanding(self, ctx: TaskContext) -> dict:
        """确认对题意的理解（题型/未知量/条件），失败注入 revise_feedback。

        平台去 Lean 后原 preverify（Lean 形式化编译）不再执行；本题前复核为
        可选的 LLM 轻量替代——默认关闭（省时），由下游 revise/重理解兜底。
        """
        if not getattr(self.config, "audit_confirm_understanding", False):
            self._record_ctx(ctx, {"step": "confirm_understanding",
                                   "skipped": "disabled"})
            return {"skipped": True}
        if ctx.is_time_critical():
            self._record_ctx(ctx, {"step": "confirm_understanding",
                                   "skipped": "time_critical"})
            return {"skipped": True}
        try:
            sys_p = ("你是题意确认器。复述下面题目的：①题型（代数/几何/组合/"
                     "数论/证明等）②未知量类型③关键条件。若题目信息不足以求解，"
                     "指出缺失。输出 JSON：{\"understood\":true|false,"
                     "\"restatement\":\"...\",\"gaps\":[\"...\"]}")
            from utils.prefill import prefill_messages, stitch
            raw = self.llm(ctx, prefill_messages(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": ctx.problem[:1500]}], '{"'),
                           0.0, 4096)
            if not raw:
                return {"understood": True, "degraded": "empty_llm"}
            raw = stitch('{"', raw)
            import re
            m = re.search(r"\{[\s\S]*\}", raw)
            parsed = None
            if m:
                import json
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    parsed = None
            if not isinstance(parsed, dict):
                self._record_ctx(ctx, {"step": "confirm_understanding",
                                       "degraded": "parse_failed"})
                return {"understood": True, "degraded": "parse_failed"}
            if not parsed.get("understood", True):
                gaps = parsed.get("gaps") or []
                msg = ("⚠️ 题意理解存疑：" + ("；".join(gaps) if gaps
                       else "模型未能确认题意"))
                ctx.revise_feedback = list(ctx.revise_feedback) + [msg]
            self._record_ctx(ctx, {"step": "confirm_understanding",
                                   "result": parsed})
            return parsed
        except Exception as e:  # noqa: BLE001  复核失败不阻断主流程
            logger.warning("AuditGate: 题意复核异常（放行）: %s", e)
            self._record_ctx(ctx, {"step": "confirm_understanding",
                                   "degraded": "exception"})
            return {"understood": True, "degraded": "exception"}

    # ------------------------------------------------------------------
    # 3.6 位：候选审核（顶替原 lean_filter）
    # ------------------------------------------------------------------
    def audit_candidates(self, ctx: TaskContext, tier: str,
                         candidates: list) -> tuple[list, list]:
        """对候选做客观审核，返回 ``(kept, feedbacks)``。

        Level0 程序硬核验：deterministic fail → 淘汰并收集反馈；
        全部候选被否 → 回退保留原候选（宁 unknown 不误杀）。
        证明题且开启 rubric 时叠加 Level2 步骤/结构化判分（B 且高置信才淘汰）。
        """
        kept = list(candidates)
        feedbacks: list[str] = []
        if not candidates:
            return kept, feedbacks
        ctx.audit_gate = getattr(ctx, "audit_gate", []) or []

        domain = getattr(ctx, "domain", "") or ""
        qtype = getattr(ctx, "question_type", "") or ""
        is_proof = (domain in ("证明", "证明题") or qtype == "证明题")
        use_rubric = bool(getattr(self.config, "use_rubric", False))

        n_fail = 0
        rejected: list[tuple] = []
        for cand in candidates:
            # 时间保护：单题接近 deadline → 提前退出逐候选审核（Level0 数值代回不再
            # 触发），与下方 rubric 分支的 is_time_critical 口径一致；留痕便于区分
            # "因时间跳过" 与 "根本没触发"。
            if ctx.is_time_critical():
                self.record(ctx, "audit_gate_timeout",
                            f"时间临界，提前退出候选审核：已否决 {n_fail}/{len(candidates)}")
                break
            ans = (cand.get("answer", "") if isinstance(cand, dict)
                   else getattr(cand, "answer", ""))
            if not ans or not str(ans).strip():
                continue
            entry = {"step": "candidate_audit", "tier": tier,
                     "cand_id": (cand.get("id", "?") if isinstance(cand, dict)
                                 else getattr(cand, "id", "?")),
                     "answer": str(ans)[:60], "verdict": "unknown"}
            # Level 0：程序硬核验
            try:
                det = DeterministicChecker().check_answer(
                    ctx, ctx.problem or "", str(ans), domain or "")
                entry["deterministic"] = det.get("verdict")
            except Exception as e:  # noqa: BLE001
                det = {"verdict": "unknown", "evidence": f"异常: {str(e)[:80]}"}
                entry["deterministic"] = "unknown"
            if det.get("verdict") == "fail":
                n_fail += 1
                entry["verdict"] = "incorrect"
                rejected.append((cand, det))
            # Level 2：证明题 rubric 结构化判分（LLM，高置信 B 才采纳）
            elif is_proof and use_rubric and not ctx.is_time_critical():
                try:
                    rub = self._verifier_inst._vote_one_rubric(
                        ctx, ctx.problem or "", str(ans))
                    entry["rubric"] = (rub or {}).get("verdict")
                    if rub and str(rub.get("verdict", "B")).upper() == "B":
                        try:
                            conf = float(rub.get("confidence", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            conf = 0.0
                        if conf >= float(getattr(
                                self.config, "audit_rubric_reject_conf", 0.85)):
                            n_fail += 1
                            entry["verdict"] = "incorrect"
                            entry["rubric_conf"] = conf
                            rejected.append((cand, rub))
                except Exception as e:  # noqa: BLE001
                    entry["rubric"] = "exception"
                    logger.debug("AuditGate: rubric 审核异常（放行）: %s", e)
            self._record_ctx(ctx, entry)

        # 全部被否 → 回退保留（宁 unknown 不误杀，绝不整批清空）
        if rejected and n_fail < len(candidates):
            kept = [c for c in candidates
                    if not any(c is rc for rc, _ in rejected)]
            for rc, evidence in rejected:
                feedbacks.append(
                    f"[AuditGate 客观审核] 候选被程序硬核验否决："
                    f"{str(evidence.get('evidence', ''))[:120]}")
            self.record(ctx, "audit_gate",
                        f"审核淘汰 {len(rejected)}/{len(candidates)} 候选，"
                        f"保留 {len(kept)}")
        elif rejected:
            self.record(ctx, "audit_gate",
                        "全部候选被客观否决 → 回退保留（宁 unknown 不误杀）")
            kept = list(candidates)
            feedbacks = []
        else:
            self.record(ctx, "audit_gate",
                        f"候选审核通过 {len(candidates)}（无程序否决）")
        return kept, feedbacks

    # ------------------------------------------------------------------
    # 6.5 位：最终答案闸门（顶替原 lean_gate.gate_final_answer）
    # ------------------------------------------------------------------
    def gate_final_answer(self, ctx: TaskContext, tier: str,
                          answer: str, reasoning: str = "") -> bool:
        """对最终答案做 Level0-2 审核，返回 ``True`` 放行 / ``False`` 打回。

        - 空答案 → True（formatter 已兜底，交由上层处理）
        - Level0 deterministic fail / Level1 反例命中 → False（客观硬否决，
          6.5 rework 循环据此换候选/重做）
        - Level2 rubric B（高置信）→ False；其余 → True（宁 unknown 不误杀）
        - 任何异常 → True（绝不让审核缺陷阻断输出）
        """
        entry = {"step": "final_gate", "tier": tier,
                 "answer": str(answer)[:80], "verdict": "pass"}
        if not answer or not str(answer).strip():
            entry["degraded"] = "empty_answer"
            self._record_ctx(ctx, entry)
            return True
        domain = getattr(ctx, "domain", "") or ""
        qtype = getattr(ctx, "question_type", "") or ""
        is_proof = (domain in ("证明", "证明题") or qtype == "证明题")
        use_challenge = bool(getattr(self.config, "use_challenge", False))
        use_rubric = bool(getattr(self.config, "use_rubric", False))

        # Level 0：程序硬核验（0 LLM、可复现、客观）
        try:
            det = DeterministicChecker().check_answer(
                ctx, ctx.problem or "", str(answer), domain or "")
            entry["deterministic"] = det.get("verdict")
            if det.get("verdict") == "fail":
                entry["verdict"] = "reject"
                entry["reason"] = str(det.get("evidence", ""))[:200]
                self._record_ctx(ctx, entry)
                return False
        except Exception as e:  # noqa: BLE001
            logger.debug("AuditGate: 最终答案确定性核验异常（放行）: %s", e)

        # Level 1：反例挑战（仅非数值答案；数值答案已由 Level0 代入覆盖）
        if use_challenge:
            chal = self._verifier_inst._challenge_counterexample(
                ctx, ctx.problem or "", reasoning or answer, str(answer))
            entry["challenge"] = chal
            if chal.get("hard_fail"):
                entry["verdict"] = "reject"
                entry["reason"] = str(chal.get("evidence", ""))[:200]
                self._record_ctx(ctx, entry)
                return False

        # Level 2：rubric 结构化判分（LLM 同源，高置信 B 才打回）
        if use_rubric and not ctx.is_time_critical():
            try:
                rub = self._verifier_inst._vote_one_rubric(
                    ctx, ctx.problem or "", reasoning or answer)
                entry["rubric"] = (rub or {}).get("verdict")
                if rub and str(rub.get("verdict", "B")).upper() == "B":
                    try:
                        conf = float(rub.get("confidence", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        conf = 0.0
                    if conf >= float(getattr(
                            self.config, "audit_rubric_reject_conf", 0.85)):
                        entry["verdict"] = "reject"
                        entry["rubric_conf"] = conf
                        reason = str(rub.get("reason", ""))[:200]
                        entry["reason"] = reason
                        step = rub.get("step_index")
                        err = rub.get("error_type", "")
                        detail = "；".join(
                            x for x in
                            ((f"步骤{step}" if step is not None else ""),
                             str(err) if err and err != "无" else "",
                             reason) if x)
                        entry["feedback"] = (detail or "rubric 判 B")[:300]
                        self._record_ctx(ctx, entry)
                        return False
            except Exception as e:  # noqa: BLE001
                logger.debug("AuditGate: 最终答案 rubric 审核异常（放行）: %s", e)

        entry["verdict"] = "pass"
        if is_proof and use_rubric and not ctx.is_time_critical():
            # 证明题：无程序否决、rubric 未高置信拒绝 → 放行（投票共识已把关）
            entry["note"] = "证明题：无客观否决，交由投票共识"
        self._record_ctx(ctx, entry)
        return True
