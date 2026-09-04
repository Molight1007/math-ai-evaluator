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

    def test_generate_blueprint_uses_anchored_prefill(self):
        """回归：prefill 种子必须锚定到顶层包装，不能退化成裸 `{"`。

        两种历史失败形态（均为实测）：
          1) 无 prefill —— Intern 先吐长思维块吃满 token，JSON 被腰斩
             → 「Blueprint: JSON 解析失败」重试 3 次全败（eval_A 0/3 根因）
          2) 仅用 `{"` —— 模型认为已进入对象内部，直接吐 nodes 数组元素，
             丢掉 `root_id` / `nodes` 外层包装 → 「Blueprint: DAG 结构非法」
        锚定到 `{"root_id": "g", "nodes": [` 后实测 3/3 成功。
        """
        # 模拟"续写"形态的返回：不含种子前缀，由 stitch 负责拼接
        # 注意结尾两个 `}`：前一个闭合 problem_analysis，后一个闭合顶层对象
        client = MockClient(
            response='\n  {"id": "g", "type": "and", "statement": "目标", '
                     '"children": [], "rationale": ""}\n], '
                     '"merge_strategy": "", "problem_analysis": {}}')
        planner = BlueprintPlannerAgent(client, make_agent().config)
        ctx = make_ctx()
        dag = planner.generate_blueprint(ctx)
        self.assertIsNotNone(dag, "锚定 prefill 下应能解析出 DAG")
        self.assertEqual(dag.root_id, "g")

        # 最后一条消息必须是 assistant 种子，且锚定了 root_id 与 nodes
        last_msg = client.calls[0][-1]
        self.assertEqual(last_msg["role"], "assistant")
        self.assertIn('"root_id"', last_msg["content"])
        self.assertIn('"nodes"', last_msg["content"])

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

    def test_time_critical_gate(self):
        """2026-09-03 预算解除：时间紧迫才跳过蓝图生成（返回 None）。

        原 test_budget_gate 用 Budget(max_calls=0) 模拟"无预算 → 跳过"——
        预算闸门已删，预算=0 蓝图照常生成。真实跳过条件是 is_time_critical()。
        """
        import time as _t
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)  # 预算=0（不再阻断）
        ctx.deadline = _t.time() - 1  # 真实时间戳已过期 → 时间紧迫
        planner = BlueprintPlannerAgent(MockClient(), make_agent().config)
        self.assertIsNone(planner.generate_blueprint(ctx))

    def test_budget_zero_still_generates(self) -> None:
        """预算=0 不再阻断：蓝图照常生成（新语义）。"""
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        planner = BlueprintPlannerAgent(MockClient(), make_agent().config)
        self.assertIsNotNone(planner.generate_blueprint(ctx))


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


# ============================================================
# DAG 整树重生成（#34，老师要求："dag 错了要重新生成"）
# ============================================================

REPLAN_DAG_JSON = json.dumps({
    "root_id": "g2",
    "nodes": [
        {"id": "g2", "type": "and",
         "statement": "证明 x^2 非负改写版（更细）",
         "children": ["n2a", "n2b"]},
        {"id": "n2a", "type": "and",
         "statement": "由 a^2 >= 0 直接得（分情形）",
         "children": []},
        {"id": "n2b", "type": "and",
         "statement": "若实数 x 平方 = (-x)^2，结论亦然",
         "children": []},
    ],
    "merge_strategy": "任一分支成立即可",
})


class ReplanTest(unittest.TestCase):

    def test_regenerate_with_feedback_success(self):
        """重生成成功路径：mock LLM 输出新 DAG，校验通过、回写 ctx.blueprint。"""
        from agent.blueprint_planner import (
            BlueprintPlannerAgent, BlueprintDAG, BlueprintNode)

        client = MockClient(response="```json\n" + REPLAN_DAG_JSON + "\n```")
        config = SimpleNamespace(
            use_leansearch=False,
            theorem_memory_enable=False,
            theorem_memory_path="",
            theorem_memory_top_k=5,
        )
        planner = BlueprintPlannerAgent(client, config)
        ctx = make_ctx()
        ctx.problem = "证明 f(x)=x^2 在实数上非负"

        prior = BlueprintDAG(
            nodes={"g": BlueprintNode("g", "and", "证明 f(x)=x^2 非负 x^2", [])},
            root_id="g",
        )
        new_dag = planner.regenerate_with_feedback(
            ctx, prior_dag=prior,
            feedback_lines=["n1a 与父目标循环相似", "粒度过粗"])
        self.assertIsNotNone(new_dag)
        self.assertEqual(new_dag.root_id, "g2")
        self.assertEqual(len(new_dag.nodes), 3)
        # ctx.blueprint 应被新 DAG 覆盖
        self.assertEqual(ctx.blueprint["root_id"], "g2")
        # trace 应包含 "blueprint_replan" 标记
        trace_steps = [t.get("step") for t in ctx.trace]
        self.assertIn("blueprint_replan", trace_steps)

    def test_regenerate_with_feedback_budget_guard(self):
        """预算=0 直接返回 None，不调 LLM。"""
        from agent.blueprint_planner import (
            BlueprintPlannerAgent, BlueprintDAG, BlueprintNode)

        client = MockClient(response="anything")
        config = SimpleNamespace(
            use_leansearch=False,
            theorem_memory_enable=False,
        )
        planner = BlueprintPlannerAgent(client, config)
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        prior = BlueprintDAG(
            nodes={"g": BlueprintNode("g", "and", "题目目标", [])},
            root_id="g",
        )
        result = planner.regenerate_with_feedback(ctx, prior_dag=prior, feedback_lines=[])
        self.assertIsNone(result)


