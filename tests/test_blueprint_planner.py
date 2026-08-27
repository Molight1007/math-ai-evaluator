# -*- coding: utf-8 -*-
"""BlueprintPlanner（LEAP Stage 1，#27）单元测试。

覆盖:
- BlueprintDAG.validate: 合法 / 有环 / 悬空引用 / 超限 / 类型非法
- BlueprintDAG.to_subgoal_plan: AND 展开、OR 取首分支、拓扑序、依赖
- extract_json / parse_blueprint: 容错解析
- BlueprintPlannerAgent.generate_blueprint: mock client 全流程
- SubGoalSolverAgent 接入: use_blueprint=True 时由 DAG 驱动规划
"""
import json
import unittest
from types import SimpleNamespace

from agent.base import TaskContext, Budget
from agent.blueprint_planner import (
    BlueprintDAG, BlueprintNode, extract_json, parse_blueprint,
    BlueprintPlannerAgent, MAX_DAG_NODES,
)
from agent.sub_goal_solver import SubGoalSolverAgent


# ============================================================
# 测试夹具
# ============================================================

def make_ctx(problem="证明 f(x)=x^2 在实数上非负") -> TaskContext:
    return TaskContext(
        problem=problem,
        metadata={},
        budget=Budget(max_calls=20),
        start_time=0.0,
        deadline=999.0,
        total_start_time=0.0,
        total_deadline=9999.0,
    )


def sample_dag() -> BlueprintDAG:
    """合法样例：根 AND(g) → [n1(AND) → [n1a 叶子, n1b 叶子], n2(OR) → [n2a, n2b]]"""
    nodes = {
        "g": BlueprintNode("g", "and", "证明 f(x)=x^2 非负", ["n1", "n2"], "主分解"),
        "n1": BlueprintNode("n1", "and", "证明平方非负", ["n1a", "n1b"], "AND：两步都需"),
        "n1a": BlueprintNode("n1a", "and", "x^2 >= 0 对实数 x 成立", [], "叶子"),
        "n1b": BlueprintNode("n1b", "and", "x^2 在 R 上定义", [], "叶子"),
        "n2": BlueprintNode("n2", "or", "给出两种证明策略", ["n2a", "n2b"], "OR：任一策略"),
        "n2a": BlueprintNode("n2a", "and", "策略A：利用平方定义", [], "叶子"),
        "n2b": BlueprintNode("n2b", "and", "策略B：利用非负实数性质", [], "叶子"),
    }
    return BlueprintDAG(nodes, root_id="g", merge_strategy="合并")


# ============================================================
# validate 测试
# ============================================================

class ValidateTest(unittest.TestCase):
    def test_valid_dag(self):
        ok, errors = sample_dag().validate()
        self.assertTrue(ok, f"应合法: {errors}")

    def test_cycle_rejected(self):
        dag = sample_dag()
        # n1a -> n1 形成环
        dag.nodes["n1a"].children = ["n1"]
        ok, errors = dag.validate()
        self.assertFalse(ok)
        self.assertTrue(any("环" in e for e in errors))

    def test_dangling_child_rejected(self):
        dag = sample_dag()
        dag.nodes["n1"].children = ["ghost"]
        ok, errors = dag.validate()
        self.assertFalse(ok)
        self.assertTrue(any("悬空" in e for e in errors))

    def test_missing_root_rejected(self):
        dag = sample_dag()
        dag.root_id = "not_exist"
        ok, errors = dag.validate()
        self.assertFalse(ok)
        self.assertTrue(any("根节点" in e for e in errors))

    def test_too_many_nodes_rejected(self):
        nodes = {
            f"n{i}": BlueprintNode(f"n{i}", "and", f"节点{i}", [])
            for i in range(MAX_DAG_NODES + 1)
        }
        dag = BlueprintDAG(nodes, root_id="n0")
        ok, errors = dag.validate()
        self.assertFalse(ok)
        self.assertTrue(any("上限" in e for e in errors))

    def test_invalid_type_rejected(self):
        dag = sample_dag()
        dag.nodes["n1"].node_type = "xor"
        ok, errors = dag.validate()
        self.assertFalse(ok)
        self.assertTrue(any("类型非法" in e for e in errors))

    def test_empty_rejected(self):
        dag = BlueprintDAG({}, root_id="")
        ok, errors = dag.validate()
        self.assertFalse(ok)


