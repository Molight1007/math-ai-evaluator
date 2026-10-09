# -*- coding: utf-8 -*-
"""Oracle / 对抗 / 证伪职责簇（2026-10-08 批9：从 agent/orchestrator.py
的 Orchestrator 逐字搬出）。

搬出方法：  · _enhance_window_ok  · _adversarial_probe
            · _falsify_candidates  · _falsify_rejects  · _oracle_review_best

**纯搬迁**：方法体逐字搬入（仅对「字符串 token 之外」的物理行去 4 空格缩进，
多行 docstring 的字符串值逐字不变），签名原样保留；Orchestrator 内保留
**同名一行委托** ⇒ 21 处 `self.<x>(...)` 跨模块调用点零改。

耦合实测（AST 自由变量分析）：方法体只引用 1 个 orchestrator 模块级符号
`logger` ⇒ 以同名 logger 单例复用（`logging.getLogger` 按名单例，同一对象）；
其余外部依赖全部经 `self`（`self.record` / `self.client` / `self.config` /
`self.adv_verifier` / `self._enhance_window_ok` / `self._deep_revise_loop`）或
函数内惰性 `from .answer_oracle | .answer_falsifier import ...`。
"""
from __future__ import annotations

import logging

from .base import TaskContext  # noqa: F401  （签名注解用）

logger = logging.getLogger("MathPilot")


def _enhance_window_ok(self, ctx: TaskContext, tag: str) -> bool:
    """4.5 Oracle / 4.6 对抗：可弃验证增强的剩余时间窗口检查。

        单次复核 LLM 调用最坏 ~360s（LLMClient 180s 超时 ×2 次重试）且
        不可打断——放行会把 6.5 final_gate 的 verify_reserve 烧穿（冒烟 v2
        实证：oracle 365s / 对抗 372s → 6.5 仍 time_critical、compile_valid 0）。
        增强属可弃：要求剩余时间 ≥ est(默认360) + critical_tail + 30s 缓冲，
        否则跳过直进 6.5（宁少一层深查，不饿死最终闸门）。
        verify_enhance_est_seconds=0 关闭护栏（= 旧行为）。
        """
    est = float(getattr(self.config, "verify_enhance_est_seconds", 360.0))
    if est <= 0:
        return True
    rem = ctx.time_remaining()
    need = est + float(ctx.critical_tail_seconds) + 30.0
    ok = rem >= need
    if not ok:
        self.record(ctx, "control",
                    f"验证增强 {tag} 跳过：剩余 {rem:.0f}s < 需 {need:.0f}s"
                    f"（est {est:.0f} + critical {ctx.critical_tail_seconds:.0f}"
                    f" + 30），保 6.5 终局")
    return ok


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
        # 预算护栏：时间紧张时不跑，避免抢走写题时间（#43 归因）。
        # 2026-09-06：升级 gen_time_up——对抗审查是可弃增强，到生成侧
        # 软截止即弃，把 reserve 时间留给 4_verify 主投票与 6.5 最终闸门。
        if ctx.gen_time_up():
            self.record(ctx, "adversarial", "预算不足，跳过对抗式审查")
            return False
        if getattr(ctx.state, 'emergency', False) or ctx.gen_time_up():
            self.record(ctx, "adversarial", "时间紧张，跳过对抗式审查")
            return False
        # 2026-09-07 增强窗口护栏：剩余时间不足（est + critical_tail + 30）
        # 时跳过——对抗审查单次 LLM 最坏 ~360s 不可打断，放行会把 6.5
        # final_gate 的 verify_reserve 烧穿（冒烟 v2：4.6_adv=372s → 6.5
        # time_critical、compile_valid 0）。可弃增强，宁跳过保 6.5 终局。
        if not self._enhance_window_ok(ctx, "adversarial"):
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

        # 检出错误 → 注入 revise 通道（audit_reject_feedback 通用反馈通道）
        if not getattr(ctx, 'audit_reject_feedback', None):
            ctx.audit_reject_feedback = []
        ctx.audit_reject_feedback.append(result.to_feedback())
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