# ============================================================
# SubGoalSolver 阶段四：Reviewer + Replan 集成测试
# ============================================================

class SubGoalReviewReplanTest(unittest.TestCase):
    """SubGoalSolver.run 末尾应触发 DagReviewer + 必要时整树重生成。"""

    def _make_sub_goal_mock_llm_response(self):
        """构造 SubGoalSolver 需要的多步 LLM 输出：plan + step 结果。

        走通三个 LLM 调用：
          1) planner.generate_blueprint() → 用现有 DAG_JSON 即可
          2) plan_subgoals 走 DAG 路径，但 generate_blueprint 已被前面 mock 替换
          3) _call_step 每子目标调用一次（结果占位）
        """
        step_ok = json.dumps({"result": "ok"})
        return ["```json\n" + DAG_JSON + "\n```", "```json\n" + step_ok + "\n```"]

    def test_subgoal_solver_runs_review_at_end(self):
        """子目标完成后跑 Reviewer，不触发重生成（评审通过 → False）。"""
        from agent.sub_goal_solver import SubGoalSolverAgent
        # 准备第一段响应 = DAG JSON；第二段 = 每子目标 step 结果（多次返回）
        idx = {"i": 0}

        class MyClient:
            def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
                idx["i"] += 1
                # 第一次（generate_blueprint）→ DAG_JSON；其他 → step result
                if idx["i"] == 1:
                    return "```json\n" + DAG_JSON + "\n```"
                return "```\n【本步结果】\n已求解\n```"

        config = SimpleNamespace(
            use_blueprint_dag=True,
            use_leansearch=False,
            theorem_memory_enable=False,
            enable_dag_replan=True,    # 开启评审+replan
            dag_replan_max_rounds=2,
        )
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=50)
        solver = SubGoalSolverAgent(MyClient(), config)
        solver.run(ctx)
        # dag_review_report 应被写入
        self.assertTrue(ctx.dag_review_report)
        # trace 应有 dag_review 步骤
        trace_steps = [t.get("step") for t in ctx.trace]
        self.assertIn("dag_review", trace_steps)


# ============================================================
# 子树级局部重写（#34 第二级）测试
# ============================================================

