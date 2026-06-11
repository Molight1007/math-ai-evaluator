"""
Intern-S1 inference module.
Calls Intern-S1 model to solve math problems and extracts structured JSON.
"""
import logging
import time
from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import Problem, InferenceResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert math problem solver. "
    "For each problem, output a JSON object with these fields: "
    '"answer": the final answer, '
    '"reasoning": step-by-step reasoning in Chinese, '
    '"steps": array of reasoning steps, '
    '"verification": self-check of the answer. '
    "Output ONLY the JSON object, no extra text."
)


def parse_intern_response(raw_content: str) -> dict:
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        answer = str(parsed.get("answer", ""))
        reasoning = str(parsed.get("reasoning", ""))
        steps = parsed.get("steps", [])
        if not isinstance(steps, list):
            steps = [str(steps)]
        verification = str(parsed.get("verification", ""))
        if not answer and reasoning:
            answer = reasoning.split("\n")[0][:200]
        return {
            "answer": answer,
            "reasoning": reasoning,
            "steps": [str(s) for s in steps],
            "verification": verification,
        }
    lines = raw_content.strip().split("\n")
    return {
        "answer": lines[0][:200] if lines else "",
        "reasoning": raw_content,
        "steps": [x for x in lines if x.strip()],
        "verification": "",
    }


async def run_inference(problem: Problem) -> InferenceResult:
    cfg = get_config()
    client = LLMClient(cfg.intern_s1)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem.question},
    ]
    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
        )
        latency = round(time.time() - start_time, 2)
        parsed = parse_intern_response(response["content"])
        return InferenceResult(
            problem_id=problem.id,
            question=problem.question,
            answer=parsed["answer"],
            reasoning=parsed["reasoning"],
            steps=parsed["steps"],
            verification=parsed["verification"],
            raw_response=response["content"],
            tokens_used=response.get("tokens_used", 0),
            latency_seconds=latency,
        )
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Inference failed for [{problem.id}]: {e}")
        return InferenceResult(
            problem_id=problem.id,
            question=problem.question,
            answer="",
            reasoning="",
            latency_seconds=latency,
            error=str(e),
        )
