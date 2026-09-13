"""计算分档（2026-09-12 用户要求）单元测试。

用户原话：「不是一定要让大模型不计算，而是让它易错的根号、组合数、log
什么的用工具计算。像加减乘除什么的可以计算。」

覆盖：
1. calc_tool.hard_op_hits / needs_tool_calc / has_hard_op —— 高危算子识别
2. calc_tool.find_naked_numeric_asserts(hard_only=True) —— 只回收高危裸断言
3. calc_tool.find_naked_numeric_asserts(hard_only=False) —— 旧行为可回退
4. SolverAgent._maybe_calc_rewrite —— 纯四则响应不再重问（不触发 LLM）
"""

import pytest

from agent.calc_tool import (
    find_naked_numeric_asserts, has_hard_op, needs_tool_calc,
)

HARD_LINES = [
    "sqrt(45) = 6.708",
    "\u221a2 = 1.4142",
    "C(50,3) = 19600",
    "comb(50,3) = 19600",
    "log(100) = 2",
    "ln(2) = 0.693",
    "2^30 = 1073741824",
    "12! = 479001600",
    "e^2 = 7.389",
    "sum(k,1,10) = 55",
    "\\sqrt{45} = 6.708",
    "2**100 = 1267650600228229401496703205376",
    "sin(pi/6) = 0.5",
    "log_2(8) = 3",
    "log_{10}(100) = 2",
    "\\binom{5}{2} = 10",
    "C_{50}^{3} = 19600",
    "0.05^12 = 2.44e-16",
    # 取模（高危档）—— 2026-09-12 修复：_free_vars 曾漏挖 mod/bmod 致漏检
    "1024 mod 100 = 24",
    "100 bmod 7 = 2",
]

EASY_LINES = [
    "25*4 = 100",
    "1/2+1/3 = 5/6",
    "48/6 = 8",
    "3.5 + 1.25 = 4.75",
    "x = 2",
    "x^2 = 4",
    "n = comb(m,2)",
    "所以 x = 5",
    "2e3 = 2000",
    # 裸 e 作变量（非自然常数）—— 2026-09-12 修复：曾因无条件挖掉裸 e 而误判
    "e = 5",
    "e + 1 = 6",
    # 2026-09-13 用户裁决：幂按规模分档 ——「加减乘除、平方这些基本计算都可以
    # （让模型自己）算」，故小幂（平方/小次方）的裸断言不再回收（原在 HARD_LINES）。
    # 大幂（2^30 / 2**100 / 10**20 / 0.05^12）仍留在 HARD_LINES。
    "2^10 = 1024",
    "2**10 = 1024",
    "7**2 = 49",
]


@pytest.mark.parametrize("line", HARD_LINES)
def test_hard_lines_are_flagged(line):
    assert find_naked_numeric_asserts(line) == [line.strip()]


@pytest.mark.parametrize("line", EASY_LINES)
def test_easy_lines_are_passed(line):
    assert find_naked_numeric_asserts(line) == []


def test_needs_tool_calc():
    assert needs_tool_calc("sqrt(45)") is True
    assert needs_tool_calc("comb(50,3)*2**10") is True
    assert needs_tool_calc("25*4+1") is False
    assert needs_tool_calc("1/2+1/3") is False


def test_has_hard_op_strict_ignores_latex_superscript():
    # 整段扫描：LaTeX 符号上标 x^{2} / n^{k} 不算高危（代数式而非心算数值）
    assert has_hard_op("设 x^{2}+y^{2}=1") is False
    assert has_hard_op("设 n^{k} 为幂次") is False
    # 2026-09-13 用户裁决：幂两档统一按规模分档 —— 数字底数的小幂同样放行
    assert has_hard_op("由 2^{10} 得 1024") is False
    assert has_hard_op("由 2**10 得 1024") is False
    # 数字底数的**大**幂、函数调用、单字母组合数 → 算
    assert has_hard_op("由 2^{100} 得 1.27e30") is True
    assert has_hard_op("代入 sqrt(2) 得 1.414") is True
    assert has_hard_op("组合数 C(50,3) 得 19600") is True
    # strict 档保留的护栏：符号底数的 ** 仍算（与 x^{2} 的放行不同）
    assert has_hard_op("代数式 x**2 + y**2 = 1") is True
    # 纯四则整段 → 放行
    assert has_hard_op("相加得 25*4 = 100") is False


