from __future__ import annotations
"""
MathPilot SymPy 数学引擎
========================

提供真实符号计算能力 — 化简、求值、微分、积分、方程求解、极限、符号等价判定。
采用显式安全守卫、中文注释、分级降级策略。

核心接口:
- are_expressions_equal(a, b) → bool: 符号等价判定（最常用）
- normalize_with_sympy(expr) → str|None: 表达式标准化
- safe_simplify / eval_expression / compute_derivative / compute_integral / solve_equation / compute_limit

修改影响:
- 修改 are_expressions_equal 签名时需同步检查: agent/verifier.py, agent/orchestrator.py
- 修改安全黑名单 _SYMPY_BLACKLIST 时需确保不误封数学函数
- 被 agent/orchestrator.py (快车道 SymPy 调用) 延迟导入引用
"""

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("MathPilot.SymPyTools")

# ---------------------------------------------------------------------------
# 可选依赖检测
# ---------------------------------------------------------------------------
try:
    import sympy as sp
    _HAS_SYMPY = True
except ImportError:
    _HAS_SYMPY = False
    logger.warning("SymPy 未安装，符号计算将不可用。pip install sympy")


# ===========================================================================
# 安全守卫
# ===========================================================================

_SYMPY_BLACKLIST = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "requests",
    "open", "exec", "eval", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "hasattr",
    "__import__", "__builtins__", "__class__", "__bases__",
    "__subclasses__", "__mro__", "__globals__", "__dict__",
    "__code__", "__closure__", "__func__", "__self__",
    "breakpoint", "help", "license", "copyright", "credits",
    "exit", "quit",
})


def _is_safe_expression(text: str) -> bool:
    """检查表达式是否包含被禁用的危险关键词。"""
    tokens = set(re.findall(r'[a-zA-Z_]\w*', text.lower()))
    dangerous = tokens & _SYMPY_BLACKLIST
    if dangerous:
        logger.warning(f"表达式包含危险关键词: {dangerous}")
        return False
    return True


# ===========================================================================
# LaTeX → SymPy 转换辅助
# ===========================================================================

def _preprocess_latex(expr: str) -> str:
    """将常见 LaTeX 数学符号转换为 SymPy 可识别形式。"""
    expr = expr.strip().replace("$", "")
    # 分数
    expr = re.sub(r'\\frac\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}', r'(\1)/(\2)', expr)
    # 指数
    expr = re.sub(r'\^\s*\{\s*([^}]*)\s*\}', r'**(\1)', expr)
    # 根号
    expr = re.sub(r'\\sqrt\s*\[\s*([^]]*)\s*\]\s*\{\s*([^}]*)\s*\}', r'root(\2, \1)', expr)
    expr = re.sub(r'\\sqrt\s*\{\s*([^}]*)\s*\}', r'sqrt(\1)', expr)
    # 三角函数
    for func in ("sin", "cos", "tan", "cot", "sec", "csc",
                 "arcsin", "arccos", "arctan"):
        expr = expr.replace(f"\\{func}", func)
    # 对数/常数
    expr = expr.replace("\\ln", "log").replace("\\log", "log")
    expr = expr.replace("\\infty", "oo").replace("\\pi", "pi")
    expr = re.sub(r'\\times|\\cdot|\*', "*", expr)
    expr = expr.replace("\\div", "/")
    expr = re.sub(r'\s+', '', expr)
    # 隐式乘法补全
    expr = re.sub(r'(\d)\(', r'\1*(', expr)
    expr = expr.replace("{", "").replace("}", "")
    return expr


def _insert_implicit_mul(s: str) -> str:
    """隐式乘法归一（2026-09-03）：'c(x-1)^2(x+2)(x-4)' 在 SymPy 里解析失败
    （`c(` 当函数调用 / `2(` 报错 / `)(` 语法错）→ 插入 '*'（只插 * 不重复括号，
    lookahead 不消费原括号）：
      幂指数后括号   ^2(x → ^2*(x
      相邻括号       )(x  → )*(x
      右括号后字母   )c → )*c
      常数/变量乘括号 c(x → c*(x（函数名如 sin/cos 除外）
    """
    _MATH_FUNCS = {"sin", "cos", "tan", "arcsin", "arccos", "arctan", "exp",
                   "log", "ln", "sqrt", "abs", "min", "max", "floor", "ceil",
                   "operatorname", "frac", "gcd", "lcm"}
    s = re.sub(r"(\^)(\d+)(?=\()", r"\1\2*", s)
    s = re.sub(r"\)(?=\()", ")*", s)
    s = re.sub(r"\)(?=[A-Za-z])", r")*", s)

    def _var_open(m):
        name = m.group(1)
        if name in _MATH_FUNCS:
            return m.group(0)
        return name + "*"

    s = re.sub(r"([A-Za-z]+)(?=\()", _var_open, s)
    return s


