# -*- coding: utf-8 -*-
"""工具①：Lean4 逻辑审核（逻辑错误点 + 逻辑缺少点 · 2026-10-15 用户定稿）。

职责（用户原话）：「接收大模型产出的东西进行逻辑审核，它的产出要是逻辑错误点
和逻辑缺少点……主要目的是让他纠出大模型的错误，并返回具体情况让大模型修正。」

能力最大化（依据 Lean/lean-lsp-mcp 实际能力设计）：
  ① 编译级检查（mcp_run_code → lean-lsp-mcp 本地执行）：
       · 类型/语法错误 → 「逻辑错误点」（带行号 + 诊断原文）
       · 未解决的证明目标（unsolved goals / tactic 失败）→ 「逻辑错误点（证明层）」
  ② 缺口定位：逐行扫描 `sorry` 占位 → 「逻辑缺少点」（哪一步没证）
  ③ 公理审计（lean_verify）与反例判定为后续增强（增量接口已预留 verdict 位）。

边界（诚实声明）：Lean 只认形式化语言——审核上限由「翻译质量」决定（工具④）；
「证不出」≠「命题假」，本工具不臆断（未找到反例时不下"假"结论）。
"""
from __future__ import annotations

import re
import time

_DIAG_RE = re.compile(
    r"^(.*?):(\d+):(\d+):\s*(error|warning)\b[:：]?\s*(.*)$", re.MULTILINE)

# 「证明层」错误关键词（区分"陈述写错"与"证明证不出"）
_PROOF_LAYER_HINTS = ("unsolved goals", "tactic", "tactic '", "no goals",
                      "failed to", "invalid '", "linarith", "omega",
                      "not a definitional equality", "type mismatch")

# 环境/工具执行失败标记（❗实测教训：proxy 的 `ok=True` 只表示"MCP 调用完成"，
#   LSP 起不来时仍 ok=True、错误藏在 `raw`；不识别会把"环境坏"误报成"代码 ok"）
_ENV_FAIL_MARKERS = ("error executing tool", "failed to start",
                     "closed the connection", "mcp-env-missing",
                     "no such file", "not found")


def _detect_env_failure(res: dict) -> str:
    """从 raw/error 提取环境失败痕迹；无则返回 ""。"""
    blob = (str(res.get("raw") or "") + " " + str(res.get("error") or ""))
    low = blob.lower()
    for m in _ENV_FAIL_MARKERS:
        if m in low:
            return blob.strip()[:220]
    return ""


def _parse_items(items, line_shift: int = 0) -> list:
    """proxy `items`（LSP 诊断列表）→ 错误点（字段名容错）。

    ``line_shift``：归一化补/patch Mathlib import 造成的**行号偏移**。
    诊断来自**归一化后**的代码，而调用方（模型/人）看的是**原始**代码 ——
    不减掉偏移，报回来的「第 7 行」在原文里是第 2 行，修错位置。
    """
    out = []
    if isinstance(items, list):
        for it in items[:12]:
            if isinstance(it, dict):
                sev = str(it.get("severity") or it.get("level") or "").lower()
                msg = str(it.get("message") or it.get("text")
                          or it.get("content") or it)
                pos = it.get("line") or it.get("start_line") or ""
                pos = _shift_line(pos, line_shift)
                out.append({
                    "step": ("L%s" % pos) if pos != "" else "",
                    "type": ("error" if ("err" in sev or sev in ("1", "2"))
                             else (sev or "info")),
                    "detail": msg[:300],
                })
            elif isinstance(it, str) and it.strip():
                out.append({"step": "", "type": "error",
                            "detail": it.strip()[:300]})
    return out


def _shift_line(pos, line_shift: int):
    """行号减掉归一化偏移（原代码行号）；减不出来就原样返回。"""
    if not pos or not line_shift:
        return pos
    try:
        v = int(pos) - int(line_shift)
    except (TypeError, ValueError):
        return pos
    return v if v >= 1 else pos


