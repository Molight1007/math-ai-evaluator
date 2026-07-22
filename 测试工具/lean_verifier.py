"""
Lean 4 形式化验证模块。

功能：
1. 将书生 AI 的自然语言推理过程通过 DeepSeek 转化为 Lean 4 代码
2. 调用本地 Lean 编译器进行严格的逻辑验证
3. 编译失败时，由 DeepSeek 分析错误根因，区分转化错误 vs 逻辑错误
4. 对于翻译错误，自动修正 Lean 代码并重试编译（反馈修正循环）
5. 对于逻辑错误，定位断点并生成修正提示词

三阶段 + 反馈修正异步流水线：
  阶段一：转化 — DeepSeek 将推理 → Lean 4 代码
  阶段二：编译 — subprocess 调用 lake env lean
  阶段三：分析 — DeepSeek 分析编译错误根因
  修正循环：翻译错误 → DeepSeek 修正代码 → 重新编译（最多 2 次）

Lean 不可用时自动降级为纯 LLM 逻辑审查模式。
"""
import asyncio
import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

from config import get_config, detect_lean_environment
from llm_client import LLMClient, extract_json_from_text
from models import ANDORDAG, InferenceResult, LeanVerificationResult

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 转化阶段：DeepSeek 模型参数
_CONVERSION_TEMPERATURE = 0.1          # 低温度以获得稳定的转化输出
_CONVERSION_MAX_TOKENS = 4096          # 足以容纳完整的 Lean 4 代码

# 分析阶段：DeepSeek 模型参数
_ANALYSIS_TEMPERATURE = 0.1            # 低温度以获得一致的分析结果
_ANALYSIS_MAX_TOKENS = 4096            # 足以容纳详细的分析报告

# 降级审查阶段：DeepSeek 模型参数
_REVIEW_TEMPERATURE = 0.1              # 低温度以保证审查一致性
_REVIEW_MAX_TOKENS = 4096              # 足以容纳审查结果

# 编译错误截断长度：避免分析阶段 token 过多
_MAX_COMPILE_OUTPUT_CHARS = 5000

# 分析阶段截断 Lean 代码长度
_MAX_LEAN_CODE_ANALYSIS_CHARS = 3000

# 批量验证默认并发数
_DEFAULT_BATCH_CONCURRENCY = 3

# ==================== Prompt 模板 ====================

# 阶段一：将自然语言推理转化为 Lean 4 代码
CONVERSION_SYSTEM_PROMPT = (
    "You are a Lean 4 formalization expert. Your task is to convert "
    "a mathematical reasoning chain into Lean 4 code that can be verified "
    "by the Lean compiler.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The AI model's step-by-step reasoning\n"
    "3. The model's final answer\n\n"
    "Your job: Convert the reasoning into a Lean 4 theorem and proof. "
    "The theorem should state that the model's conclusion follows from "
    "the problem's conditions.\n\n"
    "CRITICAL RULES:\n"
    "- You CAN and SHOULD use `import Mathlib` when needed. Mathlib4 provides "
    "a vast library of theorems across analysis, algebra, topology, number theory, etc.\n"
    "- Common Mathlib imports (use as appropriate):\n"
    "  * `import Mathlib` — full library (preferred when in doubt)\n"
    "  * `import Mathlib.Data.Real.Basic` — real number basics\n"
    "  * `import Mathlib.Analysis.Calculus.MeanInequalities` — inequalities\n"
    "  * `import Mathlib.Tactic` — linarith, nlinarith, positivity, ring, field_simp\n"
    "  * `import Mathlib.Algebra.*` — algebraic structures\n"
    "  * `import Mathlib.Topology.*` — topology\n"
    "  * `import Mathlib.NumberTheory.*` — number theory\n"
    "- All standard tactics are available (linarith, nlinarith, continuity, "
    "differentiability, measurability, etc.) when Mathlib is imported.\n"
    "- Use `Nat`, `Int`, `Rat`, `Real` types as appropriate.\n"
    "- Write a complete Lean 4 file that SHOULD compile.\n"
    "- Use `theorem` (not `example`) with a meaningful name.\n"
    "- Include all necessary hypotheses in the theorem statement.\n"
    "- If a proof is too complex, you may use `sorry` for some steps, "
    "but the THEOREM STATEMENT itself should still be correct and type-check.\n"
    "- Even with `sorry`, the file should pass type-checking (no syntax/type errors).\n"
    "- PREFER using Mathlib theorems (e.g., `Real.sqrt_mul_self`) over "
    "reinventing the wheel with basic tactics.\n\n"
    "Output a JSON object with these fields:\n"
    '- "lean_code": the COMPLETE Lean 4 code (including proper Mathlib imports, theorem + proof),\n'
    '- "is_formalizable": true/false — whether this problem CAN be formalized,\n'
    '- "formalized_claim": description in Chinese of what the Lean code proves,\n'
    '- "expected_result": "pass" or "fail" — do you think this Lean code will compile?\n'
    '- "key_steps": array of key reasoning steps that were formalized.\n'
    "Output ONLY the JSON object, no other text."
)

