"""L1/L2 计算核验单元测试（2026-09-10）。

覆盖新增能力：
1. calc_tool.safe_eval_subst —— 符号代入**精确**求值（含异常回落契约）
2. calc_tool.to_exact_number —— 答案串精确数值化（非精确一律 None）
3. deterministic.verify_answer_exact —— 精确代入核验（宁漏勿误）
4. agent/symbolic_model —— L2 结构化建模的解析/规整/求值（含防偷算护栏）
5. SolverAgent 的 L1/L2 关卡开关与放行分支（不触发 LLM）
"""

from fractions import Fraction

from agent.calc_tool import safe_eval_subst, to_exact_number
from agent.deterministic import verify_answer_exact


# ---------------------------------------------------------------- 1) 代入求值
def test_subst_basic():
    assert safe_eval_subst("2*x+y", {"x": 10, "y": 5}) == "25"
    assert safe_eval_subst("2*x+y", {"x": "10", "y": "5"}) == "25"
    assert safe_eval_subst("n*(n+1)/2", {"n": 5}) == "15"
    assert safe_eval_subst("x^2-1", {"x": 3}) == "8"
    assert safe_eval_subst("2x+y", {"x": 10, "y": 5}) == "25"   # 隐式乘
    assert safe_eval_subst("a/2", {"a": "5/6"}) == "5/12"       # 精确分数
    assert safe_eval_subst("x-y", {"x": 1, "y": 3}) == "-2"


def test_subst_stays_exact_with_decimals():
    # 小数必须转精确有理数：否则会退化成 "0.250000000000000" 浮点串
    assert safe_eval_subst("x/2", {"x": 0.5}) == "1/4"
    assert safe_eval_subst("x/2", {"x": "0.5"}) == "1/4"
    assert safe_eval_subst("x+y", {"x": 1.5, "y": 2.5}) == "4"
    # 表达式里的十进制字面量同样精确化（x**0.5 → sqrt(x)）
    assert safe_eval_subst("x**0.5", {"x": 4}) == "2"
    # 非实数结果（1/0 = zoo）→ WARN，不返回伪数值
    assert safe_eval_subst("1/x", {"x": 0}).startswith("WARN:")


def test_subst_leftover_and_capability():
    # 仍有未代入变量 → WARN（不是错误）
    assert safe_eval_subst("2*x+y", {"x": 10}).startswith("WARN:")
    # 取值表里的键没出现在表达式里 → 表达式里的 x 仍是自由符号 → WARN
    assert safe_eval_subst("x+1", {"xx": 1}).startswith("WARN:")
    # 空 mapping：纯数值算式可直接精确求值；含符号则 WARN
    assert safe_eval_subst("1/2+1/3", {}) == "5/6"
    assert safe_eval_subst("x+1", {}).startswith("WARN:")
    # 无平方因子根式 → 精确式（非近似）
    assert safe_eval_subst("sqrt(x)", {"x": 5}) == "sqrt(5)"
    # 整除/取模语义歧义 → WARN
    assert safe_eval_subst("x//y", {"x": 7, "y": 2}).startswith("WARN:")


def test_subst_multiletter_and_reserved_names():
    # 多字母变量名（模型常写 length/width）必须支持
    assert safe_eval_subst("length*width", {"length": 7, "width": 3}) == "21"
    # 前缀关系不得互相破坏：n 不能污染 n2
    assert safe_eval_subst("n+n2", {"n": 1, "n2": 10}) == "11"
    # 与 SymPy 内建同名的变量必须仍按变量代入（改名为内部记号）
    # E 是自然常数：若不改名，"E*x" 会算出 2e 而不是 10
    assert safe_eval_subst("E*x", {"E": 5, "x": 2}) == "10"
    assert safe_eval_subst("I+x", {"I": 3, "x": 1}) == "4"


def test_subst_never_raises():
    # 审计 P0：任何异常都必须回落 WARN，不得穿透给调用方
    assert safe_eval_subst("x+1", {"x": "5/0"}).startswith("WARN:")   # ZeroDivision
    assert safe_eval_subst("x**", {"x": 1}).startswith("WARN:")       # 语法
    assert safe_eval_subst("x+", {"x": 1}).startswith("WARN:")
    assert safe_eval_subst("1/(x-x)", {"x": 1}).startswith("WARN:")   # zoo
    for bad in ["'x'", "__import__('os')", "x[0]", "中文"]:
        out = safe_eval_subst(bad, {"x": 1})
        assert out.startswith(("WARN:", "ERROR:")), (bad, out)


