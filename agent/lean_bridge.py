from __future__ import annotations
"""
Lean 验证桥接层（agent/lean_bridge.py）
========================================

把 Lean 4 形式化验证能力封装为与 agent 链解耦的组件，供 SolverAgent 的
证明题通道在 ``enable_lean_verify`` 开关开启时调用。

核心职责：
- 将自然语言推理（NL reasoning）转化为 Lean 4 代码；
- 调用 Lean 编译器做纯编译验证（不依赖任何 LLM client 的编译路径）；
- 编译失败时用注入的 agent 链 client 分析错误根因，映射为 BugReport/Finding；
- 全程受 wall-clock 超时与 Budget 约束；Lean 环境缺失时降级为
  ``verdict='unknown'``，供上层安全降级回退 LLM 验证。

依赖隔离：
- convert / analyze / fix 阶段的 LLM 调用一律使用注入的 client（依赖注入），
  禁止 import ``测试工具/`` 下的 ``get_config()`` / ``LLMClient``。
- 纯编译路径 ``_compile_lean`` 只依赖 Lean 编译器二进制，不依赖任何 LLM 栈，
  可独立复用。

修改影响:
- 被以下文件依赖: agent/lean_gate.py（deep 档硬验证门禁）、tests/test_lean_bridge.py
- 依赖以下文件: agent/base.py（BugReport / Finding / Budget）
- 自举依赖: deploy/setup_lean.sh（Lean 环境缺失时的自动安装脚本）
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import BugReport, Finding

logger = logging.getLogger("MathPilot")

# =====================================================================
# Lean 编译路径常量（纯编译，与 LLM 栈解耦）
# =====================================================================

_DEFAULT_LEAN_EXECUTABLE = "lake"      # Lean 4 可执行文件名
_DEFAULT_LEAN_TIMEOUT = 60.0           # 单次编译超时（秒）
_LEAN_DETECT_TIMEOUT = 10              # Lean 环境检测超时（秒）
_MAX_ERROR_CHARS = 5000                # 编译错误输出截断上限（防 token 爆炸）

# ---------------------------------------------------------------------
# 本地 Lean 工具链 / Mathlib 工程自动探测
# ---------------------------------------------------------------------
def _project_root() -> str:
    """仓库根目录（agent/ 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _detect_lean_executable() -> str:
    """自动探测本地 Lean 编译器（lean.exe）的绝对路径。

    优先级（命中即返回）：
      1) elan 管理的当前工具链 lean.exe（C:/Users/<user>/.elan/toolchains/.../bin/lean.exe）
      2) Windows: <root>/lean下载版/lean-toolchain/bin/lean.exe
      3) Linux:   <root>/deploy/lean-cache/lean-4.31.0-linux/bin/lean
    返回空串表示未探测到（调用方回退 "lake"）。
    """
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
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def _detect_lean_project_dir() -> str:
    """自动探测带 Mathlib 的 Lean 工程目录（编译 verify.lean 时 Mathlib 真正可用）。

    候选顺序：
      1) 已下载并独立编译好的 mathlib 仓库根目录 D:/mathlib4-last_bump_for_v4.31.0
         （独立 Lake 工程，含完整 Mathlib 源码与构建产物 .lake/build）；
      2) <root>/lean下载版/test_mathlib（仓库内工程，需其依赖 mathlib 已编译）。
    返回空串表示未挂载。
    """
    candidates = [
        "D:/mathlib4-last_bump_for_v4.31.0",
        os.path.join(_project_root(), "lean下载版", "test_mathlib"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return ""


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
    """
    roots: list[str] = [
        d for d in os.environ.get("LEAN_PATH", "").split(os.pathsep) if d
    ]
    if roots:
        return any(os.path.isfile(os.path.join(r, "Mathlib", "Tactic.olean"))
                   for r in roots)
    proj = _project_root()
    roots = [
        os.path.join(proj, "deploy", "mathlib-olean"),
        os.path.join(proj, "data", "mathlib-closure-core"),
        os.path.join(proj, "data", "mathlib-closure"),
    ]
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
    if re.search(r"^\s*import\s+Mathlib\.Tactic\s*$", code, re.MULTILINE):
        return re.sub(r"(?m)^\s*import\s+Mathlib\.Tactic\s*$",
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


# =====================================================================
# LLM 提示词模板（Lean 转化 / 错误分析）
# =====================================================================

# 转化阶段：把自然语言推理转成 Lean 4 代码
LEAN_CONVERT_SYSTEM = """你是一位 Lean 4 形式化专家。请把下面的数学推理过程转化为一段 Lean 4 代码（theorem + proof）。

要求：
1. 只输出 Lean 4 代码本身，不要输出解释、Markdown 代码块或额外文字。
2. 用 ``theorem ... : ... := by ...`` 结构表达命题与证明。
3. 优先使用 Mathlib 中已有的定理/引理（如 omega、linarith、ring、norm_num、positivity）。
4. 如果推理中某步无法形式化，用 ``sorry`` 占位并在代码末尾用注释标注：
   ``-- UNFORMALIZED: <该步的原始中文推理>``。
5. 不要修改题目本身，只对给定推理做形式化。"""

LEAN_CONVERT_USER = """## 原题
{problem}

## 待形式化的推理
{reasoning}

请输出对应的 Lean 4 代码。"""

# 答案审核阶段（2026-09-01，用户要求"所有题目都要用到 Lean"）：非证明题
# （解答题/计算题）的轻量答案验证 —— 只把最终答案与推理中的关键计算转成
# example + norm_num/ring 等轻量 tactic 证明，不整题形式化，控制编译开销。
LEAN_ANSWER_VERIFY_SYSTEM = """你是一位 Lean 4 形式化专家。你的任务是把"数学解答的最终答案与关键计算"转化为一段轻量 Lean 4 验证代码，用 norm_num / ring / nlinarith / omega / positivity / simp 等轻量 tactic 自动判定解答中的计算是否正确。

============================================================
要求
============================================================
1. 输出 Lean 4 代码：用 ``example : <命题> := by <轻量tactic>`` 形式表达"解答声称的计算/答案"，并让轻量 tactic 完成证明。
   - 数值计算题：example : (3 : ℚ) = 1 + 2 := by norm_num
   - 化简题：    example : (x + 1) ^ 2 = x ^ 2 + 2 * x + 1 := by ring
   - 不等式题：  example : (2 : ℚ) ≤ 3 := by norm_num
2. 只能形式化**解答中明确声称**的计算与答案，禁止自行补充解答未给出的结论。
3. **禁止 sorry / axiom / admit**，证明必须完全由轻量 tactic 完成。
4. **关键（答案锚定，最重要）**：验证命题的**结论侧必须逐字包含 USER 给出的
   最终答案原值**，左侧放推理中算出的关键计算/中间表达式：
   - 数字答案：example : <关键计算> = <最终答案> := by norm_num
     （如最终答案=7 → example : (1 + 2 * 3 : ℚ) = 7 := by norm_num）
   - 表达式答案：右侧写最终答案，左侧写推理中实际出现的中间表达式。
   - **禁止**把你自己重算的结果当右侧：USER 说最终答案是 4，你就必须写
     ``= 4``，**禁止**写 ``= 3`` 或你算出的任何其他值——否则等于没验证答案。
   - **禁止**恒等式作弊（如 example : (a : ℚ) = a，这验证不了任何计算）。
   - 若最终答案无法逐字嵌入验证命题（纯文字、解集集合、选项字母等），
     按第 5 条输出 error。
5. 若最终答案无法合理形式化（纯文字答案、答案依赖未给出的量、选项字母等），
   输出 JSON：{"error": "无法形式化原因"}，不要硬编。
6. 只输出 JSON，不要输出解释或 Markdown 代码块。

============================================================
输出格式（严格 JSON）
============================================================
```json
{
  "lean_code": "example : (3 : ℚ) = 1 + 2 := by\\n  norm_num",
  "answer_expr": "3",
  "note": "可选说明"
}
```
"""

LEAN_ANSWER_VERIFY_USER = """## 原题
{problem}

## 解答推理（含计算过程）
{reasoning}

## 解答给出的最终答案
{answer}

{answer_hint}请把最终答案与推理中的关键计算转化为轻量 Lean 验证代码（严格按系统提示输出 JSON）。
⚠ 硬性要求：上面「解答给出的最终答案」的原值必须逐字出现在你生成的验证命题结论侧
（example : <关键计算> = <最终答案>）。若你的验证代码没有包含该答案原值，
说明没有验证答案，属于无效输出——请直接输出 error。"""

# 分析阶段：把编译错误映射为可修复/致命缺陷
LEAN_ANALYZE_SYSTEM = """你是一位 Lean 4 与数学推理专家。下面是"自然语言推理"转化出的 Lean 4 代码及其编译错误，请判断错误的根因。

输出 JSON：
{{
  "error_category": "translation_error" | "logic_error" | "both" | "uncertain",
  "repairable": "yes" | "no" | "partial",
  "suggestion": "给修正建议，尽量具体",
  "critical_desc": "若是致命逻辑错误，说明错在哪一步、为什么错；否则留空"
}}

分类说明：
- translation_error：Lean 代码本身的语法/类型问题，或是对推理的形式化表述不当（可通过修改代码修复）；
- logic_error：推理本身的数学逻辑有致命缺陷，即使换一种形式化也无法成立；
- both：两者都有；uncertain：无法判断。"""

LEAN_ANALYZE_USER = """## 原题
{problem}

## 自然语言推理
{reasoning}

## Lean 4 代码
{lean_code}

## 编译错误
{compile_error}

请按 JSON 输出错误根因分析。"""


# =====================================================================
# Lean 环境检测 / 纯编译工具函数（可独立复用，不依赖 LLM 栈）
# =====================================================================

# 进程级一次性自举：Lean 缺失时尝试运行 deploy/setup_lean.sh（仅一次）
_LEAN_SETUP_TRIED = False


def _maybe_auto_setup_lean(lean_executable: str) -> None:
    """Lean 可执行缺失时，尽力运行 deploy/setup_lean.sh 自举环境（幂等）。

    - 仅在 exe 找不到且本进程未尝试过时执行一次（模块级 _LEAN_SETUP_TRIED）；
    - 纯 best-effort：任何失败都吞掉，返回后调用方照旧降级 unknown，绝不影响主流程；
    - 离线安装（--offline）优先，避免评测容器无外网时长时间等待在线安装。
    """
    global _LEAN_SETUP_TRIED
    if _LEAN_SETUP_TRIED or shutil.which(lean_executable):
        return
    _LEAN_SETUP_TRIED = True
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "deploy", "setup_lean.sh")
    if not os.path.exists(script):
        return
    try:
        # 评测容器多为 Linux；Windows 本地无 bash 时静默跳过
        subprocess.run(
            ["bash", script, "--offline"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(_LEAN_DETECT_TIMEOUT * 3, 30),
        )
    except Exception:  # noqa: BLE001
        pass


def detect_lean_environment(
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
) -> dict:
    """检测 Lean 4 环境是否可用，返回 {"available": bool, "version": str, "error": str}。

    检测前会尝试一次 lean 自举（见 _maybe_auto_setup_lean），
    使评测环境无需手工预装 Lean 即可自动接入。
    """
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LEAN_DETECT_TIMEOUT,
        )
        if result.returncode == 0:
            version = (result.stdout.strip().split("\n")[0]
                       if result.stdout else "unknown")
            return {"available": True, "version": version, "error": ""}
        return {"available": False, "version": "",
                "error": (result.stderr or result.stdout).strip()[:200]}
    except FileNotFoundError:
        # 尝试自举一次，再重新检测
        _maybe_auto_setup_lean(exe)
        try:
            result = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_LEAN_DETECT_TIMEOUT,
            )
            if result.returncode == 0:
                version = (result.stdout.strip().split("\n")[0]
                           if result.stdout else "unknown")
                return {"available": True, "version": version, "error": ""}
        except Exception:  # noqa: BLE001
            pass
        return {"available": False, "version": "",
                "error": f"Lean executable not found: {exe}"}
    except subprocess.TimeoutExpired:
        return {"available": False, "version": "",
                "error": f"Lean detection timed out ({_LEAN_DETECT_TIMEOUT}s)"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "version": "", "error": str(exc)[:200]}


def _truncate_error_output(text: str, limit: int = _MAX_ERROR_CHARS) -> str:
    """截断编译错误输出，防止提示词 token 爆炸（编译错误不记录完整原文）。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [已截断，共 %d 字符]" % len(text)


def _compile_lean(
    code: str,
    work_dir: str,
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
    timeout: float = _DEFAULT_LEAN_TIMEOUT,
    lean_filename: str = "verify.lean",
    allow_sorry: bool = False,
) -> dict:
    """调用 Lean 编译器编译一段 Lean 代码（纯编译路径，不依赖 LLM 栈）。

    参数:
        code: Lean 4 源码。
        work_dir: 编译工作目录（写入 .lean 文件并执行 lake 的目录）。
        lean_executable: Lean 可执行文件名（默认 "lake"，配合 lean-toolchain）。
        timeout: 编译超时（秒）。
        allow_sorry: 声明模式开关。True 时「编译通过但含 sorry」视为 ok
            （用于题目前置形式化验证：只校验命题声明类型正确，不要求证明完整）；
            默认 False 保持后置证明验证原行为（含 sorry 视为未完全验证）。

    返回:
        {"ok": bool, "error": str}。
    """
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    lean_file = os.path.join(work_dir, lean_filename)
    with open(lean_file, "w", encoding="utf-8") as f:
        f.write(code)

    # lake 分支（含绝对路径 lake.exe）：lake env lean <file> 正确加载工程
    # LEAN_PATH（注意必须带 "lean"，lake env 的语义是"在 lake 环境下运行命令"）
    is_lake = (exe == "lake"
               or os.path.basename(exe).lower().startswith("lake"))
    cmd = ([exe, "env", "lean", lean_filename] if is_lake
           else [exe, lean_filename])
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        err = (result.stderr or "") + (result.stdout or "")
        if result.returncode == 0:
            # 编译通过；声明模式（allow_sorry=True）允许 sorry 占位，
            # 否则仍视为未完全验证（含 sorry 视为失败）。
            if not allow_sorry and re.search(r"\bsorry\b", code):
                return {"ok": False,
                        "error": "编译通过但包含 sorry 占位（存在未形式化步骤）"}
            return {"ok": True, "error": ""}
        return {"ok": False, "error": _truncate_error_output(err)}
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": f"Lean 编译超时（>{timeout:.0f}s）"}
    except FileNotFoundError:
        return {"ok": False, "error": f"Lean executable not found: {exe}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _truncate_error_output(str(exc))}


# =====================================================================
# LeanBridge：Lean 验证桥接层（依赖注入 client）
# =====================================================================

class LeanBridge:
    """Lean 验证桥接层，把 Lean 形式化验证能力接入 agent 链。

    - ``client``：注入的 agent 链 LLM 客户端（``BaseAgent.llm()`` 或等价接口），
      用于 convert / analyze 阶段，禁止 import ``测试工具/`` 的 LLM 栈；
    - ``config``：只读配置（含 ``lean_executable`` / ``lean_timeout`` 等），
      缺省用模块默认值；
    - ``verify()`` 同步接口（内部 asyncio.run 包装），供 SolverAgent 直接调用。
    """

    def __init__(self, client, config: Any = None, budget=None):
        self.client = client
        self.config = config
        self.budget = budget
        self._lean_env_cache: Optional[dict] = None
        self._mathlib_ready_cache: Optional[bool] = None

    # ------------------------------------------------------------------
    # 环境与配置
    # ------------------------------------------------------------------

    @property
    def lean_available(self) -> bool:
        """复用 Lean 环境检测结果（带缓存），Lean 不可用时返回 False。"""
        if self._lean_env_cache is None:
            self._lean_env_cache = detect_lean_environment(
                self._lean_executable)
        return bool(self._lean_env_cache.get("available"))

    @property
    def _lean_executable(self) -> str:
        """取配置中的 Lean 可执行文件名，缺省 "lake"。"""
        cfg = getattr(self.config, "config", self.config)
        exe = getattr(cfg, "lean_executable", "") or _DEFAULT_LEAN_EXECUTABLE
        return exe

    @property
    def _lean_timeout(self) -> float:
        """取配置中的 Lean 编译超时（秒），缺省 60s。"""
        cfg = getattr(self.config, "config", self.config)
        return float(getattr(cfg, "lean_timeout", _DEFAULT_LEAN_TIMEOUT)
                     or _DEFAULT_LEAN_TIMEOUT)

    @property
    def _lean_project_dir(self) -> str:
        """取配置中的带 Mathlib 的 Lean 工程目录，缺省自动探测。"""
        cfg = getattr(self.config, "config", self.config)
        pdir = getattr(cfg, "lean_project_dir", "") or _detect_lean_project_dir()
        return pdir

    def _mathlib_ready(self) -> bool:
        """探测 Mathlib 是否已编译就绪（核心 tactic 模块可用）。

        本地工程采用「部分编译」布局：因 v4.31.0 兼容问题，全量 Mathlib 聚合
        无法生成，但核心模块 Mathlib.Tactic（norm_num/ring/omega/linarith 等）
        已编译完成，跑分证明足够。故就绪判定以 Mathlib.Tactic.olean 为准
        （而非全量 Mathlib.olean）。结果按进程缓存。

        比赛环境（无 lake 工程目录）：LEAN_PATH 挂载了 core/full 闭包
        （deploy/mathlib-olean，由 deploy/setup_lean.sh 写入）同样视为就绪，
        否则 lean_gate 硬验证会退回纯核心 Lean 而用不上闭包（2026-09-01 修复）。
        """
        if getattr(self, "_mathlib_ready_cache", None) is not None:
            return self._mathlib_ready_cache
        pdir = self._lean_project_dir
        ready = False
        if pdir:
            candidates = [
                os.path.join(pdir, ".lake", "packages", "mathlib", ".lake",
                             "build", "lib", "lean", "Mathlib", "Tactic.olean"),
                os.path.join(pdir, ".lake", "build", "lib", "lean",
                             "Mathlib", "Tactic.olean"),
                os.path.join(pdir, ".lake", "build", "lib", "lean",
                             "Mathlib.olean"),  # 全量布局兼容
            ]
            if any(os.path.isfile(c) for c in candidates):
                ready = True
            else:
                # 兜底：.lake 子树内找 Mathlib/Tactic.olean 或 Mathlib.olean
                for root, _d, files in os.walk(os.path.join(pdir, ".lake")):
                    if "Tactic.olean" in files or "Mathlib.olean" in files:
                        ready = True
                        break
        else:
            # 无 lake 工程（比赛环境）：LEAN_PATH 或默认部署目录挂载闭包即就绪
            roots: list[str] = [
                d for d in os.environ.get("LEAN_PATH", "").split(os.pathsep) if d
            ]
            proj = _project_root()
            roots += [
                os.path.join(proj, "deploy", "mathlib-olean"),
                os.path.join(proj, "data", "mathlib-closure"),
            ]
            for r in roots:
                # core 闭包无聚合入口，用具体模块 olean 判定；full 闭包两者皆有
                if (os.path.isfile(os.path.join(r, "Mathlib", "Tactic.olean"))
                        or os.path.isfile(os.path.join(
                            r, "Mathlib", "Tactic", "NormNum.olean"))):
                    ready = True
                    break
        self._mathlib_ready_cache = ready
        return ready

    def _budget_ok(self, n: int = 1) -> bool:
        """检查 LLM 调用预算是否足够（预算为 None 时不限制）。"""
        if self.budget is None:
            return True
        return self.budget.can_spend(n)

    # ------------------------------------------------------------------
    # LLM 调用（走注入的 client，计入 Budget）
    # ------------------------------------------------------------------

    def _llm_call(self, messages: list, temperature: float,
                  max_tokens: int, prefill: str = "") -> str:
        """用注入的 client 调用一次 LLM（convert/analyze 阶段），计入 Budget。

        prefill 非空时走 **assistant-prefill 解码**（Intern 系列铁律）：
        在消息末尾追加 assistant 种子前缀，让模型进入"续写模式"，
        抑制 `reasoning_content` 思维块（否则思维块吃满 max_tokens，
        JSON/代码被腰斩，finish_reason=length）。种子必须锚定顶层结构，
        如 `'{"lean_code":'` / `'{"formal_spec":'` / `'import Mathlib.Tactic'`。
        返回前用 ``stitch`` 把种子与续写拼接回完整文本（兼容后端
        continuation/echo/ignored 三种形态）。
        """
        if not self._budget_ok(1):
            logger.warning("[LeanBridge] 预算耗尽，跳过 LLM 调用")
            return ""
        msgs = messages
        seed = prefill
        stitch = None
        if seed:
            try:
                from utils.prefill import prefill_messages as _pfm, stitch as _st
            except ImportError:
                try:
                    from submit.utils.prefill import (
                        prefill_messages as _pfm, stitch as _st)
                except ImportError:
                    _pfm = _st = None
            if _pfm is not None:
                msgs = _pfm(messages, seed)
                stitch = _st
        resp = self.client.chat(
            messages=msgs, temperature=temperature, max_tokens=max_tokens)
        text = _normalize_bridge_response(resp)
        # 响应为空（API 故障/预算耗尽）时不拼接种子——否则种子本身会被当成
        # 结果（如 "import Mathlib.Tactic\n" 恰好是合法 Lean 代码 → 假 proof_valid）。
        if seed and stitch is not None and text:
            text = stitch(seed, text)
        # Anti-hack 预处理（SU-01 §3.3）：格式病理 → safe fallback。
        # 放在 stitch 之后，检查完整文本（含种子拼接后的产物）。
        if text:
            text = _anti_hack_guard(text)
        if self.budget is not None:
            self.budget.spend(1)
        return text

    # ------------------------------------------------------------------
    # 阶段一：NL → Lean 转化
    # ------------------------------------------------------------------

    def _convert_to_lean(self, problem: str, reasoning: str) -> str:
        """把自然语言推理转化为 Lean 4 代码（依赖注入的 client，走 prefill）。"""
        messages = [
            {"role": "system", "content": LEAN_CONVERT_SYSTEM},
            {"role": "user", "content": LEAN_CONVERT_USER.format(
                problem=problem, reasoning=reasoning)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=2048,
                             prefill=_mathlib_import_block() + "\n")
        return _strip_code_fence(raw)

    # ------------------------------------------------------------------
    # 阶段二：编译验证（纯编译路径）
    # ------------------------------------------------------------------

    def _compile(self, code: str, work_dir: str,
                 lean_filename: str = "verify.lean",
                 allow_sorry: bool = False) -> dict:
        """复用纯编译路径 ``_compile_lean`` 对转化出的 Lean 代码做编译验证。

        work_dir 为带 lakefile 的工程目录时强制走 ``lake env lean``
        （正确加载 Mathlib 的 LEAN_PATH）；否则用探测到的 lean.exe 编译
        （纯核心 Lean，临时目录回退路径）。

        lean_filename 仅在使用带 Mathlib 的 Lean 工程目录（避免覆盖工程内已有
        verify.lean）或需并发安全时指定；缺省仍写 verify.lean。
        allow_sorry 透传给 ``_compile_lean``：前置形式化（声明模式）允许 sorry
        占位，后置答案验证（默认）不允许。
        """
        is_lake_project = any(
            os.path.isfile(os.path.join(work_dir, f))
            for f in ("lakefile.toml", "lakefile.lean", "lake-manifest.json"))
        if is_lake_project:
            # 用 elan lake 绝对路径（避免 subprocess PATH 解析问题）
            elan_lake = os.path.expanduser(r"~\.elan\bin\lake.exe")
            exe = elan_lake if os.path.isfile(elan_lake) else "lake"
        else:
            exe = self._lean_executable
            # 非 lake 工程（比赛环境临时目录）：优先用探测到的 lean.exe 直编。
            # 否则 exe 缺省为 "lake"，在无 lakefile 的临时目录跑 `lake env lean`
            # 会报错（找不到 lakefile），导致硬验证全部失败（2026-09-01 修复）。
            detected = _detect_lean_executable()
            if detected:
                exe = detected
        return _compile_lean(code, work_dir,
                             lean_executable=exe,
                             timeout=self._lean_timeout,
                             lean_filename=lean_filename,
                             allow_sorry=allow_sorry)

    # ------------------------------------------------------------------
    # 阶段三：错误分析（映射为 BugReport / Finding）
    # ------------------------------------------------------------------

    def _analyze_error(self, problem: str, reasoning: str,
                       lean_code: str, compile_error: str) -> BugReport:
        """编译失败时分析根因，映射为 BugReport（依赖注入的 client）。

        - 逻辑错误 → Critical Finding，verdict='proof_invalid'；
        - 纯翻译错误 / 无法判断 → verdict='unknown'（供上层降级）。
        """
        messages = [
            {"role": "system", "content": LEAN_ANALYZE_SYSTEM},
            {"role": "user", "content": LEAN_ANALYZE_USER.format(
                problem=problem, reasoning=reasoning,
                lean_code=lean_code, compile_error=compile_error)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=1024,
                             prefill='{"error_category":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return BugReport(verdict="unknown", findings=[])

        category = parsed.get("error_category", "uncertain")
        repairable = parsed.get("repairable", "") or ""
        suggestion = parsed.get("suggestion", "") or ""
        critical_desc = parsed.get("critical_desc", "") or ""

        if category in ("logic_error", "both"):
            findings = [Finding(
                location="lean_verify", kind="Critical", severity=5,
                desc=critical_desc or suggestion or compile_error[:300])]
            report = BugReport(findings=findings, verdict="proof_invalid")
        else:
            # 纯翻译错误 / uncertain：视为可修复缺口，但需人工复核 → 降级 unknown
            findings = [Finding(
                location="lean_translate", kind="Gap", severity=1,
                desc=critical_desc or suggestion or "Lean 形式化/编译存在问题")] if repairable in ("yes", "partial") else []
            report = BugReport(findings=findings, verdict="unknown")

        # 附加可修复性与修正建议（改造2 新增可选字段，向后兼容）
        report.repairable = repairable
        report.suggestion = suggestion
        return report

    # ------------------------------------------------------------------
    # 对外同步接口
    # ------------------------------------------------------------------

    def verify(self, problem: str, reasoning: str, domain: str = "",
               timeout: float = 60.0) -> Optional[BugReport]:
        """NL 推理 → Lean 形式化验证 → 错误分析 → BugReport（同步接口）。

        - 编译通过且无 sorry → BugReport(verdict='proof_valid')
        - 逻辑错误 → BugReport(findings=[Critical...], verdict='proof_invalid')
        - 纯翻译错误 / Lean 环境缺失 / 超时 → BugReport(verdict='unknown') 供上层降级
        - 全程受 timeout 与 Budget 约束，不抛异常。

        参数:
            problem: 原题。
            reasoning: 待验证的推理文本。
            domain: 题目领域（暂未使用，预留扩展）。
            timeout: 整体 wall-clock 超时（秒）。

        返回:
            BugReport 或 None（内部异常时返回 None，由上层降级）。
        """
        deadline = time.monotonic() + max(1.0, timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                logger.warning("[LeanBridge] Lean 环境不可用，降级为 unknown")
                return BugReport(verdict="unknown", findings=[])

            # 2) 阶段一：NL → Lean 转化
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            lean_code = self._convert_to_lean(problem, reasoning)
            if not lean_code:
                return BugReport(verdict="unknown", findings=[])

            # 3) 阶段二：编译验证
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            project_dir = self._lean_project_dir
            # Mathlib 就绪判定提前：比赛环境无 lake 工程（_lean_project_dir 为空），
            # 但 LEAN_PATH 已挂载 core/full 闭包（deploy/setup_lean.sh）→ 同样
            # prepend Mathlib import，否则硬验证退回纯核心 Lean 用不上闭包
            # （2026-09-01 修复，比赛环境关键路径）。
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(lean_code)
                               if use_mathlib else lean_code)
            comp = None
            if project_dir:
                # 走带 Mathlib 依赖的 Lean 工程目录：Mathlib 真正可用。
                lean_file = "verify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file)
                try:
                    os.remove(os.path.join(project_dir, lean_file))
                except OSError:
                    pass
            else:
                # 比赛环境回退：单文件临时目录（lean.exe 直编 + LEAN_PATH 挂载闭包）
                with tempfile.TemporaryDirectory(prefix="lean_bridge_") as work_dir:
                    comp = self._compile(code_to_compile, work_dir)

            if comp and comp.get("ok"):
                # 编译通过且无 sorry（_compile_lean 已拦截 sorry）→ proof_valid。
                # 关键修复：此前 project_dir 分支会穿透到 _analyze_error 而把
                # 一次成功的 Mathlib 形式化验证误判为 unknown（与老师要求的
                # "AI解答→Lean形式化(mathlib)→自动判定通过/不通过" 不符）。
                return BugReport(verdict="proof_valid", findings=[])

            # 4) 阶段三：错误分析（project_dir 分支编译失败同样走此路径，
            #    避免 verify() 落空返回 None 导致上层拿不到 BugReport）
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            return self._analyze_error(
                problem, reasoning, lean_code,
                comp.get("error", "编译失败（无详细输出）") if comp else "编译失败（无详细输出）")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] verify 异常（降级 unknown）: %s", exc)
            return BugReport(verdict="unknown", findings=[])

    # ------------------------------------------------------------------
    # 答案审核（轻量路径）：最终答案 norm_num/ring 结果验证（2026-09-01）
    # ------------------------------------------------------------------
    def _convert_answer_to_lean(self, problem: str, reasoning: str,
                                answer: str,
                                answer_hint: str = "") -> Optional[str]:
        """把最终答案 + 推理关键计算转成轻量 Lean example 验证代码。

        用依赖注入的 client 调用书生：输出 ``example : <命题> := by <tactic>``
        形式的验证代码。无法形式化（LLM 返回 error / 解析失败 / 无代码）返回 None，
        由调用方降级 unknown。

        answer_hint 非空时（重试），附加到 USER 提示词强制书生把最终答案
        逐字锚定到验证命题结论侧（修正「书生自己重算、无视 USER 答案」的缺陷）。
        """
        hint = ("\n## 上一轮验证代码没有包含最终答案原值（无效输出）\n"
                + answer_hint.strip() + "\n") if answer_hint else ""
        messages = [
            {"role": "system", "content": LEAN_ANSWER_VERIFY_SYSTEM},
            {"role": "user", "content": LEAN_ANSWER_VERIFY_USER.format(
                problem=problem, reasoning=reasoning, answer=answer,
                answer_hint=hint)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=2048,
                             prefill='{"lean_code":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return None
        if parsed.get("error"):
            logger.info("[LeanBridge] 答案无法形式化: %s",
                        str(parsed["error"])[:120])
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        if not lean_code:
            return None
        # 数字锚定兜底校验：answer 为纯数字时，lean_code 必须包含该数字原值，
        # 否则视为「没有验证答案」（书生自己重算而非审核 USER 答案），带反馈重试一次。
        if not _answer_embedded(lean_code, answer):
            logger.warning(
                "[LeanBridge] 答案数字 %r 未出现在验证代码（书生自算而非审核答案），重试",
                (answer or "").strip()[:40])
            retry_hint = ("\n## 上一轮输出无效：你生成的验证代码没有包含最终答案原值 "
                          + (answer or "").strip()[:60]
                          + "。请重新生成，结论侧必须逐字写该答案："
                            "example : <关键计算> = <该答案> := by <tactic>\n")
            retry_msgs = [
                {"role": "system", "content": LEAN_ANSWER_VERIFY_SYSTEM},
                {"role": "user", "content": LEAN_ANSWER_VERIFY_USER.format(
                    problem=problem, reasoning=reasoning, answer=answer,
                    answer_hint=retry_hint)},
            ]
            raw2 = self._llm_call(retry_msgs, temperature=0.0, max_tokens=2048,
                                  prefill='{"lean_code":')
            parsed2 = _parse_analysis_json(raw2)
            if not parsed2 or parsed2.get("error"):
                return None
            lean_code = _strip_code_fence(str(parsed2.get("lean_code", "") or ""))
            if not lean_code or not _answer_embedded(lean_code, answer):
                return None
        return lean_code

    def verify_answer(self, problem: str, reasoning: str, answer: str,
                      domain: str = "", timeout: float = 60.0) -> Optional[BugReport]:
        """答案审核（轻量路径，非证明题）：最终答案 + 关键计算用 norm_num/ring 验证。

        与 ``verify()``（整题形式化，证明题）的区别：这里只验证解答**声称的计算与
        最终答案**，编译 5-21s 内，不整题形式化，满足用户「证明题+解答题都要过
        Lean」但控制时间开销的要求。

        - 编译通过 → BugReport(verdict='answer_valid')（计算/答案经 Lean 判定正确）
        - 逻辑错误（norm_num 证不出 / 计算与推理矛盾）→ verdict='proof_invalid'
        - 翻译问题 / 答案无法形式化 / 环境缺失 / 超时 → verdict='unknown' 降级放行

        返回的 BugReport 附加 ``lean_code`` 属性（供上层埋点提取 import/example）。
        """
        deadline = time.monotonic() + max(1.0, timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                logger.warning("[LeanBridge] Lean 环境不可用，答案验证降级 unknown")
                return BugReport(verdict="unknown", findings=[])

            # 2) 无答案 / 选项字母答案（选择题）→ 无法 norm_num 验证，降级放行
            answer = (answer or "").strip()
            if not answer:
                return BugReport(verdict="unknown", findings=[])
            if re.fullmatch(r"[A-Da-d][.、)]?|第[一二三四]个|（[A-Da-d]）", answer):
                return BugReport(verdict="unknown", findings=[])

            # 3) 阶段一：答案 + 关键计算 → 轻量 Lean example
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            lean_code = self._convert_answer_to_lean(problem, reasoning, answer)
            if not lean_code:
                return BugReport(verdict="unknown", findings=[])

            # 4) 阶段二：编译验证（不允许 sorry —— 答案必须被 tactic 证出）
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(lean_code)
                               if use_mathlib else lean_code)
            if project_dir:
                lean_file = "ansverify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=False)
                try:
                    os.remove(os.path.join(project_dir, lean_file))
                except OSError:
                    pass
            else:
                with tempfile.TemporaryDirectory(prefix="lean_ansverify_") as work_dir:
                    comp = self._compile(code_to_compile, work_dir,
                                         allow_sorry=False)

            if comp and comp.get("ok"):
                report = BugReport(verdict="answer_valid", findings=[])
                # 附加 lean_code 供上层埋点提取 import/example（BugReport 无此字段）
                setattr(report, "lean_code", lean_code)
                return report

            # 5) 阶段三：错误分析（把最终答案并入 reasoning 上下文，定位更准）
            if time.monotonic() > deadline:
                return BugReport(verdict="unknown", findings=[])
            return self._analyze_error(
                problem,
                reasoning + "\n## 最终答案\n" + answer,
                lean_code,
                comp.get("error", "答案验证编译失败（无详细输出）")
                if comp else "答案验证编译失败（无详细输出）")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] verify_answer 异常（降级 unknown）: %s", exc)
            return BugReport(verdict="unknown", findings=[])

    # ------------------------------------------------------------------
    # 前置形式化验证：题目 → Lean 定理声明 → 声明模式编译
    # ------------------------------------------------------------------

    def _formalize_to_lean(self, problem: str, domain: str = "",
                           feedback: str = "") -> Optional[dict]:
        """把题目转化为 Lean 定理声明（依赖注入 client），返回 {"formal_spec", "lean_code"}。

        feedback 非空时，把上一次编译错误回传给书生，要求重新理解题目并修正形式化。
        转化失败（LLM 空返回 / JSON 解析失败 / 无 lean_code）返回 None。
        """
        try:
            from prompts.lean_pre_verify import (
                LEAN_FORMALIZE_PROBLEM_SYSTEM, LEAN_FORMALIZE_PROBLEM_USER)
        except ImportError:  # 提交包（submit/）路径兜底
            from submit.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_PROBLEM_SYSTEM, LEAN_FORMALIZE_PROBLEM_USER)
        feedback_block = ""
        if feedback:
            feedback_block = ("## 上一次形式化声明编译失败（请重新理解题目并修正）\n"
                              + _truncate_error_output(feedback) + "\n\n")
        messages = [
            {"role": "system", "content": LEAN_FORMALIZE_PROBLEM_SYSTEM},
            {"role": "user", "content": LEAN_FORMALIZE_PROBLEM_USER.format(
                problem=problem, domain=domain or "未知", feedback=feedback_block)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=2048,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)  # 通用 JSON 提取（功能与 analysis 一致）
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or "")
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}

    def formalize_problem(self, problem: str, domain: str = "",
                          timeout: Optional[float] = None,
                          feedback: str = "") -> dict:
        """题目前置形式化验证（同步接口，不抛异常）。

        把题目转成 Lean 定理声明（证明 sorry 占位），用声明模式（allow_sorry）编译校验：
        - 声明 well-typed（编译 returncode==0，允许 sorry）→ verdict="ok"
        - 声明类型/语法错误 → verdict="fail"（附编译错误，供修正循环回传）
        - Lean 不可用 / 超时 / 转化失败 → verdict="unknown"（安全降级，不阻断主流程）

        参数:
            problem: 原题文本。
            domain: 题目领域（可选）。
            timeout: 整体 wall-clock 超时（秒），缺省用 self._lean_timeout。
            feedback: 上一次编译错误（非空时回传书生重新理解题目修正）。

        返回:
            {"verdict": "ok"|"fail"|"unknown", "lean_code": str,
             "formal_spec": str, "error": str,
             "gaps": list}  —— gaps 为编译失败抽取的结构化「缺口」
            （缺失定义/引理/模块/类型不匹配），供 SubGoalSolver 直接转化为子目标。
        """
        deadline = time.monotonic() + max(1.0, timeout or self._lean_timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "Lean 环境不可用"}
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "前置形式化超时"}

            # 2) 题目 → Lean 定理声明
            converted = self._formalize_to_lean(problem, domain, feedback)
            if not converted:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "题目形式化转化失败"}

            # 3) 声明模式编译（允许 sorry 占位；仅校验命题声明类型正确）
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "前置形式化超时"}
            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(converted["lean_code"])
                               if use_mathlib else converted["lean_code"])
            if project_dir:
                # 走带 Mathlib 的 Lean 工程目录：证明题真正能用上 Mathlib tactic
                # （norm_num / ring / omega / linarith …）。仅当 Mathlib 已编译就绪
                # 才 import Mathlib，否则退回核心 Lean，避免误判。
                lean_file = "preverify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=True)
                try:
                    os.remove(os.path.join(project_dir, lean_file))
                except OSError:
                    pass
            else:
                with tempfile.TemporaryDirectory(prefix="lean_preverify_") as work_dir:
                    comp = _compile_lean(
                        code_to_compile, work_dir,
                        lean_executable=self._lean_executable,
                        timeout=min(self._lean_timeout,
                                    max(1.0, deadline - time.monotonic())),
                        allow_sorry=True,
                    )
            if comp.get("ok"):
                # 声明 well-typed（允许 sorry）→ 理解正确，无缺口
                return {"verdict": "ok", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "",
                        "gaps": []}
            # 编译失败：抽取「缺口」供子目标构建（看缺哪些）
            gaps = _analyze_formal_gaps(comp.get("error", ""))
            return {"verdict": "fail", "lean_code": converted["lean_code"],
                    "formal_spec": converted["formal_spec"],
                    "error": comp.get("error", "声明编译失败"),
                    "gaps": gaps}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] formalize_problem 异常（降级 unknown）: %s", exc)
            return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                    "error": str(exc)[:200]}

    # ------------------------------------------------------------------
    # 骨架(sketch) 形式化 + Lean 语法审核（#28）
    # ------------------------------------------------------------------
    def _formalize_sketch_to_lean(self, sketch_nl: str, problem: str = "",
                                  domain: str = "", feedback: str = "") -> Optional[dict]:
        """把 AI 生成的题目骨架(sketch / Proof Body Outline)形式化为 Lean 骨架声明。

        与 ``_formalize_to_lean``（形式化题目命题）不同，这里形式化的是**解题骨架**：
        把骨架里每个子目标转成 ``theorem subgoal_i : <stmt> := by sorry`` 的声明，
        外加最终目标 ``theorem main_goal : <final> := by sorry``。编译这些声明即可用
        Lean 校验「骨架是否 well-typed」——子目标命题本身类型是否正确、彼此是否一致，
        这正是老师要求的「骨架严谨性需 Lean 审核」。

        feedback 非空时回传上一次编译错误，要求重新生成骨架。
        """
        try:
            from prompts.lean_pre_verify import (
                LEAN_FORMALIZE_SKETCH_SYSTEM, LEAN_FORMALIZE_SKETCH_USER)
        except ImportError:
            from submit.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_SKETCH_SYSTEM, LEAN_FORMALIZE_SKETCH_USER)
        feedback_block = ""
        if feedback:
            feedback_block = ("## 上一次骨架 Lean 声明编译失败（请修正骨架的形式化）\n"
                              + _truncate_error_output(feedback) + "\n\n")
        messages = [
            {"role": "system", "content": LEAN_FORMALIZE_SKETCH_SYSTEM},
            {"role": "user", "content": LEAN_FORMALIZE_SKETCH_USER.format(
                problem=problem, domain=domain or "未知",
                sketch=sketch_nl, feedback=feedback_block)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=2048,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or parsed.get("outline", ""))
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}

    def audit_sketch(self, sketch_nl: str, problem: str = "", domain: str = "",
                     timeout: Optional[float] = None,
                     feedback: str = "") -> dict:
        """骨架(sketch) Lean 语法/类型审核（#28）。

        把 AI 生成的骨架形式化为 Lean 骨架声明（子目标 theorem + sorry 占位），
        用声明模式（allow_sorry）编译，仅校验**命题声明是否 well-typed**：
        - 全部声明 well-typed → verdict="ok"（骨架严谨，可进入求解）
        - 某子目标声明类型/语法错误 → verdict="fail"，附结构化 ``gaps``
          （缺失定义/引理/模块/类型不匹配），直接告诉 AI「骨架哪一步不对」
        - Lean 不可用 / 超时 / 转化失败 → verdict="unknown"（安全降级）

        参数:
            sketch_nl: 书生生成的骨架/Proof Body Outline（自然语言或含 Lean 片段）。
            problem/domain: 原题与领域（注入形式化提示，提升骨架形式化质量）。
            timeout: 整体 wall-clock 超时（秒）。
            feedback: 上一次编译错误（非空时回传重新生成骨架）。

        返回:
            {"verdict": "ok"|"fail"|"unknown", "lean_code": str,
             "formal_spec": str, "error": str, "gaps": list}
        """
        deadline = time.monotonic() + max(1.0, timeout or self._lean_timeout)
        try:
            if not self.lean_available:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "Lean 环境不可用", "gaps": []}
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "骨架审核超时", "gaps": []}

            converted = self._formalize_sketch_to_lean(sketch_nl, problem, domain, feedback)
            if not converted:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "骨架形式化转化失败", "gaps": []}

            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"],
                        "error": "骨架审核超时", "gaps": []}

            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(converted["lean_code"])
                               if use_mathlib else converted["lean_code"])
            if project_dir:
                lean_file = "sketch_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=True)
                try:
                    os.remove(os.path.join(project_dir, lean_file))
                except OSError:
                    pass
            else:
                with tempfile.TemporaryDirectory(prefix="lean_sketch_") as work_dir:
                    comp = _compile_lean(
                        code_to_compile, work_dir,
                        lean_executable=self._lean_executable,
                        timeout=min(self._lean_timeout,
                                    max(1.0, deadline - time.monotonic())),
                        allow_sorry=True,
                    )
            if comp.get("ok"):
                return {"verdict": "ok", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "",
                        "gaps": []}
            gaps = _analyze_formal_gaps(comp.get("error", ""))
            return {"verdict": "fail", "lean_code": converted["lean_code"],
                    "formal_spec": converted["formal_spec"],
                    "error": comp.get("error", "骨架声明编译失败"),
                    "gaps": gaps}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] audit_sketch 异常（降级 unknown）: %s", exc)
            return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                    "error": str(exc)[:200], "gaps": []}