def _try_parse(expr_str: str) -> Tuple[Optional[sp.Expr], str]:
    """尝试将字符串解析为 SymPy 表达式。返回 (表达式, 错误信息)。"""
    if not _HAS_SYMPY:
        return None, "SymPy 未安装"
    if not _is_safe_expression(expr_str):
        return None, "表达式包含危险关键词"
    try:
        processed = _preprocess_latex(expr_str)
        processed = _insert_implicit_mul(processed)
        parsed = sp.sympify(processed, evaluate=False)
        return parsed, ""
    except Exception as e:
        return None, f"解析失败: {str(e)[:120]}"


# ===========================================================================
# 核心计算接口
# ===========================================================================

def safe_simplify(expr_str: str) -> Optional[str]:
    """安全化简表达式，返回 LaTeX 字符串。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        logger.debug(f"safe_simplify: {err}")
        return None
    try:
        result = sp.simplify(parsed)
        return sp.latex(result)
    except Exception:
        return str(result)


def eval_expression(expr_str: str) -> Optional[str]:
    """安全求值算术/数值表达式。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        return None
    try:
        result = sp.N(parsed)
        if result.is_Integer:
            return str(int(result))
        if result.is_Rational:
            return str(result)
        return f"{float(result):.10g}"
    except Exception:
        return None


def compute_derivative(expr_str: str, var: str = "x") -> Optional[str]:
    """计算导数。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        return None
    try:
        v = sp.Symbol(var)
        result = sp.diff(parsed, v)
        return sp.latex(result)
    except Exception:
        return None


def compute_integral(expr_str: str, var: str = "x",
                     lower: Optional[str] = None,
                     upper: Optional[str] = None) -> Optional[str]:
    """计算积分。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        return None
    try:
        v = sp.Symbol(var)
        result = sp.integrate(parsed, v)
        return sp.latex(result)
    except Exception:
        return None


def compute_determinant(matrix_str: str) -> Optional[str]:
    """计算矩阵行列式。"""
    try:
        cleaned = matrix_str.strip()
        if cleaned.startswith("[["):
            matrix_list = eval(cleaned, {"__builtins__": {}}, {})
            mat = sp.Matrix(matrix_list)
        else:
            cleaned = re.sub(r'\\begin\{.*?matrix\}', '', cleaned)
            cleaned = re.sub(r'\\end\{.*?matrix\}', '', cleaned)
            cleaned = cleaned.replace("\\\\", ";").replace("&", ",")
            rows = [row.strip() for row in cleaned.split(";") if row.strip()]
            matrix_list = []
            for row in rows:
                vals = [v.strip() for v in row.split(",") if v.strip()]
                matrix_list.append([sp.sympify(v) for v in vals])
            mat = sp.Matrix(matrix_list)
        result = sp.simplify(mat.det())
        return sp.latex(result)
    except Exception:
        return None


def solve_equation(expr_str: str, var: str = "x") -> Optional[str]:
    """求解方程。"""
    try:
        expr_str = expr_str.strip()
        if "=" in expr_str:
            left, right = expr_str.split("=", 1)
            full_expr = f"({left})-({right})"
        else:
            full_expr = expr_str
        parsed, err = _try_parse(full_expr)
        if parsed is None:
            return None
        v = sp.Symbol(var)
        solutions = sp.solve(parsed, v)
        if not solutions:
            return "无解"
        latex_parts = [sp.latex(sol) for sol in solutions]
        return ", ".join(latex_parts)
    except Exception:
        return None


def compute_limit(expr_str: str, variable: str = "x", point: str = "0") -> Optional[str]:
    """计算极限。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        return None
    try:
        v = sp.Symbol(variable)
        if point in ("oo", "inf"):
            p = sp.oo
        elif point in ("-oo", "-inf"):
            p = -sp.oo
        else:
            p = sp.sympify(point)
        result = sp.limit(parsed, v, p)
        return sp.latex(result)
    except Exception:
        return None


# ===========================================================================
# 符号等价判定（核心升级）
# ===========================================================================

def are_expressions_equal(expr_a: str, expr_b: str) -> bool:
    """判定两个数学表达式是否符号等价。通过 SymPy simplify(a - b) == 0。"""
    if not _HAS_SYMPY:
        return False
    if not expr_a or not expr_b:
        return False
    a, _ = _try_parse(expr_a)
    b, _ = _try_parse(expr_b)
    if a is None or b is None:
        return False
    try:
        diff = sp.simplify(a - b)
        return diff == 0
    except Exception:
        return False


def normalize_with_sympy(expr_str: str) -> Optional[str]:
    """用 SymPy 将表达式标准化。"""
    parsed, err = _try_parse(expr_str)
    if parsed is None:
        return None
    try:
        simplified = sp.simplify(parsed)
        simplified = sp.nsimplify(simplified, rational=True)
        return sp.latex(simplified)
    except Exception:
        return None
