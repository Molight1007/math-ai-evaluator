# -*- coding: utf-8 -*-
"""门 A 的 autoImplicit 洞 —— 全量体检（只统计，不改判据）。

背景：命题级探针（2026-11-07）发现 `example ... : ... D ...` 里 `D` 从未声明，
Lean 的 `autoImplicit`（默认开）把它绑成全称量化隐式变量 ⇒ rc=0 ⇒ 判 STATABLE，
但它陈述的东西已经不是原命题。门 A 的 `classify_stated` 只吃 (rc, err)，
实际口径由 `_compile_stated` 决定，它**没有**关 autoImplicit ⇒ 同一个洞。

本脚本对 E31 回放里全部 90 条 STATABLE 各编译两次，单变量：
  A 基线：PRELUDE + sig                     （复现原口径，防环境漂移）
  B 处理：PRELUDE + set_option autoImplicit false + sig
只多这一行。统计 A=STATABLE 而 B=ILLEGAL 的条数（翻案）与原因。

不写生产代码、不改 POLICY、不引入开关。
"""
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SRC = "/tmp/sig_gate_res.json"
OUT = "/tmp/autoimplicit_audit.json"
PRELUDE = "import Mathlib.Tactic\n\nset_option maxHeartbeats 400000\n\n"
OPT = "set_option autoImplicit false\n\n"

UNKNOWN = re.compile(r"unknown (identifier|constant|namespace)\s*[`']?([^\s`'\n]*)", re.I)


def run(code, path, timeout=120):
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        p = subprocess.run(["lean", path], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    err = (p.stderr or p.stdout or "").strip()
    return p.returncode, err


def stated_cls(rc, err):
    if rc is None:
        return "TIMEOUT", "编译超时"
    fatal = [ln for ln in (err or "").splitlines()
             if "error" in ln and "warning" not in ln.lower()]
    if rc == 0 and not fatal:
        return "STATABLE", ""
    return "ILLEGAL", (fatal[0].strip()[:400] if fatal else "非零退出无 error 行")


def first_err(err):
    for ln in (err or "").splitlines():
        if "error" in ln and "warning" not in ln.lower():
            return ln.strip()[:300]
    return ""


def main():
    rows = json.load(open(SRC, encoding="utf-8"))
    pool = [r for r in rows if r.get("stated") == "STATABLE"]
    print("总签名 %d 条，STATABLE %d 条 → 全部体检" % (len(rows), len(pool)),
          flush=True)
    tmp = tempfile.mkdtemp(prefix="ai_audit_")
    out, t0 = [], time.time()
    for i, r in enumerate(pool):
        sig = r["sig"].strip()
        rc_a, err_a = run(PRELUDE + sig + "\n", os.path.join(tmp, "a%04d.lean" % i))
        cls_a, why_a = stated_cls(rc_a, err_a)
        rc_b, err_b = run(PRELUDE + OPT + sig + "\n",
                          os.path.join(tmp, "b%04d.lean" % i))
        cls_b, why_b = stated_cls(rc_b, err_b)
        flip = (cls_a == "STATABLE" and cls_b != "STATABLE")
        unk = UNKNOWN.findall(err_b or "") if flip else []
        rec = dict(qid=r.get("qid"), sg_id=r.get("sg_id"), run=r.get("run"),
                   type=r.get("type"), sig=sig,
                   base=cls_a, base_err=first_err(err_a),
                   treat=cls_b, treat_err=first_err(err_b),
                   flip=flip,
                   unknowns=sorted(set(m[1] for m in unk if m[1])),
                   sig_chars=len(sig))
        out.append(rec)
        mark = "FLIP" if flip else ("ok  " if cls_a == cls_b == "STATABLE" else "!!  ")
        print("[%3d/%d] %-4s base=%-8s treat=%-8s %s %s" %
              (i + 1, len(pool), mark, cls_a, cls_b, r.get("qid"),
               ("unk=" + ",".join(rec["unknowns"])) if rec["unknowns"] else ""),
              flush=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n== 汇总（n=%d，同一人群全量，不是抽样）==" % len(out))
    print("  基线 STATABLE      : %d / %d" %
          (sum(1 for x in out if x["base"] == "STATABLE"), len(out)))
    print("  基线口径不可复现   : %d" % sum(1 for x in out if x["base"] != "STATABLE"))
    flips = [x for x in out if x["flip"]]
    print("  加 autoImplicit=false 后翻案 : %d / %d = %.1f%%" %
          (len(flips), len(out), 100.0 * len(flips) / (len(out) or 1)))
    kinds = collections.Counter(
        "未定义符号" if x["unknowns"] else "其它(类型/语法)" for x in flips)
    for k, v in kinds.items():
        print("    %-16s %d" % (k, v))
    names = collections.Counter(n for x in flips for n in x["unknowns"])
    print("  -- 未声明符号频次 --")
    for k, v in names.most_common(20):
        print("     %-24s %d" % (k, v))
    print("\n== 翻案样本原文（强制人工抽验）==")
    for x in flips:
        print("  [%s/%s run=%s] unk=%s" % (x["qid"], x["sg_id"], x["run"],
                                           ",".join(x["unknowns"])))
        print("     SIG: %s" % x["sig"][:260].replace("\n", " "))
        print("     ERR: %s" % x["treat_err"][:200])
    print("\n明细 %s，用时 %.0fs" % (OUT, time.time() - t0))


if __name__ == "__main__":
    main()
