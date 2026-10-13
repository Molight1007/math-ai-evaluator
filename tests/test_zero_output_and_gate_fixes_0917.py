# -*- coding: utf-8 -*-
"""P1-B 第二批回归测试（2026-09-17）：口径统一 / 去重 / 缓存 / 死配置接线。

  Audit-3  `gen_time_up()` 不得再用于 4.5 Oracle 与 5)段全0票重解（验证侧环节）
  Z6       同一次「revise_round + final_response」不重复 revise
  Z2       `_value_attack_blueprint` 的早退分支必须落 diag（不能只有 logger.debug）
  Z3       Lean 验证的**语义等价**缓存（键含 reasoning 哈希）
  Audit-1  `max_revise_rounds` 必须真正接到全局轮数上限（此前 CLI 静默失效）
  Z8       子目标规划为空必须早退
"""
import io
import os
import re

from tools.lean_local.lean_gate import LeanGate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    txt = io.open(os.path.join(ROOT, rel), encoding="utf-8",
                  errors="replace").read()
    # 2026-10-08：`AgentConfig`（配置类）已逐字搬到 user_agent__config.py。
    # 读 user_agent.py 的源码级守卫改为读「主文件 + 抽取模块」并集 ——
    # 断言字面量与守卫意图均不变（非放宽判据），与 _orch_src 同口径。
    if rel.replace("\\", "/") == "user_agent.py":
        import glob
        for p in sorted(glob.glob(os.path.join(ROOT, "user_agent__*.py"))):
            txt += "\n" + io.open(p, encoding="utf-8",
                                  errors="replace").read()
    return txt


def _orch_src():
    """orchestrator.py + 已抽出的 `agent/orchestrator__*.py` 模块的**并集**。

    2026-10-07 阶段C4：`Orchestrator.run` 的阶段段（2.7/3.2/3.3 求解族、
    4.5 Oracle 验证族等）已**逐字搬**到 `agent/orchestrator__*.py`。
    源码级守卫改为读并集 —— 断言的字面量与守卫意图**均不变**（只是被查
    代码换了文件，非放宽判据）。与 tests/test_verify_only.py::_orch_src 同口径。
    """
    import glob
    txt = _src("agent/orchestrator.py")
    for p in sorted(glob.glob(os.path.join(ROOT, "agent", "orchestrator__*.py"))):
        txt += "\n" + io.open(p, encoding="utf-8", errors="replace").read()
    return txt


# ============================ Z3：语义等价缓存 ============================
def test_verify_key_same_inputs_same_key():
    assert (LeanGate._verify_key("P", "R", "A", False)
            == LeanGate._verify_key("P", "R", "A", False))


def test_verify_key_sensitive_to_reasoning():
    """**关键**：reasoning 不同 ⇒ 键必须不同（这是"语义等价"的前提）。"""
    assert (LeanGate._verify_key("P", "R1", "A", False)
            != LeanGate._verify_key("P", "R2", "A", False))


def test_verify_key_sensitive_to_answer_and_problem_and_flag():
    a = LeanGate._verify_key("P", "R", "A", False)
    assert a != LeanGate._verify_key("P", "R", "B", False)
    assert a != LeanGate._verify_key("Q", "R", "A", False)
    assert a != LeanGate._verify_key("P", "R", "A", True)


def test_verify_key_never_raises_on_bad_input():
    assert LeanGate._verify_key(None, None, None, False)


def test_cache_roundtrip():
    class _Ctx:
        pass

    c = _Ctx()
    k = LeanGate._verify_key("P", "R", "A", False)
    assert LeanGate._cache_get(c, k) is None      # 空缓存 → None
    LeanGate._cache_put(c, k, "REPORT")
    assert LeanGate._cache_get(c, k) == "REPORT"
    assert LeanGate._cache_get(c, None) is None   # 坏键不抛
    LeanGate._cache_put(c, None, "X")             # 坏键不写不抛


def test_gate_final_answer_consults_cache():
    src = _src("tools/lean_local/lean_gate.py")
    assert "cached_from_identity" in src
    i = src.find("def gate_final_answer")
    assert i > 0
    seg = src[i:i + 4000]
    assert "_cache_get(ctx, _z3k)" in seg, "6.5 未接语义等价缓存"


# ============================ Audit-3：口径统一 ============================
# ★ 2026-10-14（五道链定案）：`test_no_gen_time_up_on_verification_side` 已删 ——
#   其目标（4.5 Oracle 与 5)段全0票重解的时钟口径）随 4.5_oracle / 5_revise
#   两阶段整体删除。


# ============================ Z6：同答案不重复 revise ============================
# ★ 2026-10-14（五道链定案）：`test_z6_dedup_guard_present` / `test_z6_dedup_excludes_force`
#   已删 —— Z6 去重逻辑（`_revise_pass_keys`）随 `orchestrator__revise.py`
#   （5_revise 回环）整体删除。


# ============================ Z2：早退埋点 ============================
def test_value_attack_early_returns_are_recorded():
    # 2026-10-08 批10：`_value_attack_blueprint`（含全部早退埋点）已**逐字搬**到
    # agent/orchestrator__numeric.py，Orchestrator 内改为一行委托。本守卫改为
    # 读该模块 —— 断言字符串与守卫意图均不变（只是被查代码换了文件，非放宽判据）。
    src = _src("agent/orchestrator__numeric.py")
    i = src.find("def _value_attack_blueprint")
    assert i > 0
    seg = src[i:i + 9000]
    n_debug = seg.count("logger.debug(")
    n_rec = seg.count('self.record(ctx, "value_attack"')
    assert n_rec >= 8, "早退埋点不足（应 ≥8 处 record，实得 %d）" % n_rec
    assert "已付出调用" in seg, "未标注「已付出调用」的静默失败分支"


# ============================ Audit-1：死配置接线 ============================
# ★ 2026-10-14（五道链定案）：`test_max_revise_rounds_is_wired` 已删 ——
#   其目标（`_deep_revise_loop_inner` 的 max_revise_rounds 接线）随
#   orchestrator__revise.py 整体删除。


def test_max_revise_rounds_default_preserves_behavior():
    """默认值必须保持旧行为（全局上限 5），否则是隐式行为变更。"""
    src = _src("user_agent.py")
    m = re.search(r"max_revise_rounds:\s*int\s*=\s*(\d+)", src)
    assert m, "字段未声明"
    assert int(m.group(1)) == 5, "默认值 %s != 5，会改变既有行为" % m.group(1)


# ============================ Z8：空子目标早退 ============================
def test_z8_empty_subgoals_early_return():
    src = _src("agent/sub_goal_solver.py")
    assert "子目标规划为空 → 跳过求解与合并" in src
