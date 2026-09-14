# -*- coding: utf-8 -*-
"""2026-09-14 沙箱实测缺陷的回归测试（#005 后处理改烂答案 / #003 selfcheck 空转）。

#005 实况（gitcode 沙箱 e2398038 报告）：
  final_postprocess_change_events:
    后处理改写了最终答案：\boxed{1234} → \boxed{The problem asks for all possible
    values of $C(1234)$ …}
  ⇒ 模型给的 1234 被替换成**整段题面英文复述** → error_class=format_unresolved。
  根因：`Orchestrator._looks_like_answer` 的判据是 `re.search(r"\\d", txt)`，
  那段散文含 `1234` ⇒ 被放行。

#003 实况：同一答案（2026）被 `answer_selfcheck` adopt 2 次、重问 3 次
  （569s / 561s 各来一遍）。根因：`resolved` 只含本轮 response 的 <calc>，
  上一轮采纳的工具值没有跨轮保存 ⇒ 下一轮又判"无工具来源"。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from agent.base import TaskContext
from agent.orchestrator import Orchestrator
from agent.solver import SolverAgent


class TestLooksLikeAnswerRejectsRestatement(unittest.TestCase):
    """#005：题面复述不得被当成答案（即便它含数字）。"""

    # gitcode 沙箱报告里的真实串（勿改）
    REAL_005_FIXED = ("The problem asks for all possible values of $C(1234)$ "
                      "for which the equation holds, so the answer is 1234.")

    def test_real_005_restatement_is_rejected(self) -> None:
        self.assertFalse(Orchestrator._looks_like_answer(self.REAL_005_FIXED))

    def test_003_meta_talk_still_rejected(self) -> None:
        self.assertFalse(Orchestrator._looks_like_answer(
            "The user wants me to act as a math answer formatting tool."))

    def test_legit_answers_still_accepted(self) -> None:
        """合法答案（含英文散文的 011 gold）**不得误杀**。"""
        for ok in [
            "1234",                       # #005 的原答案
            "2026, 2030",                 # 003 gold（枚举）
            "4,5,6",                      # 064
            "2",                          # 015
            r"\frac{1}{2}",               # 067 gold 之一
            r"\{x \mid x > 0\}",
            r"\text{有限差分法、有限元法}",  # 099 型中文答案
            # ★ 011 的 gold —— 合法英文散文，绝不能被杀
            r"$f(x,y)= g(x+y, xy(x-y)^{2})$ for some polynomial $g$",
        ]:
            with self.subTest(ans=ok):
                self.assertTrue(Orchestrator._looks_like_answer(ok),
                                "误杀了合法答案: %r" % ok)

    def test_overlong_is_rejected(self) -> None:
        self.assertFalse(Orchestrator._looks_like_answer("1" * 121))


class TestSelfcheckIdempotentShortCircuit(unittest.TestCase):
    """#003：同一答案只重问一次；工具值 == 模型答案即放行。"""

    @staticmethod
    def _agent(records):
        a = object.__new__(SolverAgent)
        a.config = SimpleNamespace(answer_selfcheck_enabled=True,
                                   max_answer_tokens=256,
                                   symbolic_solve_adopt=True)
        a.record = lambda ctx, step, content, **k: records.append((step, content))
        a._compressed_solve = lambda *ar, **kw: ""      # 重问返回空 → 不采纳
        return a

    def _ctx(self):
        return TaskContext(problem="求 C(50,3) 的值", metadata={})

    def test_verified_value_short_circuits(self) -> None:
        recs = []
        a, ctx = self._agent(recs), self._ctx()
        ctx._selfcheck_verified_vals = {"2026"}        # 上一轮已核验
        resp, ans = a._maybe_answer_selfcheck(ctx, "本题需 comb(50,3) ","2026", [])
        self.assertEqual((resp, ans), ("本题需 comb(50,3) ", "2026"))
        self.assertTrue(any(s == "answer_selfcheck_skip" for s, _ in recs),
                        recs)
        self.assertFalse(any(s == "answer_selfcheck" for s, _ in recs),
                         "不该再发起重问")

    def test_already_reasked_short_circuits(self) -> None:
        recs = []
        a, ctx = self._agent(recs), self._ctx()
        ctx._selfcheck_reasked_ans = {"2026"}
        resp, ans = a._maybe_answer_selfcheck(ctx, "本题需 comb(50,3) ", "2026", [])
        self.assertEqual(ans, "2026")
        self.assertTrue(any(s == "answer_selfcheck_skip" for s, _ in recs), recs)

    def test_fresh_context_still_reasks(self) -> None:
        """没有历史时必须照常走重问分支（防止短路改坏了正常路径）。"""
        recs = []
        a, ctx = self._agent(recs), self._ctx()
        resp, ans = a._maybe_answer_selfcheck(ctx, "本题需 comb(50,3) ", "2026", [])
        self.assertEqual(ans, "2026")
        self.assertTrue(any(s == "answer_selfcheck" for s, _ in recs),
                        "正常路径应记录 answer_selfcheck（定向重问）")
        self.assertFalse(any(s == "answer_selfcheck_skip" for s, _ in recs))

    def test_tool_value_confirms_answer_is_registered(self) -> None:
        """工具值 == 答案时，应把该值登记进跨轮集合（供下轮短路）。"""
        recs = []
        a, ctx = self._agent(recs), self._ctx()
        resp, ans = a._maybe_answer_selfcheck(
            ctx, "本题需 comb(50,3) ", "19600", [("comb(50,3)", "19600")])
        self.assertEqual(ans, "19600")
        self.assertIn("19600", getattr(ctx, "_selfcheck_verified_vals", set()))


if __name__ == "__main__":
    unittest.main()
