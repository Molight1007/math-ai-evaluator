# -*- coding: utf-8 -*-
"""lean-lsp-mcp JSONL 前端代理（LeanBridge mcp 后端专用）。

背景
----
评测器主进程（D:/python 3.14）不安装 mcp SDK；lean-lsp-mcp 与其依赖
（mcp / leanclient）装在独立 venv（如 C:/Users/<user>/leanlsp-venv）。
本代理由该 venv 的 python 执行：内部通过 MCP stdio 协议连接
lean-lsp-mcp server（README 同款），对外暴露"一行一个 JSON"的
stdin/stdout 协议，供主进程 spawn 调用：

    请求  {"id": n, "file": "<abs .lean 路径>",
           "goal_line": null | int, "goal_column": null | int}
    响应  {"id": n, "ok": bool, "items": [{"severity","message","line",
           "column"}...], "goal": str|null, "error": str}

职责边界
--------
- 只做"取诊断 / 取指定行目标状态"，不做 verdict 判定（判定语义留在
  agent/lean_bridge.py，保证 bridge/mcp 两后端判定一致）。
- 服务不可用 / 异常一律回 {"ok": false, "error": ...}，由主进程回落 bridge。

环境变量
--------
- LEAN_PROJECT_PATH：lean-lsp-mcp 的工程根（lake 工程，需含已编译 Mathlib）
- LEAN_MCP_SERVER：lean-lsp-mcp server 命令（缺省探测 venv 内可执行文件）
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

_SERVER_CANDIDATES = (
    os.environ.get("LEAN_MCP_SERVER", ""),
    str(Path(sys.executable).parent / "lean-lsp-mcp.exe"),   # Windows venv
    str(Path(sys.executable).parent / "lean-lsp-mcp"),       # unix venv
    shutil.which("lean-lsp-mcp") or "",
)

# =====================================================================
# 联网工具禁用（2026-09-06 比赛禁网对齐）
# ---------------------------------------------------------------------
# lean-lsp-mcp 默认注册 5 个「远程检索」工具，一旦被调用就会出网访问
# 共享公共服务：
#   lean_leansearch     → https://leansearch.net/search
#   lean_loogle         → https://loogle.lean-lang.org（远程形态）
#   lean_leanfinder     → huggingface 托管端点
#   lean_state_search   → https://premise-search.com
#   lean_hammer_premise → http://leanpremise.net
# 赛事平台无外网，本地评测若悄悄用这些工具成绩会虚高。本代理作为
# lean-lsp-mcp 的唯一启动入口，一律禁用上述工具（官方 LEAN_MCP_DISABLED_TOOLS
# 机制：直接从工具注册表移除，客户端根本拿不到、无法调用）；
# 再注入「黑洞代理」（死端口）做纵深防御——即使未来某条代码路径漏网发起
# urllib/httpx 请求也会立即 connection refused 快速失败，绝不静默出网。
# 本地 LSP 诊断（lean_diagnostic_messages / lean_goal / lean_build /
# lean_local_search 等）走 stdio/文件，不经代理，不受影响。
# 调参需要临时放行远程检索时：设环境变量 LEAN_MCP_ALLOW_NET=1。
# =====================================================================
_NET_TOOLS = ("lean_leansearch,lean_loogle,lean_leanfinder,"
              "lean_state_search,lean_hammer_premise")
_ALLOW_NET_ENV = "LEAN_MCP_ALLOW_NET"
_BLACKHOLE_PROXY = "http://127.0.0.1:9"   # 死端口：连接立即被拒（快速失败）


def _server_env() -> dict:
    """构造传给 lean-lsp-mcp server 的环境（默认禁网；ALLOW_NET=1 放行）。"""
    env = dict(os.environ)
    allow = (os.environ.get(_ALLOW_NET_ENV, "") or "").strip().lower()
    if allow in ("1", "true", "yes"):
        return env
    # 1) 官方禁用机制：合并用户已有的 LEAN_MCP_DISABLED_TOOLS，不覆盖丢失
    existing = (env.get("LEAN_MCP_DISABLED_TOOLS", "") or "").strip()
    merged = _NET_TOOLS if not existing else existing + "," + _NET_TOOLS
    env["LEAN_MCP_DISABLED_TOOLS"] = merged
    # 2) 黑洞代理兜底（覆盖父进程可能带出的任何代理设置）
    env["HTTP_PROXY"] = _BLACKHOLE_PROXY
    env["HTTPS_PROXY"] = _BLACKHOLE_PROXY
    env["ALL_PROXY"] = _BLACKHOLE_PROXY
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    return env


def _resolve_server() -> str:
    for c in _SERVER_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    # 最后兜底：裸命令名交由系统 PATH 解析（找不到时 MCP 启动会失败并回落）
    return "lean-lsp-mcp"


def _text(content) -> str:
    """MCP call_tool 返回 content（list of text 块）→ 拼接字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for c in content:
            if c is None:
                continue
            t = getattr(c, "text", None)
            if t is None and isinstance(c, dict):
                t = c.get("text")
            if t:
                parts.append(t)
        return "\n".join(parts)
    return str(content)


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _iter_requests():
    """逐行读 stdin 出 JSON 请求；EOF 返回。"""
    for ln in sys.stdin:
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except json.JSONDecodeError:
            _reply({"id": -1, "ok": False, "error": "bad json line",
                    "items": [], "goal": None})


async def _handle(session, req) -> None:
    rid = req.get("id")
    try:
        fpath = req.get("file", "")
        if not fpath or not os.path.isfile(fpath):
            _reply({"id": rid, "ok": False,
                    "error": f"file not found: {fpath}",
                    "items": [], "goal": None})
            return
        r = await session.call_tool("lean_diagnostic_messages",
                                    {"file_path": fpath})
        txt = _text(r.content)
        try:
            d = json.loads(txt)
        except (json.JSONDecodeError, ValueError):
            _reply({"id": rid, "ok": False,
                    "error": "诊断输出非 JSON: " + txt[:200],
                    "items": [], "goal": None})
            return
        items = d.get("items", []) or []
        norm = [{"severity": i.get("severity", "info"),
                 "message": i.get("message", ""),
                 "line": i.get("line"),
                 "column": i.get("column")} for i in items]
        goal = None
        gl = req.get("goal_line")
        if gl and not d.get("success", True):
            try:
                gr = await session.call_tool(
                    "lean_goal",
                    {"file_path": fpath, "line": int(gl),
                     "column": int(req.get("goal_column") or 1)})
                gtxt = _text(gr.content)
                try:
                    gd = json.loads(gtxt)
                    goals = gd.get("goals") or []
                    goal = ("\n".join(goals) if isinstance(goals, list)
                            else str(goals))
                except (json.JSONDecodeError, ValueError):
                    goal = gtxt[:500]
            except Exception as exc:  # noqa: BLE001
                goal = f"(goal 获取失败: {type(exc).__name__})"
        _reply({"id": rid, "ok": True, "items": norm,
                "goal": goal, "error": ""})
    except Exception as exc:  # noqa: BLE001
        _reply({"id": rid, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "items": [], "goal": None})


async def _serve(session) -> None:
    for req in _iter_requests():
        await _handle(session, req)


async def amain() -> None:
    # Windows 控制台默认可能 gbk：统一 utf-8
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = _resolve_server()
    env = _server_env()
    disabled = (env.get("LEAN_MCP_DISABLED_TOOLS", "") or "").strip()
    params = StdioServerParameters(
        command=server,
        args=(["--disable-tools", disabled] if disabled else []),
        env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _serve(session)


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
