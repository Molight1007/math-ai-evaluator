# -*- coding: utf-8 -*-
"""5.5 低置信度强制复核的**闸门口径**回归测试（2026-09-16）。

背景（0916 轮 111 题实测，决定性证据）
------------------------------------
111（standard 档）的 budget 事件：

    单题预算收紧 1100s → 540s（档位 standard）
    生成侧软截止 480s 前停手（verify_reserve=480s）

⇒ `_gen_deadline` = 540 − 480 = **仅 60 秒**。而 `2.5_difficulty`(23.6s) +
`2.7_subgoal_main`(47s) 就已经把 60s 耗尽 ⇒ 验证阶段开始时
`ctx.gen_time_up()` **恒为 True**。

后果：那个 `if ... and not ctx.gen_time_up()` 的 5.5 低置信度强制复核
**被永久禁用** —— 验证器把唯一候选投成 0/2 票（且带推理复核判 B），
却**无人消费**，错答直接提交。trace 实证：

    「全部 0 正确票，触发兜底直接求解」→ 之后 `5.5_low_conf` 阶段耗时 9.5e-06 秒
    `revise_round = 0`

★ 这是**口径错配**：`gen_time_up()` 是「**生成**侧软截止」，用于闸**生成**；
而 5.5 是**验证之后的修正**，正是那 480s `verify_reserve` 要保护的时段。
用生成时钟去闸修正环节，等于把预留的验证时间作废。

本测试用**源码级守卫**锁定该口径：5.5 块内不得再出现 `gen_time_up()`。
（这类"语义口径"很难用行为测试覆盖，源码守卫是性价比最高的防回归手段。）
"""
import glob
import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORCH = os.path.join(ROOT, "agent", "orchestrator.py")

# 2026-10-07 阶段C3b：`Orchestrator.run` 的 5.5_low_conf 段已**逐字搬**到
# agent/orchestrator__low_conf.py（调用点改为一行委托）。本测试的 5.5 位置型
# 守卫改为读该模块的函数体 —— 段文本与搬迁前一致，断言与守卫意图不变
# （只是被查代码换了文件，非放宽判据）。
# 2026-10-07 阶段C6：`Orchestrator.run` 的 5_revise_or_fallback 段亦已**逐字搬**入
# **同一模块** agent/orchestrator__low_conf.py（调用点改为一行委托）。该段位置型
# 守卫同样改为读该模块的函数体 —— 段文本与搬迁前逐字相同，断言
# （`_zero_vote_fallback` / `direct_solve` 仍在）与守卫意图不变，**非放宽判据**。
_STAGE_MODULE = {
    'self._stage_start(ctx, "5.5_low_conf")':
        ("orchestrator__low_conf.py", "def low_confidence_recheck"),
    'self._stage_start(ctx, "5_revise_or_fallback")':
        ("orchestrator__low_conf.py", "def revise_or_fallback_stage"),
}


class ReviseGuardTest(unittest.TestCase):

    def _src(self):
        # 2026-10-08 批9：改为读「主文件 + **全部** agent/orchestrator__*.py」并集，
        # 与其余 7 个并集读者（test_verify_only._orch_src 等）同口径。
        # `test_generation_stages_still_use_gen_time_up` 断言的是「**生成**阶段仍
        # 受 gen_time_up 约束」这一意图；被查代码从单文件变并集后，子串命中只增
        # 不减 ⇒ **非放宽判据**（断言字符串与比较逻辑一字不改，只是覆盖面不缩小）。
        txt = io.open(ORCH, encoding="utf-8").read()
        for _p in sorted(glob.glob(
                os.path.join(ROOT, "agent", "orchestrator__*.py"))):
            txt += "\n" + io.open(_p, encoding="utf-8").read()
        return txt

    def _extracted(self, module_rel: str, func_header: str) -> str:
        p = os.path.join(ROOT, "agent", module_rel)
        txt = io.open(p, encoding="utf-8").read()
        i = txt.find(func_header)
        self.assertGreater(i, 0, "找不到抽出函数：" + func_header)
        return txt[i:]

    def _block(self, marker: str) -> str:
        """取「本阶段」的源码：从 marker 到**下一个 `_stage_start`** 为止。

        ⚠ 不能用固定长度切片：会跨到相邻阶段（5_revise_or_fallback 里合法地
        用了 `gen_time_up()` 来闸 deep 档修订），导致误报。
        已抽出的阶段（见 `_STAGE_MODULE`）直接从其模块读函数体（逐字同源）。
        """
        spec = _STAGE_MODULE.get(marker)
        if spec is not None:
            return self._extracted(*spec)
        src = self._src()
        i = src.find(marker)
        self.assertGreater(i, 0, "找不到标记：" + marker)
        j = src.find("self._stage_start(", i + len(marker))
        return src[i:j] if j > 0 else src[i:]

    @staticmethod
    def _strip_comments(block: str) -> str:
        """去掉整行注释与行尾注释，避免守卫检查被**解释性注释**绊住。

        （第一版就踩了：修复时在块内写了说明 `gen_time_up()` 口径的注释，
          源码级守卫因此误报。）
        """
        out = []
        for line in block.split("\n"):
            s = line.strip()
            if s.startswith("#"):
                continue
            # 去掉行尾注释（字符串里的 # 极少，此处可接受）
            if "#" in line:
                line = line.split("#", 1)[0]
            out.append(line)
        return "\n".join(out)

    def test_low_conf_block_does_not_use_gen_time_up(self):
        blk = self._strip_comments(
            self._block('self._stage_start(ctx, "5.5_low_conf")'))
        self.assertNotIn(
            "gen_time_up()", blk,
            "★ 5.5 低置信度复核不得用 gen_time_up() 作闸门——"
            "standard 档单题预算收紧到 540s、verify_reserve=480s 时它恒为 True，"
            "会把验证后的修正环节彻底禁用（0916 轮 111 题实证）。")

    def test_low_conf_block_uses_real_remaining_time(self):
        blk = self._strip_comments(
            self._block('self._stage_start(ctx, "5.5_low_conf")'))
        self.assertIn("is_time_critical()", blk,
                      "5.5 应改用真实剩余时间（is_time_critical）作闸门")

    def test_zero_vote_fallback_still_present(self):
        """全 0 票兜底路径必须保留（不能因为修 5.5 而删掉）。"""
        blk = self._block('self._stage_start(ctx, "5_revise_or_fallback")')
        self.assertIn("_zero_vote_fallback", blk)
        self.assertIn("direct_solve", blk)

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