# =====================================================================
# 桥接工具函数
# =====================================================================

def _normalize_bridge_response(resp: Any) -> str:
    """把注入 client 的返回统一成字符串（与 user_agent 归一化保持一致）。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, bytes):
        try:
            return resp.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    if isinstance(resp, dict):
        for key in ("content", "text", "output", "result"):
            if key in resp and resp[key]:
                return _normalize_bridge_response(resp[key])
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            choice = resp["choices"][0]
            if isinstance(choice, dict):
                if "message" in choice:
                    return _normalize_bridge_response(choice["message"])
                if "text" in choice:
                    return str(choice["text"])
            return _normalize_bridge_response(choice)
        if "message" in resp:
            return _normalize_bridge_response(resp["message"])
        return ""
    for attr in ("content", "text", "response"):
        try:
            val = getattr(resp, attr, None)
            if val is not None:
                return _normalize_bridge_response(val)
        except Exception:  # noqa: BLE001
            pass
    try:
        s = str(resp)
        return s if s and s != "None" else ""
    except Exception:  # noqa: BLE001
        return ""


# =====================================================================
# Anti-hack 预处理（2026-09-01 SU-01 优化 1，论文 §3.3）
# ---------------------------------------------------------------------
# SU-01 在 refined RL 把「格式病理」输出替换为安全 fallback，防止模型靠
# 模板泄漏/重复等骗过验证器。MathPilot 等价物：翻译/分析阶段 LLM 输出
# 出现 chat-template token 泄漏、thinking 分隔符不平衡、严重重复时，
# 直接返回 fallback（后续 Lean 编译必失败，但显式失败好过垃圾进编译器）。
# 只影响 _llm_call 的统一出口，调用方行为可预期（编译失败 → 走错误路径）。
# =====================================================================
_SAFE_FALLBACK = "I cannot provide a solution due to generation pathology."

_CHAT_TEMPLATE_LEAK_PATS = [
    r"<\|im_start\|>", r"<\|im_end\|>", r"<\|im_sep\|>",
    r"<\|assistant\|>", r"<\|user\|>", r"<\|system\|>",
    r"<s>", r"</s>", r"<\|endoftext\|>",
    r"chat_template",
]


def _anti_hack_guard(text: str) -> str:
    """SU-01 §3.3 三检查：chat-template 泄漏 / thinking 分隔符不平衡 / 严重重复。

    命中任一 → 返回 _SAFE_FALLBACK；正常文本原样返回。
    """
    if not text:
        return text
    # 1) chat-template token 泄漏（模型吐出了模板而非内容）
    if any(re.search(p, text) for p in _CHAT_TEMPLATE_LEAK_PATS):
        logger.warning("[LeanBridge] anti-hack: chat-template 泄漏 → fallback")
        return _SAFE_FALLBACK
    # 2) thinking 分隔符不平衡（prefill 已抑制思维块；出现即病理）
    if text.count("<thinking>") != text.count("</thinking>"):
        logger.warning(
            "[LeanBridge] anti-hack: thinking 分隔符不平衡 "
            "(open=%d close=%d) → fallback",
            text.count("<thinking>"), text.count("</thinking>"),
        )
        return _SAFE_FALLBACK
    # 3) 严重重复：≥12 行文本中，同一行出现 ≥50% 次数
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 12:
        from collections import Counter
        top_line, top_cnt = Counter(lines).most_common(1)[0]
        if top_cnt >= len(lines) * 0.5:
            logger.warning(
                "[LeanBridge] anti-hack: 严重重复 (line=%r x%d) → fallback",
                top_line[:40], top_cnt,
            )
            return _SAFE_FALLBACK
    return text


def _strip_code_fence(text: str) -> str:
    """去除 LLM 返回的 Markdown 代码围栏（```lean ... ```），只保留代码体。"""
    if not text:
        return ""
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _analyze_formal_gaps(compile_error: str) -> list:
    """从 Lean 形式化声明的编译错误中抽取结构化「缺口」（子目标候选）。

    用于题目前置形式化：编译失败往往说明 AI 对题意理解存在缺口
    （未定义的量/引理、类型不匹配、缺少模块导入等）。把这些缺口结构化，
    供 SubGoalSolver 直接转化为「需要先证明/补充什么」的子目标
    —— 即"根据 Lean 编译的逻辑，看缺哪些"。

    返回 ``list[dict]``，元素:
        {"kind": str, "detail": str, "suggestion": str}
    kind ∈ {"missing_definition","missing_lemma","missing_module",
            "type_mismatch","other"}
    """
    if not compile_error:
        return []
    gaps: list = []
    seen = set()

    # 1) unknown identifier / declaration / theorem … → 缺失定义或引理
    for m in re.finditer(
        r"unknown (?:identifier|declaration|theorem|constant|axiom)"
        r"\s*[:'\"\s]*([A-Za-z_][A-Za-z0-9_'.]*)",
        compile_error,
    ):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        # 启发式：首字母大写或含 '.' 多半是引理/定理；否则是定义/量
        is_lemma = name[0].isupper() or "." in name
        gaps.append({
            "kind": "missing_lemma" if is_lemma else "missing_definition",
            "detail": name,
            "suggestion": (
                "需要引用/先证明引理「%s」（可能题目未给出该结论，需作为子目标建立）"
                % name) if is_lemma else (
                "需要定义量/函数「%s」（检查题目是否给出该符号及其含义）" % name),
        })

    # 2) unknown module prefix → 缺失 import（如 Mathlib 未加载）
    for m in re.finditer(r"unknown module prefix '([^']+)'", compile_error):
        mod = m.group(1)
        if mod in seen:
            continue
        seen.add(mod)
        gaps.append({
            "kind": "missing_module",
            "detail": mod,
            "suggestion": "形式化缺少模块导入 `import %s`（需先建立该库依赖）" % mod,
        })

    # 3) type mismatch → 逻辑缺口（量/类型不兼容），取首处即可，避免噪声
    m = re.search(r"type mismatch", compile_error)
    if m:
        snippet = _truncate_error_output(compile_error[m.start():m.start() + 400], 300)
        gaps.append({
            "kind": "type_mismatch",
            "detail": snippet,
            "suggestion": "类型不匹配：对题意中量的类型/结构理解可能有误，需核对定义与已知条件的类型。",
        })

    # 4) 兜底：有错误但未命中以上模式 → 给一个通用缺口
    if not gaps:
        gaps.append({
            "kind": "other",
            "detail": _truncate_error_output(compile_error, 300),
            "suggestion": "形式化声明无法编译通过，需重新核对题意理解与符号定义。",
        })
    return gaps


def _parse_analysis_json(raw: str) -> Optional[dict]:
    """从 LLM 返回文本解析错误分析 JSON，失败返回 None。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _answer_embedded(lean_code: str, answer: str) -> bool:
    """校验书生生成的验证代码是否真正锚定了 USER 最终答案。

    防止「书生自己重算、无视 USER 最终答案」的假验证（验证自己算的结果
    而非审核答案）：
    - 纯数字答案：lean_code 必须包含该数字原值（数字边界，防 3 匹配 13）；
    - 含字母 token 的答案（如 x=1、3n+1）：lean_code 必须引用至少一个答案 token
      （否则说明它没在验证这个答案）；
    - 纯中文/符号答案（无字母）：无法代码侧校验，靠提示词 error 路径兜底。
    """
    a = (answer or "").strip()
    if not a:
        return False
    # 纯数字 → 数字锚定（带边界）
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", a):
        pat = r"(?<![0-9])" + re.escape(a) + r"(?![0-9])"
        return re.search(pat, lean_code or "") is not None
    # 含字母 token 的答案 → 代码必须引用至少一个答案 token
    ans_tokens = set(re.findall(r"[A-Za-z_]\w*", a))
    if ans_tokens:
        code_tokens = set(re.findall(r"[A-Za-z_]\w*", lean_code or ""))
        return bool(ans_tokens & code_tokens)
    # 纯中文/符号答案 → 无法校验，放行（靠提示词约束）
    return True
