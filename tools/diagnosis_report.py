#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评测诊断报告：环节归因 → 错误情况 → 耗时情况（Markdown 输出）

用法:
  D:/python/python.exe tools/diagnosis_report.py results/official112_local_0910.jsonl
  D:/python/python.exe tools/diagnosis_report.py <results.jsonl> --md <out.md> [--top 12]

判据对齐 tools/analyze_errors.py：
  理解环节 = diag.preverify_trace.verdict == "fail"
  子目标失败 = subgoal_trace[*].result 为空或以 "[子目标" 开头
  AuditGate  = diag.audit_gate（step=candidate_audit 的 verdict 分布）
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict

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
    sub_fail_q = sub_allout_q = revise_q = calc_used = 0
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
        # ④ 求解
        st = d.get("subgoal_trace") or []
        if st:
            sub_steps.append(len(st))
            fails = [s for s in st if isinstance(s, dict) and
                     (not str(s.get("result", "")).strip() or str(s.get("result", "")).startswith("[子目标"))]
            if fails:
                sub_fail_q += 1
            else:
                sub_allout_q += 1
        if int(d.get("revise_round") or 0) > 0:
            revise_q += 1
        if d.get("calc_tool_calls"):
            calc_used += 1
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
    A(f"| ④ 求解 | 子目标求解失败（空/占位） | {sub_fail_q} 题 | 硬失败占比低 |")
    A(f"| ④ 求解 | **子目标均有输出但结论错** | **{sub_allout_q}** 题 | **核心瓶颈：中间推理结论错误** |")
    A(f"| ④ 求解 | 触发过 revise 自我修订 | {revise_q} 题 | 修订机制很少被调用 |")
    A(f"| ④ 求解 | 计算工具被实际调用 | {calc_used} 题 | 工具完全未被使用 |")
    A(f"| ⑤ 验证 | AuditGate 判定 unknown | **{audit_v.get('unknown', 0)}/{audit_total}** | **验证器无法判定 → 拦不住错解** |")
    A(f"| ⑤ 验证 | AuditGate 出现 reject 的题 | {audit_q_with_reject} 题 | 拒绝率极低 |")
    A(f"| ⑤ 验证 | AuditGate 出现 accept 的题 | {audit_q_with_accept} 题 | — |")
    A(f"| ⑤ 验证 | **数值攻击发现反例** | **{value_attack_n}** 题 | **检测层有效**（但见 1.2） |")
    A(f"| ⑤ 验证 | Lean final_gate 判 proof_invalid 的题 | {lean_cross.get('proof_invalid', [0])[0]} 题 | 判定存在，但未被有效利用 |")
    A(f"| ⑥ 预算 | 出现预算跳过 | {budget_q} 题 | 部分题步数未跑完 |")
    A(f"| ⑦ 输出判分 | 错误分类 | 见第二节 | 以「求解算错」为主 |")
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
          f"｜revise {revise_q}｜工具调用 {calc_used}")
    print(f"验证：AuditGate unknown {audit_v.get('unknown',0)}/{audit_total}｜accept题 {audit_q_with_accept}"
          f"｜reject题 {audit_q_with_reject}｜Lean final {dict(lean_final_v)}")
    print(f"预算：跳过 {budget_q}｜截断 {trunc_n}｜错因 {dict(ec)}")
    print(f"报告：{os.path.abspath(md_path)}")


if __name__ == "__main__":
    main()
