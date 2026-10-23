# -*- coding: utf-8 -*-
"""lean_bridge 拆分 · 批次3：MCP 代理簇（lean_bridge__mcp.py）。

2026-10-08 从 ``tools/lean_local/lean_bridge.py`` **逐字搬迁**（零改动）：
- MCP 代理客户端 ``_LeanMcpProxyClient``（spawn venv python 跑 lean_mcp_proxy.py）；
- venv python 探测 ``_detect_mcp_proxy_python`` / 代理脚本定位 ``_mcp_proxy_script``
  / 可用性判定 ``mcp_available``；
- lake 工程门控 ``_is_lake_workdir`` / ``_is_mcp_project_root`` /
  ``_min_toolchain_content`` / ``_ensure_min_lake_project`` / ``_mcp_gate_ok``；
- 实例池健康/丢弃/计时：``_mcp_client_alive`` / ``_mcp_mark_drop`` /
  ``_mcp_take_drop_flag`` / ``mcp_stats`` / ``_mcp_note`` / ``_wd_key``。

依赖方向：本模块 **不依赖** ``lean_bridge``（无循环导入）；仅依赖
``contracts.switch_registry``（零依赖）与同目录 ``lean_bridge__env``。
``lean_bridge.py`` 通过 re-export 保持外部
``from tools.lean_local.lean_bridge import <name>`` 契约，以及
``mock.patch("tools.lean_local.lean_bridge.<name>")`` 的可 patch 性不变
（被 patch 的名字其调用方仍留在 lean_bridge.py ⇒ 查表仍走 lean_bridge 命名空间）。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading

from contracts.switch_registry import get_bool as _sw_bool

from tools.lean_local.lean_bridge__env import _project_root

logger = logging.getLogger("MathPilot")


def _is_lake_workdir(work_dir: str) -> bool:
    """work_dir 是否为 lake 工程根（MCP/LSP 需要工程环境解析 import）。"""
    return any(os.path.isfile(os.path.join(work_dir, f))
               for f in ("lakefile.toml", "lakefile.lean", "lake-manifest.json"))


# 最小 lake 工程标记（内容刻意极简：只为让 lean-lsp-mcp 认这是工程根）
_MIN_LAKEFILE_TOML = 'name = "mathlib"\ndefaultTargets = []\n'
_MIN_MANIFEST_JSON = (
    '{"version": "1.1.0", "packagesDir": ".lake/packages", '
    '"packages": [], "name": "mathlib", "lakeDir": ".lake"}\n')
# lean-lsp-mcp 的 require_lean_project_path 还强制要求 `lean-toolchain` 文件，
# 缺失即 ValueError 启动失败（2026-09-12 实测抓到，见 _min_toolchain_content）
_FALLBACK_TOOLCHAIN = "leanprover/lean4:v4.31.0"


def _min_toolchain_content() -> str:
    """`lean-toolchain` 内容：env > 仓根同名文件 > 项目锁定版本兜底。"""
    env = (os.environ.get("LEAN_TOOLCHAIN", "") or "").strip()
    if env:
        return env + "\n"
    try:
        p = os.path.join(_project_root(), "lean-toolchain")
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                t = f.read().strip()
            if t:
                return t + "\n"
    except Exception:  # noqa: BLE001
        pass
    return _FALLBACK_TOOLCHAIN + "\n"


def _is_mcp_project_root(root: str) -> bool:
    """lean-lsp-mcp `require_lean_project_path()` 的等价要求。

    实测（2026-09-12）该库硬性要求：`lean-toolchain` **且**
    （`lakefile.lean` 或 `lakefile.toml`）；缺任一项即启动 ValueError。
    比 `_is_lake_workdir`（三选一）严格 —— 门控必须按这个口径判。
    """
    if not root or not os.path.isdir(root):
        return False
    if not os.path.isfile(os.path.join(root, "lean-toolchain")):
        return False
    return any(os.path.isfile(os.path.join(root, f))
               for f in ("lakefile.toml", "lakefile.lean"))


def _ensure_min_lake_project(root: str) -> bool:
    """Mathlib **闭包**目录缺 lake 工程标记时，补最小工程文件（幂等）。

    背景（2026-09-12，用户要求 mcp 必须可用）：
      平台部署形态是「Mathlib 闭包 + LEAN_PATH」，全仓**没有** lakefile；
      而 `verify()` 在 project_dir 非空时把 **work_dir 设为 project_dir 本身**
      （见 `_compile(code, project_dir, ...)`），于是 mcp 门控恒为 False →
      **lean-lsp-mcp 在平台永不被调用**，连带丢失它的三项高价值错误反馈能力：
      错误行 goal state / multi_attempt 可用策略 / hover 查证 API。

    这里只补**工程标记**（lean-toolchain + lakefile.toml + manifest），不搬动
    任何 olean：Lean 编译仍走 lean.exe + LEAN_PATH 原路径
    （`_compile_lean` 的 is_lake 判定只看可执行文件名），行为不变。

    返回 True 表示该目录现在满足 lean-lsp-mcp 的工程根要求。
    """
    try:
        if not root or not os.path.isdir(root):
            return False
        # 只对「含 Mathlib olean 的闭包目录」动手，避免在任意目录乱写文件
        ml = os.path.join(root, "Mathlib")
        if not os.path.isdir(ml):
            return False
        has_olean = False
        try:
            for i, fn in enumerate(os.listdir(ml)):
                if i > 400:
                    break
                if fn.endswith(".olean"):
                    has_olean = True
                    break
        except OSError:
            return False
        if not has_olean:
            return False
        wrote = []
        for fn, content in (("lakefile.toml", _MIN_LAKEFILE_TOML),
                            ("lake-manifest.json", _MIN_MANIFEST_JSON),
                            ("lean-toolchain", _min_toolchain_content())):
            p = os.path.join(root, fn)
            if not os.path.isfile(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                wrote.append(fn)
        if wrote:
            logger.info("[LeanBridge] ★ 已为 Mathlib 闭包补最小 lake 工程标记 %s：%s"
                        "（mcp 需要工程根；可用 LEAN_MCP_AUTOLAKE=0 关闭）",
                        root, ", ".join(wrote))
        return _is_mcp_project_root(root)
    except Exception as exc:  # noqa: BLE001  只读挂载/权限不足 → 静默失败
        logger.warning("[LeanBridge] 补 lake 工程标记失败（忽略）: %s", exc)
        return False


def _mcp_gate_ok(work_dir: str) -> bool:
    """mcp 后端门控：work_dir 必须满足 lean-lsp-mcp 的工程根要求。

    2026-09-12 升级：单纯 `_is_lake_workdir` 会让「闭包 + LEAN_PATH」部署形态
    永久不可用（平台实测即如此）。现按 `LEAN_MCP_AUTOLAKE`（**默认 1**，因用户
    明确要求 mcp 必须可用）在闭包目录上补最小工程文件后再判定。
    设 `LEAN_MCP_AUTOLAKE=0` 可恢复旧的严格门控（仅现成 lake 工程才走 mcp）。
    """
    if _is_mcp_project_root(work_dir):
        return True
    if not _sw_bool("lean_mcp_autolake"):
        return False
    return _ensure_min_lake_project(work_dir)


def _detect_mcp_proxy_python() -> str:
    """探测装有 lean-lsp-mcp 的 venv python（代理执行器）。

    优先级：环境变量 LEAN_MCP_PYTHON > ~/leanlsp-venv（win/unix）。
    返回空串表示本地无 mcp 环境（mcp 后端自动回落 bridge）。
    """
    env = (os.environ.get("LEAN_MCP_PYTHON", "") or "").strip()
    if env and os.path.isfile(env):
        return env
    home = os.path.expanduser("~")
    # ① 用户主目录惯例路径（本机开发用）
    for c in (os.path.join(home, "leanlsp-venv", "Scripts", "python.exe"),
              os.path.join(home, "leanlsp-venv", "bin", "python")):
        if os.path.isfile(c):
            return c
    # ② 仓内 venv —— 平台离线安装脚本 scripts/install_mcp_linux.sh 的产出位置
    #    （2026-09-11 补：脚本装到 <repo>/lean-lsp-mcp/venv-linux，而代码原先只找 ~/，
    #     导致平台侧"装了却探测不到" → 静默回落 bridge。此处补齐，避免该错位。）
    try:
        _here = os.path.dirname(os.path.abspath(__file__))      # .../tools/lean_local
        _repo = os.path.dirname(os.path.dirname(_here))          # 仓库根
        for c in (os.path.join(_repo, "lean-lsp-mcp", "venv-linux", "bin", "python"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv", "bin", "python"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv", "Scripts", "python.exe"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv-linux", "Scripts", "python.exe")):
            if os.path.isfile(c):
                return c
    except Exception:  # noqa: BLE001
        pass
    return ""


def _mcp_proxy_script() -> str:
    """agent/lean_mcp_proxy.py 绝对路径（代理脚本随主仓库走）。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "lean_mcp_proxy.py")
    return p if os.path.isfile(p) else ""


