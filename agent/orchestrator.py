from __future__ import annotations
"""
编排器（Orchestrator）—— 简化版
================================

借鉴 ss-main 的简洁流水线，不做复杂回环，每道题 LLM 调用控制在 7 次以内：

    Classifier → Solver → Verifier → Formatter
    (1次LLM)   (3次并行)  (3次投票)  (无LLM)

弱化改动：
- 不设蓝图分解（use_blueprint=False，对 Intern-S 思维流友好）
- 不设自纠错回环（直接用聚类选最优候选）
- 不设完整性审核链（省去 3+ 次 LLM 确认与续写）
- Symbol 快车道仍在（可确定性求解时短路）
"""

import logging
import time
import re as _re

from .base import BaseAgent, TaskContext, Budget, Verdict, _normalize_chat_response
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
from .verifier import VerifierAgent, AnswerCluster
from .formatter import FormatterAgent
from .difficulty_router import DifficultyRouter
from .paper_pacer import PaperPacer
from .lean_gate import LeanGate
from .collaborative_solver import CollaborativeSolver
from .lean_pre_verifier import LeanPreVerifier
from .adversarial_verifier import AdversarialVerifier
from utils.extract import safe_json_serialize, is_truncated_answer as _is_truncated_answer

try:
    from utils.sympy_tools import (
        _HAS_SYMPY, eval_expression, compute_derivative,
        compute_integral, compute_determinant, solve_equation,
        compute_limit,
    )
except ImportError:
    _HAS_SYMPY = False

logger = logging.getLogger("MathPilot")


