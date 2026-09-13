# -*- coding: utf-8 -*-
"""档2（2026-09-04）：lean_bridge mcp 后端（lean-lsp-mcp 适配）单元测试。

覆盖：
- 后端开关：默认 bridge / set / 环境变量优先级
- 不可信构造扫描（档1 抽出的共用函数）与 sorry 警告检测
- _compile_via_mcp verdict 语义（mock 代理层，不依赖真实 venv/lean）
- mcp 不可用/异常 → 返回 None（调用方回落 bridge）
- _compile_lean 在 mcp 模式 + lake 工程下分发到 mcp 路径

全部不依赖真实 Lean 环境或 lean-lsp-mcp venv。
"""
import os
import tempfile
import unittest
from unittest import mock

from tools.lean_local import lean_bridge
from tools.lean_local.lean_bridge import (
    _compile_via_mcp, _has_sorry_warning, _is_lake_workdir, _scan_untrusted,
    get_lean_backend, set_lean_backend,
)

_PROJ = r"D:/mathlib4-last_bump_for_v4.31.0"


def _mk_lake_dir():
    """构造一个满足 lean-lsp-mcp 工程根要求的临时目录。

    2026-09-13 修：原先只写 `lakefile.toml`，而 2026-09-12 起门控改用
    `_is_mcp_project_root`（要求 `lean-toolchain` **且** lakefile 之一，
    与 lean-lsp-mcp 的 `require_lean_project_path()` 对齐）；
    仅 lakefile 的目录会被判"非工程根"→ 走 bridge。
    注意 `_ensure_min_lake_project`（autolake）**只对含 Mathlib/*.olean 的
    闭包目录**生效（防止在任意目录乱写文件），所以这里必须自带 lean-toolchain。
    """
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "lakefile.toml"), "w", encoding="utf-8") as f:
        f.write('[package]\nname = "tmp"\n')
    with open(os.path.join(d, "lean-toolchain"), "w", encoding="utf-8") as f:
        f.write("leanprover/lean4:v4.31.0\n")
    return d


class BackendSwitchTest(unittest.TestCase):
    def tearDown(self):
        set_lean_backend("bridge")

    def test_default_backend_is_mcp(self):
        """档2（2026-09-04）起模块默认后端 = **mcp**（用户要求 MCP 必须可用）；
        环境不可用/门控未过时由 `_compile_lean` 自动回落 bridge。

        注意与 tearDown 的耦合：不能用 get_lean_backend() 断言"默认值"
        （前序用例的 tearDown 会把模块态改成 bridge）→ 直接锁模块常量 + 显式设置。
        """
        os.environ.pop("LEAN_BACKEND", None)
        self.assertEqual(
            lean_bridge._LEAN_BACKEND, "mcp",
            "模块默认后端应为 mcp（2026-09-04 档2 决策）")
        set_lean_backend("mcp")
        self.assertEqual(get_lean_backend(), "mcp")

    def test_set_and_get(self):
        set_lean_backend("mcp")
        self.assertEqual(get_lean_backend(), "mcp")
        set_lean_backend("bridge")
        self.assertEqual(get_lean_backend(), "bridge")

    def test_invalid_ignored(self):
        set_lean_backend("mcp")
        set_lean_backend("bogus")
        self.assertEqual(get_lean_backend(), "mcp")

    def test_env_overrides_module(self):
        set_lean_backend("bridge")
        with mock.patch.dict(os.environ, {"LEAN_BACKEND": "mcp"}):
            self.assertEqual(get_lean_backend(), "mcp")
        self.assertEqual(get_lean_backend(), "bridge")

    def test_env_invalid_falls_back(self):
        set_lean_backend("mcp")
        with mock.patch.dict(os.environ, {"LEAN_BACKEND": "nope"}):
            self.assertEqual(get_lean_backend(), "mcp")


