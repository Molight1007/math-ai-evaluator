"""agent/calc_tool.py —— 确定性精确计算工具（2026-08-31）。

给 Intern-S 提供"不会算错的计算器"：
- 模型在输出中用 <calc>表达式</calc> 标记需要精确计算的环节
- harness 用 Fraction 精确算术 + ast 白名单安全求值（拒绝任意代码执行）
- 结果回填上下文，模型基于精确值继续推理

治 value_wrong（A_base 30 题 10/22 错题 = 完整自信的错误数值，算术错误为主）。
与"给更多定理/候选"的本质区别：**新增能力（不会错的算术），不是扰动输出**。

表达式语言（模型侧约定，写进提示词）：
  - 四则 + - * /（/ 产生精确分数），幂 **（也兼容数学记号 ^，见下），
    取模 %，整除 //（仅数值表达式；含符号时语义歧义 → 不支持）
  - 括号 ( )
  - 函数：fact(n) 阶乘、comb(n,k) 组合数、perm(n,k) 排列数、
          gcd(a,b) 最大公约数、lcm(a,b) 最小公倍数、abs(x)
  - 函数（2026-09-08 扩容）：sqrt(x) 开方（完全平方→精确；
          可开方化简（含平方因子）→ 精确根式如 3*sqrt(5)；否则 ≈ 近似）、
          ln(x)/log(x) 自然对数、exp(x)、floor(x)/ceil(x) 向下/上取整、
          min(a,b,...)/max(a,b,...)
  - 函数（2026-09-08 二次扩容·符号计算）：integral(f, x) 不定积分、
          integral(f, x, a, b) 定积分；f 可为符号表达式
          （例：integral((1-x)**n, x) → -(1 - x)**(n + 1)/(n + 1)）
  - 符号变量（x/n/k/a…）与多项式/根式/含根号表达式 → SymPy 精确化简，
    不再是断链（治 comb-024 符号积分、geo-068 开方化简等 6 道工具断链错题）
  - 示例：<calc>comb(50, 3) * 2**10</calc>  →  1960000
  - 示例：<calc>1/2 + 1/3</calc>  →  5/6（精确分数）
  - 示例：<calc>sqrt(15)</calc>  →  ≈ 3.87298334620742（无平方因子，15 位近似）
  - 示例：<calc>sqrt(45)</calc>  →  3*sqrt(5)（可开方化简 → 精确根式）
  - 示例：<calc>(x-1)*(x+1)</calc>  →  x**2 - 1（符号多项式 → 精确展开）
  - 示例：<calc>floor(7/2)</calc>  →  3（精确）

降级解析（2026-09-13，实证驱动）：模型常把 <calc> 当"代码沙箱/验证块"写
（多行、name = expr 赋值、print(...) 包装、# 注释、比较式）——旧行为一律
ERROR，实测 133 次"多行/代码"拒收。现在遇到这类块**先尽力提取**可求值的
那个数学表达式再求值（如 <calc>x = 10\nx*2</calc> → 20），顺序累积的赋值可
被后续行引用；**多目标赋值 `a, b, c = 1, 2, 3`（2026-09-13 补）**同样逐个
累积进变量环境（左右个数须相等，左名须为纯标识符，否则拒绝）；纯赋值块
（单/多目标一视同仁）无独立取值行时**回填末条赋值的值**（如 `a = 7` +
`b = a//2+2` → 5）；比较式（19 < 20）明确降级 WARN，不硬算；全提不出才回落
原 ERROR 引导。安全面不变：只把提取出的文本喂给既有白名单求值核心，**绝不
eval 任意 Python**（无 import/属性/下标/函数定义，变量取值只收纯数学字符）。

结果形态（2026-09-08 两轮扩容后）：
  - 精确值（整数 / 分数 / 精确根式如 3*sqrt(5)）——可直接信任
  - 符号化简式（含变量，如 1/(n + 1)、x**2 - 1）——SymPy 化简的恒等式，
    可用于核对符号推导；含变量者如要落地成数值，代入具体值再 <calc> 自检
  - "≈ x.xxx" —— 含无理/超越函数且无法开方化简（sqrt 无平方因子、ln、
    log、exp）的近似值，只能核对量级/接近性，**不能当作精确结论**
  - "WARN: ..." —— 仍能力外（未知函数 sin/cos 等、含符号的整除/取模、
    表达式过长、SymPy 化简失败）。**不是错误消息**：告诉模型该步未经工具
    确认——必须①代入具体数值用 <calc> 自检、②核对与题目条件的符号一致性，
    或③把代数断言写成 Lean example 交本地编译器验证后再继续，
    禁止带着未确认的符号式硬算（geo-068 断链后硬算 202→817 漂移的教训）。

实现注：符号/根式化简走本地 SymPy（requirements 已有 sympy>=1.12；
import 失败/化简失败 → 回落旧行为 WARN 或 ≈，绝不阻断）。安全：表达式
先过字符集白名单（无引号/下划线/中文 → sympify 无 RCE 面）+ 幂 ^ 仅在本
符号分支内转 **；数值表达式不经过符号分支。

安全：ast.parse + 节点白名单，任何未列出的节点/函数拒绝；符号变量一律
不允许进入求值（返回 WARN 而非 ERROR，语义是"能力外"不是"写错了"）。
"""

from __future__ import annotations

import ast
import math
import os
import re
import threading
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


def _floor(fr: Fraction) -> Fraction:
    return Fraction(math.floor(fr))


def _ceil(fr: Fraction) -> Fraction:
    return Fraction(math.ceil(fr))


def _min(*args: Fraction) -> Fraction:
    return min(args)


def _max(*args: Fraction) -> Fraction:
    return max(args)


def _sqrt_exact(fr: Fraction) -> Fraction | None:
    """完全平方开方 → 精确 Fraction；否则 None（需走近似路径）。"""
    if fr < 0:
        raise ValueError("sqrt 参数不能为负")
    n, d = fr.numerator, fr.denominator
    rn, rd = math.isqrt(n), math.isqrt(d)
    if rn * rn == n and rd * rd == d:
        return Fraction(rn, rd)
    return None


def _square_part(n: int) -> int:
    """n 的最大平方因子部分（√n = √(s·b) 中的 s）。无 → 1。

    上限保护：n > 4e10 时不判定（视为无因子，走 ≈ 近似兜底），
    防 fact/comb 巨值把试除循环拖死（中学题 sqrt 参数远小于此）。
    """
    if n <= 1:
        return 1
    lim = math.isqrt(n)
    if lim > 200000:
        return 1
    best, p = 1, 2
    while p <= lim:
        p2 = p * p
        if n % p2 == 0:
            best *= p2
            n //= p2
            lim = math.isqrt(n)
        else:
            p = p + 1 if p == 2 else p + 2   # 2,3,5,7…（跳过偶数）
    return best


def _has_square_factor(fr: Fraction) -> bool:
    """sqrt(fr) 是否能开方化简（分子或分母含 >1 的平方因子）。"""
    for x in (fr.numerator, fr.denominator):
        if x > 1 and _square_part(x) > 1:
            return True
    return False


def _sqrt(fr: Fraction) -> Fraction:
    """精确路径的 sqrt：完全平方 → 精确；可提平方因子 → _SqrtSurd（走精确
    根式路径）；否则 _NeedsApprox（走 float 近似路径）。"""
    v = _sqrt_exact(fr)
    if v is not None:
        return v
    if _has_square_factor(fr):
        raise _SqrtSurd(f"sqrt({fr}) 含平方因子，可开方化简")
    raise _NeedsApprox(f"sqrt({fr}) 非完全平方")


def _ln(fr: Fraction) -> Fraction:
    raise _NeedsApprox(f"ln({fr}) 为超越数")


def _exp(fr: Fraction) -> Fraction:
    raise _NeedsApprox(f"exp({fr}) 为超越数")


# 精确路径函数表（2026-09-08 扩容）
_FUNCS = {
    "fact": _fact,
    "comb": _comb,
    "perm": _perm,
    "gcd": _gcd,
    "lcm": _lcm,
    "abs": abs,
    "binomial": _comb,   # 别名（部分模型输出 binomial 而非 comb）
    "sqrt": _sqrt,
    "floor": _floor,
    "ceil": _ceil,
    "min": _min,
    "max": _max,
    # 以下仅在 <calc> 里出现 ln/log/exp 时注册：精确路径直接抛
    # _NeedsApprox（由 safe_eval 捕获后切换 float 近似路径求值），
    # 避免"不支持函数"误伤——它们不是断链，是能力标注为近似。
    "ln": _ln,
    "log": _ln,          # 数学书写中 log 默认自然对数（提示词已注明）
    "exp": _exp,
}

# 变参函数（min/max 接受 ≥1 个参数）
_VARARGS_FUNCS = {"min", "max"}

_FUNC_ARITY = {
    "fact": 1, "comb": 2, "perm": 2, "gcd": 2, "lcm": 2,
    "abs": 1, "binomial": 2,
    "sqrt": 1, "floor": 1, "ceil": 1,
    "min": -1, "max": -1,      # -1 = 变参（≥1）
    "ln": 1, "log": 1, "exp": 1,
}

# 计算结果上限保护：防止 fact(10**9) 之类的爆炸（内存/时间）
_MAX_RESULT_DIGITS = 20000
_MAX_INT_ARG = 10**6


class _NeedsApprox(Exception):
    """表达式含无理/超越函数（sqrt 无平方因子 / ln / log / exp），需切 float 近似路径。"""


class _SqrtSurd(Exception):
    """sqrt 参数含平方因子（√45 → 3√5），需切 SymPy 精确根式路径。"""


class _SymbolicError(Exception):
    """表达式含符号变量（Name 节点），计算器仅支持数值表达式。"""


class _UnsupportedFuncError(Exception):
    """调用白名单之外的函数（sin/cos/…），工具能力外。"""


