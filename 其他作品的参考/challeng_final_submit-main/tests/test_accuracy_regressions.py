from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from math_agent.agents.proof_guardian import check_proof_structure
from math_agent.agents.router import Router
from math_agent.evaluation.judge import short_answer_match, symbolic_match
from math_agent.evaluation.metrics import evaluate_results
from math_agent.pipeline import MathAgentPipeline
from math_agent.tools.deterministic_solver import solve_deterministically


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Solve y'=-3y with y(0)=2.", "y=2*exp(-3*x)"),
        ("Solve y'=-6 with y(0)=1.", "y=-6*x+1"),
        ("Solve y'+y=2 with y(0)=-3.", "y=2-5*exp(-x)"),
        (
            "Solve y''+4y=0 with y(0)=-3, y'(0)=4.",
            "y=-3*cos(2*x)+2*sin(2*x)",
        ),
        ("Solve y'=6x^2y with y(0)=2.", "y=2*exp(2*x^3)"),
        ("Solve y'=6x with y(0)=-1.", "y=3*x^2-1"),
        ("Find all equilibrium solutions of y'=3y(1-y/10).", "0,10"),
        (
            "For y'=-4y, find the positive time at which a nonzero solution "
            "is half its initial value.",
            "ln(2)/4",
        ),
        ("Solve y''=4, y'(0)=-3, y(0)=5.", "y=2*x^2-3*x+5"),
        (
            "For the homogeneous linear ODE y'+2y=0, determine the solution "
            "anchored by y(2)=3.",
            "y=3*exp(-2*(x-2))",
        ),
        ("Solve y'=exp(x) with y(0)=-4.", "y=exp(x)-5"),
        ("Find the characteristic roots of y''-y'-6y=0.", "-2,3"),
        ("Find the Wronskian at x=0 of exp(-2x) and exp(5x).", "7"),
        ("Find the Wronskian at x=0 of exp(0) and exp(7x).", "7"),
        (
            "Give the general solution on x>0 of x^2 y''-9x y'+16y=0.",
            "y=C1*x^2+C2*x^8",
        ),
    ],
)
def test_deterministic_solver_covers_independent_ode_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


def test_deterministic_solver_does_not_guess_malformed_separable_ode() -> None:
    assert solve_deterministically("Solve y'=2x^y with y(0)=1.") is None


@pytest.mark.parametrize(
    ("prediction", "gold", "problem_type"),
    [
        ("2*e^{-3*x}", "y=2*exp(-3x)", "ode"),
        ("y(t)=-3*cos(2*t)+2*sin(2*t)", "y=-3*cos(2x)+2*sin(2x)", "second_order_ode"),
        ("[2,-1]", "-1,2", "characteristic_equation"),
        ("[0,8]", "0,8", "logistic_ode"),
        ("ln2/3", "ln(2)/3", "exponential_decay"),
        ("y=C_1*x^7+C_2*x", "y=C1*x+C2*x^7", "euler_cauchy_ode"),
        ("y=C_1*x^{10}+C_2*x^4", "y=C1*x^4+C2*x^10", "euler_cauchy_ode"),
        ("y(t)=-4*cost+sint", "y=-4*cos(x)+sin(x)", "second_order_ode"),
    ],
)
def test_short_answer_match_accepts_ode_notation_equivalence(
    prediction: str,
    gold: str,
    problem_type: str,
) -> None:
    assert short_answer_match(
        prediction,
        gold,
        problem_type=problem_type,
        domain="ODE",
    )


@pytest.mark.parametrize(
    ("prediction", "gold", "problem_type"),
    [
        ("y=2*exp(-2*x)", "y=2*exp(-3*x)", "ode"),
        ("[-1,3]", "-1,2", "characteristic_equation"),
        ("y=C1*x+C2*x^6", "y=C1*x+C2*x^7", "euler_cauchy_ode"),
    ],
)
def test_short_answer_match_rejects_wrong_ode_answers(
    prediction: str,
    gold: str,
    problem_type: str,
) -> None:
    assert not short_answer_match(
        prediction,
        gold,
        problem_type=problem_type,
        domain="ODE",
    )


