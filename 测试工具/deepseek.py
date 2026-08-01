"""
DeepSeek 评判模块。
将 Intern-S1 的推理过程和答案发送给 DeepSeek 进行正确性评估。
支持利用题库中已匹配的参考答案辅助评判，提高准确率。
支持单题评判和批量评判两种模式。
"""
import asyncio
import logging
import re
import time
from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import InferenceResult, JudgeResult

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 评判模型参数
_JUDGE_TEMPERATURE = 0.1       # 低温度以获得更一致的评价
_JUDGE_MAX_TOKENS = 2048       # 单题评判最大 token
_JUDGE_BATCH_MAX_TOKENS = 8192 # 批量评判最大 token

# 回退关键词检测：无法解析 JSON 时使用的正/负向关键词
_POSITIVE_KEYWORDS = ("correct", "true", "正确")
_FALLBACK_CONFIDENCE = 0.3     # 回退时的默认置信度

# 批量评判缺失时的默认置信度
_BATCH_MISSING_CONFIDENCE = 0.3

_PROOF_QUESTION_RE = re.compile(
    r"证明|证\s*明|prove\b|show\s+that|demonstrate|derive\b|explain\s+why|"
    r"说明\s*为什么|为何|why\b",
    re.IGNORECASE,
)

_VALID_ERROR_TYPES = frozenset({
    "mathematical_error",
    "incomplete",
    "reasoning_error",
    "formatting_error",
    "calculation_error",
    "logic_error",
    "other",
})

# ==================== Prompt 模板 ====================

JUDGE_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator aligned with international math reasoning benchmarks.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The model's final answer (conclusion)\n"
    "3. The model's proof / reasoning / steps\n"
    "4. (Optional) A reference answer from the answer bank\n\n"
    "EVALUATION PROCEDURE (execute in strict order):\n\n"
    "Step 1 — CONCLUSION CORRECTNESS (highest priority):\n"
    "  Check whether the final mathematical conclusion is correct.\n"
    "  If the conclusion is WRONG → is_correct=false.\n"
    "  If the conclusion is CORRECT → proceed to Step 2.\n\n"
    "Step 2 — LOGIC ERROR CHECK:\n"
    "  Examine the reasoning process for SERIOUS mathematical logic errors.\n"
    "  A serious logic error means: circular reasoning, wrong theorem/method,\n"
    "  invalid deduction that coincidentally produces the right answer.\n"
    "  If a serious logic error exists → is_correct=false, error_type=reasoning_error.\n"
    "  If no serious logic error → the answer is MATHEMATICALLY CORRECT.\n"
    "  Proceed to Step 3.\n\n"
    "Step 3 — PROOF COMPLETENESS (lowest priority):\n"
    "  Check whether the problem requires proof/derivation/explanation/calculation\n"
    "  and whether the model provided sufficient process.\n"
    "  If process is missing or insufficient → error_type=incomplete.\n"
    "  IMPORTANT: incomplete is NOT a mathematical error.\n"
    "  incomplete does NOT override is_correct.\n"
    "  A correct conclusion with insufficient proof → is_correct=true, error_type=incomplete.\n\n"
    "CRITICAL RULES:\n"
    "- Correct conclusion → is_correct MUST be true. Non-negotiable.\n"
    "- Wrong conclusion → is_correct MUST be false.\n"
    "- Short but valid proof → is_correct=true (may set error_type=incomplete).\n"
    "- NEVER use mathematical_error, calculation_error, or logic_error\n"
    "  when the conclusion is correct and there is no core logic flaw.\n"
    "- For Chinese-language proofs, a single sentence with mathematical\n"
    "  reasoning keywords (设/令/因为/因此/所以/推出/可得) counts as having\n"
    "  proof content. Do NOT require lengthy proofs.\n\n"
    "error_type values:\n"
    "- mathematical_error: wrong final conclusion or fatal math mistake\n"
    "- calculation_error: arithmetic mistake (wrong conclusion)\n"
    "- incomplete: conclusion correct but proof/derivation missing or insufficient\n"
    "- reasoning_error: core logic error in derivation (conclusion may be coincidental)\n"
    "- logic_error: synonym for reasoning_error (core logic flaw)\n"
    "- formatting_error: format/LaTeX issues only, math essentially correct\n"
    "- null: fully correct with adequate support\n\n"
    "Output JSON only:\n"
    "{\n"
    '  "is_correct": true/false,\n'
    '  "confidence": 0.0-1.0,\n'
    '  "explanation": "brief Chinese explanation",\n'
    '  "error_type": "mathematical_error"|"calculation_error"|"incomplete"|'
    '"reasoning_error"|"logic_error"|"formatting_error"|null,\n'
    '  "correct_answer": null or string,\n'
    '  "conclusion_correct": true/false\n'
    "}\n"
    "Output ONLY the JSON object."
)

