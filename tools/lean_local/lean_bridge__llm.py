"""Lean LLM 阶段：NL→Lean 转化 / 编译错误分析 / 轻量答案形式化 / 前置形式化（自
`tools/lean_local/lean_bridge.py` 的 `LeanBridge` 逐字搬出）。

宿主类 `_LLMStage` 持有依赖注入的 `client` 与 `budget`；方法体逐字未改，仅宿主
从 `LeanBridge` 换成本类（LeanBridge 保留同名薄委托方法以兼容：测试以实例属性
覆盖 `_analyze_error` / `_convert_answer_to_lean` / `_formalize_to_lean`）。

★ 2026-10-08 拆分（`lean_bridge.py` 上帝类拆分 · 批次2-提交2）：
  · 本模块**零 `agent` 依赖**，不加深 tools→agent 倒置债务；
  · 依赖 postproc / env / pool 三个同包新模块（单向，无环）。
"""
from __future__ import annotations

import contextlib
import logging
import threading
from typing import Optional

from contracts.types import BugReport, Finding

from tools.lean_local.lean_bridge__postproc import (
    _normalize_bridge_response,
    _anti_hack_guard,
    _strip_code_fence,
    hint_for_compile_error,
    _parse_analysis_json,
    _answer_embedded,
    _unwrap_answer,
    _truncate_error_output,
)
from tools.lean_local.lean_bridge__env import _mathlib_import_block
from tools.lean_local.lean_bridge__pool import _mcp_workers

logger = logging.getLogger("MathPilot")


def _mk_report(verdict: str, findings=None, reason: str = "",
               code: str = "", **extra) -> BugReport:
    """构造带诊断属性的 BugReport（**早退留痕的统一出口**）。

    ★ 2026-10-07（fix-obs-tail · 静默跳过埋点）：原为 `verify_answer` 的**内嵌** `_mk`。
    本函数把它**上提为模块级**（纯移动，零行为变更），供 `verify()` /
    `_analyze_error()` 等**其它早退路径**复用同一口径 —— 使它们的「静默跳过」
    也能带上 `verdict_reason`（`lean_gate` 会把该属性原样带进 `diag.lean_gate` 条目，
    见 `lean_gate.py` 的 `for _dk in ("verdict_reason", ...)`）。
    `verify_answer` 内部改为 `_mk = _mk_report` 别名，调用点一行未改。
    """
    r = BugReport(verdict=verdict, findings=findings or [])
    try:
        setattr(r, "verdict_reason", reason)
        setattr(r, "lean_code", code or "")
        for _k, _v in extra.items():
            setattr(r, _k, _v)
    except Exception:  # noqa: BLE001
        pass
    return r


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
   - **先剥外壳取数值原值**：最终答案常带 \\boxed{} / 中文说明 / 分数等外壳
     （如 \\boxed{3000}、\\dfrac{2617}{2618}、"最大值为 3000"），锚定的是
     **数值原值**——先把外壳剥掉取出数值（3000 / 2617 / 2618），
     再写 ``example : <关键计算> = <该数值> := by <tactic>``，
     结论侧逐字包含该数值；禁止把不含答案数值的式子当验证。
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


# 并行通道下 LeanBridge 会被多线程调用：Lean/MCP 编译可并行，但 LLM 调用必须
# 串行（限流口径按单线程标定；client 非线程安全契约）。K=1 时不加锁。
_LLM_SERIAL_LOCK = threading.Lock()



