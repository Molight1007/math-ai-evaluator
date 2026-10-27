# -*- coding: utf-8 -*-
"""L5 回灌 —— 把账本里的「改过 / 有效 / 无效 / 没测过」算成每个单元的状态，喂回下一轮提案。

为什么"回灌"不直接改 params.json
==============================
`params.json` 是 `tools/params_export.py` 的**生成物**，只能有一个写者；
回灌再往里写，下次 `build` 就会把回灌结果冲掉，而 diff 里会混进"看起来像候选"的字段。
所以回灌落成**独立文件** `results/_edit_ledger/effectiveness.json`：
  · 提案器读它（探索配额 / 剪枝候选）；
  · 谁想看"这个参数历史上改过几次、有没有用"就看它，不动参数层。

三种状态（对应三体架构的「有用 / 没用 / 没试过」）
================================================
| 状态 | 判据 | 用途 |
|---|---|---|
| `effective` | 至少一条 **已测且 ACCEPTED** | 别乱动它；改它要有更强证据 |
| `ineffective` | 有已测记录但**全部未采纳** | 剪枝候选（R14：**默认关闭，不删代码**） |
| `untested` | 只有 UNMEASURED（critic 拒 / smoke 失败 / 评测无效） | 重新排队 —— **不算试过** |
| `untried` | 账本里没有该单元 | 探索配额（R11 防塌缩） |

⚠ A 段只有 205 个「机器可改」单元；B/C 档改了也不会出现在这里（它们不走候选池）。

用法
====
    python tools/backfill.py                     # 只打印
    python tools/backfill.py --write             # 写 effectiveness.json
    python tools/backfill.py --top 30            # 未试清单显示前 30 个
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.edit_ledger as led  # noqa: E402
from contracts.params_io import load as load_params  # noqa: E402

SCHEMA = "effectiveness/1"
OUT = os.path.join(_ROOT, "results", "_edit_ledger", "effectiveness.json")


def _eu_of(key: str) -> str:
    """A 段键 → 账本里的 eu_id 口径（账本用 `flow.<key>`，也接受裸 key）。"""
    return "flow.%s" % key


def _match(rec_eu: str, a_keys: set) -> str:
    """账本 eu_id 可能写成 `flow.x` 或 `x`，统一成裸 key；不属于 A 段则原样返回。"""
    eu = str(rec_eu or "")
    if eu.startswith("flow.") and eu[5:] in a_keys:
        return eu[5:]
    if eu in a_keys:
        return eu
    return eu


def build(a_keys) -> dict:
    """账本 + A 段 → 每单元状态。返回 {schema, counts, units}。"""
    a_keys = set(a_keys)
    units = {k: {"n_measured": 0, "n_unmeasured": 0, "max_delta": None,
                 "outcomes": [], "last_ts": "", "status": "untried"}
             for k in a_keys}

    for r in led.records():
        key = _match(r.get("eu_id"), a_keys)
        u = units.setdefault(key, {"n_measured": 0, "n_unmeasured": 0, "max_delta": None,
                                   "outcomes": [], "last_ts": "", "status": "untried"})
        u["last_ts"] = max(u["last_ts"], str(r.get("ts") or ""))
        u["outcomes"].append(r["outcome"])
        if r["measured"]:
            u["n_measured"] += 1
            d = r.get("delta_metric")
            if d is not None:
                u["max_delta"] = d if u["max_delta"] is None else max(u["max_delta"], d)
            if r.get("accepted"):
                u["status"] = "effective"
        else:
            u["n_unmeasured"] += 1
            if u["status"] == "untried":
                u["status"] = "untested"

    # 已测但全没采纳 ⇒ ineffective（优先级低于 effective）
    for u in units.values():
        if u["status"] == "untested" and u["n_measured"]:
            u["status"] = "effective"      # 理论上不会发生；留着防状态机写错
        if u["status"] != "effective" and u["n_measured"]:
            u["status"] = "ineffective"
        u["outcomes"] = sorted(set(u["outcomes"]))

    counts = {}
    for u in units.values():
        counts[u["status"]] = counts.get(u["status"], 0) + 1
    return {"schema": SCHEMA,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "counts": counts, "units": units}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="账本 → 每单元有效性（回灌）")
    ap.add_argument("--params", default=os.path.join(_ROOT, "params.json"))
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    doc = load_params(args.params)
    a_keys = list(doc.get("a") or {})
    eff = build(a_keys)
    c = eff["counts"]
    print("# L5 回灌：A 段 %d 个单元的状态\n" % len(a_keys))
    print("| 状态 | 数量 | 含义 |")
    print("|---|---:|---|")
    for st, desc in (("effective", "已测且被采纳 ⇒ 有证据在正面起作用"),
                     ("ineffective", "测过但都没被采纳 ⇒ 剪枝候选（关闭不删）"),
                     ("untested", "只有 gate 失败（未测量）⇒ 重新排队，不算试过"),
                     ("untried", "账本无记录 ⇒ 探索配额")):
        print("| %s | %d | %s |" % (st, c.get(st, 0), desc))
    print()

    for st in ("effective", "ineffective", "untested"):
        rows = [(k, u) for k, u in eff["units"].items() if u["status"] == st]
        if not rows:
            continue
        print("## %s（%d）\n" % (st, len(rows)))
        print("| 单元 | 已测 | 未测量 | 最大Δ | outcomes |")
        print("|---|---:|---:|---:|---|")
        for k, u in sorted(rows, key=lambda x: -(x[1]["max_delta"] or -999))[:args.top]:
            print("| `%s` | %d | %d | %s | %s |"
                  % (k, u["n_measured"], u["n_unmeasured"],
                     "-" if u["max_delta"] is None else u["max_delta"],
                     ",".join(u["outcomes"])))
        print()

    untried = [k for k, u in eff["units"].items() if u["status"] == "untried"]
    print("## 未试（探索配额，%d / %d）\n" % (len(untried), len(a_keys)))
    for k in untried[:args.top]:
        print("- `%s`" % k)
    if len(untried) > args.top:
        print("- …（其余 %d 个见文件）" % (len(untried) - args.top))

    if args.write:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(eff, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print("\n已写 %s" % args.out)
        print("⚠ 没有回写 params.json：它是 params_export 的生成物，只能有一个写者。")
    else:
        print("\n（未写文件；加 --write 落盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