def test_hard_only_false_keeps_legacy_behavior():
    # 回退开关：旧行为下任何两侧纯数值的 a = b 都算裸断言
    assert find_naked_numeric_asserts("25*4 = 100", hard_only=False) == ["25*4 = 100"]
    assert find_naked_numeric_asserts("25*4 = 100") == []


class _Cfg:
    def __init__(self):
        self.calc_mandatory = True
        self.calc_hard_only = True
        self.max_answer_tokens = 512


class _Stub:
    def __init__(self):
        self.config = _Cfg()
        self.events = []

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


def test_calc_rewrite_passes_pure_arithmetic():
    """纯四则响应 → 不重问（不触发 LLM），只留 calc_easy_pass 埋点。"""
    from agent.solver import SolverAgent
    stub = _Stub()
    resp = "25*4 = 100\n1/2+1/3 = 5/6"
    out = SolverAgent._maybe_calc_rewrite(stub, None, resp)
    assert out == resp
    assert any(k == "calc_easy_pass" for k, _ in stub.events)
    assert not any(k == "solver_calc_rewrite" for k, _ in stub.events)


# ------------------------------------------------------------------
# 2026-09-12 定型前审核修复：表达式范式只能采纳**纯数值**工具结果
# （原实现 findall 抓碎片数字 → 3*sqrt(5) 会被读成 5，且直接写进最终答案）
# ------------------------------------------------------------------
def _expr_stub(tool_result):
    stub = _Stub()
    stub._calc_tool_exec = lambda _e: tool_result
    return stub


def test_expression_eval_rejects_symbolic_result():
    from agent.solver import SolverAgent
    stub = _expr_stub("3*sqrt(5)")           # 精确根式，非纯数值
    resp = "【变量赋值】x=45\n【最终表达式】sqrt(x)\n【最终答案】6.7"
    out, ans = SolverAgent._maybe_expression_eval(stub, None, resp, "6.7")
    assert out == resp and ans == "6.7"      # 弃权，保留模型原答案
    assert any(k == "expression_eval_skip" for k, _ in stub.events)


def test_expression_eval_rejects_warn_result():
    from agent.solver import SolverAgent
    stub = _expr_stub("WARN: 该表达式超出工具能力（第 12 项）")
    resp = "【变量赋值】n=7\n【最终表达式】sin(n)\n【最终答案】0.657"
    out, ans = SolverAgent._maybe_expression_eval(stub, None, resp, "0.657")
    assert out == resp and ans == "0.657"
    assert any(k == "expression_eval_skip" for k, _ in stub.events)


def test_expression_eval_adopts_numeric_result():
    from agent.solver import SolverAgent
    stub = _expr_stub("25")
    resp = "【变量赋值】x=5, y=5\n【最终表达式】(x+y)*2 + 5\n【最终答案】25"
    out, ans = SolverAgent._maybe_expression_eval(stub, None, resp, "25")
    assert ans == "25"
    assert "【最终答案】25" in out
    assert any(k == "expression_eval" for k, _ in stub.events)


# ------------------------------------------------------------------
# 2026-09-13 修复（q3_mcp 实测实锤）：参数题不得被"自造代入值"覆盖符号答案
# ------------------------------------------------------------------
def test_expression_eval_rejects_symbolic_model_answer():
    """#001 实况：gold `2-2m`，模型原答 `-2(m-1)`（恒等，正确），响应里却有
    自造赋值 m=3 + 表达式 -2*(3-1) → 旧实现以工具值 -4 覆盖正确答案。

    修复后：模型答案为符号式（含自由变量）时本关弃权。
    """
    from agent.solver import SolverAgent
    stub = _expr_stub("-4")
    ctx = _CtxStub()
    ctx.problem = "Let $m\\ge 3$ be an integer. Find the largest constant $T$."
    resp = ("推理…\n【变量赋值】m=3\n【最终表达式】-2*(3-1)\n"
            "【最终答案】\\boxed{-2(m-1)}")
    out, ans = SolverAgent._maybe_expression_eval(
        stub, ctx, resp, "\\boxed{-2(m-1)}")
    assert (out, ans) == (resp, "\\boxed{-2(m-1)}")
    assert any(k == "expression_eval_skip" for k, _ in stub.events)
    assert not any(k == "expression_eval" for k, _ in stub.events)