JUDGE_BATCH_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator. Judge MULTIPLE problems independently.\n\n"
    "EVALUATION PROCEDURE (same 3-step process for each problem):\n"
    "Step 1: Is the final mathematical conclusion correct?\n"
    "  Wrong → is_correct=false. Correct → proceed.\n"
    "Step 2: Does reasoning contain a SERIOUS logic error?\n"
    "  Yes → is_correct=false, error_type=reasoning_error. No → proceed.\n"
    "Step 3: Is the proof/derivation complete?\n"
    "  Missing/insufficient → error_type=incomplete (NOT a math error).\n"
    "  incomplete does NOT make is_correct=false.\n\n"
    "CRITICAL RULES:\n"
    "- Correct conclusion → is_correct=true ALWAYS.\n"
    "  If proof insufficient → error_type=incomplete (NOT mathematical_error).\n"
    "- Wrong conclusion → is_correct=false (error_type=mathematical_error or calculation_error).\n"
    "- Correct conclusion + core logic error → is_correct=false (error_type=reasoning_error).\n"
    "- NEVER use mathematical_error, calculation_error, or logic_error when conclusion is correct.\n"
    "- For Chinese proofs, a single sentence with reasoning keywords counts as proof.\n\n"
    "You will receive {count} problems.\n\n"
    'Output a JSON ARRAY where each element has:\n'
    '- "problem_id": string,\n'
    '- "is_correct": boolean,\n'
    '- "confidence": 0.0-1.0,\n'
    '- "explanation": Chinese,\n'
    '- "error_type": mathematical_error|calculation_error|incomplete|reasoning_error|logic_error|formatting_error|null,\n'
    '- "correct_answer": string or null,\n'
    '- "conclusion_correct": boolean\n\n'
    "Output ONLY the JSON array, same order as input."
)


def is_proof_problem(question: str) -> bool:
    if not question:
        return False
    return bool(_PROOF_QUESTION_RE.search(question))


# ---- 中文数学证明模式识别 ----

# 证明关键词：出现任意一个即表明有推理/证明意图
# 注意：不含"利用"、"根据"等过于泛化的词
_PROOF_KEYWORDS = (
    "证明", "因为", "由于", "设", "令", "假设", "由此", "因此",
    "所以", "推出", "得到", "可得", "可知", "故",
    "则", "即", "亦即", "等价", "化简", "代入", "整理得",
    "采用", "构造", "反证", "矛盾",
)

# 数学推导结构标记
_DERIVATION_MARKERS = (
    "→", "=>", "⟹", "推导", "导出", "推得",
)

# 步骤编号正则：1. / 2. / (1) / [1] / Step 1 / 第一步
_STEP_NUMBER_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"\d+[\.\)、]"           # 1. 2) 3、
    r"|\(\d+\)"              # (1) (2)
    r"|\[\d+\]"              # [1] [2]
    r"|Step\s*\d+"            # Step 1
    r"|第[一二三四五六七八九十]+步"  # 第一步
    r")",
    re.IGNORECASE,
)

# 公式推导正则：含等号链或不等式推导
_FORMULA_RE = re.compile(
    r"[a-zA-Z\u4e00-\u9fff\)\]]\s*[=<>≤≥≈≠]\s*"  # x = ... / f(x) ≥ ...
)

# 裸答案正则：只有最终结论，无推理标记
_BARE_ANSWER_RE = re.compile(r"^[\s\d\.\,\-\+/=\u4e00-\u9fff\(\)]{3,}$")


