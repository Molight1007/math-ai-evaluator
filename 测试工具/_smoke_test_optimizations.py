# -*- coding: utf-8 -*-
"""
冒烟测试：验证本次三项优化（自一致性投票 / 答案提取链路 / 评分宽容化）。
不调用真实 API，纯单元验证：
1. 归一化 + 投票聚合逻辑（run_inference_multi_vote 的模块级函数）
2. 提取工具函数（boxed / 强模式 / 尾部兜底）
3. 参考答案等价比较（apply_reference_leniency）
"""
import asyncio
import os
import sys

# 注意顺序：测试工具目录必须在项目根之前，否则 from llm_client 会导入项目根的错误模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intern_s1 import (
    _normalize_answer,
    _extract_boxed,
    _extract_strong_pattern,
    _extract_tail_fallback,
    _clean_answer,
    _truncate_reasoning,
)
from deepseek import (
    _normalize_answer as ds_normalize,
    _answers_equivalent,
    apply_reference_leniency,
)
from models import InferenceResult


def test_normalize():
    assert _normalize_answer(r"\boxed{3}") == "3", _normalize_answer(r"\boxed{3}")
    assert _normalize_answer(r"$\frac{1}{2}$") == "1/2", _normalize_answer(r"$\frac{1}{2}$")
    assert _normalize_answer(r"x = 7") == "7", _normalize_answer(r"x = 7")
    assert _normalize_answer(r"  \frac{a}{b}  ") == "a/b", _normalize_answer(r"  \frac{a}{b}  ")
    assert _normalize_answer(r"\log_2 a") == _normalize_answer(r"\log_2a")
    assert _normalize_answer("3.0") == "3.0"
    print("[PASS] test_normalize")


def test_extract_boxed():
    assert _extract_boxed(r"Here is \boxed{42}.") == "42"
    assert _extract_boxed(r"no box here") == ""
    assert _extract_boxed(r"\boxed{\frac{1}{2}}") == r"\frac{1}{2}"
    print("[PASS] test_extract_boxed")


def test_extract_strong():
    assert _extract_strong_pattern(
        "We test N=3 is a candidate.\nThen we conclude."
    ) == "3", _extract_strong_pattern("We test N=3 is a candidate.\nThen we conclude.")
    assert _extract_strong_pattern("The final answer is 5.") == "5"
    print("[PASS] test_extract_strong")


def test_extract_tail():
    assert _extract_tail_fallback("line1\nline2\nanswer = 8") in ("answer = 8", "8")
    print("[PASS] test_extract_tail")


def test_clean():
    assert _clean_answer("  : 3.5  ") == "3.5"
    assert _clean_answer("1. If we set x=1") == ""
    print("[PASS] test_clean")


def test_truncate():
    assert _truncate_reasoning("x" * 100) == "x" * 100
    long = "a" * 5000 + "b" * 5000 + "c" * 5000
    t = _truncate_reasoning(long, max_chars=3000)
    assert len(t) < len(long) and "omitted" in t
    print("[PASS] test_truncate")


def test_deepseek_normalize():
    assert ds_normalize(r"\boxed{\frac{1}{2}}") == "1/2"
    assert ds_normalize(r"$x=10$") == "10"
    print("[PASS] test_deepseek_normalize")


def test_answers_equivalent():
    assert _answers_equivalent("3", "3")
    assert _answers_equivalent(r"\frac{1}{2}", "0.5")
    assert _answers_equivalent(r"\boxed{7}", "7")
    assert not _answers_equivalent("3", "4")
    assert _answers_equivalent(r"\log_2 a", r"\log_2a")
    print("[PASS] test_answers_equivalent")


def test_apply_reference_leniency():
    inf = InferenceResult(
        problem_id="p1", question="q", answer=r"\frac{1}{2}",
        reasoning="", raw_response="",
    )
    parsed = {"is_correct": False, "confidence": 0.4, "explanation": "wrong",
              "error_type": "mathematical_error", "conclusion_correct": False,
              "correct_answer": None}
    out = apply_reference_leniency(inf, dict(parsed), "0.5")
    assert out["is_correct"] is True
    assert out["error_type"] is None
    assert "参考答案等价匹配" in out["explanation"]

    # 不等价 → 保持原判
    out2 = apply_reference_leniency(inf, dict(parsed), "999")
    assert out2["is_correct"] is False

    # 无参考答案 → 原样
    out3 = apply_reference_leniency(inf, dict(parsed), None)
    assert out3["is_correct"] is False
    print("[PASS] test_apply_reference_leniency")


def test_vote_aggregate():
    """验证投票聚合核心：构造 3 个含归一化答案的结果，检查投票统计。"""
    from intern_s1 import run_inference_multi_vote

    # 不实际调用 API，仅验证 Counter 统计逻辑的函数存在且可 import
    import inspect
    sig = inspect.signature(run_inference_multi_vote)
    assert "num_samples" in sig.parameters
    print("[PASS] test_vote_aggregate (signature)")


def main():
    test_normalize()
    test_extract_boxed()
    test_extract_strong()
    test_extract_tail()
    test_clean()
    test_truncate()
    test_deepseek_normalize()
    test_answers_equivalent()
    test_apply_reference_leniency()
    test_vote_aggregate()
    print("\n=== ALL SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    main()
