# -*- coding: utf-8 -*-
"""L2 子目标数值/代数断言 Lean 验证单测（2026-09-08 门去掉后新钩子）。

覆盖：提取器（宁缺毋滥丢弃规则/num-poly 分类/去重/上限）、隐式乘修复、
开关与每题限额守卫（mock LeanBridge，不做真编译）。
"""
import sys  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

sys.path.insert(0, "D:/挑战杯")  # noqa: E402
from agent.sub_goal_solver import SubGoalSolverAgent  # noqa: E402
from agent.base import TaskContext  # noqa: E402


def _agent(**cfg_over):
    cfg_default = dict(
        enable_numeric_lean_verify=True, lean_numeric_max_per_q=2,
        dag_replan_lean_check=True, dag_lean_max_nodes=6, max_tokens_cap=0)
    cfg_default.update(cfg_over)
    cfg = SimpleNamespace(**cfg_default)
    ag = SubGoalSolverAgent.__new__(SubGoalSolverAgent)
    ag.client = SimpleNamespace()
    ag.config = cfg
    ag.name = "SubGoalSolver"
    return ag


class ExtractAssertPairsTest(unittest.TestCase):
    def setUp(self):
        self.ag = _agent()

    def test_poly_correct_form(self):
        out = self.ag._extract_lean_assert_pairs(
            "x^2 + x - 2 = (x - 1)(x + 2)")
        self.assertEqual(len(out), 1)
        L, R, kind, v = out[0]
        self.assertEqual(kind, "poly")
        self.assertEqual(v, "x")

    def test_num_power_form(self):
        out = self.ag._extract_lean_assert_pairs("2^10 = 1024")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][2], "num")

    def test_num_fraction_form(self):
        out = self.ag._extract_lean_assert_pairs("1/2 + 1/3 = 5/6")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][2], "num")

    def test_function_call_dropped(self):
        """g(0)=0 / f(1)=2 / g(x)=x^2 是函数调用形态，不得误判为 poly。"""
        for s in ("g(0)=0", "f(1)=2", "g(x) = x^2"):
            self.assertEqual(self.ag._extract_lean_assert_pairs(s), [],
                             f"应丢弃: {s}")

    def test_implicit_mul_dropped(self):
        """2x / 6b / x(3) 隐式乘在 Lean 不合法 → 丢弃不构造。"""
        for s in ("6b = 12", "x(3) = 6"):
            self.assertEqual(self.ag._extract_lean_assert_pairs(s), [],
                             f"应丢弃: {s}")

    def test_multivar_and_slash_dropped(self):
        for s in ("a + b = 2", "k = (a - b)/(b c)", "x/y = 2"):
            self.assertEqual(self.ag._extract_lean_assert_pairs(s), [],
                             f"应丢弃: {s}")

    def test_no_assert_zero_cost(self):
        self.assertEqual(
            self.ag._extract_lean_assert_pairs("该步为方向性论证，无数值"),
            [])

    def test_dedup_and_cap3(self):
        out = self.ag._extract_lean_assert_pairs(
            "2^10 = 1024 2^10 = 1024 3^3 = 27 4^2 = 16 5^1 = 5 6^0 = 1")
        # 中文/句法会打断，保守断言：去重后不超过 3
        self.assertLessEqual(len(out), 3)

    def test_laplace_and_chinese_survive(self):
        """含 LaTeX/中文的行不得产生误构造。"""
        for s in ("面积为 12", "The inequality is equivalent to "
                  "(1 - a_i^2)(1 - a_j^2) <= 0", "f(x)=x^2"):
            self.assertEqual(self.ag._extract_lean_assert_pairs(s), [],
                             f"应丢弃: {s}")


class FixLeanMulTest(unittest.TestCase):
    def test_parentheses_mul(self):
        self.assertEqual(
            SubGoalSolverAgent._fix_lean_mul("(x - 1)(x + 2)"),
            "(x - 1) * (x + 2)")
        self.assertEqual(
            SubGoalSolverAgent._fix_lean_mul("2(x+1)"), "2 * (x+1)")

    def test_no_change_for_explicit(self):
        self.assertEqual(SubGoalSolverAgent._fix_lean_mul("x^2 + x - 2"),
                         "x^2 + x - 2")
        self.assertEqual(SubGoalSolverAgent._fix_lean_mul("2^10"), "2^10")


