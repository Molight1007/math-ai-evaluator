"""
Phase 4 验证测试：Solution Verification Score

验证内容：
1. parser 是否正常解析 verification_score 和 proof_quality_score
2. candidate 排序是否使用 verification_score（新公式）
3. 构造三个 candidate 测试选择结果
4. 兼容旧格式（模型未返回新字段时自动计算）

Phase 4.1 新增：
5. reference_answer 匹配对 verification_score 的影响
6. 矛盾检测
7. 题目条件满足检查
8. proof_required 动态权重
9. 选中候选二次验证

Phase 5 新增：
10. verification_confidence 字段解析
11. 高verification低confidence的candidate不被过度惩罚
12. 低verification高confidence的candidate受到惩罚
13. proof和answer冲突的disagreement检测
14. reference缺失时verification_confidence的计算
15. vc < 0.4 时不淘汰candidate
"""
import json
import sys
import os

# 确保能 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intern_s1 import (
    parse_multi_candidate_response,
    score_candidate,
    select_best_candidate_index,
    _compute_verification_score,
    _compute_candidate_pq_score,
    _ensure_candidate_scores,
    _verify_selected_candidate,
    _check_answer_match,
    _check_condition_satisfaction,
    _check_contradictions,
    _detect_verification_disagreement,
    _compute_verification_confidence,
    is_proof_problem,
)
from models import InferenceResult


def _make_candidate_json(candidates_data, selected_index=0, question=""):
    """构造完整的多候选 JSON 字符串。"""
    obj = {
        "candidates": candidates_data,
        "selected_index": selected_index,
        "selection_reasoning": "test selection",
        "final_answer": candidates_data[selected_index].get("final_answer", ""),
    }
    return json.dumps(obj, ensure_ascii=False)


# ==================== Test 1: Parser 解析新字段 ====================

def test_parser_new_fields():
    """模型返回了 verification_score 和 proof_quality_score，parser 应正确解析。"""
    print("\n=== Test 1: Parser 解析新字段 ===")

    question = "计算 2 + 3 的值。"
    candidates_data = [
        {
            "index": 0,
            "final_answer": "5",
            "proof": "2 + 3 = 5",
            "reasoning": "直接相加即可",
            "steps": ["2 + 3 = 5"],
            "confidence": 0.9,
            "verification_score": 0.85,
            "proof_quality_score": 0.5,
            "strength": "计算简单",
            "weakness": "",
        },
        {
            "index": 1,
            "final_answer": "5",
            "proof": "因为 2 + 3 = 5",
            "reasoning": "加法运算",
            "steps": ["2 + 3 = 5"],
            "confidence": 0.7,
            "verification_score": 0.90,
            "proof_quality_score": 0.5,
            "strength": "",
            "weakness": "",
        },
        {
            "index": 2,
            "final_answer": "5",
            "proof": "",
            "reasoning": "5",
            "steps": [],
            "confidence": 0.5,
            "verification_score": 0.30,
            "proof_quality_score": 0.0,
            "strength": "",
            "weakness": "无过程",
        },
    ]

    raw = _make_candidate_json(candidates_data, selected_index=0, question=question)
    parsed = parse_multi_candidate_response(raw, question=question)

    assert parsed.get("candidates") is not None, "candidates 不应为 None"
    cands = parsed["candidates"]
    assert len(cands) == 3, f"应有3个candidate，实际{len(cands)}"

    # 验证字段被正确解析
    c0 = cands[0]
    assert c0["verification_score"] == 0.85, f"C0 verification_score 应为0.85，实际{c0['verification_score']}"
    assert c0["proof_quality_score"] == 0.5, f"C0 proof_quality_score 应为0.5，实际{c0['proof_quality_score']}"

    c2 = cands[2]
    assert c2["verification_score"] == 0.30, f"C2 verification_score 应为0.30，实际{c2['verification_score']}"
    assert c2["proof_quality_score"] == 0.0, f"C2 proof_quality_score 应为0.0，实际{c2['proof_quality_score']}"

    # Phase 5: 验证 verification_confidence 被解析或计算
    for c in cands:
        assert "verification_confidence" in c, \
            f"C{c['index']} 应包含 verification_confidence"
        assert 0.0 <= c["verification_confidence"] <= 1.0, \
            f"C{c['index']} verification_confidence 应在 0-1 范围"

    # 验证顶层返回值
    sel = parsed["selected_index"]
    selected = next(c for c in cands if c["index"] == sel)
    assert parsed["verification_score"] == selected["verification_score"], \
        f"顶层 verification_score 应等于选中候选的值"
    assert parsed["proof_quality_score"] == selected["proof_quality_score"], \
        f"顶层 proof_quality_score 应等于选中候选的值"
    assert "verification_confidence" in parsed, "顶层应包含 verification_confidence"
    assert "verification_warning" in parsed, "顶层应包含 verification_warning"

    print(f"  [PASS] 3个candidate的新字段均正确解析")
    print(f"  [PASS] verification_confidence 已计算 (C0={cands[0]['verification_confidence']:.2f})")
    print(f"  [PASS] 顶层 verification_score={parsed['verification_score']}, proof_quality_score={parsed['proof_quality_score']}")
    print(f"  [PASS] selected_index={sel}")
    return True


# ==================== Test 2: 兼容旧格式 ====================

def test_old_format_compatibility():
    """模型未返回 verification_score / proof_quality_score，parser 应自动计算。"""
    print("\n=== Test 2: 兼容旧格式（自动计算分数） ===")

    question = "证明：三角形三条中线交于一点，且该点分每条中线为 2:1。"
    candidates_data = [
        {
            "index": 0,
            "final_answer": "三条中线交于重心G，AG:GD=2:1",
            "proof": (
                "设三角形ABC，D、E、F分别为BC、CA、AB的中点。"
                "设中线AD和BE交于G。因为D是BC中点，E是CA中点，"
                "所以由向量关系：AG = (2/3)AD，因此 AG:GD = 2:1。"
                "同理可证BG:GE = 2:1，CG:GF = 2:1。"
                "因此三条中线交于同一点G，且G分每条中线为2:1。"
            ),
            "reasoning": "利用向量法证明中线的交点性质",
            "steps": ["设中线AD和BE交于G", "由向量关系得AG:GD=2:1", "同理其他中线也过G"],
            "confidence": 0.8,
        },
        {
            "index": 1,
            "final_answer": "三条中线交于一点，比例2:1",
            "proof": "",
            "reasoning": "由重心定理可知",
            "steps": [],
            "confidence": 0.6,
        },
        {
            "index": 2,
            "final_answer": "结论成立",
            "proof": "利用向量法证明",
            "reasoning": "",
            "steps": [],
            "confidence": 0.4,
        },
    ]

    raw = _make_candidate_json(candidates_data, selected_index=0, question=question)
    parsed = parse_multi_candidate_response(raw, question=question)

    cands = parsed["candidates"]
    assert len(cands) == 3

    # Candidate 0 应有高 verification_score（完整证明）
    c0 = cands[0]
    assert c0["verification_score"] > 0.5, \
        f"C0 有完整证明，verification_score 应>0.5，实际{c0['verification_score']:.2f}"
    assert c0["proof_quality_score"] > 0.0, \
        f"C0 有证明内容，proof_quality_score 应>0.0，实际{c0['proof_quality_score']}"

    # Candidate 1 应有较低 verification_score（仅一句话）
    c1 = cands[1]
    assert c1["verification_score"] < c0["verification_score"], \
        f"C1 无证明，verification_score({c1['verification_score']:.2f}) 应低于 C0({c0['verification_score']:.2f})"

    # Candidate 2 应有最低 verification_score
    c2 = cands[2]
    assert c2["proof_quality_score"] <= 0.5, \
        f"C2 仅'利用向量法证明'，proof_quality_score 应<=0.5，实际{c2['proof_quality_score']}"

    print(f"  [PASS] 旧格式candidate自动计算了新字段")
    print(f"  C0: verification={c0['verification_score']:.2f}, pq={c0['proof_quality_score']:.2f}")
    print(f"  C1: verification={c1['verification_score']:.2f}, pq={c1['proof_quality_score']:.2f}")
    print(f"  C2: verification={c2['verification_score']:.2f}, pq={c2['proof_quality_score']:.2f}")
    return True


# ==================== Test 3: candidate 排序使用 verification_score ====================