def test_pipeline_short_circuits_model_for_second_order_ode() -> None:
    client = Mock()
    client.model = "must-not-be-called"
    pipeline = MathAgentPipeline(
        client=client,
        mock=False,
        enable_tools=True,
        run_mode="fast",
        save_trace=False,
        max_refine_rounds=0,
    )

    result = pipeline.solve("Solve y''=4, y'(0)=-3, y(0)=5.", "ode-tool")

    assert result.status == "success"
    assert result.final_answer.value == "y=2*x^2-3*x+5"
    assert result.verification.passed
    client.chat.assert_not_called()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute det([[1,-7],[-1,2]]).", "-5"),
        ("Find the rank of [[1,-7],[2,-14]].", "1"),
        (
            "Add matrices [(1,-7),(-1,2)] and [(2,3),(0,0)].",
            "[(3,-4),(-1,2)]",
        ),
        (
            "Multiply [(1,-7),(-1,2)] by [(1,2),(1,1)].",
            "[(-6,-5),(1,0)]",
        ),
        ("Compute the dot product of (1,-7,-1) and (2,-2,1).", "15"),
        ("Compute (1,-7,-1) cross (2,-2,1).", "(-9,-3,12)"),
        ("Compute -2(1,-7) + (-1,2).", "(-3,16)"),
        (
            "Find the eigenvalues of the upper triangular matrix [[-4,0],[0,3]].",
            "-4,3",
        ),
        ("Find the trace of [[-3,1,0],[0,1,2],[3,0,5]].", "3"),
        (
            "Find the inverse of [[1,-7],[-1,2]].",
            "[(-2/5,-7/5),(-1/5,-1/5)]",
        ),
        (
            "Solve [[1,-7],[-1,2]] [x,y]^T = [22,-2]^T.",
            "x=-6,y=-4",
        ),
        (
            "Give the characteristic polynomial in lambda for [[1,-7],[-1,2]].",
            "lambda^2-3*lambda-5",
        ),
        ("Find the Euclidean norm of vector (3,4).", "5"),
        ("Find the scalar projection of u=(-2,1) onto v=(3,4).", "-2/5"),
    ],
)
def test_deterministic_solver_covers_independent_linear_algebra_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Solve x^3 - 6x^2 + 3x + 10 = 0 over the reals.", "-1,2,5"),
        ("Find every real zero of x^4 - 26x^2 + 25.", "-5,-1,1,5"),
        (
            "Factor x^2 - x - 2 completely over the integers.",
            "(x+1)(x-2)",
        ),
        (
            "Find the remainder when x^3 - 3x^2 + 2x + 1 is divided by x - (-3).",
            "-59",
        ),
        ("Solve 2/x + (-2) = -1, with x != 0.", "x=2"),
        (
            "Real numbers x,y satisfy x+y=-3 and xy=-4. Compute x^2+y^2.",
            "17",
        ),
        ("Use the quadratic formula to solve 2x^2 - 2x - 4 = 0.", "-1,2"),
        ("Find all x such that |x - (-5)| = 2.", "-7,-3"),
        (
            "Which real root of x^3 + 12x^2 + 21x - 98 = 0 has multiplicity two?",
            "-7",
        ),
        ("Find k if x=1 is a root of x^2 + kx + (-5) = 0.", "4"),
        ("Solve x^2 - 4 = 0.", "-2,2"),
        (
            "The nonzero roots of x^2 - (1)x + (-2) = 0 are r,s. Find 1/r + 1/s.",
            "-1/2",
        ),
        ("Evaluate P(-2) for P(x)=x^3 + 2x^2 - 2x + 4.", "8"),
        (
            "Find the monic polynomial gcd of x^2 + 4x - 12 and x^2 + 8x + 12.",
            "x+6",
        ),
    ],
)
def test_deterministic_solver_covers_equations_polynomials_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute the arithmetic mean of [1, 3, 2, 1, 3].", "2"),
        ("Find the median of the five observations [5, -2, 7, 1, 3].", "3"),
        ("Find the variance of one fair roll of a die numbered 1 through 4.", "5/4"),
        (
            "Find the expected value of one fair roll of a die numbered 1 through 5.",
            "3",
        ),
        ("For X~Binomial(n=5,p=1/2), compute P(X=0).", "1/32"),
        (
            "A fair coin is tossed 5 times. Find the probability of exactly 1 heads.",
            "5/32",
        ),
        (
            "Independent trials succeed with probability 1/3. Find the probability "
            "of at least one success in 2 trials.",
            "5/9",
        ),
        ("Given P(A and B)=1/12 and P(B)=1/3, compute P(A|B).", "1/4"),
        (
            "Independent events have P(A)=1/6 and P(B)=1/8. Find P(A and B).",
            "1/48",
        ),
        (
            "An urn has 3 red and 5 blue balls. Two are drawn without replacement. "
            "Find the probability both are red.",
            "3/28",
        ),
        (
            "Trials are repeated until first success, with success probability 1/2. "
            "Find the expected trial count.",
            "2",
        ),
        ("If X is Poisson with rate lambda=1, give P(X=0).", "exp(-1)"),
        ("Find the range (maximum minus minimum) of [-5, 1, -3, 2, 7].", "12"),
        ("Values 2 and 5 have weights 1 and 2. Find their weighted mean.", "4"),
    ],
)
def test_deterministic_solver_covers_probability_statistics_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute (-6+i)+(1+5i).", "-5+6i"),
        ("Compute (-6+i)(1+5i).", "-11-29i"),
        ("Find the complex conjugate of -6+i.", "-6-i"),
        ("Find the modulus of 3+4i.", "5"),
        ("Compute i^7.", "-i"),
        ("Evaluate exp(i*pi*1/2).", "i"),
        ("Find all real-valued complex roots of z^2=4.", "-2,2"),
        (
            "Evaluate the positively oriented contour integral of -5/z around |z|=1.",
            "-10*pi*i",
        ),
        ("Find the residue at z=-4 of 2/(z+4).", "2"),
        (
            "Evaluate integral_|z|=3 z/(z-1) dz counterclockwise.",
            "2*pi*i",
        ),
        ("Compute 1/(3+4i) in a+bi form.", "3/25-4/25i"),
        ("Find Re[(-6+i)(1+5i)].", "-11"),
        ("Give the principal argument of 1i.", "pi/2"),
        ("Find both roots of z^2+8z+17=0.", "-4-i,-4+i"),
    ],
)
def test_deterministic_solver_covers_complex_analysis_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Classify u_xx+2u_yy=0 as elliptic, hyperbolic, or parabolic.",
            "elliptic",
        ),
        (
            "Classify 2u_xx-3u_yy=0 as elliptic, hyperbolic, or parabolic.",
            "hyperbolic",
        ),
        (
            "Classify 3u_xx+0u_yy=0 as elliptic, hyperbolic, or parabolic.",
            "parabolic",
        ),
        (
            "Solve u''(x)=0 on [0,2] with u(0)=-4, u(2)=3.",
            "u(x)=7/2*x-4",
        ),
        ("For u_tt=4u_xx, identify the positive wave speed.", "2"),
        (
            "For u_t=u_xx on (0,2) with zero endpoints, give the positive "
            "decay-rate coefficient multiplying pi^2 for sine mode n=1.",
            "1/4",
        ),
        ("Compute the Laplacian of u(x,y)=x^2+2y^2-3xy.", "6"),
    ],
)
def test_deterministic_solver_covers_pde_short_answer_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


