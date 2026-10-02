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
import os
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.dag_reviewer import (
    DagReviewerAgent, DagReviewResult, DagReviewReport,
    ISSUE_CANON, ISSUE_CN, normalize_issue_tag,
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

    def test_review_respects_time_critical(self):
        """2026-09-03 预算解除：时间紧迫才跳过 DAG 评审（返回空报告）。

        原 test_review_respects_budget 用 Budget(max_calls=0) 模拟预算耗尽
        期望空报告——预算闸门已删，预算=0 评审照常执行（启发式+LLM 全跑）。
        真实跳过条件是 is_time_critical()（deadline 过期）。
        """
        import time as _t
        client = make_mock_client()
        config = make_config()
        agent = DagReviewerAgent(client, config)
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)  # 预算=0（不再阻断）
        ctx.deadline = _t.time() - 1  # 真实时间戳已过期 → 时间紧迫
        report = agent.review(ctx, make_dag(), results_map={})
        self.assertEqual(len(report.results), 0)

    def test_budget_zero_still_reviews(self) -> None:
        """预算=0 不再阻断：DAG 评审照常产出结果（新语义）。"""
        client = make_mock_client()
        config = make_config()
        agent = DagReviewerAgent(client, config)
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        report = agent.review(ctx, make_dag(), results_map={})
        self.assertGreater(len(report.results), 0)

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


# ======================================================================
# issues 标签归一化（2026-09-30，截图 #6「蓝图的设计有没有问题」）
# ----------------------------------------------------------------------
# 背景（**存量数据实测**，official112_local_0910）：
#   circular_risk=190 / circularity=190        ← 同一含义被算成两类
#   invalid_dependencies=38 / invalid_dependency=30
#   missing_dependency=17 / missing_dependencies=16
#   simplification* 系列 7 种写法共 55 条全落 other
# ⇒ 不做归一化，「蓝图哪一维度最常出问题」的统计会被系统性打散。
# ======================================================================

ISSUE_TAG_CASES = [
    # 循环：同义异写必须合并
    ("circularity:与祖辈 X 相似", "circular_risk"),
    ("circular_risk:与祖辈 X 相似", "circular_risk"),
    ("circular:xxx", "circular_risk"),
    ("dependency_circular:自引用", "circular_risk"),
    # 依赖：单复数必须合并
    ("invalid_dependency:缺前置", "invalid_dependencies"),
    ("invalid_dependencies:缺前置", "invalid_dependencies"),
    ("dependency_error:xxx", "invalid_dependencies"),
    ("missing_dependency:缺关键前置", "missing_dependency"),
    ("missing_dependencies:缺关键前置", "missing_dependency"),
    # 简单化：7 种 simplification* 变体 + decomposition
    ("simplification:未简化", "no_simplification"),
    ("simplification_failed:未简化", "no_simplification"),
    ("simplification_failure:未简化", "no_simplification"),
    ("simplification_fail:未简化", "no_simplification"),
    ("simplifies:未简化", "no_simplification"),
    ("simplifies_fail:未简化", "no_simplification"),
    ("simplifies_failure:未简化", "no_simplification"),
    ("simplifies_parent:未简化", "no_simplification"),
    ("simplifies_child:未简化", "no_simplification"),
    ("missing_decomposition:未拆", "no_simplification"),
    ("decomposition:未拆", "no_simplification"),
    ("no_simplification:未简化", "no_simplification"),
    ("under_specified:过短", "under_specified"),
    ("underspecified:过短", "under_specified"),
    # 可行路径
    ("feasibility:无路径", "feasible_path"),
    ("feasible_route:无路径", "feasible_path"),
    ("no_feasible_path:无路径", "feasible_path"),
    ("no_plausible_route:无路径", "feasible_path"),
    ("no_valid_path:无路径", "feasible_path"),
    ("unfeasible:无路径", "feasible_path"),
    ("infeasible:无路径", "feasible_path"),
    ("feasible_path:无路径", "feasible_path"),
    # 数学合理性
    ("soundness:矛盾", "math_soundness"),
    ("math_unsoundness:矛盾", "math_soundness"),
    ("math_soundness:矛盾", "math_soundness"),
    ("math_soundness_issue:矛盾", "math_soundness"),
    # 依据（含 missing_justification / missing_lemma 实测两类）
    ("missing_rationale:无依据", "missing_rationale"),
    ("rationale:无依据", "missing_rationale"),
    ("missing_justification:无引理支撑", "missing_rationale"),
    ("missing_lemma:无引理", "missing_rationale"),
    # 衔接
    ("coherence:接不上", "coherence"),
    ("cohesion:接不上", "coherence"),
    # Lean 逻辑层（sub_goal_solver 升级写入）
    ("lean_logic_error: unknown identifier 'x'", "lean_logic_error"),
    # 兜底：认不出的一律 other，**绝不硬塞**
    ("", "other"),
    ("无冒号的一整句话", "other"),
    ("完全没见过的标签:描述", "other"),
    (None, "other"),
]