def test_candidate_selection_uses_verification():
    """
    构造3个candidate，验证新公式（含verification_score）改变了选择结果。

    Phase 5: score_candidate = base_score * verification_confidence
    为聚焦于 verification_score 的排序效果，所有 candidate 设置 vc=1.0。

    Candidate 0: 高confidence(0.9) + 低verification(0.2) + 低pq(0.0)
      → base = 0.5*0.9 + 0.5*0.2 = 0.55, final = 0.55 * 1.0 = 0.55

    Candidate 1: 中confidence(0.5) + 高verification(0.9) + 高pq(1.0)
      → base = 0.5*0.5 + 0.5*0.9 = 0.70, final = 0.70 * 1.0 = 0.70  ← 最高

    Candidate 2: 高confidence(0.8) + 中verification(0.5) + 中pq(0.5)
      → base = 0.5*0.8 + 0.5*0.5 = 0.65, final = 0.65 * 1.0 = 0.65
    """
    print("\n=== Test 3: candidate 排序使用 verification_score ===")

    question = "计算 f(x) = x^2 + 2x 在 x=3 时的值。"
    candidates = [
        {
            "index": 0,
            "final_answer": "15",
            "proof": "",
            "reasoning": "f(3) = 15",
            "steps": [],
            "confidence": 0.9,
            "verification_score": 0.2,
            "verification_confidence": 1.0,
            "proof_quality_score": 0.0,
        },
        {
            "index": 1,
            "final_answer": "15",
            "proof": "f(3) = 3^2 + 2*3 = 9 + 6 = 15",
            "reasoning": "代入x=3，计算得f(3)=15",
            "steps": ["代入x=3: f(3) = 3^2 + 2*3", "计算: 9 + 6 = 15"],
            "confidence": 0.5,
            "verification_score": 0.9,
            "verification_confidence": 1.0,
            "proof_quality_score": 1.0,
        },
        {
            "index": 2,
            "final_answer": "15",
            "proof": "f(3) = 9 + 6 = 15",
            "reasoning": "代入计算",
            "steps": ["f(3) = 9 + 6 = 15"],
            "confidence": 0.8,
            "verification_score": 0.5,
            "verification_confidence": 1.0,
            "proof_quality_score": 0.5,
        },
    ]

    # 计算各candidate的分数
    proof_required = is_proof_problem(question)
    assert not proof_required, "计算题不应是proof题"

    scores = []
    for c in candidates:
        s = score_candidate(c, proof_required)
        scores.append(s)
        print(f"  Candidate {c['index']}: score={s:.4f} "
              f"(conf={c['confidence']}, vs={c['verification_score']}, pq={c['proof_quality_score']})")

    # 验证新公式计算正确（非证明题: 0.5*conf + 0.5*vs）
    expected_scores = [0.55, 0.70, 0.65]
    for i, (actual, expected) in enumerate(zip(scores, expected_scores)):
        assert abs(actual - expected) < 0.001, \
            f"Candidate {i} score 应为 {expected}, 实际 {actual:.4f}"

    # 验证选择结果
    selected = select_best_candidate_index(candidates, model_selected=0, proof_required=proof_required)
    assert selected == 1, \
        f"应选择 Candidate 1（verification_score最高），实际选择了 {selected}"

    print(f"  [PASS] 新公式分数计算正确: {[f'{s:.2f}' for s in scores]}")
    print(f"  [PASS] 选择了 Candidate {selected}（高verification_score），而非 Candidate 0（高confidence）")
    return True


# ==================== Test 4: 证明题的 verification_score ====================

def test_proof_problem_verification():
    """证明题的 verification_score 应反映证明结构完整性。"""
    print("\n=== Test 4: 证明题 verification_score ===")

    question = "证明：对任意正整数 n，1+2+...+n = n(n+1)/2。"

    # Candidate 0: 完整数学归纳法证明
    c_full = {
        "final_answer": "1+2+...+n = n(n+1)/2 成立",
        "proof": (
            "用数学归纳法证明。设P(n): 1+2+...+n = n(n+1)/2。"
            "基础步：当n=1时，左边=1，右边=1*(1+1)/2=1，因此P(1)成立。"
            "归纳步：假设P(k)成立，即1+2+...+k=k(k+1)/2。"
            "则1+2+...+k+(k+1) = k(k+1)/2 + (k+1) = (k+1)(k+2)/2。"
            "因此P(k+1)成立。由数学归纳法，P(n)对所有正整数n成立。"
        ),
        "reasoning": "数学归纳法",
        "steps": ["基础步：n=1时成立", "归纳步：假设P(k)成立，证明P(k+1)", "由归纳法得证"],
        "confidence": 0.95,
    }

    # Candidate 1: 仅结论无证明
    c_bare = {
        "final_answer": "1+2+...+n = n(n+1)/2",
        "proof": "",
        "reasoning": "这是高斯求和公式",
        "steps": [],
        "confidence": 0.7,
    }

    # Candidate 2: 口号式"证明"
    c_slogan = {
        "final_answer": "结论成立",
        "proof": "利用数学归纳法即可证明",
        "reasoning": "",
        "steps": [],
        "confidence": 0.5,
    }

    proof_required = is_proof_problem(question)
    assert proof_required, "该题应是proof题"

    vs_full = _compute_verification_score(c_full, question, proof_required)
    vs_bare = _compute_verification_score(c_bare, question, proof_required)
    vs_slogan = _compute_verification_score(c_slogan, question, proof_required)

    pq_full = _compute_candidate_pq_score(c_full, proof_required)
    pq_bare = _compute_candidate_pq_score(c_bare, proof_required)
    pq_slogan = _compute_candidate_pq_score(c_slogan, proof_required)

    print(f"  C_full:  verification={vs_full:.2f}, pq={pq_full:.2f}")
    print(f"  C_bare:  verification={vs_bare:.2f}, pq={pq_bare:.2f}")
    print(f"  C_slogan: verification={vs_slogan:.2f}, pq={pq_slogan:.2f}")

    assert vs_full > vs_bare, \
        f"完整证明的verification_score({vs_full:.2f})应高于无证明({vs_bare:.2f})"
    assert vs_full > vs_slogan, \
        f"完整证明的verification_score({vs_full:.2f})应高于口号式({vs_slogan:.2f})"
    assert pq_full > pq_bare, \
        f"完整证明的pq({pq_full:.2f})应高于无证明({pq_bare:.2f})"
    assert pq_bare == 0.0, \
        f"无证明的pq应为0.0，实际{pq_bare:.2f}"
    assert pq_slogan <= 0.5, \
        f"口号式证明的pq应<=0.5，实际{pq_slogan:.2f}"

    # 验证完整证明的最终选择
    candidates = [
        {**c_full, "index": 0, "verification_score": vs_full, "proof_quality_score": pq_full},
        {**c_bare, "index": 1, "verification_score": vs_bare, "proof_quality_score": pq_bare},
        {**c_slogan, "index": 2, "verification_score": vs_slogan, "proof_quality_score": pq_slogan},
    ]

    selected = select_best_candidate_index(candidates, model_selected=2, proof_required=proof_required)
    assert selected == 0, \
        f"应选择完整证明(C0)，实际选择了{selected}"

    print(f"  [PASS] 完整证明的 verification_score 和 pq 均最高")
    print(f"  [PASS] 选择了 Candidate 0（完整归纳法证明）")
    return True


# ==================== Test 5: _ensure_candidate_scores 兼容性 ====================

