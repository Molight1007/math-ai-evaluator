# -*- coding: utf-8 -*-
"""E44 · 把 prover 回复送服务器 Lean 4.31 严格编译并分层统计

复用 E43 的 `compile_check_strict.py`（唯一权威严格判据，不重造）：
  - 兼容 `error: ` 与 `error(lean.unknownIdentifier): ` 两种格式
  - 判据顺序 ERROR > UNSOLVED > CLOSED，sorry 一律不算闭合

额外产出：错误类型分布，专门标出**版本漂移候选**
（unknown constant / unknown identifier / unknown namespace / unknown tactic），
因为 Goedel pin 在 Lean 4.9 + Mathlib d1d1e4b，本机是 4.31 + fabf563a。

用法：
  python verify_proofs.py --replies replies.json --out results.json
  python verify_proofs.py --units mock_units.json --out mock_results.json
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
E43 = os.path.join(HERE, "..", "步级合法率体检E43_20261108")
sys.path.insert(0, E43)
from compile_check_strict import collect_diags, classify_compile  # noqa: E402

from prover_gate import build_verify_unit  # noqa: E402

SSH = ["ssh", "-i", "C:/Users/TiAmo/.ssh/fork_demo_deploy",
       "ubuntu@211.159.188.206"]
SRV_DIR = "~/mathpilot/probe_e44_20261108"
DRIFT_RE = re.compile(
    r"unknown (?:constant|identifier|namespace|tactic|module|prefix)", re.I)


def units_from_replies(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for r in d["rows"]:
        name = r["name"] if d.get("n", 1) == 1 else "%s_s%s" % (r["name"], r["sample"])
        u = build_verify_unit(r["sig"], r.get("reply", ""), name)
        u.update(tag=r.get("tag"), qid=r.get("qid"),
                 call_status=r.get("status"))
        out.append(u)
    return out


def compile_units(units, srv_tag="run"):
    """把每条 OK 单元写成单文件，scp 到服务器串行编译，取回日志。"""
    lean_dir, out_dir = os.path.join(HERE, "lean"), os.path.join(HERE, "out")
    os.makedirs(lean_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    todo = [u for u in units if u["precheck"] == "OK"]
    for u in todo:
        with open(os.path.join(lean_dir, u["name"] + ".lean"),
                  "w", encoding="utf-8", newline="\n") as f:
            f.write(u["code"])
    if not todo:
        return {}

    subprocess.run(SSH + [
        "mkdir -p %s/lean %s/out && rm -f %s/lean/*.lean %s/out/*.log %s/out/RC.txt"
        % (SRV_DIR, SRV_DIR, SRV_DIR, SRV_DIR, SRV_DIR)], check=True)
    files = [os.path.join(lean_dir, u["name"] + ".lean") for u in todo]
    subprocess.run(["scp", "-q"] + SSH[1:3] + files +
                   ["ubuntu@211.159.188.206:%s/lean/" % SRV_DIR], check=True)
    sh = (
        "cd ~/mathpilot && source deploy/lean-env.sh && "
        "cd %s && rm -f out/RC.txt && "
        "for f in lean/*.lean; do b=$(basename $f .lean); "
        "timeout 90 lean -DmaxErrors=10000 $f > out/$b.log 2>&1; "
        "echo \"$b $?\" >> out/RC.txt; done; cat out/RC.txt" % SRV_DIR)
    p = subprocess.run(SSH + [sh], capture_output=True, text=True)
    rc = {}
    for ln in p.stdout.splitlines():
        m = re.match(r"^(\S+)\s+(\d+)$", ln.strip())
        if m:
            rc[m.group(1)] = int(m.group(2))
    subprocess.run(["scp", "-q"] + SSH[1:3] +
                   ["ubuntu@211.159.188.206:%s/out/*.log" % SRV_DIR,
                    out_dir.replace("\\", "/") + "/"],
                   check=False)
    res = {}
    for u in todo:
        n = u["name"]
        log = os.path.join(out_dir, n + ".log")
        raw = ""
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        timed_out = rc.get(n) == 124
        v = classify_compile(rc.get(n, 1), raw, timed_out=timed_out)
        hard, unsolved, sorry = collect_diags(raw)
        res[n] = dict(v, hard=hard[:5], n_hard=len(hard),
                      n_unsolved=len(unsolved), has_sorry=sorry,
                      drift=any(DRIFT_RE.search(x) for x in hard))
    return res


def report(units, compiled, out_path):
    rows = []
    for u in units:
        c = compiled.get(u["name"], {})
        rows.append(dict(u, status=c.get("status", u["precheck"]),
                         brief=c.get("brief", ""),
                         n_hard=c.get("n_hard", 0),
                         hard=c.get("hard", []),
                         drift=c.get("drift", False)))
    cnt = collections.Counter(r["status"] for r in rows)
    types = collections.Counter()
    for r in rows:
        for h in r["hard"][:1]:
            types[re.sub(r"`[^`]*`", "`X`", h)[:70]] += 1
    summary = {
        "n_units": len(rows),
        "status": dict(cnt),
        "closed": cnt.get("CLOSED", 0),
        "drift_candidates": sum(1 for r in rows if r["drift"]),
        "precheck": dict(collections.Counter(r["precheck"] for r in rows)),
        "first_error_types": types.most_common(12),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f,
                  ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replies", default="")
    ap.add_argument("--units", default="")
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    args = ap.parse_args()
    if args.replies:
        units = units_from_replies(args.replies)
    elif args.units:
        with open(args.units, encoding="utf-8") as f:
            units = json.load(f)
    else:
        ap.error("需要 --replies 或 --units")
    with open(os.path.join(HERE, "units.json"), "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    compiled = compile_units(units)
    report(units, compiled, args.out)


if __name__ == "__main__":
    main()
