# -*- coding: utf-8 -*-
"""任务列表 #3 回归守卫：题意理解产出单一「题目目标」（2026-10-14）。

用户原话（任务列表 第 3 条）：
  「题意理解…要和蓝图构建**解耦合**，它应该是单纯确定题目需要我们做什么？
    选择题那要选的是那几个选项？有几个正确选项？解答题，要求的是什么东西？
    证明题，要证明的是什么？**给出大模型一个目标**。这个环节的产出是一个目标」

用户本轮口径：「可以适当删除不需要的步骤，**不要全做增量**」
  ⇒ 本任务的做法是**收敛**：原先「理解题意、抽目标」在四处各推一遍，
     删掉其中三处副本，只留 2.6 一处。

本文件守住七件事：
  ① 2.6 末尾构建 `ctx.problem_goal`（唯一目标），且 01_understanding 落盘带它；
  ② 目标含任务原文要求的四要素：题型 / 要做什么 / 待判选项 / 答案口径；
  ③ 渲染块带 K11 标注（答案槽是**假设**，不得当作已证结论）；
  ④ 蓝图与子目标 prompt 的 JSON 契约里**不再有** `problem_analysis`；
  ⑤ `BlueprintDAG` 不再有 `problem_analysis` 字段、不再序列化 / 反序列化它；
  ⑥ 单选 / 多选口径**单一来源**（`problem_goal.is_single_choice`）——
     `sub_goal_solver` 不再保留正则副本，planner 不再自己判；
  ⑦ 题意理解不再保留「无条件复推轮数」开关（★ 2026-10-14 收敛：复推已删，
     配套开关 `understanding_refine_rounds` 等一并撤除，四处同步）。

★ 为什么用静态文本守卫 + 直调纯函数：`Orchestrator.run` 全链路依赖 LLM / Lean /
  网络，跑不动；「改了 A 忘了 B」这类错位用静态扫描最有效（沿用
  tests/test_orchestrator_static.py / test_type_understanding_merged_1014.py 风格）。
"""

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _code_only(src: str) -> str:
    """剔除**文档字符串 + 整行注释**后的代码正文。

    用于「某机制不得再有活引用」类断言：允许 docstring / 注释里刻意保留的留痕
    （"已撤除"的说明常点名被删符号，属有意留痕），只禁**代码正文**再引用。
    ★ 教训：守卫曾把 docstring 里的留痕当活引用而误判红 —— 见
      任务 #2 的同名 `_code_only`（tests/test_theorem_hint_moved_1014.py）。
    """
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))


try:
    from agent import problem_goal as PG
    _IMPORT_ERR = ""
except Exception as _e:  # noqa: BLE001  依赖缺失时跳过（纯静态守卫仍可跑）
    PG = None
    _IMPORT_ERR = str(_e)


class _Ctx:
    """TaskContext 最小桩：只放目标构建真正会读的字段。"""

    def __init__(self, problem="", qtype="", uc=None, tp=None):
        self.problem = problem
        self.question_type = qtype
        if uc is not None:
            self.understanding_chain = uc
        if tp is not None:
            self.type_path = tp


