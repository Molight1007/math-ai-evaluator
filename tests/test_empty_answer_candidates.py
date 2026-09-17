# -*- coding: utf-8 -*-
"""空答案候选剔除的回归测试（2026-09-16）。

## 背景（实测 official112-003）

候选 3 的答案是 **`\\boxed{}`**（空），但它：
1. **吃掉了 3 张验证票** —— 因为 `audit_gate.audit_candidates` 对空答案只是
   `continue`（**跳过不拒绝**），空候选留在池里参与了投票、稀释共识；
2. **通过了所有闸门** —— `audit_gate` 跳过它、`lean_gate` 因 verdict=`unknown`
   走非 strict 的 `lenient_pass` 放行；
3. 一路活到 formatter 的 `not answer.strip()` 才被丢弃（太晚）。

## ★ 关键坑（首版修复就踩了）

`\\boxed{}` **不是空字符串** —— `len('\\boxed{}') == 8`、`.strip()` 非空。
用 `if not ans or not ans.strip()` 判空**完全漏掉它**。
必须**先剥壳**（`AnswerOracle.strip_wrappers`）再判空，否则守卫形同虚设。

## 修法

`audit_candidates` 在**投票之前**跑 ⇒ 在此把空答案剔出候选池；
单独记身份集（不放进 `rejected`，否则会触发"全部被否→回退保留"把它放回来）；
若**所有**候选都为空，则恢复原列表，守住"绝不整批清空"的既有不变量。
"""
import os
import sys
import unittest
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.audit_gate import AuditGate  # noqa: E402


@dataclass
class _Cand:
    id: int
    answer: str
    reasoning: str = ""


class _Cfg:
    use_rubric = False


class _Ctx:
    problem = "test"
    domain = ""
    question_type = "解答题"
    audit_gate: list = None
    trace: list = None

    def __init__(self):
        self.audit_gate = []
        self.trace = []

    def is_time_critical(self):
        return False

    def is_timed_out(self):
        return False

    def time_remaining(self):
        return 99999

    def record(self, *a, **k):
        self.trace.append(a)


def _gate():
    g = object.__new__(AuditGate)
    g.config = _Cfg()
    return g


class EmptyAnswerCandidatesTest(unittest.TestCase):

    def test_boxed_empty_is_detected(self):
        """★ 核心：`\\boxed{}` 必须被识别为空答案（它.strip() 非空！）。"""
        from agent.answer_oracle import AnswerOracle as A
        self.assertTrue(A.strip_wrappers(r"\boxed{}").strip() == "")
        self.assertNotEqual(r"\boxed{}".strip(), "", "它本身不是空串——这正是首版漏判的原因")

    def test_removed_from_pool_before_voting(self):
        cands = [
            _Cand(0, r"\boxed{2025}"),
            _Cand(1, r"\boxed{}"),      # 空答案
            _Cand(2, r"\boxed{2026}"),
            _Cand(3, "   "),            # 纯空白
            _Cand(4, r"\boxed{1013}"),
        ]
        kept, _ = _gate().audit_candidates(_Ctx(), "deep", cands)
        self.assertEqual([c.answer for c in kept],
                         [r"\boxed{2025}", r"\boxed{2026}", r"\boxed{1013}"],
                         "空答案（含 `\\boxed{}`）必须被剔出候选池")

    def test_all_empty_keeps_invariant(self):
        """全是空答案时不制造空池（守住既有"绝不整批清空"不变量）。"""
        cands = [_Cand(0, r"\boxed{}"), _Cand(1, "")]
        kept, _ = _gate().audit_candidates(_Ctx(), "deep", cands)
        self.assertEqual(len(kept), 2)

    def test_legit_answers_untouched(self):
        """反向保护：合法答案（含带壳/带数学定界符）不得被误剔。"""
        for ans in (r"\boxed{2026}", r"\( \boxed{50} \)", "2026, 2030", "A", "48"):
            with self.subTest(ans=ans):
                kept, _ = _gate().audit_candidates(
                    _Ctx(), "deep", [_Cand(0, ans)])
                self.assertEqual(len(kept), 1, "%r 是合法答案，不该被剔除" % ans)

    def test_mixed_keeps_only_nonempty(self):
        cands = [_Cand(0, r"\boxed{2026}"), _Cand(1, r"\boxed{}")]
        kept, _ = _gate().audit_candidates(_Ctx(), "deep", cands)
        self.assertEqual([c.answer for c in kept], [r"\boxed{2026}"])


if __name__ == "__main__":
    unittest.main()
