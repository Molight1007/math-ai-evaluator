# -*- coding: utf-8 -*-
"""回归测试：2026-09-21 三处修复（对应云端 arm2c2t 巡检暴露的真实缺陷）。

覆盖：
  ① 6.5 审核闸门**未过时回滚** —— 不把 final_response 停在置信度最低的候选上。
  ② 非答案闸门补强 —— 段首连接词 / 结论文档标签形态的过程叙述。
  ③ `_deep_revise_loop` Z6 去重键 —— 去掉自增的 `revise_round`。
  ⑤ 可观测性 —— `oracle_review` / `adversarial` 事件桶真正落进 diag。

真凭实据（0921 arm2c2t，5 题完成时的 diag）：
  `pick_diag.picked` 与 `predicted` 对比 ——
    000  picked `\\boxed{1}`  → predicted `20`
    003  picked `\\boxed{2026}` → predicted `因此a_{2025} = 2026。`
    004  picked `\\boxed{1012}` → predicted 187 字过程叙述
  `lean_gate` 的 `final_gate` 事件序列证明：候选按**置信度降序**逐个试，
  全被闸门拒（Lean 全降级 ⇒ 解答题恒 unknown/strict_reject）后，
  终值停在**最后换上**的候选（= 置信度最低者），且原实现没有回滚。
"""
from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "agent") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "agent"))

from agent.formatter import _looks_like_non_answer  # noqa: E402

ORCH_PATH = os.path.join(ROOT, "agent", "orchestrator.py")

# ---------------------------------------------------------------------------
# ② 非答案闸门：真实泄漏串必须被拦下，合法答案不得误杀
# ---------------------------------------------------------------------------
# (串, 期望结果, 说明)
NARRATIVE_CASES = [
    ("因此a_{2025} = 2026。", True, "003 实际提交（含 {} ⇒ 旧代码被 has_math 跳过）"),
    ("所以对手（选5个数的人）会试图构造5个数，使得无论我们排除哪个，"
     "剩下的4个数无论怎么配对，都需要较大的 $T$。", True, "002 闸门事件中出现"),
    ('最终正确的上界证明：考虑 $2|F|$ 个"端点"（每个失败位置 $a$ 产生一个对 '
     '$(a, s(a))$）。由于 $s(a) < a$，每个对中第一个元素大于第二个。',
     True, "004 实际提交（187 字长段 + 段首结论文档标签）"),
    ("综上，答案为 42。", True, "段首连接词"),
    ("因此无解", True, "段首连接词（宁可换候选，也不提交推理碎片）"),
]

LEGIT_CASES = [
    "$2-2m$", "20460", "2026, 2030", "1012", "$\\frac{1}{2}$",
    "\\boxed{1}", "\\boxed{-4}", "\\boxed{\\dfrac{\\sqrt{5}-1}{2}}",
    "\\boxed{2026}", "有限差分法、有限元法", "解：x=1", "答：42", "无解",
    "(-\\infty, 1] \\cup [3, +\\infty)", "\\frac{3}{7}",
    "\\boxed{\\dfrac{1+\\sqrt{5}}{2}}", "2", "2026",
]


@pytest.mark.parametrize("text,expect,why", NARRATIVE_CASES)
def test_narrative_is_rejected(text, expect, why):
    assert _looks_like_non_answer(text) is expect, why


@pytest.mark.parametrize("text", LEGIT_CASES)
def test_legit_answer_not_falsely_rejected(text):
    """误杀代价高：合法答案一个都不许被拦。"""
    assert _looks_like_non_answer(text) is False, repr(text)


def test_hard_cases_left_unblocked_on_purpose():
    """刻意不拦的两类（形态与合法答案难分）——由 6.5 回滚兜底。"""
    assert _looks_like_non_answer("20") is False          # 纯数值
    assert _looks_like_non_answer("p=1：f(f(d)) = f(2) + 1。") is False  # 数学碎片


# ---------------------------------------------------------------------------
# ③ Z6 去重键
# ---------------------------------------------------------------------------
class _Cfg:
    deep_revise_rounds = 1
    max_revise_rounds = 5


class _State:
    emergency = False


