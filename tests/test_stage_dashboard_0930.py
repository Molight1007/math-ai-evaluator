"""截图 #10 落实测试：分阶段四维体检（耗时 / 结果 / 是否达标 / 工具使用）。

用户原话：
  「最后的诊断要详细，要对**每个过程消耗的时间**诊断 ——
    耗时 / 结果 / 是否达标 三维 + 关注工具使用」

本文件的重点是那个**最容易搞错、也最致命**的口径：
  ★ **分母必须是"该阶段实际跑到的题数"，不是总题数。**

为什么这条值得单独立一个测试文件：
  本项目反复吃亏的假阴性模式是「没跑 ≠ 没问题」。而本节的初版实现恰好
  犯了它的镜像错误 —— 把「**没跑到**该阶段」算成了「**该阶段没达标**」：
  实测 official112 的 `3_solve` 只在 29 题上有候选（其余 83 题上游早退），
  按 112 当分母会得出"求解达标率 25.9%"，而真实含义是
  "**能跑到求解的 29 题，29 题都产出了候选**（100%）"。
  一个分母写错，结论就从"求解环节没问题"翻成"求解是最大瓶颈"。

⚠ 本文件同时覆盖：`n_failed` 假字段（真键是 n_subgoals/dep_edges）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.test_report import (
    sec_stage_dashboard,
    _stage_dashboard_rows,
    _stage_reached,
)


def _rec(domain="离散数学", st=None, diag_extra=None, candidates=None):
    """构造一条测试用 record（结构与真实 jsonl 对齐）。"""
    diag = {"stage_timers": st or {}}
    if diag_extra:
        diag.update(diag_extra)
    return {
        "domain": domain,
        "diag": diag,
        "candidates": candidates if candidates is not None else [],
        "correct": True,
    }


class ReachedDenominatorTest(unittest.TestCase):
    """★ 分母口径：`_stage_reached` 只数"真的跑到"的题。"""

    def test_zero_elapsed_is_not_reached(self):
        """耗时 0 ⇒ 视为没跑到（不进取样、不进分母）。"""
        recs = [
            _rec(st={"3_solve": 120.0}),
            _rec(st={"3_solve": 0.0}),
            _rec(st={"3_solve": 0.0}),
        ]
        self.assertEqual(_stage_reached(recs, "3_solve"), 1)

    def test_missing_stage_key_is_not_reached(self):
        recs = [_rec(st={"1_classify": 5.0}), _rec(st={})]
        self.assertEqual(_stage_reached(recs, "3_solve"), 0)

    def test_positive_control_would_catch_using_total(self):
        """★ 阳性对照：若分母退化成 `len(recs)`，本断言应红。"""
        recs = [_rec(st={"3_solve": 10.0})] + [_rec(st={"3_solve": 0.0})] * 9
        self.assertEqual(_stage_reached(recs, "3_solve"), 1)
        self.assertNotEqual(_stage_reached(recs, "3_solve"), len(recs),
                            "分母若等于总题数，'没跑到'会被误算成'没达标'")


class DashboardRowTest(unittest.TestCase):
    """四维行内容。"""

    def test_solve_pass_rate_uses_reached_denominator(self):
        """★ 核心：10 题里只有 1 题跑到求解、且产出了候选 ⇒ 达标 1/1（100%），
        **不是** 1/10（10%）。"""
        recs = ([_rec(st={"3_solve": 30.0}, candidates=[{"answer": "5"}])]
                + [_rec(st={"3_solve": 0.0})] * 9)
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        _key, _disp, _t, _tnz, _ntot, _raw, pass_txt, _pd, _tool = rows["3_solve"]
        self.assertIn("1/1", pass_txt,
                      "达标分母必须是'跑到该阶段的题数'（1），而非总题数（10）")

    def test_all_reached_all_pass_is_100(self):
        recs = [_rec(st={"3_solve": 30.0}, candidates=[{"answer": "5"}])] * 5
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        self.assertIn("5/5", rows["3_solve"][6])

    def test_no_candidate_among_reached_is_fail(self):
        """★ 反向对照：跑到了但没候选 ⇒ 真的算不达标（不能一律放过）。"""
        recs = [_rec(st={"3_solve": 30.0}, candidates=[])] * 4
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        self.assertIn("0/4", rows["3_solve"][6])

    def test_result_mode_ignores_unreached(self):
        """结果众数也只统计'跑到'的题 —— 否则 `cands=0` 会被没跑到的题主导。"""
        recs = ([_rec(st={"3_solve": 30.0}, candidates=[1, 2, 3, 4, 5, 6])]
                + [_rec(st={"3_solve": 0.0})] * 20)
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        _raw = rows["3_solve"][5]
        self.assertIn("cands=6", _raw)
        self.assertNotIn("cands=0", _raw)


class SubgoalFailedKeyTest(unittest.TestCase):
    """`n_failed` 假字段回归（真键是 n_subgoals / dep_edges）。"""

    def test_uses_trace_not_absent_key(self):
        """★ 核心：判据读 `subgoal_trace` 的 result，而非不存在的 `n_failed`。

        历史缺陷：原实现读 `subgoal_stats["n_failed"]` —— 该键**不存在**，
        恒取 0 ⇒ 恒判"100% 达标"，掩盖了真实的 20.5%。
        """
        recs = [_rec(st={"2.7_subgoal_main": 50.0}, diag_extra={
            "subgoal_stats": {"n_subgoals": 2, "dep_edges": 1},
            "subgoal_trace": [
                {"id": 1, "result": "[子目标求解失败] 超时"},
                {"id": 2, "result": "x = 5"},
            ],
        })] * 3
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        pass_txt = rows["2.7_subgoal_main"][6]
        self.assertIn("0/3", pass_txt, "有失败子目标 ⇒ 应判不达标（0/3）")

    def test_all_subgoals_ok_is_pass(self):
        recs = [_rec(st={"2.7_subgoal_main": 50.0}, diag_extra={
            "subgoal_stats": {"n_subgoals": 2},
            "subgoal_trace": [{"id": 1, "result": "x = 5"},
                              {"id": 2, "result": "y = 7"}],
        })] * 2
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        self.assertIn("2/2", rows["2.7_subgoal_main"][6])

    def test_positive_control_absent_key_would_give_false_pass(self):
        """★ 阳性对照：若改回读 `n_failed`，下面这组有失败的题会**假达标**。"""
        recs = [_rec(st={"2.7_subgoal_main": 50.0}, diag_extra={
            "subgoal_stats": {"n_subgoals": 2},        # 注意：无 n_failed 键
            "subgoal_trace": [{"id": 1, "result": ""}],
        })] * 2
        rows = {r[0]: r for r in _stage_dashboard_rows(recs)}
        self.assertNotIn("2/2", rows["2.7_subgoal_main"][6],
                         "读不存在的键 ⇒ 恒判达标，掩盖真实失败")


class NeverRaisesTest(unittest.TestCase):
    """报告生成对垃圾输入必须稳健（报告出不来 = 一整轮数据白跑）。"""

    def test_empty_recs(self):
        L = sec_stage_dashboard([])
        self.assertTrue(isinstance(L, list) and L)

    def test_junk_recs(self):
        recs = [{"diag": None}, {"diag": {}}, {}, {"diag": {"stage_timers": "x"}}]
        try:
            L = sec_stage_dashboard(recs)
        except Exception as e:  # noqa: BLE001
            self.fail(f"sec_stage_dashboard 不应抛异常: {e!r}")
        self.assertTrue(isinstance(L, list))

    def test_all_stages_present_in_output(self):
        """11 个阶段必须在表里出现（否则读者会以为漏了环节）。"""
        recs = [_rec(st={"3_solve": 10.0}, candidates=[{"answer": "1"}])]
        text = "\n".join(sec_stage_dashboard(recs))
        for key in ("1_classify", "2.6_pre_audit", "2.7_subgoal_main", "3_solve",
                    "3.3_improve", "3.6_audit_filter", "4_verify"):
            self.assertIn(key, text, f"四维表缺少阶段 {key}")


class DisciplinesTest(unittest.TestCase):
    """报告必须自带口径说明，否则读者会误读。"""

    def test_report_states_denominator_rule(self):
        text = "\n".join(sec_stage_dashboard([_rec(st={"3_solve": 1.0})]))
        self.assertIn("实际跑到", text,
                      "报告必须写明'分母=实际跑到的题数'，否则读者会把没跑读成没达标")

    def test_report_separates_not_triggered_from_failed(self):
        """★ '未触发' 与 '触发了没达标' 必须分开 —— 修法完全不同。"""
        text = "\n".join(sec_stage_dashboard([_rec(st={"3_solve": 1.0})]))
        self.assertIn("未触发", text)


if __name__ == "__main__":
    unittest.main()
