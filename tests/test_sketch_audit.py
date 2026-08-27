#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 #28 骨架(sketch) Lean 语法审核链路（复用 formalize_problem + formal_gaps）。

用法：
    python tests/test_sketch_audit.py

验证内容：
  1) _analyze_formal_gaps 确定性单元测试（不依赖 Lean）：空错误→[]，样本错误→
     正确抽取 missing_lemma / missing_module / type_mismatch；
  2) LeanBridge.audit_sketch 返回结构 {verdict, gaps, ...}；Lean 可用且工程目录
     就绪时，well-typed 骨架 → verdict="ok"、gaps 为空；
  3) LeanPreVerifier.generate_and_audit_sketch 接线正确（写 ctx.sketch_audit）；
  4) 相关模块导入健全性。

注：Lean 编译集成断言在「本机 Lean 不可用 / mathlib 工程目录正在构建中」时自动
SKIP（逻辑已由确定性单元测试覆盖）。待 mathlib 本地编译完成后，重跑本测试即可
贯通完整 compile 链路（与 tests/validate_mathlib.py 一并）。
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agent"))

from agent.lean_bridge import LeanBridge, _analyze_formal_gaps
from agent.lean_pre_verifier import LeanPreVerifier
from agent.base import TaskContext


SKELETON_OK = (
    '{"formal_spec": "先证交换律，再归纳", '
    '"lean_code": "theorem subgoal_1 : \\u2200 (n : Nat), n + 0 = n := by sorry\\n'
    'theorem main_goal : 1 + 1 = 2 := by sorry"}'
)
SKELETON_BAD = (
    '{"formal_spec": "坏骨架", '
    '"lean_code": "theorem subgoal_1 : UnknownMod.foo := by sorry"}'
)


class MockClient:
    """忽略 prompt，固定返回指定 JSON 字符串（模拟书生/Intern-S1）。"""

    def __init__(self, payload):
        self.payload = payload

    def chat(self, messages=None, temperature=0.0, max_tokens=0):
        return self.payload


def _cfg():
    c = types.SimpleNamespace()
    c.enable_lean_preverify = True
    c.preverify_max_rounds = 2
    c.preverify_timeout = 60.0
    c.enable_sketch_audit = True
    c.lean_timeout = 60.0
    c.lean_executable = ""
    c.lean_project_dir = ""
    return c


def main():
    fails = []

    # --- 1) 确定性单元测试（不依赖 Lean）---
    assert _analyze_formal_gaps("") == [], "空错误应返回空缺口"
    err = ("error: unknown identifier: MyLemma\n"
           "error: unknown module prefix 'Mathlib'\n"
           "error: type mismatch\n  foo : Nat\n  expected Int")
    g = _analyze_formal_gaps(err)
    kinds = [x["kind"] for x in g]
    assert "missing_lemma" in kinds, "应抽取 missing_lemma"
    assert "missing_module" in kinds, "应抽取 missing_module"
    assert "type_mismatch" in kinds, "应抽取 type_mismatch"
    print("gap 抽取单元测试通过:", kinds)

    # --- 2) 集成路径（依赖 Lean 工程目录）---
    b = LeanBridge(MockClient(SKELETON_OK), config=None, budget=None)
    if not b.lean_available:
        print("[SKIP] 本机 Lean 不可用，跳过编译集成断言（逻辑/结构仍校验）")
        r = b.audit_sketch("骨架", "题", "", timeout=30.0)
        assert set(["verdict", "gaps"]).issubset(r.keys()), "audit_sketch 应返回 verdict/gaps"
        print("结构校验通过（verdict=%s）" % r["verdict"])
        print("SKIP-OK")
        return 0

    r = b.audit_sketch("证明 1+1=2 的骨架", "证明 1+1=2", "数学", timeout=120.0)
    print("audit_sketch(ok):", r["verdict"], "gaps=", len(r.get("gaps", [])))
    err_txt = (r.get("error") or "").lower()
    mid_build = ("invalid" in err_txt) or ("reconfigure" in err_txt) or ("configuration" in err_txt)
    if r["verdict"] == "ok":
        assert r.get("gaps") == [], "成功路径 gaps 应为空"
    elif mid_build:
        print("[SKIP] mathlib 工程目录正在构建中（compiled configuration is invalid），"
              "跳过编译断言；逻辑已由 gap 单元测试验证")
    else:
        fails.append("audit_sketch 成功路径异常: %s" % r)

    # 失败路径：返回结构正确（缺口交给确定性单测覆盖）
    b2 = LeanBridge(MockClient(SKELETON_BAD), config=None, budget=None)
    r2 = b2.audit_sketch("坏骨架", "x", "", timeout=120.0)
    print("audit_sketch(bad):", r2["verdict"], "gaps=", r2.get("gaps"))
    assert "verdict" in r2 and "gaps" in r2, "失败路径也应返回 verdict/gaps"

    # --- 3) LeanPreVerifier 接线 ---
    ctx = TaskContext(problem="证明 1+1=2", metadata={})
    pv = LeanPreVerifier(MockClient(SKELETON_OK), _cfg())
    pv.generate_and_audit_sketch(ctx, sketch_text="先证交换律，再证 1+1=2")
    print("preverifier sketch_audit:", ctx.sketch_audit.get("verdict"))
    assert "verdict" in ctx.sketch_audit, "preverifier 应写入 ctx.sketch_audit.verdict"

    # --- 4) 导入健全性 ---
    from agent.sub_goal_solver import SubGoalSolverAgent  # noqa: F401
    print("imports OK")

    if fails:
        print("FAIL:", fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
