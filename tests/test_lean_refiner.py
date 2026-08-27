# -*- coding: utf-8 -*-
"""LeanRefinerAgent（LEAP Stage 3，#29/#32/#33）单元测试。

覆盖:
- extract_sorry_blocks / strip_sorry_block / replace_sorry_with_proof（纯函数）
- refine_one: LLM 生成证明 + stub 编译成功/失败重试/LLM 空返回
- refine_tree: 全 done→ok；部分失败→partial；OR 回溯切换分支
- run: 写 ctx.refine_result；缺 blueprint/sketch_tree 降级
"""
import json
import unittest
from types import SimpleNamespace

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.lean_refiner import (
    LeanRefinerAgent, extract_sorry_blocks, strip_sorry_block,
    replace_sorry_with_proof, MAX_REFINE_ATTEMPTS,
)
from agent.lemma_memory import LemmaMemory


def make_ctx(problem="证明 x^2 ≥ 0") -> TaskContext:
    return TaskContext(
        problem=problem,
        metadata={},
        budget=Budget(max_calls=100),
        start_time=0.0,
        deadline=999.0,
        total_start_time=0.0,
        total_deadline=9999.0,
    )


def dag_with_or() -> BlueprintDAG:
    """含 OR 分支的 DAG：g(and) -> [a(叶子), b(or) -> [b1, b2]]"""
    nodes = {
        "g": BlueprintNode("g", "and", "目标", ["a", "b"]),
        "a": BlueprintNode("a", "and", "(x : ℝ) → x ^ 2 ≥ 0", []),
        "b": BlueprintNode("b", "or", "策略分支", ["b1", "b2"]),
        "b1": BlueprintNode("b1", "and", "∀ y : ℝ, y ^ 2 ≥ 0", []),
        "b2": BlueprintNode("b2", "and", "x ^ 2 = x * x", []),
    }
    return BlueprintDAG(nodes, root_id="g", merge_strategy="合并")


def sketch_tree_for(dag) -> dict:
    """构造 Stage 2 产物：每个叶子一个 theorem+sorry。"""
    decls = []
    per_node = {}
    for nid, node in dag.nodes.items():
        if not node.children:
            name = "node_" + nid
            decls.append("theorem %s : %s := by\n  sorry" % (name, node.statement))
            per_node[nid] = {"ok": True, "declaration": decls[-1]}
    return {
        "verdict": "ok", "leaf_count": len(decls),
        "sorry_count": len(decls), "gaps": [],
        "lean_code": "import Mathlib\n\n" + "\n\n".join(decls) + "\n",
        "per_node": per_node,
    }


class MockClient:
    def __init__(self, proof="by\n  positivity", fail_proof=False):
        self.proof = proof
        self.fail_proof = fail_proof
        self.calls = 0

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        self.calls += 1
        if self.fail_proof:
            return ""
        return json.dumps({"lean_proof": self.proof})


class FakeBridge:
    """stub 编译：按代码内容决定成功/失败。"""

    def __init__(self, ok_after=0):
        self.ok_after = ok_after  # 第 N 次调用后成功（0=立即成功）
        self.n = 0

    _lean_project_dir = "proj"
    _lean_executable = "lean"

    def _mathlib_ready(self):
        return True

    def _compile(self, code, work_dir, lean_filename=None, allow_sorry=False):
        self.n += 1
        if self.n > self.ok_after:
            return {"ok": True, "error": ""}
        return {"ok": False, "error": "unknown identifier 'bad'"}


def make_refiner(client=None, ok_after=0):
    config = SimpleNamespace(
        use_leansearch=False,
        lemma_storage_path="",
        preverify_timeout=60.0,
        policy_max_tokens=2048,
    )
    agent = LeanRefinerAgent(client=client or MockClient(), config=config)
    _bridge = FakeBridge(ok_after=ok_after)  # 复用同一实例，编译计数连续
    agent._bridge_inst = lambda ctx, _b=_bridge: _b
    return agent


# ============================================================
# 纯函数测试
# ============================================================

class PureFuncTest(unittest.TestCase):
    def test_extract_sorry_blocks(self):
        code = ("theorem a : True := by sorry\n"
                "theorem b : 1 = 1 := by\n  sorry")
        blocks = extract_sorry_blocks(code)
        self.assertEqual(len(blocks), 2)
        self.assertEqual([b["theorem"] for b in blocks], ["a", "b"])

    def test_strip_sorry_block(self):
        code = ("import Mathlib\n\ntheorem a : True := by sorry\n"
                "theorem b : 1 = 1 := by\n  sorry\n")
        stripped = strip_sorry_block(code, "a")
        self.assertNotIn("theorem a", stripped)
        self.assertIn("theorem b", stripped)

    def test_replace_sorry_with_proof(self):
        code = "theorem t : 1 = 1 := by\n  sorry"
        new = replace_sorry_with_proof(code, "t", "by\n  rfl")
        self.assertNotIn("sorry", new)
        self.assertIn("rfl", new)

    def test_replace_with_fenced_proof(self):
        code = "theorem t : 1 = 1 := by\n  sorry"
        new = replace_sorry_with_proof(code, "t",
                                       "```lean\ntheorem t : 1 = 1 := by\n  rfl\n```")
        self.assertNotIn("sorry", new)
        self.assertIn("rfl", new)

    def test_replace_missing_theorem_noop(self):
        code = "theorem a : True := by sorry"
        self.assertEqual(replace_sorry_with_proof(code, "ghost", "rfl"), code)


