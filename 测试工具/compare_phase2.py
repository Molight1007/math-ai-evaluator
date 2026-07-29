"""
MATH010 修改前后对比 — 基于 report_20260729_195359 实际数据
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import InferenceResult
from deepseek import apply_proof_aware_evaluation, is_proof_problem, inference_has_proof

REPORT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "测试结果",
    "原始输出和推理过程", "report_20260729_195359.json"
)

with open(REPORT_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 70)
print("  MATH010 修改前后对比 (基于 report_20260729_195359 实际数据)")
print("=" * 70)

# --- MATH010 详情 ---
for r in data.get("results", []):
    if r.get("problem_id") != "MATH010":
        continue

    inf = InferenceResult(
        problem_id=r["problem_id"],
        question=r.get("question", ""),
        answer=r.get("intern_answer", ""),
        reasoning=r.get("intern_reasoning", ""),
        steps=r.get("intern_steps", []),
        verification=r.get("intern_verification", ""),
    )

    old_is_correct = r.get("is_correct")
    old_error_type = r.get("error_type")
    old_explanation = r.get("judge_explanation", "")

    judge_parsed = {
        "is_correct": False,
        "confidence": 0.6,
        "explanation": old_explanation,
        "error_type": "incomplete",
        "correct_answer": None,
        "conclusion_correct": True,
    }

    new_result = apply_proof_aware_evaluation(inf, dict(judge_parsed))

    print()
    print(f"题目: {r.get('question', '')[:60]}")
    print(f"模型答案: {r.get('intern_answer', '')[:80]}")
    print(f"模型推理: {r.get('intern_reasoning', '')[:80]}")
    print(f"是证明题: {is_proof_problem(inf.question)}")
    print(f"有证明内容: {inference_has_proof(inf)}")
    print()
    print("--- 修改前 (Phase 1) ---")
    print(f"  is_correct:        {old_is_correct}")
    print(f"  error_type:        {old_error_type}")
    print(f"  judge_explanation: {old_explanation[:100]}")
    print()
    print("--- 修改后 (Phase 2) ---")
    print(f"  is_correct:  {new_result['is_correct']}")
    print(f"  error_type:  {new_result.get('error_type')}")
    print(f"  explanation: {new_result.get('explanation', '')[:100]}")
    print()
    print("--- 变化 ---")
    print(f"  is_correct: {old_is_correct} -> {new_result['is_correct']}")
    print(f"  error_type: {old_error_type} -> {new_result.get('error_type')}")
    break

# --- 全报告影响 ---
print()
print("=" * 70)
print("  全报告影响分析 (report_20260729_195359)")
print("=" * 70)

old_correct = 0
new_correct = 0
changes = []

for r in data.get("results", []):
    pid = r.get("problem_id", "")
    old_ic = r.get("is_correct", False)
    old_et = r.get("error_type")
    old_exp = r.get("judge_explanation", "")

    inf = InferenceResult(
        problem_id=pid,
        question=r.get("question", ""),
        answer=r.get("intern_answer", ""),
        reasoning=r.get("intern_reasoning", ""),
        steps=r.get("intern_steps", []),
        verification=r.get("intern_verification", ""),
    )

    # 推断 conclusion_correct
    if old_ic:
        conclusion_correct = True
    elif old_et == "incomplete":
        conclusion_correct = True
    else:
        conclusion_correct = False

    judge_parsed = {
        "is_correct": old_ic,
        "confidence": r.get("confidence", 0.5),
        "explanation": old_exp,
        "error_type": old_et,
        "correct_answer": r.get("correct_answer_judge"),
        "conclusion_correct": conclusion_correct,
    }

    new_r = apply_proof_aware_evaluation(inf, dict(judge_parsed))

    if old_ic:
        old_correct += 1
    if new_r["is_correct"]:
        new_correct += 1

    if old_ic != new_r["is_correct"] or old_et != new_r.get("error_type"):
        changes.append({
            "pid": pid,
            "old_ic": old_ic,
            "new_ic": new_r["is_correct"],
            "old_et": old_et,
            "new_et": new_r.get("error_type"),
            "conclusion_ok": conclusion_correct,
        })

print()
print(f"修改前 Accuracy: {old_correct}/10 = {old_correct * 10}%")
print(f"修改后 Accuracy: {new_correct}/10 = {new_correct * 10}%")
print()
print("变化的题目:")
if not changes:
    print("  (无变化)")
for c in changes:
    if not c["old_ic"] and c["new_ic"]:
        arrow = "[UP: now correct]"
    elif c["old_ic"] and not c["new_ic"]:
        arrow = "[DOWN: now wrong]"
    else:
        arrow = "[CHANGED]"
    print(f"  {c['pid']}: is_correct {c['old_ic']}->{c['new_ic']}, "
          f"error_type {c['old_et']}->{c['new_et']}  {arrow}")