def _falsify_candidates(self, ctx: TaskContext) -> tuple:
    """对候选池逐个跑证伪器，把**已被证伪**的候选答案记进 `ctx._falsified_answers`。

        返回 (available, n_survivors)：
        - `available=False` ⇒ 证伪器未启用/不可用/时间不足 ⇒ 调用方**必须保持原行为**；
        - `available=True` ⇒ `n_survivors` 是未被证伪的候选数（可能为 0 = 全被证伪）。

        ★ 2026-09-23 新增，回答用户"为什么把正确的排除、投票是不是有问题"：
          实测两个主力闸门（`4_verify` 全 0 票 / `lean_gate` proof_invalid）在**正确题**上
          的误报率都是 56% ⇒ "排除正确的"是结构性噪声。用户判据是
          "**错误答案一定是能证明错误的**" ⇒ 与其让闸门投票淘汰（同源自评、无判别力），
          不如用**可机检的证伪**来淘汰：只有拿到 SymPy 确认的反例才剔除。
        """
    try:
        if not getattr(self.config, "enable_answer_falsifier", True):
            return False, 0
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            return False, 0
        if ctx.is_time_critical():
            return False, 0
        from .answer_falsifier import AnswerFalsifier
        f = AnswerFalsifier(self.client, self.config)
        prob = getattr(ctx, "problem", "") or ""
        falsified = []
        for c in cands:
            if ctx.is_time_critical():
                break
            res = f.falsify(ctx, c, problem=prob)
            if res.is_incorrect:
                falsified.append({
                    "answer": str(getattr(c, "answer", ""))[:160],
                    "witness": (res.witness or "")[:200],
                    "oracle_type": res.oracle_type,
                })
        if falsified:
            try:
                ctx._falsified_answers = [x["answer"] for x in falsified]
                meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
                meta["falsified_answers"] = falsified
                ctx.metadata = meta
            except Exception:  # noqa: BLE001
                pass
            self.record(ctx, "falsify",
                        "候选证伪：%d/%d 个候选被客观证伪（SymPy 精确判定%s）"
                        % (len(falsified), len(cands),
                           "+Lean 背书" if any(x["oracle_type"] == "sympy+lean"
                                              for x in falsified) else ""))
        return True, max(0, len(cands) - len(falsified))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[orchestrator] 候选证伪异常（忽略）: %s", str(exc)[:120])
        return False, 0


def _falsify_rejects(self, ctx: TaskContext, answer: str) -> bool:
    """尝试**客观证伪**一个答案文本。返回 True 表示"已证伪、不得采纳"。

        与 `_oracle_review_best` 的分工：
        - `AnswerOracle` 只能做「多候选自洽共识」⇒ 判不出**绝对**对错；
        - 本方法只做**证伪**：数值回带（LLM 出闭式等式）→ SymPy 精确判定
          → Lean 背书（编译通过则推翻本次证伪）。

        设计红线（与 falsifier 一致，此处再兜一层）：
        - 任何异常 / 时间不足 / 证书缺失 / 判定不确定 ⇒ **返回 False（放行）**；
        - 绝不在此处判"正确"，也绝不用它替换答案（只做否决）。
        """
    try:
        if not getattr(self.config, "enable_answer_falsifier", True):
            # ★ 2026-10-09 P0 观测补齐：**前置拦截也是"证伪未命中"**。
            #   原为裸 `return False`，一条痕都不留 ⇒ "被前置条件挡住"与
            #   "调了没找到"不可区分（正是本次 P0 要消灭的观测缺口）。
            #   本出口与下列各出口互斥 ⇒ 有且仅有一条 falsify_miss 记录。
            self.record(ctx, "falsify_miss",
                        "证伪未命中（放行）：证伪器已关闭"
                        "（enable_answer_falsifier=False）")
            return False
        if not str(answer or "").strip():
            self.record(ctx, "falsify_miss",
                        "证伪未命中（放行）：答案为空白（无可检验文本）")
            return False
        if ctx.is_time_critical():
            self.record(ctx, "falsify_miss",
                        "证伪未命中（放行）：时间不足（is_time_critical）")
            return False
        from .answer_falsifier import AnswerFalsifier
        f = AnswerFalsifier(self.client, self.config)
        cand = type("_C", (), {"answer": str(answer), "reasoning": ""})()
        res = f.falsify(ctx, cand, problem=getattr(ctx, "problem", "") or "")
        if not res.is_incorrect:
            # ★★ 2026-10-05 修（**"没产出"完全不可观测** —— 用户要求"发现问题原因"）：
            #   证伪器是**唯一能产出可机检反例**的检错环节，实测三题 0 命中；
            #   但它的每个失败出口（`未取得证伪证书` / `证书无可机检等式` /
            #   `答案过长，非数值型` / `时间不足` / `已达上限` / `证伪器异常`）
            #   在 `answer_falsifier.py:135-185` 全部被 `return` 掉，
            #   而 `falsify_events` 只在**:3035/:3071 两条命中路径**记录
            #   ⇒ **一条失败原因都不留痕**，无法区分
            #   "没调用 / 调了没找到 / 被前置条件挡住"。
            #   现补一条 attempt 记录（含 reason），供后续按原因归因。
            # ★ 2026-10-09 P0 观测补齐：此 `falsify_miss` 记录此前**未被
            #   diag 导出**（`diag_export.falsify_events` 只过滤 `step=="falsify"`
            #   命中键）⇒ 恒为空。已在 diag_export 新增 `falsify_miss_events`
            #   专门导出本记录；命中键另设显式命名 `falsify_hit_events`。
            self.record(ctx, "falsify_miss",
                        "证伪未命中（放行）：%s" % (res.reason or "未给出原因"))
            return False
        # 留痕：把证伪结论记进 diag / trace，供事后审计
        self.record(ctx, "falsify",
                    "证伪命中：%s | 反例：%s" % (
                        res.reason, (res.witness or "")[:160]))
        try:
            ctx.metadata.setdefault("falsify_hits", []).append(
                {"answer": str(answer)[:120], "reason": res.reason,
                 "witness": (res.witness or "")[:200],
                 "checks": res.checks, "oracle_type": res.oracle_type})
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[orchestrator] 证伪器异常（放行）: %s", str(exc)[:120])
        # ★ 2026-10-09 P0 观测补齐：导入失败 / 未预期异常同样要留痕 ——
        #   否则整段证伪"静默消失"（本项目反复吃的坑）。此出口为异常兜底，
        #   与上面各 return 出口互斥 ⇒ 有且仅有一条 falsify_miss 记录。
        self.record(ctx, "falsify_miss",
                    "证伪未命中（放行）：证伪器异常：%s: %s"
                    % (type(exc).__name__, str(exc)[:120]))
        return False


