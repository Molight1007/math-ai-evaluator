# -*- coding: utf-8 -*-
"""实测：Lean 编译期间进程在 ps 里长什么样，以及 pgrep -x lean 是否命中。

目的：解释 monitor.csv 里 lean_procs 恒 0 与 diag 里 compile_valid=7 的矛盾。
"""
import os
import subprocess
import sys
import time

REPO = "/home/ubuntu/mathpilot"
LEAN = os.path.join(REPO, "deploy", "lean-4.31.0-linux", "bin", "lean")
CLOSURE = os.path.join(REPO, "deploy", "mathlib-olean")

os.chdir(REPO)
os.environ["LEAN_PATH"] = CLOSURE

# 造一个会跑几秒的源：多次 norm_num 让编译时间足够采样
lines = ["import Mathlib.Tactic.NormNum",
         "import Mathlib.Tactic.Ring",
         "import Mathlib.Tactic.Linarith"]
lines += [f"example : (1:{i % 7}) + 1 = 2 := by norm_num" for i in range(300)]
src = "\n".join(lines) + "\n"
with open("/tmp/lt.lean", "w", encoding="utf-8") as fh:
    fh.write(src)

print("lean:", LEAN, os.path.isfile(LEAN))
print("LEAN_PATH:", CLOSURE, os.path.isdir(CLOSURE))

t0 = time.time()
p = subprocess.Popen([LEAN, "/tmp/lt.lean"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
seen = {}
samples = 0
while p.poll() is None:
    samples += 1
    out = subprocess.run(["ps", "-eo", "pid,comm,args"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "lean" in line and "grep" not in line and "_lt.py" not in line:
            parts = line.split(None, 2)
            if len(parts) >= 2:
                key = (parts[1], (parts[2][:60] if len(parts) > 2 else ""))
                seen[key] = seen.get(key, 0) + 1
    time.sleep(0.15)

o, e = p.communicate()
dt = time.time() - t0
print(f"\n编译耗时 {dt:.1f}s   rc={p.returncode}   采样 {samples} 次")
print(f"stderr 前 200 字: {e.decode('utf-8', 'replace')[:200]!r}")
print()
print("采样到的 (comm, args前60字) -> 命中次数:")
for k, v in sorted(seen.items(), key=lambda x: -x[1])[:10]:
    print(f"   {k[0]:<16} {k[1]:<62} x{v}")

for pat in (["pgrep", "-c", "-x", "lean"],
            ["pgrep", "-c", "-x", "lake"],
            ["pgrep", "-c", "-f", "lean-4.31.0-linux/bin/lean"]):
    r = subprocess.run(pat, capture_output=True, text=True)
    print(f"\n{' '.join(pat)} -> stdout={r.stdout.strip()!r} rc={r.returncode}")
