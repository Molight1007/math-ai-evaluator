# -*- coding: utf-8 -*-
"""回归测试（v2.9）：Lean 前置形式化验证 + 子目标细化结构化输出。

覆盖：allow_sorry 声明编译、formalize_problem 降级/通过、LeanPreVerifier 修正循环
与安全降级、TaskContext 新字段默认值。全部不依赖真实 Lean 环境或 LLM。
"""
import os
import sys
import tempfile
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _make_ctx(problem="证明：根号 2 是无理数", domain="证明", budget_calls=50):
    from agent.base import TaskContext, Budget
    return TaskContext(
        problem=problem, metadata={}, domain=domain,
        budget=Budget(max_calls=budget_calls),
    )


def test_imports():
    """改动/新增模块可正常导入（无语法/循环导入错误）。"""
    import agent.lean_bridge         # noqa: F401
    import agent.lean_pre_verifier   # noqa: F401
    import agent.sub_goal_solver     # noqa: F401
    import agent.orchestrator        # noqa: F401
    import prompts.lean_pre_verify   # noqa: F401


def test_compile_lean_allow_sorry():
    """声明模式（allow_sorry=True）下含 sorry 的定理声明应编译通过。"""
    from agent import lean_bridge
    code = "import Mathlib\n\ntheorem t : True := by\n  sorry\n"
    fake_run = mock.MagicMock(returncode=0, stderr="", stdout="")
    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(lean_bridge.subprocess, "run", return_value=fake_run):
            r_strict = lean_bridge._compile_lean(code, d, allow_sorry=False)
            assert r_strict["ok"] is False, r_strict  # 后置证明模式：含 sorry 视为失败
            r_decl = lean_bridge._compile_lean(code, d, allow_sorry=True)
            assert r_decl["ok"] is True, r_decl      # 声明模式：含 sorry 仍通过


def test_formalize_problem_lean_unavailable():
    """Lean 环境不可用 → formalize_problem 降级 unknown。"""
    from agent.lean_bridge import LeanBridge
    bridge = LeanBridge(client=mock.MagicMock(), config=mock.MagicMock(), budget=None)
    with mock.patch.object(LeanBridge, "lean_available",
                           new_callable=mock.PropertyMock, return_value=False):
        r = bridge.formalize_problem("证明根号 2 是无理数")
        assert r["verdict"] == "unknown"
        assert r["error"] == "Lean 环境不可用"


def test_formalize_problem_ok():
    """声明编译通过 → formalize_problem 返回 ok。"""
    from agent.lean_bridge import LeanBridge
    bridge = LeanBridge(client=mock.MagicMock(), config=mock.MagicMock(), budget=None)
    with mock.patch.object(LeanBridge, "lean_available",
                           new_callable=mock.PropertyMock, return_value=True), \
         mock.patch.object(bridge, "_formalize_to_lean",
                           return_value={"formal_spec": "条件→结论",
                                         "lean_code": "import Mathlib\ntheorem t : True := by\n  sorry"}), \
         mock.patch("agent.lean_bridge._compile_lean", return_value={"ok": True, "error": ""}):
        r = bridge.formalize_problem("题目")
        assert r["verdict"] == "ok", r
        assert r["formal_spec"] == "条件→结论"


def test_preverify_disabled():
    """开关关闭 → 前置验证直接跳过，preverify_trace 标记 disabled。"""
    from agent.lean_pre_verifier import LeanPreVerifier

    class _Cfg:
        enable_lean_preverify = False

    agent = LeanPreVerifier(client=mock.MagicMock(), config=_Cfg())
    ctx = _make_ctx()
    agent.run(ctx)
    assert ctx.preverify_trace == {"enabled": False}
    assert ctx.formal_spec == ""