class _Ctx:
    def __init__(self, final_response: str, revise_round: int = 0):
        self.final_response = final_response
        self.revise_round = revise_round
        self.state = _State()
        self.events = []


def _make_orch():
    """绕过 __init__ 造一个只够跑 _deep_revise_loop 去重分支的对象。"""
    from agent.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = _Cfg()
    orch.events = []

    def _record(ctx, key, content, **kw):
        orch.events.append((key, str(content)))

    orch.record = _record
    return orch


def _call(orch, ctx, force=False):
    """返回去重结果；若越过去重进入回环主体则会抛异常（说明未被去重）。"""
    try:
        return orch._deep_revise_loop(ctx, {}, 3, force=force)
    except Exception as exc:  # noqa: BLE001
        return "ENTERED_BODY:" + type(exc).__name__


def test_dedup_hits_regardless_of_revise_round():
    """★ 核心：同一答案在**任意** revise_round 下都必须命中去重。"""
    orch = _make_orch()
    ctx = _Ctx("\\boxed{1}", revise_round=0)
    ctx._revise_pass_keys = {"\\boxed{1}"}       # 本趟已跑过该答案
    ctx.revise_round = 3                        # 5) 段已把它推进到 3
    assert _call(orch, ctx) is False
    assert any("已 revise 过" in c for _k, c in orch.events), orch.events


def test_dedup_key_is_not_tuple_with_round():
    """旧键形态 `(round, answer)` 必须**不再**命中（证明键已改）。"""
    orch = _make_orch()
    ctx = _Ctx("\\boxed{1}", revise_round=3)
    ctx._revise_pass_keys = {(3, "\\boxed{1}")}   # 旧实现的键
    assert str(_call(orch, ctx)).startswith("ENTERED_BODY:")


def test_dedup_does_not_block_a_changed_answer():
    """答案变了 ⇒ 不得被去重拦住（否则会漏掉真正该跑的 revise）。"""
    orch = _make_orch()
    ctx = _Ctx("\\boxed{2026}", revise_round=1)
    ctx._revise_pass_keys = {"\\boxed{1}"}
    assert str(_call(orch, ctx)).startswith("ENTERED_BODY:")


def test_force_bypasses_dedup():
    orch = _make_orch()
    ctx = _Ctx("\\boxed{1}", revise_round=1)
    ctx._revise_pass_keys = {"\\boxed{1}"}
    assert str(_call(orch, ctx, force=True)).startswith("ENTERED_BODY:")


# ---------------------------------------------------------------------------
# ① 6.5 回滚 + ⑤ 可观测性：源码级守卫（主流程无法低成本端到端构造）
# ---------------------------------------------------------------------------
def _src() -> str:
    with open(ORCH_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def test_gate_rollback_branch_present():
    """① 未过审核时必须存在回滚分支（且用统一写入口并置标志位）。"""
    src = _src()
    assert "_pre_rework_final = ctx.final_response" in src
    m = re.search(r"if not g_ok:(.{0,1400})?gate_rejected = True(.*?)\n\s+except",
                  src, re.S)
    assert m, "未找到 6.5 闸门终态分支"
    seg = m.group(2)
    assert "gate_rollback" in seg, "缺少回滚调用"
    assert "ctx._gate_rollback = True" in seg, "缺少回滚标志位"
    assert "_set_final_response(" in seg, "回滚必须走统一写入口"


def test_diag_exports_oracle_and_adversarial_events():
    """⑤ 两个事件桶必须在 _collect_diag 的导出白名单里。"""
    src = _src()
    m = re.search(r'for _k in \(("final_postprocess_change".*?)\)\}', src, re.S)
    assert m, "未找到事件桶白名单"
    names = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    # 2026-10-01：`calc_prewarm` 随 `<calc>` 计算工具板块删除，改锁仍生效的事件桶。
    for need in ("oracle_review", "adversarial", "subgoal_multi_agent", "revise"):
        assert need in names or need == "revise", names
    assert "oracle_review" in names
    assert "adversarial" in names


def test_diag_exports_gate_scalars():
    src = _src()
    for key in ('"gate_rejected"', '"gate_tried"', '"gate_rollback"'):
        assert key in src, key