def _safe_pow(a: Fraction, b: Fraction) -> Fraction:
    """幂运算保护：指数为整数；先预估结果位数，超限直接拒绝（不实际计算）。"""
    if b.denominator != 1 or abs(int(b)) > 100000:
        # 2026-09-09 G6：小数/分数指数给替代路径（10^0.5 → sqrt(10)）
        raise ValueError(
            "幂指数必须为 |n|≤100000 的整数；小数/分数指数请用 sqrt 或根式"
            "（如 10^0.5 → sqrt(10)）")
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
        if isinstance(node.value, float):
            # 2026-09-08 提交前审核修复：<calc>0.5</calc> 是常见小数写法，
            # 旧行为直接拒 → 计算悬空。十进制字符串精确转 Fraction
            # （0.5→1/2，无二进制误差）；科学计数/非有限拒绝走 ERROR。
            if not math.isfinite(node.value):
                raise ValueError("不支持非有限浮点常量")
            try:
                return Fraction(repr(node.value))
            except (ValueError, ZeroDivisionError) as e:
                raise ValueError(f"不支持的浮点常量: {node.value!r}") from e
        raise ValueError(f"不支持的常量: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> Fraction:  # noqa: N802
        # 2026-09-08：符号变量（x/n/k/a…）→ WARN 降级（工具能力外），
        # 不再是语法 ERROR。调用方据此引导模型走数值点/Lean 断言验证。
        raise _SymbolicError(
            f"含符号变量 {node.id!r}，计算器仅支持数值表达式——"
            "请代入具体数值自检，或把代数断言写成 ```lean example``` "
            "交本地编译器核验，勿把符号式硬算当结论")

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
        if not isinstance(node.func, ast.Name):
            raise ValueError("仅支持白名单函数调用")
        fname = node.func.id
        if fname not in _FUNCS:
            # 2026-09-09 G5：未知函数（sin/cos/tan 等常见越界）→ WARN 降级，
            # 文案给"为什么不可算 + 替代路径"（不再只列函数名）
            _tri_hint = ("。三角/反三角/双曲无通用精确值：特殊角请写精确式"
                         "（如 sin(pi/6) 直接给 1/2、cos(pi/4) 给 sqrt(2)/2），"
                         "一般角请用 <check> 或 lean example 断言交编译器验算，"
                         "勿把心算近似当精确结论") if fname in (
                             "sin", "cos", "tan", "cot", "sec", "csc",
                             "asin", "acos", "atan", "sinh", "cosh", "tanh") else ""
            raise _UnsupportedFuncError(
                f"不支持函数 {fname}()；可用: "
                + "/".join(sorted(_FUNCS)) + _tri_hint)
        fn = _FUNCS[fname]
        want = _FUNC_ARITY[fname]
        if want == -1:
            if len(node.args) < 1:
                raise ValueError(f"{fname} 至少需要 1 个参数")
        elif len(node.args) != want:
            raise ValueError(f"{fname} 需要 {want} 个参数")
        for kw in node.keywords:
            raise ValueError("不支持关键字参数")
        args = [self.visit(a) for a in node.args]
        v = Fraction(fn(*args))
        self._guard_digits(v)
        return v

    def generic_visit(self, node: ast.AST) -> Fraction:  # noqa: N802
        raise ValueError(f"不允许的语法节点: {type(node).__name__}")


# ============================================================
# float 近似求值器（2026-09-08）：表达式含 sqrt 非平方 / ln / log / exp 时
# 走此路径。输出 15 位有效数字并带 ≈ 前缀，模型不可当精确结论用。
# ============================================================

_FLOAT_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: math.pow(a, b),
}


def _f_int(f: float, what: str) -> int:
    if not math.isfinite(f) or not f.is_integer():
        raise ValueError(f"{what} 参数必须为整数")
    return int(f)


def _f_fact(f: float) -> float:
    n = _f_int(f, "fact")
    if n < 0 or n > 100000:
        raise ValueError("fact 参数越界")
    return float(math.factorial(n))


def _f_comb(fa: float, fb: float) -> float:
    a, b = _f_int(fa, "comb"), _f_int(fb, "comb")
    if b < 0 or b > a:
        raise ValueError(f"comb({a},{b}) 参数越界")
    return float(math.comb(a, b))


def _f_perm(fa: float, fb: float) -> float:
    a, b = _f_int(fa, "perm"), _f_int(fb, "perm")
    if b < 0 or b > a:
        raise ValueError(f"perm({a},{b}) 参数越界")
    return float(math.perm(a, b))


def _f_gcd(fa: float, fb: float) -> float:
    return float(math.gcd(_f_int(fa, "gcd"), _f_int(fb, "gcd")))