class NumericLeanVerifyGuardTest(unittest.TestCase):
    def test_switch_off_returns_empty(self):
        ag = _agent(enable_numeric_lean_verify=False)
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000
        self.assertEqual(ag._numeric_lean_verify(ctx, "2^10 = 1025"), "")

    def test_no_assert_no_compile_call(self):
        ag = _agent()
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000
        with patch("agent.sub_goal_solver.SubGoalSolverAgent"
                   "._extract_lean_assert_pairs",
                   return_value=[]) as m:
            self.assertEqual(ag._numeric_lean_verify(ctx, "随便"), "")
            m.assert_called_once()

    def test_quota_cap(self):
        """每题限额：meta 计数达到 cap 后不再编译。"""
        ag = _agent(lean_numeric_max_per_q=2)
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000
        ctx.metadata["numeric_lean_count"] = 2
        with patch("agent.sub_goal_solver.SubGoalSolverAgent"
                   "._extract_lean_assert_pairs") as m:
            self.assertEqual(ag._numeric_lean_verify(ctx, "2^10 = 1024"), "")
            m.assert_not_called()

    def test_compile_fail_returns_feedback(self):
        """编译失败（真算错）→ 返回带断言的反馈文本。"""
        ag = _agent()
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000
        fake_bridge = SimpleNamespace(
            lean_available=True,
            _lean_project_dir="D:/mathlib4-last_bump_for_v4.31.0",
            _compile=lambda *a, **k: {"ok": False,
                                      "error": "file.lean:3:0: error: "
                                               "unsolved goals"})
        with patch("tools.lean_local.lean_bridge.LeanBridge",
                   return_value=fake_bridge):
            fb = ag._numeric_lean_verify(ctx, "2^10 = 1025")
        self.assertIn("2^10 = 1025", fb)
        self.assertIn("Lean", fb)


if __name__ == "__main__":
    unittest.main()


class CheckProtocolExtractTest(unittest.TestCase):
    def setUp(self):
        self.ag = _agent()

    def test_extract_single(self):
        out = self.ag._extract_check_asserts(
            "结果：<check>2^10 = 1024</check> 完毕")
        self.assertEqual(out, [("2^10", "1024")])

    def test_extract_multiple_dedup_cap4(self):
        out = self.ag._extract_check_asserts(
            "<check>a = b</check><check>c = d</check><check>a = b</check>")
        self.assertEqual(len(out), 2)

    def test_extract_bad_forms(self):
        for s in ("<check>2^10 = 1024 和 3^3 = 27</check>",
                  "<check>x = y = z</check>", "<check>中文 = 2</check>",
                  "<check></check>"):
            self.assertEqual(self.ag._extract_check_asserts(s), [],
                             f"应丢弃: {s}")

    def test_no_check_empty(self):
        self.assertEqual(self.ag._extract_check_asserts("结果：x=5 无协议"), [])


class SympyJudgeTest(unittest.TestCase):
    def setUp(self):
        self.ag = _agent()

    def test_pow_conversion(self):
        self.assertEqual(SubGoalSolverAgent._pow_to_python("2^10"), "2**10")
        self.assertEqual(SubGoalSolverAgent._pow_to_python("2**10"), "2**10")
        self.assertEqual(SubGoalSolverAgent._pow_to_python("(x+1)^2"),
                         "(x+1)**2")

    def test_judge_num(self):
        self.assertEqual(self.ag._sympy_judge("2^10", "1024")[0], "pass")
        v, info = self.ag._sympy_judge("2^10", "1025")
        self.assertEqual(v, "fail")
        self.assertIn("1024", info)

    def test_judge_poly(self):
        self.assertEqual(
            self.ag._sympy_judge("(x-1)*(x+2)", "x^2+x-2")[0], "pass")
        v, info = self.ag._sympy_judge("(x-1)*(x+3)", "x^2+x-2")
        self.assertEqual(v, "fail")
        self.assertIn("相差", info)

    def test_judge_frac(self):
        self.assertEqual(
            self.ag._sympy_judge("1/2+1/3", "5/6")[0], "pass")
        v, _ = self.ag._sympy_judge("1/2+1/3", "4/5")
        self.assertEqual(v, "fail")

    def test_judge_unknown_no_false_alarm(self):
        """sympy 判不了（无假设超越恒等）→ unknown，绝不误报 fail。"""
        # simplify 能约分判等 → pass
        self.assertEqual(self.ag._sympy_judge("(x^2-1)/(x-1)", "x+1")[0],
                         "pass")
        # 有理式不恒等且可确定 → fail（带真值）
        self.assertEqual(self.ag._sympy_judge("(x^2-1)/(x-1)", "x")[0],
                         "fail")
        # 无假设对数恒等 sympy 判不了 → unknown（宁放行不误报）
        self.assertEqual(self.ag._sympy_judge("log(x*y)", "log(x)+log(y)")[0],
                         "unknown")


