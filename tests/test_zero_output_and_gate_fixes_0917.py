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
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


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
def test_no_gen_time_up_on_verification_side():
    """4.5 Oracle 与 5)段全0票重解不得再用生成侧软截止。"""
    src = _src("agent/orchestrator.py")
    # 两处已换成 is_time_critical
    assert ('and not ctx.is_time_critical()\n'
            '                    and self._enhance_window_ok(ctx, "oracle")') in src, \
        "4.5 Oracle 未换 is_time_critical"
    assert ("if (tier == 'deep' and not ctx.state.emergency\n"
            "                        and not ctx.is_time_critical()):") in src, \
        "5)段全0票重解未换 is_time_critical"
    # 且这两处不得再出现生成侧软截止
    assert ('and not ctx.gen_time_up()\n'
            '                    and self._enhance_window_ok(ctx, "oracle")') not in src
    assert ("and not ctx.gen_time_up()):\n"
            "                    revised_ok = self._deep_revise_loop") not in src


# ============================ Z6：同答案不重复 revise ============================
def test_z6_dedup_guard_present():
    src = _src("agent/orchestrator.py")
    assert "_revise_pass_keys" in src
    assert "同一答案（round=%d）本趟已 revise 过" in src


def test_z6_dedup_excludes_force():
    """P1 应急重解（force=True）不参与去重。"""
    src = _src("agent/orchestrator.py")
    i = src.find("_revise_pass_keys")
    assert i > 0
    seg = src[max(0, i - 900):i]
    assert "if not force:" in seg, "去重未排除 force=True"


# ============================ Z2：早退埋点 ============================
def test_value_attack_early_returns_are_recorded():
    src = _src("agent/orchestrator.py")
    i = src.find("def _value_attack_blueprint")
    assert i > 0
    seg = src[i:i + 9000]
    n_debug = seg.count("logger.debug(")
    n_rec = seg.count('self.record(ctx, "value_attack"')
    assert n_rec >= 8, "早退埋点不足（应 ≥8 处 record，实得 %d）" % n_rec
    assert "已付出调用" in seg, "未标注「已付出调用」的静默失败分支"


# ============================ Audit-1：死配置接线 ============================
def test_max_revise_rounds_is_wired():
    src = _src("agent/orchestrator.py")
    assert "max_revise_rounds" in src, "全局轮数上限未接到 config（CLI 仍静默失效）"
    assert ">= 5:" not in src, "仍有硬编码 5 轮上限"


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
