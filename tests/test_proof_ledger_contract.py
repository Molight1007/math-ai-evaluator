"""证明账本契约测试 —— 锁住四条不可让渡语义。

这份测试比实现本身重要：账本一旦允许降级或允许改目标，整条新内核就退回
「每轮覆盖上一轮」的旧语义，而那种退步**不会**在判对率上表现出来（噪声
12.6pp 完全盖得住）。所以语义必须靠单测锁死，不能靠 review。
"""

import pytest

from contracts.closure import (
    CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_SOFT, CLOSURE_UNMAPPED,
)
from contracts.proof_ledger import (
    ADMIT_ANY, ADMIT_HARD, ADMIT_SOFT, DEFAULT_ADMIT, Obligation,
    ProofLedger, admit_status, obligation_from_row,
)


def ob(oid, status=CLOSURE_OPEN, goal="", deps=(), round=0, evidence="",
       reason=""):
    return Obligation(oid=oid, goal=goal, deps=tuple(deps),
                      status=status, round=round, evidence=evidence,
                      reason=reason)


# ------------------------------------------------------------ A 单调性
def test_first_write_accepted():
    led = ProofLedger()
    assert led.record(ob("a")) is True
    assert led.get("a").status == CLOSURE_OPEN


def test_upgrade_accepted():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN))
    assert led.record(ob("a", CLOSURE_HARD, evidence="ok")) is True
    assert led.get("a").status == CLOSURE_HARD


def test_downgrade_rejected():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, evidence="ok"))
    assert led.record(ob("a", CLOSURE_OPEN, round=2)) is False
    assert led.get("a").status == CLOSURE_HARD


def test_downgrade_is_traced():
    """降级不许静默丢弃 —— 否则「有结论」看起来比实际更稳。"""
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, evidence="ok"))
    led.record(ob("a", CLOSURE_OPEN, round=3))
    regs = led.regressions()
    assert len(regs) == 1
    oid, old_s, new_s, rnd = regs[0]
    assert (oid, old_s, new_s, rnd) == ("a", CLOSURE_HARD, CLOSURE_OPEN, 3)
    assert led.stats()["regressions"] == 1


def test_unmapped_is_lowest():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_UNMAPPED))
    assert led.record(ob("a", CLOSURE_OPEN)) is True
    assert led.get("a").status == CLOSURE_OPEN


def test_same_status_ignored():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN))
    assert led.record(ob("a", CLOSURE_OPEN)) is False
    assert led.stats()["regressions"] == 0   # 不变不算回退


# --------------------------------------------------- B 目标不可改写
def test_retarget_rejected_even_when_upgrading():
    """★ 这是最要紧的一条：换了命题之后，「证明成功」可能是证了别的东西。"""
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN, goal="证明存在这样的 n"))
    assert led.record(
        ob("a", CLOSURE_HARD, goal="证明 n=5", evidence="ok")) is False
    assert led.get("a").goal == "证明存在这样的 n"
    assert led.get("a").status == CLOSURE_OPEN


def test_retarget_is_traced():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN, goal="证明 A"))
    led.record(ob("a", CLOSURE_OPEN, goal="证明 B"))
    assert led.retargets() == (("证明 A", "证明 B", "a"),)


def test_whitespace_only_diff_is_same_goal():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN, goal="证明 A"))
    assert led.record(ob("a", CLOSURE_HARD, goal=" 证明 A ", evidence="ok")) is True


def test_empty_goal_does_not_overwrite():
    """新写入没带 goal（只有状态）时，不得把既有目标抹成空。"""
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN, goal="证明 A"))
    assert led.record(ob("a", CLOSURE_HARD, goal="", evidence="ok")) is True
    assert led.get("a").goal == "证明 A"


def test_deps_kept_from_first_declaration():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_OPEN, goal="g", deps=["u1"]))
    led.record(ob("a", CLOSURE_HARD, goal="g", deps=(), evidence="ok"))
    assert led.get("a").deps == ("u1",)


# --------------------------------------------------- C 三档放行
@pytest.mark.parametrize("level,status,ok", [
    (ADMIT_HARD, CLOSURE_HARD, True),
    (ADMIT_HARD, CLOSURE_SOFT, False),
    (ADMIT_HARD, CLOSURE_OPEN, False),
    (ADMIT_HARD, CLOSURE_UNMAPPED, False),
    (ADMIT_SOFT, CLOSURE_HARD, True),
    (ADMIT_SOFT, CLOSURE_SOFT, True),
    (ADMIT_SOFT, CLOSURE_OPEN, False),
    (ADMIT_ANY, CLOSURE_OPEN, True),
    (ADMIT_ANY, CLOSURE_UNMAPPED, True),
])
def test_admit_matrix(level, status, ok):
    assert admit_status(level, status) is ok


