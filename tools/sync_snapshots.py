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

# 目录级同步：把主项目该目录下所有 .py 拷到目标同名目录
PY_DIRS = ["agent", "prompts", "utils", "tests", "tools"]
# 单文件同步
ROOT_FILES = ["user_agent.py", "run_eval.py", "llm_client.py", "main.py",
              "requirements.txt", ".gitignore"]
# 只同步 .md，避免把大附件带进快照
DOC_PATTERN = ".md"


def _sync_dir(src_dir: str, dst_dir: str, pattern: str,
              copied: list[str], skipped: list[str], dry: bool) -> None:
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True) if not dry else None
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src) or not name.endswith(pattern):
            continue
        dst = os.path.join(dst_dir, name)
        if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
            skipped.append(os.path.relpath(dst, _ROOT))
            continue
        copied.append(os.path.relpath(dst, _ROOT))
        if not dry:
            os.makedirs(dst_dir, exist_ok=True)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="同步冻结快照目录")
    ap.add_argument("--dry-run", action="store_true", help="只列出将要改动的文件")
    ap.add_argument("--only", default="", help="只同步指定目录名")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