def _parse_diagnostics(text: str, line_shift: int = 0) -> list:
    """从编译输出提取诊断（行号 + 消息）→ 逻辑错误点列表。

    2026-10-15 增强：MCP 的 error 字段可能是**一段 JSON**
    （``{"success": false, "timed_out": false, "diagnostics": [...]}``）——
    优先按 JSON 解析取结构化诊断；失败则退回行级正则。
    """
    txt = str(text or "")
    if txt.strip().startswith("{"):
        try:
            import json as _json
            d = _json.loads(txt)
            diags = d.get("diagnostics") if isinstance(d, dict) else None
            out = []
            if isinstance(diags, list):
                for it in diags[:12]:
                    if isinstance(it, dict):
                        msg = str(it.get("message") or "")
                        sev = str(it.get("severity") or "error").lower()
                        ln = it.get("line") or it.get("start_line") or ""
                        ln = _shift_line(ln, line_shift)
                        out.append({
                            "step": ("L%s" % ln) if ln != "" else "",
                            "type": ("error" if "err" in sev else sev),
                            "detail": msg[:300],
                        })
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass
    errs = []
    for m in _DIAG_RE.finditer(txt):
        errs.append({
            "step": "L%s" % _shift_line(m.group(2), line_shift),
            "type": m.group(4),                       # error / warning
            "detail": (m.group(5) or "").strip()[:300],
        })
    # ★ 2026-10-15 审核修复（S5）：删「整段当 error」兜底 —— 非诊断格式的文本
    #   不是"逻辑错误点"，塞进来会把工具/环境类问题误判为 statement_error；
    #   主流程在"无任何诊断"时按 unknown 处理（不臆断）。
    return errs[:12]


def _is_proof_layer(errs: list) -> bool:
    """错误是否属「证明层」（证不出）而非「陈述层」（写错）。"""
    blob = " ".join(e.get("detail", "") for e in errs).lower()
    return any(h in blob for h in _PROOF_LAYER_HINTS)


def _find_sorry_gaps(code: str) -> list:
    """逐行扫描 sorry → 逻辑缺少点（附带上下文行，便于大模型定位补证处）。"""
    gaps = []
    for i, ln in enumerate((code or "").splitlines(), 1):
        if re.search(r"\bsorry\b", ln):
            gaps.append({
                "step": "L%d" % i,
                "goal": "",
                "hint": "该处为 `sorry` 占位（未证明）：%s" % ln.strip()[:120],
            })
    return gaps[:20]


# Mathlib 就绪探测的进程内缓存（os.walk 有代价；lean_backcheck 对每个存活
# 候选都会调一次本工具，逐次重探测会白烧 I/O）。键 = work_dir（空串 = 自动探测）。
_MATHLIB_READY_CACHE = {}


def _mathlib_ready_for(work_dir: str):
    """Mathlib 是否可编译 —— **复用** `LeanBridge._mathlib_ready`，不复制判据。

    为什么不能自己写 `_has_mathlib_tactics(work_dir)`（★ 实测踩到）：
      `_has_mathlib_tactics` 只认「root 下手写 `Mathlib/Tactic.olean` 或
      `Mathlib/Tactic/NormNum.olean`」。本机 `<lean-env>/test_mathlib` 是
      lake 工程，Mathlib 的 olean 挂在
      `.lake/packages/mathlib/.lake/build/lib/lean/`（或 `.lake` 子树内），
      根目录**没有** `Mathlib/` ⇒ 判 False。而 `_mathlib_ready()` 会查这三条
      `.lake` 路径 + `.lake` 子树兜底 + `_closure_roots()` 兜底 ⇒ 判 True。
      用窄判据的后果是归一化被整条跳过，等于没修（本机实测 False / True）。
      按 `lean_bridge__env` docstring：`_has_mathlib_tactics` 回答的是
      「聚合入口 vs 裁剪闭包」的**形态**问题，不是「要不要归一化」。

    返回 ``(ready: bool, reason: str)``。
    """
    key = work_dir or ""
    if key in _MATHLIB_READY_CACHE:
        return _MATHLIB_READY_CACHE[key]
    try:
        from types import SimpleNamespace
        from tools.lean_local.lean_bridge import LeanBridge
        # 传空串 ⇒ property 回落到 `_detect_lean_project_dir()`，与主链同口径
        cfg = SimpleNamespace(lean_project_dir=key)
        ready = bool(LeanBridge(None, cfg)._mathlib_ready())
        res = (ready, ("mathlib-ready@%s" % (key or "<auto>")) if ready
               else "mathlib-not-ready@%s" % (key or "<auto>"))
    except Exception as exc:  # noqa: BLE001  探测失败 ⇒ 不冒险归一化
        res = (False, "probe-failed: %s: %s"
               % (type(exc).__name__, str(exc)[:80]))
    _MATHLIB_READY_CACHE[key] = res
    return res


