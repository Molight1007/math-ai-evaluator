"""纯 Lean 内置检索探针：对 B 组 18 条目标依次试 simp/omega/norm_num/exact?/apply?
不调 LLM，零配额，只用编译器。用来测「引理检索」这一环补上能解几条。
"""
import json
import os
import subprocess
import time

LEAN = "/home/ubuntu/mathpilot/deploy/lean-4.31.0-linux/bin/lean"
ENV_LEAN_PATH = "/home/ubuntu/mathpilot/deploy/mathlib-olean"
WORK = "/tmp/l2probe/srch"
GOALS = "/tmp/l2probe/l2_goals.json"

# 顺序：便宜的、确定性的先试；exact?/apply? 放最后因为慢
TACTICS = ["omega", "norm_num", "simp", "positivity", "ring",
           "exact?", "apply?"]


def build(sig, tactic):
    body = "import Mathlib.Tactic\n\n" + sig.strip()
    import re
    body = re.sub(r":=\s*by\s+sorry\b", ":= by", body)
    return body + "\n  " + tactic + "\n"


def run_tactic(sig, tactic, tag, timeout=120):
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, "%s.lean" % tag)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(sig, tactic))
    env = dict(os.environ)
    env["LEAN_PATH"] = ENV_LEAN_PATH
    t0 = time.time()
    try:
        r = subprocess.run([LEAN, path], capture_output=True, timeout=timeout, env=env)
        raw = (r.stderr or b"").decode("utf-8", "replace") + \
              (r.stdout or b"").decode("utf-8", "replace")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "TIMEOUT", "sec": round(time.time() - t0, 1)}
    el = round(time.time() - t0, 1)
    has_err = any(": error:" in ln for ln in raw.splitlines() if ln)
    has_sorry = ("declaration uses `sorry`" in raw or
                 "declaration uses 'sorry'" in raw)
    ok = (rc == 0 and not has_err and not has_sorry)
    return {"ok": ok, "why": "OK" if ok else "FAIL", "sec": el}


def main():
    with open(GOALS, encoding="utf-8") as f:
        g = [x for x in json.load(f) if x.get("compile_ok")]
    print("n =", len(g), flush=True)
    rows = []
    for x in g:
        tag = "q%02d" % x["no"]
        got = None
        hits = []
        for t in TACTICS:
            r = run_tactic(x["formal_sig"], t, "%s_%s" % (tag, t.replace("?", "q")),
                           timeout=180 if "?" in t else 60)
            hits.append((t, r["ok"], r["why"], r["sec"]))
            if r["ok"]:
                got = t
                break
        rows.append({"tag": tag, "qid": x.get("qid", ""), "solved_by": got,
                     "tried": hits})
        print("[%s] %s  %s" % (tag, "SOLVED by " + got if got else "no",
                               " ".join("%s=%s(%ss)" % (t, w, s) for t, _, w, s in hits)),
              flush=True)
    out = "/tmp/l2probe/l2_tactic_only.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    n = sum(1 for r in rows if r["solved_by"])
    print("SOLVED %d / %d" % (n, len(rows)))
    print("WROTE", out)


if __name__ == "__main__":
    main()
