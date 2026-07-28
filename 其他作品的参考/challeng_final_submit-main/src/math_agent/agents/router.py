from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from math_agent.agents.route_taxonomy import match_semantic_route
from math_agent.clients.interns1_client import InternS1Client
from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.typing import ChatClient


class RouteInfo(BaseModel):
    domain: str
    problem_type: str
    recommended_solver: str
    needs_tool: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class Router:
    DOMAIN_RULES: dict[str, list[str]] = {
        "ODE": [
            "solve ode",
            "ordinary differential",
            "dy/dx",
            "d^2y/dx^2",
            "常微分方程",
        ],
        "PDE": [
            "偏微分",
            "边值",
            "边界条件",
            "pde",
            "boundary condition",
            "heat equation",
            "wave equation",
            "laplace equation",
            "u_xx",
            "u_yy",
            "u_tt",
        ],
        "ComplexAnalysis": [
            "复分析",
            "围道积分",
            "contour integral",
            "residue theorem",
            "complex analysis",
            "留数",
        ],
        "Topology": [
            "拓扑",
            "紧致",
            "topology",
            "compact",
            "homeomorphism",
            "同胚",
        ],
        "DiscreteMath": [
            "graph theory",
            "adjacency matrix",
            "complete graph",
            "path graph",
            "chromatic number",
            "eulerian circuit",
            "bipartite graph",
            "tree with",
            "图论",
            "邻接矩阵",
            "欧拉回路",
            "二分图",
        ],
        "GeneralReasoning": ["comprehensive reasoning", "综合推理"],
        "OperationsResearch": [
            "operations research",
            "linear program",
            "linear programming",
            "bounded polytope",
            "extreme point",
            "shortest path",
            "dijkstra",
            "eoq",
            "queue",
            "max-flow",
            "min-cut",
            "knapsack",
            "transportation problem",
            "m/m/1",
        ],
        "Optimization": [
            "linear programming",
            "线性规划",
            "约束",
            "最大化",
            "最小化",
            "最优",
            "maximize",
            "minimize",
            "constraint",
        ],
        "Algebra": [
            "eigenvalue",
            "eigenvalues",
            "determinant",
            "rank of matrix",
            "dot product",
            "cross product",
            "matrices",
            "矩阵",
            "特征值",
            "特征向量",
            "matrix",
            "equation",
            "polynomial",
            "quadratic",
            "linear",
            "inequality",
            "factor:",
            "find roots",
            "find root",
            "evaluate:",
            "evaluate ",
            "sqrt(",
            "multiplied by",
        ],
        "Geometry": [
            "几何",
            "角",
            "三角形",
            "圆",
            "矩形",
            "面积",
            "距离",
            "坐标",
            "内切圆",
            "弦长",
            "geometry",
            "angle",
            "triangle",
            "circle",
            "rectangle",
            "midpoint",
            "distance",
            "coordinate",
            "area",
            "inradius",
            "chord",
            "side lengths",
            "right triangle",
            "median",
        ],
        "Probability": [
            "probability",
            "概率",
            "随机变量",
            "期望",
            "方差",
            "coin",
            "dice",
            "binomial",
            "random variable",
            "expected value",
            "variance",
            "statistics:",
            "conditional probability",
            "standard normal",
        ],
        "Combinatorics": [
            "combinatorics",
            "choose",
            "combination",
            "permutation",
            "arrangement",
            "catalan",
            "组合",
            "排列",
        ],
        "NumberTheory": [
            "数论",
            "number theory",
            "素数",
            "同余",
            "整除",
            "prime",
            "congruence",
            "gcd",
            "lcm",
            "remainder",
            "divisible",
            "modulo",
            "modular",
            "least nonnegative residue",
            "euler phi",
            "positive divisors",
            "multiplicative inverse",
            "congruence system",
        ],
        "Calculus": [
            "微积分",
            "derivative",
            "integral",
            "limit",
            "导数",
            "求导",
            "积分",
            "极限",
            "integrate:",
            "directional derivative",
            "partial derivative",
            "gradient of",
            "double integral",
            "jacobian",
            "uniformly convergent",
            "continuous at",
            "series sum",
        ],
        "Recurrence": [
            "recurrence",
            "sequence",
            "arithmetic sequence",
            "geometric sequence",
        ],
        "Functions": ["function", "f(x)", "g(x)", "functional equation", "composition"],
    }

    SPECIFIC_PROBLEM_TYPE_RULES: dict[str, list[str]] = {
        "pde_classification": ["pde: classify", "classify the equation"],
        "pde_boundary_value": ["pde: find the solution to u_xx"],
        "pde_derivation": [
            "solve the heat equation",
            "solve the wave equation",
            "solve laplace equation",
            "separation of variables",
        ],
        "ode": ["solve ode", "dy/dx", "d^2y/dx^2"],
        "directional_derivative": ["directional derivative"],
        "partial_derivative": ["partial derivative"],
        "gradient": ["gradient of"],
        "double_integral": ["double integral"],
        "jacobian": ["jacobian"],
        "eigenvalues": ["eigenvalue"],
        "determinant": ["determinant of matrix"],
        "matrix_rank": ["rank of matrix"],
        "matrix_operation": ["add matrices", "multiply matrices"],
        "vector_operation": ["dot product", "cross product"],
        "linear_system": ["solve the system"],
        "inequality": ["solve inequality"],
        "absolute_value": ["solve: |"],
        "rational_equation": ["solve: ", "/x"],
        "polynomial": ["find roots", "find root", "factor:"],
        "quadratic_equation": ["quadratic formula"],
        "graph_theory": ["graph theory"],
        "shortest_path": ["shortest path"],
        "max_flow": ["max-flow"],
        "queue_theory": ["m/m/1", "utilization"],
        "expected_value": ["expected value"],
        "variance": ["variance"],
        "conditional_probability": ["p(a|b)", "conditional probability"],
        "mean": ["have mean"],
        "derivative": ["derivative", "differentiate"],
        "limit": ["limit as", "approaches"],
        "definite_integral": ["definite integral", "integral from"],
        "indefinite_integral": ["integrate:"],
        "combination": ["choose", "combination"],
        "binomial_probability": ["exactly", "heads", "coin"],
        "gcd": ["gcd"],
        "lcm": ["lcm"],
        "modular_exponent": ["least nonnegative residue"],
        "totient": ["euler phi", "phi("],
        "divisor_count": ["positive divisors"],
        "modular_inverse": ["multiplicative inverse", "least positive inverse"],
        "crt": ["least nonnegative solution"],
        "modular_arithmetic": ["remainder", "modulo", "mod "],
        "coordinate_geometry": ["squared distance", "midpoint", "coordinate"],
        "inradius": ["inradius"],
        "chord_length": ["chord"],
        "area": ["area", "rectangle", "triangle", "circle", "side lengths"],
        "arithmetic_sequence": ["arithmetic sequence"],
        "geometric_sequence": ["geometric sequence"],
        "recurrence": ["recurrence"],
        "function_evaluation": ["compute f("],
        "function_composition": ["f(g("],
        "functional_equation": ["functional equation"],
    }

    PROBLEM_TYPE_RULES: dict[str, list[str]] = {
        "proof": ["证明", "证毕", "prove", "show that"],
        "optimization": [
            "maximize",
            "minimize",
            "constraint",
            "最大化",
            "最小化",
            "约束",
            "最优",
        ],
        "calculation": [
            "calculate",
            "evaluate",
            "compute",
            "solve",
            "计算",
            "求值",
            "解方程",
        ],
        "conceptual": ["concept", "definition", "explain", "定义", "解释"],
    }

    PROGRAM_HINTS = [
        "number",
        "equation",
        "integral",
        "matrix",
        "expression",
        "polynomial",
        "sequence",
        "function",
        "probability",
        "area",
        "distance",
        "数值",
        "方程",
        "积分",
        "矩阵",
        "表达式",
    ]
    TOOL_HINTS = [
        "calculate",
        "solve",
        "compute",
        "evaluate",
        "计算",
        "求解",
    ]
    PROGRAM_TYPES = {
        "calculation",
        "derivation",
        "linear_equation",
        "quadratic_equation",
        "linear_system",
        "nonlinear_system",
        "inequality",
        "absolute_value",
        "rational_equation",
        "polynomial",
        "ode",
        "pde_classification",
        "pde_boundary_value",
        "derivative",
        "indefinite_integral",
        "limit",
        "definite_integral",
        "directional_derivative",
        "partial_derivative",
        "gradient",
        "double_integral",
        "jacobian",
        "eigenvalues",
        "determinant",
        "matrix_rank",
        "matrix_operation",
        "vector_operation",
        "graph_theory",
        "shortest_path",
        "max_flow",
        "queue_theory",
        "expected_value",
        "variance",
        "conditional_probability",
        "mean",
        "permutation",
        "pigeonhole",
        "inclusion_exclusion",
        "catalan",
        "binomial_sum",
        "transportation",
        "complex_number",
        "topology_conceptual",
        "uniform_convergence",
        "probability",
        "word_problem",
        "prime_test",
        "combination",
        "binomial_probability",
        "gcd",
        "lcm",
        "modular_arithmetic",
        "modular_exponent",
        "totient",
        "divisor_count",
        "modular_inverse",
        "crt",
        "coordinate_geometry",
        "area",
        "inradius",
        "chord_length",
        "arithmetic_sequence",
        "geometric_sequence",
        "recurrence",
        "function_evaluation",
        "function_composition",
    }

    def __init__(
        self,
        mode: str = "rule_based",
        client: ChatClient | None = None,
        prompt_config_path: str | Path = "configs/prompts.yaml",
    ) -> None:
        if mode not in {"rule_based", "llm"}:
            raise ValueError("mode must be one of: rule_based, llm")
        self.mode = mode
        self.client = client or InternS1Client(mock=True)
        self.prompt_config_path = Path(prompt_config_path)

    def route(self, question: str) -> RouteInfo:
        if self.mode == "llm":
            llm_result = self._route_with_llm(question)
            if llm_result is not None:
                return llm_result
        return self._route_rule_based(question)

    def _route_rule_based(self, question: str) -> RouteInfo:
        text = question.lower()

        semantic_route = match_semantic_route(text)
        if semantic_route is not None:
            semantic_hit = f"semantic:{semantic_route.rule_name}"
            domain = semantic_route.domain
            problem_type = semantic_route.problem_type
            domain_hits = [semantic_hit]
            type_hits = [semantic_hit]
        else:
            domain, domain_hits = self._detect_domain(text)
            problem_type, type_hits = self._detect_problem_type(text)
            if problem_type == "unknown":
                problem_type, type_hits = self._fallback_problem_type(text)
            if domain == "Unknown":
                domain = "GeneralReasoning"
                domain_hits = ["typed-general-fallback"]
        recommended_solver = self._recommend_solver(text, domain, problem_type)
        needs_tool = self._needs_tool(text, domain, recommended_solver)

        hit_count = len(domain_hits) + len(type_hits)
        confidence = min(0.99, 0.35 + 0.15 * hit_count)
        if "typed-general-fallback" in domain_hits:
            confidence = min(confidence, 0.3)
        if domain == "Unknown" and problem_type == "unknown":
            confidence = 0.2

        reason = (
            f"domain={domain} via {domain_hits or ['no-keyword']}; "
            f"problem_type={problem_type} via {type_hits or ['no-keyword']}; "
            f"solver={recommended_solver}; needs_tool={needs_tool}"
        )

        return RouteInfo(
            domain=domain,
            problem_type=problem_type,
            recommended_solver=recommended_solver,
            needs_tool=needs_tool,
            confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _fallback_problem_type(text: str) -> tuple[str, list[str]]:
        if re.search(r"\b(?:prove|show that|derive|justify)\b", text):
            return "proof", ["proof-intent-fallback"]
        if re.search(r"^\s*(?:is|does|can|why|what is|which)\b", text):
            return "conceptual", ["concept-intent-fallback"]
        if re.search(
            r"\b(?:calculate|compute|determine|evaluate|find|give|how many|"
            r"simplify|solve|classify)\b",
            text,
        ):
            return "calculation", ["calculation-intent-fallback"]
        return "conceptual", ["typed-conceptual-fallback"]

    def _route_with_llm(self, question: str) -> RouteInfo | None:
        try:
            prompts = load_prompts(self.prompt_config_path)
            system_template = get_prompt(prompts, "router_system")
            system_prompt = render_prompt(system_template)
            user_prompt = (
                "Classify and route this math question. Return strict JSON only with fields: "
                "domain, problem_type, recommended_solver, needs_tool, confidence, reason.\n"
                f"Question:\n{question}"
            )
            content = self.client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            data = self._extract_json(content)
            return RouteInfo.model_validate(data)
        except (
            ValidationError,
            ValueError,
            TypeError,
            KeyError,
            FileNotFoundError,
            json.JSONDecodeError,
        ):
            return None

    @staticmethod
    def _extract_json(content: str) -> dict:
        content = content.strip()
        if content.startswith("{") and content.endswith("}"):
            return json.loads(content)
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group(0))
        raise ValueError("No JSON object found")

    def _detect_domain(self, text: str) -> tuple[str, list[str]]:
        if re.search(
            r"\bcompute\s+[-+]?\d+\s*\*\s*\([^()]+\)\s*\+\s*"
            r"[-+]?\d+\s*\*\s*\([^()]+\)",
            text,
        ):
            return "Algebra", ["vector-linear-combination"]
        for domain, keywords in self.DOMAIN_RULES.items():
            hits = [k for k in keywords if k in text]
            if hits:
                return domain, hits
        if re.search(r"\bsolve\b.*=", text):
            return "Algebra", ["solve-equation"]
        return "Unknown", []

    def _detect_problem_type(self, text: str) -> tuple[str, list[str]]:
        proof_hits = [k for k in self.PROBLEM_TYPE_RULES["proof"] if k in text]
        if proof_hits:
            return "proof", proof_hits

        strict_patterns: list[tuple[str, str]] = [
            ("pde_classification", r"\bpde\b.*\bclassify\b"),
            ("pde_boundary_value", r"\bpde\b.*u_xx\s*=\s*0.*boundary"),
            (
                "proof",
                r"\bpde\b.*(?:heat equation|wave equation|laplace equation|"
                r"separation of variables)",
            ),
            ("proof", r"\bpde\b.*\bderive\b.*\bfourier"),
            ("ode", r"(?:\bsolve\s+ode\b|dy/dx|d\^2y/dx\^2)"),
            ("directional_derivative", r"\bdirectional derivative\b"),
            ("partial_derivative", r"\bpartial derivative\b"),
            ("double_integral", r"\bdouble integral\b"),
            ("jacobian", r"\bjacobian\b"),
            ("gradient", r"\bgradient of\b"),
            ("shortest_path", r"\bshortest path\b"),
            ("max_flow", r"\bmax-flow\b"),
            ("queue_theory", r"\bm/m/1\b"),
            ("linear_system", r"\bsolve the system\b"),
            ("inequality", r"\bsolve inequality\b"),
            ("absolute_value", r"\bsolve\s*:\s*\|"),
            ("rational_equation", r"\bsolve\s*:[^=\n]*/x\b"),
            ("quadratic_equation", r"\bsolve\b.*x\^2"),
            ("polynomial", r"\b(?:find roots?|factor)\s*:"),
            ("eigenvalues", r"\beigenvalues?\b"),
            ("determinant", r"\bdeterminant of matrix\b"),
            ("matrix_rank", r"\brank of matrix\b"),
            ("matrix_operation", r"\b(?:add|multiply) matrices\b"),
            ("vector_operation", r"\b(?:dot|cross) product\b"),
            ("conditional_probability", r"\bp\(a\|b\)"),
            ("expected_value", r"\bexpected value\b"),
            ("variance", r"\bvariance\b"),
            ("mean", r"\bhave mean\b"),
            ("permutation", r"\bpermutations?\b"),
            ("pigeonhole", r"\bminimum number of people\b"),
            ("inclusion_exclusion", r"\bdivisible by\b.+\bor\b"),
            ("catalan", r"\bcatalan number\b"),
            ("binomial_sum", r"\bsum of binomial coefficients\b"),
            ("transportation", r"\btransportation problem\b"),
            (
                "complex_number",
                r"(?:\bmodulus\b|\bconjugate\b|\bcube roots\b|e\^\(i\*pi\))",
            ),
            (
                "functional_equation",
                r"\bfind all functions\b.*f\(x\+y\)",
            ),
            (
                "number_theory_reasoning",
                r"\bpositive integers n\b.*\bdivides\b",
            ),
            (
                "topology_conceptual",
                r"\btopology\s*:\s*(?:is|what is)\b",
            ),
            ("uniform_convergence", r"\buniformly convergent\b"),
            (
                "probability",
                r"\b(?:standard normal|fair six-sided die)\b",
            ),
            (
                "word_problem",
                r"\bif a number is multiplied by\b",
            ),
            ("prime_test", r"\bis \d+ a prime number\b"),
            (
                "coordinate_geometry",
                r"\banalytic geometry\b.*(?:equation of line|slope of line|"
                r"distance from point)",
            ),
            (
                "function_evaluation",
                r"\bevaluate\b.+\bat x\s*=",
            ),
            (
                "calculation",
                r"\bevaluate\s*:",
            ),
            ("graph_theory", r"\bgraph theory\b"),
        ]
        for problem_type, pattern in strict_patterns:
            if re.search(pattern, text):
                return problem_type, [pattern]

        for problem_type, keywords in self.SPECIFIC_PROBLEM_TYPE_RULES.items():
            if problem_type in {
                "rational_equation",
                "quadratic_equation",
                "graph_theory",
                "shortest_path",
            }:
                continue
            hits = [k for k in keywords if k in text]
            if hits:
                return problem_type, hits

        equation_hits: list[str] = []
        if "=" in text and any(k in text for k in ["solve", "解方程", "求解", "解"]):
            equation_hits.append("equation-intent")
        if "=" in text and re.search(r"[a-z]\s*=", text):
            equation_hits.append("single-var-equation")
        if equation_hits:
            if "solve:" in text or "solve the" in text:
                if "x**2" in text or "x^2" in text:
                    return "quadratic_equation", equation_hits
                return "linear_equation", equation_hits
            return "calculation", equation_hits

        for problem_type in ["optimization", "calculation", "conceptual"]:
            keywords = self.PROBLEM_TYPE_RULES[problem_type]
            hits = [k for k in keywords if k in text]
            if hits:
                return problem_type, hits
        return "unknown", []

    def _recommend_solver(self, text: str, domain: str, problem_type: str) -> str:
        if problem_type in {"proof", "pde_derivation"}:
            return "proof"
        if problem_type == "functional_equation" and "find all functions" in text:
            return "proof"
        if problem_type == "optimization" or domain == "Optimization":
            return "optimization"
        if problem_type in self.PROGRAM_TYPES and (
            problem_type != "calculation" or any(h in text for h in self.PROGRAM_HINTS)
        ):
            return "program"
        return "general"

    def _needs_tool(self, text: str, domain: str, recommended_solver: str) -> bool:
        if recommended_solver in {"program", "optimization"}:
            return True
        if domain == "Unknown":
            return False
        if recommended_solver == "proof":
            return False
        return any(h in text for h in self.TOOL_HINTS)
