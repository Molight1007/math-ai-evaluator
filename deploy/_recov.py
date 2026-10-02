# -*- coding: utf-8 -*-
"""从"被换行劈开"的旧 CSV 里反推出 lean 相关列，验证第 1 题的 Lean 阶段。

损坏形态：每个采样被写成两行
  行1: ts,epoch,mt,ma,pct,su,st,<lean_n 的前半>
  行2: <lean_n 的后半>,lean_rss,py_n,load1,cpu_pct,jl
⇒ 按对读取即可还原：lean_n = 行1第8列 + 行2第1列；lean_rss = 行2第2列
"""
import os
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    "/home/ubuntu/mathpilot/logs/monitor_cloud112_0920c.csv"

lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")
         if l.strip()]
print(f"文件 {os.path.basename(path)}  原始行数 {len(lines)}")

rows = []
i = 1  # 跳过表头
while i + 1 < len(lines):
    a = lines[i].split(",")
    b = lines[i + 1].split(",")
    if len(a) >= 8 and len(b) >= 6:
        try:
            rows.append({
                "ts": a[0] + " " + a[1],
                "avail": int(a[3]),
                "pct": int(a[4]),
                "lean_n": int(a[7] + b[0]),
                "lean_rss": int(b[1]),
                "py_n": int(b[2]),
                "cpu": float(b[4]),
                "jl": int(b[5]),
            })
        except ValueError:
            pass
    i += 2

print(f"还原出 {len(rows)} 个采样点")
if not rows:
    raise SystemExit(0)

print(f"时间范围 {rows[0]['ts'][:19]} → {rows[-1]['ts'][:19]}")
print()
nz = [r for r in rows if r["lean_n"] > 0]
print(f"★ lean_n > 0 的采样点: {len(nz)} / {len(rows)}")
if nz:
    print(f"   首次出现 {nz[0]['ts']}   lean_n={nz[0]['lean_n']}  lean_rss={nz[0]['lean_rss']}MB")
    print(f"   最后出现 {nz[-1]['ts']}  lean_n={nz[-1]['lean_n']}  lean_rss={nz[-1]['lean_rss']}MB")
    print()
    print("   出现 Lean 的时间段内逐点：")
    for r in nz:
        print(f"     {r['ts'][:19]}  lean_n={r['lean_n']}  rss合计={r['lean_rss']:>5}MB  "
              f"可用内存={r['avail']:>5}MB  占用={r['pct']:>2}%  CPU={r['cpu']:.1f}%")
else:
    print("   ⇒ 这段时间内确实没有 Lean 进程")

print()
print(f"可用内存最低 {min(r['avail'] for r in rows)} MB")
print(f"内存占用峰值 {max(r['pct'] for r in rows)}%")
print(f"CPU 峰值 {max(r['cpu'] for r in rows):.1f}%")
print(f"lean_rss 峰值 {max(r['lean_rss'] for r in rows)} MB")
print()
print("非零 lean 采样点占比 %.1f%%" % (len(nz) / len(rows) * 100))