# 阶段三：分析编译错误根因
ANALYSIS_SYSTEM_PROMPT = (
    "You are a Lean 4 debugging expert. Your task is to analyze a Lean "
    "compilation error and determine whether it reveals a logical flaw "
    "in the original mathematical reasoning, or is merely a translation error.\n\n"
    "You will receive:\n"
    "1. The original math problem\n"
    "2. The AI model's original reasoning (the reasoning that was formalized)\n"
    "3. The auto-generated Lean 4 code\n"
    "4. The Lean compiler error output\n\n"
    "Your analysis must determine:\n"
    "- Is the Lean code correctly representing the original reasoning?\n"
    "- Does the compilation error indicate a logical flaw in the reasoning?\n"
    "- Or is it just a mistake in writing the Lean code?\n\n"
    "CRITICAL: Even if the Lean code is incomplete or uses 'sorry', "
    "you MUST still analyze what the code ATTEMPTS to prove and identify "
    "any logical issues in the underlying reasoning. "
    "A Lean error is NOT just a syntax issue — it often reveals that "
    "the reasoning itself cannot be formalized, which IS a logical flaw.\n\n"
    "Output a JSON object with these fields:\n"
    '- "error_category": one of "translation_error" / "logic_error" / "both" / "uncertain",\n'
    '- "confidence": 0.0-1.0,\n'
    '- "human_readable_error": explain the error in plain Chinese (面向中文用户的简洁说明),\n'
    '- "root_cause": root cause analysis in Chinese (3-5 sentences, 必须明确是逻辑问题还是转化问题),\n'
    '- "logic_flaw_location": if logic_error, which step in the original reasoning is wrong (引用原文),\n'
    '- "logic_flaw_why": why that step is mathematically incorrect (用中文详细说明),\n'
    '- "correct_approach": the correct mathematical approach (用中文说明正确解法),\n'
    '- "translation_issue": if translation_error, what went wrong in the Lean code,\n'
    '- "fix_prompt_for_ai": a concise prompt (in Chinese) that can be sent to '
    "the original AI model to help it correct its reasoning,\n"
    '- "suggested_fix": 推荐的修改方法 (in Chinese, 告诉用户应该如何修正推理过程或代码).\n'
    "Output ONLY the JSON object."
)

# 反馈修正循环 — 根据错误分析结果修正 Lean 代码
REVISER_SYSTEM_PROMPT = (
    "You are a Lean 4 code fixer. Your task is to correct Lean 4 code "
    "based on compilation error feedback and error analysis.\n\n"
    "You will receive:\n"
    "1. The original math problem\n"
    "2. The original Lean 4 code that failed to compile\n"
    "3. The Lean compiler error output\n"
    "4. A detailed error analysis (including the root cause)\n\n"
    "Your job: Fix the Lean 4 code so that it compiles correctly.\n"
    "Focus on fixing syntax errors, type mismatches, missing imports, "
    "incorrect theorem statements, and any other compilation issues.\n\n"
    "CRITICAL RULES:\n"
    "- Preserve the original theorem's intent — don't change the math, "
    "only fix the Lean formalization\n"
    "- Use `sorry` for sub-proofs you cannot immediately fix\n"
    "- If Mathlib is used, ensure correct imports\n"
    "- Fix ALL reported errors, not just the first one\n"
    "- The output must be a syntactically valid, compilable Lean 4 file\n"
    "- If the error is fundamentally unfixable (the reasoning itself is wrong), "
    "add a comment explaining why and use `sorry` for the broken parts\n\n"
    "Output a JSON object with these fields:\n"
    '- "lean_code": the corrected COMPLETE Lean 4 code,\n'
    '- "changes_summary": brief description of what was changed and why,\n'
    '- "fixed_all_errors": true/false — whether you believe all compilation errors are fixed,\n'
    '- "remaining_issues": if any issues remain, describe them briefly.\n'
    "Output ONLY the JSON object."
)

# 分解阶段：DeepSeek 模型参数
_BLUEPRINT_TEMPERATURE = 0.1           # 低温度以获得一致的分解输出
_BLUEPRINT_MAX_TOKENS = 4096           # 足以容纳完整的 AND-OR DAG JSON

# 修正阶段：DeepSeek 模型参数
_REVISION_TEMPERATURE = 0.1            # 低温度以获得一致的修正输出
_REVISION_MAX_TOKENS = 4096            # 足以容纳完整的 Lean 4 代码
_MAX_REVISION_RETRIES = 2              # 反馈修正循环最大重试次数

# 阶段四（可选）：蓝图分解 — 将推理过程分解为 AND-OR DAG 子引理树
BLUEPRINT_SYSTEM_PROMPT = (
    "You are a mathematical proof decomposition expert. Your task is to "
    "decompose a mathematical reasoning chain into an AND-OR proof tree "
    "(blueprint DAG).\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The AI model's step-by-step reasoning\n"
    "3. The Lean compilation error (if available)\n\n"
    "The AND-OR tree structure:\n"
    "- **OR node**: A goal that needs to be proven. Can be decomposed into "
    "multiple alternative approaches (AND children).\n"
    "- **AND node**: A decomposition approach. ALL its children must be "
    "proven for this approach to succeed.\n"
    "- **LEAF node**: A sub-lemma that can be directly attempted (may be "
    "verified or marked as sorry/unknown).\n\n"
    "CRITICAL RULES:\n"
    "- The root node MUST be an OR node representing the overall theorem.\n"
    "- Each OR node should have at least one AND child (decomposition).\n"
    "- Each AND node should have 1-5 LEAF children (sub-lemmas).\n"
    "- Node IDs must be unique strings (e.g. 'root', 'and1', 'leaf1a').\n"
    "- node_type: exactly one of 'OR', 'AND', 'LEAF'.\n"
    "- status for LEAF: 'verified' if the reasoning covered it, 'sorry' if "
    "the reasoning skipped it, 'open' otherwise.\n"
    "- label: a short Chinese label (e.g. '证明目标', '分解方案1', '子引理1').\n"
    "- statement: the mathematical statement in Chinese or mixed notation.\n"
    "- children: array of child node IDs (empty for LEAF nodes).\n"
    "- detail: optional brief explanation of this node's role.\n\n"
    "Output a JSON object with this structure:\n"
    '{"dag": {"root_id": "...", "nodes": {"id1": {"node_id": "id1", '
    '"node_type": "OR", "label": "...", "statement": "...", '
    '"status": "...", "children": [...], "detail": "..."}, ...}}}\n'
    "Output ONLY the JSON object, no other text."
)

