"""
Aggregator - merges inference + judge results and computes summary statistics.
"""
import logging
from models import Problem, InferenceResult, JudgeResult, EvaluationResult

logger = logging.getLogger(__name__)


def merge_result(
    problem: Problem,
    inference: InferenceResult,
    judge: JudgeResult,
) -> EvaluationResult:
    return EvaluationResult(
        problem_id=problem.id,
        question=problem.question,
        domain=problem.domain,
        reference_answer=problem.reference_answer,
        intern_answer=inference.answer,
        intern_reasoning=inference.reasoning,
        intern_steps=inference.steps,
        intern_verification=inference.verification,
        is_correct=judge.is_correct,
        confidence=judge.confidence,
        judge_explanation=judge.explanation,
        error_type=judge.error_type,
        correct_answer_judge=judge.correct_answer,
        inference_tokens=inference.tokens_used,
        judge_tokens=judge.tokens_used,
        inference_latency=inference.latency_seconds,
        judge_latency=judge.latency_seconds,
        inference_error=inference.error,
        judge_error=judge.error,
    )


def compute_summary(results: list[EvaluationResult]) -> dict:
    total = len(results)
    if total == 0:
        return {
            "total": 0, "correct": 0, "accuracy": 0.0,
            "avg_confidence": 0.0, "avg_inference_latency": 0.0,
            "avg_judge_latency": 0.0, "total_inference_tokens": 0,
            "total_judge_tokens": 0, "error_types": {}, "domain_stats": {},
        }

    correct = sum(1 for r in results if r.is_correct)
    valid_judges = [r for r in results if not r.judge_error]
    valid_inferences = [r for r in results if not r.inference_error]

    error_types = {}
    for r in results:
        if r.error_type:
            error_types[r.error_type] = error_types.get(r.error_type, 0) + 1

    domain_stats = {}
    for r in results:
        domain = r.domain or "unknown"
        if domain not in domain_stats:
            domain_stats[domain] = {"total": 0, "correct": 0}
        domain_stats[domain]["total"] += 1
        if r.is_correct:
            domain_stats[domain]["correct"] += 1
    for d in domain_stats:
        t = domain_stats[d]["total"]
        c = domain_stats[d]["correct"]
        domain_stats[d]["accuracy"] = round(c / t * 100, 2) if t > 0 else 0.0

    return {
        "total": total, "correct": correct,
        "accuracy": round(correct / total * 100, 2),
        "avg_confidence": round(
            sum(r.confidence for r in valid_judges) / len(valid_judges), 4
        ) if valid_judges else 0.0,
        "avg_inference_latency": round(
            sum(r.inference_latency for r in valid_inferences) / len(valid_inferences), 2
        ) if valid_inferences else 0.0,
        "avg_judge_latency": round(
            sum(r.judge_latency for r in valid_judges) / len(valid_judges), 2
        ) if valid_judges else 0.0,
        "total_inference_tokens": sum(r.inference_tokens for r in results),
        "total_judge_tokens": sum(r.judge_tokens for r in results),
        "error_types": error_types,
        "domain_stats": domain_stats,
    }
