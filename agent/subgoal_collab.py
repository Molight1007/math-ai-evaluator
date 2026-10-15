# -*- coding: utf-8 -*-
"""子目标三角色协作求解（2026-10-15 用户定案 · 第一版）。

用户三条口径（原文要点）：
 ① 子目标求解按**三个 agent 合作**：求解（完成求解目标）/ 审核（查逻辑、计算
    错误）/ 规划（为**下一个**子目标制定任务）。
 ② 规划 agent 与**蓝图**实时合作：求解产出回传蓝图（补充未知点、看能否进一步
    构建）→ 按更新后的蓝图为下一个子目标制定计划；**提前制定**（PC 指令预取
    模型：始终存着"下一个要执行的子目标计划"）。审核用**工具①**（Lean 逻辑
    检查）与**工具③**（计算验证）——求解产出必须完整返回「逻辑板块 + 计算板块」。
 ③ **无条件 3 遍生成**（蓝图 + 子目标求解）：**在现有基础上再生成**（迭代完善；
    不告知"错误"、不推倒重来）——内化重试、提高质量。

接入：drop-in 替换 `sub_goal_solver__loop.solve_subgoals`，由开关
`subgoal_collab_mode` 切换；结果写入（results_map / _subgoal_done 缓存 /
subgoal_trace / artifact）与旧循环**格式兼容**，下游 merge 零改动。
"""
from __future__ import annotations

import re
import time

# ---------------------------------------------------------------- 提示词
# ★ 2026-10-15 审核修复（F1）：求解不再用自带极简 prompt（功能子集），改复用
#   旧链 `_solve_subgoal`（承接块/formal_sig/K11 掩码/结论契约全注入）；
#   原 `_SOLVER_SYS` / `_REGEN_SYS` 已删。审核与规划仍用各自提示词：
_REVIEWER_SYS = (
    "你是数学子目标求解的审核员。你会收到：子目标、待审产出（逻辑推导/计算/结论）、"
    "以及**工具给出的客观检测结果**（计算复算 + Lean 逻辑检查）。\n"
    "请据此给出审核结论：\n"
    "① 计算错误：工具复算不一致的等式（引用其一）；\n"
    "② 逻辑问题：Lean 检查报出的错误点/缺少点；\n"
    "③ 若两者皆无问题，判「通过」。\n"
    "只输出 JSON（一行）：{\"pass\": true/false, \"issues\": [\"...\"]}"
)
_PLANNER_SYS = (
    "你是数学解题的**规划员**，同时负责维护解题蓝图。你会收到：当前蓝图的进展摘要、"
    "刚完成的子目标及其产出、以及下一个待求解子目标。\n"
    "请完成两件事：\n"
    "① 为**下一个子目标**制定**具体的求解计划**（方法、关键步骤、可用的已知结论）；\n"
    "② 判断刚刚的产出是否为蓝图**补充了未知点**（新事实/新条件/可细化的节点）——"
    "若有，简述应补充进蓝图的内容；没有就写「无」。\n"
    "输出格式：\n"
    "## 下一个子目标计划\n...\n## 蓝图补充\n..."
)


def _enabled(solver) -> bool:
    """开关 subgoal_collab_mode（默认 False —— 可 A/B，验证后翻默认）。"""
    try:
        from .switch_registry import get_bool as _g
        return bool(_g("subgoal_collab_mode"))
    except Exception:  # noqa: BLE001
        return bool(getattr(getattr(solver, "config", None),
                            "subgoal_collab_mode", False))


def _rounds(solver) -> int:
    """3 遍生成的轮数（默认 3；1 = 关闭迭代）。"""
    try:
        v = int(getattr(getattr(solver, "config", None),
                        "subgoal_collab_regen_rounds", 3) or 3)
    except Exception:  # noqa: BLE001
        v = 3
    return max(1, min(v, 5))


