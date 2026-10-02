"""截图 #10 落实测试：统一工具调用门面（ToolGateway）。

用户原话：
  「调用工具的方法有没有写成**规范性的类函数**，需要 Lean 检测时直接调用，适配各阶段」

本文件锁住门面的**契约**（而不仅是"能跑"）：
  ① 所有方法返回 `ToolResult`，**绝不抛异常**（工具问题不得阻断主流程）；
  ② `reason` 取值必须落在**闭合原因码集合**内（归因可聚合的前提）；
  ③ **三态可区分**：没跑 / 跑了成功 / 跑了失败 —— 本项目反复吃亏的假阴性模式；
  ④ `for_ctx` 按 ctx 缓存（同题共享遥测、跨题隔离）；
  ⑤ `lean_check_statement` 正确构造 `example : (...) := by sorry`（挖空检测）；
  ⑥ `calc` 必须区分"算出数值"与"返回错误说明串"（典型假阳性陷阱）。

⚠ 每个核心断言都配**阳性对照**。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tool_gateway import (
    REASON_BUDGET,
    REASON_DISABLED,
    REASON_EMPTY,
    REASON_NOT_APPLICABLE,
    REASON_OK,
    REASON_UNAVAILABLE,
    _ALL_REASONS,
    ToolGateway,
    ToolResult,
)


class _Ctx:
    """最小 ctx 替身（门面只依赖 trace / _tool_gateway 两个属性）。"""

    def __init__(self):
        self.trace = []


class _Cfg:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class ToolResultContractTest(unittest.TestCase):
    """① + ② 契约本身。"""

    def test_to_dict_is_json_serializable(self):
        import json
        r = ToolResult(tool="t", ok=True, value={"a": 1, "b": [1, 2]},
                       meta={"x": "y"})
        json.dumps(r.to_dict())          # 不抛 = 可落盘

    def test_to_dict_truncates_long_value(self):
        r = ToolResult(tool="t", value="x" * 5000)
        self.assertLessEqual(len(r.to_dict()["value"]), 300)

    def test_reason_set_is_closed(self):
        """★ 原因码是**闭合集合** —— 归因脚本可穷举，不会出现野生取值。"""
        self.assertIsInstance(_ALL_REASONS, tuple)
        self.assertIn(REASON_OK, _ALL_REASONS)
        self.assertEqual(len(set(_ALL_REASONS)), len(_ALL_REASONS),
                         "原因码不得重复")

    def test_ran_distinguishes_not_run_from_failed(self):
        """★★ 三态核心：'没跑' 与 '跑了失败' 必须可区分。

        本项目实测教训：`Lean 没跑` 与 `Lean 跑完判 unknown` 在日志里
        长得一样 → 假阴性被读成"没问题"。`ran` 是拆开这两态的唯一入口。
        """
        not_run = ToolResult(reason=REASON_UNAVAILABLE)
        not_run2 = ToolResult(reason=REASON_DISABLED)
        not_run3 = ToolResult(reason=REASON_BUDGET)
        ran_fail = ToolResult(reason="reject")
        ran_ok = ToolResult(reason=REASON_OK)
        for r in (not_run, not_run2, not_run3):
            self.assertFalse(r.ran, "未跑的情形 ran 必须为 False")
        self.assertTrue(ran_fail.ran, "跑了但失败 ⇒ ran 必须为 True")
        self.assertTrue(ran_ok.ran)

    def test_positive_control_ran_would_catch_always_true(self):
        """★ 阳性对照：若 `ran` 退化成恒 True，本断言应红。"""
        self.assertFalse(ToolResult(reason=REASON_DISABLED).ran)


class GatewayCachingTest(unittest.TestCase):
    """④ 按 ctx 缓存。"""

    def test_for_ctx_returns_same_instance(self):
        c = _Ctx()
        self.assertIs(ToolGateway.for_ctx(c), ToolGateway.for_ctx(c))

    def test_different_ctx_get_different_instances(self):
        """★ 跨题必须隔离 —— 否则调用计数串台，归因全错。"""
        a, b = _Ctx(), _Ctx()
        self.assertIsNot(ToolGateway.for_ctx(a), ToolGateway.for_ctx(b))

    def test_late_client_config_is_backfilled(self):
        c = _Ctx()
        gw = ToolGateway.for_ctx(c)
        self.assertIsNone(gw.client)
        _cli = object()
        gw2 = ToolGateway.for_ctx(c, client=_cli, config=_Cfg())
        self.assertIs(gw, gw2)
        self.assertIs(gw.client, _cli)

    def test_for_ctx_never_raises_on_hostile_ctx(self):
        """ctx 不让挂属性时也必须返回可用实例（不抛）。"""
        class _Bad:
            def __setattr__(self, k, v):
                raise RuntimeError("nope")
        try:
            gw = ToolGateway.for_ctx(_Bad())
        except Exception as e:  # noqa: BLE001
            self.fail(f"for_ctx 不应抛异常: {e!r}")
        self.assertIsInstance(gw, ToolGateway)


class NeverRaisesTest(unittest.TestCase):
    """① 所有入口对垃圾输入都不抛异常。"""

    def setUp(self):
        self.gw = ToolGateway.for_ctx(_Ctx())

    def test_all_entrypoints_on_empty(self):
        """空输入不得抛异常；原因码必须是**闭合集合内的**合法值。

        ⚠ 有意**不**断言所有入口都返回 `empty`：`lean_compile("")` 在本机
        （无 Lean）会返回 `unavailable` —— 这是**正确的优先级**：
        "环境根本没有 Lean" 比 "这次传了空代码" 更根本，先说更根本的那条。
        强行让它返回 empty 反而会掩盖"环境缺失"这一真问题。
        """
        for name, args in (("lean_compile", (None,)),
                           ("lean_check_statement", ("",)),
                           ("search_mathlib", ("",)),
                           ("calc", ("",))):
            fn = getattr(self.gw, name)
            try:
                r = fn(*args)
            except Exception as e:  # noqa: BLE001
                self.fail(f"{name} 不应抛异常: {e!r}")
            self.assertIsInstance(r, ToolResult)
            self.assertIn(r.reason, _ALL_REASONS,
                          f"{name} 返回了闭合集合外的原因码")
            self.assertFalse(r.ok, f"{name} 空输入不得判成功")

    def test_calc_junk_expression_does_not_raise(self):
        r = self.gw.calc("这不是一个数学表达式!!!")
        self.assertIsInstance(r, ToolResult)
        self.assertFalse(r.ok)
        self.assertNotEqual(r.reason, REASON_OK)

    def test_lean_compile_without_lean_returns_unavailable_not_error(self):
        """★ Lean 环境缺失 ⇒ `unavailable`（环境问题），**不是** `error`（调用失败）。

        这两者归因方向完全相反：前者该去装 Lean，后者该查代码。
        """
        r = self.gw.lean_compile("def f := 1")
        if not self.gw.pure_lean_available():
            self.assertEqual(r.reason, REASON_UNAVAILABLE)
            self.assertFalse(r.available)
            self.assertFalse(r.ran, "环境缺失 = 没跑")
        else:
            self.assertTrue(r.ran)


class LeanStatementCheckTest(unittest.TestCase):
    """⑤ 挖空检测（用户 #6 的机制）。"""

    def setUp(self):
        self.gw = ToolGateway.for_ctx(_Ctx())

    def test_constructs_example_by_sorry(self):
        """★ 核心：调用方只给命题，门面负责拼 `example : (...) := by sorry`。

        拼错（如漏 `sorry`）会让编译失败被误读成"命题不成立" ⇒ 假阴性。
        """
        captured = {}

        def _fake_compile(code, step="", timeout=120.0):
            captured["code"] = code
            return ToolResult(tool="lean.compile", ok=True, reason=REASON_OK)

        self.gw.lean_compile = _fake_compile            # type: ignore[assignment]
        self.gw.lean_check_statement("1 + 1 = 2")
        self.assertIn("example : (1 + 1 = 2)", captured["code"])
        self.assertIn("by sorry", captured["code"])

    def test_passes_through_full_lean_code(self):
        """已写成 example/theorem 的则**原样**送编译（不再套一层括号）。"""
        captured = {}

        def _fake_compile(code, step="", timeout=120.0):
            captured["code"] = code
            return ToolResult(tool="lean.compile", ok=True, reason=REASON_OK)

        self.gw.lean_compile = _fake_compile            # type: ignore[assignment]
        orig = "example : 1 + 1 = 2 := by norm_num"
        self.gw.lean_check_statement(orig)
        self.assertEqual(captured["code"], orig)

    def test_positive_control_would_catch_missing_sorry(self):
        """★ 阳性对照：若拼串漏掉 `by sorry`，上面的断言应红。"""
        captured = {}

        def _fake_compile(code, step="", timeout=120.0):
            captured["code"] = code
            return ToolResult(tool="lean.compile", ok=True, reason=REASON_OK)

        self.gw.lean_compile = _fake_compile            # type: ignore[assignment]
        self.gw.lean_check_statement("True")
        self.assertNotEqual(captured["code"], "example : (True)",
                            "漏 `by sorry` ⇒ 编译失败会被误读成命题不成立")


