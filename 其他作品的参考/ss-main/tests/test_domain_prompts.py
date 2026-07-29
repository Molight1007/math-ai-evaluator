"""Tests for domain-specific solver prompt routing."""

from __future__ import annotations

from prompts.solver_prompts import (
    build_routed_solver_prompt,
    build_solver_prompt,
    get_solver_prompt_route,
    select_solver_prompt_builder,
)
from prompts.domain_prompts import (
    build_algebra_solver_prompt,
    build_analysis_solver_prompt,
    build_choice_solver_prompt_specialized,
    build_combinatorics_solver_prompt,
    build_optimization_solver_prompt,
    build_probability_solver_prompt,
    build_proof_solver_prompt_specialized,
)


def _prompt(profile: dict) -> str:
    return build_routed_solver_prompt(
        problem="示例题目",
        profile=profile,
        plan="按步骤求解",
        candidate_id="candidate_1",
    )


def test_algebra_routed_prompt():
    text = _prompt({"subject": "algebra", "problem_type": "calculation"})
    assert any(k in text for k in ("代数", "有限域", "子群"))
    assert "最终答案" in text
    assert get_solver_prompt_route({"subject": "algebra"}) == "algebra"


def test_analysis_routed_prompt():
    text = _prompt({"subject": "analysis", "problem_type": "calculation"})
    assert any(k in text for k in ("定义域", "收敛", "极限"))
    assert "最终答案" in text


def test_probability_routed_prompt():
    text = _prompt({"subject": "probability", "problem_type": "calculation"})
    assert any(k in text for k in ("样本空间", "独立性"))
    assert "最终答案" in text


def test_combinatorics_routed_prompt():
    text = _prompt({"subject": "combinatorics", "problem_type": "calculation"})
    assert any(k in text for k in ("计数", "重复计数"))
    assert "最终答案" in text


def test_optimization_routed_prompt():
    text = _prompt({"subject": "optimization", "problem_type": "calculation"})
    assert any(k in text for k in ("目标函数", "约束"))
    assert "最终答案" in text


def test_proof_priority_over_subject():
    profile = {"subject": "analysis", "problem_type": "proof"}
    assert get_solver_prompt_route(profile) == "proof"
    assert select_solver_prompt_builder(profile) is build_proof_solver_prompt_specialized
    text = _prompt(profile)
    assert "证明" in text
    assert "最终答案" in text


def test_choice_priority_over_subject():
    profile = {"subject": "algebra", "problem_type": "choice"}
    assert get_solver_prompt_route(profile) == "choice"
    assert select_solver_prompt_builder(profile) is build_choice_solver_prompt_specialized
    text = _prompt(profile)
    assert "选项" in text
    assert "最终答案" in text


def test_unknown_profile_falls_back_default():
    profile = {"subject": "other", "problem_type": "other"}
    assert get_solver_prompt_route(profile) == "default"
    assert select_solver_prompt_builder(profile) is build_solver_prompt
    text = _prompt(profile)
    assert "最终答案" in text


def test_all_domain_builders_contain_final_answer_marker():
    builders = [
        build_algebra_solver_prompt,
        build_analysis_solver_prompt,
        build_probability_solver_prompt,
        build_combinatorics_solver_prompt,
        build_optimization_solver_prompt,
        build_proof_solver_prompt_specialized,
        build_choice_solver_prompt_specialized,
        build_solver_prompt,
    ]
    for builder in builders:
        text = builder(problem="题", profile={}, plan="计划", candidate_id="candidate_1")
        assert "最终答案" in text