def _collect_proof_text(inference: InferenceResult) -> str:
    """汇总推理相关文本，用于证明模式识别。"""
    parts = []
    if inference.reasoning:
        parts.append(inference.reasoning)
    if inference.verification:
        parts.append(inference.verification)
    if inference.steps:
        parts.extend(inference.steps)
    # 多候选：取选中候选的 proof/reasoning
    candidates = inference.candidates or []
    sel = inference.selected_candidate_index
    for c in candidates:
        if sel is not None:
            try:
                if int(c.get("index", -1)) != int(sel):
                    continue
            except (ValueError, TypeError):
                continue
        for key in ("proof", "reasoning"):
            val = c.get(key)
            if val:
                parts.append(str(val))
        if c.get("steps"):
            parts.extend(c.get("steps"))
    # 如果没有选中候选，也检查所有候选
    if candidates and not sel:
        for c in candidates:
            for key in ("proof", "reasoning"):
                val = c.get(key)
                if val:
                    parts.append(str(val))
            if c.get("steps"):
                parts.extend(c.get("steps"))
    return "\n".join(parts)


def _detect_proof_features(text: str) -> dict:
    """
    分析文本中的证明特征，返回特征字典。

    返回:
        {
            "has_keywords": bool,       # 含证明关键词
            "has_derivation": bool,     # 含数学推导结构
            "has_steps": bool,          # 含步骤编号
            "has_formula": bool,        # 含公式推导
            "keyword_count": int,       # 关键词出现次数
            "step_count": int,          # 步骤编号数量
        }
    """
    if not text or not text.strip():
        return {
            "has_keywords": False,
            "has_derivation": False,
            "has_steps": False,
            "has_formula": False,
            "keyword_count": 0,
            "step_count": 0,
        }

    # 关键词检测
    keyword_count = sum(1 for kw in _PROOF_KEYWORDS if kw in text)
    has_keywords = keyword_count >= 1

    # 推导结构检测
    has_derivation = any(marker in text for marker in _DERIVATION_MARKERS)

    # 步骤编号检测
    step_matches = _STEP_NUMBER_RE.findall(text)
    step_count = len(step_matches)
    has_steps = step_count >= 2  # 至少两步才算有步骤

    # 公式推导检测
    formula_matches = _FORMULA_RE.findall(text)
    has_formula = len(formula_matches) >= 1

    return {
        "has_keywords": has_keywords,
        "has_derivation": has_derivation,
        "has_steps": has_steps,
        "has_formula": has_formula,
        "keyword_count": keyword_count,
        "step_count": step_count,
    }


