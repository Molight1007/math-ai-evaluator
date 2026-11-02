"""六步内核的编排测试 —— 锁住「结构差异」，不是锁实现细节。

重点锁三条：
1. 依赖先解、环即失败（旧链靠多跑几轮掩盖顺序问题）
2. 裁决**永不**产出「模型认为对」这一档
3. 投影里不含未放行条目（新内核唯一新增的那层）
"""

import pytest

from agent.kernel import (
    DELIVERY_NONE, DELIVERY_PROVEN, DELIVERY_UNPROVEN, CycleError, Kernel,
    KernelError, PlanNode, SolveOutcome, judge, make_checker_result,
    project_text, topo_order,
)
from contracts.closure import (
    CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_SOFT, CLOSURE_UNMAPPED,
)

PASS_TOOL = lambda n, o: make_checker_result(
    "pass", tool_ran=True, evidence="norm_num ok")
FAIL_TOOL = lambda n, o: make_checker_result(
    "fail", tool_ran=True, evidence="unsolved goals")
PASS_RULE = lambda n, o: make_checker_result("pass", tool_ran=False)
FAIL_RULE = lambda n, o: make_checker_result("fail", tool_ran=False)


def node(nid, goal="证明某命题", deps=()):
    return PlanNode(nid=nid, goal=goal, deps=tuple(deps))


def out(nid, claim="成立", action=""):
    return SolveOutcome(nid=nid, claim=claim, action=action)


# --------------------------------------------------------- A 拓扑序
def test_topo_deps_first():
    order, ext = topo_order([node("c", deps=["b"]), node("a"),
                             node("b", deps=["a"])])
    assert order == ("a", "b", "c")
    assert ext == {}


def test_topo_stable_for_independent():
    """无依赖时保持声明顺序 —— 否则同一输入的运行结果不可复现。"""
    order, _ = topo_order([node("z"), node("a"), node("m")])
    assert order == ("z", "a", "m")


def test_topo_cycle_raises():
    with pytest.raises(CycleError):
        topo_order([node("a", deps=["b"]), node("b", deps=["a"])])


def test_topo_self_dep_ignored():
    """自引用不算环（历史产物里出现过），但也不构成依赖。"""
    order, _ = topo_order([node("a", deps=["a"])])
    assert order == ("a",)


def test_topo_break_cycles_recovers():
    """★ 环是规划缺陷，但不应让整题崩：破环后仍能排序，且互指边被记为
    未满足前提 —— 问题不被掩盖，只是不再阻断整条链。"""
    nodes = [node("1"), node("2", deps=["1", "3"]),
             node("3", deps=["1", "2"]), node("4", deps=["1", "2"])]
    with pytest.raises(CycleError):
        topo_order(nodes)
    order, ext = topo_order(nodes, break_cycles=True)
    assert set(order) == {"1", "2", "3", "4"}
    assert order[0] == "1"
    assert "3" in ext.get("2", []) or "2" in ext.get("3", [])


def test_topo_break_keeps_acyclic_part_intact():
    """破环不得顺手把正常依赖也摘掉。"""
    nodes = [node("1"), node("2", deps=["1", "3"]),
             node("3", deps=["1", "2"]), node("4", deps=["1"])]
    order, ext = topo_order(nodes, break_cycles=True)
    assert "4" not in ext          # 4 只依赖 1，没被牵连
    assert order.index("4") > order.index("1")


def test_topo_unknown_dep_reported_not_fatal():
    order, ext = topo_order([node("a", deps=["ghost"])])
    assert order == ("a",)
    assert ext == {"a": ["ghost"]}


def test_topo_duplicate_id_raises():
    with pytest.raises(KernelError):
        topo_order([node("a"), node("a")])


# --------------------------------------------------------- B 裁决
def test_judge_no_outcome_is_unmapped():
    assert judge(node("a"), None).status == CLOSURE_UNMAPPED


def test_judge_empty_output_is_unmapped():
    assert judge(node("a"), out("a", claim="")).status == CLOSURE_UNMAPPED


def test_judge_question_claim_not_closed():
    """求解器把目标原样抄回来 ⇒ 这不是结论。旧链会当推导往下传。"""
    j = judge(node("a"), out("a", claim="证明存在 n 使得 n^2 > 2"),
              PASS_TOOL)
    assert j.status == CLOSURE_OPEN
    assert j.reason == "claim_is_question"


def test_judge_tool_pass_is_hard():
    j = judge(node("a"), out("a", claim="x=1"), PASS_TOOL)
    assert j.status == CLOSURE_HARD
    assert j.by == "tool"
    assert j.evidence


def test_judge_tool_pass_without_evidence_rejected():
    """跑了个空动作不算证完 —— 没有输出就无法复核。"""
    j = judge(node("a"), out("a", claim="x=1"),
              lambda n, o: make_checker_result("pass", tool_ran=True))
    assert j.status == CLOSURE_OPEN
    assert j.reason == "tool_passed_without_evidence"


def test_judge_tool_fail_is_open():
    j = judge(node("a"), out("a", claim="x=1"), FAIL_TOOL)
    assert j.status == CLOSURE_OPEN
    assert j.by == "tool"


def test_judge_sorry_evidence_is_not_hard():
    """带 sorry 的证明能编译通过，不能算闭合。"""
    j = judge(node("a"), out("a", claim="x=1"),
              lambda n, o: make_checker_result(
                  "pass", tool_ran=True, evidence="declaration uses sorry"))
    assert j.status == CLOSURE_OPEN