def mcp_available() -> bool:
    """MCP 通道是否真可用（venv python + 代理脚本都在）。

    用途：**并行只在 MCP 可用时启用**。理由：MCP 走 LSP 常驻诊断（单次 60s 量级、
    实例间彼此独立 ⇒ 并行收益明确）；而 bridge 是 `lake env lean` 全量编译，
    并行收益未验证，且同工程目录并发跑 lake 有额外风险。
    MCP 不可用时（如比赛平台无 Lean 环境）一切照旧走串行 bridge —— 零行为变化。
    """
    try:
        return bool(_detect_mcp_proxy_python() and _mcp_proxy_script())
    except Exception:  # noqa: BLE001
        return False



def _ensure_lake_in_path(env: dict) -> str:
    """保证 `lake` 所在目录在 env['PATH'] 里，返回命中的目录（未命中返回空）。

    为什么必须由代码兜底（2026-10-23 实测）
    ---------------------------------------
    `lean-lsp-mcp` 启动 Lean LSP 时执行的是 **`lake` 命令**，不是 `lean` 绝对路径。
    云端 `lake` 就在 `deploy/lean-4.31.0-linux/bin/` 里，但那个目录**不在 PATH 上**
    ⇒ MCP 报 `No such file or directory: 'lake'` ⇒ 整条 Lean 通道静默失效
    （val1_r1_1022：4.3 全空、leansearch calls=0；val1_r2_1023 复现）。

    虽然 `deploy/cloud_run.env` 已加 PATH，但依赖"启动路径确实 source 了它"太脆
    （实测 run 里仍失败）。这里从两个**已有**事实反推目录，自给自足：
      ① `LEAN_EXECUTABLE` —— lean 绝对路径；
      ② `LEAN_PROJECT_PATH` —— mathlib-olean 目录，其**兄弟目录**里通常放着 lean 发行版。
    """
    if shutil.which("lake", path=env.get("PATH", "")):
        return ""
    cand = []
    exe = env.get("LEAN_EXECUTABLE", "")
    if exe:
        cand.append(os.path.dirname(exe))
    proj = env.get("LEAN_PROJECT_PATH", "")
    if proj:
        parent = os.path.dirname(os.path.abspath(proj))
        try:
            for name in sorted(os.listdir(parent)):
                d = os.path.join(parent, name, "bin")
                if os.path.isfile(os.path.join(d, "lake")):
                    cand.append(d)
        except OSError:
            pass
    for d in cand:
        if os.path.isfile(os.path.join(d, "lake")):
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
            return d
    return ""


