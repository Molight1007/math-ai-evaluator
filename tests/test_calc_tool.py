"""agent/calc_tool.py 单元测试（2026-09-01 新增净化容错；09-08 扩容三态）。

覆盖：
- 正常路径（纯表达式精确求值）
- 近似路径（sqrt 非平方 / ln / exp → ≈ 前缀 15 位有效数字）
- 符号/未知函数降级（WARN 前缀，非 ERROR——治断链后硬算）
- 污染路径（中文/等号尾巴 → 净化重试）
- 不可净化路径（变量 → WARN，不误伤成错误值）
- 多块混合回填
"""

from agent.calc_tool import safe_eval, extract_calc_blocks, resolve_all_calcs, _clean_expr


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
    # 2026-09-08 二次扩容：符号变量 → SymPy 精确化简（不再是 WARN 断链）
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
    # 2026-09-08 二次扩容：sqrt 可开方化简 → 精确根式（原 ≈ 近似丢失结构）
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
    # 2026-09-08 二次扩容：integral(f, x[, a, b]) 符号/定积分（SymPy）
    assert safe_eval("integral(1/x, x)") == "log(x)"
    assert "n + 1)/(n + 1)" in safe_eval("integral((1-x)**n, x)")
    assert "n + 1)/(n + 1)" in safe_eval("integral((1-x)^n, x)")   # ^ 幂兼容
    assert safe_eval("integral(2*x, x)") == "x**2"
    assert safe_eval("integral(2*x, x, 0, 3)") == "9"
    # 2026-09-09 G9 超时护栏：大幂定积分（sympy 实测 6.3s）超 3s 护栏 → 降级
    # WARN（带引导），不占评测预算；小幂定积分照常精确给出（能力契约不变）
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


def test_resolve_all_calcs_cleanup_retry():
    # 中文污染 → 净化重试成功
    out, resolved = resolve_all_calcs("结果是 <calc>3/6 + 2/6 + 1/6 约分后</calc>")
    assert resolved[0][1] == "1"
    assert "[计算] 3/6+2/6+1/6 = 1" in out
    # 等号尾巴 → 净化重试成功
    out, resolved = resolve_all_calcs("算 <calc>3*7-1=20</calc> 对吧")
    assert resolved[0][1] == "20"
    assert "= 20" in out


def test_resolve_all_calcs_symbolic_computes():
    # 2026-09-08 二次扩容：符号变量回填为精确化简式（不再是 WARN）
    out, resolved = resolve_all_calcs("求 <calc>x+1</calc>")
    assert "x + 1" in resolved[0][1]
    assert "[计算] x+1 = x + 1" in out
    # 中文污染 + 符号 → 净化后仍能符号化简
    out, resolved = resolve_all_calcs("求 <calc>x+1 的值</calc>")
    assert "x + 1" in resolved[0][1]
    assert "x+1" in resolved[0][0]


def test_resolve_all_calcs_multi_blocks():
    text = "A=<calc>comb(50,3)</calc> B=<calc>1/2+1/3</calc>"
    out, resolved = resolve_all_calcs(text)
    assert len(resolved) == 2
    assert resolved[0][1] == "19600"
    assert resolved[1][1] == "5/6"
    assert "A=[计算] comb(50,3) = 19600" in out
    assert "B=[计算] 1/2+1/3 = 5/6" in out


def test_extract_blocks_order():
    assert extract_calc_blocks("<calc>1</calc> a <calc>2</calc>") == ["1", "2"]


def test_safe_eval_pow_caret_numeric():
    # 2026-09-08 提交前审核修复：^ 幂记号（提示词声明合法）不再 BitXor ERROR
    assert safe_eval("2^10") == "1024"
    assert safe_eval("2^10+1") == "1025"
    assert safe_eval("1.5^3") == "27/8"
    assert safe_eval("2**10") == "1024"        # ** 写法不受影响（幂等）
    assert safe_eval("x^2") == "x**2"           # 符号分支仍正常


def test_safe_eval_float_literal():
    # 2026-09-08 提交前审核修复：小数写法精确转 Fraction，不再"不支持的常量"
    assert safe_eval("0.5") == "1/2"
    assert safe_eval("0.5 + 1/3") == "5/6"
    assert safe_eval("-0.25") == "-1/4"
    assert safe_eval("1.5^3") == "27/8"
    assert safe_eval("sqrt(0.25)") == "1/2"     # 小数进 sqrt 精确路径


def test_safe_eval_math_constants_approx():
    # 2026-09-09 G1：pi 常量 → ≈ 数值近似（不再当符号 "pi" 回填）；精确根式保留
    assert safe_eval("pi").startswith("≈ 3.14159")
    assert safe_eval("2*pi").startswith("≈ 6.28318")
    assert safe_eval("pi/2").startswith("≈ 1.5707")
    assert safe_eval("sqrt(45)") == "3*sqrt(5)"   # 精确根式不受影响
    r = safe_eval("x*pi")                          # 含变量 → 符号式保留（可代入）
    assert "x" in r and "pi" in r


def test_safe_eval_implicit_mul():
    # 2026-09-09 G2：数学隐式乘自动显式化
    assert safe_eval("2(x+1)") == "2*x + 2"
    assert safe_eval("(a+b)(c+d)") == "a*c + a*d + b*c + b*d"
    assert safe_eval("2x+3") == "2*x + 3"
    assert safe_eval("sum(2k,1,5)") == "30"        # 隐式乘与 sum 组合
    assert safe_eval("comb(5,2)") == "10"           # 函数调用不受影响
    # 分母位 1/2x 数学歧义（1/(2x)）→ 不静默改义，ERROR 引导显式写法
    assert safe_eval("1/2x").startswith("ERROR:")
    assert "分式分母含变量" in safe_eval("1/2x")


