# -*- coding: utf-8 -*-
"""LLM 数学认知探针 —— 主入口。

用法示例：
    python run.py --check                    # 只做环境自检（Lean + 密钥），不花钱
    python run.py --mode gold                # 离线自检：用题库自带的正解走一遍判据与指纹
    python run.py --mode dry  --probe A      # 假模型跑通管线（不联网）
    python run.py --probe A B --model deepseek --repeat 3
    python run.py --probe all --no-lean      # 不跑 Lean，只收自然语言结果

产出在 results/<时间戳>_<tag>/：raw.jsonl（全量原文，供人工复核）、
per_item.csv（明细）、summary.json、report.md（人读的报告）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 保证从任意 cwd 运行都能 import 到本项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from analysis import metrics, report as report_mod  # noqa: E402
from judge import fingerprint as fpmod  # noqa: E402
from judge import lean as lean_judge  # noqa: E402
from llm.client import LLMClient  # noqa: E402
from probes import abstraction, structure, trap, transfer  # noqa: E402
from record import Record  # noqa: E402

PROBE_FUNCS = {
    "A": transfer.run,
    "B": trap.run,
    "C": structure.run,
    "D": abstraction.run,
}
PROBE_DESC = {
    "A": "同构迁移（测联想能否发生）",
    "B": "陷阱题（测类比是否用错地方）",
    "C": "结构指认（元认知 + 反向构造）",
    "D": "抽象⇄实例化",
}


# ---------------------------------------------------------------- 自检
def _mask(t: str) -> str:
    """密钥脱敏显示，便于确认"到底用的是哪一个 key"。"""
    return f"{t[:6]}…{t[-4:]}（{len(t)} 位）" if len(t) > 12 else "—"


def do_check() -> int:
    print("=" * 62)
    print("环境自检")
    print("=" * 62)
    ok_lean, msg = lean_judge.available()
    print(f"[{'OK ' if ok_lean else 'FAIL'}] Lean：{msg}")

    config.load_main_env()
    loaded = os.environ.get("_MATHPILOT_ENV_LOADED", "")
    mode = "覆盖同名环境变量" if os.environ.get(
        "MATHPILOT_ENV_NO_OVERRIDE") != "1" else "不覆盖"
    print(f"[INFO] 主项目 .env 已载入：{loaded or '（无）'}")
    print(f"[INFO] 覆盖策略：{mode}"
          "（若 shell 里残留旧 key，必须设为'覆盖'才不会被遮住）")
    print()
    for key, spec in config.MODELS.items():
        token = os.environ.get(spec["api_key_env"], "")
        print(f"[{'OK ' if token else 'WARN'}] {key:<10}"
              f"{spec['model']:<26}{_mask(token) if token else '缺失'}")
    print(f"\n默认模型：{config.DEFAULT_MODEL}")
    print("（--check 不发起任何 API 调用，只确认配置已就位）")
    return 0 if ok_lean else 1


def do_gold() -> int:
    """离线自检：把题库里所有正解 Lean 代码送进判据，验证链路 + 看指纹长啥样。

    这一步不联网、不花钱，但能回答两个关键问题：
      1. 我设计的"标准答案"真的能编译过吗？（不能就是我题出错了）
      2. 指纹抽取能否稳定抓到我期望的结构族？（抓不到迁移指标就无意义）
    """
    from bank.problems import all_gold_lean

    ok_lean, msg = lean_judge.available()
    print(f"Lean：{msg}\n")
    if not ok_lean:
        print("Lean 不可用，无法做 gold 自检。")
        return 1

    print("=" * 78)
    print(f"{'题号':<16}{'编译':<6}{'无sorry':<8}{'耗时':<8}指纹")
    print("=" * 78)
    n_ok = 0
    total = 0
    for name, code in all_gold_lean():
        total += 1
        res = lean_judge.check(code, tag=f"gold_{name}")
        fp = sorted(fpmod.fingerprint(code))
        if res.ok:
            n_ok += 1
        err = (res.errors[0][:60] if res.errors else res.note)
        print(f"{name:<16}{'✓' if res.compiled else '✗':<6}"
              f"{'✓' if not res.sorry else '✗':<8}"
              f"{res.elapsed:<8.1f}{','.join(fp) if fp else '-'}")
        if not res.ok:
            print(f"{'':<16}└─ {err}")
    print("=" * 78)
    print(f"gold 通过 {n_ok}/{total}")
    print("（失败样本已存入 results/lean_debug/ 供排查）")
    return 0 if n_ok == total else 1


# ---------------------------------------------------------------- 主流程
def run_probes(args) -> int:
    probes = list(PROBE_FUNCS) if "all" in args.probe else args.probe

    client = LLMClient(
        model_key=args.model,
        dry_run=(args.mode == "dry"),
        use_cache=not args.no_cache,
        max_tokens=args.max_tokens,
    )

    use_lean = not args.no_lean
    if use_lean:
        ok_lean, msg = lean_judge.available()
        lean_status = msg
        if not ok_lean:
            print(f"[WARN] {msg} → 自动降级为 --no-lean 模式")
            use_lean = False
    else:
        lean_status = "已跳过（--no-lean）"
    print(f"Lean：{lean_status}")
    print(f"模型：{client.model_key} → {client.spec['model']}（mode={args.mode}）")
    print(f"探针：{', '.join(f'{p} {PROBE_DESC[p]}' for p in probes)}\n")

    records: list[Record] = []
    for rep in range(args.repeat):
        if args.repeat > 1:
            print(f"\n===== 第 {rep + 1}/{args.repeat} 轮 =====")
        for p in probes:
            print(f"--- 探针 {p}：{PROBE_DESC[p]} ---")
            t0 = time.time()
            try:
                recs = PROBE_FUNCS[p](client, repeat=rep, use_lean=use_lean)
            except KeyboardInterrupt:
                print("\n[中断] 用户终止，已跑部分结果仍会保存。")
                break
            for r in recs:
                flag = "✓" if (r.lean_ok or not use_lean) else "·"
                note = r.error or (r.lean_error if use_lean else "")
                print(f"  {flag} {r.item_id:<6}{r.variant:<20}"
                      f"{r.elapsed:>6.1f}s  {(note or '')[:60]}")
            records.extend(recs)
            print(f"  小计 {len(recs)} 条，{time.time() - t0:.1f}s")

    if not records:
        print("\n没有产生任何记录。")
        return 1

    summary = metrics.summarize_all(records)
    meta = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": client.model_key,
        "model_label": client.spec["model"],
        "mode": args.mode,
        "repeat": args.repeat,
        "lean_status": lean_status,
    }
    outdir = report_mod.new_outdir(args.tag or args.model)
    paths = report_mod.save_all(outdir, records, summary, meta)

    print("\n" + "=" * 62)
    print("结果汇总")
    print("=" * 62)
    print(f"记录数：{summary['total']}  "
          f"API错误：{summary['errors']}  截断：{summary['truncated']}")
    if use_lean:
        print(f"整体 Lean 验证通过率：{summary['lean_ok_rate_all']}")
    for k in ("A", "B", "C", "D"):
        if k in summary:
            print(f"\n[{k}] {PROBE_DESC[k]}")
            for kk, vv in summary[k]["aggregate"].items():
                print(f"    {kk:<32}{vv}")
    print("\n输出文件：")
    for name, p in paths.items():
        print(f"  {name:<8}{p}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="LLM 数学认知探针：探大模型是否有联想/结构理解能力",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--probe", nargs="+", default=["all"],
                    choices=list(PROBE_FUNCS) + ["all"],
                    help="要跑的探针，默认 all")
    ap.add_argument("--model", default=config.DEFAULT_MODEL,
                    choices=list(config.MODELS), help="模型")
    ap.add_argument("--mode", default="live", choices=["live", "dry", "gold"],
                    help="live=真跑；dry=假模型跑管线；gold=离线自检判据")
    ap.add_argument("--repeat", type=int, default=config.REPEATS,
                    help="每题重复采样轮数（统计随机性）")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="覆盖模型默认 max_tokens")
    ap.add_argument("--no-lean", action="store_true", help="跳过 Lean 判定")
    ap.add_argument("--no-cache", action="store_true", help="禁用结果缓存")
    ap.add_argument("--tag", default="", help="输出目录后缀")
    ap.add_argument("--check", action="store_true", help="只做环境自检")
    args = ap.parse_args()

    if args.check:
        return do_check()
    if args.mode == "gold":
        return do_gold()
    return run_probes(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