def test_deterministic_solver_refuses_malformed_pde_classification() -> None:
    question = "Classify 3u_xxu_yy=0 as elliptic, hyperbolic, or parabolic."
    assert solve_deterministically(question) is None


@pytest.mark.parametrize(
    "question",
    [
        (
            "On 0<x<2, solve u_t=u_xx with zero endpoints and initial sine "
            "data; derive the separated solution."
        ),
        (
            "Derive by characteristics and verify the solution of "
            "u_t-3u_x=0 on R with u(x,0)=x+1."
        ),
        (
            "Derive the Fourier-sine-series solution for u_t=u_xx on 0<x<2 "
            "with zero endpoint values and initial data f(x)."
        ),
    ],
)
def test_router_marks_pde_derivations_as_proofs(question: str) -> None:
    route = Router().route(question)
    assert route.domain == "PDE"
    assert route.problem_type == "proof"
    assert route.recommended_solver == "proof"


def test_proof_structure_accepts_standard_pde_derivation_language() -> None:
    question = (
        "For a smooth solution of u_t=3u_xx with zero endpoints, prove that "
        "the squared-energy integral is nonincreasing."
    )
    proof = (
        "For a smooth solution with the stated boundary conditions, define "
        "E(t)=integral u^2 dx. Differentiate and substitute u_t=3u_xx. "
        "By integration by parts, E'(t)=-6 integral u_x^2 dx<=0. "
        "Thus E is nonincreasing. QED."
    )
    assert check_proof_structure(question, proof).passed


