# -*- coding: utf-8 -*-
"""板块诊断器：**某板块用不了了，查断在哪一层**。

与 runner.py 的分工
--------------------
    runner   —— 改完代码，验证有没有改坏（回归）
    diagnose —— 它现在为什么不能用（故障定位）

本模块是**独立板块**：主链从不 import 它；默认也**不初始化 Orchestrator**
（那是主链的路径）。只有显式加 `--with-orch` 才进编排器内部查判定链。

设计依据（业界做法）
--------------------
· 「健康检查在撒谎：要探工作路径，不能只探进程」（liveness ≠ 能干活）。
  本项目的实证：`lean_available=True` 但 `lean_active=False` —— 进程活着、路径断了。
· **按序排除**：先验数据/环境（便宜），再验工具，最后才碰模型/编排（贵）。
· 断点之后标 SKIP，不标 FAIL —— 否则会把上游问题算到下游头上。

用法
----
    python tests/bench/diagnose.py --list
    python tests/bench/diagnose.py --chain lean
    python tests/bench/diagnose.py --chain lean --layer mcp_run     # 只跑一层
    python tests/bench/diagnose.py --chain lean --with-orch          # 进编排器查判定链
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ------------------------------------------------------------------ 公共
def _load_env() -> None:
    """按生产的方式加载环境（.env → lean-env.sh → cloud_run.env）。"""
    try:
        p = os.path.join(_ROOT, ".env")
        if os.path.isfile(p):
            import io
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


def _r(ok: bool, evidence: str = "", fix: str = "") -> dict:
    return {"ok": ok, "evidence": evidence, "fix": fix}


# ------------------------------------------------------------------ Lean 探针
def p_lean_exe() -> dict:
    exe = os.environ.get("LEAN_EXECUTABLE", "") or shutil.which("lean") or ""
    return _r(bool(exe), exe or "未找到",
              "装 Lean 4 或设 LEAN_EXECUTABLE 指向二进制")


def p_lake_exe() -> dict:
    lake = shutil.which("lake") or ""
    if not lake:
        exe = os.environ.get("LEAN_EXECUTABLE", "")
        if exe:
            cand = os.path.join(os.path.dirname(exe), "lake")
            lake = cand if os.path.isfile(cand) else ""
    return _r(bool(lake), lake or "未找到（MCP 用它启动 LSP）",
              "把 lean 发行版的 bin 目录加进 PATH；或确认与 lean 同目录")


def p_lean_path() -> dict:
    lp = os.environ.get("LEAN_PATH", "")
    dirs = [d for d in lp.split(os.pathsep) if d and os.path.isdir(d)]
    return _r(bool(dirs), "LEAN_PATH=%r（有效目录 %d 个）" % (lp[:120], len(dirs)),
              "source deploy/lean-env.sh；或由 _compile_lean 挂 LEAN_PROJECT_PATH")


def p_mathlib_olean() -> dict:
    proj = os.environ.get("LEAN_PROJECT_PATH", "")
    if not proj or not os.path.isdir(proj):
        return _r(False, "LEAN_PROJECT_PATH=%r 不存在" % proj, "指向 Mathlib 闭包根")
    hit = os.path.isfile(os.path.join(proj, "Mathlib", "Tactic.olean"))
    agg = os.path.isfile(os.path.join(proj, "Mathlib.olean"))
    return _r(hit, "Mathlib/Tactic.olean=%s 顶层 Mathlib.olean=%s" % (hit, agg),
              "闭包不完整：重跑 deploy/setup_lean.sh")


def p_mathlib_import() -> dict:
    """真正编译一次 import —— 这是「能不能用」而不是「文件在不在」。"""
    proj = os.environ.get("LEAN_PROJECT_PATH", "")
    if not proj:
        return _r(False, "无 LEAN_PROJECT_PATH", "同上一层")
    try:
        from tools.lean_local.lean_bridge import _compile_lean
        r = _compile_lean("import Mathlib.Tactic\n#eval (1 + 1 : Nat)", proj,
                          lean_executable=os.environ.get("LEAN_EXECUTABLE", ""),
                          timeout=300)
        return _r(bool(r.get("ok")), (str(r.get("error")) or "ok")[:200],
                  "检查 _normalize_lean_imports 是否生效、Mathlib 闭包是否完整")
    except Exception as exc:  # noqa: BLE001
        return _r(False, "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                  "lean_bridge 本身导入失败")


def p_mcp_run() -> dict:
    """MCP 通道 —— 曾因 lake 不在 PATH 全废，且失败被包成 ok=True。"""
    proj = os.environ.get("LEAN_PROJECT_PATH", "")
    if not proj:
        return _r(False, "无 LEAN_PROJECT_PATH", "同 mathlib_olean 层")
    try:
        from tools.lean_local.lean_bridge import mcp_run_code
        r = mcp_run_code("#eval (1 + 1 : Nat)", proj, timeout=300)
        ok = bool(r.get("ok")) and bool(r.get("items"))
        return _r(ok, "ok=%s items=%d err=%s" % (
            r.get("ok"), len(r.get("items") or []),
            str(r.get("error") or "")[:160]),
            "看 _ensure_lake_in_path 是否命中；确认 lake 在子进程 PATH")
    except Exception as exc:  # noqa: BLE001
        return _r(False, "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                  "proxy 启动失败")


def p_lean_import_error() -> dict:
    """读主链留下的 import 异常（2026-10-24 新增的 `_LEAN_IMPORT_ERROR`）。

    这是「查不到原因」那类 bug 的正解：失败现场被显式保存，诊断器直接读。
    """
    try:
        import agent.orchestrator as _o
    except Exception as exc:  # noqa: BLE001
        return _r(False, "import agent.orchestrator 失败: %s" % exc,
                  "先解决主链导入问题")
    if bool(getattr(_o, "_LEAN_MODULES_OK", False)):
        return _r(True, "_LEAN_MODULES_OK=True（顶部导入正常）", "")
    err = str(getattr(_o, "_LEAN_IMPORT_ERROR", "") or "")
    return _r(False, "import 异常：\n" + (err[:800] or "(未记录)"),
              "看 traceback 定位缺失依赖或循环导入")


def p_active_flag(with_orch: bool) -> dict:
    """`_lean_active()` 的最终判定 —— 需要真实编排器，故默认跳过。"""
    if not with_orch:
        return {"ok": None, "evidence": "跳过（加 --with-orch 才进编排器）",
                "fix": ""}
    # ★ 用**真实 Orchestrator**（client=None 只构造不发请求）：
    #   诊断的目的就是"与生产一致"，用 ProbeOrch 模拟等于自己骗自己；
    #   构造失败本身就是诊断结果。只读，不发任何 LLM 请求。
    try:
        from user_agent__config import AgentConfig
        from agent.orchestrator import Orchestrator
        orch = Orchestrator(client=None, config=AgentConfig())
        val = bool(orch._lean_active())
        why = str(getattr(orch, "_lean_why", "") or "")
        gate = (type(orch.lean_gate).__name__
                if getattr(orch, "lean_gate", None) is not None else None)
        return _r(val, "返回 %r | lean_gate=%s | 原因=%r" % (val, gate, why),
                  "按原因修：switch_off / config_off / gate_none / probe_false")
    except Exception as exc:  # noqa: BLE001
        return _r(False, "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                  "构造编排器失败（这本身也是诊断结果）")


# ------------------------------------------------------------------ LLM 探针
def p_llm_key() -> dict:
    have = bool(os.environ.get("DEEPSEEK_API_KEY"))
    return _r(have, "DEEPSEEK_API_KEY=%s" % ("有" if have else "无"),
              "在 .env 里配 DEEPSEEK_API_KEY")


def p_llm_reachable() -> dict:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return _r(False, "无凭据", "同上")
    try:
        from utils.llm_client import LLMClient
        cli = LLMClient(api_key=os.environ["DEEPSEEK_API_KEY"],
                        base_url=os.environ.get("DEEPSEEK_API_BASE",
                                                "https://api.deepseek.com"),
                        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                        timeout=120)
        out = cli.chat(messages=[{"role": "user", "content": "hi"}],
                       max_tokens=16)
        return _r(bool(str(out).strip()), "返回 %r" % str(out)[:60],
                  "检查网络 / base_url / 模型名")
    except Exception as exc:  # noqa: BLE001
        return _r(False, "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                  "服务不可达或凭据无效")


def p_llm_truncated() -> dict:
    """★ 静默失效的探针：跑一次真实调用，看 truncated 计数有没有涨。

    `llm_stats()` 是模块级累计，**必须在同一进程内**比对前后差值。
    """
    try:
        from utils.llm_client import llm_stats
    except Exception:  # noqa: BLE001
        return _r(False, "llm_stats 不可用", "检查 utils/llm_client")
    before = int((llm_stats() or {}).get("truncated") or 0)
    try:
        from agent.subgoal_selfcheck import check_subgoal_chain
        chain = [{"id": "1", "title": "t",
                  "conclusion": "值 = 1/2",
                  "basis": "由 A 得 1，故 1/2"}]
        check_subgoal_chain(chain, "（探针）", timeout=300, max_tokens=16384)
    except Exception as exc:  # noqa: BLE001
        return _r(False, "调用异常: %s: %s" % (type(exc).__name__, exc),
                  "先修 llm_reachable 层")
    after = int((llm_stats() or {}).get("truncated") or 0)
    delta = after - before
    return _r(delta == 0, "truncated 增加 %d（前 %d 后 %d）" % (delta, before, after),
              "增加说明 token 被推理吃光 ⇒ 抬高 max_tokens 或缩短输入")


# ------------------------------------------------------------------ 入池探针
def p_normalize_basic() -> dict:
    from utils.extract import normalize_pool_answer
    a, ok = normalize_pool_answer("603729", "解答题")
    return _r(bool(ok), "normalize('603729') => (%r, %r)" % (a, ok),
              "入池判据基本形态坏了")


def p_normalize_meta() -> dict:
    from utils.extract import normalize_pool_answer
    a, ok = normalize_pool_answer("- 依赖：子问题1的上界", "解答题")
    return _r(not ok, "元话语被判 %r（期望不可用）" % ok,
              "补 _looks_like_plan_or_setup 的列表项判据")


def p_normalize_boxed() -> dict:
    from utils.extract import normalize_pool_answer
    a, ok = normalize_pool_answer("\\boxed{\\dfrac{603729}{2}}", "解答题")
    return _r(bool(ok), "boxed 被判 %r" % ok, "boxed 提取坏了")


# ------------------------------------------------------------------ 链定义
CHAINS = {
    "lean": ("Lean 通道（4.3 / 4.4 依赖它）", [
        ("lean_exe", p_lean_exe),
        ("lake_exe", p_lake_exe),
        ("lean_path", p_lean_path),
        ("mathlib_olean", p_mathlib_olean),
        ("mathlib_import", p_mathlib_import),
        ("mcp_run", p_mcp_run),
        ("lean_import_error", p_lean_import_error),
        ("active_flag", None),          # 特殊：需要 with_orch
    ]),
    "subgoal_selfcheck": ("子目标第二模型复核（2.7 merge 前）", [
        ("llm_key", p_llm_key),
        ("llm_reachable", p_llm_reachable),
        ("llm_truncated", p_llm_truncated),
    ]),
    "answer_pool": ("候选入池判据", [
        ("normalize_basic", p_normalize_basic),
        ("normalize_meta", p_normalize_meta),
        ("normalize_boxed", p_normalize_boxed),
    ]),
}


def run_chain(name: str, only_layer: str = "", with_orch: bool = False) -> int:
    desc, layers = CHAINS[name]
    print("诊断板块：%s（%d 层）\n" % (desc, len(layers)))
    broken_at, n_ok, n_skip = "", 0, 0
    for lname, fn in layers:
        if only_layer and lname != only_layer:
            continue
        if broken_at:
            print("  ○  %-20s 跳过（上游 %s 已断）" % (lname, broken_at))
            n_skip += 1
            continue
        res = (p_active_flag(with_orch) if fn is None else fn())
        if res.get("ok") is None:
            print("  ○  %-20s %s" % (lname, res.get("evidence") or "跳过"))
            n_skip += 1
            continue
        if res["ok"]:
            print("  ✅ %-20s %s" % (lname, res.get("evidence") or ""))
            n_ok += 1
        else:
            broken_at = lname
            print("  ❌ %-20s %s" % (lname, res.get("evidence") or ""))
            if res.get("fix"):
                print("     → 修法：%s" % res["fix"])
    print()
    if broken_at:
        print("断点：%s —— 该板块在这里失效，下游会降级/放行" % broken_at)
        return 1
    if n_skip and not only_layer:
        print("结论：已跑的 %d 层全部通过；%d 层因需 --with-orch 跳过" % (n_ok, n_skip))
    else:
        print("结论：%d 层全部通过 —— 该板块依赖链健康" % n_ok)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="板块诊断（独立板块，不启主链）")
    ap.add_argument("--chain", default="", help="lean / subgoal_selfcheck / answer_pool")
    ap.add_argument("--layer", default="", help="只跑某一层")
    ap.add_argument("--with-orch", action="store_true",
                    help="进编排器查判定链（默认不碰主链）")
    ap.add_argument("--list", action="store_true", help="列出板块与层")
    args = ap.parse_args(argv)

    _load_env()

    if args.list:
        for k, (desc, layers) in CHAINS.items():
            print("%-20s %s（%d 层）" % (k, desc, len(layers)))
            for ln, _fn in layers:
                print("    - %s" % ln)
        return 0
    if not args.chain:
        ap.error("请给 --chain（或用 --list 看有哪些）")
    if args.chain not in CHAINS:
        print("未知板块 %r，用 --list 查看" % args.chain)
        return 1
    return run_chain(args.chain, args.layer, args.with_orch)


if __name__ == "__main__":
    sys.exit(main())
