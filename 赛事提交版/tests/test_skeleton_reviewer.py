# -*- coding: utf-8 -*-
"""
SkeletonReviewer（骨架编排层评审，老师 9/2 建议）单元测试 —— 不依赖真实 LLM。
覆盖:
- review pass：mock LLM 全 ok → should_regenerate False（进入语法审核）
- review replan（ill_posed）：任一子目标不适定 → 触发重生成 + hint 聚合
- review replan（not_simplifying）：子目标难度 >= 原题 → 触发重生成
- LLM 异常 / JSON 解析失败 → degraded 降级放行（质量门不阻断主流程）
- 预算不足 → 降级放行
- verdicts 非法值归一化为 ok
- _skeleton_review_loop：评审 replan → regenerate_with_feedback（mock planner）→
  二次评审 pass → 采用新骨架（集成路径）
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.skeleton_reviewer import (
    SkeletonReviewerAgent, SkeletonReviewReport, SkeletonVerdict)


def make_ctx(problem="证明 f(x)=x² 在实数上非负") -> TaskContext:
    return TaskContext(
        problem=problem,
        metadata={},
        budget=Budget(max_calls=50),
        start_time=0.0,
        deadline=999.0,
        total_start_time=0.0,
        total_deadline=9999.0,
    )


def make_config(**over):
    base = dict(
        use_blueprint_dag=True,
        enable_sketch_audit=False,
        enable_skeleton_review=True,
        skeleton_review_max_rounds=2,
    )
    base.update(over)
    return SimpleNamespace(**base)


def make_mock_client(resp_map=None, default_resp=""):
    if resp_map is None:
        resp_map = {}
    client = MagicMock()
    def chat(messages, **kw):
        last_user = next((m["content"] for m in reversed(messages)
                          if m.get("role") == "user"), "")
        for key, val in resp_map.items():
            if key in last_user:
                return val
        return default_resp
    client.chat = chat
    return client


def make_dag():
    """测试 DAG：g(AND) -> n1(AND) -> n1a/n1b 叶子；n2(OR) -> n2a 叶子"""
    nodes = {
        "g": BlueprintNode(id="g", node_type="and",
                           statement="证明原命题", children=["n1", "n2"]),
        "n1": BlueprintNode(id="n1", node_type="and",
                            statement="先证明关键引理", children=["n1a", "n1b"]),
        "n1a": BlueprintNode(id="n1a", node_type="and",
                             statement="证明 f 的非负性引理", children=[]),
        "n1b": BlueprintNode(id="n1b", node_type="and",
                             statement="证明 f 的连续性引理", children=[]),
        "n2": BlueprintNode(id="n2", node_type="or",
                            statement="选择主证明路径", children=["n2a"]),
        "n2a": BlueprintNode(id="n2a", node_type="and",
                             statement="直接完成原题证明", children=[]),
    }
    return BlueprintDAG(nodes=nodes, root_id="g", merge_strategy="测试")


def _resp(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TestSkeletonReviewerAgent(unittest.TestCase):

    def test_review_pass(self):
        """全 ok → pass，should_regenerate False。"""
        client = make_mock_client(resp_map={
            "评审要求": _resp({
                "verdicts": {
                    "g": {"verdict": "ok", "reason": ""},
                    "n1": {"verdict": "ok", "reason": ""},
                    "n1a": {"verdict": "ok", "reason": ""},
                    "n1b": {"verdict": "ok", "reason": ""},
                    "n2": {"verdict": "ok", "reason": ""},
                    "n2a": {"verdict": "ok", "reason": ""},
                },
                "overall": "pass",
                "feedback": "",
            }),
        })
        reviewer = SkeletonReviewerAgent(client, make_config())
        ctx = make_ctx()
        report = reviewer.review(ctx, make_dag())
        self.assertEqual(report.overall, "pass")
        self.assertFalse(report.should_regenerate())
        self.assertEqual(report.replan_nodes, [])
        self.assertFalse(report.degraded)

    def test_review_ill_posed_triggers_replan(self):
        """n1a 不适定（ill_posed）→ replan + hint 进入 feedback_lines。"""
        client = make_mock_client(resp_map={
            "评审要求": _resp({
                "verdicts": {
                    "n1a": {"verdict": "ill_posed",
                            "reason": "缺乏 f 的定义域",
                            "hint": "补上 f 的定义域与连续性假设"},
                    "n1b": {"verdict": "ok", "reason": ""},
                    "n2a": {"verdict": "ok", "reason": ""},
                },
                "overall": "replan",
                "feedback": "请补充子目标所需定义域条件",
            }),
        })
        reviewer = SkeletonReviewerAgent(client, make_config())
        ctx = make_ctx()
        report = reviewer.review(ctx, make_dag())
        self.assertTrue(report.should_regenerate())
        self.assertIn("n1a", report.replan_nodes)
        lines = report.feedback_lines()
        self.assertTrue(any("定义域" in ln for ln in lines))

    def test_review_not_simplifying_triggers_replan(self):
        """n2a 难度 >= 原题（not_simplifying）→ replan。"""
        client = make_mock_client(resp_map={
            "评审要求": _resp({
                "verdicts": {
                    "n2a": {"verdict": "not_simplifying",
                            "reason": "等价于原题",
                            "hint": "拆出可独立推进的中间结论"},
                },
                "overall": "replan",
                "feedback": "",
            }),
        })
        reviewer = SkeletonReviewerAgent(client, make_config())
        report = reviewer.review(make_ctx(), make_dag())
        self.assertTrue(report.should_regenerate())
        self.assertEqual(report.replan_nodes, ["n2a"])

    def test_llm_exception_degrades_pass(self):
        """LLM 抛异常 → degraded=True，should_regenerate False（放行不阻断）。"""
        client = MagicMock()
        client.chat = MagicMock(side_effect=RuntimeError("boom"))
        reviewer = SkeletonReviewerAgent(client, make_config())
        ctx = make_ctx()
        report = reviewer.review(ctx, make_dag())
        self.assertTrue(report.degraded)
        self.assertFalse(report.should_regenerate())

    def test_json_parse_fail_degrades_pass(self):
        """LLM 返回非 JSON → degraded 放行。"""
        client = make_mock_client(default_resp="这不是 JSON")
        reviewer = SkeletonReviewerAgent(client, make_config())
        report = reviewer.review(make_ctx(), make_dag())
        self.assertTrue(report.degraded)
        self.assertFalse(report.should_regenerate())

    def test_budget_exhausted_degrades_pass(self):
        """预算耗尽（can_spend=False）→ 跳过评审直接放行。"""
        client = make_mock_client(resp_map={"评审要求": _resp({
            "overall": "replan", "verdicts": {}})})
        reviewer = SkeletonReviewerAgent(client, make_config())
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        report = reviewer.review(ctx, make_dag())
        self.assertTrue(report.degraded)
        self.assertFalse(report.should_regenerate())

    def test_invalid_verdict_normalized_to_ok(self):
        """非法 verdict 值归一化为 ok。"""
        client = make_mock_client(resp_map={
            "评审要求": _resp({
                "verdicts": {
                    "n1a": {"verdict": "maybe", "reason": ""},
                },
                "overall": "pass",
                "feedback": "",
            }),
        })
        reviewer = SkeletonReviewerAgent(client, make_config())
        report = reviewer.review(make_ctx(), make_dag())
        self.assertEqual(report.verdicts["n1a"].verdict, "ok")
        self.assertFalse(report.should_regenerate())

    def test_overall_replan_with_empty_verdicts(self):
        """overall=replan 但 verdicts 缺失 → 仍触发重生成（overall 为主判）。"""
        client = make_mock_client(resp_map={
            "评审要求": _resp({"overall": "replan",
                              "feedback": "整体拆解方向不对"}),
        })
        reviewer = SkeletonReviewerAgent(client, make_config())
        report = reviewer.review(make_ctx(), make_dag())
        self.assertTrue(report.should_regenerate())
        # feedback_lines 兜底不为空
        self.assertTrue(report.feedback_lines())

    def test_loop_regenerate_then_pass(self):
        """集成：评审 replan → regenerate_with_feedback（mock planner）→
        二次评审 pass → 返回新骨架。"""
        from agent.sub_goal_solver import SubGoalSolverAgent

        reviewer = SkeletonReviewerAgent(
            make_mock_client(resp_map={
                "评审要求": _resp({
                    "verdicts": {"n1a": {"verdict": "ill_posed",
                                         "reason": "不适定",
                                         "hint": "拆细"}},
                    "overall": "replan",
                    "feedback": "请拆细 n1a",
                }),
            }), make_config())
        # 第二次评审 pass
        reviewer_patcher = patch.object(
            SkeletonReviewerAgent, "review",
            side_effect=[
                SkeletonReviewReport(
                    verdicts={"n1a": SkeletonVerdict("n1a", "ill_posed",
                                                     "不适定", "拆细")},
                    overall="replan",
                    feedback="请拆细 n1a"),
                SkeletonReviewReport(
                    verdicts={"n1a": SkeletonVerdict("n1a", "ok")},
                    overall="pass"),
            ])
        # mock planner：regenerate_with_feedback 返回新 DAG
        new_dag = make_dag()
        new_dag.nodes["n1a"].statement = "证明 f 定义域内非负（细化）"
        planner = MagicMock()
        planner.regenerate_with_feedback.return_value = new_dag

        solver = SubGoalSolverAgent(MagicMock(), make_config(
            enable_skeleton_review=True, skeleton_review_max_rounds=2))
        with reviewer_patcher, patch.object(
                SubGoalSolverAgent, "_audit_blueprint_tree", lambda self, ctx, dag: None):
            result = solver._skeleton_review_loop(make_ctx(), make_dag(), planner)
        self.assertIs(result, new_dag)
        # regenerate_with_feedback 只被调用 1 次（第二次评审通过就停）
        self.assertEqual(planner.regenerate_with_feedback.call_count, 1)
        # 反馈确实传给了重生成
        fb = planner.regenerate_with_feedback.call_args[1]["feedback_lines"]
        self.assertTrue(any("拆细" in ln for ln in fb))

    def test_loop_budget_exhausted_keeps_dag(self):
        """集成：重生成前预算不足（can_spend 检查在循环内）→ 保留当前骨架。"""
        from agent.sub_goal_solver import SubGoalSolverAgent
        planner = MagicMock()
        solver = SubGoalSolverAgent(MagicMock(), make_config(
            enable_skeleton_review=True, skeleton_review_max_rounds=2))
        ctx = make_ctx()
        # 第一次评审返回 replan（非 degraded），但循环内重生成前 can_spend(2)=False
        with patch.object(SkeletonReviewerAgent, "review", return_value=SkeletonReviewReport(
                verdicts={"n1a": SkeletonVerdict("n1a", "ill_posed")},
                overall="replan")):
            dag = make_dag()
            ctx.budget = Budget(max_calls=1)  # 1+2<=1 False → 重生成前卡住
            result = solver._skeleton_review_loop(ctx, dag, planner)
        self.assertIs(result, dag)
        self.assertEqual(planner.regenerate_with_feedback.call_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
