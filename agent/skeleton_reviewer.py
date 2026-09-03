"""
SkeletonReviewer —— 骨架编排层评审（老师 9/2 建议：求解前的规划质量门）
========================================================================

老师建议原文：
"在大模型生成骨架后，将此骨架再次提交给大模型，进行编排层面的 review：
所提出的子目标是否是不适定的、或者子目标的求解难度大于等于原问题。
如果有上述问题，请重新再次生成骨架，再次 review 确认。之后再进行语法审核。"

定位：
- 时机：Blueprint DAG 生成之后、语法审核（_audit_blueprint_tree）之前
- 与 DagReviewer 的区别：DagReviewer 是**求解后**评审子目标结果质量（LEAP 5.3）；
  本模块是**求解前**评审骨架本身的规划质量（拆得对不对，不是算得对不对）
- 维度：① 子目标不适定（ill_posed）② 子目标难度 ≥ 原问题（not_simplifying）
- 动作：整体 replan → 带评审反馈重新生成骨架 → 再评审（最多 N 轮）

安全护栏：
- 单次 LLM 评审整棵骨架（编排层面整体审查，不逐节点烧预算）
- 所有调用过 budget.can_spend；预算不足降级放行（质量门不阻断主流程）
- LLM 异常/JSON 解析失败 → 默认 pass（评审是增强项，失败不应让题目白做）

对外接口：
- SkeletonReviewReport：评审报告（verdicts/overall/feedback_lines/to_dict/should_regenerate）
- SkeletonReviewerAgent.review(ctx, dag)：主入口，返回 SkeletonReviewReport
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseAgent, TaskContext
from .blueprint_planner import BlueprintDAG, extract_json

logger = logging.getLogger("MathPilot")

# 单次评审允许的最大节点数（防超深 DAG 烧光 max_tokens）
MAX_SKELETON_NODES = 40


@dataclass
class SkeletonVerdict:
    """单个子目标的编排层评审结论。"""
    node_id: str
    verdict: str          # "ok" | "ill_posed" | "not_simplifying"
    reason: str = ""
    hint: str = ""

    @property
    def is_ok(self) -> bool:
        return self.verdict == "ok"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "hint": self.hint,
        }


@dataclass
class SkeletonReviewReport:
    """整棵骨架的编排层评审报告。"""
    verdicts: dict = field(default_factory=dict)   # node_id -> SkeletonVerdict
    overall: str = "pass"                          # "pass" | "replan"
    feedback: str = ""                             # replan 时的重写建议（原文）
    degraded: bool = False                         # LLM 异常/预算不足降级标记

    @property
    def replan_nodes(self) -> list:
        return [v.node_id for v in self.verdicts.values() if not v.is_ok]

    def should_regenerate(self) -> bool:
        """需要重新生成骨架？降级（LLM 不可用）时不强制 replan——
        骨架评审是质量增强，不是正确性门，失败不应阻断求解（与 DagReviewer.degraded
        语义不同：那边假 pass 会烧预算，这里假 replan 会白重生成）。"""
        if self.degraded:
            return False
        if self.overall == "replan":
            return True
        return bool(self.replan_nodes)

    def feedback_lines(self) -> list:
        """聚合非 ok 子目标的 hint + 总体 feedback，供 regenerate_with_feedback 消费。"""
        lines = []
        for v in self.verdicts.values():
            if not v.is_ok:
                if v.hint:
                    lines.append(f"[{v.node_id}] {v.hint}")
                elif v.reason:
                    lines.append(f"[{v.node_id}] {v.reason}")
        if self.feedback:
            lines.append(self.feedback)
        if not lines:
            lines.append("请重新审视子目标分解：每个子目标必须适定（可独立判定），"
                         "且比原问题更简单（可独立推进），不要出现难度不低于原题的子目标")
        return lines

    def to_dict(self) -> dict:
        return {
            "verdicts": {nid: v.to_dict() for nid, v in self.verdicts.items()},
            "overall": self.overall,
            "feedback": self.feedback,
            "degraded": self.degraded,
            "should_regenerate": self.should_regenerate(),
        }


class SkeletonReviewerAgent(BaseAgent):
    """蓝图骨架编排层评审（老师 9/2 建议落地）。"""

    name = "SkeletonReviewer"

    def __init__(self, client, config):
        super().__init__(client, config)
        self._max_nodes = int(getattr(config, "skeleton_review_max_nodes",
                                      MAX_SKELETON_NODES) or MAX_SKELETON_NODES)

    # ----------------------------------------------------------
    # BaseAgent 抽象方法实现
    # ----------------------------------------------------------
    def run(self, ctx: TaskContext) -> TaskContext:
        """标准 Agent run 入口：从 ctx.blueprint 读 DAG → 评审 → 报告回写 ctx。"""
        if not ctx.blueprint:
            self.record(ctx, "skeleton_review", "无 ctx.blueprint，跳过")
            return ctx
        try:
            dag = BlueprintDAG.from_dict(ctx.blueprint)
        except Exception as exc:  # noqa: BLE001
            self.record(ctx, "skeleton_review", f"DAG 解析失败：{exc}")
            return ctx
        report = self.review(ctx, dag)
        ctx.skeleton_review_report = report.to_dict()
        return ctx

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def review(self, ctx: TaskContext, dag) -> SkeletonReviewReport:
        """评审整棵骨架，返回 SkeletonReviewReport。

        入参兼容 BlueprintDAG 与 dict（dict 时先解析）。
        """
        if dag is None:
            return SkeletonReviewReport(degraded=True)
        if isinstance(dag, dict):
            try:
                dag = BlueprintDAG.from_dict(dag)
            except Exception as exc:  # noqa: BLE001
                self.record(ctx, "skeleton_review", f"DAG 解析失败: {exc}")
                return SkeletonReviewReport(degraded=True)
        if not dag.nodes:
            return SkeletonReviewReport(degraded=True)
        # 预算闸门
        if ctx.is_time_critical():
            self.record(ctx, "skeleton_review", "预算不足，跳过骨架评审（放行）")
            return SkeletonReviewReport(degraded=True)

        # 节点太多时截断（防止 max_tokens 溢出）
        node_ids = list(dag.nodes.keys())[: self._max_nodes]

        try:
            from prompts.skeleton_review import (
                SKELETON_REVIEW_SYSTEM, SKELETON_REVIEW_USER_TEMPLATE)
            from utils.prefill import prefill_messages, stitch
        except ImportError:
            from submit.prompts.skeleton_review import (
                SKELETON_REVIEW_SYSTEM, SKELETON_REVIEW_USER_TEMPLATE)
            from submit.utils.prefill import prefill_messages, stitch

        # 骨架块：节点列表 + 依赖（children）+ 类型
        dag_lines = []
        for nid in node_ids:
            node = dag.nodes[nid]
            kids = node.children or []
            kids_txt = ", ".join(kids) if kids else "（叶子，需求解）"
            dag_lines.append(
                f"- [{nid}] ({node.node_type}) {node.statement[:200]}  → 子节点: {kids_txt}")
        dag_block = "\n".join(dag_lines)

        user_msg = SKELETON_REVIEW_USER_TEMPLATE.format(
            problem=(ctx.problem or "")[:1500],
            dag_block=dag_block,
        )

        # prefill 锚定顶层 JSON（同 DagReviewer/BlueprintPlanner 同根因修复）
        _PREFILL = '{"overall": '
        try:
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": SKELETON_REVIEW_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    _PREFILL,
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch(_PREFILL, resp)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SkeletonReviewer LLM 异常: %s", exc)
            return SkeletonReviewReport(degraded=True)

        if not resp:
            return SkeletonReviewReport(degraded=True)

        raw = extract_json(resp)
        if not isinstance(raw, dict):
            self.record(ctx, "skeleton_review", "骨架评审 JSON 解析失败（放行）")
            return SkeletonReviewReport(degraded=True)

        verdicts_raw = raw.get("verdicts") or {}
        verdicts: dict = {}
        for nid, v in verdicts_raw.items():
            if nid not in dag.nodes:
                continue
            if not isinstance(v, dict):
                continue
            verdict = str(v.get("verdict", "ok")).lower().strip()
            if verdict not in ("ok", "ill_posed", "not_simplifying"):
                verdict = "ok"
            verdicts[nid] = SkeletonVerdict(
                node_id=nid,
                verdict=verdict,
                reason=str(v.get("reason", ""))[:200],
                hint=str(v.get("hint", ""))[:300],
            )
        overall = str(raw.get("overall", "pass")).lower().strip()
        if overall not in ("pass", "replan"):
            overall = "replan" if verdicts and any(
                not v.is_ok for v in verdicts.values()) else "pass"
        feedback = str(raw.get("feedback", "") or "")[:600]

        report = SkeletonReviewReport(
            verdicts=verdicts, overall=overall, feedback=feedback)
        replan_nodes = report.replan_nodes
        self.record(
            ctx, "skeleton_review",
            f"骨架编排评审: 节点={len(verdicts)}, "
            f"replan={replan_nodes or ('全 ok' if not replan_nodes else '')}, "
            f"overall={overall}",
            skeleton_review_overall=overall,
            skeleton_review_replan_nodes=replan_nodes[:5],
        )
        return report
