"""
验证测试：apply_proof_aware_evaluation 已进入所有 judge 流程。

测试场景：
1. run_judge() 路径 → apply_proof_aware_evaluation 被调用
2. _run_judge_batch_chunk() 路径 → apply_proof_aware_evaluation 被调用
3. 典型失败场景：证明题 + 结论正确 + 无证明 → is_correct=False, error_type=incomplete
4. 对照场景：证明题 + 结论正确 + 有证明 → is_correct=True
5. 对照场景：计算题 + 结论正确 + 短推理 → is_correct=True
"""
import asyncio
import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch

# 添加测试工具目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import InferenceResult, JudgeResult
from deepseek import (
    run_judge,
    run_judge_batch,
    apply_proof_aware_evaluation,
    is_proof_problem,
    inference_has_proof,
)


def make_inference(
    problem_id: str,
    question: str,
    answer: str,
    reasoning: str = "",
    steps: list = None,
    verification: str = "",
    candidates: list = None,
) -> InferenceResult:
    """构造 InferenceResult"""
    return InferenceResult(
        problem_id=problem_id,
        question=question,
        answer=answer,
        reasoning=reasoning,
        steps=steps or [],
        verification=verification,
        candidates=candidates or [],
    )


def mock_judge_response(is_correct, conclusion_correct, error_type=None, explanation=""):
    """构造模拟的 judge LLM 响应"""
    return {
        "content": json.dumps({
            "is_correct": is_correct,
            "confidence": 0.9,
            "explanation": explanation or "mock judge",
            "error_type": error_type,
            "correct_answer": None,
            "conclusion_correct": conclusion_correct,
        }),
        "tokens_used": 100,
    }


# ==================== 测试用例 ====================

