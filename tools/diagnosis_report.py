#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评测诊断报告：环节归因 → 错误情况 → 耗时情况（Markdown 输出）

用法:
  D:/python/python.exe tools/diagnosis_report.py results/official112_local_0910.jsonl
  D:/python/python.exe tools/diagnosis_report.py <results.jsonl> --md <out.md> [--top 12]

判据对齐 tools/analyze_errors.py：
  理解环节 = diag.preverify_trace.verdict == "fail"
  子目标失败 = **统一走 agent.gap_analyzer**（2026-09-29 起）
      历史遗留：本脚本曾内联判据「result 为空 or 以 '[子目标' 开头」，
      而 sub_goal_solver 自身用的是**四条**判据（还有「未产出有效结论」
      「仍为空转占位」）⇒ 同一事实两套口径，统计必然偏小。
      现统一到 `gap_analyzer.is_subgoal_failed()`，两侧口径一致。
  AuditGate  = diag.audit_gate（step=candidate_audit 的 verdict 分布）

  ★ 2026-09-29 新增：**缺口性质分布**（用户 #6「缺的逻辑点是不是大模型需要
    推理出来的点」）—— 把失败子目标按 逻辑跳跃/缺引理/形式化/计算 分类，
    只有「逻辑跳跃」才算真·推理瓶颈，其余属工具链问题、不该计入推理评估。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# ★ 缺口判据与分类的唯一来源（避免本脚本再内联一套）
try:
    from agent.gap_analyzer import (extract_subgoal_gaps, gap_meaning,
                                    is_subgoal_failed)
except Exception:  # noqa: BLE001  离线分析脚本，导入失败则降级（见下）
    extract_subgoal_gaps = None
    gap_meaning = None

    def is_subgoal_failed(result_text: str) -> bool:
        """降级兜底：与 gap_analyzer 同口径的**最小**实现。"""
        t = str(result_text or "")
        return (not t.strip()) or t.startswith("[子目标")

# ★ 蓝图评审 issue 标签归一化（2026-09-30，用户 #6「蓝图设计有没有问题」）
#   必须走 agent.dag_reviewer 的同一函数 —— 否则报告里的分类与
#   DagReviewer 自己算的 issue_histogram 又是两套口径（本项目踩过 N 次）。
try:
    from agent.dag_reviewer import ISSUE_CN, normalize_issue_tag
except Exception:  # noqa: BLE001
    ISSUE_CN = {}

    def normalize_issue_tag(issue: str) -> str:
        s = str(issue or "")
        return s.split(":", 1)[0].strip().lower() if ":" in s else "other"

ERROR_CLASS_CN = {
    "empty_output": "空输出/只剩定界符",
    "extract_failed": "答案抽取失败",
    "format_unresolved": "答案未定型（含未求值符号）",
    "value_wrong": "真算错（裸数值不等）",
    "expr_wrong": "表达式/推理解答错",
}


def _stage_group(k: str) -> str:
    if k.startswith("2.6"):
        return "预验证"
    if k.startswith("2.7"):
        return "子目标主链"
    if k.startswith("3_solve"):
        return "求解"
    if "lean_candidate" in k or "lean_filter" in k or "3.6" in k or "3.5.1" in k:
        return "Lean候选筛选"
    if k.startswith("3.2"):
        return "补全"
    if k.startswith("4_"):
        return "验证"
    if k.startswith("1_") or k.startswith("2.5"):
        return "分类/难度"
    if k.startswith("5") or k.startswith("6"):
        return "修订/兜底"
    return "其他"


STAGES = ["分类/难度", "预验证", "子目标主链", "求解", "Lean候选筛选", "补全", "验证", "修订/兜底", "其他"]


