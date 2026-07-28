from __future__ import annotations

import pytest

from math_agent.agents.router import Router


@pytest.mark.parametrize(
    ("question", "domain", "problem_type"),
    [
        (
            "Find all real roots of x^2 + x - 2 = 0.",
            "Algebra",
            "quadratic_equation",
        ),
        (
            "Find the remainder when x^3 - 3x^2 + 2x + 1 is divided by x - (-3).",
            "Algebra",
            "polynomial_remainder",
        ),
        (
            "Find the sum of the interior angles, in degrees, of a convex 7-gon.",
            "Geometry",
            "polygon_angles",
        ),
        (
            "Find the slope of the line through (-7,-9) and (-6,-15).",
            "Geometry",
            "slope",
        ),
        (
            "Compute d/dx[(x-4)^2] at x=-2.",
            "Calculus",
            "chain_rule",
        ),
        (
            "Find the z-component of curl F for F=(-2y,x,0).",
            "Calculus",
            "curl",
        ),
        (
            "Compute det([[1,-7],[-1,2]]).",
            "Algebra",
            "determinant",
        ),
        (
            "Find the median of the five observations [5, -2, 7, 1, 3].",
            "Probability",
            "median",
        ),
        (
            "How many nonnegative integer solutions satisfy x1+...+x2=8?",
            "Combinatorics",
            "stars_and_bars",
        ),
        (
            "Find the least nonnegative x satisfying x congruent to 3 (mod 5).",
            "NumberTheory",
            "congruence",
        ),
        (
            "How many edges does the complete graph K_4 have?",
            "DiscreteMath",
            "complete_graph",
        ),
        (
            "Find the Wronskian at x=0 of exp(-3x) and exp(4x).",
            "Calculus",
            "wronskian",
        ),
        (
            "Compute the Laplacian of u(x,y)=x^2+2y^2-3xy.",
            "PDE",
            "laplacian",
        ),
        (
            "Find Re[(-6+i)(1+5i)].",
            "ComplexAnalysis",
            "real_part",
        ),
        (
            "Does sum_(n=1)^infinity 1/n^(11/10) converge? Answer yes or no.",
            "Calculus",
            "series_convergence",
        ),
        (
            "Find the closure in R of the finite set {-2,1,3}.",
            "Topology",
            "closure",
        ),
        (
            "Find the minimum assignment cost for matrix [[4,2],[3,6]].",
            "OperationsResearch",
            "assignment",
        ),
        (
            "Prove that among any 4 integers, two have the same remainder modulo 3.",
            "Combinatorics",
            "proof",
        ),
    ],
)
def test_router_recognizes_independent_dataset_families(
    question: str, domain: str, problem_type: str
) -> None:
    route = Router().route(question)

    assert route.domain == domain
    assert route.problem_type == problem_type


@pytest.mark.parametrize(
    ("question", "domain", "problem_type"),
    [
        ("solve ODE: dy/dx = 5y", "ODE", "ode"),
        (
            "graph theory: how many edges does K_5 have?",
            "DiscreteMath",
            "graph_theory",
        ),
        ("topology: Is R connected?", "Topology", "topology_conceptual"),
    ],
)
def test_router_preserves_explicit_legacy_routes(
    question: str, domain: str, problem_type: str
) -> None:
    route = Router().route(question)

    assert route.domain == domain
    assert route.problem_type == problem_type


def test_router_uses_typed_low_confidence_fallback() -> None:
    route = Router().route("Determine whether this mathematical construction is valid.")

    assert route.domain != "Unknown"
    assert route.problem_type != "unknown"
    assert route.confidence <= 0.3


def test_generic_proof_keeps_subject_domain_detection() -> None:
    route = Router().route("Prove that every tree with n vertices has n-1 edges.")

    assert route.domain == "DiscreteMath"
    assert route.problem_type == "proof"
