# -*- coding: utf-8 -*-
"""工具测试台：**只跑指定工具/环节，绝不启动主链**。

为什么需要（2026-10-24 用户定）
--------------------------------
「这个东西和主测试没有任何关系，正常测试不会用到它，它不会启动。
  只有我们测试的时候才会启动，用提前准备好的数据库测试我们要测试的环节和工具。」

主链一次 4~6 小时，任何一环坏了都要跑完才知道。本工具用**预置样本**
（`tests/bench/cases/*.jsonl`）单独喂给某个工具，秒级看产出对不对：

    python tests/bench/runner.py --list                    # 有哪些样本
    python tests/bench/runner.py --tool lean_compile       # 只测 Lean 编译
    python tests/bench/runner.py --case lean_sorry_rejected # 只测一个
    python tests/bench/runner.py --all                     # 全跑

与主链的关系
------------
**零耦合**：不被 `run_eval` / `run_112` import，只在命令行手动调用。
样本里声明的 `requires` 不满足（如本地没有 Mathlib）⇒ 该条 SKIP，不算失败。

样本格式（每行一个 JSON）
------------------------
    {"id": "...", "tool": "lean_compile", "requires": ["lean","mathlib"],
     "input": {...}, "expect": {...}, "note": "为什么有这条"}

`expect` 支持的断言：`ok` / `error_contains` / `items_min` / `n_suspects` /
`kind` / `not_ok`。不写就只检查"没抛异常"。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

CASES_DIR = os.path.join(_ROOT, "tests", "bench", "cases")


# ------------------------------------------------------------------ 环境
def load_prod_env() -> None:
    """加载 .env 与 lean 环境（与主链一致），失败静默。"""
    try:
        p = os.path.join(_ROOT, ".env")
        if os.path.isfile(p):
            for ln in io.open(p, encoding="utf-8", errors="ignore"):
                ln = ln.strip()
                if "=" in ln and not ln.startswith("#"):
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(),
                                          v.strip().strip('"').strip("'"))
    except Exception:  # noqa: BLE001
        pass
    try:
        import subprocess
        for f in ("deploy/lean-env.sh", "deploy/cloud_run.env"):
            fp = os.path.join(_ROOT, f)
            if not os.path.isfile(fp):
                continue
            r = subprocess.run(["bash", "-c", 'set -a; . "%s" 2>/dev/null; env' % fp],
                               cwd=_ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
            for ln in (r.stdout or "").splitlines():
                if "=" in ln:
                    k, v = ln.partition("=")[0], ln.partition("=")[2]
                    if k and not k.startswith("_"):
                        os.environ[k] = v
    except Exception:  # noqa: BLE001
        pass


def env_status() -> dict:
    """探测三类前置条件是否具备。"""
    proj = os.environ.get("LEAN_PROJECT_PATH", "")
    exe = os.environ.get("LEAN_EXECUTABLE", "") or shutil.which("lean") or ""
    return {
        "lean": bool(exe),
        "mathlib": bool(proj and os.path.isdir(proj)
                        and os.path.isfile(os.path.join(proj, "Mathlib", "Tactic.olean"))),
        "lean_exe": exe,
        "project": proj,
    }


# ------------------------------------------------------------------ 工具适配器
def _work_dir(env: dict) -> str:
    """Lean 编译工作目录：优先用 Mathlib 工程，没有就用一个临时目录。"""
    if env.get("project") and os.path.isdir(env["project"]):
        return env["project"]
    return tempfile.mkdtemp(prefix="bench_lean_")


def run_lean_compile(case: dict, env: dict) -> dict:
    from tools.lean_local.lean_bridge import _compile_lean
    code = str((case.get("input") or {}).get("code") or "")
    wd = _work_dir(env)
    timeout = float((case.get("input") or {}).get("timeout") or 300)
    r = _compile_lean(code, wd, lean_executable=env.get("lean_exe", ""),
                      timeout=timeout)
    return {"ok": bool(r.get("ok")), "error": str(r.get("error") or "")}


def run_lean_mcp(case: dict, env: dict) -> dict:
    from tools.lean_local.lean_bridge import mcp_run_code
    code = str((case.get("input") or {}).get("code") or "")
    r = mcp_run_code(code, env.get("project", ""), timeout=300)
    return {"ok": bool(r.get("ok")), "n_items": len(r.get("items") or []),
            "error": str(r.get("error") or "")}


def run_obligation_selfcheck(case: dict, env: dict) -> dict:
    from agent.obligation_selfcheck import check_ledger
    lg = {"obligations": (case.get("input") or {}).get("obligations") or []}
    sus = check_ledger(lg)
    return {"n_suspects": len(sus), "kind": (sus[0]["kind"] if sus else ""),
            "detail": sus}


def run_subgoal_selfcheck(case: dict, env: dict) -> dict:
    """需要第二模型；没有 key 时抛错（该条判 FAIL 而不是 SKIP，提醒配凭据）。"""
    from agent.subgoal_selfcheck import check_subgoal_chain
    inp = case.get("input") or {}
    sus = check_subgoal_chain(inp.get("chain") or [], str(inp.get("problem") or ""))
    return {"n_suspects": len(sus), "detail": sus}


TOOLS = {
    "lean_compile": run_lean_compile,
    "lean_mcp": run_lean_mcp,
    "obligation_selfcheck": run_obligation_selfcheck,
    "subgoal_selfcheck": run_subgoal_selfcheck,
}


# ------------------------------------------------------------------ 执行
def load_cases() -> list[dict]:
    out = []
    if not os.path.isdir(CASES_DIR):
        return out
    for name in sorted(os.listdir(CASES_DIR)):
        if not name.endswith(".jsonl"):
            continue
        for ln in io.open(os.path.join(CASES_DIR, name), encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                try:
                    out.append(json.loads(ln))
                except Exception:  # noqa: BLE001
                    pass
    return out


def check_expect(got: dict, exp: dict) -> tuple[bool, str]:
    """按 expect 逐条断言；返回 (通过, 失败说明)。"""
    for key, want in (exp or {}).items():
        if key == "ok":
            if bool(got.get("ok")) != bool(want):
                return False, "ok 期望 %r 实际 %r" % (want, got.get("ok"))
        elif key == "not_ok":
            if bool(got.get("ok")):
                return False, "期望不 ok，实际 ok=True"
        elif key == "error_contains":
            if str(want) not in str(got.get("error") or ""):
                return False, "错误信息里没有 %r（实际：%s）" % (
                    want, str(got.get("error"))[:120])
        elif key == "items_min":
            if int(got.get("n_items") or 0) < int(want):
                return False, "items 期望 ≥%d 实际 %d" % (want, got.get("n_items") or 0)
        elif key == "n_suspects":
            if int(got.get("n_suspects") or 0) != int(want):
                return False, "可疑条数期望 %d 实际 %d" % (want, got.get("n_suspects") or 0)
        elif key == "kind":
            if str(got.get("kind") or "") != str(want):
                return False, "类型期望 %r 实际 %r" % (want, got.get("kind"))
    return True, ""


def run_one(case: dict, env: dict) -> dict:
    cid = case.get("id", "?")
    tool = case.get("tool", "")
    need = case.get("requires") or []
    missing = [n for n in need if not env.get(n)]
    if missing:
        return {"id": cid, "status": "SKIP", "why": "缺 " + ",".join(missing),
                "elapsed": 0.0}
    fn = TOOLS.get(tool)
    if fn is None:
        return {"id": cid, "status": "FAIL", "why": "未知工具 %r" % tool, "elapsed": 0.0}
    t0 = time.time()
    try:
        got = fn(case, env)
    except Exception as exc:  # noqa: BLE001
        return {"id": cid, "status": "FAIL",
                "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                "elapsed": time.time() - t0}
    ok, why = check_expect(got, case.get("expect") or {})
    return {"id": cid, "status": "PASS" if ok else "FAIL", "why": why,
            "got": got, "elapsed": time.time() - t0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工具测试台（不启动主链）")
    ap.add_argument("--tool", default="", help="只测某工具")
    ap.add_argument("--case", default="", help="只测某个 id")
    ap.add_argument("--list", action="store_true", help="列出样本")
    ap.add_argument("--all", action="store_true", help="全跑")
    args = ap.parse_args(argv)

    load_prod_env()
    env = env_status()
    cases = load_cases()

    if args.list:
        print("环境：lean=%s mathlib=%s" % (env["lean"], env["mathlib"]))
        print("样本 %d 条：\n" % len(cases))
        for c in cases:
            print("  %-26s %-22s %s" % (c.get("id"), c.get("tool"),
                                        (c.get("note") or "")[:52]))
        print("\n工具：%s" % ", ".join(sorted(TOOLS)))
        return 0

    if args.case:
        cases = [c for c in cases if c.get("id") == args.case]
    elif args.tool:
        cases = [c for c in cases if c.get("tool") == args.tool]
    elif not args.all:
        ap.error("请给 --tool / --case / --all / --list 之一")

    if not cases:
        print("没有匹配的样本")
        return 1

    print("环境：lean=%s mathlib=%s\n" % (env["lean"], env["mathlib"]))
    n_pass = n_fail = n_skip = 0
    for c in cases:
        r = run_one(c, env)
        tag = {"PASS": "✅", "FAIL": "❌", "SKIP": "○"}[r["status"]]
        print("%s %-26s %6.1fs  %s" % (tag, r["id"], r["elapsed"],
                                       r["why"] or "-"))
        if r["status"] == "PASS":
            n_pass += 1
        elif r["status"] == "FAIL":
            n_fail += 1
            if r.get("got"):
                print("      got: %s" % str(r["got"])[:160])
        else:
            n_skip += 1
    print("\n合计：PASS %d / FAIL %d / SKIP %d" % (n_pass, n_fail, n_skip))
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
