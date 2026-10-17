# -*- coding: utf-8 -*-
"""4.4 数学工具计算检测 —— 五道审核链第 4 道（2026-10-14 用户定案）。

用户口径（原话）：「第四道就是利用数学工具进行计算检测，看看计算步骤有没有问题」。

实现口径（加模块优先，复用既有数学工具内核）：
  · 后端 = `agent/deterministic.DeterministicChecker.check_answer`（SymPy
    精确判定：答案可解析性 / 常量等式全量回带 / 函数方程回代 / 反例搜索
    —— 均为**可机检**判定，非 LLM 自评），**不新写第二个计算器**；
  · 输入优先取 4.0 的 `answer_norm`（规范化的意义就在于此）；无则回退原文。

判定纪律（沿用 AuditGate Level0 既有实证口径）：
  · 单候选 `verdict == "fail"` ⇒ 计算检测不通过 ⇒ **淘汰**（机器判定，非自评）；
  · `unknown`（不可解析 / 超时 / sympy 不可用）⇒ **放行**（宁 unknown 不误杀）；
  · **全拒** ⇒ 回退保留原候选池（与 `AuditGate.audit_candidates` 的
    「全部候选被否 → 回退保留（宁 unknown 不误杀）」逐字一致），显式留痕。

观测：trace step=``math_check``，diag 键 ``math_check`` / ``math_check_events``。

五道链位置：4.0 规范化 → 4.1 自审 → 4.2 对抗证伪 → 4.3 Lean 代回 →
**4.4 计算检测** → ⑤投票。
"""
from __future__ import annotations

import re

from .switch_registry import get_bool as _sw_get_bool