def test_safe_eval_sum_protocol():
    # 2026-09-09 G3：求和协议 sum(f,x,a,b) / 省略变量 sum(f,a,b)
    assert safe_eval("sum(k,1,10)") == "55"
    assert safe_eval("sum(k,k,1,n)") == "n**2/2 + n/2"
    assert safe_eval("sum(k^2,1,n)") == "n**3/3 + n**2/2 + n/6"
    assert safe_eval("sum(k,k,1,0)") == "0"
    assert safe_eval("sum(x*y,x,1,3)") == "6*y"


def test_safe_eval_trig_hint():
    # 2026-09-09 G5：三角 WARN 带替代路径提示（特殊角精确式 / 断言验算）
    r = safe_eval("sin(1)")
    assert r.startswith("WARN:") and "特殊角" in r and "sqrt(2)/2" in r


def test_safe_eval_err_hints():
    # 2026-09-09 G6/G7：错误文案给可行动替代
    assert "sqrt(10)" in safe_eval("10^0.5")
    assert "除数为零" in safe_eval("1/0")


def test_find_naked_numeric_asserts():
    """2026-09-12 计算分档（默认 hard_only=True）：只回收**高危算子**裸断言。"""
    from agent.calc_tool import find_naked_numeric_asserts as f
    # 高危运算的心算痕迹 → 检出（开方/组合数/幂）
    assert f("sqrt(45) = 6.708") == ["sqrt(45) = 6.708"]
    assert f("comb(50,3) = 19600") == ["comb(50,3) = 19600"]
    # 2026-09-13 幂按规模分档后：大幂仍回收，小幂（2^10）允许自算
    assert f("2^30 - 1 = 1073741823") == ["2^30 - 1 = 1073741823"]
    assert f("2^10 - 1 = 1023") == []
    # 纯四则（加减乘除）→ 允许模型自算，不再算裸断言
    assert f("25*4 = 100") == []
    assert f("1/2+1/3 = 5/6") == []
    assert f("故 2024 % 17 = 1") == []   # 整行含中文 → 宁漏不检（防打断推导）
    # 有工具来源 → 不算裸
    assert f("[计算] sqrt(45) = 6.708") == []
    assert f("<calc>sqrt(45)</calc> = 6.708") == []
    # 方程/结论（含变量）→ 放行
    assert f("x = 2") == []
    assert f("x^2 = 4") == []            # 含自由变量 → 方程，非心算数值
    assert f("解得 n = 3，代回成立") == []
    assert f("a + b = c") == []
    # 单侧/平凡
    assert f("= 1023") == []             # RHS-only：无算式侧可判高危 → 放行
    assert f("5 = 5") == []              # 平凡同式


def test_find_naked_numeric_asserts_legacy_mode():
    """hard_only=False 回退旧行为：任何两侧纯数值的 a = b 都算裸断言。"""
    from agent.calc_tool import find_naked_numeric_asserts as f
    assert f("25*4 = 100", hard_only=False) == ["25*4 = 100"]
    assert f("1/2+1/3 = 5/6", hard_only=False) == ["1/2+1/3 = 5/6"]
    assert f("= 1023", hard_only=False) == ["= 1023"]
    assert f("解得 n = 3，代回成立", hard_only=False) == []


def test_audit_calc_fallbacks():
    from agent.calc_tool import audit_calc_fallbacks as a
    resolved = [("2^10", "1024"), ("sin(1)", "WARN: 不支持函数 sin()…"),
                ("1/0", "ERROR: 除数为零…"), ("sqrt(45)", "3*sqrt(5)")]
    out = a(resolved)
    assert len(out) == 2
    assert out[0][0] == "sin(1)" and out[0][1].startswith("WARN:")
    assert out[1][1].startswith("ERROR:")
    assert a([]) == []


def test_safe_eval_code_misuse_hints():
    # 2026-09-09 P3 冒烟实证修复：<calc> 误用为代码执行器 → 专门引导文案
    from agent.calc_tool import safe_eval
    # 2026-09-13 策略B：纯赋值块回填末条赋值（单/多目标一视同仁，语义一致）
    assert safe_eval("a = 7\nresult = a // 2 + 2") == "5"
    assert safe_eval("a = 7\nb = 8") == "8"            # 多行单目标赋值块
    assert safe_eval("a=7;b=8") == "8"                 # `;` 分隔同义
    assert "单个数学表达式" in safe_eval("def f(n):\n    return n")   # 多行先命中
    assert "Python 代码" in safe_eval("if x > 0: x + 1 else 0")       # 单行关键字分支
    assert "simplify" in safe_eval("simplify(x+1)") and "没有 simplify" in safe_eval("simplify(x+1)")
    # 兼容 ≠ 放弃校验：真正非法输入仍拒绝（不因"回填末条赋值"而放行代码执行）
    assert safe_eval("__import__('os').system('ls')").startswith("ERROR:")
    assert safe_eval("__import__('os')\nos.system('ls')").startswith("ERROR:")
    # 正常表达式/净化路径不受影响
    assert safe_eval("x+1") == "x + 1"
    assert safe_eval("3*7-1=20").startswith("ERROR:")   # 单等号仍走语法错净化（resolve 层可救回）