def test_ensure_candidate_scores():
    """测试 _ensure_candidate_scores 对有/无字段的处理。"""
    print("\n=== Test 5: _ensure_candidate_scores 兼容性 ===")

    question = "求方程 x^2 - 4 = 0 的解。"
    proof_required = is_proof_problem(question)

    # Case 1: 模型返回了新字段
    c_with = {
        "final_answer": "x = 2 或 x = -2",
        "proof": "x^2 = 4，因此 x = 2 或 x = -2",
        "reasoning": "",
        "steps": [],
        "confidence": 0.9,
        "verification_score": 0.8,
        "proof_quality_score": 0.5,
    }
    result_with = _ensure_candidate_scores(c_with, question, proof_required)
    assert result_with["verification_score"] == 0.8, "应保留模型返回的verification_score"
    assert result_with["proof_quality_score"] == 0.5, "应保留模型返回的proof_quality_score"
    assert "verification_confidence" in result_with, "应包含 verification_confidence"
    assert 0.0 <= result_with["verification_confidence"] <= 1.0

    # Case 2: 模型未返回新字段
    c_without = {
        "final_answer": "x = 2 或 x = -2",
        "proof": "x^2 = 4，因此 x = 2 或 x = -2",
        "reasoning": "",
        "steps": ["x^2 - 4 = 0", "x^2 = 4", "x = 2 或 x = -2"],
        "confidence": 0.9,
    }
    result_without = _ensure_candidate_scores(c_without, question, proof_required)
    assert "verification_score" in result_without, "应自动计算 verification_score"
    assert "proof_quality_score" in result_without, "应自动计算 proof_quality_score"
    assert "verification_confidence" in result_without, "应自动计算 verification_confidence"
    assert 0.0 <= result_without["verification_score"] <= 1.0, "verification_score 应在 0-1 范围"
    assert 0.0 <= result_without["proof_quality_score"] <= 1.0, "proof_quality_score 应在 0-1 范围"
    assert 0.0 <= result_without["verification_confidence"] <= 1.0, "verification_confidence 应在 0-1 范围"

    # Case 3: 模型返回了无效值
    c_invalid = {
        "final_answer": "x = 2",
        "proof": "",
        "reasoning": "",
        "steps": [],
        "confidence": 0.5,
        "verification_score": "invalid",
        "proof_quality_score": None,
    }
    result_invalid = _ensure_candidate_scores(c_invalid, question, proof_required)
    assert isinstance(result_invalid["verification_score"], float), "无效verification_score应被计算替换"
    assert isinstance(result_invalid["proof_quality_score"], float), "无效proof_quality_score应被计算替换"
    assert isinstance(result_invalid["verification_confidence"], float), "无效verification_confidence应被计算替换"
    assert 0.0 <= result_invalid["verification_score"] <= 1.0
    assert 0.0 <= result_invalid["proof_quality_score"] <= 1.0
    assert 0.0 <= result_invalid["verification_confidence"] <= 1.0

    print(f"  [PASS] 模型返回新字段时直接使用")
    print(f"  [PASS] 模型未返回新字段时自动计算")
    print(f"  [PASS] 模型返回无效值时回退计算")
    return True


# ==================== Test 6: InferenceResult 包含新字段 ====================

def test_inference_result_fields():
    """验证 InferenceResult 新增字段正常工作。"""
    print("\n=== Test 6: InferenceResult 新字段 ===")

    result = InferenceResult(
        problem_id="TEST001",
        question="test",
        answer="42",
        verification_score=0.75,
        proof_quality_score=0.6,
    )
    assert result.verification_score == 0.75, f"verification_score 应为0.75，实际{result.verification_score}"
    assert result.proof_quality_score == 0.6, f"proof_quality_score 应为0.6，实际{result.proof_quality_score}"

    # 验证默认值
    default_result = InferenceResult(problem_id="TEST002", question="test")
    assert default_result.verification_score == 0.5, f"默认 verification_score 应为0.5"
    assert default_result.proof_quality_score == 0.0, f"默认 proof_quality_score 应为0.0"

    print(f"  [PASS] InferenceResult 新字段赋值和默认值均正确")
    return True


# ==================== Test 7: 端到端 parser 流程 ====================

def test_end_to_end_parser():
    """完整 JSON → parser → 选择 端到端测试。"""
    print("\n=== Test 7: 端到端 parser 流程 ===")

    question = "证明：若 a | b 且 b | c，则 a | c。"
    raw_json = json.dumps({
        "candidates": [
            {
                "index": 0,
                "final_answer": "a | c 成立",
                "proof": (
                    "因为 a | b，所以存在整数 k1 使得 b = k1*a。"
                    "因为 b | c，所以存在整数 k2 使得 c = k2*b。"
                    "代入得 c = k2*(k1*a) = (k1*k2)*a。"
                    "令 k = k1*k2，则 c = k*a，因此 a | c。"
                ),
                "reasoning": "利用整除定义和代换",
                "steps": ["由 a|b 得 b=k1*a", "由 b|c 得 c=k2*b", "代入得 c=(k1*k2)*a", "因此 a|c"],
                "confidence": 0.85,
            },
            {
                "index": 1,
                "final_answer": "a | c",
                "proof": "根据传递性可知",
                "reasoning": "",
                "steps": [],
                "confidence": 0.6,
            },
            {
                "index": 2,
                "final_answer": "结论成立",
                "proof": "",
                "reasoning": "显然",
                "steps": [],
                "confidence": 0.3,
            },
        ],
        "selected_index": 2,  # 模型选了最差的
        "selection_reasoning": "模型选择",
        "final_answer": "结论成立",
    }, ensure_ascii=False)

    parsed = parse_multi_candidate_response(raw_json, question=question)

    cands = parsed["candidates"]
    print(f"  Candidates: {len(cands)}")
    for c in cands:
        s = score_candidate(c, is_proof_problem(question))
        print(f"    C{c['index']}: confidence={c['confidence']:.2f}, "
              f"vs={c['verification_score']:.2f}, pq={c['proof_quality_score']:.2f}, "
              f"score={s:.4f}")

    # 模型选了C2(最差)，但服务端应重选C0(最好)
    assert parsed["selected_index"] == 0, \
        f"服务端应选择C0（最好证明），实际选择了{parsed['selected_index']}"
    assert parsed["verification_score"] > 0.5, \
        f"选中候选的verification_score应>0.5"
    assert parsed["proof_quality_score"] > 0.0, \
        f"选中候选的proof_quality_score应>0.0"

    print(f"  [PASS] 服务端覆盖了模型的错误选择（C2→C0）")
    print(f"  [PASS] 选中候选: verification={parsed['verification_score']:.2f}, "
          f"pq={parsed['proof_quality_score']:.2f}")
    return True


# ==================== Phase 4.1 新增测试 ====================

# ==================== Test 8: reference_answer 匹配 ====================

def test_reference_answer_matching():
    """reference_answer 匹配应影响 verification_score。"""
    print("\n=== Test 8: reference_answer 匹配 ===")

    question = "求方程 x^2 - 5x + 6 = 0 的解。"
    proof_required = is_proof_problem(question)

    # 答案与参考答案匹配
    c_match = {
        "final_answer": "x = 2 或 x = 3",
        "proof": "x^2 - 5x + 6 = 0，因式分解得 (x-2)(x-3) = 0",
        "reasoning": "因式分解",
        "steps": ["x^2 - 5x + 6 = 0", "(x-2)(x-3) = 0", "x=2 或 x=3"],
        "confidence": 0.8,
    }

    # 答案与参考答案不匹配
    c_mismatch = {
        "final_answer": "x = 1 或 x = 6",
        "proof": "x^2 - 5x + 6 = 0，计算得 x=1 或 x=6",
        "reasoning": "代入求解",
        "steps": ["x^2 - 5x + 6 = 0", "x=1 或 x=6"],
        "confidence": 0.8,
    }

    reference_answer = "x = 2 或 x = 3"

    vs_with_ref_match = _compute_verification_score(c_match, question, proof_required, reference_answer)
    vs_with_ref_mismatch = _compute_verification_score(c_mismatch, question, proof_required, reference_answer)
    vs_without_ref = _compute_verification_score(c_match, question, proof_required, None)

    print(f"  匹配+ref:   vs={vs_with_ref_match:.3f}")
    print(f"  不匹配+ref: vs={vs_with_ref_mismatch:.3f}")
    print(f"  匹配无ref:  vs={vs_without_ref:.3f}")

    # 有参考答案且匹配 → 分数应高于无参考答案
    assert vs_with_ref_match >= vs_without_ref, \
        f"匹配参考答案的vs({vs_with_ref_match:.3f})应>=无ref的vs({vs_without_ref:.3f})"
    # 不匹配参考答案 → 分数应低于匹配的
    assert vs_with_ref_mismatch < vs_with_ref_match, \
        f"不匹配参考答案的vs({vs_with_ref_mismatch:.3f})应低于匹配的({vs_with_ref_match:.3f})"

    # 验证 _check_answer_match 直接调用
    assert _check_answer_match("5", "5") == 1.0, "完全匹配应为1.0"
    assert _check_answer_match("x=2", "x = 2") >= 0.7, "格式不同但内容相同应>=0.7"
    assert _check_answer_match("3", "7") <= 0.1, "不匹配应<=0.1"

    print(f"  [PASS] reference_answer 匹配提升 verification_score")
    print(f"  [PASS] 不匹配降低 verification_score")
    return True


