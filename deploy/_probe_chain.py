# -*- coding: utf-8 -*-
"""在服务器上实测 lean_bridge 的探测链 —— 决定主链路能否找到 lean/lake。"""
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

print("cwd        =", REPO)
print("python     =", sys.version.split()[0])
print("LEAN_PATH  =", os.environ.get("LEAN_PATH", "(未设置)"))
print()

print("--- 环境 PATH 前 3 段 ---")
for p in os.environ.get("PATH", "").split(os.pathsep)[:3]:
    print("   ", p)
print("shutil.which('lean') =", shutil.which("lean"))
print("shutil.which('lake') =", shutil.which("lake"))
print()

from tools.lean_local.lean_bridge import (  # noqa: E402
    _detect_lean_executable, detect_lean_environment,
    _detect_mcp_proxy_python, _is_mcp_project_root, _ensure_min_lake_project,
)

exe = _detect_lean_executable()
print("★ _detect_lean_executable() =", repr(exe))
print()
env = detect_lean_environment("")
print("★ detect_lean_environment('') =")
for k, v in env.items():
    print(f"      {k} = {str(v)[:110]}")
print()
print("★ _detect_mcp_proxy_python() =", repr(_detect_mcp_proxy_python()))

print()
print("--- MCP 工程门控（对闭包目录做实测）---")
closure = os.path.join(REPO, "deploy", "mathlib-olean")
print("  work_dir =", closure)
print("  AUTOLAKE =", os.environ.get("LEAN_MCP_AUTOLAKE", "(默认 1)"))
try:
    before = _is_mcp_project_root(closure)
    print("  _is_mcp_project_root  之前:", before)
    ok = _ensure_min_lake_project(closure)
    after = _is_mcp_project_root(closure)
    print("  _ensure_min_lake_project ->", ok)
    print("  _is_mcp_project_root  之后:", after)
    for f in ("lean-toolchain", "lakefile.toml", "lakefile.lean"):
        p = os.path.join(closure, f)
        print(f"      {f}: {'存在' if os.path.exists(p) else '无'}")
except Exception as e:  # noqa: BLE001
    print("  异常:", type(e).__name__, e)
