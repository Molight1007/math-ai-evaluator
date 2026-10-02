# -*- coding: utf-8 -*-
"""机制开关策略锁定（2026-09-21，用户指示「开开啊」）。

背景
----
云端 n=38 快照复核发现 6 个阶段累计耗时 0 s。逐项定性后确认：
其中 5 项并非缺陷，而是 `AgentConfig` 的类默认值为 `False`（且云端 overrides 未覆盖）——
即**机制从未被打开过**，而不是「打开后失效」。

用户 2026-09-21 指示全部启用。本文件锁定该策略值，防止将来被无意翻回。

⚠ 2026-09-29 变更：`enable_calc_prewarm` **整体废弃**（用户决策，见
`CHANGES_2026-09-29.md` 截图 #5）—— 生成前算式预计算被判定「没必要、不合逻辑」，
`solver.prewarm_calcs()` / `_prewarm_applicable()` / 相关常量连同配置项一并删除。
故本文件由「五项」收敛为**四项**，`enable_calc_prewarm` 不再参与断言。

配套（不改但必须知道）
--------------------
· 2026-10-01 研究期：类默认时间已放开为 `max_time_per_question=86400` /
  `tier_budget={"deep": 86400.0}` ⇒ **不再有按剩余时间降级的逻辑**，
  机制不会再被时间窗口"饿死"（`deploy/run_112.py` 早已硬编码 86400）。
"""
from __future__ import annotations

import unittest

# 2026-09-21 用户指示启用（原值见下方注释）
EXPECTED_TRUE = {
    "enable_collaborative_deep": False,   # 原 2026-09-14 关闭（机制未触发）
    "enable_lean_preverify": False,       # 原 2026-09-12 关闭（5/5 fail、零产出）
}
# 2026-09-29 移除：`enable_calc_prewarm`（整项废弃，配置字段与实现均已删除）
# 2026-10-01 移除：`enable_calc_tool`（`<calc>` 计算工具板块整体删除）
# 2026-10-01 移除：`use_sub_goal`（档位时代遗留，全仓 0 读取点；真正生效的是
#   `deep_use_sub_goal`。见 CHANGES_2026-10-01 死代码清理）


class MechanismSwitchesOnTest(unittest.TestCase):
    def setUp(self) -> None:
        from user_agent import AgentConfig
        self.cfg = AgentConfig()

    def test_all_switches_are_enabled(self) -> None:
        """各项机制开关必须为 True（2026-09-21 用户指示）。"""
        for name in EXPECTED_TRUE:
            with self.subTest(switch=name):
                self.assertTrue(
                    getattr(self.cfg, name),
                    "%s 应为 True（2026-09-21 用户指示启用）" % name)

    def test_switches_are_declared_on_config(self) -> None:
        """★ 五层检查第①层：开关必须**声明在 AgentConfig** 上。

        本项目踩过多次「有读取点但无声明」⇒ `getattr(cfg, X, 默认)` 恒取默认、
        机制被锁死（见 MEMORY「新增配置项必须过四层检查」）。
        """
        for name in EXPECTED_TRUE:
            with self.subTest(switch=name):
                self.assertIn(name, self.cfg.__dataclass_fields__,
                              "%s 未声明在 AgentConfig" % name)

    def test_switches_are_in_override_whitelist(self) -> None:
        """★ 五层检查第②层：必须在覆盖白名单里，否则 CLI/overrides 会被静默丢弃。

        历史坑：`max_subgoals` 与 `enable_calc_prewarm` 都曾因漏加白名单而
        「传参成功但无效果」（user_agent.py 内多处以「同 enable_calc_prewarm 那次的坑」为戒）。
        """
        import io
        import os
        import re

        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "user_agent.py")
        text = io.open(src, encoding="utf-8", errors="replace").read()
        for name in EXPECTED_TRUE:
            with self.subTest(switch=name):
                self.assertRegex(
                    text, r'"%s"' % re.escape(name),
                    "%s 不在覆盖白名单 ⇒ CLI/overrides 会被静默丢弃" % name)


class TimeWindowPrerequisiteTest(unittest.TestCase):
    """`enable_collaborative_deep` 需要时间窗口才有意义 —— 记录该前提。"""

    def test_documented_time_prerequisite(self) -> None:
        """云端启动器必须把时间放开（否则 3.4 会被生成侧截止门控跳过）。

        这不是断言启动器内容，而是断言「类默认可被覆盖」这一路径存在：
        `max_time_per_question` / `tier_budget` 都必须在白名单里。
        """
        import io
        import os

        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "user_agent.py")
        text = io.open(src, encoding="utf-8", errors="replace").read()
        for key in ("max_time_per_question", "tier_budget"):
            self.assertIn('"%s"' % key, text, "%s 必须可被 overrides 覆盖" % key)


if __name__ == "__main__":
    unittest.main()