def inference_has_proof(inference: InferenceResult) -> bool:
    """
    proof-aware：是否有证明/推理/步骤内容。
    不再使用简单长度阈值，改为中文数学证明模式识别。

    判定有证明的条件（满足任意一项）：
    1. 含证明关键词（证明/因为/设/令/因此/所以/推出 等）
    2. 含数学推导结构（→ / => / 推导 / 导出）
    3. 含步骤编号（1. 2. 3. / (1) / Step 1 / 第一步）
    4. 含公式推导（含等号/不等号的推导链）
    5. 有 steps 列表（非空）

    特殊处理：极短文本（<20字符）仅含1个关键词且无结构化推导特征时，
    视为仅引用方法名而非实际证明（如"欧几里得证明法可以证明"）。
    """
    # steps 列表非空 → 有证明
    if inference.steps:
        return True

    text = _collect_proof_text(inference)
    if not text.strip():
        return False

    features = _detect_proof_features(text)

    # 短文本保护：极短文本 + 仅1个关键词 + 无结构化特征 → 不是证明
    text_len = len(text.strip())
    structural_signals = (
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if (
        text_len < 20
        and features["keyword_count"] <= 1
        and not any(structural_signals)
    ):
        return False

    return (
        features["has_keywords"]
        or features["has_derivation"]
        or features["has_steps"]
        or features["has_formula"]
    )


def proof_quality_score(inference: InferenceResult) -> float:
    """
    评估证明质量分数（0-1）。

    返回值:
        0.0: 无证明（无关键词、无推导、无步骤、无公式）
        0.5: 有简单推理（含关键词或基本推导，但不够完整）
        1.0: 完整证明（多维度证据：关键词+推导/步骤/公式）
    """
    text = _collect_proof_text(inference)
    if not text.strip():
        return 0.0

    features = _detect_proof_features(text)

    # 无任何证明特征 → 0
    score_signals = (
        features["has_keywords"],
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if not any(score_signals):
        return 0.0

    # 短文本保护：极短文本 + 仅1个关键词 + 无结构化特征 → 无实际证明
    text_len = len(text.strip())
    structural_signals = (
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if (
        text_len < 20
        and features["keyword_count"] <= 1
        and not any(structural_signals)
    ):
        return 0.0

    # 完整证明：关键词 + 至少一个结构化推导特征
    if features["has_keywords"] and any(structural_signals):
        return 1.0

    # 有多个关键词但无结构化推导 → 较好但仍不完整
    if features["keyword_count"] >= 3:
        return 1.0

    # 有步骤编号但无关键词 → 也算较完整
    if features["has_steps"] and features["step_count"] >= 3:
        return 1.0

    # 有公式推导但无关键词 → 简单推理
    if features["has_formula"] and not features["has_keywords"]:
        return 0.5

    # 有关键词但无结构化推导 → 简单推理
    if features["has_keywords"] and not any(structural_signals):
        return 0.5

    # 有推导结构但无关键词 → 简单推理
    if features["has_derivation"] and not features["has_keywords"]:
        return 0.5

    # 默认：有证据但不够充分
    return 0.5


def _normalize_error_type(raw: str | None) -> str | None:
    if not raw:
        return None
    et = str(raw).strip().lower()
    mapping = {
        "math_error": "mathematical_error",
    }
    et = mapping.get(et, et)
    if et not in _VALID_ERROR_TYPES:
        return "other"
    return et


def apply_proof_aware_evaluation(
    inference: InferenceResult,
    parsed: dict,
) -> dict:
    """
    后处理 judge 结果，执行 3 步判断流程 + 错误分类规则。

    流程（与 JUDGE_SYSTEM_PROMPT 一致）：
    Step 1: 检查最终数学结论正确性
    Step 2: 检查推理过程是否存在严重逻辑错误
    Step 3: 检查证明完整度（incomplete ≠ 数学错误）

    核心原则：
    - 结论正确 → is_correct=true（不可因证明不足而判错）
    - 结论正确 + 证明不足 → error_type=incomplete
    - 结论错误 → is_correct=false
    - 结论正确 + 核心逻辑错误 → is_correct=false, error_type=reasoning_error
    """
    out = dict(parsed)
    out["error_type"] = _normalize_error_type(out.get("error_type"))
    conclusion_ok = out.get("conclusion_correct")
    if conclusion_ok is None:
        conclusion_ok = out.get("is_correct", False)
    out["conclusion_correct"] = bool(conclusion_ok)

    # 计算 proof_quality_score 并注入输出
    pq_score = proof_quality_score(inference)
    out["proof_quality_score"] = pq_score

    proof_required = is_proof_problem(inference.question)
    has_proof = inference_has_proof(inference)

    # ---- Step 1: 结论错误 → is_correct=false ----
    if not conclusion_ok:
        out["is_correct"] = False
        if not out.get("error_type") or out.get("error_type") in (
            "incomplete", "formatting_error"
        ):
            out["error_type"] = "mathematical_error"
        return out

    # ---- Step 2: 结论正确，检查逻辑错误 ----
    # reasoning_error / logic_error 表示核心逻辑有问题
    # 但对于非证明题，如果结论正确，小推理瑕疵不应判错
    if out.get("error_type") in ("reasoning_error", "logic_error"):
        if proof_required and pq_score == 0:
            # 证明题 + 无任何证明 + 逻辑错误标记 → 可能是 judge 把"无证明"误判为逻辑错误
            out["is_correct"] = True
            out["error_type"] = "incomplete"
        elif not proof_required:
            # 计算题 + 结论正确 + 推理瑕疵 → 不判错
            out["is_correct"] = True
            # 保留 reasoning_error 标记但不影响 is_correct
        # 证明题 + 有证明 + 真正的逻辑错误 → 保持 is_correct=false
        return out

    # ---- Step 3: 结论正确 + 无逻辑错误，检查证明完整度 ----

    # Rule A: 结论正确但被判定为 mathematical_error / calculation_error
    # → judge 误判，修正为 incomplete + is_correct=true
    if out.get("error_type") in ("mathematical_error", "calculation_error"):
        out["is_correct"] = True
        if proof_required and pq_score == 0:
            out["error_type"] = "incomplete"
            if not out.get("explanation"):
                out["explanation"] = "数学结论正确，但缺少证明过程。"
        else:
            out["error_type"] = None
            if not out.get("explanation"):
                out["explanation"] = "数学结论正确，不应判定为数学错误。"
        return out

    # Rule B: 证明题 + 结论正确 + 完全无证明（quality=0）
    # → is_correct=true, error_type=incomplete
    if proof_required and pq_score == 0:
        out["is_correct"] = True
        out["error_type"] = "incomplete"
        if not out.get("explanation"):
            out["explanation"] = "数学结论正确，但证明题缺少证明或推导过程。"
        return out

    # Rule C: 结论正确 + incomplete → 确保 is_correct=true
    if out.get("error_type") == "incomplete":
        out["is_correct"] = True
        # 如果有证明内容（quality > 0），可以清除 incomplete 标记
        if pq_score >= 0.5 and not proof_required:
            out["error_type"] = None
        return out

    # Rule D: 结论正确 + formatting_error → is_correct=true
    if out.get("error_type") == "formatting_error":
        out["is_correct"] = True
        return out

    # Rule E: 结论正确 + 无 error_type → is_correct=true
    if not out.get("error_type"):
        out["is_correct"] = True

    # 最终安全网：结论正确 → is_correct 必须为 true
    if conclusion_ok:
        out["is_correct"] = True

    return out


def _parse_single_result(parsed: dict) -> dict:
    """
    从解析后的评判 JSON 中提取标准化的判定字段。
    """
    conclusion_correct = parsed.get("conclusion_correct")
    if conclusion_correct is None:
        conclusion_correct = parsed.get("is_correct", False)
    return {
        "is_correct": bool(parsed.get("is_correct", False)),
        "confidence": float(parsed.get("confidence", 0.5)),
        "explanation": str(parsed.get("explanation", "")),
        "error_type": _normalize_error_type(parsed.get("error_type")),
        "correct_answer": parsed.get("correct_answer"),
        "conclusion_correct": bool(conclusion_correct),
    }


def parse_judge_response(raw_content: str) -> dict:
    """
    解析 DeepSeek 评判响应，提取正确性判定和置信度。
    """
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        return _parse_single_result(parsed)

    lower = raw_content.lower()
    is_correct = any(kw in lower or kw in raw_content for kw in _POSITIVE_KEYWORDS)
    return {
        "is_correct": is_correct,
        "confidence": _FALLBACK_CONFIDENCE,
        "explanation": raw_content[:500],
        "error_type": None,
        "correct_answer": None,
        "conclusion_correct": is_correct,
    }


def parse_judge_batch_response(
    raw_content: str, expected_ids: list[str]
) -> list[dict]:
    """
    解析 DeepSeek 批量评判响应，返回每道题的判定字典列表。

    支持两种格式：
    1. 直接 JSON 数组 [{problem_id, is_correct, ...}, ...]
    2. {"results": [...]} 或 {"judgements": [...]} 包装格式

    参数:
        raw_content: DeepSeek API 返回的原始文本
        expected_ids: 期望的题目 ID 列表（用于按序组装和缺失补全）

    返回:
        与 expected_ids 等长的判定 dict 列表
    """
    parsed = extract_json_from_text(raw_content)
    results_map = {}

    # 处理 JSON 数组格式
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                pid = item.get("problem_id", "")
                results_map[pid] = _parse_single_result(item)

    # 处理 {"results": [...]} 或 {"judgements": [...]} 格式
    elif isinstance(parsed, dict):
        inner = parsed.get("results") or parsed.get("judgements")
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    pid = item.get("problem_id", "")
                    results_map[pid] = _parse_single_result(item)

    # 按 expected_ids 顺序组装结果，缺失的用默认值补全
    output = []
    for pid in expected_ids:
        if pid in results_map:
            output.append(results_map[pid])
        else:
            logger.warning(
                f"[Batch Judge] Missing result for problem {pid}, "
                f"using default"
            )
            output.append({
                "is_correct": False,
                "confidence": _BATCH_MISSING_CONFIDENCE,
                "explanation": "(未能在批量响应中找到该题目的判定结果)",
                "error_type": None,
                "correct_answer": None,
            })
    return output


def _build_judge_user_prompt(
    inference: InferenceResult,
    reference_answer: str = None,
    answer_source: str = None,
) -> str:
    """
    构建单题评判的 user prompt。

    参数:
        inference: 推理结果
        reference_answer: 参考答案（可选）
        answer_source: 参考答案来源说明（可选）

    返回:
        结构化的 user prompt 字符串
    """
    steps_text = (
        chr(10).join(f"- {s}" for s in inference.steps)
        if inference.steps else "N/A"
    )

    reference_section = ""
    if reference_answer:
        source_info = (
            f"(Source: {answer_source})" if answer_source else ""
        )
        reference_section = f"""
## Reference Answer (Ground Truth)
{reference_answer}

{source_info}

**IMPORTANT**: The reference answer above is from an official solution manual.
Use it as the ground truth when judging correctness.
If the model's answer matches the reference answer
(considering equivalent forms), mark it as correct.
If the model's answer contradicts the reference answer, mark it as incorrect."""

    return f"""## Math Problem
{inference.question}
{reference_section}
## Model's Answer
{inference.answer}

## Model's Reasoning
{inference.reasoning}

## Model's Steps
{steps_text}

Please judge whether the answer is correct."""


async def run_judge(
    inference: InferenceResult,
    reference_answer: str = None,
    answer_source: str = None,
) -> JudgeResult:
    """
    对单道推理结果进行评判。

    参数:
        inference: Intern-S1 的推理结果
        reference_answer: 从答案库匹配的参考答案（可选，有则大幅提升准确率）
        answer_source: 参考答案来源说明

    返回:
        JudgeResult 对象
    """
    cfg = get_config()
    client = LLMClient(cfg.deepseek)

    user_content = _build_judge_user_prompt(
        inference, reference_answer, answer_source
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    logger.info(
        f"[Judge {inference.problem_id}] prompt length: "
        f"system={len(JUDGE_SYSTEM_PROMPT)}, user={len(user_content)}"
    )
    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=_JUDGE_TEMPERATURE,
            max_tokens=_JUDGE_MAX_TOKENS,
        )
        latency = round(time.time() - start_time, 2)
        parsed = parse_judge_response(response["content"])
        parsed = apply_proof_aware_evaluation(inference, parsed)
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=parsed["is_correct"],
            confidence=parsed["confidence"],
            explanation=parsed["explanation"],
            error_type=parsed.get("error_type"),
            correct_answer=parsed.get("correct_answer"),
            raw_response=response["content"],
            tokens_used=response.get("tokens_used", 0),
            latency_seconds=latency,
        )
    except asyncio.TimeoutError as te:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Judge timeout for [{inference.problem_id}]: {te}")
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=False,
            confidence=0.0,
            explanation="Judge timeout: answer may be too long or service is slow.",
            raw_response="",
            latency_seconds=latency,
            error=str(te),
        )
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Judge failed for [{inference.problem_id}]: {e}")
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=False,
            confidence=0.0,
            explanation=f"Judge error: {e}",
            raw_response="",
            latency_seconds=latency,
            error=str(e),
        )


