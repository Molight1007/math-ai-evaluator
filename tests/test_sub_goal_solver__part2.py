# -*- coding: utf-8 -*-
"""子目标求解智能体（SubGoalSolverAgent）单元测试 · 第 2 部分（2026-10-09 拆分 批6-3）。

由 `tests/test_sub_goal_solver.py` **逐字切出**（仅移动、不删用例）。覆盖：
  · ``_solve_subgoal`` 的 extra_hint 回灌（S1-lite 校验反馈）
  · DAG 重规划门控（replan gate）
  · merge 自旋重试
  · 多子目标并发与答案汇总
  · ``<check>`` 结论协议守卫

共享辅助 ``make_agent`` / ``make_ctx`` / ``_ctx`` 从第 1 部分
（`tests/test_sub_goal_solver.py`）原样 import，避免重复定义。
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.sub_goal_solver import SubGoalSolverAgent
from agent.blueprint_planner import BlueprintDAG, BlueprintNode

from test_sub_goal_solver import _ctx, make_agent, make_ctx

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
        # ★ 2026-10-04 修断言（配合 K11 注入点守卫 D8）：蓝图根结论仍被注入，
        #   但其中**被断言的数值**会被掩为占位符
        #   （`证明最终答案为 42` → `证明最终[待求解值：由子目标结果现场确定]`）。
        #   原断言锁的是"未掩码的原样注入"，而那正是 K11（唯一过半根因）的注入通道，
        #   所以改断言为：① 蓝图结论**确实被注入**（保留原文前缀）；
        #   ② 断言数值**必须已被掩掉**（新增，正向锁住修复本身）。
        self.assertIn("证明最终", first_user)
        self.assertIn("待求解值", first_user)
        self.assertNotIn("答案为 42", first_user)

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


# ======================================================================
# 多 agent 子目标求解（2026-09-30，截图 #8）
# ----------------------------------------------------------------------
# 用户原话：
# > 子目标……多 agent 拿子目标的求解能不能换成多 agent？
# > 那样是不是能提高子目标的正确率？
#
# 本组测试锁三件事（都不依赖网络/LLM）：
#   ① `_pick_consensus_sample` 的选择规则**正确**（选错只会放大错误）；
#   ② `_multi_agent_n` 的三道闸门**都真的会退回 1**（成本失控防线）；
#   ③ 默认配置下行为与改动前**逐字一致**（A/B 的 baseline 必须干净）。
# ======================================================================
class SubgoalMultiAgentTest(unittest.TestCase):

    # ---------- ① 选择规则 ----------
    def test_majority_key_wins(self):
        """多数一致 → 取多数派（self-consistency 的核心）。"""
        got, key, nd = SubGoalSolverAgent._pick_consensus_sample(
            ["答案是 42", "答案是 42", "答案是 7"])
        self.assertEqual(got, "答案是 42")
        self.assertEqual(nd, 2)

    def test_all_distinct_takes_longest(self):
        """全不同 → 取最长（短的多半是敷衍/未完成）。"""
        got, _key, nd = SubGoalSolverAgent._pick_consensus_sample(
            ["短", "中等长度", "这是最长的一个答案内容"])
        self.assertEqual(got, "这是最长的一个答案内容")
        self.assertEqual(nd, 3)

    def test_boxed_takes_priority_for_key(self):
        """关键值优先取 \\boxed{} —— 与判分口径一致，避免拿到散文尾巴。"""
        _got, key, nd = SubGoalSolverAgent._pick_consensus_sample(
            ["\\boxed{42} 一段推导", "\\boxed{42}", "\\boxed{7}"])
        self.assertEqual(key, "42")
        self.assertEqual(nd, 2)

    def test_whitespace_differences_normalize_to_same_key(self):
        """`a = 1 + 2` 与 `a=1+2` 必须视为同一结论，否则一致性永远达不成。"""
        _got, key, nd = SubGoalSolverAgent._pick_consensus_sample(
            ["a = 1 + 2", "a=1+2"])
        self.assertEqual(key, "a=1+2")
        self.assertEqual(nd, 1)

    def test_all_empty_returns_none_not_fake_success(self):
        """★ 全部为空/失败 ⇒ 返回 None，让上层走失败分支，**绝不伪造成功**。"""
        got, key, nd = SubGoalSolverAgent._pick_consensus_sample([None, "", "   "])
        self.assertIsNone(got)
        self.assertEqual(nd, 0)
        got2, _k2, nd2 = SubGoalSolverAgent._pick_consensus_sample([])
        self.assertIsNone(got2)
        self.assertEqual(nd2, 0)

    def test_tie_prefers_longer_reasoning(self):
        """平票时取更长的原文（推理更完整）。"""
        short = "\\boxed{5}"
        long = "\\boxed{5}" + " 补充推导过程" * 10
        got, _key, nd = SubGoalSolverAgent._pick_consensus_sample([short, long])
        self.assertEqual(got, long)
        self.assertEqual(nd, 1)

    def test_positive_control_would_catch_wrong_pick(self):
        """★ 阳性对照：若选择规则退化成"取第一个"，本断言应红。"""
        got, _k, _n = SubGoalSolverAgent._pick_consensus_sample(
            ["少数派结论", "多数派 A", "多数派 A"])
        self.assertNotEqual(got, "少数派结论")
        self.assertEqual(got, "多数派 A")

    # ---------- ② 三道闸门 ----------
    def _solver(self, **cfg):
        base = dict(enable_subgoal_multi_agent=True, subgoal_agents_n=3)
        base.update(cfg)
        return SubGoalSolverAgent(client=MagicMock(),
                                  config=SimpleNamespace(**base))

    def test_switch_off_returns_one(self):
        s = SubGoalSolverAgent(client=MagicMock(), config=SimpleNamespace(
            enable_subgoal_multi_agent=False, subgoal_agents_n=3))
        self.assertEqual(s._multi_agent_n(_ctx()), 1)

    def test_default_config_is_off(self):
        """★ 默认必须是关的 —— 否则 baseline 不干净，A/B 无从比较。"""
        cfg = SimpleNamespace()   # 完全不配这两个键
        s = SubGoalSolverAgent(client=MagicMock(), config=cfg)
        self.assertEqual(s._multi_agent_n(_ctx()), 1)

    def test_enabled_returns_n(self):
        s = self._solver()
        self.assertEqual(s._multi_agent_n(_ctx()), 3)

    def test_time_critical_falls_back_to_one(self):
        """★ 时间紧迫 ⇒ 退回 1，避免生成侧吃光预算把验证饿死。"""
        s = self._solver()
        c = _ctx()
        c.deadline = time.time() - 10      # 已过截止
        self.assertEqual(s._multi_agent_n(c), 1)

    def test_insufficient_budget_falls_back_to_one(self):
        """★ 剩余调用数不足 N ⇒ 退回 1。"""
        s = self._solver(subgoal_agents_n=5)
        c = _ctx(max_calls=2)
        self.assertEqual(s._multi_agent_n(c), 1)

    def test_n_is_clamped_to_sane_range(self):
        """配置写错（0 / 负数 / 超大）不得把预算打爆。"""
        self.assertEqual(self._solver(subgoal_agents_n=0)._multi_agent_n(_ctx()), 1)
        self.assertEqual(self._solver(subgoal_agents_n=-5)._multi_agent_n(_ctx()), 1)
        self.assertEqual(self._solver(subgoal_agents_n=999)._multi_agent_n(_ctx()), 8)


class CheckProtocolGuardTest(unittest.TestCase):
    """问题 2.9：`<check>` **协议守卫**（判据 + 违反提取）。

    依据（smoke10 2026-10-06 实测）：题 000 大量把**中文句子**塞进 `<check>`
    （`<check>图 G 是弱连通的</check>` 出现 6 次、`<check>若 a(x)=a(y) 则 x=y</check>`
    6 次）⇒ `is_parseable=False` ⇒ 全部 10 题 `n_judged = 0/73`。守卫须：
      ① 中文/非等式 ⇒ 判"违反"；② 合法纯等式（含 `|D_8| = 8` 这类阶记号，实测 8 次）
         不得假阳（初版字符类漏 `|` 已修正）。
    """

    def test_verifiable_bodies_pass(self):
        from agent.sub_goal_solver import _is_verifiable_check_body as f
        # 全部取自 smoke10 实测合法 `<check>` 内容 + 幂等回归（`|D_8| = 8`）
        for b in ["2^60 * 3^40 = 2^60 * 3^40", "T(m) = -4", "a^2 = a",
                  "c^2 = c + 1", "A(0)^2 = A(0) + 1", "L = D_out - A",
                  "floor(2025/2) = 1012", "1 = 1", "bc = -b", "|D_8| = 8",
                  "(a, b) = (1, 2)", "n! = 120"]:
            self.assertTrue(f(b), b)

    def test_cjk_and_non_equality_flagged(self):
        from agent.sub_goal_solver import _is_verifiable_check_body as f
        for b in ["图 G 是弱连通的", "若 a(x)=a(y) 则 x=y", "EXHAUSTIVE: no",
                  "", "x = 5 = 6", "所求即最小值"]:
            self.assertFalse(f(b), b)

    def test_violations_extracted_only_illegal(self):
        from agent.sub_goal_solver import _check_protocol_violations as cv
        txt = ("结论。\n<check>图 G 是弱连通的</check>\n<check>T(m) = -4</check>\n"
               "<check>若 a(x)=a(y) 则 x=y</check>")
        self.assertEqual(cv(txt), ["图 G 是弱连通的", "若 a(x)=a(y) 则 x=y"])

    def test_no_check_returns_empty(self):
        from agent.sub_goal_solver import _check_protocol_violations as cv
        self.assertEqual(cv("没有断言"), [])
        self.assertEqual(cv(""), [])
        self.assertEqual(cv(None), [])


if __name__ == "__main__":
    unittest.main()