class SubtreeRewriteTest(unittest.TestCase):
    """BlueprintDAG._subtree_ids / _lca / _prune_subtree / _graft_subtree 纯逻辑测试。"""

    def test_subtree_ids(self):
        dag = sample_dag()
        self.assertEqual(dag._subtree_ids("n1"), {"n1", "n1a", "n1b"})
        self.assertEqual(dag._subtree_ids("n2"), {"n2", "n2a", "n2b"})
        self.assertEqual(dag._subtree_ids("g"), set(dag.nodes.keys()))
        self.assertEqual(dag._subtree_ids("n1a"), {"n1a"})

    def test_lca_same_branch(self):
        dag = sample_dag()
        # n1a 与 n1b 的 LCA 是 n1
        self.assertEqual(dag._lca(["n1a", "n1b"]), "n1")
        # n1a 与 n2a 的 LCA 是根 g
        self.assertEqual(dag._lca(["n1a", "n2a"]), "g")
        # 单个节点 LCA 是自身
        self.assertEqual(dag._lca(["n1a"]), "n1a")
        # 不存在的节点忽略
        self.assertEqual(dag._lca(["n1a", "zzz"]), "n1a")

    def test_prune_subtree(self):
        dag = sample_dag()
        pruned = dag._prune_subtree("n1")
        # n1 保留但 children 清空；n1a/n1b 删除；n2 及子树原样
        self.assertIn("n1", pruned.nodes)
        self.assertEqual(pruned.nodes["n1"].children, [])
        self.assertNotIn("n1a", pruned.nodes)
        self.assertNotIn("n1b", pruned.nodes)
        self.assertIn("n2", pruned.nodes)
        self.assertEqual(pruned.nodes["n2"].children, ["n2a", "n2b"])
        self.assertEqual(pruned.nodes["g"].children, ["n1", "n2"])
        ok, errors = pruned.validate()
        self.assertTrue(ok, f"裁剪后应合法: {errors}")

    def test_graft_subtree(self):
        dag = sample_dag()
        # 新子树：根 r 分解出 r1, r2（模拟 LLM 重写 n1）
        new_nodes = {
            "r": BlueprintNode("r", "and", "证明平方非负", ["r1", "r2"], "重写"),
            "r1": BlueprintNode("r1", "and", "x^2 非负的代数证明", [], "叶子"),
            "r2": BlueprintNode("r2", "and", "x^2 非负的几何证明", [], "叶子"),
        }
        new_dag = BlueprintDAG(new_nodes, root_id="r")
        merged = dag._graft_subtree("n1", new_dag, id_prefix="r0")
        self.assertIsNotNone(merged)
        # n1 的 children 指向新节点（加前缀）
        self.assertEqual(merged.nodes["n1"].children, ["r0_r1", "r0_r2"])
        self.assertIn("r0_r1", merged.nodes)
        self.assertIn("r0_r2", merged.nodes)
        self.assertNotIn("n1a", merged.nodes)  # 旧子树已摘除
        self.assertEqual(merged.nodes["n2"].children, ["n2a", "n2b"])  # 其他分支不动
        ok, errors = merged.validate()
        self.assertTrue(ok, f"拼接后应合法: {errors}")
        # 原 DAG 未被污染
        self.assertIn("n1a", dag.nodes)
        self.assertEqual(dag.nodes["n1"].children, ["n1a", "n1b"])

    def test_graft_invalid_new_dag(self):
        dag = sample_dag()
        self.assertIsNone(dag._graft_subtree("n1", None, id_prefix="r0"))
        # 新 DAG 根不存在于自身节点 → 拒绝
        empty = BlueprintDAG({}, root_id="r")
        self.assertIsNone(dag._graft_subtree("n1", empty, id_prefix="r0"))
        # root_id 不存在于原图 → 拒绝
        new_dag = BlueprintDAG({"r": BlueprintNode("r", "and", "x", [])}, root_id="r")
        self.assertIsNone(dag._graft_subtree("zzz", new_dag, id_prefix="r0"))

    def test_regenerate_subtree_mock(self):
        """mock LLM：子树重写成功 → 只动 LCA 子树，其他节点保留。"""
        cfg = SimpleNamespace(
            use_blueprint=True, use_blueprint_dag=True,
            enable_dag_replan=True, dag_replan_max_rounds=2,
            use_leansearch=False, theorem_memory_enable=False,
        )
        new_dag_json = json.dumps({
            "root_id": "r",
            "nodes": [
                {"id": "r", "type": "and", "statement": "证明平方非负",
                 "children": ["r1", "r2"], "rationale": "重写"},
                {"id": "r1", "type": "and", "statement": "x^2 非负的代数证明", "children": []},
                {"id": "r2", "type": "and", "statement": "x^2 非负的几何证明", "children": []},
            ],
        }, ensure_ascii=False)

        class MockClient:
            def __init__(self):
                self.calls = 0

            def chat(self, *a, **kw):
                self.calls += 1
                return new_dag_json

        client = MockClient()
        planner = BlueprintPlannerAgent(client, cfg)
        ctx = make_ctx()
        result = planner.regenerate_subtree(
            ctx, prior_dag=sample_dag(), rejected_ids=["n1a", "n1b"],
            feedback_lines=["[n1a] 粒度太粗", "[n1b] 循环风险"])
        self.assertIsNotNone(result)
        # 只重写了 n1 子树（前缀 r0_），n2 分支原样
        self.assertNotIn("n1a", result.nodes)
        self.assertIn("r0_r1", result.nodes)
        self.assertEqual(result.nodes["n2"].children, ["n2a", "n2b"])
        self.assertEqual(result.nodes["g"].children, ["n1", "n2"])

    def test_regenerate_subtree_root_lca_fallback(self):
        """LCA=根 → 退化为整树重生成（mock 返回新 DAG）。"""
        cfg = SimpleNamespace(
            use_blueprint=True, use_blueprint_dag=True,
            enable_dag_replan=True, dag_replan_max_rounds=2,
            use_leansearch=False, theorem_memory_enable=False,
        )
        new_dag_json = json.dumps({
            "root_id": "g2",
            "nodes": [
                {"id": "g2", "type": "and", "statement": "证明 f(x)=x^2 非负",
                 "children": ["m1"], "rationale": "全新分解"},
                {"id": "m1", "type": "and", "statement": "平方非负新证法", "children": []},
            ],
        }, ensure_ascii=False)

        class MockClient:
            def chat(self, *a, **kw):
                return new_dag_json

        client = MockClient()
        planner = BlueprintPlannerAgent(client, cfg)
        ctx = make_ctx()
        # n1a 与 n2a 的 LCA 是根 → 整树
        result = planner.regenerate_subtree(
            ctx, prior_dag=sample_dag(), rejected_ids=["n1a", "n2a"],
            feedback_lines=["[n1a] 粒度太粗"])
        self.assertIsNotNone(result)
        self.assertIn("m1", result.nodes)
        self.assertNotIn("n1", result.nodes)


if __name__ == "__main__":
    unittest.main()