def _oracle_review_best(self, ctx: TaskContext, ver_result: dict,
                        tier_votes: int) -> None:
    """deep 档：对 best_cluster 代表候选做 AnswerOracle 客观复核。

        投票是"验证器与解题器同源"的自评，会一起错；这里用 AnswerOracle
        （SymPy 符号等价/可解析性）做独立客观验证。2026-09-06 去 Lean 化：
        证明题不再做 Lean 编译（平台无 Lean），verify() 对证明题直接返回
        unknown，客观把关由 AuditGate（6.5 rubric）与对抗式验证（4.6）承担。
        incorrect 时把客观反馈注入 revise 通道并触发一次定向修正。
        """
    try:
        from .answer_oracle import AnswerOracle
    except Exception as _e_imp:  # noqa: BLE001
        # ★ 2026-10-04 修（D5，纯可观测）：原为裸 `return`，**不写任何 record**
        #   ⇒ 一旦导入失败，4.5 阶段整段静默消失，事后无法区分
        #   「4.5 没触发」与「触发了但模块炸了」—— 正是本项目反复吃的
        #   「埋点缺失 = 归因失效」坑。此处补留痕后再退，行为不变（仍放行）。
        self.record(ctx, "oracle_review",
                    f"AnswerOracle 导入失败，4.5 客观复核跳过: "
                    f"{type(_e_imp).__name__}: {str(_e_imp)[:120]}")
        return
    bc = getattr(ctx, '_best_cluster', None)
    if bc is None or not ctx.candidates:
        return
    cids = getattr(bc, 'candidate_ids', []) or []
    idx = cids[0] if cids and cids[0] < len(ctx.candidates) else 0
    rep = ctx.candidates[idx]
    oracle = AnswerOracle(self.client, self.config, ctx.budget)
    try:
        result = oracle.verify(ctx, rep, candidates=ctx.candidates)
    except Exception as e:  # noqa: BLE001
        self.record(ctx, "oracle_review", f"AnswerOracle 复核异常: {e}")
        return
    self.record(ctx, "oracle_review",
                f"AnswerOracle 客观复核: {result.verdict} ({result.oracle_type})",
                verdict=result.verdict, oracle_type=result.oracle_type)
    # ★ 2026-09-23 叠加「证伪」——补 oracle 的能力缺口。
    #   oracle 只有"多候选自洽共识"，没有 reference ⇒ **判不出绝对对错**
    #   （0923 效能审计：本环节召回仅 **3%**）。而证伪器能给出**可机检的反例**
    #   （数值回带 → SymPy 精确判定 → Lean 背书），正好补上"证明某个候选是错的"。
    #   被证伪 ⇒ 与 incorrect 同路：注入 revise 通道并触发一次定向修正。
    _bad_fb = result.feedback if (result.is_incorrect and result.feedback) else ""
    try:
        from .answer_falsifier import AnswerFalsifier
        _fr = AnswerFalsifier(self.client, self.config, ctx.budget).falsify(
            ctx, rep, problem=getattr(ctx, "problem", "") or "")
        if _fr.is_incorrect:
            self.record(ctx, "oracle_review",
                        "证伪器命中（%s）：%s" % (_fr.oracle_type, _fr.reason))
            _ffb = _fr.to_feedback()
            if _ffb:
                _bad_fb = (_ffb + ("\n" + _bad_fb if _bad_fb else "")).strip()
    except Exception as _e:  # noqa: BLE001
        logger.warning("[orchestrator] 证伪器叠加异常（忽略）: %s", str(_e)[:120])
    if _bad_fb and not ctx.state.emergency:
        # 客观反馈注入 revise 通道（audit_reject_feedback 通用反馈通道）
        if not getattr(ctx, 'audit_reject_feedback', None):
            ctx.audit_reject_feedback = []
        ctx.audit_reject_feedback.append(_bad_fb)
        self.record(ctx, "oracle_review",
                    f"客观复核/证伪判错，触发定向修正: {_bad_fb[:120]}")
        self._deep_revise_loop(ctx, ver_result, tier_votes)