def _f_lcm(fa: float, fb: float) -> float:
    return float(abs(_f_int(fa, "lcm") * _f_int(fb, "lcm"))
                 // math.gcd(_f_int(fa, "lcm"), _f_int(fb, "lcm")))


_FLOAT_FUNCS = {
    "fact": _f_fact, "comb": _f_comb, "perm": _f_perm,
    "gcd": _f_gcd, "lcm": _f_lcm, "binomial": _f_comb,
    "abs": abs,
    "sqrt": math.sqrt,
    "floor": math.floor, "ceil": math.ceil,
    "min": min, "max": max,
    "ln": math.log, "log": math.log, "exp": math.exp,
}


class _FloatEvaluator(ast.NodeVisitor):
    """float 域近似求值器（仅由 safe_eval 在 _NeedsApprox 后调用）。"""

    def __init__(self) -> None:
        self._symbolic = False

    def _guard(self, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("结果过大或未定义（inf/nan）")
        return v

    def visit_Expression(self, node: ast.Expression) -> float:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> float:  # noqa: N802
        if isinstance(node.value, int):
            return float(node.value)
        if isinstance(node.value, float):
            return node.value
        raise ValueError(f"不支持的常量: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> float:  # noqa: N802
        raise _SymbolicError(f"含符号变量 {node.id!r}，计算器仅支持数值表达式")

    def visit_BinOp(self, node: ast.BinOp) -> float:  # noqa: N802
        op_fn = _FLOAT_BINOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        try:
            return self._guard(op_fn(self.visit(node.left), self.visit(node.right)))
        except ZeroDivisionError as e:
            raise ZeroDivisionError("除零") from e
        except OverflowError as e:
            raise ValueError("结果过大") from e

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:  # noqa: N802
        v = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise ValueError(f"不支持的运算符: {type(node.op).__name__}")

    def visit_Call(self, node: ast.Call) -> float:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise ValueError("仅支持白名单函数调用")
        fname = node.func.id
        if fname not in _FLOAT_FUNCS:
            _tri_hint = (
                "。三角/反三角/双曲无通用精确值：特殊角请写精确式（如 sin(pi/6)"
                "= 1/2），一般角请用 <check> 或 lean example 断言验算") if fname in (
                    "sin", "cos", "tan", "asin", "acos", "atan",
                    "sinh", "cosh", "tanh") else ""
            raise _UnsupportedFuncError(
                f"不支持函数 {fname}()；可用: "
                + "/".join(sorted(_FUNCS)) + _tri_hint)
        fn = _FLOAT_FUNCS[fname]
        want = _FUNC_ARITY[fname]
        if want == -1:
            if len(node.args) < 1:
                raise ValueError(f"{fname} 至少需要 1 个参数")
        elif len(node.args) != want:
            raise ValueError(f"{fname} 需要 {want} 个参数")
        for kw in node.keywords:
            raise ValueError("不支持关键字参数")
        args = [self.visit(a) for a in node.args]
        return self._guard(float(fn(*args)))

    def generic_visit(self, node: ast.AST) -> float:  # noqa: N802
        raise ValueError(f"不允许的语法节点: {type(node).__name__}")


# ============================================================
# SymPy 符号/根式计算（2026-09-08 二次扩容）：
# 治"计算工具断链"（comb-024/geo-068 等 6 题）——符号变量、可开方化简
# 的根式、integral() 积分不再是断链点，交本地 SymPy 精确化简/求值。
# 安全：先过字符集白名单（无引号/下划线/中文 → sympify 无 RCE 面），
# ^ 幂记号仅在本分支内转 **（数值表达式不经过这里）；import 失败/化简
# 失败/超长 → 一律返回 None，调用方回落旧行为（WARN 或 ≈），绝不阻断。
# ============================================================

# 允许的数学字符集：数字/单字母符号/运算/括号/逗号/小数点/空白。
# 有意排除：引号 ' "、下划线 _（禁 dunder 属性链）、方括号 []（禁下标）、
# % //（符号下语义歧义）。无引号+无下标+无下划线 → sympify 无代码执行面。
_SYM_SAFE_RE = re.compile(r"^[0-9a-zA-Z*/().,\-+ ]+$")
_INTEGRAL_CALL_RE = re.compile(r"\bintegral\s*\(", re.IGNORECASE)
# 2026-09-09 G3：求和协议 sum(f, x, a, b)（SymPy summation；对齐 integral 语法）
_SUM_CALL_RE = re.compile(r"\bsum\s*\(", re.IGNORECASE)
# 2026-09-09 G9：符号分支超时护栏（sympy 极端输入防卡主线程）
_SYM_TIMEOUT_SEC = 3.0
_SYM_EXECUTOR = None
_POW_INT_RE = re.compile(r"\*\*\s*(\d+)")
_SQRT_NUM_RE = re.compile(r"sqrt\(\s*(\d+)(?:\s*/\s*(\d+))?\s*\)")


def _max_int_exponent(expr: str) -> int:
    """表达式里最大的数字幂指数（**N），用于决定是否安全展开。"""
    mx = 0
    for m in _POW_INT_RE.finditer(expr):
        try:
            mx = max(mx, int(m.group(1)))
        except ValueError:
            pass
    return mx


def _expr_has_simplifiable_sqrt(expr: str) -> bool:
    """表达式含可开方化简的 sqrt(数字)（√45 → 3√5 型）。

    只扫纯数字参数的 sqrt（复合参数如 sqrt(2*15) 罕见，覆盖不到时走 ≈）。
    """
    for m in _SQRT_NUM_RE.finditer(expr):
        try:
            num = int(m.group(1))
            den = int(m.group(2)) if m.group(2) else 1
        except ValueError:
            continue
        if den and _has_square_factor(Fraction(num, den)):
            return True
    return False


def _symbolic_eval(expr: str) -> str | None:
    """符号/根式/积分/求和表达式 → SymPy 化简，返回结果串；失败返回 None。

    2026-09-09 G9：外包线程池 + 3s 超时——sympy 对极端输入（深嵌套/病态
    化简）可能秒级卡死，不能占用评测主线程。超时线程仍会跑完（占 1 个池
    worker），卡死极罕见可接受；超时按"化简失败"回落（WARN/≈），不阻断。
    """
    try:
        import concurrent.futures as _cf
    except Exception:  # noqa: BLE001
        return None
    global _SYM_EXECUTOR
    if _SYM_EXECUTOR is None:
        _SYM_EXECUTOR = _cf.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="calc_sym")
    try:
        fut = _SYM_EXECUTOR.submit(_symbolic_eval_core, expr)
        return fut.result(timeout=_SYM_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001  超时/化简失败一律回落，不阻断
        return None


def _symbolic_eval_core(expr: str) -> str | None:
    """符号分支实际执行（见 _symbolic_eval 外层说明）。"""
    if not expr.strip():
        return None
    s = expr.replace("^", "**")                  # 兼容数学幂记号（仅本分支）
    if not _SYM_SAFE_RE.match(s):
        return None
    if "//" in s or "%" in s:                    # 符号整除/取模语义歧义 → 能力外
        return None
    try:
        import sympy as sp              # noqa: PLC0415  # 延迟导入（requirements 已含）
    except ImportError:
        return None
    try:
        res = None
        # ---- 求和协议 sum(f, x, a, b)（G3，对齐 integral 拆参）----
        msum = _SUM_CALL_RE.search(s)
        if msum and _INTEGRAL_CALL_RE.search(s) is None:
            iargs = _split_call_args(s, msum.end() - 1)
            # 支持显式变量 sum(f, x, a, b) 与省略变量 sum(f, a, b)（自动取被加式
            # 唯一自由符号；多符号歧义 → None 回落 WARN）
            if iargs is None or len(iargs) not in (3, 4):
                return None
            f_expr = sp.sympify(iargs[0])
            if len(iargs) == 4:
                var = sp.Symbol(iargs[1].strip())
                a, b = sp.sympify(iargs[2]), sp.sympify(iargs[3])
            else:
                _fs = list(f_expr.free_symbols)
                if len(_fs) != 1:
                    return None
                var = _fs[0]
                a, b = sp.sympify(iargs[1]), sp.sympify(iargs[2])
            res = sp.summation(f_expr, (var, a, b))
            if isinstance(res, sp.Sum):          # 求不出闭合和 → 能力外
                return None
        else:
            # ---- 积分协议 integral(f, x[, a, b])：手动拆参（支持定积分）----
            m = _INTEGRAL_CALL_RE.search(s)
            if m:
                iargs = _split_call_args(s, m.end() - 1)   # 平衡括号取参
                if iargs is None or len(iargs) not in (2, 4):
                    return None
                f_expr = sp.sympify(iargs[0])
                var = sp.Symbol(iargs[1].strip())
                if len(iargs) == 2:
                    res = sp.integrate(f_expr, var)
                else:
                    a, b = sp.sympify(iargs[2]), sp.sympify(iargs[3])
                    res = sp.integrate(f_expr, (var, a, b))
                if isinstance(res, sp.Integral):   # 仍积分不出 → 能力外
                    return None
            else:
                # ---- 常规符号/根式化简 ----
                parsed = sp.sympify(s)
                if _max_int_exponent(expr) > 50:
                    # 大指数（如 (1-x)**2024）：simplify 会走慢路径（秒级）→ 跳过，
                    # sympify 本身已规范化；此时也不展开（防爆炸）。
                    res = parsed
                else:
                    res = sp.simplify(parsed)
                    # 数字幂指数 ≤12 时补一次展开（simplify 常保持积形式 k*(1-k)，
                    # expand 给出展开式 -k**2+k——更有"运算发生"，且避免 X=X 被当空转；
                    # 展开后**不再 simplify**：simplify 会把展开式重新因子化回去）
                    if _max_int_exponent(expr) <= 12:
                        _exp = sp.expand(res)
                        if len(sp.sstr(_exp)) <= 8 * len(expr) + 200:  # 防爆炸兜底
                            res = _exp
        if res is None:
            return None
        # Piecewise 可能带外层系数（如 -Piecewise(...)）→ 递归取主分支
        res = res.replace(
            lambda e: isinstance(e, sp.Piecewise),
            lambda pw: pw.args[0][0])
        out = sp.sstr(res)
        if len(out) > 2000 or "\n" in out:
            return None
        # 2026-09-09 G1：纯数学常量（pi/e 等 NumberSymbol、无自由变量）→ 给 15 位
        # 数值近似（≈ 前缀），防 `pi` 被当普通符号结果回填（模型误以为"π=pi"已算
        # 出）。精确根式（3*sqrt(5)）不含 NumberSymbol → 不受影响，仍返回精确式。
        try:
            if not getattr(res, "free_symbols", None) and res.atoms(sp.NumberSymbol):
                return f"≈ {sp.N(res, 15)}"
        except Exception:  # noqa: BLE001
            pass
        return out
    except Exception:                               # 化简失败一律回落，不阻断
        return None


def _split_call_args(s: str, open_idx: int) -> list[str] | None:
    """从 '(' 位置开始按**顶层逗号**切分调用参数（含嵌套括号）。

    返回参数串列表（strip 后）；括号不闭合/含嵌套 integral → None。
    """
    depth, start, parts = 0, open_idx + 1, []
    i = open_idx
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                parts.append(s[start:i])
                return [p.strip() for p in parts]
        elif c == "," and depth == 1:
            parts.append(s[start:i])
            start = i + 1
        i += 1
    return None                                   # 未闭合


# ============================================================
# 2026-09-09 G2：数学隐式乘预处理（2(x+1) / (a+b)(c+d) / 2x → 显式 *）
# ============================================================
_IMPLICIT_DIGIT_LPAREN = re.compile(r"(?<=[0-9])\(")       # 2(  → 2*(
_IMPLICIT_RPAREN_TOKEN = re.compile(r"\)(?=[0-9a-zA-Z(])")  # )( )x )2 → )*…
_IMPLICIT_DIGIT_LETTER = re.compile(r"([0-9])([a-zA-Z])")   # 2x → 2*x（分母位除外）


def _prev_nonspace_char(s: str, pos: int) -> str:
    j = pos - 1
    while j >= 0 and s[j].isspace():
        j -= 1
    return s[j] if j >= 0 else ""


def _preprocess_implicit_mul(s: str) -> str:
    """把确定无歧义的数学隐式乘转为显式 `*`（ast 解析前调用，safe_eval 内）。

    规则（宁漏勿误，绝不静默改义）：
      - `2(x+1)` → `2*(x+1)`（数字紧跟左括号）
      - `(a+b)(c+d)` / `)x` / `)2` → `(a+b)*(c+d)`（右括号后接数字/字母/左括号）
      - `2x+1` → `2*x+1`（数字紧跟字母；**分母位跳过**：`1/2x` 数学上有
        1/(2x) 歧义，保留原样 → 解析失败走 WARN 引导，不静默按 (1/2)*x 算错）
    函数名后括号（sin(…)/sqrt(…)/comb(…)/integral(…)）与 `^`/`**` 后括号不转。
    """
    s = _IMPLICIT_DIGIT_LPAREN.sub("*(", s)
    s = _IMPLICIT_RPAREN_TOKEN.sub(")*", s)
    s = _IMPLICIT_DIGIT_LETTER.sub(
        lambda m: m.group(1)
        + ("*" if _prev_nonspace_char(m.string, m.start()) != "/" else "")
        + m.group(2),
        s)
    return s


def _err_msg(e: Exception) -> str:
    """统一错误文案：除零专名，其余用异常消息原文。"""
    if isinstance(e, ZeroDivisionError):
        return "除数为零（表达式非法，检查分母）"
    return str(e) or type(e).__name__


# ============================================================
# 2026-09-09 P3 冒烟实证修复：<calc> 被误用为"代码执行器"
# （def 函数/多语句赋值/simplify() 命令 整段塞入）→ 专门检测与引导
# ============================================================
_CODE_KW_RE = re.compile(
    r"\b(def|while|if|for|return|print|import|lambda|and|or|not"
    r"|True|False|None)\b")
_SIMPLIFY_CMD_RE = re.compile(r"\bsimplify\s*\(")


def _looks_like_code(expr: str) -> str | None:
    """检测"伪代码/多语句/命令式"误用，返回专门引导文案（非代码返回 None）。

    命中形态：多行/分号多语句、def/while/if 等 Python 关键字、simplify()
    等命令式调用——<calc> 是"单个表达式求值器"，不是 CAS 命令面板。
    """
    if "\n" in expr or ";" in expr:
        return ("<calc> 只支持**单个数学表达式**（单行），不支持代码/多语句/"
                "换行/赋值（如 a=7 后接多行）。请只写一个要算的表达式，"
                "如 <calc>a//2+2</calc>。")
    if _CODE_KW_RE.search(expr):
        return ("<calc> 只支持单个数学表达式，不支持 Python 代码（def/while/"
                "if/for/return 等关键字）。请把要算的量写成单个表达式。")
    if _SIMPLIFY_CMD_RE.search(expr):
        return ("<calc> 没有 simplify() 命令：直接给要化简的表达式本身"
                "（如 <calc>x+1</calc> 系统会自动化简回填），不要包 simplify()。")
    return None


# ============================================================
# 2026-09-13 降级解析：模型把 <calc> 当"代码沙箱/验证块"（多行、赋值、
# print 包装、# 注释、比较式）时，不再一律 ERROR —— 先尽力提取**可求值的
# 数学表达式**再求值，全部失败才回落原 ERROR 文案。
# 实证来源：official112-016 v5 的 4 个 <calc> 全是 Python（n = 20 /
# x = [1]*10 + [-1]*10 / S = sum(x) / print(...)）、010 是多行
# `# 验证…` + from sympy import…、016 v7 是 19 < 20 比较式。
# 安全边界**不变**：提取出的文本只喂给既有白名单求值核心（_eval_core），
# 绝不 eval 任意 Python；赋值取值只能是白名单表达式的求值结果。
# ============================================================
_DEGRADE_LINE_SPLIT_RE = re.compile(r"[\n;]+")
# 赋值 `name = <expr>`；比较式（== / <= …）先由 _DEGRADE_CMP_RE 剔除，不会误配
_DEGRADE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*=\s*(\S.*?)\s*$")
_DEGRADE_PRINT_RE = re.compile(r"^\s*print\s*\(", re.IGNORECASE)
# 比较/判断式：19 < 20、x == 3、k != 0 —— 工具只算数值，不解命题（不硬算）
_DEGRADE_CMP_RE = re.compile(r"[<>]=?|==|!=")
_DEGRADE_MAX_LINES = 30          # 行数上限（防超长块把逐行求值拖成秒级）
_DEGRADE_MAX_LINE_LEN = 200      # 单行长度上限（同上）
_DEGRADE_ENV_MAX_LEN = 40        # 可入变量环境的取值串长上限
# 裸标识符行（`S` / `y`）：单独一个变量名不是"运算"。只有当它确实是本块内
# 赋值过的变量（有值可代入）才可当取值行；否则是悬空符号 → 跳过（否则会把
# 未定义变量名本身回填成"结果"，如 <calc>y = [1,2][0]\nprint(y)</calc> → y）。
_DEGRADE_BARE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_CMP_HINT = ("<calc> 只能算**数值表达式**，不能做比较/判断（如 19 < 20、x == 3）。"
             "比较请直接写出结论；要留数值依据，就把两侧算式分别用 <calc> 算出来。")


def _degrade_subst(text: str, env: dict) -> str:
    """降级路径的变量代入：把 env 里的 `name` 按标识符边界替换为 `(取值)`。

    语义 = 模型自己那段"代码"里的变量替换（忠实代入，不做内建名特殊化）：
    `pi = 3` 后 `pi*2` → 6（而不是按数学常量 π 算）。env 取值入表前已过
    `_SYM_SAFE_RE`（无引号/下划线/方括号）且长度受限 —— 替换结果仍要过
    _eval_core 的白名单求值，越界的字符/函数照旧拒绝。
    """
    for name, val in env.items():
        pat = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
        text = re.sub(pat, f"({val})", text)
    return text


def _degrade_eval_line(text: str, env: dict) -> str | None:
    """求值单行（先代入 env）；WARN/ERROR 一律视为"该行不可用" → None。"""
    if not text or len(text) > _DEGRADE_MAX_LINE_LEN:
        return None
    res = _eval_core(_degrade_subst(text, env))
    if res.startswith(("WARN:", "ERROR:")):
        return None
    return res


def _degrade_env_value(rhs: str, env: dict) -> str | None:
    """求值一条赋值右端 → 可入变量环境的取值串；不可用返回 None。

    单目标（`name = expr`）与多目标（`a, b = e1, e2`）赋值**共用**此累积逻辑：
    求值失败或取值含引号/下划线/方括号（_SYM_SAFE_RE 不许）→ None（不收）。
    """
    val = _degrade_eval_line(rhs, env)
    if val is None or len(val) > _DEGRADE_ENV_MAX_LEN:
        return None
    if not _SYM_SAFE_RE.match(val):
        return None                              # 只收无引号/下划线/方括号的取值
    return val


# 多目标赋值（tuple unpacking）`a, b, c = 1, 2, 3`（2026-09-13 实证修复）：
# official112-010 一轮 8 条 calc_fallback 中 6 条是此形态（p1, q1, r1, s1 = 1, 0, -1, 0），
# 旧降级解析只认单目标 `name = expr`，整块提不出值 → 一律 ERROR。现按左名/右值
# **逐个求值累积**进同一变量环境。安全边界不变：左侧每个目标必须是**纯标识符**
# （字母开头 + 字母数字）——含下标 `a[0]`、属性 `o.x`、dunder/调用 `__import__(…)`
# 者一律返回 None（整条不累积，宁多拒绝）；左右个数必须相等，否则拒绝。
_TUPLE_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def _split_top_commas(s: str) -> list[str]:
    """按**顶层逗号**切分（括号 [[({]] 内的逗号不切）；不校验括号配对。"""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(s):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == "," and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return parts


def _find_top_level_eq(s: str) -> int:
    """首个顶层 `=` 的下标（跳过 ==/!=/<=/>= 里的 =）；无则 -1。"""
    depth = 0
    for i, c in enumerate(s):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == "=" and depth == 0:
            if i + 1 < len(s) and s[i + 1] == "=":
                continue                         # ==
            if i > 0 and s[i - 1] in "=!<>":
                continue                         # != / <= / >=
            return i
    return -1


def _degrade_parse_tuple_assign(s: str) -> tuple[list[str], list[str]] | None:
    """解析多目标赋值 `a, b, c = 1, 2, 3` → ([左名], [右值串])；否则 None。

    单目标赋值（左无逗号）返回 None，仍走既有 _DEGRADE_ASSIGN_RE；左名含
    下标/属性/非标识符、或左右个数不等、或右值有空项 → 一律 None（拒绝）。
    """
    eq = _find_top_level_eq(s)
    if eq < 0:
        return None
    lhs, rhs = s[:eq], s[eq + 1:]
    if "," not in lhs:
        return None
    names = [p.strip() for p in _split_top_commas(lhs)]
    if len(names) < 2 or not all(_TUPLE_TARGET_RE.match(n) for n in names):
        return None                              # a[0] / o.x / __import__(…) → 拒
    vals = [p.strip() for p in _split_top_commas(rhs)]
    if len(vals) != len(names) or any(not v for v in vals):
        return None                              # 个数不等/空项 → 拒
    return names, vals


def _degraded_eval(expr: str) -> str | None:
    """多行/代码/赋值块 → 尽力提取单个可求值表达式；提不出返回 None（回落 ERROR）。

    规则（宁多拒绝、绝不放宽执行面）：
      1. 按 `\\n` / `;` 拆行，去掉 `#` 注释与空白行（`#` 不是合法数学字符）；
      2. 先**顺序**累积赋值数值进本次求值环境（取值只收无引号/下划线/方括号的
         求值结果，供后续行引用）：单目标 `name = <expr>` 与多目标
         `a, b, c = 1, 2, 3`（左名纯标识符、左右个数相等、右值逐个对当前
         环境求值）**共用** `_degrade_env_value` 累积；含比较符的行不求值；
      3. 再**从后往前**找第一条「可求值的表达式行」（剥 `print(...)` 外壳，跳过
         赋值行/多目标赋值行/比较行/代码关键字行；裸变量名只在本块内赋过值时才
         认），求值成功即返回该值（末行通常是答案）；
      4. 若第 3 步无表达式行，回填**末条赋值的值**——单目标 `a = 7` + `b = a//2+2`
         与多目标 `a, b = 1, 2` 块**一视同仁**（实测模型大量写"赋值 + 末条引用"
         形态，语义须一致，不给模型"有时能用有时不能用"的不确定性）；一条赋值
         都没累积成功 → None（调用方回落原 ERROR 文案）。
    """
    lines = []
    for raw in _DEGRADE_LINE_SPLIT_RE.split(expr):
        s = raw.split("#", 1)[0].strip()      # 去（行尾）注释
        if s:
            lines.append(s)
    if not lines:
        return None
    lines = lines[:_DEGRADE_MAX_LINES]
    # ---- 第 1 步：顺序累积赋值（为后续行提供数值环境）----
    env: dict = {}
    last_assign: str | None = None
    for s in lines:
        if _DEGRADE_CMP_RE.search(s):
            continue                          # 比较/判断式：不求值（不硬算）
        tup = _degrade_parse_tuple_assign(s)
        if tup is not None:
            names, rhs_list = tup
            # 右端统一对**本条赋值前的环境快照**求值（右端可引用前文已累积变量，
            # 但同条内互不可见 —— 与 Python "先算右端再赋值" 语义一致）。
            vals = [_degrade_env_value(r, env) for r in rhs_list]
            if any(v is None for v in vals):
                continue                      # 任一右值不可用 → 整条不累积
            for n, v in zip(names, vals):
                env[n] = v
            last_assign = vals[-1]
            continue
        m = _DEGRADE_ASSIGN_RE.match(s)
        if not m:
            continue
        name, rhs = m.group(1), m.group(2)
        val = _degrade_env_value(rhs, env)
        if val is None:
            continue
        env[name] = val
        last_assign = val
    # ---- 第 2 步：从后往前找第一个可求值的表达式行 ----
    for s in reversed(lines):
        if (_DEGRADE_CMP_RE.search(s) or _DEGRADE_ASSIGN_RE.match(s)
                or _degrade_parse_tuple_assign(s) is not None):
            continue                          # 比较行 / 赋值行（非"取值行"）
        body = s
        if _DEGRADE_PRINT_RE.match(s):
            args = _split_call_args(s, s.index("("))
            if not args or len(args) != 1:
                continue                      # print 多参/括号不闭合 → 不可用
            body = args[0]
        if _CODE_KW_RE.search(body):
            continue                          # def/if/for/return/import/lambda…
        if _DEGRADE_BARE_NAME_RE.match(body) and body not in env:
            continue                          # 悬空变量名：不是运算，别回声变量名
        val = _degrade_eval_line(body, env)
        if val is not None:
            return val
    # ---- 第 3 步：纯赋值块（无独立取值行）→ 回填末条赋值的值 ----
    # 单目标与多目标赋值块一视同仁；一条都没累积成功时 last_assign 仍为 None。
    return last_assign


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
    """安全求值 <calc> 表达式，返回精确/符号/近似/WARN 多态结果字符串。

    成功（精确）→ "1960000" / "5/6" / "3*sqrt(5)"（精确根式）/
                  "x**2 - 1" / "1/(n + 1)"（SymPy 符号化简式）
    近似 → "≈ 3.14159265358979"（sqrt 无平方因子 / ln / log / exp，15 位）
    能力外 → "WARN: ..."（未知函数 / **比较式** / 含符号的整除取模 / SymPy
             化简失败——**不是错误**，是降级标记，调用方应引导数值点自检 /
             Lean 断言）
    失败 → "ERROR: ..."（语法/数值非法，调用方走净化重试）
    降级 → 多行/赋值/print 包装的"代码块"先尽力提取可求值表达式
            （_degraded_eval，2026-09-13），提到即返回其值；全提不出才回落
            ERROR 引导文案
    """
    expr = expr.strip()
    if not expr:
        return "ERROR: 空表达式"
    if len(expr) > 500:
        return "ERROR: 表达式过长"
    # G-code（2026-09-09 P3 冒烟实证）：模型把 Python 代码/多语句/simplify()
    # 命令塞进 <calc> → 先尝试降级提取（2026-09-13），提不出才给专门引导文案
    _code_hint = _looks_like_code(expr)
    if _code_hint:
        _degraded = _degraded_eval(expr)
        if _degraded is not None:
            return _degraded
        return f"ERROR: {_code_hint}"
    # 比较/判断式（19 < 20 / x == 3）：工具只算数值、不解命题 → 明确降级为 WARN。
    # 原行为是"不允许的语法节点: Compare"（语法错文案），模型会误以为格式写错
    # 而反复改格式；这里给"工具不算比较、该怎么办"的可行动引导。
    if _DEGRADE_CMP_RE.search(expr):
        return f"WARN: {_CMP_HINT}"
    return _eval_core(expr)


def _eval_core(expr: str) -> str:
    """白名单求值核心（safe_eval 与降级路径共用）：单个数学表达式 → 结果串。

    前置合法性判定（空/超长/代码误用/比较式）在 safe_eval；本函数只做
    `^`→`**` 归一 → 隐式乘预处理 → ast 白名单求值 → 精确 / 符号根式 / float
    近似。**不 eval 任意 Python**：未列出的 ast 节点一律拒绝（参数安全边界）。
    """
    # 2026-09-08 提交前审核修复：Python ast 中 ^ 是 BitXor，精确/近似求值器
    # 均不识 → `<calc>2^10</calc>`（提示词声明的幂记号写法）永久 ERROR、净化
    # 重试也救不回（_clean_expr 不转 ^）。统一在解析前 ^→**（对已含 ** 的串
    # 幂等；_symbolic_eval 内自带 ^→** 亦幂等）。数学语境 ^ 仅作幂记号，无误伤。
    expr = expr.replace("^", "**")
    # 2026-09-09 G2：数学隐式乘（2(x+1)/2x/(a+b)(c+d)）→ 显式 *，再解析
    expr = _preprocess_implicit_mul(expr)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        # 语法错对模型要给可行动引导（G6 文案口径：运算符显式、分式分母带变量写法）
        return (f"ERROR: 表达式语法错误（{e.msg}）。"
                "请检查：运算符需显式（如 2*x 勿写 2x）、括号配对、"
                "分式分母含变量请写 1/(2*x) 形式。")
    # 1) 精确路径（纯数值；sqrt 完全平方→精确）
    try:
        v = _Evaluator().visit(tree)
        if v.denominator == 1:
            return str(v.numerator)
        return f"{v.numerator}/{v.denominator}"
    except _SqrtSurd:
        # 1a) sqrt 可开方化简（√45 → 3*sqrt(5)）：SymPy 精确根式，失败回落 ≈
        _sym = _symbolic_eval(expr)
        if _sym is not None:
            return _sym
    except _NeedsApprox:
        # 1b) 表达式里含其他可开方化简的 sqrt（√15+√20 型）→ 根式化简优先
        if _expr_has_simplifiable_sqrt(expr):
            _sym = _symbolic_eval(expr)
            if _sym is not None:
                return _sym
        # 1c) 纯无理无平方因子 → 走 float 近似（下方第 2 段）
    except _SymbolicError as e:
        # 1d) 含符号变量 → SymPy 符号化简（comb-024 1/(n+1)、整式恒等）；
        #     失败才退回 WARN 引导（原行为）
        _sym = _symbolic_eval(expr)
        if _sym is not None:
            return _sym
        return f"WARN: {e}"
    except _UnsupportedFuncError as e:
        # integral()/sum() 是符号分支协议函数（精确求值器不识）→ 先试 SymPy
        if _INTEGRAL_CALL_RE.search(expr) or _SUM_CALL_RE.search(expr):
            _sym = _symbolic_eval(expr)
            if _sym is not None:
                return _sym
        return f"WARN: {e}"
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError) as e:
        return f"ERROR: {_err_msg(e)}"
    # 2) 近似路径（仅含超越/无理函数时到达；符号/未知函数同样 WARN）
    try:
        v = _FloatEvaluator().visit(tree)
    except _SymbolicError as e:
        return f"WARN: {e}"
    except _UnsupportedFuncError as e:
        return f"WARN: {e}"
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError) as e:
        return f"ERROR: {_err_msg(e)}"
    return f"≈ {v:.15g}"


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


# ============================================================
# 2026-09-13（用户要求「把数值给大模型，但不让它计算危险数值」·方案 A）
# 把**上文已回填**的 [计算] 精确值汇总出来，供 revise / 自改进 / 子目标 step /
# merge 四条"上下文回灌"路径**前置注入** —— 模型不必自己在长文本里翻找那些
# [计算] 行（更不必重算）。与 resolve_all_calcs 同源：只解析它写出的形态。
# ------------------------------------------------------------
# 形态：`[计算] <expr> = <result>`。三个实证要点：
#   ① **`[计算]` 不一定在行首**（真实存档 166 条里有 13 条 = 7.8% 是句中写法，
#      如「最终答案: [计算] 230 = 1073741824」；且 `_CALC_GUIDE` 的节奏示范
#      本身就是句中写法）⇒ 按**行内出现位置**定位，取标记**之后**的内容为块体。
#   ② 表达式**可能跨行**——模型写多行 <calc> 时降级解析的回填就是跨行的：
#      `<calc>x = 5\nprint(x*2)</calc>` → `[计算] \nx = 5\nprint(x*2) = 10`。
#      续行判据见 `_is_calc_continuation`（非空、不以 `[计算]` 开头、全为
#      数学/代码字符、不含连续两个英文单词）。
#   ③ 切分取块内**最后一个** `=`（回填拼接顺序恒为 `shown = result`，
#      且 `result` 必在块尾行、不含 `=`）。
# 散文（中/英）只用于**截断**，绝不因此丢弃值本身：
#   - 散文在值**之后** → 在散文起点截断后再切分（例：`= 19600，即所求。`）；
#   - 散文在值**之前** → 退回未截断块体切分，只把表达式里的散文前缀剪掉
#     （例：`[计算] The answer is comb(50,3) = 19600`）。
_CALC_MARK = "[计算]"
_CALC_CONT_MAX_LINES = 12      # 块体最多续行数（防跨段吞并）
# 算式/代码可出现的字符（中文、中文标点等散文字符一律不算续行）；
# 含 ≈ 与根式/常量记号 —— 多行 <calc> 的**末行**常是 `sqrt(x) = ≈ 3.87…`，
# 漏了 ≈ 会把该行判成散文、整块只剩前面的赋值（真值丢失）。
_CALC_LINE_CHARS_RE = re.compile(
    r"^[0-9A-Za-z_+\-*/%^=(),.\[\]{}<>!'\" \t≈√π∞°]*$")
# 连续两个英文单词（≥2 字母）→ 判定为自然语言散文，不是算式
_CALC_PROSE_RE = re.compile(r"[A-Za-z]{2,}[ \t]+[A-Za-z]{2,}")
# 中文散文/中文标点（含全角括号、全角逗号等）——值后粘的中文尾巴在此截断
_CALC_CJK_RE = re.compile(
    r"[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]")
# 表达式尾部"纯算式"片段（散文前缀剪枝用；空匹配 = 剪不出算式）
_CALC_MATH_TAIL_RE = re.compile(r"[0-9A-Za-z_+\-*/%^(),.\[\]{}<>!'\"|]*$")
# 结果必须"像值"：不含引号/冒号/分号/反斜杠等 JSON·代码标点 ——
# 防把 `[计算] 0 = 0"}, "x": 1` 这类**非模型解答**文本里的伪条目注入提示词
# （注入错值比漏一条更糟：它会被当成"系统已算出的精确值"）。
_CALC_VALUE_RE = re.compile(r"^[-0-9A-Za-z_+\-*/%^().\[\]{}!,<>= \t≈√π∞°]*$")


def _is_calc_continuation(line: str) -> bool:
    """判断某行是否为 `[计算]` 多行回填块的**续行**（算式/代码行）。"""
    s = line.strip()
    if not s or s.startswith(_CALC_MARK):
        return False
    if not _CALC_LINE_CHARS_RE.match(s):
        return False
    if _CALC_PROSE_RE.search(s):
        return False
    return True


def _norm_calc_expr(expr: str) -> str:
    """把（可能跨行的）表达式压成单行，行间用 `; ` 连接（供注入提示词）。"""
    return "; ".join(ln.strip() for ln in expr.splitlines() if ln.strip())


def _calc_prose_cut(text: str) -> int:
    """返回 `text` 中**第一处散文起点**下标（中/英散文取更早者；无则 len）。"""
    cut = len(text)
    m = _CALC_PROSE_RE.search(text)
    if m:
        cut = min(cut, m.start())
    m = _CALC_CJK_RE.search(text)
    if m:
        cut = min(cut, m.start())
    return cut


def _extract_calc_item(body: str):
    """从 `[计算]` 之后的块体 `body` 抽出 "<expr> = <result>"（抽不出返回 None）。

    散文只截断、不丢值：先按"散文起点截断"重切；若散文在值之前（截断后已无
    `=`）则退回原块体切分，并把表达式里的散文前缀剪掉。
    """
    cut = _calc_prose_cut(body)
    head = body[:cut] if cut < len(body) else body
    pos = head.rfind("=")
    if pos <= 0:                      # 散文在值之前 → 退回未截断块体切分
        head, pos = body, body.rfind("=")
    if pos <= 0:
        return None
    expr = _norm_calc_expr(head[:pos])
    if _CALC_CJK_RE.search(expr) or _CALC_PROSE_RE.search(expr):
        # 表达式混进散文（前缀）→ 只保留尾部纯算式片段；值本身不丢
        # （先 strip：`head[:pos]` 尾随空格会让"尾部算式"匹配落空）
        expr = _CALC_MATH_TAIL_RE.search(head[:pos].strip()).group(0).strip()
    result = head[pos + 1:].strip()
    result = result[:_calc_prose_cut(result)].strip()    # 值尾残余散文再截一次
    result = result.rstrip(",;:")
    if (not expr or not result
            or not _CALC_VALUE_RE.match(result)
            or result.startswith(("WARN", "ERROR"))):
        return None
    return f"{expr} = {result}"


def collect_calc_results(text: str, limit: int = 20) -> list:
    """汇总文本中所有 `[计算] <expr> = <result>` 条目，返回 "<expr> = <result>" 列表。

    - `[计算]` **行首/句中均可**（真实存档 7.8% 为句中形态）；
    - **去重**（同一算式重复回填只留首次）、**保持出现顺序**；
    - 最多返回 `limit`（默认 20）条，防注入提示词时膨胀；
    - 跳过非值回填（结果以 WARN/ERROR 开头，即工具能力外/求值失败）；
    - result 可为符号式（如 n**2/2 + n/2，呈跨行回填形态）或含空格 ⇒ 整条吃下不截断。

    2026-09-13 方案 A：写清楚"系统已经算好了"（而非让模型自己找/自己算）。
    """
    if not text:
        return []
    lines = text.splitlines()
    out, seen = [], set()
    i, n = 0, len(lines)
    offset = 0                       # 同一行内多个 [计算] 的扫描起点
    while i < n and len(out) < limit:
        line = lines[i]
        p = line.find(_CALC_MARK, offset)
        if p < 0:
            i += 1
            offset = 0
            continue
        start = p + len(_CALC_MARK)
        # 同一行的下一个 [计算] 起新条目 → 本块体不跨过它
        seg = line[start:]
        nxt = seg.find(_CALC_MARK)
        if nxt >= 0:
            seg = seg[:nxt]
        body = [seg]
        j = i + 1
        while (j < n and j - i <= _CALC_CONT_MAX_LINES
               and _is_calc_continuation(lines[j])):
            body.append(lines[j])
            j += 1
        item = _extract_calc_item("\n".join(body))
        if item and item not in seen:
            seen.add(item)
            out.append(item)
        if line.find(_CALC_MARK, start) >= 0:
            offset = start            # 本行还有标记 → 原地续扫
        else:
            i, offset = j, 0          # 否则跳过已并入的续行
    return out


# ============================================================
# 2026-09-12 计算分档：只对"易错算子"强制走工具（用户要求）
# ------------------------------------------------------------
# 用户原话：「不是一定要让大模型不计算，而是让它易错的根号、组合数、log
# 什么的用工具计算。像加减乘除什么的可以计算。」
# 于是把数值计算分成两档：
#   ① 高危档（必须工具）—— 大模型心算容易"答案漂移"**且工具真算得出**的算子：
#      开方/根式 sqrt、对数 ln/log、指数 exp 与自然常数 e、组合数 comb/C、
#      排列 perm/P、阶乘 !、幂运算 ** ^、取模 mod、求和/积分 sum/integral、
#      圆周率 pi。这些算子结果位数多、心算易错且模型无法自证，必须交
#      calc_tool 精确求值。
#   ② 低危档（可自算）—— 整数/小数的加、减、乘、除、括号与比较。
#      这类运算模型几乎不出错，强制走工具只增加重问开销（实测代价高）。
# 落点：find_naked_numeric_asserts 默认只回收高危档的裸断言行。
#
# 2026-09-13 能力对齐（用户要求）：**能力外算子必须从强制档摘除** —— 原清单里
# 的 sin/cos/tan 等三角（含反三角/双曲）、求积 prod/product、开立方 cbrt/root、
# 带底对数 log2/log10，经实测 calc_tool 一律返回 WARN「不支持函数」（工具只认
# _FUNCS/_FLOAT_FUNCS + integral/sum 协议），强制重问只会空转（诊断里 26×
# "不支持 sin()"、8× tan()、若干 prod/cbrt 即此故）。它们改为"能力外"处理：
# 特殊角写精确式、其余交 <check>/Lean example 验算（见 solver._CALC_GUIDE 第 2 条）。
# 保留 choose/ncr/npr/factorial：其**运算**工具支持（comb/perm/fact/binomial），
# 只是记法别名不同 —— 仍属"该走工具"的心算高危项，提示词已要求写成规范记法。
# ============================================================
_HARD_FUNC_NAMES = (
    "sqrt",                                       # 开方/根式（cbrt/root 能力外）
    "ln", "log", "exp",                           # 对数/指数（log2/log10 能力外）
    "comb", "perm", "fact", "factorial",          # 计数
    "binomial", "choose", "ncr", "npr",
    "gcd", "lcm",                                 # 数论
    "sum", "integral",                            # 求和/积分（prod/product 能力外）
)
# 支持带下标的写法：log_2(8)、log_{10}(100)、sqrt[3](8)
_HARD_CALL_RE = re.compile(
    r"\b(%s)(?:_\{?[A-Za-z0-9]+\}?)?\s*[\(\{\[]"
    % "|".join(_HARD_FUNC_NAMES), re.I)
_HARD_LATEX_RE = re.compile(
    r"\\(?:sqrt|log|ln|exp|binom|choose|sum|int|lim|pi|omega)",
    re.I)
_HARD_FUNC_WORD_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(_HARD_FUNC_NAMES), re.I)
_LATEX_CMD_ANY_RE = re.compile(r"\\[A-Za-z]+")
# 幂运算（`**` 与数学记号 `^`）的识别/分档统一由下方的 _POW_OP_RE + _pow_class
# 处理：旧实现用"数字底数的幂"正则（_HARD_POW_NUM_RE）与"凡 `**` 必高危"两套
# 简单判据，2026-09-13 起改为按规模分档（小幂放行，见 _has_hard_pow）。
_HARD_FACT_RE = re.compile(r"(?<!=)!(?!=)")
_HARD_MOD_RE = re.compile(r"\b(?:mod|bmod)\b", re.I)
_HARD_PI_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:pi|\u03c0)(?![A-Za-z0-9_])", re.I)
_HARD_E_RE = re.compile(r"(?<![A-Za-z0-9_.])e(?![A-Za-z0-9_])")
_HARD_E_POW_RE = re.compile(r"(?<![A-Za-z0-9_.])e\s*(?:\*\*|\^)", re.I)
# 单字母组合/排列记号 C(n,k)、P(n,k)、A(n,k)：要求括号内以数字开头，
# 避免把普通函数调用（C(x)）误判 —— 例题 C(50,3)、P(5,2)。
_CPA_CALL_RE = re.compile(r"\b[CPA]\s*(?:\(\s*[-+]?\d|_\{?\s*\d)")

