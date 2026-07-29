from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.agents.proof_guardian import check_proof_structure, detect_proof_problem
from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.schemas import Verification
from math_agent.tools.answer_normalizer import (
    canonicalize_final_answer,
    normalize_answer,
)
from math_agent.tools.deterministic_solver import solve_deterministically
from math_agent.tools.sympy_tools import check_equivalent, numeric_compare


class Verifier:
    def __init__(
        self,
        client: Any,
        prompt_config_path: str | Path = "configs/prompts.yaml",
        mock: bool = True,
    ) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def _tool_verify(
        self,
        draft_solution: str,
        final_answer: str,
        *,
        question: str = "",
        route_info: dict | None = None,
    ) -> Verification | None:
        _ = draft_solution
        route = route_info or {}
        expected = solve_deterministically(
            question,
            problem_type=str(route.get("problem_type", "")),
            domain=str(route.get("domain", "")),
        )
        if expected is None:
            return None

        problem_type = str(route.get("problem_type", ""))
        actual_value = canonicalize_final_answer(
            final_answer,
            problem_type=problem_type,
            question=question,
        )
        expected_value = canonicalize_final_answer(
            expected.value,
            problem_type=problem_type,
            question=question,
        )
        actual = normalize_answer(actual_value)
        target = normalize_answer(expected_value)
        if not actual or not target:
            return None
        if actual.casefold() == target.casefold():
            return Verification(
                method=expected.method,
                passed=True,
                notes="Final answer matches an independent deterministic recomputation.",
            )
        if numeric_compare(actual, target):
            return Verification(
                method="numeric_check",
                passed=True,
                notes="Final answer numerically matches an independent recomputation.",
            )
        if check_equivalent(actual, target):
            return Verification(
                method="symbolic_check",
                passed=True,
                notes="Final answer symbolically matches an independent recomputation.",
            )
        return Verification(
            method="symbolic_check",
            passed=False,
            notes="Final answer conflicts with an independent deterministic recomputation.",
        )

    def verify(
        self,
        question: str,
        draft_solution: str,
        final_answer: str,
        route_info: dict | None = None,
    ) -> Verification:
        is_proof = detect_proof_problem(question, route_info)
        if is_proof:
            try:
                structure = check_proof_structure(question, draft_solution)
            except Exception as exc:
                return Verification(
                    method="logic_review",
                    passed=False,
                    notes=f"Proof structure validation failed: {type(exc).__name__}.",
                )
            if not structure.passed:
                return structure
        else:
            try:
                tv = self._tool_verify(
                    draft_solution,
                    final_answer,
                    question=question,
                    route_info=route_info,
                )
                if tv is not None:
                    return tv
            except Exception:
                tv = None

        if self.mock:
            return Verification(
                method="self_review",
                passed=False,
                notes="Mock mode cannot independently verify this answer.",
            )
        try:
            template = get_prompt(self.prompts, "verifier_system")
            system_prompt = render_prompt(
                template, question=question, draft_solution=draft_solution
            )
            review_payload = json.dumps(
                {
                    "question": question,
                    "draft_solution": draft_solution,
                    "final_answer": final_answer,
                    "route_info": route_info or {},
                },
                ensure_ascii=False,
            )
            reply = self.client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": "Verify this JSON data:\n" + review_payload,
                    },
                ]
            )
            data = json.loads(reply)
            if isinstance(data, dict):
                return Verification.model_validate(data)
        except Exception as exc:
            return Verification(
                method="self_review",
                passed=False,
                notes=f"Verifier failed safely: {type(exc).__name__}.",
            )
        return Verification(
            method="self_review",
            passed=False,
            notes="Verifier fallback: non-JSON or invalid JSON response.",
        )


def run(question: str) -> str:
    _ = question
    return "pass"
