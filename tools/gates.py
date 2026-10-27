# -*- coding: utf-8 -*-
"""四道门的人用入口 —— 把候选指标喂进去，看每一道为什么过/不过。

为什么单独有个 CLI
==================
`contracts/selection.py` 只做判定（纯函数，供闭环调用）。但人也要能问：
「这个候选到底卡在哪一道？」—— 尤其是 δ 还没标定的时候，
要能一眼看到"全部候选都在第一道被拒，原因是没标定"，而不是等跑完评测才发现。

用法
====
    # 看一眼标定状态（没有就提示怎么建模板）
    python tools/gates.py show

    # 建一份**未标定**模板（source=unmeasured ⇒ 四道门仍然全拒，这是预期）
    python tools/gates.py init

    # 判定：候选可以是文件，也可以直接在命令行给
    python tools/gates.py decide --cands cands.json
    python tools/gates.py decide --cand c1:5.0:-20      # 简写 id:ΔSpp:ΔC%
    python tools/gates.py decide --cands cands.json --allow-borrowed
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from contracts.selection import (  # noqa: E402
    CAL_SCHEMA, SelectionError, calibration_usable, decide, load_calibration,
    validate_calibration,
)

CAL_PATH = os.path.join(_ROOT, "results", "_calibration", "gates.json")

# 模板里的 β/δ 是 RRSI coding 域的**参考值**，明确标 unmeasured ⇒ 不会被当成本项目标定。
_TEMPLATE = {
    "schema": CAL_SCHEMA,
    "s_star": None,
    "delta_pp": None,
    "beta0_pct": 10.0,
    "beta1_pct_per_pp": 44.5,
    "w_s": 0.0,
    "w_c": 1.0,
    "w_n": 0.0,
    "source": "unmeasured",
    "note": ("s_star / delta_pp 必须来自本项目基线的 k 次重复评测（δ = z×sd(null)，z=2）；"
             "beta/w 若照抄 RRSI coding 域只能当参考，抄完仍标 source=rrsi-borrowed。"),
}


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_show(args) -> int:
    path = args.cal or CAL_PATH
    print("标定文件：%s" % path)
    if not os.path.isfile(path):
        print("  （不存在）先跑：python tools/gates.py init")
        return 1
    try:
        cal = load_calibration(path)
    except SelectionError as e:
        print("  ❌ %s" % e)
        return 1
    for k in ("source", "s_star", "delta_pp", "beta0_pct", "beta1_pct_per_pp",
              "w_s", "w_c", "w_n", "measured_at", "n_repeats"):
        if k in cal:
            print("  %-18s %r" % (k, cal[k]))
    ok, why = calibration_usable(cal, require_measured=not args.allow_borrowed)
    print("  可用：%s%s" % ("是" if ok else "否", "" if ok else "（%s）" % why))
    return 0


def cmd_init(args) -> int:
    path = args.cal or CAL_PATH
    if os.path.exists(path) and not args.force:
        print("已存在，不覆盖：%s（要重写加 --force）" % path)
        return 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(_TEMPLATE, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("已写模板：%s" % path)
    print("⚠ source=unmeasured、s_star/delta_pp 为空 ⇒ 四道门会**拒绝所有候选**（这是刻意的）。")
    return 0


def _parse_cand(text: str) -> dict:
    """简写 `id:ΔSpp:ΔC%[:novelty]`。"""
    parts = text.split(":")
    if len(parts) < 3:
        raise ValueError("简写格式应为主 id:ΔSpp:ΔC%%[:novelty]，实际 %r" % text)
    c = {"id": parts[0], "delta_s_pp": float(parts[1]), "delta_c_pct": float(parts[2])}
    if len(parts) > 3 and parts[3] != "":
        c["novelty"] = float(parts[3])
    return c


def cmd_decide(args) -> int:
    cal_path = args.cal or CAL_PATH
    if not os.path.isfile(cal_path):
        print("❌ 没有标定文件 %s ⇒ 无法判定。先跑 `python tools/gates.py init`。" % cal_path)
        return 1
    try:
        cal = load_calibration(cal_path)
    except SelectionError as e:
        print("❌ 标定文件不可用：%s" % e)
        return 1

    cands = []
    if args.cands:
        doc = _load_json(args.cands)
        cands.extend(doc.get("candidates") or doc.get("cands") or [])
    for text in args.cand or []:
        cands.append(_parse_cand(text))
    if not cands:
        print("没有候选：给 --cands <file> 或 --cand id:ΔSpp:ΔC%")
        return 2

    out = decide(cands, cal, require_measured=not args.allow_borrowed)
    print("标定：source=%r  δ=%r pp  S*=%r ｜ 可用=%s%s"
          % (out["calibration"].get("source"), out["calibration"].get("delta_pp"),
             out["calibration"].get("s_star"), out["usable"],
             "" if out["usable"] else "（%s）" % out["reason"]))
    if not out["rows"]:
        print("（没有判定行）")
    for r in out["rows"]:
        print("  %-6s %-9s %s  %s" % (r["id"], r["gate"],
                                      "✅" if r["passed"] else "❌", r["reason"]))
    print("选中：%s" % (out["selected"] or "（无）"))
    if out["ranking"]:
        print("排序：%s" % " > ".join(out["ranking"]))
    for n in out.get("notes") or []:
        print("备注：%s" % n)
    return 0 if out["selected"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L4 四道门（floor → cost → guard → argmax）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="看标定状态")
    s.add_argument("--cal", default="")
    s.add_argument("--allow-borrowed", action="store_true")
    s.set_defaults(func=cmd_show)

    i = sub.add_parser("init", help="写一份未标定模板（不会让候选通过）")
    i.add_argument("--cal", default="")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)

    d = sub.add_parser("decide", help="跑四道门")
    d.add_argument("--cands", default="", help="候选文件（JSON）")
    d.add_argument("--cand", action="append", help="简写 id:ΔSpp:ΔC%%[:novelty]，可多次给")
    d.add_argument("--cal", default="")
    d.add_argument("--allow-borrowed", action="store_true",
                   help="允许 source≠measured 的借用参数（判定里会记明）")
    d.set_defaults(func=cmd_decide)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
