# -*- coding: utf-8 -*-
"""「本步结果」切片只在上游段头处终止（2026-10-27）。

背景（为什么需要这组测试）
--------------------------------------------------------------------------
`_call_step` 用 prefill 把「【本步结果】」钉在响应**开头**（抑制 CoT），而
`SUBGOAL_STEP_SYSTEM` 又把推导安排在它后面（「【推导过程】」段）。旧正则

    re.search(r"【本步结果】\\s*\\n?(.*?)(?:$|【)", resp, re.DOTALL)

遇到任意 `【` 就停 ⇒ **推导整段被切掉**，进管道的 `sg["result"]` 只剩结论。
实测（10 月服务器数据 1368 个子目标）：推导均长 925 字，`result` 中位 106 字。
而 `_build_full_reasoning` 读的正是 `read_step()` = `sg["result"]` ⇒ 4.1 自审 /
4.2 证伪 / 4.4 计算检测拿到的 reasoning 是骨架，不是论证。

契约（本文件锁定的行为）
--------------------------------------------------------------------------
1. `【推导过程】`/`【验算】`/`【证明】`/`【注】` 属**本步内容**，必须保留。
2. 只在 `SUBGOAL_STEP_USER_TEMPLATE` 注入的上游段头处终止（`_STEP_RESULT_HEADS`）。
3. `【当前子目标 #3】` 这种带编号后缀的形态同样要终止。
4. 模型写两遍「【本步结果】」时**不截断**（后半往往是修正结果，宁长勿丢）。
5. 无标记时退回尾部切片（既有行为，不得回归）。
"""
from __future__ import annotations

import unittest

from agent.sub_goal_solver__solve import (
    _STEP_RESULT_HEADS,
    _STEP_RESULT_RE,
)


def _extract(resp: str) -> str:
    m = _STEP_RESULT_RE.search(resp)
    return m.group(1).strip() if m else ""


class TestDerivationIsPreserved(unittest.TestCase):
    """核心回归：推导不能被切掉。"""

    def test_prefill_form_keeps_derivation(self):
        """prefill 形态（结果在前、推导在后）—— 这是实际运行的形态。"""
        resp = (
            "【本步结果】\n"
            "结论 A = 3/5\n\n"
            "【推导过程】\n"
            "由第 2 步的 s=265/247 出发，代入面积公式得 A = 3/5。\n\n"
            "【验算】\n"
            "代回原式两端相等。"
        )
        out = _extract(resp)
        self.assertIn("【推导过程】", out)
        self.assertIn("s=265/247", out)
        self.assertIn("【验算】", out)
        self.assertIn("代回原式两端相等", out)

    def test_multiline_derivation_not_truncated(self):
        """推导跨多段（含空行）时整段保留。"""
        resp = (
            "【本步结果】\nx = 4\n\n"
            "【推导过程】\n第一步：设 t = x²。\n\n"
            "第二步：由 t² - 5t + 4 = 0 得 t ∈ {1, 4}。\n\n"
            "第三步：x > 0 ⇒ x = 4。"
        )
        out = _extract(resp)
        self.assertIn("第一步", out)
        self.assertIn("第二步", out)
        self.assertIn("第三步", out)

    def test_proof_and_note_sections_kept(self):
        """【证明】/【注】也是本步内容，不是上游段头。"""
        resp = (
            "【本步结果】\nT = 1\n\n"
            "【证明】\n因为 f 在闭区间连续，所以取到最值。\n\n"
            "【注】\n边界 g=0 的情形需单独讨论。"
        )
        out = _extract(resp)
        self.assertIn("【证明】", out)
        self.assertIn("【注】", out)
        self.assertIn("闭区间连续", out)

    def test_prompt_original_order_still_works(self):
        """模型按 prompt 原序输出（推导在前、结果在后）时取到结果段。"""
        resp = "【推导过程】\n先算 a = 1。\n\n【本步结果】\na = 1"
        self.assertEqual(_extract(resp), "a = 1")


class TestUpstreamHeadsTerminate(unittest.TestCase):
    """只在上游注入的段头处终止。"""

    def test_current_subgoal_with_index(self):
        """`【当前子目标 #3】` 带编号后缀 ⇒ 仍要终止。"""
        resp = "【本步结果】\nx = 5\n\n【当前子目标 #3】\n标题：求 y"
        self.assertEqual(_extract(resp), "x = 5")

    def test_current_subgoal_bare(self):
        resp = "【本步结果】\nx = 5\n\n【当前子目标】\n标题：求 y"
        self.assertEqual(_extract(resp), "x = 5")

    def test_original_problem_head(self):
        resp = "【本步结果】\ny = 2\n\n【原题】\n某题面若干行"
        self.assertEqual(_extract(resp), "y = 2")

    def test_previous_results_head(self):
        resp = "【本步结果】\nz = 7\n\n【前面步骤的结果】\n第 1 步：z = 7"
        self.assertEqual(_extract(resp), "z = 7")

    def test_plan_head(self):
        resp = "【本步结果】\nw = 1\n\n【子目标规划】\n#1 …"
        self.assertEqual(_extract(resp), "w = 1")

    def test_heads_tuple_is_whitelist_only(self):
        """白名单里不得混入推导类标记（否则等于恢复旧 bug）。"""
        for bad in ("推导过程", "验算", "证明", "注", "本步结果"):
            self.assertNotIn(
                bad, _STEP_RESULT_HEADS,
                msg=f"「{bad}」属本步内容，不能当截断点")


class TestNoInformationLoss(unittest.TestCase):
    """宁长勿丢：重复段头不静默丢内容。"""

    def test_double_result_blocks_not_truncated(self):
        """模型写两遍「本步结果」，第二段（修正值）必须保留。"""
        resp = (
            "【本步结果】\n初值 8\n\n"
            "【推导过程】\n重算后发现应为 9。\n\n"
            "【本步结果】\n9"
        )
        out = _extract(resp)
        self.assertIn("初值 8", out)
        self.assertIn("9", out)
        self.assertIn("【推导过程】", out)


class TestNoMarkerFallback(unittest.TestCase):
    """无标记时走既有兜底路径（本文件只锁定正则侧不回归为空）。"""

    def test_no_marker_returns_empty_from_regex(self):
        """无「【本步结果】」⇒ 正则不匹配，由调用方走尾部切片兜底。"""
        self.assertIsNone(_STEP_RESULT_RE.search("只有一段没有标记的文字"))


if __name__ == "__main__":
    unittest.main()