# 纯 LLM 逻辑审查 prompt（Lean 不可用时降级方案）
LOGIC_REVIEW_SYSTEM_PROMPT = (
    "You are a rigorous mathematical logic reviewer. Your task is to "
    "carefully examine an AI model's mathematical reasoning and identify "
    "any logical flaws, hidden assumptions, or reasoning gaps.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The AI model's step-by-step reasoning\n"
    "3. The model's final answer\n\n"
    "Output a JSON object with these fields:\n"
    '- "has_logic_error": true/false,\n'
    '- "confidence": 0.0-1.0,\n'
    '- "logic_flaw_location": which step has the logical problem,\n'
    '- "logic_flaw_why": why it is wrong (用中文说明),\n'
    '- "correct_approach": the correct approach (用中文说明),\n'
    '- "fix_prompt_for_ai": a prompt to help the AI correct its reasoning (中文),\n'
    '- "suggested_fix": 推荐的修改方法 (中文).\n'
    "Output ONLY the JSON object."
)


# ==================== 工具函数 ====================

def _truncate_error_output(output: str, max_chars: int = _MAX_COMPILE_OUTPUT_CHARS) -> str:
    """
    截断编译错误输出，避免分析阶段 token 过多。

    保留策略：开头一半 + 结尾一半，中间插入截断标记。
    这样既能保留错误开头（通常含最关键的错误信息），又保留尾部上下文。

    参数:
        output: 原始编译输出文本
        max_chars: 最大保留字符数（默认 5000）

    返回:
        截断后的文本
    """
    if len(output) <= max_chars:
        return output
    half = max_chars // 2
    return output[:half] + "\n... (truncated) ...\n" + output[-half:]


def _build_lean_code_safe(lean_code: str) -> str:
    """
    清理 Lean 代码，使其适合在纯 Lean 4 核心环境下编译。

    移除所有 import Mathlib（Mathlib 不可用），只使用 Lean 4 核心库。

    参数:
        lean_code: 原始 Lean 4 代码

    返回:
        清理后的 Lean 4 代码
    """
    # 移除 import Mathlib（Mathlib 不可用）
    for pattern in ["import Mathlib\n", "import Mathlib", "open Real\n", "open Real"]:
        lean_code = lean_code.replace(pattern, "")
    # 移除空行残留
    while "\n\n\n" in lean_code:
        lean_code = lean_code.replace("\n\n\n", "\n\n")
    lean_code = lean_code.strip()
    return lean_code


def _build_conversion_user_prompt(inference: InferenceResult) -> str:
    """
    构建转化阶段的 user prompt。

    将推理结果的所有字段（问题、答案、推理过程、步骤）组织成适合
    DeepSeek 理解的格式。

    参数:
        inference: 需要转化的推理结果

    返回:
        结构化的 user prompt 字符串
    """
    steps_text = (
        chr(10).join(f"- {s}" for s in inference.steps)
        if inference.steps else "N/A"
    )
    return f"""## Math Problem
{inference.question}

## Model's Answer
{inference.answer}

## Model's Reasoning
{inference.reasoning}

## Model's Steps
{steps_text}

Please convert this reasoning to Lean 4 code."""


def _build_analysis_user_prompt(
    inference: InferenceResult,
    lean_code: str,
    compile_output: str,
) -> str:
    """
    构建错误分析阶段的 user prompt。

    将原始题目、推理过程、生成的 Lean 代码和编译错误输出组织成
    适合 DeepSeek 进行根因分析的格式。Lean 代码和编译输出会被截断
    以控制 token 消耗。

    参数:
        inference: 原始推理结果
        lean_code: 自动生成的 Lean 4 代码
        compile_output: Lean 编译器的错误输出

    返回:
        结构化的 user prompt 字符串
    """
    truncated_output = _truncate_error_output(compile_output)
    truncated_code = lean_code[:_MAX_LEAN_CODE_ANALYSIS_CHARS]

    return f"""## Original Math Problem
{inference.question}

## Original AI Reasoning (the reasoning that was formalized)
{inference.reasoning}

## Auto-generated Lean 4 Code
```lean
{truncated_code}
```

## Lean Compiler Error Output
{truncated_output}

Please analyze whether this reveals a logic error in the original reasoning."""


def _build_review_user_prompt(inference: InferenceResult) -> str:
    """
    构建降级逻辑审查阶段的 user prompt。

    当 Lean 编译器不可用时，使用此 prompt 进行纯 LLM 逻辑审查。

    参数:
        inference: 需要审查的推理结果

    返回:
        结构化的 user prompt 字符串
    """
    steps_text = (
        chr(10).join(f"- {s}" for s in inference.steps)
        if inference.steps else "N/A"
    )
    return f"""## Math Problem
{inference.question}

## Model's Answer
{inference.answer}

## Model's Reasoning
{inference.reasoning}

## Model's Steps
{steps_text}"""


def _build_blueprint_user_prompt(
    inference: InferenceResult,
    lean_code: str = "",
    compile_output: str = "",
) -> str:
    """
    构建蓝图分解阶段的 user prompt。

    将原始题目、推理过程和编译错误（如有）组织成适合 DeepSeek
    进行 AND-OR DAG 分解的格式。

    参数:
        inference: 原始推理结果
        lean_code: 编译失败的 Lean 4 代码（可选，截断至 2000 字符）
        compile_output: 编译错误输出（可选，截断至 2000 字符）

    返回:
        结构化的 user prompt 字符串
    """
    parts = [f"## Math Problem\n{inference.question}"]
    parts.append(f"\n## Model's Reasoning\n{inference.reasoning}")

    if lean_code:
        truncated_code = lean_code[:2000]
        parts.append(
            f"\n## Lean 4 Code (that failed to compile)\n```lean\n"
            f"{truncated_code}\n```"
        )

    if compile_output:
        truncated_output = compile_output[:2000]
        parts.append(
            f"\n## Compilation Error\n{truncated_output}"
        )

    parts.append(
        "\nPlease decompose the reasoning into an AND-OR proof tree."
    )
    return "\n".join(parts)


# ==================== 阶段一：转化 ====================