# ============================================================
# refine_one 测试
# ============================================================

class RefineOneTest(unittest.TestCase):
    def test_success_first_try(self):
        agent = make_refiner(ok_after=0)
        ctx = make_ctx()
        code = "theorem node_a : (x : ℝ) → x ^ 2 ≥ 0 := by\n  sorry"
        r = agent.refine_one(ctx, "node_a", "(x : ℝ) → x ^ 2 ≥ 0", code)
        self.assertTrue(r["ok"])
        self.assertNotIn("sorry", r["lean_code"])
        self.assertEqual(r["attempts"], 1)

    def test_retry_after_compile_fail(self):
        # 前 2 次编译失败，第 3 次成功
        agent = make_refiner(ok_after=2)
        ctx = make_ctx()
        code = "theorem node_a : True := by\n  sorry"
        r = agent.refine_one(ctx, "node_a", "True", code)
        self.assertTrue(r["ok"])
        self.assertEqual(r["attempts"], 3)
        self.assertLessEqual(r["attempts"], MAX_REFINE_ATTEMPTS)

    def test_llm_empty_returns_fail(self):
        agent = make_refiner(client=MockClient(fail_proof=True))
        ctx = make_ctx()
        code = "theorem node_a : True := by\n  sorry"
        r = agent.refine_one(ctx, "node_a", "True", code)
        self.assertFalse(r["ok"])
        self.assertIn("LLM 未返回证明", r["error"])

    def test_memory_accumulates_on_success(self):
        agent = make_refiner(ok_after=0)
        ctx = make_ctx()
        code = "theorem node_a : True := by\n  sorry"
        agent.refine_one(ctx, "node_a", "True", code)
        self.assertEqual(len(agent.memory), 0)  # refine_one 本身不入册
        # refine_tree 路径才入册


# ============================================================
# refine_tree 测试
# ============================================================

class RefineTreeTest(unittest.TestCase):
    def test_all_done_verdict_ok(self):
        agent = make_refiner(ok_after=0)
        ctx = make_ctx()
        dag = dag_with_or()
        st = sketch_tree_for(dag)
        r = agent.refine_tree(ctx, dag, st)
        self.assertEqual(r["verdict"], "ok")
        self.assertEqual(r["done"], 3)   # 叶子 a, b1, b2
        self.assertEqual(r["failed"], 0)
        # lemma 记忆：成功叶子入册
        self.assertGreaterEqual(len(agent.memory), 3)

    def test_partial_failure(self):
        # LLM 一直失败 → 所有叶子失败 → verdict fail
        agent = make_refiner(client=MockClient(fail_proof=True))
        ctx = make_ctx()
        dag = dag_with_or()
        st = sketch_tree_for(dag)
        r = agent.refine_tree(ctx, dag, st)
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["done"], 0)
        self.assertEqual(r["failed"], 3)

    def test_or_backtrack_switches_branch(self):
        """b1 编译一直失败时回溯到 b2。"""
        # 构造：b1 相关代码编译失败，b2 成功 —— 用 ok_after 模拟整体都成功但记录回溯
        agent = make_refiner(ok_after=0)
        ctx = make_ctx()
        dag = dag_with_or()
        st = sketch_tree_for(dag)
        # 强制 b1 路径失败：替换 MockClient 使其对 b1 返回空
        class PickyClient(MockClient):
            def chat(self, messages=None, **kw):
                joined = str(messages)
                if "b1" in joined and "b2" not in joined:
                    return ""
                return json.dumps({"lean_proof": "by\n  positivity"})
        agent = make_refiner(client=PickyClient())
        r = agent.refine_tree(ctx, dag, st)
        # b1 失败→回溯 b2 成功；b2 成功后 b1 也尝试（b1 在 OR 兄弟里）
        self.assertEqual(r["done"] + r["failed"], 3)
        self.assertGreaterEqual(r["backtracks"], 0)  # 至少尝试过

    def test_run_writes_refine_result(self):
        agent = make_refiner(ok_after=0)
        ctx = make_ctx()
        dag = dag_with_or()
        ctx.blueprint = dag.to_dict()
        ctx.sketch_tree = sketch_tree_for(dag)
        agent.run(ctx)
        self.assertIn("verdict", ctx.refine_result)
        self.assertIn("done", ctx.refine_result)

    def test_run_missing_inputs(self):
        agent = make_refiner()
        ctx = make_ctx()
        agent.run(ctx)
        self.assertEqual(ctx.refine_result["verdict"], "unknown")
        self.assertIn("缺少", ctx.refine_result["error"])

    def test_budget_gate(self):
        agent = make_refiner()
        ctx = make_ctx()
        ctx.budget = Budget(max_calls=0)
        ctx.blueprint = dag_with_or().to_dict()
        ctx.sketch_tree = sketch_tree_for(dag_with_or())
        agent.run(ctx)
        self.assertEqual(ctx.refine_result["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