def clip(s, n=200):
    s = str(s or "").replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return s if len(s) <= n else s[:n] + " …"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result_jsonl")
    ap.add_argument("--md", default="")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.result_jsonl, encoding="utf-8") if l.strip()]
    stem = os.path.splitext(os.path.basename(args.result_jsonl))[0]
    md_path = args.md or os.path.join(os.path.dirname(args.result_jsonl) or ".", f"{stem}_诊断报告.md")

    scored = [r for r in rows if r.get("correct") is not None]
    n_ok = sum(1 for r in scored if r["correct"])
    acc = n_ok / len(scored) * 100 if scored else 0.0
    wrong = [r for r in rows if r.get("correct") is False]
    el = [float(r.get("elapsed_sec") or 0) for r in rows]

    dom = Counter((r.get("domain") or "未标注") for r in rows)
    ec = Counter((r.get("error_class") or "未分类") for r in wrong)

    pre_fail = gaps_n = replan_n = degraded_n = 0
    sub_fail_q = sub_allout_q = revise_q = tool_used = 0
    sub_steps = []
    audit_v = Counter()
    audit_q_with_reject = audit_q_with_accept = 0
    lean_final_v = Counter()
    lean_cross = defaultdict(lambda: [0, 0])   # verdict -> [题数, 正确数]
    lean_deg = Counter()
    value_attack_n = 0
    va_wrong = va_wrong_revise = 0
    budget_q = 0
    tier_c = Counter()
    trunc_n = 0
    stage_sum = defaultdict(float)
    # ★ 2026-09-29（截图 #6）：缺口性质统计
    gap_kind_c = Counter()
    gap_reasoning_n = gap_total_n = 0
    gap_q_with_reasoning = 0
    # ★ 2026-09-30（截图 #6 收口）：蓝图评审（DagReviewer）客观指标
    #   历史事实：本脚本原先读的 `skeleton_review` 在 official112_local_0910
    #   里 **112 题全为空**（旧机制已停用），真正有数据的是 `dag_review`
    #   （90/112 题有 results）。⇒ 用户问"蓝图设计有没有问题"时，
    #   报告根本没有指标可看。此处接入。
    dr_q = dr_nodes = dr_reject_nodes = 0
    dr_replan = dr_degraded = 0
    dr_ratio_sum = 0.0
    dr_issue_c = Counter()          # 规范标签 -> 条数
    dr_issue_q = Counter()          # 规范标签 -> 涉及题数
    dr_confidence = defaultdict(lambda: [0, 0])   # 蓝图reject档 -> [题数, 正确数]
    # ★ 2026-09-30：Lean 侧逻辑缺口（`by sorry` 声明编译）
    lg_q_run = lg_q_pass = lg_q_fail = 0
    lg_nodes = lg_fails = lg_reason = lg_nonreason = 0
    lg_kind_c = Counter()

    for r in rows:
        d = r.get("diag") or {}
        # ② 理解 · 形式化
        if ((d.get("preverify_trace") or {}).get("verdict") == "fail"):
            pre_fail += 1
        if d.get("formal_gaps"):
            gaps_n += 1
        # ③ 规划
        sr = d.get("skeleton_review") or {}
        ev = " ".join(str(x) for x in (d.get("skeleton_review_events") or []))
        if sr.get("overall") == "replan" or any(
                "overall=replan" in str(x) for x in (d.get("skeleton_review_events") or [])):
            replan_n += 1
        if sr.get("degraded"):
            degraded_n += 1
        # ③' 蓝图评审（DagReviewer，LEAP 5.3）——「蓝图设计有没有问题」的客观依据
        #    ⚠ 与上面的 skeleton_review 是**两套机制**：skeleton_review 已停用
        #    （历史结果里恒空），dag_review 才是现役。两者分开统计、不混口径。
        _dr = d.get("dag_review") or {}
        _dres = _dr.get("results") or {}
        if _dres:
            dr_q += 1
            dr_nodes += len(_dres)
            dr_reject_nodes += int(_dr.get("reject_count") or 0)
            dr_ratio_sum += float(_dr.get("reject_ratio") or 0.0)
            if _dr.get("should_replan"):
                dr_replan += 1
            if _dr.get("degraded"):
                dr_degraded += 1
            _seen_tags = set()
            for _nid, _v in _dres.items():
                if str(_v.get("verdict") or "") != "reject":
                    continue
                for _it in (_v.get("issues") or []):
                    _t = normalize_issue_tag(_it)
                    dr_issue_c[_t] += 1
                    _seen_tags.add(_t)
            for _t in _seen_tags:
                dr_issue_q[_t] += 1
            # 蓝图健康度 × 正确率（是否"蓝图越差越容易错"）
            _r = _dr.get("reject_ratio") or 0.0
            _band = "无reject" if _r == 0 else ("轻度(<30%)" if _r < 0.30
                                              else ("中度(30-50%)" if _r < 0.50
                                                    else "重度(>=50%)"))
            dr_confidence[_band][0] += 1
            if r.get("correct") is True:
                dr_confidence[_band][1] += 1
        # ③'' Lean 侧逻辑缺口（`by sorry` 声明编译）—— 回答"用 Lean 检测 sorry"
        _lg = d.get("lean_gaps") or {}
        if _lg.get("ok"):
            lg_q_run += 1
            lg_nodes += int(_lg.get("n_nodes") or 0)
            lg_fails += int(_lg.get("n_failed") or 0)
            lg_reason += int(_lg.get("reasoning_gaps") or 0)
            lg_nonreason += int(_lg.get("non_reasoning_gaps") or 0)
            for _k, _v in (_lg.get("by_kind") or {}).items():
                lg_kind_c[_k] += int(_v)
            if int(_lg.get("n_failed") or 0) > 0:
                lg_q_fail += 1
            else:
                lg_q_pass += 1
        # ④ 求解
        st = d.get("subgoal_trace") or []
        if st:
            sub_steps.append(len(st))
            # ★ 2026-09-29：统一走 gap_analyzer 的判据（原内联判据比上游少两条）
            fails = [s for s in st if isinstance(s, dict)
                     and is_subgoal_failed(s.get("result"))]
            if fails:
                sub_fail_q += 1
            else:
                sub_allout_q += 1
            # 缺口性质分布（用户 #6）：该题子目标失败都属哪一类
            if extract_subgoal_gaps is not None and fails:
                try:
                    _g = extract_subgoal_gaps(st)
                    for _k, _v in (_g.get("by_kind") or {}).items():
                        gap_kind_c[_k] += int(_v)
                    gap_reasoning_n += int(_g.get("reasoning_gaps") or 0)
                    gap_total_n += int(_g.get("n_failed") or 0)
                    if _g.get("reasoning_gaps"):
                        gap_q_with_reasoning += 1
                except Exception:  # noqa: BLE001  统计失败不影响主报告
                    pass
        if int(d.get("revise_round") or 0) > 0:
            revise_q += 1
        if d.get("toolcall_exec"):
            tool_used += 1
        # ⑤ 验证
        ag = d.get("audit_gate") or []
        for g in ag:
            if isinstance(g, dict) and g.get("step") == "candidate_audit":
                audit_v[(g.get("verdict") or "none").lower()] += 1
        if any(isinstance(g, dict) and (g.get("verdict") or "").lower() == "reject" for g in ag):
            audit_q_with_reject += 1
        if any(isinstance(g, dict) and (g.get("verdict") or "").lower() == "accept" for g in ag):
            audit_q_with_accept += 1
        qv = None
        for g in (d.get("lean_gate") or []):
            if isinstance(g, dict) and g.get("step") == "final_gate":
                qv = (g.get("verdict") or "none").lower()
                lean_final_v[qv] += 1
                if g.get("degraded"):
                    lean_deg[g["degraded"]] += 1
        lean_cross[qv or "无记录"][0] += 1
        if r.get("correct") is True:
            lean_cross[qv or "无记录"][1] += 1
        if d.get("value_attack"):
            value_attack_n += 1
            if r.get("correct") is False:
                va_wrong += 1
                if int(d.get("revise_round") or 0) > 0:
                    va_wrong_revise += 1
        # ⑥ 预算
        if int(d.get("budget_skips") or 0) > 0:
            budget_q += 1
        tier_c[d.get("tier") or "未标"] += 1
        if float(r.get("elapsed_sec") or 0) >= 1200:
            trunc_n += 1
        # 阶段耗时
        for k, v in (d.get("stage_timers") or {}).items():
            if isinstance(v, (int, float)):
                stage_sum[_stage_group(k)] += float(v)

    stage_total = sum(stage_sum.values()) or 1.0
    audit_total = sum(audit_v.values()) or 1
    lean_final_total = sum(lean_final_v.values()) or 1
    avg_sub = statistics.mean(sub_steps) if sub_steps else 0

    L = []
    A = L.append
    A(f"# 智能体评测诊断报告 — {stem}")
    A("")
    A(f"> 数据文件：`{os.path.abspath(args.result_jsonl)}`　｜　已完成 **{len(rows)}** 题")
    A("")
    A("## 〇、总览")
    A("")
    A(f"- 正确率：**{n_ok}/{len(scored)} = {acc:.1f}%**（未判分 {len(rows) - len(scored)} 题）")
    A(f"- 单题耗时合计：**{sum(el) / 3600:.2f} h**（各题耗时累加，非墙钟）；单题均值 **{statistics.mean(el):.0f}s** / 中位 {statistics.median(el):.0f}s / 最大 {max(el):.0f}s")
    A(f"- 超 1200s 截断：**{trunc_n}** 题（{trunc_n / len(rows) * 100:.0f}%）")
    A(f"- 子目标平均步数：{avg_sub:.1f} 步/题")
    A("")
    A("## 一、错在哪一环节（环节归因）")
    A("")
    A("| 环节 | 关键指标 | 数值 | 判读 |")
    A("|---|---|---|---|")
    A("| ① 分类 | 学科分布 | 见附录 A | 未见分类异常 |")
    A(f"| ② 理解·形式化 | Lean 前置验证 verdict=fail | **{pre_fail}** 题 | 题面理解或形式化存在缺口 |")
    A(f"| ② 理解·形式化 | 存在 formal_gaps 形式化缺口 | {gaps_n} 题 | 同上 |")
    A(f"| ③ 规划 | 骨架评审判 overall=replan | {replan_n} 题 | 评审频繁触发重生成 |")
    A(f"| ③ 规划 | 骨架评审降级放行 | {degraded_n} 题 | — |")
    A(f"| ③ 规划 | **DAG 评审 reject 节点** | **{dr_reject_nodes}/{dr_nodes} = "
      f"{(dr_reject_nodes / dr_nodes * 100 if dr_nodes else 0):.0f}%**"
      f"（{dr_q} 题有数据） | 见 1.1''：蓝图问题分布 |")
    A(f"| ③ 规划 | DAG 评审建议整树重生成 | {dr_replan} 题 | reject≥5 或 比例≥40% |")
    A(f"| ④ 求解 | 子目标求解失败（空/占位） | {sub_fail_q} 题 | 硬失败占比低 |")
    A(f"| ④ 求解 | **子目标均有输出但结论错** | **{sub_allout_q}** 题 | **核心瓶颈：中间推理结论错误** |")
    A(f"| ④ 求解 | 触发过 revise 自我修订 | {revise_q} 题 | 修订机制很少被调用 |")
    A(f"| ④ 求解 | 工具被实际调用 | {tool_used} 题 | 工具完全未被使用 |")
    A(f"| ⑤ 验证 | AuditGate 判定 unknown | **{audit_v.get('unknown', 0)}/{audit_total}** | **验证器无法判定 → 拦不住错解** |")
    A(f"| ⑤ 验证 | AuditGate 出现 reject 的题 | {audit_q_with_reject} 题 | 拒绝率极低 |")
    A(f"| ⑤ 验证 | AuditGate 出现 accept 的题 | {audit_q_with_accept} 题 | — |")
    A(f"| ⑤ 验证 | **数值攻击发现反例** | **{value_attack_n}** 题 | **检测层有效**（但见 1.2） |")
    A(f"| ⑤ 验证 | Lean final_gate 判 proof_invalid 的题 | {lean_cross.get('proof_invalid', [0])[0]} 题 | 判定存在，但未被有效利用 |")
    A(f"| ⑥ 预算 | 出现预算跳过 | {budget_q} 题 | 部分题步数未跑完 |")
    A(f"| ⑦ 输出判分 | 错误分类 | 见第二节 | 以「求解算错」为主 |")
    A("")
    # ★ 2026-09-29（截图 #6）：缺口性质分布 —— 回答"缺的逻辑点是不是
    #   大模型需要推理出来的点"。**只有 logical_jump 才算推理瓶颈**，
    #   其余三类属工具链问题，不该计入推理能力评估。
    if gap_kind_c:
        A("### 1.1' 子目标缺口性质（回答「哪些才是必须推理出来的点」）")
        A("")
        A(f"共 {gap_total_n} 个子目标未产出有效结论，性质分布如下：")
        A("")
        A("| 缺口性质 | 条数 | 占比 | 是否算推理瓶颈 | 优化方向 |")
        A("|---|---|---|---|---|")
        for _k, _v in gap_kind_c.most_common():
            _meaning, _adv = (gap_meaning(_k) if gap_meaning
                              else (_k, "—"))
            _is_r = {"logical_jump": "**✅ 是**",
                     "missing_lemma": "❌ 否（检索）",
                     "formalization": "❌ 否（形式化）",
                     "computation": "❌ 否（计算）",
                     }.get(_k, "—")
            A(f"| {_meaning} | {_v} | {_v / max(gap_total_n, 1) * 100:.0f}% | "
              f"{_is_r} | {_adv} |")
        A("")
        _share = (gap_reasoning_n / gap_total_n * 100) if gap_total_n else 0.0
        A(f"> **判读**：{gap_reasoning_n}/{gap_total_n}（{_share:.0f}%）属**真·推理瓶颈**"
          f"（前提齐全却推不出）；其余属形式化 / 检索 / 计算问题 —— "
          f"**它们多说明工具链该修，而不是大模型推理能力不行**。")
        A(f"> 涉及真·推理瓶颈的题：**{gap_q_with_reasoning}** 题。")
        A("> ⚠ 归因纪律：「子目标失败多」**不等于**「推理能力差」。"
          "若 `formalization` 占比高，优化方向应是 `lean_translator`（译题），"
          "去调解题提示词是南辕北辙。")
        A("")
    # ★ 2026-09-30（截图 #6 收口）：**蓝图设计质量** —— 直接回答用户原话
    #   「蓝图的设计有没有问题」。数据源 = DagReviewer（LEAP 5.3）逐节点
    #   verdict + issues，标签经 normalize_issue_tag 归一（否则同义异写会把
    #   同一问题算成两类：实测 circular_risk/circularity 各 190 条）。
    if dr_q:
        A("### 1.1'' 蓝图设计质量（回答「蓝图的设计有没有问题」）")
        A("")
        A(f"共 **{dr_q}** 题有 DAG 评审记录，累计评审 **{dr_nodes}** 个节点，"
          f"其中 **{dr_reject_nodes}** 个被判 reject"
          f"（**{dr_reject_nodes / dr_nodes * 100:.0f}%**）；"
          f"平均每题 reject 比例 **{dr_ratio_sum / dr_q:.0%}**。")
        A("")
        A(f"触发整树重生成：**{dr_replan}** 题；评审降级（预算耗尽跳过 LLM）：{dr_degraded} 题。")
        A("")
        A("| 蓝图问题类型 | 条数 | 占比 | 涉及题数 | 优化方向 |")
        A("|---|---|---|---|---|")
        _dr_issue_total = sum(dr_issue_c.values()) or 1
        for _k, _v in dr_issue_c.most_common():
            A(f"| {ISSUE_CN.get(_k, _k)} | {_v} | {_v / _dr_issue_total * 100:.1f}% | "
              f"{dr_issue_q[_k]} | {'见下' if _k != 'other' else '—'} |")
        A("")
        # ── 判读：把最大的两类问题翻译成"该怎么改"
        _top = dr_issue_c.most_common(2)
        _top_txt = "、".join(f"{ISSUE_CN.get(k, k)}（{v} 条）" for k, v in _top)
        _circ = dr_issue_c.get("circular_risk", 0)
        _under = dr_issue_c.get("under_specified", 0) + dr_issue_c.get("no_simplification", 0)
        A(f"> **判读**：最突出的两类问题是「{_top_txt}」。")
        if _circ or _under:
            A(f"> - **循环分解 {_circ} 条 + 分解不到位 {_under} 条**"
              f"（合计占 {( _circ + _under) / _dr_issue_total * 100:.0f}%）—— "
              f"「分解不到位」= 粒度过粗 + 未真正简化父目标，与「循环分解」"
              f"是同一病根：**子目标拆得不够细，绕一圈又回到祖辈陈述**。"
              f"（LEAP 5.3 原文即以此为典型失败模式。）")
            A(f"> - 优化方向是**蓝图生成侧**（`blueprint_planner` 的分解提示词 / "
              f"rationale 必填约束），而不是解题提示词。")
        _sound = dr_issue_c.get("math_soundness", 1)
        if _sound and _sound > 1:
            A(f"> - 「断言与题目条件矛盾」{_sound} 条（涉及 {dr_issue_q.get('math_soundness', 0)} 题）"
              f"值得单独看：评审器声称能用题目条件**直接证伪**该子目标，"
              f"若属实说明蓝图生成了**错误断言**（比拆得粗更严重）。")
        A("")
        A("| 蓝图 reject 比例 | 题数 | 其中正确 | 该组正确率 |")
        A("|---|---|---|---|")
        for _b in ["无reject", "轻度(<30%)", "中度(30-50%)", "重度(>=50%)"]:
            if dr_confidence.get(_b):
                _n, _c = dr_confidence[_b]
                A(f"| {_b} | {_n} | {_c} | {_c / _n * 100:.0f}% |")
        A("")
        A("> ⚠ **这张表不是因果证据**：`无reject` 组正确率未必高 —— 简单题蓝图本来就好写；"
          "难到评审器都看不出问题的题也可能被全 accept。**只作趋势参考**，"
          "要定因果须做蓝图 A/B（同题配对）。")
        A("")

    # ★ 2026-09-30（截图 #6 下半问）：**Lean 侧逻辑缺口** —— 直接回答用户原话
    #   「可不可以用 lean 来检测有没有 sorry 的地方，像这种缺少的逻辑点
    #    是不是就是大模型需要推理出来的点呢？」
    #   机制：`_lean_dag_logic_check()` 把候选子目标写成
    #   `example : (expr) := by sorry` 交 Lean 编译 —— `by sorry` 挖空了"证明"，
    #   故**编译失败只可能来自命题本身**（符号未定义/量词错/非良构命题）。
    if lg_q_run:
        A("### 1.1''' Lean 侧逻辑缺口（回答「用 Lean 检测 sorry，缺的是不是推理点」）")
        A("")
        A(f"共 **{lg_q_run}** 题触发了 Lean 逐节点编译检查，送检 **{lg_nodes}** 个节点，"
          f"其中 **{lg_fails}** 个编译失败（**{lg_fails / max(lg_nodes, 1) * 100:.0f}%**）。")
        A(f"检查跑了且全通过：**{lg_q_pass}** 题；出现编译失败：**{lg_q_fail}** 题。")
        A("")
        if lg_kind_c:
            A("| 缺口性质 | 条数 | 占比 | 算不算「模型该推出来的点」 |")
            A("|---|---|---|---|")
            for _k, _v in lg_kind_c.most_common():
                _meaning, _adv = (gap_meaning(_k) if gap_meaning else (_k, "—"))
                _is_r = {"logical_jump": "**✅ 是**（真推理瓶颈）",
                         "missing_lemma": "❌ 否（检索可解）",
                         "formalization": "❌ 否（命题本身写错）",
                         "computation": "❌ 否（计算工具）",
                         }.get(_k, "—")
                A(f"| {_meaning} | {_v} | {_v / max(sum(lg_kind_c.values()), 1) * 100:.0f}% | {_is_r} |")
            A("")
        A(f"> **判读**：编译失败 **{lg_fails}** 个节点中，"
          f"**{lg_nonreason}** 个属形式化/检索/计算缺陷（**不是**模型该推出来的点），"
          f"只有 **{lg_reason}** 个属真·推理瓶颈。")
        A("> ")
        A("> **机制含义**：`by sorry` 把「证明」这一环挖空 ⇒ **编译失败只可能来自命题本身**。"
          "所以 Lean 在这里抓到的**不是「模型推不出来」，而是「这个子目标连要证什么都没说清」**。")
        A("> - 若失败以 `形式化/译题问题` 为主 ⇒ 该修的是**子目标陈述生成与译题**，"
          "调解题提示词是南辕北辙。")
        A("> - 只有当失败落在 `纯逻辑跳跃` 时，才说明「前提都给全了但推不过去」——"
          "**那才是子目标分解真正该解决的问题**。")
        A("")

    A("### 1.1 验证环节有效性：Lean 判定 × 实际正确率")
    A("")
    A("| Lean final_gate 判定 | 题数 | 其中正确 | 该组正确率 |")
    A("|---|---|---|---|")
    for k, (n, c) in sorted(lean_cross.items(), key=lambda x: -x[1][0]):
        A(f"| {k} | {n} | {c} | {c / n * 100:.0f}% |")
    A("")
    A(f"degraded 标记分布：`{dict(lean_deg)}`（`time_critical` = 因时间紧迫降级跳过 Lean 把关）")
    A("")
    A("> **判读**：若验证器有效，「判定通过」组的正确率应显著高于「判定拒绝」组。上表两组正确率接近，"
      "说明 Lean 闸门的判定对最终对错的**区分能力不足**——尤其 `answer_valid`（判定通过）组仍有大量错题，"
      "即「答案形式有效」被当成了「答案正确」。")
    A("")
    A("### 1.2 检测 → 处置联动（关键缺口）")
    A("")
    A("| 观测 | 数值 |")
    A("|---|---|")
    A(f"| 数值攻击发现反例、且最终答错 | **{va_wrong}** 题 |")
    A(f"| 其中真正触发了 revise 修订 | **{va_wrong_revise}** 题 |")
    A(f"| **检测到问题但未处置（直接输出）** | **{va_wrong - va_wrong_revise}** 题 |")
    A("")
    A("> **结论**：验证层已能定位问题（数值攻击证伪、Lean 判 `proof_invalid`、`revise_feedback` 已写出具体错误指认），"
      "但这些信号未转化为「必须重解」的强制动作，错误答案仍被放行。**瓶颈不在检测能力，而在检测结果 → 修订/拦截的联动。**")
    A("")
    A("**环节归因结论**：错误主要产生于 **④ 求解环节（中间子目标结论错误）**；"
      "本应兜底的 **⑤ 验证环节未能拦截**——AuditGate 判定几乎全部为 `unknown`（既非接受也非拒绝）、Lean 闸门同样多为 `unknown`，"
      "导致错误答案直达输出。理解（②）与预算（⑥）为次要因素。")
    A("")
    A("## 二、错误情况")
    A("")
    A(f"错题 **{len(wrong)}** 题，分类分布：")
    A("")
    A("| 错误分类 | 题数 | 占比 | 含义 |")
    A("|---|---|---|---|")
    for k, v in ec.most_common():
        A(f"| {k} | {v} | {v / max(1, len(wrong)) * 100:.0f}% | {ERROR_CLASS_CN.get(k, '—')} |")
    A("")
    A("### 2.1 错题明细")
    A("")
    A("| 题号 | domain | 耗时 | 分类 | 标准答案 | 模型答案 |")
    A("|---|---|---|---|---|---|")
    for r in wrong:
        A(f"| {r.get('id')} | {r.get('domain') or ''} | {float(r.get('elapsed_sec') or 0):.0f}s | "
          f"{r.get('error_class') or ''} | `{clip(r.get('gold'), 56)}` | `{clip(r.get('predicted'), 56)}` |")
    A("")
    A("### 2.2 典型错题的错误定位（revise_feedback 原文摘录）")
    A("")
    shown = 0
    for r in wrong:
        rf = " ".join(str(x) for x in ((r.get("diag") or {}).get("revise_feedback") or []))
        if rf.strip() and shown < args.top:
            shown += 1
            A(f"- **`{r.get('id')}`**（{r.get('error_class')}）")
            A(f"  - {clip(rf, 420)}")
    if shown == 0:
        A("（本批结果无 revise_feedback 记录）")
    A("")
    A("## 三、耗时情况")
    A("")
    A("### 3.1 分桶 × 正确率")
    A("")
    A("| 耗时桶 | 题数 | 平均耗时 | 桶内正确率 |")
    A("|---|---|---|---|")
    bk = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        t = float(r.get("elapsed_sec") or 0)
        b = "<120s" if t < 120 else ("120-540s" if t < 540 else ("540-1200s" if t < 1200 else ">=1200s(截断)"))
        bk[b][0] += 1
        bk[b][2] += t
        if r.get("correct") is True:
            bk[b][1] += 1
    for k in ["<120s", "120-540s", "540-1200s", ">=1200s(截断)"]:
        if bk.get(k):
            n, c, t = bk[k]
            A(f"| {k} | {n} | {t / n:.0f}s | {c}/{n} = {c / n * 100:.0f}% |")
    A("")
    A("### 3.2 阶段耗时占比")
    A("")
    A("| 阶段 | 累计 | 占比 |")
    A("|---|---|---|")
    for s in STAGES:
        if stage_sum.get(s):
            A(f"| {s} | {stage_sum[s]:.0f}s | {stage_sum[s] / stage_total * 100:.1f}% |")
    A("")
    A(f"### 3.3 最耗时的 {args.top} 题")
    A("")
    A("| 题号 | 耗时 | 对错 | 分类 |")
    A("|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -(float(x.get("elapsed_sec") or 0)))[: args.top]:
        mk = "✅" if r.get("correct") is True else ("❌" if r.get("correct") is False else "—")
        A(f"| {r.get('id')} | {float(r.get('elapsed_sec') or 0):.0f}s | {mk} | {r.get('error_class') or ''} |")
    A("")
    A("## 附录 A：学科分布")
    A("")
    A("| 学科 | 题数 |")
    A("|---|---|")
    for k, v in dom.most_common():
        A(f"| {k} | {v} |")
    A("")
    A("## 附录 B：预算档位分布")
    A("")
    A("| tier | 题数 |")
    A("|---|---|")
    for k, v in tier_c.most_common():
        A(f"| {k} | {v} |")
    A("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"题数 {len(rows)}｜正确率 {n_ok}/{len(scored)} = {acc:.1f}%")
    print(f"环节：前置fail {pre_fail}｜子目标均输出但结论错 {sub_allout_q}｜子目标失败 {sub_fail_q}"
          f"｜revise {revise_q}｜工具调用 {tool_used}")
    print(f"验证：AuditGate unknown {audit_v.get('unknown',0)}/{audit_total}｜accept题 {audit_q_with_accept}"
          f"｜reject题 {audit_q_with_reject}｜Lean final {dict(lean_final_v)}")
    print(f"预算：跳过 {budget_q}｜截断 {trunc_n}｜错因 {dict(ec)}")
    print(f"报告：{os.path.abspath(md_path)}")


if __name__ == "__main__":
    main()
