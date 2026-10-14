# -*- coding: utf-8 -*-
"""子目标求解智能体（SubGoalSolverAgent）单元测试。

覆盖:
- ``_extract_json``: JSON 解析（代码块 / 纯 JSON / 坏输入）
- ``_parse_subgoal_plan``: 规划校验、去重、类型白名单、上限
- ``run``: 全流程（mock client）追加候选
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.base import TaskContext, Budget, Candidate
from agent.sub_goal_solver import SubGoalSolverAgent
from agent.blueprint_planner import BlueprintDAG


def _ctx(max_calls: int = 50) -> TaskContext:
    """多 agent 测试用的 ctx（时间/预算宽裕，闸门默认放行）。"""
    return TaskContext(
        problem="求 x^2 = 4 的解",
        metadata={},
        start_time=time.time(),
        deadline=time.time() + 900,
        budget=Budget(max_calls=max_calls),
    )


def make_agent(client=None) -> SubGoalSolverAgent:
    config = SimpleNamespace(
        subgoal_self_improve_rounds=0,  # 2026-10-13 隔离：新接线（子目标自改进）会多跑 LLM 调用
        max_total_calls=20,
        max_time_per_question=300,
        max_total_time_seconds=21000,
        policy_max_tokens=2048,
    )
    return SubGoalSolverAgent(client=client or MockClient(), config=config)


_PLAN_JSON = (
    "```json\n"
    '{"problem_analysis": {"domain": "代数", "core_objective": "求解"},'
    '"subgoals": ['
    '{"id": 1, "title": "化简", "description": "先化简", '
    '"type": "compute", "depends_on": [], "expected_output": "化简结果"}'
    '], "merge_strategy": "合并"}'
    "\n```"
)


class MockClient:
    """按**调用类型**返回：规划 JSON / 本步结果 / 合并最终答案。

    ★ 2026-10-07（问题 2.4 候选入池门槛 v2）：原 mock 对**所有**调用都返回同一段
    规划 JSON —— 它不含最终答案，新门槛（`pool_gate_v2`，默认开）会**正确地**
    拒绝该子目标候选 ⇒ 这 3 个"run() 追加候选"用例失败。此处按真实流水线给
    三类调用分别返回合规内容（step 段给结论契约、merge 段给纯答案），
    断言与语义均保持不变。
    """

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        return self.call(messages=messages, temperature=temperature,
                         max_tokens=max_tokens, **kw)

    def call(self, messages=None, temperature=0.0, max_tokens=256, **kw):
        blob = "\n".join(str(m.get("content", "")) for m in (messages or []))
        if "输出子目标规划" in blob:            # ① 规划调用
            return _PLAN_JSON
        if "【当前子目标" in blob:               # ② 单步求解调用
            return "【本步结果】\n本步结论: 值 = 1\n本步依据: 本步推导"
        # ③ 合并/兜底调用：走 prefill（`【最终答案】`），拼接后首行即答案
        return "1"


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

    def test_fixed_budget_not_tail_capped(self) -> None:
        """2026-10-01：tail_reserve 已按用户决策删除 ⇒ 真实 deadline 下
        stage_end 不再被 `deadline - reserve` 压制，而是固定预算 start+budget。"""
        import time as _t
        agent = make_agent()
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300  # 真实未来时间戳（但不再参与压制）
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        end = self._stage_end_of(ctx)
        self.assertGreater(end, 0.0)
        # 固定预算 750s > 该 deadline(now+300) ⇒ 可越过 deadline（已无尾部预留）
        self.assertGreater(end, ctx.deadline)

    def test_override_budget_sec_zero_disables_cap(self) -> None:
        """subgoal_stage_budget_sec=0 ⇒ 阶段预算完全停用（stage_end=0）。

        （2026-10-01：tail_reserve 已删，不再有"第二层"deadline 兜底。）"""
        import time as _t
        from types import SimpleNamespace as _NS
        agent = make_agent()
        agent.config = _NS(
            max_total_calls=20, max_time_per_question=300,
            subgoal_self_improve_rounds=0,  # 4.2 隔离
            max_total_time_seconds=21000, policy_max_tokens=2048,
            subgoal_stage_budget_sec=0.0,  # 放弃固定预算
        )
        ctx = make_ctx()
        ctx.deadline = _t.time() + 300  # 真实 deadline
        ctx.candidates.append(Candidate(id=1, answer="1", reasoning="候选1", revised=False))
        agent.run(ctx)
        self.assertEqual(self._stage_end_of(ctx), 0.0)

    def test_disable_both_budget_and_reserve(self) -> None:
        """固定预算=0 且 tail_reserve=0 → 阶段预算完全停用（stage_end=0）。"""
        import time as _t
        from types import SimpleNamespace as _NS
        agent = make_agent()
        agent.config = _NS(
            max_total_calls=20, max_time_per_question=300,
            subgoal_self_improve_rounds=0,  # 4.2 隔离
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
            subgoal_self_improve_rounds=0,  # 2026-10-13 隔离：新接线（子目标自改进）会多跑 LLM 调用
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


if __name__ == "__main__":
    unittest.main()
