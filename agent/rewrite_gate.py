# -*- coding: utf-8 -*-
"""4.6 重写通道 —— 五道审核链配套（2026-10-14 用户定案）。

用户口径（原话）：「不要这个东西（emergency 直答兜底）！没有答案了就讲错误
情况返回给大模型，让大模型找到问题出在哪里，重新构建蓝图和子目标，重写」。

职责：当五道审核把候选**全部淘汰**（池空）时，不走"直接要一个答案"，而是：
  ① 汇总错误情况（各道淘汰原因：pool_empty_errors + 各道 rejected 清单）；
  ② **大模型诊断**：找出问题出在哪里（root_cause）+ 给出重写调整指令（fix）；
  ③ **重新构建蓝图和子目标 + 重写**：把「错误情况 + 诊断」写入
     `ctx.rewrite_context`（经蓝图/子目标规划的"题目"占位符内部注入），
     重置规划状态后重跑 `sub_goal_solver.run`（蓝图 DAG → 子目标 → 逐步求解
     → 合并 ⇒ 追加新候选）；
  ④ 新候选**重过五道链**（规范化→自审→证伪→Lean→计算→投票）；
  ⑤ 仍全灭 ⇒ 带着上一轮错误再循环（上限 `rewrite_max_rounds`，默认 2）。

判定纪律：
  · 触发条件 = `ctx.candidates` 为空（五道链清空池）；池非空 ⇒ 本阶段不动作；
  · 轮数耗尽仍空 ⇒ 留痕交下游（formatter 的"必须有答案"兜底仍在地基，
    但不再是"池空直接要答案"的路径——先修复，修复尽再走）；
  · 任何异常 ⇒ 记录后不阻断主链。

观测：trace step=``rewrite``，diag 键 ``rewrite_gate`` / ``rewrite_gate_events``。

五道链位置：4.0 → 4.1 → 4.2 → 4.3 → 4.4 → 4.5 → **4.6_rewrite（池空修复）** → 6_format。
"""
from __future__ import annotations

from .switch_registry import get_bool as _sw_get_bool

_PROBLEM_MAX = 4000
_ERRORS_MAX = 3000
_REJECTED_MAX = 1600
_CTX_MAX = 2500        # 注入 rewrite_context 的总长度（蓝图/规划共用）


def _parse_diag_json(raw) -> dict:
    """容错解析诊断输出。{} = 无法解析（调用方用裸错误摘要继续重写）。"""
    if not raw:
        return {}
    txt = str(raw).strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
    try:
        import json as _json_rw
        _m = txt[txt.find("{"):txt.rfind("}") + 1] if "{" in txt else ""
        if not _m:
            return {}
        d = _json_rw.loads(_m)
        if not isinstance(d, dict):
            return {}
        if not (d.get("root_cause") or d.get("fix")):
            return {}
        return {"root_cause": str(d.get("root_cause") or "").strip()[:600],
                "fix": str(d.get("fix") or "").strip()[:1200]}
    except Exception:  # noqa: BLE001
        return {}