def test_unknown_level_admits_nothing():
    """未知档位一律不放行 —— 显式失败，而不是悄悄退化成全放。"""
    assert admit_status("typo", CLOSURE_HARD) is False


def test_default_is_hard():
    """默认必须最严：把 soft 当默认等于把同源失效往下游搬一层。"""
    assert DEFAULT_ADMIT == ADMIT_HARD


# --------------------------------------------------- D 投影
def test_project_excludes_unadmitted():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, goal="A", evidence="ok"))
    led.record(ob("b", CLOSURE_SOFT, goal="B"))
    led.record(ob("c", CLOSURE_OPEN, goal="C"))
    out = led.project(ADMIT_HARD)
    assert [x["oid"] for x in out] == ["a"]


def test_project_returns_tuple():
    """返回 tuple：调用方不能就地 append 把未闭合的塞回去。"""
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, evidence="ok"))
    out = led.project()
    assert isinstance(out, tuple)
    with pytest.raises(AttributeError):
        out.append({})


def test_project_carries_evidence():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, goal="A", evidence="norm_num ok"))
    assert led.project()[0]["evidence"] == "norm_num ok"


def test_project_soft_level_includes_hard():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, evidence="ok"))
    led.record(ob("b", CLOSURE_SOFT))
    assert {x["oid"] for x in led.project(ADMIT_SOFT)} == {"a", "b"}


# --------------------------------------------------- E 断点归因
def test_blocked_by_reports_missing_dep():
    led = ProofLedger()
    led.record(ob("u", CLOSURE_OPEN, goal="上游"))
    led.record(ob("d", CLOSURE_HARD, goal="下游", deps=["u"], evidence="ok"))
    assert led.blocked_by(ADMIT_HARD) == {"d": ["u"]}


def test_blocked_by_empty_when_dep_admitted():
    led = ProofLedger()
    led.record(ob("u", CLOSURE_HARD, goal="上游", evidence="ok"))
    led.record(ob("d", CLOSURE_HARD, goal="下游", deps=["u"], evidence="ok"))
    assert led.blocked_by(ADMIT_HARD) == {}


def test_blocked_by_ignores_unknown_dep_target():
    """依赖名写错（账本里没有这条）也算未放行 —— 不能当满足。"""
    led = ProofLedger()
    led.record(ob("d", CLOSURE_HARD, goal="下游", deps=["ghost"], evidence="ok"))
    assert led.blocked_by(ADMIT_HARD) == {"d": ["ghost"]}


# --------------------------------------------------- F 未闭合清单
def test_unresolved_goals_only_non_hard():
    led = ProofLedger()
    led.record(ob("a", CLOSURE_HARD, goal="A", evidence="ok"))
    led.record(ob("b", CLOSURE_OPEN, goal="B", reason="未判定"))
    out = led.unresolved_goals()
    assert [x["oid"] for x in out] == ["b"]
    assert out[0]["goal"] == "B"


# --------------------------------------------------- G 从历史产物构造
def test_obligation_from_row_hard():
    row = {"tool_ran": True, "tool_verdict": "ok", "depends_on": "u1"}
    o = obligation_from_row("x", row)
    assert o.status == CLOSURE_HARD
    assert o.deps == ("u1",)
    assert o.evidence == "ok"


def test_obligation_from_row_sorry_is_not_hard():
    """带 sorry 的证明能编译通过 —— 不识别就会被当成已闭合成事实。"""
    o = obligation_from_row("x", {"tool_ran": True, "tool_verdict": "sorry"})
    assert o.status != CLOSURE_HARD


def test_obligation_from_row_empty_is_unmapped():
    assert obligation_from_row("x", {}).status == CLOSURE_UNMAPPED
    assert obligation_from_row("x", None).status == CLOSURE_UNMAPPED


def test_record_rows_counts_accepted():
    led = ProofLedger()
    rows = [
        {"sid": "a", "objective_verdict": "correct"},
        {"sid": "b", "objective_verdict": "correct"},
        {"sid": "a", "objective_verdict": "incorrect"},   # 降级，拒
    ]
    assert led.record_rows(rows, oid_of=lambda r, i: r["sid"]) == 2
    assert led.get("a").status == CLOSURE_SOFT
