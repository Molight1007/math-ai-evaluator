"""Tests for Planner module."""

from agents.planner import Planner, rule_create_plan
from user_agent import ReasoningAgent


class FakeClient:
    def chat(self, messages, temperature=0.2, max_tokens=4096):
        return "步骤1：分析条件\n步骤2：选择方法\n步骤3：验证结果"


def test_algebra_plan_non_empty():
    planner = Planner(client=None)
    profile = {"subject": "algebra", "problem_type": "calculation"}
    plan = planner.create_plan("有限域问题", {}, profile)
    assert isinstance(plan, str)
    assert plan.strip()
    assert "代数" in plan or "子域" in plan or "同态" in plan


def test_proof_plan_contains_proof_hint():
    planner = Planner(client=None)
    profile = {"subject": "analysis", "problem_type": "proof"}
    plan = planner.create_plan("证明连续函数性质", {}, profile)
    assert "证明" in plan


def test_rule_create_plan_algebra():
    plan = rule_create_plan("test", {"subject": "algebra"})
    assert plan


def test_planner_client_none_no_error():
    planner = Planner(client=None)
    plan = planner.create_plan("计算 1+1", {}, {"subject": "other"})
    assert isinstance(plan, str)
    assert plan


def test_planner_does_not_break_solve():
    class SolveFakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            return "推理过程\n最终答案：42"

    agent = ReasoningAgent(client=SolveFakeClient())
    result = agent.solve("计算40+2", {})
    assert result["final_response"] == "42"
    steps = [t["step"] for t in result["trace"]]
    assert "plan" in steps


def test_llm_invalid_plan_falls_back_to_rules():
    class BadPlanClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            return "用户要求制定解题计划。最终答案是72。"

    planner = Planner(client=BadPlanClient())
    profile = {"subject": "algebra", "problem_type": "calculation"}
    plan = planner.create_plan("有限域问题", {}, profile)
    assert "代数" in plan or "子域" in plan
    assert "最终答案" not in plan


def test_planner_with_fake_client():
    planner = Planner(client=FakeClient())
    plan = planner.create_plan("求极限", {}, {"subject": "analysis"})
    assert "步骤" in plan