class UntrustedScanTest(unittest.TestCase):
    def test_clean_code_not_untrusted(self):
        self.assertFalse(_scan_untrusted(
            "import Mathlib.Tactic\n\nexample (x : ℝ) : x ^ 2 ≥ 0 := by\n  positivity\n"))

    def test_sorry_hit(self):
        self.assertTrue(_scan_untrusted("theorem t : True := by sorry"))

    def test_axiom_hit(self):
        self.assertTrue(_scan_untrusted("axiom magic : False"))

    def test_unsafe_hit(self):
        self.assertTrue(_scan_untrusted("unsafe def f : Nat := 0"))

    def test_implemented_by_hit(self):
        self.assertTrue(_scan_untrusted("opaque f : Nat\n@[implemented_by f]"))

    def test_sorry_warning_text(self):
        self.assertTrue(_has_sorry_warning("x.lean:3:9: warning: declaration uses `sorry`"))
        self.assertFalse(_has_sorry_warning("no warning here"))

    def test_is_lake_workdir(self):
        d = _mk_lake_dir()
        self.assertTrue(_is_lake_workdir(d))
        tmp = tempfile.mkdtemp()
        self.assertFalse(_is_lake_workdir(tmp))


class CompileViaMcpTest(unittest.TestCase):
    """mock 代理层，验证 verdict 语义（bridge/mcp 判定对齐）。"""

    def setUp(self):
        # 模块级 proxy 单例跨测试泄漏 → 每个用例重置
        lean_bridge._MCP_PROXY = None

    def tearDown(self):
        lean_bridge._MCP_PROXY = None

    def _stub_proxy(self, items=None, goal=None, ok=True):
        py = mock.Mock()
        client = mock.MagicMock()
        client.request.return_value = {"ok": ok, "items": items or [],
                                       "goal": goal, "error": ""}
        py.return_value = client
        return mock.patch("tools.lean_local.lean_bridge._detect_mcp_proxy_python",
                          return_value="C:/py.exe"), \
            mock.patch("tools.lean_local.lean_bridge._LeanMcpProxyClient", py), client

    def test_error_items_fail_with_locations(self):
        p1, p2, client = self._stub_proxy(items=[
            {"severity": "error", "message": "Unknown constant `Foo`",
             "line": 3, "column": 7}])
        with p1, p2:
            r = _compile_via_mcp("C:/p/verify.lean", "import Mathlib.Tactic",
                                 _PROJ, timeout=60.0, allow_sorry=False)
        self.assertIsNotNone(r)
        self.assertFalse(r["ok"])
        self.assertIn("verify.lean:3:7", r["error"])
        self.assertIn("Unknown constant `Foo`", r["error"])

    def test_clean_pass(self):
        p1, p2, client = self._stub_proxy(items=[])
        with p1, p2:
            r = _compile_via_mcp("C:/p/verify.lean",
                                 "example : 1 = 1 := by rfl",
                                 _PROJ, 60.0, allow_sorry=False)
        self.assertEqual(r, {"ok": True, "error": ""})

    def test_sorry_warning_fail_strict_pass_decl(self):
        # 声明模式（allow_sorry=True）：有 sorry 警告仍放行
        items_warn = [{"severity": "warning", "message": "declaration uses `sorry`",
                       "line": 3, "column": 9}]
        p1, p2, _ = self._stub_proxy(items=items_warn)
        with p1, p2:
            r = _compile_via_mcp("C:/p/v.lean", "theorem t : True := by sorry",
                                 _PROJ, 60.0, allow_sorry=True)
        self.assertEqual(r, {"ok": True, "error": ""})
        # 后置验证：拒绝
        p1, p2, _ = self._stub_proxy(items=items_warn)
        with p1, p2:
            r = _compile_via_mcp("C:/p/v.lean", "theorem t : True := by sorry",
                                 _PROJ, 60.0, allow_sorry=False)
        self.assertFalse(r["ok"])

    def test_axiom_in_source_rejected_strict(self):
        # 编译无 error，但源码含 axiom → 后置验证拒绝
        p1, p2, _ = self._stub_proxy(items=[])
        with p1, p2:
            r = _compile_via_mcp("C:/p/v.lean", "axiom magic : 1 = 2",
                                 _PROJ, 60.0, allow_sorry=False)
        self.assertFalse(r["ok"])

    def test_goal_appended_on_first_error(self):
        p1, p2, client = self._stub_proxy(
            items=[{"severity": "error", "message": "linarith failed",
                    "line": 5, "column": 3}],
            goal="⊢ x ≤ 1")
        with p1, p2, mock.patch.dict(os.environ, {}):
            r = _compile_via_mcp("C:/p/v.lean", "code", _PROJ, 60.0,
                                 allow_sorry=False)
        self.assertFalse(r["ok"])
        self.assertIn("[lean-lsp-mcp]", r["error"])
        self.assertIn("⊢ x ≤ 1", r["error"])
        # 第二次 request（goal 定位）确实发出
        self.assertEqual(client.request.call_count, 2)

    def test_no_proxy_env_returns_none(self):
        with mock.patch("tools.lean_local.lean_bridge._detect_mcp_proxy_python",
                        return_value=""):
            r = _compile_via_mcp("C:/p/v.lean", "code", _PROJ, 60.0,
                                 allow_sorry=False)
        self.assertIsNone(r)

    def test_proxy_exception_returns_none_and_closes(self):
        client = mock.MagicMock()
        client.request.side_effect = RuntimeError("proxy 崩溃")
        py = mock.Mock(return_value=client)
        with mock.patch("tools.lean_local.lean_bridge._detect_mcp_proxy_python",
                        return_value="C:/py.exe"), \
             mock.patch("tools.lean_local.lean_bridge._LeanMcpProxyClient", py):
            r = _compile_via_mcp("C:/p/v.lean", "code", _PROJ, 60.0,
                                 allow_sorry=False)
        self.assertIsNone(r)
        client.close.assert_called_once()

    def test_proxy_ok_false_returns_none(self):
        p1, p2, _ = self._stub_proxy(ok=False)
        with p1, p2:
            r = _compile_via_mcp("C:/p/v.lean", "code", _PROJ, 60.0,
                                 allow_sorry=False)
        self.assertIsNone(r)


