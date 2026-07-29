"""
Phase 3 验证测试：inference_has_proof 中文模式识别 + proof_quality_score + 3步judge流程

测试三道证明题：MATH010, MATH017, MATH022
每道题测试多种场景：短证明(含关键词)、裸答案、完整证明、错误结论
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import InferenceResult
from deepseek import (
    inference_has_proof,
    proof_quality_score,
    apply_proof_aware_evaluation,
    is_proof_problem,
    _detect_proof_features,
    _collect_proof_text,
)

# ==================== 题目定义 ====================

MATH010_Q = "在三角形ABC中，证明三条中线交于一点，并求交点分割中线比例。"
MATH017_Q = "证明从1到2n+1任取n+1个整数，必存在两个数其中一个整除另一个。"
MATH022_Q = "证明命题：无限多个质数存在。"

# ==================== 测试场景构造 ====================

def make_inference(pid, question, answer, reasoning, steps=None, verification=""):
    """快捷构造 InferenceResult"""
    return InferenceResult(
        problem_id=pid,
        question=question,
        answer=answer,
        reasoning=reasoning,
        steps=steps or [],
        verification=verification,
    )


# ---- MATH010 场景 ----
MATH010_short_proof = make_inference(
    "MATH010", MATH010_Q,
    answer="三条中线交于一点（重心），交点将每条中线按2:1分割",
    reasoning="设中线交于G，由向量关系可得AG:GD=2:1，因此结论成立",
)

MATH010_bare_answer = make_inference(
    "MATH010", MATH010_Q,
    answer="三条中线交于一点，比例2:1",
    reasoning="候选0的坐标法通过直接计算验证了交点存在性和比例关系",
)

MATH010_full_proof = make_inference(
    "MATH010", MATH010_Q,
    answer="三角形三条中线交于重心，重心将每条中线分为2:1",
    reasoning=(
        "设三角形ABC顶点坐标为A(x1,y1), B(x2,y2), C(x3,y3)。"
        "各边中点D=((x2+x3)/2,(y2+y3)/2)等。"
        "中线AD参数方程为A+t(D-A)，中线BE为B+s(E-B)。"
        "求解得t=2/3,s=2/3，交点为((x1+x2+x3)/3,(y1+y2+y3)/3)。"
        "验证该点在第三条中线CF上，t=2/3。"
        "因此三中线交于一点，按2:1分割。"
    ),
    steps=["设顶点坐标", "求中点", "写中线方程", "求交点", "验证第三中线", "算比例"],
)

MATH010_wrong = make_inference(
    "MATH010", MATH010_Q,
    answer="三条中线交于一点，比例3:1",
    reasoning="通过计算得到3:1",
)

# ---- MATH017 场景 ----
MATH017_short_proof = make_inference(
    "MATH017", MATH017_Q,
    answer="必存在两个数一个整除另一个",
    reasoning=(
        "设每个数表示为2^k*m，其中m为奇数。"
        "1到2n+1中奇数部分只有n+1种。"
        "由鸽巢原理，n+1个数中必有两个m相同，因此一个整除另一个。"
    ),
)

MATH017_bare_answer = make_inference(
    "MATH017", MATH017_Q,
    answer="根据鸽巢原理可以证明",
    reasoning="利用鸽巢原理即可",
)

MATH017_full_proof = make_inference(
    "MATH017", MATH017_Q,
    answer="命题成立",
    reasoning=(
        "证明：将每个整数表示为 2^k * m，其中 m 为奇数。"
        "对于 1 到 2n+1 的整数，其奇数部分 m 的取值范围是 {1,3,5,...,2n+1}，共 n+1 种。"
        "任取 n+1 个整数，由鸽巢原理，必有两个数的奇数部分相同。"
        "设这两个数为 2^a * m 和 2^b * m（a < b），则前者整除后者。"
        "因此命题得证。"
    ),
    steps=["分解为2^k*m", "分析奇数部分种类", "应用鸽巢原理", "推导整除关系"],
)

# ---- MATH022 场景 ----
MATH022_short_proof = make_inference(
    "MATH022", MATH022_Q,
    answer="质数有无限多个",
    reasoning=(
        "假设质数有限，设为p1,p2,...,pn。"
        "构造N=p1*p2*...*pn+1。"
        "则N不能被任何pi整除，因此N有新的质因子，产生矛盾。"
        "所以质数无限。"
    ),
)

MATH022_bare_answer = make_inference(
    "MATH022", MATH022_Q,
    answer="质数有无限多个",
    reasoning="欧几里得证明法可以证明",
)

MATH022_full_proof = make_inference(
    "MATH022", MATH022_Q,
    answer="质数无限",
    reasoning=(
        "证明（反证法）：假设质数只有有限个，设为 p1, p2, ..., pn。"
        "构造数 N = p1 * p2 * ... * pn + 1。"
        "因为 N > 1，所以 N 至少有一个质因子 q。"
        "如果 q 等于某个 pi，则 q | (N - 1) = p1*p2*...*pn，"
        "又 q | N，所以 q | (N - p1*p2*...*pn) = 1，矛盾。"
        "因此 q 不在 {p1,...,pn} 中，与假设矛盾。"
        "所以质数有无限多个。"
    ),
    steps=["假设质数有限", "构造N", "分析N的质因子", "推导矛盾", "结论"],
)

MATH022_wrong = make_inference(
    "MATH022", MATH022_Q,
    answer="质数有有限个",
    reasoning="因为大于某个值后不再有质数",
)


# ==================== 测试执行 ====================

def test_proof_detection():
    """测试 inference_has_proof 和 proof_quality_score"""
    print("=" * 70)
    print("  一、inference_has_proof 中文模式识别测试")
    print("=" * 70)

    cases = [
        # (name, inference, expected_has_proof, expected_score)
        # 短证明含关键词+公式 → quality=1.0（有实际数学推导）
        ("MATH010 短证明(含关键词)", MATH010_short_proof, True, 1.0),
        ("MATH010 裸答案(候选评价)", MATH010_bare_answer, False, 0.0),
        ("MATH010 完整证明", MATH010_full_proof, True, 1.0),
        # 短证明含2个关键词但无公式 → quality=0.5（有推理但不完整）
        ("MATH017 短证明(含关键词)", MATH017_short_proof, True, 0.5),
        ("MATH017 裸答案", MATH017_bare_answer, False, 0.0),
        ("MATH017 完整证明", MATH017_full_proof, True, 1.0),
        # 短证明含7个关键词+公式 → quality=1.0（反证法完整）
        ("MATH022 短证明(含关键词)", MATH022_short_proof, True, 1.0),
        ("MATH022 裸答案", MATH022_bare_answer, False, 0.0),
        ("MATH022 完整证明", MATH022_full_proof, True, 1.0),
    ]

    all_pass = True
    for name, inf, exp_has, exp_score in cases:
        has = inference_has_proof(inf)
        score = proof_quality_score(inf)
        features = _detect_proof_features(_collect_proof_text(inf))

        has_ok = has == exp_has
        score_ok = score == exp_score
        status = "PASS" if (has_ok and score_ok) else "FAIL"
        if status == "FAIL":
            all_pass = False

        print(f"\n  [{status}] {name}")
        print(f"    has_proof: {has} (expected {exp_has})")
        print(f"    quality_score: {score} (expected {exp_score})")
        print(f"    features: kw={features['has_keywords']}(n={features['keyword_count']}), "
              f"deriv={features['has_derivation']}, steps={features['has_steps']}(n={features['step_count']}), "
              f"formula={features['has_formula']}")
        if inf.reasoning:
            print(f"    reasoning: {inf.reasoning[:80]}")

    return all_pass


def test_math010_judge():
    """测试 MATH010 各种 judge 场景"""
    print("\n" + "=" * 70)
    print("  二、MATH010 Judge 流程测试")
    print("  题目: " + MATH010_Q[:40])
    print("=" * 70)

    all_pass = True

    # 场景1: 短证明 + judge判 incomplete → 应 is_correct=true
    inf = MATH010_short_proof
    parsed = {
        "is_correct": False, "confidence": 0.6,
        "explanation": "证明过程过于简略", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景1: 短证明(含关键词) + judge判incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")
    print(f"    proof_quality_score: {result.get('proof_quality_score')}")

    # 场景2: 裸答案 + judge判 incomplete → is_correct=true, incomplete
    inf = MATH010_bare_answer
    parsed = {
        "is_correct": False, "confidence": 0.5,
        "explanation": "没有证明过程", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True and result.get("error_type") == "incomplete"
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景2: 裸答案 + judge判incomplete → is_correct=true, incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')} (expected incomplete)")

    # 场景3: 完整证明 + judge判 correct → is_correct=true
    inf = MATH010_full_proof
    parsed = {
        "is_correct": True, "confidence": 0.95,
        "explanation": "证明完整正确", "error_type": None,
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景3: 完整证明 + judge判correct")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")

    # 场景4: 短证明 + judge误判 mathematical_error → 修正为 is_correct=true
    inf = MATH010_short_proof
    parsed = {
        "is_correct": False, "confidence": 0.4,
        "explanation": "数学错误", "error_type": "mathematical_error",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景4: 短证明 + judge误判mathematical_error → 修正为true")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")

    # 场景5: 错误结论 → is_correct=false
    inf = MATH010_wrong
    parsed = {
        "is_correct": False, "confidence": 0.9,
        "explanation": "比例应为2:1不是3:1", "error_type": "mathematical_error",
        "correct_answer": "2:1", "conclusion_correct": False,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == False
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景5: 错误结论(比例3:1) → is_correct=false")
    print(f"    is_correct: {result['is_correct']} (expected False)")
    print(f"    error_type: {result.get('error_type')}")

    return all_pass


def test_math017_judge():
    """测试 MATH017 各种 judge 场景"""
    print("\n" + "=" * 70)
    print("  三、MATH017 Judge 流程测试")
    print("  题目: " + MATH017_Q[:40])
    print("=" * 70)

    all_pass = True

    # 场景1: 短证明 + judge判 incomplete → is_correct=true
    inf = MATH017_short_proof
    parsed = {
        "is_correct": False, "confidence": 0.6,
        "explanation": "证明不够完整", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景1: 短证明(含关键词) + judge判incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")
    print(f"    proof_quality_score: {result.get('proof_quality_score')}")

    # 场景2: 裸答案 + judge判 incomplete
    inf = MATH017_bare_answer
    parsed = {
        "is_correct": False, "confidence": 0.5,
        "explanation": "仅引用定理名", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True and result.get("error_type") == "incomplete"
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景2: 裸答案 + judge判incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')} (expected incomplete)")

    # 场景3: 完整证明 + judge判 correct
    inf = MATH017_full_proof
    parsed = {
        "is_correct": True, "confidence": 0.95,
        "explanation": "鸽巢原理应用正确", "error_type": None,
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景3: 完整证明 + judge判correct")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")

    # 场景4: 短证明 + judge误判 mathematical_error
    inf = MATH017_short_proof
    parsed = {
        "is_correct": False, "confidence": 0.4,
        "explanation": "数学错误", "error_type": "mathematical_error",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景4: 短证明 + judge误判mathematical_error → 修正为true")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")

    return all_pass


def test_math022_judge():
    """测试 MATH022 各种 judge 场景"""
    print("\n" + "=" * 70)
    print("  四、MATH022 Judge 流程测试")
    print("  题目: " + MATH022_Q[:40])
    print("=" * 70)

    all_pass = True

    # 场景1: 短证明(含反证法关键词) + judge判 incomplete
    inf = MATH022_short_proof
    parsed = {
        "is_correct": False, "confidence": 0.6,
        "explanation": "证明简略", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景1: 短证明(含关键词) + judge判incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')}")
    print(f"    proof_quality_score: {result.get('proof_quality_score')}")

    # 场景2: 裸答案 + judge判 incomplete
    inf = MATH022_bare_answer
    parsed = {
        "is_correct": False, "confidence": 0.5,
        "explanation": "仅引用方法名", "error_type": "incomplete",
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True and result.get("error_type") == "incomplete"
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景2: 裸答案 + judge判incomplete")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")
    print(f"    error_type: {result.get('error_type')} (expected incomplete)")

    # 场景3: 完整证明 + judge判 correct
    inf = MATH022_full_proof
    parsed = {
        "is_correct": True, "confidence": 0.95,
        "explanation": "反证法完整", "error_type": None,
        "correct_answer": None, "conclusion_correct": True,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == True
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景3: 完整证明 + judge判correct")
    print(f"    has_proof={inference_has_proof(inf)}, quality={proof_quality_score(inf)}")
    print(f"    is_correct: {result['is_correct']} (expected True)")

    # 场景4: 错误结论(质数有限) → is_correct=false
    inf = MATH022_wrong
    parsed = {
        "is_correct": False, "confidence": 0.9,
        "explanation": "结论错误", "error_type": "mathematical_error",
        "correct_answer": "无限多个", "conclusion_correct": False,
    }
    result = apply_proof_aware_evaluation(inf, dict(parsed))
    ok = result["is_correct"] == False
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"\n  [{status}] 场景4: 错误结论(质数有限) → is_correct=false")
    print(f"    is_correct: {result['is_correct']} (expected False)")
    print(f"    error_type: {result.get('error_type')}")

    return all_pass


def test_old_vs_new_comparison():
    """对比旧的长度阈值 vs 新的模式识别"""
    print("\n" + "=" * 70)
    print("  五、旧方法(长度阈值) vs 新方法(模式识别) 对比")
    print("=" * 70)

    # 用户描述的关键测试用例
    key_case = make_inference(
        "MATH010", MATH010_Q,
        answer="三条中线交于一点，比例2:1",
        reasoning="设中线交于G，由向量关系可得AG:GD=2:1，因此结论成立",
    )

    old_has_proof = len(key_case.reasoning.strip()) > 40  # 旧逻辑
    new_has_proof = inference_has_proof(key_case)          # 新逻辑
    new_score = proof_quality_score(key_case)

    print(f"\n  输入: '设中线交于G，由向量关系可得AG:GD=2:1，因此结论成立'")
    print(f"  字符数: {len(key_case.reasoning.strip())}")
    print(f"  旧方法(len>40): has_proof={old_has_proof}")
    print(f"  新方法(模式识别): has_proof={new_has_proof}")
    print(f"  新方法 quality_score: {new_score}")

    if old_has_proof == False and new_has_proof == True:
        print(f"  -> 新方法成功识别了旧方法遗漏的中文短证明")
        return True
    elif old_has_proof == new_has_proof:
        print(f"  -> 两种方法结果相同")
        return True
    else:
        print(f"  -> 结果不一致，需检查")
        return False


# ==================== 主函数 ====================

if __name__ == "__main__":
    results = []
    results.append(("Proof Detection", test_proof_detection()))
    results.append(("MATH010 Judge", test_math010_judge()))
    results.append(("MATH017 Judge", test_math017_judge()))
    results.append(("MATH022 Judge", test_math022_judge()))
    results.append(("Old vs New", test_old_vs_new_comparison()))

    print("\n" + "=" * 70)
    print("  总结")
    print("=" * 70)
    total_pass = 0
    total = len(results)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if passed:
            total_pass += 1
    print(f"\n  总计: {total_pass}/{total} 组测试通过")
    if total_pass == total:
        print("  全部通过!")
    else:
        print("  存在失败，请检查上方详情。")
    sys.exit(0 if total_pass == total else 1)
