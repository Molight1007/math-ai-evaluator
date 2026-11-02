"""内核数据契约 —— 六步之间只传这几种东西。

设计原则
--------
1. **不发明新结构**：节点沿用现有规划产物的字段（goal / open_goals /
   deps），只是语义收紧。为了「干净重写」重新设计一套数据结构，会引入
   大量序列化与投影漏洞 —— 那正是旧链反复踩的坑。
2. **目标与结论分家**：`PlanNode.goal` 是提问，`SolveOutcome.claim` 是宣告。
   旧链一个槽同时承载三种语义，下游无从区分权威性。
3. **诊断字段不进下游**：`statement` / `raw` 只用于排错，投影时不带。
"""

from dataclasses import dataclass, field

__all__ = ["PlanNode", "SolveOutcome", "Judgement", "GoalSpec"]


@dataclass(frozen=True)
class GoalSpec:
    """第 1 步的产出：题面被抽成什么。

    goal     整题要证/要求的命题（提问形态）
    givens   已知条件（每条一个陈述，不是散文）
    kind     题型（沿用现有题型键，便于复用既有判定）
    """

    goal: str = ""
    givens: tuple = ()
    kind: str = ""
    answer_slot: bool = False


@dataclass(frozen=True)
class PlanNode:
    """第 2 步的产出：一个待证义务。

    nid        稳定标识（同一命题在多次重解里必须同名）
    goal       要证什么（**提问形态**；不得写具体值）
    deps       依赖的上游 nid
    open_goals 未闭合前提清单（命题级欠账）
    statement  原始文本（诊断用，不进下游）
    """

    nid: str
    goal: str = ""
    deps: tuple = ()
    open_goals: tuple = ()
    statement: str = ""
    tool: str = ""

    def as_obligation(self, status, reason="", evidence="", round=0, claim=""):
        """转成账本条目 —— 账本是唯一的事实源，节点本身不是。"""
        from contracts.proof_ledger import Obligation
        return Obligation(
            oid=self.nid, goal=self.goal, claim=claim, deps=self.deps,
            status=status, reason=reason, evidence=evidence, round=round)


@dataclass(frozen=True)
class SolveOutcome:
    """第 3 步的产出：一次求解。

    claim      候选结论（**宣告形态**；空表示没给出结论）
    derivation 推导正文（只做证据，不做判据）
    action     提议的证明动作（形式语言片段 / 符号表达式；可空）
    round      第几轮（内核只跑 1 轮，字段留给将来对照）
    """

    nid: str
    claim: str = ""
    derivation: str = ""
    action: str = ""
    round: int = 0
    raw: str = ""
    # 求解器**自己复述**的目标。与 PlanNode.goal 不比对就无法发现「目标被
    # 悄悄换掉」——旧链允许每轮重写目标，这就是「把存在性问题拆成分类
    # 证明题」的机制。这里只做对照，不参与判定（目标以节点声明为准）。
    goal: str = ""
    # 求解时附带的外部判定证据（工具是否真跑、跑了给出什么）。
    # ★ 不是历史产物专用：在线求解同样会产生这些 —— 求解器调用工具后
    #   把执行痕迹一并带出，裁决层才有东西可查。
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Judgement:
    """第 4 步的产出：一条义务的裁决。

    status   闭合层级（contracts.closure 四级）
    by       tool / symbol / model / none —— 谁判的，必须可查
    reason   判定依据（人读）
    evidence 工具裁决原文（机器可复核；HARD 必须非空）
    """

    nid: str
    status: str
    by: str = "none"
    reason: str = ""
    evidence: str = ""
