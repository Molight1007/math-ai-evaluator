# -*- coding: utf-8 -*-
"""
前瞻引理规划（Anticipatory Lemma Planning）单元测试
====================================================

LEAP §2.3 / Figure 2 机制落地验证（2026-09-15，呼应 ima 论文分析报告缺口 A）。

**机制**：蓝图生成时允许提议"当前 sketch 不需要、但后续证明步骤可能用到"的
辅助引理；这些引理挂到 DAG 记忆里但**不阻塞当前 AND 节点的完成**。
论文消融（Table 6）：DAG vs 朴素树 +10.0pp(Basic)/+16.7pp(Advanced)。

**本项目的落地形态**：
- `BlueprintNode.node_role` ∈ {"required"(默认), "anticipatory"}
- `to_subgoal_plan()` 把 anticipatory 节点排除出求解链，
  收集进返回值的 `anticipatory_lemmas`
- `SubGoalSolver._inject_anticipatory_lemmas()` 把它们写入 `ctx.lemma_repo`，
  由现成的 `lemma_context` 注入通路供下游子目标引用
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.blueprint_planner import BlueprintDAG, BlueprintNode


def make_config(**over):
    base = dict(
        use_leaf_accumulation=True,
        use_lemma_accumulation=True,
        lemma_domains=[],           # 空 = 全领域放行
    )
    base.update(over)
    return SimpleNamespace(**base)


def make_ctx(domain="数论"):
    from agent.base import TaskContext, Budget
    ctx = TaskContext(
        problem="证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除",
        metadata={}, budget=Budget(max_calls=50),
        start_time=0.0, deadline=999.0,
        total_start_time=0.0, total_deadline=9999.0,
    )
    ctx.domain = domain
    return ctx


def make_solver():
    from agent.sub_goal_solver import SubGoalSolverAgent
    return SubGoalSolverAgent(MagicMock(), make_config())


# ============================================================
# 第 1 层 · 数据结构与序列化
# ============================================================

class TestNodeRoleField(unittest.TestCase):

    def test_default_is_required(self):
        """旧调用方式（不传 node_role）→ 默认 required，行为不变。"""
        n = BlueprintNode("a", "and", "证明某命题成立", [], "理由")
        self.assertEqual(n.node_role, "required")
        self.assertFalse(n.is_anticipatory)

    def test_anticipatory_flag(self):
        n = BlueprintNode("a", "and", "辅助引理", [], "", "anticipatory")
        self.assertTrue(n.is_anticipatory)

    def test_flag_is_case_insensitive(self):
        n = BlueprintNode("a", "and", "辅助引理", [], "", "Anticipatory")
        self.assertTrue(n.is_anticipatory)

    def test_none_role_is_safe(self):
        n = BlueprintNode("a", "and", "辅助引理")
        n.node_role = None
        self.assertFalse(n.is_anticipatory)

    def test_serialization_roundtrip(self):
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["n1"]),
            "n1": BlueprintNode("n1", "and", "证 A", []),
            "aux": BlueprintNode("aux", "and", "辅助引理", [], "", "anticipatory"),
        }, root_id="g")
        d = dag.to_dict()
        roles = {n["id"]: n["node_role"] for n in d["nodes"]}
        self.assertEqual(roles["aux"], "anticipatory")
        self.assertEqual(roles["n1"], "required")
        back = BlueprintDAG.from_dict(d)
        self.assertTrue(back.nodes["aux"].is_anticipatory)
        self.assertFalse(back.nodes["n1"].is_anticipatory)

    def test_legacy_serialization_without_role(self):
        """旧 DAG 序列化（无 node_role 键）→ 反序列化为 required，不崩。"""
        data = {
            "root_id": "g",
            "nodes": [
                {"id": "g", "type": "and", "statement": "证明 P",
                 "children": ["n1"], "rationale": ""},
                {"id": "n1", "type": "and", "statement": "证 A",
                 "children": [], "rationale": ""},
            ],
        }
        dag = BlueprintDAG.from_dict(data)
        self.assertEqual(dag.nodes["n1"].node_role, "required")

    def test_role_alias_key_accepted(self):
        """兼容 `role` 简写键（提示词里给模型写的是 "role"）。"""
        data = {
            "root_id": "g",
            "nodes": [
                {"id": "g", "type": "and", "statement": "证明 P",
                 "children": [], "role": "anticipatory"},
            ],
        }
        dag = BlueprintDAG.from_dict(data)
        self.assertTrue(dag.nodes["g"].is_anticipatory)


# ============================================================
# 第 2 层 · 求解链隔离（核心语义）
# ============================================================

class TestAnticipatoryExcludedFromSolveChain(unittest.TestCase):

    def _dag_with_aux(self):
        return BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P 成立", ["n1", "n2"]),
            "n1": BlueprintNode("n1", "and", "证明引理 A 成立", []),
            "n2": BlueprintNode("n2", "and", "证明引理 B 成立", []),
            "aux": BlueprintNode("aux", "and", "中间恒等式 (x-1)(x+1)=x^2-1",
                                 [], "后续化归用", "anticipatory"),
        }, root_id="g")

    def test_aux_not_in_subgoals(self):
        plan = self._dag_with_aux().to_subgoal_plan()
        descs = " ".join(s["description"] for s in plan["subgoals"])
        self.assertNotIn("(x-1)(x+1)", descs,
                         "前瞻引理不得进入子目标求解链")
        self.assertEqual(len(plan["subgoals"]), 2)

    def test_aux_collected(self):
        """★ 前瞻引理是旁挂的（不在 children 里），必须仍被收集。

        2026-09-15 实测踩到：若只从 root 做 DFS，旁挂节点永远发现不了，
        anticipatory_lemmas 恒为空。
        """
        plan = self._dag_with_aux().to_subgoal_plan()
        ids = [a["id"] for a in plan["anticipatory_lemmas"]]
        self.assertIn("aux", ids)
        stmts = " ".join(a["statement"] for a in plan["anticipatory_lemmas"])
        self.assertIn("(x-1)(x+1)", stmts)

    def test_aux_appearing_as_child_is_still_excluded(self):
        """即使模型把前瞻节点误挂进 children，也不得混入求解链。"""
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["n1", "aux"]),
            "n1": BlueprintNode("n1", "and", "证明引理 A 成立", []),
            "aux": BlueprintNode("aux", "and", "前瞻父节点陈述", ["c1"],
                                 "", "anticipatory"),
            "c1": BlueprintNode("c1", "and", "aux 的子节点陈述", []),
        }, root_id="g")
        plan = dag.to_subgoal_plan()
        self.assertEqual(len(plan["subgoals"]), 1)
        self.assertIn("证明引理 A 成立",
                      plan["subgoals"][0]["description"])
        self.assertEqual([a["id"] for a in plan["anticipatory_lemmas"]], ["aux"])

    def test_depends_on_not_broken_by_anticipatory(self):
        """前瞻引理被排除后，其余子目标的 depends_on 索引仍正确。

        注意 DAG 语义：`to_subgoal_plan()` 只把**叶子**收进求解链，
        非叶节点（如这里的 n1）只是结构节点、不作为子目标出现。
        因此叶子之间若无祖先关系，depends_on 就是空 —— 这是既有语义。
        本测试要保证的是：前瞻引理的出现**不会扰动**这套索引。
        """
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["n1", "n2"]),
            "n1": BlueprintNode("n1", "and", "证明引理 A 成立", ["n1a"]),
            "n1a": BlueprintNode("n1a", "and", "证明引理 A 的叶子", []),
            "n2": BlueprintNode("n2", "and", "证明引理 B 成立", []),
            "aux": BlueprintNode("aux", "and", "前瞻引理陈述", [],
                                 "", "anticipatory"),
        }, root_id="g")
        plan = dag.to_subgoal_plan()
        # 只有两个叶子进链（n1 非叶，不进）
        self.assertEqual(len(plan["subgoals"]), 2)
        sgs = {s["description"]: s for s in plan["subgoals"]}
        self.assertEqual(set(sgs),
                         {"证明引理 A 的叶子", "证明引理 B 成立"})
        # ★ 2026-09-15：依赖边改为按**依赖锥**计算（修复此前的"恒空"）。
        # n2 在 g.children 里排在 n1 之后 ⇒ 依赖 n1 子树下的叶子 n1a。
        self.assertEqual(sgs["证明引理 A 的叶子"]["depends_on"], [])
        self.assertEqual(sgs["证明引理 B 成立"]["depends_on"], [1],
                         "后序兄弟子树下的叶子应成为依赖（前瞻引理不得扰动）")
        # 索引必须是稠密的 1..n（前瞻引理未占据任何 id 位）
        self.assertEqual([s["id"] for s in plan["subgoals"]], [1, 2])

    def test_depends_on_with_ancestor_leaf(self):
        """真正存在"叶子依赖叶子"时，索引须指向正确的序号。

        DAG 语义：`to_subgoal_plan()` 只收**初始叶子**（children 为空的节点）。
        要造出"叶子 a 是叶子 b 的祖先"，必须让 b 的 children 指向 a ——
        但那样 b 就变成非叶了。所以叶子之间的依赖**无法**用 DAG 父子边表达。

        真正会产出非空 depends_on 的情形是 **OR 分支**：
        OR 节点只展开第一个 child，但另一个 child 若也被引用，
        仍能作为祖先出现在 selected 里。这里用"同一节点被两处引用"构造。

        本测试的实质断言：**depends_on 的序号始终是稠密且正确的**，
        引入前瞻引理不会让它错位。
        """
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["a", "b"]),
            # a 是叶子
            "a": BlueprintNode("a", "and", "第一步：得到中间结论 C", []),
            # b 是叶子（无 children）
            "b": BlueprintNode("b", "and", "第二步：综合得出最终结论", []),
            # aux 旁挂
            "aux": BlueprintNode("aux", "and", "前瞻引理陈述", [],
                                 "", "anticipatory"),
        }, root_id="g")
        plan = dag.to_subgoal_plan()
        sgs = {s["description"]: s for s in plan["subgoals"]}
        self.assertEqual(len(plan["subgoals"]), 2)
        # 序号必须稠密 1..n，且是从 1 开始 —— 前瞻引理不占位
        self.assertEqual(sorted(s["id"] for s in plan["subgoals"]), [1, 2])
        # ★ 2026-09-15：依赖锥语义 —— b 在 g.children 里排在 a 之后，故依赖 a。
        # 旧断言（两叶子恒无依赖）反映的是"depends_on 结构性恒空"的更早 bug。
        self.assertEqual(sgs["第一步：得到中间结论 C"]["depends_on"], [])
        self.assertEqual(sgs["第二步：综合得出最终结论"]["depends_on"], [1])
        # 加入前瞻引理后不变
        self.assertIn("aux", [a["id"] for a in plan["anticipatory_lemmas"]])

    def test_ancestor_leaf_referenced_twice_keeps_index(self):
        """同一叶子被两处引用 → 只出现一次，且被依赖方的序号正确。"""
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["m", "n"]),
            # m 非叶：展开后是 leaf1
            "m": BlueprintNode("m", "and", "中间步骤 M", ["leaf1"]),
            "leaf1": BlueprintNode("leaf1", "and", "第一步：得到中间结论 C", []),
            # n 直接引用 leaf1 作为子（形成"共享节点"）
            "n": BlueprintNode("n", "and", "收尾步骤 N", ["leaf1"]),
        }, root_id="g")
        plan = dag.to_subgoal_plan()
        # leaf1 被 m 和 n 共享 → 只入链一次（去重）
        descs = [s["description"] for s in plan["subgoals"]]
        self.assertEqual(descs.count("第一步：得到中间结论 C"), 1,
                         "共享引理节点不得重复入链（LEAP 引理记忆化语义）")
        for s in plan["subgoals"]:
            self.assertEqual(s["id"], 1)

    def test_no_anticipatory_yields_empty_list(self):
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", "证明 P", ["n1"]),
            "n1": BlueprintNode("n1", "and", "证 A", []),
        }, root_id="g")
        plan = dag.to_subgoal_plan()
        self.assertEqual(plan["anticipatory_lemmas"], [])
        self.assertIn("anticipatory_lemmas", plan)

    def test_empty_dag_has_key(self):
        plan = BlueprintDAG(nodes={}, root_id="").to_subgoal_plan()
        self.assertEqual(plan["subgoals"], [])
        self.assertEqual(plan["anticipatory_lemmas"], [])


# ============================================================
# 第 3 层 · 引理记忆注入
# ============================================================

class TestInjectAnticipatoryLemmas(unittest.TestCase):

    def test_injects_into_lemma_repo(self):
        solver = make_solver()
        ctx = make_ctx()
        n = solver._inject_anticipatory_lemmas(ctx, [
            {"id": "aux1", "statement": "中间恒等式 (x-1)(x+1)=x^2-1",
             "rationale": "后续化归"},
        ])
        self.assertEqual(n, 1)
        self.assertEqual(len(ctx.lemma_repo), 1)
        self.assertIn("(x-1)(x+1)", ctx.lemma_repo[0])
        self.assertIn("前瞻引理", ctx.lemma_repo[0])
        self.assertIn("aux1", ctx.lemma_repo[0])

    def test_dedup(self):
        """重复注入同一条 → 不重复写。"""
        solver = make_solver()
        ctx = make_ctx()
        item = [{"id": "a", "statement": "某辅助引理陈述"}]
        solver._inject_anticipatory_lemmas(ctx, item)
        solver._inject_anticipatory_lemmas(ctx, item)
        self.assertEqual(len(ctx.lemma_repo), 1)

    def test_empty_input_noop(self):
        solver = make_solver()
        ctx = make_ctx()
        self.assertEqual(solver._inject_anticipatory_lemmas(ctx, []), 0)
        self.assertEqual(ctx.lemma_repo, [])

    def test_blank_statement_skipped(self):
        solver = make_solver()
        ctx = make_ctx()
        n = solver._inject_anticipatory_lemmas(ctx, [
            {"id": "x", "statement": "   "},
            {"id": "y", "statement": ""},
            {}, "  ",
        ])
        self.assertEqual(n, 0)
        self.assertEqual(ctx.lemma_repo, [])

    def test_respects_domain_routing(self):
        """领域路由关闭时（lemma_domains 不含当前域）不注入。

        与 _accumulate_lemma 同规则：既有 A/B 结论"引理注入只在数论开"
        不得被悄悄绕过。
        """
        solver = make_solver()
        solver.config.lemma_domains = ["数论"]
        ctx_int = make_ctx(domain="数论")
        ctx_alg = make_ctx(domain="代数")
        items = [{"id": "a", "statement": "辅助引理陈述"}]
        self.assertEqual(solver._inject_anticipatory_lemmas(ctx_int, items), 1)
        self.assertEqual(solver._inject_anticipatory_lemmas(ctx_alg, items), 0)
        self.assertEqual(ctx_alg.lemma_repo, [])

    def test_disabled_when_accumulation_off(self):
        solver = make_solver()
        solver.config.use_lemma_accumulation = False
        ctx = make_ctx()
        self.assertEqual(
            solver._inject_anticipatory_lemmas(
                ctx, [{"id": "a", "statement": "辅助引理"}]), 0)
        self.assertEqual(ctx.lemma_repo, [])

    def test_plain_string_item_tolerated(self):
        """容错：非 dict 条目（裸字符串）也能注入。"""
        solver = make_solver()
        ctx = make_ctx()
        n = solver._inject_anticipatory_lemmas(ctx, ["裸字符串形式的前瞻引理"])
        self.assertEqual(n, 1)
        self.assertIn("裸字符串", ctx.lemma_repo[0])

    def test_consumed_by_lemma_context(self):
        """端到端：注入的引理能被 _use_lemma 门禁放行并出现在提示词上下文。

        这是"整根线接通"的关键断言 —— 注入 write 侧与读取侧必须同源。
        """
        solver = make_solver()
        ctx = make_ctx(domain="数论")
        solver._inject_anticipatory_lemmas(
            ctx, [{"id": "aux", "statement": "关键恒等式 x^2-1=(x-1)(x+1)"}])
        self.assertTrue(solver._use_lemma(ctx),
                        "读取侧的门禁必须与写入侧一致，否则注入白做")
        lemmas = list(getattr(ctx, "lemma_repo", []))
        self.assertTrue(any("x^2-1" in l for l in lemmas))


if __name__ == "__main__":
    unittest.main()
