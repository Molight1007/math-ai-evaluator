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
import os
import re
from concurrent.futures import ThreadPoolExecutor

from agent.base import BaseAgent, Budget, TaskContext
from tools.lean_local.lean_bridge import (
    LeanBridge, hint_for_compile_error, lean_parallelism, mcp_available)

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
    def _enabled(self, tier: str, domain: str, question_type: str = "") -> bool:
        """判断 Lean 门禁是否对本题启用。

        2026-08-30（#45 移除题型分流）：原逻辑第 60 行为
        ``if domain not in ("证明", "证明题"): return False``，把**计算题整体挡在
        Lean 之外**。老师指出：计算题同样含证明成分、且主要依赖依赖链，
        不该被排除在 Lean / 定理检索之外。故移除题型硬过滤，改为
        **「题型 × 档位」两级控制**：

        ==========  ===================================================
        题型        条件
        ==========  ===================================================
        证明题      全档启用（沿用 ``lean_gate_all_proofs``，False 时退回仅 deep）
        非证明题    仅 deep 档，且受 ``lean_gate_nonproof`` 总开关控制
        ==========  ===================================================

        非证明题限制在 deep 档的原因：Lean 编译约 21s/次（#43 归因），
        而 deep 档有 25% 配额闸封顶，不会让计算题的编译拖垮全卷时间预算。
        若实测超时，把 ``lean_gate_nonproof`` 置 False 即可一键回退。

        2026-09-01 用户要求「所有题目都要用到 Lean」：
        - 证明题判定从「仅 domain」扩展为「domain 或 question_type == 证明题」。
          此前题库 PB 题 domain 是 Algebra（元数据），is_proof 恒 False →
          Lean 门禁 0 触发（A_base/G 组 17 题 compile_valid 全 0 的根因之一）。
        - 非证明题（计算/解答）也启用 Lean，但走轻量路径：只验证最终答案
          （norm_num/ring 结果验证，约 5-21s），不整题形式化，控制时间开销。
        """
        cfg = self.config
        if not getattr(cfg, "enable_lean_verify", True):
            return False

        is_proof = (domain in ("证明", "证明题")
                    or question_type == "证明题")
        if is_proof:
            # v2.8：扩展到全部证明题（含 standard 档）；旧行为（仅 deep）由
            # lean_gate_all_proofs=False 保留。
            if not getattr(cfg, "lean_gate_all_proofs", True) and tier != "deep":
                return False
            return True

        # 非证明题（计算/解答等）：2026-09-01 起全档启用（用户要求所有题过 Lean）。
        # 旧行为（仅 deep 档）由 lean_gate_nonproof_deep_only=True 保留。
        if not getattr(cfg, "lean_gate_nonproof", True):
            return False
        if getattr(cfg, "lean_gate_nonproof_deep_only", False) and tier != "deep":
            return False
        return True

    @property
    def strict(self) -> bool:
        return bool(getattr(self.config, "lean_gate_strict", False))

    @staticmethod
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

    @property
    def _unknown_stop(self) -> int:
        """连续 N 个 unknown 后止损（B，2026-09-07）：剩余候选不再逐个
        整题 verify。同题同翻译器，连续 unknown = 验证器对该题失效（翻译/
        形式化失败有传染性），再验也只是重复烧 LLM+编译时间；PB-002 实证
        六候选整题 verify 563s 全 unknown 白烧 9 分钟。0 = 关闭（逐候选全验）。"""
        return int(getattr(self.config, "lean_gate_unknown_stop", 2) or 0)

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
    # 候选级并行预取（2026-09-13）
    # ------------------------------------------------------------------
    def _prefetch_reports(self, ctx: TaskContext, candidates: list,
                          bridge, is_proof: bool, domain: str):
        """波次并行预取候选的 Lean 报告；返回与 ``candidates`` 等长的 list。

        元素为 ``(report, exc)``；``None`` = "该候选未预取，由原循环按原路径验证"。

        设计约束（全部为了不改变原语义）：
        - **纯计算**：不改 ctx、不写 kept/feedbacks，所有决策与埋点仍留给原循环；
        - 逐波提交（波宽 = 并行度 K），每波后判**时间护栏**与**空转止损**（与原
          循环同一判据），命中即停 —— 未预取的候选走原串行路径；
        - 并行度 <=1 / ``LEAN_GATE_PARALLEL=0`` → 返回 None：完全旧路径。

        依据：候选级验证彼此独立（各写各的 .lean、各要一份 report），原为
        6 候选 ×20–38s 全串行；并行后压缩到 ⌈N/K⌉ 波。
        """
        import time as _t
        if os.environ.get("LEAN_GATE_PARALLEL", "1") == "0":
            return None
        # 只在 MCP 通道真可用时并行：bridge 是 `lake env lean` 全量编译，
        # 并行收益未验证且同目录并发 lake 有额外风险 → 保持旧的串行行为。
        if not mcp_available():
            logger.info("LeanGate: MCP 通道不可用（无 venv/代理）→ 候选验证保持串行")
            return None
        try:
            _k = int(lean_parallelism())
        except Exception:  # noqa: BLE001
            return None
        if _k <= 1 or len(candidates) < 2:
            return None
        _stop = self._unknown_stop
        timeout = float(getattr(self.config, "lean_timeout", 60.0))
        _hard = float(getattr(self.config, "max_time_per_question", 1200))
        out: list = [None] * len(candidates)

        def _one(_cand):
            """只做「算 report」：入参与原循环逐字相同，异常原样带回主线程重抛。"""
            try:
                if is_proof:
                    return bridge.verify(
                        problem=ctx.problem or "",
                        reasoning=_cand.reasoning or "",
                        domain=domain, timeout=timeout), None
                return bridge.verify_answer(
                    problem=ctx.problem or "",
                    reasoning=_cand.reasoning or "",
                    answer=_cand.answer or "",
                    domain=domain, timeout=timeout), None
            except Exception as _e:  # noqa: BLE001
                return None, _e

        i, n, _streak = 0, len(candidates), 0
        while i < n:
            # 时间护栏（与原循环同口径）：剩余 < 45s 即停止取件
            if (ctx.start_time >= 10**8
                    and (ctx.start_time + _hard) - _t.time() < 45.0):
                logger.info("LeanGate: 并行预取停止（剩余时间不足 45s）")
                break
            wave = list(enumerate(candidates))[i:i + _k]
            _tk = _t.perf_counter()
            try:
                with ThreadPoolExecutor(max_workers=len(wave)) as _ex:
                    _res = list(_ex.map(lambda p: _one(p[1]), wave))
            except Exception as _we:  # noqa: BLE001  线程池异常 → 整体退回串行
                logger.warning("LeanGate: 并行预取异常，退回串行: %s",
                               str(_we)[:160])
                return None
            _unk = 0
            for (_idx, _cand), (_r, _e) in zip(wave, _res):
                out[_idx] = (_r, _e)
                if _r is None or getattr(_r, "verdict", "") == "unknown":
                    _unk += 1
            _streak = _streak + _unk if _unk == len(wave) else 0
            logger.info("LeanGate: 并行预取 %d 个候选耗时 %.1fs（K=%d）",
                        len(wave), _t.perf_counter() - _tk, _k)
            i += len(wave)
            # 空转止损（与原循环同判据）：整波 unknown → 剩余不再预取
            if _stop > 1 and _streak >= _stop and n > _stop + 1:
                logger.info("LeanGate: 连续 %d 个候选 unknown，停止预取剩余候选",
                            _streak)
                break
        return out

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
        qtype = getattr(ctx, "question_type", "")
        # 按题豁免（2026-09-10）：答案非数学对象 → Lean 整题跳过（调用方
        # orchestrator 已把这类题改路由 AuditGate，此处是防御性兜底）。
        _na, _na_why = self._not_applicable(ctx)
        if _na:
            self._record_ctx(ctx, {"enabled": False, "skipped": "not_applicable",
                                   "reason": _na_why, "tier": tier,
                                   "domain": domain, "question_type": qtype,
                                   "candidates": len(candidates)})
            return kept, feedbacks
        if not self._enabled(tier, domain, qtype):
            self._record_ctx(ctx, {"enabled": False, "tier": tier,
                                   "domain": domain, "question_type": qtype,
                                   "candidates": len(candidates)})
            return kept, feedbacks

        # 2026-09-02 老师强调：Lean 答案检查一定不能跳过。
        # 时间保护改用 **1200s hard 硬顶** 而非被 soft_budget 收紧的 deadline——
        # standard 档 soft=540s，题实际跑 560s（超 soft 才结束），若用
        # ctx.time_remaining()（看 soft deadline）闸门必然 time_critical 跳过。
        # 单答案验证 5-21s 相对 1200s 硬顶完全可负担，只有快撞硬顶才放行。
        # 2026-09-04 审核修复：start_time 为伪值（<1e8，测试 fixture 常用 0）
        # 时该判断 `start_time + 1200 - now < 2` 恒 True → 整批误降级放行
        # （lean_gate 5 个测试全挂）。伪值视同无硬顶，与 base.time_remaining
        # / llm() 的 deadline<1e8 口径统一。
        import time as _t
        _hard_deadline = ctx.start_time + float(
            getattr(self.config, "max_time_per_question", 1200))
        if ctx.start_time >= 10**8 and _hard_deadline - _t.time() < 2:
            self._record_ctx(ctx, {"enabled": True, "degraded": "time_critical",
                                   "tier": tier, "domain": domain})
            return kept, feedbacks
        # 2026-09-03 老师：比赛无次数上限。删 budget 强制（保留 spend 记账作指标）。

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
        is_proof = (domain in ("证明", "证明题") or qtype == "证明题")
        _unknown_streak = 0  # B（2026-09-07）：连续 unknown 计数 → 空转止损
        _stop = self._unknown_stop
        # 2026-09-13：候选级验证**波次并行预取**（并行度 >1 时启用，开关
        # LEAN_GATE_PARALLEL，默认跟随 LEAN_MCP_WORKERS）。
        # 原循环逻辑一行不改：只把"算 report"这一段挪进并行批次（纯计算），
        # 决策 / kept / feedbacks / ctx 埋点**全部仍在主线程按原顺序执行** ——
        # 并发面收敛到最小，行为与串行版逐候选一致。
        _pre = self._prefetch_reports(ctx, candidates, bridge, is_proof, domain)
        for _idx, cand in enumerate(candidates):
            # 逐候选时间护栏（2026-09-11，依据 审计_112题Lean阻断路径全量排查_0910.md）
            # 问题：本循环此前**无时间检查**，而 72/81 题有 6 个候选，6 × 20–38s =
            #   120–230s，可能把该题推过 1200s 硬墙 → 反过来饿死 6.5 最终闸门
            #   （实测 14/81 = 17.3% 的题在 6.5 因 time_critical 跳过 Lean）。
            # 口径：剩余 < 45s（≈ 一次编译 + 余量）即停止验剩余候选，按"未验"降级
            #   保留（不淘汰，与 lenient 一致），记 degraded="time_budget" 便于统计。
            if ctx.start_time >= 10**8 and (_pre is None or _pre[_idx] is None):
                _left_budget = (ctx.start_time + float(getattr(
                    self.config, "max_time_per_question", 1200))) - _t.time()
                if _left_budget < 45.0:
                    self._record_ctx(ctx, {
                        "id": getattr(cand, "id", None), "verdict": "unknown",
                        "lean_valid": False, "degraded": "time_budget",
                        "error": None,
                        "reason": f"剩余 {_left_budget:.0f}s < 45s，保留候选不验"
                                  f"（护 6.5 最终闸门）",
                    })
                    kept.append(cand)
                    continue
            entry = {
                "id": cand.id,
                "verdict": "unknown",
                "lean_valid": False,
                "degraded": None,
                "error": None,
            }
            # B：验证空转止损 —— 已连续 _stop 个 unknown（翻译/形式化失效传染），
            # 剩余候选不再逐个整题 verify（PB-002 实证 6 候选 563s 全 unknown 白烧）。
            # 剩余候选按当前 unknown 策略处理：strict 拒（不进 kept）/默认 lenient 保候选。
            if _stop > 1 and _unknown_streak >= _stop and len(candidates) > _stop + 1:
                entry["degraded"] = "verify_stop"
                entry["reason"] = (f"连续 {_unknown_streak} 个候选 Lean 验证 unknown"
                                   "（验证器失效），止损跳过整题 verify")
                if self.strict:
                    feedbacks.append(
                        f"[Lean 硬验证] 候选 {cand.id} 跳过验证（unknown 止损，"
                        "strict 保守拒绝）")
                    # strict 模式：不进 kept
                else:
                    kept.append(cand)
                self._record_ctx(ctx, entry)
                continue
            try:
                # 2026-09-01 用户要求「所有题目都要用到 Lean」两阶段流程：
                # 阶段二答案审核 —— 证明题走整题形式化 verify（原逻辑），
                # 非证明题（解答/计算）走轻量 verify_answer（norm_num/ring
                # 验证最终答案与关键计算，5-21s，避免整题形式化拖垮时间预算）。
                # 2026-09-13：已并行预取的候选直接取结果（异常原样重抛 → 落到下方
                # degraded 分支，与串行版逐字一致）；未预取（预算不足 / 已止损 /
                # 并行关闭）的候选照旧当场串行验证。
                if _pre is not None and _pre[_idx] is not None:
                    report, _pre_exc = _pre[_idx]
                    if _pre_exc is not None:
                        raise _pre_exc
                elif is_proof:
                    report = bridge.verify(
                        problem=ctx.problem or "",
                        reasoning=cand.reasoning or "",
                        domain=domain,
                        timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                    )
                else:
                    report = bridge.verify_answer(
                        problem=ctx.problem or "",
                        reasoning=cand.reasoning or "",
                        answer=cand.answer or "",
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
                        # 2026-08-30 修 bug：add_used_theorems / note_compile_valid
                        # 是 TaskContext 的静态方法，原代码误用 self.（LeanGate 无此方法）
                        # 调用，每次都抛 AttributeError 被下方 except 吞掉 →
                        # proof_valid 候选被当成"验证异常"降级放行，导致
                        # used_theorems / compile_valid / 跨题定理记忆全部从未写入。
                        BaseAgent.add_used_theorems(ctx, used_names)
                if report is None:
                    entry["degraded"] = "no_report"
                    _unknown_streak += 1
                    kept.append(cand)          # 无报告 → 降级放行
                elif report.verdict in ("proof_valid", "answer_valid"):
                    entry["verdict"] = report.verdict
                    entry["lean_valid"] = True
                    _unknown_streak = 0        # 验证器正常工作（出绿点），计数清零
                    BaseAgent.note_compile_valid(ctx)  # 真正的形式化验证成功
                    # #44 埋点第四维：定理「最终被采用」以 Lean 编译通过为准。
                    # 检索命中 ≠ 采用（老师 #46：命中不等于编译通过），
                    # 检索侧无法判断定理是否真的进了证明，只有这里能确认。
                    # 注：仅证明题整题形式化（is_proof）有"定理采用"语义；
                    # 非证明题的 example 答案验证无定理名，跳过避免污染统计/记忆。
                    if is_proof:
                        self._note_theorems_adopted(used_names)
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
                        from agent.answer_oracle import AnswerOracle
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
                    _unknown_streak = 0   # 编译器明确判错 = 验证器正常，计数清零
                else:  # unknown
                    entry["verdict"] = "unknown"
                    _unknown_streak += 1
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
    # 最终答案闸门（2026-09-02 老师需求：Lean 拦错误逻辑、提高优先级）
    # ------------------------------------------------------------------
    def gate_final_answer(self, ctx: TaskContext, tier: str,
                          answer: str, reasoning: str = "") -> bool:
        """对**被选中提交的最终答案**做一次 Lean 验证（5-21s）。

        与原 apply()（全候选过滤，8×10s 常因 time_critical 整批跳过）不同：
        只验 1 个答案 → 单次成本可负担 → 不再因时间紧张跳过 Lean 把关。
        - verdict in (proof_valid, answer_valid) → True（通过放行）
        - proof_invalid / 严格拒绝 → False（调用方换候选）
        - 环境缺失 / 异常 → 降级放行 True（不因 Lean 环境误伤答案）
        """
        if not answer or not answer.strip():
            self._record_ctx(ctx, {"step": "final_gate", "gate": "final_answer",
                                   "tier": tier, "skipped": "empty_answer"})
            return True
        # 按题豁免（2026-09-10）：答案非数学对象 → Lean 无法形式化核验，跳过。
        # 调用方 orchestrator 6.5 已把这类题改路由 AuditGate（LLM 判分链），
        # 此处是防御性兜底：绝不因 Lean 形式化不了就把客观题的答案判死。
        _na, _na_why = self._not_applicable(ctx)
        if _na:
            self._record_ctx(ctx, {"step": "final_gate", "gate": "final_answer",
                                   "tier": tier, "skipped": "not_applicable",
                                   "reason": _na_why})
            return True
        domain = getattr(ctx, "domain", "")
        qtype = getattr(ctx, "question_type", "")
        is_proof = (domain in ("证明", "证明题") or qtype == "证明题")
        entry = {"step": "final_gate", "gate": "final_answer", "tier": tier,
                 "is_proof": is_proof, "answer": answer[:80]}
        # 2026-09-02 老师强调：Lean 答案检查一定不能跳过。
        # 时间检查必须用 **1200s hard 硬顶**（不是 ctx.time_remaining 看的 soft
        # deadline）——standard 档 soft=540s，题跑 560s 超 soft 才结束，用 soft
        # deadline 算剩余必然 <2s 全跳（wrong10b 实测 5/10 题因此跳过）。
        # 2026-09-04 审核修复：start_time 伪值（<1e8）视同无硬顶（同 apply()）。
        import time as _t2
        if (ctx.start_time >= 10**8
                and ctx.start_time + float(getattr(self.config,
                                                   "max_time_per_question", 1200))
                - _t2.time() < 2):
            entry["degraded"] = "time_critical"
            self._record_ctx(ctx, entry)
            return True
        # 2026-09-02 老师强调：Lean 是最后保证，**不受 LLM 调用次数预算限制**。
        # 2026-09-03 老师：比赛无次数上限。删 budget 强制——base.py llm() 入口
        # 已删除 can_spend 检查，bridge 内部 _llm_call 也不再强制。Lean 是
        # 最后保证，让它有需要多少次 LLM 调用就跑多少次。
        bridge = self._bridge_inst
        if bridge is None or not bridge.lean_available:
            entry["degraded"] = "env_unavailable"
            self._record_ctx(ctx, entry)
            return True
        try:
            if is_proof:
                report = bridge.verify(
                    problem=ctx.problem or "",
                    reasoning=reasoning or answer,
                    domain=domain,
                    timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                )
            else:
                report = bridge.verify_answer(
                    problem=ctx.problem or "",
                    reasoning=reasoning or answer,
                    answer=answer,
                    domain=domain,
                    timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                )
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:200]
            entry["degraded"] = "exception_lenient"
            self._record_ctx(ctx, entry)
            return True
        if report is None:
            entry["degraded"] = "no_report"
            self._record_ctx(ctx, entry)
            return True
        if report.verdict in ("proof_valid", "answer_valid"):
            entry["verdict"] = report.verdict
            entry["lean_valid"] = True
            BaseAgent.note_compile_valid(ctx)
            self._record_ctx(ctx, entry)
            return True
        if report.verdict == "proof_invalid":
            entry["verdict"] = "proof_invalid"
            entry["lean_valid"] = False
            msg = "Lean 编译/逻辑错误"
            try:
                from agent.answer_oracle import AnswerOracle
                structured = AnswerOracle.findings_to_feedback(
                    getattr(report, "findings", []) or [])
                if structured:
                    msg = structured
                elif getattr(report, "suggestion", ""):
                    msg = report.suggestion
            except Exception:  # noqa: BLE001
                msg = report.suggestion or str(
                    (report.findings or [None])[0])[:400]
            # 2026-09-12：截断由 200 → 400。原因：`desc` 现在会在末尾追加
            # 「修法提示」（`hint_for_compile_error`），若仍按 200 截断，**可操作
            # 的修法会被切掉**，只剩 LLM 的定性描述 —— 与本次修复目的相悖。
            entry["feedback"] = msg[:400]
            self._record_ctx(ctx, entry)
            return False
        # 2026-09-03 老师指令："当答案无法被验证或标记为未知时，必须默认拒绝
        # 而非放行"。unknown（翻译失败/验证无法判定/自证嫌疑）→ 一律拒绝，
        # 让 6.5 步换候选/重生成（校验不了就不许裸奔输出）。
        # A1（2026-09-12）：加开关（**默认仍是老师要求的严格拒绝**）。
        # 依据：平台实测 strict_reject 17 次、verdict 100% unknown，6.5 因此
        # 白烧 ~1520s，而"拒绝后仍输出某答案"→ 只烧时间不改输出。开关用于
        # 量化严格拒绝的真实代价（关掉做 A/B，用数据决定是否调整）。
        if os.environ.get("LEAN_GATE_STRICT_UNKNOWN", "1") == "0":
            entry["degraded"] = "lenient_unknown"
            entry["feedback"] = ("Lean 无法判定（unknown）→ 按开关配置**弃权放行**"
                                 "（LEAN_GATE_STRICT_UNKNOWN=0，用于 A/B 对照）")
            self._record_ctx(ctx, entry)
            return True
        entry["verdict"] = "unknown"
        entry["degraded"] = "strict_reject"
        # 2026-09-12：在方向性要求之外，附上**具体编译错误 + 按错误类型给的修法**。
        # 原文案只说"锚定题目数值与条件"，模型无从知道验证代码错在哪一行（与 2.6
        # 实测「2 轮重试 0 成功」同源问题：反馈不可操作）。
        _err6 = str(entry.get("error") or entry.get("reason") or "")
        _hint6 = hint_for_compile_error(_err6)
        entry["feedback"] = (
            "Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。"
            "禁止放行裸答案——请重写验证代码，锚定题目数值与条件。"
            + (("\n编译错误：%s\n修法提示：%s" % (_err6[:200], _hint6))
               if _hint6 else ""))
        self._record_ctx(ctx, entry)
        return False

    # ------------------------------------------------------------------
    # 诊断记录
    # ------------------------------------------------------------------
    def _record_ctx(self, ctx: TaskContext, data: dict) -> None:
        try:
            ctx.lean_gate.append(data)
        except Exception:  # noqa: BLE001
            ctx.lean_gate = [data]

    def _note_theorems_adopted(self, names: list) -> None:
        """#44 埋点：回记「最终被采用」的定理（Lean 编译通过＝真采用）。

        与 `_record_to_memory` 的区别：那是跨题持久记忆（#13），
        这是单题内的埋点统计（#44），两者数据来源相同但用途不同。
        失败一律吞掉——统计不可靠也好过主流程中断。
        """
        try:
            if not names:
                return
            from tools.lean_local.lean_search import get_stats
            get_stats().note_adopted(names)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[lean_gate] 采用埋点回记失败（已忽略）: %s", exc)

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
