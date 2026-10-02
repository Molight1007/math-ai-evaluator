# -*- coding: utf-8 -*-
"""验证 MCP 修法：把 LEAN_PROJECT_PATH 指向闭包目录后，MCP 通道能否真正生效。

不重启评测、不改任何配置，只在**本进程**里设环境变量做验证。
"""
import logging
import os
import sys
import time

REPO = "/home/ubuntu/mathpilot"
CLOSURE = os.path.join(REPO, "deploy", "mathlib-olean")
LEAN = os.path.join(REPO, "deploy", "lean-4.31.0-linux", "bin", "lean")

# ---- 关键：本进程内设置（不影响正在跑的评测）----
os.environ["LEAN_PROJECT_PATH"] = CLOSURE
os.environ.setdefault("LEAN_MCP_ALLOW_NET", "1")
os.environ.setdefault("LEAN_MCP_TIMEOUT_FLOOR", "300")

sys.path.insert(0, REPO)
os.chdir(REPO)

logging.basicConfig(level=logging.DEBUG,
                    format="%(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)

from tools.lean_local.lean_bridge import (  # noqa: E402
    get_lean_backend, _mcp_gate_ok, _detect_mcp_proxy_python,
    _detect_lean_project_dir, _is_mcp_project_root, _ensure_min_lake_project,
    _compile_lean,
)

print("=" * 76)
print("一、前置条件")
print("=" * 76)
print("  LEAN_PROJECT_PATH        =", os.environ["LEAN_PROJECT_PATH"])
print("  get_lean_backend()       =", get_lean_backend())
print("  _detect_lean_project_dir =", repr(_detect_lean_project_dir()))
print("  _detect_mcp_proxy_python =", repr(_detect_mcp_proxy_python()))
print("  闭包目录存在             =", os.path.isdir(CLOSURE))
print("  Mathlib/ 存在            =", os.path.isdir(os.path.join(CLOSURE, "Mathlib")))
print()
print("  _is_mcp_project_root(闭包) 调用前 =", _is_mcp_project_root(CLOSURE))
print("  _ensure_min_lake_project(闭包)     =", _ensure_min_lake_project(CLOSURE))
print("  _is_mcp_project_root(闭包) 调用后 =", _is_mcp_project_root(CLOSURE))
print("  ★ _mcp_gate_ok(闭包)              =", _mcp_gate_ok(CLOSURE))

print()
print("=" * 76)
print("二、实际编译一次（观察是否走 mcp 后端；MCP 冷启动可能 60-300s）")
print("=" * 76)
CODE_verify_mcp_fix = ("import Mathlib.Tactic.NormNum\n"
        "example : (19 * 3 * 2 ^ 18 : ℕ) = 14942208 := by norm_num\n")

t0 = time.time()
res = _compile_lean(CODE_verify_mcp_fix, CLOSURE, lean_executable=LEAN, timeout=600)
dt = time.time() - t0
print()
print(f"  返回: {str(res)[:300]}")
print(f"  耗时: {dt:.1f}s")
print()
print("=" * 76)
print("三、结论")
print("=" * 76)
if res.get("ok"):
    print("  ✅ 编译通过 —— MCP 修法有效（上面若出现『★ 走 mcp 后端』即为走了 MCP）")
else:
    print("  ⚠️ 编译未通过，见上面 error；据此判断是 MCP 起不来还是 Lean 代码问题")
