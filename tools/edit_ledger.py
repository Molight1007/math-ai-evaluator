# -*- coding: utf-8 -*-
"""编辑账本 —— 一次原子改动 = 一行记录（R13 七字段）。

为什么需要它
============
现有 `results/_research/ledger.jsonl` 回答的是「**这道题为什么错**」（错题归因），
回答不了「**我上次改的那一处到底有没有用**」（编辑记录）。后者才是自动化的燃料：
提案器要读历史才知道哪些改动该重提、哪些单元从没碰过、哪些改了从没涨分。

七字段（对齐《智能体要求》R13）
==============================
    组件 / 假设 / 实际改动 / 指标变化 / 成本变化 / 是否采纳 / 拒绝原因
本 schema 另加 `stage` `dim` `eu_id`（定位到三级）与 `commit` `evidence`（证据链）。

★ 2026-10-25 增补三字段（抄自 RRSI `propose.py::done()` 契约）
============================================================
RRSI 的每个 edit 必填 8 项，其中三项我们原账本没有，恰好是最能防"乱改"的：
    `why_not_lower_lever`  —— 为什么不用更省力的改法（防提示词塌缩 R11）
    `predicted_affected`   —— 事前预测会影响哪些题（事后可核 = 可归因的强实现）
    `retroactive_check`    —— 事前写清"怎么验证它真有效"
默认**可选但会警告**；加 `--strict` 则必填。理由：历史记录没有这三项，
一刀切必填会让老账不可读。`stats` 里报"三字段完整率"作为质量指标。

三条派生判据（对应"哪里有用/哪里没用"）
======================================
    ① 消费率 = 0        —— 由 `tools/prune_scan.py` 提供，提案前直接拒
    ② 零正贡献           —— 窗口内该 EU 的最大 Δ ≤ 0 ⇒ 剪枝候选（R14：关闭不删）
    ③ 从未被改过         —— 账本无记录 ⇒ 探索配额（R11 防塌缩）

★ 2026-10-27 升 v2（三体架构 L5「账本与回灌」）
==============================================
新增两个字段，把「未测量」从数据里摘出去：

    `bundle`   一个候选捆了几个 edit（=1 才是单组件证据）
    `outcome`  ACCEPTED / REJECTED / BASELINE / LOST / **UNMEASURED**

`measured` 由 `delta_metric is not None` **派生**（不单独存，避免两处权威漂移）。
UNMEASURED（critic 拒 / smoke 失败 / 评测无效）**不进已试集、不进收益窗口、
不算接受率分母** —— 原文：*a wall of aborts is a feedback loop, not evidence*。
v1 老记录读出来会被 `normalize()` 自动补齐，不需要改历史文件。

用法
====
    python tools/edit_ledger.py add --stage 2.7_subgoal_main --dim flow \\
        --eu flow.blueprint_multi_gen_rounds --hypothesis "3→2 遍减少锁值" \\
        --diff "3 -> 2" --delta-metric 3.0 --delta-cost 0.12 --accepted

    python tools/edit_ledger.py add ... --reject-reason "低于噪声带 δ"
    python tools/edit_ledger.py list --stage 2.7
    python tools/edit_ledger.py stats

⚠ 写入 `results/_edit_ledger/ledger.jsonl`（追加，不覆盖）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SCHEMA = "edit_ledger/2"
DIMS = ("prompt", "flow", "tool", "memory", "context")
# RRSI 的四个 outcome + 我们的「未测量」。
#   ACCEPTED 过四道门被采纳 ｜ REJECTED 过了评测但没被采纳 ｜ BASELINE 基线参考
#   LOST 被更强的候选取代 ｜ **UNMEASURED 根本没测**（critic 拒 / smoke 失败 / 评测无效）
# ★ 三体架构铁律「未测量不是数据」：UNMEASURED 不进已试集、不进收益窗口、不算接受率分母。
OUTCOMES = ("ACCEPTED", "REJECTED", "BASELINE", "LOST", "UNMEASURED")
_DIR = os.path.join(_ROOT, "results", "_edit_ledger")
PATH = os.path.join(_DIR, "ledger.jsonl")


def load() -> list:
    if not os.path.isfile(PATH):
        return []
    out = []
    for line in io.open(PATH, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append(rec: dict) -> None:
    os.makedirs(_DIR, exist_ok=True)
    with io.open(PATH, "a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def normalize(rec: dict) -> dict:
    """补齐 v2 字段（v1 老记录照样能统计，不靠手改历史）。

    `measured` 由 `delta_metric is not None` **派生**，不单独存真值 ——
    两处都存必然漂移（本项目「同一个值两三处权威」踩过太多次）。
    `bundle` = 这一条记录所属候选**捆了几个 edit**（1 = 单组件证据）。
    """
    r = dict(rec)
    r["measured"] = r.get("delta_metric") is not None
    if not str(r.get("outcome") or "").strip():
        if not r["measured"]:
            r["outcome"] = "UNMEASURED"
        elif r.get("accepted"):
            r["outcome"] = "ACCEPTED"
        else:
            r["outcome"] = "REJECTED"
    try:
        r["bundle"] = max(1, int(r.get("bundle") or 1))
    except (TypeError, ValueError):
        r["bundle"] = 1
    return r


def records() -> list:
    """读 + 归一。统计/剪枝一律走这里，避免各处各自判 `measured`（口径分叉）。"""
    return [normalize(r) for r in load()]


def validate(rec: dict, strict: bool = False) -> tuple:
    """返回 (错误列表, 警告列表)；错误非空 = 拒写，警告只提示。

    `strict=True` 时把"缺三字段"的警告升级为错误（正式流程用）。
    v2 新增两条硬约束（都是「未测量不是数据」的落地）：
      · `outcome` 必须在枚举内；
      · `accepted` 与「未测量」互斥 —— 没测过就不能说它有用。
    """
    errs, warns = [], []
    rec = normalize(rec)
    for k in ("stage", "dim", "eu_id", "hypothesis", "diff"):
        if not str(rec.get(k) or "").strip():
            errs.append("缺少 %s" % k)
    if rec.get("dim") not in DIMS:
        errs.append("dim 必须是 %s 之一" % "/".join(DIMS))
    if str(rec.get("outcome")) not in OUTCOMES:
        errs.append("outcome 必须是 %s 之一（当前 %r）"
                    % ("/".join(OUTCOMES), rec.get("outcome")))
    if rec.get("accepted") and rec.get("delta_metric") is None:
        errs.append("未测指标就标 accepted（违反 R7：报分必须带度量）")
    if rec.get("accepted") and str(rec.get("outcome")) == "UNMEASURED":
        errs.append("outcome=UNMEASURED 却标 accepted（违反「未测量不是数据」）")
    if rec.get("measured") and str(rec.get("outcome")) == "UNMEASURED":
        errs.append("有 Δ 指标却记 UNMEASURED（口径矛盾：改 outcome 或去掉 delta_metric）")
    if not rec.get("accepted") and not str(rec.get("reject_reason") or "").strip() \
            and rec.get("measured"):
        errs.append("未采纳但无 reject_reason（违反 R2：禁静默；未测量条目除外）")
    # RRSI done() 三字段
    missing = [k for k in ("why_not_lower_lever", "predicted_affected", "retroactive_check")
               if not str(rec.get(k) or "").strip()]
    if missing:
        msg = "缺 RRSI 三字段：%s（--strict 下必填）" % ", ".join(missing)
        (errs if strict else warns).append(msg)
    return errs, warns


def cmd_add(args) -> int:
    rec = {
        "schema": SCHEMA,
        "id": "%s-%04d" % (time.strftime("%Y%m%d%H%M%S"), len(load()) + 1),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stage": args.stage, "dim": args.dim, "eu_id": args.eu,
        "hypothesis": args.hypothesis, "diff": args.diff,
        "delta_metric": args.delta_metric, "delta_cost": args.delta_cost,
        "accepted": bool(args.accepted), "reject_reason": args.reject_reason or "",
        "commit": args.commit or "", "evidence": args.evidence or "",
        "why_not_lower_lever": args.why_not_lower_lever or "",
        "predicted_affected": args.predicted_affected or "",
        "retroactive_check": args.retroactive_check or "",
        "bundle": int(args.bundle or 1),
        "outcome": (args.outcome or "").upper(),
    }
    rec = normalize(rec)
    errs, warns = validate(rec, strict=bool(args.strict))
    for w in warns:
        print("[警告] %s" % w, file=sys.stderr)
    if errs:
        print("拒绝写入，缺 %d 项：" % len(errs), file=sys.stderr)
        for e in errs:
            print("  - %s" % e, file=sys.stderr)
        return 2
    append(rec)
    print("已记账：%s  [%s/%s]  outcome=%s  measured=%s  bundle=%d"
          % (rec["id"], rec["stage"], rec["eu_id"], rec["outcome"],
             rec["measured"], rec["bundle"]))
    return 0


def cmd_list(args) -> int:
    rows = records()
    if args.stage:
        rows = [r for r in rows if r.get("stage", "").startswith(args.stage)]
    if args.dim:
        rows = [r for r in rows if r.get("dim") == args.dim]
    if args.unmeasured_only:
        rows = [r for r in rows if not r["measured"]]
    if not rows:
        print("（无记录）")
        return 0
    print("| id | 环节 | 维 | 单元 | Δ指标 | Δ成本 | outcome | bundle |")
    print("|---|---|---|---|---:|---:|:--:|---:|")
    for r in rows[-args.limit:]:
        print("| %s | %s | %s | `%s` | %s | %s | %s | %d |" % (
            r.get("id", ""), r.get("stage", ""), r.get("dim", ""), r.get("eu_id", ""),
            "-" if r.get("delta_metric") is None else r["delta_metric"],
            "-" if r.get("delta_cost") is None else r["delta_cost"],
            r["outcome"], r["bundle"]))
    return 0


def _all_eu_ids() -> set:
    """借 eu_inventory 拿全量 EU（失败则返回空集，不阻塞 stats）。"""
    try:
        sys.path.insert(0, os.path.join(_ROOT, "tools"))
        import eu_inventory as EUI  # noqa: PLC0415
        EUI._load_corpus()
        items = []
        for fn in (EUI.scan_prompts, EUI.scan_flow, EUI.scan_tools, EUI.scan_memory, EUI.scan_context):
            try:
                items.extend(fn())
            except Exception:  # noqa: BLE001
                pass
        return {x["id"] for x in items}
    except Exception:  # noqa: BLE001
        return set()


def cmd_stats(args) -> int:
    rows = records()
    n = len(rows)
    if n == 0:
        print("账本为空。先记第一条：`python tools/edit_ledger.py add --help`")
        return 0
    measured = [r for r in rows if r["measured"]]
    unmeasured = [r for r in rows if not r["measured"]]
    acc = [r for r in measured if r.get("accepted")]
    print("# 编辑账本统计（%d 条：已测 %d ／ 未测量 %d）\n" % (n, len(measured), len(unmeasured)))
    print("| 指标 | 数值 |")
    print("|---|---:|")
    # ★ 接受率分母只算「已测」：未测量条目（critic 拒 / smoke 失败 / 评测无效）
    #   进分母会把接受率稀释成好看的数字，等于用"没测"冒充"测过不行"。
    denom = len(measured)
    print("| 接受率（只算已测） | %d/%d = %s |"
          % (len(acc), denom, ("%.1f%%" % (len(acc) / denom * 100)) if denom else "N/A"))
    print("| 接受率参考区间（S11） | 10%–15% 属正常 |")
    print("| 未测量（不进统计、不进已试集） | %d |" % len(unmeasured))
    rrsi3 = ("why_not_lower_lever", "predicted_affected", "retroactive_check")
    full = sum(1 for r in rows if all(str(r.get(k) or "").strip() for k in rrsi3))
    print("| RRSI 三字段完整 | %d/%d = %.1f%%（缺则无法证明改动可归因） |"
          % (full, n, full / n * 100))
    print()
    from collections import Counter
    print("## 按 outcome 分布\n")
    print("| outcome | 条数 |")
    print("|---|---:|")
    for k, v in Counter(r["outcome"] for r in rows).most_common():
        print("| %s | %d |" % (k, v))
    print()
    print("## 按 bundle 分布（一条候选捆了几个 edit；=1 才是单组件证据）\n")
    print("| bundle | 条数 |")
    print("|---|---:|")
    for k, v in sorted(Counter(r["bundle"] for r in rows).items()):
        print("| %d | %d |" % (k, v))
    print()
    # 分布
    for key, label in (("stage", "环节"), ("dim", "五维")):
        c = Counter(r.get(key) or "(空)" for r in rows)
        print("## 按%s分布\n" % label)
        print("| %s | 条数 |" % label)
        print("|---|---:|")
        for k, v in c.most_common():
            print("| %s | %d |" % (k, v))
        print()
    # 判据②：零正贡献（只看已测）
    zero, seen = [], set()
    for r in measured:
        eu = r.get("eu_id")
        if not eu:
            continue
        d = r.get("delta_metric")
        if d is not None and d <= 0:
            zero.append((eu, d, r.get("id")))
        seen.add(eu)
    print("## 判据② 零正贡献（窗口内 Δ ≤ 0 ⇒ 剪枝候选，R14 关闭不删）\n")
    if zero:
        print("| 单元 | 最大Δ | 记录 |")
        print("|---|---:|---|")
        for eu, d, rid in zero:
            print("| `%s` | %s | %s |" % (eu, d, rid))
    else:
        print("（无）")
    print()
    # 判据③：从未被改过（未测量不算"改过" —— 见三体架构「未测量不是数据」）
    allids = _all_eu_ids()
    if allids:
        untried = sorted(allids - seen)
        print("## 判据③ 从未被改过的单元（探索空间，R11 防塌缩）\n")
        print("共 **%d / %d** 个 EU 从未被改动过（%.1f%%）。前 15 个：\n"
              % (len(untried), len(allids), len(untried) / len(allids) * 100))
        for x in untried[:15]:
            print("- `%s`" % x)
        print("\n> 完整清单：`python tools/eu_inventory.py --json out.json` 后与本账本取差集。")
    else:
        print("## 判据③ 未探索单元\n\n（EU 清单加载失败，跳过）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="编辑账本（R13 七字段）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="追加一次改动")
    a.add_argument("--stage", required=True)
    a.add_argument("--dim", required=True, choices=DIMS)
    a.add_argument("--eu", required=True, help="单元 ID")
    a.add_argument("--hypothesis", required=True, help="一句话：改了什么行为、为何该有效（R15）")
    a.add_argument("--diff", required=True, help="实际改动")
    a.add_argument("--delta-metric", type=float, default=None, help="ΔS（配对差值）")
    a.add_argument("--delta-cost", type=float, default=None, help="ΔC（相对成本变化）")
    a.add_argument("--accepted", action="store_true")
    a.add_argument("--reject-reason", default="")
    a.add_argument("--commit", default="")
    a.add_argument("--evidence", default="")
    a.add_argument("--why-not-lower-lever", default="",
                   help="为什么不用更省力的改法（防提示词塌缩 R11）")
    a.add_argument("--predicted-affected", default="",
                   help="事前预测会影响哪些题（事后可核）")
    a.add_argument("--retroactive-check", default="",
                   help="怎么验证它真有效")
    a.add_argument("--strict", action="store_true",
                   help="三字段必填（正式流程用；历史记录无此三字段）")
    a.add_argument("--bundle", type=int, default=1,
                   help="这条记录所属候选捆了几个 edit（=1 才是单组件证据）")
    a.add_argument("--outcome", default="",
                   choices=[""] + [o.lower() for o in OUTCOMES],
                   help="结果；留空则按 delta_metric / accepted 自动推断")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="列出记录")
    l.add_argument("--stage", default="")
    l.add_argument("--dim", default="")
    l.add_argument("--limit", type=int, default=30)
    l.add_argument("--unmeasured-only", action="store_true",
                   help="只看未测量条目（gate 失败的那批）")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("stats", help="统计（三条判据）")
    s.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
