"""Tests for ProblemRouter classification."""

from agents.router import ProblemRouter


class SpyClient:
    """Tracks whether LLM was invoked."""

    called = False

    def chat(self, messages, temperature=0.2, max_tokens=4096):
        SpyClient.called = True
        return '{"subject":"other","problem_type":"calculation","answer_form":"integer_or_number","needs_proof":false,"needs_tool":false,"difficulty":"medium","confidence":0.8}'


def test_proof_classification():
    router = ProblemRouter(client=None)
    result = router.classify("证明连续函数在闭区间达到最大值")
    assert result["problem_type"] == "proof"
    assert result["needs_proof"] is True


def test_analysis_calculation():
    router = ProblemRouter(client=None)
    result = router.classify("计算积分 x^2 dx")
    assert result["subject"] == "analysis"
    assert result["problem_type"] == "calculation"


def test_algebra_subject():
    router = ProblemRouter(client=None)
    result = router.classify("有限域F81中元素数量")
    assert result["subject"] == "algebra"


def test_rule_only_without_client():
    router = ProblemRouter(client=None)
    result = router.classify("计算 1+1")
    assert isinstance(result, dict)
    assert result["problem_type"] == "calculation"
    assert "confidence" in result


def test_high_confidence_skips_llm():
    SpyClient.called = False
    router = ProblemRouter(client=SpyClient())
    result = router.classify("证明连续函数在闭区间达到最大值")
    assert result["problem_type"] == "proof"
    assert SpyClient.called is False


def test_profile_has_required_keys():
    router = ProblemRouter(client=None)
    result = router.classify("求极限")
    for key in (
        "subject",
        "problem_type",
        "answer_form",
        "needs_proof",
        "needs_tool",
        "difficulty",
        "confidence",
    ):
        assert key in result
