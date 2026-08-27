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
- 被以下文件依赖: agent/solver.py（证明题通道）、tests/test_lean_bridge.py
- 依赖以下文件: agent/base.py（BugReport / Finding / Budget）
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
_MAX_LEAN_CONVERT_TRIES = 2            # NL→Lean 转化最大尝试次数（编译失败反馈重试）

# Mathlib 源码目录（离线定理检索索引源；不存在时检索自动降级为空）
_MATHLIB_SOURCE_DIR = "E:/mathlib4-last_bump_for_v4.31.0"

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
5. 不要修改题目本身，只对给定推理做形式化。
6. import 路径必须真实存在（当前 Mathlib = last_bump_for_v4.31.0）：
   - 自然数/整除/素数基础：``import Mathlib.Data.Nat.Defs``、``import Mathlib.Data.Nat.Prime.Defs``
   - 整数：``import Mathlib.Data.Int.Defs``
   - 算术策略可用：omega / norm_num / ring / linarith（这些在基础库内置）
   - 不确定定理所在模块时，优先用上面的已验证模块；
     不要使用旧版路径（如 Mathlib.NumberTheory.Prime 已不存在），
     也不要 ``import Mathlib``（全量导入）。"""

LEAN_CONVERT_USER = """## 原题
{problem}

## 待形式化的推理
{reasoning}

