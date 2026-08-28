# -*- coding: utf-8 -*-
"""Stage 1（Blueprint DAG 生成）专项验收脚本。

用途：隔离验证 BlueprintPlanner 的 LLM 调用是否稳定产出可解析的 DAG JSON，
不牵涉 Stage 2 翻译与 Stage 3 Lean 编译——因此比 tools/leap_eval.py 便宜得多
（每题最多 3 次 LLM 调用，无编译、无 Mathlib 依赖）。

背景（2026-08-28 修复）：
    blueprint_planner 的 LLM 调用原先缺少 assistant prefill 种子，
    Intern 系列会先输出长思维块吃满 token 预算，JSON 被腰斩
    → 表现为「Blueprint: JSON 解析失败」重试 3 次全败（eval_A 0/3 的根因）。

用法：
    python tools/validate_blueprint.py --limit 3
    python tools/validate_blueprint.py --problems PB-Basic-001,PB-Basic-002
    python tools/validate_blueprint.py --limit 3 --backend deepseek

验收标准：DAG 生成成功率 ≥ 2/3（计划 §6 D2'）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agent.base import TaskContext, Budget  # noqa: E402
from agent.blueprint_planner import BlueprintPlannerAgent  # noqa: E402
from user_agent import AgentConfig  # noqa: E402
from tools.leap_eval import load_bench, make_client  # noqa: E402


def make_ctx(problem: str) -> TaskContext:
    """构造最小可用的 TaskContext（TaskContext 不接收 config）。"""
    ctx = TaskContext(problem=problem, metadata={}, domain="")
    ctx.budget = Budget(max_calls=20)
    return ctx


def main() -> int:
    ap = argparse.ArgumentParser(description="Blueprint Stage 1 专项验收")
    ap.add_argument("--backend", default="intern", choices=["intern", "deepseek"])
    ap.add_argument("--model", default="", help="覆盖模型名")
    ap.add_argument("--problems", default="", help="逗号分隔 Problem ID")
    ap.add_argument("--limit", type=int, default=3, help="最多跑 N 题")
    ap.add_argument("--bench", default="", help="基准 CSV 路径")
    ap.add_argument("--out", default="eval_out", help="输出目录")
    args = ap.parse_args()

    client = make_client(args.backend, args.model)
    print(f"[backend] {args.backend} model={client.model}")

    items = load_bench(args.bench)
    if args.problems:
        wanted = {p.strip() for p in args.problems.split(",") if p.strip()}
        items = [it for it in items if it["id"] in wanted]
    else:
        items = items[:max(0, args.limit)]
    if not items:
        print("[error] 没有可跑的题目", file=sys.stderr)
        return 1
    print(f"[select] {len(items)} 题: {[it['id'] for it in items]}")

    cfg = AgentConfig(use_blueprint_dag=True, use_leansearch=False)
    planner = BlueprintPlannerAgent(client, cfg)

    results = []
    for idx, item in enumerate(items, 1):
        print(f"\n=== [{idx}/{len(items)}] {item['id']} ===", flush=True)
        ctx = make_ctx(item["problem"])
        t0 = time.time()
        try:
            dag = planner.generate_blueprint(ctx)
        except Exception as e:  # noqa: BLE001
            dag = None
            print(f"  异常: {e}")
        dt = time.time() - t0
        ok = dag is not None
        n_nodes = len(dag.nodes) if ok else 0
        n_leaves = sum(1 for n in dag.nodes.values() if not n.children) if ok else 0
        print(f"  DAG={'成功' if ok else '失败'}  节点={n_nodes} 叶子={n_leaves} "
              f"耗时={dt:.1f}s")
        results.append({
            "id": item["id"], "ok": ok, "nodes": n_nodes,
            "leaves": n_leaves, "elapsed_sec": round(dt, 2),
            "level": item.get("level", ""), "category": item.get("category", ""),
        })

    total = len(results)
    succ = sum(1 for r in results if r["ok"])
    rate = succ / total if total else 0.0
    print("\n========== 汇总 ==========")
    print(f"Blueprint DAG 生成成功: {succ}/{total} = {rate:.0%}")
    avg_t = sum(r["elapsed_sec"] for r in results) / max(total, 1)
    avg_nodes = sum(r["nodes"] for r in results) / max(succ, 1)
    print(f"平均耗时 {avg_t:.1f}s/题，平均节点数 {avg_nodes:.1f}")
    print(f"判定: {'通过' if rate >= 2 / 3 else '未通过'}（验收线 ≥2/3）")

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "blueprint_validate.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"backend": args.backend, "model": client.model,
                   "success_rate": round(rate, 4), "results": results},
                  fh, ensure_ascii=False, indent=2)
    print(f"结果已写入 {out_path}")
    return 0 if rate >= 2 / 3 else 2


if __name__ == "__main__":
    raise SystemExit(main())
