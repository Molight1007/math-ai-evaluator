# -*- coding: utf-8 -*-
"""有界存在性搜索的**离线评估床**（纯函数，不跑 LLM，δ=0）。

用法：

    python replay_bounded_search.py                        # 默认跑 omni8 + official112
    python replay_bounded_search.py --bank 题库/omni8_20261027.jsonl --show 20
    python replay_bounded_search.py --problem "Find an integer n, where 1 <= n <= 50, such that (2^n+2)/n is an integer."
    python replay_bounded_search.py --json out.json

输出四块：
  ① **识别率**：多少题被认成「有界 ∃ 命题」（分母是全部题）；
  ② **判定一致**：命中的取值与 gold 是否一致（不一致要逐条看，可能是 gold 错，
     也可能是识别错 —— 后者必须修）；
  ③ **refuse 分布**：认得出条件但判不了的理由（`unsupported_expr` /
     `range_too_large` / `unevaluated` / `timeout`）—— 这是后续要扩的能力清单；
  ④ **成本**：单题毫秒数。

为什么要有这个床：`bounded_search` 的判据是纯函数，输入题面、输出取值，
改判据前后跑同一批题即可 δ=0 对比（漏认/错认各增加多少条，一眼可见）。
这正是 RRSI 规则 E 要求的「同一假设只测一次」。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.bounded_search import detect, run_search  # noqa: E402

_DEFAULT_BANKS = [
    os.path.join("题库", "omni8_20261027.jsonl"),
    os.path.join("题库", "official112_本地测试题库", "official112_full.jsonl"),
]
_ANS_JUNK = "$ \\{} ,"


def _norm(v) -> str:
    return str(v if v is not None else "").strip().strip(_ANS_JUNK).replace(" ", "")


def _rows(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:  # noqa: BLE001
        return []
    return out


def _problem(row: dict) -> str:
    for k in ("question", "problem", "content", "stem", "text"):
        if row.get(k):
            return str(row[k])
    return ""


def _answer(row: dict) -> str:
    for k in ("answer", "gold", "target", "expected"):
        if row.get(k) not in (None, ""):
            return str(row[k])
    return ""


def run_bank(path: str, show: int = 0, budget_hint: str = "") -> dict:
    rows = _rows(path)
    stat = {"bank": path, "total": len(rows), "detected": 0, "ok": 0,
            "agree": 0, "disagree": [], "refuse": {}, "ms": 0.0, "detail": []}
    if not rows:
        return stat
    t_all = time.perf_counter()
    for row in rows:
        prob = _problem(row)
        if not prob:
            continue
        spec = detect(prob)
        if spec is None:
            continue
        stat["detected"] += 1
        res = run_search(spec)
        if not res.get("ok"):
            reason = str(res.get("reason", "")).split("(")[0]
            stat["refuse"][reason] = stat["refuse"].get(reason, 0) + 1
            continue
        stat["ok"] += 1
        gold = _norm(_answer(row))
        hits = [_norm(h) for h in res["hits"]]
        agree = bool(gold) and gold in hits
        if agree:
            stat["agree"] += 1
        elif gold:
            stat["disagree"].append({"id": row.get("id", budget_hint), "gold": gold,
                                     "hits": res["hits"][:6],
                                     "predicate": res.get("predicate", "")})
        stat["detail"].append({
            "id": row.get("id", ""), "gold": gold, "hits": res["hits"][:6],
            "n_hits": len(res["hits"]), "predicate": res.get("predicate", ""),
            "domain": [res["lo"], res["hi"]], "ms": res.get("elapsed_ms", 0.0),
            "agree": agree,
        })
    stat["ms"] = round((time.perf_counter() - t_all) * 1000.0, 1)
    if show:
        for d in stat["detail"][:show]:
            print("   %-22s gold=%-10s hits=%-22s %s %s"
                  % (d["id"], d["gold"], str(d["hits"]), d["predicate"],
                     "OK" if d["agree"] else "MISMATCH"))
    return stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", action="append", default=[])
    ap.add_argument("--problem", default="")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if args.problem:
        spec = detect(args.problem)
        print("spec =", spec)
        if spec:
            res = run_search(spec)
            print("reason =", res.get("reason"), "| hits =", res["hits"],
                  "| checked =", res["checked"], "| %.2fms" % res["elapsed_ms"])
        return 0

    banks = args.bank or [b for b in _DEFAULT_BANKS if os.path.exists(b)]
    out = []
    for b in banks:
        st = run_bank(b, show=args.show)
        out.append(st)
        print("=" * 78)
        print("[%s] 题数 %d | 识别 %d (%.1f%%) | 判定成功 %d | 与 gold 一致 %d"
              " | 用时 %.1fms"
              % (b, st["total"], st["detected"],
                 100.0 * st["detected"] / max(1, st["total"]), st["ok"],
                 st["agree"], st["ms"]))
        if st["refuse"]:
            print("   refuse 分布:", st["refuse"])
        if st["disagree"]:
            print("   与 gold 不一致 %d 条（需逐条核，可能是 gold 错）:" % len(st["disagree"]))
            for d in st["disagree"][:10]:
                print("     %-22s gold=%-10s hits=%s  ← %s"
                      % (d["id"], d["gold"], d["hits"][:5], d["predicate"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("→", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