def test_proof_structure_accepts_verified_solution_with_final_answer_heading() -> None:
    question = (
        "Derive by characteristics and verify u_t-3u_x=0 with the initial "
        "condition u(x,0)=x+15."
    )
    proof = (
        "Use characteristics to obtain x_0=x+3t, so u(x,t)=x+3t+15. "
        "Substitute: u_t-3u_x=3-3=0, and the initial condition is satisfied. "
        "Final Answer: u(x,t)=x+3t+15."
    )
    assert check_proof_structure(question, proof).passed


def test_proof_structure_still_rejects_a_shallow_assertion() -> None:
    verification = check_proof_structure(
        "Prove that the wave energy is conserved.",
        "The result is true. QED.",
    )
    assert not verification.passed


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Solve the linear equation 2x - 3 = -17.", "-7"),
        ("Solve the inequality 2x - 9 > -19.", "x>-5"),
        ("Find all real roots of x^2 + x - 2 = 0.", "-2,1"),
        (
            "Solve the system 2x + y = -19, x + 3y = -22.",
            "x=-7,y=-5",
        ),
        ("Evaluate x^2 - 8x - 9 at x = -3.", "24"),
        ("Compute the integer power 2^2.", "4"),
        ("Simplify sqrt(9) + (-6).", "-3"),
        (
            "A number is multiplied by 3, then -11 is added, giving -23. "
            "What is the number?",
            "-4",
        ),
        (
            "An arithmetic progression has first term -3 and common difference 2. "
            "Find its 6th term.",
            "7",
        ),
        (
            "A geometric progression starts at 1 with ratio 2. Find term number 4.",
            "8",
        ),
        ("Compute and reduce the fraction 2/3 + 1/4.", "11/12"),
        ("A price of 40 is increased by 5%. What is the new price?", "42"),
        ("Solve |2x - 4| = 3.", "1/2,7/2"),
        ("Solve |6x| = 7.", "-7/6,7/6"),
        (
            "Let f(x) = 2x - 6 and g(x) = x + 3. Compute f(g(-4)).",
            "-8",
        ),
    ],
)
def test_deterministic_solver_covers_elementary_algebra_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