def test_expression_eval_still_adopts_for_numeric_answer():
    """回归护栏：模型答案为纯数值（本关本来适用的场景）→ 行为不变。"""
    from agent.solver import SolverAgent
    stub = _expr_stub("25")
    ctx = _CtxStub()
    ctx.problem = "设 x=5, y=5，计算 (x+y)*2+5"
    resp = "【变量赋值】x=5, y=5\n【最终表达式】(x+y)*2 + 5\n【最终答案】25"
    out, ans = SolverAgent._maybe_expression_eval(stub, ctx, resp, "25")
    assert ans == "25"
    assert any(k == "expression_eval" for k, _ in stub.events)


# ------------------------------------------------------------------
# 2026-09-12 逻辑堆叠治理：同族"答案取工具值"机制不得重复处理
# （表达式范式采纳后，答案自洽核验与符号化求解都应跳过）
# ------------------------------------------------------------------
class _CtxStub:
    """最小 ctx 桩：只需支持属性读写。"""

    def __init__(self):
        self.problem = "计算 (5+5)*2+5"


def test_expression_eval_adoption_blocks_downstream_selfcheck():
    from agent.solver import SolverAgent
    stub = _expr_stub("25")
    stub.config.answer_selfcheck_enabled = True
    ctx = _CtxStub()
    resp = "【变量赋值】x=5, y=5\n【最终表达式】(x+y)*2 + 5\n【最终答案】25"
    out, ans = SolverAgent._maybe_expression_eval(stub, ctx, resp, "25")
    assert ans == "25"
    assert getattr(ctx, "_expr_eval_adopted", False) is True
    # 下游：答案是纯数值且无 <calc> 来源，但不得再打回重问一次
    out2, ans2 = SolverAgent._maybe_answer_selfcheck(stub, ctx, out, ans, [])
    assert (out2, ans2) == (out, ans)
    assert not any(k == "answer_selfcheck" for k, _ in stub.events)
    assert any(k == "answer_selfcheck_skip" for k, _ in stub.events)


def test_expression_eval_replaces_existing_final_answer_marker():
    """resp 已有【最终答案】时必须替换 —— 否则双标记会让下游抽到模型旧值。"""
    from agent.solver import SolverAgent
    from utils.extract import extract_final_answer
    stub = _expr_stub("25")
    resp = ("推理过程…\n【变量赋值】n=25\n【最终表达式】sqrt(n)*5\n"
            "【最终答案】\n\\boxed{35}\n最简形式：35")
    out, ans = SolverAgent._maybe_expression_eval(stub, None, resp, "35")
    assert ans == "25"
    assert out.count("【最终答案】") == 1          # 不得留下两个标记
    assert extract_final_answer(out) == "25"      # 下游抽到的必须是工具值


def test_expression_eval_skips_objective_questions():
    """客观题答案是选项字母/判断值，不得被工具数值改写。"""
    from agent.solver import SolverAgent
    stub = _expr_stub("25")
    ctx = _CtxStub()
    ctx.question_type = "选择题"
    resp = "【变量赋值】x=5\n【最终表达式】x*5\n【最终答案】C"
    out, ans = SolverAgent._maybe_expression_eval(stub, ctx, resp, "C")
    assert (out, ans) == (resp, "C")
    assert not any(k == "expression_eval" for k, _ in stub.events)


def test_formatter_keeps_single_char_answer():
    """2026-09-12 定型前审核修复：单字符答案不得被丢弃。

    原判据 `not answer or len(answer) < 2` 会把选项字母（A/C）、判断题值、
    个位数整条丢弃并换成推理尾部 500 字 → 客观题必然判错。
    用源码契约锁定（与 tests/test_p1_hard_signal.py 同风格）。
    """
    import os

    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "formatter.py")
    src = open(p, encoding="utf-8").read()
    # 只检查可执行代码（剔除注释行）—— 注释里对旧判据的引用会误报
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "len(answer) < 2" not in code, "单字符答案判据已回归"
    assert "not answer.strip()" in code, "空答案回退分支丢失"


def test_expression_eval_adoption_blocks_downstream_symbolic_solve():
    from agent.solver import SolverAgent
    stub = _Stub()
    stub.config.symbolic_solve_enabled = True
    ctx = _CtxStub()
    ctx._expr_eval_adopted = True
    out, ans = SolverAgent._maybe_symbolic_solve(stub, ctx, "resp", "25")
    assert (out, ans) == ("resp", "25")
    assert any(k == "symbolic_solve_skip" for k, _ in stub.events)
