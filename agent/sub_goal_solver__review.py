# -*- coding: utf-8 -*-
"""子目标求解器的 review 职责簇
（2026-10-08 批3：从 agent/sub_goal_solver.py 逐字搬出 6 个方法）。

搬出后为模块级函数（实例方法保留 `self` 首参，方法体逐字不变）；
原文件类内保留 1 行跳板（`_x = _sgs_review._x`）⇒ `self._x(...)` /
`SubGoalSolverAgent._x(...)` 契约逐字不变（同 verifier__review.py 批6）。
"""
from __future__ import annotations

import logging

from .base import TaskContext

logger = logging.getLogger("MathPilot")


def _review_and_maybe_replan(self, ctx, dag=None, max_replan_rounds: int = 2) -> bool:
    """评审 DAG + 三级动态修复（#34 老师要求："dag 蓝图不能是死的"）。

        三级漏斗（由精准到全局，LEAP 2.5 子树回溯 + 5.3 reviewer 信号）：
          1. 子树级局部重写：只重写 reject 节点所在子树（LCA），其余保留
          2. 整树重生成：子树修不动 / 波及根 → 全图重写（带全部 hint）
          3. 硬上限防死循环

        判定信号（DagReviewer）：
          - reject_count >= 5（绝对，9/1 由 3 调高）或 reject_ratio >= 40%（相对）→ 触发修复
        返回是否触发了任何修复。

        2026-09-17 修复（**重规划白跑**）：本方法原全程只改**局部变量 `dag`**
        （`dag = new_dag`），从不写回 `ctx.blueprint` ⇒ 重规划结果被丢弃，下游
        （merge 的 `_blueprint_conclusion`、后续 run()、其它读 ctx.blueprint 的
        agent）看到的仍是旧蓝图；实测 9 题 `dag_replan_events` 全为 []。
        现改为：确实产出新 DAG 时 `ctx.blueprint = dag.to_dict()`（与求解前评审门
        `_dag_replan_gate` 第 1591 行回写口径一致），并把评审/重规划结果写入
        `ctx.dag_review_report`（见 `_note_dag_replan`）。
        """
    prep = self._review_dag_prepare(ctx, dag, max_replan_rounds)
    if prep is None:
        return False
    (dag, reviewer, planner, rejected_ids,
     feedback_lines, replan_rounds) = prep
    for round_idx in range(replan_rounds):
        # 2026-09-13 循环时间闸（单题上限 1200→3600s 放开后的必备兜底）：
        # 本循环每轮 = 评审 + 子树/整树重生成（2-3 次 LLM，以生成为主），
        # 属 LLM 生成类；评审始终不放行时会反复重建 → 必须查生成侧软截止。
        # 用 gen_time_up()（与同族 _dag_replan_gate:1239 同口径；未设
        # _gen_deadline 时自动回退 is_time_critical）。到点跳出，保留已产出
        # 候选，不空转烧穿验证预算。
        if ctx.gen_time_up():
            self.record(ctx, "dag_replan",
                        f"生成侧时间已到，提前退出 DAG 修复循环 "
                        f"(round={round_idx + 1}/{replan_rounds})")
            self._note_dag_replan(
                ctx, triggered=True, success=True,
                reason=f"生成侧软截止已到，第 {round_idx + 1} 轮提前退出修复循环")
            break
        # 2026-09-12 定型前审核：原为 `if not ctx.budget or not True:`
        # （`or not True` 恒为 False，`A or False ≡ A`，删除属恒等变换，
        #  语义与行为完全不变）
        if not ctx.budget:
            self.record(ctx, "dag_replan",
                        f"DAG 修复预算不足，提前停止 (round={round_idx + 1})")
            self._note_dag_replan(
                ctx, triggered=True, success=False,
                reason=f"DAG 修复预算不足，第 {round_idx + 1} 轮提前停止")
            return False
        # 3a) 先试子树级局部重写（精准修改，不动好的部分）
        # 9/1 冒烟 10 题实锤：reject 波及根（LCA=根）时子树重写全白费
        # （013 子树77%>整树44%、029 71%>64%、028 80%≈80%），且 3a 的
        # 退化转发会多生成一次整树 → 直接跳过子树走 3b，省一轮 LLM+评审
        if rejected_ids:
            lca = dag._lca(rejected_ids)
            if lca is not None and lca != dag.root_id:
                new_dag = planner.regenerate_subtree(
                    ctx, prior_dag=dag, rejected_ids=rejected_ids,
                    feedback_lines=feedback_lines)
                if new_dag is not None:
                    dag = new_dag
                    # 2026-09-17：确实产出新 DAG → **回写 ctx.blueprint**，
                    # 否则重规划结果被丢弃（见方法 docstring）。
                    ctx.blueprint = dag.to_dict()
                    self._note_dag_replan(
                        ctx, triggered=True, replanned=True,
                        rejected_ids=rejected_ids, branch="subtree",
                        success=True, reason="子树级局部重写产出新 DAG")
                    self.record(ctx, "dag_replan",
                                f"DAG 子树重写: {len(dag.nodes)} 节点, "
                                f"rejected={rejected_ids[:5]}")
                    # 重写后再评审一次：通过则停，否则升级整树
                    report2 = reviewer.review(ctx, dag, results_map={})
                    if not report2.should_replan():
                        self.record(ctx, "dag_replan",
                                    "子树重写后 DAG 通过评审，停止修复")
                        self._note_dag_replan(
                            ctx, triggered=True, replanned=True,
                            rejected_ids=rejected_ids, branch="subtree",
                            success=True, reason="子树重写后 DAG 通过评审")
                        return True
                    feedback_lines = (report2.merge_from_hints().split("\n")
                                      if report2.merge_from_hints() else feedback_lines)
                    rejected_ids = report2.rejected_nodes()
                    continue  # 子树修不动 → 下一轮升级整树
        # 3b) 整树重生成（子树修不动 / 无 reject 明细 / LCA=根 时兜底）
        new_dag = planner.regenerate_with_feedback(
            ctx, prior_dag=dag, feedback_lines=feedback_lines)
        if new_dag is None:
            self.record(ctx, "dag_replan", f"第 {round_idx + 1} 轮重生成失败，停止")
            self._note_dag_replan(
                ctx, triggered=True, replanned=False, success=False,
                reason=f"第 {round_idx + 1} 轮整树重生成失败（保留原蓝图）")
            return True  # 已尝试过，标记触发
        dag = new_dag
        # 2026-09-17：确实产出新 DAG → **回写 ctx.blueprint**（同 _dag_replan_gate）。
        ctx.blueprint = dag.to_dict()
        self._note_dag_replan(
            ctx, triggered=True, replanned=True, rejected_ids=rejected_ids,
            branch="full", success=True,
            reason=f"第 {round_idx + 1}/{replan_rounds} 轮整树重生成产出新 DAG")
        self.record(ctx, "dag_replan",
                    f"DAG 第 {round_idx + 1}/{replan_rounds} 轮整树重生成: "
                    f"{len(new_dag.nodes)} 节点, root={new_dag.root_id}")
        # 重生成后再评审一次，避免死循环（重写还拒 → 停）
        # ★ 2026-09-15：改走按档位分档的上限（见 _subgoal_cap）
        new_plan = new_dag.to_subgoal_plan(
            self._subgoal_cap(ctx),
            with_deps=getattr(self.config, "blueprint_deps_enabled", True),
            or_expand_all=getattr(self.config, "blueprint_or_expand_all", False))
        subgoals = new_plan.get("subgoals", [])
        # 重生成后的 DAG 若含前瞻引理，同样入记忆（否则重写一次就丢一批）
        self._inject_anticipatory_lemmas(
            ctx, new_plan.get("anticipatory_lemmas") or [])
        if subgoals:
            # 用 placeholder 结果集触发下一轮评审（即用新 DAG 但旧求解结果视作未知）
            report2 = reviewer.review(ctx, new_dag, results_map={})
            if not report2.should_replan():
                self.record(ctx, "dag_replan",
                            "重生成 DAG 通过评审，停止整树重构")
                self._note_dag_replan(
                    ctx, triggered=True, replanned=True,
                    rejected_ids=rejected_ids, branch="full",
                    success=True, reason="整树重生成后 DAG 通过评审")
                return True
            feedback_lines = report2.merge_from_hints().split("\n") \
                if report2.merge_from_hints() else feedback_lines
    else:
        # 仅"跑满硬上限"这一既有退出路径才记录（同 _dag_replan_gate:1334 的
        # for...else 惯例）；新增的时间闸 break 提前退出时不冒领此记录。
        self.record(ctx, "dag_replan",
                    f"达到重生成硬上限 {replan_rounds} 轮，停止")
        self._note_dag_replan(
            ctx, triggered=True, success=True,
            rejected_ids=rejected_ids,
            reason=f"评审始终不通过，达到重生成硬上限 {replan_rounds} 轮")
    return True