def _switch_enabled() -> bool:
    """读「五道链·重写通道」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_rewrite")
    except Exception:  # noqa: BLE001
        return True


def _collect_error_brief(ctx) -> str:
    """汇总各道淘汰原因（错误情况）。无留痕时给保守描述。"""
    lines = []
    for e in (getattr(ctx, "pool_empty_errors", None) or []):
        if isinstance(e, dict):
            lines.append("- [%s] %s" % (e.get("stage") or e.get("kind") or "?",
                                        (e.get("error") or "")[:220]))
    for _key, _tag in (("self_audit_rejected", "4.1自审"),
                       ("adversarial_gate_rejected", "4.2证伪"),
                       ("math_check_rejected", "4.4计算检测")):
        for r in (getattr(ctx, _key, None) or []):
            if isinstance(r, dict):
                lines.append("- [%s] %s" % (_tag, str(
                    r.get("error_desc") or r.get("reason")
                    or r.get("evidence") or "")[:220]))
    _lg = getattr(ctx, "lean_gate", None)
    if isinstance(_lg, list):
        for g in _lg:
            if not isinstance(g, dict):
                continue
            # ★ 2026-10-15 审核修复（S3）：lean_gate 的实际字段口径 ——
            #   verdict ∈ {proof_invalid, unknown}；strict 拒绝落在 `degraded`
            #   （如 "strict_reject"）；错误文本在 `feedback`。原实现只读
            #   verdict∈{reject,strict_reject}/reason ⇒ 两类淘汰原因全部丢失。
            _v = str(g.get("verdict") or "")
            _deg = str(g.get("degraded") or "")
            if (_v in ("reject", "strict_reject", "proof_invalid")
                    or _deg == "strict_reject"):
                _txt = str(g.get("feedback") or g.get("reason")
                           or g.get("error") or "").strip()
                lines.append("- [4.3Lean] %s%s"
                             % (_txt[:180] or "(无文本)",
                                ("（degraded=%s）" % _deg) if _deg else ""))
    if not lines:
        lines.append("（无具体错误点留痕：候选在各道被整体淘汰，或错误点未记录）")
    return "\n".join(lines)[:_ERRORS_MAX]


def _collect_rejected_brief(ctx) -> str:
    """被淘汰候选答案摘要（含各道原因缩略）。"""
    lines = []
    for _key, _tag in (("self_audit_rejected", "4.1"),
                       ("adversarial_gate_rejected", "4.2"),
                       ("math_check_rejected", "4.4")):
        for r in (getattr(ctx, _key, None) or []):
            if isinstance(r, dict):
                lines.append("- [%s] %s" % (_tag, str(r.get("answer") or "")[:60]))
    return "\n".join(lines)[:_REJECTED_MAX] or "（无）"


def _reset_plan_state(ctx) -> None:
    """重置规划/求解状态，使「重建蓝图和子目标」真实重跑（而非复用旧产物）。"""
    # ★ 2026-10-17（p0b5_r3 审核）：原实现漏清 `_subgoal_done`（子目标结果缓存）
    #   ⇒ 重写时旧子目标指纹命中缓存、直接复用旧结果 ⇒ 产出候选与上一轮相同
    #   （题6/7 重写后仍是旧的 \boxed{4}/\boxed{76} 的根因）。一并清除。
    for _f in ("blueprint_plan", "blueprint_nodes", "_subgoal_done"):
        try:
            setattr(ctx, _f, None)
        except Exception:  # noqa: BLE001
            pass
    # 子目标主路径完成位（orchestrator 2.7 标记；重跑期间允许再次置位）
    try:
        ctx._subgoal_main_done = False
    except Exception:  # noqa: BLE001
        pass


def rewrite_stage(self, ctx, tier: str) -> None:
    """4.6 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。"""
    try:
        if not _switch_enabled():
            self.record(ctx, "rewrite",
                        "4.6 重写：开关关闭（five_gate_rewrite=0）")
            return
        if getattr(ctx, "candidates", None):
            self.record(ctx, "rewrite", "4.6 重写：候选池非空，无需重写")
            return

        # 延迟导入各阶段函数（重写成功后让新候选重过五道链；不触发本阶段自身）
        from .answer_normalizer import normalize_stage
        from .self_auditor import self_audit_stage
        from .adversarial_gate import adversarial_gate_stage
        from .lean_backcheck import lean_backcheck_stage
        from .math_check_gate import math_check_stage
        from .vote_gate import vote_stage
        from prompts.rewrite import REWRITE_DIAG_SYSTEM, REWRITE_DIAG_USER

        _max_rounds = int(getattr(self.config, "rewrite_max_rounds", 2) or 2)
        problem = str(getattr(ctx, "problem", "") or "")[:_PROBLEM_MAX]
        rounds, diag_ok, produced = 0, 0, 0

        for rnd in range(1, _max_rounds + 1):
            rounds = rnd
            errs = _collect_error_brief(ctx)
            rejs = _collect_rejected_brief(ctx)
            # ① 大模型诊断：问题出在哪里 + 重写调整指令
            diag_d = {}
            try:
                raw = self.llm(ctx, [
                    {"role": "system", "content": REWRITE_DIAG_SYSTEM},
                    {"role": "user", "content": REWRITE_DIAG_USER.format(
                        problem=problem, errors=errs, rejected=rejs)},
                ], 0.1, 8192)
                diag_d = _parse_diag_json(raw)
                if diag_d:
                    diag_ok += 1
            except Exception as _e_d:  # noqa: BLE001  诊断失败仍继续重写
                self.record(ctx, "rewrite",
                            "第%d轮诊断调用失败（用裸错误摘要重写）: %s"
                            % (rnd, str(_e_d)[:120]))
            _rc = diag_d.get("root_cause") or "（诊断未给出，依据错误情况直接重写）"
            _fx = diag_d.get("fix") or "请依据上述错误情况调整分解与求解方法后重写。"
            self.record(ctx, "rewrite",
                        "第%d轮诊断：根因=%s；调整=%s"
                        % (rnd, _rc[:160], _fx[:200]))

            # ② 组「错误情况 + 诊断」→ rewrite_context（注入规划/求解的题目占位符内部）
            ctx.rewrite_context = (
                "【上一轮全部候选被审核淘汰——错误情况汇总】\n" + errs +
                "\n【被淘汰的候选答案摘要】\n" + rejs +
                "\n【诊断与重写调整指令（必须遵循）】\n根因：" + _rc +
                "\n调整：" + _fx + "\n（重写时务必避免上述同类错误。）"
            )[:_CTX_MAX]
            ctx.rewrite_round = (getattr(ctx, "rewrite_round", 0) or 0) + 1

            # ③ 重建蓝图和子目标 + 重写（重跑子目标主链，结果追加到候选池）
            _reset_plan_state(ctx)
            try:
                self.sub_goal_solver.run(ctx)
            except Exception as _e_s:  # noqa: BLE001  重写异常 ⇒ 记录，按未产出处理
                self.record(ctx, "rewrite",
                            "第%d轮重写异常: %s: %s"
                            % (rnd, type(_e_s).__name__, str(_e_s)[:160]))
            if not getattr(ctx, "candidates", None):
                self.record(ctx, "rewrite", "第%d轮重写未产出候选" % rnd)
                continue
            produced += 1

            # ④ 新候选重过五道链（不触发 rewrite 自身，防递归）
            normalize_stage(self, ctx)
            self_audit_stage(self, ctx)
            adversarial_gate_stage(self, ctx, tier)
            lean_backcheck_stage(self, ctx, tier)
            math_check_stage(self, ctx)
            vote_stage(self, ctx, tier)
            if getattr(ctx, "candidates", None):
                self.record(ctx, "rewrite",
                            "第%d轮重写成功：新候选通过五道链（存活 %d 个）"
                            % (rnd, len(ctx.candidates)))
                break
            self.record(ctx, "rewrite",
                        "第%d轮重写候选再次被审核全灭，进入下一轮" % rnd)

        ctx.rewrite_gate = {
            "rounds": rounds, "max_rounds": _max_rounds,
            "n_diag_ok": diag_ok, "n_produced": produced,
            "survived": bool(getattr(ctx, "candidates", None)),
            "root_cause": (_rc if rounds else ""),
        }
        self.record(ctx, "rewrite",
                    "4.6 重写：%d/%d 轮完成（诊断成功 %d 次，产候选 %d 次，"
                    "最终%s）" % (rounds, _max_rounds, diag_ok, produced,
                                  "存活" if ctx.rewrite_gate["survived"] else "仍空"))
    except Exception as _e:  # noqa: BLE001  修复环节绝不阻断主链
        self.record(ctx, "rewrite",
                    f"4.6 重写异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