def test_deterministic_solver_refuses_malformed_absolute_value_question() -> None:
    assert solve_deterministically("Solve |5x - | = 6.") is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Is (-8,3) open in the standard topology of R? Answer yes or no.",
            "yes",
        ),
        (
            "Is [-8,3] compact in the standard topology of R? Answer yes or no.",
            "yes",
        ),
        (
            "Is the interval [-8,3] connected as a subspace of R? Answer yes or no.",
            "yes",
        ),
        ("Give the fundamental group of the 1-torus (S).", "Z"),
        ("Give the fundamental group of the 4-torus (S)^4.", "Z^4"),
        (
            "Does d(x,y)=3|x-y| define a metric on R? Answer yes or no.",
            "yes",
        ),
        (
            "For continuous f:R->R given by f(x)=x^3, is f^(-1)(U) open "
            "whenever U is open? Answer yes or no.",
            "yes",
        ),
        ("Find the closure in R of the finite set {-2,1,3}.", "{-2,1,3}"),
        ("Find the interior in R of [-8,3].", "(-8,3)"),
        ("Find the boundary in R of [-8,3].", "{-8,3}"),
        (
            "Is [-8,3]x[-3,5] compact in R^2? Answer yes or no.",
            "yes",
        ),
        ("For p:S->S, p(z)=z^2, how many sheets does this covering have?", "2"),
        (
            "Find the Euler characteristic of a closed orientable surface of genus 0.",
            "2",
        ),
    ],
)
def test_deterministic_solver_covers_topology_short_answer_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "A 0-1 knapsack has items (weight,value)=[(1, 3), (2, 5), (3, 4)] "
            "and capacity 5. Find the maximum value.",
            "9",
        ),
        (
            "Maximize 2x+3y subject to x+y<=6, x>=0, y>=0. Give the optimum value.",
            "18",
        ),
        (
            "Minimize 2x+3y subject to x+y>=7, x>=0, y>=0. Give the optimum value.",
            "14",
        ),
        (
            "A network has costs A-B=2, B-D=5, A-C=3, C-D=4, A-D=12. "
            "Find the minimum A-D path cost.",
            "7",
        ),
        (
            "A flow network has only arcs s-a=3, a-t=4, s-b=5, b-t=6. "
            "Find the max s-t flow.",
            "8",
        ),
        (
            "In EOQ, annual demand D=5, ordering cost S=5, and holding cost H=2. "
            "Compute sqrt(2DS/H).",
            "5",
        ),
        ("For an M/M/1 queue with lambda=2 and mu=7, find utilization rho.", "2/7"),
        (
            "A transportation model has supplies [8, 9] and demands [5, 6]. "
            "Assuming feasibility, how many total units must be shipped to meet "
            "all demand?",
            "11",
        ),
        (
            "Find the minimum assignment cost for matrix "
            "[[4, 2, 9], [3, 6, 4], [7, 1, 5]] "
            "(one entry per row and column).",
            "9",
        ),
        (
            "A project has two parallel start-to-finish paths with activity "
            "durations [2, 4, 3] and [3, 5]. Find project duration.",
            "9",
        ),
        (
            "Constant demand is 3 units/day and lead time is 2 days with no "
            "safety stock. Find the reorder point.",
            "6",
        ),
        (
            "Maximize 2x+3y with 0<=x<=4 and 0<=y<=5. Give the optimum value.",
            "23",
        ),
        (
            "Weighted intervals (start,end,value) are "
            "[(1, 3, 2), (3, 5, 4), (1, 5, 3), (5, 7, 5)]. "
            "Find the maximum value of a nonoverlapping subset.",
            "11",
        ),
        (
            "Directed arc costs are s-a=2, a-t=5, s-b=3, b-t=4, a-b=1. "
            "Find the minimum s-t path cost.",
            "7",
        ),
    ],
)
def test_deterministic_solver_covers_operations_research_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("A triangle has side lengths 4, 7, and 9. Find its perimeter.", "20"),
        ("A right triangle has legs 3 and 4. Find its hypotenuse.", "5"),
        ("Find the area of a triangle with base 5 and altitude 4.", "10"),
        ("A rectangle has side lengths 3 and 4. Find the diagonal length.", "5"),
        ("Give the exact area of a circle of radius 2.", "4*pi"),
        ("Give the exact circumference of a circle of radius 3.", "6*pi"),
        (
            "A chord lies 4 units from the center of a circle of radius 5. "
            "Find the chord length.",
            "6",
        ),
        (
            "A trapezoid has parallel sides 3 and 9 and height 4. Find its area.",
            "24",
        ),
        (
            "Find the sum of the interior angles, in degrees, of a convex 3-gon.",
            "180",
        ),
        (
            "What is each exterior angle, in degrees, of a regular 17-gon?",
            "360/17",
        ),
        (
            "A sector has radius 2 and central angle 12 degrees. "
            "Give its exact area as a multiple of pi.",
            "2/15*pi",
        ),
        (
            "Give the exact volume of a cylinder with radius 2 and height 5.",
            "20*pi",
        ),
        (
            "Corresponding sides of two similar triangles have scale factor 3/2. "
            "If the first side is 4, find the matching side.",
            "6",
        ),
        (
            "Two circles of radii 2 and 3 are externally tangent. "
            "Find the distance between their centers.",
            "5",
        ),
    ],
)
def test_deterministic_solver_covers_euclidean_geometry_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute partial_x of f(x,y)=x^2y at (1,1).", "2"),
        ("Compute partial_y of f(x,y)=x*y^2 at (1,1).", "2"),
        ("Find grad f at (1,1) for f(x,y)=x^2-2xy+y^2.", "(0,0)"),
        (
            "For f(x,y)=x-2y, compute the directional derivative along the "
            "unit direction (3/5,4/5).",
            "-1",
        ),
        (
            "For f(x,y)=3x, compute the directional derivative along the "
            "unit direction (6/10,8/10).",
            "9/5",
        ),
        ("Find the Jacobian determinant of T(x,y)=(2x,3y).", "6"),
        ("Find det(DT) for T(x,y)=(x-3y,(-1)x+2y).", "-1"),
        ("Find det(DT) for T(x,y)=(4x,(2)x+5y).", "20"),
        ("Find det(DT) for T(x,y)=(5x+y,(-1)x+6y).", "31"),
        ("Evaluate the double integral of 1 over [0,2]x[0,3].", "6"),
        ("Evaluate integral_0^2 integral_0^1 (x+2y) dy dx.", "4"),
        ("Compute partial_xy of x^2y^2 at (1,1).", "4"),
        (
            "For z=x+2y-3, give the normal vector with positive z-component "
            "to the level surface z-x-2y+3=0.",
            "(-1,-2,1)",
        ),
        (
            "For z=4x+5y, give the normal vector with positive z-component "
            "to the level surface z-4x-5y=0.",
            "(-4,-5,1)",
        ),
        ("Compute div F for F=(x,2y,3z).", "6"),
        ("Find the z-component of curl F for F=(-2y,x,0).", "3"),
        ("Find det(H_f) for f(x,y)=x^2-3xy+2y^2.", "-1"),
        (
            "Maximize 3x+4y subject to x^2+y^2=1. Give the maximum value.",
            "5",
        ),
    ],
)
def test_deterministic_solver_covers_multivariable_calculus_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    "question",
    [
        "Compute partial_y of f(x,y)=x^y^2 at (1,1).",
        "Evaluate integral_0^2 integral_0 (x+2y) dy dx.",
    ],
)
def test_deterministic_solver_refuses_ambiguous_multivariable_syntax(
    question: str,
) -> None:
    assert solve_deterministically(question) is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "A finite undirected graph has 5 edges. Find the sum of all "
            "vertex degrees.",
            "10",
        ),
        ("How many edges are in any tree on 4 vertices?", "3"),
        ("How many edges does the complete graph K_4 have?", "6"),
        ("How many edges does K_{2,3} have?", "6"),
        ("Find the chromatic number of cycle C_3.", "3"),
        (
            "In path P_8 with vertices numbered consecutively, find the "
            "distance from 1 to 8.",
            "7",
        ),
        ("What is the maximum vertex degree in a star with 3 leaves?", "3"),
        ("Does K_3 have an Eulerian circuit? Answer yes or no.", "yes"),
        (
            "For the adjacency matrix A of path P_5, compute the (1,1) entry of A^2.",
            "1",
        ),
        (
            "A weighted graph has edges A-B=2, B-D=5, A-C=3, C-D=4, "
            "A-D=12. Find the shortest A-D distance.",
            "7",
        ),
        ("Find the independence number of cycle C_5.", "2"),
        ("How many spanning trees does K_3 have?", "3"),
        (
            "A connected planar embedding has V=5 and E=5. Find the number of faces.",
            "2",
        ),
        (
            "A graph has 6 vertices and 5 edges. Find its average degree.",
            "5/3",
        ),
    ],
)
def test_deterministic_solver_covers_graph_theory_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute C(8,1).", "8"),
        (
            "How many ordered selections of 2 distinct objects can be made "
            "from 7 objects?",
            "42",
        ),
        ("How many strings use exactly 1 A's, 1 B's, and 1 C's?", "6"),
        (
            "How many nonnegative integer solutions satisfy x1+...+x2=8?",
            "9",
        ),
        (
            "How many integers from 1 through 50 are divisible by 2 or 5?",
            "30",
        ),
        (
            "What is the minimum number of objects placed into 3 boxes that "
            "guarantees one box contains at least 2 objects?",
            "4",
        ),
        ("Compute the Catalan number C_1.", "1"),
        ("How many subsets does a set of size 6 have?", "64"),
        ("How many derangements are there of 3 labeled objects?", "2"),
        (
            "How many shortest lattice paths from (0,0) to (2,3) use only "
            "right and up steps?",
            "10",
        ),
        (
            "How many circular arrangements of 5 distinct people are there, "
            "counting rotations as identical?",
            "24",
        ),
        (
            "How many onto functions are there from a set of 4 elements to "
            "a labeled 2-element set?",
            "14",
        ),
        ("Compute sum_(k=0)^5 C(5,k).", "32"),
        (
            "How many compositions of 8 into exactly 2 positive parts are there?",
            "7",
        ),
    ],
)
def test_deterministic_solver_covers_combinatorics_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Find lim_(n->infinity) (n-4)/(2n+3).", "1/2"),
        (
            "Does the sequence (1/6)^n converge? If so, give its limit.",
            "0",
        ),
        (
            "Does sum_(n=1)^infinity 1/n^(11/10) converge? Answer yes or no.",
            "yes",
        ),
        (
            "Does sum_(n=1)^infinity (-1)^n/(n+1) converge? Answer yes or no.",
            "yes",
        ),
        ("Is f(x)=x-3 continuous at x=-7? Answer yes or no.", "yes"),
        (
            "Does f_n(x)=x/n converge uniformly to 0 on [0,1]? Answer yes or no.",
            "yes",
        ),
        ("Find sup_{x in [0,2]} |x/(5)|.", "2/5"),
        ("Find limsup of the sequence a_n=(-1)^n.", "1"),
        (
            "Is a_n=1/(n+1) a Cauchy sequence in R? Answer yes or no.",
            "yes",
        ),
        (
            "Using the difference quotient result, give the derivative of "
            "f(x)=x-5 at x=-2.",
            "1",
        ),
        ("Compute sum_(n=0)^infinity (1/2)^n.", "2"),
    ],
)
def test_deterministic_solver_covers_math_analysis_short_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "A line of slope -3 passes through (-4,7). Find its y-intercept.",
            "-5",
        ),
        (
            "Write the circle equation with center (-7,5) and radius 2 in "
            "the form (x-h)^2+(y-k)^2=r^2.",
            "(x+7)^2+(y-5)^2=4",
        ),
        (
            "Point P divides the segment from A=(-7,-9) to B=(5,3) "
            "internally with AP:PB=1:2. Find P.",
            "(-3,-5)",
        ),
        (
            "Find the distance from (-7,-9) to the horizontal line y=-3.",
            "6",
        ),
        ("For y=(x+5)^2-3, give the vertex coordinates.", "(-5,-3)"),
        ("For y=2(x)^2+7, give the vertex coordinates.", "(0,7)"),
        (
            "For the ellipse x^2/9 + y^2/4 = 1, find the full length of "
            "the x-axis intercept chord.",
            "6",
        ),
        (
            "Find the y-coordinate where y=x-2 intersects y=-x+1.",
            "-1/2",
        ),
        (
            "Find the y-coordinate where y=3x intersects y=-3x+7.",
            "7/2",
        ),
        (
            "Find the area of the coordinate triangle with vertices (0,0), "
            "(4,0), and (0,3).",
            "6",
        ),
        ("Reflect the point (-7,-9) across the x-axis.", "(-7,9)"),
        (
            "A line has slope 2/3. Find the slope of any perpendicular line.",
            "-3/2",
        ),
        (
            "Find the distance from (1,-3) to the line 3x+4y-20=0.",
            "29/5",
        ),
        ("Find the distance from (5,5) to the line 3x+4y=0.", "7"),
    ],
)
def test_deterministic_solver_covers_analytic_geometry_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("For f(x)=x^2, compute f'(-2).", "-4"),
        ("For f(x)=2*exp(x), compute f'(0).", "2"),
        (
            "Differentiate sin(x) and evaluate the derivative at x=0.",
            "1",
        ),
        ("Find an antiderivative of 4x; use C for the constant.", "2*x^2+C"),
        (
            "Evaluate the definite integral of 2x from x=0 to x=2.",
            "4",
        ),
        ("Compute lim_(x->-3) [x^2 - 5x - 7].", "17"),
        ("Evaluate lim_(x->2) (x^2-4)/(x-2).", "4"),
        ("Compute d/dx[(x-4)^2] at x=-2.", "-12"),
        ("Compute d/dx[(5x)^2] at x=2.", "100"),
        ("If f(x)=(x-5)*exp(x), find f'(0).", "-4"),
        (
            "Find the slope of the tangent to y=x^2 - 6x + 3 at x=-2.",
            "-10",
        ),
        ("Find the signed area under y=x+2 from x=0 to x=2.", "6"),
        ("Find the average value of f(x)=-2x+1 on [0,2].", "-1"),
        ("For f(x)=x^3, compute f''(-2).", "-12"),
        ("Evaluate integral_0^ln(2) exp(x) dx.", "1"),
    ],
)
def test_deterministic_solver_covers_single_variable_calculus_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute gcd(6,10).", "2"),
        ("Compute lcm(4,7).", "28"),
        ("Find the least nonnegative residue of 15 modulo 5.", "0"),
        ("Compute 2^5 mod 11.", "10"),
        ("Find the least positive inverse of 2 modulo 5.", "3"),
        (
            "Find the least nonnegative x satisfying x congruent to 3 (mod 5).",
            "3",
        ),
        (
            "Find the least nonnegative x with x congruent to 1 (mod 3) and "
            "x congruent to 3 (mod 5).",
            "13",
        ),
        ("Compute Euler phi(57).", "36"),
        ("How many positive divisors does 8 have?", "4"),
        ("Is 29 prime? Answer yes or no.", "yes"),
        ("Find the sum of all positive divisors of 69.", "96"),
        ("Find the exponent of prime 5 in 20!.", "4"),
        ("How many trailing zeros are in 25!?", "6"),
        (
            "Does 6x+9y=4 have an integer solution? Answer yes or no.",
            "no",
        ),
    ],
)
def test_deterministic_solver_covers_number_theory_templates(
    question: str,
    expected: str,
) -> None:
    result = solve_deterministically(question)
    assert result is not None
    assert result.value == expected