def _review_dag_prepare(self, ctx, dag=None, max_replan_rounds: int = 2):
    """DAG 评审/重规划**前置段**（2026-10-08 批2：从 `_review_and_maybe_replan`
        原地拆出）。

        构造 DagReviewer/Planner，归一化 DAG，跑评审；不通过 / 无 DAG / 解析失败
        ⇒ `return None`（调用侧据此 `return False`）。
        通过则返回 `(dag, reviewer, planner, rejected_ids, feedback_lines,
        replan_rounds)` —— **`dag` 必须回传**：段内 `dag = BlueprintDAG.from_dict(dag)`
        重绑定了参数，若不回传则调用侧拿到的仍是 dict（回归实证会 `dict has no
        attribute '_lca'`）。
        段体**逐字搬**（4 处 `return False`→`return None` 为哨兵改写）。
        """
    from .dag_reviewer import DagReviewerAgent
    from .blueprint_planner import BlueprintDAG
    reviewer = DagReviewerAgent(self.client, self.config)
    # 1) 评审当前 DAG：兼容 BlueprintDAG 与 dict 两种入参
    if dag is None and ctx.blueprint:
        dag = ctx.blueprint
    if dag is None:
        self._note_dag_replan(ctx, triggered=False, reason="无 DAG，跳过评审")
        return None
    if isinstance(dag, dict):
        try:
            dag = BlueprintDAG.from_dict(dag)
        except Exception as exc:  # noqa: BLE001
            self.record(ctx, "dag_replan", f"DAG 解析失败: {exc}")
            self._note_dag_replan(ctx, triggered=False, success=False,
                                  reason=f"DAG 解析失败: {exc}")
            return None
    if not dag.nodes:
        self._note_dag_replan(ctx, triggered=False, reason="DAG 无节点，跳过评审")
        return None
    results_map = {sg["id"]: sg.get("result", "")
                   for sg in getattr(ctx, "subgoal_trace", []) or []}
    report = reviewer.review(ctx, dag, results_map=results_map)
    if not report.should_replan():
        # 2026-09-17：未触发也要留痕，否则 diag 无法区分"评审通过"与"压根没评审"。
        self._note_dag_replan(ctx, triggered=False, success=True,
                              rejected_ids=report.rejected_nodes(),
                              reason="DAG 评审通过，未触发重规划")
        return None
    # 2) 应修复：聚合 hint + rejected 节点（"错误的地方 + 原因"）
    from .blueprint_planner import (
        BlueprintPlannerAgent, BlueprintDAG)
    planner = BlueprintPlannerAgent(self.client, self.config)
    rejected_ids = report.rejected_nodes()
    hints = report.merge_from_hints()
    feedback_lines = hints.split("\n") if hints else []
    if not feedback_lines:
        feedback_lines.append(
            "请提供粒度更细、子目标间无循环、可独立证明的 DAG")
    # 3) 硬上限 + budget 闸
    replan_rounds = int(getattr(self.config, "dag_replan_max_rounds",
                                max_replan_rounds) or max_replan_rounds)
    replan_rounds = max(1, replan_rounds)
    return (dag, reviewer, planner, rejected_ids, feedback_lines,
            replan_rounds)