class _LLMStage:
    """Lean LLM 阶段宿主（依赖注入 client / budget）。"""

    def __init__(self, client, budget=None):
        self.client = client
        self.budget = budget

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
        # 2026-09-03 审核：原有 `_budget_ok` 预算闸门已删（比赛无次数上限，
        # 恒放行的死分支反而掩盖了"翻译被跳过 → unknown"的历史根因）。
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
        _guard = (_LLM_SERIAL_LOCK if _mcp_workers() > 1
                  else contextlib.nullcontext())
        with _guard:
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

    def _convert_to_lean(self, problem: str, reasoning: str) -> str:
        """把自然语言推理转化为 Lean 4 代码（依赖注入的 client，走 prefill）。"""
        messages = [
            {"role": "system", "content": LEAN_CONVERT_SYSTEM},
            {"role": "user", "content": LEAN_CONVERT_USER.format(
                problem=problem, reasoning=reasoning)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill=_mathlib_import_block() + "\n")
        return _strip_code_fence(raw)

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
        raw = self._llm_call(messages, temperature=0.0, max_tokens=32768,
                             prefill='{"error_category":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            # ★ 2026-10-07（fix-obs-tail · 静默跳过埋点）：原**静默**返回裸 unknown
            #   （既无 logger 也无 verdict_reason）⇒ "错误分析被跳过"在 diag 里不可见。
            return _mk_report("unknown", reason="analyze_unparsed")

        category = parsed.get("error_category", "uncertain")
        repairable = parsed.get("repairable", "") or ""
        suggestion = parsed.get("suggestion", "") or ""
        critical_desc = parsed.get("critical_desc", "") or ""

        # 2026-09-12：叠加**确定性修法**（由编译器原文特征推断）。
        # 原实现 desc = `critical_desc or suggestion or compile_error[:300]` ——
        # 只要 LLM 给出描述，编译器原文就被丢弃，模型因此拿不到"改哪一行"的信息
        # （与 2.6 实测「2 轮重试 0 成功」同源）。此处把确定性修法**追加在末尾**：
        # 既不破坏 LLM 的业务判断（逻辑错/翻译错的定性），又保证反馈始终可操作。
        _det_hint = hint_for_compile_error(compile_error)
        _base_desc = critical_desc or suggestion or compile_error[:300]
        _desc = (_base_desc + "\n修法提示：" + _det_hint) if _det_hint else _base_desc

        if category in ("logic_error", "both"):
            findings = [Finding(
                location="lean_verify", kind="Critical", severity=5,
                desc=_desc)]
            report = BugReport(findings=findings, verdict="proof_invalid")
        else:
            # 纯翻译错误 / uncertain：视为可修复缺口，但需人工复核 → 降级 unknown
            findings = [Finding(
                location="lean_translate", kind="Gap", severity=1,
                desc=_desc or "Lean 形式化/编译存在问题")] if repairable in ("yes", "partial") else []
            report = BugReport(findings=findings, verdict="unknown")

        # 附加可修复性与修正建议（改造2 新增可选字段，向后兼容）
        report.repairable = repairable
        report.suggestion = suggestion
        return report

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
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
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
        # 数字锚定兜底校验：答案数字（剥 \boxed 壳后）必须出现在 lean_code，
        # 否则视为「没有验证答案」（书生自己重算而非审核 USER 答案），带反馈重试一次。
        if not _answer_embedded(lean_code, answer):
            _anchor = _unwrap_answer(answer) or (answer or "").strip()
            logger.warning(
                "[LeanBridge] 答案 %r 的数值未出现在验证代码（书生自算而非审核答案），重试",
                _anchor[:40])
            retry_hint = ("\n## 上一轮输出无效：你生成的验证代码没有包含最终答案的数值原值 "
                          + _anchor[:60]
                          + "。请重新生成：先把最终答案的数值提取出来（如 \\boxed{3000} "
                            "锚 3000、\\dfrac{2617}{2618} 锚 2617 / 2618），"
                            "再写 example : <关键计算> = <该数值> := by <tactic>，"
                            "结论侧必须逐字包含该数值原值。\n")
            retry_msgs = [
                {"role": "system", "content": LEAN_ANSWER_VERIFY_SYSTEM},
                {"role": "user", "content": LEAN_ANSWER_VERIFY_USER.format(
                    problem=problem, reasoning=reasoning, answer=answer,
                    answer_hint=retry_hint)},
            ]
            raw2 = self._llm_call(retry_msgs, temperature=0.0, max_tokens=65536,
                                  prefill='{"lean_code":')
            parsed2 = _parse_analysis_json(raw2)
            if not parsed2 or parsed2.get("error"):
                return None
            lean_code = _strip_code_fence(str(parsed2.get("lean_code", "") or ""))
            if not lean_code or not _answer_embedded(lean_code, answer):
                return None
        return lean_code

    def _formalize_to_lean(self, problem: str, domain: str = "",
                           feedback: str = "") -> Optional[dict]:
        """把题目转化为 Lean 定理声明（依赖注入 client），返回 {"formal_spec", "lean_code"}。

        feedback 非空时，把上一次编译错误回传给书生，要求重新理解题目并修正形式化。
        转化失败（LLM 空返回 / JSON 解析失败 / 无 lean_code）返回 None。
        """
        try:
            from tools.lean_local.prompts.lean_pre_verify import (
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
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)  # 通用 JSON 提取（功能与 analysis 一致）
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or "")
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}

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
            from tools.lean_local.prompts.lean_pre_verify import (
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
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or parsed.get("outline", ""))
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}
