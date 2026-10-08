"""Lean 环境探测 + Mathlib import 归一化（自 `tools/lean_local/lean_bridge.py` 逐字搬出）。

职责：
  · 探测本地 Lean 编译器（lean.exe）与含 Mathlib 的 Lean 工程目录；
  · 判定 Mathlib tactic 可用性（聚合入口 / 裁剪闭包）并生成对应 import 块；
  · 把代码里的 Mathlib import 归一化为当前环境可编译的形态。

★ 2026-10-08 拆分（`lean_bridge.py` 上帝类拆分）：本模块由原文件**逐字搬出**，
  原文件改为 re-export（`from tools.lean_local.lean_bridge import X` 契约不变）。
  ★ 分层约束：本模块**零 `agent` 依赖**（不 import agent/*），
    不加深仓库已知的 tools→agent 倒置债务。
"""
from __future__ import annotations

import os
import re


# ---------------------------------------------------------------------
# 本地 Lean 工具链 / Mathlib 工程自动探测
# ---------------------------------------------------------------------
def _project_root() -> str:
    """仓库根目录（agent/ 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _detect_lean_executable() -> str:
    """自动探测本地 Lean 编译器（lean.exe）的绝对路径。

    优先级（命中即返回）：
      0) 环境变量 LEAN_EXE（MathPilot-lean-toolchain 调用约定协议，
         指向 vendor/lean-toolchain/lean/lean-4.31.0/bin/lean.exe）
      1) elan 管理的当前工具链 lean.exe（C:/Users/<user>/.elan/toolchains/.../bin/lean.exe）
      2) Windows: <root>/lean下载版/lean-toolchain/bin/lean.exe
      3) Linux:   <root>/deploy/lean-cache/lean-4.31.0-linux/bin/lean
      4) vendor 挂载：<root>/vendor/lean-toolchain/lean/lean-4.31.0/bin/lean(.exe)
    返回空串表示未探测到（调用方回退 "lake"）。
    """
    exe_env = (os.environ.get("LEAN_EXE", "") or "").strip()
    if exe_env and os.path.isfile(exe_env):
        return exe_env
    # elan 工具链（与实际 lake env 使用的版本一致；Windows 带 .exe，Linux 不带）
    elan_toolchains = os.path.expanduser(
        r"~\.elan\toolchains\leanprover--lean4---v4.31.0\bin\lean.exe")
    elan_toolchains_linux = os.path.expanduser(
        "~/.elan/toolchains/leanprover--lean4---v4.31.0/bin/lean")
    candidates = [
        elan_toolchains,
        elan_toolchains_linux,
        os.path.join(_project_root(), "lean下载版", "lean-toolchain", "bin", "lean.exe"),
        os.path.join(_project_root(), "deploy", "lean-cache",
                     "lean-4.31.0-linux", "bin", "lean"),
        # setup_lean.sh 的 zip 解压路径（deploy/lean-4.31.0-linux/bin/lean）
        os.path.join(_project_root(), "deploy", "lean-4.31.0-linux", "bin", "lean"),
        # 2026-09-06 vendor 挂载（MathPilot-lean-toolchain submodule 形态）
        os.path.join(_project_root(), "vendor", "lean-toolchain", "lean",
                     "lean-4.31.0", "bin", "lean.exe"),
        os.path.join(_project_root(), "vendor", "lean-toolchain", "lean",
                     "lean-4.31.0", "bin", "lean"),
        # 2026-09-07 root 形态（MathPilot-lean-toolchain 成为主仓，代码与
        # lean/mathlib 同根：<root>/lean/lean-4.31.0-linux（平台 Linux）
        # 与 <root>/lean/lean-4.31.0（Windows 开发）双树并存按 OS 命中）
        os.path.join(_project_root(), "lean", "lean-4.31.0-linux", "bin", "lean"),
        os.path.join(_project_root(), "lean", "lean-4.31.0", "bin", "lean.exe"),
        os.path.join(_project_root(), "lean", "lean-4.31.0", "bin", "lean"),
    ]
    for c in candidates:
        # Windows 只接受 .exe（无后缀 lean 为 ELF，Windows 不可执行——
        # root 形态双树并存时 lean-4.31.0-linux/bin/lean 真实存在会误命中）
        if os.path.isfile(c) and (os.name != "nt" or c.lower().endswith(".exe")):
            return c
    return ""


def _detect_lean_project_dir() -> str:
    """自动探测带 Mathlib 的 Lean 工程目录（编译 verify.lean 时 Mathlib 真正可用）。

    候选顺序：
      0) 环境变量 LEAN_PROJECT_PATH（lean-lsp-mcp 调用约定协议）
      1) 已下载并独立编译好的 mathlib 仓库根目录 D:/mathlib4-last_bump_for_v4.31.0
         （独立 Lake 工程，含完整 Mathlib 源码与构建产物 .lake/build）；
      2) <root>/lean下载版/test_mathlib（仓库内工程，需其依赖 mathlib 已编译）。
      3) vendor 挂载的 mathlib 闭包 <root>/vendor/lean-toolchain/mathlib/closure-full
         （非 lake 工程 → _compile 自动走 lean.exe 直编 + LEAN_PATH，见 _compile()）。
    返回空串表示未挂载。
    """
    candidates = [
        (os.environ.get("LEAN_PROJECT_PATH", "") or "").strip(),
        "D:/mathlib4-last_bump_for_v4.31.0",
        os.path.join(_project_root(), "lean下载版", "test_mathlib"),
        os.path.join(_project_root(), "vendor", "lean-toolchain",
                     "mathlib", "closure-full"),
        # 2026-09-07 root 形态（主仓切换后 <root>/mathlib/closure-full）
        os.path.join(_project_root(), "mathlib", "closure-full"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return ""


def _repo_closure_roots() -> list[str]:
    """仓库内**默认**可能挂载 Mathlib 闭包的目录（不含 LEAN_PATH）。

    2026-09-21 抽取：此前 `_mathlib_tactic_entry_available()` 与
    `_mathlib_ready()` 各维护一份同样的列表，已经漂移过一次
    （前者有 `data/mathlib-closure-core`，后者没有）⇒ 统一到本函数。
    """
    proj = _project_root()
    return [
        os.path.join(proj, "deploy", "mathlib-olean"),
        os.path.join(proj, "data", "mathlib-closure-core"),
        os.path.join(proj, "data", "mathlib-closure"),
        # 2026-09-06 vendor 挂载（MathPilot-lean-toolchain closure-full）
        os.path.join(proj, "vendor", "lean-toolchain",
                     "mathlib", "closure-full"),
        # 2026-09-07 root 形态（主仓切换后 <root>/mathlib/closure-full）
        os.path.join(proj, "mathlib", "closure-full"),
    ]


def _closure_roots() -> list[str]:
    """实际可能被编译器搜索到的闭包根：LEAN_PATH 优先，再补仓库内的默认位置。"""
    roots: list[str] = [
        d for d in os.environ.get("LEAN_PATH", "").split(os.pathsep) if d
    ]
    return roots + _repo_closure_roots()


def _has_mathlib_tactics(root: str) -> bool:
    """``root`` 下是否有**可用的 Mathlib tactic**（聚合入口或裁剪闭包都算）。

    判据：
      - ``Mathlib/Tactic.olean``             —— 聚合入口（full 闭包 / 完整工程）
      - ``Mathlib/Tactic/NormNum.olean``     —— 裁剪闭包（deploy/mathlib-olean）

    ★ 2026-09-21 修复（云端「Lean 验证全降级」根因）：
      此前该判据**只认聚合入口**。而 `deploy/mathlib-olean` 是由 5 个具体入口
      （NormNum/Ring/Linarith/Positivity/Omega）BFS 构建的**裁剪闭包**，
      **没有** `Mathlib/Tactic.olean` ⇒ 被判为「Mathlib 未就绪」。
      后果不是降级而是**全降级**：`_mathlib_ready()` 返回 False ⇒
      `verify()` / `verify_answer()` / `run_pre_verification()` /
      `audit_sketch()` 四处调用点全部跳过 `_prepend_mathlib_import()` ⇒
      原始 ``import Mathlib.Tactic``（或裸 ``import Mathlib``）原样送编译 ⇒
      闭包内无该 olean ⇒ 编译必败 ⇒ ``verdict`` 恒 ``unknown``、
      ``lean_valid`` 恒 ``False``。

      本地为何不暴露：本地同时存在带聚合入口的 ``vendor/.../closure-full``
      与 ``data/mathlib-closure``，`_detect_lean_project_dir()` 命中其中之一
      ⇒ 判据为真 ⇒ 归一化正常执行。云端 2026-09-20 为让 MCP 通道生效把
      ``LEAN_PROJECT_PATH`` 指向了裁剪闭包（deploy/cloud_run.env），
      于是 ``_lean_project_dir`` 非空且**恰为裁剪闭包根** ⇒ 必现。
    """
    if not root:
        return False
    return (os.path.isfile(os.path.join(root, "Mathlib", "Tactic.olean"))
            or os.path.isfile(os.path.join(root, "Mathlib", "Tactic",
                                           "NormNum.olean")))


def _mathlib_tactic_entry_available() -> bool:
    """聚合入口 Mathlib/Tactic.olean 是否可用（full 闭包/本地完整工程为 True）。

    core 闭包（deploy/mathlib-olean，5 具体入口 BFS 构建）**没有**
    Mathlib/Tactic.olean 聚合入口（它 import 337 个子模块，core 只覆盖
    194 个），`import Mathlib.Tactic` 会编译失败。判断当前环境应该用聚合
    入口还是具体模块导入。

    优先级：LEAN_PATH 环境变量显式设置时（比赛环境 deploy/setup_lean.sh
    挂载闭包后 lean 直编只用 LEAN_PATH 搜索）**以它为准**，避免被本机残留
    的 full 闭包目录（data/mathlib-closure）误导；LEAN_PATH 未设置时
    （本地 lake 工程场景）fallback 到默认部署目录探测。

    ⚠️ 本函数问的是「聚合入口在不在」，与 `_has_mathlib_tactics()` 问的
    「有没有可用的 tactic」是**两个不同问题**，不可互相替代：前者决定
    import 块形态，后者决定要不要做 import 归一化。
    """
    roots: list[str] = [
        d for d in os.environ.get("LEAN_PATH", "").split(os.pathsep) if d
    ]
    if not roots:
        roots = _repo_closure_roots()
    return any(os.path.isfile(os.path.join(r, "Mathlib", "Tactic.olean"))
               for r in roots)


# core 闭包模式下的替代导入集：覆盖 lean_gate 硬验证实际用到的 6 种 tactic
# （norm_num/ring/linarith/nlinarith/positivity/omega），探针实测可编译通过。
CORE_MATHLIB_IMPORTS = (
    "import Mathlib.Tactic.NormNum\n"
    "import Mathlib.Tactic.Ring\n"
    "import Mathlib.Tactic.Linarith\n"
    "import Mathlib.Tactic.Positivity\n"
)


def _mathlib_import_block() -> str:
    """当前环境应使用的 Mathlib import 块（full 用聚合入口，core 用具体模块）。"""
    return "import Mathlib.Tactic" if _mathlib_tactic_entry_available() \
        else CORE_MATHLIB_IMPORTS.rstrip("\n")


def _prepend_mathlib_import(code: str) -> str:
    """归一化代码的 Mathlib import（兼容本地部分编译布局）。

    本地 mathlib 工程因 v4.31.0 兼容问题缺失 517 个冷门模块（代数几何/拓扑/
    层论等），无法 import 全量 Mathlib；但核心 tactic 模块（Mathlib.Tactic，
    含 norm_num / ring / omega / linarith / positivity / aesop / simp）
    已编译完成，跑分证明完全够用。

    规则：
    - 代码有 `import Mathlib.Tactic` 或具体 `import Mathlib.X` → 原样返回
    - 代码有全量 `import Mathlib`（裸）→ 替换为可用 import 块
    - 无任何 import → 补可用 import 块
    - core 闭包（无 Mathlib.Tactic.olean 聚合入口）→ 用具体模块导入集，
      避免 `import Mathlib.Tactic` 编译失败导致验证全降级（2026-09-01 修复）
    """
    if not code:
        return _mathlib_import_block() + "\n"
    # 聚合入口 import Mathlib.Tactic（行尾无子模块）→ 替换为可用块
    # ★ 2026-09-21 加固：原先锚点写作 `\s*$`，`import Mathlib.Tactic -- 注释`
    #   这类带行尾注释的写法会逃过本规则，转而被下方「已有具体模块导入 → 原样
    #   返回」的分支放行 ⇒ 聚合入口被保留 ⇒ 裁剪闭包下同样编译必败
    #   （与 0921 云端全降级同一失效家族）。现允许行尾 `--` 注释与空白。
    if re.search(r"^\s*import\s+Mathlib\.Tactic\s*(?:--[^\n]*)?$",
                 code, re.MULTILINE):
        return re.sub(r"(?m)^\s*import\s+Mathlib\.Tactic\s*(?:--[^\n]*)?$",
                      _mathlib_import_block(), code)
    # 已有具体模块导入（Mathlib.Tactic.NormNum / Mathlib.Data.X）→ 原样返回
    if re.search(r"^\s*import\s+Mathlib\.", code, re.MULTILINE):
        return code
    # 全量 import Mathlib（裸）→ 替换为可用块
    if re.search(r"^\s*import\s+Mathlib\b", code, re.MULTILINE):
        return re.sub(r"(?m)^\s*import\s+Mathlib\b.*$",
                      _mathlib_import_block(), code)
    # 无任何 import → 补可用块
    return _mathlib_import_block() + "\n\n" + code


def _normalize_lean_imports(code: str) -> str:
    """mcp 后端兼容：把裸 ``import Mathlib`` 换成 ``import Mathlib.Tactic``。

    依据（2026-09-11 实测定位）：本机 Mathlib 布局**缺聚合入口 ``Mathlib.olean``**
    （v4.31.0 部分编译布局，与项目既有结论一致）。写裸 ``import Mathlib`` 时，
    Lean LSP 报 ``fileProgress kind=2``（fatalError）→ lean-lsp-mcp 恒返回
    ``diagnostics_unavailable: Lean did not finish; the file is not known clean``，
    这正是"mcp 后端从未可用"的真实根因。
    改为 ``import Mathlib.Tactic`` 后 mcp 诊断完全正常（实测 0.1s 增量秒回，
    且能给出精确 ``行:列`` 与目标状态）。

    仅替换**独占一行的** ``import Mathlib``；``import Mathlib.Xxx`` 具体导入不触碰。
    """
    return re.sub(r"(?m)^[ \t]*import[ \t]+Mathlib[ \t]*$",
                  "import Mathlib.Tactic", code)
