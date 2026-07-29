import json
import os

path = os.path.join("..", "测试结果", "原始输出和推理过程", "report_20260724_233324.json")
with open(path, encoding="utf-8") as f:
    data = json.load(f)

out = []
for r in data.get("results", []):
    if not r.get("is_correct", True):
        out.append({
            "problem_id": r.get("problem_id"),
            "is_correct": r.get("is_correct"),
            "error_type": r.get("error_type"),
            "intern_answer": r.get("intern_answer"),
            "intern_reasoning_len": len(r.get("intern_reasoning", "")),
            "intern_reasoning": r.get("intern_reasoning", "")[:300],
            "judge_explanation": r.get("judge_explanation"),
            "inference_error": r.get("inference_error"),
        })

with open("check_final_out.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("wrote", len(out), "fail records")
