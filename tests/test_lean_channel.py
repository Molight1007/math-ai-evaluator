# -*- coding: utf-8 -*-
"""Lean 双通道单测（2026-09-06 晚恢复）。

覆盖：
1) _lean_active 三态：LEAN_VERIFY=0 关 / enable_lean_verify=False 关 /
   lean 环境可用（打桩）→ 开；
2) LeanGate.gate_final_answer 的 entry 带 step="final_gate"
   （orchestrator 6.5 回环反馈读取兼容 lean/audit 两后端）；
3) LEAN_VERIFY 逃生门不影响 AuditGate 路径（回落语义 = 现有全量测试回归）。

lean 真实验证链路（编译/LLM 翻译）属集成行为，见本地冒烟，不在单测范围。
"""
import os

import pytest

from agent.base import TaskContext
from user_agent import AgentConfig


def _make_agent_config(**kw):
    kw.setdefault("enable_audit_gate", True)
    return AgentConfig(**kw)


class _DummyClient:
    """零能力 client：lean 链路里 LLM 翻译返回空（翻译失败 → unknown 放行）。"""

    def chat(self, messages=None, temperature=0.0, max_tokens=1, **kw):
        return None


# ----------------------------------------------------------------------
# 1) orchestrator._lean_active 三态
# ----------------------------------------------------------------------
def _orchestrator(monkeypatch, cfg=None, lean_module=True):
    monkeypatch.setattr("agent.orchestrator._LEAN_MODULES_OK", lean_module)
    from agent.orchestrator import Orchestrator
    orch = Orchestrator(_DummyClient(), cfg or _make_agent_config())
    orch._lean_probe = None
    return orch


def test_lean_active_env_off(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "0")
    orch = _orchestrator(monkeypatch)
    assert orch._lean_active() is False