# ==================== Test 9: 矛盾检测 ====================

def test_contradiction_detection():
    """矛盾检测应识别推理中的内部矛盾。"""
    print("\n=== Test 9: 矛盾检测 ===")

    question = "求解不等式 x^2 - 4 < 0。"

    # 无矛盾的正常推理
    c_normal = {
        "final_answer": "-2 < x < 2",
        "proof": "x^2 - 4 < 0 即 (x+2)(x-2) < 0，解得 -2 < x < 2",
        "reasoning": "因式分解后求解",
        "steps": ["x^2 - 4 < 0", "(x+2)(x-2) < 0", "-2 < x < 2"],
    }

    # 有矛盾：同一变量赋不同值
    c_contradiction = {
        "final_answer": "x = 2",
        "proof": "由计算得 x = 2。又由验证得 x = 3。因此 x = 2。",
        "reasoning": "计算",
        "steps": ["x = 2", "x = 3", "x = 2"],
    }

    # 有矛盾：推理说无解但final_answer非空
    c_no_solution = {
        "final_answer": "x = 5",
        "proof": "经分析，该方程不存在实数解。因此 x = 5。",
        "reasoning": "分析",
        "steps": [],
    }

    # 反证法中的"矛盾"是正常的
    c_proof_by_contradiction = {
        "final_answer": "假设不成立，原命题成立",
        "proof": (
            "假设原命题不成立。由此推导得出矛盾。"
            "因此假设不成立，原命题成立。"
        ),
        "reasoning": "反证法",
        "steps": ["假设不成立", "推导得矛盾", "故原命题成立"],
    }

    contra_normal = _check_contradictions(c_normal, question)
    contra_conflict = _check_contradictions(c_contradiction, question)
    contra_nosol = _check_contradictions(c_no_solution, question)
    contra_pbc = _check_contradictions(c_proof_by_contradiction, question)

    print(f"  正常推理:       contradiction={contra_normal:.2f}")
    print(f"  变量矛盾:       contradiction={contra_conflict:.2f}")
    print(f"  无解矛盾:       contradiction={contra_nosol:.2f}")
    print(f"  反证法(正常):   contradiction={contra_pbc:.2f}")

    assert contra_normal >= 0.9, f"正常推理应无矛盾(>=0.9)，实际{contra_normal:.2f}"
    assert contra_conflict < 0.9, f"变量矛盾应检出(<0.9)，实际{contra_conflict:.2f}"
    assert contra_nosol < 0.9, f"无解矛盾应检出(<0.9)，实际{contra_nosol:.2f}"
    assert contra_pbc >= 0.9, f"反证法中的矛盾是正常的(>=0.9)，实际{contra_pbc:.2f}"

    print(f"  [PASS] 正常推理无矛盾")
    print(f"  [PASS] 变量赋值矛盾被检出")
    print(f"  [PASS] 无解矛盾被检出")
    print(f"  [PASS] 反证法中的'矛盾'未被误判")
    return True


# ==================== Test 10: 题目条件满足检查 ====================

def test_condition_satisfaction():
    """题目条件满足检查应反映推理对条件的覆盖。"""
    print("\n=== Test 10: 题目条件满足检查 ===")

    # 题目含明确条件"正整数"
    question = "证明：对任意正整数 n，n^2 + n 是偶数。"

    # 推理引用了"正整数"条件
    c_with_cond = {
        "final_answer": "n^2 + n 是偶数",
        "proof": "对正整数 n，n^2 + n = n(n+1)。因为 n 和 n+1 是连续正整数，必有一个偶数，所以 n(n+1) 是偶数。",
        "reasoning": "因式分解",
        "steps": ["n^2+n = n(n+1)", "连续正整数必含偶数", "因此是偶数"],
    }

    # 推理未引用"正整数"条件
    c_without_cond = {
        "final_answer": "n^2 + n 是偶数",
        "proof": "n^2 + n 是偶数。",
        "reasoning": "显然",
        "steps": [],
    }

    proof_required = is_proof_problem(question)
    cond_with = _check_condition_satisfaction(c_with_cond, question, proof_required)
    cond_without = _check_condition_satisfaction(c_without_cond, question, proof_required)

    print(f"  引用条件:   satisfaction={cond_with:.2f}")
    print(f"  未引用条件: satisfaction={cond_without:.2f}")

    assert cond_with > cond_without, \
        f"引用条件的satisfaction({cond_with:.2f})应高于未引用的({cond_without:.2f})"
    assert cond_with >= 0.5, f"引用条件应>=0.5，实际{cond_with:.2f}"

    print(f"  [PASS] 引用题目条件的推理得分更高")
    return True


# ==================== Test 11: proof_required 动态权重 ====================

def test_dynamic_scoring_weights():
    """证明题和非证明题应使用不同评分公式。"""
    print("\n=== Test 11: proof_required 动态权重 ===")

    candidate = {
        "confidence": 0.6,
        "verification_score": 0.8,
        "verification_confidence": 1.0,
        "proof_quality_score": 1.0,
    }

    # 证明题: 0.3*0.6 + 0.4*0.8 + 0.3*1.0 = 0.18 + 0.32 + 0.30 = 0.80
    score_proof = score_candidate(candidate, proof_required=True)
    expected_proof = 0.3 * 0.6 + 0.4 * 0.8 + 0.3 * 1.0

    # 非证明题: 0.5*0.6 + 0.5*0.8 = 0.30 + 0.40 = 0.70
    score_nonproof = score_candidate(candidate, proof_required=False)
    expected_nonproof = 0.5 * 0.6 + 0.5 * 0.8

    print(f"  证明题:   score={score_proof:.4f} (expected={expected_proof:.4f})")
    print(f"  非证明题: score={score_nonproof:.4f} (expected={expected_nonproof:.4f})")

    assert abs(score_proof - expected_proof) < 0.001, \
        f"证明题分数应为{expected_proof:.4f}，实际{score_proof:.4f}"
    assert abs(score_nonproof - expected_nonproof) < 0.001, \
        f"非证明题分数应为{expected_nonproof:.4f}，实际{score_nonproof:.4f}"

    # 证明题中 proof_quality_score 有影响
    candidate_low_pq = dict(candidate, proof_quality_score=0.0)
    score_proof_low_pq = score_candidate(candidate_low_pq, proof_required=True)
    assert score_proof_low_pq < score_proof, \
        f"证明题中低pq({score_proof_low_pq:.4f})应低于高pq({score_proof:.4f})"

    # 非证明题中 proof_quality_score 无影响
    score_nonproof_low_pq = score_candidate(candidate_low_pq, proof_required=False)
    assert abs(score_nonproof_low_pq - score_nonproof) < 0.001, \
        f"非证明题中pq不应影响分数: {score_nonproof_low_pq:.4f} vs {score_nonproof:.4f}"

    print(f"  [PASS] 证明题使用 0.3/0.4/0.3 公式")
    print(f"  [PASS] 非证明题使用 0.5/0.5 公式")
    print(f"  [PASS] proof_quality_score 仅影响证明题评分")
    return True


# ==================== Test 12: 选中候选二次验证 ====================

