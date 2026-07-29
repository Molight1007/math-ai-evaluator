from __future__ import annotations


def run_python_code(code: str, timeout_seconds: int = 5) -> dict[str, str]:
    """Reject arbitrary Python execution in the preliminary submission.

    In-process namespace restrictions are not a security boundary. Mathematical
    computation is handled by the whitelisted SymPy and AST evaluators instead.
    """

    _ = code, timeout_seconds
    return {
        "status": "blocked",
        "stdout": "",
        "stderr": "Arbitrary Python execution is disabled.",
        "result_summary": "Use deterministic math tools instead.",
    }
