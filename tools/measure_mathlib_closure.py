# -*- coding: utf-8 -*-
"""测量 Mathlib olean 传递闭包体积，供比赛部署方案选型（计划 §9.2）。

背景：deploy/ 曾因按目录通配符拷贝 olean 导致打包 1.28GB，且全量 Mathlib
（5.2GB）根本不可能带上场比赛。本脚本给出**精确依赖闭包**的体积，
把"要不要带、带多少"从拍脑袋变成有数据。

用法：
    python tools/measure_mathlib_closure.py
    python tools/measure_mathlib_closure.py --project D:/mathlib4-last_bump_for_v4.31.0

决策规则（与计划 §9.2 一致）：
    闭包 ≤ 1.2GB   → 方案 A：打包完整 Mathlib.Tactic 闭包
    1.2 ~ 2.5GB    → 方案 B：只带 NormNum/Ring/Linarith/Omega 最小闭包
    > 2.5GB        → 方案 C：放弃比赛端带 Mathlib
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEF_PROJECT = r"D:/mathlib4-last_bump_for_v4.31.0"
# 方案 B 的最小闭包（仅在方案 A 体积超标时才需要）
# 注意：Omega.lean 在本版本源码树里没有顶层文件（omega 经由 Linarith 传递引入）
MINIMAL_TACTICS = ["Mathlib/Tactic/NormNum", "Mathlib/Tactic/Ring",
                   "Mathlib/Tactic/Linarith"]

# 打包验收探针：`import Mathlib.Tactic` 下这些 tactic 必须都能编译通过。
# 覆盖了竞赛数学最常用的机械化手段（数值/多项式/线性/非线性/符号/整数）。
PROBE_SOURCE = """import Mathlib.Tactic

