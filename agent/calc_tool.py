"""agent/calc_tool.py —— 确定性精确计算工具（2026-08-31）。

给 Intern-S 提供"不会算错的计算器"：
- 模型在输出中用 <calc>表达式</calc> 标记需要精确计算的环节
- harness 用 Fraction 精确算术 + ast 白名单安全求值（拒绝任意代码执行）
- 结果回填上下文，模型基于精确值继续推理

治 value_wrong（A_base 30 题 10/22 错题 = 完整自信的错误数值，算术错误为主）。
与"给更多定理/候选"的本质区别：**新增能力（不会错的算术），不是扰动输出**。

表达式语言（模型侧约定，写进提示词）：
  - 四则 + - * /（/ 产生精确分数），幂 **，取模 %，整除 //
  - 括号 ( )
  - 函数：fact(n) 阶乘、comb(n,k) 组合数、perm(n,k) 排列数、
          gcd(a,b) 最大公约数、lcm(a,b) 最小公倍数、abs(x)
  - 示例：<calc>comb(50, 3) * 2**10</calc>  →  1960000
  - 示例：<calc>1/2 + 1/3</calc>  →  5/6（精确分数）

安全：ast.parse + 节点白名单，任何未列出的节点/函数直接拒绝并返回错误。
"""

from __future__ import annotations

import ast
import math
import re
from fractions import Fraction

_CALC_RE = re.compile(r"<calc>(.*?)</calc>", re.DOTALL)

# 允许的二元运算符 → (ast 节点类型, Fraction 运算)
_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,          # Fraction / Fraction → 精确分数
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: _safe_pow(a, b),
}

_UNARYOPS = {
    ast.UAdd: lambda a: a,
    ast.USub: lambda a: -a,
}

# 白名单函数：名称 → (实现, 参数个数限制说明)
def _fact(n: Fraction) -> Fraction:
    if n.denominator != 1 or n < 0:
        raise ValueError("fact 仅支持非负整数")
    return Fraction(math.factorial(int(n)))


def _comb(n: Fraction, k: Fraction) -> Fraction:
    if n.denominator != 1 or k.denominator != 1:
        raise ValueError("comb 参数必须为整数")
    nn, kk = int(n), int(k)
    if kk < 0 or kk > nn:
        raise ValueError(f"comb({nn},{kk}) 参数越界")
    return Fraction(math.comb(nn, kk))


def _perm(n: Fraction, k: Fraction) -> Fraction:
    if n.denominator != 1 or k.denominator != 1:
        raise ValueError("perm 参数必须为整数")
    nn, kk = int(n), int(k)
    if kk < 0 or kk > nn:
        raise ValueError(f"perm({nn},{kk}) 参数越界")
    return Fraction(math.perm(nn, kk))


def _gcd(a: Fraction, b: Fraction) -> Fraction:
    if a.denominator != 1 or b.denominator != 1:
        raise ValueError("gcd 仅支持整数")
    return Fraction(math.gcd(int(a), int(b)))