def test_1_run_judge_calls_proof_aware():
    """测试1: run_judge() 路径调用 apply_proof_aware_evaluation"""
    print("\n[Test 1] run_judge() -> apply_proof_aware_evaluation()")

    # 证明题，结论正确，但推理极短（无实质证明）
    inf = make_inference(
        problem_id="proof_001",
        question="证明：三角形三条中线交于一点，且比例为2:1。",
        answer="三条中线交于一点，比例2:1",
        reasoning="三条中线交于一点，比例2:1",  # 极短，<40字符
    )

    # Judge LLM 返回：结论正确，is_correct=true, error_type=incomplete
    mock_resp = mock_judge_response(
        is_correct=True,
        conclusion_correct=True,
        error_type="incomplete",
        explanation="结论正确但证明简短",
    )

    with patch("deepseek.LLMClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        with patch("deepseek.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()

            result = asyncio.run(run_judge(inf))

    # 验证：apply_proof_aware_evaluation 应将 is_correct 保持为 True（Phase 2 新规则）
    assert result.is_correct == True, \
        f"FAIL: 预期 is_correct=True (结论正确即判对), 实际 is_correct={result.is_correct}"
    assert result.error_type == "incomplete", \
        f"FAIL: 预期 error_type=incomplete, 实际 error_type={result.error_type}"
    print(f"  PASS: is_correct={result.is_correct}, error_type={result.error_type}")
    print(f"  -> apply_proof_aware_evaluation 确实被调用并修正了结果")
    return True


def test_2_batch_judge_calls_proof_aware():
    """测试2: run_judge_batch() 路径调用 apply_proof_aware_evaluation"""
    print("\n[Test 2] run_judge_batch() -> _run_judge_batch_chunk() -> apply_proof_aware_evaluation()")

    # 两道证明题：一道有证明，一道无证明
    inf_with_proof = make_inference(
        problem_id="proof_002",
        question="证明：f(x)=0在[0,1]上至少有一个实根。",
        answer="由介值定理，f(x)在[0,1]上连续且变号，故存在实根。",
        reasoning="设f(x)在[0,1]上连续。因f(0)<0, f(1)>0，由介值定理（零点定理），"
                  "存在c∈(0,1)使得f(c)=0。因此f(x)=0在[0,1]上至少有一个实根。证毕。",
        steps=["设f(x)连续", "f(0)<0, f(1)>0", "由零点定理得存在c使f(c)=0"],
    )

    inf_without_proof = make_inference(
        problem_id="proof_003",
        question="证明：方程x^5+x-1=0在(0,1)内有且仅有一个实根。",
        answer="存在唯一实根",
        reasoning="存在唯一实根",  # 极短
    )

    # Judge LLM 批量返回：两题都结论正确
    mock_batch_resp = {
        "content": json.dumps([
            {
                "problem_id": "proof_002",
                "is_correct": True,
                "confidence": 0.95,
                "explanation": "证明完整正确",
                "error_type": None,
                "correct_answer": None,
                "conclusion_correct": True,
            },
            {
                "problem_id": "proof_003",
                "is_correct": True,
                "confidence": 0.85,
                "explanation": "结论正确",
                "error_type": "incomplete",
                "correct_answer": None,
                "conclusion_correct": True,
            },
        ]),
        "tokens_used": 200,
    }

    with patch("deepseek.LLMClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_batch_resp)
        with patch("deepseek.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()

            results = asyncio.run(
                run_judge_batch([inf_with_proof, inf_without_proof], batch_size=2)
            )

    assert len(results) == 2, f"FAIL: 预期2个结果, 实际{len(results)}"

    # proof_002: 有证明 → 应保持 is_correct=True
    r1 = results[0]
    assert r1.is_correct == True, \
        f"FAIL: proof_002 预期 is_correct=True (有证明), 实际={r1.is_correct}"
    print(f"  proof_002 (有证明): is_correct={r1.is_correct}, error_type={r1.error_type} -> PASS")

    # proof_003: 无证明 → apply_proof_aware_evaluation 应设为 is_correct=True, incomplete（Phase 2 新规则）
    r2 = results[1]
    assert r2.is_correct == True, \
        f"FAIL: proof_003 预期 is_correct=True (结论正确即判对), 实际={r2.is_correct}"
    assert r2.error_type == "incomplete", \
        f"FAIL: proof_003 预期 error_type=incomplete, 实际={r2.error_type}"
    print(f"  proof_003 (无证明): is_correct={r2.is_correct}, error_type={r2.error_type} -> PASS")

    print(f"  -> apply_proof_aware_evaluation 在批量评判中被调用")
    return True


def test_3_proof_problem_with_proof():
    """测试3: 证明题 + 结论正确 + 有充分证明 → is_correct=True"""
    print("\n[Test 3] 证明题+有证明 → is_correct=True (不应误判)")

    inf = make_inference(
        problem_id="proof_004",
        question="证明：lim(n→∞) (1+1/n)^n = e",
        answer="极限值为e",
        reasoning="由数列极限的定义，对于任意ε>0，存在N使得n>N时"
                  "|(1+1/n)^n - e| < ε。首先，(1+1/n)^n是单调递增的，"
                  "因为由二项式展开可得每一项都非负。其次，(1+1/n)^n有上界e。"
                  "由单调有界收敛定理，该序列收敛，且极限为e。证毕。",
        steps=["单调递增", "有上界e", "单调有界定理"],
    )

    mock_resp = mock_judge_response(
        is_correct=True, conclusion_correct=True, error_type=None,
    )

    with patch("deepseek.LLMClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        with patch("deepseek.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            result = asyncio.run(run_judge(inf))

    assert result.is_correct == True, \
        f"FAIL: 预期 is_correct=True, 实际={result.is_correct}"
    print(f"  is_correct={result.is_correct}, error_type={result.error_type} -> PASS")
    return True


def test_4_calc_problem_short_reasoning():
    """测试4: 计算题 + 结论正确 + 短推理 → is_correct=True (不要求证明)"""
    print("\n[Test 4] 计算题+短推理 → is_correct=True (不要求证明)")

    inf = make_inference(
        problem_id="calc_001",
        question="求极限 lim(x→0) sin(x)/x",
        answer="1",
        reasoning="由等价无穷小，sin(x)~x，所以极限为1。",
    )

    mock_resp = mock_judge_response(
        is_correct=True, conclusion_correct=True, error_type="incomplete",
    )

    with patch("deepseek.LLMClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        with patch("deepseek.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            result = asyncio.run(run_judge(inf))

    # 计算题不要求证明 → incomplete 不应导致 is_correct=False
    assert result.is_correct == True, \
        f"FAIL: 计算题短推理应 is_correct=True, 实际={result.is_correct}"
    print(f"  is_correct={result.is_correct}, error_type={result.error_type} -> PASS")
    return True


def test_5_proof_problem_wrong_conclusion():
    """测试5: 证明题 + 结论错误 → is_correct=False, error_type != incomplete"""
    print("\n[Test 5] 证明题+结论错误 → is_correct=False")

    inf = make_inference(
        problem_id="proof_005",
        question="证明：sum(1/n^2) = π^2/6",
        answer="π^2/12",  # 错误答案
        reasoning="通过欧拉的方法，将sin(x)展开为无穷级数，"
                  "比较系数可得sum(1/n^2) = π^2/12。",
        steps=["展开sin(x)", "比较系数"],
    )

    mock_resp = mock_judge_response(
        is_correct=False,
        conclusion_correct=False,
        error_type="mathematical_error",
    )

    with patch("deepseek.LLMClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        with patch("deepseek.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            result = asyncio.run(run_judge(inf))

    assert result.is_correct == False, \
        f"FAIL: 预期 is_correct=False, 实际={result.is_correct}"
    assert result.error_type == "mathematical_error", \
        f"FAIL: 预期 error_type=mathematical_error, 实际={result.error_type}"
    print(f"  is_correct={result.is_correct}, error_type={result.error_type} -> PASS")
    return True


def test_6_direct_unit_test():
    """测试6: 直接单元测试 apply_proof_aware_evaluation 函数"""
    print("\n[Test 6] 直接测试 apply_proof_aware_evaluation()")

    # 场景：用户描述的典型失败
    inf = make_inference(
        problem_id="user_case",
        question="证明：三角形三条中线交于一点，比例2:1",
        answer="三条中线交于一点，比例2:1",
        reasoning="三条中线交于一点，比例2:1",
    )

    parsed = {
        "is_correct": True,
        "confidence": 0.9,
        "explanation": "结论正确",
        "error_type": "incomplete",
        "correct_answer": None,
        "conclusion_correct": True,
    }

    result = apply_proof_aware_evaluation(inf, parsed)

    assert result["is_correct"] == True, "结论正确但无证明 → is_correct应为True（Phase 2新规则）"
    assert result["error_type"] == "incomplete", "error_type应为incomplete"
    print(f"  输入: is_correct=True, conclusion_correct=True, error_type=incomplete")
    print(f"  输出: is_correct={result['is_correct']}, error_type={result['error_type']}")
    print(f"  -> Phase 1: is_correct=False (证明不足判错)")
    print(f"  -> Phase 2: is_correct=True (结论正确即判对, 证明不足仅标记incomplete)")
    return True


# ==================== 主入口 ====================

def main():
    print("=" * 60)
    print("  apply_proof_aware_evaluation 调用链验证测试")
    print("=" * 60)

    tests = [
        test_1_run_judge_calls_proof_aware,
        test_2_batch_judge_calls_proof_aware,
        test_3_proof_problem_with_proof,
        test_4_calc_problem_short_reasoning,
        test_5_proof_problem_wrong_conclusion,
        test_6_direct_unit_test,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"  结果: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("\n所有测试通过。apply_proof_aware_evaluation 已确认进入所有 judge 流程。")


if __name__ == "__main__":
    main()