请输出对应的 Lean 4 代码。"""

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

def detect_lean_environment(
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
) -> dict:
    """检测 Lean 4 环境是否可用，返回 {"available": bool, "version": str, "error": str}。"""
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=_LEAN_DETECT_TIMEOUT,
        )
        if result.returncode == 0:
            version = (result.stdout.strip().split("\n")[0]
                       if result.stdout else "unknown")
            return {"available": True, "version": version, "error": ""}
        return {"available": False, "version": "",
                "error": (result.stderr or result.stdout).strip()[:200]}
    except FileNotFoundError:
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


def _mathlib_project_usable(proj_dir: str) -> bool:
    """判断目录是否为「可用 Mathlib 工程」：有 lakefile 且带 .lake 依赖缓存。

    兼容两种形态：
    A) mathlib 包在 .lake/packages/mathlib（本地缓存）；
    B) mathlib 是外部 path 依赖（如 E:/mathlib4-...），工程仅需 lakefile + .lake/packages。
    """
    if not proj_dir or not os.path.isdir(proj_dir):
        return False
    has_lakefile = (os.path.exists(os.path.join(proj_dir, "lakefile.toml"))
                    or os.path.exists(os.path.join(proj_dir, "lakefile.lean")))
    if not has_lakefile:
        return False
    # 形态 A：mathlib 包本地缓存非空
    mathlib_pkg = os.path.join(proj_dir, ".lake", "packages", "mathlib")
    if os.path.isdir(mathlib_pkg):
        try:
            entries = os.listdir(mathlib_pkg)
        except OSError:
            entries = []
        if any(not e.startswith(".") for e in entries):
            return True
    # 形态 B：有 .lake/packages（path 依赖声明在 lakefile 内）即视为可用
    if os.path.isdir(os.path.join(proj_dir, ".lake", "packages")):
        return True
    return False


def _compile_lean(
    code: str,
    work_dir: str,
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
    timeout: float = _DEFAULT_LEAN_TIMEOUT,
    mathlib_project_dir: str = "",
) -> dict:
    """调用 Lean 编译器编译一段 Lean 代码（纯编译路径，不依赖 LLM 栈）。

    参数:
        code: Lean 4 源码。
        work_dir: 编译工作目录（写入 .lean 文件并执行 lake 的目录）。
        lean_executable: Lean 可执行文件名（默认 "lake"，配合 lean-toolchain）。
        timeout: 编译超时（秒）。
        mathlib_project_dir: 可选 Mathlib 工程目录。非空且可用时走「工程模式」：
            在带 .lake 缓存（含 mathlib 包）的工程目录编译，使 `import Mathlib`
            可解析；verify.lean 以临时文件名写入、编译后清理，不污染工程。

    返回:
        {"ok": bool, "error": str, "env_missing": bool}
        —— ok=True 表示编译通过（且无未解决的 sorry 关键错误）；
           env_missing=True 表示工具链缺失（区别于真实编译失败）。
    """
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    env_missing = False
    # exe 可能是完整路径（如 E:/.../lake.exe），按文件名判断是否为 lake
    is_lake = os.path.basename(exe).lower() in ("lake", "lake.exe")

    use_mathlib = bool(mathlib_project_dir and _mathlib_project_usable(mathlib_project_dir))
    if use_mathlib:
        # 工程模式：利用 .lake 缓存让 import Mathlib 可解析
        lean_file = os.path.join(mathlib_project_dir, "verify_lean_bridge.lean")
        cwd = mathlib_project_dir
        fname = os.path.basename(lean_file)
        cmd = [exe, "env", "lean", fname] if is_lake else [exe, fname]
    else:
        lean_file = os.path.join(work_dir, "verify.lean")
        cwd = work_dir
        cmd = [exe, "env", "lean", "verify.lean"] if is_lake else [exe, "verify.lean"]

    with open(lean_file, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        err = (result.stderr or "") + (result.stdout or "")
        if result.returncode == 0:
            # 编译通过，但仍需检查是否使用了 sorry 占位（视为未完全验证）
            if re.search(r"\bsorry\b", code):
                return {"ok": False,
                        "error": "编译通过但包含 sorry 占位（存在未形式化步骤）",
                        "env_missing": False}
            return {"ok": True, "error": "", "env_missing": False}
        return {"ok": False, "error": _truncate_error_output(err),
                "env_missing": False}
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": f"Lean 编译超时（>{timeout:.0f}s）",
                "env_missing": False}
    except FileNotFoundError:
        env_missing = True
        return {"ok": False, "error": f"Lean executable not found: {exe}",
                "env_missing": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _truncate_error_output(str(exc)),
                "env_missing": False}
    finally:
        if use_mathlib and os.path.exists(lean_file):
            try:
                os.remove(lean_file)
            except Exception:  # noqa: BLE001 沙箱可能拦截删除，忽略即可
                pass


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

    def _budget_ok(self, n: int = 1) -> bool:
        """检查 LLM 调用预算是否足够（预算为 None 时不限制）。"""
        if self.budget is None:
            return True
        return self.budget.can_spend(n)

    # ------------------------------------------------------------------
    # LLM 调用（走注入的 client，计入 Budget）
    # ------------------------------------------------------------------

    def _llm_call(self, messages: list, temperature: float,
                  max_tokens: int) -> str:
        """用注入的 client 调用一次 LLM（convert/analyze 阶段），计入 Budget。"""
        if not self._budget_ok(1):
            logger.warning("[LeanBridge] 预算耗尽，跳过 LLM 调用")
            return ""
        resp = self.client.chat(
            messages=messages, temperature=temperature, max_tokens=max_tokens)
        text = _normalize_bridge_response(resp)
        if self.budget is not None:
            self.budget.spend(1)
        return text

    # ------------------------------------------------------------------
    # 阶段一：NL → Lean 转化
    # ------------------------------------------------------------------

    def _convert_to_lean(self, problem: str, reasoning: str,
                         prev_error: str = "") -> str:
        """把自然语言推理转化为 Lean 4 代码（依赖注入的 client）。

        - 先检索 Mathlib 可用定理（离线索引，leansearch 轻量版），注入提示词，
          让模型写对 import 与定理名（对应老师要求 #31）；
        - prev_error 非空时作为「编译失败反馈」附带，让 LLM 修正代码。
        """
        user_content = LEAN_CONVERT_USER.format(
            problem=problem, reasoning=reasoning)
        hints = self._retrieve_mathlib_hints(problem + "\n" + reasoning)
        if hints:
            user_content += "\n\n" + hints
        if prev_error:
            user_content += (
                "\n\n你上一版代码编译失败，错误如下：\n%s\n"
                "请修正后重新输出完整 Lean 4 代码。" % prev_error[:1500])
        messages = [
            {"role": "system", "content": LEAN_CONVERT_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=2048)
        return _strip_code_fence(raw)

    def _retrieve_mathlib_hints(self, query: str, k: int = 6) -> str:
        """检索 Mathlib 相关定理并格式化为提示词。任何异常静默降级为空。"""
        try:
            from .mathlib_retriever import MathlibRetriever
            retriever = MathlibRetriever(_MATHLIB_SOURCE_DIR)
            hits = retriever.search(query, k=k)
            return retriever.format_results(hits)
        except Exception:  # noqa: BLE001 检索失败不影响主流程
            return ""

    # ------------------------------------------------------------------
    # 阶段二：编译验证（纯编译路径）
    # ------------------------------------------------------------------

    def _compile(self, code: str, work_dir: str, mathlib_dir: str = "") -> dict:
        """复用纯编译路径 ``_compile_lean`` 对转化出的 Lean 代码做编译验证。

        mathlib_dir 非空且为有效 Mathlib 工程时走「工程模式」：在带 .lake 缓存
        的工程目录编译，`import Mathlib` 可解析（Phase 0 修复：消除单文件
        临时目录解析不到 Mathlib 导致的空转/误降级）。"""
        return _compile_lean(code, work_dir,
                             lean_executable=self._lean_executable,
                             timeout=self._lean_timeout,
                             mathlib_project_dir=mathlib_dir)

    @property
    def _mathlib_dir(self) -> str:
        """探测可用的 Mathlib 工程目录（含非空 .lake/packages/mathlib 缓存）。

        优先取配置 mathlib_dir；否则默认探测项目内置
        `与lean相关的插件/test_mathlib`（要求 mathlib 包源码非空，空壳不算）。"""
        cfg = getattr(self.config, "config", self.config)
        d = (getattr(cfg, "mathlib_dir", "") or "").strip()
        if d and os.path.isdir(d) and _mathlib_project_usable(d):
            return d
        cand = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "与lean相关的插件", "test_mathlib")
        if _mathlib_project_usable(cand):
            return cand
        return ""

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
        raw = self._llm_call(messages, temperature=0.0, max_tokens=1024)
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
                logger.warning("[LeanBridge] Lean 环境不可用，降级为 unknown"
                               "（工具链缺失，非验证失败）")
                return BugReport(verdict="unknown", findings=[])

            # 2) 阶段一：NL → Lean 转化（编译失败时带错误反馈重试，最多 MAX_LEAN_CONVERT_TRIES 轮）
            lean_code = ""
            comp = None
            for attempt in range(_MAX_LEAN_CONVERT_TRIES):
                if time.monotonic() > deadline:
                    return BugReport(verdict="unknown", findings=[])
                prev_error = (comp or {}).get("error", "") if comp else ""
                lean_code = self._convert_to_lean(problem, reasoning,
                                                  prev_error=prev_error)
                if not lean_code:
                    return BugReport(verdict="unknown", findings=[])
                mathlib_dir = self._mathlib_dir
                if mathlib_dir:
                    logger.info("[LeanBridge] Mathlib 工程模式编译: %s (attempt %d)",
                                mathlib_dir, attempt + 1)
                with tempfile.TemporaryDirectory(prefix="lean_bridge_") as work_dir:
                    comp = self._compile(lean_code, work_dir,
                                         mathlib_dir=mathlib_dir)
                if comp.get("ok"):
                    # 编译通过且无 sorry → proof_valid
                    return BugReport(verdict="proof_valid", findings=[])
                if attempt < _MAX_LEAN_CONVERT_TRIES - 1:
                    logger.info("[LeanBridge] 编译失败，带错误反馈重试转化 "
                                "(attempt %d): %s",
                                attempt + 1,
                                (comp.get("error") or "")[:120])
            # 4) 阶段三：错误分析（多次重试仍失败）
            return self._analyze_error(
                problem, reasoning, lean_code,
                comp.get("error", "编译失败（无详细输出）"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] verify 异常（降级 unknown）: %s", exc)
            return BugReport(verdict="unknown", findings=[])


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


def _strip_code_fence(text: str) -> str:
    """去除 LLM 返回的 Markdown 代码围栏（```lean ... ```），只保留代码体。"""
    if not text:
        return ""
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


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