def test_lean_active_config_off(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    cfg = _make_agent_config(enable_lean_verify=False)
    orch = _orchestrator(monkeypatch, cfg)
    assert orch._lean_active() is False


def test_lean_active_probe_unavailable_falls_back(monkeypatch):
    """Lean 环境探测失败 → `_lean_active()` False（回落 AuditGate）。

    2026-09-10 变更说明：`_lean_active()` 首行新增 `_ensure_lean_modules()`
    「首用自愈」（治循环导入静默禁用），原「模块缺失 → 永久 False」前提
    不再成立（模块会被重建）。故改为验证真正的回落语义：环境不可用即关闭。
    另保留 LEAN_VERIFY=0 与 config 关闭两条独立路径的覆盖（见上两个用例）。
    """
    monkeypatch.setenv("LEAN_VERIFY", "1")
    orch = _orchestrator(monkeypatch, _make_agent_config())

    class _FakeBridge:
        lean_available = False

    orch.lean_gate._bridge = _FakeBridge()
    assert orch._lean_active() is False
    assert orch._lean_probe is False


def test_lean_active_env_on_and_probe_ok(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    orch = _orchestrator(monkeypatch, _make_agent_config())
    # 打桩 bridge：lean_available=True → lean 通道激活
    class _FakeBridge:
        lean_available = True
    orch.lean_gate._bridge = _FakeBridge()
    assert orch._lean_active() is True
    # 结果缓存：第二次不再重探
    assert orch._lean_probe is True


# ----------------------------------------------------------------------
# 2) LeanGate.gate_final_answer entry 兼容（step=final_gate）
# ----------------------------------------------------------------------
def test_lean_gate_final_entry_step(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config())
    ctx = TaskContext(problem="计算 1+1", metadata={})
    ctx.domain = ""
    ctx.question_type = "解答题"
    # 空答案 → 放行，且 entry 写 ctx.lean_gate 且带 step=final_gate
    assert gate.gate_final_answer(ctx, "standard", "  ") is True
    entries = list(getattr(ctx, "lean_gate", []) or [])
    assert entries, "空答案也应留记录"
    assert entries[-1].get("step") == "final_gate"


def test_lean_gate_final_reject_entry(monkeypatch):
    """proof_invalid → False，entry verdict 供 6.5 回环读取（verdict∈拒绝集）。"""
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config())
    ctx = TaskContext(problem="求 f(2)，题目数字 42", metadata={})
    ctx.domain = ""
    ctx.question_type = "解答题"

    class _FakeBridge:
        lean_available = True

        def verify_answer(self, **kw):
            class _R:
                verdict = "proof_invalid"
                findings = []
                suggestion = "逻辑错误：42 代入后不等"
                lean_code = ""
            return _R()

    gate._bridge = _FakeBridge()
    assert gate.gate_final_answer(ctx, "deep", "0", "步骤……") is False
    entries = list(getattr(ctx, "lean_gate", []) or [])
    rej = [e for e in entries
           if e.get("step") == "final_gate"
           and e.get("verdict") in ("reject", "proof_invalid", "unknown")]
    assert rej, "拒绝路径 entry 应可被 6.5 回环识别"
    assert "42" in (rej[-1].get("feedback") or "") or rej[-1].get("feedback")


# ----------------------------------------------------------------------
# 3) LEAN_VERIFY 逃生门：关 lean 后 gate 仍为 audit（回落）
# ----------------------------------------------------------------------
def test_env_off_keeps_audit_gate(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "0")
    from agent.orchestrator import Orchestrator
    cfg = _make_agent_config()
    orch = Orchestrator(_DummyClient(), cfg)
    assert orch._lean_active() is False
    assert orch.audit_gate is not None


# ----------------------------------------------------------------------
# 4) LeanGate.apply 连续 unknown 止损（B，2026-09-07）
#    PB-002 实证：6 候选整题 verify 563s 全 unknown 白烧 → 连续 2 个
#    unknown 后剩余候选 verify_stop，不再逐个整题 verify。
# ----------------------------------------------------------------------
from types import SimpleNamespace


def _mk_cands(n):
    return [SimpleNamespace(id=i, answer=f"ans{i}", reasoning=f"推理{i}",
                            confidence=0.5) for i in range(n)]


def _disable_prefetch(monkeypatch):
    """关掉候选级并行预取（2026-09-13 新增能力）。

    本组用例锁的是**顺序止损语义**（"连续 N 个 unknown 后不再逐个 verify"）——
    那是主循环的行为，与预取无关。预取按波提交，天然会多验 ≤K-1 个候选
    （波宽代价），该行为由 test_apply_parallel_prefetch_same_outcome 单独锁定。
    """
    monkeypatch.setenv("LEAN_GATE_PARALLEL", "0")


def _gate_with_verify(monkeypatch, verdict="unknown", stop=2, strict=False):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    _disable_prefetch(monkeypatch)
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config(
        lean_gate_unknown_stop=stop, lean_gate_strict=strict))

    calls = {"n": 0}

    class _FakeBridge:
        lean_available = True

        def verify(self, **kw):
            calls["n"] += 1
            r = SimpleNamespace(verdict=verdict, findings=[], suggestion="",
                                lean_code="")
            return r

    gate._bridge = _FakeBridge()
    return gate, calls


def test_apply_stops_after_2_unknown(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=2)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    ctx.question_type = ""
    kept, fb = gate.apply(ctx, "standard", _mk_cands(6))
    # ★ 2026-10-17（用户定案「删降级/保底」）：不再"止损跳过"，全部候选逐个验证
    assert calls["n"] == 6, "无止损：6 个候选应全部逐个 verify"
    assert len(kept) == 6, "lenient：unknown 全保留"
    obs = [e for e in ctx.lean_gate
           if e.get("degraded") == "unknown_streak_observed"]
    assert obs, "连续 unknown 只记录现象，不跳过验证"
    assert not fb


def test_apply_stop_disabled_verifies_all(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=0)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, _ = gate.apply(ctx, "standard", _mk_cands(6))
    assert calls["n"] == 6, "stop=0 关闭止损，应逐候选全验"
    assert len(kept) == 6