def test_selected_candidate_verification():
    """_verify_selected_candidate 应检出选中候选的问题并降低分数。"""
    print("\n=== Test 12: 选中候选二次验证 ===")

    question = "证明：若 a | b 且 b | c，则 a | c。"
    proof_required = is_proof_problem(question)
    assert proof_required, "该题应为证明题"

    # Case 1: 正常候选（有证明，无问题）
    c_good = {
        "index": 0,
        "final_answer": "a | c 成立",
        "proof": (
            "因为 a|b，所以 b = k1*a。因为 b|c，所以 c = k2*b。"
            "代入得 c = k2*k1*a = (k1*k2)*a。令 k = k1*k2，则 c = k*a，因此 a|c。"
        ),
        "reasoning": "整除定义+代换",
        "steps": ["b = k1*a", "c = k2*b", "c = (k1*k2)*a", "a|c"],
        "confidence": 0.85,
        "verification_score": 0.8,
        "proof_quality_score": 1.0,
    }
    verified_good = _verify_selected_candidate(c_good, question, proof_required)
    assert "verification_issues" not in verified_good, \
        f"正常候选不应有问题，实际: {verified_good.get('verification_issues')}"
    assert verified_good["verification_score"] == 0.8, \
        f"正常候选vs不应降低，实际{verified_good['verification_score']}"

    # Case 2: 证明题但无证明内容
    c_no_proof = {
        "index": 1,
        "final_answer": "a | c",
        "proof": "",
        "reasoning": "",
        "steps": [],
        "confidence": 0.5,
        "verification_score": 0.6,
        "proof_quality_score": 0.0,
    }
    verified_noproof = _verify_selected_candidate(c_no_proof, question, proof_required)
    assert "verification_issues" in verified_noproof, \
        "证明题无证明应有verification_issues"
    assert "missing_proof" in verified_noproof["verification_issues"], \
        f"应有missing_proof，实际: {verified_noproof['verification_issues']}"
    assert verified_noproof["verification_score"] < 0.6, \
        f"有问题时vs应降低，实际{verified_noproof['verification_score']}"

    # Case 3: 答案与reference_answer冲突
    c_mismatch = {
        "index": 2,
        "final_answer": "x = 42",
        "proof": "经计算 x = 42",
        "reasoning": "计算",
        "steps": ["x = 42"],
        "confidence": 0.7,
        "verification_score": 0.7,
        "proof_quality_score": 0.5,
    }
    verified_mismatch = _verify_selected_candidate(
        c_mismatch, "求解 x + 1 = 3", False, reference_answer="x = 2"
    )
    assert "verification_issues" in verified_mismatch, \
        "答案不匹配应有verification_issues"
    assert "answer_mismatch" in verified_mismatch["verification_issues"], \
        f"应有answer_mismatch，实际: {verified_mismatch['verification_issues']}"
    assert verified_mismatch["verification_score"] < 0.7, \
        f"不匹配时vs应降低，实际{verified_mismatch['verification_score']}"

    print(f"  [PASS] 正常候选不受影响")
    print(f"  [PASS] 证明题缺证明被检出，vs降低")
    print(f"  [PASS] 答案不匹配被检出，vs降低")
    return True


# ==================== Test 13: 端到端含 reference_answer ====================

def test_end_to_end_with_reference_answer():
    """端到端：reference_answer 贯穿整个 parser 流程。"""
    print("\n=== Test 13: 端到端含 reference_answer ===")

    question = "求 1 + 2 + ... + 100 的值。"
    reference_answer = "5050"

    raw_json = json.dumps({
        "candidates": [
            {
                "index": 0,
                "final_answer": "5050",
                "proof": "利用高斯求和公式：S = n(n+1)/2 = 100*101/2 = 5050",
                "reasoning": "高斯求和",
                "steps": ["S = 100*101/2", "S = 5050"],
                "confidence": 0.9,
            },
            {
                "index": 1,
                "final_answer": "5050",
                "proof": "直接逐项相加",
                "reasoning": "",
                "steps": [],
                "confidence": 0.5,
            },
            {
                "index": 2,
                "final_answer": "5150",
                "proof": "计算得 5150",
                "reasoning": "估算",
                "steps": ["5150"],
                "confidence": 0.7,
            },
        ],
        "selected_index": 2,
        "selection_reasoning": "模型选择",
        "final_answer": "5150",
    }, ensure_ascii=False)

    # 有 reference_answer
    parsed_with_ref = parse_multi_candidate_response(
        raw_json, question=question, reference_answer=reference_answer
    )
    # 无 reference_answer
    parsed_no_ref = parse_multi_candidate_response(
        raw_json, question=question, reference_answer=None
    )

    print(f"  有ref: selected={parsed_with_ref['selected_index']}, "
          f"vs={parsed_with_ref['verification_score']:.3f}")
    print(f"  无ref: selected={parsed_no_ref['selected_index']}, "
          f"vs={parsed_no_ref['verification_score']:.3f}")

    # C2 (answer=5150, wrong) 与 reference_answer=5050 不匹配
    # verification_score 计算时通过 _check_answer_match 降低分数
    cands = parsed_with_ref["candidates"]
    c0 = next(c for c in cands if c["index"] == 0)
    c2 = next(c for c in cands if c["index"] == 2)
    assert c2["verification_score"] < c0["verification_score"], \
        f"C2(答案错误)vs({c2['verification_score']:.3f})应低于C0(答案正确)vs({c0['verification_score']:.3f})"

    # C0 (answer=5050, correct) 应被选中
    assert parsed_with_ref["selected_index"] == 0, \
        f"应选择C0（答案正确），实际选择了{parsed_with_ref['selected_index']}"

    print(f"  [PASS] 答案错误的C2 verification_score 更低")
    print(f"  [PASS] 答案正确的C0被选中")
    return True


# ==================== Phase 5 新增测试 ====================

# ==================== Test 14: verification_confidence 字段解析 ====================

def test_verification_confidence_parsing():
    """模型返回了 verification_confidence，parser 应正确解析。"""
    print("\n=== Test 14: verification_confidence 字段解析 ===")

    question = "计算 3 * 7 的值。"
    candidates_data = [
        {
            "index": 0,
            "final_answer": "21",
            "proof": "3 * 7 = 21",
            "reasoning": "直接乘法",
            "steps": ["3 * 7 = 21"],
            "confidence": 0.9,
            "verification_score": 0.85,
            "verification_confidence": 0.9,
            "proof_quality_score": 0.5,
        },
        {
            "index": 1,
            "final_answer": "21",
            "proof": "3 * 7 = 21",
            "reasoning": "乘法",
            "steps": ["3 * 7 = 21"],
            "confidence": 0.7,
            "verification_score": 0.80,
            "verification_confidence": 0.3,
            "proof_quality_score": 0.5,
        },
    ]

    raw = _make_candidate_json(candidates_data, selected_index=0, question=question)
    parsed = parse_multi_candidate_response(raw, question=question)

    cands = parsed["candidates"]
    c0 = next(c for c in cands if c["index"] == 0)
    c1 = next(c for c in cands if c["index"] == 1)

    assert c0["verification_confidence"] == 0.9, \
        f"C0 vc应为0.9，实际{c0['verification_confidence']}"
    assert c1["verification_confidence"] == 0.3, \
        f"C1 vc应为0.3，实际{c1['verification_confidence']}"

    # 顶层返回值
    assert "verification_confidence" in parsed, "顶层应有 verification_confidence"
    assert "verification_warning" in parsed, "顶层应有 verification_warning"

    print(f"  [PASS] 模型返回的 verification_confidence 被正确解析")
    print(f"  C0: vc={c0['verification_confidence']:.2f}")
    print(f"  C1: vc={c1['verification_confidence']:.2f}")
    print(f"  顶层: vc={parsed['verification_confidence']:.2f}, warning='{parsed['verification_warning']}'")
    return True


# ==================== Test 15: 高verification低confidence不被过度惩罚 ====================

def test_high_vs_low_vc_not_over_penalized():
    """
    Phase 5.1: vc 对 final_score 的影响被限制在 80%–100% 范围。

    final = base_score * (0.8 + 0.2 * vc)

    - vc=1.0 → 100% base_score
    - vc=0.5 →  90% base_score
    - vc=0.0 →  80% base_score

    低 vc 不会过度惩罚高质量 candidate。
    """
    print("\n=== Test 15: vc 影响限制在 80%-100% 范围 ===")

    question = "计算 2^10 的值。"
    proof_required = is_proof_problem(question)
    assert not proof_required

    # base_score (non-proof): 0.5*0.8 + 0.5*0.8 = 0.80
    base_candidate = {
        "confidence": 0.8,
        "verification_score": 0.8,
        "verification_confidence": 1.0,
        "proof_quality_score": 0.5,
    }
    base_score = 0.5 * 0.8 + 0.5 * 0.8  # 0.80

    # Test key vc points
    for vc, expected_pct in [(1.0, 1.0), (0.5, 0.9), (0.0, 0.8), (0.3, 0.86)]:
        c = dict(base_candidate, verification_confidence=vc)
        score = score_candidate(c, proof_required)
        expected = base_score * expected_pct
        assert abs(score - expected) < 0.001, \
            f"vc={vc}: final应为{expected:.4f}({expected_pct*100:.0f}%)，实际{score:.4f}"
        print(f"  vc={vc:.1f}: final={score:.4f} ({expected_pct*100:.0f}% of base)")

    # vc=0 的 candidate 仍保留 80% base_score，不被淘汰
    c_zero_vc = dict(base_candidate, verification_confidence=0.0)
    score_zero = score_candidate(c_zero_vc, proof_required)
    assert abs(score_zero - base_score * 0.8) < 0.001, \
        f"vc=0时应保留80%base({base_score*0.8:.4f})，实际{score_zero:.4f}"
    assert score_zero > 0, "vc=0的candidate分数仍应>0"

    print(f"  [PASS] vc=1.0 → 100% base_score")
    print(f"  [PASS] vc=0.5 → 90% base_score")
    print(f"  [PASS] vc=0.0 → 80% base_score (不被淘汰)")
    print(f"  [PASS] vc=0.3 → 86% base_score (温和惩罚)")
    return True


