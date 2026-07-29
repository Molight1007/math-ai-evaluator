"""
Phase 2 验证测试：Judge Prompt 优化 — MATH010 场景对比

测试目标：
1. MATH010 典型场景：结论正确但证明不足
   - 修改前：is_correct=False, error_type=incomplete
   - 修改后：is_correct=True, error_type=incomplete

2. 结论正确但被误判为 mathematical_error
   - 修改后：修正为 is_correct=True, error_type=incomplete

3. 结论正确但被误判为 logic_error
   - 修改后：修正为 is_correct=True, error_type=incomplete

4. 结论错误 → 确保 is_correct=False

5. 结论正确 + 有完整证明 → is_correct=True, error_type=None

6. 结论正确 + reasoning_error（证明题有证明，核心逻辑错误）→ 保持 is_correct=False
   注：无证明内容时，reasoning_error 视为误标 → 修正为 incomplete + is_correct=True

7. 计算题结论正确 + reasoning_error → is_correct=True
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import InferenceResult
from deepseek import apply_proof_aware_evaluation

# ==================== MATH010 测试数据 ====================

MATH010_QUESTION = "在三角形ABC中，证明三条中线交于一点，并求交点分割中线比例。"
MATH010_REFERENCE = "利用坐标法或向量法可证明三条中线交于重心，重心将每条中线按2:1分割，靠近顶点部分较长。"

# 场景1: 模型只给出结论，没有证明（典型失败场景）
inference_no_proof = InferenceResult(
    problem_id="MATH010",
    question=MATH010_QUESTION,
    answer="三条中线交于一点，该点将每条中线分为2:1的比例",
    reasoning="候选0的坐标法通过直接计算验证了交点存在性和比例关系，逻辑完整且结果明确，可信度最高。",
    steps=[],
    verification="",
    candidates=[],
    selected_candidate_index=None,
    tokens_used=100,
    latency_seconds=1.0,
    error=None,
)

# 场景2: 模型给出完整证明
inference_with_proof = InferenceResult(
    problem_id="MATH010",
    question=MATH010_QUESTION,
    answer="三角形的三条中线交于一点，称为重心，且交点将每条中线分成2:1的比例。",
    reasoning=(
        "[Proof] 使用坐标法证明：设三角形ABC的顶点坐标为A(x1,y1), B(x2,y2), C(x3,y3)。"
        "各边中点D、E、F的坐标分别为((x2+x3)/2, (y2+y3)/2)等。"
        "中线AD的参数方程为A+t(D-A)，中线BE的参数方程为B+s(E-B)。"
        "求解两条中线交点得到t=2/3, s=2/3，交点坐标为((x1+x2+x3)/3, (y1+y2+y3)/3)。"
        "验证该交点在第三条中线CF上，t=2/3。"
        "因此三条中线交于一点（重心），且交点将每条中线按2:1分割。"
    ),
    steps=["设顶点坐标", "求中点坐标", "写中线参数方程", "求解交点", "验证第三条中线", "计算比例"],
    verification="交点坐标对称性验证通过",
    candidates=[],
    selected_candidate_index=None,
    tokens_used=500,
    latency_seconds=3.0,
    error=None,
)

# 计算题测试数据
CALC_QUESTION = "求极限 lim(x->0) (sin x - x) / x^3"
inference_calc = InferenceResult(
    problem_id="MATH019",
    question=CALC_QUESTION,
    answer="-1/6",
    reasoning="利用泰勒展开 sinx = x - x^3/6 + ... 代入得 (-x^3/6) / x^3 = -1/6",
    steps=[],
    verification="",
    candidates=[],
    selected_candidate_index=None,
    tokens_used=100,
    latency_seconds=1.0,
    error=None,
)

# 计算题错误答案
inference_calc_wrong = InferenceResult(
    problem_id="MATH019",
    question=CALC_QUESTION,
    answer="1/6",
    reasoning="利用泰勒展开计算",
    steps=[],
    verification="",
    candidates=[],
    selected_candidate_index=None,
    tokens_used=100,
    latency_seconds=1.0,
    error=None,
)


def run_test(name, inference, judge_parsed, expected_is_correct, expected_error_type):
    """运行单个测试"""
    result = apply_proof_aware_evaluation(inference, dict(judge_parsed))
    ok = (result["is_correct"] == expected_is_correct and
          result.get("error_type") == expected_error_type)
    status = "PASS" if ok else "FAIL"
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"  Input:  is_correct={judge_parsed.get('is_correct')}, "
          f"error_type={judge_parsed.get('error_type')}, "
          f"conclusion_correct={judge_parsed.get('conclusion_correct')}")
    print(f"  Output: is_correct={result['is_correct']}, "
          f"error_type={result.get('error_type')}")
    print(f"  Expected: is_correct={expected_is_correct}, "
          f"error_type={expected_error_type}")
    print(f"  Result: {status}")
    if not ok:
        print(f"  [DEBUG] full output: {result}")
    return ok


passed = 0
total = 0

# ==================== Test 1: MATH010 结论正确 + 无证明 → is_correct=True ====================
total += 1
if run_test(
    "MATH010: 结论正确 + 无证明 (典型失败场景)",
    inference_no_proof,
    # Judge 返回：结论正确，但证明不足，判incomplete
    {"is_correct": False, "error_type": "incomplete", "conclusion_correct": True,
     "explanation": "模型答案仅给出了结论，没有提供完整的证明过程。", "confidence": 0.6},
    expected_is_correct=True,   # 修改后：结论正确即判对
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 2: MATH010 结论正确 + 被误判 mathematical_error ====================
total += 1
if run_test(
    "MATH010: 结论正确 + 被误判 mathematical_error",
    inference_no_proof,
    {"is_correct": False, "error_type": "mathematical_error", "conclusion_correct": True,
     "explanation": "", "confidence": 0.5},
    expected_is_correct=True,   # 修正：结论正确不应判数学错误
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 3: MATH010 结论正确 + 被误判 calculation_error ====================
total += 1
if run_test(
    "MATH010: 结论正确 + 被误判 calculation_error",
    inference_no_proof,
    {"is_correct": False, "error_type": "calculation_error", "conclusion_correct": True,
     "explanation": "", "confidence": 0.5},
    expected_is_correct=True,
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 4: MATH010 结论正确 + 被误判 logic_error ====================
total += 1
if run_test(
    "MATH010: 结论正确 + 被误判 logic_error",
    inference_no_proof,
    {"is_correct": False, "error_type": "logic_error", "conclusion_correct": True,
     "explanation": "", "confidence": 0.5},
    expected_is_correct=True,   # 正确答案不判 logic_error
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 5: MATH010 结论错误 → is_correct=False ====================
total += 1
if run_test(
    "MATH010: 结论错误 (比例说成3:1)",
    InferenceResult(
        problem_id="MATH010", question=MATH010_QUESTION,
        answer="三条中线交于一点，比例3:1",
        reasoning="通过坐标法计算得到3:1",
        steps=[], verification="", candidates=[],
        selected_candidate_index=None,
        tokens_used=100, latency_seconds=1.0, error=None,
    ),
    {"is_correct": False, "error_type": "mathematical_error", "conclusion_correct": False,
     "explanation": "比例应为2:1而非3:1", "confidence": 0.9},
    expected_is_correct=False,
    expected_error_type="mathematical_error",
):
    passed += 1

# ==================== Test 6: MATH010 结论正确 + 有完整证明 → is_correct=True, error_type=None ====================
total += 1
if run_test(
    "MATH010: 结论正确 + 有完整证明",
    inference_with_proof,
    {"is_correct": True, "error_type": None, "conclusion_correct": True,
     "explanation": "证明完整，结论正确", "confidence": 0.95},
    expected_is_correct=True,
    expected_error_type=None,
):
    passed += 1

# ==================== Test 7: MATH010 结论正确 + reasoning_error (无证明内容) → 修正为 incomplete ====================
total += 1
if run_test(
    "MATH010: 结论正确 + reasoning_error (无证明内容)",
    inference_no_proof,
    {"is_correct": False, "error_type": "reasoning_error", "conclusion_correct": True,
     "explanation": "推理存在循环论证", "confidence": 0.7},
    expected_is_correct=True,   # Phase 3: 无证明时 reasoning_error 视为误标 → incomplete + true
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 7b: MATH010 结论正确 + reasoning_error (有证明内容) → 保持 is_correct=False ====================
total += 1
if run_test(
    "MATH010: 结论正确 + reasoning_error (有完整证明, 核心逻辑错误)",
    inference_with_proof,
    {"is_correct": False, "error_type": "reasoning_error", "conclusion_correct": True,
     "explanation": "推理存在循环论证", "confidence": 0.7},
    expected_is_correct=False,  # 有证明 + 核心逻辑错误 → 保持判错
    expected_error_type="reasoning_error",
):
    passed += 1

# ==================== Test 8: 计算题结论正确 + reasoning_error → is_correct=True ====================
total += 1
if run_test(
    "计算题: 结论正确 + reasoning_error (非证明题)",
    inference_calc,
    {"is_correct": False, "error_type": "reasoning_error", "conclusion_correct": True,
     "explanation": "推理过程有小瑕疵", "confidence": 0.6},
    expected_is_correct=True,   # 非证明题不应因小推理瑕疵判错
    expected_error_type="reasoning_error",  # error_type 保持
):
    passed += 1

# ==================== Test 9: 计算题结论错误 → is_correct=False ====================
total += 1
if run_test(
    "计算题: 结论错误",
    inference_calc_wrong,
    {"is_correct": False, "error_type": "mathematical_error", "conclusion_correct": False,
     "explanation": "答案应为-1/6", "confidence": 0.9},
    expected_is_correct=False,
    expected_error_type="mathematical_error",
):
    passed += 1

# ==================== Test 10: 结论正确 + formatting_error → is_correct=True ====================
total += 1
if run_test(
    "结论正确 + formatting_error",
    inference_calc,
    {"is_correct": False, "error_type": "formatting_error", "conclusion_correct": True,
     "explanation": "LaTeX格式有误", "confidence": 0.5},
    expected_is_correct=True,
    expected_error_type="formatting_error",
):
    passed += 1

# ==================== Test 11: 结论正确 + incomplete + 有证明 → is_correct=True ====================
total += 1
if run_test(
    "MATH010: 结论正确 + incomplete + 有证明",
    inference_with_proof,
    {"is_correct": False, "error_type": "incomplete", "conclusion_correct": True,
     "explanation": "证明略短", "confidence": 0.6},
    expected_is_correct=True,   # 结论正确即判对
    expected_error_type="incomplete",
):
    passed += 1

# ==================== Test 12: 结论错误 + error_type=None → 补充 mathematical_error ====================
total += 1
if run_test(
    "结论错误 + error_type=None → 补充 mathematical_error",
    inference_calc_wrong,
    {"is_correct": False, "error_type": None, "conclusion_correct": False,
     "explanation": "答案错误", "confidence": 0.9},
    expected_is_correct=False,
    expected_error_type="mathematical_error",
):
    passed += 1


print(f"\n{'='*60}")
print(f"Results: {passed}/{total} passed")
if passed == total:
    print("ALL TESTS PASSED")
else:
    print(f"{total - passed} TESTS FAILED")