def test_apply_valid_resets_streak(monkeypatch):
    """候选 2 出绿点（valid）→ 计数清零 → 候选 3/4 unknown 只累计 2 不到
    阈值？候选 4 仍验（streak 从 0 数，第 3、4 个 unknown 后候选 5、6 止损）。"""
    calls = {"n": 0, "seq": []}
    monkeypatch.setenv("LEAN_VERIFY", "1")
    _disable_prefetch(monkeypatch)
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config(
        lean_gate_unknown_stop=2))

    class _FakeBridge:
        lean_available = True

        def verify(self, **kw):
            calls["n"] += 1
            calls["seq"].append(calls["n"])
            # 候选 2（第 2 次调用）返回 valid → 计数清零
            if calls["n"] == 2:
                return SimpleNamespace(verdict="proof_valid", findings=[],
                                       suggestion="", lean_code="import Mathlib.Tactic\nexample : True := by trivial\n")
            return SimpleNamespace(verdict="unknown", findings=[],
                                   suggestion="", lean_code="")

    gate._bridge = _FakeBridge()
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, _ = gate.apply(ctx, "standard", _mk_cands(6))
    # 1 unknown(1) → 2 valid(清零) → 3 unknown(1) → 4 unknown(2,达阈值)
    # → 5、6 verify_stop。verify 调用 = 候选 1-4 = 4 次
    # ★ 2026-10-17：无止损 ⇒ 6 个候选全部验证
    assert calls["n"] == 6, f"无止损：应全验 6 个，实际 {calls['n']}"
    assert len(kept) == 6


def test_apply_stop_strict_rejects_rest(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=2,
                                    strict=True)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, fb = gate.apply(ctx, "standard", _mk_cands(6))
    assert calls["n"] == 6, "无止损：全部验证"
    assert len(kept) == 0, "strict：unknown 全拒"
    assert len(fb) == 6, "6 候选全产生拒绝反馈（全部验证）"


# ----------------------------------------------------------------------
# 2026-09-13：候选级并行预取（LEAN_GATE_PARALLEL / LEAN_MCP_WORKERS）
#   并发本身不改变任何决策 —— 该用例把"结果等价 + 超验量有界"钉死。
# ----------------------------------------------------------------------
def _run_gate(monkeypatch, parallel, verdicts, stop=2, strict=False, n=6):
    """跑一遍 apply，返回 (调用次数, kept ids, 逐候选 verdict/degraded)。"""
    monkeypatch.setenv("LEAN_GATE_PARALLEL", "1" if parallel else "0")
    monkeypatch.setenv("LEAN_VERIFY", "1")
    monkeypatch.setenv("LEAN_MCP_WORKERS", "3")
    monkeypatch.setattr("tools.lean_local.lean_gate.mcp_available",
                        lambda: True, raising=False)
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config(
        lean_gate_unknown_stop=stop, lean_gate_strict=strict))
    calls = {"n": 0}

    class _FB:
        lean_available = True

        def verify(self, problem="", reasoning="", domain="", timeout=0):
            calls["n"] += 1
            return SimpleNamespace(
                verdict=verdicts.get(reasoning, "unknown"), findings=[],
                suggestion="", lean_code="")

    gate._bridge = _FB()
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, fb = gate.apply(ctx, "standard", _mk_cands(n))
    sig = [(e.get("id"), e.get("verdict"), e.get("degraded"))
           for e in ctx.lean_gate]
    return calls["n"], [c.id for c in kept], sig, fb


def test_apply_parallel_prefetch_same_outcome(monkeypatch):
    """并行预取：决策逐候选等价于串行；超验量 ≤ 波宽-1。"""
    mixed = {"推理0": "proof_valid", "推理1": "proof_invalid",
             "推理2": "unknown", "推理3": "proof_valid",
             "推理4": "unknown", "推理5": "proof_invalid"}
    s = _run_gate(monkeypatch, False, mixed)
    p = _run_gate(monkeypatch, True, mixed)
    assert s[1] == p[1], "kept 必须一致"
    assert s[2] == p[2], "逐候选 verdict/degraded 必须一致"
    assert s[3] == p[3], "拒绝反馈必须一致"
    assert s[0] == p[0] == 6, "无止损场景两边都应验满"

    # 全 unknown：串行在第 2 个后止损；并行第一波（K=3）后止损
    allunk = dict(("推理%d" % i, "unknown") for i in range(6))
    s = _run_gate(monkeypatch, False, allunk)
    p = _run_gate(monkeypatch, True, allunk)
    assert s[1] == p[1], "止损后的 kept 必须一致"
    assert s[2] == p[2], "止损后的埋点必须一致"
    # ★ 2026-10-17：无止损 ⇒ 串行/并行都全验 6 个
    assert s[0] == 6, "无止损：串行全验 6 个"
    assert p[0] == 6, "无止损：并行也全验 6 个"