# ---- 数值取模 `a % b`（2026-09-13 补：取模属高危档，原判据只认 mod/bmod 漏了 %）----
# ⚠ `%` 在 LaTeX 里是**注释符**、转义写 `\%` 才是百分号，故两层防误判：
#   ① 负向后顾 `(?<!\\)` —— `50\%` 的 `%` 前是反斜杠 → 不算取模；
#   ② 要求 `%` 右侧紧跟**操作数**（数字/字母，可带正负号），左侧紧邻操作数
#      （数字/字母/右括号/右花括号）—— 把 "增长 20% 到 30%"、行首 `% 注释`
#      这类文本百分号/注释排除在外。
_HARD_PCT_MOD_RE = re.compile(
    r"(?<!\\)(?<=[0-9A-Za-z_)\]}])[ \t]*%[ \t]*(?=[-+]?[0-9A-Za-z])")
# 中文散文里的 `%` 一律按百分号处理（宁漏勿误）—— 与既有护栏
# `f("故 2024 % 17 = 1") == []`（整行含中文 → 不打断推导）一致。
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

# ---- 幂运算规模分档（2026-09-13 用户要求）----
# 用户原话：「像加减乘除、平方这些基本计算都可以（让模型自己）算。但组合数、
# 根号、太大的次方，就留给工具计算。」⇒ 幂不再"凡幂必高危"，改按规模分档：
#   低危（可自算）⇔ 底数是**字面数字** 且 指数是**非负整数字面量**
#                 且 指数 ≤ CALC_POW_HARD_EXP 且 结果整数位数 ≤ CALC_POW_HARD_DIGITS
#   例：7**2 = 49（指数 2、2 位）、2**10 = 1024（指数 10、4 位）⇒ 低危；
#       2**100（指数 100 > 20）、10**20（21 位 > 6）⇒ 高危。
# 「指数」与「结果位数」是**且**关系（10**20 指数虽 ≤20，但结果是 21 位大数 ⇒
# 高危）—— 单看指数会把 10**20 这类"低位底数、高位结果"放进来。
# 符号底数/符号指数（x**2、2**n、(1-x)**k）不是心算数值、无算错风险 ⇒ 放行。
# 阈值可被环境变量覆盖：CALC_POW_HARD_EXP（默认 20）、CALC_POW_HARD_DIGITS（默认 6）。
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


