"""utils/math_eval.py 单元测试（2026-10-01 由 tests/test_calc_tool.py 迁移）。

背景：`agent/calc_tool.py` 的「`<calc>` 计算工具板块」（A 类：协议识别 /
`resolve_all_calcs` 回填 / 裸数值断言检测 / 工具失败审计）已按用户决策整体删除；
其**纯数学求值内核**（B 类：`safe_eval` / `safe_eval_subst` / `to_exact_number`）
原样迁至 `utils/math_eval.py`。本文件覆盖迁走后的 B 类精度与安全契约。

已随板块删除、不再覆盖的项（原 test_calc_tool.py 中的 A 类用例）：
- `resolve_all_calcs` / `extract_calc_blocks`（协议识别与回填）
- `find_naked_numeric_asserts` / `audit_calc_fallbacks`（断言检测 / 失败审计）
- `safe_eval` 的「`<calc>` 被误用为代码沙箱」降级层与 `_CMP_HINT`
  （这些文案专对模型讲 `<calc>` 用法，板块删除后无意义，已一并移除）

覆盖范围（B 类内核）：
- 正常路径（纯表达式精确求值）
- 近似路径（sqrt 非平方 / ln / exp → ≈ 前缀 15 位有效数字）
- 符号/未知函数降级（WARN 前缀，非 ERROR）
- 污染净化（中文/等号尾巴 → 净化重试成功）
- 精确根式 / 符号化简 / 定积分 / 求和 / 隐式乘
- 安全面（拒绝 dunder / 任意代码 / 超长式）
"""

from utils.math_eval import _clean_expr, safe_eval


def test_safe_eval_pure():
    assert safe_eval("comb(50,3) * 2**10") == "20070400"
    assert safe_eval("1/2 + 1/3") == "5/6"
    assert safe_eval("3*7-1") == "20"
    assert safe_eval("fact(5)") == "120"
    assert safe_eval("floor(7/2)") == "3"
    assert safe_eval("ceil(7/2)") == "4"
    assert safe_eval("min(3, 5, 2)") == "2"
    assert safe_eval("max(3, 5, 2)") == "5"
    assert safe_eval("sqrt(16)") == "4"          # 完全平方 → 精确
    assert safe_eval("sqrt(4/9)") == "2/3"       # 分数完全平方 → 精确


def test_safe_eval_approx():
    # 无理/超越 → ≈ 近似（15 位有效数字），不可当精确结论
    assert safe_eval("sqrt(15)").startswith("≈ ")
    assert safe_eval("ln(2)").startswith("≈ ")
    assert safe_eval("exp(1)").startswith("≈ ")
    assert safe_eval("2*sqrt(15)+1").startswith("≈ ")
    assert safe_eval("(187/240)*sqrt(15)").startswith("≈ ")
    assert safe_eval("log(10)").startswith("≈ ")


def test_safe_eval_symbolic_now_computes():
    # 符号变量 → SymPy 精确化简（不是 WARN 断链）
    assert "x + 1" in safe_eval("x+1")
    assert safe_eval("(x-1)*(x+1)") == "x**2 - 1"
    assert safe_eval("k*(1-k)") == "-k**2 + k"
    assert "1/(n + 1)" in safe_eval("1/(n+1)")
    assert safe_eval("2*x+3*x") == "5*x"
    # 符号整除（//）语义歧义 → 仍 WARN 引导数值点自检
    assert safe_eval("(k-1)*(l-1)//2").startswith("WARN:")
    # 未知函数（sin/cos…）→ 仍 WARN（工具能力外，列出可用函数）
    assert safe_eval("sin(2)").startswith("WARN:")
    assert "可用" in safe_eval("sin(2)")


def test_safe_eval_sqrt_surd_exact():
    # sqrt 可开方化简 → 精确根式（不是 ≈ 近似丢失结构）
    assert safe_eval("sqrt(45)") == "3*sqrt(5)"
    assert safe_eval("sqrt(50)") == "5*sqrt(2)"
    assert safe_eval("sqrt(45)+sqrt(20)") == "5*sqrt(5)"
    assert safe_eval("sqrt(2)*sqrt(8)") == "4"
    assert safe_eval("sqrt(2025)") == "45"
    # 无平方因子 → 维持 ≈ 近似（原契约）
    assert safe_eval("sqrt(15)").startswith("≈ ")
    assert safe_eval("2*sqrt(15)+1").startswith("≈ ")
    assert safe_eval("(187/240)*sqrt(15)").startswith("≈ ")


def test_safe_eval_integral_protocol():
    # integral(f, x[, a, b]) 符号/定积分（SymPy）
    assert safe_eval("integral(1/x, x)") == "log(x)"
    assert "n + 1)/(n + 1)" in safe_eval("integral((1-x)**n, x)")
    assert "n + 1)/(n + 1)" in safe_eval("integral((1-x)^n, x)")   # ^ 幂兼容
    assert safe_eval("integral(2*x, x)") == "x**2"
    assert safe_eval("integral(2*x, x, 0, 3)") == "9"
    # G9 超时护栏：大幂定积分（sympy 实测 6.3s）超 3s 护栏 → 降级 WARN，
    # 不占评测预算；小幂定积分照常精确给出（能力契约不变）
    assert safe_eval("integral((1-x)**20, x, 0, 1)") == "1/21"
    _big = safe_eval("integral((1-x)**2024, x, 0, 1)")
    assert _big == "1/2025" or _big.startswith("WARN:")
    assert safe_eval("integral(sqrt(x), x, 1, 4)") == "14/3"
    assert safe_eval("integral(x**2 + 1, x, 0, 2)") == "14/3"


