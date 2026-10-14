# -*- coding: utf-8 -*-
"""子目标求解器的 format 职责簇
（2026-10-08 批3：从 agent/sub_goal_solver.py 逐字搬出 10 个方法）。

搬出后为模块级函数（实例方法保留 `self` 首参，方法体逐字不变）；
跨模块引用原文件模块级符号者（含 `SubGoalSolverAgent` 与其常量/函数）
在**函数体内惰性 import**（避免循环导入）—— 下表已显式列出。
原文件类内保留 1 行跳板（`_x = _sgs_format._x`）⇒ `self._x(...)` /
`SubGoalSolverAgent._x(...)` 契约逐字不变（同 verifier__review.py 批6）。
"""
from __future__ import annotations

import re

from .base import TaskContext



def _blueprint_conclusion(ctx: TaskContext) -> str:
    """从 ctx.blueprint 提取 root 节点结论文本（供 merge 输出对齐）。

        兼容 dict（{root_id, nodes}) 与 list（nodes 为 [ {...} ]）两种形态；
        提取失败返回占位文本（不阻断 merge）。
        """
    try:
        bp = getattr(ctx, "blueprint", None)
        if not bp:
            return "（无——按题目与子目标规划合并）"
        if not isinstance(bp, dict):
            return "（无——按题目与子目标规划合并）"
        root_id = bp.get("root_id") or ""
        nodes = bp.get("nodes") or []
        if isinstance(nodes, dict):
            node = nodes.get(root_id) if root_id else None
        else:  # list 形态：[{"id":..., "statement":...}, ...]
            node = None
            for n in nodes:
                if isinstance(n, dict) and n.get("id") == root_id:
                    node = n
                    break
        stmt = (node or {}).get("statement") if isinstance(node, dict) else ""
        if stmt and str(stmt).strip():
            return str(stmt).strip()[:400]
        return "（蓝图无显式最终结论——按题目与子目标规划合并）"
    except Exception:  # noqa: BLE001  提取失败不阻断 merge
        return "（无——按题目与子目标规划合并）"


def _build_trace_item(sg: dict, step_result: str, reused: bool = False) -> dict:
    """构建一条 `ctx.subgoal_trace` 记录（唯一出口，防两处漂移）。

        2026-10-06（子目标交付重写 A/B/C）：在原有字段基础上补上结论契约与
        客观判定的可归因字段 —— 这些字段进 `diag.subgoal_trace`（结果文件），
        使"这一步到底交付了什么、有没有被客观判定过、有没有推导支撑"**可被
        事后核验**（此前只能看到 `result` 与空的 `expected_output`）。
        """
    item = {
        "id": sg["id"],
        "title": sg["title"],
        "description": sg["description"],
        "type": sg["type"],
        "calc_kind": sg.get("calc_kind", "inline"),
        "depends_on": sg["depends_on"],
        "expected_output": sg["expected_output"],
        "result": step_result,
        # ★ 阶段二-1/二-2：保留全部候选（「淘汰」→「保留」）+ 抽取答案 + 客观验证下标。
        "candidates": list(sg.get("candidates") or []),
        "candidates_picked_index": sg.get("candidates_picked_index", -1),
        "candidate_answers": list(sg.get("candidate_answers") or []),
        "candidates_verified_index": sg.get("candidates_verified_index", -1),
        # ---- 2026-10-06 结论契约（A/C）----
        "conclusion": sg.get("conclusion", ""),
        "conclusion_kind": sg.get("conclusion_kind", ""),
        "conclusion_support": sg.get("conclusion_support", ""),
        "conclusion_contract_ok": sg.get("conclusion_contract_ok", False),
        "has_derivation": sg.get("has_derivation", False),
        "derivation_chars": sg.get("derivation_chars", 0),
        # ---- 2026-10-06 客观判定（B）----
        "objective_verdict": sg.get("objective_verdict", ""),
        "objective_reason": sg.get("objective_reason", ""),
        # ---- 2026-10-07 `<check>` 协议违规（问题 2.9，可见化）----
        "check_protocol_violations": list(
            sg.get("check_protocol_violations") or []),
    }
    if reused:
        item["reused"] = True
    return item


def _subgoal_stats(subgoals: list[dict]) -> dict:
    """S4-lite 独立性指标（老师 9/6：减少子目标数、降低上下文依赖）。

        返回 n_subgoals / dep_edges（依赖边总数）/ avg_indegree（平均入度，
        越小独立性越高，0 = 全独立）/ dep_free（零依赖子目标数）。
        进 diag 供 A/B 对照（S2 deps 模式是否真降了上下文与依赖）。
        """
    n = len(subgoals)
    edges = sum(len(sg.get("depends_on") or []) for sg in subgoals)
    dep_free = sum(
        0 if (sg.get("depends_on") or []) else 1 for sg in subgoals)
    return {
        "n_subgoals": n,
        "dep_edges": edges,
        "avg_indegree": round(edges / n, 2) if n else 0.0,
        "dep_free": dep_free,
    }


