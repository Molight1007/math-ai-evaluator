"""
Phase 6.3 测试：数学定义约束验证增强 (Mathematical Constraint Verification)

测试 _check_mathematical_constraints 的 4 类约束检测：
  A. 基础范围约束（概率 0-1、非负物理量、正整数）
  B. 定义约束（对数定义域、分母非零、开方实数范围）
  C. 解集完整性（二次方程遗漏根）
  D. 极值问题约束（可行域检查）

以及 constraint_score 融入 verification_score 的效果。

测试原则：
  - 正常答案不能被误判（低误杀）
  - 明显定义错误可以检测
  - constraint_score 正常返回
  - constraint_issues 正常记录

运行: python verify_phase6_3.py
"""
import sys
import os
import json

# 添加当前目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intern_s1 import (
    _check_mathematical_constraints,
    _detect_math_domain,
    _extract_primary_number,
    _ensure_candidate_scores,
    parse_multi_candidate_response,
)

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}" + (f" — {detail}" if detail else ""))


# ==================== 辅助函数测试 ====================


def test_1_domain_detection():
    """测试数学域自动检测。"""
    test("test_1a_probability_domain",
         _detect_math_domain("求某事件发生的概率") == "probability")
    test("test_1b_geometry_domain",
         _detect_math_domain("求圆的面积和周长") == "geometry")
    test("test_1c_algebra_domain",
         _detect_math_domain("解二次方程 x^2 - 5x + 6 = 0") == "algebra")
    test("test_1d_number_theory_domain",
         _detect_math_domain("求所有正整数 n 使得 n 整除 12") == "number_theory")
    test("test_1e_general_domain",
         _detect_math_domain("计算 2 + 2") == "general")


def test_2_extract_primary_number():
    """测试数值提取。"""
    test("test_2a_integer", _extract_primary_number("42") == 42.0)
    test("test_2b_decimal", _extract_primary_number("3.14") == 3.14)
    test("test_2c_fraction", _extract_primary_number("3/4") == 0.75)
    test("test_2d_negative", _extract_primary_number("-5") == -5.0)
    test("test_2e_with_text", _extract_primary_number("x = 7") == 7.0)
    test("test_2f_percentage", _extract_primary_number("50%") == 0.5)
    test("test_2g_none", _extract_primary_number("abc") is None)


# ==================== A. 基础范围约束 ====================


def test_3_probability_valid():
    """概率值在 [0,1] 范围内，不应标记问题（不误杀）。"""
    candidate = {
        "final_answer": "0.5",
        "reasoning": "该事件发生的概率为 0.5",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_3_probability_valid: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')
    test("test_3_probability_valid: score=1.0",
         result["constraint_score"] == 1.0,
         f'score={result["constraint_score"]}')


def test_4_probability_out_of_range():
    """概率值 >1 应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "1.5",
        "reasoning": "概率为 1.5",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_4_probability_out_of_range: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_4_probability_out_of_range: type",
         result["constraint_issues"][0]["type"] == "probability_out_of_range")
    test("test_4_probability_out_of_range: score<1",
         result["constraint_score"] < 1.0,
         f'score={result["constraint_score"]}')


def test_5_probability_fraction_valid():
    """概率为分数 3/4 = 0.75 在范围内，不应标记（不误杀）。"""
    candidate = {
        "final_answer": "3/4",
        "reasoning": "概率为 3/4",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_5_probability_fraction_valid: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_6_probability_negative():
    """概率为负数应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "-0.3",
        "reasoning": "概率为 -0.3",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_6_probability_negative: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')


def test_7_negative_area():
    """面积为负应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "-12",
        "reasoning": "面积计算结果为 -12",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求圆的面积")
    test("test_7_negative_area: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_7_negative_area: type",
         result["constraint_issues"][0]["type"] == "negative_physical_quantity")


def test_8_non_negative_area_ok():
    """正面积不应被标记（不误杀）。"""
    candidate = {
        "final_answer": "12",
        "reasoning": "面积计算结果为 12",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求圆的面积")
    test("test_8_non_negative_area_ok: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_9_positive_integer_violation():
    """正整数条件违反（明显错误检测）。"""
    candidate = {
        "final_answer": "1.5",
        "reasoning": "结果为 1.5",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求所有正整数 n")
    test("test_9_positive_integer_violation: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_9_positive_integer_violation: type",
         result["constraint_issues"][0]["type"] == "not_positive_integer")


def test_10_positive_integer_ok():
    """正整数满足条件不应标记（不误杀）。"""
    candidate = {
        "final_answer": "5",
        "reasoning": "结果为 5",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求所有正整数 n")
    test("test_10_positive_integer_ok: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


# ==================== B. 定义约束 ====================


def test_11_log_domain_violation():
    """推理中出现 log(0) 应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "undefined",
        "reasoning": "计算 log(0) 得到结果",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "计算对数值")
    test("test_11_log_domain_violation: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_11_log_domain_violation: type",
         result["constraint_issues"][0]["type"] == "log_domain_violation")


