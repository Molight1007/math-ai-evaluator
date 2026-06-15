"""
DeepSeek 评判模块。
将 Intern-S1 的推理过程和答案发送给 DeepSeek 进行正确性评估。
"""
import logging
import time
from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import InferenceResult, JudgeResult

logger = logging.getLogger(__name__)

# DeepSeek 评判系统提示词：要求输出正确性、置信度、解释和错误类型
JUDGE_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator. Your task is to judge whether "
    "an AI model's answer to a math problem is correct.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The model's answer\n"
    "3. The model's step-by-step reasoning\n\n"
    "Output a JSON object with these fields:\n"
    '- "is_correct": true/false (boolean),\n'
    '- "confidence": a number 0.0-1.0 indicating your confidence,\n'
    '- "explanation": brief explanation in Chinese of why it is correct/wrong,\n'
    '- "error_type": if wrong, categorize as "calculation_error"/"logic_error"/"incomplete"/"other"/null,\n'
    '- "correct_answer": the correct answer if you can determine it, or null.\n'
    "Output ONLY the JSON object."
)


def parse_judge_response(raw_content: str) -> dict:
    """解析 DeepSeek 评判响应，提取正确性判定和置信度"""
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        return {
            "is_correct": bool(parsed.get("is_correct", False)),
            "confidence": float(parsed.get("confidence", 0.5)),
            "explanation": str(parsed.get("explanation", "")),
            "error_type": parsed.get("error_type"),
            "correct_answer": parsed.get("correct_answer"),
        }
    # 无法解析 JSON 时的关键词回退：检测 "correct"、"正确" 等
    lower = raw_content.lower()
    is_correct = "correct" in lower or "true" in lower or "正确" in raw_content
    return {
        "is_correct": is_correct,
        "confidence": 0.3,
        "explanation": raw_content[:500],
        "error_type": None,
        "correct_answer": None,
    }


async def run_judge(inference: InferenceResult) -> JudgeResult:
    """对单道推理结果进行评判，返回 JudgeResult"""
    cfg = get_config()
    client = LLMClient(cfg.deepseek)
    # 构建包含题目、答案、推理过程、推理步骤的评判请求
    steps_text = chr(10).join(f"- {s}" for s in inference.steps) if inference.steps else "N/A"
    user_content = f"""## Math Problem
:{inference.question}

## Model's Answer
:{inference.answer}

## Model's Reasoning
:{inference.reasoning}

## Model's Steps
:{steps_text}

Please judge whether the answer is correct."""

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=0.1,  # 低温度以获得更一致的评价
            max_tokens=2048,
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