def test_subst_error_paths():
    assert safe_eval_subst("", {"x": 1}).startswith("ERROR:")
    assert safe_eval_subst("x+1", {"x": "abc"}).startswith("ERROR:")
    assert safe_eval_subst("x+1", {"x": "2*3"}).startswith("ERROR:")   # 只收数值字面
    # 非数学字符（中文/引号）→ WARN（能力外，非写错）
    assert safe_eval_subst("x+一", {"x": 1}).startswith("WARN:")


# ------------------------------------------------------------ 2) 答案数值化
def test_to_exact_number_accepts():
    assert to_exact_number("25") == Fraction(25)
    assert to_exact_number("-3") == Fraction(-3)
    assert to_exact_number("5/6") == Fraction(5, 6)
    assert to_exact_number("0.5") == Fraction(1, 2)
    assert to_exact_number("$25$") == Fraction(25)
    assert to_exact_number("\\boxed{25}") == Fraction(25)
    assert to_exact_number("\\frac{1}{2}") == Fraction(1, 2)
    assert to_exact_number("\\boxed{\\frac{1}{2}}") == Fraction(1, 2)


def test_to_exact_number_rejects():
    assert to_exact_number("") is None
    assert to_exact_number(None) is None
    assert to_exact_number("≈ 3.14159") is None      # 近似值不可精确判等
    assert to_exact_number("3*sqrt(5)") is None      # 精确根式（非有理）
    assert to_exact_number("2*x+y") is None          # 含变量
    assert to_exact_number("25%") is None            # 百分号歧义
    assert to_exact_number("25个") is None            # 带文字
    assert to_exact_number("1 2") is None             # 内部空格不得被吃掉
    assert to_exact_number("1,234") is None           # 千分位歧义


def test_to_exact_number_latex_edge_cases():
    # 无括号 LaTeX 必须弃权：否则剥掉 \dfrac 后会错读成数值 12
    assert to_exact_number("\\dfrac12") is None
    assert to_exact_number("\\boxed{\\dfrac12}") is None
    assert to_exact_number("\\dfrac{1}{2}") == Fraction(1, 2)
    assert to_exact_number("\\boxed{\\frac{1}{2}}") == Fraction(1, 2)
    assert to_exact_number("+5") == Fraction(5)


def test_subst_robust_inputs():
    # 非字符串入参不得抛异常
    assert safe_eval_subst(5, {"x": 1}) == "5"
    assert safe_eval_subst(None, {"x": 1}).startswith("ERROR:")
    assert safe_eval_subst("x", None).startswith("WARN:")
    assert safe_eval_subst("x", "notadict").startswith("WARN:")
    # 超长表达式直接拒绝，不进 SymPy
    assert safe_eval_subst("1+" * 400 + "1", {"x": 1}).startswith("ERROR:")


# ------------------------------------------------------------ 3) 精确代入核验
def test_verify_answer_exact():
    r = verify_answer_exact("2*x+y", "25", {"x": 10, "y": 5})
    assert r["verdict"] == "pass", r
    r = verify_answer_exact("2*x+y", "26", {"x": 10, "y": 5})
    assert r["verdict"] == "fail", r
    # 答案无法精确数值化 → unknown（绝不误杀）
    assert verify_answer_exact("2*x", "2*x", {"x": 5})["verdict"] == "unknown"
    # 无取值 → unknown
    assert verify_answer_exact("2*x", "10", None)["verdict"] == "unknown"
    # 表达式为空 → unknown
    assert verify_answer_exact("", "10", {"x": 1})["verdict"] == "unknown"


# --------------------------------------------------- 4) 关卡开关（不触发 LLM）
class _Cfg:
    def __init__(self, enabled):
        self.answer_selfcheck_enabled = enabled
        self.max_answer_tokens = 1024


class _Stub:
    def __init__(self, enabled):
        self.config = _Cfg(enabled)
        self.events = []

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, timeup=True, problem="计算 2*10+5 的值", remain=None):
        self._timeup = timeup
        self.problem = problem
        self.question_type = ""
        self._remain = remain          # 2026-09-13：非 None 时走"剩余预算"判定

    def gen_time_up(self):
        return self._timeup

    def time_remaining(self):
        # remain 未给 ⇒ 抛异常，令生产代码退回 gen_time_up() 判定，
        # 从而保持既有测试的语义逐字不变（它们只桩了 gen_time_up）。
        if self._remain is None:
            raise AttributeError("remain not provided")
        return float(self._remain)


def test_selfcheck_disabled_is_noop():
    from agent.solver import SolverAgent
    stub = _Stub(False)
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=False), "推理…【最终答案】25", "25", [("2*10+5", "25")])
    assert out == ("推理…【最终答案】25", "25")
    assert stub.events == []