class Orchestrator(BaseAgent):
    name = "Orchestrator"

    def __init__(self, client, config):
        super().__init__(client, config)
        self.classifier = ClassifierAgent(client, config)
        self.solver = SolverAgent(client, config)
        self.sub_goal_solver = SubGoalSolverAgent(client, config)
        self.verifier = VerifierAgent(client, config)
        self.formatter = FormatterAgent(client, config)
        # 难题深度求解通道（v2.5）
        self.difficulty_router = DifficultyRouter(client, config)
        self.pacer = PaperPacer(config)
        # deep 档证明题 Lean 硬验证门禁（v2.5+LeanBridge）
        self.lean_gate = LeanGate(client, config)
        # deep 档难题三Agent协作求解器（v2.6：解题→审查→整合→反复验证）
        self.collab = CollaborativeSolver(client, config)
        # Lean 前置形式化验证（v2.9）：解题前把题目转 Lean 声明校验理解
        self.lean_pre_verifier = LeanPreVerifier(client, config)
        # 对抗式验证器（#16，2026-08-30）：正向验证**通过后**主动证伪，治漏检。
        # 与 Step 4（_review_bug_feedback，治误杀）互补：
        #   正向不过 → Step 4 复核是否误报
        #   正向通过 → 本模块去找漏掉的错误
        self.adv_verifier = AdversarialVerifier(client, config)

    # ------------------------------------------------------------------
    # 阶段耗时埋点（2026-09-03 老师：deep 档需要每个环节具体耗时做决定）
    # ------------------------------------------------------------------
    @staticmethod
    def _stage_start(ctx, name: str) -> None:
        # 2026-09-03 修正：进入新阶段前先结束所有未 stop 的旧阶段。
        # 否则 stop 只在流程末尾统一调用 → 每阶段耗时 = "从该阶段开始到
        # 流程结束"的剩余时间（实测 0_paper_pacer=1310s 全等于总时长，数据无效）。
        for _old in list((getattr(ctx, "_stage_starts", {}) or {}).keys()):
            if _old != name:
                Orchestrator._stage_stop(ctx, _old)
        ctx._stage_starts = getattr(ctx, "_stage_starts", {}) or {}
        ctx._stage_starts[name] = time.time()

    @staticmethod
    def _stage_stop(ctx, name: str) -> None:
        starts = getattr(ctx, "_stage_starts", {}) or {}
        s = starts.pop(name, None)
        if s is None:
            return
        ctx._stage_durs = getattr(ctx, "_stage_durs", {}) or {}
        ctx._stage_durs[name] = ctx._stage_durs.get(name, 0.0) + (time.time() - s)

    def _collect_stage_durs(self, ctx) -> dict:
        return dict(getattr(ctx, "_stage_durs", {}) or {})

    # ------------------------------------------------------------------
    # C-lite：数值攻击蓝图极值声称（2026-09-03 老师拍板）
    # ------------------------------------------------------------------
    def _value_attack_blueprint(self, ctx, tier: str) -> None:
        """蓝图 merge 声称"极值=数值"时，数值采样攻击验证。

        009 实况：蓝图声称最大 4∛(85/98)≈3.815，真值 2∛(196/13)≈4.94——
        LLM 心算错值后全链路自洽执行，Lean unknown 拦不住。这里用
        **确定性 Python 采样**（20k 点）找突破声称值的可行点 → 证伪。
        """
        try:
            if ctx.is_time_critical():
                return
            merge_text = (getattr(ctx, "blueprint_merge", "") or ""
                          or getattr(ctx, "subgoal_merge_plan", "") or "")
            if not merge_text:
                return
            # 只对"极值声称"题下手（其余题型放行，零误伤）
            import re as _re2
            if not (_re2.search(r"max|min|最大|最小", merge_text, _re2.I)):
                return
            from .value_attack import attack_value_claim
            from utils.prefill import prefill_messages, stitch
            # 1) LLM 从题目 + 声称提取: 方向/声称值/目标函数 Python 源码
            sys_p = (
                "你是数值提取器。根据题目（一个连续优化/极值问题）生成可执行 Python。\n"
                "输出 JSON：\n"
                "{\"direction\": \"max\"|\"min\", \"claimed\": <声称的极值数值近似>, "
                "\"code\": \"def f(x): ... 用 x[0],x[1]... 计算目标函数返回 float; "
                "def sample_point(): 返回一个满足约束的可行点 list\"}\n"
                "注意：claimed 是把题目声称的极值（含根式分数）算出的十进制近似；"
                "code 必须自含约束检查（不可行点返回 None）；禁止 import 外部库之外的；"
                "只输出 JSON。"
            )
            user_p = f"题目：\n{ctx.problem[:1500]}\n\n声称的答案/蓝图结论：\n{merge_text[:800]}"
            raw = self.llm(ctx, prefill_messages(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": user_p}], '{"direction":'), 0.0, 32768)
            if not raw:
                return
            raw = stitch('{"direction":', raw)
            m = _re2.search(r"\{[\s\S]*\}", raw)
            if not m:
                return
            import json as _json
            try:
                parsed = _json.loads(m.group())
            except Exception:  # noqa: BLE001
                return
            direction = str(parsed.get("direction") or "")
            claimed = parsed.get("claimed")
            code = str(parsed.get("code") or "")
            if direction not in ("max", "min") or claimed is None:
                return
            # 2) 数值攻击
            result = attack_value_claim(
                ctx.problem or "", float(claimed), direction, code)
            if not result.get("ok"):
                reason = result.get("reason", "数值攻击证伪")
                ctx.blueprint_value_false = reason
                self.record(ctx, "value_attack",
                            f"蓝图极值证伪（{direction}={claimed}）：{reason[:160]}")
                # 传给下游：候选生成/求解时提示蓝图方向不可信
                ctx.revise_feedback = list(getattr(ctx, "revise_feedback", []) or []) + [
                    f"[数值攻击] 蓝图声称极值 {claimed} 已被数值采样证伪"
                    f"（发现 {result.get('found', '?')}）。请重新推导极值，"
                    f"不要沿用蓝图的候选值。{reason[:200]}"]
            else:
                self.record(ctx, "value_attack",
                            f"蓝图极值未被证伪（采样上界 "
                            f"{result.get('found', '?')}，声称 {claimed}）")
        except Exception as _e:  # noqa: BLE001  攻击失败不影响主流程
            self.record(ctx, "value_attack",
                        f"数值攻击异常跳过: {str(_e)[:120]}")

    def _lean_verify_top_candidates(self, ctx, tier: str, n: int = 2) -> None:
        """2026-09-03 老师："2 候选必加 Lean verify"——对 top n 候选各做一次
        独立 Lean 验证（与投票同源 verifier 解耦，更客观）。比赛无次数上限。

        每候选调用一次 verify/verify_answer（5-21s），n=2 约 10-40s。
        记录到 ctx.lean_gate 与 trace，用于后续 6.5 步判定（已知答案对错）。
        """
        if not getattr(self.config, "enable_lean_verify", True):
            return
        bridge = self.lean_gate._bridge_inst
        if bridge is None or not bridge.lean_available:
            self.record(ctx, "lean_gate", "候选 Lean verify: 环境不可用跳过")
            return
        domain = getattr(ctx, "domain", "") or ""
        qtype = getattr(ctx, "question_type", "") or ""
        is_proof = domain in ("证明", "证明题") or qtype == "证明题"
        # 按 confidence 排序取 top n（候选的 answer 字段非空且非空字符串）
        cands = sorted(
            (ctx.candidates or []),
            key=lambda c: getattr(c, "confidence", 0.0),
            reverse=True,
        )[:n]
        verified = []
        for c in cands:
            ans = (getattr(c, "answer", "") or "").strip()
            if not ans:
                continue
            reasoning = getattr(c, "reasoning", "") or ""
            try:
                if is_proof:
                    report = bridge.verify(
                        problem=ctx.problem or "",
                        reasoning=reasoning,
                        domain=domain,
                        timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                    )
                else:
                    report = bridge.verify_answer(
                        problem=ctx.problem or "",
                        reasoning=reasoning,
                        answer=ans,
                        domain=domain,
                        timeout=float(getattr(self.config, "lean_timeout", 60.0)),
                    )
            except Exception as e:  # noqa: BLE001
                report = None
                self.record(ctx, "lean_gate",
                            f"候选 #{c.id} Lean 异常: {str(e)[:80]}")
            if report is None:
                verdict = "no_report"
                findings = []
            else:
                verdict = getattr(report, "verdict", "unknown") or "unknown"
                findings = getattr(report, "findings", []) or []
            entry = {
                "gate": "candidate_verify",
                "cand_id": c.id,
                "answer": ans[:60],
                "verdict": verdict,
                "is_proof": is_proof,
            }
            if findings:
                entry["findings_count"] = len(findings)
            ctx.lean_gate = list(getattr(ctx, "lean_gate", []) or []) + [entry]
            verified.append((c.id, verdict))
            self.record(ctx, "lean_gate",
                        f"候选 #{c.id} Lean verify: {verdict}")
        # 把"已知 Lean verdict"的候选集合存到 ctx，供 6.5 步复用（避免重复验证）
        ctx._lean_verified_map = {cid: v for cid, v in verified}

    # ----------------------------------------------------------
    # 主入口（简化版流水线）
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        now = time.time()
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
            start_time=now,
            deadline=now + getattr(self.config, 'max_time_per_question', 300),
            total_start_time=now,
            total_deadline=now + getattr(self.config, 'max_total_time_seconds', 21000),
        )
        try:
            self._stage_start(ctx, "0_paper_pacer")
            # 0) PaperPacer 全卷时间池：5h 目标动态预算帽 + MIN_SOFT 保底
            self.pacer.begin()
            ctx.pacer_remaining = self.pacer.hard_remaining()
            # 单题 20 分钟硬限：超时直接跳过（保留已有候选/兜底产出）
            if ctx.is_timed_out():
                self.record(ctx, "timeout", "单题超过 20 分钟，跳过处理")
                # 2026-09-02 bug 修复：超时分支先看已有候选（比瞎直答可靠），
                # 003 1206s 超时直接 emergency_direct_solve → "No such function"
                # 裸奔（无推理、无 Lean 把关）的根因。
                answer = self._pick_best_from_candidates(ctx)
                if not answer:
                    answer = self._emergency_direct_solve(ctx.problem)
                if not answer:
                    answer = "未给出有效解答。"
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
                return safe_json_serialize({
                    "final_response": answer, "trace": ctx.trace,
                    "diag": self._collect_diag(ctx),
                })
            elapsed_total = time.time() - ctx.total_start_time
            total_budget = ctx.total_deadline - ctx.total_start_time
            ratio = elapsed_total / total_budget if total_budget > 0 else 0.0
            # v2.8：运行时覆盖统一写入 ctx.state（RunState），不再改写共享 config，
            # 消除并发=3 时跨题污染（时间预算自律核心）。
            if ratio > 0.95:
                # P1 修复：阈值 0.75→0.95。本地测试更晚进入应急模式，把准确率放在时间前面。
                # 应急模式：候选→1、投票→1，跳过续写/复算（45 error 主因根治）
                ctx.state.sample_times = max(1, self.config.policy_sample_times - 1)
                ctx.state.voting_times = 1
                ctx.state.emergency = True
                ctx.state.playoff_enabled = False
                self.record(ctx, "paper_pacer", f"应急模式：已用 {ratio:.0%} 总预算")
            elif ratio > 0.8:
                ctx.state.voting_times = 1
                ctx.state.emergency = False
                ctx.state.playoff_enabled = False
                self.record(ctx, "paper_pacer", f"时间收紧：已用 {ratio:.0%} 总预算")
            else:
                ctx.state.emergency = False
                ctx.state.playoff_enabled = True

            self._stage_start(ctx, "1_classify")
            # 1) 题型识别（零 LLM 关键词分类，供 Lean 门禁区分证明题/解答题、
            #    及题型差异化策略使用）。
            # 2026-09-01 补漏：原逻辑仅在「元数据 domain 未知」时才跑 classifier.run，
            # 若 metadata.domain ∈ _KNOWN_DOMAINS（如 "代数"）则跳过 → ctx.question_type
            # 永不赋值 → lean_gate 拿不到 question_type，该 domain 下的证明题会被误判
            # 为非证明题走轻量答案验证而非整题 verify。这里无条件先做题型识别。
            if self.config.enable_question_type:
                from .question_type import classify_question_type
                ctx.question_type = classify_question_type(ctx.problem)
                self.record(ctx, "classify_type",
                            f"题型识别结果: {ctx.question_type}",
                            question_type=ctx.question_type)

            # 1.5) 领域（元数据已知时跳过 LLM）
            pre_known_domain = (metadata or {}).get("domain", "")
            if pre_known_domain and pre_known_domain in _KNOWN_DOMAINS:
                ctx.domain = pre_known_domain
                self.record(ctx, "classify",
                    f"题型分类（元数据已知）: {pre_known_domain}", domain=pre_known_domain)
            elif self.config.enable_domain_hint:
                self.classifier.run(ctx)

            # 2) 快车道（可确定性求解 → 直接出结果）
            fast_result = self._fast_path(ctx)
            if fast_result is not None:
                ctx.final_response = fast_result
                self.record(ctx, "fast_path", f"快车道直接求解: {fast_result[:200]}")
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
                return safe_json_serialize({
                    "final_response": fast_result, "trace": ctx.trace,
                    "candidates": [], "verdicts": [],
                    "diag": self._collect_diag(ctx),
                })

            self._stage_start(ctx, "2.5_difficulty")
            # 2.5) 难度路由：静态预判 + LLM 自评 → 三级档位（难题深度通道）
            self.difficulty_router.run(ctx)
            tier = getattr(ctx, 'tier', 'standard')
            # 应急模式：所有档位强制降级到 fast（预算收紧，保产出）
            if ctx.state.emergency and tier != 'fast':
                ctx.tier = 'fast'
                tier = 'fast'
                self.record(ctx, "paper_pacer", "应急模式：强制降档到 fast")
            # deep 档配额闸（2026-08-28 新增）：deep 占比封顶 25%。
            # 时间账：并发 3 × 6h = 64800 题·秒；deep 占 30% 需 70080，超 5280
            # → 全卷必爆。超配额时降级到 standard，保证全卷能做完。
            if tier == 'deep' and not self.pacer.allow_deep():
                ctx.tier = 'standard'
                tier = 'standard'
                self.record(ctx, "paper_pacer",
                            f"deep 配额用尽（{self.pacer.deep_used}/"
                            f"{self.pacer.total_questions}×"
                            f"{self.pacer.deep_quota_ratio:.0%}），降级到 standard")
            elif tier == 'deep':
                self.pacer.note_deep()
            # 全卷时间池动态预算帽
            ctx.soft_budget = self.pacer.budget_for(tier)
            # 让动态预算**真正生效**：把单题 deadline 收紧到软预算帽。
            # 2026-09-03 老师："每题上限 1200s，不到 1200 不要截断；
            # 强制结束 = 错误"。**取消 deadline 收紧**——此前 ctx.deadline 被
            # PaperPacer soft_budget（如 540s）收紧，导致 540s 后所有环节
            # is_time_critical()（看 deadline）假超时 → 验证/Lean 闸门全跳 =
            # 变相强制结束。deadline 保持 1200s 硬顶，soft_budget 仅作 PaperPacer
            # 跨题调度的预算参考（paper_cap 仍控制总卷时间，那是正确的时间池）。
            # if ctx.soft_budget > 0:
            #     ctx.deadline = min(ctx.deadline,
            #                        ctx.start_time + ctx.soft_budget)
            # 尾部阈值：默认 120s；deep 档再收紧到 60s，把时间用得更尽
            ctx.critical_tail_seconds = float(
                getattr(self.config, 'critical_tail_seconds', 120.0))
            if tier == 'deep':
                ctx.critical_tail_seconds = float(
                    getattr(self.config, 'deep_critical_tail_seconds', 60.0))
            # 按档位调整 LLM 调用预算（deep 档需要更多调用次数）
            max_calls = self.config.tier_max_calls.get(
                tier, self.config.max_total_calls)
            if ctx.budget is not None:
                ctx.budget.set_max_calls(max_calls)
            self.record(ctx, "paper_pacer",
                        f"档位 {tier} 软预算帽 {ctx.soft_budget:.0f}s "
                        f"(剩余目标 {ctx.pacer_remaining:.0f}s, 调用预算 {max_calls})",
                        tier=tier, soft_budget=round(ctx.soft_budget))

            self._stage_start(ctx, "2.6_preverify")
            # 2.6) Lean 前置形式化验证（v2.9）：解题前把题目转 Lean 声明校验理解，
            # 通过后 ctx.formal_spec 会注入后续子目标规划；失败/降级不阻断主流程。
            # 2026-08-29：按档位执行（默认只 deep）——preverify 每次 21s 编译 +
            # 多次 LLM 调用挤占求解预算（D5 实测 Solver 225 次被跳过），而其
            # "理解提示"收益未在数据体现；fast/standard 跳过省时间给真正求解。
            preverify_tiers = list(getattr(self.config,
                                           'lean_preverify_tiers', ["deep"]))
            if (getattr(self.config, 'enable_lean_preverify', True)
                    and tier in preverify_tiers
                    and not ctx.state.emergency):
                self.lean_pre_verifier.run(ctx)

            # 2.6.1) 骨架审核结果回灌（#26/#28）
            # 2026-08-28：骨架审核的 gaps 已经由 lean_pre_verifier.py:197-204
            # 并入 ctx.formal_gaps（下游 blueprint_planner / sub_goal_solver 消费），
            # 但 **revise_feedback 这条通路是空的** —— 自纠错回环看不到
            # "骨架哪一步不严谨"。这里只补这一条，避免重复注入 formal_gaps。
            audit = getattr(ctx, "sketch_audit", None) or {}
            if audit.get("verdict") == "fail":
                gaps = [g for g in (audit.get("gaps") or [])
                        if isinstance(g, dict) and g.get("detail")]
                if gaps:
                    ctx.revise_feedback = list(ctx.revise_feedback) + [
                        f"[骨架严谨性缺口] {g['detail']}" for g in gaps
                    ]
                    self.record(ctx, "sketch_audit_reinject",
                                f"骨架审核未通过，{len(gaps)} 条缺口注入自纠错回环")

            # 2026-09-02 B：preverify 多次重试仍 fail → 标记"理解未确认"。
            # 老师要求"没理解不放行"，但阻断主流程会死锁（难题永远编译不过），
            # 实际做法：把"理解未确认"信号强注入到 revise_feedback + trace，
            # 让下游 Solver/SubGoal 在推理时知道要谨慎（不破坏"仍继续求解"）。
            if getattr(ctx, '_preverify_unconfirmed', False):
                unconf_msg = (
                    "⚠️ 题目理解未通过 Lean 前置验证：多次重试仍编译失败。"
                    "下游推理必须**先重读题面**确认数学定义/条件，"
                    "勿依赖未确认的 Lean 声明。"
                )
                ctx.revise_feedback = list(ctx.revise_feedback) + [unconf_msg]
                self.record(ctx, "preverify_unconfirmed",
                            "preverify 失败：理解未确认 → 警告注入下游 revise_feedback")

            self._stage_start(ctx, "2.7_subgoal_main")
            # 2.7) 子目标细化主路径（v2.9）：全部档位统一先跑一次子目标分解逐步求解
            if (getattr(self.config, 'enable_subgoal_main_path', True)
                    and not ctx.state.emergency
                    and not ctx.is_time_critical()):
                self.record(ctx, "control",
                            "子目标细化主路径先行（前置形式化已校准题意）")
                self.sub_goal_solver.run(ctx)
                ctx._subgoal_main_done = True

            # C-lite（2026-09-03）：子目标蓝图 merge 产出后、候选生成前，
            # 数值攻击蓝图极值声称——009 型"蓝图心算错值"在求解前就证伪。
            if not getattr(ctx, "_blueprint_value_false", None):
                try:
                    self._value_attack_blueprint(ctx, tier)
                except Exception as _e2:  # noqa: BLE001
                    pass

            self._stage_start(ctx, "3_solve")
            # 3) 求解
            # deep 档：Plan-and-Execute 主路径先行（子目标分解逐步求解 + 每步 oracle 校验），
            # 让结构化计划-执行候选先进入后续 Lean 验证与投票。
            if (tier == 'deep'
                    and getattr(self.config, 'deep_use_sub_goal', True)
                    and not getattr(ctx, '_subgoal_main_done', False)
                    and not ctx.state.emergency
                    and not ctx.is_time_critical()):
                self.record(ctx, "control", "deep 档 Plan-and-Execute 主路径先行（子目标分解）")
                self.sub_goal_solver.run(ctx)

            # Solver 多路采样（候选数/温度分层按档位，solver 内部读取 ctx.tier）
            # L1 验证优先（2026-08-31）：剩余时间不足 verify_only_seconds 时
            # 停止生成新候选，把最后的时间留给验证投票。
            # 依据：A_base 30 题日志 170 次"剩余时间不足"跳过调用、
            # 117 次"验证拿到 None 默认判错" —— 生成阶段把时间烧光，
            # 验证投票被饿死（误杀正确候选）。verify_only 治的就是这个。
            # ⚠ D 组对照实测净 −1、p=1.0 → 默认关闭（verify_only_seconds=0），
            # 触发条件必须显式 > 0，避免 deadline 已过（remaining<0）时误触发。
            _remaining_before_solve = (
                ctx.deadline - time.time() if ctx.deadline else float("inf"))
            _verify_only_seconds = getattr(self.config, 'verify_only_seconds', 0)
            if _verify_only_seconds > 0 and _remaining_before_solve < _verify_only_seconds:
                ctx.state.verify_only = True
                self.record(ctx, "paper_pacer",
                            f"L1 验证优先：剩余 {_remaining_before_solve:.0f}s"
                            f" < {_verify_only_seconds}s，"
                            f"停止生成新候选，只保留验证",
                            verify_only=True)
            if not ctx.state.verify_only:
                self.solver.run(ctx)
            if not ctx.candidates:
                self.record(ctx, "control", "Solver 未产出候选，触发兜底直接求解")
                self.pacer.end(tier=tier, soft=getattr(ctx, "soft_budget", None))
                return self._fallback_direct(ctx)

            self._stage_start(ctx, "3.2_complete")
            # 3.2) 截断候选续写：每档 max_completions 个（fast=0 跳过），应急模式跳过
            if (getattr(ctx, 'candidates', None)
                    and not ctx.state.emergency
                    and not ctx.state.verify_only):
                max_comp = self.config.tier_max_completions.get(tier, 1)
                if max_comp > 0:
                    n_completed = self.solver.complete_truncated_candidates(
                        ctx, max_count=max_comp)
                    if n_completed > 0:
                        self.record(ctx, "control",
                                    f"截断续写完成 {n_completed} 个候选")

            self._stage_start(ctx, "3.3_improve")
            # 3.3) Step 2 无条件自改进（IMO2025 论文流水线）：
            #      生成后、验证前，对候选先 review+improve 一遍（注入第二段推理
            #      预算）。论文实测初始解质量低、此步显著改进。
            #      仅 deep/standard 档执行；fast 档与应急模式跳过（控成本）。
            if (getattr(self.config, 'enable_self_improve', True)
                    and tier != 'fast'
                    and not ctx.state.emergency
                    and not ctx.state.verify_only
                    and ctx.candidates):
                if not ctx.is_time_critical():
                    n_imp = self.solver.improve_candidates(ctx)
                    if n_imp > 0:
                        self.record(ctx, "control",
                                    f"Step2 自改进完成 {n_imp} 个候选")

            self._stage_start(ctx, "3.4_collab")
            # 3.4) deep 档难题：三Agent协作（解题→审查→整合→反复验证）
            #      只要时间未到且未验证通过，CollaborativeSolver 内部反复循环，
            #      保证难题高正确率。
            if (tier == 'deep'
                    and getattr(self.config, 'enable_collaborative_deep', True)
                    and not ctx.state.emergency
                    and not ctx.state.verify_only):
                self.record(ctx, "control", "deep 档启用三Agent协作验证机制")
                self.collab.run(ctx)

            self._stage_start(ctx, "3.5_subgoal_sup")
            # 3.5) 子目标分解补充候选：仅非 deep 档（deep 档已作为主路径提前执行）
            # 2026-08-30（#45 移除题型分流）：原逻辑带 `or is_proof`，即证明题
            # **无条件**触发子目标分解。但 IMO 基本全是证明题，该分支等于让
            # 全部题目都多跑一轮子目标规划 —— 而 #43 归因已证明：错题主因是
            # 时间分配错误（规划抢走了真正写题的预算）。故去掉题型条件，
            # 只保留与题型无关的统一触发条件：候选不足时才补。
            use_sub = getattr(self.config, 'use_sub_goal', False)
            if (tier != 'deep'
                    and use_sub
                    and not getattr(ctx, '_subgoal_main_done', False)
                    and not ctx.state.verify_only
                    and not ctx.is_time_critical()
                    and len(ctx.candidates) < 2):
                self.record(ctx, "control",
                            "触发子目标分解补充候选",
                            sub_goal_trigger=f"tier={tier}, "
                                             f"candidates={len(ctx.candidates)}")
                self.sub_goal_solver.run(ctx)

            # 2026-09-03 老师："2 候选必加 Lean verify"——在 3.5 步后对 top 2
            # 候选各做一次独立 Lean verify（与投票同源 verifier 解耦，更客观）。
            # 比赛无次数上限，可放心加。占 20-40s（2 候选 × 5-21s）。
            self._stage_start(ctx, "3.5.1_lean_candidate")
            try:
                self._lean_verify_top_candidates(ctx, tier, n=2)
            except Exception as _e:
                self.record(ctx, "lean_gate", f"候选 Lean verify 异常: {str(_e)[:120]}")
            self._stage_stop(ctx, "3.5.1_lean_candidate")

            self._stage_start(ctx, "3.6_lean_filter")
            # 3.6) deep 档证明题：Lean 硬验证门禁（v2.5+LeanBridge）
            # 仅当 lean 门禁实际生效（deep+证明+环境可用）才过滤候选；
            # proof_valid 候选进入后续验证，proof_invalid 淘汰并收集 revise 反馈。
            # 若全部候选被 Lean 淘汰，则降级保留原候选（保证有输出，不损失分数）。
            # L1：verify_only 时跳过（每次编译 ~21s，时间不够花在 Lean 上）。
            if ctx.state.verify_only:
                self.record(ctx, "lean_gate",
                            "L1 验证优先：跳过 Lean 硬验证门禁（时间不足）")
            else:
                _lean_total = len(ctx.candidates)
                lean_kept, lean_feedbacks = self.lean_gate.apply(
                    ctx, tier, ctx.candidates)
                if lean_kept:
                    ctx.candidates = lean_kept
                    self.record(ctx, "lean_gate",
                                f"Lean 硬验证通过 {len(lean_kept)}/{_lean_total} 候选")
                if lean_feedbacks:
                    ctx.lean_reject_feedback = lean_feedbacks
                    self.record(ctx, "lean_gate",
                                f"Lean 硬验证淘汰 {len(lean_feedbacks)} 候选，"
                                f"revise 将注入 Lean 反馈")

            self._stage_start(ctx, "4_verify")
            # 4) 验证（投票数按档位：fast=1/standard=1/deep=3）
            # P0-4 修复：playoff 复算按时间宽裕度开关，deep 档且时间宽裕时启用
            #
            # 2026-08-31 修复 NameError：#45 移除题型分流时把 3.5 步的
            # `is_proof = ...` 赋值一起删了，但这里的 verifier.run 仍在用它 →
            # 每题抛 `name 'is_proof' is not defined`，整条流水线走异常兜底。
            # 说明：#45 要移除的是「**子目标触发** / **Lean 门禁**看题型」，
            # 验证器的 is_proof 是另一回事（verifier.py 用它决定单候选时的
            # 严格度），属于正当用途，必须保留。
            is_proof = (getattr(ctx, 'question_type', '') == '证明题'
                        or getattr(ctx, 'domain', '') in ('证明', '证明题'))
            tier_votes = self.config.tier_voting_times.get(tier, 1)
            # 2026-09-02 老师需求：候选池统一封顶 8（兜底所有生成路径：
            # 初始/改进/续写/协作/子目标/revise 追加总量都可能超）
            _pre_verify_n = len(ctx.candidates or [])
            if _pre_verify_n > 8:
                ctx.candidates = (ctx.candidates or [])[:8]
                self.record(ctx, "control",
                            f"候选池 {_pre_verify_n} → 8（统一封顶）")
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=is_proof,
                use_playoff=(
                    (tier == 'deep' and getattr(self.config, 'deep_use_playoff', True))
                    or (tier != 'deep' and ctx.state.playoff_enabled)
                ),
                use_deterministic=getattr(self.config, 'enable_deterministic', True),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result, ctx.candidates)
            ctx._best_cluster = ver_result.get("best_cluster")
            ctx._cluster_data = ver_result.get("cluster_data", [])

            self._stage_start(ctx, "4.5_oracle")
            # 4.5) deep 档：AnswerOracle 客观复核 best_cluster（区别于投票同源自评）
            if tier == 'deep' and getattr(ctx, '_best_cluster', None) is not None:
                self._oracle_review_best(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "4.6_adv")
            # 4.6) 对抗式验证（#16）：正向通过后主动证伪，抓漏检。
            #      仅当"确有候选被正向判对"时才跑——正向全错的会走 revise，
            #      再证伪一次是纯浪费（每轮调用都吃预算，见 #43 归因）。
            _any_correct = any(
                getattr(v, 'correct_votes', 0) > 0 for v in (ctx.verdicts or []))
            if _any_correct:
                self._adversarial_probe(ctx, tier)

            self._stage_start(ctx, "5_revise_or_fallback")
            # 5) 全部 0 正确票：
            #    - deep 档：先 revise 自纠错回环（最多 deep_revise_rounds 轮）
            #    - 其他档：直接兜底直接求解
            if (ctx.verdicts
                    and all(v.total_votes > 0 for v in ctx.verdicts)
                    and all(v.correct_votes == 0 for v in ctx.verdicts)):
                revised_ok = False
                if tier == 'deep' and not ctx.state.emergency:
                    revised_ok = self._deep_revise_loop(ctx, ver_result, tier_votes)
                if not revised_ok:
                    self.record(ctx, "control", "全部 0 正确票，触发兜底直接求解")
                    # 2026-09-02 bug 修复：不再提前 return！
                    # 旧代码 direct_solve/_pick_best 后直接 return，跳过了
                    # formatter(6步：占位符拦截/截断续写/拒绝兜底) 和
                    # 6.5 Lean 最终闸门 → Lean 闸门 10/10 题 0 执行、
                    # 003 直答 "No such function" 裸奔的根因。
                    # 现改为：兜底答案先存入 ctx.final_response，落回统一出口，
                    # 由 formatter 校验/修复（候选都差时保留预设答案），
                    # 再进 6.5 Lean 闸门把关，最后统一 return。
                    direct_answer = self.solver.direct_solve(ctx)
                    if direct_answer:
                        ctx.final_response = direct_answer
                    else:
                        ctx.final_response = self._pick_best_from_candidates(ctx) or ""
                    # 标记 0 票兜底路径：formatter 需要它来判断是否保留预设答案
                    ctx._zero_vote_fallback = True

            self._stage_start(ctx, "5.5_low_conf")
            # 5.5) 低置信度强制复核（v2.6 杀掉虚高置信度）：
            #   deep 档 best_cluster 置信度 < 0.5（正确票未过半，验证器自身都不确定）
            #   且时间/预算宽裕时，不自信接受低共识答案，而是触发 revise 提升共识。
            # 所有档位（不只 deep）启用低置信度强制复核：
            # 只要投票共识 < 0.5（验证器自身都不确定），就不再"自信接受"错答案，
            # 而是触发 revise 反复验证，直到获得正确票或超时/预算耗尽。
            _bc = getattr(ctx, '_best_cluster', None)
            if (_bc is not None
                    and getattr(_bc, 'confidence', 1.0) < 0.5
                    and not ctx.state.emergency):
                self.record(
                    ctx, "control",
                    f"deep 档低置信度({_bc.confidence:.2f})，强制 revise 复核提升共识",
                )
                self._deep_revise_loop(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "6_format")
            # 6) 格式化输出
            self.formatter.run(ctx)

            self._stage_start(ctx, "6.5_lean_gate")
            # 6.5) Lean 最终答案闸门（2026-09-02 老师需求：Lean 拦错误逻辑）。
            #      只验 formatter 选中的 1 个最终答案（5-21s，不再整批跳过）。
            #      验不过 → 换候选（按答案与 final 不同的顺序试 ≤2 个）。
            # v4 修正：去掉 emergency/verify_only 外层保护——v4 10/10 题 Lean 闸门
            # 被 ctx.state.emergency 阻断（应急模式可能误触发），完全没执行。
            # gate_final_answer 内部已自护：time_remaining<15s 或 budget.skip 才跳过。
            if (getattr(self.config, 'enable_lean_verify', True)
                    and ctx.final_response):
                try:
                    # 2026-09-03 老师：不到 1200s 且 Lean 验证错误就**不放过**，
                    # 一直换候选重做（去掉"≤2 次"硬限），时间到 1200s 才放行。
                    # 同时把上一轮 Lean 反馈注入到 revise_feedback（让 LLM 重生成时能看到具体错）。
                    import time as _t3
                    _hard_end = ctx.start_time + float(
                        getattr(self.config, "max_time_per_question", 1200))
                    best_reasoning = ""
                    for _c in (ctx.candidates or []):
                        if getattr(_c, "answer", "") == ctx.final_response:
                            best_reasoning = getattr(_c, "reasoning", "") or ""
                            break
                    g_ok = self.lean_gate.gate_final_answer(
                        ctx, tier, ctx.final_response, best_reasoning)
                    _switched = False
                    _tried = 0
                    _last_feedback = ""
                    while (not g_ok
                           and _t3.time() < _hard_end - 5):
                        # 取最近一条 Lean gate 反馈（gate_final_answer 写 ctx.lean_gate）
                        for _entry in reversed(ctx.lean_gate or []):
                            if _entry.get("gate") == "final_answer" and _entry.get("feedback"):
                                _last_feedback = _entry["feedback"][:400]
                                break
                        # 注入到 revise_feedback 供 LLM 重生成时参考
                        if _last_feedback:
                            ctx.revise_feedback = list(ctx.revise_feedback) + [
                                f"[Lean 闸门反馈] 上一候选 (#{_tried+1}) "
                                f"未通过 Lean：{_last_feedback}"
                            ]
                        self.record(ctx, "lean_gate",
                                    f"Lean 拒候选 #{_tried+1}（剩余 "
                                    f"{int(_hard_end - _t3.time())}s）继续换/重做")
                        # 换下一候选（按置信度）试；候选换尽后 → 让 Solver 读
                        # Lean 反馈**重新生成**新候选（真正的"告诉 AI 错哪了"闭环）
                        _next = None
                        for _c in sorted(
                                ctx.candidates or [],
                                key=lambda c: getattr(c, "confidence", 0.0),
                                reverse=True):
                            if _c.answer == ctx.final_response:
                                continue
                            if not getattr(_c, "answer", ""):
                                continue
                            if _c.id in (getattr(ctx, "_lean_tried", []) or []):
                                continue
                            _next = _c
                            break
                        if _next is None:
                            # 候选已全部试过 → 触发 Solver 读反馈重新生成（重做到对）
                            if _t3.time() < _hard_end - 60:
                                self.record(
                                    ctx, "lean_gate",
                                    "所有候选未过 Lean，触发 Solver 读反馈重新生成"
                                    f"（revise_feedback 已含 {_tried+1} 条 Lean 定位）")
                                try:
                                    # solver.run 内部：ctx.revise_round>0 且
                                    # ctx.revise_feedback 非空 → 走 _generate_revise
                                    # （读反馈定向修正，见 solver.py:122）。
                                    # **先腾位**：候选池已满 8（cap）时 solver.run
                                    # remaining=0 直接 return 不生成 → 保留通过
                                    # Lean 的最优候选，其余清空给新候选腾位。
                                    _pass_cands = []
                                    for _cc in (ctx.candidates or []):
                                        if _cc.id in (getattr(ctx, "_lean_tried", []) or []):
                                            _pass_cands.append(_cc)  # 未过 Lean 的作参考保留
                                    ctx.candidates = _pass_cands[:3]  # 腾位
                                    ctx.revise_round = getattr(ctx, "revise_round", 0) + 1
                                    _before = len(ctx.candidates or [])
                                    self.solver.run(ctx)
                                    if len(ctx.candidates or []) > _before:
                                        _tried += 1
                                        _fresh = ctx.candidates[-1]
                                        ctx.final_response = _fresh.answer
                                        g_ok = self.lean_gate.gate_final_answer(
                                            ctx, tier, _fresh.answer,
                                            getattr(_fresh, "reasoning", "") or "")
                                        if g_ok:
                                            _switched = True
                                            self.record(
                                                ctx, "lean_gate",
                                                f"Solver 读 Lean 反馈重生成的候选 "
                                                f"#{_fresh.id} 过闸门，采用")
                                        continue  # 未过则回到 while 顶部继续
                                except Exception as _e2:  # noqa: BLE001
                                    self.record(ctx, "lean_gate",
                                                f"Lean 反馈重生成异常: {str(_e2)[:120]}")
                            self.record(ctx, "lean_gate",
                                        "重生成后仍无候选过 Lean 或时间不足，停")
                            break
                        _tried += 1
                        ctx._lean_tried = list(getattr(ctx, "_lean_tried", []) or []) + [_next.id]
                        ctx.final_response = _next.answer
                        g_ok = self.lean_gate.gate_final_answer(
                            ctx, tier, _next.answer,
                            getattr(_next, "reasoning", "") or "")
                        if g_ok:
                            _switched = True
                            self.record(ctx, "lean_gate",
                                        f"换候选 #{_next.id} 过 Lean 闸门，采用其答案")
                    if not g_ok:
                        ctx.lean_rejected = True
                        self.record(ctx, "lean_gate",
                                    f"直到 1200s 硬限 Lean 仍拒（{_tried} 次换候选），原答案标 rejected")
                except Exception as _e:  # noqa: BLE001  闸门异常绝不阻断
                    self.record(ctx, "lean_gate",
                                f"Lean 闸门异常，降级放行: {str(_e)[:120]}")

            self.pacer.end(tier=tier, soft=getattr(ctx, "soft_budget", None))

            # 阶段耗时收尾（2026-09-03）：统一 stop 全部 18 阶段（之前 start 在阶段开始）
            for _stg in ("0_paper_pacer","1_classify","2.5_difficulty","2.6_preverify",
                         "2.7_subgoal_main","3_solve","3.2_complete","3.3_improve",
                         "3.4_collab","3.5_subgoal_sup","3.5.1_lean_candidate",
                         "3.6_lean_filter","4_verify","4.5_oracle","4.6_adv",
                         "5_revise_or_fallback","5.5_low_conf","6_format","6.5_lean_gate"):
                self._stage_stop(ctx, _stg)

            # 构建返回
            candidates_out = [
                {"id": c.id, "answer": c.answer,
                 "reasoning": c.reasoning, "revised": c.revised}
                for c in ctx.candidates
            ]
            verdicts_out = [
                {"id": v.id, "answer": v.answer,
                 "confidence": v.confidence,
                 "correct_votes": v.correct_votes,
                 "total_votes": v.total_votes,
                 "feedback": v.feedback}
                for v in (ctx.verdicts or [])
            ]
            cluster_out = None
            bc = getattr(ctx, '_best_cluster', None)
            if bc:
                cluster_out = {
                    "answer_norm": bc.answer_norm,
                    "size": bc.size,
                    "confidence": bc.confidence,
                    "candidate_ids": bc.candidate_ids,
                }
            return safe_json_serialize({
                "final_response": ctx.final_response or "",
                "trace": ctx.trace,
                "candidates": candidates_out,
                "verdicts": verdicts_out,
                "cluster": cluster_out,
                # AI 实际检索/引用过的 Mathlib 定理（#1/#2 证据链）
                "used_theorems": list(ctx.used_theorems or []),
                # 检索/命中/编译通过统计（回应"调用频繁但定理不多"）
                "mathlib_usage_stats": {
                    **(ctx.mathlib_usage_stats or {}),
                    "distinct_theorems": len(ctx.used_theorems or []),
                },
                # ---- 逐步归因诊断（2026-09-02 用户要求：错题要能定位到环节）----
                # 统一由 _collect_diag 构建（全 getattr 兜底：提前 return / 异常路径也覆盖）
                "diag": self._collect_diag(ctx),
            })
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            try:
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
            except Exception:
                pass
            return self._fallback(ctx, problem, e)

    # ----------------------------------------------------------
    # 快车道：可确定性求解的题目直接用 SymPy 短路
    # ----------------------------------------------------------
    _FAST_PATH_PATTERNS = [
        (r"\d+\s*[\+\-\*/×÷]\s*\d+", "arithmetic"),
        (r"(?:calculate|compute|evaluate)\b", "arithmetic"),
        (r"(?:求导|导数|微分|derivative?|differentiate|f'|f''|d/dx)", "derivative"),
        (r"(?:积分|∫|integral|integrate)", "integral"),
        (r"(?:行列式|determinant|det\s*\(|矩阵的?行列式)", "determinant"),
        (r"(?:解(?:方程|方程组)|solve.{0,6}equation)", "equation"),
        (r"(?:一元二次|二次方程|quadratic)", "quadratic"),
        (r"(?:极限|limit)", "limit"),
    ]

    _FAST_PATH_TIME_LIMIT = 20.0  # 快车道总耗时上限（秒），超限即放弃、回退主流程

    def _fast_path(self, ctx: TaskContext) -> str | None:
        problem = ctx.problem or ""
        start = time.time()
        for pattern, tag in self._FAST_PATH_PATTERNS:
            if not _re.search(pattern, problem, _re.IGNORECASE):
                continue
            self.record(ctx, "fast_path", f"检测到可快车道求解题型: {tag}")
            if not _HAS_SYMPY:
                self.record(ctx, "fast_path", "SymPy 未安装，跳过快车道")
                continue
            # 耗时控制：超过预算立即放弃快车道，避免过度消耗时间
            if time.time() - start > self._FAST_PATH_TIME_LIMIT:
                self.record(ctx, "fast_path", "快车道耗时超限，放弃，回退主流程")
                return None
            result = self._try_sympy_solve(problem, tag)
            if result:
                self.record(ctx, "fast_path", f"快车道 SymPy 求解成功: {result}")
                return result
            self.record(ctx, "fast_path", f"快车道 {tag}: SymPy 求解失败，回退")
        return None

    def _try_sympy_solve(self, problem: str, tag: str) -> str | None:
        extract_prompt = (
            "请从以下题目中提取**核心数学表达式**（只输出表达式，不要额外文字）。"
            f"\n\n题目类型: {tag}\n题目: {problem}\n\n表达式:"
        )
        try:
            # v2.4.1：prefill「表达式：」抑制 CoT——快车道只需表达式，秒级返回
            from utils.prefill import prefill_messages, stitch
            raw_expr = _normalize_chat_response(self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": "你只输出数学表达式，不要任何解释。"},
                        {"role": "user", "content": extract_prompt},
                    ],
                    "表达式：",
                ),
                temperature=0.0,
                max_tokens=32768,
            ))
            if raw_expr:
                raw_expr = stitch("表达式：", raw_expr)
            raw_expr = (raw_expr or "").strip()
        except Exception:
            return None
        if not raw_expr or len(raw_expr) > 500:
            return None
        try:
            if tag in ("arithmetic", "quadratic"):
                return eval_expression(raw_expr)
            elif tag == "derivative":
                return compute_derivative(raw_expr)
            elif tag == "integral":
                return compute_integral(raw_expr)
            elif tag == "determinant":
                return compute_determinant(raw_expr)
            elif tag in ("equation",):
                return solve_equation(raw_expr)
            elif tag == "limit":
                return compute_limit(raw_expr)
        except Exception:
            pass
        return None

    def _review_bug_feedback(self, ctx: TaskContext, feedback: str) -> str:
        """Step 4：让模型复核验证器的缺陷反馈，可驳回误报（论文流水线）。

        论文（Huang & Yang 2025）：验证器产出的 bug report 不一定全对，
        模型复核后可驳回误报——避免好答案被错误反馈引导改坏。
        返回复核后的 feedback；复核失败/无实质缺陷时返回精简反馈。
        """
        if not feedback or len(feedback) < 10:
            return feedback
        if not getattr(self.config, 'enable_feedback_review', True):
            return feedback
        # 候选：用最佳候选的 reasoning 作复核依据
        cand_text = ""
        bc = getattr(ctx, '_best_cluster', None)
        if bc is not None and getattr(bc, 'rep_candidate', None) is not None:
            cand_text = str(getattr(bc.rep_candidate, 'reasoning', ''))[:900]
        if not cand_text and ctx.candidates:
            cand_text = str(getattr(ctx.candidates[0], 'reasoning', ''))[:900]
        user_msg = (
            f"【题目】\n{ctx.problem}\n\n"
            f"【当前解答（节选）】\n{cand_text}\n\n"
            f"【验证器给出的缺陷反馈】\n{feedback}\n\n"
            "请逐条复核上述缺陷反馈是否属实：\n"
            "- 属实（真实存在且影响正确性）→ 保留该条\n"
            "- 误报（与解答不符或判断错误）→ 驳回该条\n"
            "只输出复核后保留的缺陷清单，若全部误报则输出：无实质缺陷")
        raw = self.llm(ctx, [
            {"role": "system",
             "content": "你是严谨的数学复核员，只客观判断缺陷反馈是否属实。"},
            {"role": "user", "content": user_msg},
        ], temperature=0.0, max_tokens=32768)
        if not raw or not raw.strip():
            return feedback
        reviewed = raw.strip()
        self.record(ctx, "review",
                    f"反馈复核完成: {reviewed[:60]}")
        if "无实质缺陷" in reviewed:
            return "解答已较完整，请重新审题核对计算细节后给出最终答案。"
        return reviewed

    def _deep_revise_loop(self, ctx: TaskContext, ver_result: dict,
                          tier_votes: int) -> bool:
        """deep 档 0 正确票时的 revise 自纠错回环。

        用验证器反馈驱动定向修正：最多 deep_revise_rounds 轮，
        每轮 solver 走 _generate_revise 重解 + verifier 重新验证。
        返回是否在回环中获得至少 1 个候选获得正确票。
        """
        max_rounds = getattr(self.config, 'deep_revise_rounds', 1)
        if max_rounds <= 0 or ctx.state.emergency:
            return False
        # 2026-09-02 老师需求：revise 全局轮数上限 5（revise_round 跨主路径累计）
        if getattr(ctx, 'revise_round', 0) >= 5:
            self.record(ctx, "revise", "revise 已达全局上限 5 轮，不再继续")
            return False
        feedback = ver_result.get("feedback", "")
        if not feedback:
            feedback = "所有候选均未获验证通过，请重新审题并纠正推理错误。"
        # Step 4：复核验证器反馈（可驳回误报），避免被错误反馈误导修正。
        # 仅当反馈非空且预算允许时做（deep 档 +1 次调用，回环前只做一次）。
        if (not ctx.is_time_critical()
                and len(feedback) > 10):
            feedback = self._review_bug_feedback(ctx, feedback)
        # deep 档证明题：注入 Lean 硬验证淘汰反馈，驱动定向修正
        lean_fb = getattr(ctx, "lean_reject_feedback", None)
        if lean_fb:
            feedback = feedback + "\n" + "\n".join(lean_fb)
        for r in range(max_rounds):
            if ctx.is_time_critical():
                self.record(ctx, "revise", "revise 回环预算不足，提前终止")
                break
            ctx.revise_round += 1
            ctx.revise_feedback = [feedback]
            self.record(ctx, "revise",
                        f"deep 档 revise 自纠错 第{ctx.revise_round}轮",
                        round=ctx.revise_round)
            self.solver.run(ctx)  # 走 _generate_revise 路径
            ver2 = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=getattr(ctx, 'domain', '') in ('证明', '证明题'),
                use_playoff=ctx.state.playoff_enabled,
                use_deterministic=getattr(self.config, 'enable_deterministic', True),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver2, ctx.candidates)
            ctx._best_cluster = ver2.get("best_cluster")
            ctx._cluster_data = ver2.get("cluster_data", [])
            # v2.8 AcceptGate：按本轮结果更新门控，连续重大缺陷达阈值 → 提前放弃
            decision = self._update_accept_gate(
                ctx, is_proof=getattr(ctx, 'domain', '') in ('证明', '证明题'))
            # 2026-09-02 老师需求：≥4 个候选获得正确票才算通过（防 1 票假阳性误收）
            n_pass = sum(1 for v in ctx.verdicts
                         if getattr(v, 'correct_votes', 0) > 0)
            if n_pass >= 4:
                self.record(ctx, "revise",
                            f"revise 第{ctx.revise_round}轮 {n_pass} 个候选通过（≥4）")
                return True
            if decision == "REJECT":
                self.record(ctx, "revise", "AcceptGate 连续重大缺陷达阈值，放弃 revise")
                return False
            feedback = ver2.get("feedback") or feedback
        self.record(ctx, "revise", f"revise 回环 {max_rounds} 轮仍未获得正确票")
        return False

    def _update_accept_gate(self, ctx: TaskContext, is_proof: bool = False) -> str:
        """按本轮验证结果更新 AcceptGate（RoundState），返回最新 decision。

        - is_pass：best_cluster 置信度 >= accept_confidence；
        - has_major_defect：证明题全部 0 正确票，或常规题置信度 < 0.3。
        """
        accept_conf = getattr(self.config, 'accept_confidence', 0.6)
        bc = getattr(ctx, '_best_cluster', None)
        conf = bc.confidence if bc is not None else 0.0
        is_pass = conf >= accept_conf
        has_major = False
        if is_proof:
            has_major = bool(ctx.verdicts) and all(v.correct_votes == 0 for v in ctx.verdicts)
        elif conf < 0.3:
            has_major = True
        decision = ctx.round_state.update(is_pass=is_pass, has_major_defect=has_major)
        self.record(
            ctx, "accept_gate",
            f"AcceptGate={decision} (pass={ctx.round_state.consecutive_pass}, "
            f"defect={ctx.round_state.consecutive_major_defect})",
            confidence=round(conf, 3),
        )
        return decision

    def _lean_verdict_final(self, ctx: TaskContext, cand) -> bool:
        """该候选是否已被 Lean 门禁给出**确定结论**（valid / invalid）。

        2026-08-30（#45）新增，用于替代 `_oracle_review_best` 里按题型跳过的判断。
        """
        for e in getattr(ctx, "lean_gate", None) or []:
            if e.get("id") == getattr(cand, "id", None):
                return e.get("verdict") in ("proof_valid", "proof_invalid")
        return False

    def _adversarial_probe(self, ctx: TaskContext, tier: str) -> bool:
        """对抗式验证（#16）：正向通过后主动证伪，抓正向漏检的错误。

        为什么只在"正向通过"后跑
        --------------------------
        - 正向**不过**的候选会直接进 revise / Step 4 复核是否误报，
          再证伪一次纯属浪费调用。
        - 正向**通过**的候选才是漏检风险区：验证器顺着作者思路走
          （确认偏误），错误没被审出来，这类答案会直接提交。

        返回 True 表示检出错误并已注入 revise 通道。
        任何异常都被吞掉返回 False——验证器的问题绝不能阻断主流程。
        """
        try:
            if not getattr(self.config, 'enable_adversarial_verify', True):
                return False
            bc = getattr(ctx, '_best_cluster', None)
            rep = getattr(bc, 'rep_candidate', None) if bc is not None else None
            if rep is None:
                rep = ctx.candidates[0] if ctx.candidates else None
            if rep is None:
                return False
            # 预算护栏：时间紧张时不跑，避免抢走写题时间（#43 归因）
            if ctx.is_time_critical():
                self.record(ctx, "adversarial", "预算不足，跳过对抗式审查")
                return False
            if getattr(ctx.state, 'emergency', False) or ctx.is_time_critical():
                self.record(ctx, "adversarial", "时间紧张，跳过对抗式审查")
                return False

            result = self.adv_verifier.probe(ctx, rep, tier=tier)
            if result.skipped:
                self.record(ctx, "adversarial", f"跳过：{result.skipped}")
                return False

            if not result.is_actionable:
                # 正向通过 + 尽力证伪仍无反例 → 高置信接受。
                # 这比"第二层再判一遍"更可信，也正是治误杀的关键：
                # 不再被一个单纯更严的第二层无脑否掉。
                self.record(ctx, "adversarial",
                            f"对抗式审查未找到错误（置信 {result.confidence:.2f}），"
                            f"高置信接受",
                            adv_found=False,
                            adv_confidence=result.confidence)
                ctx.adversarial_result = result
                return False

            # 检出错误 → 注入 revise 通道（复用 lean_reject_feedback 字段）
            if not getattr(ctx, 'lean_reject_feedback', None):
                ctx.lean_reject_feedback = []
            ctx.lean_reject_feedback.append(result.to_feedback())
            ctx.adversarial_result = result
            self.record(ctx, "adversarial",
                        f"对抗式审查检出「{result.error_type or '未知类型'}」，"
                        f"注入 revise（置信 {result.confidence:.2f}）",
                        adv_found=True,
                        adv_error_type=result.error_type,
                        adv_confidence=result.confidence)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] 对抗式审查异常（已忽略）: %s", str(exc)[:120])
            return False

    def _oracle_review_best(self, ctx: TaskContext, ver_result: dict,
                            tier_votes: int) -> None:
        """deep 档：对 best_cluster 代表候选做 AnswerOracle 客观复核。

        投票是"验证器与解题器同源"的自评，会一起错；这里用 AnswerOracle
        （Lean / SymPy）做独立客观验证。incorrect 时把客观反馈
        注入 revise 通道并触发一次定向修正。

        2026-08-30（#45 移除题型分流）：原逻辑是「证明题直接 return」，
        理由是"已由 lean_gate 覆盖、避免重复编译"。但该理由只在 lean_gate
        **真的跑出确定结论**时成立 —— 门禁未启用 / 降级 / unknown 放行时，
        证明题会完全没有客观复核。
        改为按**该候选是否已有 Lean 确定结论**判断，与题型无关：
        有确定结论 → 跳过（避免重复编译）；unknown / 未记录 → 照常复核。
        """
        try:
            from .answer_oracle import AnswerOracle
        except Exception:  # noqa: BLE001
            return
        bc = getattr(ctx, '_best_cluster', None)
        if bc is None or not ctx.candidates:
            return
        cids = getattr(bc, 'candidate_ids', []) or []
        idx = cids[0] if cids and cids[0] < len(ctx.candidates) else 0
        rep = ctx.candidates[idx]
        if self._lean_verdict_final(ctx, rep):
            self.record(ctx, "oracle_review",
                        "该候选已有 Lean 确定结论，跳过客观复核（避免重复编译）")
            return
        oracle = AnswerOracle(self.client, self.config, ctx.budget)
        try:
            result = oracle.verify(ctx, rep, candidates=ctx.candidates)
        except Exception as e:  # noqa: BLE001
            self.record(ctx, "oracle_review", f"AnswerOracle 复核异常: {e}")
            return
        self.record(ctx, "oracle_review",
                    f"AnswerOracle 客观复核: {result.verdict} ({result.oracle_type})",
                    verdict=result.verdict, oracle_type=result.oracle_type)
        if (result.is_incorrect and result.feedback
                and not ctx.state.emergency):
            # 客观反馈注入 revise 通道（复用 lean_reject_feedback 字段）
            if not getattr(ctx, 'lean_reject_feedback', None):
                ctx.lean_reject_feedback = []
            ctx.lean_reject_feedback.append(result.feedback)
            self.record(ctx, "oracle_review",
                        f"客观复核判错，触发定向修正: {result.feedback[:120]}")
            self._deep_revise_loop(ctx, ver_result, tier_votes)

    def _verdicts_from_ver_result(self, ver_result: dict, candidates: list = None) -> list:
        """将验证器产出的多票结果汇总为 Verdict 数据类列表。

        每个候选可能有多张票（Verdict），此处聚合成一个汇总 Verdict：
        - confidence = 正确票 / 总票数
        - answer 取自候选（便于 Formatter 兜底直接使用）
        - feedback 取第一张有效票的反馈，score 取第一张非空票的评分
        """
        all_verdicts = ver_result.get("verdicts", [])
        result = []
        for idx, vds in enumerate(all_verdicts):
            correct_votes = sum(1 for v in vds if v.correct)
            total_votes = len(vds)
            candidate = candidates[idx] if candidates and idx < len(candidates) else None
            answer = candidate.answer if candidate else ""
            feedback = next((v.feedback for v in vds if v.feedback), "")
            score = next((v.score for v in vds if v.score is not None), None)
            result.append(Verdict(
                id=idx,
                answer=answer,
                confidence=correct_votes / total_votes if total_votes else 0.0,
                correct_votes=correct_votes,
                total_votes=total_votes,
                feedback=feedback,
                score=score,
            ))
        return result

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        import re as _re
        # 1) 从 verdicts 找有非拒绝答案的
        if ctx.verdicts:
            sorted_v = sorted(ctx.verdicts, key=lambda v: v.confidence, reverse=True)
            for v in sorted_v:
                ans = getattr(v, "answer", "") or ""
                if ans and len(ans) > 3 and not _re.search(r"无法求解|无法解决|不能解决", ans):
                    return ans
        # 2) 从 candidates 找有非拒绝答案的
        if ctx.candidates:
            sorted_c = sorted(ctx.candidates, key=lambda c: len(c.reasoning or ""), reverse=True)
            for c in sorted_c:
                if c.answer and len(c.answer) > 3 and not _re.search(r"无法求解|无法解决|不能解决", c.answer):
                    return c.answer
        # 3) 最后防线：取最详细推理的尾部
        if ctx.candidates:
            best = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))
            if best.reasoning and len(best.reasoning) > 50:
                return best.reasoning.strip()[-500:]
        return ""

    _DIRECT_SYS = (
        "你是数学解题专家。请解答下面这道题。"
        "最后一行必须以【最终答案】: <答案> 的格式给出最终答案，"
        "答案只写数值、表达式或选项字母，不要写任何解释或推理。"
    )

    def _collect_diag(self, ctx: TaskContext) -> dict:
        """逐步归因诊断（2026-09-02 用户要求：错题要能定位到环节）。

        打包各阶段中间状态：理解→蓝图→骨架评审→子目标→Lean→验证→预算。
        全部 getattr + 默认值兜底：任意提前 return / 异常路径下调用都安全
        （TaskContext 各字段均有默认值，直接访问也不会崩）。
        由 run_eval.solve_one 落盘为结果行 diag 字段；tools/analyze_errors.py 消费。
        """
        return {
            # ① 题型与档位
            "question_type": getattr(ctx, "question_type", "") or "",
            "domain": getattr(ctx, "domain", "") or "",
            "tier": getattr(ctx, "tier", "") or "",
            "tier_evidence": getattr(ctx, "tier_evidence", None) or {},
            "soft_budget": round(float(getattr(ctx, "soft_budget", 0) or 0), 1),
            # ② 题目理解（Lean 前置 preverify）
            "formal_spec": (getattr(ctx, "formal_spec", "") or "")[:600],
            "formal_gaps": list(getattr(ctx, "formal_gaps", None) or [])[:10],
            "preverify_trace": getattr(ctx, "preverify_trace", None) or {},
            # ③ 蓝图 DAG + 骨架评审 + DAG 评审
            "blueprint_nodes": len((getattr(ctx, "blueprint", None) or {}).get("nodes", []) or []),
            "blueprint_merge": (getattr(ctx, "blueprint", None) or {}).get("merge_strategy", ""),
            "skeleton_review": getattr(ctx, "skeleton_review_report", None) or None,
            "dag_review": getattr(ctx, "dag_review_report", None) or {},
            "sketch_audit": getattr(ctx, "sketch_audit", None) or {},
            # ④ 子目标求解（结构化轨迹）
            "subgoal_trace": getattr(ctx, "subgoal_trace", None) or [],
            "subgoal_merge_plan": (getattr(ctx, "subgoal_merge_plan", "") or "")[:300],
            "lemma_repo": list(getattr(ctx, "lemma_repo", None) or [])[:20],
            # ⑤ Lean 硬验证门禁
            "lean_gate": getattr(ctx, "lean_gate", None) or [],
            # ⑥ 候选/验证/自纠错
            "n_candidates": len(getattr(ctx, "candidates", None) or []),
            "n_verdicts": len(getattr(ctx, "verdicts", None) or []),
            "revise_round": getattr(ctx, "revise_round", 0),
            "revise_feedback": list(getattr(ctx, "revise_feedback", None) or [])[:20],
            # ⑦ 预算健康（trace 中 budget_skip / degraded / 占位符计数）
            "budget_skips": sum(1 for t in (getattr(ctx, "trace", None) or [])
                                if isinstance(t, dict) and t.get("step") == "budget_skip"),
            "degraded_flags": sum(1 for t in (getattr(ctx, "trace", None) or [])
                                  if isinstance(t, dict)
                                  and ("degrad" in str(t.get("step", "")).lower()
                                       or "degrad" in str(t.get("content", "")).lower())),
            "placeholder": "[子目标求解失败]" in (getattr(ctx, "final_response", "") or ""),
            # 2026-09-02 老师需求：答案截断可观测（003 题 g(x)=-2x^{ 截断被识别）
            "answer_complete": not _is_truncated_answer(
                getattr(ctx, "final_response", "") or ""),
            # 阶段耗时（2026-09-03 老师要看 deep 档每环节具体耗时）
            "stage_timers": self._collect_stage_durs(ctx),
        }

    def _emergency_direct_solve(self, problem: str) -> str:
        """紧急直答：用最精简 prompt 逼模型输出答案，绝不返回原题。

        P0-4 修复：集成 prefill 答案前置——时间最紧时优先保答案，
        抑制 CoT 开启，即使截断也只损失思考、不损失答案（ICMA 验证 58-140× 加速）。
        """
        try:
            from utils.prefill import prefill_messages, stitch
            resp = self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": self._DIRECT_SYS},
                        {"role": "user", "content": problem},
                    ],
                    "【最终答案】: ",
                ),
                temperature=0.0,
                max_tokens=self.config.max_answer_tokens,
            )
            text = _normalize_chat_response(resp)
            if text:
                text = stitch("【最终答案】: ", text)
            if not text or not text.strip():
                return ""
            # 优先提取【最终答案】行
            m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            if m:
                ans = m.group(1).strip().split("\n")[0].strip()
                if ans:
                    return ans
            # 兜底：最后一个非空行
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines[-1][:500]
            return text.strip()[:500]
        except Exception:
            return ""

    def _fallback_direct(self, ctx: TaskContext) -> dict:
        """Solver 无候选 → 直接 LLM 求解（紧急直答，绝不返回原题）"""
        answer = self._emergency_direct_solve(ctx.problem)
        if not answer:
            # 2026-09-02 二次尝试：换更强调语气重答（094 实测一次直答失败
            # 即返回"未给出有效解答"——多一次机会，成本仅 1 次调用）
            try:
                from utils.prefill import prefill_messages, stitch
                resp2 = self.client.chat(
                    messages=prefill_messages(
                        [
                            {"role": "system", "content": (
                                "直接输出本题最终答案。禁止拒绝、禁止解释。"
                                "若答案是数值给出数值，若需集合/表达式按标准数学格式。")},
                            {"role": "user", "content": ctx.problem},
                        ],
                        "【最终答案】: ",
                    ),
                    temperature=0.0, max_tokens=65536,
                )
                text = _normalize_chat_response(resp2)
                if text:
                    text = stitch("【最终答案】: ", text)
                    m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
                    if m:
                        ans2 = m.group(1).strip().split("\n")[0].strip()
                        if ans2 and len(ans2) > 1:
                            answer = ans2
            except Exception:  # noqa: BLE001
                pass
        if not answer:
            answer = "未给出有效解答。"
            ctx.trace.append({"agent": self.name, "step": "fallback",
                              "content": "紧急直答失败，返回占位答案"})
        return safe_json_serialize({
            "final_response": answer, "trace": ctx.trace,
            "diag": self._collect_diag(ctx),
        })

    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        trace = list(ctx.trace) if ctx.trace else []
        trace.append({
            "agent": self.name, "step": "error",
            "content": f"求解异常: {type(exc).__name__}: {exc}",
        })
        answer = self._pick_best_from_candidates(ctx)
        if answer:
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "使用已有候选最佳答案作为兜底"})
            return {"final_response": answer, "trace": trace,
                    "diag": self._collect_diag(ctx)}
        # 紧急直答
        answer = self._emergency_direct_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "紧急直答失败，返回占位答案"})
        return {"final_response": answer, "trace": trace,
                "diag": self._collect_diag(ctx)}