def test_judge_rule_pass_is_not_closed():
    """纯规则说「通过」不构成闭合：规则没有执行任何东西。"""
    j = judge(node("a"), out("a", claim="x=1"), PASS_RULE)
    assert j.status != CLOSURE_HARD


def test_judge_rule_fail_is_open_by_symbol():
    j = judge(node("a"), out("a", claim="x=1"), FAIL_RULE)
    assert j.status == CLOSURE_OPEN
    assert j.by == "symbol"


def test_judge_checker_error_does_not_crash():
    def boom(n, o):
        raise RuntimeError("tool down")
    j = judge(node("a"), out("a", claim="x=1"), boom)
    assert j.status == CLOSURE_OPEN
    assert "checker_error" in j.reason


def test_judge_without_checker_is_undecidable():
    j = judge(node("a"), out("a", claim="x=1"))
    assert j.status == CLOSURE_OPEN
    assert j.reason == "undecidable"


@pytest.mark.parametrize("checker", [None, PASS_TOOL, FAIL_TOOL,
                                     PASS_RULE, FAIL_RULE])
def test_judge_never_emits_soft(checker):
    """★ 同源评审是旧链死因。裁决层永不产出「模型认为对」这一档。"""
    j = judge(node("a"), out("a", claim="x=1"), checker)
    assert j.status in (CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_UNMAPPED)
    assert j.status != CLOSURE_SOFT


# --------------------------------------------------------- C 投影
def test_projection_excludes_unadmitted():
    nodes = [node("a"), node("b")]
    k = Kernel(checker=lambda n, o: PASS_TOOL(n, o) if n.nid == "a" else FAIL_TOOL(n, o))
    r = k.run_solved(nodes, {"a": out("a", "a=1"), "b": out("b", "b=2")})
    text = project_text(r.ledger)
    assert "a=1" in text
    assert "b=2" not in text


def test_projection_empty_returns_empty_string():
    """空就说空，不写「暂无」—— 占位会让下游以为「查过了确实没有」。"""
    assert project_text(Kernel().run_solved([], {}).ledger) == ""


# --------------------------------------------------------- D 交付
def test_deliver_proven():
    r = Kernel(checker=PASS_TOOL).run_solved(
        [node("a")], {"a": out("a", "x=1")}, root_oid="a")
    assert r.delivery.tier == DELIVERY_PROVEN
    assert r.delivery.answer == "x=1"


def test_deliver_unproven_when_open():
    r = Kernel().run_solved([node("a")], {"a": out("a", "x=1")}, root_oid="a")
    assert r.delivery.tier == DELIVERY_UNPROVEN
    assert r.delivery.answer == "x=1"


def test_deliver_none_without_claim():
    r = Kernel().run_solved([node("a")], {"a": SolveOutcome("a")},
                            root_oid="a")
    assert r.delivery.tier == DELIVERY_NONE
    assert r.delivery.answer == ""


def test_deliver_does_not_recompute_closure():
    """账本说没闭合，答案写得再对也不算证出 —— 交付只查表。"""
    r = Kernel().run_solved([node("a")], {"a": out("a", "x=1")}, root_oid="a")
    assert r.ledger.get("a").status == CLOSURE_OPEN
    assert r.delivery.proven is False


# --------------------------------------------------------- E 账本联动
def test_multiple_candidates_keep_best():
    """同一节点多条求解产出：任一被工具验证即算闭合（存在性语义）。"""
    outs = {"a": [out("a", "x=1"), out("a", "x=2")]}
    k = Kernel(checker=lambda n, o: PASS_TOOL(n, o)
               if o.claim == "x=2" else FAIL_TOOL(n, o))
    r = k.run_solved([node("a")], outs, root_oid="a")
    assert r.ledger.get("a").status == CLOSURE_HARD
    assert r.ledger.get("a").claim == "x=2"


def test_no_downgrade_after_hard():
    """先证成再被判错 ⇒ 不许降级（旧链每轮覆盖，结论会来回翻）。"""
    outs = {"a": [out("a", "x=1"), out("a", "y=9")]}
    k = Kernel(checker=lambda n, o: PASS_TOOL(n, o)
               if o.claim == "x=1" else FAIL_TOOL(n, o))
    r = k.run_solved([node("a")], outs, root_oid="a")
    assert r.ledger.get("a").status == CLOSURE_HARD
    assert r.ledger.get("a").claim == "x=1"
    assert r.ledger.stats()["regressions"] == 1


def test_external_dep_blocks_downstream():
    nodes = [node("a", deps=["ghost"])]
    r = Kernel(checker=PASS_TOOL).run_solved(nodes, {"a": out("a", "x=1")})
    assert r.ledger.blocked_by() == {"a": ["ghost"]}


# --------------------------------------------------------- F 在线模式
def test_online_requires_steps():
    with pytest.raises(KernelError):
        Kernel().run("题目")


def test_online_passes_only_projection_to_solver():
    """★ 下游拿到的上下文只能来自投影：上游未闭合时必须是空。"""
    seen = []

    def solve(n, ctx):
        seen.append((n.nid, ctx))
        return out(n.nid, "x=1")

    k = Kernel(understand=lambda p, m: None,
               plan=lambda spec, p: [node("a"), node("b", deps=["a"])],
               solve=solve)
    k.run("题目")
    assert seen[0][1] == ""          # 第一条没有上游
    assert seen[1][1] == ""          # a 未闭合 ⇒ 投影为空，b 看不到任何东西


def test_online_empty_plan_fails_loudly():
    k = Kernel(understand=lambda p, m: None, plan=lambda s, p: [],
               solve=lambda n, c: None)
    with pytest.raises(KernelError):
        k.run("题目")
