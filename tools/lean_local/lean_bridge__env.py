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


def _lean_env_roots() -> list[str]:
    """本机独立 Lean 环境的候选根目录（2026-10-15 新增）。

    动机：本机布局是「仓库 `E:/math-ai-evaluator` + 同级 `E:/lean-env`」，
    此前探测链只认仓库**内部**路径（`vendor/`、`lean下载版/`、`deploy/`），
    同级目录完全不在候选里 ⇒ `lean_available` 恒 False，所有 Lean 特性
    （子目标证明核验 / 4.3 代回 / tool=lean 兑现）在本地**静默关闭**。

    顺序：`LEAN_ENV_DIR` 环境变量（显式最高优先）→ 仓库根的同级 `lean-env/`
    → 仓库内的 `lean-env/`。
    """
    roots: list[str] = []
    env_dir = (os.environ.get("LEAN_ENV_DIR", "") or "").strip()
    if env_dir:
        roots.append(env_dir)
    roots.append(os.path.join(os.path.dirname(_project_root()), "lean-env"))
    roots.append(os.path.join(_project_root(), "lean-env"))
    return roots


def _detect_lean_executable() -> str:
    """自动探测本地 Lean 编译器（lean.exe）的绝对路径。

    优先级（命中即返回）：
      0) 环境变量 LEAN_EXE（MathPilot-lean-toolchain 调用约定协议，
         指向 vendor/lean-toolchain/lean/lean-4.31.0/bin/lean.exe）
      0.5) 环境变量 LEAN_ENV_DIR（本机 lean 开发环境根，如 E:/lean-env）
      1) elan 管理的当前工具链 lean.exe（C:/Users/<user>/.elan/toolchains/.../bin/lean.exe）
      2) Windows: <root>/lean下载版/lean-toolchain/bin/lean.exe
      3) Linux:   <root>/deploy/lean-cache/lean-4.31.0-linux/bin/lean
      4) vendor 挂载：<root>/vendor/lean-toolchain/lean/lean-4.31.0/bin/lean(.exe)
      5) ★ 2026-10-15 新增：**仓库根的同级目录** `../lean-env/lean-toolchain/bin/lean(.exe)`
         （本机独立 lean 环境，形如 `E:/lean-env/lean-toolchain`；此前探测不到 ⇒
         `lean_available` 恒 False，所有 Lean 特性在本地静默关闭）
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
    ]
    # ★ 2026-10-15：本机独立 lean 环境（`LEAN_ENV_DIR` / 同级 `lean-env/`）
    for _r in _lean_env_roots():
        candidates.append(os.path.join(_r, "lean-toolchain", "bin", "lean.exe"))
        candidates.append(os.path.join(_r, "lean-toolchain", "bin", "lean"))
    candidates += [
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


_DEFAULT_LAKE_EXECUTABLE = "lake"


def _detect_lake_executable() -> str:
    """自动探测本地 `lake` 可执行文件（2026-10-15 新增）。

    动机：`LeanBridge._compile` 在「work_dir 是 lake 工程」时强制走
    `lake env lean`（这样 lake 才会从 lake-manifest 解析出 Mathlib 的
    LEAN_PATH）；但它此前只认 `~/.elan/bin/lake.exe`，否则回落裸 `"lake"`
    （依赖 PATH）。本机 elan 未安、lake 不在 PATH ⇒ 该分支必然
    `FileNotFoundError`。本函数按与 lean.exe 相同的候选链找 `lake(.exe)`。
    """
    exe_env = (os.environ.get("LAKE_EXE", "") or "").strip()
    if exe_env and os.path.isfile(exe_env):
        return exe_env
    candidates = [
        os.path.expanduser(r"~\.elan\bin\lake.exe"),
        os.path.expanduser("~/.elan/bin/lake"),
    ]
    for _r in _lean_env_roots():
        candidates.append(os.path.join(_r, "lean-toolchain", "bin", "lake.exe"))
        candidates.append(os.path.join(_r, "lean-toolchain", "bin", "lake"))
    # 与探测到的 lean(.exe) 同目录的 lake（同一工具链 bin/ 下必然同存）
    for _exe in (_detect_lean_executable(),):
        if _exe:
            _d = os.path.dirname(_exe)
            candidates.append(os.path.join(_d, "lake.exe"))
            candidates.append(os.path.join(_d, "lake"))
    for c in candidates:
        if os.path.isfile(c) and (os.name != "nt" or c.lower().endswith(".exe")):
            return c
    return _DEFAULT_LAKE_EXECUTABLE


def _looks_like_lean_project(path: str) -> bool:
    """`path` 是否像**可用的** Lean 工程/闭包根（2026-10-15 新增）。

    判据（任一命中即可）：`lakefile.toml` / `lakefile.lean` /
    `lake-manifest.json` / `.lake/` / `Mathlib/` 子目录。

    动机：`D:/mathlib4-last_bump_for_v4.31.0` 是一个**残留空壳**
    （只剩 `_lean_trash/`），却因 `os.path.isdir()` 为真而**排在候选最前**，
    把真正可用的同名工程（`E:/mathlib4-last_bump_for_v4.31.0`）挡在外面 ⇒
    `_lean_project_dir` 指向空目录、`_mathlib_ready()` 恒 False、
    `import Mathlib.Tactic` 不做归一化 ⇒ 编译必败。加本判据即跳过空壳。
    """
    if not path or not os.path.isdir(path):
        return False
    return any(os.path.exists(os.path.join(path, n))
               for n in ("lakefile.toml", "lakefile.lean", "lake-manifest.json",
                         ".lake", "Mathlib"))


def _detect_lean_project_dir() -> str:
    """自动探测带 Mathlib 的 Lean 工程目录（编译 verify.lean 时 Mathlib 真正可用）。

    候选顺序：
      0) 环境变量 LEAN_PROJECT_PATH（lean-lsp-mcp 调用约定协议）
      1) <lean-env>/test_mathlib —— ★ 2026-10-15 新增，本机实际可用者：
         `lake env lean` 在该工程内会按 lake-manifest 把 Mathlib 的 olean
         根挂进搜索路径（实测可编译 norm_num/ring/linarith 证明）。
      2) 同级 `mathlib4*` 源码工程根（本机 `E:/mathlib4-last_bump_for_v4.31.0`，
         含真实 `.lake/build`，665 个 olean）；
      3) 历史硬编码 `D:/mathlib4-last_bump_for_v4.31.0`（**保留但降级**：
         它在本机是只剩 `_lean_trash/` 的空壳，此前排在首位 ⇒ 挡住真正可用的
         E: 同名工程。现由 `_looks_like_lean_project` 判据自动跳过）；
      4) <root>/lean下载版/test_mathlib（仓库内工程，需其依赖 mathlib 已编译）。
      5) vendor 挂载的 mathlib 闭包 <root>/vendor/lean-toolchain/mathlib/closure-full
         （非 lake 工程 → _compile 自动走 lean.exe 直编 + LEAN_PATH，见 _compile()）。
    返回空串表示未挂载。

    ★ 2026-10-15 起所有候选统一过 `_looks_like_lean_project()`：
      `os.path.isdir()` 为真是**不够的**（空壳目录同样为真），必须看得出是
      Lean 工程/闭包才接受。
    """
    candidates = [
        (os.environ.get("LEAN_PROJECT_PATH", "") or "").strip(),
    ]
    for _r in _lean_env_roots():
        candidates.append(os.path.join(_r, "test_mathlib"))
    # 同级 `mathlib4*` 源码工程（glob 展开，避免再写死某个盘符）
    import glob as _glob
    for _base in {os.path.dirname(_project_root())} | set(_lean_env_roots()):
        candidates.extend(sorted(_glob.glob(os.path.join(_base, "mathlib4*"))))
    candidates += [
        "D:/mathlib4-last_bump_for_v4.31.0",
        os.path.join(_project_root(), "lean下载版", "test_mathlib"),
        os.path.join(_project_root(), "vendor", "lean-toolchain",
                     "mathlib", "closure-full"),
        # 2026-09-07 root 形态（主仓切换后 <root>/mathlib/closure-full）
        os.path.join(_project_root(), "mathlib", "closure-full"),
    ]
    for c in candidates:
        if _looks_like_lean_project(c):
            return c
    return ""


def _local_mathlib_olean_roots() -> list[str]:
    """本机独立 Mathlib 工程的 olean 搜索根（2026-10-15 新增）。

    形态：`<mathlib4 工程根>/.lake/build/lib/lean`（含 `Mathlib/**/*.olean`）。
    覆盖两种本机布局：
      · `LEAN_ENV_DIR` / 同级 `lean-env/test_mathlib` 的依赖包目录
        （`<lean-env>/test_mathlib/.lake/packages/mathlib/.lake/build/lib/lean`）；
      · 同级 `mathlib4*` 源码工程自身的构建产物。

    ★ 为什么需要它：`LeanBridge._mathlib_ready()` 的**最终兜底**是
      `any(_has_mathlib_tactics(r) for r in _closure_roots())`，而
      `_closure_roots()` 只含 `LEAN_PATH` + 仓库**内部**默认位置。本机
      Mathlib 在仓库**外部** ⇒ 该兜底恒 False ⇒ `_mathlib_ready()` 恒 False
      ⇒ `_prepend_mathlib_import()` 被跳过 ⇒ 模型写的 `import Mathlib.Tactic`
      （聚合入口在本机部分编译布局下**不存在**）原样送编译 ⇒ 必败。
      （实测：聚合 `Mathlib/Tactic.olean` 缺失，只有具体 tactic 模块。）
    """
    import glob as _glob
    roots: list[str] = []
    for _r in _lean_env_roots():
        roots.extend(sorted(_glob.glob(os.path.join(
            _r, "test_mathlib", ".lake", "packages", "*", ".lake",
            "build", "lib", "lean"))))
        roots.extend(sorted(_glob.glob(os.path.join(
            _r, "mathlib4*", ".lake", "build", "lib", "lean"))))
    for _base in {os.path.dirname(_project_root())} | set(_lean_env_roots()):
        roots.extend(sorted(_glob.glob(os.path.join(
            _base, "mathlib4*", ".lake", "build", "lib", "lean"))))
        # ★ 2026-10-22（Lean 编译失败根因）：Mathlib 的**依赖包**必须一并挂上。
        #   实测：只挂 Mathlib 层 ⇒ `import Mathlib.Tactic` 报
        #   `unknown module prefix 'Batteries'`；补齐 batteries/aesop/Qq/
        #   LeanSearchClient/plausible/proofwidgets/importGraph 七个包后退出码 0。
        roots.extend(sorted(_glob.glob(os.path.join(
            _base, "mathlib4*", ".lake", "packages", "*", ".lake",
            "build", "lib", "lean"))))
    seen: set[str] = set()
    out: list[str] = []
    for p in roots:
        if os.path.isdir(p) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _repo_closure_roots() -> list[str]:
    """仓库内**默认**可能挂载 Mathlib 闭包的目录（不含 LEAN_PATH）。

    2026-09-21 抽取：此前 `_mathlib_tactic_entry_available()` 与
    `_mathlib_ready()` 各维护一份同样的列表，已经漂移过一次
    （前者有 `data/mathlib-closure-core`，后者没有）⇒ 统一到本函数。
    ★ 2026-10-15：并入 `_local_mathlib_olean_roots()`（仓库**外部**的本机
      Mathlib 构建产物），否则本地环境 `_mathlib_ready()` 恒 False。
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
    ] + _local_mathlib_olean_roots()


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