def _switch_enabled() -> bool:
    """读「五道链·第 4 道计算检测」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_math_check")
    except Exception:  # noqa: BLE001
        return True


def _calcverify_enabled() -> bool:
    """读「4.4 工具③等式复算观测通道」开关（默认 False，云端 A/B 时开）。

    ★ 2026-10-15（工具化定稿）：开启后对**存活候选的推理**提取"数值等式"
    （如 ``19.9 + (10 - sqrt(9.9))**2 = 20``），逐条调工具③
    ``tools/agent_toolkit.calc_verify`` 机械复算；算错的条目写 diag
    （``ctx.math_calcverify``）与 trace —— **观测模式：暂不改淘汰**。
    """
    try:
        return _sw_get_bool("five_gate_math_check_calcverify")
    except Exception:  # noqa: BLE001
        return False


# 数值等式提取（2026-10-15 工具③）：两侧须以数字开头；白名单函数名之外的
# 裸字母（变量）一律拒 —— 防止把 `x = 3` 这类赋值当"计算式"误报算错。
# ★ 2026-10-15 修复：原正则两侧都强制"首字符+中间≥2+尾字符"三段式 ⇒
#   单字符结果（如 `2 + 3 = 6` 的右值 "6"）**提取失败**（实测暴露）。
#   现改为「首数字 +（中间任意 + 尾字符）可选」两段式，单字符结果可提取。
# ★ 2026-10-15 修复二（审核 S1）：模型常写 Unicode 运算符 `×`/`÷`/`−` ——
#   字符类不收会把 `20 × 3 = 60` 从 `3` 起劈成假等式（`3 = 60`）⇒ 误报"算错"。
#   现收录 Unicode 运算符，并在提取时归一化为 ASCII 交给 SymPy。
_CALC_EQ_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"([0-9](?:[0-9A-Za-z.\s*+\-/()^×÷−]*?[0-9A-Za-z)×÷−])?)"
    r"\s*=\s*"
    r"([0-9](?:[0-9A-Za-z.\s*+\-/()^×÷−]*?[0-9A-Za-z)×÷−])?)"
    r"(?![A-Za-z0-9_])")
_OP_NORMALIZE = (("×", "*"), ("·", "*"), ("⋅", "*"), ("÷", "/"),
                 ("−", "-"), ("–", "-"), ("—", "-"))
_ALLOWED_FUNCS = ("sqrt", "abs", "floor", "ceil", "log", "exp", "sin",
                  "cos", "tan", "pi", "ln", "pow", "e")


def _looks_numeric(s: str) -> bool:
    """去掉白名单函数名后不得残留裸字母（否则疑似含变量 ⇒ 拒收）。"""
    t = s
    for fn in sorted(_ALLOWED_FUNCS, key=len, reverse=True):
        t = t.replace(fn, " ")
    return not re.search(r"[A-Za-z]", t)


def _extract_numeric_equations(text: str) -> list:
    """从推理文本提取数值等式 [(lhs, rhs), ...]（最多 8 条）。

    ★ 2026-10-15（审核 S1）：Unicode 运算符（× ÷ − · 等）归一化为 ASCII
    后再交给 SymPy —— 否则 SymPy 解析失败会被判"无法验证"，而错误的分割
    还可能产生假等式。
    """
    def _norm(s: str) -> str:
        for _u, _a in _OP_NORMALIZE:
            s = s.replace(_u, _a)
        return s
    out = []
    for m in _CALC_EQ_RE.finditer(text or ""):
        lhs, rhs = _norm(m.group(1).strip()), _norm(m.group(2).strip())
        if _looks_numeric(lhs) and _looks_numeric(rhs):
            out.append((lhs, rhs))
        if len(out) >= 8:
            break
    return out


_CALC_INEQ_RE = None


def _extract_inequalities(text: str) -> list:
    """从推理文本提取**可机器复算的不等式** [(lhs, rhs, op), ...]（最多 8 条）。

    ★ 2026-10-17（用户要求「计算错误要靠工具检」）：原工具只验数值等式，
      017 型错误（``a^2+3b^2 >= 4|a||b|^3`` 为假）不在检测范围。
    ★ 安全边界（防误杀题面条件）：**两侧都必须含运算符/函数**（`^ * / + - sqrt abs`
      等）；`n >= 2` / `k >= 1` 这类纯条件（两侧只有变量/常数）**不提取**。
    """
    global _CALC_INEQ_RE
    import re as _re
    if _CALC_INEQ_RE is None:
        _CALC_INEQ_RE = _re.compile(
            r"([^\n=<>]{2,80}?)\s*(>=|<=|≥|≤|>|<)\s*([^\n=<>]{1,80})")
    _OPS = {">=": "ge", "<=": "le", "≥": "ge", "≤": "le", ">": "gt", "<": "lt"}
    _LOOKS = _re.compile(r"[\^*+\-/]|sqrt|abs|\\frac")
    def _clean(x: str) -> str:
        # 去中文前后缀（"由 a^2" / " 可得…"）并把 |expr| 归一化为 Abs(expr)
        x = _re.sub(r"[\u4e00-\u9fff，。；、：（）【】]+", " ", x).strip()
        x = _re.sub(r"\|([^|]+)\|", r"Abs(\1)", x)
        x = _re.sub(r"[.…·]+\s*$", "", x).strip()   # 去省略号尾巴（"…可得..."）
        return x

    out = []
    for m in _CALC_INEQ_RE.finditer(text or ""):
        lhs, op, rhs = _clean(m.group(1)), m.group(2), _clean(m.group(3))
        if not lhs or not rhs:
            continue
        # 两侧都必须"像表达式"（含运算符/函数）——纯变量/常数视为题面条件
        if not _LOOKS.search(lhs) or not _LOOKS.search(rhs):
            continue
        if len(lhs) > 70 or len(rhs) > 70:
            continue
        out.append((lhs, rhs, _OPS[op]))
        if len(out) >= 8:
            break
    return out


def math_check_stage(self, ctx) -> None:
    """4.4 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。

    注入点：``getattr(self, "math_check_det", None) or DeterministicChecker()``
    （与 4.3/4.2 同款，便于单测注入桩）。
    """
    try:
        if not _switch_enabled():
            self.record(ctx, "math_check",
                        "4.4 计算检测：开关关闭（five_gate_math_check=0）")
            return
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            self.record(ctx, "math_check", "4.4 计算检测：候选池为空，跳过")
            return

        from .deterministic import DeterministicChecker
        _det = getattr(self, "math_check_det", None) or DeterministicChecker()
        problem = str(getattr(ctx, "problem", "") or "")
        domain = str(getattr(ctx, "domain", "") or "")

        kept, rejected, n_fail, n_unknown = [], [], 0, 0
        for c in cands:
            cid = getattr(c, "id", "?")
            kind = str(getattr(c, "answer_kind", "") or "")
            ans = str(getattr(c, "answer_norm", None)
                      or getattr(c, "answer", "") or "")
            det = {"verdict": "unknown", "evidence": "", "method": ""}
            try:
                det = _det.check_answer(ctx, problem, ans, domain or None) or det
            except Exception as _e_d:  # noqa: BLE001  异常 ⇒ 放行（不误杀）
                self.record(ctx, "math_check",
                            "cid=%s 计算检测异常（放行）: %s: %s"
                            % (cid, type(_e_d).__name__, str(_e_d)[:120]))
            # ★ 2026-10-17（用户要求「计算过程交给工具检」）：工具③逐式复算
            #   推理里的等式 + 不等式；**确有反例/算错 ⇒ 淘汰**（带证据）；
            #   无法判定（n_err）⇒ 放行（不误杀）。
            try:
                from tools.agent_toolkit.calc_verify import calc_verify as _cv
                _txt = str(getattr(c, "reasoning", "") or "")
                _eqs = _extract_numeric_equations(_txt)
                _ineq = _extract_inequalities(_txt)
                _items = [{"expr": a, "claimed": b} for a, b in _eqs[:8]]
                _items += [{"expr": a, "claimed": b, "op": op}
                           for a, b, op in _ineq[:8]]
                if _items:
                    _rv = _cv(_items)
                    _nb = int(_rv.get("n_bad") or 0)
                    if _nb > 0:
                        _r0 = next((x for x in (_rv.get("results") or [])
                                    if not x.get("ok") and "不成立" in str(x.get("detail"))
                                    or "算错" in str(x.get("detail"))), {})
                        n_fail += 1
                        rejected.append({
                            "id": cid, "kind": kind, "answer": ans[:160],
                            "method": "calc_verify",
                            "evidence": str(_r0.get("detail") or "")[:300]})
                        self.record(ctx, "math_check",
                                    "cid=%s 工具③逐式复算：%d 条不一致 ⇒ 淘汰；样例 %s"
                                    % (cid, _nb, str(_r0.get("detail") or "")[:160]))
                        continue
            except Exception as _e_cv:  # noqa: BLE001
                self.record(ctx, "math_check",
                            "cid=%s 工具③复算异常（放行）: %s: %s"
                            % (cid, type(_e_cv).__name__, str(_e_cv)[:100]))
            _v = str(det.get("verdict") or "unknown")
            if _v == "fail":
                n_fail += 1
                rejected.append({
                    "id": cid, "kind": kind, "answer": ans[:160],
                    "method": str(det.get("method") or ""),
                    "evidence": str(det.get("evidence") or "")[:300]})
                self.record(ctx, "math_check",
                            "cid=%s **计算检测不通过**（%s）⇒ 淘汰：%s"
                            % (cid, det.get("method") or "-",
                               str(det.get("evidence") or "")[:200]))
            else:
                if _v == "unknown":
                    n_unknown += 1
                kept.append(c)
                self.record(ctx, "math_check",
                            "cid=%s 通过/放行（verdict=%s%s）"
                            % (cid, _v,
                               "、kind=%s" % kind if kind else ""))

        if rejected and not kept:
            # 全拒 ⇒ 回退保留（宁 unknown 不误杀；与 AuditGate 口径一致）
            kept = cands
            ctx.math_check = {
                "n": len(cands), "n_rejected": 0, "n_fail": n_fail,
                "n_unknown": n_unknown, "all_rejected_fallback": True,
                "would_reject_ids": [r["id"] for r in rejected],
            }
            self.record(ctx, "math_check",
                        "⚠ 4.4 计算检测：%d 个候选**全部未通过** ⇒ 回退保留"
                        "原候选池（宁 unknown 不误杀）" % len(cands))
        else:
            if rejected:
                ctx.candidates = kept
                ctx.audit_reject_feedback = list(
                    getattr(ctx, "audit_reject_feedback", None) or []) + [
                        "[计算检测] cid=%s: %s（%s）"
                        % (r["id"], r["evidence"], r["method"])
                        for r in rejected]
                ctx.math_check_rejected = list(
                    getattr(ctx, "math_check_rejected", None) or []) + rejected
            ctx.math_check = {
                "n": len(cands), "n_rejected": len(rejected), "n_fail": n_fail,
                "n_unknown": n_unknown, "all_rejected_fallback": False,
                "rejected_ids": [r["id"] for r in rejected],
            }
            self.record(ctx, "math_check",
                        "4.4 计算检测：%d 候选 ⇒ 淘汰 %d / 保留 %d"
                        "（无法判定 %d）"
                        % (len(cands), len(rejected), len(kept), n_unknown))

        # ★ 2026-10-15（工具③接线 · 观测模式）：对最终存活候选的推理做
        #   "等式逐条机械复算"（工具③ calc_verify）——算错条目写 diag/record，
        #   不影响淘汰（等云端验证后再升级为判定通道）。
        if _calcverify_enabled() and kept:
            try:
                from tools.agent_toolkit import calc_verify as _cv
                _n_eq, _bad = 0, []
                for _c in kept:
                    _eqs = _extract_numeric_equations(
                        str(getattr(_c, "reasoning", "") or ""))
                    if not _eqs:
                        continue
                    _n_eq += len(_eqs)
                    _r = _cv([{"expr": a, "claimed": b}
                              for a, b in _eqs[:8]])
                    for _x in (_r.get("results") or []):
                        if not _x.get("ok"):
                            _bad.append({
                                "id": getattr(_c, "id", None),
                                "expr": str(_x.get("expr", ""))[:80],
                                "claimed": str(_x.get("claimed", ""))[:40],
                                "actual": str(_x.get("actual", ""))[:40],
                                "detail": str(_x.get("detail", ""))[:140]})
                ctx.math_calcverify = {"n_checked": _n_eq, "n_bad": len(_bad),
                                       "bad": _bad[:8]}
                if _bad:
                    _x0 = _bad[0]
                    self.record(ctx, "math_check",
                                "4.4（工具③观测）：复算 %d 条等式，发现 %d 条"
                                "**不一致**；样例 cid=%s: %s = %s → 实际 %s"
                                % (_n_eq, len(_bad), _x0["id"], _x0["expr"],
                                   _x0["claimed"], _x0["actual"]))
                else:
                    self.record(ctx, "math_check",
                                "4.4（工具③观测）：复算 %d 条等式，全部一致"
                                % _n_eq)
            except Exception as _e_cv:  # noqa: BLE001  观测通道绝不阻断主链
                self.record(ctx, "math_check",
                            "4.4（工具③观测）异常（跳过）: %s: %s"
                            % (type(_e_cv).__name__, str(_e_cv)[:100]))

        try:
            from .orchestrator__verify import _pool_empty_fallback as _pef
            _pef(self, ctx, "4.4_math_check")
        except Exception:  # noqa: BLE001  兜底检查失败不影响主流程
            pass
    except Exception as _e:  # noqa: BLE001  增益环节绝不阻断主链
        self.record(ctx, "math_check",
                    f"4.4 计算检测异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
