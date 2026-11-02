# -*- coding: utf-8 -*-
"""已定义符号表 —— 让「差含符号」从「判不出」变成「能判」。

为什么需要它
------------
推导里的等式绝大多数不是恒等断言，而是「在本题配置下 L 等于 R」：

    T_max - 76                 T_max 是前面步骤定义的量
    -4*a + Δ - 5               Δ 是定义过的常量
    x^2 + y^2 + z^2 - 3        这是**题设条件**

判据里没有符号表，就无法区分「自由变量」与「前面已定义的常量」，于是任何
用到已定义量的正确步骤都只能判 unknown。2026-11-02 当时的处置是**放弃判定**
（含符号一律放行）—— 那是用删除判据来解决信息缺失，违反项目「兜底≠修复」
「显式失败留痕」两条硬约束，而且实测它在 112 行里直接放弃了 35 次判定。

正确做法：**把定义收集起来，代入后再判**。定义本来就都在盘上 ——
同题前序步骤的结论行、本步依据、题面条件。收不齐时才允许 unknown，
且必须把「缺哪个符号」写进原因（可归因，不是静默放行）。

边界（不可让渡）
----------------
1. **只收「已成立」的定义**：调用方只在判定为 correct 之后才并入，避免把
   假前提当事实喂给后续步骤（`obligation_ledger` 就是这么被污染的）。
2. **不做猜测性绑定**：只认 `sym = expr` 形态且 sym 是单个符号；`f(x) = ...`
   这种函数定义不收（无法安全代入）。
3. **循环定义有上限**：代入最多 3 轮，超限留 unresolved，绝不无限展开。

★★★ 实测结论：这个模块**不能接进生产链路**（2026-11-03）
-------------------------------------------------------
干净 A/B（63 题次 / 112 行，只翻「有没有符号表」一个变量）看起来不错：
undecided→correct 3、undecided→incorrect 5、反向退化 0。但**逐条抽验这 8 条，
只有 1 条经得起检验**，其余 7 条是污染造成的误判：

    P(x) = x - 4     判「实际值应为 x」     把函数名当常量（P = 1）
    a+b+c = 10       判「实际值应为 2」     a=1,b=1 抄自某特例分支
    x^2 = 3-y^2-z^2  判不成立              x=0 / z=x^3 是错误绑定

两层根因：① 正则从散文里抽「符号 = 式」不可靠，抽错一条毒化后续所有判定；
② 数学推导里同一符号在不同分支含义可以不同，**全局单一符号表语义上不成立**。

⇒ 只作回放/诊断用（`replay_symtab_ab.py`）。生产的 `_sympy_judge` 不接收
  symtab（默认 None）。要真做对：绑定必须来自受控句式（设/记/令）或结构化
  字段，并按分支作用域隔离。
"""
import re

try:
    import sympy as _sp
except Exception:  # noqa: BLE001
    _sp = None

__all__ = [
    "is_symbol", "collect_bindings", "merge_bindings",
    "substitute", "describe",
]

# 单个符号：x / T_max / x_k / Δ / λ（允许下标，不允许函数调用）
_SYMBOL_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
# `sym = expr`（行内、可前后有其他文字），expr 到行尾或分隔符为止
_BIND_RE = re.compile(
    r"(?<![\w\\])([A-Za-z\u0391-\u03c9][A-Za-z0-9_]*)"
    r"\s*=\s*([^=,\n;，；。\u4e00-\u9fff]{1,80})",
    re.UNICODE)
# 明显不该当定义的开头（散文/集合/区间）
_BAD_TAIL = re.compile(
    r"^(真|假|是|否|成立|不成立|当且仅当|the|true|false|yes|no)(?:\b|$|[\s，。；])",
    re.I)

_MAX_BINDINGS = 40


def is_symbol(s: str) -> bool:
    """是不是**一个符号**（x / T_max / x_k / Δ）。"""
    return bool(_SYMBOL_RE.match((s or "").strip()))


def _clean(expr: str) -> str:
    return (expr or "").strip().strip("$").strip().rstrip(".,;:，。；：").strip()


def _plausible(expr: str) -> bool:
    """右侧像不像一个可代入的数学式（而非散文）。"""
    e = _clean(expr)
    if not e or len(e) > 80:
        return False
    if _BAD_TAIL.match(e):
        return False
    # 必须含至少一个数字或运算符，且不含明显的中文散文（允许少量中文量词）
    if not re.search(r"[0-9+\-*/^()]|sqrt|pi|sin|cos|tan|log", e):
        return False
    if re.search(r"[\u4e00-\u9fff]{2,}", e):
        return False
    return True


def collect_bindings(*texts, max_n=_MAX_BINDINGS) -> dict:
    """从若干段文本里抽 `sym = expr` 定义。返回 {sym: expr_str}。

        只收**单符号左值 + 看似数学式右值**，宁可漏收不误收 ——
        误收一条假定义会污染后续所有判定。
    """
    out = {}
    for t in texts:
        if not t or len(out) >= max_n:
            continue
        for m in _BIND_RE.finditer(str(t)):
            sym, expr = m.group(1), _clean(m.group(2))
            if not is_symbol(sym) or not _plausible(expr):
                continue
            if sym in out and out[sym] != expr:
                # 同名不同值：保留先出现的（前序定义），冲突留给 unresolved
                continue
            out.setdefault(sym, expr)
            if len(out) >= max_n:
                break
    return out


def merge_bindings(symtab: dict, bindings: dict, *, overwrite=False) -> int:
    """把新定义并入表。返回新增条数。已有定义**默认不覆盖**（先定义先算数）。"""
    if symtab is None:
        return 0
    n = 0
    for k, v in (bindings or {}).items():
        if k in symtab and not overwrite:
            continue
        symtab[k] = v
        n += 1
    return n


def substitute(expr, symtab, max_rounds=3):
    """把 expr 里的自由符号用 symtab 代入，返回 (新表达式, 未解析符号集, 用到的定义)。

        最多 3 轮（支持 Δ = -4a+5、a = 2 这类链式），有环也必然停下。
    """
    if _sp is None or not symtab:
        return expr, set(getattr(expr, "free_symbols", set()) or set()), {}
    used = {}
    cur = expr
    unresolved = set()
    for _ in range(max_rounds):
        free = set(getattr(cur, "free_symbols", set()) or set())
        if not free:
            break
        sub = {}
        for s in free:
            name = str(s)
            if name not in symtab:
                unresolved.add(name)
                continue
            val, _err = _parse(symtab[name])
            if val is None:
                unresolved.add(name)
                continue
            # 自指定义（a = a + 1）跳过，防无限膨胀
            if s in getattr(val, "free_symbols", set()):
                unresolved.add(name)
                continue
            sub[s] = val
            used[name] = symtab[name]
        if not sub:
            break
        try:
            cur = cur.subs(sub)
        except Exception:  # noqa: BLE001
            break
    free = set(getattr(cur, "free_symbols", set()) or set())
    unresolved |= {str(s) for s in free}
    return cur, unresolved, used


def _parse(text):
    try:
        from utils.sympy_tools import _try_parse
        return _try_parse(str(text))
    except Exception:  # noqa: BLE001
        return None, "解析不可用"


def describe(symtab, limit=6) -> str:
    """给原因字段用的一行摘要。"""
    if not symtab:
        return "空"
    items = sorted(symtab.items())[:limit]
    s = ", ".join("%s=%s" % (k, v) for k, v in items)
    if len(symtab) > limit:
        s += " …(%d 条)" % len(symtab)
    return s