# ---------------------------------------------------------------- 2026-10-27
# P0-2：`lean_check` 送编译前必须做 Mathlib import 归一化。
#
# 病灶（队友 10-27 报告 + 本次静态核实）：主链
# `sub_goal_solver__lean._lean_block_verify` 在 `_compile` 前调了
# `_prepend_mathlib_import`，唯独 `tools/agent_toolkit/lean_check.py` 是
# `runner(code, …)` 直送 ⇒ 模型写的 `import Mathlib.Tactic` 在裁剪闭包下
# 必然编译失败（unknown tactic / 缺 LT ℕ）⇒ 「run_code 16/16 全失败」。
# 同一段代码走主链能编、走本工具必败 —— 与编译器可用性无关。
def _stub_runner(seen):
    def _run(code, work_dir, timeout):
        seen["code"] = code
        seen["work_dir"] = work_dir
        return {"ok": True, "items": []}
    return _run


def test_lean_check_normalizes_import_before_runner(monkeypatch):
    """无 import 的代码 → runner 收到的必须已带可用 import 块。"""
    import importlib
    # ★ `from tools.agent_toolkit import lean_check` 拿到的是**函数**（包内
    #   re-export 覆盖了子模块名），要打桩模块属性必须走 import_module。
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (True, "mathlib-ready@stub"))
    seen = {}
    r = _m.lean_check(lean_code="theorem t : 1 = 1 := rfl",
                      work_dir="/stub/proj",
                      runner=_stub_runner(seen))
    assert r["import_norm"]["applied"] is True
    assert "import Mathlib" in seen["code"]
    # 归一化后的代码才是**实际送编译**的，必须同步进 lean_code
    assert r["lean_code"] == seen["code"]
    assert "theorem t : 1 = 1 := rfl" in seen["code"]


def test_lean_check_rewrites_aggregate_entry(monkeypatch):
    """聚合入口 `import Mathlib.Tactic` 在裁剪闭包下必败 → 必须被改写。"""
    import importlib
    # ★ `from tools.agent_toolkit import lean_check` 拿到的是**函数**（包内
    #   re-export 覆盖了子模块名），要打桩模块属性必须走 import_module。
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (True, "mathlib-ready@stub"))
    seen = {}
    r = _m.lean_check(lean_code="import Mathlib.Tactic\ntheorem t : 1 = 1 := rfl",
                      work_dir="/stub/proj", runner=_stub_runner(seen))
    assert r["import_norm"]["applied"] is True
    # 改写目标是**具体模块**（core 闭包无聚合入口 olean）
    assert "import Mathlib.Tactic.NormNum" in seen["code"]
    assert "import Mathlib.Tactic\n" not in seen["code"]


def test_lean_check_keeps_concrete_import_untouched(monkeypatch):
    """已有具体模块导入 → 原样（归一化必须幂等，否则等于改坏用户代码）。"""
    import importlib
    # ★ `from tools.agent_toolkit import lean_check` 拿到的是**函数**（包内
    #   re-export 覆盖了子模块名），要打桩模块属性必须走 import_module。
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (True, "mathlib-ready@stub"))
    seen = {}
    code = "import Mathlib.Tactic.Ring\ntheorem t : 1 = 1 := rfl"
    r = _m.lean_check(lean_code=code, work_dir="/stub/proj",
                      runner=_stub_runner(seen))
    assert r["import_norm"]["applied"] is False
    assert seen["code"] == code