def test_metrics_counts_proven_semantic_equivalence_as_pass(tmp_path: Path) -> None:
    result_path = tmp_path / "result.jsonl"
    answer_path = tmp_path / "answer.jsonl"
    result = {
        "question_id": "ode-semantic",
        "domain": "ODE",
        "problem_type": "ode",
        "problem_parse": {"goal": "solve", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": ["Solve the IVP."],
        "tool_trace": [],
        "final_answer": {
            "type": "expression",
            "value": "2*e^{-3*x}",
            "boxed": "\\boxed{2*e^{-3*x}}",
        },
        "verification": {
            "method": "symbolic_check",
            "passed": True,
            "notes": "checked",
        },
        "didactic_hint": "Use separation of variables.",
        "confidence": 0.9,
        "status": "success",
        "error": None,
    }
    answer = {
        "question_id": "ode-semantic",
        "answer": "y=2*exp(-3x)",
        "domain": "ODE",
        "problem_type": "ode",
        "evaluation_mode": "short_answer",
    }
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    answer_path.write_text(json.dumps(answer) + "\n", encoding="utf-8")

    metrics = evaluate_results(result_path, answer_path)

    assert metrics["normalized_match"] == 0.0
    assert metrics["semantic_match"] == 1.0
    assert metrics["evaluation_pass_count"] == 1
    assert metrics["evaluation_pass_rate"] == 1.0


def test_symbolic_match_always_returns_a_boolean() -> None:
    assert symbolic_match("x+x", "2*x") is True
    assert symbolic_match("x+x", "3*x") is False


def test_semantic_match_rejects_large_wrong_numeric_expression_quickly() -> None:
    assert not short_answer_match(
        "27*5^{27}*ln(5)",
        "135",
        problem_type="partial_derivative",
        domain="Calculus",
    )


@pytest.mark.parametrize(
    ("prediction", "gold", "problem_type", "domain"),
    [
        ("[-2,1]", "-2,1", "quadratic_equation", "Algebra"),
        ("[3,-4]", "-4,3", "eigenvalue", "Algebra"),
        ("[-4+i,-4-i]", "-4-i,-4+i", "complex_root", "ComplexAnalysis"),
        ("2", "x=2", "rational_equation", "Algebra"),
        (
            "[[-2/5,-7/5],[-1/5,-1/5]]",
            "[(-2/5,-7/5),(-1/5,-1/5)]",
            "matrix_inverse",
            "Algebra",
        ),
        ("e^{-1}", "exp(-1)", "poisson_probability", "Probability"),
        ("-10*pii", "-10*pi*i", "contour_integral", "ComplexAnalysis"),
        ("(x+2)^2+y^2=49", "(x+2)^2+(y)^2=49", "circle_equation", "Geometry"),
        ("Yes.", "yes", "eulerian", "DiscreteMath"),
        ("14!", "87178291200", "circular_permutation", "DiscreteMath"),
        ("mathbb{Z}", "Z", "fundamental_group", "Topology"),
    ],
)
def test_short_answer_match_accepts_proven_general_equivalence(
    prediction: str,
    gold: str,
    problem_type: str,
    domain: str,
) -> None:
    assert short_answer_match(
        prediction,
        gold,
        problem_type=problem_type,
        domain=domain,
    )


@pytest.mark.parametrize(
    ("prediction", "gold", "problem_type", "domain"),
    [
        ("[-2,2]", "-2,1", "quadratic_equation", "Algebra"),
        (
            "[[-2/5,-7/5],[-1/5,-1/5]]",
            "[(-2/5,-7/5),(-1/5,1/5)]",
            "matrix_inverse",
            "Algebra",
        ),
        ("-10*pi*i", "10*pi*i", "contour_integral", "ComplexAnalysis"),
        ("(x+2)^2+y^2=36", "(x+2)^2+y^2=49", "circle_equation", "Geometry"),
        ("no", "yes", "eulerian", "DiscreteMath"),
    ],
)
def test_short_answer_match_rejects_wrong_general_answers(
    prediction: str,
    gold: str,
    problem_type: str,
    domain: str,
) -> None:
    assert not short_answer_match(
        prediction,
        gold,
        problem_type=problem_type,
        domain=domain,
    )
