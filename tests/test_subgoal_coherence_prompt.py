# -*- coding: utf-8 -*-
"""
子目标 / 蓝图提示词的**衔接设计**回归测试（2026-09-15）
=========================================================

背景：李平老师 0915 16:53 提出三条判断——
  ① 关注子目标的数量；
  ② 子目标需要一定**冗余**以保证上下文衔接；
  ③ 逻辑推理的"断 / 跳"现象与**衔接**相关；
  ④ 提示词要补充强调子目标之间的**语义衔接**。

本测试锁定提示词层面的改造，防止回退到"时间墙版"的极简主义。

⚠ 为什么值得锁：改前的 `SUBGOAL_PLAN_SYSTEM` 有三条准则与老师意图**直接相反**，
且都是时间墙产物——
  - 准则 2「独立性优先…上下文最小」
  - 准则 3「砍传递节点」
  - 准则 5「子目标数宜少不宜多：4-5 个优于 6 个」
若哪天有人以"精简"为由改回去，本测试会失败。
"""
import unittest


class TestSubgoalPlanCoherence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prompts.sub_goal import SUBGOAL_PLAN_SYSTEM
        cls.P = SUBGOAL_PLAN_SYSTEM

    # ---- 新增的衔接准则 ----

    def test_explicit_coherence_rule(self):
        """★ 核心：必须有「显式衔接」准则。"""
        self.assertIn("显式衔接", self.P)

    def test_symbol_closure_rule(self):
        """符号封闭：不得引入未定义对象。"""
        self.assertIn("符号封闭", self.P)

    def test_forbids_step_skipping(self):
        self.assertIn("禁止跳步", self.P)

    def test_forbids_broken_chain(self):
        self.assertIn("禁止断链", self.P)

    def test_allows_carry_over_redundancy(self):
        """★ 承接冗余是**刻意允许**的（与旧的"上下文最小"相反）。"""
        self.assertIn("承接冗余", self.P)

    def test_pass_through_node_kept_when_linking(self):
        """传递节点若承担衔接作用则保留（旧版是"砍传递节点"）。"""
        self.assertIn("衔接载体", self.P)
        self.assertNotIn("砍传递节点", self.P)

    # ---- 数量放开 ----

    def test_complexity_tiered_count(self):
        """数量按复杂度分档（旧版是固定 2-6 + "宜少不宜多"）。"""
        self.assertIn("简单题", self.P)
        self.assertIn("难题", self.P)

    def test_no_more_minimalism_rule(self):
        """★ 旧的"子目标数宜少不宜多"必须已删除。"""
        self.assertNotIn("宜少不宜多", self.P)

    def test_no_fixed_2_to_6(self):
        self.assertNotIn("拆解为 2-6 个", self.P)

    # ---- 时间墙理由清除 ----

    def test_no_time_wall_rationale(self):
        """时间墙理由（"越快/越慢"）不得残留。"""
        self.assertNotIn("精简即提速", self.P)
        self.assertNotIn("越慢", self.P)

    # ---- 防冗余条款仍在（与衔接不冲突） ----

    def test_still_forbids_verbatim_problem_copy(self):
        """必须仍禁止**整段**复述题干（否则会退化成抄题）。"""
        self.assertIn("禁止整段复述题干", self.P)

    def test_permits_short_reference_to_givens(self):
        """但允许简短指代题设（衔接必需）。"""
        self.assertIn("允许", self.P)
        self.assertIn("题设", self.P)

    # ---- 输出契约 ----

    def test_carry_over_shown_in_json_example(self):
        self.assertIn("承接语开头", self.P)

    def test_final_subgoal_required(self):
        self.assertIn("收尾子目标", self.P)


class TestSubgoalStepCoherence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prompts.sub_goal import SUBGOAL_STEP_SYSTEM
        cls.S = SUBGOAL_STEP_SYSTEM

    def test_must_open_with_carry_over(self):
        """★ 每步必须先写承接语。"""
        self.assertIn("先写承接语", self.S)

    def test_forbids_step_skipping(self):
        self.assertIn("不得跳步", self.S)

    def test_forbids_undefined_symbols(self):
        self.assertIn("未定义的符号", self.S)

    def test_word_limit_relaxed_for_coherence(self):
        """上限放宽（200 → 300 字），给承接语留空间。"""
        self.assertIn("300 字", self.S)
        self.assertNotIn("≤ 200 字", self.S)

    def test_carry_over_not_counted_as_verbatim(self):
        """承接语不应被当作"复述题目"。"""
        self.assertIn("不算", self.S)


class TestBlueprintCoherence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prompts.blueprint import BLUEPRINT_DAG_SYSTEM
        cls.B = BLUEPRINT_DAG_SYSTEM

    def test_node_coherence_rule(self):
        self.assertIn("节点间衔接", self.B)

    def test_symbol_closure(self):
        self.assertIn("符号封闭", self.B)

    def test_forbids_step_skipping(self):
        self.assertIn("禁止跳步", self.B)

    def test_cites_teacher_reason(self):
        """保留依据出处，便于以后判断该条款还要不要。"""
        self.assertIn("李平", self.B)


class TestDagReviewerCoherenceDimension(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prompts.dag_review import DAG_REVIEW_SYSTEM
        cls.R = DAG_REVIEW_SYSTEM

    def test_coherence_dimension_present(self):
        self.assertIn("衔接与符号封闭", self.R)

    def test_rejects_undefined_symbols(self):
        self.assertIn("没定义过", self.R)

    def test_rejects_broken_chain(self):
        self.assertIn("跳步", self.R)

    def test_carry_over_is_not_redundancy(self):
        """★ 正常承接**不算**冗余——防止评审器把衔接误判为啰嗦。"""
        self.assertIn("不算", self.R)


if __name__ == "__main__":
    unittest.main()