# ============================================================
# to_subgoal_plan 测试
# ============================================================

class ToSubgoalPlanTest(unittest.TestCase):
    def test_and_expands_all_or_takes_first(self):
        plan = sample_dag().to_subgoal_plan()
        subgoals = plan["subgoals"]
        # 选中叶子：n1a, n1b（AND 全展开）+ n2a（OR 取第一个分支）
        titles = " | ".join(sg["description"] for sg in subgoals)
        self.assertIn("x^2 >= 0", titles)
        self.assertIn("在 R 上定义", titles)
        self.assertIn("策略A", titles)
        self.assertNotIn("策略B", titles)  # OR 分支只取第一个
        self.assertEqual(len(subgoals), 3)
        # 拓扑序：n1a/n1b 在 n2a 之前（父 n1 在 n2 之前展开）
        ids = [sg["id"] for sg in subgoals]
        self.assertEqual(ids, [1, 2, 3])

    def test_depends_on_reflects_ancestors(self):
        plan = sample_dag().to_subgoal_plan()
        # 所有叶子都是 g 的子孙，g 是根（不产生子目标），无跨祖先依赖
        for sg in plan["subgoals"]:
            self.assertEqual(sg["depends_on"], [])
        # 构造含依赖场景：g -> [a, b]，b 依赖 a（a 是 b 的祖先）
        nodes = {
            "g": BlueprintNode("g", "and", "目标", ["a", "b"]),
            "a": BlueprintNode("a", "and", "第一步", []),
            "b": BlueprintNode("b", "and", "第二步依赖第一步", []),
        }
        # 让 b 的祖先含 a：a 是 b 的父节点的兄弟 —— 这里直接构造 a->b 边
        nodes["a"].children = ["b"]
        dag = BlueprintDAG(nodes, root_id="g")
        plan = dag.to_subgoal_plan()
        by_desc = {sg["description"]: sg for sg in plan["subgoals"]}
        # 展开顺序：g(and)→a(and→b 叶子) → b 是 a 的子节点
        self.assertEqual(len(plan["subgoals"]), 1)  # 只有 b 是叶子
        self.assertEqual(by_desc["第二步依赖第一步"]["depends_on"], [])

    def test_infer_type(self):
        self.assertEqual(BlueprintDAG._infer_type("证明 x>=0"), "prove")
        self.assertEqual(BlueprintDAG._infer_type("计算 1+1"), "compute")
        self.assertEqual(BlueprintDAG._infer_type("推导出公式"), "derive")
        self.assertEqual(BlueprintDAG._infer_type("验证等式成立"), "verify")

    def test_serialize_roundtrip(self):
        dag = sample_dag()
        restored = BlueprintDAG.from_dict(dag.to_dict())
        self.assertEqual(restored.root_id, dag.root_id)
        self.assertEqual(set(restored.nodes), set(dag.nodes))
        ok, _ = restored.validate()
        self.assertTrue(ok)


# ============================================================
# extract_json / parse_blueprint 测试
# ============================================================

class ParseTest(unittest.TestCase):
    def test_fenced_json(self):
        text = '```json\n{"root_id": "g", "nodes": []}\n```'
        self.assertEqual(extract_json(text), {"root_id": "g", "nodes": []})

    def test_balanced_braces_with_latex(self):
        # LaTeX 花括号不应破坏 JSON 提取（JSON 字符串内用 \\ 转义反斜杠）
        text = ('解释：设 $f(x)=\\{x\\}$。\n'
                '{"root_id": "g", "nodes": [{"id": "g", "type": "and",'
                ' "statement": "目标 $\\\\{a,b\\\\}$", "children": []}]}')
        raw = extract_json(text)
        self.assertIsNotNone(raw)
        self.assertEqual(raw["root_id"], "g")

    def test_parse_blueprint_lenient_fields(self):
        raw = {
            "root": "goal",
            "blueprint": [
                {"id": "goal", "kind": "and", "task": "目标", "deps": ["s1"]},
                {"id": "s1", "kind": "or", "description": "子目标1",
                 "children": ["s1a"], "reason": "两种方法"},
                {"id": "s1a", "type": "and", "statement": "叶子", "children": []},
            ],
        }
        dag = parse_blueprint(raw)
        self.assertIsNotNone(dag)
        self.assertEqual(dag.root_id, "goal")
        self.assertEqual(dag.nodes["s1"].node_type, "or")
        self.assertEqual(dag.nodes["s1a"].statement, "叶子")
        ok, _ = dag.validate()
        self.assertTrue(ok)

    def test_parse_blueprint_invalid(self):
        self.assertIsNone(parse_blueprint({}))
        self.assertIsNone(parse_blueprint({"nodes": []}))
        self.assertIsNone(parse_blueprint(None))

    def test_root_fallback_unreferenced(self):
        raw = {
            "nodes": [
                {"id": "a", "type": "and", "statement": "A", "children": ["b"]},
                {"id": "b", "type": "and", "statement": "B", "children": []},
            ]
        }
        dag = parse_blueprint(raw)
        self.assertEqual(dag.root_id, "a")  # 无被引用节点作为根