class _LeanMcpProxyClient:
    """spawn venv python 跑 lean_mcp_proxy.py，一行 JSON 一问一答。

    - 单实例常驻（lean-lsp-mcp server / lean server 跨请求复用 → 增量秒回）；
    - request 带 wall-clock 读超时；进程退出/无响应抛 RuntimeError（上层回落）；
    - close() 终止子进程。
    """

    def __init__(self, python: str, script: str, project_dir: str):
        env = dict(os.environ)
        env["LEAN_PROJECT_PATH"] = project_dir
        # ★ 2026-10-23：先补 lake 所在目录，再 spawn —— 否则 LSP 起不来且失败被包成 ok=True
        _lake_dir = _ensure_lake_in_path(env)
        if _lake_dir:
            logger.info("[LeanMCP] lake 补进 PATH: %s", _lake_dir)
        env.setdefault("LEAN_LOG_LEVEL", "NONE")
        # 2026-09-13 修复（诊断能力）：stderr 由 DEVNULL 改为 PIPE + 后台收割。
        # 原因：`lean-lsp-mcp` 启动失败时（典型场景：LEAN_PROJECT_PATH 指向的
        # 目录不是合法 Lean 工程 → app_lifespan 里 require_lean_project_path
        # 抛异常），**子进程是活着的但永不响应任何请求**；原实现把 stderr 丢弃，
        # 且统一报"proxy 无响应（可能崩溃）"，把排查方向带偏（实测误导过一次
        # 完整诊断）。注意必须**持续读取**——PIPE 写满会阻塞子进程。
        try:
            self._proc = subprocess.Popen(
                [python, script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", env=env, bufsize=1)
        except OSError as exc:
            raise RuntimeError(f"proxy 启动失败: {exc}") from exc
        self._seq = 0
        self._stderr_tail = ""
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        """后台收割 stderr，仅保留尾部（供启动失败时给出真实原因）。"""
        try:
            proc = self._proc
            if proc is None or proc.stderr is None:
                return
            for line in iter(proc.stderr.readline, ""):
                if not line:
                    break
                self._stderr_tail = (self._stderr_tail + line)[-4000:]
        except Exception:  # noqa: BLE001
            pass

    def _stderr_hint(self, limit: int = 3) -> str:
        """把 stderr 尾部压成一行附到异常信息里（无内容则返回空串）。"""
        raw = (self._stderr_tail or "").strip()
        if not raw:
            return ""
        lines = [x.strip(" |+") for x in raw.splitlines() if x.strip()]
        return "；stderr 尾部: " + " / ".join(lines[-limit:])[:400]

    def request(self, file_path: str, timeout: float = 150.0,
                goal_line=None, goal_column=None) -> dict:
        """发一次诊断请求（可选带目标行定位），阻塞等响应。"""
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("proxy 进程已退出")
        self._seq += 1
        req = {"id": self._seq, "file": file_path,
               "goal_line": goal_line, "goal_column": goal_column}
        try:
            self._proc.stdin.write(
                json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"proxy 写入失败: {exc}") from exc
        try:
            # readline 无超时参数 → 用 selectors/线程包装。简单可靠：
            # 以读线程 + join(timeout) 实现 wall-clock 超时。
            import queue
            q: "queue.Queue[str]" = queue.Queue()

            def _reader() -> None:
                try:
                    ln = self._proc.stdout.readline()
                    q.put(ln)
                except Exception:  # noqa: BLE001  pyflakes: exc 未使用，去掉绑定
                    q.put("")

            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            t.join(timeout)
            if t.is_alive():
                raise RuntimeError(f"proxy 响应超时（>{timeout:.0f}s）")
            resp_line = q.get_nowait() if not q.empty() else ""
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"proxy 读响应失败: {exc}") from exc
        if not resp_line:
            # 2026-09-13：区分两种**完全不同**的故障，避免误判（见 __init__ 注释）。
            #   · 进程已退出            → 真崩溃 / 被外部杀掉
            #   · 进程存活但无输出      → MCP 服务启动失败（真实原因在 stderr）
            _rc = self._proc.poll()
            _hint = self._stderr_hint()
            if _rc is not None:
                raise RuntimeError(f"proxy 进程已退出（退出码={_rc}）{_hint}")
            raise RuntimeError(
                "proxy 无输出：进程存活但 MCP 服务未就绪"
                "（常见原因：LEAN_PROJECT_PATH 指向的不是合法 Lean 工程）"
                + _hint)
        try:
            resp = json.loads(resp_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"proxy 响应非 JSON: {resp_line[:120]}") from exc
        return resp

    def call(self, payload: dict, timeout: float = 150.0) -> dict:
        """通用代理请求（2026-09-11）：下发任意 op（run_code/local_search/verify）。

        payload 除 ``id`` 外原样下发；返回代理的 JSON 响应。
        超时/进程退出语义与 request() 一致（抛 RuntimeError，上层回落）。
        """
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("proxy 进程已退出")
        self._seq += 1
        req = {"id": self._seq}
        req.update(payload)
        try:
            self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"proxy 写入失败: {exc}") from exc
        import queue
        q: "queue.Queue[str]" = queue.Queue()

        def _reader() -> None:
            try:
                q.put(self._proc.stdout.readline())
            except Exception:  # noqa: BLE001
                q.put("")

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise RuntimeError(f"proxy 响应超时（>{timeout:.0f}s）")
        resp_line = q.get_nowait() if not q.empty() else ""
        if not resp_line:
            # 2026-09-13：区分两种**完全不同**的故障，避免误判（见 __init__ 注释）。
            #   · 进程已退出            → 真崩溃 / 被外部杀掉
            #   · 进程存活但无输出      → MCP 服务启动失败（真实原因在 stderr）
            _rc = self._proc.poll()
            _hint = self._stderr_hint()
            if _rc is not None:
                raise RuntimeError(f"proxy 进程已退出（退出码={_rc}）{_hint}")
            raise RuntimeError(
                "proxy 无输出：进程存活但 MCP 服务未就绪"
                "（常见原因：LEAN_PROJECT_PATH 指向的不是合法 Lean 工程）"
                + _hint)
        try:
            return json.loads(resp_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"proxy 响应非 JSON: {resp_line[:120]}") from exc

    def run_code(self, code: str, timeout: float = 120.0) -> dict:
        """本地执行 Lean 代码片段（计算；不联网）。"""
        return self.call({"op": "run_code", "code": code}, timeout=timeout)

    def local_search(self, query: str, limit: int = 10,
                     timeout: float = 60.0) -> dict:
        """本地 Mathlib 声明检索（找引理；不联网）。"""
        return self.call({"op": "local_search", "query": query,
                          "limit": limit}, timeout=timeout)

    def verify_theorem(self, file_path: str, theorem_name: str,
                       timeout: float = 120.0) -> dict:
        """定理公理/可疑构造检查（检测；不联网）。"""
        return self.call({"op": "verify", "file": file_path,
                          "theorem": theorem_name}, timeout=timeout)

    def multi_attempt(self, file_path: str, line: int, snippets: list,
                      column: int = 0, timeout: float = 120.0) -> dict:
        """在指定行尝试多个 tactic（B4 修复建议；不联网）。"""
        payload = {"op": "multi_attempt", "file": file_path,
                   "line": int(line), "snippets": list(snippets)}
        if column:
            payload["column"] = int(column)
        return self.call(payload, timeout=timeout)

    def hover(self, file_path: str, line: int, column: int,
              timeout: float = 60.0) -> dict:
        """取某位置符号的类型签名/文档（B6 API 校验；不联网）。"""
        return self.call({"op": "hover", "file": file_path,
                          "line": int(line), "column": int(column)},
                         timeout=timeout)

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None