def _format_plan_summary(subgoals: list[dict], merge_strategy: str) -> str:
    """格式化子目标规划摘要（用于后续步骤提示）"""
    lines = []
    for sg in subgoals:
        deps = f"依赖: {sg['depends_on']}" if sg["depends_on"] else "无依赖"
        lines.append(
            f"  #{sg['id']} [{sg['type']}] {sg['title']}"
            f"  → {sg['description']} ({deps})"
        )
    if merge_strategy:
        lines.append(f"\n合并策略: {merge_strategy}")
    return "\n".join(lines)


def _format_previous_results(results_map: dict[int, str],
                             subgoals: list[dict]) -> str:
    """格式化已求解的子目标结果（全量前序，subgoal_ctx_mode="all" 时用）"""
    if not results_map:
        return "（尚无前置结果）"
    lines = []
    for sg in subgoals:
        if sg["id"] in results_map:
            lines.append(f"  子目标 #{sg['id']}「{sg['title']}」结果: {results_map[sg['id']]}")
    return "\n".join(lines) if lines else "（尚无前置结果）"


def _format_dep_results(results_map: dict[int, str],
                        subgoals: list[dict], sg: dict) -> str:
    """按 depends_on 只注入**直接依赖**的结果（老师 9/6 建议：子目标独立性、
        最小上下文依赖）。无依赖 / 依赖未解出 → 返回空串（零前序上下文），
        让独立子目标可并行、不被无关中间量污染。id 缺失容错：依赖未解出跳过。

        与 _format_previous_results 的区别：后者把**所有**已解子目标都塞进
        提示词（O(n²) 上下文膨胀）；本函数只带声明依赖的少数几条。
        """
    deps = [d for d in (sg.get("depends_on") or []) if d in results_map]
    if not deps:
        return ""
    title_map = {s.get("id"): (s.get("title") or "") for s in subgoals}
    lines = []
    for d in deps:
        _txt = str(results_map[d])
        _title = title_map.get(d, "")
        # 2026-09-14 P1：**切断"基准污染"链**。
        # 实测 #098 的基准子目标违规吐 `\boxed{D}`；而 #103 的「判定选项 E」
        # 直接输出 `\boxed{ABCD}`（照抄了基准的答案形态）⇒ 聚合层认不出 E。
        # 故：基准结果里若出现 `\boxed{...}`，注入下游**前**剥离外壳并加显式告警。
        if "基准" in _title and "\\boxed" in _txt:
            _txt = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", _txt)
            _txt = ("（⚠ 本基准曾误输出最终答案，其 `\\boxed` 外壳已被系统剥离；"
                    "请只把它当作**判断依据**，**不要照抄**为任何选项的答案）"
                    + _txt)
        lines.append(f"  子目标 #{d}「{_title}」结果: {_txt}")
    # 2026-09-14 P1：**依赖未产出时的降级**（实测 #110）。
    # #110 的基准子目标求解失败 ⇒ 注入字符数 = 0 ⇒ 依赖它的选项子目标
    # 拿到空上下文、整个判定链断掉（gold A / 模型 D）。
    # 故：声明的依赖**全部未解出**时不再返回空串，而是显式告知下游
    # "共享依据缺失，请独立完成"，避免静默断链。
    _declared = [d for d in (sg.get("depends_on") or [])]
    if _declared and not deps:
        _names = "、".join(
            "#{}「{}」".format(d, title_map.get(d, "")) for d in _declared)
        return ("  （⚠ 前置子目标 {} **未能产出有效结果**，本次无法提供共享依据；"
                "请**基于题目本身独立完成**本步判定，"
                "不要因缺少依据而放弃或空转）").format(_names)
    return "\n".join(lines)


def _extract_option_verdict(cls, text: str):
    """从选项子目标的结果里解析出「正确 / 错误」；解析不到返回 None。

        按**优先级**匹配（先"结论："和"选项X："这类强信号，再退到独立词）。
        解析不到 ⇒ 调用方应显式标注"判定缺失"，让合并层单独复核，
        **不得**默认当作"跳过"（那正是 #103 丢 E 的机制）。
        """
    t = str(text or "")
    if not t:
        return None
    # 先看强信号（"结论：" / "选项X："）
    for pat, verdict in cls._VERDICT_PATTERNS[:4]:
        if pat.search(t):
            return verdict
    # 再退到独立词（但同一结果里两种都有 ⇒ 歧义，返回 None）
    has_ok = bool(cls._VERDICT_PATTERNS[4][0].search(t))
    has_no = bool(cls._VERDICT_PATTERNS[5][0].search(t))
    if has_ok and not has_no:
        return "正确"
    if has_no and not has_ok:
        return "错误"
    return None