def _dag_replan_gate(self, ctx, dag, max_rounds: int = 2):
    """求解前 DAG 强制评审门：拒绝率>40% 的蓝图不许带病进求解。

        蓝图经骨架评审通过后、转子目标求解前，再用 DagReviewer 评审一次
        （results_map={} 时按结构评审：启发式循环/粒度过粗 + LLM 评估叶子
        与分解节点）。should_replan（reject≥5 或 比例≥40% 或评审降级）
        → **强制**进入带反馈重规划循环（子树局部重写 → 整树重生成），
        直到评审通过或达硬上限/预算耗尽——不允许带着高拒绝率蓝图推进求解。
        错题实证：comb-032 48%、geo-051 50%、nt-031 41.7%、nt-037 47.6%、
        nt-077 45%、nt-096 60% 的蓝图审查已亮红灯并建议重规划，但实际
        修订轮数=0（后置 replan 受 stage budget 限制 + 修复结果从不落盘）。

        与候选入池后的 _review_and_maybe_replan（事后兜底）区别：
        - 本门在求解前，replan 产生的新 DAG 真正被消费（转 plan 求解）；
          旧方法即使 replan 成功也不写回 ctx.blueprint → 白跑。
        - 预算耗尽 / 评审降级且无 reject 明细 → 放行原 DAG（质量门不阻断）。
        返回最终 DAG（已写回 ctx.blueprint）。
        """
    (_status, dag, rounds, reviewer, planner) = (
        self._dag_replan_gate_prepare(ctx, dag, max_rounds))
    if _status == "none":
        return None
    if _status == "dag":
        return dag
    for round_idx in range(rounds):
        if ctx.gen_time_up():
            self.record(ctx, "dag_replan",
                        f"求解前评审门预算耗尽（round={round_idx}），放行当前蓝图")
            break
        report = reviewer.review(ctx, dag, results_map={})
        # 门升级（2026-09-08）：Lean 逻辑层检测。仅当本轮评审已出现 reject
        # 信号（report.reject_count > 0）时，在首轮触发一次 Lean 声明编译：
        # - 编译失败的节点（含 LLM 漏判的叶子）硬升级为 reject —— Lean 抓
        #   可判定的逻辑/类型层错误（符号未定义/自引用/类型错/不成良构命题）；
        # - 方向/语义错误仍完全由 LLM 评审判，本检测绝不降低任何 reject；
        # - 成本受控：每题至多 1 次（见 _lean_dag_logic_check 守卫），
        #   无 reject 信号（评审直接放行）的题零 Lean 开销。
        # 2026-09-08 修复：**accept 叶子优先、reject 补位**。实测 reject 节点
        # 多为操作类陈述（"令 y=0…"/"平移分割…"/"建坐标系…"），无法闭合
        # 形式化 → 翻译模型按"宁缺毋滥"全给空串，整组 Lean 检查作废；且
        # reject 节点已被 LLM 判错（Lean 升级只是补证据）。真正增量在
        # "LLM 放行的叶子被 Lean 抓住"——故名额先给叶子，reject 仅补位。
        if (round_idx == 0 and report.reject_count > 0
                and not ctx.is_time_critical()):
            cap = max(1, int(getattr(self.config, "dag_lean_max_nodes",
                                     6) or 6))
            leaves = [nid for nid in report.accepted_nodes()
                      if nid in dag.nodes
                      and not dag.nodes[nid].children]
            cand = list(leaves[:cap])
            if len(cand) < cap:
                cand += [nid for nid in report.rejected_nodes()
                         if nid not in cand][:cap - len(cand)]
            lean_fails = self._lean_dag_logic_check(ctx, dag, cand)
            # ★ 2026-09-30（截图 #6）：把 Lean 检查的**结构化结果**存到 ctx。
            #   动机：用户问「可不可以用 lean 来检测有没有 sorry 的地方，
            #   像这种缺少的逻辑点是不是就是大模型需要推理出来的点」——
            #   检查结果原先只以字符串 `lean_logic_error: xxx` 混进
            #   report.results[*].issues，**没有节点级结构化记录**，
            #   无法离线做缺口性质分类（是符号未定义？还是推不出来？）。
            #   存原始 {node_id: 首条诊断} 即可，零额外开销（本就已算出）。
            try:
                ctx.lean_dag_fails = dict(lean_fails or {})
                ctx.lean_dag_checked = list(cand)
            except Exception:  # noqa: BLE001  纯埋点，绝不阻断
                pass
            if lean_fails:
                upgraded = self._merge_lean_rejects(report, lean_fails)
                if upgraded:
                    self.record(ctx, "dag_replan",
                                "求解前 Lean 逻辑错误升级 reject: "
                                + ",".join(upgraded))
        if not report.should_replan():
            self.record(ctx, "dag_replan",
                        f"求解前 DAG 评审通过（round={round_idx + 1}），进入子目标求解")
            break
        # 评审降级且无明确 reject（LLM 预算跳过）→ 不盲重构，放行
        if report.degraded and report.reject_count == 0:
            self.record(ctx, "dag_replan",
                        "求解前评审降级（无 reject 明细），放行当前蓝图")
            break
        if planner is None:
            from .blueprint_planner import BlueprintPlannerAgent
            planner = BlueprintPlannerAgent(self.client, self.config)
        rejected = report.rejected_nodes()
        hints = report.merge_from_hints()
        feedback = hints.split("\n") if hints else []
        # Lean 逻辑诊断并入重规划反馈（若本轮有升级）
        lean_lines = []
        for _r in report.results.values():
            if not _r.is_reject:
                continue
            for _iss in _r.issues:
                _t = str(_iss)
                if _t.startswith("lean_logic_error"):
                    lean_lines.append(
                        f"[{_r.node_id}] Lean 逻辑检查: "
                        f"{_t[len('lean_logic_error:'):].strip()}")
                    break
        if lean_lines:
            feedback = lean_lines + feedback
        if not feedback:
            feedback.append(
                "请重新审视蓝图拆解：结论族须覆盖题目全部约束、不引入"
                "题目未允许的假设，子目标须可独立求解且比原题简单")
        new_dag = None
        if rejected:
            lca = dag._lca(rejected)
            if lca is not None and lca != dag.root_id:
                try:
                    new_dag = planner.regenerate_subtree(
                        ctx, prior_dag=dag, rejected_ids=rejected,
                        feedback_lines=feedback)
                except Exception as exc:  # noqa: BLE001
                    self.record(ctx, "dag_replan", f"子树重写异常: {exc}")
                    new_dag = None
        if new_dag is None:
            try:
                new_dag = planner.regenerate_with_feedback(
                    ctx, prior_dag=dag, feedback_lines=feedback)
            except Exception as exc:  # noqa: BLE001
                self.record(ctx, "dag_replan", f"整树重生成异常: {exc}")
                new_dag = None
        if new_dag is None:
            self.record(ctx, "dag_replan",
                        f"求解前第 {round_idx + 1}/{rounds} 轮重规划失败，"
                        "保留当前蓝图进入求解（重规划信号已记入 diag）")
            break
        dag = new_dag
        self.record(ctx, "dag_replan",
                    f"求解前 DAG 第 {round_idx + 1}/{rounds} 轮重规划: "
                    f"{len(dag.nodes)} 节点, root={dag.root_id}")
    else:
        self.record(ctx, "dag_replan",
                    f"求解前评审门达硬上限 {rounds} 轮，采用末轮蓝图进入求解")
    ctx.blueprint = dag.to_dict()
    return dag


