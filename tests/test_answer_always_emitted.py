# -*- coding: utf-8 -*-
"""「无论超没超时都要把答案生成出来」——回归测试。

背景（2026-09-13 晚，4 题实测复盘）
----------------------------------
010/016 两题的最终答案是字符串 ``[生成失败] 调用受限或模型拒绝回答``。
根因不是"超时"本身，而是超时之后**占位符被一层层放行成最终答案**：

  ① ``solver._generate_initial`` 在候选生成失败时 append 一个
     ``reasoning="[生成失败] 调用受限或模型拒绝回答"`` 的占位候选
     ⇒ ``ctx.candidates`` 非空 ⇒ orchestrator 的"无候选 → 兜底直接求解"
     分支（``orchestrator.py`` 的 ``if not ctx.candidates``）永远不触发；
  ② ``formatter._REFUSAL_RE`` 旧版不含「生成失败/调用受限/拒绝回答」
     ⇒ 占位文本被当成合法答案，直接写入 ``final_response``；
  ③ ``user_agent._validate_output`` 只查"非空" ⇒ 占位符原样返回给平台。

同时 ``utils/llm_client.py`` 的超时**重试**让单次故障成本高达
``180s × 2 + 退避 ≈ 365s``（实测 5/5 全败），正是烧穿单题预算的元凶。

本文件把这些不变量钉住。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

# 真实运行里出现过的占位符（勿改，这是回归锚点）
PLACEHOLDER = "[生成失败] 调用受限或模型拒绝回答"


class TestPlaceholderIsRecognized(unittest.TestCase):
    """占位符必须被**三处**判据同时识别为"不可用答案"。"""

    def test_three_copies_of_regex_agree(self) -> None:
        from agent.formatter import _MISSING_ANSWER_RE
        from agent.orchestrator import _DEGRADED_ANSWER_RE
        from user_agent import ReasoningAgent

        for name, rx in (
            ("formatter._MISSING_ANSWER_RE", _MISSING_ANSWER_RE),
            ("orchestrator._DEGRADED_ANSWER_RE", _DEGRADED_ANSWER_RE),
            ("user_agent.ReasoningAgent._DEGRADED_ANSWER_RE",
             ReasoningAgent._DEGRADED_ANSWER_RE),
        ):
            with self.subTest(rx=name):
                self.assertRegex(PLACEHOLDER, rx)
                # 「未给出有效解答」是 user_agent 写的终极终态，也要认
                self.assertRegex("未给出有效解答。", rx)
                # ⚠ 窄口径：`无解` / `暂无` 是**合法答案**，绝不能被判为"无答案"
                # （独立验证者实测：`无解` 被误判 ⇒ 正确答案被直答覆盖成 '7'）
                self.assertIsNone(rx.search("无解"), "误判合法答案「无解」")
                self.assertIsNone(rx.search("暂无"), "误判合法答案「暂无」")

    def test_real_answers_are_not_flagged(self) -> None:
        """正常答案（数值/表达式/选项字母）绝不能被误判为拒绝语。"""
        from agent.formatter import _REFUSAL_RE
        from agent.orchestrator import _DEGRADED_ANSWER_RE

        for good in ("20460", "2", "21", r"\boxed{20971520}", "A",
                     "x^2+2x-1", r"\frac{1}{2}", "{1,2,3}", "0"):
            for rx in (_REFUSAL_RE, _DEGRADED_ANSWER_RE):
                self.assertIsNone(rx.search(good), "误判正常答案: %r" % good)

    def test_is_degraded_answer(self) -> None:
        from user_agent import ReasoningAgent
        f = ReasoningAgent._is_degraded_answer
        self.assertTrue(f(""))
        self.assertTrue(f("   "))
        self.assertTrue(f(None))
        self.assertTrue(f(PLACEHOLDER))
        self.assertFalse(f("20460"))
        self.assertFalse(f("A"))


class TestHasUsableCandidate(unittest.TestCase):
    """orchestrator 的兜底判据必须能看穿占位候选。"""

    def _ctx(self, cands):
        return SimpleNamespace(candidates=list(cands))

    @staticmethod
    def _call(ctx):
        from agent.orchestrator import Orchestrator
        # 该方法只用到 ctx 与模块级正则，用一个哑 self 直接调用即可
        return Orchestrator._has_usable_candidate(object(), ctx)

    def test_empty_pool_is_not_usable(self) -> None:
        self.assertFalse(self._call(self._ctx([])))

    def test_only_placeholder_is_not_usable(self) -> None:
        """**核心回归**：池子里全是占位候选 ⇒ 必须判为"无可用候选"，
        从而触发 orchestrator 的兜底直接求解（旧实现会在这里返回 True）。"""
        ctx = self._ctx([
            SimpleNamespace(answer="", reasoning=PLACEHOLDER),
            SimpleNamespace(answer="", reasoning=PLACEHOLDER),
        ])
        self.assertFalse(self._call(ctx))

    def test_real_answer_is_usable(self) -> None:
        ctx = self._ctx([SimpleNamespace(answer="20460", reasoning="推导…")])
        self.assertTrue(self._call(ctx))

    def test_empty_answer_but_usable_reasoning_is_usable(self) -> None:
        """formatter 会用 reasoning 尾部当答案 ⇒ 这类候选不能判死。"""
        ctx = self._ctx([SimpleNamespace(answer="", reasoning="所以最终结果是 20460")])
        self.assertTrue(self._call(ctx))

    def test_only_empty_is_not_usable(self) -> None:
        ctx = self._ctx([SimpleNamespace(answer="", reasoning="")])
        self.assertFalse(self._call(ctx))


class TestTimeoutIsNotRetried(unittest.TestCase):
    """超时默认不重试（359s → 120s 的关键）。"""

    def _client(self, max_retries=1):
        from utils.llm_client import LLMClient
        return LLMClient(api_key="k", base_url="http://example.invalid/v1",
                         model="m", timeout=5, max_retries=max_retries)

    def test_timeout_posts_once(self) -> None:
        sleeps = []
        with patch("utils.llm_client.requests.post",
                   side_effect=requests.exceptions.Timeout("read timeout")) as post, \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append):
            c = self._client(max_retries=1)
            with self.assertRaises(Exception) as cm:
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_count, 1, "超时应只发 1 次请求")
        self.assertEqual(sleeps, [], "超时不应有任何退避等待")
        self.assertIn("after 1 attempt", str(cm.exception))

    def test_retry_on_timeout_can_be_reenabled(self) -> None:
        import utils.llm_client as lc
        sleeps = []
        with patch.object(lc, "_RETRY_ON_TIMEOUT", True), \
             patch("utils.llm_client.requests.post",
                   side_effect=requests.exceptions.Timeout("t")) as post, \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            c = self._client(max_retries=1)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_count, 2, "开回退开关后应恢复 2 次尝试")
        self.assertEqual(len(sleeps), 1)

    def test_non_timeout_errors_still_retry(self) -> None:
        """HTTP 5xx 等非超时故障**保持**重试（这些失败很快，重试有正收益）。"""
        sleeps = []
        resp = SimpleNamespace(status_code=500, text="internal server error")
        with patch("utils.llm_client.requests.post", return_value=resp) as post, \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            c = self._client(max_retries=2)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_count, 3)
        self.assertEqual(len(sleeps), 2)


class TestPrewarmBudgetGuard(unittest.TestCase):
    """预计算必须有独立预算下限，不能挤掉主生成。"""

    def test_min_remain_constant_is_300(self) -> None:
        from agent import solver as S
        self.assertEqual(S._CALC_PREWARM_MIN_REMAIN, 300.0)

    def test_skipped_when_low_on_time(self) -> None:
        """剩余不足 300s ⇒ 跳过预计算（旧实现只要剩 150s 就跑，实测吃掉 364s）。"""
        import time as _t
        from agent.solver import SolverAgent
        from agent.base import TaskContext

        recorded = []
        agent = object.__new__(SolverAgent)
        agent.config = SimpleNamespace(enable_calc_prewarm=True,
                                       enable_calc_tool=True)
        agent.record = lambda ctx, step, content, **kw: recorded.append(content)

        ctx = TaskContext(problem="计算 comb(50,3) 的值", metadata={})
        ctx.deadline = _t.time() + 200          # 只剩 200s < 300
        ctx._gen_deadline = ctx.deadline - 60
        self.assertFalse(agent._prewarm_applicable(ctx, "standard"))
        self.assertTrue(any("剩余不足" in c for c in recorded), recorded)


class TestRescueFailureDoesNotLeakPlaceholder(unittest.TestCase):
    """**关键回归**（独立验证者抓到的缺口）。

    `solve()` 里原来的顺序是「先 `_validate_output`，再判不可用 → rescue」，
    而 rescue **失败**时只追加 trace、**不替换** `final_response`
    ⇒ 占位符仍然漏给平台。复现条件正是 010/016 的原始现场：
    orchestrator 交出占位答案 **且** 直答也失败（服务端持续超时）。
    """

    @staticmethod
    def _agent(run_result, chat):
        from user_agent import ReasoningAgent
        a = object.__new__(ReasoningAgent)          # 不跑 __init__，只装必需属性
        a.orchestrator = SimpleNamespace(
            run=lambda problem, metadata: dict(run_result))
        a.config = SimpleNamespace(max_answer_tokens=64)
        a.client = SimpleNamespace(chat=chat)
        return a

    @staticmethod
    def _dead_chat(**kwargs):
        raise requests.exceptions.Timeout("simulated dead server")

    def test_placeholder_with_dead_llm_is_replaced(self) -> None:
        """占位符 + 直答超时 ⇒ 必须换成终态文本，绝不能返回占位符。"""
        a = self._agent({"final_response": PLACEHOLDER, "trace": [], "diag": {}},
                        self._dead_chat)
        out = a.solve("求 1+1 的值")
        self.assertNotIn("生成失败", out["final_response"])
        self.assertNotIn("调用受限", out["final_response"])
        self.assertEqual(out["final_response"], "未给出有效解答。")

    def test_rescue_prefers_candidate_residue(self) -> None:
        a = self._agent({
            "final_response": PLACEHOLDER, "trace": [],
            "diag": {"pick_diag": {"cand_answers": [PLACEHOLDER, "20460"]}},
        }, self._dead_chat)
        self.assertEqual(a.solve("求值")["final_response"], "20460")

    def test_rescue_uses_subgoal_result(self) -> None:
        a = self._agent({
            "final_response": PLACEHOLDER, "trace": [],
            "diag": {"subgoal_trace": [{"result": "x = 21"}]},
        }, self._dead_chat)
        self.assertEqual(a.solve("求 x")["final_response"], "x = 21")

    def test_rescue_falls_back_to_direct_solve(self) -> None:
        a = self._agent({"final_response": PLACEHOLDER, "trace": [], "diag": {}},
                        lambda **kw: "【最终答案】: 42")
        self.assertEqual(a.solve("求值")["final_response"], "42")

    def test_good_answer_is_untouched(self) -> None:
        """正常答案绝不能被兜底逻辑改写（零后悔）。"""
        a = self._agent({"final_response": "20460", "trace": [], "diag": {}},
                        self._dead_chat)
        self.assertEqual(a.solve("求值")["final_response"], "20460")

    def test_no_solution_answer_is_untouched(self) -> None:
        """「无解」是合法答案 —— 不得被误判为"没有答案"而覆盖。"""
        a = self._agent({"final_response": "无解", "trace": [], "diag": {}},
                        lambda **kw: "7")
        self.assertEqual(a.solve("求值")["final_response"], "无解")


class TestSubgoalResidueMustLookLikeAnAnswer(unittest.TestCase):
    """**2026-09-14 修复回归**：来源②不得把「子目标中间推导」当答案交出去。

    实况 official112-016 的 `predicted` 逐字等于 `diag.subgoal_trace[1].result`：
        （该步含未用 <calc> 的易错运算结果，未经系统确认）|10 - sqrt(9.9)| < 1
        19.9 + (10 - sqrt(9.9))^2 = 20
    ⇒ 它避开了「生成失败」占位符，却**伪装成答案**（判分同为 0，归因时还会误判成
    "模型答的"，并把系统提示串塞进提交给平台的答案字段）。
    """

    # 真实数据，勿改（回归锚点）
    REAL_016_RESULT = ("（该步含未用 <calc> 的易错运算结果，未经系统确认）"
                       "|10 - sqrt(9.9)| < 1\n19.9 + (10 - sqrt(9.9))^2 = 20")

    def test_real_016_fragment_is_rejected(self) -> None:
        from user_agent import _subgoal_answer_candidate
        self.assertEqual(_subgoal_answer_candidate(self.REAL_016_RESULT), "")

    def test_short_value_is_accepted(self) -> None:
        from user_agent import _subgoal_answer_candidate
        self.assertEqual(_subgoal_answer_candidate("20460"), "20460")
        self.assertEqual(_subgoal_answer_candidate("x = 21"), "x = 21")

    def test_boxed_value_is_accepted(self) -> None:
        from user_agent import _subgoal_answer_candidate
        self.assertEqual(_subgoal_answer_candidate(r"所以 \boxed{21}"), "21")
        # 带提示前缀 + boxed：剥前缀后仍应取出
        self.assertEqual(
            _subgoal_answer_candidate("（该步未经系统确认）\\boxed{21}"), "21")

    def test_multiline_derivation_is_rejected(self) -> None:
        from user_agent import _subgoal_answer_candidate
        self.assertEqual(_subgoal_answer_candidate("a = 1\nb = 2\nc = 3"), "")
        self.assertEqual(_subgoal_answer_candidate(""), "")
        self.assertEqual(_subgoal_answer_candidate(None), "")

    def test_long_single_line_is_rejected(self) -> None:
        from user_agent import _subgoal_answer_candidate
        self.assertEqual(_subgoal_answer_candidate("x" * 120), "")

    def test_rescue_skips_junk_subgoal_and_uses_direct_solve(self) -> None:
        """只有垃圾子目标结果时，应跳过它、走直答，而不是把它当答案。"""
        from user_agent import ReasoningAgent
        a = object.__new__(ReasoningAgent)
        a.orchestrator = SimpleNamespace(run=lambda p, m: {
            "final_response": PLACEHOLDER, "trace": [],
            "diag": {"subgoal_trace": [{"result": self.REAL_016_RESULT}]},
        })
        a.config = SimpleNamespace(max_answer_tokens=64)
        a.client = SimpleNamespace(chat=lambda **kw: "【最终答案】: 21")
        out = a.solve("求值")
        self.assertEqual(out["final_response"], "21")
        self.assertNotIn("未经系统确认", out["final_response"])
