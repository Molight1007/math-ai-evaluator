from __future__ import annotations
"""统一客观答案验证层（AnswerOracle，v2.7；2026-09-06 去 Lean 化）。

设计背景
========
当前"写不对难题"的根因之一是：验证器（Verifier）与解题器（Solver）同源，
A/B 投票本质是"让同一个模型再读一遍"，会一起错；而客观工具没有形成闭环。

本模块把"客观答案验证"从 verifier 中抽离为统一入口。2026-09-06 起
Lean 系（LeanBridge/lean_gate）随「检测链去 Lean 化」从平台链路移除
（平台无 Lean 可执行文件，历史实证只空转不审核），本模块只保留：
- 计算/数值题 → SymPy 符号等价（多候选 self-consistency 聚类）+ 答案可解析性；
- 证明题 → 不编译不误判，直接返回 unknown（散文证明不可程序化等价判定），
  由 AuditGate（rubric 结构化判分）与对抗式验证承担客观把关。

客观验证不依赖"验证器与解题器同源"的 LLM 自评，是数学领域区别于通用
LLM 编排的最大增量（对应 LangGraph 的 oracle-in-the-loop 思想）。

隔离原则
========
- 独立文件，不污染 orchestrator 主流程；上层只调用
  ``AnswerOracle(client, config, budget).verify(ctx, candidate)`` 一行；
- 任何异常一律吞掉并降级 ``verdict='unknown'``，绝不因 oracle 导致评测崩溃；
- SymPy 不可用时仅打 warning 并整体降级 unknown，不阻断主流程。

对外契约
========
``verify()`` 返回 ``OracleResult``：
- verdict: 'correct' | 'incorrect' | 'unknown'
- feedback: 结构化错误定位（供 revise / 审查复用）
- evidence: 客观证据（sympy 重算值 / 共识统计）
- oracle_type: 'sympy' | 'none'
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .base import TaskContext

logger = logging.getLogger("MathPilot.Oracle")

# 证明题判定信号（与 lean_gate / solver / difficulty_router 保持一致）
_PROOF_TYPE = "证明题"
_PROOF_DOMAINS = ("证明", "证明题")


@dataclass
class OracleResult:
    """客观验证结果（单一数据契约，JSON 可序列化）。"""
    verdict: str = "unknown"            # 'correct' | 'incorrect' | 'unknown'
    feedback: str = ""                  # 结构化错误定位（供 revise / 审查复用）
    evidence: dict = field(default_factory=dict)  # 客观证据
    oracle_type: str = "none"           # 'sympy' | 'none'（'lean' 已于 2026-09-06 移除）

    @property
    def is_correct(self) -> bool:
        return self.verdict == "correct"

    @property
    def is_incorrect(self) -> bool:
        return self.verdict == "incorrect"

    def to_dict(self) -> dict:
        """JSON 可序列化表示（供 trace / 诊断 / 评测报告复用）。"""
        return {
            "verdict": self.verdict,
            "feedback": self.feedback,
            "evidence": self.evidence,
            "oracle_type": self.oracle_type,
        }


class AnswerOracle:
    """统一客观答案验证层。按题型分流：证明题 unknown，计算题走 SymPy。"""

    name = "AnswerOracle"

    def __init__(self, client=None, config=None, budget=None):
        self.client = client
        self.config = config
        self.budget = budget

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def verify(self, ctx: TaskContext, candidate,
               question_type: Optional[str] = None,
               candidates: Optional[list] = None) -> OracleResult:
        """按题型分流验证单个候选解答。

        参数:
            ctx: 共享上下文（含 problem / domain / question_type）。
            candidate: 待验证候选（含 answer / reasoning）。
            question_type: 题型（证明题/选择题/判断题/填空题/解答题），缺省取 ctx。
            candidates: 全部候选（计算题做多候选符号等价 self-consistency 用）。

        返回:
            OracleResult（verdict / feedback / evidence）。

        2026-09-06 去 Lean 化：证明题不再走 LeanBridge 编译（平台无 Lean），
        散文证明无法程序化等价判定 → 直接 unknown 放行，避免误把证明文本
        当"无法解析的表达式"判 incorrect（会把每题证明都误触发 revise）。
        客观把关由 AuditGate（6.5 rubric）+ 对抗式验证（4.6）承担。
        """
        qt = question_type or getattr(ctx, "question_type", "") or ""
        domain = getattr(ctx, "domain", "") or ""
        if qt == _PROOF_TYPE or any(k in domain for k in _PROOF_DOMAINS):
            return OracleResult(verdict="unknown", oracle_type="none",
                                evidence={"reason": "proof_not_computational"})
        return self.verify_computational(candidate, candidates)

    # ------------------------------------------------------------------
    # 计算题：SymPy 客观验证
    # ------------------------------------------------------------------
    def verify_computational(self, candidate,
                             candidates: Optional[list] = None) -> OracleResult:
        """计算题 → SymPy 符号等价 + 答案可解析性。

        解题阶段无 reference_answer，无法对单候选做绝对对错判定，因此：
        - 多候选符号等价（self-consistency）给出"多数一致"客观信号；
        - 答案可解析性过滤明显非法答案；
        - 其余一律 unknown，交由上层投票/playoff 收敛，避免假阳性。
        """
        answer = getattr(candidate, "answer", "") or ""
        parseable = self.is_parseable(answer)
        group_size, total, usable = self._consensus(candidate, candidates)

        evidence = {
            "parseable": parseable,
            "group_size": group_size,
            "total": total if usable else None,
        }

        if not answer:
            return OracleResult(verdict="incorrect", feedback="候选答案为空",
                                evidence=evidence, oracle_type="sympy")
        if not parseable:
            return OracleResult(verdict="incorrect",
                                feedback="候选答案无法解析为有效数学表达式",
                                evidence=evidence, oracle_type="sympy")
        if usable and total >= 2 and group_size >= max(2, total // 2 + 1):
            # 多数候选符号一致 → self-consistency 强信号，视为可信
            return OracleResult(verdict="correct", oracle_type="sympy",
                                evidence=evidence)
        if usable and total >= 2 and group_size == 1:
            # 与其他候选均不等价 → 孤立答案，弱信号（供上层压低置信度）
            return OracleResult(verdict="unknown", oracle_type="sympy",
                                feedback="该候选答案与其他候选符号不等价",
                                evidence=evidence)
        return OracleResult(verdict="unknown", oracle_type="sympy",
                            evidence=evidence)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def is_parseable(answer: str) -> bool:
        """答案能否被 SymPy 解析为有效表达式（纯本地，不消耗 LLM 预算）。"""
        if not answer:
            return False
        try:
            from utils.sympy_tools import _try_parse
            parsed, _ = _try_parse(answer)
            return parsed is not None
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _consensus(candidate, candidates: Optional[list]) -> tuple[int, int, bool]:
        """计算候选答案在候选集中的符号等价组大小。

        返回 (组大小, 总候选数, 是否可用多候选共识)。
        """
        if not candidates:
            return 1, 1, False
        target = getattr(candidate, "answer", "") or ""
        total = len(candidates)
        group = 0
        for c in candidates:
            if AnswerOracle.answers_equivalent(target, getattr(c, "answer", "")):
                group += 1
        return group, total, True

    @staticmethod
    def answers_equivalent(a: str, b: str) -> bool:
        """两级答案等价：文本完全相同 → SymPy 符号等价。"""
        if not a or not b:
            return False
        if a.strip() == b.strip():
            return True
        try:
            from utils.sympy_tools import are_expressions_equal
            return bool(are_expressions_equal(a, b))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def findings_to_feedback(findings) -> str:
        """把 Finding 列表结构化为可注入 revise 的错误定位文本。

        格式：`- {location} [{kind}](严重度{severity}): {desc}`
        2026-09-06 起主链路不再产生 Lean Finding（去 Lean 化）；本方法保留
        供本地 Lean 证据链工具（lean_gate 迁移 tools/lean_local 前）复用。
        """
        if not findings:
            return ""
        lines = []
        for f in findings:
            loc = getattr(f, "location", "") or "未定位"
            kind = getattr(f, "kind", "") or ""
            desc = getattr(f, "desc", "") or ""
            sev = getattr(f, "severity", 0) or 0
            tag = f"[{kind}]" if kind else ""
            sev_tag = f"(严重度{sev})" if sev else ""
            lines.append(f"- {loc} {tag}{sev_tag}: {desc}".strip())
        return "\n".join(lines)

    @staticmethod
    def cluster_equivalent_answers(answers: list) -> list[list[int]]:
        """多候选答案符号等价聚类，返回候选下标分组（self-consistency 信号）。

        纯本地、O(n²) 两两比对，不消耗 LLM 预算。
        """
        n = len(answers)
        visited = [False] * n
        groups: list[list[int]] = []
        for i in range(n):
            if visited[i]:
                continue
            group = [i]
            visited[i] = True
            for j in range(i + 1, n):
                if visited[j]:
                    continue
                if AnswerOracle.answers_equivalent(answers[i], answers[j]):
                    group.append(j)
                    visited[j] = True
            groups.append(group)
        return groups