class CheckVerifyFeedbackTest(unittest.TestCase):
    def test_fail_feedback_carries_true_value(self):
        """协议版：错断言反馈必须携带可行动真值，且经 Lean 背书。"""
        ag = _agent()
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000

        def _fake_compile(code, work_dir=None, lean_filename="verify.lean",
                          allow_sorry=False):
            """P4 语义：组内每个策略声明行全部编译失败（unsolved goals）。

            旧版 mock 写死 error 行号 3:0（落在 import 块区）——P4 行号解析
            （错误行 < 首个声明行 = 文件级/环境问题 → 宁放行不反馈）后不再
            代表"策略全部失败"，本 mock 按真实 code 动态把每个 ":=" 声明行
            标注为 unsolved goals，等价真实编译输出。
            """
            errs = []
            for i, ln in enumerate(str(code).split("\n"), start=1):
                if ":=" in ln and " by " in ln:
                    errs.append(f"{lean_filename}:{i}:0: error: unsolved goals")
            return {"ok": False,
                    "error": "\n".join(errs) if errs
                    else f"{lean_filename}:1:0: error: unsolved goals"}

        fake_bridge = SimpleNamespace(
            lean_available=True,
            _lean_project_dir="D:/mathlib4-last_bump_for_v4.31.0",
            _compile=_fake_compile)
        with patch("tools.lean_local.lean_bridge.LeanBridge",
                   return_value=fake_bridge):
            fb = ag._check_assert_verify(
                ctx, "本步 <check>2^10 = 1025</check>")
        self.assertIn("1024", fb)          # 携带正确值
        self.assertIn("Lean", fb)          # 双确认背书
        self.assertEqual(ctx.metadata.get("numeric_lean_count"), 1)

    def test_correct_assert_no_lean_cost(self):
        """正确断言 sympy 直接放行，不触发 Lean 编译（0 成本）。"""
        ag = _agent()
        ctx = TaskContext(problem="p", metadata={})
        ctx.deadline = time.time() + 1000
        with patch("agent.sub_goal_solver.SubGoalSolverAgent"
                   "._lean_backup_fails") as m:
            fb = ag._check_assert_verify(
                ctx, "本步 <check>2^10 = 1024</check>")
        self.assertEqual(fb, "")
        m.assert_not_called()


class AssignmentGuardTest(unittest.TestCase):
    """2026-09-08 smoke10 实证：<check>x = 5</check> 是赋值结果非恒等断言，
    必须 unknown 放行，绝不能误报 fail（把对的改错）。"""

    def setUp(self):
        self.ag = _agent()

    def test_assignment_forms_unknown(self):
        for L, R in [("x", "5"), ("5", "x"), ("s", "265/247"),
                     ("n", "4"), ("X", "2")]:
            v, _ = self.ag._sympy_judge(L, R)
            self.assertEqual(v, "unknown", f"{L} = {R} 应 unknown 放行")

    def test_real_identities_still_judged(self):
        self.assertEqual(self.ag._sympy_judge("2^10", "1024")[0], "pass")
        self.assertEqual(self.ag._sympy_judge("(x-1)*(x+2)", "x^2+x-2")[0],
                         "pass")
        v, _ = self.ag._sympy_judge("2^10", "1025")
        self.assertEqual(v, "fail")