def test_selfcheck_skips_when_tool_provenance_exists():
    from agent.solver import SolverAgent
    stub = _Stub(True)
    # 2026-09-12 计算分档：须含高危算子（sqrt）才进本关卡判定范围
    resp = "推导 [计算] sqrt(625) = 25\n【最终答案】25"
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=False), resp, "25", [("sqrt(625)", "25")])
    assert out == (resp, "25")
    assert stub.events == []          # 有工具来源 → 放行，不重问


def test_selfcheck_skips_non_numeric_answer():
    from agent.solver import SolverAgent
    stub = _Stub(True)
    resp = "【最终答案】2*x+y"
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=False), resp, "2*x+y", [])
    assert out == (resp, "2*x+y")
    assert stub.events == []


def test_selfcheck_respects_time_wall():
    from agent.solver import SolverAgent
    stub = _Stub(True)
    # 2026-09-12 计算分档：resp 须含高危算子（sqrt）才进本关卡判定范围
    resp = "心算得 sqrt(625) = 25\n【最终答案】25"
    # 时间到 → 记录事件但不重问（返回原输出）
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=True), resp, "25", [])
    assert out == (resp, "25")
    assert any(k == "answer_selfcheck" for k, _ in stub.events)


def test_selfcheck_skips_pure_arithmetic_answer():
    """2026-09-12 计算分档：解答全程纯四则（无高危算子）→ 不要求工具来源。"""
    from agent.solver import SolverAgent
    stub = _Stub(True)
    resp = "先算 25*4 = 100，再 100-75 = 25\n【最终答案】25"
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=False), resp, "25", [])
    assert out == (resp, "25")
    assert not any(k == "answer_selfcheck" for k, _ in stub.events)
    assert any(k == "answer_selfcheck_skip" for k, _ in stub.events)


def test_selfcheck_uses_remaining_budget_not_gen_wall():
    """2026-09-13：时间判定由「生成侧软截止」改为「剩余总预算 >=300s」。

    背景（实测驱动）：三轮冒烟（v1/v2/v5）在 010 上都记为"生成侧时间到，跳过
    重问"，而该机制是当时唯一能纠正错答案的途径（Lean 的 answer_valid 在题面
    无 ≥3 位数字时会退化为自证放行）。故改为按剩余总预算判定。
    """
    from agent.solver import SolverAgent
    resp = "心算得 sqrt(625) = 25\n【最终答案】25"
    # 生成侧已到（gen_time_up=True），但剩余预算充足 → 仍应定向重问
    stub = _Stub(True)
    out = SolverAgent._maybe_answer_selfcheck(
        stub, _Ctx(timeup=True, remain=400.0), resp, "25", [])
    assert out == (resp, "25")
    msg = [m for k, m in stub.events if k == "answer_selfcheck"]
    assert msg, "应记录 answer_selfcheck 事件"
    assert "跳过重问" not in msg[0], msg
    assert "定向重问" in msg[0], msg
    assert "400" in msg[0], msg

    # 剩余确实不足（200s < 300s）→ 跳过重问，且打标记供 6.5 闸门联动
    stub2 = _Stub(True)
    ctx2 = _Ctx(timeup=False, remain=200.0)
    SolverAgent._maybe_answer_selfcheck(stub2, ctx2, resp, "25", [])
    assert getattr(ctx2, "selfcheck_unverified_answer", "") == "25"
    msg2 = [m for k, m in stub2.events if k == "answer_selfcheck"]
    assert msg2 and "跳过重问" in msg2[0], msg2


# ----------------------------------------------------- 5) L2 符号建模（纯函数）
def test_parse_symbolic_payload():
    from agent.symbolic_model import parse_symbolic_payload
    ok = '{"vars": {"x": 10, "y": 5}, "target": "书数", "expr": "2*x+y"}'
    p = parse_symbolic_payload(ok)
    assert p and p["expr"] == "2*x+y" and p["vars"]["x"] == 10
    # markdown 围栏
    p = parse_symbolic_payload("```json\n" + ok + "\n```")
    assert p and p["expr"] == "2*x+y"
    # 前后有解释文字 → 抠第一个平衡花括号块
    p = parse_symbolic_payload("好的，结果如下：\n" + ok + "\n希望有帮助")
    assert p and p["expr"] == "2*x+y"
    # 缺右括号（prefill 续写被截断）→ 正则兜底
    p = parse_symbolic_payload('{"vars": {"x": 10}, "expr": "2*x+1"')
    assert p and p["expr"] == "2*x+1" and p["vars"] == {"x": "10"}
    # 垃圾输入 → None
    assert parse_symbolic_payload("") is None
    assert parse_symbolic_payload("无法建模") is None
    assert parse_symbolic_payload(None) is None