def _dag_replan_gate_prepare(self, ctx, dag, max_rounds):
    """求解前 DAG 评审门**前置段**（2026-10-08 批2：从 `_dag_replan_gate`
        原地拆出）。归一化 dag 并构造 reviewer/planner。

        返回 `(status, dag, rounds, reviewer, planner)`：status ∈ {none,dag,go}；
        `none`⇒调用侧 `return None`；`dag`⇒`return dag`；`go`⇒继续主循环。
        **dag 回传**（段内 `dag = BlueprintDAG.from_dict(dag)` 重绑定了参数）。
        段体**逐字搬**（3 行 return 为哨兵改写）。
        """
    from .dag_reviewer import DagReviewerAgent
    if dag is None:
        # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return None。
        self.record(ctx, "dag_replan",
                    "求解前 DAG 评审门已跳过：入参 dag 为 None")
        return ("none", None, None, None, None)
    if isinstance(dag, dict):
        from .blueprint_planner import BlueprintDAG
        try:
            dag = BlueprintDAG.from_dict(dag)
        except Exception as exc:  # noqa: BLE001
            self.record(ctx, "dag_replan", f"DAG 解析失败: {exc}")
            return ("none", None, None, None, None)
    if not dag.nodes:
        return ("dag", dag, None, None, None)
    rounds = int(getattr(self.config, "dag_replan_max_rounds",
                         max_rounds) or max_rounds)
    rounds = max(1, rounds)
    reviewer = DagReviewerAgent(self.client, self.config)
    planner = None  # 惰性导入（仅需 replan 时才建）
    return ("go", dag, rounds, reviewer, planner)