CALC_POW_HARD_EXP = _env_int("CALC_POW_HARD_EXP", 20)
CALC_POW_HARD_DIGITS = _env_int("CALC_POW_HARD_DIGITS", 6)
_POW_OP_RE = re.compile(r"\*\*|\^")
# 幂运算符**之后**紧跟的指数记号：10 / {10} / (10) / 2.5 / n / k1
_POW_EXP_RE = re.compile(
    r"\s*[\(\{]?\s*([-+]?\d+(?:\.\d+)?|[A-Za-z_]\w*)\s*[\)\}]?")
# 幂运算符**之前**紧邻的底数：字面数字 `7`，或 `(1.05)` 这类括号字面数字
_POW_NUM_BASE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*$")
_POW_PAREN_BASE_RE = re.compile(r"\(\s*([-+]?\d+(?:\.\d+)?)\s*\)\s*$")


def _pow_est_digits(base: float, exp: int):
    """估算 base**exp 的**整数位数**；无法可靠估算（结果 <1）→ None（按高危）。"""
    if base <= 0:
        return None
    if exp == 0 or base == 1:
        return 1
    v = exp * math.log10(base)
    if v < 0:
        return None
    return int(v) + 1


def _pow_class(text: str, m) -> str:
    """单次幂运算分档 → 'symbolic'（符号式）/ 'small'（可自算小幂）/ 'big'（高危）。"""
    head = text[:m.start()]
    bm = _POW_NUM_BASE_RE.search(head) or _POW_PAREN_BASE_RE.search(head)
    if bm is None:
        return "symbolic"              # 底数非字面数字（x**2 / (1-x)**k）→ 符号式
    em = _POW_EXP_RE.match(text, m.end())
    if em is None:
        return "big"                   # 读不到指数 → 保守算高危
    etok = em.group(1)
    if not re.fullmatch(r"[-+]?\d+", etok):
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", etok):
            return "big"               # 非整数指数（2**2.5）→ 保守算高危
        return "symbolic"              # 符号指数（2**n / x**k）→ 符号式
    base, exp = float(bm.group(1)), int(etok)
    if exp < 0 or base < 1 or exp > CALC_POW_HARD_EXP:
        return "big"
    digits = _pow_est_digits(base, exp)
    return "small" if (digits is not None and digits <= CALC_POW_HARD_DIGITS) else "big"


