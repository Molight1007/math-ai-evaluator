"""
多智能体基础组件
================

提供：
- ``Candidate`` / ``Verdict``：候选解答与验证结果的数据结构
- ``Budget``：LLM 调用预算（防止竞赛平台超时 / 超额）
- ``TaskContext``：共享黑板（Blackboard），所有 Agent 读写同一上下文，全程可追溯
- ``BaseAgent``：抽象基类，统一封装 LLM 安全调用、预算扣减、trace 记录
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("MathPilot")


# ============================================================
# 数据结构
# ============================================================
@dataclass
class Candidate:
    """一个候选解答"""
    id: int
    answer: str                 # 提取出的简洁最终答案
    reasoning: str              # 完整推理过程（含文本）
    revised: bool = False       # 是否由自纠错回环产生


@dataclass
class Verdict:
    """一个候选解答的验证结果"""
    id: int
    answer: str
    reasoning: str
    confidence: float           # 置信度 = 正确票数 / 总票数
    correct_votes: int
    total_votes: int
    feedback: str = ""          # 失败时由验证器提取的错误原因


@dataclass
class Budget:
    """LLM 调用预算控制器"""
    max_calls: int
    used_calls: int = 0

    def can_spend(self, n: int = 1) -> bool:
        """是否还有余额"""
        return self.used_calls + n <= self.max_calls

    def spend(self, n: int = 1) -> None:
        self.used_calls += n

    def remaining(self) -> int:
        return max(0, self.max_calls - self.used_calls)


@dataclass
class TaskContext:
    """黑板：所有 Agent 共享的推理上下文"""
    problem: str
    metadata: dict
    domain: Optional[str] = None               # ClassifierAgent 写入
    candidates: list = field(default_factory=list)   # SolverAgent 写入
    verdicts: list = field(default_factory=list)     # VerifierAgent 写入
    revise_feedback: list = field(default_factory=list)  # 回传给 Solver 的错误原因
    trace: list = field(default_factory=list)        # 全程决策轨迹
    budget: Optional[Budget] = None            # 预算控制器
    revise_round: int = 0                       # 已触发的自纠错轮数
    final_response: str = ""

    def verified_ids(self) -> set:
        """已验证过的候选 id 集合（避免重复验证）"""
        return {v.id for v in self.verdicts}


# ============================================================
# Agent 抽象基类
# ============================================================
class BaseAgent(ABC):
    """所有智能体的基类"""

    name: str = "base"

    def __init__(self, client, config):
        self.client = client
        self.config = config

    @abstractmethod
    def run(self, ctx: TaskContext) -> TaskContext:
        """处理上下文并返回（可能更新的）上下文"""
        ...

    # ----------------------------------------------------------
    # 通用能力：trace 记录 + 带预算管控的安全 LLM 调用
    # ----------------------------------------------------------
    def record(self, ctx: TaskContext, step: str, content: str, **extra) -> None:
        """向 trace 追加一条决策记录"""
        entry = {"agent": self.name, "step": step, "content": content}
        if extra:
            entry.update(extra)
        ctx.trace.append(entry)

    def llm(self, ctx: TaskContext, messages: list, temperature: float,
            max_tokens: int) -> Optional[str]:
        """
        带预算管控与降级的安全 LLM 调用。

        - 预算不足时直接返回 None（不调用，避免超时/超额）；
        - 调用异常时返回 None（由调用方决定降级策略）。
        成功时自动扣减预算。
        """
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            logger.debug("[%s] Budget exhausted, skip LLM call", self.name)
            return None
        try:
            resp = self.client.chat(messages, temperature, max_tokens)
            if ctx.budget is not None:
                ctx.budget.spend(1)
            return resp
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] LLM call failed: %s", self.name, e)
            return None