@mock.patch.dict(os.environ, {"LEAN_VERIFY": "0"})
class TestIssueTagNormalization(unittest.TestCase):

    def test_all_synonym_variants_normalize(self):
        """★ 核心：同义异写必须归到同一标签（否则统计被打散）。"""
        bad = []
        for raw, expected in ISSUE_TAG_CASES:
            got = normalize_issue_tag(raw)
            if got != expected:
                bad.append(f"{raw!r}: got {got!r}, want {expected!r}")
        self.assertEqual(bad, [], "归一化失效：\n" + "\n".join(bad))

    def test_unknown_tags_are_not_forced_into_a_category(self):
        """★ 反向对照：认不出的标签必须落 other，不得被猜着塞进某类。"""
        self.assertEqual(normalize_issue_tag("totally_new_tag:描述"), "other")
        self.assertEqual(normalize_issue_tag(""), "other")

    def test_case_and_space_insensitive(self):
        """标签大小写/前后空格不应影响归类（模型输出很随意）。"""
        self.assertEqual(normalize_issue_tag("  Circular_Risk : x"), "circular_risk")
        self.assertEqual(normalize_issue_tag("UNDER_SPECIFIED:x"), "under_specified")

    def test_every_canon_target_has_chinese_label(self):
        """ISSUE_CN 必须覆盖 ISSUE_CANON 的全部取值 —— 否则报告里出现裸英文标签。"""
        missing = [t for t in set(ISSUE_CANON.values()) if t not in ISSUE_CN]
        self.assertEqual(missing, [], f"缺中文释义: {missing}")

    def test_histogram_merges_synonyms(self):
        """★ 直方图：190 条 circularity + 190 条 circular_risk 应合成 380。"""
        rep = DagReviewReport(results={
            "a": DagReviewResult("a", "reject", issues=["circularity:x"] * 3),
            "b": DagReviewResult("b", "reject", issues=["circular_risk:y"] * 2),
            "c": DagReviewResult("c", "accept", quality_score=0.9),
            "d": DagReviewResult("d", "reject", issues=["under_specified:z"]),
        })
        h = rep.issue_histogram()
        self.assertEqual(h["circular_risk"], 5)
        self.assertEqual(h["under_specified"], 1)
        self.assertEqual(sum(h.values()), 6)
        # accept 节点不进直方图
        self.assertNotIn("accept", h)

    def test_histogram_handles_no_issues(self):
        rep = DagReviewReport(results={"a": DagReviewResult("a", "reject")})
        self.assertEqual(rep.issue_histogram(), {})

    def test_to_dict_includes_histogram(self):
        """to_dict 是落盘通道 —— 不带直方图，离线就没法做归因。"""
        rep = DagReviewReport(results={
            "a": DagReviewResult("a", "reject", issues=["circularity:x"])})
        self.assertIn("issue_histogram", rep.to_dict())
        self.assertEqual(rep.to_dict()["issue_histogram"]["circular_risk"], 1)

    def test_fix_rate_counts_only_persisting_node_ids(self):
        """★ 修复率只认"两轮都在的节点"：节点换 id 不计入，避免'节点没了=修好了'的自欺。"""
        prev = DagReviewReport(results={
            "n1": DagReviewResult("n1", "reject", issues=["circular_risk:x"]),
            "n2": DagReviewResult("n2", "reject", issues=["circular_risk:y"]),
            # 本轮换 id 消失的节点 —— 不算修复证据
            "gone": DagReviewResult("gone", "reject", issues=["circular_risk:z"]),
        })
        cur = DagReviewReport(results={
            "n1": DagReviewResult("n1", "accept", quality_score=0.9),   # 修好了
            "n2": DagReviewResult("n2", "reject", issues=["circular_risk:y"]),  # 没修
        })
        fr = cur.issue_fix_rate(prev)
        self.assertEqual(fr["circular_risk"]["seen"], 2)   # gone 不算
        self.assertEqual(fr["circular_risk"]["fixed"], 1)
        self.assertEqual(fr["circular_risk"]["fixed_ratio"], 0.5)

    def test_fix_rate_empty_without_prev(self):
        """首轮无对照 ⇒ 必须返回空，不得伪造修复率。"""
        cur = DagReviewReport(results={
            "n1": DagReviewResult("n1", "accept", quality_score=0.9)})
        self.assertEqual(cur.issue_fix_rate(None), {})
        self.assertEqual(cur.issue_fix_rate(DagReviewReport()), {})

    def test_real_gt_would_break_if_canon_were_identity(self):
        """★ 阳性对照：若 ISSUE_CANON 退化成恒等映射，本用例应红。"""
        # circularity 不是规范标签 ⇒ 映射后必须变化
        self.assertNotEqual(normalize_issue_tag("circularity:x"), "circularity")
        # invalid_dependency（单数）不是规范标签
        self.assertNotEqual(normalize_issue_tag("invalid_dependency:x"),
                            "invalid_dependency")