def test_12_log_valid():
    """正常的 log(2) 不应标记（不误杀）。"""
    candidate = {
        "final_answer": "0.301",
        "reasoning": "计算 log(2) 得到 0.301",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "计算对数值")
    test("test_12_log_valid: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_13_division_by_zero():
    """推理中出现除以零应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "infinity",
        "reasoning": "将 5 除以 0 得到无穷大",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "计算结果")
    test("test_13_division_by_zero: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_13_division_by_zero: type",
         result["constraint_issues"][0]["type"] == "division_by_zero")


def test_14_sqrt_negative():
    """推理中对负数开平方应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "2i",
        "reasoning": "计算 sqrt(-4) 得到 2i",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "计算结果")
    test("test_14_sqrt_negative: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_14_sqrt_negative: type",
         result["constraint_issues"][0]["type"] == "sqrt_negative")


# ==================== C. 解集完整性 ====================


def test_15_quadratic_missing_roots():
    """二次方程要求所有解但只给出一个，应被标记（明显错误检测）。"""
    candidate = {
        "final_answer": "x = 2",
        "reasoning": "解方程得到 x = 2",
        "steps": ["代入公式得到 x = 2"],
    }
    result = _check_mathematical_constraints(candidate, "求二次方程 x² - 5x + 6 = 0 的所有解")
    test("test_15_quadratic_missing_roots: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_15_quadratic_missing_roots: type",
         result["constraint_issues"][0]["type"] == "quadratic_missing_roots")