# ==================== Test 16: proof高但answer错误的disagreement检测 ====================

def test_disagreement_proof_answer_conflict():
    """
    proof_quality_score 高但 answer 与 reference_answer 不匹配 →
    应检测到 disagreement。
    """
    print("\n=== Test 16: proof和answer冲突的disagreement检测 ===")

    question = "求解方程 x^2 - 4 = 0。"
    reference_answer = "x = 2 或 x = -2"
    proof_required = is_proof_problem(question)

    # Candidate: proof 结构好（长证明），但最终答案错误
    c_proof_good_answer_wrong = {
        "final_answer": "x = 5 或 x = -5",
        "proof": (
            "因为 x^2 - 4 = 0，所以 x^2 = 4。"
            "因此 x = 5 或 x = -5。"
            "验证：5^2 = 25 ≠ 4，但这不影响结论。"
        ),
        "reasoning": "因式分解求解",
        "steps": ["x^2 - 4 = 0", "x^2 = 4", "x = 5 或 x = -5"],
        "confidence": 0.8,
        "verification_score": 0.7,
        "proof_quality_score": 1.0,  # 证明结构完整
    }

    # Candidate: 一切正常
    c_all_good = {
        "final_answer": "x = 2 或 x = -2",
        "proof": "x^2 - 4 = 0，因式分解得 (x-2)(x+2) = 0，因此 x=2 或 x=-2",
        "reasoning": "因式分解",
        "steps": ["x^2 - 4 = 0", "(x-2)(x+2) = 0", "x=2 或 x=-2"],
        "confidence": 0.9,
        "verification_score": 0.9,
        "proof_quality_score": 1.0,
    }

    warning_conflict, severity_conflict = _detect_verification_disagreement(
        c_proof_good_answer_wrong, question, proof_required, reference_answer
    )
    warning_good, severity_good = _detect_verification_disagreement(
        c_all_good, question, proof_required, reference_answer
    )

    print(f"  proof好答案错: warning='{warning_conflict}', severity={severity_conflict:.2f}")
    print(f"  一切正常:      warning='{warning_good}', severity={severity_good:.2f}")

    assert "proof_high_answer_wrong" in warning_conflict, \
        f"proof高但answer错应检测到proof_high_answer_wrong，实际: {warning_conflict}"
    assert severity_conflict > 0, "有冲突时severity应>0"

    assert warning_good == "", \
        f"一切正常不应有warning，实际: {warning_good}"
    assert severity_good == 0, f"一切正常severity应为0，实际{severity_good}"

    print(f"  [PASS] proof高但answer错误 → 检测到 proof_high_answer_wrong")
    print(f"  [PASS] 一切正常 → 无 warning")
    return True


# ==================== Test 17: confidence高但verification低的disagreement检测 ====================

def test_disagreement_confidence_verification_conflict():
    """
    confidence >= 0.7 但 verification_score <= 0.4 →
    应检测到 confidence_high_verification_low。
    """
    print("\n=== Test 17: confidence高但verification低的disagreement检测 ===")

    question = "计算 5! 的值。"
    proof_required = is_proof_problem(question)

    c_conflict = {
        "final_answer": "120",
        "proof": "5! = 120",
        "reasoning": "阶乘",
        "steps": [],
        "confidence": 0.95,        # 高 confidence
        "verification_score": 0.2,  # 低 verification
        "proof_quality_score": 0.0,
    }

    warning, severity = _detect_verification_disagreement(
        c_conflict, question, proof_required, reference_answer=None
    )

    print(f"  warning='{warning}', severity={severity:.2f}")

    assert "confidence_high_verification_low" in warning, \
        f"conf=0.95, vs=0.2 应检测到confidence_high_verification_low，实际: {warning}"

    # verification_confidence 应因 disagreement 降低
    vc = _compute_verification_confidence(
        c_conflict, question, proof_required,
        reference_answer=None,
        disagreement=warning,
        disagreement_severity=severity,
    )
    print(f"  verification_confidence = {vc:.2f}")

    # 有 disagreement 时 vc 应低于 baseline 0.5
    vc_no_disagree = _compute_verification_confidence(
        c_conflict, question, proof_required,
        reference_answer=None,
        disagreement="",
        disagreement_severity=0.0,
    )
    print(f"  vc without disagreement = {vc_no_disagree:.2f}")
    assert vc < vc_no_disagree, \
        f"有disagreement时vc({vc:.2f})应低于无disagreement的({vc_no_disagree:.2f})"

    print(f"  [PASS] confidence高verification低 → 检测到 disagreement")
    print(f"  [PASS] disagreement 降低 verification_confidence")
    return True


# ==================== Test 18: reference缺失时verification_confidence计算 ====================

def test_vc_without_reference_answer():
    """
    无 reference_answer 时，verification_confidence 应低于有 reference_answer 时。
    （缺少外部参照，verifier 可信度降低）
    """
    print("\n=== Test 18: reference缺失时verification_confidence计算 ===")

    question = "求 sin(π/6) 的值。"
    proof_required = is_proof_problem(question)

    candidate = {
        "final_answer": "1/2",
        "proof": "sin(π/6) = 1/2 是基本三角函数值",
        "reasoning": "特殊角三角函数",
        "steps": ["sin(π/6) = 1/2"],
        "confidence": 0.9,
        "verification_score": 0.8,
        "proof_quality_score": 0.5,
    }

    vc_with_ref = _compute_verification_confidence(
        candidate, question, proof_required,
        reference_answer="1/2",
        disagreement="",
        disagreement_severity=0.0,
    )
    vc_without_ref = _compute_verification_confidence(
        candidate, question, proof_required,
        reference_answer=None,
        disagreement="",
        disagreement_severity=0.0,
    )

    print(f"  有reference: vc = {vc_with_ref:.2f}")
    print(f"  无reference: vc = {vc_without_ref:.2f}")

    assert vc_with_ref > vc_without_ref, \
        f"有reference_answer时vc({vc_with_ref:.2f})应高于无reference的({vc_without_ref:.2f})"
    assert vc_without_ref >= 0.1, f"vc不应低于0.1，实际{vc_without_ref:.2f}"
    assert vc_with_ref <= 1.0, f"vc不应高于1.0，实际{vc_with_ref:.2f}"

    print(f"  [PASS] 有 reference_answer 时 vc 更高（+0.15 外部参照加成）")
    print(f"  [PASS] 无 reference_answer 时 vc 仍在合理范围")
    return True


# ==================== Test 19: vc < 0.4 不淘汰candidate ====================

