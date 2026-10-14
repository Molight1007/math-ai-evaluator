# -*- coding: utf-8 -*-
"""任务 #2 守卫：定理检索从 `1.2` 独立阶段下移到 `2.7` 子目标求解。

用户任务列表原文 #2：
    「定理检索移到后面子目标求解过程中，但定理检索能不能帮助大模型理解题目
      这个需要测试。就是用 leansearch 去搜索定理然后将定理返回给大模型，让
      大模型的推理方向更准确。这个环节的产出就是 25 个定理。」

本文件守住四层：

① **阶段层** —— `1.2_theorem_hint` 的打点 / 函数 / 预算 / 收尾清单 / 审计行
   已全部撤除，现行阶段 14 段；
② **执行点** —— 检索只在 `SubGoalSolverAgent.run` 体首发起，且**早于**
   `_plan_subgoals`（蓝图构建在其内）⇒ 蓝图 3 处 / 规划 / merge+solve / 3_solve
   的 8 个消费点全部仍在检索之后，无需改动；
③ **消费层** —— 2.6 内两处注入（`audit_gate.confirm_understanding`、
   `lean_pre_verifier` 理解链）已撤：检索在其后，留着即静默死代码；
④ **效用层** —— 子目标规划提示词真正注入定理块（`subgoal` 环节），
   默认条数 25，且注册表默认 JSON 与模块默认表一致。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _code_only(src: str) -> str:
    """剔除**文档字符串 + 整行注释**后的正文。

    用于「某符号不得再出现」类断言：允许 docstring / 注释留痕（阶段名是契约，
    历史留痕是刻意保留的；"已撤除"说明也会点名被删符号），只禁止**代码正文**
    再引用。
    """
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))


class StageRemovalTest(unittest.TestCase):
    """① 1.2_theorem_hint 作为独立阶段已彻底撤销。"""

    def test_no_stage_start_call(self):
        self.assertNotIn('_stage_start(ctx, "1.2_theorem_hint")',
                         _read("agent/orchestrator.py"))

    def test_no_stage_stop_entry(self):
        src = _read("agent/orchestrator.py")
        m = re.search(r"for _stg in \((.*?)\):", src, flags=re.S)
        self.assertIsNotNone(m, "未找到 _run_finalize 的统一收尾清单")
        self.assertNotIn("1.2_theorem_hint", m.group(1),
                         "收尾清单仍含 1.2（_stage_stop 会对不存在的阶段空转）")

    def test_stage_function_removed(self):
        self.assertNotIn("def theorem_hint_stage",
                         _read("agent/orchestrator__prep.py"))

    def test_not_imported_by_orchestrator(self):
        code = _code_only(_read("agent/orchestrator.py"))
        self.assertNotIn("theorem_hint_stage", code)

    def test_budget_entry_removed(self):
        code = _code_only(_read("agent/orchestrator__budget.py"))
        self.assertNotIn('"1.2_theorem_hint"', code,
                         "阶段预算表仍给 1.2 留额度（该阶段已不存在）")

    def test_stage_audit_row_removed(self):
        code = _code_only(_read("tools/stage_audit.py"))
        self.assertNotIn('("1.2_theorem_hint"', code)

    def test_cloud_hint_says_14_stages(self):
        self.assertIn("14 个阶段", _read("tools/cloud.py"))
        self.assertIn("2.6_pre_audit", _read("tools/cloud.py"))

    def test_current_stage_set(self):
        """现行阶段名集合恰好 14 个，且两个已撤阶段都不在其中。"""
        names = set(re.findall(
            r'_stage_start\(ctx, "([^"]+)"', _read("agent/orchestrator.py")))
        self.assertEqual(len(names), 14, "阶段数应为 14：%s" % sorted(names))
        self.assertNotIn("1.2_theorem_hint", names)
        self.assertNotIn("1.1_type_understanding", names)
        self.assertIn("2.6_pre_audit", names)
        self.assertIn("2.7_subgoal_main", names)


class ExecutionPointTest(unittest.TestCase):
    """② 检索执行点在 2.7 体首，且早于 `_plan_subgoals`。"""

    def test_run_hint_for_is_duck_typed(self):
        from agent.theorem_hint import run_hint_for
        self.assertEqual(list(inspect.signature(run_hint_for).parameters),
                         ["agent", "ctx"],
                         "必须是鸭子类型签名，否则子目标求解器无法调用")

    def test_called_in_subgoal_run_before_plan(self):
        from agent.sub_goal_solver import SubGoalSolverAgent
        src = inspect.getsource(SubGoalSolverAgent.run)
        # 用**实际调用形态**定位，避开注释里对 `run_hint_for` 的引用
        i_hint = src.find("run_hint_for(self, ctx)")
        i_plan = src.find("_plan_subgoals(ctx)")
        self.assertGreater(i_hint, 0, "SubGoalSolver.run 未发起定理检索")
        self.assertLess(i_hint, i_plan,
                        "检索必须早于 _plan_subgoals（蓝图构建在其内）")

    def test_emergency_guard_preserved(self):
        """搬移不得丢掉原 `theorem_hint_stage` 的紧急态守卫。

        注意：用**实际调用点** `run_hint_for(self, ctx)` 定位（体首注释里也
        出现过裸名 `run_hint_for`，用裸名会把窗口落在注释上而误判）。
        """
        from agent.sub_goal_solver import SubGoalSolverAgent
        src = inspect.getsource(SubGoalSolverAgent.run)
        i = src.find("run_hint_for(self, ctx)")
        self.assertGreater(i, 0, "SubGoalSolver.run 未发起定理检索")
        self.assertIn("ctx.state.emergency", src[max(0, i - 300):i],
                      "紧急态守卫（ctx.state.emergency）丢失")

    def test_master_switch_gate_preserved(self):
        """搬移不得丢掉 master 开关 `enable_theorem_hint`（任务 #10 的 A/B 把手）。

        原 `theorem_hint_stage` 的判据是 `enable_theorem_hint and not
        ctx.state.emergency`；第一次搬移只留了后者 ⇒ 开关失效（`--enable_
        theorem_hint 0` 关不掉检索），A/B 实验会退化成「两组跑同一配置」。
        """
        from agent.sub_goal_solver import SubGoalSolverAgent
        src = inspect.getsource(SubGoalSolverAgent.run)
        i = src.find("run_hint_for(self, ctx)")
        self.assertGreater(i, 0)
        self.assertIn("enable_theorem_hint", src[max(0, i - 300):i],
                      "master 开关 enable_theorem_hint 丢失 ⇒ A/B 把手失效")

    def test_not_called_from_main_stages(self):
        source = _code_only(_read("agent/orchestrator.py"))
        seg = source[source.find("def _run_main_stages"):]
        seg = seg[:seg.find("\n    def ", 10)]
        self.assertNotIn("theorem_hint_stage(", seg)
        self.assertNotIn("run_hint_for", seg)

    def test_delegation_kept_for_compat(self):
        """`orchestrator__lean._retrieve_theorem_hints` 保留为薄委托。"""
        code = _code_only(_read("agent/orchestrator__lean.py"))
        self.assertIn("def _retrieve_theorem_hints", code)
        self.assertIn("run_hint_for", code)


class ConsumerTest(unittest.TestCase):
    """③ 2.6 内两处已失效注入已撤；2.7 及之后的消费点一个未少。"""

    def test_audit_gate_no_longer_reads_block(self):
        code = _code_only(_read("agent/audit_gate.py"))
        self.assertNotIn("theorem_hint_block", code,
                         "2.6 的题意复核已取不到定理（检索在其后），不得留死代码")

    def test_audit_gate_confirm_understanding_removed(self):
        """★ 2026-10-14 更新（题意理解收敛）：2.6 的 ``confirm_understanding``
        （原"题前理解确认"）已作为**双重不可达的死分支**整条删除 —— 其答题形态
        提示（`render_type_path_hint`）随之撤除，职责由 `judge_question_type`
        + `problem_goal` 覆盖。此处守住"确实已撤"，防止死分支回填。
        """
        code = _code_only(_read("agent/audit_gate.py"))
        self.assertNotIn("confirm_understanding", code,
                         "confirm_understanding 死分支已被删除，不得回填")
        self.assertNotIn("render_type_path_hint", code)

    def test_lean_pre_verifier_no_render_for_stage(self):
        code = _code_only(_read("tools/lean_local/lean_pre_verifier.py"))
        self.assertNotIn("render_for_stage", code)

    def test_downstream_consumers_all_intact(self):
        """8 个消费点全在 2.7 及之后 ⇒ 下移后逐个仍能取到定理。"""
        points = (
            "agent/blueprint_planner.py",
            "agent/solver.py",
            "agent/solver__prompt.py",
            "agent/solver__revise.py",
            "agent/sub_goal_solver__merge.py",
            "agent/sub_goal_solver__solve.py",
        )
        for rel in points:
            self.assertIn("theorem_hint_block", _read(rel),
                          "%s 的定理注入点丢失" % rel)


class UtilityTest(unittest.TestCase):
    """④ 定理真正进入子目标规划；条数 25；注册表与模块默认一致。"""

    def test_planner_injects_hint_block(self):
        src = _read("agent/sub_goal_solver__planner.py")
        i_inj = src.find("render_for_stage")
        i_tpl = src.find("SUBGOAL_PLAN_USER_TEMPLATE.format")
        self.assertGreater(i_inj, 0, "子目标规划未注入定理块")
        self.assertLess(i_inj, i_tpl,
                        "注入必须发生在规划提示词装订**之前**")

    def test_inject_targets_subgoal_stage(self):
        self.assertIn('_rfs(ctx, "subgoal")',
                      _read("agent/sub_goal_solver__planner.py"))

    def test_inject_writes_into_problem_placeholder(self):
        """注入对象必须是 `problem_text`（"题目"占位符内部），不得拼到提示词末尾。

        历史教训 algebra-075：末尾追加会破坏收尾结构，模型进入续写模式。
        """
        src = _read("agent/sub_goal_solver__planner.py")
        seg = src[src.find("render_for_stage"): src.find(
            "SUBGOAL_PLAN_USER_TEMPLATE.format")]
        self.assertIn("problem_text = problem_text +", seg)

    def test_default_topk_subgoal_is_25(self):
        from agent.theorem_hint import DEFAULT_TOPK_BY_STAGE
        self.assertEqual(DEFAULT_TOPK_BY_STAGE["subgoal"], 25,
                         "任务原文：这个环节的产出就是 25 个定理")

    def test_registry_default_matches_module(self):
        m = re.search(r"'(\{[^']*\"subgoal\"[^']*\})'",
                      _read("contracts/switch_registry.py"))
        self.assertIsNotNone(m, "未找到注册表里的分环节条数默认 JSON")
        from agent.theorem_hint import DEFAULT_TOPK_BY_STAGE as D
        self.assertEqual(json.loads(m.group(1)), D,
                         "注册表默认 JSON 与模块默认表必须逐字一致")

    def test_pre_audit_key_kept_for_history(self):
        """`pre_audit` 键保留（供外部脚本/历史数据取确定性条数），但无调用者。"""
        from agent.theorem_hint import DEFAULT_TOPK_BY_STAGE
        self.assertIn("pre_audit", DEFAULT_TOPK_BY_STAGE)
        # 只看**代码正文**：迁移说明注释里会引用该键名（阶段名是契约，留痕是
        # 刻意的），不得因注释而误判为「仍在取用」。
        for rel in ("agent/audit_gate.py",
                    "tools/lean_local/lean_pre_verifier.py"):
            self.assertNotIn('"pre_audit"', _code_only(_read(rel)),
                             "%s 不应再有 pre_audit 环节的定理取用" % rel)


# ----------------------------------------------------------------------
# ⑤ A/B 小样实测暴露的缺陷（2026-10-14 下午，3 题 × 2 轮）
#
# 事故链：`intern-s2-preview` 是推理模型，先吐 "Thinking Process" 再给 JSON。
#   `run_hint_for` 的 query 调用原先 `max_tokens=512` ⇒ 思考块就吃满
#   （日志 `finish_reason=length, max_tokens=512, <- theorem_hint.py:675`）
#   ⇒ `utils/llm_client.py` 对推理模型**优先返回 reasoning_content**
#   ⇒ 调用方拿到被截断的**思考文本** ⇒ 旧解析器按行切分，产出
#   `'Problem Analysis:**'` / `'y) \\mid 0 \\leq x \\leq 19'` 这类碎片
#   ⇒ 检索层把 LLM query **前置**并占配额 ⇒ 碎片挤掉规则 query
#   ⇒ source_scan 在碎片上匹配出 99 条噪声命中全量注入（adopted_ratio=0.0）。
#
# 两条修复：① query 调用 max_tokens 512 → 2048；② 解析加质量闸门
#   `_looks_like_query`，垃圾一律丢弃 ⇒ 返回 [] ⇒ 规则 query 兜底。
# ----------------------------------------------------------------------

# 小样里 trace 原文中的真实垃圾输入（回归夹具，勿改）
_SMOKE_THINKING = (
    "Thinking Process:\n\n"
    "1.  **Analyze the Request:**\n"
    "    *   Problem Analysis:**\n"
    "    *   The problem asks for the number of permutations of a set $S = \\{(x\n"
    "    *   y) \\mid 0 \\leq x \\leq 19"
)


class QueryGateTest(unittest.TestCase):
    """⑤-1 解析闸门：垃圾 query 必须被丢弃（宁缺毋滥）。"""

    def test_smoke_garbage_rejected(self):
        """小样真实垃圾输入 ⇒ 空列表（让规则 query 兜底）。"""
        from agent.theorem_hint import parse_llm_queries
        self.assertEqual(parse_llm_queries(_SMOKE_THINKING), [])

    def test_reasoning_narration_rejected(self):
        """思考叙述句式（纯英文词，字符检查拦不住）必须被识别并拒绝。"""
        from agent.theorem_hint import parse_llm_queries
        for junk in (
            "The problem asks for the number",
            "We need to determine the count carefully",
            "Let us consider the structure of the graph",
            "**Requirements:**",
            "y) \\mid 0 \\leq x \\leq 19",
            "题目分析：这是一个组合计数问题",
        ):
            self.assertEqual(parse_llm_queries(junk), [],
                             "垃圾 query 未被拒绝: %r" % junk)

    def test_legit_queries_survive(self):
        """合规 query（JSON / 裸行 / 带序号）不得被闸门误杀。"""
        from agent.theorem_hint import parse_llm_queries
        cases = {
            '["prime number infinitely many", "Euclid proof"]':
                ["prime number infinitely many", "Euclid proof"],
            "prime number infinite\nEuclid theorem":
                ["prime number infinite", "Euclid theorem"],
            "1. graph coloring chromatic\n2. Ramsey theorem":
                ["graph coloring chromatic", "Ramsey theorem"],
            "permutation count cycle index":
                ["permutation count cycle index"],
        }
        for raw, want in cases.items():
            self.assertEqual(parse_llm_queries(raw), want,
                             "合规 query 被误杀: %r" % raw)

    def test_gate_used_on_both_paths(self):
        """闸门必须同时作用于 JSON 路径与降级路径（思考文本里也有 `[...]`）。"""
        import agent.theorem_hint as th
        src = inspect.getsource(th.parse_llm_queries)
        self.assertGreaterEqual(
            src.count("_looks_like_query"), 2,
            "闸门只作用于一条路径（JSON 路径也要过滤）")

    def test_max_tokens_raised_for_reasoning_model(self):
        """query 调用必须给推理模型留足思考空间（512 会被截断在思考块内）。"""
        import agent.theorem_hint as th
        src = inspect.getsource(th.run_hint_for)
        mt = [int(x) for x in re.findall(r"\]\s*,\s*0\.2\s*,\s*(\d+)\)", src)]
        self.assertTrue(mt, "未找到 query 调用的 max_tokens")
        self.assertGreaterEqual(min(mt), 2048,
                                "query 调用 max_tokens 退化到 %r（推理模型会被截断）"
                                % (mt,))


if __name__ == "__main__":
    sys.exit(unittest.main())