def _skeleton_review_loop(self, ctx: TaskContext, dag,
                          planner, max_rounds: int = 2):
    """骨架编排层评审循环（老师 9/2 建议：求解前规划质量门）。

        评审 → 不过 → 带评审反馈重生成骨架 → 再评审，最多 max_rounds 轮。
        结束条件：评审通过 / 预算不足 / LLM 降级 → 返回当前 DAG。
        评审是质量增强门（非正确性门）：失败降级放行，不阻断主流程。
        """
    max_rounds = int(getattr(self.config, "skeleton_review_max_rounds",
                             max_rounds) or max_rounds)
    max_rounds = max(1, max_rounds)
    for round_idx in range(max_rounds):
        from .skeleton_reviewer import SkeletonReviewerAgent
        reviewer = SkeletonReviewerAgent(self.client, self.config)
        report = reviewer.review(ctx, dag)
        if not report.should_regenerate():
            if report.degraded:
                self.record(ctx, "skeleton_review",
                            f"骨架评审降级/预算不足（round={round_idx + 1}），放行")
            else:
                self.record(ctx, "skeleton_review",
                            f"骨架评审通过（round={round_idx + 1}），进入语法审核")
            return dag
        if ctx.gen_time_up():
            self.record(ctx, "skeleton_review",
                        "骨架重生成预算不足，保留当前骨架")
            return dag
        feedback_lines = report.feedback_lines()
        new_dag = planner.regenerate_with_feedback(
            ctx, prior_dag=dag, feedback_lines=feedback_lines)
        if new_dag is None:
            self.record(ctx, "skeleton_review",
                        f"第 {round_idx + 1} 轮骨架重生成失败，保留当前骨架")
            return dag
        dag = new_dag
        # ★ 2026-10-04 修（写回）：`_review_and_maybe_replan` 早在 2026-09-17
        #   就修过同型 bug（"只改局部变量 dag，从不写回 ctx.blueprint ⇒ 重规划
        #   结果被丢弃"），但**本函数与 `_dag_replan_gate` 漏了同样的写回**
        #   ⇒ 重生成后的骨架只经返回值进入 `to_subgoal_plan`，而下游读
        #   `ctx.blueprint` 的地方（`_merge_results` 的 blueprint_conclusion、
        #   orchestrator 的 `02_blueprint` 落盘、诊断）看到的仍是**旧蓝图**
        #   ⇒ 同一份 DAG 两个版本，属"改一处=没改"。
        try:
            ctx.blueprint = dag.to_dict()
        except Exception as _e_wb:  # noqa: BLE001
            logger.warning("骨架重生成写回 ctx.blueprint 失败: %s", _e_wb)
        self.record(ctx, "skeleton_review",
                    f"骨架第 {round_idx + 1}/{max_rounds} 轮重生成: "
                    f"{len(dag.nodes)} 节点")
    self.record(ctx, "skeleton_review",
                f"骨架评审达硬上限 {max_rounds} 轮，采用末轮骨架")
    return dag