def test_normalize_payload():
    from agent.symbolic_model import normalize_payload
    m, e = normalize_payload({"vars": {"x": 10, "y": "5"}, "expr": "2*x+y"})
    assert m == {"x": "10", "y": "5"} and e == "2*x+y"
    # 多字母变量名也要保留（实测模型会写 length/width）
    m, e = normalize_payload({"vars": {"length": 7, "width": 3},
                              "expr": "length*width"})
    assert m == {"length": "7", "width": "3"}
    # 非法键名（非标识符）被剔除
    m, _ = normalize_payload({"vars": {"x": 1, "小明": 2}, "expr": "x+1"})
    assert m == {"x": "1"}
    # 缺 expr / expr 为空 → 不可用；vars 可为空（纯数值算式）
    assert normalize_payload({"vars": {"x": 1}}) == (None, None)
    assert normalize_payload({"vars": {"x": 1}, "expr": "  "}) == (None, None)
    assert normalize_payload({"vars": {}, "expr": "1/2+1/3"}) == ({}, "1/2+1/3")
    assert normalize_payload(None) == (None, None)
    # answer_expr 别名兼容
    m, e = normalize_payload({"vars": {"x": 2}, "answer_expr": "x*x"})
    assert e == "x*x"


def test_evaluate_payload():
    from agent.symbolic_model import evaluate_payload
    v, why = evaluate_payload({"vars": {"x": 10, "y": 5}, "expr": "2*x+y"})
    assert v == "25" and "25" in why
    # 多字母变量 + 几何题（真实探测暴露过）
    v, _ = evaluate_payload({"vars": {"length": 7, "width": 3},
                             "expr": "length*width"})
    assert v == "21"
    # 纯数值算式（vars 为空）也必须能算（真实探测暴露过）
    v, _ = evaluate_payload({"vars": {}, "expr": "1/2+1/3"})
    assert v == "5/6"
    # 防偷算①：expr 是裸数值 → 弃权（模型已自行算出，可能算错）
    v, why = evaluate_payload({"vars": {"n": 2024}, "expr": "4"})
    assert v is None and "裸数值" in why
    # 防偷算②：声明了变量却完全没用上 → 弃权
    v, why = evaluate_payload({"vars": {"x": 10}, "expr": "3+5"})
    assert v is None and "未使用" in why
    # 非精确结果（无理式）→ None
    v, _ = evaluate_payload({"vars": {"x": 5}, "expr": "sqrt(x)"})
    assert v is None
    # 无法建模 → None
    v, why = evaluate_payload({"vars": {"x": 1}, "expr": ""})
    assert v is None and "表达式" in why
    # 未代入变量 → None
    v, _ = evaluate_payload({"vars": {"x": 1}, "expr": "x+y"})
    assert v is None


def test_symbolic_crosscheck_disabled_is_noop():
    from agent.solver import SolverAgent
    stub = _Stub(False)
    stub.config.symbolic_crosscheck_enabled = False
    resp = "推理…【最终答案】25"
    out = SolverAgent._maybe_symbolic_crosscheck(stub, _Ctx(timeup=False), resp, "25")
    assert out == (resp, "25")
    assert stub.events == []


def test_symbolic_crosscheck_time_wall_is_noop():
    from agent.solver import SolverAgent
    stub = _Stub(False)
    stub.config.symbolic_crosscheck_enabled = True
    stub.config.symbolic_max_tokens = 512
    resp = "推理…【最终答案】25"
    ctx = _Ctx(timeup=True)
    out = SolverAgent._maybe_symbolic_crosscheck(stub, ctx, resp, "25")
    assert out == (resp, "25")                       # 时间到 → 不调 LLM
    assert any(k == "symbolic_crosscheck" for k, _ in stub.events)


def test_symbolic_crosscheck_skips_non_numeric_and_proof():
    from agent.solver import SolverAgent
    stub = _Stub(False)
    stub.config.symbolic_crosscheck_enabled = True
    # 非纯数值答案 → 直接放行（不进 LLM）
    out = SolverAgent._maybe_symbolic_crosscheck(
        stub, _Ctx(timeup=False), "【最终答案】2*x+y", "2*x+y")
    assert out == ("【最终答案】2*x+y", "2*x+y")
    # 证明题 → 放行
    out = SolverAgent._maybe_symbolic_crosscheck(
        stub, _Ctx(timeup=False, problem="证明：对任意 n 有 n^2 >= n"),
        "【最终答案】25", "25")
    assert out == ("【最终答案】25", "25")
    assert stub.events == []
