# -*- coding: utf-8 -*-
"""2026-09-14 沙箱实测缺陷的回归测试（#005 后处理改烂答案）。

#005 实况（gitcode 沙箱 e2398038 报告）：
  final_postprocess_change_events:
    后处理改写了最终答案：\boxed{1234} → \boxed{The problem asks for all possible
    values of $C(1234)$ …}
  ⇒ 模型给的 1234 被替换成**整段题面英文复述** → error_class=format_unresolved。
  根因：`Orchestrator._looks_like_answer` 的判据是 `re.search(r"\\d", txt)`，
  那段散文含 `1234` ⇒ 被放行。

2026-10-01：原 #003（`answer_selfcheck` 空转）一节随 `<calc>` 计算工具板块
  一并删除（`SolverAgent._maybe_answer_selfcheck` 已移除），本节用例不再覆盖。
"""
from __future__ import annotations

import unittest

from agent.orchestrator import Orchestrator


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


if __name__ == "__main__":
    unittest.main()