@unittest.skipIf(PG is None, f"agent.problem_goal 不可导入: {_IMPORT_ERR}")
class ProblemGoalBuildTest(unittest.TestCase):
    """① ② 目标构建：四要素齐备，且是**派生**（零 LLM）。"""

    def test_choice_goal_carries_options_and_coverage(self):
        """选择题：必须带「要判哪几个选项」（任务原文点名的要素之一）。"""
        ctx = _Ctx("下列各说法中正确的有（ ）A. 甲说法 B. 乙说法 C. 丙说法 D. 丁说法",
                   "选择题")
        g = PG.build_problem_goal(ctx)
        self.assertEqual(g["question_type"], "选择题")
        self.assertEqual(len(g["options"]), 4)
        self.assertEqual([o["label"] for o in g["options"]], ["A", "B", "C", "D"])
        self.assertIn("选项", g["task"])
        self.assertEqual(g["answer_form"], "option")

    def test_choice_n_correct_single_vs_all(self):
        """答案口径：单选措辞 → single；多选措辞 → all；都不命中 → unknown（不猜）。"""
        self.assertEqual(
            PG.build_problem_goal(_Ctx("下列哪一项是正确做法（ ）", "选择题"))["n_correct"],
            "single")
        self.assertEqual(
            PG.build_problem_goal(_Ctx("下列选项中正确的有（ ）", "选择题"))["n_correct"],
            "all")
        self.assertEqual(
            PG.build_problem_goal(_Ctx("下列选项中正确的是（ ）", "选择题"))["n_correct"],
            "unknown")

    def test_proof_goal_is_about_proof_not_value(self):
        """证明题：目标是「证明什么」，**不得**被要求给具体值（答案形态=proof）。"""
        g = PG.build_problem_goal(_Ctx("证明：对任意整数 n，n²-n 是偶数。", "证明题"))
        self.assertIn("证明", g["task"])
        self.assertEqual(g["answer_form"], "proof")
        self.assertEqual(g["options"], [])

    def test_solution_goal_and_terminal_state(self):
        """解答题：带「目标情形」（理解链终态）；无链时该字段为空。"""
        g1 = PG.build_problem_goal(_Ctx("求所有满足条件的正整数 n。", "解答题"))
        self.assertEqual(g1["terminal_state"], "")
        g2 = PG.build_problem_goal(_Ctx(
            "求所有满足条件的正整数 n。", "解答题",
            uc={"terminal_state": "把所有满足条件的 n 列出来", "answer_slot": "N"}))
        self.assertEqual(g2["terminal_state"], "把所有满足条件的 n 列出来")
        self.assertEqual(g2["answer_slot"], "N")
        self.assertIn("目标情形", g2["goal_statement"])

    def test_goal_is_derived_not_llm(self):
        """目标必须是**派生**产物：构建过程不得触发任何 LLM 调用。"""
        calls = []

        class _Boom:
            def __call__(self, *a, **k):
                calls.append(a)
                raise AssertionError("目标构建不得调用 LLM")

        ctx = _Ctx("证明：1+1=2。", "证明题")
        ctx.llm = _Boom()
        PG.build_problem_goal(ctx)
        self.assertEqual(calls, [])
        self.assertEqual(PG.build_problem_goal(ctx)["source"], "derived")

    def test_unknown_type_degrades_gracefully(self):
        """题型未识别 ⇒ 任务句兜底、不抛异常（不因目标构建阻断主链）。"""
        g = PG.build_problem_goal(_Ctx("随便一句话", ""))
        self.assertEqual(g["question_type"], "")
        self.assertTrue(g["task"])
        self.assertEqual(g["options"], [])


@unittest.skipIf(PG is None, f"agent.problem_goal 不可导入: {_IMPORT_ERR}")
class RenderTest(unittest.TestCase):
    """③ 渲染块：可注入提示词、且守 K11 红线。"""

    def test_render_marks_answer_slot_as_hypothesis(self):
        ctx = _Ctx("证明：n²-n 是偶数。", "证明题",
                   uc={"terminal_state": "结论成立", "answer_slot": "证明"})
        ctx.problem_goal = PG.build_problem_goal(ctx)
        txt = PG.render_problem_goal(ctx)
        self.assertIn("题目目标", txt)
        self.assertIn("假设", txt)
        self.assertIn("不得当作已证结论", txt)

    def test_render_hides_unknown_coverage(self):
        """口径未识别（unknown）时不显示，避免给模型一个无意义的标签。"""
        ctx = _Ctx("下列选项中正确的是（ ）A. 甲 B. 乙 C. 丙", "选择题")
        ctx.problem_goal = PG.build_problem_goal(ctx)
        self.assertNotIn("unknown", PG.render_problem_goal(ctx))

    def test_render_empty_without_goal(self):
        """无目标 ⇒ 空串（下游零成本，与接线前一致）。"""
        self.assertEqual(PG.render_problem_goal(_Ctx("题", "")), "")
        ctx = _Ctx("题", "")
        ctx.problem_goal = {}
        self.assertEqual(PG.render_problem_goal(ctx), "")


@unittest.skipIf(PG is None, f"agent.problem_goal 不可导入: {_IMPORT_ERR}")
class SingleChoiceSingleSourceTest(unittest.TestCase):
    """⑥ 单选口径单一来源。"""

    def test_reads_goal_first_then_falls_back(self):
        ctx = _Ctx("下列哪一项正确（ ）", "选择题")
        ctx.problem_goal = {"n_correct": "all"}        # 2.6 的结论优先
        self.assertFalse(PG.is_single_choice(ctx))
        ctx.problem_goal = {"n_correct": "single"}
        self.assertTrue(PG.is_single_choice(ctx))
        # 无 goal（未接线 / 老 ctx）⇒ 回退题面正则，与接线前行为一致
        self.assertTrue(PG.is_single_choice(_Ctx("下列哪一项正确（ ）", "选择题")))

    def test_solver_no_longer_keeps_regex_copy(self):
        src = _read("agent/sub_goal_solver.py")
        self.assertNotIn("_SINGLE_CHOICE_RE = re.compile", src,
                         "单选正则必须只在 problem_goal.py 保留一份")
        self.assertIn("problem_goal", src)

    def test_planner_does_not_judge_by_itself(self):
        src = _read("agent/sub_goal_solver__planner.py")
        self.assertNotIn("_SINGLE_CHOICE_RE", src,
                         "2.7 规划不得再自判单选/多选")
        self.assertIn("is_single_choice", src)


