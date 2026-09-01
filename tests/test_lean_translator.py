# -*- coding: utf-8 -*-
"""LeanTranslatorAgent（LEAP Stage 2，#26/#28）单元测试。

覆盖:
- build_declaration: Lean 陈述直包 / 非 Lean 返回 None / 去证明体 / 去 theorem 前缀
- sanitize_node_id / count_sorries / extract_declaration_names
- translate_node: 直包优先；LLM 兜底（JSON 解析）；失败返回 None
- translate_and_audit: stub _compile 成功→ok；失败→fail+gaps；全翻译失败→unknown
- run: 从 ctx.blueprint 整树搭桥，写 ctx.sketch_tree
- SubGoalSolver 集成: use_blueprint=True 时蓝图+整树审核不阻断主流程
"""
import json
import unittest
from types import SimpleNamespace

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.lean_translator import (
    LeanTranslatorAgent, build_declaration, sanitize_node_id,
    count_sorries, extract_declaration_names, _strip_fence,
)
from agent.sub_goal_solver import SubGoalSolverAgent


def make_ctx(problem="证明 f(x)=x^2 非负") -> TaskContext:
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
    nodes = {
        "g": BlueprintNode("g", "and", "证明 f(x)=x^2 非负", ["n1", "n2"], "主分解"),
        "n1": BlueprintNode("n1", "and", "证明平方非负", ["n1a"], "AND"),
        "n1a": BlueprintNode("n1a", "and",
                             "theorem : (x : ℝ) → x ^ 2 ≥ 0", [], "Lean 叶子"),
        "n2": BlueprintNode("n2", "or", "策略分支", ["n2a", "n2b"], "OR"),
        "n2a": BlueprintNode("n2a", "and", "∀ y : ℝ, y ^ 2 ≥ 0", [], "Lean 叶子"),
        "n2b": BlueprintNode("n2b", "and", "x^2 >= 0 另一种策略", [], "自然语言叶子"),
    }
    return BlueprintDAG(nodes, root_id="g", merge_strategy="合并")


class MockClient:
    """按阶段返回响应的 mock：蓝图阶段返回 DAG JSON，翻译阶段返回 Lean 声明 JSON。"""

    def __init__(self, response=None, fail_all=False):
        self.response = response
        self.fail_all = fail_all
        self.calls = []

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        self.calls.append(messages)
        if self.fail_all:
            return "抱歉，无法处理。"
        if self.response is not None:
            return self.response
        system = (messages or [{}])[0].get("content", "") if messages else ""
        if "lean_declaration" in system:
            # 翻译阶段：返回 Lean 声明 JSON
            return json.dumps({
                "lean_declaration": "theorem node_x (x : ℝ) : x ^ 2 ≥ 0 := by\n  sorry",
                "formal_statement": "∀ x : ℝ, x ^ 2 ≥ 0",
            })
        if '"root_id"' in system or "AND-OR 有向无环图" in system:
            # 蓝图阶段：返回 DAG JSON
            return "```json\n" + json.dumps({
                "root_id": "g",
                "nodes": [
                    {"id": "g", "type": "and", "statement": "证明 f(x)=x^2 非负",
                     "children": ["n1"]},
                    {"id": "n1", "type": "and", "statement": "平方非负",
                     "children": ["n1a"]},
                    {"id": "n1a", "type": "and",
                     "statement": "证明 x 的平方非负", "children": []},
                ],
                "merge_strategy": "直接",
            }) + "\n```"
        return json.dumps({
            "lean_declaration": "theorem node_x (x : ℝ) : x ^ 2 ≥ 0 := by\n  sorry",
            "formal_statement": "∀ x : ℝ, x ^ 2 ≥ 0",
        })


def make_agent(client=None):
    config = SimpleNamespace(
        use_blueprint=True,
        enable_sketch_audit=True,
        use_leansearch=False,
        preverify_timeout=60.0,
        policy_max_tokens=2048,
    )
    return SubGoalSolverAgent(client=client or MockClient(), config=config)


# ============================================================
# 纯函数测试
# ============================================================

class BuildDeclarationTest(unittest.TestCase):
    def test_lean_statement_wrapped(self):
        decl = build_declaration("n1a", "(x : ℝ) → x ^ 2 ≥ 0")
        self.assertIsNotNone(decl)
        self.assertTrue(decl.startswith("theorem node_n1a :"))
        self.assertIn("by\n  sorry", decl)

    def test_full_theorem_prefix_stripped(self):
        decl = build_declaration("t1", "theorem my_thm (x : ℝ) : x ≥ 0")
        self.assertIsNotNone(decl)
        self.assertTrue(decl.startswith("theorem node_t1 :"))
        self.assertIn("(x : ℝ) : x ≥ 0", decl)

    def test_proof_body_stripped(self):
        decl = build_declaration("t2", "x ^ 2 ≥ 0 := by\n  exact sq_nonneg x")
        self.assertIsNotNone(decl)
        self.assertNotIn("exact", decl)
        self.assertTrue(decl.endswith("by\n  sorry"))

    def test_natural_language_returns_none(self):
        self.assertIsNone(build_declaration("n2b", "证明平方非负"))
        self.assertIsNone(build_declaration("e", ""))
        self.assertIsNone(build_declaration("e", "   "))

    def test_sanitize_node_id(self):
        self.assertEqual(sanitize_node_id("n1a"), "node_n1a")
        self.assertEqual(sanitize_node_id("12"), "node_n12")
        self.assertEqual(sanitize_node_id(""), "node_x")
        self.assertTrue(sanitize_node_id("a-b c").startswith("node_"))

    def test_count_and_names(self):
        code = ("theorem a : True := by sorry\n"
                "theorem b : 1 = 1 := by\n  sorry")
        self.assertEqual(count_sorries(code), 2)
        self.assertEqual(extract_declaration_names(code), ["a", "b"])

    def test_strip_fence(self):
        self.assertEqual(_strip_fence("```lean\ntheorem a : True := by sorry\n```"),
                         "theorem a : True := by sorry")