def test_16_quadratic_both_roots_ok():
    """二次方程给出两个解，不应标记（不误杀）。"""
    candidate = {
        "final_answer": "x = 2 或 x = 3",
        "reasoning": "解方程得到两个解 x = 2 和 x = 3",
        "steps": ["判别式 > 0", "两个解分别为 2 和 3"],
    }
    result = _check_mathematical_constraints(candidate, "求二次方程 x² - 5x + 6 = 0 的所有解")
    test("test_16_quadratic_both_roots_ok: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_17_quadratic_no_all_solutions():
    """二次方程但题目不要求所有解时，不检查遗漏根（不误杀）。"""
    candidate = {
        "final_answer": "x = 2",
        "reasoning": "解方程得到 x = 2",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "二次方程 x² - 5x + 6 = 0 的较大根是多少")
    test("test_17_quadratic_no_all_solutions: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


# ==================== D. 极值问题约束 ====================


def test_18_feasible_domain_violation():
    """答案违反可行域约束 x > 0（明显错误检测）。"""
    candidate = {
        "final_answer": "-3",
        "reasoning": "结果为 -3",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "已知 x > 0 ，求 x 的值")
    test("test_18_feasible_domain_violation: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')
    test("test_18_feasible_domain_violation: type",
         result["constraint_issues"][0]["type"] == "feasible_domain_violation")


def test_19_feasible_domain_ok():
    """答案满足可行域约束 x > 0（不误杀）。"""
    candidate = {
        "final_answer": "5",
        "reasoning": "结果为 5",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "已知 x > 0 ，求 x 的值")
    test("test_19_feasible_domain_ok: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


# ==================== constraint_score 融入 verification_score ====================


def test_20_constraint_score_blending():
    """constraint_score 应融入 verification_score（权重 0.15），且 candidate 中存储 constraint_score/issues。"""
    candidate_bad = {
        "final_answer": "1.5",
        "reasoning": "概率为 1.5",
        "steps": [],
        "confidence": 0.8,
    }
    out_bad = _ensure_candidate_scores(candidate_bad, "求某事件的概率", False)

    candidate_good = {
        "final_answer": "0.5",
        "reasoning": "概率为 0.5",
        "steps": [],
        "confidence": 0.8,
    }
    out_good = _ensure_candidate_scores(candidate_good, "求某事件的概率", False)

    vs_bad = out_bad["verification_score"]
    vs_good = out_good["verification_score"]

    test("test_20a_constraint_score_stored_bad",
         "constraint_score" in out_bad and out_bad["constraint_score"] < 1.0,
         f'cs={out_bad.get("constraint_score")}')
    test("test_20b_constraint_score_stored_good",
         "constraint_score" in out_good and out_good["constraint_score"] == 1.0,
         f'cs={out_good.get("constraint_score")}')
    test("test_20c_constraint_issues_stored",
         "constraint_issues" in out_bad and len(out_bad["constraint_issues"]) > 0)
    test("test_20d_vs_bad_lower_than_good",
         vs_bad < vs_good,
         f'vs_bad={vs_bad:.4f}, vs_good={vs_good:.4f}')


def test_21_constraint_blending_weight():
    """验证融合权重约为 0.15：vs_diff > 0 且合理。"""
    candidate_no_issue = {
        "final_answer": "0.5",
        "reasoning": "概率为 0.5，根据概率论计算",
        "steps": ["步骤1: 确定样本空间", "步骤2: 计算有利事件数"],
        "confidence": 0.9,
    }
    candidate_with_issue = {
        "final_answer": "1.5",
        "reasoning": "概率为 1.5，根据概率论计算",
        "steps": ["步骤1: 确定样本空间", "步骤2: 计算有利事件数"],
        "confidence": 0.9,
    }
    out_no = _ensure_candidate_scores(candidate_no_issue, "求某事件的概率", False)
    out_yes = _ensure_candidate_scores(candidate_with_issue, "求某事件的概率", False)

    cs_diff = out_no["constraint_score"] - out_yes["constraint_score"]
    vs_diff = out_no["verification_score"] - out_yes["verification_score"]

    test("test_21a_cs_diff_positive", cs_diff > 0, f'cs_diff={cs_diff:.4f}')
    test("test_21b_vs_diff_positive", vs_diff > 0, f'vs_diff={vs_diff:.4f}')
    test("test_21c_vs_diff_reasonable",
         vs_diff > 0.01,
         f'vs_diff={vs_diff:.4f}')


def test_22_model_vs_not_overwritten():
    """模型自评的 verification_score 不应被 constraint_score 覆盖。"""
    candidate = {
        "final_answer": "1.5",
        "reasoning": "概率为 1.5",
        "steps": [],
        "confidence": 0.8,
        "verification_score": 0.9,  # 模型自评
    }
    out = _ensure_candidate_scores(candidate, "求某事件的概率", False)
    test("test_22a_model_vs_preserved",
         abs(out["verification_score"] - 0.9) < 1e-9,
         f'vs={out["verification_score"]}')
    test("test_22b_constraint_score_stored",
         "constraint_score" in out and out["constraint_score"] < 1.0,
         f'cs={out.get("constraint_score")}')
    test("test_22c_vs_from_model_flag",
         out.get("_vs_from_model") is True)


# ==================== 不误杀测试 ====================


def test_23_no_false_positive_general():
    """一般数学题不应误触发约束检查（不误杀）。"""
    candidate = {
        "final_answer": "42",
        "reasoning": "根据计算 6 * 7 = 42",
        "steps": ["6 * 7 = 42"],
    }
    result = _check_mathematical_constraints(candidate, "计算 6 乘以 7")
    test("test_23_no_false_positive_general: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')
    test("test_23_no_false_positive_general: score=1.0",
         result["constraint_score"] == 1.0)


def test_24_multiple_issues():
    """多个约束违反应累积扣分。"""
    candidate = {
        "final_answer": "1.5",
        "reasoning": "概率为 1.5，计算中使用了 log(0) 和除以 0",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_24a_multiple_issues: multiple flagged",
         len(result["constraint_issues"]) >= 2,
         f'count={len(result["constraint_issues"])}, issues={result["constraint_issues"]}')
    test("test_24b_multiple_issues: score_low",
         result["constraint_score"] <= 0.5,
         f'score={result["constraint_score"]}')


def test_25_constraint_score_in_parse_output():
    """parse_multi_candidate_response 输出应包含 constraint_score（集成验证）。"""
    json_text = json.dumps({
        "candidates": [
            {
                "index": 0,
                "final_answer": "0.5",
                "proof": "",
                "reasoning": "概率为 0.5",
                "steps": ["计算样本空间"],
                "confidence": 0.9,
            },
        ],
        "selected_index": 0,
        "selection_reasoning": "唯一候选",
        "final_answer": "0.5",
    })
    result = parse_multi_candidate_response(json_text, "求某事件的概率")
    test("test_25a_has_candidates",
         result.get("candidates") is not None)
    if result.get("candidates"):
        c = result["candidates"][0]
        test("test_25b_candidate_has_constraint_score",
             "constraint_score" in c,
             f'keys={list(c.keys())}')
        test("test_25c_candidate_has_constraint_issues",
             "constraint_issues" in c,
             f'keys={list(c.keys())}')


def test_26_explicit_domain_param():
    """显式传入 domain 参数应正常工作。"""
    candidate = {
        "final_answer": "1.5",
        "reasoning": "结果",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "某问题", domain="probability")
    test("test_26_explicit_domain_param: flagged",
         len(result["constraint_issues"]) == 1,
         f'issues={result["constraint_issues"]}')


def test_27_empty_answer_no_crash():
    """空答案不应导致崩溃。"""
    candidate = {
        "final_answer": "",
        "reasoning": "",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_27_empty_answer_no_crash: returns valid",
         "constraint_score" in result and "constraint_issues" in result)
    test("test_27_empty_answer_no_crash: score=1.0",
         result["constraint_score"] == 1.0,
         f'score={result["constraint_score"]}')


def test_28_negative_coordinate_not_flagged():
    """负数坐标不应被标记为 negative_physical_quantity（不误杀）。"""
    candidate = {
        "final_answer": "x = -3",
        "reasoning": "坐标为 x = -3",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求圆的面积")
    has_neg = any(i["type"] == "negative_physical_quantity" for i in result["constraint_issues"])
    test("test_28_negative_coordinate_not_flagged: not flagged",
         not has_neg,
         f'issues={result["constraint_issues"]}')


def test_29_probability_zero_valid():
    """概率为 0 是合法值，不应标记（不误杀）。"""
    candidate = {
        "final_answer": "0",
        "reasoning": "不可能事件，概率为 0",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_29_probability_zero_valid: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_30_probability_one_valid():
    """概率为 1 是合法值，不应标记（不误杀）。"""
    candidate = {
        "final_answer": "1",
        "reasoning": "必然事件，概率为 1",
        "steps": [],
    }
    result = _check_mathematical_constraints(candidate, "求某事件的概率")
    test("test_30_probability_one_valid: no issues",
         len(result["constraint_issues"]) == 0,
         f'issues={result["constraint_issues"]}')


def test_31_normal_math_answer_not_affected():
    """正常代数题答案不应被 constraint_score 影响（不误杀）。"""
    candidate = {
        "final_answer": "x = 3",
        "reasoning": "解方程 x + 2 = 5，得到 x = 3",
        "steps": ["x + 2 = 5", "x = 5 - 2", "x = 3"],
        "confidence": 0.9,
    }
    out = _ensure_candidate_scores(candidate, "解方程 x + 2 = 5", False)
    test("test_31a_no_constraint_issues",
         len(out.get("constraint_issues", [])) == 0,
         f'issues={out.get("constraint_issues")}')
    test("test_31b_constraint_score_is_1",
         out.get("constraint_score") == 1.0,
         f'cs={out.get("constraint_score")}')


# ==================== 运行所有测试 ====================


def run_all():
    print("=" * 60)
    print("Phase 6.3: Mathematical Constraint Verification Tests")
    print("=" * 60)

    tests = [
        # 辅助函数
        test_1_domain_detection,
        test_2_extract_primary_number,
        # A. 基础范围约束
        test_3_probability_valid,
        test_4_probability_out_of_range,
        test_5_probability_fraction_valid,
        test_6_probability_negative,
        test_7_negative_area,
        test_8_non_negative_area_ok,
        test_9_positive_integer_violation,
        test_10_positive_integer_ok,
        # B. 定义约束
        test_11_log_domain_violation,
        test_12_log_valid,
        test_13_division_by_zero,
        test_14_sqrt_negative,
        # C. 解集完整性
        test_15_quadratic_missing_roots,
        test_16_quadratic_both_roots_ok,
        test_17_quadratic_no_all_solutions,
        # D. 极值问题约束
        test_18_feasible_domain_violation,
        test_19_feasible_domain_ok,
        # constraint_score 融入
        test_20_constraint_score_blending,
        test_21_constraint_blending_weight,
        test_22_model_vs_not_overwritten,
        # 不误杀测试
        test_23_no_false_positive_general,
        test_24_multiple_issues,
        test_25_constraint_score_in_parse_output,
        test_26_explicit_domain_param,
        test_27_empty_answer_no_crash,
        test_28_negative_coordinate_not_flagged,
        test_29_probability_zero_valid,
        test_30_probability_one_valid,
        test_31_normal_math_answer_not_affected,
    ]

    for t in tests:
        print(f"\n--- {t.__name__} ---")
        t()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
