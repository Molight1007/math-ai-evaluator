# -*- coding: utf-8 -*-
"""终答审核闸门（2026-10-07 阶段C2：从 agent/orchestrator.py 的 Orchestrator.run 抽出 6.5_audit_gate 段）。

**纯搬迁**：段内源码逐字搬入（仅去 8 空格的缩进），调用点由 `run` 改为一行委托。
`run` 保留 `self._stage_start(ctx, "6.5_audit_gate")` 打点**原位不动**（阶段名是稳定
契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：本段对 `run` 的局部变量依赖**仅为 `ctx` 与 `tier`**；
段内 42 个局部名**零外泄**、无 `return`、所有 `break/continue/try` 均归属段内循环。
其余外部符号为模块级 `os` / `logger` 与 `_sw_num_or` / `_collect_tool_findings`
（后两者由本模块**惰性 import** 自 `agent/orchestrator.py`，避免循环导入；二者仍是
单一来源，不在本文件复制实现）。

返回 None；结果全部写回 `ctx`（final_response / gate_rejected / revise_feedback /
revise_round / candidates / _gate_tried / _gate_rollback 等）。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("MathPilot")


def final_answer_gate(self, ctx, tier: str) -> None:
    """6.5 最终答案闸门（门控后换候选 / 读反馈重生成 / 无进展与轮数守卫）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位（本项目恒为 "deep"）。
    """
    from .orchestrator import _sw_num_or, _collect_tool_findings

    # 2026-10-01：原 6.5 处「`calc_inconsistent`（计算冲突）优先于 Lean
    #   answer_valid」的裁决已随 `<calc>` 计算工具板块整体删除 —— 其唯一
    #   来源（`_maybe_answer_selfcheck` 里"有工具值却与答案不符"的判据）
    #   已移除 ⇒ 该分支随之消失（原 L4「判据在当前配置下不可达」已成历史）。
    # 6.5) 最终答案闸门（2026-09-06 晚：Lean/AuditGate 双后端路由）。
    #      Lean 环境可用 → LeanGate.gate_final_answer：证明题整题 verify、
    #      非证明题 verify_answer（norm_num/ring 答案锚定核验，5-21s），
    #      proof_invalid/unknown → 拒绝换候选（老师 9/2：Lean 一定不能跳过；
    #      9/3：无法验证/未知必须默认拒绝，不许裸奔）；
    #      Lean 不可用 → AuditGate.gate_final_answer（Level0 程序硬核验等，
    #      平台 AI 判分兜底，与去 Lean 期完全一致）。
    #      验不过 → 换候选（按答案与 final 不同的顺序试 ≤2 个）。
    # gate_final_answer 内部已自护：空答案放行、time_remaining<15s
    # 或 budget.skip 才跳过；rubric 高置信 B 才打回（宁 unknown 不误杀）。
    #  2026-09-10：再叠加「按题适用性」——豁免题（答案非数学对象）
    #      不改路由到 Lean，改用 AuditGate 做最终闸门，绝不裸奔。
    _gate_lean = self._lean_active() and self._lean_applicable(ctx)
    if ((_gate_lean or getattr(self.config, 'enable_audit_gate', True))
            and ctx.final_response):
        _gk = "lean_gate" if _gate_lean else "audit_gate"
        _gate = self.lean_gate if _gate_lean else self.audit_gate
        try:
            # 2026-09-03 老师：不到 1200s 且审核判错就**不放过**，
            # 一直换候选重做、时间到 1200s 才放行 —— 该"不放过"规则自
            # 2026-09-04 起**仅保留给 deep 档**（见下方 2026-09-04 档位封顶说明）。
            # 同时把上一轮审核反馈注入到 revise_feedback（让 LLM 重生成时能看到具体错）。
            import time as _t3
            _hard_end = ctx.start_time + float(
                getattr(self.config, "max_time_per_question", 1200))
            # 2026-09-04 按档位封顶（治本：2534334 平台 64 invalid = 时间墙归因）。
            # 此前 6.5 对**所有档**都用 1200s 硬限 → fast/standard 题也被拖到
            # 墙边，重做耗尽的题整题超时无最终答案。现改为：
            #   fast/standard：最多 2 次打回，且整题时间超 tier_budget 即放行；
            #   deep：保留"做到 1200s"，但每次打回前保证剩余时间够完成。
            #   ⚠ 2026-10-04 修注释（D32）：上面的 "1200s" 是**比赛期**口径，
            #     现行研究期配置下 `max_time_per_question=86400`、
            #     `tier_budget['deep']=86400` ⇒ 实际 `_rework_deadline`
            #     = start+86100s（≈23.9h，见下方 A5 无进展保护处的实测注释）。
            _tbl_budget = getattr(self.config, 'tier_budget', None) or {}
            _tier_budget = float(_tbl_budget.get(tier, 1200.0))
            # ⚠ 2026-09-13 修复（审查发现；这是会导致**计 C（0 分）**的严重问题）：
            # 原式 `min(_hard_end, start + _tier_budget)`，而 deep 档
            # tier_budget=1150 恰等于 max_time_per_question ⇒ **与硬墙完全相等、
            # 零余量**。但 while 循环体内会调 `solver.run`（**单次 200-300s、
            # 不可中断**），而护栏只在"发起时刻"判断（`<_rework_deadline - 5`）、
            # **不约束调用时长** ⇒ 只要在剩余 200-300s 时发起一次重做，就会
            # 跨过 1150/1200 硬墙：平台**终止整个进程组、不执行 finally**，
            # 该题**计 C 且分母不变**。
            # 修复：为"一次重做 + 闸门复验"预留 `_rework_reserve`（默认 300s），
            # 让循环体内的 solver.run 必定能在硬墙前跑完。
            # ★ 2026-10-07 注册制补齐（问题总账 §2.3「B 类裸 env 未登记」）：
            #   原为裸 `os.environ.get("REWORK_RESERVE_SEC", "300")` ⇒ 不入
            #   注册表（diag 看不到）、"先 import 后改 env" 有静默失效风险。
            #   现走注册表 `rework_reserve_sec`（优先级 env > config > 默认）；
            #   注册未落时回退"调用时读 env"（与旧行为一致）。
            try:
                _rr_env = float(os.environ.get("REWORK_RESERVE_SEC", "300"))
            except (TypeError, ValueError):
                _rr_env = 300.0
            _rework_reserve = float(
                _sw_num_or("rework_reserve_sec", _rr_env))
            _rework_deadline = min(
                _hard_end,
                ctx.start_time + _tier_budget) - max(0.0, _rework_reserve)
            # 2026-10-01：比赛期上限（默认 3）已按研究期标尺放开 ⇒ 默认 -1 = 无上限
            # （审计 A 级第 3 条）。原注释自述动机是「6.5 成为新的时间黑洞」
            # 的省时考虑；研究期求正确率上限，不再以时间为由限制终审重做。
            # `DEEP_MAX_REWORK=N`（N>=0）仍可显式设上限，便于 A/B。
            # ★ 2026-10-07 同上：改走注册表 `deep_max_rework`（默认 -1）。
            try:
                _dmr_env = int(os.environ.get("DEEP_MAX_REWORK", "-1"))
            except (TypeError, ValueError):
                _dmr_env = -1
            try:
                _deep_cap = int(
                    _sw_num_or("deep_max_rework", float(_dmr_env)))
            except (TypeError, ValueError):
                _deep_cap = _dmr_env
            # 2026-09-14：fast 档已删除 ⇒ 原 `tier in ("fast","standard")`
            # 简化为 `tier == "standard"`。
            _max_rework = (2 if tier == "standard"
                           else (None if _deep_cap < 0 else _deep_cap))
            best_reasoning = ""
            for _c in (ctx.candidates or []):
                if getattr(_c, "answer", "") == ctx.final_response:
                    best_reasoning = getattr(_c, "reasoning", "") or ""
                    break
            g_ok = _gate.gate_final_answer(
                ctx, tier, ctx.final_response, best_reasoning)
            _tried = 0
            _last_feedback = ""
            # ★ 2026-09-21：记下"进入重做循环前"的答案，供未过审核时回滚。
            #   候选按 confidence **降序**试探（下方 sorted(...reverse=True)），
            #   循环因次数/时间耗尽而退出时 ctx.final_response 停在**最后换上**
            #   的候选 = 置信度最低者；而"闸门没能确认更强" ≠ "确认更弱"。
            _pre_rework_final = ctx.final_response
            # ★ 2026-10-04 防挂死（**只加「无进展保护」，不加轮数配额** ——
            #   研究期口径不允许「为省时间砍方法」）：
            #   实测复核配置：deep 档 `tier_budget['deep']=86400`、
            #   `max_time_per_question=86400`、`DEEP_MAX_REWORK` 未设 ⇒ `-1`
            #   ⇒ `_max_rework=None`（**无轮数上限**）；且
            #   `_rework_deadline = min(start+86400, start+86400) - 300
            #    = start + 86100s` ⇒ 退出条件只剩 `g_ok` 或 **≈23.9 小时**。
            #   循环体每轮会再调 `self.solver.run()`（单次 200-300s、不可中断）
            #   且**无任何进展检测** ⇒ 单题可跑满近 24h，把整轮 112 题串行评测卡死。
            #   处理：**时间墙 `_rework_deadline` 与轮数语义 `_max_rework` 一律不动**，
            #   仅在「连续 2 轮答案完全未变（本轮空转）」时提前退出。
            #   ⚠ 检测放在**循环体顶部**而非物理末尾：循环体有 **3 处 `continue`**
            #   （重生成脏答案 :2342 / 重生成未过闸门 :2351 / 换候选脏答案 :2372），
            #   放末尾会被 `continue` 跳过 ⇒ 保护在最常见的「重生成」路径上静默失效
            #   （即本项目「只改一处=没改」的老病灶）。顶部检测对全部路径等效生效。
            _prev_rework_ans = None
            _no_progress_rounds = 0
            # ★ 2026-10-07 分支静默跳过埋点（问题总账 §2.6「隐形门控」）：
            #   while 条件不成立时循环**一次都不进**、下游只见"6.5 没重做"
            #   却分不清是「闸门本已通过」还是「被时间/轮数闸挡在门外」。
            #   此处仅**记录**原因，不改动 while 的任何条件（控制流不变）。
            if not g_ok:
                if _t3.time() >= _rework_deadline - 5:
                    self.record(
                        ctx, _gk,
                        f"6.5 重做循环跳过：剩余 "
                        f"{_rework_deadline - _t3.time():.0f}s < 5s（时间不足一轮重做）")
                elif _max_rework is not None and _tried >= _max_rework:
                    self.record(
                        ctx, _gk,
                        f"6.5 重做循环跳过：已达重做轮数上限 {_max_rework}")
            while (not g_ok
                   and _t3.time() < _rework_deadline - 5
                   and (_max_rework is None or _tried < _max_rework)):
                # ★ 无进展保护：与上一轮答案比较（首轮不判）。
                #   语义对齐 `_deep_revise_loop` 内同类保护（`revise 第N轮无进展`）：
                #   仅「答案完全未变」视为空转；答案一变即归零继续跑满。
                _cur_rework_ans = str(ctx.final_response or "")
                if (_prev_rework_ans is not None
                        and _cur_rework_ans == _prev_rework_ans):
                    _no_progress_rounds += 1
                    if _no_progress_rounds >= 2:
                        self.record(
                            ctx, "revise",
                            "6.5 重做无进展（连续 2 轮答案未变），提前退出重做循环")
                        break
                else:
                    _no_progress_rounds = 0
                _prev_rework_ans = _cur_rework_ans
                # 取最近一条闸门拒绝反馈（写 ctx.lean_gate / ctx.audit_gate；
                # lean 的拒绝 verdict=proof_invalid/unknown，audit 的=reject）
                for _entry in reversed(getattr(ctx, _gk, []) or []):
                    if (_entry.get("step") == "final_gate"
                            and _entry.get("verdict")
                            in ("reject", "proof_invalid", "unknown")):
                        _last_feedback = (_entry.get("feedback")
                                          or _entry.get("reason") or "")[:400]
                        break
                # 注入到 revise_feedback 供 LLM 重生成时参考
                if _last_feedback:
                    ctx.revise_feedback = list(ctx.revise_feedback) + [
                        f"[审核闸门反馈] 上一候选 (#{_tried+1}) "
                        f"未通过客观审核：{_last_feedback}"
                    ]
                # ★★ 2026-10-05 修（**真定位在这条路径上被丢掉** —— 三步论第 2 步）：
                #   本路径此前**只读闸门自己的日志**（`ctx[_gk]`），
                #   而 `ctx.audit_reject_feedback`（4.6 对抗证伪的 `to_feedback()`、
                #   4.5 oracle 判错反馈）**在 6.5 重写路径上从不被读取**。
                #   问题是：4.6 对抗是**唯一产出 `error_step` 具体定位**的检错环节
                #   （实测三题分别检出 boundary_missed / special_case_missed /
                #    skipped_step，置信 0.85~0.95）⇒ 最有用的一条被扔掉。
                #   现一并在闸门反馈后注入（去重、只取最近 3 条）。
                _audit_fb = [str(_x) for _x in (
                    getattr(ctx, "audit_reject_feedback", None) or [])
                    if str(_x).strip()]
                if _audit_fb:
                    _seen_af, _af_lines = set(), []
                    for _x in reversed(_audit_fb):
                        if _x in _seen_af:
                            continue
                        _seen_af.add(_x)
                        _af_lines.append(_x[:400])
                        if len(_af_lines) >= 3:
                            break
                    ctx.revise_feedback = list(ctx.revise_feedback) + [
                        "[已检出的具体错误（含定位步骤；此前未送达本题重写）] "
                        + " ｜ ".join(reversed(_af_lines))]
                self.record(ctx, _gk,
                            f"审核拒候选 #{_tried+1}（本档位重做剩余 "
                            f"{int(_rework_deadline - _t3.time())}s）继续换/重做")
                # 换下一候选（按置信度）试；候选换尽后 → 让 Solver 读
                # 审核反馈**重新生成**新候选（真正的"告诉 AI 错哪了"闭环）
                _next = None
                for _c in sorted(
                        ctx.candidates or [],
                        key=lambda c: getattr(c, "confidence", 0.0),
                        reverse=True):
                    if _c.answer == ctx.final_response:
                        continue
                    if not getattr(_c, "answer", ""):
                        continue
                    if _c.id in (getattr(ctx, "_gate_tried", []) or []):
                        continue
                    _next = _c
                    break
                if _next is None:
                    # 候选已全部试过 → 触发 Solver 读反馈重新生成（重做到对）
                    # 2026-09-04：重生成 ≈ 生成(~60-120s) + 闸门验证(秒级)，
                    # 剩余 <180s 时无法保证完成 → 不再打回，提交当前答案碰运气。
                    if _t3.time() < _rework_deadline - 180:
                        self.record(
                            ctx, _gk,
                            "所有候选未过客观审核，触发 Solver 读反馈重新生成"
                            f"（revise_feedback 已含 {_tried+1} 条审核定位）")
                        try:
                            # solver.run 内部：ctx.revise_round>0 且
                            # ctx.revise_feedback 非空 → 走 _generate_revise
                            # （读反馈定向修正，见 solver.py:122）。
                            # **先腾位**：候选池已满 6（cap）时 solver.run
                            # remaining=0 直接 return 不生成 → 保留已过
                            # 审核的最优候选，其余清空给新候选腾位。
                            _pass_cands = []
                            for _cc in (ctx.candidates or []):
                                if _cc.id in (getattr(ctx, "_gate_tried", []) or []):
                                    _pass_cands.append(_cc)  # 未过审核的作参考保留
                            # ★ 2026-09-17（M2）：`_gate_tried` 为空时**禁止清空**候选池。
                            # 此时 `_pass_cands` 必为空，原代码把原有全部候选（含较优/
                            # 正确者）删光，随后 revise 生成的 3 个成为唯一候选，且
                            # **没有任何新旧对比**。`_gate_tried` 为空意味着"一个候选都还
                            # 没试过"，清空属误删；保留原池，由 `_generate_revise` 自行腾位。
                            if _pass_cands:
                                ctx.candidates = _pass_cands[:3]  # 腾位
                            else:
                                self.record(ctx, "control",
                                            "审核未试过任何候选 → 保留原候选池"
                                            "（不清空，M2 2026-09-17）")
                            # ★★ 2026-10-05 修（**绕过全局轮数上限**）：本路径此前
                            #   直接 `revise_round += 1`，**不经过
                            #   `_deep_revise_loop` 入口的 `max_revise_rounds` 校验**
                            #   （校验在 :2652 附近，只作用于该函数入口）
                            #   ⇒ 6.5 这一段可以无限加轮（实测 revise_round 达 6
                            #   = 前面入口 4 轮 + 这里 2 轮，而全局上限是 5）。
                            #   现与 `_deep_revise_loop` 同口径先校验上限。
                            _max_total = int(getattr(
                                self.config, "max_revise_rounds", 5) or 5)
                            if getattr(ctx, "revise_round", 0) >= _max_total:
                                self.record(
                                    ctx, _gk,
                                    f"6.5 重做已达全局上限 {_max_total} 轮"
                                    "（max_revise_rounds），停止重做、提交当前答案")
                                break
                            # ★★ 2026-10-06 修（**让结构化定位成为重写的主导反馈**）：
                            #   实测题 000 在 revise_round=5 的情况下，反馈里结构化
                            #   「位置：」出现 **0 次** —— 因为 `_extract_revise_feedback`
                            #   被 `confidence >= 0.5` 挡住，而该题正是"**投票高置信但答错**"
                            #   ⇒ 结构化报告从未生成，模型只能靠 Lean「疑似自证」
                            #   与对抗那几条噪声重写（12/15 被噪声占据、且把答案改得更偏）。
                            #   本路径是**已经确定要重写**的地方 ⇒ 补齐一份"错在第几步、
                            #   哪句话、为什么"的定位。失败/未启用时返回空串，行为不变。
                            _has_struct = any("位置：" in str(_x)
                                              for _x in (ctx.revise_feedback or []))
                            if not _has_struct:
                                # 取"最优候选"作为报告对象：按 (正确票数, 置信度)
                                # 降序；属性缺失时安全回退到第一个候选。
                                try:
                                    _bcs = sorted(
                                        (ctx.candidates or []),
                                        key=lambda c: (
                                            -int(getattr(c, "vote_correct", 0) or 0),
                                            -float(getattr(c, "confidence", 0.0) or 0.0)))
                                    _best_for_report = _bcs[0] if _bcs else None
                                except Exception:  # noqa: BLE001
                                    _best_for_report = (
                                        (ctx.candidates or [None])[0])
                                try:
                                    _rep = self.verifier.structured_report_for(
                                        ctx, ctx.problem, _best_for_report,
                                        tool_findings=_collect_tool_findings(ctx))
                                    if _rep:
                                        ctx.revise_feedback = list(
                                            ctx.revise_feedback) + [_rep]
                                except Exception as _e_rp:  # noqa: BLE001
                                    logger.warning(
                                        "补取结构化报告失败（继续原流程）: %s",
                                        str(_e_rp)[:120])
                            ctx.revise_round = getattr(ctx, "revise_round", 0) + 1
                            _before = len(ctx.candidates or [])
                            self.solver.run(ctx)
                            if len(ctx.candidates or []) > _before:
                                _tried += 1
                                _fresh = ctx.candidates[-1]
                                # 2026-09-18：过闸门；脏答案不采纳、回 while 继续
                                if not self._set_final_response(
                                        ctx, _fresh.answer, "gate_rework"):
                                    self.record(ctx, _gk,
                                                f"重生成候选 #{_fresh.id} 的答案被判为"
                                                "非答案（过程叙述/脏文本）→ 不采纳")
                                    continue
                                g_ok = _gate.gate_final_answer(
                                    ctx, tier, _fresh.answer,
                                    getattr(_fresh, "reasoning", "") or "")
                                if g_ok:
                                    self.record(
                                        ctx, _gk,
                                        f"Solver 读审核反馈重生成的候选 "
                                        f"#{_fresh.id} 过闸门，采用")
                                continue  # 未过则回到 while 顶部继续
                        except Exception as _e2:  # noqa: BLE001
                            self.record(ctx, _gk,
                                        f"审核反馈重生成异常: {str(_e2)[:120]}")
                    self.record(ctx, _gk,
                                "重生成后仍无候选过审核或时间不足，停")
                    break
                # 2026-09-04：换候选=再验 1 次，剩余 <35s 时打完
                # 就到墙边，不再打回，直接提交当前答案（避免撞 1200s 无答案）。
                if _rework_deadline - _t3.time() < 35:
                    self.record(ctx, _gk,
                                f"剩余 {int(_rework_deadline - _t3.time())}s "
                                "不足完成换候选验证，停")
                    break
                _tried += 1
                ctx._gate_tried = list(getattr(ctx, "_gate_tried", []) or []) + [_next.id]
                # 2026-09-18：过闸门；脏答案不采纳、继续换下一个候选
                if not self._set_final_response(ctx, _next.answer, "gate_next"):
                    self.record(ctx, _gk,
                                f"换候选 #{_next.id} 的答案被判为非答案"
                                "（过程叙述/脏文本）→ 不采纳，继续换")
                    continue
                g_ok = _gate.gate_final_answer(
                    ctx, tier, _next.answer,
                    getattr(_next, "reasoning", "") or "")
                if g_ok:
                    self.record(ctx, _gk,
                                f"换候选 #{_next.id} 过审核闸门，采用其答案")
            if not g_ok:
                ctx.gate_rejected = True
                # ★ 2026-09-21 回滚：本重做循环把 ctx.final_response 一路往前
                #   覆盖（gate_next / gate_rework），而候选按置信度降序试探
                #   ⇒ 循环退出时终值 = 最后换上 = **置信度最低**者。
                #   实测 0921 arm2c2t：000 `\boxed{1}`(conf 0.667) → `20`
                #   (conf 0.000)；003 `\boxed{2026}` → `因此a_{2025} = 2026。`；
                #   004 `\boxed{1012}` → 187 字过程叙述。Lean 全降级时闸门
                #   对所有解答题恒拒 ⇒ 必然退到最弱候选。
                #   未过审核 = 无可信证据支持替换 ⇒ 回到重做前的答案。
                if (_pre_rework_final
                        and ctx.final_response != _pre_rework_final
                        and self._set_final_response(
                            ctx, _pre_rework_final, "gate_rollback")):
                    try:
                        ctx._gate_rollback = True
                    except Exception as _e_gr:  # noqa: BLE001
                        # ★ 2026-10-07 观测补齐（问题总账 §2.6「纯空吞异常」A 类）：
                        #   原为裸 `pass`。回滚标记是下游（诊断/报告）识别
                        #   "终答被回滚到重做前答案"的唯一信号；置位失败 ⇒
                        #   终答值已回滚但标记为假，事后归因自相矛盾且无痕迹。
                        self.record(ctx, _gk,
                                    f"gate_rollback 标记置位失败"
                                    f"（{type(_e_gr).__name__}: {str(_e_gr)[:120]}）"
                                    f"→ 终答已回滚但缺少下游标记")
                    self.record(ctx, _gk,
                                "候选尽数未过客观审核 → 回滚到重做前的答案"
                                f"（{str(_pre_rework_final)[:60]}），"
                                "不以置信度最低的候选收尾（2026-09-21）")
                self.record(ctx, _gk,
                            f"{tier} 档审核重做达上限仍拒（{_tried} 次换候选/重生成），"
                            "当前答案标 rejected 放行")
        except Exception as _e:  # noqa: BLE001  闸门异常绝不阻断
            self.record(ctx, _gk,
                        f"审核闸门异常，降级放行: {str(_e)[:120]}")
