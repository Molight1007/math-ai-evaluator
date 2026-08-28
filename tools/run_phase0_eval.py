# -*- coding: utf-8 -*-
"""加载 .env 并跑本地评测（D5：45 题回归基线）。

解决的问题：run_eval.py 的 LLMClient 读的是 OPENAI_API_KEY /
OPENAI_BASE_URL / LLM_MODEL，而项目 .env 里存的是 INTERN_* 系列，
直接跑会因为 base_url 为空而连不上（且不报错，表现为全部超时）。

本脚本把 .env 里的书生配置映射为 run_eval 期望的变量后再调用它。

用法：
    python tools/run_phase0_eval.py
    python tools/run_phase0_eval.py --limit 5          # 小样本冒烟
    python tools/run_phase0_eval.py --concurrency 3 --output results/xxx.jsonl
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def load_env(env_path: str | None = None) -> None:
    """读取 .env，并映射成 run_eval / LLMClient 期望的变量名。"""
    path = env_path or os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        print(f"[warn] 未找到 {path}，依赖既有环境变量", file=sys.stderr)
        return
    data = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v:
                data[k] = v
    os.environ.update(data)
    # run_eval.LLMClient 读 OPENAI_*；项目 .env 用 INTERN_*
    #
    # **必须强制覆盖**，不能用「为空才覆盖」：系统环境变量里可能残留
    # 过期的旧 token（曾实测：系统里的 35 字符旧 key 已 401 user token expired，
    # 而 .env 里的 51 字符新 key 有效）。沿用旧值会直接全量 401。
    pairs = [
        ("OPENAI_API_KEY", "INTERN_API_KEY"),
        ("OPENAI_BASE_URL", "INTERN_API_BASE"),
        ("LLM_MODEL", "INTERN_MODEL"),
    ]
    for dst, src in pairs:
        if os.environ.get(src):
            os.environ[dst] = os.environ[src]


def main() -> int:
    ap = argparse.ArgumentParser(description="D5 本地评测基线")
    ap.add_argument("--bank", default="IMO-AnswerBench")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--output", default=os.path.join(_ROOT, "results",
                                                    "phase0_baseline.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（冒烟用）")
    ap.add_argument("--resume", action="store_true", help="断点续跑")
    ap.add_argument("--override", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="覆盖 AgentConfig 任意字段（可重复传）。"
                         "例：--override use_lemma_accumulation=True "
                         "--override verifier_voting_times=3（D6 三把钥匙 A/B 用）")
    args = ap.parse_args()

    load_env()
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL"):
        v = os.environ.get(k)
        print(f"  {k:<18} {'已设置 (%d 字符)' % len(v) if v else '缺失'}")

    # 解析 --override 成 AgentConfig 覆盖（D6 三把钥匙 A/B 用）
    overrides: dict = {}
    for kv in args.override:
        if "=" not in kv:
            print(f"[warn] 忽略无效 override: {kv}", file=sys.stderr)
            continue
        k, _, v = kv.partition("=")
        k = k.strip()
        v = v.strip()
        if v.lower() in ("true", "false"):
            overrides[k] = v.lower() == "true"
        else:
            try:
                overrides[k] = int(v)
            except ValueError:
                try:
                    overrides[k] = float(v)
                except ValueError:
                    overrides[k] = v
    if overrides:
        print(f"  [override] {overrides}")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    test_file = os.path.join(_ROOT, "sample_data", f"{args.bank}.jsonl")
    if not os.path.exists(test_file):
        print(f"[error] 题集不存在: {test_file}\n"
              f"        先跑 python tools/build_sample_bank.py", file=sys.stderr)
        return 1

    if args.limit > 0:
        # 冒烟：截断成小样本
        smoke = test_file.replace(".jsonl", f"_smoke{args.limit}.jsonl")
        with open(test_file, encoding="utf-8") as fh:
            lines = [ln for ln in fh if ln.strip()][:args.limit]
        with open(smoke, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        test_file = smoke
        print(f"  冒烟模式：只跑 {len(lines)} 题")

    from run_eval import EvalEngine

    engine = EvalEngine(concurrency=args.concurrency, resume=args.resume,
                        agent_overrides=overrides or None)
    tests = engine.load_tests(test_file)
    print(f"  加载 {len(tests)} 道题，输出 → {args.output}")
    summary = engine.run(test_file, args.output)

    print("\n========== 汇总 ==========")
    for k in ("total", "scored", "correct", "accuracy", "avg_elapsed_sec"):
        if k in summary:
            print(f"  {k:<18} {summary[k]}")
    if summary.get("per_domain"):
        print("  分领域:")
        for d, s in summary["per_domain"].items():
            print(f"    {d:<22} {s['correct']}/{s['total']} = {s['accuracy']:.0%}")
    if summary.get("error_distribution"):
        ed = summary["error_distribution"]
        print(f"  错误分布（判错 {ed['wrong_total']} 条）:")
        for k, v in sorted(ed["counts"].items(), key=lambda kv: -kv[1]):
            print(f"    {k:<22} {v}  ({ed['ratios'][k]:.0%})")
    if summary.get("recommendation"):
        print(f"\n  决策建议: {summary['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
