# -*- coding: utf-8 -*-
"""把主项目的源码同步到两个冻结快照目录（赛事提交版/ 与 gitcode_sync/）。

背景：赛事提交版/ 与 gitcode_sync/ 是比赛/镜像用的冻结副本，
改动主项目后必须同步，否则提交出去的仍是旧代码。
手工拷贝容易漏项（tools/、docs/、deploy/ 各自分散），故脚本化。

同步范围（只覆盖源码与文档，不含大体积部署产物）：
    agent/*.py  prompts/*.py  utils/*.py  tests/*.py  tools/*.py
    user_agent.py  run_eval.py  llm_client.py  main.py  requirements.txt
    docs/*.md  .gitignore
    deploy/setup_lean.sh  deploy/README.md   （仅 gitcode_sync 有 deploy/）

不拷贝：deploy/lean-*.zip、deploy/mathlib-olean/、lean下载版/ 等 GB 级产物。

用法：
    python tools/sync_snapshots.py                 # 同步两个目录
    python tools/sync_snapshots.py --dry-run       # 只看会改什么
    python tools/sync_snapshots.py --only 赛事提交版
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 赛事提交版是要交给评委看的**评审材料**，只放运行时代码；
# tools/ 是开发/诊断工具（部分还依赖本地 superhuman/ 目录），不进提交版。
TARGETS = ["赛事提交版", "gitcode_sync"]
EXCLUDE_DIRS = {
    "赛事提交版": {"tools"},
    "gitcode_sync": set(),   # 镜像站，与仓库保持一致，全量同步
}

# 镜像中**独有逻辑**的文件：不可被主仓覆盖（vendor split，设计使然）。
# 例：tools/lean_local/lean_bridge.py 在镜像里额外含「大文件分片合并」
# （绕过 GitCode 单文件 100MiB 硬限，2026-09-07 加）——若被主仓版本覆盖，
# 该逻辑会被删掉，镜像将无法上传 GitCode。
# 这类文件的正确同步方式 = 定向移植主仓的改动（2026-09-13 已这样处理一次）。
SYNC_SKIP_FILES = {"tools/lean_local/lean_bridge.py"}

# 目录级同步：把主项目该目录下所有 .py 拷到目标同名目录
PY_DIRS = ["agent", "prompts", "utils", "tests", "tools"]
# 单文件同步
ROOT_FILES = ["user_agent.py", "run_eval.py", "llm_client.py", "main.py",
              "requirements.txt", ".gitignore"]
# 只同步 .md，避免把大附件带进快照
DOC_PATTERN = ".md"


def _sync_dir(src_dir: str, dst_dir: str, pattern: str,
              copied: list[str], skipped: list[str], dry: bool) -> None:
    """把 src_dir 下（**含子目录**）匹配 pattern 的文件同步到 dst_dir。

    2026-09-13 修复：原实现用 `os.listdir` + `isfile` 只遍历**直接子文件**，
    ⇒ `tools/lean_local/*` 这类**子目录**下的文件**从未被同步**（实测发现
    lean_gate / lean_pre_verifier / lean_bridge 长期滞留在镜像 ⇒ 线上跑旧代码）。
    现改为 `os.walk` 递归；并跳过 `SYNC_SKIP_FILES`（镜像独有逻辑，设计使然）。
    """
    if not os.path.isdir(src_dir):
        return
    if not dry:
        os.makedirs(dst_dir, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if not name.endswith(pattern):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, _ROOT).replace(os.sep, "/")
            if rel in SYNC_SKIP_FILES:
                skipped.append(rel + "（镜像独有逻辑，按设计跳过）")
                continue
            dst = os.path.join(dst_dir, os.path.relpath(src, src_dir))
            if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
                skipped.append(os.path.relpath(dst, _ROOT))
                continue
            copied.append(os.path.relpath(dst, _ROOT))
            if not dry:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)


def sync_target(target: str, dry: bool) -> tuple[list[str], list[str]]:
    tdir = os.path.join(_ROOT, target)
    if not os.path.isdir(tdir):
        print(f"[warn] 目标目录不存在，跳过: {tdir}", file=sys.stderr)
        return [], []
    copied: list[str] = []
    skipped: list[str] = []

    excluded = EXCLUDE_DIRS.get(target, set())
    for d in PY_DIRS:
        if d in excluded:
            continue
        _sync_dir(os.path.join(_ROOT, d), os.path.join(tdir, d), ".py",
                  copied, skipped, dry)
    _sync_dir(os.path.join(_ROOT, "docs"), os.path.join(tdir, "docs"),
              DOC_PATTERN, copied, skipped, dry)

    for f in ROOT_FILES:
        src = os.path.join(_ROOT, f)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(tdir, f)
        if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
            skipped.append(os.path.join(target, f))
            continue
        copied.append(os.path.join(target, f))
        if not dry:
            shutil.copy2(src, dst)

    # deploy 脚本（gitcode_sync 有 deploy/，赛事提交版没有则跳过）
    deploy_dst = os.path.join(tdir, "deploy")
    if os.path.isdir(deploy_dst):
        for f in ("setup_lean.sh", "README.md"):
            src = os.path.join(_ROOT, "deploy", f)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(deploy_dst, f)
            if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
                skipped.append(os.path.join(target, "deploy", f))
                continue
            copied.append(os.path.join(target, "deploy", f))
            if not dry:
                shutil.copy2(src, dst)

    return copied, skipped


def verify_mirror(target: str) -> tuple[bool, str]:
    """同步后验证：pyflakes（抓 undefined name）+ 自测（真实运行）。

    为什么必须做（2026-09-13 教训）：**hash 对比只能发现"文件内容不同"，发现不了
    语义缺陷** —— 当天两次踩坑都是靠这套验证才暴露的：
      · 镜像缺 `import contextlib`，却仍在第 1083 行用 `@contextlib.contextmanager`
        ⇒ 走到即 NameError；
      · 镜像残留 `_LeanMcpProxyClient(python, script, work_dir)`（函数内变量名是
        py/sc）⇒ `python`/`script` 未定义 ⇒ 执行即 NameError。
    这两类问题 pyflakes 的 `undefined name` 能直接抓到，自测能兜住运行时行为。
    """
    tdir = os.path.join(_ROOT, target)
    if not os.path.isdir(tdir):
        return True, "  [%s] 目录不存在，跳过验证" % target

    out: list[str] = []
    ok = True

    # ① pyflakes：重点抓 undefined name（最致命），其余只统计不报错
    undefined: list[str] = []
    try:
        import glob
        import io
        from pyflakes.api import checkPath
        from pyflakes.reporter import Reporter
        for f in sorted(glob.glob(os.path.join(tdir, "**", "*.py"), recursive=True)):
            if "__pycache__" in f:
                continue
            buf = io.StringIO()
            checkPath(f, Reporter(buf, buf))
            undefined += [
                x for x in buf.getvalue().splitlines()
                if "undefined name" in x or "referenced before assignment" in x]
    except Exception as exc:  # noqa: BLE001
        out.append("  ⚠ pyflakes 检查跳过：%s" % str(exc)[:100])
    if undefined:
        ok = False
        out.append("  ⚠ pyflakes 发现 %d 处 undefined name（必须修，最多列 5 条）："
                   % len(undefined))
        for u in undefined[:5]:
            out.append("      " + u[:160])
    elif not out:
        out.append("  ✓ pyflakes：无 undefined name")

    # ② 自测：仅对含 tools/ + tests/ 的完整镜像（评委版排除 tools ⇒ 自动跳过）
    # 2026-09-13 修正：仅"目录不存在"还不够 —— 评委版把 tools/ 整体排除，
    # 但 tests/ 仍在，依赖 Lean 工具链的用例（如 test_numeric_lean_verify）
    # 必然失败。故按 EXCLUDE_DIRS 判定：排除了 tools 的目标只做静态检查。
    _skips_tools = "tools" in EXCLUDE_DIRS.get(target, set())
    if (not _skips_tools
            and os.path.isdir(os.path.join(tdir, "tools"))
            and os.path.isdir(os.path.join(tdir, "tests"))):
        try:
            import subprocess as _sp
            r = _sp.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                        cwd=tdir, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
            tail = [x for x in (r.stdout or "").strip().splitlines() if x.strip()]
            if r.returncode == 0:
                out.append("  ✓ 自测通过：%s" % (tail[-1][:110] if tail else ""))
            else:
                ok = False
                out.append("  ⚠ 自测失败（退出码 %d）：%s"
                           % (r.returncode, (tail[-1][:150] if tail else "")))
                for x in tail[-6:-1]:
                    out.append("      " + x[:150])
        except Exception as exc:  # noqa: BLE001
            out.append("  ⚠ 自测执行跳过：%s" % str(exc)[:100])
    else:
        out.append("  – 跳过自测（该目标无 tools/ 或被 EXCLUDE_DIRS 排除——"
                   "依赖 Lean 工具链的用例在此形态下必然失败）")

    return ok, "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="同步冻结快照目录")
    ap.add_argument("--dry-run", action="store_true", help="只列出将要改动的文件")
    ap.add_argument("--only", default="", help="只同步指定目录名")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过同步后验证（pyflakes + 自测）")
    args = ap.parse_args()

    targets = [args.only] if args.only else TARGETS
    total = 0
    for t in targets:
        copied, skipped = sync_target(t, args.dry_run)
        print(f"=== {t} ===")
        print(f"  已同步 {len(copied)} 个文件，{len(skipped)} 个无变化")
        for c in copied:
            print(f"    → {c}")
        total += len(copied)
    tag = "（dry-run，未实际改动）" if args.dry_run else ""
    print(f"\n合计同步 {total} 个文件{tag}")

    # 2026-09-13 新增：同步后**强制验证**（只读，不改任何文件）。
    # 必要性见 verify_mirror 的 docstring：hash 对比发现不了语义缺陷，
    # 当天两次踩坑（缺 import contextlib、残留 undefined name）都是它抓到的。
    if not args.dry_run and not args.no_verify:
        print("\n" + "=" * 60)
        print("同步后验证（pyflakes + 自测）")
        print("=" * 60)
        all_ok = True
        for t in targets:
            ok_t, msg = verify_mirror(t)
            all_ok = all_ok and ok_t
            print("--- %s ---" % t)
            print(msg)
        if not all_ok:
            print("\n⚠ 验证未通过：请修复后重新同步（本次改动已写入，未自动回退）")
            return 1
        print("\n✓ 验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
