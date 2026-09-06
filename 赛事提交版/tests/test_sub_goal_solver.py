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


class StageBudgetTest(unittest.TestCase):
    """2026-09-04 子目标阶段预算（subgoal_stage_budget_sec）。

    目标（老师）：preverify 省下的时间不被 subgoal 贪婪 re-plan/re-review 吃掉；
    到点强制收尾 merge；且体系须在 deadline 内跑完（第二层保险）。
    """

    def _stage_end_of(self, ctx: TaskContext) -> float:
        return float(getattr(ctx, "_subgoal_stage_end", 0.0) or 0.0)

    def test_fixed_budget_set_on_ctx(self) -> None:
        """固定 750s 预算写入 ctx._subgoal_stage_end（无真实 deadline 时）。"""
        agent = make_agent()
        ctx = make_ctx()  # deadline=999.0（伪 epoch）→ 走固定预算分支
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertGreater(self._stage_end_of(ctx), 0.0)

    def test_tail_reserve_caps_stage_end(self) -> None:
        """真实 deadline 下：stage_end ≤ deadline - tail_reserve（180s，默认）。"""
        import time as _t
        agent = make_agent()
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300  # 真实未来时间戳
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        end = self._stage_end_of(ctx)
        self.assertGreater(end, 0.0)
        # deadline - end >= tail_reserve(180) - 容忍(计时抖动 5s)
        self.assertGreaterEqual(ctx.deadline - end, 175.0)

    def test_override_budget_sec_still_tail_capped(self) -> None:
        """subgoal_stage_budget_sec=0：放弃固定上限，但真实 deadline 下
        tail_reserve 仍把 stage_end 约束在 deadline-180 前（第二层独立生效）。"""
        import time as _t
        from types import SimpleNamespace as _NS
        agent = make_agent()
        agent.config = _NS(
            max_total_calls=20, max_time_per_question=300,
            max_total_time_seconds=21000, policy_max_tokens=2048,
            subgoal_stage_budget_sec=0.0,  # 放弃固定预算
        )
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300  # 真实 deadline
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        end = self._stage_end_of(ctx)
        self.assertGreater(end, 0.0)
        # deadline - end >= tail_reserve(180) - 容忍(5s)
        self.assertGreaterEqual(ctx.deadline - end, 175.0)

    def test_disable_both_budget_and_reserve(self) -> None:
        """固定预算=0 且 tail_reserve=0 → 阶段预算完全停用（stage_end=0）。"""
        import time as _t
        from types import SimpleNamespace as _NS
        agent = make_agent()
        agent.config = _NS(
            max_total_calls=20, max_time_per_question=300,
            max_total_time_seconds=21000, policy_max_tokens=2048,
            subgoal_stage_budget_sec=0.0,
            subgoal_tail_reserve_sec=0.0,
        )
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertEqual(self._stage_end_of(ctx), 0.0)

    def test_share_stage_start_across_runs(self) -> None:
        """时钟挂 ctx：两次 run() 共享同一 _subgoal_stage_start（不重置）。"""
        import time as _t
        agent = make_agent()
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        start1 = float(getattr(ctx, "_subgoal_stage_start", 0.0) or 0.0)
        self.assertGreater(start1, 0.0)
        # 第二次 run：模拟更晚时刻，start 不应重置
        ctx._subgoal_stage_start = start1 - 100  # 反向验证：显式改早后应被保留
        agent.run(ctx)
        self.assertAlmostEqual(
            float(getattr(ctx, "_subgoal_stage_start", 0.0) or 0.0),
            start1 - 100, places=0)  # 已存在 → 不重写


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


class StepCalcDisciplineTest(unittest.TestCase):
    """2026-09-04 calc 纪律下沉子目标步骤：system 注入 <calc> 引导 + 响应回填。"""

    class _RecordingClient:
        def __init__(self, resp: str):
            self.resp = resp
            self.last_messages = None

        def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
            self.last_messages = messages
            return self.resp

        def call(self, messages=None, temperature=0.0, max_tokens=256, **kw):
            return self.chat(messages=messages, temperature=temperature,
                             max_tokens=max_tokens, **kw)

    def _make_agent(self, enable_calc_tool: bool):
        config = SimpleNamespace(
            max_total_calls=20,
            max_time_per_question=300,
            max_total_time_seconds=21000,
            policy_max_tokens=2048,
            enable_calc_tool=enable_calc_tool,
        )
        return SubGoalSolverAgent(client=None, config=config)

    def _call_step(self, agent, resp_text: str):
        client = self._RecordingClient(resp_text)
        agent.client = client
        ctx = make_ctx()
        out = agent._call_step(ctx, "【原题】求值\n【当前子目标 #1】计算")
        return out, client.last_messages

    def test_system_injects_calc_guide_and_resolves(self) -> None:
        agent = self._make_agent(enable_calc_tool=True)
        out, msgs = self._call_step(
            agent,
            "【推导过程】\n略\n【本步结果】\n<calc>1/2+1/3</calc>",
        )
        # ① system 提示词注入了 calc 纪律
        sys_content = msgs[0]["content"]
        self.assertIn("计算环节请用 <calc>", sys_content)
        # ② <calc> 块被精确回填，不留原始标记
        self.assertNotIn("<calc>", out)
        self.assertIn("5/6", out)

    def test_disabled_keeps_original(self) -> None:
        agent = self._make_agent(enable_calc_tool=False)
        out, msgs = self._call_step(
            agent,
            "【推导过程】\n略\n【本步结果】\n<calc>1/2+1/3</calc>",
        )
        sys_content = msgs[0]["content"]
        self.assertNotIn("计算环节请用 <calc>", sys_content)
        # 关闭时不做回填：<calc> 原样保留（与 solver 开关语义一致）
        self.assertIn("<calc>1/2+1/3</calc>", out)


if __name__ == "__main__":
    unittest.main()