def _has_hard_pow(text: str, strict: bool) -> bool:
    """文本中是否出现"大规模幂"（需工具）。

    **两个档位共用同一套规模判据**（2026-09-13 用户裁决："平方这类基本计算
    允许模型自算"）：数字底数的小幂（7**2、2**10=1024）⇒ 都不算高危。
    strict 档保留的**唯一**差异（防代数推导误报，不动）：
      - 符号底数的 `^`（LaTeX 上标 x^{2}）不算高危（两档一致）；
      - 符号底数的 `**`（x**2、x**n）在 strict 档仍算高危（保守，维持原行为）；
      - 符号指数（2**n）同属符号式。
    """
    for m in _POW_OP_RE.finditer(text):
        cls = _pow_class(text, m)
        if cls == "big":
            return True
        if cls == "symbolic" and strict and m.group(0) == "**":
            return True                # strict 档对符号底数 ** 继续保守
    return False


def hard_op_hits(text: str, strict: bool = False) -> list:
    """返回文本中命中的"高危算子"记号列表（去重保序）；空 = 纯四则，可自算。

    幂判据两档**统一**（`_has_hard_pow`）：数字底数按规模分档 —— 平方/小次方
    （7**2、2**10=1024）低危可自算，太大的次方（2**100、10**20）才算高危。
    strict=False（默认，表达式档 —— "这个算式是否必须交工具"）：
    符号底/指数（x**2、2**n）也放行（符号式无算错风险）；裸 `e` 算高危。
    strict=True（整段解答/裸断言档）：仅保留两条防代数推导误报的护栏 ——
    裸 `^`（LaTeX 符号上标 x^{2}）与裸 `e` 不算高危；符号底数的 `**`（x**2）
    仍算高危（维持旧保守行为）。
    """
    if not text:
        return []
    hits = []
    for m in _HARD_CALL_RE.finditer(text):
        hits.append(m.group(1).lower())
    if _HARD_LATEX_RE.search(text):
        hits.append("latex")
    if _has_hard_pow(text, strict):
        hits.append("幂运算")
    if _CPA_CALL_RE.search(text):
        hits.append("组合/排列")
    if "\u221a" in text:
        hits.append("根号")
    if _HARD_FACT_RE.search(text):
        hits.append("阶乘")
    if _HARD_MOD_RE.search(text) or (_HARD_PCT_MOD_RE.search(text)
                                     and not _CJK_RE.search(text)):
        hits.append("取模")
    if _HARD_PI_RE.search(text):
        hits.append("pi")
    if _HARD_E_POW_RE.search(text):
        hits.append("自然常数e")
    elif not strict and _HARD_E_RE.search(text):
        hits.append("自然常数e")
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def needs_tool_calc(expr: str) -> bool:
    """该表达式是否属"必须交工具计算"的高危档（纯四则 → False）。"""
    return bool(hard_op_hits(expr))