async def _convert_to_lean(
    inference: InferenceResult,
    client: LLMClient,
) -> dict:
    """
    阶段一：调用 DeepSeek 将推理转化为 Lean 4 代码。

    将推理结果中的自然语言推理过程发送给 DeepSeek，要求输出包含
    lean_code、is_formalizable、formalized_claim 等字段的 JSON。

    参数:
        inference: 需要转化的推理结果
        client: DeepSeek LLM 客户端实例

    返回:
        解析后的 dict，包含 lean_code, is_formalizable, formalized_claim,
        expected_result, key_steps, _tokens, _latency 等字段。
        如果 LLM 调用或 JSON 解析失败，返回带默认值的 dict。
    """
    messages = [
        {"role": "system", "content": CONVERSION_SYSTEM_PROMPT},
        {"role": "user", "content": _build_conversion_user_prompt(inference)},
    ]

    try:
        response = await client.chat(
            messages=messages,
            temperature=_CONVERSION_TEMPERATURE,
            max_tokens=_CONVERSION_MAX_TOKENS,
        )
        parsed = extract_json_from_text(response["content"])
        if parsed and isinstance(parsed, dict):
            return {
                **parsed,
                "_tokens": response.get("tokens_used", 0),
                "_latency": 0,  # 由调用方统一计算耗时
            }
        # JSON 解析失败时，回退：将原始内容作为 lean_code
        return _fallback_conversion_result(response)
    except Exception as e:
        logger.error(f"Lean conversion failed: {e}")
        return _empty_conversion_result(str(e))


def _fallback_conversion_result(response: dict) -> dict:
    """
    JSON 解析失败时的回退处理。
    将 LLM 的原始响应内容作为 lean_code 保存，标记为不可形式化。

    参数:
        response: LLM 客户端返回的响应 dict

    返回:
        带默认值的转化结果 dict
    """
    return {
        "lean_code": response["content"][:2000],
        "is_formalizable": False,
        "formalized_claim": "",
        "expected_result": "fail",
        "key_steps": [],
        "_tokens": response.get("tokens_used", 0),
        "_raw": response["content"],
    }


def _empty_conversion_result(error_msg: str = "") -> dict:
    """
    返回一个空的转化结果，用于 LLM 调用完全失败时。

    参数:
        error_msg: 错误描述信息

    返回:
        全默认值的转化结果 dict
    """
    return {
        "lean_code": "",
        "is_formalizable": False,
        "formalized_claim": "",
        "expected_result": "fail",
        "key_steps": [],
        "_tokens": 0,
        "_error": error_msg,
    }


# ==================== 阶段二：编译 ====================

# 轻量级 Lean 4 验证项目根目录（不依赖 Mathlib）
_LEAN_VERIFY_PROJECT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "lean_verify")
)


async def _compile_lean(lean_code: str, config) -> dict:
    """
    阶段二：直接使用 lean 编译器编译 Lean 4 代码（不依赖 Mathlib）。

    策略：
    1. 将 Lean 代码写入临时文件
    2. 直接调用 lean 编译器编译该文件
    3. 编译完成后清理临时文件

    参数:
        lean_code: 需要编译的 Lean 4 代码
        config: EvalConfig 配置对象（含 lean_compiler 和 lean_timeout）

    返回:
        {"passed": bool, "output": str, "timeout": bool, "latency": float}
    """
    if not lean_code.strip():
        return {
            "passed": False,
            "output": "(empty Lean code)",
            "timeout": False,
            "latency": 0.0,
        }

    lean_code = _build_lean_code_safe(lean_code)

    start_time = time.time()
    tmp_file = None

    try:
        # 使用临时文件，写入 Lean 代码
        fd, tmp_file = tempfile.mkstemp(suffix=".lean", prefix="verify_", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(lean_code)

        # 直接使用 lean 编译器编译（而不是 lake build）
        lean_compiler = getattr(config, "lean_compiler", None) or "lean"
        proc = await asyncio.create_subprocess_exec(
            lean_compiler, tmp_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=config.lean_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            latency = round(time.time() - start_time, 2)
            return {
                "passed": False,
                "output": "(compilation timed out)",
                "timeout": True,
                "latency": latency,
            }

        latency = round(time.time() - start_time, 2)
        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            output += stderr.decode("utf-8", errors="replace")

        return {
            "passed": proc.returncode == 0,
            "output": output.strip() if output.strip() else "(compilation successful, no output)",
            "timeout": False,
            "latency": latency,
        }
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Lean compilation error: {e}")
        return {"passed": False, "output": str(e), "timeout": False, "latency": latency}
    finally:
        # 清理临时文件
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except OSError:
                logger.debug(f"Failed to clean up: {tmp_file}")


# ==================== sorry 检测 ====================

def _detect_sorry(lean_code: str) -> dict:
    """
    扫描 Lean 代码中的 `sorry` 关键字，统计数量和判断证明是否完整。

    参数:
        lean_code: Lean 4 代码文本

    返回:
        dict: {"count": int, "has_sorry": bool}
    """
    import re
    matches = re.findall(r'\bsorry\b', lean_code)
    count = len(matches)
    return {"count": count, "has_sorry": count > 0}


# ==================== 阶段三：分析 ====================

async def _analyze_error(
    inference: InferenceResult,
    lean_code: str,
    compile_output: str,
    client: LLMClient,
) -> dict:
    """
    阶段三：编译失败时，调用 DeepSeek 分析错误根因。

    将原始题目、推理过程、生成的 Lean 代码和编译器错误输出发送给
    DeepSeek，要求区分是「转化错误」（Lean 代码写错了）还是
    「逻辑错误」（原始推理本身有逻辑问题）。

    参数:
        inference: 原始推理结果
        lean_code: 编译失败的 Lean 4 代码
        compile_output: Lean 编译器的错误输出
        client: DeepSeek LLM 客户端实例

    返回:
        解析后的分析结果 dict，包含 error_category, confidence,
        logic_flaw_location, logic_flaw_why, fix_prompt_for_ai 等字段。
    """
    messages = [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": _build_analysis_user_prompt(
            inference, lean_code, compile_output
        )},
    ]

    try:
        response = await client.chat(
            messages=messages,
            temperature=_ANALYSIS_TEMPERATURE,
            max_tokens=_ANALYSIS_MAX_TOKENS,
        )
        parsed = extract_json_from_text(response["content"])
        if parsed and isinstance(parsed, dict):
            return {**parsed, "_tokens": response.get("tokens_used", 0)}
        return _fallback_analysis_result(response)
    except Exception as e:
        logger.error(f"Lean error analysis failed: {e}")
        return _empty_analysis_result(str(e))


