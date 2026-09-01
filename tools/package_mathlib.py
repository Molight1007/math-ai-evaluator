# -*- coding: utf-8 -*-
"""按依赖清单打包 Mathlib olean，供比赛环境离线使用（计划 §9.3）。

背景：deploy 曾被打到 1.28GB，根因是**按目录通配符拷贝** olean——
把 CategoryTheory / MeasureTheory 等整个目录都带上了。

2026-09-01 重大修复：**`lean --deps` 的清单不完整**（实测只输出 337 个
模块，而 `import Mathlib.Tactic` 的真实传递依赖是 2932 个模块），导致
闭包编译必挂。根因是 lean 4.31 的 --deps 只列出部分依赖。
改用 **.ilean 导入图缓存（JSON）的 directImports 字段做 BFS**，
收集完整传递闭包（build_lib 内 Mathlib + .lake/packages 下外部包模块）。

另修复：lean 4.31 加载 olean 时要求伴随数据文件（.olean.hash/.ilean/.ir
等），只拷 .olean 会报 "missing data file for module X"。打包时整组拷贝。

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
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_PROJECT = r"D:/mathlib4-last_bump_for_v4.31.0"
DEF_OUT = os.path.join(_ROOT, "deploy", "mathlib-olean")

# 探针覆盖 6 种战术（norm_num/ring/linarith/nlinarith/positivity/omega），
# 与 lean_gate 硬验证实际用到的能力一致。
PROBE_SOURCE = """import Mathlib.Tactic