def has_hard_op(text: str) -> bool:
    """整段文本是否出现过高危算子（供答案自洽核验判断"是否需要工具来源"）。

    纯四则解答 → False，其数值答案允许模型自算（用户 2026-09-12 要求）。
    """
    return bool(hard_op_hits(text, strict=True))


# 指标变量是**绑定变量**的函数（sum/prod/integral 的第一参数）：整段调用
# 挖掉，避免把 `sum(k,1,10)` 的 k 误判为自由变量（那是纯计算，不是方程）。
_BINDING_FUNCS = ("sum", "prod", "product", "integral")
_BINDING_CALL_RE = re.compile(
    r"\b(?:%s)\s*\((?:[^()]|\([^()]*\))*\)" % "|".join(_BINDING_FUNCS), re.I)


def _free_vars(expr: str) -> str:
    """挖掉算子名/常数/绑定变量后剩余的字母；非空 ⇒ 含自由变量（方程/结论式）。

    `x^2 = 4`、`n = comb(m,2)`、`e = 5` 这类是方程/赋值而非心算数值，必须放行；
    `2^10 = 1024`、`C(50,3) = 19600`、`1024 mod 100 = 24` 无剩余字母 ⇒ 高危心算。
    """
    t = _BINDING_CALL_RE.sub(" ", expr or "")
    # 先挖"完整调用记号"（sqrt( / log_2( / log_{10}( …）：`\b` 对带下标写法
    # （下划线是 \w）不成立，故必须先于单词挖除
    t = _HARD_CALL_RE.sub(" ", t)
    t = _HARD_FUNC_WORD_RE.sub(" ", t)
    t = _LATEX_CMD_ANY_RE.sub(" ", t)
    t = _HARD_PI_RE.sub(" ", t)
    # 自然常数 e：**只有「e 紧跟幂运算」才算常数**（e^2 / e**2）。
    # 裸 e（`e = 5`、`e + 1 = 6`）是变量赋值/方程，必须放行 ——
    # 2026-09-12 修复：原实现无条件挖掉裸 e，导致 `e = 5` 被判为"高危心算"。
    t = re.sub(r"(?<![A-Za-z0-9_.])e(?=\s*(?:\*\*|\^))", " ", t, flags=re.I)
    # 取模关键字（mod/bmod）是**算子**不是变量，必须挖除 ——
    # 2026-09-12 修复：漏挖导致 `1024 mod 100 = 24` 因残留 "mod" 被判为
    # "含自由变量"而漏检（取模属高危档，漏检＝心算无人拦）。
    t = _HARD_MOD_RE.sub(" ", t)
    t = _CPA_CALL_RE.sub(" ", t)
    return "".join(re.findall(r"[A-Za-z]", t))


_NUMERIC_RHS_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\d+\s*/\s*\d+)$")
_APPROX_LHS_CHARS = "\u2248~\u2243\u2245="


def _is_numeric_rhs(r: str) -> bool:
    """RHS 是否为"写死的纯数值"（整数/小数/科学计数/简单分数，可带 ≈ 前缀）。"""
    if r is None:
        return False
    s = str(r).strip().lstrip(_APPROX_LHS_CHARS).strip().replace(",", "")
    s = s.rstrip("\u3002.")
    return bool(_NUMERIC_RHS_RE.match(s))


# ============================================================
# 2026-09-09 P1：计算纪律辅助（心算痕迹检测 + 工具失败审计）
# ============================================================
_NON_MATH_TOKEN = re.compile(r"[A-Za-z\u4e00-\u9fff]")


def find_naked_numeric_asserts(text: str, hard_only: bool = True) -> list:
    """返回文本中的"裸数值断言"行（心算/自算痕迹，未走 <calc> 工具）。

    hard_only=True（默认，2026-09-12 用户要求）—— **只回收高危算子的裸断言**：
      行形如 `<含 sqrt/log/组合数/幂/… 的算式> = <纯数值>`，即模型自己算出了
      一个易错运算的结果 → 必须打回改用 <calc>。
      纯四则行（`25*4 = 100`、`1/2+1/3 = 5/6`）不再算裸断言 —— 用户明确
      允许模型自算加减乘除，强制走工具只会徒增重问开销。
      幂同样按规模分档（2026-09-13 用户裁决）：小幂（`2^10 = 1024`、`7**2 = 49`）
      允许自算、不再回收；只有大幂（`2**100`）的裸断言才打回。
    hard_only=False —— 恢复旧行为：任何两侧纯数值的 `a = b` 都算裸断言。

    共同约束（宁漏勿误，绝不打断推导）：
      - 行首不是 [计算]/[自算]/<calc>/<check>/```（有工具来源的不算裸）；
      - 整行按 '=' 恰好切成两半，两侧非空且 ≤64 字符；
      - RHS 必须是**写死的纯数值**（可带 ≈ 前缀），否则视为结论式放行；
      - 算式侧含自由变量（x^2 = 4、n = comb(m,2)）→ 方程，放行。
    """
    if not text:
        return []
    out = []
    for ln in str(text).split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith(("[计算]", "[自算]", "<calc>", "<check>", "```",
                         "example", "theorem")):
            continue
        if "=" not in s:
            continue
        parts = [p.strip() for p in s.split("=")]
        if len(parts) != 2:
            continue
        L, R = parts
        if not (len(L) <= 64 and 1 <= len(R) <= 64):
            continue
        if not _is_numeric_rhs(R):
            continue                        # RHS 不是算出的数 → 结论式，放行
        if hard_only:
            if not hard_op_hits(L, strict=True):
                continue                    # 纯四则（加减乘除）→ 允许自算
            if _free_vars(L):
                continue                    # 算式含变量 → 方程，非心算
            if L and L == R:
                continue
            out.append(s)
            continue
        # ---- 旧行为（hard_only=False）：两侧纯数值且无字母/中文即算裸 ----
        l_ok = (L == "" or (re.search(r"\d", L) and not _NON_MATH_TOKEN.search(L)))
        r_ok = (re.search(r"\d", R) and not _NON_MATH_TOKEN.search(R))
        if not (l_ok and r_ok):
            continue
        if L and L == R:
            continue
        out.append(s)
    return out


def audit_calc_fallbacks(resolved: list) -> list:
    """从 resolve_all_calcs 的 resolved 里筛出工具失败项（WARN:/ERROR:）。

    供调用方 record 审计事件 calc_fallback（P1-2 自算降级可观测/留痕）。
    返回 [(expr, result)]，各自截断到可读长度。
    """
    out = []
    for expr, result in resolved or []:
        if result.startswith(("WARN:", "ERROR:")):
            out.append((expr[:90], result[:70]))
    return out


