"""
MathPilot 多智能体包
====================

对外暴露核心类，便于 ``user_agent.py`` 以薄壳方式调用：

    from agent.orchestrator import Orchestrator
    from agent.base import TaskContext, Budget, Candidate, Verdict
"""

from .base import BaseAgent, TaskContext, Budget, Candidate, Verdict
from .classifier import ClassifierAgent
from .solver import SolverAgent
from .verifier import VerifierAgent
from .formatter import FormatterAgent
from .orchestrator import Orchestrator

__all__ = [
    "BaseAgent", "TaskContext", "Budget", "Candidate", "Verdict",
    "ClassifierAgent", "SolverAgent", "VerifierAgent",
    "FormatterAgent", "Orchestrator",
]