example : (1:ℕ) + 1 = 2 := by norm_num
example (x : ℚ) : x + x = 2*x := by ring
example (x y : ℚ) (h : x < y) : x + 1 < y + 1 := by linarith
example (x : ℚ) (h : x^2 ≤ 4) (h2 : x ≥ 0) : x ≤ 2 := by nlinarith
example (x : ℚ) (h : x > 0) : x^2 > 0 := by positivity
example (n : ℕ) : n + 3 ≥ 3 := by omega
"""

# lean 内置模块前缀：随 lean 分发，不重复打包（BFS 中直接跳过）
BUILTIN_PREFIXES = ("Init.", "Std.", "Lean.", "Lake.")
# 裸模块名（无子模块）：BFS 中 .ilean 解析不到的 lean 内置根模块
BUILTIN_BARE = {"Init", "Lean", "Lake", "Std"}


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


def find_lean() -> str:
    elan = os.path.expanduser(r"~/.elan/bin/lean.exe")
    if os.path.isfile(elan):
        return elan
    from shutil import which
    for c in ("lean", "lean.exe"):
        p = which(c)
        if p:
            return p
    return ""


def _to_module(entry: str) -> str:
    """兼容 'Mathlib/Tactic' 与 'Mathlib.Tactic' 两种入口写法。"""
    return entry.replace("/", ".").replace("\\", ".").removesuffix(".lean")


def discover_build_roots(project: str) -> list[str]:
    """返回所有可能放置 olean 的 build 根目录（build_lib 优先，外部包随后）。"""
    roots = []
    build_lib = os.path.normpath(
        os.path.join(project, ".lake", "build", "lib", "lean"))
    if not os.path.isdir(build_lib):
        build_lib = os.path.normpath(
            os.path.join(project, ".lake", "build", "lib"))
    if os.path.isdir(build_lib):
        roots.append(build_lib)
    pkgs_dir = os.path.join(project, ".lake", "packages")
    if os.path.isdir(pkgs_dir):
        for pkg in sorted(os.listdir(pkgs_dir)):
            cand = os.path.join(pkgs_dir, pkg, ".lake", "build", "lib", "lean")
            if os.path.isdir(cand):
                roots.append(cand)
    return roots


def collect_deps_bfs(project: str, entry: str = "Mathlib.Tactic") -> list[tuple[str, str]]:
    """用 .ilean 的 directImports 做 BFS，收集入口模块的完整传递依赖。

    lean --deps 会漏模块（实测漏 Mathlib.Util.AtomM.Recurse 等 2000+ 模块），
    不可靠。.ilean 是 lean 4.31 的导入图缓存（JSON），directImports 字段
    记录每个模块的直接 import，BFS 展开即完整传递闭包。

    返回 [(源 olean 绝对路径, 目标相对路径)]，如
    ("D:/.../lean/Mathlib/Tactic/Abel.olean", "Mathlib/Tactic/Abel.olean")。
    仅含根目录下存在 .olean 的模块；lean 内置（Init/Std/Lean/Lake）跳过。
    """
    roots = discover_build_roots(project)
    if not roots:
        print("[error] 未找到任何 build 根目录", file=sys.stderr)
        return []
    entry = _to_module(entry)

    def ilean_of(mod: str) -> tuple[str | None, str | None]:
        """返回 (模块 .ilean 所在根, 源 olean 绝对路径)。找不到返回 (None, None)。"""
        rel = mod.replace(".", os.sep)
        for r in roots:
            ilean = os.path.join(r, rel + ".ilean")
            if os.path.isfile(ilean):
                olean = os.path.join(r, rel + ".olean")
                return r, olean if os.path.isfile(olean) else None
        return None, None

    seen: set[str] = set()
    queue = [entry]
    entries: list[tuple[str, str]] = []
    while queue:
        mod = queue.pop(0)
        if mod in seen:
            continue
        seen.add(mod)
        if mod in BUILTIN_BARE or mod.startswith(BUILTIN_PREFIXES):
            continue
        root, olean = ilean_of(mod)
        if root is None:
            # 找不到 .ilean：非 build 产物模块（理论只剩 lean 内置，已过滤）
            continue
        if olean:
            entries.append((olean, mod.replace(".", os.sep) + ".olean"))
        try:
            with open(os.path.join(root, mod.replace(".", os.sep) + ".ilean"),
                      encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for imp in data.get("directImports", []):
            if isinstance(imp, list) and imp and isinstance(imp[0], str):
                queue.append(imp[0])
    return entries


# Lean 4.31+ 每个 olean 的伴随文件。加载 olean 时若缺失任一 hash/ilean/ir
# 数据文件会报 "missing data file for module X"（实测 2026-09-01）。
# 打包必须整组拷贝，不能只拷 .olean。
def companion_files(olean_path: str) -> list[str]:
    """返回 olean 同目录下属于该模块的伴随文件（存在才列入）。

    用 **stem 前缀**匹配（如 Abel.olean → stem "Abel"，匹配 Abel.*），
    覆盖与 .olean 平行的 .ilean/.ir 及 .olean.xxx 后缀系列：
      .olean / .olean.hash / .ilean / .ilean.hash / .ir / .ir.hash /
      .olean.server / .olean.server.hash / .olean.private / .olean.private.hash
    排除 .trace（lake 构建跟踪，加载不需要）。
    """
    d = os.path.dirname(olean_path)
    base = os.path.basename(olean_path)          # 如 Abel.olean
    stem = base[:-len(".olean")] if base.endswith(".olean") else base  # 如 Abel
    out = []
    for name in os.listdir(d):
        if name == base or (name.startswith(stem + ".") and not name.endswith(".trace")):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                out.append(p)
    return sorted(out)


def package(entries: list[tuple[str, str]], out_dir: str) -> tuple[int, int]:
    """按 (源 olean, 目标相对路径) 清单拷贝，olean 连同伴随文件整组拷贝。

    返回 (拷贝文件数, 总字节)。
    """
    n = total = 0
    for src, rel in entries:
        if not os.path.exists(src):
            continue
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
        total += os.path.getsize(src)
        for cf in companion_files(src):
            # 伴随文件与 olean 同目录同前缀，目标目录与 olean 一致，文件名原样
            dst_cf = os.path.join(out_dir, os.path.dirname(rel), os.path.basename(cf))
            os.makedirs(os.path.dirname(dst_cf), exist_ok=True)
            shutil.copy2(cf, dst_cf)
            n += 1
            total += os.path.getsize(cf)
    return n, total


def verify(out_dir: str, project: str) -> bool:
    """用打包产物（而非本地 build 库）编译探针，验证闭包完整可用。

    严格模式：不经过 lake env（那会把源工程 build 库塞进 LEAN_PATH，
    造成假阳性），直接用 lean + LEAN_PATH=闭包，与比赛环境用法一致。
    """
    lean_exe = find_lean()
    if not lean_exe:
        print("[warn] 无 lean，跳过验证", file=sys.stderr)
        return False
    tmpdir = tempfile.mkdtemp(prefix="leanprobe_")
    path = os.path.join(tmpdir, "t.lean")
    # Lean 不认 Git Bash 的 /tmp 路径，必须用 Windows 绝对路径
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(PROBE_SOURCE)
    env = dict(os.environ)
    # 只指闭包：验证的就是"闭包 + lean 自带库"这一组合能否独立工作
    env["LEAN_PATH"] = out_dir
    proc = subprocess.run([lean_exe, path], cwd=tmpdir,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          timeout=900)
    ok = proc.returncode == 0
    print(f"  编译探针: {'通过' if ok else '失败'}")
    if not ok:
        print("  " + (proc.stdout or "")[:800])
        print("  " + (proc.stderr or "")[:800])
    shutil.rmtree(tmpdir, ignore_errors=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="按依赖清单打包 Mathlib olean")
    ap.add_argument("--project", default=DEF_PROJECT)
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--entry", default="Mathlib.Tactic",
                    help="入口模块（点分或斜杠均可，默认 Mathlib.Tactic）")
    ap.add_argument("--no-verify", action="store_true", help="跳过编译探针")
    args = ap.parse_args()

    entries = collect_deps_bfs(args.project, args.entry)
    if not entries:
        return 1
    print(f"依赖模块 {len(entries)} 个")

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out, exist_ok=True)

    n, total = package(entries, args.out)
    print(f"打包 {n} 个文件，{total / 1e6:.1f} MB → {args.out}")

    if total > 2.5e9:
        print("[warn] 超过 2.5GB 门禁，不建议带上比赛环境", file=sys.stderr)
    elif total > 1.2e9:
        print("[warn] 超过 1.2GB，注意平台体积约束", file=sys.stderr)

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
