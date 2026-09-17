# -*- coding: utf-8 -*-
"""
蓝图 / 子目标 **设计层** 回归测试（2026-09-15）
================================================

锁定四项设计改动，防止静默退化：

1. `cap_subgoals_keep_last` 的统一语义
   （None→默认 / <=0→不截断 / 保留收尾）
2. `to_subgoal_plan` 遵守 `config.max_subgoals`（两条路径同源）
3. 蓝图提示词的设计约束一致（无 ≤5 冲突、含收尾节点规则、rationale 必填）
4. DAG 评审器确实拿到 `rationale`（LEAP §2.1 Purpose）

背景（为什么这些是"设计"而非"实现细节"）：
- ≤5 节点硬约束与 `MAX_SUBGOALS=6` 都是**时间墙遗留**——其理由原文是
  "蓝图输出越长，后续 2.7/3_solve 越慢"。时限解除后它们不再是设计目标。
- `to_subgoal_plan()` 原先不传参 ⇒ `config.max_subgoals`（含 --max_subgoals CLI）
  对 blueprint 路径**完全无效**；实测 003/074 走该路径 ⇒ 旋钮是死的。
- 盲截拓扑序尾部会丢掉"合并结论"那一步 ⇒ 前面子目标全白解。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.base import TaskContext, Budget
from agent.blueprint_planner import (
    BlueprintDAG, BlueprintNode, cap_subgoals_keep_last, MAX_SUBGOALS,
)


def make_chain_dag(n: int) -> BlueprintDAG:
    """根 + n 个叶子（叶子按 id 顺序挂在根下）。"""
    nodes = {"g": BlueprintNode("g", "and", "证明总目标 P",
                                [f"n{i}" for i in range(1, n + 1)])}
    for i in range(1, n + 1):
        nodes[f"n{i}"] = BlueprintNode(f"n{i}", "and", f"第{i}步推导结论{i}", [])
    return BlueprintDAG(nodes=nodes, root_id="g")


# ============================================================
# 1. cap_subgoals_keep_last
# ============================================================

class TestCapSubgoalsKeepLast(unittest.TestCase):

    def setUp(self):
        self.seq = ["a", "b", "c", "d", "e"]

    def test_zero_means_no_truncation(self):
        """★ 0 = 不截断（旧 `or` 写法会把 0 吃成 6，该意图无法表达）。"""
        keep, drop = cap_subgoals_keep_last(self.seq, 0)
        self.assertEqual(keep, self.seq)
        self.assertEqual(drop, [])

    def test_negative_means_no_truncation(self):
        keep, drop = cap_subgoals_keep_last(self.seq, -5)
        self.assertEqual(keep, self.seq)
        self.assertEqual(drop, [])

    def test_none_falls_back_to_default(self):
        long_seq = [str(i) for i in range(MAX_SUBGOALS + 4)]
        keep, drop = cap_subgoals_keep_last(long_seq, None)
        self.assertEqual(len(keep), MAX_SUBGOALS)
        self.assertTrue(drop)

    def test_keeps_last_element(self):
        """★ 收尾保留：截断后最后一个元素必须还是原序列的最后一个。"""
        for m in (1, 2, 3, 4):
            keep, _ = cap_subgoals_keep_last(self.seq, m)
            self.assertEqual(keep[-1], "e", f"max={m} 丢了收尾元素")
            self.assertEqual(len(keep), m)

    def test_keeps_prefix_then_last(self):
        keep, drop = cap_subgoals_keep_last(self.seq, 3)
        self.assertEqual(keep, ["a", "b", "e"])
        self.assertEqual(drop, ["c", "d"])

    def test_max_one_keeps_only_last(self):
        keep, drop = cap_subgoals_keep_last(self.seq, 1)
        self.assertEqual(keep, ["e"])
        self.assertEqual(drop, ["a", "b", "c", "d"])

    def test_no_truncation_when_within_limit(self):
        keep, drop = cap_subgoals_keep_last(self.seq, 5)
        self.assertEqual(keep, self.seq)
        self.assertEqual(drop, [])
        keep, drop = cap_subgoals_keep_last(self.seq, 99)
        self.assertEqual(keep, self.seq)
        self.assertEqual(drop, [])

    def test_empty_and_none_input(self):
        self.assertEqual(cap_subgoals_keep_last([], 3), ([], []))
        self.assertEqual(cap_subgoals_keep_last(None, 3), ([], []))

    def test_invalid_value_falls_back(self):
        keep, _ = cap_subgoals_keep_last(self.seq, "not-a-number")
        self.assertEqual(keep, self.seq)   # 回退默认 6 > 5 ⇒ 不截断

    def test_elements_preserved_no_duplication(self):
        """截断后不得出现重复元素（前缀与尾部的区间必须不相交）。"""
        for m in range(1, 6):
            keep, _ = cap_subgoals_keep_last(self.seq, m)
            self.assertEqual(len(keep), len(set(keep)), f"max={m} 有重复")


# ============================================================
# 2. to_subgoal_plan 遵守 max_subgoals
# ============================================================

class TestToSubgoalPlanRespectsCap(unittest.TestCase):

    def test_default_matches_max_subgoals(self):
        plan = make_chain_dag(9).to_subgoal_plan()
        self.assertEqual(len(plan["subgoals"]), MAX_SUBGOALS)

    def test_zero_means_all(self):
        plan = make_chain_dag(9).to_subgoal_plan(0)
        self.assertEqual(len(plan["subgoals"]), 9)

    def test_explicit_cap_applied(self):
        plan = make_chain_dag(9).to_subgoal_plan(3)
        self.assertEqual(len(plan["subgoals"]), 3)

    def test_concluding_subgoal_survives_truncation(self):
        """★ 截断后必须仍含收尾子目标（否则解完也无最终答案）。"""
        plan = make_chain_dag(9).to_subgoal_plan(3)
        descs = [s["description"] for s in plan["subgoals"]]
        self.assertIn("第9步推导结论9", descs)

    def test_depends_on_indices_consistent_after_truncation(self):
        """截断后 depends_on 必须指向存活序号（1..n，稠密）。"""
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["leaf1", "leaf2"]),
            "leaf1": BlueprintNode("leaf1", "and", "第一步得到中间结论", []),
            "leaf2": BlueprintNode("leaf2", "and", "第二步综合出最终答案", []),
        }, root_id="g")
        plan = dag.to_subgoal_plan(1)
        self.assertEqual(len(plan["subgoals"]), 1)
        sg = plan["subgoals"][0]
        self.assertEqual(sg["id"], 1)
        self.assertEqual(sg["depends_on"], [])


class TestBlueprintPathHonoursConfig(unittest.TestCase):
    """★ 两条路径同源：config.max_subgoals 必须对 blueprint 路径生效。"""

    def _plan_from_blueprint(self, cfg_max, dag):
        from agent.sub_goal_solver import SubGoalSolverAgent
        from unittest.mock import patch

        cfg = SimpleNamespace(max_subgoals=cfg_max, use_blueprint_dag=True,
                              enable_skeleton_review=False,
                              dag_replan_gate=False)
        agent = SubGoalSolverAgent(MagicMock(), cfg)
        ctx = TaskContext(
            problem="证明 P", metadata={}, budget=Budget(max_calls=50),
            start_time=0.0, deadline=999.0,
            total_start_time=0.0, total_deadline=9999.0,
        )
        with patch("agent.blueprint_planner.BlueprintPlannerAgent") as m_cls:
            m_cls.return_value.generate_blueprint.return_value = dag
            return agent._plan_from_blueprint(ctx)

    def test_config_cap_is_applied(self):
        plan = self._plan_from_blueprint(3, make_chain_dag(9))
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["subgoals"]), 3)

    def test_config_zero_means_all(self):
        plan = self._plan_from_blueprint(0, make_chain_dag(9))
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["subgoals"]), 9)

    def test_config_cap_differs_from_default(self):
        """回归断言：若旋钮再次失效（恒回退默认），本条会失败。"""
        plan3 = self._plan_from_blueprint(3, make_chain_dag(9))
        plan8 = self._plan_from_blueprint(8, make_chain_dag(9))
        self.assertNotEqual(len(plan3["subgoals"]), len(plan8["subgoals"]))


# ============================================================
# 3. 提示词设计约束一致性
# ============================================================

class TestBlueprintPromptDesign(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prompts.blueprint import BLUEPRINT_DAG_SYSTEM
        cls.S = BLUEPRINT_DAG_SYSTEM

    def test_no_contradictory_hard_cap(self):
        """★ 不得再有"节点总数 ≤ 5"这类与"3~30"自相矛盾的硬约束。"""
        self.assertNotIn("节点总数 ≤ 5", self.S)
        self.assertNotIn("节点总数≤5", self.S)

    def test_no_time_wall_rationale(self):
        """时间墙理由（"越长越慢"）应已移除——它是 ≤5 约束的依据。"""
        self.assertNotIn("越慢", self.S)

    def test_complexity_tiered_budget_present(self):
        self.assertIn("简单题", self.S)
        self.assertIn("难题", self.S)

    def test_anti_verbosity_rules_kept(self):
        """与时间无关的防冗余条款必须保留（评审器靠它们判质量）。"""
        self.assertIn("禁止复述题干条件", self.S)

    def test_concluding_node_rule_present(self):
        self.assertIn("收尾节点", self.S)

    def test_rationale_required(self):
        self.assertIn("必填", self.S)
        self.assertIn("同义反复", self.S)

    def test_json_example_has_no_empty_rationale(self):
        self.assertNotIn('"rationale": ""', self.S)

    def test_anticipatory_section_still_present(self):
        self.assertIn("anticipatory", self.S)

    def test_dag_review_prompt_has_purpose_dimension(self):
        from prompts.dag_review import DAG_REVIEW_SYSTEM, DAG_REVIEW_USER_TEMPLATE
        self.assertIn("分解依据", DAG_REVIEW_SYSTEM)
        self.assertIn("{rationale}", DAG_REVIEW_USER_TEMPLATE)


# ============================================================
# 4. 评审器确实拿到 rationale
# ============================================================

class TestReviewerReceivesRationale(unittest.TestCase):

    def test_rationale_reaches_prompt(self):
        """★ LEAP §2.1：Purpose 必须真的传给评审器，否则第 6 维无法判断。"""
        from agent.dag_reviewer import DagReviewerAgent
        import json as _json

        captured = {}

        def chat(messages, **kw):
            last_user = next((m["content"] for m in reversed(messages)
                              if m.get("role") == "user"), "")
            captured["user"] = last_user
            return _json.dumps({"verdict": "accept", "quality_score": 0.9,
                                "issues": [], "reconstruction_hint": ""})

        client = MagicMock()
        client.chat = chat
        cfg = SimpleNamespace(use_blueprint_dag=True, dag_review_max_nodes=30,
                              dag_review_reject_thr=0.4)
        agent = DagReviewerAgent(client, cfg)

        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明总目标 P", ["n1"]),
            "n1": BlueprintNode("n1", "and", "证明引理 A 成立", [],
                                "排除负值情形，否则下界无法确立"),
        }, root_id="g")
        ctx = TaskContext(
            problem="证明 P", metadata={}, budget=Budget(max_calls=50),
            start_time=0.0, deadline=999.0,
            total_start_time=0.0, total_deadline=9999.0,
        )
        agent._llm_review_node(ctx, dag, dag.nodes["n1"], {})
        self.assertIn("排除负值情形，否则下界无法确立", captured["user"])

    def test_missing_rationale_marked(self):
        """缺 rationale 的节点应显示占位符（而非空白，便于人工核对）。"""
        from agent.dag_reviewer import DagReviewerAgent
        import json as _json

        captured = {}

        def chat(messages, **kw):
            captured["user"] = next(
                (m["content"] for m in reversed(messages)
                 if m.get("role") == "user"), "")
            return _json.dumps({"verdict": "accept", "quality_score": 0.9,
                                "issues": [], "reconstruction_hint": ""})

        client = MagicMock()
        client.chat = chat
        cfg = SimpleNamespace(use_blueprint_dag=True, dag_review_max_nodes=30,
                              dag_review_reject_thr=0.4)
        agent = DagReviewerAgent(client, cfg)
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明总目标 P", ["n1"]),
            "n1": BlueprintNode("n1", "and", "证明引理 A 成立", []),
        }, root_id="g")
        ctx = TaskContext(
            problem="证明 P", metadata={}, budget=Budget(max_calls=50),
            start_time=0.0, deadline=999.0,
            total_start_time=0.0, total_deadline=9999.0,
        )
        agent._llm_review_node(ctx, dag, dag.nodes["n1"], {})
        self.assertIn("未给出", captured["user"])


if __name__ == "__main__":
    unittest.main()
