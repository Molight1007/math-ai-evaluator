# -*- coding: utf-8 -*-
"""Orchestrator 主流程的静态守卫测试。

为什么需要这个测试
-------------------
2026-08-31 冒烟（2 题）抓到 `name 'is_proof' is not defined`：
#45 移除题型分流时删掉了 `is_proof = ...` 赋值，但 `verifier.run(is_proof=...)`
仍在引用它 → **每一道题都抛 NameError，整条流水线走异常兜底**。

而当时 262 个单测全绿——因为**没有任何测试会跑 `Orchestrator.run` 的完整链路**
（verifier 等依赖都被 mock 掉了）。这类「只在真实端到端跑批才暴露」的
未定义名称错误，靠补端到端用例成本太高，用静态分析拦截性价比最高。

因此本测试用 pyflakes 扫描主流程模块，断言**不存在未定义名称**。
它不能替代端到端冒烟，但能把「改一行删掉变量、另一行还在用」这类错误
挡在跑批之前——一次跑批 4.5 小时，冒烟 + 静态检查是必要的两道保险。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 主流程模块：只要这些文件出现未定义名称，跑批必然整轮作废
GUARDED = [
    "agent/orchestrator.py",
    "agent/solver.py",
    "agent/verifier.py",
    "agent/lean_gate.py",
    "agent/adversarial_verifier.py",
    "agent/sub_goal_solver.py",
    "agent/blueprint_planner.py",
    "agent/collaborative_solver.py",
    "agent/lean_pre_verifier.py",
    "user_agent.py",
]


def _pyflakes_available() -> bool:
    try:
        import pyflakes  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _pyflakes_available(),
                    reason="pyflakes 未安装，跳过静态未定义名称检查")
def test_no_undefined_names_in_main_flow():
    """主流程模块不得存在未定义名称（2026-08-31 is_proof 事故回归）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *GUARDED],
        cwd=ROOT, capture_output=True, text=True,
    )
    # pyflakes 退出码非 0 只是"有告警"，具体看输出内容
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines()
             if "undefined name" in ln]
    assert not lines, (
        "主流程存在未定义名称，跑批会整轮 NameError：\n"
        + "\n".join(lines)
        + "\n\n（2026-08-31 事故：#45 删掉 is_proof 赋值，verifier.run 仍在用）"
    )


def test_is_proof_still_defined_before_verifier_call():
    """针对性回归：`is_proof` 必须在 orchestrator.run 内被赋值后再传给 verifier。

    只查源码文本，不依赖 pyflakes。即便将来有人再次删掉赋值行，
    这个断言会先于 pyflakes 给出人话解释。
    """
    path = os.path.join(ROOT, "agent", "orchestrator.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    assert "is_proof=is_proof" in src, (
        "orchestrator.py 里已找不到 `is_proof=is_proof`（verifier.run 的入参）。"
        "若是有意重构，请同步更新本测试。"
    )
    # `is_proof = ` 必须出现（赋值），且出现在调用之前
    assign_idx = src.find("is_proof = (")
    if assign_idx < 0:
        assign_idx = src.find("is_proof = getattr")
    call_idx = src.find("is_proof=is_proof")
    assert assign_idx >= 0, (
        "orchestrator.py 使用了 is_proof 但没有赋值 —— "
        "2026-08-31 的 NameError 就是这样产生的"
    )
    assert assign_idx < call_idx, (
        f"is_proof 的赋值（第 {src[:assign_idx].count(chr(10)) + 1} 行）"
        f"必须早于使用处（第 {src[:call_idx].count(chr(10)) + 1} 行）"
    )
