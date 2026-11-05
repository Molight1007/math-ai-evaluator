# -*- coding: utf-8 -*-
"""E34 构造用例：Lean 闭环（编译器硬错误驱动一次带反馈重证）。

不依赖 LLM / Lean 真编译 —— 用 FakeSolver 把 `_tool_declared_verify`
（返回反馈）与 `_solve_subgoal`（返回重解文本）接管，验证：

  · `verify_and_mark` 把反馈文本返回给主循环（单一职责：核验+留痕+返回）；
  · 异常路径按契约层口径显式否决（绝不静默放行）；
  · `_maybe_lean_reclose` 仅在 `tool=lean` + 真编译失败（无 tool_not_run_reason）
    时触发重解，且重解后再过一次核验；
  · 决定性反例：sympy 的失败不重解；环境未真跑（tool_not_run_reason）不重解；
    重解文本过短视为无效；空反馈不重解。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subgoal_collab import verify_and_mark, _maybe_lean_reclose


class _Raise:
    """哨兵：让 `_tool_declared_verify` 抛异常的注入标记。"""
    pass


_RAISE = _Raise()


class _FakeCtx:
    pass


class _FakeSolver:
    def __init__(self, verify_fb="", solve_out="", solve_raises=False):
        self._verify_fb = verify_fb
        self._solve_out = solve_out
        self._solve_raises = solve_raises
        self.verify_calls = 0
        self.solve_calls = 0
        self.verify_args = []
        self.solve_args = []
        self.records = []

    def _tool_declared_verify(self, ctx, sg, text):
        self.verify_calls += 1
        self.verify_args.append((sg, text))
        if self._verify_fb is _RAISE:
            raise RuntimeError("verify boom")
        return self._verify_fb

    def _solve_subgoal(self, ctx, sg, plan, done_digest, fb):
        self.solve_calls += 1
        self.solve_args.append((sg, fb))
        if self._solve_raises:
            raise RuntimeError("solve boom")
        return self._solve_out

    def record(self, ctx, tag, msg):
        self.records.append((tag, msg))


def test_verify_and_mark_returns_fb():
    s = _FakeSolver(verify_fb="【Lean 编译未通过】第 3 行：error: ...")
    sg = {"tool": "lean"}
    fb = verify_and_mark(s, _FakeCtx(), sg, "some result text")
    assert fb == "【Lean 编译未通过】第 3 行：error: ...", fb
    assert s.verify_calls == 1


def test_verify_and_mark_exception_is_explicit_deny():
    s = _FakeSolver(verify_fb=_RAISE)
    sg = {}
    fb = verify_and_mark(s, _FakeCtx(), sg, "text")
    assert fb == ""                       # 异常路径无反馈可返
    assert sg.get("sig_gate_allowed") is False
    assert sg.get("sig_gate_stage") == "UNAVAILABLE"
    assert sg.get("tool_ran") is False
    assert "UNAVAILABLE" in str(sg.get("tool_verdict", ""))


def test_reclose_triggers_on_lean_real_fail():
    s = _FakeSolver(verify_fb="【Lean 编译未通过】第 3 行：error: type mismatch",
                    solve_out=">40 " + "字" * 60)
    sg = {"tool": "lean"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == s._solve_out
    assert s.solve_calls == 1
    # 重证后必须再过一次核验（复核闭合层级）
    assert s.verify_calls == 1
    assert any("重证" in m for _, m in s.records)


def test_reclose_skips_sympy_fail():
    s = _FakeSolver(verify_fb="【SymPy 符号核验未通过】...", solve_out="x" * 80)
    sg = {"tool": "sympy"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == ""                       # 不重解
    assert s.solve_calls == 0


def test_reclose_skips_not_really_run():
    s = _FakeSolver(verify_fb="【Lean 编译未通过】...", solve_out="x" * 80)
    sg = {"tool": "lean", "tool_not_run_reason": "lean-unavailable"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == ""                       # 环境未真跑不重解
    assert s.solve_calls == 0


def test_reclose_skips_short_resolve():
    s = _FakeSolver(verify_fb="【Lean 编译未通过】...", solve_out="短文本")
    sg = {"tool": "lean"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == ""                       # 重解无效（≤40字）
    assert s.solve_calls == 1              # 调了，但被长度门槛挡下


def test_reclose_skips_empty_fb():
    s = _FakeSolver(verify_fb="", solve_out="x" * 80)
    sg = {"tool": "lean"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == ""
    assert s.solve_calls == 0


def test_reclose_solve_raises_is_safe():
    s = _FakeSolver(verify_fb="【Lean 编译未通过】...", solve_raises=True)
    sg = {"tool": "lean"}
    out = _maybe_lean_reclose(s, _FakeCtx(), sg, s._verify_fb, "plan", "done", "T")
    assert out == ""                       # 重解异常不崩溃