def _format_all_results(results_map: dict[int, str],
                        subgoals: list[dict]) -> str:
    """格式化所有子目标结果"""
    from .sub_goal_solver import SubGoalSolverAgent
    lines = []
    for sg in subgoals:
        result = results_map.get(sg["id"], "（未求解）")
        _title = str(sg.get("title") or "")
        _txt = str(result)
        # 2026-09-14：聚合层不再依赖模型的格式自觉（实测 #103/#107/#110）——
        # 对「判定选项 X」子目标**解析结论并结构化前置**，使合并层无需理解
        # 自由文本即可汇总；解析不到则显式标注"判定缺失，需单独复核"。
        _m = re.match(r"^判定选项\s*([A-E])\s*$", _title.strip())
        if _m:
            _lab = _m.group(1)
            _v = SubGoalSolverAgent._extract_option_verdict(_txt)
            if _v:
                _txt = "【系统解析：选项 {} = {}】{}".format(_lab, _v, _txt[:400])
            else:
                _txt = (
                    "（⚠ 本步**未给出明确结论** —— 既无『结论：正确/错误』"
                    "也无『选项{}：正确/错误』，原文：{}；"
                    "合并时请**单独复核选项 {}**，"
                    "**不得**因其格式不规范而默认排除）"
                ).format(_lab, _txt[:200], _lab)
        lines.append(f"子目标 #{sg['id']}「{_title}」: {_txt}")
    return "\n".join(lines)


def _fallback_from_last_subgoal(subgoals: list[dict]) -> str:
    """兜底：使用最后一个**剥壳后仍有实质内容**的子目标结果。

        2026-09-17 两处修复（实测 official112-025）：
        ① 返回前剥壳：子目标 result 可能是 `</tool_call>` 这类纯工具残留，
           原样返回会把标签当最终答案（025 的 5/6 候选即此形态）；
        ② 倒序找第一个**剥壳后非空**的结果：原实现只看 `sg.get("result")`
           真值，若最后一个子目标是空壳（纯标签）就被当答案返回，故剥壳后
           为空则继续往前找，避免"空壳顶替真结论"。
        """
    from .sub_goal_solver import SubGoalSolverAgent
    # ★ 2026-10-06（结论契约）：结论契约生效后 `result` 会包含「结论行 +
    #   依据行 + 验算段」，整体当最终答案过于冗长 ⇒ **优先取结构化结论**
    #   （`value`/`equation` 形态可直接作为答案），没有再退回 result。
    for sg in reversed(subgoals):
        _concl = str(sg.get("conclusion") or "").strip()
        if _concl:
            return SubGoalSolverAgent._strip_tool_residue(_concl).strip()
        _res = sg.get("result")
        if not _res:
            continue
        _clean = SubGoalSolverAgent._strip_tool_residue(str(_res)).strip()
        if _clean:
            return _clean
    return "无法求解"


def _build_full_reasoning(subgoals: list[dict],
                          problem_goal: dict,
                          final_answer: str) -> str:
    """构建完整的推理过程文本（用于展示和回溯）。

    ★ 2026-10-14（任务列表 #3）：原「## 问题分析」区块读的是蓝图 / 子目标规划
      自产的 `problem_analysis`（同一件事被推了三遍），现改读 2.6 的**唯一题目
      目标** `ctx.problem_goal`（`agent/problem_goal.py`），该副本字段已删除。
    """
    lines = ["# 子目标分解求解过程\n"]
    if problem_goal:
        lines.append(f"## 题目目标\n题型: {problem_goal.get('question_type', 'N/A')}")
        lines.append(f"要做什么: {problem_goal.get('task', 'N/A')}\n")
    lines.append("## 子目标规划")
    for sg in subgoals:
        lines.append(f"  #{sg['id']} [{sg['type']}] {sg['title']}: {sg['description']}")
    lines.append("\n## 逐步求解")
    for sg in subgoals:
        lines.append(f"\n### 子目标 #{sg['id']}「{sg['title']}」")
        lines.append(f"结果: {sg.get('result', '未求解')}")
    lines.append(f"\n## 最终答案\n{final_answer}")
    return "\n".join(lines)
