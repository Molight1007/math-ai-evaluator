#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 LeanBridge 是否已真正接入 Mathlib（AI 解答 → Lean 形式化 → Mathlib 硬验证）。

用法（需先在本机完成 mathlib 本地编译）：
    python tests/validate_mathlib.py

验证内容：
  1) 自动探测的 Lean 工程目录是否指向已编译好 Mathlib 的工程；
  2) _mathlib_ready() 是否正确识别核心 tactic 模块（Mathlib.Tactic）已就绪；
  3) 用一段「import Mathlib.Tactic + norm_num」的证明直接走 _compile 编译，确认 Mathlib 真正可用；
  4) 用 Mock client 跑一次完整的 verify()（NL→Lean→编译→分析），确认整条链路可贯通。

注：本地 mathlib 采用「部分编译」布局——因 v4.31.0 兼容问题缺失 517 个冷门
模块（代数几何/拓扑/层论），全量 import Mathlib 不可用；核心 Mathlib.Tactic
（norm_num/ring/omega/linarith/positivity/aesop/simp）已编译，跑分证明够用。
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agent"))

from agent.lean_bridge import LeanBridge, _detect_lean_project_dir  # noqa: E402


class MockClient:
    """返回一段固定的、依赖 Mathlib tactic 的 Lean 证明。"""

    def chat(self, messages=None, temperature=0.0, max_tokens=0):
        # 模拟「书生/Intern-S1」把推理转化为 Lean 代码：用到 Mathlib 的 norm_num
        return (
            "```lean\n"
            "import Mathlib.Tactic\n"
            "theorem validate_add : (1 : ℝ) + (1 : ℝ) = (2 : ℝ) := by\n"
            "  norm_num\n"
            "```"
        )


def _banner(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    _banner("1) 自动探测 Lean 工程目录")
    pdir = _detect_lean_project_dir()
    print("lean_project_dir =", repr(pdir))
    if not pdir:
        print("[FAIL] 未探测到任何带 Mathlib 的 Lean 工程目录")
        return 1
    print("[OK] 探测到工程目录")

    _banner("2) 构造 LeanBridge 并检查 Mathlib 是否已编译就绪")
    bridge = LeanBridge(MockClient(), config=None, budget=None)
    # 强制刷新 readiness 缓存（避免进程内旧缓存）
    bridge._mathlib_ready_cache = None
    ready = bridge._mathlib_ready()
    print("lean_available =", bridge.lean_available)
    print("mathlib_ready  =", ready)
    if not ready:
        print("[FAIL] Mathlib 核心模块（Mathlib.Tactic）尚未编译，请先完成 mathlib 本地编译")
        print("       工程目录:", pdir)
        return 1
    print("[OK] Mathlib 已编译就绪（Mathlib.Tactic 可用）")

    _banner("3) 直接编译一段 import Mathlib.Tactic + norm_num 的证明")
    code = ("import Mathlib.Tactic\n"
            "theorem validate_add : (1 : ℝ) + (1 : ℝ) = (2 : ℝ) := by\n"
            "  norm_num\n")
    fname = "validate_%d.lean" % int(time.monotonic() * 1e6)
    comp = bridge._compile(code, pdir, lean_filename=fname)
    try:
        os.remove(os.path.join(pdir, fname))
    except OSError:
        pass
    print("compile result:", comp)
    if not comp.get("ok"):
        print("[FAIL] Mathlib 证明编译未通过：", comp.get("error"))
        return 1
    print("[OK] import Mathlib.Tactic + norm_num 编译通过，Mathlib 真实可用")

    _banner("4) 完整 verify() 链路（Mock client → NL→Lean→编译）")
    report = bridge.verify(
        problem="证明 1+1=2。",
        reasoning="显然成立。",
        domain="数学",
        timeout=120.0,
    )
    print("BugReport:", report)
    if report is None:
        print("[FAIL] verify 返回 None")
        return 1
    print("[OK] verify 返回 verdict =", report.verdict)

    _banner("总结")
    print("Mathlib 接入验证通过：LeanBridge 已能加载并使用 Mathlib 做硬验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