# ============================================================
# translate_node 测试
# ============================================================

class TranslateNodeTest(unittest.TestCase):
    def test_direct_wrap_preferred(self):
        agent = LeanTranslatorAgent(MockClient(fail_all=True), make_agent().config)
        ctx = make_ctx()
        decl = agent.translate_node(ctx, "n1a", "(x : ℝ) → x ^ 2 ≥ 0")
        self.assertIsNotNone(decl)  # 直包，不触发 LLM
        self.assertEqual(agent._llm_call_count if hasattr(agent, "_llm_call_count") else 0, 0)

    def test_llm_translation_fallback(self):
        agent = LeanTranslatorAgent(MockClient(), make_agent().config)
        ctx = make_ctx()
        decl = agent.translate_node(ctx, "n2b", "证明 x 的平方非负")
        self.assertIsNotNone(decl)
        self.assertIn("sorry", decl)

    def test_llm_failure_returns_none(self):
        agent = LeanTranslatorAgent(MockClient(fail_all=True), make_agent().config)
        ctx = make_ctx()
        decl = agent.translate_node(ctx, "n2b", "证明 x 的平方非负")
        self.assertIsNone(decl)


# ============================================================
# translate_and_audit 测试
# ============================================================

class TranslateAndAuditTest(unittest.TestCase):
    def _stub_bridge(self, agent, ok=True):
        """用假 bridge 替换 _bridge_inst，stub _compile 返回结果。"""
        class FakeBridge:
            _lean_project_dir = "proj"
            _mathlib_ready_cache = True
            _lean_executable = "lean"

            def _mathlib_ready(self):
                return True

            def _compile(self, code, work_dir, lean_filename=None, allow_sorry=False):
                if ok:
                    return {"ok": True, "error": ""}
                return {"ok": False, "error": "type mismatch at line 3: ℝ"}

        agent._bridge_inst = lambda ctx: FakeBridge()

    def test_success_verdict_ok(self):
        agent = LeanTranslatorAgent(MockClient(), make_agent().config)
        self._stub_bridge(agent, ok=True)
        ctx = make_ctx()
        result = agent.translate_and_audit(ctx, sample_dag())
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["leaf_count"], 3)
        self.assertEqual(result["sorry_count"], 3)  # 每叶子一个 sorry
        self.assertIn("import Mathlib", result["lean_code"])  # 兼容 core 闭包（具体模块导入）

    def test_compile_fail_verdict_fail(self):
        agent = LeanTranslatorAgent(MockClient(), make_agent().config)
        self._stub_bridge(agent, ok=False)
        ctx = make_ctx()
        result = agent.translate_and_audit(ctx, sample_dag())
        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(result["gaps"])  # 抽取到缺口
        self.assertIn("per_node", result)

    def test_all_translation_failed(self):
        # 叶子含自然语言，LLM 全失败 → 无声明 → unknown
        agent = LeanTranslatorAgent(MockClient(fail_all=True), make_agent().config)
        ctx = make_ctx()
        nodes = {
            "g": BlueprintNode("g", "and", "目标", ["a"]),
            "a": BlueprintNode("a", "and", "纯自然语言子目标", []),
        }
        result = agent.translate_and_audit(ctx, BlueprintDAG(nodes, root_id="g"))
        self.assertEqual(result["verdict"], "unknown")
        self.assertIn("翻译失败", result["error"])

    def test_run_writes_sketch_tree(self):
        agent = LeanTranslatorAgent(MockClient(), make_agent().config)
        self._stub_bridge(agent, ok=True)
        ctx = make_ctx()
        ctx.blueprint = sample_dag().to_dict()
        agent.run(ctx)
        self.assertEqual(ctx.sketch_tree["verdict"], "ok")

    def test_run_without_blueprint(self):
        agent = LeanTranslatorAgent(MockClient(), make_agent().config)
        ctx = make_ctx()
        agent.run(ctx)
        self.assertEqual(ctx.sketch_tree["verdict"], "unknown")
        self.assertIn("无 Blueprint DAG", ctx.sketch_tree["error"])


# ============================================================
# SubGoalSolver 集成测试
# ============================================================

class SubGoalIntegrationTest(unittest.TestCase):
    def test_blueprint_flow_with_tree_audit(self):
        """use_blueprint=True 时：DAG 规划 + 整树审核，候选仍生成。"""
        client = MockClient()
        agent = make_agent(client)
        # 让整树审核走 stub（避免真实 Lean 编译）
        from agent.lean_translator import LeanTranslatorAgent
        orig = LeanTranslatorAgent.translate_and_audit

        def fake_audit(self, ctx, dag):
            return {"verdict": "ok", "leaf_count": 2, "sorry_count": 2,
                    "gaps": [], "per_node": {}, "lean_code": ""}
        LeanTranslatorAgent.translate_and_audit = fake_audit
        try:
            ctx = make_ctx()
            agent.run(ctx)
            self.assertTrue(ctx.candidates)
            self.assertTrue(ctx.blueprint)
            self.assertTrue(ctx.sketch_tree)
        finally:
            LeanTranslatorAgent.translate_and_audit = orig


if __name__ == "__main__":
    unittest.main()
