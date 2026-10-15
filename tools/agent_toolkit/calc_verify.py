# -*- coding: utf-8 -*-
"""工具③：数学计算验证器（逐条机械复算 · 2026-10-15 用户定稿）。

职责（用户原话）：「就是对大模型的每一个数学计算进行机械检测，这需要大模型
将它的数学计算都发给这个工具，它来利用工具计算一遍，确保大模型不会算错；
要是算错就将算错的地方和正确答案返回。」

实现：SymPy 独立复算（与 Lean 数值核验互为独立交叉校验——见 config 注释）。
本工具是**纯计算**：不做逻辑审核（那是工具①），不做定理检索（那是工具②）。

安全防护：仅接受数学表达式字符串（禁 `__` / `import` / 换行 / 超长），
表达式解析失败按"无法验证"处理（不误判为错）。
"""
from __future__ import annotations

_EXPR_MAX = 800
_FORBIDDEN = ("__", "import", "open(", "exec", "eval", "lambda", "\\n")


def _parse(s: str):
    """字符串 → sympy 表达式；不可解析抛异常。"""
    import sympy
    from sympy.parsing.sympy_parser import (
        parse_expr, standard_transformations, implicit_multiplication_application,
        convert_xor)
    txt = str(s or "").strip()
    if not txt or len(txt) > _EXPR_MAX:
        raise ValueError("empty-or-too-long")
    low = txt.lower()
    for bad in _FORBIDDEN:
        if bad in low:
            raise ValueError("forbidden-token: %s" % bad)
    # ★ 2026-10-15（审核 S10）：幂塔/超大指数防护 —— `9**9**9`（右结合
    #   ⇒ 9**387420489）级表达式会拖垮 SymPy。拒收（按"无法验证"处理）。
    import re as _re_e
    if _re_e.search(r"\*\*\s*\(?\s*\d{6,}", txt):
        raise ValueError("exponent-too-large")
    if _re_e.search(r"[\^*]{1,2}\s*[^*=+\-/()]{1,24}\*\*", txt) or \
            _re_e.search(r"\^\s*[^^=+\-/()]{1,24}\^", txt):
        raise ValueError("power-tower")
    tr = (standard_transformations
          + (implicit_multiplication_application, convert_xor))
    return parse_expr(txt, transformations=tr, evaluate=True,
                      local_dict={"pi": sympy.pi, "e": sympy.E,
                                  "sqrt": sympy.sqrt, "inf": sympy.oo})


def _equal(a, b, tol: float) -> "bool | None":
    """数学等价判定：数值按容差、符号按 simplify(a-b)==0。"""
    import sympy
    try:
        d = sympy.simplify(a - b)
        if d == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        da, db = complex(a.evalf()), complex(b.evalf())
        scale = max(1.0, abs(da), abs(db))
        return abs(da - db) <= tol * scale
    except Exception:  # noqa: BLE001
        pass
    # ★ 2026-10-15（审核 S10）：简化非零且数值不可比 —— 含自由符号时**无法
    #   判定**（返回 None，调用方计 n_err），绝不武断"算错"。
    try:
        if getattr(a, "free_symbols", None) or getattr(b, "free_symbols", None):
            return None
    except Exception:  # noqa: BLE001
        pass
    return False


def _render(v) -> str:
    """把 sympy 值渲染为可读字符串（数值保留足够精度）。"""
    try:
        if v.is_Number:
            if v.is_Integer:
                return str(int(v))
            if v.is_Rational:
                f = float(v)
                return str(v) if abs(f - round(f)) < 1e-12 else "%.15g" % f
            return "%.15g" % float(v.evalf())
    except Exception:  # noqa: BLE001
        pass
    return str(v)


def calc_verify(computations, tol: float = 1e-9) -> dict:
    """逐条机械复算。

    参数
    ----
    computations : list[dict]（[{"expr": "19.9 + (10 - sqrt(9.9))**2", "claimed": "20"}]）
                   或单条 dict / 单个字符串（视为 expr，claimed 留空 ⇒ 只求真值）
    tol          : 数值容差（相对）

    返回
    ----
    {"ok": bool,           # 全部通过（含"无法验证"条目？否——err 计入不通过语义由调用方定，
                           #   本处 ok=False 当且仅当存在 ok=False 的条目）
     "n_ok": int, "n_bad": int, "n_err": int,
     "results": [{"expr","claimed","actual","ok","detail"}]}
        · ok=True  → 一致（或 claimed 留空时的求值成功）
        · ok=False → 不一致（detail 给正确答案）或无法验证（detail 说明原因）
    """
    if isinstance(computations, (str, dict)):
        computations = [computations]
    results, n_ok, n_bad, n_err = [], 0, 0, 0
    for item in (computations or []):
        if isinstance(item, str):
            item = {"expr": item, "claimed": ""}
        if not isinstance(item, dict):
            continue
        expr_s = str(item.get("expr") or "")
        claimed_s = str(item.get("claimed") or "")
        rec = {"expr": expr_s, "claimed": claimed_s, "actual": "",
               "ok": False, "detail": ""}
        try:
            val = _parse(expr_s)
        except Exception as exc:  # noqa: BLE001
            rec["detail"] = "表达式无法解析（未做判定）：%s" % str(exc)[:120]
            n_err += 1
            results.append(rec)
            continue
        rec["actual"] = _render(val)
        if not claimed_s.strip():
            rec["ok"] = True
            rec["detail"] = "已复算（无声称值可比）"
            n_ok += 1
            results.append(rec)
            continue
        try:
            claimed = _parse(claimed_s)
        except Exception as exc:  # noqa: BLE001
            rec["detail"] = "声称值无法解析（未做判定）：%s" % str(exc)[:120]
            n_err += 1
            results.append(rec)
            continue
        _eq = _equal(val, claimed, tol)
        if _eq is True:
            rec["ok"] = True
            rec["detail"] = "一致"
            n_ok += 1
        elif _eq is None:
            # 含自由符号的差异 ⇒ 无法判定（计 n_err，不误报"算错"）
            rec["detail"] = "无法判定（含自由符号的符号差异，未下结论）"
            n_err += 1
        else:
            rec["detail"] = "**算错**：正确结果是 %s（声称 %s）" % (
                _render(val), claimed_s.strip()[:60])
            n_bad += 1
        results.append(rec)
    return {"ok": n_bad == 0 and n_err == 0, "n_ok": n_ok, "n_bad": n_bad,
            "n_err": n_err, "results": results}
