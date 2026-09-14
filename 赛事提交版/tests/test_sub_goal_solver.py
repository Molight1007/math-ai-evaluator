# -*- coding: utf-8 -*-
"""子目标求解智能体（SubGoalSolverAgent）单元测试。

覆盖:
- ``_extract_json``: JSON 解析（代码块 / 纯 JSON / 坏输入）
- ``_parse_subgoal_plan``: 规划校验、去重、类型白名单、上限
- ``run``: 全流程（mock client）追加候选
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.base import TaskContext, Budget, Candidate
from agent.sub_goal_solver import SubGoalSolverAgent
from agent.blueprint_planner import BlueprintDAG, BlueprintNode


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


# ------------------------------------------------------------------
# S1-lite / S2（2026-09-06 老师建议：子目标独立性 + 校验前移）单元测试
# ------------------------------------------------------------------
class SubgoalCtxModeTest(unittest.TestCase):
    """S2：subgoal_ctx_mode="deps" 时按 depends_on 只注入直接依赖结果。"""

    @staticmethod
    def _subgoals() -> list:
        return [
            {"id": 1, "title": "a", "depends_on": []},
            {"id": 2, "title": "b", "depends_on": [1]},
            {"id": 3, "title": "c", "depends_on": [1, 2]},
        ]

    def test_only_direct_deps_injected(self) -> None:
        results = {1: "R1", 2: "R2"}
        out = SubGoalSolverAgent._format_dep_results(
            results, self._subgoals(), self._subgoals()[2])
        self.assertIn("#1", out)
        self.assertIn("#2", out)
        self.assertIn("R1", out)
        self.assertIn("R2", out)

    def test_no_dep_returns_empty(self) -> None:
        """无依赖子目标 → 零前序上下文（独立性，可并行）。"""
        out = SubGoalSolverAgent._format_dep_results(
            {1: "R1"}, self._subgoals(), self._subgoals()[0])
        self.assertEqual(out, "")

    def test_unresolved_deps_all_skipped(self) -> None:
        out = SubGoalSolverAgent._format_dep_results(
            {}, self._subgoals(), self._subgoals()[1])
        self.assertEqual(out, "")

    def test_partial_unresolved_filtered(self) -> None:
        """id=3 依赖 [1,2]，2 未解出 → 只带已解出的 1。"""
        out = SubGoalSolverAgent._format_dep_results(
            {1: "R1"}, self._subgoals(), self._subgoals()[2])
        self.assertIn("#1", out)
        self.assertNotIn("#2", out)


class ExtractLeanCodeTest(unittest.TestCase):
    """_extract_lean_code：从子目标结果提取 lean 代码片。"""

    def test_lean_fence(self) -> None:
        r = SubGoalSolverAgent._extract_lean_code(
            "说明\n```lean\nimport Mathlib.Tactic\nexample : 1+1=2 := by norm_num\n```\n尾")
        self.assertIn("example", r)
        self.assertIn("import Mathlib.Tactic", r)

    def test_plain_fence(self) -> None:
        r = SubGoalSolverAgent._extract_lean_code("```\nfoo bar\n```")
        self.assertEqual(r, "foo bar")

    def test_bare_import_block(self) -> None:
        """无 fence 但以 import 开头（裸 lean 代码）→ 收整段。"""
        r = SubGoalSolverAgent._extract_lean_code(
            "import Mathlib.Tactic\n#check Nat.add_comm")
        self.assertIn("#check Nat.add_comm", r)

    def test_no_code(self) -> None:
        self.assertEqual(SubGoalSolverAgent._extract_lean_code("纯文字：x=1"), "")
        self.assertEqual(SubGoalSolverAgent._extract_lean_code(""), "")
        self.assertEqual(SubGoalSolverAgent._extract_lean_code(None), "")


class SubgoalLightCheckTest(unittest.TestCase):
    """S1-lite：子目标级 0-LLM 校验（L0 截断 / L1 lean 代码片编译）。"""

    @staticmethod
    def _make_agent() -> SubGoalSolverAgent:
        config = SimpleNamespace(
            max_total_calls=20,
            max_time_per_question=300,
            max_total_time_seconds=21000,
            policy_max_tokens=2048,
            enable_subgoal_lean_check=True,
        )
        return SubGoalSolverAgent(client=None, config=config)

    @staticmethod
    def _deep_ctx() -> TaskContext:
        ctx = make_ctx()
        ctx.tier = "deep"
        return ctx

    @staticmethod
    def _lean_result() -> str:
        return "```lean\nexample : True := by trivial\n```"

    def test_empty_result_returns_hint(self) -> None:
        out = self._make_agent()._subgoal_light_check(self._deep_ctx(), {}, "")
        self.assertIn("为空", out)

    def test_truncated_result_returns_hint(self) -> None:
        with patch("utils.extract.is_truncated_answer", return_value=True):
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, "结果内容很长很完整…")
        self.assertIn("截断", out)

    def test_standard_tier_skips_lean(self) -> None:
        """L1 仅 deep 档：standard 档带 lean 代码也不编译（L0 截断检查照跑）。"""
        ctx = make_ctx()  # tier 默认 standard
        out = self._make_agent()._subgoal_light_check(ctx, {}, self._lean_result())
        self.assertEqual(out, "")

    def test_deep_no_code_passes(self) -> None:
        out = self._make_agent()._subgoal_light_check(
            self._deep_ctx(), {}, "正常数学结果 x=1")
        self.assertEqual(out, "")

    def test_lean_unavailable_passes(self) -> None:
        with patch("tools.lean_local.lean_bridge.LeanBridge") as m_cls:
            m_cls.return_value.lean_available = False
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, self._lean_result())
        self.assertEqual(out, "")

    def test_lean_compile_error_returns_hint(self) -> None:
        with patch("tools.lean_local.lean_bridge.LeanBridge") as m_cls:
            inst = m_cls.return_value
            inst.lean_available = True
            inst._lean_project_dir = "/fake/proj"
            inst._compile.return_value = {
                "ok": False, "error": "unknown identifier 'x'"}

            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, self._lean_result())
        self.assertIn("编译失败", out)

    def test_lean_constructor_exception_passes(self) -> None:
        """校验异常一律放行（0-LLM 校验绝不阻断主流程）。"""
        with patch("tools.lean_local.lean_bridge.LeanBridge",
                   side_effect=RuntimeError("boom")):
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, self._lean_result())
        self.assertEqual(out, "")

    def test_config_disable_skips_lean(self) -> None:
        agent = self._make_agent()
        agent.config.enable_subgoal_lean_check = False
        with patch("tools.lean_local.lean_bridge.LeanBridge") as m_cls:
            out = agent._subgoal_light_check(
                self._deep_ctx(), {}, self._lean_result())
        m_cls.assert_not_called()
        self.assertEqual(out, "")

    # ---- L0P 占位/空转检测（2026-09-07 禁网冒烟实证拦截项）----

    def test_placeholder_None_hint(self) -> None:
        out = self._make_agent()._subgoal_light_check(
            self._deep_ctx(), {}, "（无）")
        self.assertIn("占位", out)

    def test_placeholder_solved_hint(self) -> None:
        out = self._make_agent()._subgoal_light_check(
            self._deep_ctx(), {}, "（子目标4 已求解）")
        self.assertIn("占位", out)

    def test_trivial_calc_backfill_blocked(self) -> None:
        """2026-09-08 升级：`[计算] X = X`（result 与表达式逐字相同）是**无运算**
        的平凡回填（模型把结论原样丢给 <calc> 自证）→ 判占位拦截，带反馈重解。
        `<calc>191/192</calc>` 也是同型（没有任何运算发生），不属"真分数验证"——
        真验证应写实际运算（如 <calc>gcd(191,192)</calc>）。"""
        for s in ("[计算] 1 = 1", "[计算] 0 = 0", "[计算] 191/192 = 191/192",
                  "[计算] (k-1)*(l-1)//2 = (k-1)*(l-1)//2"):
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, s)
            self.assertIn("占位", out, f"平凡回填未拦截: {s!r}")

    def test_real_calc_backfill_passes(self) -> None:
        """真正发生运算的 calc 回填（result ≠ 表达式）不误伤。"""
        for s in ("[计算] comb(50,3) = 19600",
                  "[计算] 3*7-1 = 20",
                  "[计算] 5+1 = 6",
                  "[计算] gcd(191,192) = 1",
                  "经代入得 [计算] 2**10 = 1024，故结果为 1024"):
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, s)
            self.assertEqual(out, "", f"误伤真实回填: {s!r}")

    def test_real_short_result_passes(self) -> None:
        """短但真实的结果（数值/不等式）不误伤。"""
        for real in ("191/192",
                     "(x+y+z+t)/4 ≥ (xyz t)^{1/4}",
                     "x²+y²+z²+t² ≥ 2(xy+zt)",
                     "方程无解",          # "无解"是真数学结论，勿拦
                     "用待定系数求得 a=1"):  # "待定"是真数学术语，勿拦
            out = self._make_agent()._subgoal_light_check(
                self._deep_ctx(), {}, real)
            self.assertEqual(out, "", f"误伤真实结果: {real!r}")

    def test_long_result_with_word_passes(self) -> None:
        """>50 字符的长结果不做占位判定（"已求解"可能出现在正常行文中）。"""
        long_text = "（该子目标已求解，结论如下）" + "进一步分析..." * 10
        out = self._make_agent()._subgoal_light_check(
            self._deep_ctx(), {}, long_text)
        self.assertEqual(out, "")

    def test_lookup_helper_direct(self) -> None:
        self.assertTrue(SubGoalSolverAgent._looks_placeholder("（无）"))
        self.assertTrue(SubGoalSolverAgent._looks_placeholder("暂无"))
        self.assertTrue(SubGoalSolverAgent._looks_placeholder("（子目标2 已求解）"))
        self.assertTrue(SubGoalSolverAgent._looks_placeholder("[计算] 1 = 1"))
        self.assertTrue(SubGoalSolverAgent._looks_placeholder("[计算] 191/192 = 191/192"))
        self.assertFalse(SubGoalSolverAgent._looks_placeholder("[计算] comb(50,3) = 19600"))
        self.assertFalse(SubGoalSolverAgent._looks_placeholder("191/192"))
        self.assertFalse(SubGoalSolverAgent._looks_placeholder(None))
        self.assertFalse(SubGoalSolverAgent._looks_placeholder(""))


class SolveSubgoalHintTest(unittest.TestCase):
    """_solve_subgoal extra_hint：S1-lite 校验反馈随重解请求带回提示词。"""

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

    @staticmethod
    def _sg() -> dict:
        return {"id": 1, "title": "求值", "type": "compute", "depends_on": [],
                "description": "计算 x", "expected_output": "数值"}

    def _user_content(self, client) -> str:
        return next(m["content"] for m in client.last_messages
                    if m["role"] == "user")

    def test_hint_appended_when_present(self) -> None:
        agent = make_agent()
        client = self._RecordingClient("【本步结果】\nx=1")
        agent.client = client
        out = agent._solve_subgoal(make_ctx(), self._sg(), "plan", "",
                                   extra_hint="Lean 编译失败：unknown identifier 'x'")
        content = self._user_content(client)
        self.assertIn("[本步结果校验反馈]", content)
        self.assertIn("Lean 编译失败", content)
        self.assertEqual(out, "x=1")

    def test_no_hint_no_feedback_block(self) -> None:
        agent = make_agent()
        client = self._RecordingClient("【本步结果】\nx=1")
        agent.client = client
        agent._solve_subgoal(make_ctx(), self._sg(), "plan", "")
        self.assertNotIn("[本步结果校验反馈]", self._user_content(client))


class DagReplanGateTest(unittest.TestCase):
    """_dag_replan_gate：求解前 DAG 强制评审门（2026-09-08 改进建议1）。

    蓝图高拒绝率（should_replan）→ 强制带反馈重规划循环 → 通过才放行；
    修复后的 DAG 必须写回 ctx.blueprint（旧 replan 从不落盘 = 白跑）。
    """

    @staticmethod
    def _dag() -> BlueprintDAG:
        return BlueprintDAG(
            nodes={
                "r": BlueprintNode(id="r", node_type="and",
                                   statement="根：证明原题结论", children=["a", "b"]),
                "a": BlueprintNode(id="a", node_type="or",
                                   statement="子目标 a：中间引理", children=[]),
                "b": BlueprintNode(id="b", node_type="or",
                                   statement="子目标 b：中间引理", children=[]),
            },
            root_id="r",
        )

    @staticmethod
    def _fixed_dag() -> BlueprintDAG:
        return BlueprintDAG(
            nodes={
                "r": BlueprintNode(id="r", node_type="and",
                                   statement="根：修复后的分解", children=["a2"]),
                "a2": BlueprintNode(id="a2", node_type="or",
                                    statement="新子目标（覆盖全部约束）", children=[]),
            },
            root_id="r",
        )

    @staticmethod
    def _report(replan: bool, rejected=None) -> SimpleNamespace:
        rejected = rejected or []
        return SimpleNamespace(
            should_replan=lambda: replan,
            rejected_nodes=lambda: list(rejected),
            accepted_nodes=lambda: [],       # 2026-09-08 门升级：Lean 检查需要
            results={},                      # 2026-09-08 门升级：Lean 诊断并入 feedback
            merge_from_hints=lambda: "[a] 子目标粒度过粗" if rejected else "",
            degraded=False,
            reject_count=len(rejected),
        )

    def test_high_reject_forces_replan_and_persists(self) -> None:
        """should_replan → regenerate 被调 → 重评审通过 → 新 DAG 写回 ctx.blueprint。"""
        agent = make_agent()
        ctx = make_ctx()
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_cls, \
                patch("agent.blueprint_planner.BlueprintPlannerAgent") as p_cls:
            reviewer = m_cls.return_value
            # 第 1 轮评审：48% 拒绝（应重规划）；重规划后再评审：通过
            reviewer.review.side_effect = [
                self._report(True, ["a", "b"]),
                self._report(False),
            ]
            planner = p_cls.return_value
            planner.regenerate_with_feedback.return_value = self._fixed_dag()

            out = agent._dag_replan_gate(ctx, self._dag())

        self.assertIsNotNone(out)
        self.assertEqual(out.root_id, "r")
        # 强制触发了整树重生成（高拒绝蓝图不得带病进求解）
        self.assertEqual(planner.regenerate_with_feedback.call_count, 1)
        self.assertEqual(reviewer.review.call_count, 2)
        # 修复后的 DAG 写回 ctx.blueprint，供 _plan_from_blueprint 转 plan 消费
        self.assertIsNotNone(ctx.blueprint)
        self.assertEqual(ctx.blueprint["root_id"], "r")
        node_ids = [n.get("id") for n in ctx.blueprint["nodes"]]
        self.assertIn("a2", node_ids)

    def test_clean_dag_passes_without_replan(self) -> None:
        """蓝图评审通过 → 不触发重规划，原 DAG 原样返回并写回。"""
        agent = make_agent()
        ctx = make_ctx()
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_cls, \
                patch("agent.blueprint_planner.BlueprintPlannerAgent") as p_cls:
            m_cls.return_value.review.return_value = self._report(False)
            out = agent._dag_replan_gate(ctx, self._dag())
        self.assertIsNotNone(out)
        p_cls.return_value.regenerate_with_feedback.assert_not_called()
        self.assertEqual(ctx.blueprint["root_id"], "r")

    def test_budget_exhausted_passes_original(self) -> None:
        """全局预算耗尽 → 放行原 DAG（质量门不阻断主流程）。"""
        agent = make_agent()
        ctx = make_ctx()
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_cls, \
                patch.object(ctx, "gen_time_up", return_value=True):
            out = agent._dag_replan_gate(ctx, self._dag())
        # 实例化无害；关键是不执行评审（不烧 LLM 预算）
        m_cls.return_value.review.assert_not_called()
        self.assertIsNotNone(out)
        self.assertEqual(ctx.blueprint["root_id"], "r")

    def test_replan_failure_keeps_current_dag(self) -> None:
        """重生成失败 → 保留当前蓝图进求解（信号记入 diag，不阻断）。"""
        agent = make_agent()
        ctx = make_ctx()
        with patch("agent.dag_reviewer.DagReviewerAgent") as m_cls, \
                patch("agent.blueprint_planner.BlueprintPlannerAgent") as p_cls:
            m_cls.return_value.review.return_value = self._report(True, ["a"])
            p_cls.return_value.regenerate_subtree.return_value = None
            p_cls.return_value.regenerate_with_feedback.return_value = None
            out = agent._dag_replan_gate(ctx, self._dag())
        self.assertIsNotNone(out)
        self.assertEqual(ctx.blueprint["root_id"], "r")


class MergeSpinRetryTest(unittest.TestCase):
    """_merge_results：蓝图结论注入 + merge 空转自动重试（2026-09-08 建议3/6）。

    alg-009 教训：merge 计划最终答案 = "[计算]0=0"（空转）仍照常入候选。
    现在 merge 提取到占位/平凡回填 → 带反馈重试一次；蓝图 root 结论注入
    user 模板供输出对齐（防 alg-053/068 输出端漂移）。
    """

    def test_placeholder_merge_retried_once(self) -> None:
        agent = make_agent()
        ctx = make_ctx()
        ctx.blueprint = {
            "root_id": "r",
            "nodes": [{"id": "r", "statement": "证明最终答案为 42",
                       "children": []}],
        }
        subgoals = [{"id": 1, "title": "求解", "description": "求 x",
                     "type": "compute", "depends_on": [], "expected_output": "数值",
                     "result": "x=42"}]
        spin = "【矛盾检查】无矛盾\n【结论合并】略\n【最终答案】\n[计算] 0 = 0"
        ok = "【矛盾检查】无矛盾\n【结论合并】合并各子目标\n【最终答案】\n42"
        with patch.object(agent, "llm", side_effect=[spin, ok]) as m_llm:
            out = agent._merge_results(
                ctx, subgoals, "plan-summary", {1: "x=42"}, "合并策略")
        self.assertEqual(out.strip(), "42")
        self.assertEqual(m_llm.call_count, 2)          # 空转 → 带反馈重试
        second_user = m_llm.call_args_list[1].args[1][1]["content"]
        self.assertIn("空转", second_user)
        # 蓝图最终结论注入 user 模板（输出对齐锚点）
        first_user = m_llm.call_args_list[0].args[1][1]["content"]
        self.assertIn("证明最终答案为 42", first_user)

    def test_good_merge_no_retry(self) -> None:
        agent = make_agent()
        ctx = make_ctx()
        ctx.blueprint = None   # 无蓝图 → 占位文本，不阻断
        subgoals = [{"id": 1, "title": "t", "description": "d", "type": "compute",
                     "depends_on": [], "expected_output": "", "result": "3"}]
        ok = "【矛盾检查】一致\n【结论合并】合并\n【最终答案】\n3"
        with patch.object(agent, "llm", side_effect=[ok]) as m_llm:
            out = agent._merge_results(ctx, subgoals, "p", {1: "3"}, "s")
        self.assertEqual(m_llm.call_count, 1)
        self.assertEqual(out.strip(), "3")


if __name__ == "__main__":
    unittest.main()