class PromptContractTest(unittest.TestCase):
    """④ 两处 LLM 契约里不再有 problem_analysis（题意理解不再各推一遍）。"""

    def test_blueprint_prompt_dropped_problem_analysis(self):
        src = _read("prompts/blueprint.py")
        self.assertNotIn("problem_analysis", src,
                         "蓝图契约不得再要求模型产出 problem_analysis")

    def test_subgoal_prompt_dropped_problem_analysis(self):
        src = _read("prompts/sub_goal.py")
        self.assertNotIn("problem_analysis", src,
                         "子目标规划契约不得再要求模型产出 problem_analysis")


class BlueprintDagDroppedFieldTest(unittest.TestCase):
    """⑤ BlueprintDAG 不再携带 problem_analysis（含序列化双端）。"""

    def test_no_field_no_serialisation(self):
        src = _read("agent/blueprint_planner__dag.py")
        # 只查「活的引用」模式；注释 / docstring 里的留痕说明不算
        for pat in ('"problem_analysis"', "'problem_analysis'",
                    "problem_analysis=", ".problem_analysis",
                    "problem_analysis:"):
            self.assertNotIn(pat, src, f"代码正文仍引用 {pat}（仅允许注释留痕）")

    def test_dag_serialise_roundtrip(self):
        try:
            from agent.blueprint_planner__dag import BlueprintDAG
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"BlueprintDAG 不可导入: {e}")
        d = BlueprintDAG(nodes={}, root_id="g", merge_strategy="夹逼")
        self.assertEqual(set(d.to_dict().keys()), {"root_id", "merge_strategy", "nodes"})
        self.assertEqual(set(d.to_subgoal_plan(6).keys()),
                         {"subgoals", "merge_strategy", "anticipatory_lemmas"})
        # 老 jsonl（带 problem_analysis）反序列化不得报错（容忍并忽略该字段）
        old = {"root_id": "g", "merge_strategy": "x",
               "problem_analysis": {"domain": "代数"}, "nodes": []}
        back = BlueprintDAG.from_dict(old)
        self.assertEqual(back.root_id, "g")
        self.assertFalse(hasattr(back, "problem_analysis"))


class StageWiringTest(unittest.TestCase):
    """① 2.6 接线：构建目标、落盘进 01_understanding、且在三类题上都不阻断。"""

    def test_pre_audit_builds_goal(self):
        src = _read("agent/orchestrator__prep.py")
        self.assertIn("build_problem_goal", src)
        self.assertIn('"problem_goal": dict(ctx.problem_goal or {})', src)
        # 必须在 2.6 段内（pre_audit_stage）且被 try 包裹（判题/目标都不得阻断主链）
        seg = src[src.index("def pre_audit_stage"):]
        self.assertIn("build_problem_goal", seg)

    def test_ctx_and_protocol_declare_field(self):
        self.assertIn("problem_goal: dict", _read("agent/base__types.py"))
        self.assertIn("problem_goal: dict", _read("contracts/protocols.py"))


class UnderstandingRoundsRetiredTest(unittest.TestCase):
    """⑦ ★ 2026-10-14 收敛：复推已删 ⇒ 三个配套开关必须**四处同步撤除**。

    只看**活引用**（带引号 / 冒号的代码形态），放过注释里刻意保留的留痕
    （"已撤除"的说明会点名开关，属有意留痕，不得据此判红）。
    """

    _RETIRED = ("understanding_refine_rounds",
                "understanding_no_gain_stop",
                "understanding_chain_lean_check")

    def test_switches_removed_everywhere(self):
        places = {
            "① 注册表": _read("contracts/switch_registry.py"),
            "② 配置字段": _read("user_agent__config.py"),
            "③ 覆盖白名单": _read("user_agent.py"),
            "④ 参数用量表": _read("agent/param_usage.py"),
        }
        for name in self._RETIRED:
            for place, src in places.items():
                for pat in ('"%s"' % name, "%s:" % name):
                    self.assertNotIn(
                        pat, src,
                        "开关 %s 仍以活引用形态留在 %s（应四处同步撤除）"
                        % (name, place))

    def test_no_refine_machinery_in_pre_verifier(self):
        # ★ 只看代码正文（docstring 里刻意保留的"已删 X"留痕不算活引用）
        lv = _code_only(_read("tools/lean_local/lean_pre_verifier.py"))
        for dead in ("_canonical_chain", "UNDERSTANDING_REFINE_USER",
                     "_understanding_lean_check",
                     "_understanding_make_lean_code"):
            self.assertNotIn(dead, lv, "题意理解收敛后不应再有 %s" % dead)
        # 三个开关名：代码里应以 `getattr(cfg, "xxx"` 形态消失（留痕不算）
        for name in self._RETIRED:
            self.assertNotIn('%s"' % name, lv,
                             "lean_pre_verifier 仍以活引用形态引用开关 %s" % name)


if __name__ == "__main__":
    sys.exit(unittest.main())