class CalcFalsePositiveTest(unittest.TestCase):
    """⑥ calc 必须区分"数值结果"与"错误说明串"。"""

    def setUp(self):
        self.gw = ToolGateway.for_ctx(_Ctx())

    def test_plain_arithmetic_is_ok(self):
        r = self.gw.calc("123*456")
        self.assertTrue(r.ok)
        self.assertEqual(r.reason, REASON_OK)
        self.assertEqual(str(r.value), "56088")

    def test_error_string_is_not_reported_as_ok(self):
        """★ 核心：`safe_eval` 失败时返回的是**中文错误说明**。

        若不做区分，`ok=True` 且 `value="无法解析表达式"` 会被下游当成
        "算出来了一个字符串结果" —— 典型假阳性。
        """
        r = self.gw.calc("@#$$%^&*")
        self.assertFalse(r.ok, "错误说明串不得被当成成功结果")
        self.assertNotEqual(r.reason, REASON_OK)

    def test_positive_control_would_catch_always_ok(self):
        """★ 阳性对照：若 calc 恒返回 ok=True，本断言应红。"""
        r = self.gw.calc("@#$$%^&*")
        self.assertNotEqual(r.reason, REASON_OK)


class NoteApplicableTest(unittest.TestCase):
    """题面不适用 Lean（豁免题）必须与"环境缺失"区分。"""

    def test_not_applicable_reason(self):
        c = _Ctx()
        c._lean_applicable_override = False
        gw = ToolGateway.for_ctx(c, config=_Cfg(enable_lean_verify=True))
        # 环境可用时才会走到"题面不适用"这一支
        if gw.pure_lean_available():
            r = gw.lean_compile("def f := 1")
            self.assertEqual(r.reason, REASON_NOT_APPLICABLE)
            self.assertFalse(r.ran)
        else:
            self.skipTest("本机无 Lean，'题面不适用'分支不可达")


class TelemetryTest(unittest.TestCase):
    """遥测（诊断报告「工具使用」维度的数据源）。"""

    def test_stats_aggregates_by_tool_and_reason(self):
        c = _Ctx()
        gw = ToolGateway.for_ctx(c)
        gw.calc("1+1")
        gw.calc("")
        s = gw.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_tool"].get("calc"), 2)
        self.assertGreaterEqual(s["by_reason"].get(REASON_OK, 0), 1)
        self.assertGreaterEqual(s["by_reason"].get(REASON_EMPTY, 0), 1)

    def test_summarize_safe_without_gateway(self):
        """无门面时返回零值结构（诊断报告可无脑调用）。"""
        s = ToolGateway.summarize(_Ctx())
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["by_tool"], {})

    def test_failures_are_written_to_ctx_trace(self):
        """★ 失败必须留痕 —— 否则"工具没跑起来"在报告里查不到。"""
        c = _Ctx()
        gw = ToolGateway.for_ctx(c)
        gw.calc("")
        self.assertTrue(any(isinstance(t, dict) and t.get("reason")
                            for t in c.trace),
                        "失败调用应写入 ctx.trace")


if __name__ == "__main__":
    unittest.main()