def _lcm(a: Fraction, b: Fraction) -> Fraction:
    if a.denominator != 1 or b.denominator != 1:
        raise ValueError("lcm 仅支持整数")
    return Fraction(a.denominator * b.denominator and
                    abs(int(a) * int(b)) // math.gcd(int(a), int(b)))


_FUNCS = {
    "fact": _fact,
    "comb": _comb,
    "perm": _perm,
    "gcd": _gcd,
    "lcm": _lcm,
    "abs": abs,
    "binomial": _comb,   # 别名（部分模型输出 binomial 而非 comb）
}

_FUNC_ARITY = {
    "fact": 1, "comb": 2, "perm": 2, "gcd": 2, "lcm": 2,
    "abs": 1, "binomial": 2,
}

# 计算结果上限保护：防止 fact(10**9) 之类的爆炸（内存/时间）
_MAX_RESULT_DIGITS = 20000
_MAX_INT_ARG = 10**6


def _safe_pow(a: Fraction, b: Fraction) -> Fraction:
    """幂运算保护：指数为整数；先预估结果位数，超限直接拒绝（不实际计算）。"""
    if b.denominator != 1 or abs(int(b)) > 100000:
        raise ValueError("幂指数必须为 |n|≤100000 的整数")
    e = int(b)
    if a.denominator != 1 and e < 0:
        raise ValueError("分数负指数不支持")
    # 位数预估：整数底数 ≈ len(str(a)) * e；分数取分子（更保守）
    digits = max(len(str(a.numerator)), len(str(a.denominator))) * e
    if digits > _MAX_RESULT_DIGITS:
        raise ValueError("计算结果过大（超过 20000 位）")
    return a ** e


class _Evaluator(ast.NodeVisitor):
    """ast 白名单求值器：任何未识别节点抛 ValueError。"""

    def __init__(self) -> None:
        self._result_digits = 0

    def _guard_digits(self, v: Fraction) -> None:
        self._result_digits = max(self._result_digits, len(str(v.numerator)) + len(str(v.denominator)))
        if self._result_digits > _MAX_RESULT_DIGITS:
            raise ValueError("计算结果过大（超过 20000 位）")

    def visit_Expression(self, node: ast.Expression) -> Fraction:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Fraction:  # noqa: N802
        if isinstance(node.value, int):
            if abs(node.value) > _MAX_INT_ARG:
                raise ValueError("整数字面量过大")
            return Fraction(node.value)
        raise ValueError(f"不支持的常量: {node.value!r}")

    def visit_BinOp(self, node: ast.BinOp) -> Fraction:  # noqa: N802
        op_fn = _BINOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        a = self.visit(node.left)
        b = self.visit(node.right)
        v = op_fn(a, b)
        self._guard_digits(v)
        return v

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Fraction:  # noqa: N802
        op_fn = _UNARYOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return op_fn(self.visit(node.operand))

    def visit_Call(self, node: ast.Call) -> Fraction:  # noqa: N802
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("仅支持白名单函数 fact/comb/perm/gcd/lcm/abs")
        fn = _FUNCS[node.func.id]
        want = _FUNC_ARITY[node.func.id]
        if len(node.args) != want:
            raise ValueError(f"{node.func.id} 需要 {want} 个参数")
        for kw in node.keywords:
            raise ValueError("不支持关键字参数")
        args = [self.visit(a) for a in node.args]
        v = Fraction(fn(*args))
        self._guard_digits(v)
        return v

    def generic_visit(self, node: ast.AST) -> Fraction:  # noqa: N802
        raise ValueError(f"不允许的语法节点: {type(node).__name__}")


# 净化用正则：剥离非 ASCII（中文/全角标点/全角乘除号）与 = 尾巴
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
_TRAIL_TAIL_RE = re.compile(r"[=＝].*$")          # 截断 "3-1=2" 的 = 尾巴
_WS_RE = re.compile(r"\s+")


def _clean_expr(expr: str) -> str:
    """净化被污染的 <calc> 表达式（仅当直接求值失败时调用）。

    剥离中文/全角标点、截断 = 尾巴、压缩空白；**保留 ASCII 全部字符**
    （`*`、`,`、`(` 等都是合法语法，删了会算出错误值）。
    返回净化后表达式；若没有可净化内容返回原串（此时调用方不重试）。
    """
    cleaned = _NON_ASCII_RE.sub("", expr)
    cleaned = _TRAIL_TAIL_RE.sub("", cleaned)
    cleaned = _WS_RE.sub("", cleaned)
    return cleaned


def safe_eval(expr: str) -> str:
    """安全求值 <calc> 表达式，返回精确结果字符串。

    成功 → 结果字符串（如 "1960000" / "5/6" / "1267650600228229401496703205376"）
    失败 → 错误消息（以 ERROR: 开头），由调用方决定如何展示。
    """
    expr = expr.strip()
    if not expr:
        return "ERROR: 空表达式"
    if len(expr) > 500:
        return "ERROR: 表达式过长"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"ERROR: 表达式语法错误（{e.msg}）"
    try:
        v = _Evaluator().visit(tree)
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError) as e:
        return f"ERROR: {e}"
    # 整数直接输出；分数输出 a/b；负数保留
    if v.denominator == 1:
        return str(v.numerator)
    return f"{v.numerator}/{v.denominator}"


def extract_calc_blocks(text: str) -> list[str]:
    """提取文本中所有 <calc>...</calc> 表达式（去空白，按出现顺序）。"""
    return [m.group(1).strip() for m in _CALC_RE.finditer(text)]


def resolve_all_calcs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """扫描文本中的 <calc> 块，全部求值，返回 (回填后的文本, [(表达式, 结果)]).

    回填规则：<calc>expr</calc> → [计算] expr = 结果（保留可读性）。
    若直接求值失败（模型在块里塞了中文/标点/等号），尝试净化后重试一次。
    """
    blocks = extract_calc_blocks(text)
    if not blocks:
        return text, []
    resolved = []
    out = text
    for expr in blocks:
        result = safe_eval(expr)
        shown = expr
        if result.startswith("ERROR:"):
            cleaned = _clean_expr(expr)
            if cleaned and cleaned != expr:
                retry = safe_eval(cleaned)
                if not retry.startswith("ERROR:"):
                    result, shown = retry, cleaned
        resolved.append((shown, result))
        out = out.replace(f"<calc>{expr}</calc>", f"[计算] {shown} = {result}", 1)
    return out, resolved
