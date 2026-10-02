#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_audit.py — 环节审计：每个阶段/机制的「原定目的 → 完成判据 → 实测结论」

为什么需要它
    `cloud_health_report.py` 的 C 节只报「触发次数」，但**次数为 0 有两种含义**：
      · 设计上就该跑却没跑 ⇒ **真 bug**
      · 设计上关闭 / 前置条件不满足 ⇒ **正常**
    只看次数无法区分，会把「正常」误报成「失效」（反之亦然）。
    本脚本对每个环节给出**原定目的**与**可达判据**，再判 ✅/⚪/❌ 三态。

结论三态
    ✅ 完成     设计上应跑，实测有产出
    ⚪ 设计如此  开关默认关 / 前置条件结构性不满足（非缺陷）
    ❌ 未完成   设计上应跑，实测无产出（需查因）

用法
    python tools/stage_audit.py <run.jsonl> [--log <run.log>] [--out <x.md>]
"""
# 2026-10-01 去同名：load -> load_jsonl_rows（读 JSONL 成行列表；原名 load 太泛，无法自解释）
from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 阶段意图表
# (阶段名, 中文名, 原定目的, 完成判据, 预期态)
#   预期态：'run' = 设计上应跑；'cond' = 条件触发（凭条件判）；'off' = 设计上关闭
#
# ★★ 判据必须用「产出物」而不是「耗时」——
#    `_stage_start` 的计时是「本阶段开始 → 下一阶段开始」，本身极快的阶段
#    （如 6_format 纯字符串处理）会记成 0.0s，**不能据此判定「没跑」**。
#    2026-09-21 首版误把 6_format / 0_paper_pacer 判成「未完成」，已修正。
STAGES_stage_audit = [
    # ★ 2026-10-02 移除 `0_paper_pacer`（阶段已删，用户 2026-10-02 点名「全卷配速删了」）；
    #   阶段名是稳定契约，下方按名分派的 handler 保留，供**历史 jsonl** 兼容渲染。
    # ★ 2026-10-02 移除 `1_classify` / `2.5_difficulty`（前者阶段已删、后者统一档位后
    #   空转）；此前报告仍含这两个阶段名（留痕）。下方按名分派的 handler 保留，
    #   供**历史 jsonl** 兼容渲染。
    # ★ 2026-10-02 补登 `1.2_theorem_hint`（现行阶段，此前审计清单漏登 ⇒ 其耗时从未进
    #   审计/报告）；其 `_stage_start` 无条件执行 ⇒ 预期态 run。
    ("1.2_theorem_hint", "定理检索提示",
     "leansearch 到 Mathlib 检索定理并写入 ctx，供 2.6/3_solve 提示词使用"
     "（超时可跳过，失败不阻断主流程）",
     "阶段耗时 > 0（恒被 _stage_start/_stage_stop 包裹）", "run"),
    ("2.6_pre_audit", "题意理解确认",
     "Lean 前置形式化：题目转 Lean 声明编译校验，失败带错强制重审",
     "preverify_trace 非空 或 lean_preverify 记录", "cond"),
    # ★ 2026-10-02 移除 `2.65_calc_prewarm`（calc 板块 2026-10-01 整体删除时的漏网残留）；
    #   其 D 类兜底 handler 保留，供**历史 jsonl** 兼容渲染。
    ("2.7_subgoal_main", "子目标主循环",
     "全部档位统一先做一次子目标分解 + 逐步求解（v2.9 主路径）",
     "subgoal_trace 非空", "run"),
    ("3_solve", "主体求解",
     "生成候选解答（deep 档先走 Plan-and-Execute）",
     "candidates 非空", "run"),
    ("3.2_complete", "截断候选续写",
     "对被 max_tokens 截断的候选补写完整（每档 max_completions 个）",
     "候选数 > 初始候选数", "cond"),
    ("3.3_improve", "无条件自改进",
     "生成后、验证前先 review+improve 一遍（IMO2025 论文：初始解质量低，此步显著改进；本地实测 22.2%→31.1%）",
     "control_events 含 3.3/improve 记录", "run"),
    ("3.4_collab", "三 Agent 协作",
     "deep 档难题：协作（解题→审查→整合→反复验证）",
     "control_events 含「三Agent协作」记录", "cond"),
    ("3.5_subgoal_sup", "子目标补充候选",
     "非 deep 档候选不足时补一轮子目标分解（**已被 2.7 取代**）",
     "control_events 含「子目标分解补充候选」", "off"),
    ("3.6_audit_filter", "候选客观审核",
     "Lean 双通道 + AuditGate 串行审核候选，淘汰 proof_invalid",
     "lean_gate 非空", "run"),
    ("4_verify", "验证器投票",
     "多候选投票定对错（投票数按档位）",
     "verdicts 非空", "run"),
    ("4.5_oracle", "Oracle 客观复核",
     "deep 档用 AnswerOracle 客观复核 best_cluster（区别于同源自评）",
     "control/oracle 记录 或 stage 耗时 > 0", "cond"),
    ("4.6_adv", "对抗式证伪",
     "正向通过后主动证伪，抓漏检（仅当确有候选被正向判对时）",
     "stage 耗时 > 0", "cond"),
    ("5_revise_or_fallback", "修订/兜底",
     "全部 0 正确票时：deep 走 revise 回环，其他档直接兜底求解",
     "revise_round > 0 或兜底记录", "cond"),
    ("5.5_low_conf", "低置信强制复核",
     "best_cluster 置信度 < 0.5 且时间宽裕时，不接受低共识，触发 revise 提升共识",
     "stage 耗时 > 0", "cond"),
    ("6_format", "格式化输出",
     "最终响应格式化（纯字符串处理，本身极快 ⇒ 耗时必然≈0）",
     "response_full 非空", "run"),
    ("6.5_audit_gate", "最终答案闸门",
     "最终答案过 Lean/AuditGate 双后端；proof_invalid/unknown → 拒绝换候选",
     "audit_gate 含 final 记录", "run"),
]

# ---------------------------------------------------------------- 机制意图表
# (diag 字段, 中文名, 原定目的, 预期态)
MECHS = [
    ("lean_gate", "Lean 硬验证闸门", "编译验证候选/答案，淘汰 proof_invalid 并收 revise 反馈", "cond"),
    ("audit_gate", "审计闸门", "候选与最终答案的客观审核（Level0 数值代回等）", "run"),
    ("control_events", "流程控制事件", "记录兜底/协作/触发等控制流决策", "run"),
    ("revise_events", "修订事件", "验证不过时的定向修正记录", "cond"),
    ("skeleton_review_events", "骨架评审", "对蓝图骨架做多轮评审（arm2 专用）", "off"),
    ("dag_replan_events", "DAG 重规划", "依赖图变化时重规划（arm2 专用）", "off"),
    ("subgoal_trace", "子目标轨迹", "子目标分解的执行轨迹", "run"),
    ("answer_form_events", "答案形式检查", "答案格式/形式合规检查", "run"),
    ("p1_check_events", "P1 检查", "候选质量一级检查", "cond"),
    ("phase_budget_events", "阶段预算事件", "各阶段预算的收紧/恢复记录", "run"),
    ("toolcall_text_detected", "伪工具调用检测", "模型在正文里「假装」调用工具的检测", "run"),
    ("revise_feedback", "修订反馈", "喂给修订的反馈文本", "cond"),
    ("value_attack", "数值攻击", "对候选做数值反例攻击（C-lite）", "cond"),
    ("exhaust_diag", "穷尽性诊断", "枚举/穷尽性搜索的可行性诊断", "cond"),
    ("deep_review", "深度评审", "验证器的深度复核（deep_final）", "cond"),
    ("formal_gaps", "形式化缺口", "Lean 形式化中未覆盖的缺口记录", "cond"),
    ("lemma_repo", "引理库", "累积的引理仓库（use_lemma_accumulation 关闭时为空）", "off"),
    ("toolcall_mode", "工具调用模式", "记录工具循环的启用模式", "run"),
    ("toolcall_exec", "工具调用执行", "工具循环里实际执行的调用", "cond"),
    ("numericize_events", "数值化", "把符号问题数值化以便验证", "cond"),
    ("objective_check_events", "客观检查", "客观数值回代检查", "cond"),
    ("expression_eval_events", "表达式求值", "表达式求值验证", "cond"),
    ("final_postprocess_change_events", "终稿后处理改写", "格式化阶段对答案的改写记录", "cond"),
    ("lean_feedback_revise_events", "Lean 反馈修订", "把 Lean 错误反馈给修订回环", "cond"),
    ("subgoal_l0c", "子目标 L0c", "子目标一级检查", "cond"),
    ("subgoal_recover_events", "子目标恢复", "子目标失败后的恢复", "cond"),
    ("subgoal_replan_needed_events", "子目标重规划", "子目标需重规划的判定", "cond"),
    ("symbolic_crosscheck_events", "符号交叉核对", "符号解与数值解交叉核对", "cond"),
    ("symbolic_solve_events", "符号求解", "符号求解通道（symbolic_solve_enabled）", "off"),
    ("dag_review", "DAG 评审", "蓝图依赖图评审", "off"),
    ("preverify_trace", "预验证轨迹", "前置形式化的细粒度轨迹", "cond"),
    ("sketch_audit", "骨架审计", "骨架/草图的审计（LEAP Stage2/3，未接入）", "off"),
]


def load_jsonl_rows(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return rows


def _log_evidence(key: str, logtxt: str) -> tuple[int, str]:
    """从**日志**取该阶段的执行痕迹（jsonl 埋点缺失时的兜底判据）。

    ★ 2026-09-21 教训：不能只靠 jsonl。`2.6_pre_audit` 的
      `LeanPreVerifier.run()` 成功路径**不写 record**，jsonl 侧看起来「没跑」，
      但日志里明明有 `走 mcp 后端：preverify_*.lean`。
      只信 jsonl 会把「在跑」误判成「未跑」。
    返回 (命中次数, 命中的模式描述)。
    """
    if not logtxt:
        return 0, ""
    PATS = {
        "2.6_pre_audit": [r"走 mcp 后端：preverify_",
                          r"前置形式化", r"lean_preverify"],
        "2.65_calc_prewarm": [r"prewarm", r"预计算"],
        "3.4_collab": [r"三Agent协作", r"协作", r"collab"],
        "3.5_subgoal_sup": [r"子目标分解补充候选"],
        "4.5_oracle": [r"oracle", r"Oracle"],
        "5.5_low_conf": [r"低置信"],
        "0_paper_pacer": [r"软预算帽", r"paper_pacer"],
    }.get(key, [])
    for p in PATS:
        n = len(re.findall(p, logtxt))
        if n:
            return n, p
    return 0, ""


def judge_stage(key, rows, ts, logtxt):
    """按**产出物**判定阶段是否完成，返回 (实测描述, 结论)。

    ★ 不用耗时做判据：`_stage_start` 计的是「本阶段开始→下一阶段开始」，
      本身极快的阶段（6_format 纯字符串处理）必然记成 0.0s。
    ★ jsonl 判不出时用**日志侧痕迹**兜底（见 `_log_evidence`）。
    """
    n = len(rows)
    if not ts:
        return "无该阶段埋点", "未完成"
    med, mx, nz = st.median(ts), max(ts), sum(1 for x in ts if x > 0.05)

    def cnt(pred):
        return sum(1 for r in rows if pred(r))

    d = lambda r: (r.get("diag") or {})  # noqa: E731
    ctrl = lambda r, s: any(  # noqa: E731
        s in str(e) for e in (d(r).get("control_events") or []))

    ok = None
    extra = ""
    if key == "0_paper_pacer":
        # ★ soft_budget 在 diag 里，不在顶层（首版从顶层取 ⇒ 误判为未跑）
        ok = cnt(lambda r: ctrl(r, "paper_pacer") or d(r).get("soft_budget") is not None)
        extra = "(soft_budget 已设置)"
    elif key == "1_classify":
        ok = cnt(lambda r: bool(d(r).get("question_type")))
    elif key == "2.5_difficulty":
        ok = cnt(lambda r: bool(d(r).get("tier")))
    elif key == "2.6_pre_audit":
        # ⚠ 该阶段成功时**不写 record**（只在异常时记 lean_preverify），
        #    且 `preverify_trace` 实测恒空 ⇒ **jsonl 侧无判据**。
        #    真实证据在服务器 `deploy/mathlib-olean/_lean_trash/preverify_*.lean`
        #    与日志的「走 mcp 后端：preverify_*」。故本项单独标「埋点不足」。
        ok = None
    elif key == "2.65_calc_prewarm":
        ok = cnt(lambda r: bool(d(r).get("calc_prewarm_events")))
    elif key == "2.7_subgoal_main":
        ok = cnt(lambda r: bool(d(r).get("subgoal_trace")))
    elif key == "3_solve":
        ok = cnt(lambda r: bool(r.get("candidates")))
    elif key == "3.2_complete":
        ok = cnt(lambda r: len(r.get("candidates") or []) > 1)
        extra = "(>1 候选)"
    elif key == "3.3_improve":
        ok = cnt(lambda r: ctrl(r, "3.3") or ctrl(r, "improve") or nz > 0)
    elif key == "3.4_collab":
        ok = cnt(lambda r: ctrl(r, "三Agent协作") or ctrl(r, "3.4"))
    elif key == "3.5_subgoal_sup":
        ok = cnt(lambda r: ctrl(r, "子目标分解补充候选"))
    elif key == "3.6_audit_filter":
        ok = cnt(lambda r: bool(d(r).get("lean_gate")))
    elif key == "4_verify":
        ok = cnt(lambda r: bool(r.get("verdicts")))
    elif key == "4.5_oracle":
        ok = nz
    elif key == "4.6_adv":
        ok = nz
    elif key == "5_revise_or_fallback":
        ok = cnt(lambda r: (d(r).get("revise_round") or 0) > 0)
    elif key == "5.5_low_conf":
        ok = nz
    elif key == "6_format":
        ok = cnt(lambda r: bool(r.get("response_full") or r.get("response")))
        extra = "(最终响应非空)"
    elif key == "6.5_audit_gate":
        ok = cnt(lambda r: bool(d(r).get("audit_gate")))
    else:
        ok = nz

    # 日志侧兜底
    loghit = ""
    if logtxt and ok == 0:
        for pat in ("paper_pacer", "calc_prewarm", "三Agent协作"):
            if key.split("_")[0] in pat and pat in logtxt:
                loghit = "（日志有痕迹）"
    logn, logpat = _log_evidence(key, logtxt)
    if ok is None:
        # jsonl 侧无判据 ⇒ 用**日志侧痕迹**兜底
        if logn:
            return ("耗时中位 %.1fs；**jsonl 无判据，但日志命中 `%s` %d 次** ⇒ 实际在跑；"
                    "max %.1fs" % (med, logpat, logn, mx),
                    "完成（日志侧证据）")
        return ("耗时中位 %.1fs；max %.1fs；**jsonl 与日志均无判据**" % (med, mx),
                "无法判定")
    meas = "耗时中位 %.1fs；**产出 %d/%d 题**%s；max %.1fs" % (med, ok, n, extra, mx)
    if logn:
        meas += "；日志命中 `%s` %d 次" % (logpat, logn)
    if ok >= n * 0.5:
        v = "完成"
    elif ok > 0:
        v = "部分完成"
    else:
        # ★ jsonl 说 0，但日志有痕迹 ⇒ 埋点缺口，不是功能失效
        v = ("完成（jsonl 无埋点，日志侧 %d 次）" % logn) if logn else "未完成"
    return meas, v


def main() -> int:
    ap = argparse.ArgumentParser(description="环节审计：目的 → 判据 → 结论")
    ap.add_argument("jsonl")
    ap.add_argument("--log", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = load_jsonl_rows(args.jsonl)
    if not rows:
        print("解析出 0 条记录")
        return 2

    n = len(rows)
    logtxt = ""
    if args.log and os.path.isfile(args.log):
        logtxt = open(args.log, encoding="utf-8", errors="replace").read()

    # ---- 阶段：耗时 + 覆盖题数 ----
    stage_t = defaultdict(list)
    for r in rows:
        for k, v in ((r.get("diag") or {}).get("stage_timers") or {}).items():
            try:
                stage_t[k].append(float(v))
            except (TypeError, ValueError):
                pass

    # ---- 机制：触发次数分布 ----
    mech_c = defaultdict(list)
    for r in rows:
        d = r.get("diag") or {}
        for f, *_ in MECHS:
            v = d.get(f)
            if v is None:
                mech_c[f].append(None)
            elif isinstance(v, (list, dict)):
                mech_c[f].append(len(v))
            else:
                try:
                    mech_c[f].append(float(v))
                except (TypeError, ValueError):
                    mech_c[f].append(None)

    out = []
    W = out.append

    W("# 环节审计：原定目的 → 完成判据 → 实测结论")
    W("")
    W("数据源：%s（%d 题）" % (os.path.basename(args.jsonl), n))
    if logtxt:
        W("日志：%s" % os.path.basename(args.log))
    W("")
    W("结论三态：**完成** = 应跑且跑出东西；**设计如此** = 开关默认关或前置条件")
    W("结构性不满足；**未完成** = 应跑却无产出（需查因）。")
    W("")

    # ---------------- 阶段表 ----------------
    W("## 一、19 个阶段（判据基于**产出物**，非耗时）")
    W("")
    W("| 阶段 | 原定目的 | 完成判据 | 实测 | 结论 |")
    W("|---|---|---|---|---|")
    stats = Counter()
    for key, cn, purpose, crit, expect in STAGES_stage_audit:
        ts = stage_t.get(key, [])
        meas, verdict = judge_stage(key, rows, ts, logtxt)
        if expect == "off" and verdict == "未完成":
            verdict = "设计如此"
        stats[verdict] += 1
        W("| %s（%s） | %s | %s | %s | **%s** |" % (
            key, cn, purpose, crit, meas, verdict))
    W("")
    W("统计：%s" % "，".join("%s %d 项" % (k, v) for k, v in stats.items()))
    W("")

    # ---------------- 机制表 ----------------
    W("## 二、%d 个机制字段" % len(MECHS))
    W("")
    W("| 机制 | 原定目的 | 实测 | 结论 |")
    W("|---|---|---|---|")
    stats2 = Counter()
    for f, cn, purpose, expect in MECHS:
        vals = [v for v in mech_c.get(f, []) if v is not None]
        if not vals:
            meas = "该轮无此字段"
            verdict = "无数据"
        else:
            zero = sum(1 for v in vals if not v)
            mx = max(vals)
            meas = "触发 %d/%d 题（中位 %.4g，max %.4g）" % (
                len(vals) - zero, len(vals), st.median(vals), mx)
            if zero == len(vals):
                verdict = "设计如此" if expect == "off" else (
                    "未完成" if expect == "run" else "未触发（条件未满足）")
            else:
                verdict = "完成"
        stats2[verdict] += 1
        W("| %s | %s | %s | **%s** |" % (f, purpose, meas, verdict))
    W("")
    W("统计：%s" % "，".join("%s %d 项" % (k, v) for k, v in stats2.items()))
    W("")

    # ---------------- 日志侧补充 ----------------
    if logtxt:
        W("## 三、日志侧补充判据")
        W("")
        W("| 判据 | 计数 | 说明 |")
        W("|---|---|---|")
        for pat, label, note in (
            (r"mcp 返回成功：ok=True", "Lean 编译成功", "应 > 0；恒 0 = 环境或代码质量全线失败"),
            (r"mcp 返回成功：ok=False", "Lean 编译失败", "与上一行对照看成功率"),
            (r"走 mcp 后端", "走 MCP 后端", "MCP 通道被实际使用"),
            (r"回落 bridge", "回落 bridge", "应尽量为 0"),
            (r"axiom 检查通过", "axiom 检查通过", "修 example 盲区后此数应上升"),
            (r"axiom 检查发现 sorryAx", "★ 检出 sorryAx", "该数 > 0 说明防线真的在拦"),
            (r"axiom 检查改用 example 改写副本", "★ example 改写副本", "新修复的触发证据"),
            (r"multi_attempt 找到可用策略", "multi_attempt 找到策略", "MCP 增强 B4"),
            (r"hover 查证", "hover 查证", "MCP 增强 B6"),
        ):
            W("| %s | %d | %s |" % (label, len(re.findall(pat, logtxt)), note))
        W("")

    text = "\n".join(out).replace("|", "\u2223") if False else "\n".join(out)
    # 只把**正文里**的竖线替换掉会破坏表格，故此处保留表格竖线；
    # 交给 md→docx 生成器时再按需处理。
    print(text)
    if args.out:
        # 写 md：表格竖线保留（生成器已能处理表格），正文另行约定
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("\n已写出 %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
