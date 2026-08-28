# -*- coding: utf-8 -*-
"""离线错误分析：用本地严格判分器重判历史评测结果，并输出错误分类分布。

目的：在花任何 LLM 调用之前，先拿到"严格口径"的真实基线与瓶颈分布（Phase 0 的预演）。
这与 run_eval.py 在线跑的区别在于：本脚本复用历史 report 里已经有的模型作答，
零 API 成本、秒级出结果。在线基线跑完后应与本脚本结论互相印证。

⚠️ 口径前提（解读数字时必须注意）：
  历史 report 里的 intern_answer 由 **测试工具/ 这条本地评测流水线**产出
  （测试工具/intern_s1.py 自带的 _extract_boxed / _extract_tail_fallback），
  与比赛路径（user_agent.py → agent/）**不是同一条代码路径**。
  因此本脚本测出的"抽取失败"比例反映的是本地评测路径的问题，
  不能直接等同于比赛端的丢分；但"判分口径落差""答案未定型"两类结论
  与路径无关，对比赛端同样成立。
  2026-08-28 实测：严格 31.1% vs 宽松 LLM 判分 46.7%（同一批作答，差 15.6pp）。

用法：
    python tools/offline_error_analysis.py
    python tools/offline_error_analysis.py --show 10   # 打印前 N 条判错明细
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from run_eval import answers_match, _classify_error, _norm_candidate  # noqa: E402

REPORT_GLOB = os.path.join(_ROOT, "测试结果", "原始输出和推理过程", "report_*.json")


def load_history() -> list[dict]:
    """加载全部历史 report，按 problem_id 去重（保留最后一次）。"""
    seen: dict[str, dict] = {}
    for f in sorted(glob.glob(REPORT_GLOB)):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] 跳过 {os.path.basename(f)}: {e}", file=sys.stderr)
            continue
        for r in data.get("results", []):
            pid = r.get("problem_id")
            if not pid:
                continue
            seen[str(pid)] = r  # 后出现的覆盖先出现的
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="离线错误分析（零 API 成本）")
    ap.add_argument("--show", type=int, default=0, help="打印前 N 条判错明细")
    args = ap.parse_args()

    rows = load_history()
    if not rows:
        print("[error] 未加载到历史结果", file=sys.stderr)
        return 1

    total = len(rows)
    correct = 0
    dist: dict[str, int] = {}
    by_domain: dict[str, list[int]] = {}
    wrong_samples: list[dict] = []
    # 与历史报告自带的 LLM 判分对照（看宽松判分灌了多少水）
    llm_judge_correct = 0
    deterministic_hits = 0

    for r in rows:
        pred = (r.get("intern_answer") or "").strip()
        gold = (r.get("reference_answer") or "").strip()
        domain = r.get("domain") or "unknown"
        ok = bool(pred) and bool(gold) and answers_match(pred, gold)
        if r.get("is_correct"):
            llm_judge_correct += 1
        if r.get("reference_matched"):
            deterministic_hits += 1

        slot = by_domain.setdefault(domain, [0, 0])
        slot[0] += 1
        if ok:
            correct += 1
            slot[1] += 1
        else:
            k = _classify_error(pred, gold)
            dist[k] = dist.get(k, 0) + 1
            wrong_samples.append({
                "id": r.get("problem_id"),
                "domain": domain,
                "cls": k,
                "pred": pred[:90],
                "gold": gold[:90],
            })

    wrong = total - correct
    print(f"历史样本 {total} 条（按 problem_id 去重）")
    print(f"  严格判分器（run_eval.answers_match）: {correct}/{total} = {correct/total:.1%}")
    print(f"  历史 LLM 判分（DeepSeek 宽松）      : {llm_judge_correct}/{total} = {llm_judge_correct/total:.1%}")
    print(f"  确定性等价兜底命中次数              : {deterministic_hits}")
    print()
    print("错误分布（严格口径，共 %d 条判错）:" % wrong)
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {k:20s} {v:3d}  {v/wrong:6.1%}（占判错）  {v/total:6.1%}（占全卷）")
    print()
    print("分领域正确率:")
    for d, (t, c) in sorted(by_domain.items(), key=lambda kv: -kv[1][0]):
        print(f"  {d:20s} {c}/{t} = {c/t:.0%}")

    cheap = dist.get("empty_output", 0) + dist.get("format_unresolved", 0)
    print()
    print("=" * 60)
    print(f"非推理类错误（可低成本修复）: {cheap}/{wrong} = {cheap/wrong:.0%}" if wrong else "无判错样本")
    if wrong:
        if cheap / wrong >= 0.25:
            print("→ 决策：先做答案定型（Phase 1-A），0 风险提分")
        elif dist.get("value_wrong", 0) / wrong >= 0.55:
            print("→ 决策：主攻答案题推理深度（多候选/投票/revise）")
        else:
            print("→ 决策：投 deep 通道扩容")

    if args.show:
        print()
        print("判错明细（前 %d 条）:" % args.show)
        for s in wrong_samples[:args.show]:
            print(f"  [{s['cls']}] {s['domain']}")
            print(f"      pred: {s['pred']}")
            print(f"      gold: {s['gold']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
