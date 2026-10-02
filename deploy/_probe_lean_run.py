# -*- coding: utf-8 -*-
"""决定性实验：调用主链路的 _compile_lean()，同时高频采样 ps，
看它到底会不会真的拉起 lean 进程、峰值内存多少。

同时检查 v2 监控 CSV 里有没有 lean 活动。
"""
import glob
import os
import subprocess
import sys
import threading
import time

REPO = "/home/ubuntu/mathpilot"
sys.path.insert(0, REPO)
os.chdir(REPO)
os.environ.setdefault("LEAN_PATH", os.path.join(REPO, "deploy", "mathlib-olean"))

peaks = {}
stop = False


def sampler():
    while not stop:
        try:
            out = subprocess.run(["ps", "-eo", "pid,comm,rss,args"],
                                 capture_output=True, text=True).stdout
        except Exception:  # noqa: BLE001
            continue
        for line in out.splitlines():
            p = line.split(None, 3)
            if len(p) < 3:
                continue
            comm = p[1]
            if comm in ("lean", "lake"):
                try:
                    rss = int(p[2])
                except ValueError:
                    rss = 0
                peaks[comm] = max(peaks.get(comm, 0), rss)
        time.sleep(0.05)


print("=" * 74)
print("A) v2 监控 CSV 里的 lean 活动")
print("=" * 74)
for f in sorted(glob.glob("logs/monitor_cloud*_v2.csv")):
    mx = 0
    nz = 0
    cnt = 0
    for line in open(f, encoding="utf-8", errors="replace").readlines()[1:]:
        c = line.strip().split(",")
        if len(c) < 13:
            continue
        cnt += 1
        try:
            ln = int(c[7])
        except ValueError:
            continue
        if ln > 0:
            nz += 1
            mx = max(mx, ln)
    print(f"  {f}: {cnt} 点，lean_n>0 的 {nz} 个，最大 lean_n={mx}")

print()
print("=" * 74)
print("B) 直接调 _compile_lean() —— 观察是否真的 spawn lean")
print("=" * 74)
from tools.lean_local.lean_bridge import _compile_lean  # noqa: E402

CODE = "import Mathlib.Tactic.NormNum\nimport Mathlib.Tactic.Ring\n" + \
       "\n".join(f"example : (1:{(i % 5) + 1}) + 1 = 2 := by norm_num"
                 for i in range(150))

th = threading.Thread(target=sampler, daemon=True)
th.start()
t0 = time.time()
res = _compile_lean(CODE, REPO, lean_executable=os.path.join(
    REPO, "deploy", "lean-4.31.0-linux", "bin", "lean"), timeout=600)
dt = time.time() - t0
stop = True
time.sleep(0.3)

print(f"  _compile_lean 返回: {str(res)[:200]}")
print(f"  耗时 {dt:.1f}s")
print(f"  ★ 采样到的进程峰值 RSS: {peaks if peaks else '（没抓到 lean/lake！）'}")

print()
print("=" * 74)
print("C) 结论判据")
print("=" * 74)
if peaks:
    for k, v in peaks.items():
        print(f"  ✅ 确实 spawn 了 {k}，峰值 RSS {v / 1024:.0f} MB")
else:
    print("  ❌ 没有抓到 lean/lake —— 说明主链路这一次没真正起 Lean 进程")
