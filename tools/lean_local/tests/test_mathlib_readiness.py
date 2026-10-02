# -*- coding: utf-8 -*-
"""回归测试：Mathlib 就绪判定与 import 归一化（2026-09-21 云端全降级修复）。

背景（云端实测，2026-09-21）
---------------------------
云端 `deploy/cloud_run.env` 为让 MCP 通道生效，把 `LEAN_PROJECT_PATH`
指向了 **裁剪闭包** `deploy/mathlib-olean`（由 5 个具体入口 BFS 构建，
**没有** `Mathlib/Tactic.olean` 聚合入口，但有 `Mathlib/Tactic/NormNum.olean`
等具体模块）。

于是 `_lean_project_dir`（= `_detect_lean_project_dir()` 的候选 0）非空且
恰为裁剪闭包根 ⇒ `_mathlib_ready()` 走 `if pdir:` 分支 ⇒ 该分支此前只认
`.lake/**/Tactic.olean` 与 `pdir/Mathlib/Tactic.olean` ⇒ **恒 False**
⇒ `verify()` / `verify_answer()` / `run_pre_verification()` /
`audit_sketch()` 四处全部跳过 `_prepend_mathlib_import()`
⇒ 原始 `import Mathlib.Tactic` 原样送编译 ⇒ 闭包内无该 olean ⇒ 编译必败
⇒ `verdict` 恒 `unknown`、`lean_valid` 恒 `False`。

服务器取证（只读）：
  - trash 落点 `<repo>/deploy/mathlib-olean/_lean_trash`（204 文件）⇒ pdir 非空
  - `preverify_*.lean` 首行 = `import Mathlib.Tactic`（未归一化）
  - `daglogic_*.lean` 前 3 行 = 3 条 `import Mathlib.Tactic.*`（已归一化，
    该站点 L2259 无条件调用归一化）
  - `ansverify_*.lean` 连 import 行都没有

本地为何不暴露：本地另有带聚合入口的 `vendor/.../closure-full`（及
`data/mathlib-closure`），`_detect_lean_project_dir()` 命中 ⇒ 判据为真。

本测试用**伪造闭包目录**复现云端布局，不依赖本机是否安装 Lean。
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tools.lean_local import lean_bridge as lb


# ---------------------------------------------------------------------------
# 工具：伪造闭包 / 构造 bridge
# ---------------------------------------------------------------------------
def _make_closure(root: str, with_aggregate_entry: bool) -> str:
    """造一个假闭包目录。

    ``with_aggregate_entry=True``  → 同时含 `Mathlib/Tactic.olean`（full 形态）
    ``with_aggregate_entry=False`` → 仅含具体 tactic 模块（裁剪闭包形态，云端）
    """
    mdir = os.path.join(root, "Mathlib")
    tdir = os.path.join(mdir, "Tactic")
    os.makedirs(tdir, exist_ok=True)
    if with_aggregate_entry:
        with open(os.path.join(mdir, "Tactic.olean"), "wb"):
            pass
    for name in ("NormNum", "Ring", "Linarith", "Positivity"):
        with open(os.path.join(tdir, name + ".olean"), "wb"):
            pass
    return root


class _Cfg:
    """极简 config 存根：只需 `lean_project_dir`。"""

    def __init__(self, pdir: str = ""):
        self.lean_project_dir = pdir


def _make_bridge(pdir: str) -> lb.LeanBridge:
    b = lb.LeanBridge(client=mock.Mock(), config=_Cfg(pdir), budget=None)
    b._lean_env_cache = {"available": True}   # 绕开真实 Lean 可执行文件探测
    b._mathlib_ready_cache = None             # 清缓存，避免跨用例污染
    return b


class _NoRepoRoots:
    """上下文管理器：把仓库内默认闭包路径清空，隔离来自真实仓库的干扰。"""

    def __enter__(self):
        self._p = mock.patch.object(lb, "_repo_closure_roots", return_value=[])
        self._p.start()
        self._lp = os.environ.pop("LEAN_PATH", None)
        return self

    def __exit__(self, *exc):
        self._p.stop()
        if self._lp is not None:
            os.environ["LEAN_PATH"] = self._lp
        else:
            os.environ.pop("LEAN_PATH", None)
        return False


class _Env:
    """临时目录 + 可选 LEAN_PATH 上下文。"""

    def __init__(self, lean_path: str = ""):
        self.lean_path = lean_path

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
        self._lp = os.environ.get("LEAN_PATH")
        if self.lean_path:
            os.environ["LEAN_PATH"] = self.lean_path
        else:
            os.environ.pop("LEAN_PATH", None)
        return self.tmp

    def __exit__(self, *exc):
        if self._lp is not None:
            os.environ["LEAN_PATH"] = self._lp
        else:
            os.environ.pop("LEAN_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


# ---------------------------------------------------------------------------
# 1) _has_mathlib_tactics：判据本身
# ---------------------------------------------------------------------------
class HasMathlibTacticsTest(unittest.TestCase):

    def test_full_closure_with_aggregate_entry(self):
        with _Env() as tmp:
            root = _make_closure(os.path.join(tmp, "full"), True)
            self.assertTrue(lb._has_mathlib_tactics(root))

    def test_cropped_closure_without_aggregate_entry(self):
        """★ 核心：裁剪闭包（无聚合入口）也应判为「有 Mathlib tactic」。"""
        with _Env() as tmp:
            root = _make_closure(os.path.join(tmp, "cropped"), False)
            self.assertFalse(
                os.path.isfile(os.path.join(root, "Mathlib", "Tactic.olean")))
            self.assertTrue(lb._has_mathlib_tactics(root))

    def test_empty_dir_and_empty_string(self):
        with _Env() as tmp:
            empty = os.path.join(tmp, "empty")
            os.makedirs(empty, exist_ok=True)
            self.assertFalse(lb._has_mathlib_tactics(empty))
        self.assertFalse(lb._has_mathlib_tactics(""))


# ---------------------------------------------------------------------------
# 2) _mathlib_ready()：云端分支（pdir 即裁剪闭包）必须为 True
# ---------------------------------------------------------------------------
class MathlibReadyTest(unittest.TestCase):

    def test_ready_when_pdir_is_cropped_closure(self):
        """★ 云端回归：pdir = 裁剪闭包（无聚合入口）→ 修复前 False，修复后 True。

        这是本次「Lean 验证全降级」的直接回归点：
        `_mathlib_ready()` 为 False ⇒ 调用点跳过 import 归一化 ⇒ 必败。
        """
        with _NoRepoRoots(), _Env() as tmp:
            cropped = _make_closure(os.path.join(tmp, "olean"), False)
            b = _make_bridge(cropped)
            self.assertTrue(b._mathlib_ready())

    def test_ready_when_pdir_is_full_closure(self):
        with _NoRepoRoots(), _Env() as tmp:
            full = _make_closure(os.path.join(tmp, "closure-full"), True)
            b = _make_bridge(full)
            self.assertTrue(b._mathlib_ready())

    def test_ready_when_pdir_empty_and_leanpath_has_cropped_closure(self):
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    b = _make_bridge("")
                    self.assertTrue(b._mathlib_ready())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_ready_when_pdir_has_no_mathlib_but_leanpath_does(self):
        """pdir 指向非闭包目录、闭包另经 LEAN_PATH 挂载 ⇒ 仍就绪（统一兜底）。"""
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                plain = os.path.join(tmp, "not_a_closure")
                os.makedirs(plain, exist_ok=True)
                with _Env(cropped):
                    b = _make_bridge(plain)
                    self.assertTrue(b._mathlib_ready())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_not_ready_when_no_mathlib_anywhere(self):
        """机器上确实没有 Mathlib ⇒ 必须仍为 False（不得因本次放宽而误报就绪）。"""
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                with _Env():
                    b = _make_bridge(tmp)
                    self.assertFalse(b._mathlib_ready())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3) import 块形态与归一化
# ---------------------------------------------------------------------------
class ImportNormalizationTest(unittest.TestCase):

    def test_import_block_is_concrete_for_cropped_closure(self):
        """裁剪闭包（LEAN_PATH 指向它）⇒ 必须用 4 行具体模块，而非聚合入口。"""
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    self.assertFalse(lb._mathlib_tactic_entry_available())
                    block = lb._mathlib_import_block()
                    self.assertIn("import Mathlib.Tactic.NormNum", block)
                    self.assertNotIn("import Mathlib.Tactic\n", block + "\n")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_import_block_is_aggregate_for_full_closure(self):
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                full = _make_closure(os.path.join(tmp, "closure-full"), True)
                with _Env(full):
                    self.assertTrue(lb._mathlib_tactic_entry_available())
                    self.assertEqual(lb._mathlib_import_block(),
                                     "import Mathlib.Tactic")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_prepend_replaces_aggregate_import(self):
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    out = lb._prepend_mathlib_import(
                        "import Mathlib.Tactic\nexample : (1:ℚ) = 1 := by norm_num\n")
                    self.assertNotIn("import Mathlib.Tactic\n", out + "\n")
                    self.assertTrue(out.startswith("import Mathlib.Tactic.NormNum"))
                    self.assertIn("norm_num", out)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_prepend_replaces_aggregate_import_with_trailing_comment(self):
        """★ 2026-09-21 加固：`import Mathlib.Tactic -- 注释` 也必须被替换。"""
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    out = lb._prepend_mathlib_import(
                        "import Mathlib.Tactic -- 核心战术\n"
                        "example : (1:ℚ) = 1 := by norm_num\n")
                    self.assertNotIn("import Mathlib.Tactic --", out)
                    self.assertTrue(out.startswith("import Mathlib.Tactic.NormNum"))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_prepend_keeps_concrete_import_and_replaces_bare_mathlib(self):
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    concrete = ("import Mathlib.Tactic.Ring\n"
                                "example : (1:ℚ) = 1 := by norm_num\n")
                    self.assertEqual(lb._prepend_mathlib_import(concrete), concrete)
                    bare = "import Mathlib\nexample : (1:ℚ) = 1 := by norm_num\n"
                    out = lb._prepend_mathlib_import(bare)
                    self.assertNotIn("import Mathlib\n", out + "\n")
                    self.assertTrue(out.startswith("import Mathlib.Tactic.NormNum"))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_prepend_adds_block_when_no_import(self):
        """ansverify 实测形态：原始代码**连 import 行都没有** ⇒ 必须补上。"""
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                with _Env(cropped):
                    raw = "example : (2025 - 1) / 2 = 1012 := by\n  norm_num\n"
                    out = lb._prepend_mathlib_import(raw)
                    self.assertTrue(out.startswith("import Mathlib.Tactic.NormNum"))
                    self.assertIn("example : (2025 - 1) / 2 = 1012", out)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4) 调用点回归：verify_answer 在云端布局下必须把归一化后的代码交给编译器
# ---------------------------------------------------------------------------
class CallSiteRegressionTest(unittest.TestCase):
    """★ 最强回归：模拟云端（pdir=裁剪闭包 + LEAN_PATH=裁剪闭包），断言真正
    送进 `_compile()` 的代码**已归一化**（不再含裸 `import Mathlib.Tactic`）。
    """

    def _run(self, pdir: str, lean_path: str, raw_code: str) -> str:
        captured = {}

        # 注意：patch 打在类上 ⇒ 该函数会成为实例方法 ⇒ 首个形参是 self。
        def _fake_compile(_self, code, work_dir, **kw):
            captured["code"] = code
            return {"ok": False, "error": "stub-compile"}

        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                cropped = _make_closure(os.path.join(tmp, "olean"), False)
                pdir_real = cropped if pdir == "<cropped>" else pdir
                lp = cropped if lean_path == "<cropped>" else lean_path
                with _Env(lp):
                    b = _make_bridge(pdir_real)
                    b._convert_answer_to_lean = lambda *a, **k: raw_code
                    with mock.patch.object(type(b), "_compile", _fake_compile):
                        b.verify_answer(problem="计算 (2025-1)/2。",
                                        reasoning="(2025-1)/2 = 1012。",
                                        answer="1012", domain="代数",
                                        timeout=30.0)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return captured.get("code", "")

    def test_cloud_layout_normalizes_bare_aggregate_import(self):
        """preverify 实测首行 `import Mathlib.Tactic` → 必须被归一化。"""
        raw = ("import Mathlib.Tactic\n"
               "example : (2025 - 1) / 2 = 1012 := by norm_num\n")
        code = self._run("<cropped>", "<cropped>", raw)
        self.assertTrue(code, "verify_answer 未走到编译（提前降级）")
        self.assertNotIn("import Mathlib.Tactic\n", code + "\n")
        self.assertIn("import Mathlib.Tactic.NormNum", code)

    def test_cloud_layout_normalizes_code_without_any_import(self):
        """ansverify 实测形态：无 import 行 → 必须补上具体模块 import。"""
        raw = "example : (2025 - 1) / 2 = 1012 := by\n  norm_num\n"
        code = self._run("<cropped>", "<cropped>", raw)
        self.assertTrue(code, "verify_answer 未走到编译（提前降级）")
        self.assertIn("import Mathlib.Tactic.NormNum", code)

    def test_full_layout_keeps_aggregate_import(self):
        """对照组：完整闭包（有聚合入口）应保留 `import Mathlib.Tactic`。"""
        raw = ("import Mathlib.Tactic\n"
               "example : (2025 - 1) / 2 = 1012 := by norm_num\n")
        with _NoRepoRoots():
            tmp = tempfile.mkdtemp(prefix="mp_mathlib_test_")
            try:
                full = _make_closure(os.path.join(tmp, "closure-full"), True)
                captured = {}

                def _fake_compile(_self, code, work_dir, **kw):
                    captured["code"] = code
                    return {"ok": False, "error": "stub-compile"}

                with _Env(full):
                    b = _make_bridge(full)
                    b._convert_answer_to_lean = lambda *a, **k: raw
                    with mock.patch.object(type(b), "_compile", _fake_compile):
                        b.verify_answer(problem="计算 (2025-1)/2。",
                                        reasoning="(2025-1)/2 = 1012。",
                                        answer="1012", domain="代数",
                                        timeout=30.0)
                self.assertIn("import Mathlib.Tactic\n", captured.get("code", ""))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