def test_low_vc_does_not_eliminate():
    """
    Phase 5.1: 两个candidate，一个 vc 低但 base_score 高，一个 vc 高但 base_score 低。
    新公式 base * (0.8 + 0.2*vc) 下，vc 的影响仅 ±20%，
    高 base_score 的 candidate 即使 vc 很低也不会被淘汰。
    """
    print("\n=== Test 19: 低vc不淘汰高base candidate ===")

    question = "计算 15 + 27 的值。"
    proof_required = is_proof_problem(question)

    # C0: 高 base_score 但 vc 很低
    # base = 0.5*0.9 + 0.5*0.9 = 0.90
    # final = 0.90 * (0.8 + 0.2*0.1) = 0.90 * 0.82 = 0.738
    c_high_base_low_vc = {
        "index": 0,
        "final_answer": "42",
        "proof": "15 + 27 = 42",
        "reasoning": "加法",
        "steps": ["15 + 27 = 42"],
        "confidence": 0.9,
        "verification_score": 0.9,
        "verification_confidence": 0.1,  # very low vc
        "proof_quality_score": 0.5,
    }

    # C1: 低 base_score 但 vc 高
    # base = 0.5*0.3 + 0.5*0.3 = 0.30
    # final = 0.30 * (0.8 + 0.2*1.0) = 0.30 * 1.0 = 0.30
    c_low_base_high_vc = {
        "index": 1,
        "final_answer": "42",
        "proof": "15 + 27 = 42",
        "reasoning": "加法",
        "steps": ["15 + 27 = 42"],
        "confidence": 0.3,
        "verification_score": 0.3,
        "verification_confidence": 1.0,  # perfect vc
        "proof_quality_score": 0.5,
    }

    score_0 = score_candidate(c_high_base_low_vc, proof_required)
    score_1 = score_candidate(c_low_base_high_vc, proof_required)

    # Verify exact values
    expected_0 = 0.90 * (0.8 + 0.2 * 0.1)  # 0.738
    expected_1 = 0.30 * (0.8 + 0.2 * 1.0)  # 0.300

    print(f"  C0: base=0.90, vc=0.1 → final={score_0:.4f} (expected {expected_0:.4f})")
    print(f"  C1: base=0.30, vc=1.0 → final={score_1:.4f} (expected {expected_1:.4f})")

    assert abs(score_0 - expected_0) < 0.001, \
        f"C0 final应为{expected_0:.4f}，实际{score_0:.4f}"
    assert abs(score_1 - expected_1) < 0.001, \
        f"C1 final应为{expected_1:.4f}，实际{score_1:.4f}"

    # C0 应被选中（base_score 高，vc低但不被淘汰）
    assert score_0 > score_1, \
        f"C0(base高,vc低)的final({score_0:.4f})应高于C1(base低,vc高)的({score_1:.4f})"

    selected = select_best_candidate_index(
        [c_high_base_low_vc, c_low_base_high_vc],
        model_selected=1, proof_required=proof_required,
    )
    assert selected == 0, \
        f"应选择C0（base高vc低不被淘汰），实际选择了{selected}"

    # C0 仍保留了 82% 的 base_score（> 80% 下限）
    retention = score_0 / 0.90
    assert retention >= 0.80, \
        f"C0应保留>=80%的base_score，实际保留{retention*100:.1f}%"

    print(f"  [PASS] C0 保留 {retention*100:.1f}% base_score (≥80%)")
    print(f"  [PASS] C0 final({score_0:.4f}) > C1 final({score_1:.4f})")
    print(f"  [PASS] 低vc的C0不被淘汰，最终被选中")
    return True


# ==================== Test 20: verification_warning 端到端 ====================

def test_verification_warning_end_to_end():
    """端到端：disagreement 在 parser 流程中产生 verification_warning。"""
    print("\n=== Test 20: verification_warning 端到端 ===")

    question = "求 2^8 的值。"
    reference_answer = "256"

    raw_json = json.dumps({
        "candidates": [
            {
                "index": 0,
                "final_answer": "256",
                "proof": "2^8 = 256，因为 2^8 = 2*2*2*2*2*2*2*2 = 256",
                "reasoning": "幂运算",
                "steps": ["2^8 = 256"],
                "confidence": 0.9,
                "verification_score": 0.9,
                "proof_quality_score": 0.5,
            },
            {
                "index": 1,
                "final_answer": "512",
                "proof": "2^8 = 512，由连续乘法计算得出",
                "reasoning": "幂运算",
                "steps": ["2^8 = 512"],
                "confidence": 0.9,        # 高 confidence
                "verification_score": 0.3,  # 低 verification（answer 错误）
                "proof_quality_score": 0.5,
            },
        ],
        "selected_index": 1,
        "selection_reasoning": "模型选择",
        "final_answer": "512",
    }, ensure_ascii=False)

    parsed = parse_multi_candidate_response(
        raw_json, question=question, reference_answer=reference_answer
    )

    cands = parsed["candidates"]
    c0 = next(c for c in cands if c["index"] == 0)
    c1 = next(c for c in cands if c["index"] == 1)

    # C1 有 confidence_high_verification_low disagreement
    assert c1.get("verification_warning"), \
        f"C1 (conf=0.9, vs=0.3) 应有 verification_warning"
    assert "confidence_high_verification_low" in c1["verification_warning"], \
        f"C1 warning 应包含 confidence_high_verification_low，实际: {c1['verification_warning']}"

    # C1 有 disagreement 时 vc 应低于 C0（无 disagreement）
    assert c1["verification_confidence"] < c0["verification_confidence"], \
        f"C1(有disagreement)vc({c1['verification_confidence']:.2f})应低于C0(无disagreement)vc({c0['verification_confidence']:.2f})"

    # C0 无 disagreement
    assert not c0.get("verification_warning"), \
        f"C0 不应有 warning，实际: {c0.get('verification_warning')}"

    # C0 (answer 正确) 应被选中
    assert parsed["selected_index"] == 0, \
        f"应选择C0（答案正确），实际选择了{parsed['selected_index']}"

    print(f"  [PASS] C1 检测到 disagreement: {c1['verification_warning']}")
    print(f"  [PASS] C1 vc({c1['verification_confidence']:.2f}) < C0 vc({c0['verification_confidence']:.2f})")
    print(f"  [PASS] C0 (答案正确) 被选中")
    return True


# ==================== Phase 5.1 新增测试 ====================

# ==================== Test 21: 高base低vc vs 低base高vc ====================

def test_case1_high_base_low_vc_vs_low_base_high_vc():
    """
    Case 1: 高base低vc vs 低base高vc

    新公式 base * (0.8 + 0.2*vc) 下，vc 影响仅 ±20%。
    高 base_score 的 candidate 即使 vc 很低仍应胜出。

    C0: conf=0.9, vs=0.9, vc=0.1 → base=0.90, final=0.90*0.82=0.738
    C1: conf=0.5, vs=0.5, vc=1.0 → base=0.50, final=0.50*1.0=0.500
    """
    print("\n=== Test 21: Case1 高base低vc vs 低base高vc ===")

    proof_required = False  # 非证明题

    c0 = {
        "index": 0,
        "final_answer": "42",
        "confidence": 0.9,
        "verification_score": 0.9,
        "verification_confidence": 0.1,  # very low vc
        "proof_quality_score": 0.5,
    }
    c1 = {
        "index": 1,
        "final_answer": "42",
        "confidence": 0.5,
        "verification_score": 0.5,
        "verification_confidence": 1.0,  # perfect vc
        "proof_quality_score": 0.5,
    }

    base_0 = 0.5 * 0.9 + 0.5 * 0.9  # 0.90
    base_1 = 0.5 * 0.5 + 0.5 * 0.5  # 0.50
    expected_0 = base_0 * (0.8 + 0.2 * 0.1)  # 0.738
    expected_1 = base_1 * (0.8 + 0.2 * 1.0)  # 0.500

    score_0 = score_candidate(c0, proof_required)
    score_1 = score_candidate(c1, proof_required)

    print(f"  C0: base={base_0:.2f}, vc=0.1 → final={score_0:.4f} (expected {expected_0:.4f})")
    print(f"  C1: base={base_1:.2f}, vc=1.0 → final={score_1:.4f} (expected {expected_1:.4f})")

    assert abs(score_0 - expected_0) < 0.001
    assert abs(score_1 - expected_1) < 0.001

    # 高base低vc 胜出
    assert score_0 > score_1, \
        f"C0(高base低vc)final({score_0:.4f})应高于C1(低base高vc)final({score_1:.4f})"

    selected = select_best_candidate_index([c0, c1], model_selected=1, proof_required=proof_required)
    assert selected == 0, f"应选择C0，实际选择了{selected}"

    # C0 保留了 82% 的 base_score
    retention = score_0 / base_0
    assert retention >= 0.80, f"C0应保留>=80%base，实际{retention*100:.1f}%"

    print(f"  [PASS] C0 保留 {retention*100:.1f}% base_score，不被低vc淘汰")
    print(f"  [PASS] C0({score_0:.4f}) > C1({score_1:.4f})，高base低vc胜出")
    return True


# ==================== Test 22: 正确答案但verification不确定 ====================