example : (1:ℕ) + 1 = 2 := by norm_num
example (x : ℚ) : x + x = 2*x := by ring
example (x y : ℚ) (h : x < y) : x + 1 < y + 1 := by linarith
example (x : ℚ) (h : x^2 ≤ 4) (h2 : x ≥ 0) : x ≤ 2 := by nlinarith
example (x : ℚ) (h : x > 0) : x^2 > 0 := by positivity
example (n : ℕ) : n + 3 ≥ 3 := by omega
"""


def run_probe(project: str) -> bool:
    """编译探针：验证 `import Mathlib.Tactic` 确实能用到这些 tactic。

    体积数字再好看，若 tactic 实际不可用就毫无意义——这是打包的验收闸门。
    """
    import tempfile
    lake = find_lake()
    if not lake:
        print("[warn] 无 lake，跳过编译探针", file=sys.stderr)
        return False
    tmpdir = tempfile.mkdtemp(prefix="leanprobe_")
    path = os.path.join(tmpdir, "t.lean")
    # Lean 不认 Git Bash 风格的 /tmp 路径，必须用 Windows 绝对路径
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(PROBE_SOURCE)
    print("--- 编译探针（import Mathlib.Tactic）---", flush=True)
    proc = subprocess.run([lake, "env", "lean", path], cwd=project,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    print(f"  norm_num/ring/linarith/nlinarith/positivity/omega → "
          f"{'全部可用' if ok else '编译失败'}")
    if not ok:
        print("  " + (proc.stdout or "")[:600])
        print("  " + (proc.stderr or "")[:600])
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        pass
    return ok


def find_lake() -> str:
    """定位 lake 可执行文件（优先 elan）。"""
    elan = os.path.expanduser(r"~/.elan/bin/lake.exe")
    if os.path.isfile(elan):
        return elan
    for c in ("lake", "lake.exe"):
        from shutil import which
        p = which(c)
        if p:
            return p
    return ""


def get_deps(project: str, modules: list[str]) -> list[str]:
    """用 `lake env lean --deps` 取模块的传递依赖清单。

    两个实测前提（都踩过坑）：
      1. `--deps` 只接受**显式 .lean 文件路径**，传模块名会报
         "permission denied (error code: 13)"（误导性错误，实为找不到文件）
      2. **一次只能传一个文件**，多个会报 "Expected exactly one file name"

    输出是 olean 的**绝对路径**列表，含工具链自带的 Init/Std（这些已随
    Lean 工具链分发，部署时不需要重复打包）。
    """
    lake = find_lake()
    if not lake:
        print("[error] 未找到 lake 可执行文件", file=sys.stderr)
        return []
    seen: set[str] = set()
    for m in modules:
        path = m if m.endswith(".lean") else m + ".lean"
        cmd = [lake, "env", "lean", "--deps", path]
        proc = subprocess.run(cmd, cwd=project, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            print(f"[warn] 失败 rc={proc.returncode}: {' '.join(cmd)}",
                  file=sys.stderr)
            print("  " + (proc.stderr or "")[:300], file=sys.stderr)
            continue
        for ln in proc.stdout.splitlines():
            ln = ln.strip()
            if ln:
                seen.add(os.path.normpath(ln))
    return sorted(seen)


def measure(project: str, deps: list[str]) -> tuple[int, int, int, int]:
    """统计 olean 体积，区分「Mathlib 专属」与「工具链自带」。

    返回 (mathlib_文件数, mathlib_字节, 工具链_文件数, 工具链_字节)。
    只有 Mathlib 专属部分需要额外打包。
    """
    build_lib = os.path.normpath(os.path.join(project, ".lake", "build", "lib"))
    m_n = m_b = t_n = t_b = 0
    for p in deps:
        if not os.path.exists(p):
            continue
        size = os.path.getsize(p)
        if os.path.normpath(p).startswith(build_lib):
            m_n += 1
            m_b += size
        else:
            t_n += 1
            t_b += size
    return m_n, m_b, t_n, t_b


def main() -> int:
    ap = argparse.ArgumentParser(description="测量 Mathlib olean 闭包体积")
    ap.add_argument("--project", default=DEF_PROJECT)
    args = ap.parse_args()

    lib = os.path.join(args.project, ".lake", "build", "lib", "lean")
    if not os.path.isdir(lib):
        print(f"[error] 未找到 olean 库: {lib}", file=sys.stderr)
        return 1

    print(f"工程目录: {args.project}")
    print(f"olean 库: {lib}")
    print()

    results = {}
    for label, mods in (("Mathlib.Tactic 完整闭包", ["Mathlib/Tactic"]),
                        ("三个 tactic 最小闭包", MINIMAL_TACTICS)):
        print(f"--- 计算 {label} ---", flush=True)
        deps = get_deps(args.project, mods)
        if not deps:
            print("  取依赖失败，跳过", file=sys.stderr)
            continue
        m_n, m_b, t_n, t_b = measure(args.project, deps)
        results[label] = m_b
        print(f"  依赖 olean {len(deps)} 个")
        print(f"  Mathlib 专属：{m_n} 个文件，{m_b / 1e9:.2f} GB  ← 这部分才需要打包")
        print(f"  工具链自带：{t_n} 个文件，{t_b / 1e9:.2f} GB  （随 Lean 分发，无需重复打包）")
        print()

    if "Mathlib.Tactic 完整闭包" in results:
        gb = results["Mathlib.Tactic 完整闭包"] / 1e9
        print("=" * 55)
        if gb <= 1.2:
            print(f"决策：方案 A —— Mathlib 专属 {gb:.2f}GB ≤ 1.2GB，打包完整 Tactic 闭包")
        elif gb <= 2.5:
            print(f"决策：方案 B —— {gb:.2f}GB 偏大，只带三个 tactic 最小闭包"
                  f"（{results.get('三个 tactic 最小闭包', 0) / 1e9:.2f}GB）")
        else:
            print(f"决策：方案 C —— {gb:.2f}GB > 2.5GB，放弃比赛端带 Mathlib")
        print()
        probe_ok = run_probe(args.project)
        if probe_ok:
            print("\n✅ 体积与可用性两项均通过，方案可执行。")
        else:
            print("\n⚠️ 编译探针未通过：即使体积合适，打包后也不可用，需排查。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