def _fallback_analysis_result(response: dict) -> dict:
    """
    JSON 解析失败时的分析回退结果。
    将 LLM 原始响应内容作为 human_readable_error 保存。

    参数:
        response: LLM 客户端返回的响应 dict

    返回:
        带默认值的分析结果 dict
    """
    return {
        "error_category": "uncertain",
        "confidence": 0.3,
        "human_readable_error": (
            f"Failed to parse analysis: {response['content'][:500]}"
        ),
        "root_cause": "Analysis parsing failed",
        "logic_flaw_location": "",
        "logic_flaw_why": "",
        "correct_approach": "",
        "translation_issue": "",
        "fix_prompt_for_ai": "",
        "suggested_fix": "",
        "_tokens": response.get("tokens_used", 0),
    }


def _empty_analysis_result(error_msg: str = "") -> dict:
    """
    返回空的分析结果，用于 LLM 调用完全失败时。

    参数:
        error_msg: 错误描述信息

    返回:
        全默认值的分析结果 dict
    """
    return {
        "error_category": "uncertain",
        "confidence": 0.0,
        "human_readable_error": f"Analysis API call failed: {error_msg}",
        "root_cause": "",
        "logic_flaw_location": "",
        "logic_flaw_why": "",
        "correct_approach": "",
        "translation_issue": "",
        "fix_prompt_for_ai": "",
        "suggested_fix": "",
        "_tokens": 0,
    }


# ==================== 反馈修正循环 ====================

async def _revise_lean_code(
    inference: InferenceResult,
    lean_code: str,
    compile_output: str,
    analysis: dict,
    client: LLMClient,
) -> Optional[dict]:
    """
    反馈修正循环：根据错误分析结果，调用 DeepSeek 修正 Lean 代码。

    仅在 error_category 为 "translation_error" 或 "both" 时调用，
    因为纯逻辑错误无法通过修改 Lean 代码来解决。

    参数:
        inference: 原始推理结果
        lean_code: 编译失败的 Lean 4 代码
        compile_output: Lean 编译器的错误输出
        analysis: 阶段三的错误分析结果 dict
        client: DeepSeek LLM 客户端实例

    返回:
        解析后的修正结果 dict，包含修正后的 lean_code、changes_summary 等，
        失败时返回 None
    """
    revision_user_prompt = (
        f"## 原始数学问题\n{inference.problem}\n\n"
        f"## 原始 Lean 代码（编译失败）\n```lean\n{lean_code}\n```\n\n"
        f"## 编译器错误输出\n```\n{compile_output[:2000]}\n```\n\n"
        f"## 错误分析\n"
        f"- 错误类别: {analysis.get('error_category', 'unknown')}\n"
        f"- 根因: {analysis.get('root_cause', '无')}\n"
        f"- 转化问题: {analysis.get('translation_issue', '无')}\n"
        f"- 建议修改: {analysis.get('suggested_fix', '无')}\n\n"
        f"请修正上述 Lean 代码，修复所有编译错误。"
    )

    messages = [
        {"role": "system", "content": REVISER_SYSTEM_PROMPT},
        {"role": "user", "content": revision_user_prompt},
    ]

    try:
        response = await client.chat(
            messages=messages,
            temperature=_REVISION_TEMPERATURE,
            max_tokens=_REVISION_MAX_TOKENS,
        )
        parsed = extract_json_from_text(response["content"])
        if parsed and isinstance(parsed, dict):
            result = {**parsed, "_tokens": response.get("tokens_used", 0)}
            logger.info(
                f"[Lean] [{inference.problem_id}] Code revised. "
                f"Changes: {parsed.get('changes_summary', 'N/A')[:100]}"
            )
            return result
        else:
            logger.warning(
                f"[Lean] [{inference.problem_id}] Failed to parse reviser response"
            )
            return None
    except Exception as e:
        logger.error(f"[Lean] [{inference.problem_id}] Revision failed: {e}")
        return None


# ==================== 阶段四：蓝图分解 ====================

async def _decompose_blueprint(
    inference: InferenceResult,
    lean_code: str,
    compile_output: str,
    client: LLMClient,
) -> Optional[ANDORDAG]:
    """
    阶段四（可选）：编译失败且存在逻辑错误时，将推理分解为 AND-OR DAG。

    调用 DeepSeek 将原始推理过程分解为 AND-OR 证明树（蓝图），
    用于可视化展示证明的逻辑结构和未完成的子目标。

    仅在编译失败且 error_category 为 logic_error 或 both 时触发。

    参数:
        inference: 原始推理结果
        lean_code: 编译失败的 Lean 4 代码
        compile_output: Lean 编译器的错误输出
        client: DeepSeek LLM 客户端实例

    返回:
        解析后的 ANDORDAG 对象。解析失败或 LLM 调用失败时返回 None。
    """
    messages = [
        {"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_blueprint_user_prompt(
            inference, lean_code, compile_output
        )},
    ]

    try:
        response = await client.chat(
            messages=messages,
            temperature=_BLUEPRINT_TEMPERATURE,
            max_tokens=_BLUEPRINT_MAX_TOKENS,
        )
        parsed = extract_json_from_text(response["content"])
        if parsed and isinstance(parsed, dict) and "dag" in parsed:
            dag = ANDORDAG.from_dict(parsed["dag"])
            if not dag.is_empty():
                return dag
        # 尝试直接从响应内容解析 DAG（兜底策略）
        if parsed and isinstance(parsed, dict):
            dag = ANDORDAG.from_dict(parsed)
            if not dag.is_empty():
                return dag
        return None
    except Exception as e:
        logger.error(f"Blueprint decomposition failed: {e}")
        return None


# ==================== 降级方案：纯 LLM 逻辑审查 ====================