async def run_judge_batch(
    inferences: list[InferenceResult],
    reference_map: dict[str, tuple[str, str]] | None = None,
    batch_size: int = 3,
) -> list[JudgeResult]:
    """
    对多道推理结果进行批量评判，按 batch_size 分批调用，避免上下文过长
    导致答案被截断或 JSON 解析失败。

    参数:
        inferences: 多个 InferenceResult 列表
        reference_map: {problem_id: (answer_text, source)} 可选参考答案映射
        batch_size: 每批最多评判的题目数，默认 3

    返回:
        与 inferences 等长的 JudgeResult 列表。
        如果某一批调用失败，该批内题目单独走逐题评判作为兜底。
    """
    if not inferences:
        return []

    cfg = get_config()
    client = LLMClient(cfg.deepseek)
    all_results: list[JudgeResult] = []

    total = len(inferences)
    for start in range(0, total, batch_size):
        chunk = inferences[start:start + batch_size]
        chunk_results = await _run_judge_batch_chunk(
            client, chunk, reference_map, start // batch_size + 1
        )
        all_results.extend(chunk_results)

    return all_results


async def _run_judge_batch_chunk(
    client: LLMClient,
    inferences: list[InferenceResult],
    reference_map: dict[str, tuple[str, str]] | None,
    chunk_index: int,
) -> list[JudgeResult]:
    """评判一个批次，失败时自动 fallback 到单题评判。"""
    # 构建批量 prompt：依次列出每道题的信息
    items_text = ""
    for i, inf in enumerate(inferences):
        steps_text = (
            chr(10).join(f"- {s}" for s in inf.steps)
            if inf.steps else "N/A"
        )

        ref_section = ""
        if reference_map and inf.problem_id in reference_map:
            ans, src = reference_map[inf.problem_id]
            source_info = f"(Source: {src})" if src else ""
            ref_section = (
                f"\n### Reference Answer (Ground Truth)\n{ans}\n"
                f"{source_info}\n**Use this as ground truth.**"
            )

        # 对超长答案/推理做截断提示，防止整批 prompt 超出模型上下文
        answer_text = inf.answer
        reasoning_text = inf.reasoning
        max_item_len = 8000
        if len(answer_text) > max_item_len:
            answer_text = (
                answer_text[:max_item_len // 2]
                + "\n...[答案中间部分已省略]\n"
                + answer_text[-max_item_len // 2:]
            )
        if len(reasoning_text) > max_item_len:
            reasoning_text = (
                reasoning_text[:max_item_len // 2]
                + "\n...[推理中间部分已省略]\n"
                + reasoning_text[-max_item_len // 2:]
            )

        items_text += (
            f"\n--- Problem #{i + 1} ---\n"
            f"**ID**: {inf.problem_id}\n\n"
            f"**Question**: {inf.question}\n"
            f"{ref_section}\n\n"
            f"**Model's Answer**: {answer_text}\n\n"
            f"**Model's Reasoning**: {reasoning_text}\n\n"
            f"**Model's Steps**:\n{steps_text}\n"
        )

    system_prompt = JUDGE_BATCH_SYSTEM_PROMPT.format(count=len(inferences))
    user_content = (
        f"Please judge each of the following {len(inferences)} math "
        f"problems independently.\n"
        f"Output a JSON array with one judgment per problem.\n\n"
        f"{items_text}\n\n"
        f"Remember: Output ONLY a JSON array, one object per problem, "
        f"preserving order."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info(
        f"[Batch Judge] Chunk {chunk_index}: prompt length "
        f"system={len(system_prompt)}, user={len(user_content)}"
    )
    start_time = time.time()
    try:
        logger.info(
            f"[Batch Judge] Chunk {chunk_index}: sending {len(inferences)} "
            f"problems together..."
        )
        response = await client.chat(
            messages=messages,
            temperature=_JUDGE_TEMPERATURE,
            max_tokens=_JUDGE_BATCH_MAX_TOKENS,
        )
        latency = round(time.time() - start_time, 2)
        expected_ids = [inf.problem_id for inf in inferences]
        parsed_list = parse_judge_batch_response(
            response["content"], expected_ids
        )

        judge_results = []
        for inf, parsed in zip(inferences, parsed_list):
            parsed = apply_proof_aware_evaluation(inf, parsed)
            judge_results.append(JudgeResult(
                problem_id=inf.problem_id,
                is_correct=parsed["is_correct"],
                confidence=parsed["confidence"],
                explanation=parsed["explanation"],
                error_type=parsed.get("error_type"),
                correct_answer=parsed.get("correct_answer"),
                raw_response=response["content"],
                tokens_used=response.get("tokens_used", 0),
                latency_seconds=latency,
            ))

        logger.info(
            f"[Batch Judge] Chunk {chunk_index}: completed {len(judge_results)} "
            f"judgments in {latency}s"
        )
        return judge_results

    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(
            f"[Batch Judge] Chunk {chunk_index} failed: {e}. "
            f"Falling back to single judge for {len(inferences)} problems."
        )
        # 该批次失败时，逐题兜底评判
        fallback_results = []
        for inf in inferences:
            try:
                ref = reference_map.get(inf.problem_id) if reference_map else None
                ref_answer = ref[0] if ref else None
                ref_source = ref[1] if ref else None
                judge = await run_judge(
                    inf,
                    reference_answer=ref_answer,
                    answer_source=ref_source,
                )
                fallback_results.append(judge)
            except Exception as inner_e:
                logger.error(
                    f"[Batch Judge] Single fallback failed for {inf.problem_id}: {inner_e}"
                )
                fallback_results.append(JudgeResult(
                    problem_id=inf.problem_id,
                    is_correct=False,
                    confidence=0.0,
                    explanation=f"Judge fallback error: {inner_e}",
                    raw_response="",
                    latency_seconds=latency,
                    error=str(inner_e),
                ))
        return fallback_results