def _note_dag_replan(self, ctx, *, triggered: bool, replanned: bool = False,
                     rejected_ids: list | None = None,
                     branch: str = "", success: bool = False,
                     reason: str = "") -> None:
    """把评审/重规划结果并入 ctx.dag_review_report["replan"]（2026-09-17）。

        背景（实测 9 题 diag.dag_review 全为 {}）：DagReviewerAgent.review() 虽会
        写 ctx.dag_review_report，但它在 `is_time_critical()` / 空 DAG 处**提前
        return 就不写**；而重规划本身的触发与成败（分支 / 被拒子目标）此前
        **无任何落盘** ⇒ 无法归因"重规划到底跑没跑、跑成什么样"。
        此处补齐，且**合并写入**（保留评审器写的 results / reject_count 明细）。
        留痕失败一律吞掉，绝不阻断求解。
        """
    try:
        _rep = getattr(ctx, "dag_review_report", None)
        if not isinstance(_rep, dict):
            _rep = {}
            ctx.dag_review_report = _rep
        _rp = _rep.get("replan")
        if not isinstance(_rp, dict):
            _rp = {}
            _rep["replan"] = _rp
        _rp["triggered"] = bool(triggered)
        _rp["replanned"] = bool(replanned)
        if rejected_ids is not None:
            _rp["rejected_ids"] = [str(_x) for _x in list(rejected_ids)][:20]
        if branch:
            _branches = _rp.setdefault("branches", [])
            if branch not in _branches:
                _branches.append(branch)
        if reason:
            _rp["reason"] = reason
        _rp["success"] = bool(success)
        # 落盘后的蓝图规模/根：供 diag 判断"蓝图是否真的被换掉"
        _bp = getattr(ctx, "blueprint", None)
        if isinstance(_bp, dict) and _bp.get("nodes"):
            _rp["dag_nodes"] = len(_bp.get("nodes") or {})
            _rp["root_id"] = _bp.get("root_id")
    except Exception:  # noqa: BLE001  留痕失败不阻断
        pass
