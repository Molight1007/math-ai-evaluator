"""
DeepSeek 评判模块。
将 Intern-S1 的推理过程和答案发送给 DeepSeek 进行正确性评估。
支持利用题库中已匹配的参考答案辅助评判，提高准确率。
支持单题评判和批量评判两种模式。
"""
import asyncio
import logging
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

# ==================== Prompt 模板 ====================

# DeepSeek 评判系统提示词：要求输出正确性、置信度、解释和错误类型
JUDGE_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator. Your task is to judge whether "
    "an AI model's answer to a math problem is correct.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The model's answer\n"
    "3. The model's step-by-step reasoning\n"
    "4. (Optional) A reference answer from the answer bank\n\n"
    "If a reference answer is provided, use it as ground truth to compare. "
    "The reference answer comes from an official solution manual and is "
    "highly reliable.\n\n"
    "Output a JSON object with these fields:\n"
    '- "is_correct": true/false (boolean),\n'
    '- "confidence": a number 0.0-1.0 indicating your confidence,\n'
    '- "explanation": brief explanation in Chinese of why it is correct/wrong,\n'
    '- "error_type": if wrong, categorize as '
    '"calculation_error"/"logic_error"/"incomplete"/"other"/null,\n'
    '- "correct_answer": the correct answer if you can determine it, or null.\n'
    "Output ONLY the JSON object."
)

# 批量评判系统提示词：要求输出 JSON 数组
JUDGE_BATCH_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator. Your task is to judge whether "
    "an AI model's answers to MULTIPLE math problems are correct.\n\n"
    "You will receive {count} math problems with the model's answers "
    "and reasoning.\n"
    "For each problem you may also receive a reference answer (ground truth).\n\n"
    'Output a JSON ARRAY (not an object) where each element has these fields:\n'
    '- "problem_id": the problem identifier string,\n'
    '- "is_correct": true/false (boolean),\n'
    '- "confidence": a number 0.0-1.0,\n'
    '- "explanation": brief explanation in Chinese,\n'
    '- "error_type": "calculation_error"/"logic_error"/"incomplete"/"other"/null,\n'
    '- "correct_answer": the correct answer or null.\n\n'
    "IMPORTANT: Output ONLY the JSON array, one entry per problem, "
    "in the same order as input."
)


def _parse_single_result(parsed: dict) -> dict:
    """
    从解析后的评判 JSON 中提取标准化的判定字段。

    参数:
        parsed: 解析后的 dict

    返回:
        包含 is_correct, confidence, explanation, error_type, correct_answer 的 dict
    """
    return {
        "is_correct": bool(parsed.get("is_correct", False)),
        "confidence": float(parsed.get("confidence", 0.5)),
        "explanation": str(parsed.get("explanation", "")),
        "error_type": parsed.get("error_type"),
        "correct_answer": parsed.get("correct_answer"),
    }


def parse_judge_response(raw_content: str) -> dict:
    """
    解析 DeepSeek 评判响应，提取正确性判定和置信度。

    先尝试 JSON 解析，失败后使用关键词回退检测。

    参数:
        raw_content: DeepSeek API 返回的原始文本

    返回:
        包含 is_correct, confidence, explanation, error_type, correct_answer 的 dict
    """
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        return _parse_single_result(parsed)

    # 无法解析 JSON 时的关键词回退
    lower = raw_content.lower()
    is_correct = any(kw in lower or kw in raw_content for kw in _POSITIVE_KEYWORDS)
    return {
        "is_correct": is_correct,
        "confidence": _FALLBACK_CONFIDENCE,
        "explanation": raw_content[:500],
        "error_type": None,
        "correct_answer": None,
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