async def _logic_review_only(
    inference: InferenceResult,
    client: LLMClient,
) -> dict:
    """
    Lean 不可用时的降级方案：纯 LLM 逻辑审查。

    直接将推理过程发送给 DeepSeek，要求检查其中是否存在逻辑错误。
    不涉及任何 Lean 代码或编译操作。

    参数:
        inference: 需要审查的推理结果
        client: DeepSeek LLM 客户端实例

    返回:
        解析后的审查结果 dict，包含 has_logic_error, confidence,
        logic_flaw_location, fix_prompt_for_ai 等字段。
    """
    messages = [
        {"role": "system", "content": LOGIC_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": _build_review_user_prompt(inference)},
    ]

    try:
        response = await client.chat(
            messages=messages,
            temperature=_REVIEW_TEMPERATURE,
            max_tokens=_REVIEW_MAX_TOKENS,
        )
        parsed = extract_json_from_text(response["content"])
        if parsed and isinstance(parsed, dict):
            return {**parsed, "_tokens": response.get("tokens_used", 0)}
        return _fallback_review_result(response)
    except Exception as e:
        logger.error(f"Logic review failed: {e}")
        return _empty_review_result()


def _fallback_review_result(response: dict) -> dict:
    """
    JSON 解析失败时的审查回退结果。

    参数:
        response: LLM 客户端返回的响应 dict

    返回:
        带默认值的审查结果 dict
    """
    return {
        "has_logic_error": False,
        "confidence": 0.0,
        "logic_flaw_location": "",
        "logic_flaw_why": "",
        "correct_approach": "",
        "fix_prompt_for_ai": "",
        "suggested_fix": "",
        "_tokens": response.get("tokens_used", 0),
    }


def _empty_review_result() -> dict:
    """
    返回空的审查结果，用于 LLM 调用完全失败时。

    返回:
        全默认值的审查结果 dict
    """
    return {
        "has_logic_error": False,
        "confidence": 0.0,
        "logic_flaw_location": "",
        "logic_flaw_why": "",
        "correct_approach": "",
        "fix_prompt_for_ai": "",
        "suggested_fix": "",
        "_tokens": 0,
    }


# ==================== 缓存：Lean 环境检测 ====================

_lean_env_cache: Optional[dict] = None


def _get_lean_env(config) -> dict:
    """
    获取 Lean 环境检测结果（带缓存）。

    首次调用时执行 detect_lean_environment，后续调用直接返回缓存结果。
    避免每次验证都执行子进程检测。

    参数:
        config: EvalConfig 配置对象

    返回:
        {"available": bool, "version": str, "error": str}
    """
    global _lean_env_cache
    if _lean_env_cache is None:
        _lean_env_cache = detect_lean_environment(config.lean_compiler)
        if _lean_env_cache["available"]:
            logger.info(f"Lean 4 detected: {_lean_env_cache['version']}")
        else:
            logger.warning(
                f"Lean 4 not available: {_lean_env_cache['error']}"
            )
    return _lean_env_cache


def reset_lean_env_cache() -> None:
    """
    重置 Lean 环境缓存。

    用于配置变更后（如修改了 LEAN_EXECUTABLE 路径）强制重新检测。
    """
    global _lean_env_cache
    _lean_env_cache = None


# ==================== 结果填充辅助函数 ====================

def _fill_conversion_fields(
    result: LeanVerificationResult,
    conv_result: dict,
) -> None:
    """
    将转化阶段的输出填充到 LeanVerificationResult 对象。

    参数:
        result: 待填充的 LeanVerificationResult 实例（会被原地修改）
        conv_result: _convert_to_lean 返回的 dict
    """
    result.lean_code = conv_result.get("lean_code", "")
    result.formalized_claim = conv_result.get("formalized_claim", "")
    result.conversion_tokens = conv_result.get("_tokens", 0)
    if conv_result.get("_error"):
        result.conversion_error = conv_result["_error"]


def _fill_compile_fields(
    result: LeanVerificationResult,
    compile_result: dict,
) -> None:
    """
    将编译阶段的输出填充到 LeanVerificationResult 对象。

    参数:
        result: 待填充的 LeanVerificationResult 实例（会被原地修改）
        compile_result: _compile_lean 返回的 dict
    """
    result.compile_passed = compile_result["passed"]
    result.compile_output = compile_result["output"]
    result.compile_latency = compile_result["latency"]
    result.compile_timeout = compile_result["timeout"]


def _fill_analysis_fields(
    result: LeanVerificationResult,
    analysis: dict,
) -> None:
    """
    将分析阶段的输出填充到 LeanVerificationResult 对象。

    参数:
        result: 待填充的 LeanVerificationResult 实例（会被原地修改）
        analysis: _analyze_error 返回的 dict
    """
    result.analysis_performed = True
    result.analysis_tokens = analysis.get("_tokens", 0)
    result.error_category = analysis.get("error_category", "uncertain")
    result.analysis_confidence = analysis.get("confidence", 0.0)
    result.human_readable_error = analysis.get("human_readable_error", "")
    result.root_cause = analysis.get("root_cause", "")
    result.logic_flaw_location = analysis.get("logic_flaw_location", "")
    result.logic_flaw_why = analysis.get("logic_flaw_why", "")
    result.correct_approach = analysis.get("correct_approach", "")
    result.translation_issue = analysis.get("translation_issue", "")
    result.fix_prompt_for_ai = analysis.get("fix_prompt_for_ai", "")
    result.suggested_fix = analysis.get("suggested_fix", "")


def _fill_review_fields(
    result: LeanVerificationResult,
    review: dict,
) -> None:
    """
    将降级审查阶段的输出填充到 LeanVerificationResult 对象。

    参数:
        result: 待填充的 LeanVerificationResult 实例（会被原地修改）
        review: _logic_review_only 返回的 dict
    """
    result.conversion_tokens = review.get("_tokens", 0)
    result.compile_passed = None  # 降级模式不编译
    result.compile_output = "(Lean not available — LLM-only review)"

    if review.get("has_logic_error"):
        result.analysis_performed = True
        result.error_category = "logic_error"
        result.analysis_confidence = review.get("confidence", 0.5)
        result.logic_flaw_location = review.get("logic_flaw_location", "")
        result.logic_flaw_why = review.get("logic_flaw_why", "")
        result.correct_approach = review.get("correct_approach", "")
        result.fix_prompt_for_ai = review.get("fix_prompt_for_ai", "")
        result.suggested_fix = review.get("suggested_fix", "")
        result.human_readable_error = (
            f"LLM logic review found a potential logic error at: "
            f"{review.get('logic_flaw_location', 'unknown step')}"
        )


# ==================== 主入口函数 ====================

async def _run_full_lean_pipeline(
    inference: InferenceResult,
    deepseek_client: LLMClient,
    config,
    result: LeanVerificationResult,
) -> LeanVerificationResult:
    """
    执行完整的 Lean 三阶段验证流水线（Lean 可用时）。

    流程：转化 → 编译 →（若编译失败）分析。

    参数:
        inference: 需要验证的推理结果
        deepseek_client: DeepSeek LLM 客户端
        config: EvalConfig 配置
        result: 预初始化的 LeanVerificationResult 对象（会被原地修改）

    返回:
        填充完成的 LeanVerificationResult
    """
    # 阶段一：转化
    logger.info(
        f"[Lean] Converting reasoning for [{inference.problem_id}]..."
    )
    conv_start = time.time()
    conv_result = await _convert_to_lean(inference, deepseek_client)
    result.conversion_latency = round(time.time() - conv_start, 2)
    _fill_conversion_fields(result, conv_result)

    # 只要 Lean 代码非空，就强制尝试编译
    # （即使 is_formalizable=false，编译错误本身也能暴露逻辑问题）
    lean_code = result.lean_code
    if not lean_code.strip():
        logger.info(
            f"[Lean] [{inference.problem_id}] Empty Lean code, "
            f"skipping compilation"
        )
        result.compile_passed = None
        result.compile_output = "(empty Lean code)"
        return result

    # 阶段二：编译
    logger.info(
        f"[Lean] Compiling Lean code for [{inference.problem_id}]..."
    )
    compile_result = await _compile_lean(lean_code, config)
    _fill_compile_fields(result, compile_result)

    # sorry 检测（编译后，无论通过与否都执行）
    sorry_info = _detect_sorry(lean_code)
    result.sorry_count = sorry_info["count"]
    result.has_incomplete_proof = sorry_info["has_sorry"]

    if compile_result["passed"]:
        if sorry_info["has_sorry"]:
            logger.info(
                f"[Lean] [{inference.problem_id}] Compilation PASSED "
                f"but proof is INCOMPLETE — {sorry_info['count']} sorry detected"
            )
            result.analysis_performed = True
            result.error_category = "logic_error"
            result.analysis_confidence = 1.0
            result.human_readable_error = (
                f"证明不完整：Lean 代码中检测到 {sorry_info['count']} 处 sorry，"
                f"说明原始推理的关键步骤未能被形式化证明。"
            )
            result.root_cause = (
                f"推理过程存在未完成的证明步骤（共 {sorry_info['count']} 处 sorry），"
                f"这些步骤在 Lean 形式化验证中被跳过，无法确认其正确性。"
            )
        else:
            logger.info(
                f"[Lean] [{inference.problem_id}] Compilation PASSED "
                f"— reasoning is logically sound"
            )
        return result

    # 阶段三：编译失败 → 分析错误
    logger.info(
        f"[Lean] [{inference.problem_id}] Compilation FAILED, "
        f"analyzing errors..."
    )
    analysis_start = time.time()
    analysis = await _analyze_error(
        inference, lean_code, compile_result["output"], deepseek_client
    )
    result.analysis_latency = round(time.time() - analysis_start, 2)
    _fill_analysis_fields(result, analysis)

    # 反馈修正循环：如果是翻译错误，尝试自动修正后重新编译
    _needs_revision = result.error_category in ("translation_error", "both")
    if _needs_revision:
        current_lean_code = lean_code
        current_compile_output = compile_result["output"]
        current_analysis = analysis

        for retry_i in range(1, _MAX_REVISION_RETRIES + 1):
            logger.info(
                f"[Lean] [{inference.problem_id}] Translation error detected, "
                f"attempting revision {retry_i}/{_MAX_REVISION_RETRIES}..."
            )
            result.revision_attempts = retry_i

            # 调用修正
            revision_start = time.time()
            revision = await _revise_lean_code(
                inference, current_lean_code,
                current_compile_output, current_analysis, deepseek_client
            )
            revision_latency = round(time.time() - revision_start, 2)

            if not revision or not revision.get("lean_code"):
                logger.warning(
                    f"[Lean] [{inference.problem_id}] Revision {retry_i} "
                    f"returned no code, stopping retries"
                )
                break

            revised_code = revision["lean_code"]
            result.revised_lean_code = revised_code

            # 重新编译
            logger.info(
                f"[Lean] [{inference.problem_id}] Re-compiling revised code "
                f"(attempt {retry_i})..."
            )
            recompile_result = await _compile_lean(revised_code, config)
            _fill_compile_fields(result, recompile_result)

            # 重新检测 sorry
            sorry_info = _detect_sorry(revised_code)
            result.sorry_count = sorry_info["count"]
            result.has_incomplete_proof = sorry_info["has_sorry"]

            if recompile_result["passed"]:
                logger.info(
                    f"[Lean] [{inference.problem_id}] Revision {retry_i} "
                    f"SUCCEEDED — compilation passed after fix "
                    f"({revision_latency}s)"
                )
                # 清除之前的错误标记
                result.error_category = None
                result.analysis_confidence = 0.0
                result.human_readable_error = (
                    f"代码经过 {retry_i} 次自动修正后编译通过。"
                )
                result.root_cause = ""
                result.logic_flaw_location = ""
                result.logic_flaw_why = ""
                result.fix_prompt_for_ai = ""
                return result

            # 重新分析修正后仍然失败的原因
            logger.info(
                f"[Lean] [{inference.problem_id}] Revision {retry_i} still "
                f"failed, re-analyzing..."
            )
            new_analysis = await _analyze_error(
                inference, revised_code,
                recompile_result["output"], deepseek_client
            )
            _fill_analysis_fields(result, new_analysis)
            result.analysis_latency += revision_latency

            # 如果新分析发现是纯逻辑错误，停止修正
            if new_analysis.get("error_category") == "logic_error":
                logger.info(
                    f"[Lean] [{inference.problem_id}] Root cause is logic_error, "
                    f"stopping revision loop"
                )
                break

            # 更新当前状态，准备下一轮修正
            current_lean_code = revised_code
            current_compile_output = recompile_result["output"]
            current_analysis = new_analysis

            if not revision.get("fixed_all_errors", False):
                logger.info(
                    f"[Lean] [{inference.problem_id}] Reviser indicates "
                    f"remaining issues, continuing to next retry..."
                )

    # 阶段四（可选）：编译失败且存在逻辑错误时 → 蓝图分解
    _is_logic_related = result.error_category in ("logic_error", "both")
    if _is_logic_related:
        logger.info(
            f"[Lean] [{inference.problem_id}] Logic error detected, "
            f"decomposing blueprint..."
        )
        blueprint_start = time.time()
        blueprint_result = await _decompose_blueprint(
            inference, lean_code, compile_result["output"], deepseek_client
        )
        blueprint_latency = round(time.time() - blueprint_start, 2)
        if blueprint_result and not blueprint_result.is_empty():
            result.dag = blueprint_result.to_dict()
            logger.info(
                f"[Lean] [{inference.problem_id}] Blueprint DAG generated "
                f"({len(blueprint_result.nodes)} nodes, "
                f"{blueprint_latency}s)"
            )
        else:
            logger.info(
                f"[Lean] [{inference.problem_id}] Blueprint decomposition "
                f"returned empty result"
            )

    return result


async def _run_llm_review_pipeline(
    inference: InferenceResult,
    deepseek_client: LLMClient,
    result: LeanVerificationResult,
) -> LeanVerificationResult:
    """
    执行降级逻辑审查流水线（Lean 不可用时）。

    直接使用 LLM 审查推理的逻辑一致性，不涉及任何编译操作。

    参数:
        inference: 需要审查的推理结果
        deepseek_client: DeepSeek LLM 客户端
        result: 预初始化的 LeanVerificationResult 对象（会被原地修改）

    返回:
        填充完成的 LeanVerificationResult
    """
    logger.info(
        f"[Lean] Lean not available, using LLM-only logic review "
        f"for [{inference.problem_id}]..."
    )
    review_start = time.time()
    review = await _logic_review_only(inference, deepseek_client)
    result.conversion_latency = round(time.time() - review_start, 2)
    _fill_review_fields(result, review)
    return result


async def run_lean_verification(
    inference: InferenceResult,
) -> LeanVerificationResult:
    """
    对一道题目的推理结果执行完整的 Lean 验证流程。

    流程：
    1. 检测 Lean 环境是否可用
    2. 如果可用：转化 → 编译 → 分析（三阶段）
    3. 如果不可用：降级为纯 LLM 逻辑审查

    参数:
        inference: 需要验证的推理结果

    返回:
        完整的 LeanVerificationResult 对象
    """
    config = get_config()
    deepseek_client = LLMClient(config.deepseek)
    lean_env = _get_lean_env(config)

    # 初始化结果对象，标记为已执行验证
    result = LeanVerificationResult(
        problem_id=inference.problem_id,
        verified=True,
        lean_available=lean_env["available"],
    )

    if lean_env["available"]:
        return await _run_full_lean_pipeline(
            inference, deepseek_client, config, result
        )
    else:
        return await _run_llm_review_pipeline(
            inference, deepseek_client, result
        )


async def run_lean_verification_batch(
    inferences: list[InferenceResult],
    concurrency: int = _DEFAULT_BATCH_CONCURRENCY,
) -> list[LeanVerificationResult]:
    """
    对多道题目的推理结果并发执行 Lean 验证。

    使用 asyncio.Semaphore 控制并发数，避免 LLM API 限流。

    参数:
        inferences: 需要验证的推理结果列表
        concurrency: 最大并发数（默认 3）

    返回:
        与 inferences 等长的 LeanVerificationResult 列表。
        验证失败的题目会返回 verified=False 的结果。
    """
    if not inferences:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    async def _verify_one(inf: InferenceResult) -> LeanVerificationResult:
        """单题验证包装器：获取信号量后执行验证，捕获异常。"""
        async with semaphore:
            try:
                return await run_lean_verification(inf)
            except Exception as e:
                logger.error(
                    f"[Lean] Verification failed for [{inf.problem_id}]: {e}"
                )
                return LeanVerificationResult(
                    problem_id=inf.problem_id,
                    verified=False,
                    lean_available=False,
                )

    tasks = [_verify_one(inf) for inf in inferences]
    return await asyncio.gather(*tasks)


# ==================== 筛选判断函数 ====================

# 触发 Lean 验证的置信度阈值
_LEAN_VERIFY_CONFIDENCE_THRESHOLD = 0.8


def should_verify_lean(eval_result) -> bool:
    """
    判断一道题是否需要进行 Lean 验证。

    触发条件（满足任一即触发）：
    1. DeepSeek 判定为错误（is_correct=False）
    2. 评判置信度低于阈值（默认 0.8）

    这样既能发现已知的错误推理中的逻辑问题，也能捕获评判模型
    不够确定的情况（可能隐藏了逻辑瑕疵）。

    参数:
        eval_result: EvaluationResult 或具有 is_correct/confidence 属性的对象

    返回:
        True 表示需要进行 Lean 验证
    """
    if not eval_result.is_correct:
        return True
    if eval_result.confidence < _LEAN_VERIFY_CONFIDENCE_THRESHOLD:
        return True
    return False