def _normalize_switch_on() -> bool:
    """`lean_check_normalize_imports` 开关（默认 True）。

    ★ 为什么"开关 + 能力探测"**两个条件都要**（2026-10-27 合并口径）：
      只有开关 ⇒ 开关开着但环境里 Mathlib 未就绪时，归一化会产出
      `import Mathlib.Tactic`，在裁剪闭包（无聚合入口 olean）下**必败**
      —— 等于把「缺 import」换成「import 不可用」，失败原因更难查。
      只有探测 ⇒ 失去 A/B 能力，`params.json` 里也没有该键。
    读取失败按默认开处理（与注册表默认一致）。
    """
    try:
        from contracts.switch_registry import get_bool as _g
        return bool(_g("lean_check_normalize_imports"))
    except Exception:  # noqa: BLE001
        return True


def _normalize_imports_for_env(code: str, work_dir: str, out: dict):
    """送编译前把 Mathlib import 归一化成**当前环境可用**的形式。

    为什么本工具必须自己做（★ 2026-10-27，P0-2）：
      主链 `sub_goal_solver__lean._lean_block_verify` 在 `_compile` 前调了
      `_prepend_mathlib_import`，本工具一直是 `runner(code, …)` 直送 ——
      模型惯写的 `import Mathlib.Tactic` 在裁剪闭包（无聚合入口 olean）
      下编译必败（`unknown tactic` / 缺 `LT ℕ` 实例）。**同一段无 import
      的代码走主链能编、走本工具必败**，这正是「run_code 16/16 全失败」
      的成因之一，与编译器/环境可用性无关。

    返回**实际送编译**的代码。任何一步不可用时原样返回并在 `out` 里留痕
    （`import_norm`），不静默、不阻断。
    """
    if not _normalize_switch_on():
        out["import_norm"] = {"applied": False, "reason": "switch-off"}
        return code
    ready, why = _mathlib_ready_for(work_dir)
    if not ready:
        out["import_norm"] = {"applied": False, "reason": why}
        return code
    try:
        # ★ 从零依赖模块导（`lean_bridge__env` 只依赖 stdlib）；不走
        #   `lean_bridge` 的 re-export 面，避免将来分层/循环导入牵连。
        from tools.lean_local.lean_bridge__env import _prepend_mathlib_import
    except Exception as exc:  # noqa: BLE001  环境模块不可用 → 原样返回
        out["import_norm"] = {"applied": False,
                              "reason": "env-module-unavailable: %s"
                                        % type(exc).__name__}
        return code
    try:
        new = _prepend_mathlib_import(code)
    except Exception as exc:  # noqa: BLE001  归一化失败 → 用原代码（不阻断）
        out["import_norm"] = {"applied": False,
                              "reason": "normalize-failed: %s: %s"
                                        % (type(exc).__name__, str(exc)[:80])}
        return code
    changed = (new or "") != (code or "")
    out["import_norm"] = {"applied": changed,
                          "reason": ("改写为当前环境可用 import 块（%s）" % why
                                     if changed else "已是可用形式（原样，%s）" % why)}
    return new or code


