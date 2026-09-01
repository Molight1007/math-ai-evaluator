# -*- coding: utf-8 -*-
"""
DagReviewer（LEAP 5.3，#34）单元测试 —— 不依赖真实 LLM。
覆盖:
- _token_overlap：词袋 Jaccard 边界
- _heuristic_screen：循环风险 + 粒度过粗识别（不调 LLM）
- _llm_review_node：mock LLM 走通 accept / reject 两路
- review：启发式 + LLM 全流程，含 budget.can_spend 护栏
- DagReviewReport.should_replan：阈值正确性
- DagReviewReport.merge_from_hints：hint 聚合格式
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.dag_reviewer import (
    DagReviewerAgent, DagReviewResult, DagReviewReport,
    _token_overlap, MIN_STATEMENT_CHARS, CIRCULARITY_TOKEN_OVERLAP,
    REJECT_REPLAN_THRESHOLD, REJECT_REPLAN_COUNT,
)


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
    """构造最小 config（用 SimpleNamespace，模仿 user_agent.ReasoningAgent 风格）。"""
    base = dict(
        use_blueprint_dag=True,
        enable_sketch_audit=False,
        use_leansearch=False,
        theorem_memory_enable=False,
        theorem_memory_path="",
        theorem_memory_top_k=5,
        dag_review_max_nodes=30,
        dag_review_reject_thr=REJECT_REPLAN_THRESHOLD,
    )
    base.update(over)
    return SimpleNamespace(**base)


def make_mock_client(resp_map=None, default_resp=""):
    """构造 mock LLM client：按 messages 末段内容查表返回，否则用 default。"""
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
    """构造测试 DAG：

    g (AND, root)
      ├── n1 (AND)
      │     ├── n1a (leaf, 大概率循环风险 - 与 g 词袋重叠 90%)
      │     └── n1b (leaf, 短句 - 粒度过粗)
      └── n2 (OR)
            ├── n2a (leaf, 健康)
            └── n2b (leaf, 健康)

    关键约束：根 g 必须列 n1/n2 为 children，
    否则 DAG 是退化的（root leaf only），失去 AND 分解意义。
    """
    nodes = {
        "g": BlueprintNode("g", "and", "证明 f(x)=x^2 在实数上非负 x^2 几何平方",
                            ["n1", "n2"]),
        "n1": BlueprintNode("n1", "and", "第一步 x^2 几何平方平方", ["n1a", "n1b"]),
        "n2": BlueprintNode("n2", "or", "策略二：直接展开代数", ["n2a", "n2b"]),
        # n1a 与 g 词袋高度重叠 → 启发式 reject（circular_risk）
        "n1a": BlueprintNode("n1a", "and", "证明 f(x)=x^2 在实数上非负 x^2 几何平方", []),
        # n1b 短句 → 启发式 reject（under_specified）
        "n1b": BlueprintNode("n1b", "and", "ok", []),
        # n2a / n2b 健康（叶子） → LLM 评审
        "n2a": BlueprintNode("n2a", "and", "写出 f(x)=x^2-0 的非负性", []),
        "n2b": BlueprintNode("n2b", "and", "归纳 x≥0 与 x<0 两种情形", []),
    }
    return BlueprintDAG(nodes=nodes, root_id="g")


# ============================================================
# 词袋相似度（基础工具）
# ============================================================

class TestTokenOverlap(unittest.TestCase):

    def test_identical(self):
        self.assertGreater(_token_overlap("x^2 平方", "x^2 平方"), 0.99)

    def test_no_overlap(self):
        self.assertEqual(_token_overlap("apple", "banana cat"), 0.0)

    def test_empty(self):
        self.assertEqual(_token_overlap("", "abc"), 0.0)
        self.assertEqual(_token_overlap("abc", ""), 0.0)

    def test_partial_overlap_below_threshold(self):
        # 0.5 < CIRCULARITY_TOKEN_OVERLAP 0.7 → 不循环
        s1 = "证明 x^2 非负"
        s2 = "考虑正整数 n 的等差数列求和"
        sim = _token_overlap(s1, s2)
        self.assertLess(sim, CIRCULARITY_TOKEN_OVERLAP)

    def test_high_overlap_above_threshold(self):
        # 词袋相似 > 0.7 → 视为循环风险
        s1 = "证明函数 f x 平方 在 实数 上 非负 等价于 几何 平方"
        s2 = "证明函数 f x 平方 在 实数 上 非负 这是 几何 平方定义"
        sim = _token_overlap(s1, s2)
        self.assertGreater(sim, CIRCULARITY_TOKEN_OVERLAP)


# ============================================================
# 启发式筛
# ============================================================

class TestHeuristicScreen(unittest.TestCase):

    def setUp(self):
        self.config = make_config()
        self.ctx = make_ctx()
        self.client = make_mock_client()
        self.agent = DagReviewerAgent(self.client, self.config)
        self.dag = make_dag()

    def test_circular_risk_caught(self):
        results = self.agent._heuristic_screen(self.dag)
        # n1a 与 g 词袋重叠高 → reject
        self.assertIn("n1a", results)
        self.assertEqual(results["n1a"].verdict, "reject")
        self.assertTrue(any("circular_risk" in i for i in results["n1a"].issues))

    def test_under_specified_caught(self):
        results = self.agent._heuristic_screen(self.dag)
        # n1b 字数 < MIN → reject
        self.assertIn("n1b", results)
        self.assertEqual(results["n1b"].verdict, "reject")
        self.assertTrue(any("under_specified" in i for i in results["n1b"].issues))
        self.assertTrue(results["n1b"].heuristic_only)

    def test_healthy_nodes_not_rejected_by_heuristic(self):
        results = self.agent._heuristic_screen(self.dag)
        # n2a / n2b 是健康的，启发式不应 reject 它们
        self.assertNotIn("n2a", results)
        self.assertNotIn("n2b", results)


# ============================================================
# LLM 评审（mock 拒真/拒假）
# ============================================================

class TestLLMReviewNode(unittest.TestCase):

    def setUp(self):
        self.config = make_config()
        self.ctx = make_ctx()
        self.dag = make_dag()

    def test_accept_path(self):
        accept_json = json.dumps({
            "verdict": "accept", "quality_score": 0.92,
            "issues": [],
            "reconstruction_hint": "",
        })
        client = make_mock_client(default_resp=accept_json)
        agent = DagReviewerAgent(client, self.config)
        n2a = self.dag.nodes["n2a"]
        res = agent._llm_review_node(self.ctx, self.dag, n2a, {})
        self.assertEqual(res.verdict, "accept")
        self.assertEqual(res.quality_score, 0.92)
        self.assertFalse(res.heuristic_only)

    def test_reject_path(self):
        reject_json = json.dumps({
            "verdict": "reject", "quality_score": 0.3,
            "issues": ["粒度过粗：该子目标重述了父目标语义", "无新约束"],
            "reconstruction_hint": "把 statement 改成具体可证明的等价命题",
        })
        client = make_mock_client(default_resp=reject_json)
        agent = DagReviewerAgent(client, self.config)
        n2a = self.dag.nodes["n2a"]
        res = agent._llm_review_node(self.ctx, self.dag, n2a, {})
        self.assertEqual(res.verdict, "reject")
        self.assertEqual(len(res.issues), 2)
        self.assertIn("把 statement", res.reconstruction_hint)

    def test_malformed_response_defaults_to_accept(self):
        # LLM 返回非 JSON 时不应崩；默认 accept（保守）
        client = make_mock_client(default_resp="我没法评审这道题")
        agent = DagReviewerAgent(client, self.config)
        res = agent._llm_review_node(
            self.ctx, self.dag, self.dag.nodes["n2a"], {})
        self.assertEqual(res.verdict, "accept")  # 兜底
        self.assertFalse(res.heuristic_only)


# ============================================================
# review 全流程
# ============================================================

class TestReviewFullFlow(unittest.TestCase):

    def test_dag_review_produces_report(self):
        # 启发式 reject: n1a (循环) + n1b (粒度粗)
        # LLM reject: n2a; accept: n2b / n1 / n2 / g (非叶 + 根, 默认 accept)
        resp_map = {
            "n2a": json.dumps({"verdict": "reject", "quality_score": 0.3,
                               "issues": ["粒度过粗"],
                               "reconstruction_hint": "改具体"}),
            "n2b": json.dumps({"verdict": "accept", "quality_score": 0.92,
                               "issues": [], "reconstruction_hint": ""}),
        }
        client = make_mock_client(resp_map=resp_map, default_resp=json.dumps(
            {"verdict": "accept", "quality_score": 0.5, "issues": [], "reconstruction_hint": ""}
        ))
        config = make_config()
        agent = DagReviewerAgent(client, config)
        dag = make_dag()
        ctx = make_ctx()

        report = agent.review(ctx, dag, results_map={})

        # 启发式 reject: n1a + n1b; LLM reject: n2a → 共 3 reject
        self.assertEqual(report.reject_count, 3)
        # accept: g/n1/n2/n2b（非启发式 reject 的全走 LLM，默认 accept）→ 4
        self.assertEqual(report.accept_count, 4)
        # should_replan 默认 True（reject_ratio = 3/7 ≈ 0.43 > 0.40）
        self.assertTrue(report.should_replan())
        self.assertIn("n1a", report.rejected_nodes())
        self.assertIn("n1b", report.rejected_nodes())
        self.assertIn("n2a", report.rejected_nodes())
        self.assertIn("n2b", report.accepted_nodes())

        # 写入 ctx.dag_review_report（dict 序列化）
        self.assertIn("results", ctx.dag_review_report)
        self.assertEqual(ctx.dag_review_report["reject_count"], 3)

    def test_review_respects_budget(self):
        # 预算耗尽时 review 直接返回空报告
        client = make_mock_client()
        config = make_config()
        agent = DagReviewerAgent(client, config)
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)  # 预算=0
        report = agent.review(ctx, make_dag(), results_map={})
        self.assertEqual(len(report.results), 0)

    def test_should_replan_thresholds(self):
        # 阈值正确性
        r1 = DagReviewReport({"a": DagReviewResult("a", "reject", 0.3)})
        self.assertTrue(r1.should_replan())  # 1 个 reject ≥ 3？不，1 < 3 但 ratio 1.0 ≥ 0.4
        r2 = DagReviewReport({"a": DagReviewResult("a", "accept", 0.9),
                              "b": DagReviewResult("b", "accept", 0.9),
                              "c": DagReviewResult("c", "accept", 0.9)})
        self.assertFalse(r2.should_replan())  # 0 reject
        # 拒绝数恰好 = 3 且 ratio = 0.4
        r3 = DagReviewReport(
            {f"x{i}": DagReviewResult(f"x{i}", "reject", 0.2) for i in range(3)}
        )
        # 拒 3 占比 1.0 → True
        r4 = DagReviewReport({f"x{i}": DagReviewResult(f"x{i}", "reject", 0.2)
                               for i in range(3)} | {
            f"y{i}": DagReviewResult(f"y{i}", "accept", 0.9) for i in range(7)
        })
        # 9/1 阈值 3→5：3/10=30% 不触发（原 count>=3 误卡低比例大图，见冒烟 006/017/027）
        self.assertFalse(r4.should_replan())
        # 5 reject + 5 accept = 50% → 比例触发
        r5 = DagReviewReport({f"x{i}": DagReviewResult(f"x{i}", "reject", 0.2)
                               for i in range(5)} | {
            f"y{i}": DagReviewResult(f"y{i}", "accept", 0.9) for i in range(5)
        })
        self.assertTrue(r5.should_replan())  # 5/10=50% ≥ 40%

    def test_merge_from_hints(self):
        report = DagReviewReport({
            "n1": DagReviewResult("n1", "reject", 0.2,
                                  [], "粒度过粗应改具体"),
            "n2": DagReviewResult("n2", "reject", 0.3,
                                  [], "循环风险应重写"),
            "n3": DagReviewResult("n3", "accept", 0.9,
                                  [], ""),
        })
        s = report.merge_from_hints()
        self.assertIn("[n1] 粒度过粗应改具体", s)
        self.assertIn("[n2] 循环风险应重写", s)
        self.assertNotIn("[n3]", s)


# ============================================================
# 与 BlueprintDAG 集成
# ============================================================

class TestIntegrationWithBlueprint(unittest.TestCase):

    def test_reviewer_records_to_ctx(self):
        client = make_mock_client(default_resp=json.dumps(
            {"verdict": "accept", "quality_score": 0.8, "issues": [], "reconstruction_hint": ""}
        ))
        agent = DagReviewerAgent(client, make_config())
        ctx = make_ctx()
        dag = make_dag()
        report = agent.review(ctx, dag)
        # trace 包含 dag_review
        trace_types = [t.get("step", "") for t in ctx.trace]
        self.assertTrue(any("dag_review" == st for st in trace_types))


if __name__ == "__main__":
    unittest.main()