def test_case2_correct_answer_uncertain_verification():
    """
    Case 2: 正确答案但verification不确定

    正确答案的 vc 很低（verifier 不确定），但 base_score 足够高，
    不应被错误答案（vc 高但 base 低）淘汰。

    C0: correct answer, conf=0.7, vs=0.7, vc=0.2 → base=0.70, final=0.588
    C1: wrong answer,  conf=0.5, vs=0.5, vc=0.9 → base=0.50, final=0.490
    """
    print("\n=== Test 22: Case2 正确答案但verification不确定 ===")

    proof_required = False

    c0_correct = {
        "index": 0,
        "final_answer": "5050",
        "confidence": 0.7,
        "verification_score": 0.7,
        "verification_confidence": 0.2,  # verifier 不确定
        "proof_quality_score": 0.5,
    }
    c1_wrong = {
        "index": 1,
        "final_answer": "5150",
        "confidence": 0.5,
        "verification_score": 0.5,
        "verification_confidence": 0.9,  # verifier 很确信（但答案错）
        "proof_quality_score": 0.5,
    }

    base_0 = 0.5 * 0.7 + 0.5 * 0.7   # 0.70
    base_1 = 0.5 * 0.5 + 0.5 * 0.5   # 0.50
    expected_0 = base_0 * (0.8 + 0.2 * 0.2)  # 0.70 * 0.84 = 0.588
    expected_1 = base_1 * (0.8 + 0.2 * 0.9)  # 0.50 * 0.98 = 0.490

    score_0 = score_candidate(c0_correct, proof_required)
    score_1 = score_candidate(c1_wrong, proof_required)

    print(f"  C0(correct): base={base_0:.2f}, vc=0.2 → final={score_0:.4f}")
    print(f"  C1(wrong):   base={base_1:.2f}, vc=0.9 → final={score_1:.4f}")

    assert abs(score_0 - expected_0) < 0.001
    assert abs(score_1 - expected_1) < 0.001

    # 正确答案仍被选中（base 更高，vc 低但不被淘汰）
    assert score_0 > score_1, \
        f"正确答案C0({score_0:.4f})应高于错误答案C1({score_1:.4f})，不被低vc淘汰"

    selected = select_best_candidate_index(
        [c0_correct, c1_wrong], model_selected=1, proof_required=proof_required
    )
    assert selected == 0, f"应选择正确答案C0，实际选择了{selected}"

    # C0 保留了 84% 的 base_score
    retention = score_0 / base_0
    assert retention >= 0.80, f"C0应保留>=80%base，实际{retention*100:.1f}%"

    print(f"  [PASS] 正确答案C0保留{retention*100:.1f}%base，不被低vc淘汰")
    print(f"  [PASS] C0({score_0:.4f}) > C1({score_1:.4f})，正确答案胜出")
    return True


# ==================== Test 23: 错误答案但verification高 ====================

def test_case3_wrong_answer_high_verification():
    """
    Case 3: 错误答案但verification高

    错误答案有高 vc 和高 base，会胜出（scoring 无 ground truth）。
    但正确答案的 candidate 仍保留了 ≥80% 的 base_score，不被完全淘汰。
    vc 的影响被限制在 ±20%，不会无限放大错误答案的优势。

    C0: wrong answer, conf=0.7, vs=0.7, vc=1.0 → base=0.70, final=0.70
    C1: correct answer, conf=0.65, vs=0.65, vc=0.1 → base=0.65, final=0.533

    关键验证：
    1. C0 胜出（base 更高 + vc 完美）
    2. C1 仍保留 ≥80% base_score（0.533/0.65 = 82%）
    3. vc 造成的分差 ≤ 20% base（0.70 vs 0.533，差距来自 base 差 + vc 差）
    4. 如果 C1 的 base 稍高（0.87），即使 vc=0.1 也能胜出
    """
    print("\n=== Test 23: Case3 错误答案但verification高 ===")

    proof_required = False

    c0_wrong = {
        "index": 0,
        "final_answer": "5150",
        "confidence": 0.7,
        "verification_score": 0.7,
        "verification_confidence": 1.0,  # high vc
        "proof_quality_score": 0.5,
    }
    c1_correct = {
        "index": 1,
        "final_answer": "5050",
        "confidence": 0.65,
        "verification_score": 0.65,
        "verification_confidence": 0.1,  # low vc
        "proof_quality_score": 0.5,
    }

    base_0 = 0.5 * 0.7 + 0.5 * 0.7    # 0.70
    base_1 = 0.5 * 0.65 + 0.5 * 0.65  # 0.65
    expected_0 = base_0 * (0.8 + 0.2 * 1.0)  # 0.70 * 1.0 = 0.70
    expected_1 = base_1 * (0.8 + 0.2 * 0.1)  # 0.65 * 0.82 = 0.533

    score_0 = score_candidate(c0_wrong, proof_required)
    score_1 = score_candidate(c1_correct, proof_required)

    print(f"  C0(wrong):   base={base_0:.2f}, vc=1.0 → final={score_0:.4f}")
    print(f"  C1(correct): base={base_1:.2f}, vc=0.1 → final={score_1:.4f}")

    assert abs(score_0 - expected_0) < 0.001
    assert abs(score_1 - expected_1) < 0.001

    # 1. C0 (wrong, high vc) wins — expected, scoring has no ground truth
    assert score_0 > score_1, \
        f"C0(base高+vc高)应胜出，即使答案错误"

    # 2. C1 保留了 ≥80% base_score（不被淘汰）
    retention = score_1 / base_1
    assert retention >= 0.80, \
        f"C1应保留>=80%base_score，实际{retention*100:.1f}%"

    # 3. vc 造成的额外分差 ≤ 20% base
    # 如果两者 base 相同，vc 差距造成的 final 差距应 ≤ 0.2 * base
    vc_gap = (0.8 + 0.2 * 1.0) - (0.8 + 0.2 * 0.1)  # 1.0 - 0.82 = 0.18
    assert vc_gap <= 0.20, f"vc造成的分差应<=20%，实际{vc_gap*100:.0f}%"

    # 4. 如果 C1 的 base 足够高（0.87），即使 vc=0.1 也能胜过 C0
    c1_strong = dict(c1_correct, confidence=0.87, verification_score=0.87)
    base_1_strong = 0.87
    score_1_strong = score_candidate(c1_strong, proof_required)
    expected_1_strong = base_1_strong * (0.8 + 0.2 * 0.1)  # 0.87 * 0.82 = 0.7134
    assert abs(score_1_strong - expected_1_strong) < 0.001
    assert score_1_strong > score_0, \
        f"base=0.87+vc=0.1的candidate({score_1_strong:.4f})应胜过base=0.70+vc=1.0的({score_0:.4f})"

    print(f"  [PASS] C0(wrong,vc=1.0)胜出 — scoring无ground truth，符合预期")
    print(f"  [PASS] C1保留{retention*100:.1f}%base（≥80%），不被淘汰")
    print(f"  [PASS] vc造成的分差≤20%（实际{vc_gap*100:.0f}%）")
    print(f"  [PASS] base=0.87+vc=0.1({score_1_strong:.4f}) > base=0.70+vc=1.0({score_0:.4f})")
    return True

def main():
    print("=" * 60)
    print("Phase 4/5 验证测试：Verification Score + Verifier Calibration")
    print("=" * 60)

    tests = [
        test_parser_new_fields,
        test_old_format_compatibility,
        test_candidate_selection_uses_verification,
        test_proof_problem_verification,
        test_ensure_candidate_scores,
        test_inference_result_fields,
        test_end_to_end_parser,
        # Phase 4.1 新增
        test_reference_answer_matching,
        test_contradiction_detection,
        test_condition_satisfaction,
        test_dynamic_scoring_weights,
        test_selected_candidate_verification,
        test_end_to_end_with_reference_answer,
        # Phase 5 新增
        test_verification_confidence_parsing,
        test_high_vs_low_vc_not_over_penalized,
        test_disagreement_proof_answer_conflict,
        test_disagreement_confidence_verification_conflict,
        test_vc_without_reference_answer,
        test_low_vc_does_not_eliminate,
        test_verification_warning_end_to_end,
        # Phase 5.1 新增
        test_case1_high_base_low_vc_vs_low_base_high_vc,
        test_case2_correct_answer_uncertain_verification,
        test_case3_wrong_answer_high_verification,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"结果: {passed}/{passed + failed} 通过, {failed} 失败")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