def _mcp_env_missing(res: dict) -> bool:
    """这次失败是「MCP 通道根本不可用」而不是「代码错」。"""
    err = str(res.get("error") or "").lower()
    if "mcp-env-missing" in err or "mcp-channel-exception" in err:
        return True
    try:
        from tools.lean_local.lean_bridge import _detect_mcp_proxy_python
        return not (_detect_mcp_proxy_python() or "").strip()
    except Exception:  # noqa: BLE001  探测不了 ⇒ 保守认为可用（不回落）
        return False


def _compile_via_bridge(code: str, work_dir: str, timeout: float, client):
    """用 `LeanBridge._compile`（`lake env lean` 直编）执行 —— 本机正路。"""
    import os as _os
    from types import SimpleNamespace
    out = {"ok": False, "error": "", "_via": "bridge"}
    try:
        from tools.lean_local.lean_bridge import LeanBridge, _trash_lean_file
    except Exception as exc:  # noqa: BLE001
        out["error"] = ("bridge-unavailable: %s: %s"
                        % (type(exc).__name__, str(exc)[:100]))
        return out
    cfg = SimpleNamespace(lean_project_dir=work_dir or "",
                          lean_timeout=timeout)
    try:
        bridge = LeanBridge(client, cfg)
    except Exception as exc:  # noqa: BLE001
        out["error"] = ("bridge-init-failed: %s: %s"
                        % (type(exc).__name__, str(exc)[:100]))
        return out
    fname = "lc_%d_%d.lean" % (_os.getpid(), int(time.time() * 1000) % 1000000)
    try:
        r = bridge._compile(code, work_dir, lean_filename=fname,
                            allow_sorry=True)
    except Exception as exc:  # noqa: BLE001
        out["error"] = ("bridge-compile-exception: %s: %s"
                        % (type(exc).__name__, str(exc)[:120]))
        return out
    finally:
        try:
            _trash_lean_file(work_dir, fname)
        except Exception:  # noqa: BLE001  清理失败不影响判定
            pass
    r = r if isinstance(r, dict) else {"ok": bool(r)}
    r["_via"] = "bridge"
    return r


def _default_runner(client):
    """默认执行器：MCP 优先，MCP 环境不可用则回落 bridge 直编。

    ★ 2026-10-27（P0-3）：`mcp_run_code` 依赖 lean-lsp-mcp 的 venv
    （`_detect_mcp_proxy_python()`）。本机实测该探测返回空串 ⇒ `mcp_run_code`
    恒返回 `mcp-env-missing`、耗时 **0.0s** ⇒ 本工具 verdict 恒 `unknown`。
    而主链 `sub_goal_solver__lean._lean_block_verify` 走的是 `bridge._compile`
    （`lake env lean` 直编，不依赖 MCP）—— 同一台机器上「主链能编、本工具恒
    unknown」，这就是「run_code 16/16 全失败」的第二层成因。

    这不是"降级兜底"，是**选对执行器**：`_compile_via_mcp` 的既有契约本就写着
    「proxy 取不到 ⇒ 返回 None ⇒ 调用方回落 bridge」（见其 docstring），
    本工具此前是唯一没实现这条契约的调用方。

    只对**环境不可用**回落。真编译错误（`行:列: error:`）原样返回 ——
    否则会把「代码错」误报成「环境坏」，那比不修更糟。
    """
    def _run(code, work_dir, timeout):
        try:
            from tools.lean_local.lean_bridge import mcp_run_code
            res = mcp_run_code(code, work_dir, timeout)
        except Exception:  # noqa: BLE001  MCP 通道异常 → 直接走 bridge
            res = {"ok": False, "error": "mcp-channel-exception"}
        res = res if isinstance(res, dict) else {"ok": bool(res)}
        if not _mcp_env_missing(res):
            res["_via"] = "mcp"
            return res
        return _compile_via_bridge(code, work_dir, timeout, client)
    return _run


