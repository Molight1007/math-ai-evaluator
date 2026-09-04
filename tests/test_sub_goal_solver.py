# -*- coding: utf-8 -*-
"""子目标求解智能体（SubGoalSolverAgent）单元测试。

覆盖:
- ``_extract_json``: JSON 解析（代码块 / 纯 JSON / 坏输入）
- ``_parse_subgoal_plan``: 规划校验、去重、类型白名单、上限
- ``run``: 全流程（mock client）追加候选
"""
import unittest
from types import SimpleNamespace

from agent.base import TaskContext, Budget, Candidate
from agent.sub_goal_solver import SubGoalSolverAgent


def make_agent(client=None) -> SubGoalSolverAgent:
    config = SimpleNamespace(
        max_total_calls=20,
        max_time_per_question=300,
        max_total_time_seconds=21000,
        policy_max_tokens=2048,
    )
    return SubGoalSolverAgent(client=client or MockClient(), config=config)


class MockClient:
    """返回固定子目标规划 JSON 的 mock 客户端。"""

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        return self.call(messages=messages, temperature=temperature,
                         max_tokens=max_tokens, **kw)

    def call(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        return (
            "```json\n"
            '{"problem_analysis": {"domain": "代数", "core_objective": "求解"},'
            '"subgoals": ['
            '{"id": 1, "title": "化简", "description": "先化简", '
            '"type": "compute", "depends_on": [], "expected_output": "化简结果"}'
            '], "merge_strategy": "合并"}'
            "\n```"
        )


def make_ctx(problem="求极限 lim_{x→0} (sin x)/x") -> TaskContext:
    return TaskContext(
        problem=problem,
        metadata={},
        budget=Budget(max_calls=20),
        start_time=0.0,
        deadline=999.0,
        total_start_time=0.0,
        total_deadline=9999.0,
    )


class ExtractJsonTest(unittest.TestCase):
    def test_fenced_json(self) -> None:
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(SubGoalSolverAgent._extract_json(text), {"a": 1})

    def test_plain_json(self) -> None:
        text = '{"a": 1}'
        self.assertEqual(SubGoalSolverAgent._extract_json(text), {"a": 1})

    def test_invalid_json_returns_none(self) -> None:
        self.assertIsNone(SubGoalSolverAgent._extract_json("not json at all"))

    def test_empty_input(self) -> None:
        self.assertIsNone(SubGoalSolverAgent._extract_json(""))
        self.assertIsNone(SubGoalSolverAgent._extract_json(None))

    def test_trailing_comma_repaired(self) -> None:
        text = '{"subgoals": [{"id": 1, "title": "x",}]}'
        data = SubGoalSolverAgent._extract_json(text)
        self.assertIsNotNone(data)
        self.assertEqual(len(data["subgoals"]), 1)


class ParseSubgoalPlanTest(unittest.TestCase):
    def test_valid_plan(self) -> None:
        raw = {"subgoals": [
            {"id": 1, "title": "化简", "type": "compute",
             "depends_on": [], "expected_output": "x"},
        ]}
        plan = SubGoalSolverAgent._parse_subgoal_plan(raw)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["id"], 1)

    def test_empty_or_missing_subgoals(self) -> None:
        self.assertIsNone(SubGoalSolverAgent._parse_subgoal_plan({}))
        self.assertIsNone(SubGoalSolverAgent._parse_subgoal_plan({"subgoals": []}))

    def test_duplicate_ids_deduplicated(self) -> None:
        raw = {"subgoals": [
            {"id": 1, "title": "a", "type": "compute"},
            {"id": 1, "title": "b", "type": "compute"},
            {"id": 2, "title": "c", "type": "compute"},
        ]}
        plan = SubGoalSolverAgent._parse_subgoal_plan(raw)
        self.assertEqual(len(plan), 2)

    def test_type_whitelist(self) -> None:
        raw = {"subgoals": [
            {"id": 1, "title": "a", "type": "hack"},  # 非法类型 → compute
        ]}
        plan = SubGoalSolverAgent._parse_subgoal_plan(raw)
        self.assertEqual(plan[0]["type"], "compute")

    def test_too_many_subgoals_capped(self) -> None:
        """默认上限 6（2026-09-03 老师：子目标是简化求解，拆 10 步反而更碎）。"""
        raw = {"subgoals": [
            {"id": i, "title": f"s{i}", "type": "compute"} for i in range(1, 20)
        ]}
        plan = SubGoalSolverAgent._parse_subgoal_plan(raw)
        self.assertEqual(len(plan), 6)

    def test_max_subgoals_param_override(self) -> None:
        """上限可由调用方（config.max_subgoals）覆盖。"""
        raw = {"subgoals": [
            {"id": i, "title": f"s{i}", "type": "compute"} for i in range(1, 20)
        ]}
        plan = SubGoalSolverAgent._parse_subgoal_plan(raw, 3)
        self.assertEqual(len(plan), 3)