def test_lean_check_records_why_it_did_not_normalize(monkeypatch):
    """Mathlib 未就绪 → 原样送编译，但**必须留痕**（不许静默）。

    静默的代价：事后看到 verdict=unknown 无法区分「环境没挂载」与
    「代码真错」，只能靠猜 —— 这正是 16/16 全失败查不出来的原因。
    """
    import importlib
    # ★ `from tools.agent_toolkit import lean_check` 拿到的是**函数**（包内
    #   re-export 覆盖了子模块名），要打桩模块属性必须走 import_module。
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (False, "mathlib-not-ready@stub"))
    seen = {}
    code = "theorem t : 1 = 1 := rfl"
    r = _m.lean_check(lean_code=code, work_dir="/stub/proj",
                      runner=_stub_runner(seen))
    assert r["import_norm"]["applied"] is False
    assert "not-ready" in r["import_norm"]["reason"]
    assert seen["code"] == code


def test_mathlib_ready_reuses_bridge_probe(monkeypatch):
    """就绪判定必须复用 `LeanBridge._mathlib_ready`，不许自写窄判据。

    ★ 本轮实际踩到的坑：一开始用 `_has_mathlib_tactics(work_dir)` 当守卫，
      它只认 pdir 根下的 `Mathlib/Tactic.olean`（或 `Mathlib/Tactic/NormNum.olean`）。
      本机 `<lean-env>/test_mathlib` 是 lake 工程，Mathlib 的 olean 在
      `.lake/packages/mathlib/.lake/build/lib/lean/` ⇒ 窄判据判 **False**
      ⇒ 归一化被整条跳过 ⇒ **修了等于没修**（本机实测 False vs True）。
      按 `lean_bridge__env` docstring：`_has_mathlib_tactics` 回答的是
      「聚合入口 vs 裁剪闭包」的**形态**问题，不是「要不要归一化」。
    """
    import importlib
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    called = {}

    class _FakeBridge:
        def __init__(self, client, cfg):
            called["pdir"] = getattr(cfg, "lean_project_dir", None)

        def _mathlib_ready(self):
            called["hit"] = True
            return True

    monkeypatch.setattr("tools.lean_local.lean_bridge.LeanBridge", _FakeBridge)
    monkeypatch.setattr(_m, "_MATHLIB_READY_CACHE", {})
    ok, why = _m._mathlib_ready_for("/some/pdir")
    assert ok is True
    assert called.get("hit") is True, "必须走 LeanBridge._mathlib_ready"
    assert called.get("pdir") == "/some/pdir", "work_dir 要真正传进去"
    assert "ready" in why


def test_lean_check_reports_original_line_numbers(monkeypatch):
    """归一化插了 import 后，诊断行号必须**减回原始代码**的行号。

    ★ 本轮实测踩到：补 import 让 sorry 从第 2 行变成第 7 行，旧输出报 `L7`
    —— 用户/模型拿着 `L7` 去改原始代码，改的是 import 块那一行。
    import 块永远插在文件最前面 ⇒ 「总行数差」就是唯一偏移量。
    """
    import importlib
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (True, "mathlib-ready@stub"))
    # 归一化后 theorem 在第 6 行（4 行 import + 空行）⇒ 报 L7 时原文是第 2 行
    err = "demo.lean:7:0: error: unsolved goals"
    r = _m.lean_check(lean_code="theorem t : 1 = 1 := by\n  trivial",
                      work_dir="/stub/proj",
                      runner=lambda c, w, t: {"ok": False, "error": err})
    assert r["import_norm"]["applied"] is True
    assert r["line_shift"] == 5
    assert r["errors"][0]["step"] == "L2", r["errors"]