def _mcp_client_alive(client) -> bool:
    """实例健康判定：进程存在且未退出（已 close() 视为不可用）。"""
    try:
        proc = getattr(client, "_proc", None)
        return proc is not None and proc.poll() is None
    except Exception:  # noqa: BLE001
        return False


# 异常/超时后"必须丢弃"的实例（按 id 登记，避免给对象加属性）。
# 为什么不能只看进程存活：读超时后进程往往还活着，但那次的**响应会迟到**，
# 一旦归还池里被下一个请求读到就会"张冠李戴"（一问一答协议错位）。
_MCP_DROP: set = set()
_MCP_DROP_LOCK = threading.Lock()


def _mcp_mark_drop(client) -> None:
    """标记实例不可复用：下次归还时关闭并释放名额（调用方不再自行 close）。"""
    if client is None:
        return
    with _MCP_DROP_LOCK:
        _MCP_DROP.add(id(client))


def _mcp_take_drop_flag(client) -> bool:
    """取出并清除"需丢弃"标记。"""
    key = id(client)
    with _MCP_DROP_LOCK:
        if key in _MCP_DROP:
            _MCP_DROP.discard(key)
            return True
    return False


# MCP 计时统计（累计）。用途：让"单次 61s / 占总时长 54%"这类结论**可取证** ——
# 此前全仓没有任何 MCP 计时埋点，所有耗时都是用日志时间戳反推的。
_MCP_STATS = {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0}
_MCP_STATS_LOCK = threading.Lock()


def mcp_stats() -> dict:
    """累计 MCP 诊断调用统计（calls / ok / fail / seconds）。"""
    with _MCP_STATS_LOCK:
        return dict(_MCP_STATS)


def _mcp_note(seconds: float, ok: bool) -> None:
    with _MCP_STATS_LOCK:
        _MCP_STATS["calls"] += 1
        _MCP_STATS["seconds"] += float(seconds)
        _MCP_STATS["ok" if ok else "fail"] += 1


def _wd_key(work_dir: str) -> str:
    """池分桶键：同一工程目录的不同写法必须落到同一桶。"""
    try:
        return os.path.normcase(os.path.abspath(work_dir))
    except Exception:  # noqa: BLE001
        return str(work_dir)
