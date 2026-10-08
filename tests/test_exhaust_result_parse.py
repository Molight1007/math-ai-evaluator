# -*- coding: utf-8 -*-
"""穷尽性检查「可检测性」的回归测试（2026-09-17）。

## 背景

「解族穷尽性检查」子目标由代码在 `asks_all_values` 为真时**强制追加**
（`agent/sub_goal_solver.py`）。原实现的 `result` 是**自由文本** ⇒
**无法区分**"列了所有解族后确认只有一解"与"压根没列、直接把前序结论抄了一遍"。

实测 official112-003 的 result 就是一句 `a_n = n \\text{ for all } n \\ge 0` ——
它既没列解族、也没做排除，但外观上"看起来完成了检查"。

## 修法

1. 在子目标描述里强制**固定格式**输出（四段）：
   `解族清单:` / `逐族判定:` / `前序结论复核:` / `结论: EXHAUSTIVE: yes|no`
2. 新增 `_parse_exhaust_result()` 解析该格式，落 diag 为 `exhaust_result`：
   `{found, complete, n_families, verdict, missed, reason}`
   **`complete=False` 即"未完成检查"的可机检信号。**
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import _parse_exhaust_result  # noqa: E402

TITLE = "解族穷尽性检查"


def _sgs_union_src() -> str:
    """`agent/sub_goal_solver.py` + 已抽出的 `agent/sub_goal_solver__*.py` 的**并集**。

    2026-10-08 批1：`SubGoalSolverAgent.run` 的「穷尽性搜索机制」段（含
    『待检验假设』『遗漏解族』等**子目标描述字面量**）已**逐字搬**到
    `agent/sub_goal_solver__exhaust.py`。源码级守卫改为读「主文件 + 抽出模块」
    并集 —— 断言的字面量与守卫意图**均不变**（只是被查代码换了文件，非放宽判据）。
    与 `tests/test_orchestrator_static.py::_orch_union_src` 同口径。
    """
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    txt = open(os.path.join(root, "agent", "sub_goal_solver.py"),
               encoding="utf-8").read()
    for p in sorted(glob.glob(
            os.path.join(root, "agent", "sub_goal_solver__*.py"))):
        with open(p, encoding="utf-8") as fh:
            txt += "\n" + fh.read()
    return txt


def _trace(result, title=TITLE):
    return [{"id": 5, "title": title, "result": result}]


FULL_YES = ("解族清单: 常数 / 线性 / 周期 / 取整解 / 分段解\n"
            "逐族判定: 常数解不存在（代入矛盾）；线性解存在 a_n=n\n"
            "前序结论复核: 前序找到的 a_n=n 属于线性族，同族无其他解\n"
            "结论: EXHAUSTIVE: yes\n"
            "遗漏解族: 无")

FULL_NO = ("解族清单: 常数、线性、周期\n"
           "逐族判定: 略\n"
           "前序结论复核: 略\n"
           "结论: EXHAUSTIVE: no\n"
           "遗漏解族: a_n = n + 1")


class ExhaustResultParseTest(unittest.TestCase):

    def test_003_real_case_is_incomplete(self):
        """★ 核心：003 的真实 result（只复述结论）必须判为**未完成检查**。"""
        r = _parse_exhaust_result(_trace("a_n = n \\text{ for all } n \\ge 0"))
        self.assertTrue(r["found"])
        self.assertFalse(r["complete"], "只复述结论 ⇒ 必须判未完成")
        self.assertEqual(r["n_families"], 0, "没列解族 ⇒ 族数应为 0")
        self.assertEqual(r["verdict"], "", "没写 EXHAUSTIVE ⇒ verdict 为空")
        self.assertIn("缺段", r["reason"])

    def test_compliant_output_is_complete(self):
        r = _parse_exhaust_result(_trace(FULL_YES))
        self.assertTrue(r["complete"])
        self.assertEqual(r["verdict"], "yes")
        self.assertGreater(r["n_families"], 0, "合规输出应能数出解族")

    def test_missed_family_captured(self):
        r = _parse_exhaust_result(_trace(FULL_NO))
        self.assertTrue(r["complete"])
        self.assertEqual(r["verdict"], "no")
        self.assertIn("n + 1", r["missed"], "遗漏解族应被捕获")

    def test_missing_sections_each_detected(self):
        """缺任一段都应判 incomplete 并在 reason 中列明缺哪段。"""
        cases = {
            "缺解族清单": FULL_YES.replace("解族清单: ", "族: "),
            "缺逐族判定": FULL_YES.replace("逐族判定: ", "判定: "),
            "缺前序结论复核": FULL_YES.replace("前序结论复核: ", "复核: "),
            "缺EXHAUSTIVE": FULL_YES.replace("EXHAUSTIVE: yes", "结论: 已穷尽"),
        }
        for name, txt in cases.items():
            with self.subTest(name=name):
                r = _parse_exhaust_result(_trace(txt))
                self.assertFalse(r["complete"], "%s 应判 incomplete" % name)

    def test_empty_result(self):
        r = _parse_exhaust_result(_trace(""))
        self.assertTrue(r["found"])
        self.assertFalse(r["complete"])
        self.assertEqual(r["reason"], "result 为空")

    def test_no_subgoal(self):
        r = _parse_exhaust_result([])
        self.assertFalse(r["found"])
        self.assertEqual(r["reason"], "无该子目标")

    def test_other_subgoal_ignored(self):
        r = _parse_exhaust_result(_trace(FULL_YES, title="其它子目标"))
        self.assertFalse(r["found"])

    def test_never_raises_on_garbage(self):
        """任何异常都必须被兜底（返回 dict），不得穿透。"""
        for bad in (None, [{"title": TITLE}], [{"title": TITLE, "result": None}],
                    [{"title": TITLE, "result": 12345}]):
            with self.subTest(bad=bad):
                r = _parse_exhaust_result(bad)
                self.assertIsInstance(r, dict)
                self.assertIn("complete", r)


class ExhaustPromptFormatTest(unittest.TestCase):
    """子目标描述必须把四段格式写清楚（否则模型无从遵守）。"""

    def test_description_requires_fixed_sections(self):
        src = _sgs_union_src()
        for seg in ("解族清单", "逐族判定", "前序结论复核", "EXHAUSTIVE", "遗漏解族"):
            with self.subTest(seg=seg):
                self.assertIn(seg, src)

    def test_description_frames_prior_as_hypotheses(self):
        """前序结论必须被标注为"待检验假设"，否则会被锚定（实测失败根因）。"""
        src = _sgs_union_src()
        self.assertIn("待检验", src)
        self.assertIn("遗漏", src)


if __name__ == "__main__":
    unittest.main()