def test_preverify_budget_zero_still_runs():
    """2026-09-03 预算解除：预算=0 不再阻断前置形式化。

    原 test_preverify_budget_exhausted 断言"预算耗尽→unknown+预算不足"——
    预算闸门已删，该行为不复存在。现验证：预算=0 时流程照常执行，
    结果取决于 bridge 实际返回（mock 为 ok → verdict=ok）。
    """
    from agent.lean_pre_verifier import LeanPreVerifier

    class _Cfg:
        enable_lean_preverify = True
        preverify_max_rounds = 2
        preverify_timeout = 60.0

    agent = LeanPreVerifier(client=mock.MagicMock(), config=_Cfg())
    ctx = _make_ctx(budget_calls=0)  # 预算=0（历史语义：已耗尽）
    fake_bridge = mock.MagicMock()
    fake_bridge.formalize_problem.return_value = {
        "verdict": "ok", "lean_code": "code",
        "formal_spec": "已知条件→结论", "error": ""}
    with mock.patch.object(agent, "_build_bridge", return_value=fake_bridge):
        agent.run(ctx)
    assert ctx.preverify_trace["verdict"] == "ok"


def test_preverify_time_critical_skips():
    """真实跳过条件：时间紧迫（is_time_critical=True）→ 降级 unknown。"""
    import time as _t
    from agent.lean_pre_verifier import LeanPreVerifier

    class _Cfg:
        enable_lean_preverify = True
        preverify_max_rounds = 2
        preverify_timeout = 60.0

    agent = LeanPreVerifier(client=mock.MagicMock(), config=_Cfg())
    ctx = _make_ctx()
    ctx.deadline = _t.time() - 1  # 真实时间戳已过期
    agent.run(ctx)
    assert ctx.preverify_trace["verdict"] == "unknown"
    assert "时间" in ctx.preverify_trace["error"]


def test_preverify_ok_writes_formal_spec():
    """前置验证通过 → 写入 ctx.formal_spec 与 preverify_trace。"""
    from agent.lean_pre_verifier import LeanPreVerifier

    class _Cfg:
        enable_lean_preverify = True
        preverify_max_rounds = 2
        preverify_timeout = 60.0

    agent = LeanPreVerifier(client=mock.MagicMock(), config=_Cfg())
    ctx = _make_ctx()
    fake_bridge = mock.MagicMock()
    fake_bridge.formalize_problem.return_value = {
        "verdict": "ok", "lean_code": "code",
        "formal_spec": "已知条件→结论", "error": ""}
    with mock.patch.object(agent, "_build_bridge", return_value=fake_bridge):
        agent.run(ctx)
    assert ctx.preverify_trace["verdict"] == "ok"
    assert ctx.formal_spec == "已知条件→结论"


def test_preverify_fail_then_ok_retry():
    """失败后带反馈重试，第二轮通过（修正循环）。"""
    from agent.lean_pre_verifier import LeanPreVerifier

    class _Cfg:
        enable_lean_preverify = True
        preverify_max_rounds = 2
        preverify_timeout = 60.0

    agent = LeanPreVerifier(client=mock.MagicMock(), config=_Cfg())
    ctx = _make_ctx()
    fake_bridge = mock.MagicMock()
    # 第一轮 fail（带编译错误），第二轮 ok
    fake_bridge.formalize_problem.side_effect = [
        {"verdict": "fail", "lean_code": "bad", "formal_spec": "",
         "error": "unknown identifier 'x'"},
        {"verdict": "ok", "lean_code": "good", "formal_spec": "修正后的条件→结论",
         "error": ""},
    ]
    with mock.patch.object(agent, "_build_bridge", return_value=fake_bridge):
        agent.run(ctx)
    assert ctx.preverify_trace["verdict"] == "ok"
    assert ctx.preverify_trace["rounds"] == 1
    assert ctx.formal_spec == "修正后的条件→结论"


def test_taskcontext_new_fields():
    """TaskContext 新字段默认值正确。"""
    from agent.base import TaskContext
    ctx = TaskContext(problem="x", metadata={})
    assert ctx.formal_spec == ""
    assert ctx.preverify_trace == {}
    assert ctx.subgoal_trace == []
    assert ctx.subgoal_merge_plan == ""


if __name__ == "__main__":
    _tests = [(k, v) for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for name, fn in _tests:
        fn()
        print(f"PASS {name}")
    print(f"ALL {len(_tests)} TESTS PASSED")