def test_safe_eval_symbolic_security():
    # 符号分支安全面：无引号/下划线/方括号 → dunder/调用链不可达
    assert safe_eval("().__class__").startswith(("WARN:", "ERROR:"))
    assert safe_eval("x.__class__").startswith(("WARN:", "ERROR:"))
    assert safe_eval("__import__('os')").startswith(("WARN:", "ERROR:"))
    # 超长符号式 → 截断/拒绝
    assert safe_eval("x+" * 300 + "x").startswith(("WARN:", "ERROR:"))


def test_safe_eval_errors():
    assert safe_eval("").startswith("ERROR:")             # 空
    assert safe_eval("1/0").startswith("ERROR:")          # 除零
    assert safe_eval("comb(2, 5)").startswith("ERROR:")   # 参数越界
    assert safe_eval("sqrt(-1)").startswith("ERROR:")     # 负数开方


def test_clean_expr_strips_cn_and_tail():
    assert _clean_expr("3/6 + 2/6 + 1/6 约分后") == "3/6+2/6+1/6"
    assert _clean_expr("3*7-1=20") == "3*7-1"
    assert _clean_expr("1/2，然后 1/3") == "1/21/3"      # 剥中文后残留，无意义但仍安全
    assert _clean_expr("comb(50, 3) × 2") == "comb(50,3)2"  # 全角×被剥，ASCII 语法保留


def test_safe_eval_pow_caret_numeric():
    # ^ 幂记号（提示词声明合法）不再 BitXor ERROR
    assert safe_eval("2^10") == "1024"
    assert safe_eval("2^10+1") == "1025"
    assert safe_eval("1.5^3") == "27/8"
    assert safe_eval("2**10") == "1024"        # ** 写法不受影响（幂等）
    assert safe_eval("x^2") == "x**2"           # 符号分支仍正常


def test_safe_eval_float_literal():
    # 小数写法精确转 Fraction，不再"不支持的常量"
    assert safe_eval("0.5") == "1/2"
    assert safe_eval("0.5 + 1/3") == "5/6"
    assert safe_eval("-0.25") == "-1/4"
    assert safe_eval("1.5^3") == "27/8"
    assert safe_eval("sqrt(0.25)") == "1/2"     # 小数进 sqrt 精确路径


def test_safe_eval_math_constants_approx():
    # G1：pi 常量 → ≈ 数值近似（不再当符号 "pi" 回填）；精确根式保留
    assert safe_eval("pi").startswith("≈ 3.14159")
    assert safe_eval("2*pi").startswith("≈ 6.28318")
    assert safe_eval("pi/2").startswith("≈ 1.5707")
    assert safe_eval("sqrt(45)") == "3*sqrt(5)"   # 精确根式不受影响
    r = safe_eval("x*pi")                          # 含变量 → 符号式保留（可代入）
    assert "x" in r and "pi" in r


def test_safe_eval_implicit_mul():
    # G2：数学隐式乘自动显式化
    assert safe_eval("2(x+1)") == "2*x + 2"
    assert safe_eval("(a+b)(c+d)") == "a*c + a*d + b*c + b*d"
    assert safe_eval("2x+3") == "2*x + 3"
    assert safe_eval("sum(2k,1,5)") == "30"        # 隐式乘与 sum 组合
    assert safe_eval("comb(5,2)") == "10"           # 函数调用不受影响
    # 分母位 1/2x 数学歧义（1/(2x)）→ 不静默改义，ERROR 引导显式写法
    assert safe_eval("1/2x").startswith("ERROR:")
    assert "分式分母含变量" in safe_eval("1/2x")


def test_safe_eval_sum_protocol():
    # G3：求和协议 sum(f,x,a,b) / 省略变量 sum(f,a,b)
    assert safe_eval("sum(k,1,10)") == "55"
    assert safe_eval("sum(k,k,1,n)") == "n**2/2 + n/2"
    assert safe_eval("sum(k^2,1,n)") == "n**3/3 + n**2/2 + n/6"
    assert safe_eval("sum(k,k,1,0)") == "0"
    assert safe_eval("sum(x*y,x,1,3)") == "6*y"


def test_safe_eval_trig_hint():
    # G5：三角 WARN 带替代路径提示（特殊角精确式 / 断言验算）
    r = safe_eval("sin(1)")
    assert r.startswith("WARN:") and "特殊角" in r and "sqrt(2)/2" in r


def test_safe_eval_err_hints():
    # G6/G7：错误文案给可行动替代
    assert "sqrt(10)" in safe_eval("10^0.5")
    assert "除数为零" in safe_eval("1/0")
