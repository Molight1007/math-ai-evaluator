# -*- coding: utf-8 -*-
"""revise 闸门口径守卫 —— 2026-10-14 五道链定案后**仅保留反向保护**。

历史沿革
========
本文件原为「5.5 低置信度强制复核的闸门口径」回归测试（2026-09-16，0916 轮
111 题实证：5.5 用 `gen_time_up()` 作闸门导致修正环节被永久禁用）。

★ 2026-10-14（五道链定案）：`5.5_low_conf` 与 `5_revise_or_fallback` 两阶段
连同其模块（`agent/orchestrator__low_conf.py`）**整体删除** ⇒ 原三条位置型
守卫（`test_low_conf_block_*` / `test_zero_vote_fallback_still_present`）
失去目标，已随之删除。

保留：`test_generation_stages_still_use_gen_time_up` —— **反向保护**：
生成阶段仍应受 `gen_time_up()` 约束（那是它的正当用途），
防"为修 5.5 而把 gen_time_up 一刀切删光"的老坑。
"""
import glob
import io
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORCH = os.path.join(ROOT, "agent", "orchestrator.py")


class ReviseGuardTest(unittest.TestCase):

    def _src(self):
        # 2026-10-08 批9：改为读「主文件 + **全部** agent/orchestrator__*.py」并集，
        # 与其余并集读者同口径。断言字符串与比较逻辑一字不改，只是覆盖面不缩小。
        txt = io.open(ORCH, encoding="utf-8").read()
        for _p in sorted(glob.glob(
                os.path.join(ROOT, "agent", "orchestrator__*.py"))):
            txt += "\n" + io.open(_p, encoding="utf-8").read()
        return txt

    def test_generation_stages_still_use_gen_time_up(self):
        """⚠ 反向保护：**生成**阶段仍应受 gen_time_up 约束（那是它的正当用途）。

        防的是"为了修 5.5 而把 gen_time_up 一刀切删光"——那会让生成阶段
        烧穿 verify_reserve，退回"验证投票全跳、答案零验证裸提交"的老坑。
        """
        src = self._src()
        self.assertGreaterEqual(
            src.count("gen_time_up()"), 5,
            "生成侧仍须保留 gen_time_up 约束，别一刀切删掉")


if __name__ == "__main__":
    unittest.main()
