from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from math_agent.agents.router import Router
from math_agent.agents.verifier import Verifier
from math_agent.clients.interns1_client import InternS1Client
from math_agent.pipeline import MathAgentPipeline
from math_agent.prompting import default_prompt_config_path, load_prompts
from math_agent.tools.answer_normalizer import (
    canonicalize_final_answer,
    normalize_answer,
)
from math_agent.tools.deterministic_solver import solve_deterministically


@pytest.mark.parametrize(
    ("question", "domain", "problem_type"),
    [
        ("solve ODE: dy/dx = 5y", "ODE", "ode"),
        ("graph theory: how many edges does K_5 have?", "DiscreteMath", "graph_theory"),
        ("directional derivative of f(x,y) = 5x + y", "Calculus", "directional_derivative"),
        ("find eigenvalues of matrix [[1,0],[0,3]]", "Algebra", "eigenvalues"),
        (
            "PDE: solve u_xx + u_yy = 0 and derive the Fourier-series solution.",
            "PDE",
            "proof",
        ),
        ("probability: variance of a fair six-sided die roll", "Probability", "variance"),
    ],
)
def test_router_recognizes_high_value_families(
    question: str, domain: str, problem_type: str
) -> None:
    route = Router().route(question)
    assert route.domain == domain
    assert route.problem_type == problem_type


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("solve: 2x^2 + 24x + 40 = 0", "-10,-2"),
        ("solve inequality: 3x + -14 > 36", "x>50/3"),
        (
            "solve the system: 4x + 3y = -29, 3x + 2y = -21",
            "x=-5,y=-3",
        ),
        (
            "solve the system: x + y = 8, xy = 15",
            "x=3,y=5;x=5,y=3",
        ),
        ("derivative of f(x) = 2x^4 at x = 1", "8"),
        ("definite integral of x^2 from x = 0 to x = 7", "343/3"),
        ("compute the determinant of matrix [[-3,-4],[-2,5]]", "-23"),
        ("find eigenvalues of matrix [[3,0],[0,3]]", "3,3"),
        ("combinatorics: what is the 3rd Catalan number?", "5"),
        (
            "geometry: A circle has radius 14 and a chord is 4 from the "
            "center. Find the chord length.",
            "12*sqrt(5)",
        ),
        ("probability: variance of a fair six-sided die roll", "35/12"),
        ("graph theory: how many edges does a complete graph K_5 have?", "10"),
        (
            "operations research: M/M/1 queue with arrival rate lambda=3 and "
            "service rate mu=5. What is the utilization?",
            "3/5",
        ),
        (
            "operations research: find the max-flow from source S to sink T in "
            "a network with capacity 10 on edge S-A, 5 on S-B, 5 on A-T, "
            "10 on B-T, 4 on A-B",
            "14",
        ),
        (
            "PDE: classify the equation u_xx + u_yy = 0 "
            "(elliptic, parabolic, hyperbolic?)",
            "elliptic",
        ),
        ("solve ODE: dy/dx = 5y, y(0) = 2", "y=2*e^(5*x)"),
        ("solve: 2x^2 + 0x + -18 = 0", "-3,3"),
        ("solve: x^3 + 0x^2 + 0x + 0 = 0", "0"),
        ("number theory: compute euler phi(47)", "46"),
        ("number theory: compute gcd(55, 152)", "1"),
        ("number theory: compute lcm(20, 23)", "460"),
        (
            "number theory: find the least nonnegative solution to "
            "x = 3 mod 5, x = 0 mod 7",
            "28",
        ),
        (
            "number theory: find the least positive multiplicative inverse "
            "of 17 modulo 29",
            "12",
        ),
        ("number theory: how many positive divisors does 106 have?", "4"),
        ("number theory: least nonnegative residue of 5^5 modulo 29", "22"),
        ("number theory: remainder when 145 is divided by 32", "17"),
        (
            "solve the system: 3x + 2y = -25, 3x + 2y = -25",
            "x=-2*y/3-25/3",
        ),
    ],
)
def test_deterministic_solver_handles_strict_templates(
    question: str, expected: str
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


def test_deterministic_solver_never_short_circuits_proof_mode() -> None:
    assert (
        solve_deterministically(
            "topology: Prove that (0,1) is homeomorphic to R.",
            problem_type="proof",
            domain="Topology",
        )
        is None
    )


def test_functional_equation_uses_proof_solver() -> None:
    route = Router().route(
        "Find all functions f: R -> R such that f(x+y)=f(x)+f(y), "
        "given f is continuous."
    )
    assert route.problem_type == "functional_equation"
    assert route.recommended_solver == "proof"


def test_topology_concept_question_is_not_forced_into_proof_mode() -> None:
    route = Router().route("topology: Is R connected?")
    assert route.problem_type == "topology_conceptual"
    assert route.recommended_solver != "proof"


def test_final_answer_canonicalization_removes_root_wrappers() -> None:
    assert (
        canonicalize_final_answer(
            "[-2, -10]",
            problem_type="quadratic_equation",
            question="solve: 2x^2 + 24x + 40 = 0",
        )
        == "-10,-2"
    )
    assert (
        canonicalize_final_answer(
            "[x=-4, y=-2]",
            problem_type="linear_system",
            question="solve the system",
        )
        == "x=-4,y=-2"
    )


def test_normalizer_preserves_coordinate_commas_and_prose_spaces() -> None:
    assert normalize_answer("(243,810)") == "(243,810)"
    assert (
        normalize_answer("number of walks of length 3")
        == "number of walks of length 3"
    )
    assert normalize_answer("1,000") == "1000"


def test_packaged_prompt_config_matches_submission_config() -> None:
    assert load_prompts(default_prompt_config_path()) == load_prompts(
        Path("configs/prompts.yaml")
    )


def test_verifier_recomputes_question_instead_of_accepting_self_consistency() -> None:
    verifier = Verifier(client=Mock(), mock=False)
    wrong = verifier._tool_verify(
        "The result is \\boxed{7}.",
        "7",
        question="solve: 2x + 1 = 5",
        route_info={"problem_type": "linear_equation"},
    )
    correct = verifier._tool_verify(
        "The result is \\boxed{2}.",
        "2",
        question="solve: 2x + 1 = 5",
        route_info={"problem_type": "linear_equation"},
    )
    assert wrong is not None and not wrong.passed
    assert correct is not None and correct.passed


def test_false_proof_is_not_accepted_by_keyword_structure_alone() -> None:
    client = Mock()
    client.chat.return_value = (
        '{"method":"logic_review","passed":false,'
        '"notes":"The argument assumes the conclusion and is invalid."}'
    )
    verifier = Verifier(client=client, mock=False)
    result = verifier.verify(
        "Prove that 1 = 2.",
        "Proof. Assume 1 = 2. Therefore 1 = 2. QED.",
        "1=2",
        {"domain": "GeneralReasoning", "problem_type": "proof"},
    )
    assert not result.passed
    client.chat.assert_called_once()


def test_client_retries_transient_http_statuses() -> None:
    responses = [
        Mock(status_code=500, headers={}, text="busy"),
        Mock(status_code=429, headers={}, text="slow down"),
        Mock(
            status_code=200,
            headers={},
            json=Mock(return_value={"choices": [{"message": {"content": "ok"}}]}),
        ),
    ]
    for response in responses:
        response.raise_for_status = Mock()
    client = InternS1Client(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        max_retries=3,
    )
    with patch("math_agent.clients.interns1_client.requests.post", side_effect=responses):
        with patch("math_agent.clients.interns1_client.time.sleep"):
            assert client.chat([{"role": "user", "content": "hi"}]) == "ok"


def test_fast_mode_keeps_a_complete_proof_as_a_successful_proof() -> None:
    client = Mock()
    client.model = "test-model"
    client.chat.side_effect = [
        (
            "Proof. Let n be arbitrary. By the binomial theorem, "
            "C(n,0)+...+C(n,n)=(1+1)^n=2^n. "
            "Therefore the claimed identity holds. QED."
        ),
        (
            '{"method":"logic_review","passed":true,'
            '"notes":"The binomial-theorem proof is valid."}'
        ),
    ]
    pipeline = MathAgentPipeline(
        client=client,
        mock=False,
        enable_tools=True,
        run_mode="fast",
        save_trace=False,
        max_refine_rounds=0,
    )
    result = pipeline.solve(
        "comprehensive reasoning: prove that the sum of binomial coefficients "
        "C(n,0)+C(n,1)+...+C(n,n) = 2^n",
        "proof-case",
    )
    assert result.status == "success"
    assert result.final_answer.type == "proof"
    assert result.final_answer.value
    assert result.verification.passed
    assert client.chat.call_count == 2


def test_unverified_mock_proof_is_partial_but_keeps_a_response() -> None:
    pipeline = MathAgentPipeline(
        mock=True,
        enable_tools=True,
        run_mode="fast",
        save_trace=False,
        max_refine_rounds=0,
    )
    result = pipeline.solve("Prove that 1 = 1.", "mock-proof")
    assert result.status == "partial"
    assert not result.verification.passed
    assert result.final_answer.value
