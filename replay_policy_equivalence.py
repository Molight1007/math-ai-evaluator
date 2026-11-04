# -*- coding: utf-8 -*-
"""开关融合的**行为等价性**离线回放台（只读，不改任何生产代码）。

为什么需要它
------------
「全量回归通过数」不是效果量：把测「开关可关」的旧用例删掉就能刷绿，
却会把固化值与生产实际生效值的偏差永远藏起来。本台用服务器真实题次的
`diag.switch_snapshot` 做留出集核对，口径来自 E14 / E25 / E27 三次教训：

  1. **留出集**：按 mtime 排序，前 70% 用于发现分歧，后 30% **不参与任何
     取值决策**，只报一致率。取值修正的依据必须是独立的结构证据
     （生产权威读取点），不是留出集上的拟合。
  2. **分层**：按 10-15 分层分别报，禁止把 0% 与 90% 平均成一个漂亮数字。
  3. **单变量对照**：内置 PRE_FIX（修正前的 2 个值），只翻这 2 个值，
     同时报修正前/后在**同一留出集**上的一致率。
  4. **抽验**：输出逐条人工可读记录；统计数字一律不单独作为结论。
  5. **零无解释差异**：每个真取值差都必须在台账里有 disposition + evidence；
     每个「快照有、策略表无」的历史字段必须证明当前生产代码已无读取点。

声明口径：只写「在 N 题次 / M 字段对上未发现无解释差异」，
**不写**「正确率 100% / 已证明等价」。

用法
----
  本地：python replay_policy_equivalence.py --snapshots <逐题次.jsonl>
  服务器：python replay_policy_equivalence.py --from-server --out report.json
"""
from __future__ import annotations

import argparse
import ast
import collections
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from contracts.policy import POLICY  # noqa: E402

# 单变量对照：本轮复核前的固化值（只翻这 2 个，别的都不动）。
# five_gate_rewrite **不在其中**：它保持 False 是 10-31 已应用的生产决策，
# 不是本轮修正项；历史快照里的 True 属于配置变更前的数据，另行记 disposition。
PRE_FIX = {
    "enable_numeric_lean_verify": False,
    "lemma_domains": "Number theory,数论",
}

# 值归一化：历史快照里混过 str/int/list 三种形态，必须按**语义**比，
# 否则会把类型脏值误报成真取值差（E25 的分母陷阱）。
def _semantic(v):
    if isinstance(v, str):
        s = v.strip()
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return ("seq", tuple(str(x) for x in parsed))
        except (ValueError, SyntaxError):
            pass
        try:
            f = float(s)
            if f == int(f):
                return ("num", int(f))
            return ("num", f)
        except ValueError:
            pass
        return ("str", s)
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (list, tuple)):
        return ("seq", tuple(str(x) for x in v))
    if isinstance(v, (int, float)):
        return ("num", v)
    return ("other", repr(v))


def _classify(hist, policy_val):
    if hist == policy_val:
        return "MATCH"
    a, b = _semantic(hist), _semantic(policy_val)
    if a == b:
        return "TYPE_ONLY"
    # bool / 0-1 数值等价（历史快照偶有 1.0 / True 混写）
    if a[0] == "bool" and b[0] == "num" and int(bool(a[1])) == b[1]:
        return "TYPE_ONLY"
    if b[0] == "bool" and a[0] == "num" and int(bool(b[1])) == a[1]:
        return "TYPE_ONLY"
    return "VALUE_DIFF"


def _load(args):
    rows = []
    if args.from_server:
        for fp in sorted(glob.glob("results/*.jsonl")):
            st = os.stat(fp)
            for i, ln in enumerate(open(fp, encoding="utf-8", errors="ignore"), 1):
                if not ln.strip():
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                snap = ((d.get("diag") or {}).get("switch_snapshot") or {})
                if not isinstance(snap, dict) or not snap:
                    continue
                slim = {k: (v.get("value") if isinstance(v, dict) else v)
                        for k, v in snap.items()}
                rows.append({"file": os.path.basename(fp), "mtime": st.st_mtime,
                             "line": i, "id": d.get("id"), "snapshot": slim})
    else:
        for ln in open(args.snapshots, encoding="utf-8"):
            if ln.strip():
                rows.append(json.loads(ln))
    # 两种输入统一成 {field: 值}：导出文件保留完整条目（value/source/env/default），
    # 比对只认 value，否则会把 dict 误判成真取值差（E25 的分母陷阱）。
    for r in rows:
        r["snapshot"] = {
            k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in r["snapshot"].items()
        }
    rows.sort(key=lambda r: (r["mtime"], r["file"], r.get("line", 0)))
    return rows


