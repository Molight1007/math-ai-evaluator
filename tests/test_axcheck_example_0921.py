# -*- coding: utf-8 -*-
"""axiom 检查对 `example` 形式的覆盖 —— 2026-09-21 修复的防回归测试。

背景
    `tools/lean_local/lean_bridge.py` 的 axiom 检查（用 lean-lsp-mcp 的
    `lean_verify` 查定理依赖公理、捕捉**间接引入**的 sorry）原正则
    **只匹配 `theorem`**：
        re.search(r"\btheorem\\s+([A-Za-z_][\\w'.]*)", code)
    对 `example : ... := by ...` 整体跳过 —— 而 MathPilot 生成的验证代码
    **大量使用 `example`**。实测：`ansverify_880065_88791123086.lean`
    = `example : (2:ℚ)*(-2) = -4 := by norm_num` 编译 ok=True，
    但 axiom 检查静默跳过（日志里既无"通过"也无"sorryAx"）。

修复
    先找 `theorem`/`lemma`；找不到时把**首个 `example`** 改写成命名 theorem
    （`_mp_axcheck`）的副本，**重新诊断**（LSP 才会加载新名字）后按名验证。

本测试两层防回归
    ① 源码探针：确保关键片段没有被改回去；
    ② 行为形态：把同一套正则固化下来，验证提取/改写行为符合预期。
    ⚠️ 局限：② 是"同形态固化"而非直接调用源码内联逻辑——若将来把该逻辑
       抽成模块级函数，应改为直接 import 调用。
"""
from __future__ import annotations

import io
import os
import re
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "lean_local", "lean_bridge.py")

# 与 lean_bridge.py 修复后保持同形态
_THEOREM_RE = re.compile(r"\b(?:theorem|lemma)\s+([A-Za-z_][\w'.]*)")
_EXAMPLE_RE = re.compile(r"(?m)^[ \t]*example\s*:")
_EXAMPLE_SUB = re.compile(r"(?m)^([ \t]*)example\s*:")
_AXNAME = "_mp_axcheck"


def pick_verify_name(code: str):
    """返回 (待验证的定理名, 可能被改写后的代码)。找不到返回 (None, code)。"""
    m = _THEOREM_RE.search(code or "")
    if m:
        return m.group(1), code
    if _EXAMPLE_RE.search(code or ""):
        alt = _EXAMPLE_SUB.sub(r"\1theorem " + _AXNAME + " :",
                               code or "", count=1)
        if alt != (code or ""):
            return _AXNAME, alt
    return None, code


class TestSourceProbe(unittest.TestCase):
    """① 源码探针：修复关键片段必须仍在。"""

    @classmethod
    def setUpClass(cls):
        cls.src = io.open(SRC, encoding="utf-8").read()

    def test_axiom_check_runs_when_env_not_zero(self):
        # 2026-10-01：开关统一走 switch_registry（注册表默认 True = "非 0" 语义）
        self.assertIn('_sw_bool("lean_mcp_verify_axioms")', self.src)

    def test_axiom_check_switch_registered_default_true(self):
        """行为层断言：该开关必须已注册且默认开（不再依赖源码字面量）。"""
        from agent.switch_registry import get_bool
        self.assertTrue(get_bool("lean_mcp_verify_axioms"))

    def test_regex_covers_theorem_and_lemma(self):
        self.assertIn(r"(?:theorem|lemma)\s+([A-Za-z_][\w'.]*)", self.src,
                      "axiom 检查正则退化：应同时覆盖 theorem 与 lemma")

    def test_old_theorem_only_regex_is_gone(self):
        # 旧写法（只认 theorem）不应再现；用精确形态避免误伤注释
        self.assertNotIn(r'_tm = re.search(\n                        r"\btheorem', self.src)

    def test_example_rewrite_branch_exists(self):
        self.assertIn("_mp_axcheck", self.src)
        self.assertIn("axiom 检查改用 example 改写副本", self.src)

    def test_reparse_after_rewrite(self):
        """改写后必须重新诊断，否则 LSP 不知道新名字。"""
        self.assertIn("_px.request(lean_file, timeout=max(timeout, 90.0))",
                      self.src)


class TestNamePicking(unittest.TestCase):
    """② 行为形态。"""

    def test_theorem_uses_its_own_name(self):
        name, alt = pick_verify_name("theorem foo : 1 = 1 := rfl")
        self.assertEqual(name, "foo")
        self.assertIn("theorem foo", alt)

    def test_lemma_supported(self):
        name, _ = pick_verify_name("lemma bar : 1 = 1 := rfl")
        self.assertEqual(name, "bar")

    def test_example_is_rewritten(self):
        code = "example : (2 : \u211a) * (-2) = -4 := by norm_num"
        name, alt = pick_verify_name(code)
        self.assertEqual(name, _AXNAME)
        self.assertIn("theorem " + _AXNAME + " :", alt)
        self.assertNotIn("example :", alt)

    def test_example_rewrite_preserves_indentation(self):
        code = "namespace X\n  example : True := trivial\nend X"
        name, alt = pick_verify_name(code)
        self.assertEqual(name, _AXNAME)
        self.assertIn("\n  theorem " + _AXNAME + " :", alt)

    def test_only_first_example_rewritten(self):
        code = "example : True := trivial\nexample : True := trivial"
        name, alt = pick_verify_name(code)
        self.assertEqual(name, _AXNAME)
        self.assertEqual(alt.count("theorem " + _AXNAME + " :"), 1)
        self.assertEqual(alt.count("example :"), 1)

    def test_mixed_theorem_wins_over_example(self):
        code = "example : True := trivial\ntheorem real_one : True := trivial"
        name, alt = pick_verify_name(code)
        self.assertEqual(name, "real_one")
        self.assertEqual(alt, code)

    def test_no_proof_declaration_returns_none(self):
        name, alt = pick_verify_name("import Mathlib.Tactic\n#check Nat")
        self.assertIsNone(name)
        self.assertEqual(alt, "import Mathlib.Tactic\n#check Nat")

    def test_empty_and_none(self):
        self.assertEqual(pick_verify_name("")[0], None)
        self.assertEqual(pick_verify_name(None)[0], None)

    def test_example_inside_comment_is_not_rewritten(self):
        """`-- example : ...` 行首有注释符号，不应被当成 example 声明。"""
        code = "-- example : True := trivial\ntheorem t : True := trivial"
        name, _ = pick_verify_name(code)
        self.assertEqual(name, "t")

    def test_qualified_theorem_name_kept(self):
        name, _ = pick_verify_name("theorem Foo.bar : True := trivial")
        self.assertEqual(name, "Foo.bar")


if __name__ == "__main__":
    unittest.main()