def test_lean_check_falls_back_to_bridge_when_mcp_missing(monkeypatch):
    """MCP 通道不可用 ⇒ 必须回落 bridge 直编，而不是把 verdict 定死 unknown。

    ★ 本轮实测：`mcp_run_code` 依赖 lean-lsp-mcp 的 venv，本机
    `_detect_mcp_proxy_python()` 返回空串 ⇒ 恒 `mcp-env-missing`、0.0s。
    主链 `_lean_block_verify` 走 `bridge._compile` 能编 —— 同一台机器
    「主链能编、本工具恒 unknown」，这就是 run_code 全失败的第三层成因。
    """
    import importlib
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    from tools.lean_local import lean_bridge as _lb

    monkeypatch.setattr(_lb, "mcp_run_code",
                        lambda c, w, t: {"ok": False, "error": "mcp-env-missing"})
    monkeypatch.setattr(_lb, "_detect_mcp_proxy_python", lambda: "")
    called = {}

    class _FakeBridge:
        def __init__(self, client, cfg):
            called["pdir"] = getattr(cfg, "lean_project_dir", None)

        def _compile(self, code, work_dir, **kw):
            called["compiled"] = code
            return {"ok": True}

    monkeypatch.setattr(_lb, "LeanBridge", _FakeBridge)
    monkeypatch.setattr(_lb, "_trash_lean_file", lambda *a, **k: None)
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (False, "mathlib-not-ready@stub"))

    r = _m.lean_check(lean_code="theorem t : 1 = 1 := rfl", work_dir="/stub/proj")
    assert r["runner_used"] == "bridge", r
    assert r["verdict"] == "ok"
    assert "compiled" in called, "bridge._compile 必须真被调用"


def test_lean_check_does_not_fall_back_on_real_compile_error(monkeypatch):
    """真编译错误**不许**回落 —— 否则把「代码错」洗成「环境坏」，比不修更糟。"""
    import importlib
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    from tools.lean_local import lean_bridge as _lb

    err = "demo.lean:1:0: error: unknown identifier 'foo'"
    monkeypatch.setattr(_lb, "mcp_run_code",
                        lambda c, w, t: {"ok": False, "error": err})
    monkeypatch.setattr(_lb, "_detect_mcp_proxy_python", lambda: "/fake/python")

    class _BoomBridge:
        def __init__(self, *a, **k):
            raise AssertionError("真编译错误时不该走 bridge")

    monkeypatch.setattr(_lb, "LeanBridge", _BoomBridge)
    monkeypatch.setattr(_m, "_mathlib_ready_for",
                        lambda wd: (False, "mathlib-not-ready@stub"))

    r = _m.lean_check(lean_code="theorem t : 1 = 1 := rfl", work_dir="/stub/proj")
    assert r["runner_used"] == "mcp"
    assert r["verdict"] == "statement_error"


def test_lean_check_switch_off_keeps_code_untouched(monkeypatch):
    """开关关 ⇒ 完全不归一化（A/B 底线），且必须留痕 `switch-off`。

    ★ 顺序约定：开关先判，再做 Mathlib 探测 —— 关掉时不该白耗一次 bridge 探测
      （探测要 import lean_bridge 并查三条 `.lake` 路径）。
    """
    import importlib
    _m = importlib.import_module("tools.agent_toolkit.lean_check")
    monkeypatch.setattr(_m, "_normalize_switch_on", lambda: False)

    def _should_not_probe(wd):
        raise AssertionError("开关关了不该再探测 mathlib")

    monkeypatch.setattr(_m, "_mathlib_ready_for", _should_not_probe)
    seen = {}
    code = "theorem t : 1 = 1 := rfl"
    r = _m.lean_check(lean_code=code, work_dir="/stub/proj",
                      runner=_stub_runner(seen))
    assert r["import_norm"] == {"applied": False, "reason": "switch-off"}
    assert seen["code"] == code


def test_normalize_switch_registered_default_on():
    """开关必须登记且默认 True（四表同步的门禁之外的**值**断言）。

    只有开关、没有探测 ⇒ 会归一化到不可用形式；只有探测、没有开关 ⇒ 失去 A/B
    且 params.json 里没有该键。本用例锁住「开关这一半」。
    """
    from contracts.switch_registry import SWITCHES
    from user_agent__config import AgentConfig

    assert "lean_check_normalize_imports" in SWITCHES
    _env, _kind, _default = SWITCHES["lean_check_normalize_imports"][:3]
    assert _kind == "bool"
    assert _default is True
    assert getattr(AgentConfig, "lean_check_normalize_imports", None) is True
