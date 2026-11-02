"""六步内核 —— 理解 / 规划 / 求解 / 裁决 / 投影 / 交付。

对外只有两个入口：
    Kernel(...).run(problem, metadata)        在线：六步全跑
    Kernel().run_solved(nodes, outcomes, ...) 离线：只跑裁决/投影/交付

★ 与旧链并行存在，不替换任何现有模块。切换由外部开关控制 ——
  没有并行就没有回退，也没有同输入的 A/B。
"""

from .deliver import (
    DELIVERY_NONE, DELIVERY_PROVEN, DELIVERY_UNPROVEN, Delivery, deliver,
)
from .judge import CHECKER_CONTRACT, judge, make_checker_result
from .pipeline import (
    CycleError, Kernel, KernelError, KernelResult, topo_order,
)
from .project import PROJECTION_MARK, project_items, project_text
from .types import GoalSpec, Judgement, PlanNode, SolveOutcome

__all__ = [
    "GoalSpec", "PlanNode", "SolveOutcome", "Judgement",
    "judge", "make_checker_result", "CHECKER_CONTRACT",
    "project_text", "project_items", "PROJECTION_MARK",
    "Delivery", "deliver",
    "DELIVERY_PROVEN", "DELIVERY_UNPROVEN", "DELIVERY_NONE",
    "Kernel", "KernelResult", "KernelError", "CycleError", "topo_order",
]