class RunFlowTest(unittest.TestCase):
    def test_run_appends_candidate(self) -> None:
        agent = make_agent()
        ctx = make_ctx()
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertEqual(len(ctx.candidates), 2)
        self.assertIn("最终答案", ctx.candidates[-1].reasoning)

    def test_time_critical_skips(self) -> None:
        """2026-09-03 预算解除后：只有**时间紧迫**才跳过子目标求解。

        原 test_run_exhausted_budget_skips 用 Budget(max_calls=0) 模拟"预算
        耗尽 → 跳过"——预算闸门已删（比赛无次数上限），该行为不复存在。
        改为验证真实跳过条件：deadline 已过（is_time_critical=True）。
        """
        import time as _t
        agent = make_agent()
        ctx = make_ctx()
        ctx.deadline = _t.time() - 1  # 真实时间戳，已过期 → 时间紧迫
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertEqual(len(ctx.candidates), 1)

    def test_budget_zero_still_runs(self) -> None:
        """预算=0 不再阻断（闸门删除后的新语义）：子目标求解照常追加候选。"""
        agent = make_agent()
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertEqual(len(ctx.candidates), 2)

    def test_run_partial_budget_still_appends_fallback(self) -> None:
        agent = make_agent()
        ctx = make_ctx()
        ctx.budget.spend(18)  # 剩 2 次：规划可用，但子目标阶段预算不足
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        # 规划成功但子目标/合并预算不足 → 以"无法求解"兜底仍追加候选
        self.assertEqual(len(ctx.candidates), 2)


class ReplanDispatchTest(unittest.TestCase):
    """_review_and_maybe_replan 分流逻辑（9/1 优化 B：LCA=根 跳过子树直接整树）。"""

    @staticmethod
    def _make_dag(n1_children: list) -> "BlueprintDAG":
        from agent.blueprint_planner import BlueprintDAG, BlueprintNode
        nodes = {
            "g": BlueprintNode("g", "compute", "Solve the whole problem",
                               ["n1", "n2"]),
            "n1": BlueprintNode("n1", "compute", "First branch", n1_children),
            "n2": BlueprintNode("n2", "compute", "Second branch", []),
        }
        for c in n1_children:
            nodes[c] = BlueprintNode(c, "compute", f"Leaf {c}", [])
        return BlueprintDAG(nodes=nodes, root_id="g")

    def test_lca_root_skips_subtree(self) -> None:
        # reject 横跨两个顶层分支（n1、n2）→ LCA=g=根 → 跳过子树，直接整树
        from unittest.mock import patch

        from agent.dag_reviewer import DagReviewReport, DagReviewResult
        dag = self._make_dag([])
        reject_r = DagReviewReport(results={
            "n1": DagReviewResult("n1", "reject", 0.2, ["粒度不当"], "改细"),
            "n2": DagReviewResult("n2", "reject", 0.2, ["循环"], "改"),
        })
        accept_r = DagReviewReport(results={})
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_rev_cls, \
                patch("agent.blueprint_planner.BlueprintPlannerAgent") as m_pl_cls:
            m_rev = m_rev_cls.return_value
            m_rev.review.side_effect = [reject_r, accept_r]
            m_pl = m_pl_cls.return_value
            m_pl.regenerate_with_feedback.return_value = dag
            ctx = make_ctx()
            ok = make_agent()._review_and_maybe_replan(ctx, dag=dag,
                                                       max_replan_rounds=1)
            self.assertTrue(ok)
            # 关键断言：子树重写未被调用（LCA=根 快速分流）
            m_pl.regenerate_subtree.assert_not_called()
            m_pl.regenerate_with_feedback.assert_called_once()

    def test_lca_nonroot_uses_subtree_first(self) -> None:
        # reject 集中在 n1 分支（n1a、n1b）→ LCA=n1 ≠ 根 → 先子树重写
        from unittest.mock import patch

        from agent.dag_reviewer import DagReviewReport, DagReviewResult
        dag = self._make_dag(["n1a", "n1b"])
        reject_r = DagReviewReport(results={
            "n1a": DagReviewResult("n1a", "reject", 0.2, ["粒度不当"], "改细"),
            "n1b": DagReviewResult("n1b", "reject", 0.2, ["循环"], "改"),
        })
        accept_r = DagReviewReport(results={})
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_rev_cls, \
                patch("agent.blueprint_planner.BlueprintPlannerAgent") as m_pl_cls:
            m_rev = m_rev_cls.return_value
            m_rev.review.side_effect = [reject_r, accept_r]
            m_pl = m_pl_cls.return_value
            m_pl.regenerate_subtree.return_value = dag
            ctx = make_ctx()
            ok = make_agent()._review_and_maybe_replan(ctx, dag=dag,
                                                       max_replan_rounds=1)
            self.assertTrue(ok)
            # 关键断言：先走子树重写，未升级整树
            m_pl.regenerate_subtree.assert_called_once()
            m_pl.regenerate_with_feedback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