def lean_check(lean_code: str = "", reasoning: str = "", problem: str = "",
               work_dir: str = "", client=None, runner=None,
               timeout: float = 120.0) -> dict:
    """Lean4 逻辑审核（输入 Lean 代码 或 自然语言推理 → 错误点 + 缺少点）。

    参数
    ----
    lean_code : 已形式化的 Lean 代码（优先；有它就直接审核）
    reasoning : 自然语言推理（无 lean_code 时经工具④ to_lean 翻译，需注入 client）
    problem   : 题目上下文（翻译/审核参考）
    work_dir  : Lean 工程目录（传给 mcp_run_code；缺省由 runner 决定）
    client    : LLM 客户端（仅翻译路径需要；由调用方注入）
    runner    : 编译执行器（默认惰性用 lean_bridge.mcp_run_code；测试可注入桩）

    返回
    ----
    {"ok": bool,
     "verdict": "ok"|"statement_error"|"proof_failed"|"proof_incomplete"
                |"needs_translation"|"unknown",
     "errors":  [{"step","type","detail"}],      # 逻辑错误点
     "missing": [{"step","goal","hint"}],        # 逻辑缺少点
      "lean_code": str, "notes": "", "elapsed_s": float, "error": str,
     "import_norm": {"applied": bool, "reason": str},   # Mathlib import 归一化留痕
     "runner_used": "mcp"|"bridge"|""}                  # 实际执行器（MCP 不可用时回落 bridge）
    """
    t0 = time.time()
    out = {"ok": False, "verdict": "unknown", "errors": [], "missing": [],
           "lean_code": "", "notes": "", "elapsed_s": 0.0, "error": "",
           "import_norm": {"applied": False, "reason": "未执行"},
           "runner_used": ""}
    code = (lean_code or "").strip()

    # 无代码 → 尝试翻译（需 client；没有 ⇒ 如实告知"需要翻译"）
    if not code:
        if not (reasoning or "").strip():
            out["error"] = "empty-input（既无 lean_code 也无 reasoning）"
            out["elapsed_s"] = round(time.time() - t0, 2)
            return out
        from .to_lean import to_lean
        tr = to_lean(reasoning, context=problem, client=client)
        if not tr.get("ok"):
            out["verdict"] = "needs_translation"
            out["error"] = "翻译失败/缺 client：%s" % tr.get("error", "")
            out["elapsed_s"] = round(time.time() - t0, 2)
            return out
        code = tr["lean_code"]
        out["lean_code"] = code
        out["notes"] = tr.get("notes", "")
    else:
        out["lean_code"] = code

    # 惰性取默认执行器（可注入桩：runner(code, work_dir, timeout) -> {"ok","error"}）
    # ★ 2026-10-27（P0-3）：默认执行器不再裸挂 `mcp_run_code` —— 它依赖
    #   lean-lsp-mcp venv，本机探测为空 ⇒ 恒 `mcp-env-missing`、0.0s、必 unknown。
    if runner is None:
        try:
            import tools.lean_local.lean_bridge  # noqa: F401  提前暴露导入错误
            runner = _default_runner(client)
        except Exception as exc:  # noqa: BLE001
            out["error"] = "lean-runner-unavailable: %s: %s" % (
                type(exc).__name__, str(exc)[:120])
            out["elapsed_s"] = round(time.time() - t0, 2)
            return out

    # ★ 2026-10-15：work_dir 缺省 → 复用 lean_bridge 的**自动探测**
    #   （与主链同口径；本机探测 = D:/mathlib4-last_bump_for_v4.31.0 ——
    #   这正是「之前能跑通」的配置。此前不探测直接用空目录 ⇒ mcp-env-missing）
    if not work_dir:
        try:
            from tools.lean_local.lean_bridge import (
                _detect_lean_project_dir as _detect_wd)
            work_dir = str(_detect_wd() or "")
        except Exception:  # noqa: BLE001
            work_dir = ""

    # ★ 2026-10-27（P0-2）：归一化**必须在 runner 之前**，且 out["lean_code"]
    #   要同步成实际送编译的代码 —— 否则下游看到的代码与真正编译的不是同一份。
    #   同时算出**行号偏移**：诊断/错误点的 `行:列` 来自归一化后的代码，而
    #   调用方（模型/人）对着的是原始代码。import 块永远插在文件最前面，
    #   所以「总行数差」对所有原 import 之后的行都是同一个偏移量。
    _raw_code = code
    code = _normalize_imports_for_env(code, work_dir, out)
    _shift = 0
    if code != _raw_code:
        out["lean_code"] = code
        _shift = max(0, code.count("\n") - _raw_code.count("\n"))
    out["line_shift"] = _shift

    try:
        res = runner(code, work_dir, timeout)
    except Exception as exc:  # noqa: BLE001  执行异常 ⇒ unknown（不误判）
        out["error"] = "runner-exception: %s: %s" % (
            type(exc).__name__, str(exc)[:160])
        out["elapsed_s"] = round(time.time() - t0, 2)
        return out
    res = res if isinstance(res, dict) else {"ok": bool(res)}
    # 实际用了哪个执行器（mcp / bridge）—— 不记的话「unknown」时又只能靠猜
    out["runner_used"] = str(res.pop("_via", "") or "")

    err_text = str(res.get("error") or "")
    env_fail = _detect_env_failure(res)

    # ★ 环境失败优先判定（含"假 ok"：ok=True 但 raw 写明 LSP 起不来/工具执行失败）
    #   环境问题不是"逻辑错误"，绝不能误报 —— 一律 unknown。
    if env_fail and ("mcp-env-missing" in err_text
                     or "error executing tool" in env_fail.lower()
                     or "failed to start" in env_fail.lower()
                     or "closed the connection" in env_fail.lower()
                     or not res.get("ok")):
        out["verdict"] = "unknown"
        out["error"] = "lean-env-unavailable: %s" % env_fail
        out["elapsed_s"] = round(time.time() - t0, 2)
        return out

    if res.get("ok"):
        # LSP 正常时：诊断在 items；先取错误项（若有 → 错误点）
        items_diag = _parse_items(res.get("items"), line_shift=_shift)
        items_err = [d for d in items_diag if d.get("type") == "error"]
        if items_err:
            out["errors"] = items_err
            out["verdict"] = ("proof_failed" if _is_proof_layer(items_err)
                              else "statement_error")
            out["elapsed_s"] = round(time.time() - t0, 2)
            return out
        # sorry 位置按**原始代码**算：它与 import 无关，用归一化后的会偏移
        gaps = _find_sorry_gaps(_raw_code)
        out["ok"] = True
        if gaps:
            out["verdict"] = "proof_incomplete"
            out["missing"] = gaps
        else:
            out["verdict"] = "ok"
        out["elapsed_s"] = round(time.time() - t0, 2)
        return out

    # 编译失败 → 分类错误点（★ 优先 `items` —— MCP 已结构化的诊断列表；
    #   `error`/`raw` 的 JSON 包装作为次选；无任何诊断 ⇒ unknown 不臆断）
    errs = _parse_items(res.get("items"), line_shift=_shift)
    if not errs:
        errs = _parse_diagnostics(err_text, line_shift=_shift)
    if not errs:
        errs = _parse_diagnostics(str(res.get("raw") or ""), line_shift=_shift)
    if not errs:
        # ★ 2026-10-15 审核修复（S5）：无诊断文本 ⇏ statement_error（可能是
        #   工具/环境/超时类问题）——按 unknown 处理，绝不误判成逻辑错误。
        out["verdict"] = "unknown"
        out["error"] = "no-diagnostics（失败但无诊断文本）: %s" % (
            (err_text or str(res.get("raw") or ""))[:160] or "(空)")
        out["elapsed_s"] = round(time.time() - t0, 2)
        return out
    out["errors"] = errs
    out["verdict"] = "proof_failed" if _is_proof_layer(errs) else "statement_error"
    out["elapsed_s"] = round(time.time() - t0, 2)
    return out