# ============================================================
# 2026-09-10 L1：符号代入求值 + 答案数值化
# ------------------------------------------------------------
# 动机：模型给出的**符号表达式答案**（如 "2*x+y"、"n*(n+1)/2"）此前无法被
# 程序核对——判分器只比字符串，工具也只做数值/化简。补上"把 givens 代入
# expr 求精确值"这一环后，才能把「关系式」与「给定的具体数值」接起来做核验
# （用户 9/10 思路：数值→变量、模型只给关系式、工具负责代入求值）。
# ============================================================
_SUBST_VAR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_SUBST_VAL_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:/\d+)?$")
# 答案数值化：只接受可**精确**判等的形式（整数/小数/分数），
# 近似值（"≈ …"）与符号式（"3*sqrt(5)"、"2*x+y"）一律弃权——宁漏勿误。
_NUM_ONLY_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:/\d+)?$")
_BOXED_PREFIXES = ("\\boxed", "\\fbox")
_ANSWER_FRAC_RE = re.compile(r"\\[dt]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
# 代入求值的超时护栏：每次调用起一个 daemon 线程，join 超时即放弃
# （见 _subst_with_timeout）。已放弃（卡死）线程计数有上限，防无界建线程。
_SUBST_HUNG = 0
_SUBST_HUNG_MAX = 4


def _rename_vars(expr: str, names: list) -> tuple[str, dict]:
    """把表达式里的变量名整体改名为内部安全记号 q0/q1/...。

    为什么必须改名：SymPy 里 `E / I / N / O / S / pi / sin / sqrt ...` 是
    **内建常量或函数**。直接 sympify("E*x") 会把 E 当自然常数 → 代入被静默
    忽略、算出错值（`{"E": 5, "x": 2}` 的 "E*x" 会得 2e 而不是 10）。
    改名为绝不与内建冲突的记号后，代入语义才确定。

    词边界替换：`n` 不会破坏 `n2`（后随数字 → 前瞻失败），故名字顺序无关。
    返回 (改名后的表达式, {原名: 记号})。
    """
    out = expr
    token_of: dict = {}
    used = set(re.findall(r"[A-Za-z0-9]+", expr))
    idx = 0
    for name in names:
        token = f"q{idx}"
        while token in used:
            idx += 1
            token = f"q{idx}"
        used.add(token)
        idx += 1
        pat = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
        out = re.sub(pat, token, out)
        token_of[name] = token
    return out, token_of


def _subst_eval_core(expr: str, pairs: list) -> str:
    """safe_eval_subst 的实际执行体（外层有 3s 超时护栏）。"""
    import sympy as sp                      # noqa: PLC0415  延迟导入
    subs = {}
    for name, val in pairs:
        # 统一转精确有理数："0.5" → 1/2（否则 sympify 出 Float，结果退化成
        # "0.250000000000000" 这种浮点串，违背"精确代入"的初衷）。
        fr = Fraction(val)
        subs[sp.Symbol(name)] = sp.Rational(fr.numerator, fr.denominator)
    parsed = sp.sympify(expr)
    # 表达式里的十进制字面量（如 "x**0.5"）同样转有理数，保持全程精确
    try:
        parsed = sp.nsimplify(parsed, rational=True)
    except Exception:  # noqa: BLE001
        pass
    res = parsed.subs(subs)
    free = getattr(res, "free_symbols", None) or set()
    if free:
        return "WARN: 仍有未代入变量 " + ", ".join(sorted(str(s) for s in free))
    try:
        if res.is_real is False:            # zoo / nan / 复数 → 能力外
            return f"WARN: 代入结果不是实数（{sp.sstr(res)[:30]}）"
    except Exception:  # noqa: BLE001
        pass
    # 1) 精确有理数（含 Fraction 化的整数/小数/分数）
    if getattr(res, "is_rational", False):
        num, den = int(sp.numer(res)), int(sp.denom(res))
        return str(num) if den == 1 else f"{num}/{den}"
    # 2) 含 pi/e 等常量 → 15 位近似（与 _symbolic_eval 口径一致）
    try:
        if res.atoms(sp.NumberSymbol):
            return f"≈ {sp.N(res, 15)}"
    except Exception:  # noqa: BLE001
        pass
    # 3) 精确无理式（如 sqrt(5)、3*sqrt(5)）→ 化简后原样返回
    out = sp.sstr(sp.simplify(res))
    if not out or len(out) > 300 or "\n" in out:
        return f"≈ {sp.N(res, 15)}"
    return out


def safe_eval_subst(expr: str, mapping: dict) -> str:
    """把 mapping 里的变量代入 expr 后求**精确**值（L1 自洽核验内核）。

    - expr 可含变量（"2*x+y"、"n*(n+1)/2"、"length*width"、"x^2-1"）；
      变量名须为「字母开头 + 字母数字」；**空 mapping 也合法**（纯数值算式）；
    - mapping 形如 {"x": 10, "y": "5/6"}（值可为数值/数值串）；非法名忽略；
    - 变量名会先整体改名为内部记号再代入（避免 E/I/N/pi/sin 等 SymPy
      内建名把代入静默吃掉 → 算出错值，见 _rename_vars）；
    - 返回与 safe_eval 同构的结果串：
        "25" / "5/6" / "3*sqrt(5)"（精确）· "≈ 3.14…"（含 pi/e）
        "WARN: …"（仍有未代入变量 / 能力外，**不是错误**）
        "ERROR: …"（语法非法 / 取值非数值）

    安全边界与 _symbolic_eval 一致：先过字符白名单（无引号/下划线/方括号
    → sympify 无代码执行面），再交给 3s 超时线程池，超时/异常一律回落 WARN。
    """
    expr = "" if expr is None else str(expr)
    expr = expr.strip()
    if not expr:
        return "ERROR: 空表达式"
    if len(expr) > 500:
        return "ERROR: 表达式过长"
    s = _preprocess_implicit_mul(expr.replace("^", "**"))
    if "//" in s or "%" in s:
        return "WARN: 符号整除/取模语义歧义，计算器不支持"
    if not _SYM_SAFE_RE.match(s):
        return "WARN: 表达式含非数学字符（仅支持字母/数字/运算/括号）"
    names, vals = [], {}
    if isinstance(mapping, dict):
        for key, val in mapping.items():
            name = str(key).strip()
            if not _SUBST_VAR_RE.match(name):
                continue           # 非法名忽略（真被用到时会成自由符号 → WARN）
            text = str(val).strip()
            if not _SUBST_VAL_RE.match(text):
                return f"ERROR: 变量 {name} 的取值 {text!r} 不是数值"
            if name not in vals:
                names.append(name)
                vals[name] = text
    # 空 mapping 也合法：纯数值算式（如 "1/2+1/3"）直接精确求值；
    # 表达式里仍有未提供取值的符号时，内核的 free_symbols 检查会回落 WARN。
    renamed, token_of = _rename_vars(s, names)
    pairs = [(token_of[n], vals[n]) for n in names]
    return _subst_with_timeout(renamed, pairs)


def _subst_with_timeout(expr: str, pairs: list) -> str:
    """在 **daemon 线程**里跑代入求值并施加 3s 超时（见下方说明）。

    2026-09-10 审计修复（P0/P1）：
    - 原实现用 ThreadPoolExecutor（非 daemon worker）。SymPy 病态输入卡死后，
      worker 永不释放 → 池被堵死，后续调用全部排队超时（能力静默全失）；
      而且"重建池"会遗弃非 daemon 线程，进程退出时 `_python_exit` 会去 join
      它们 → **正常退出被挂死**。
    - 现在改为每次调用起一个 **daemon** 线程：卡死既不堵后续调用，也不阻塞
      退出；已放弃线程数超过上限即整体降级（返回 WARN），避免无界建线程。
    - 异常兜底回到"一律回落 WARN"的契约（原拆分时漏掉了通用 except）。
    """
    global _SUBST_HUNG
    if _SUBST_HUNG >= _SUBST_HUNG_MAX:
        return "WARN: 代入求值已降级（历史超时过多）"
    box: dict = {}

    def _run() -> None:
        try:
            box["v"] = _subst_eval_core(expr, pairs)
        except Exception as exc:  # noqa: BLE001  线程内异常回传，不逃逸
            box["e"] = exc

    th = threading.Thread(target=_run, name="calc_subst", daemon=True)
    th.start()
    th.join(_SYM_TIMEOUT_SEC)
    if th.is_alive():                      # 卡死 → 放弃该线程（daemon，不影响退出）
        _SUBST_HUNG += 1
        return "WARN: 代入求值超时"
    if "e" in box:
        return f"WARN: 代入求值未成功（{type(box['e']).__name__}）"
    return box.get("v") or "WARN: 代入求值无结果"


def to_exact_number(text) -> Fraction | None:
    """答案串 → 精确 Fraction；非纯数值一律返回 None（宁漏勿误）。

    接受：  "25" / "-3" / "5/6" / "0.5" / "\\boxed{25}" / "\\frac{1}{2}" / "$25$"
    拒绝：  含变量（"2*x+y"）、精确根式（"3*sqrt(5)"）、近似（"≈ 3.14"）、
            百分数、带单位或文字的长答案 —— 这些无法**精确**判等。
    """
    if text is None:
        return None
    t = str(text).strip()
    if not t or t.startswith("≈"):
        return None
    t = _ANSWER_FRAC_RE.sub(r"\1/\2", t)
    # 只去首尾空白与 $，**不去内部空白**——否则 "1 2" 会被误读成 12
    t = t.strip().strip("$").strip()
    for prefix in _BOXED_PREFIXES:
        if t.startswith(prefix):
            i = t.find("{")
            if i >= 0 and t.endswith("}"):
                t = t[i + 1:-1]
            break
    t = t.strip()
    # 2026-09-10 修复：残留反斜杠 = 没被上面规则识别的 LaTeX（如无括号的
    # "\dfrac12"）→ 直接弃权。否则剥掉命令后会把 "\dfrac12" 错读成 12。
    if "\\" in t:
        return None
    if not _NUM_ONLY_RE.match(t):
        return None
    try:
        return Fraction(t)
    except Exception:  # noqa: BLE001
        return None