def _llm(solver, ctx, sys_text: str, user_text: str, temp: float = 0.3):
    """包装 solver.llm：失败返回 ""（绝不抛，与主链口径一致）。"""
    try:
        r = solver.llm(
            ctx,
            [{"role": "system", "content": sys_text},
             {"role": "user", "content": user_text}],
            temp,
            int(getattr(getattr(solver, "config", None),
                        "policy_max_tokens", 8192) or 8192),
        )
        return str(r or "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- 板块提取
def _section(text: str, name: str) -> str:
    """提取 "## name" 到下一个 "## " 之间的内容（没有则返回 ""）。"""
    t = str(text or "")
    m = re.search(r"##\s*" + re.escape(name) + r"\s*\n([\s\S]*?)(?=\n##\s|\Z)", t)
    return (m.group(1).strip() if m else "")


def split_blocks(text: str) -> dict:
    """求解产出 → {"logic", "calc", "result"}（三节缺失时兜底整段进 result）。"""
    t = str(text or "")
    logic = _section(t, "逻辑推导")
    calc = _section(t, "计算")
    result = _section(t, "结论")
    if not (logic or calc or result):
        result = t.strip()
    return {"logic": logic, "calc": calc, "result": result}


# ---------------------------------------------------------------- ① 求解 agent
def solve_agent(solver, ctx, sg: dict, plan: str, prev: str = "",
                rnd: int = 0, prev_results: str = "") -> str:
    """求解一个子目标（★ 2026-10-15 审核修复 F1：**复用旧链单步求解**）。

    旧链 `_solve_subgoal` 承载全部注入与机制（承接块 / formal_sig / 定理线索 /
    K11 掩码 / 结论契约 / 工具兑现 / 自改进 / 重试）——此前 collab 自带极简
    prompt 属「功能子集」，开启即降级；现**直接复用**，杜绝子集。

    rnd>0 = 「在现有基础上再生成」：上一轮产出经 `extra_hint` 带回
    （语义即"带反馈重解"，**不告知"有错"、不推倒重来**）。
    """
    _hint = str(plan or "")
    if prev and rnd > 0:
        _hint = (_hint + "\n\n【上一轮产出——请在此基础上继续深化：补齐遗漏、"
                 "加强严谨性、核对每一处计算；不要推倒重来】\n" + prev[-6000:])
    try:
        out = solver._solve_subgoal(ctx, sg, _hint, prev_results, _hint) or ""
    except Exception as _e:  # noqa: BLE001  单步失败不抛（由调用方记/降级链处理）
        solver.record(ctx, "subgoal_collab",
                      "①求解异常（%s）: %s: %s"
                      % (str(sg.get("title") or "")[:30],
                         type(_e).__name__, str(_e)[:120]))
        return ""
    try:
        solver.record(ctx, "subgoal_collab",
                      "①求解 %s（第%d遍，产出 %d 字）"
                      % (str(sg.get("title") or "")[:40], rnd + 1, len(out)))
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------- ② 审核 agent
def review_agent(solver, ctx, sg: dict, out_text: str) -> dict:
    """工具③ 复算计算板块 + 工具① Lean 检逻辑板块 → 审核结论。

    返回 {"pass": bool, "issues": [...], "tool_report": {...}}。
    任何工具不可用 ⇒ 该维度跳过（不阻塞、不误杀）。
    """
    blocks = split_blocks(out_text)
    issues, tool_report = [], {}

    # —— 工具③：计算板块逐条复算 ——
    try:
        from .math_check_gate import _extract_numeric_equations
        eqs = _extract_numeric_equations(blocks.get("calc", "") or out_text)
        if eqs:
            from tools.agent_toolkit import calc_verify
            r = calc_verify([{"expr": a, "claimed": b} for a, b in eqs[:8]])
            tool_report["calc"] = {"n": len(eqs), "n_bad": r.get("n_bad", 0)}
            for x in (r.get("results") or []):
                if not x.get("ok"):
                    issues.append("计算错误：%s = %s 实际为 %s"
                                  % (str(x.get("expr"))[:60],
                                     str(x.get("claimed"))[:30],
                                     str(x.get("actual"))[:30]))
    except Exception:  # noqa: BLE001
        pass

    # —— 工具①：对「结论+逻辑」做 Lean 逻辑检查（可选，环境不可用则跳过）——
    try:
        from tools.agent_toolkit import lean_check, to_lean
        _stmt = (blocks.get("result") or "").strip()
        _ctx_txt = ((str(sg.get("title") or "") + "；"
                     + blocks.get("logic", "")[:800]))
        if _stmt:
            tr = to_lean(_stmt, context=_ctx_txt,
                         client=getattr(solver, "client", None))
            if tr.get("ok"):
                lr = lean_check(lean_code=tr["lean_code"],
                                problem=str(getattr(ctx, "problem", "") or ""),
                                client=getattr(solver, "client", None))
                _lv = str(lr.get("verdict") or "")
                tool_report["lean"] = {
                    "verdict": _lv,
                    "n_missing": len(lr.get("missing") or [])}
                # ★ 2026-10-15 审核修复（S8）：本检查的定位 = 「结论陈述的可
                #   形式化性」——to_lean 恒产出 `by sorry` 骨架 ⇒ 常态
                #   verdict=proof_incomplete（missing 计入 tool_report 供追溯，
                #   **不构成问题**、不触发重解）；statement_error / proof_failed
                #   = 陈述/类型病态 ⇒ 真问题。`disproved` 死值已删（lean_check
                #   从不返回它）。
                if _lv in ("statement_error", "proof_failed"):
                    for e in (lr.get("errors") or [])[:2]:
                        issues.append("逻辑问题（%s）：%s"
                                      % (_lv, str(e.get("detail"))[:120]))
    except Exception:  # noqa: BLE001
        pass

    # —— LLM 综合（把工具结果交给审核 agent 归纳）——
    if issues:
        verdict = {"pass": False, "issues": issues[:6]}
    else:
        _llm_out = _llm(solver, ctx, _REVIEWER_SYS,
                        "【子目标】%s\n【待审产出】\n%s\n\n【客观检测】\n%s"
                        % (str(sg.get("title") or "")[:120], out_text[-3000:],
                           str(tool_report)), temp=0.1)
        m = re.search(r"\{[\s\S]*\}", _llm_out or "")
        verdict = None
        if m:
            try:
                import json as _json
                d = _json.loads(m.group(0))
                verdict = {"pass": bool(d.get("pass", True)),
                           "issues": [str(x)[:160] for x in (d.get("issues") or [])][:5]}
            except Exception:  # noqa: BLE001
                verdict = None
        if verdict is None:
            verdict = {"pass": True, "issues": []}
    verdict["tool_report"] = tool_report
    try:
        solver.record(ctx, "subgoal_collab",
                      "②审核 %s：pass=%s%s"
                      % (str(sg.get("title") or "")[:40], verdict["pass"],
                         ("；" + "；".join(verdict["issues"][:2]))
                         if verdict["issues"] else ""))
    except Exception:  # noqa: BLE001
        pass
    return verdict


# ---------------------------------------------------------------- ③ 规划 agent
def planning_agent(solver, ctx, sg_next: dict, solved_digest: str,
                   blueprint_digest: str) -> str:
    """为**下一个**子目标制定计划（预取）+ 蓝图补充建议。

    返回计划文本；蓝图补充写入 `ctx.subgoal_blueprint_updates`（list）。
    """
    if not sg_next:
        return ""
    user = ("【蓝图进展摘要】\n%s\n\n【刚完成的子目标产出摘要】\n%s\n\n"
            "【下一个待求解子目标】%s\n%s"
            % ((blueprint_digest or "（无）")[:1200],
               (solved_digest or "（无）")[:1500],
               str(sg_next.get("title") or ""),
               str(sg_next.get("description") or "")[:600]))
    out = _llm(solver, ctx, _PLANNER_SYS, user, temp=0.2)
    plan = _section(out, "下一个子目标计划") or out.strip()
    _bp = _section(out, "蓝图补充")
    if _bp and _bp.strip() not in ("无", "（无）", "None"):
        try:
            ups = list(getattr(ctx, "subgoal_blueprint_updates", None) or [])
            ups.append({"after": str(sg_next.get("title") or ""),
                        "update": _bp[:600]})
            ctx.subgoal_blueprint_updates = ups
        except Exception:  # noqa: BLE001
            pass
    try:
        solver.record(ctx, "subgoal_collab",
                      "③规划 下一个子目标：%s（计划 %d 字%s）"
                      % (str(sg_next.get("title") or "")[:40], len(plan),
                         "，含蓝图补充" if _bp else ""))
    except Exception:  # noqa: BLE001
        pass
    return plan


# ---------------------------------------------------------------- 主循环
def solve_subgoals_collab(solver, ctx, subgoals, subgoal_plan_summary,
                          results_map) -> int:
    """三角色协作逐步求解（drop-in 替换 `solve_subgoals`）。

    返回 `_ctx_inject_chars`（与旧循环同语义；第一版按产出字符数近似累计）。
    """
    from .sub_goal_solver import _artifact_append
    _ctx_inject_chars = 0

    # 复用缓存（与旧循环同口径：同 run() 多次调用不重解）
    _reuse_on = bool(getattr(solver.config, "subgoal_reuse_done", True))
    _done = getattr(ctx, "_subgoal_done", None)
    if not isinstance(_done, dict):
        _done = {}
        try:
            setattr(ctx, "_subgoal_done", _done)
        except Exception:  # noqa: BLE001
            pass

    _n = _rounds(solver)
    _blueprint_digest = ""
    _done_digest = ""          # 已完成子目标结论摘要（作 prev_results 供后续步）

    # ★ 预取（PC 指令预取模型）：先为**第一个**子目标制定计划
    _next_plan = planning_agent(
        solver, ctx, subgoals[0] if subgoals else {}, "",
        subgoal_plan_summary or "")

    for _idx, sg in enumerate(subgoals):
        _title = str(sg.get("title") or "")
        # 复用命中 → 零 LLM 调用（与旧循环一致）
        _fp = "|".join(str(sg.get(_k, "")) for _k in
                       ("title", "description", "type"))[:240]
        if _reuse_on and _fp in _done:
            _cached = _done[_fp]
            step_result = (str(_cached.get("result") or "")
                           if isinstance(_cached, dict) else str(_cached))
            if isinstance(_cached, dict):
                try:
                    solver._restore_contract(sg, _cached.get("contract") or {})
                except Exception:  # noqa: BLE001
                    pass
            results_map[sg["id"]] = step_result
            try:
                ctx.subgoal_trace.append(
                    solver._build_trace_item(sg, step_result, reused=True))
                _artifact_append(ctx, "04_subgoal_results",
                                 ctx.subgoal_trace[-1])
            except Exception:  # noqa: BLE001
                pass
            solver.record(ctx, "subgoal_collab", "复用已完成子目标：%s" % _title[:40])
            continue

        # ① 求解 ×N（无条件、在现有基础上再生成；复用旧链单步求解）
        _t0 = time.time()
        _out = ""
        for _r in range(_n):
            _out = solve_agent(solver, ctx, sg, _next_plan, prev=_out,
                               rnd=_r, prev_results=_done_digest)

        # ★ 2026-10-15 审核修复（F2）：动态倒推（拆图补前提；内部双闸门
        #   `sg_missing_premise` 自判触发）——与旧循环同位置（recover 之后）。
        try:
            from .sub_goal_solver__backward import sg_dynamic_backward as _bd
            _bd_out = _bd(solver, ctx, sg, _out, _next_plan, _done_digest,
                          results_map)
            if _bd_out and len(str(_bd_out)) > 20:
                _out = str(_bd_out)
        except Exception as _e_bd:  # noqa: BLE001
            solver.record(ctx, "subgoal_collab",
                          "动态倒推异常（不阻断）: %s: %s"
                          % (type(_e_bd).__name__, str(_e_bd)[:100]))

        # ② 审核（工具③ + 工具①）；不通过 → 带审核意见重解 1 次（经旧链单步）
        _rev = review_agent(solver, ctx, sg, _out)
        if not (_rev.get("pass", True)) and _rev.get("issues"):
            _fb = "【审核意见（请修正）】\n" + "\n".join(_rev["issues"])
            try:
                _out2 = solver._solve_subgoal(ctx, sg, _next_plan,
                                              _done_digest, _fb) or ""
            except Exception:  # noqa: BLE001
                _out2 = ""
            if _out2 and len(_out2) > 40:
                _out = _out2
                solver.record(ctx, "subgoal_collab",
                              "②审核未过 → 带反馈重解：%s" % _title[:40])

        # 剥 <check> 协议标签（防污染下游提示词 / 终答；与旧循环同口径）
        try:
            _out = solver._strip_check_tags(_out) or _out
        except Exception:  # noqa: BLE001
            pass

        _blocks = split_blocks(_out)
        step_result = _blocks.get("result") or _out.strip()

        # 写入（与旧循环格式兼容）
        try:
            results_map[sg["id"]] = step_result
            try:
                from .sub_goal_solver__contract import _parse_step_contract
                _contract = _parse_step_contract(step_result) or {}
            except Exception:  # noqa: BLE001
                _contract = {}
            _done[_fp] = {"result": step_result, "contract": _contract}
            ctx.subgoal_trace.append(solver._build_trace_item(sg, step_result))
            _artifact_append(ctx, "04_subgoal_results", ctx.subgoal_trace[-1])
        except Exception as _e_w:  # noqa: BLE001
            solver.record(ctx, "subgoal_collab",
                          "写入异常（不阻断）：%s: %s"
                          % (type(_e_w).__name__, str(_e_w)[:100]))

        _ctx_inject_chars += len(_out)
        _elapsed = time.time() - _t0
        solver.record(ctx, "subgoal_collab",
                      "子目标 %d/%d 完成：%s（%d 遍 + 审核，%.0fs）"
                      % (_idx + 1, len(subgoals), _title[:40], _n, _elapsed))

        # ③ 规划（预取下一个）+ 蓝图回传
        _digest = ("结论：%s\n逻辑要点：%s"
                   % (step_result[:400], _blocks.get("logic", "")[:600]))
        _sg_next = subgoals[_idx + 1] if _idx + 1 < len(subgoals) else {}
        _next_plan = planning_agent(solver, ctx, _sg_next, _digest,
                                    _blueprint_digest or (subgoal_plan_summary or ""))
        _blueprint_digest = (_blueprint_digest + "\n" + _digest)[-2000:]
        _done_digest = (_done_digest + "\n" + "【%s】%s" % (_title[:30], _digest))[-3000:]

    # 落一份协作全景（可观测）
    try:
        ctx.subgoal_collab_diag = {
            "enabled": True, "n_subgoals": len(subgoals),
            "regen_rounds": _n,
            "blueprint_updates": list(
                getattr(ctx, "subgoal_blueprint_updates", None) or [])[:8],
        }
    except Exception:  # noqa: BLE001
        pass
    return _ctx_inject_chars
