# -*- coding: utf-8 -*-
"""reasoning 预算裁剪必须**按步摊开**（2026-10-27）。

背景
--------------------------------------------------------------------------
`_build_full_reasoning` 的产出结构是：

    # 子目标分解求解过程
    ## 题目目标
    ## 子目标规划          ← 纯标题骨架，没有推导
    ## 逐步求解            ← **唯一有效信息**（每步的结论 + 推导）
    ## 最终答案

`self_auditor` 原来用 `reasoning[:6000]`（**从头截断**）⇒ 最先切掉的正是
「逐步求解」的后半。实测 95 个历史 run：

    从头截断   平均可见 78% 的步，全步可见的 run 只有 49/95
    按步分配   平均可见 100% 的步，全步可见 95/95

最差一例是 16 个子目标只看到 2 个。而且把每步产出补全之后，从头截断的
可见比例**从 86% 掉到 78%** —— 内容更全、读者反而看得更少，说明这不是
"预算不够"，是**分配方式错了**。

契约
--------------------------------------------------------------------------
1. 总预算不超（`budget` 是上界，允许少量 note 溢出）。
2. **每一步的标题都要出现** —— 审阅者必须知道"这题有几步、我漏了哪些"。
3. 每步的**结论**（`结果:` 行的开头）不能丢 —— 那是判「这步做成了没有」的依据。
4. 短步用不完的余量回收给长步（两轮），不做无意义的均分浪费。
5. `budget<=0` 或文本本身不超预算 ⇒ 原样返回（不制造多余标记）。
"""
from __future__ import annotations

import unittest

from agent.subgoal_result import clip_reasoning


def _build(steps: list[tuple[int, str, str]], head_pad: int = 400) -> str:
    """复刻 `_build_full_reasoning` 的结构。"""
    parts = ["# 子目标分解求解过程", "", "## 题目目标", "题型: proof",
             "要做什么: " + "x" * head_pad, "", "## 子目标规划"]
    for sid, title, _ in steps:
        parts.append(f"  #{sid} [proof] {title}: 描述若干字")
    parts += ["", "## 逐步求解"]
    for sid, title, res in steps:
        parts += ["", f"### 子目标 #{sid}「{title}」", f"结果: {res}"]
    parts += ["", "## 最终答案", "42"]
    return "\n".join(parts)


def _visible(out: str, steps) -> list:
    return [sid for sid, _, _ in steps if f"### 子目标 #{sid}" in out]


class TestEveryStepVisible(unittest.TestCase):
    """核心：预算再紧，也要让每一步都被看到。"""

    def test_six_long_steps_all_visible(self):
        steps = [(i + 1, f"T{i}", "结论" * 600) for i in range(6)]
        out = clip_reasoning(_build(steps), 6000)
        self.assertEqual(_visible(out, steps), [s[0] for s in steps])

    def test_sixteen_steps_all_visible(self):
        """16 步是历史最差形态（旧实现只看到 2 步）。"""
        steps = [(i + 1, f"T{i}", "推导" * 300) for i in range(16)]
        out = clip_reasoning(_build(steps), 6000)
        self.assertEqual(len(_visible(out, steps)), 16)

    def test_tight_budget_still_keeps_all_heads(self):
        steps = [(i + 1, f"T{i}", "内容" * 800) for i in range(8)]
        out = clip_reasoning(_build(steps), 1500)
        self.assertEqual(len(_visible(out, steps)), 8)


class TestConclusionPreserved(unittest.TestCase):
    """每步的结论行不能被切掉（它在步内最前面，所以理论上安全）。"""

    def test_each_step_conclusion_present(self):
        steps = [(i + 1, f"T{i}", f"答案{i}=值。 " + "推导" * 400)
                 for i in range(5)]
        out = clip_reasoning(_build(steps), 3000)
        for i in range(5):
            self.assertIn(f"答案{i}=值", out, msg=f"第 {i+1} 步结论被切掉")


class TestBudgetRespected(unittest.TestCase):
    """预算上界：允许 note 的少量溢出，但不能失控。"""

    def test_within_budget_with_slack(self):
        steps = [(i + 1, f"T{i}", "长文" * 900) for i in range(7)]
        src = _build(steps)
        out = clip_reasoning(src, 6000)
        self.assertLessEqual(len(out), 6000 + 200,
                             msg=f"超预算过多：{len(out)}")

    def test_no_clip_when_fits(self):
        steps = [(1, "T", "短结论")]
        src = _build(steps)
        self.assertEqual(clip_reasoning(src, 6000), src)

    def test_zero_budget_passthrough(self):
        src = _build([(1, "T", "x" * 9000)])
        self.assertEqual(clip_reasoning(src, 0), src)


class TestCarryToLongSteps(unittest.TestCase):
    """短步省下的预算要回收给长步，而不是均分浪费。"""

    def test_short_step_surplus_reused(self):
        steps = [(1, "短", "短结论"), (2, "长", "长" * 5000)]
        out = clip_reasoning(_build(steps), 2000)
        # 短步整段保留
        self.assertIn("短结论", out)
        # 长步应当拿到远超一半预算的正文
        long_body = out[out.index("### 子目标 #2"):]
        self.assertGreater(len(long_body), 1200,
                           msg="余量没有回收给长步")

    def test_all_short_returns_everything(self):
        steps = [(1, "a", "一"), (2, "b", "二"), (3, "c", "三")]
        src = _build(steps)
        out = clip_reasoning(src, 99999)
        self.assertEqual(out, src)


class TestNoStepHeadsFallback(unittest.TestCase):
    """无步标题时退回通用 clip（它按 `## ` 节保结论）。"""

    def test_generic_text_falls_back(self):
        txt = "随便一段" + "填充" * 5000
        out = clip_reasoning(txt, 500)
        self.assertLessEqual(len(out), 700)
        self.assertIn("随便一段", out)


if __name__ == "__main__":
    unittest.main()