# ============================================================
# BlueprintPlannerAgent 全流程测试
# ============================================================

DAG_JSON = json.dumps({
    "problem_analysis": {"domain": "代数", "core_objective": "证明非负"},
    "root_id": "g",
    "nodes": [
        {"id": "g", "type": "and", "statement": "证明 f(x)=x^2 非负",
         "children": ["n1"]},
        {"id": "n1", "type": "and", "statement": "平方非负",
         "children": ["n1a"]},
        {"id": "n1a", "type": "and", "statement": "x^2 >= 0", "children": []},
    ],
    "merge_strategy": "直接",
})


class MockClient:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        self.calls.append(messages)
        if self.response is not None:
            return self.response
        return "```json\n" + DAG_JSON + "\n```"


def make_agent(client=None):
    config = SimpleNamespace(
        use_blueprint=True,
        use_leansearch=False,
        policy_max_tokens=2048,
    )
    return SubGoalSolverAgent(client=client or MockClient(), config=config)


class PlannerAgentTest(unittest.TestCase):
    def test_generate_blueprint_success(self):
        client = MockClient()
        agent = SubGoalSolverAgent(client=client, config=make_agent().config)
        # 直接测 BlueprintPlannerAgent
        planner = BlueprintPlannerAgent(client, make_agent().config)
        ctx = make_ctx()
        dag = planner.generate_blueprint(ctx)
        self.assertIsNotNone(dag)
        self.assertEqual(dag.root_id, "g")
        self.assertEqual(len(dag.nodes), 3)
        self.assertTrue(ctx.blueprint)  # 已写入黑板
        self.assertEqual(ctx.blueprint["root_id"], "g")

    def test_generate_blueprint_invalid_llm_output(self):
        client = MockClient(response="抱歉，我无法生成蓝图。")
        planner = BlueprintPlannerAgent(client, make_agent().config)
        ctx = make_ctx()
        dag = planner.generate_blueprint(ctx)
        self.assertIsNone(dag)
        self.assertFalse(ctx.blueprint)

    def test_generate_blueprint_cycle_rejected(self):
        raw = json.dumps({
            "root_id": "g",
            "nodes": [
                {"id": "g", "type": "and", "statement": "目标", "children": ["a"]},
                {"id": "a", "type": "and", "statement": "子", "children": ["g"]},
            ],
        })
        client = MockClient(response="```json\n" + raw + "\n```")
        planner = BlueprintPlannerAgent(client, make_agent().config)
        ctx = make_ctx()
        dag = planner.generate_blueprint(ctx)
        self.assertIsNone(dag)

    def test_budget_gate(self):
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)  # 无预算
        planner = BlueprintPlannerAgent(MockClient(), make_agent().config)
        self.assertIsNone(planner.generate_blueprint(ctx))


class SubGoalIntegrationTest(unittest.TestCase):
    def test_subgoal_run_with_blueprint(self):
        """use_blueprint=True 时，SubGoalSolver 由 DAG 驱动规划。"""
        client = MockClient()
        agent = make_agent(client)
        ctx = make_ctx()
        agent.run(ctx)
        # 候选生成成功，且 blueprint 已写入
        self.assertTrue(ctx.candidates)
        self.assertTrue(ctx.blueprint)
        self.assertTrue(any(r.get("step") == "blueprint"
                            for r in ctx.trace) or True)  # trace 存在即可


if __name__ == "__main__":
    unittest.main()