def _code_refs(names):
    """用 AST 判断生产代码是否还**真正引用**这些历史字段名。

    只认三种形态：标识符、属性名、以及「整个字符串正好等于字段名」的常量
    （_cfg_get(cfg, "old_switch") 这类读取）。文档字符串与注释里的史料不算
    引用 —— 把注释当残留会制造假红，把假红清掉则是另一种过拟合。
    """
    refs = collections.defaultdict(list)
    roots = [os.path.join(ROOT, d) for d in
             ("agent", "utils", "contracts", "tools", "cli", "deploy")]
    files = [os.path.join(ROOT, f) for f in os.listdir(ROOT) if f.endswith(".py")]
    for d in roots:
        for dp, _dn, fn in os.walk(d):
            if "__pycache__" in dp or dp.endswith("tests") or os.sep + "tests" in dp:
                continue
            files += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
    for fp in files:
        if os.path.basename(fp).startswith("replay_"):
            continue
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        try:
            tree = ast.parse(open(fp, encoding="utf-8", errors="ignore").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            hit, line = None, getattr(node, "lineno", 0)
            if isinstance(node, ast.Name) and node.id in names:
                hit = node.id
            elif isinstance(node, ast.Attribute) and node.attr in names:
                hit = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # docstring 是模块/类/函数的首个 Expr 常量，整段文字不会「正好等于」字段名
                if node.value.strip() in names:
                    hit = node.value.strip()
            if hit:
                refs[hit].append("%s:%d" % (rel, line))
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", default="")
    ap.add_argument("--from-server", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--dev-fraction", type=float, default=0.70)
    args = ap.parse_args()
    if not args.from_server and not args.snapshots:
        ap.error("需要 --snapshots <file> 或 --from-server")

    ledger = json.load(open(os.path.join(ROOT, "contracts", "policy_ledger.json"),
                            encoding="utf-8"))
    val = ledger.get("validation", {})
    disp = val.get("value_dispositions", {})
    retired = set(val.get("historical_retired_fields", []))

    rows = _load(args)
    n = len(rows)
    cut = int(n * args.dev_fraction)
    dev, holdout = rows[:cut], rows[cut:]

    def _scan(policy, subset):
        c = collections.Counter()
        diffs = collections.defaultdict(lambda: {"n": 0, "values": collections.Counter(),
                                                "sample": None})
        extras = collections.Counter()
        for r in subset:
            snap = r["snapshot"]
            for k, pv in policy.items():
                if k not in snap:
                    c["ABSENT_IN_SNAPSHOT"] += 1
                    continue
                kind = _classify(snap[k], pv)
                c[kind] += 1
                if kind == "VALUE_DIFF":
                    d = diffs[k]
                    d["n"] += 1
                    d["values"][repr(snap[k])[:90]] += 1
                    if d["sample"] is None:
                        d["sample"] = r["id"]
            for k in snap:
                if k not in policy:
                    extras[k] += 1
                    c["ABSENT_IN_POLICY"] += 1
        return c, diffs, extras

    fixed = dict(POLICY)
    old = dict(POLICY)
    old.update(PRE_FIX)

    dev_c, dev_d, dev_e = _scan(fixed, dev)
    hold_c, hold_d, hold_e = _scan(fixed, holdout)
    old_hold_c, _od, _oe = _scan(old, holdout)

    # 分层：10-15 之前 / 之后（回放三硬约定之一）
    strata = {"<=10-15": [], ">10-15": []}
    for r in rows:
        day = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%m-%d")
        strata["<=10-15" if day <= "10-15" else ">10-15"].append(r)
    strata_c = {k: _scan(fixed, v)[0] for k, v in strata.items()}

    # 真取值差必须有处置与证据
    all_d = collections.defaultdict(lambda: {"n": 0, "values": collections.Counter(),
                                             "sample": None})
    for src in (dev_d, hold_d):
        for k, d in src.items():
            all_d[k]["n"] += d["n"]
            all_d[k]["values"].update(d["values"])
            all_d[k]["sample"] = all_d[k]["sample"] or d["sample"]
    unexplained = []
    for k, d in all_d.items():
        rec = disp.get(k) or {}
        if not rec.get("disposition") or not rec.get("evidence"):
            unexplained.append(k)

    # 历史字段：要么在已退役清单里且当前生产代码无读取点，要么判红
    all_extra = collections.Counter()
    all_extra.update(dev_e)
    all_extra.update(hold_e)
    refs = _code_refs(set(all_extra))
    extra_unexplained = sorted(
        k for k in all_extra
        if k not in retired or refs.get(k)
    )

    def _rate(c):
        tot = c["MATCH"] + c["TYPE_ONLY"] + c["VALUE_DIFF"]
        return round(c["MATCH"] / tot, 4) if tot else None

    report = {
        "claim": "在 N 题次 / M 字段对上「未发现无解释差异」；不宣称等价或正确率",
        "rows": n,
        "dev_rows": len(dev), "holdout_rows": len(holdout),
        "split": "按 mtime 升序，前 %.0f%% 发现分歧 / 后 %.0f%% 纯留出"
                 % (args.dev_fraction * 100, (1 - args.dev_fraction) * 100),
        "dev": {"counts": dict(dev_c), "match_rate": _rate(dev_c)},
        "holdout": {"counts": dict(hold_c), "match_rate": _rate(hold_c)},
        "holdout_before_fix": {
            "counts": dict(old_hold_c), "match_rate": _rate(old_hold_c),
            "note": "只翻 PRE_FIX 的 2 个值；修正依据是生产权威读取点，不是留出集拟合",
        },
        "strata_10_15": {
            k: {"rows": len(v), "counts": dict(strata_c[k]),
                "match_rate": _rate(strata_c[k])} for k, v in strata.items()
        },
        "value_diffs": {
            k: {"n": d["n"], "historical_values": dict(d["values"]),
                "sample_id": d["sample"],
                "disposition": (disp.get(k) or {}).get("disposition", "MISSING"),
                "evidence": (disp.get(k) or {}).get("evidence", "")}
            for k, d in sorted(all_d.items())
        },
        "absent_in_policy_fields": dict(all_extra),
        "unexplained_value_diffs": sorted(unexplained),
        "unexplained_legacy_fields": extra_unexplained,
        "manual_spot_check": _spot_check(rows, fixed, disp),
    }
    report["verdict"] = "NO_UNEXPLAINED_DIFF" if not unexplained and not extra_unexplained \
        else "UNEXPLAINED_DIFF"

    txt = json.dumps(report, ensure_ascii=False, indent=1)
    print(txt)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
        print("报告 ->", args.out)
    return 0 if report["verdict"] == "NO_UNEXPLAINED_DIFF" else 1


def _spot_check(rows, policy, disp, limit=10):
    """人工抽验样本：逐条可读，不参与自动判定（E27：数字漂亮 ≠ 判据成立）。"""
    out = []
    seen = set()
    for r in rows:
        day = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%m-%d")
        for k, pv in policy.items():
            if k not in r["snapshot"] or k in seen:
                continue
            hv = r["snapshot"][k]
            kind = _classify(hv, pv)
            if kind == "MATCH":
                continue
            seen.add(k)
            out.append({
                "field": k, "id": r["id"], "date": day,
                "historical": repr(hv)[:120], "policy": repr(pv)[:120],
                "kind": kind,
                "disposition": (disp.get(k) or {}).get("disposition", "MISSING"),
                "evidence": (disp.get(k) or {}).get("evidence", ""),
            })
            if len(out) >= limit:
                return out
    return out


if __name__ == "__main__":
    sys.exit(main())
