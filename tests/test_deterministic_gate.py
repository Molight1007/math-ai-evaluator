# -*- coding: utf-8 -*-
"""回归测试（v2.8 增量移植）：确定性硬否决 / AcceptGate 门控 / RunState 覆盖 / LeanGate 扩展。

可直接 `python tests/test_deterministic_gate.py` 运行，也可被 pytest 收集。
"""
import os
import sys

# 确保能 import 根目录的 agent / utils / prompts 包
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_imports():
    """所有被改动的模块均可正常导入（无语法/循环导入错误）。"""
    import agent.base            # noqa: F401
    import agent.deterministic   # noqa: F401
    import agent.verifier        # noqa: F401
    import agent.orchestrator    # noqa: F401
    import agent.solver          # noqa: F401
    import agent.difficulty_router  # noqa: F401
    import agent.lean_gate       # noqa: F401


def test_deterministic_check_answer():
    """确定性硬否决：方程根应 pass，错误根应 fail，无法解析应 unknown。"""
    from agent.deterministic import DeterministicChecker
    c = DeterministicChecker()
    r2 = c.check_answer(None, "求解方程 x^2-5x+6=0", "2")
    assert r2["verdict"] == "pass", r2
    r3 = c.check_answer(None, "求解方程 x^2-5x+6=0", "3")
    assert r3["verdict"] == "pass", r3
    r5 = c.check_answer(None, "求解方程 x^2-5x+6=0", "5")
    assert r5["verdict"] == "fail", r5
    runk = c.check_answer(None, "求解方程 x^2-5x+6=0", "【不适用】")
    assert runk["verdict"] == "unknown", runk


def test_verify_by_substitution():
    from agent.deterministic import DeterministicChecker
    c = DeterministicChecker()
    r = c.verify_by_substitution("x^2+2x+1=(x+1)^2")
    assert r["verdict"] == "pass", r


def test_search_counterexample():
    from agent.deterministic import DeterministicChecker
    c = DeterministicChecker()
    r = c.search_counterexample("n > 10")
    assert r["found"] is True, r


def test_roundstate_acceptgate():
    from agent.base import RoundState
    rs = RoundState()
    d = "HOLD"
    for _ in range(5):
        d = rs.update(is_pass=True)
    assert d == "ACCEPT", d

    rs2 = RoundState()
    d2 = "HOLD"
    for _ in range(10):
        d2 = rs2.update(is_pass=False, has_major_defect=True)
    assert d2 == "REJECT", d2


def test_taskcontext_state_defaults():
    from agent.base import TaskContext, RunState, RoundState
    ctx = TaskContext(problem="x", metadata={})
    assert isinstance(ctx.state, RunState)
    assert isinstance(ctx.round_state, RoundState)
    assert ctx.state.emergency is False
    assert ctx.round_state.decision == "HOLD"


def test_verdict_deterministic_field():
    from agent.base import Verdict
    v = Verdict(correct=False, deterministic={"verdict": "fail"})
    assert v.deterministic["verdict"] == "fail"


def test_leangate_enabled_all_proofs():
    from agent.lean_gate import LeanGate

    class _CfgAll:
        enable_lean_verify = True
        lean_gate_all_proofs = True

    class _CfgDeepOnly:
        enable_lean_verify = True
        lean_gate_all_proofs = False
        lean_gate_nonproof_deep_only = True

    g1 = LeanGate.__new__(LeanGate)
    g1.config = _CfgAll()
    assert g1._enabled("standard", "证明") is True
    assert g1._enabled("deep", "证明") is True
    # 2026-09-01 用户要求「所有题目都要用到 Lean」：非证明题默认全档启用
    # （走轻量 verify_answer）。旧行为由 lean_gate_nonproof_deep_only=True 保留。
    assert g1._enabled("standard", "计算") is True
    assert g1._enabled("standard", "计算", "解答题") is True

    g2 = LeanGate.__new__(LeanGate)
    g2.config = _CfgDeepOnly()
    assert g2._enabled("standard", "证明") is False
    assert g2._enabled("deep", "证明") is True
    # 非证明题仅 deep 档（旧行为回退开关）
    assert g2._enabled("standard", "计算") is False
    assert g2._enabled("deep", "计算") is True


if __name__ == "__main__":
    _tests = [(k, v) for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for name, fn in _tests:
        fn()
        print(f"PASS {name}")
    print(f"ALL {len(_tests)} TESTS PASSED")