class CompileLeanDispatchTest(unittest.TestCase):
    """_compile_lean 在 mcp 模式 + lake 工程下应分发到 mcp 路径。"""

    def tearDown(self):
        set_lean_backend("bridge")

    def test_mcp_dispatch_in_lake_workdir(self):
        d = _mk_lake_dir()
        code = "import Mathlib.Tactic\n\nexample : 1 = 1 := by rfl\n"
        with mock.patch("tools.lean_local.lean_bridge._compile_via_mcp",
                        return_value={"ok": True, "error": ""}) as m_via:
            set_lean_backend("mcp")
            r = lean_bridge._compile_lean(code, d, timeout=30.0,
                                           lean_filename="verify.lean")
        self.assertTrue(r["ok"])
        m_via.assert_called_once()

    def test_bridge_does_not_dispatch(self):
        d = _mk_lake_dir()
        code = "import Mathlib.Tactic\n\nexample : 1 = 1 := by rfl\n"
        with mock.patch("tools.lean_local.lean_bridge._compile_via_mcp") as m_via:
            set_lean_backend("bridge")
            # 真实 lake 不可用则 _compile_lean 走命令失败——改用 mock subprocess
            with mock.patch("tools.lean_local.lean_bridge.subprocess.run") as m_run:
                m_run.return_value = mock.MagicMock(
                    returncode=0, stderr="", stdout="")
                r = lean_bridge._compile_lean(code, d, timeout=30.0,
                                               lean_filename="verify.lean")
        self.assertTrue(r["ok"])
        m_via.assert_not_called()

    def test_mcp_not_dispatch_in_plain_dir(self):
        # 非 lake 工程（比赛临时目录直编场景）→ mcp 不适用，走 bridge
        d = tempfile.mkdtemp()
        code = "example : 1 = 1 := by rfl\n"
        with mock.patch("tools.lean_local.lean_bridge._compile_via_mcp") as m_via, \
             mock.patch("tools.lean_local.lean_bridge.subprocess.run") as m_run:
            m_run.return_value = mock.MagicMock(returncode=0, stderr="",
                                                stdout="")
            set_lean_backend("mcp")
            r = lean_bridge._compile_lean(code, d, timeout=30.0,
                                           lean_filename="verify.lean")
        self.assertTrue(r["ok"])
        m_via.assert_not_called()


if __name__ == "__main__":
    unittest.main()
