# -*- coding: utf-8 -*-
"""按依赖清单打包 Mathlib olean，供比赛环境离线使用（计划 §9.3）。

背景：deploy 曾被打到 1.28GB，根因是**按目录通配符拷贝** olean——
把 CategoryTheory / MeasureTheory 等整个目录都带上了。真实依赖闭包
（tools/measure_mathlib_closure.py 实测）只有 **337 个文件 / 0.11GB**。

本脚本严格**按文件清单逐个拷贝**，并在打包后跑编译探针自验。

用法：
    python tools/package_mathlib.py --out deploy/mathlib-olean
    python tools/package_mathlib.py --out deploy/mathlib-olean --verify

⚠️ 平台注意：本地 .lake/build 是 **Windows 下构建**的，而比赛环境是 Linux。
   Lean 4 的 olean 是序列化格式，理论上跨平台可移植（Mathlib 为纯 Lean，
   不含 native 实现），但**必须在真实 Linux 评测环境跑一次 --verify 才能确认**。
   若验证失败，退路是在评测环境本地构建（耗时数小时），或走计划方案 C。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_PROJECT = r"D:/mathlib4-last_bump_for_v4.31.0"
DEF_OUT = os.path.join(_ROOT, "deploy", "mathlib-olean")

PROBE_SOURCE = """import Mathlib.Tactic

example : (1:ℕ) + 1 = 2 := by norm_num
example (x : ℚ) : x + x = 2*x := by ring
example (x y : ℚ) (h : x < y) : x + 1 < y + 1 := by linarith
example (x : ℚ) (h : x^2 ≤ 4) (h2 : x ≥ 0) : x ≤ 2 := by nlinarith
example (x : ℚ) (h : x > 0) : x^2 > 0 := by positivity
example (n : ℕ) : n + 3 ≥ 3 := by omega
"""


def find_lake() -> str:
    elan = os.path.expanduser(r"~/.elan/bin/lake.exe")
    if os.path.isfile(elan):
        return elan
    from shutil import which
    for c in ("lake", "lake.exe"):
        p = which(c)
        if p:
            return p
    return ""


def get_deps(project: str, entry: str = "Mathlib/Tactic") -> list[str]:
    """取入口模块的传递依赖 olean 路径（一次只能传一个文件）。"""
    lake = find_lake()
    if not lake:
        print("[error] 未找到 lake", file=sys.stderr)
        return []
    path = entry if entry.endswith(".lean") else entry + ".lean"
    proc = subprocess.run([lake, "env", "lean", "--deps", path],
                          cwd=project, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"[error] --deps 失败: {(proc.stderr or '')[:400]}", file=sys.stderr)
        return []
    return sorted({os.path.normpath(x.strip())
                   for x in proc.stdout.splitlines() if x.strip()})


def package(deps: list[str], project: str, out_dir: str) -> tuple[int, int]:
    """按文件清单拷贝，保持 lib/lean 下的相对结构。

    返回 (拷贝文件数, 总字节)。
    """
    build_lib = os.path.normpath(os.path.join(project, ".lake", "build", "lib"))
    n = total = 0
    for src in deps:
        if not os.path.exists(src):
            continue
        if not os.path.normpath(src).startswith(build_lib):
            continue    # 工具链自带的（Init/Std）随 Lean 分发，不重复打包
        rel = os.path.relpath(src, build_lib)
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
        total += os.path.getsize(src)
    return n, total


def verify(out_dir: str, project: str) -> bool:
    """用打包产物（而非本地 build 库）编译探针，验证闭包完整可用。"""
    lake = find_lake()
    if not lake:
        print("[warn] 无 lake，跳过验证", file=sys.stderr)
        return False
    tmpdir = tempfile.mkdtemp(prefix="leanprobe_")
    path = os.path.join(tmpdir, "t.lean")
    # Lean 不认 Git Bash 的 /tmp 路径，必须用 Windows 绝对路径
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(PROBE_SOURCE)
    env = dict(os.environ)
    env["LEAN_PATH"] = out_dir + os.pathsep + env.get("LEAN_PATH", "")
    proc = subprocess.run([lake, "env", "lean", path], cwd=project,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    ok = proc.returncode == 0
    print(f"  编译探针: {'通过' if ok else '失败'}")
    if not ok:
        print("  " + (proc.stdout or "")[:500])
        print("  " + (proc.stderr or "")[:500])
    shutil.rmtree(tmpdir, ignore_errors=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="按依赖清单打包 Mathlib olean")
    ap.add_argument("--project", default=DEF_PROJECT)
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--entry", default="Mathlib/Tactic")
    ap.add_argument("--no-verify", action="store_true", help="跳过编译探针")
    args = ap.parse_args()

    deps = get_deps(args.project, args.entry)
    if not deps:
        return 1
    print(f"依赖 olean {len(deps)} 个")

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out, exist_ok=True)

    n, total = package(deps, args.project, args.out)
    print(f"打包 {n} 个文件，{total / 1e6:.1f} MB → {args.out}")

    if total > 2.5e9:
        print("[warn] 超过 2.5GB 门禁，不建议带上比赛环境", file=sys.stderr)
    elif total > 1.2e9:
        print("[warn] 超过 1.2GB，按计划应改用最小闭包方案", file=sys.stderr)

    if not args.no_verify:
        print("--- 验证 ---")
        ok = verify(args.out, args.project)
        print("\n⚠️ 验证用的是本地 Windows 构建；比赛环境为 Linux，"
              "olean 理论上跨平台但仍需在评测环境实测一次。"
              if ok else "\n❌ 打包产物不可用，需排查。")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
