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

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

# 真实运行里出现过的占位符（勿改，这是回归锚点）
PLACEHOLDER = "[生成失败] 调用受限或模型拒绝回答"


class TestPlaceholderIsRecognized(unittest.TestCase):
    """占位符必须被**三处**判据同时识别为"不可用答案"。"""

    def test_remaining_copies_of_regex_agree(self) -> None:
        # ★ 2026-10-15：user_agent 那份 `_DEGRADED_ANSWER_RE` 已随降级兜底删除；
        #   此处只校验 formatter / orchestrator 两份同源仍能识别占位符。
        from agent.formatter import _MISSING_ANSWER_RE
        from agent.orchestrator import _DEGRADED_ANSWER_RE

        for name, rx in (
            ("formatter._MISSING_ANSWER_RE", _MISSING_ANSWER_RE),
            ("orchestrator._DEGRADED_ANSWER_RE", _DEGRADED_ANSWER_RE),
        ):
            with self.subTest(rx=name):
                self.assertRegex(PLACEHOLDER, rx)
                # 「未给出有效解答」是 user_agent 写的终极终态，也要认
                self.assertRegex("未给出有效解答。", rx)
                # ⚠ 窄口径：`无解` / `暂无` 是**合法答案**，绝不能被判为"无答案"
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

    # ★ 2026-10-15：`test_is_degraded_answer` 已删 —— `ReasoningAgent._is_degraded_answer`
    #   随降级兜底（直答/抢救）链删除。


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
        """2026-10-07：开关为调用时实时读取 ⇒ 用 env 覆盖（原 patch 模块常量已失效）。"""
        sleeps = []
        with patch.dict(os.environ, {"LLM_RETRY_ON_TIMEOUT": "1"}), \
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


# ★ 2026-10-15（用户定案「不要降级兜底」）：
#   以下两个测试类已删 —— `TestRescueFailureDoesNotLeakPlaceholder`（锁
#   `_rescue_answer` 抢救链）与 `TestSubgoalResidueMustLookLikeAnAnswer`
#   （锁 `_subgoal_answer_candidate` 形态判据）随「必须有答案」兜底
#   （`_fallback_solve` / `_rescue_answer` / `_is_degraded_answer` /
#   `_subgoal_answer_candidate`）一并删除。删除后：流水线交什么就是什么，
#   占位符/空答案如实暴露，不再由入口侧抢救。
