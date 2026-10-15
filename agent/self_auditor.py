# -*- coding: utf-8 -*-
"""4.1 AI 自审逻辑错误 —— 五道审核链第 1 道（2026-10-14 用户定案）。

用户口径（原话）：「第一道先让 ai 自己审核一遍逻辑错误，然后排除错题」。

职责：对每个候选解答做一次 LLM **逻辑自审**（只审逻辑、不审数值 —— 数值归
第四道计算检测）；能明确指出具体逻辑错误的候选 → **淘汰** + 反馈入
``ctx.audit_reject_feedback``。

判定纪律（宁缺勿滥，防误杀）：
  · 只有 ``logic_error=true`` **且** ``error_desc`` 非空才淘汰；
  · 输出不可解析 / LLM 调用失败 ⇒ **保留**候选（记为 unparsed，绝不因基础设施
    故障淘汰候选）；
  · 拿不准由提示词纪律约束（拿不准 ⇒ false）。

观测：trace step=``self_audit``（逐候选 + 汇总），diag 键
``self_audit`` / ``self_audit_events``。

五道链位置：4.0 规范化 → **4.1 自审** → ②对抗证伪 → ③Lean 代回 → ④计算检测
→ ⑤投票。
"""
from __future__ import annotations

from .switch_registry import get_bool as _sw_get_bool
# 单候选自审的输入截断（防超长上下文；题目 4000 / 推理 6000 与既有阶段同量级）
_PROBLEM_MAX = 4000
_REASONING_MAX = 6000
_ANSWER_MAX = 500
# 自审输出是短 JSON（error_desc ≤300 字），1024 token 足够且防失控
_MAX_TOKENS = 1024
_TEMPERATURE = 0.1

_TRUE_TOKENS = {"true", "1", "yes", "y", "是", "对", "有", "有错误"}


def parse_self_audit_json(raw) -> dict:
    """容错解析自审输出。返回 {} 表示无法解析（调用方**保留**候选）。"""
    if not raw:
        return {}
    txt = str(raw).strip()
    # 剥 markdown 围栏（```json ... ```）
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
    try:
        import json as _json_sa
        _m = txt[txt.find("{"):txt.rfind("}") + 1] if "{" in txt else ""
        if not _m:
            return {}
        d = _json_sa.loads(_m)
        if not isinstance(d, dict) or "logic_error" not in d:
            return {}
        _v = d.get("logic_error")
        if isinstance(_v, str):
            d["logic_error"] = _v.strip().lower() in _TRUE_TOKENS
        else:
            d["logic_error"] = bool(_v)
        d["error_desc"] = str(d.get("error_desc") or "").strip()
        d["error_at"] = str(d.get("error_at") or "").strip()
        return d
    except Exception:  # noqa: BLE001  解析失败 ⇒ 保留候选
        return {}


def _switch_enabled() -> bool:
    """读「五道链·第 1 道自审」开关（默认 True，=0 关闭做 A/B）。"""
    try:
        return _sw_get_bool("five_gate_self_audit")
    except Exception:  # noqa: BLE001
        return True


def self_audit_stage(self, ctx) -> None:
    """4.1 阶段入口（orchestrator 一行委托；``self`` 即 Orchestrator 实例）。"""
    try:
        if not _switch_enabled():
            self.record(ctx, "self_audit",
                        "4.1 自审：开关关闭（five_gate_self_audit=0）")
            return
        cands = list(getattr(ctx, "candidates", None) or [])
        if not cands:
            self.record(ctx, "self_audit", "4.1 自审：候选池为空，跳过")
            return

        from prompts.self_audit import SELF_AUDIT_SYSTEM, SELF_AUDIT_USER

        problem = str(getattr(ctx, "problem", "") or "")[:_PROBLEM_MAX]
        kept, rejected, unparsed, llm_fail = [], [], [], 0

        for c in cands:
            cid = getattr(c, "id", "?")
            # 规范化形态优先（4.0 已挂）；否则回退原 answer
            ans = str(getattr(c, "answer_norm", None)
                      or getattr(c, "answer", "") or "")[:_ANSWER_MAX]
            reasoning = str(getattr(c, "reasoning", "") or "")[:_REASONING_MAX]
            d = {}
            try:
                raw = self.llm(ctx, [
                    {"role": "system", "content": SELF_AUDIT_SYSTEM},
                    {"role": "user", "content": SELF_AUDIT_USER.format(
                        problem=problem, answer=ans, reasoning=reasoning)},
                ], _TEMPERATURE, _MAX_TOKENS)
                d = parse_self_audit_json(raw)
            except Exception as _e_call:  # noqa: BLE001  LLM 故障绝不淘汰候选
                llm_fail += 1
                kept.append(c)
                self.record(ctx, "self_audit",
                            "cid=%s LLM 调用失败（保留候选）: %s"
                            % (cid, str(_e_call)[:120]))
                continue

            if not d:
                unparsed.append(cid)
                kept.append(c)
                self.record(ctx, "self_audit",
                            "cid=%s 输出不可解析 ⇒ 保留（记为 unparsed）" % cid)
                continue

            if d.get("logic_error") and d.get("error_desc"):
                desc = d["error_desc"][:300]
                at = (d.get("error_at") or "")[:120]
                rejected.append({"id": cid, "answer": ans[:120],
                                 "error_desc": desc, "error_at": at})
                self.record(ctx, "self_audit",
                            "cid=%s 逻辑错误 ⇒ 淘汰：%s（位置：%s）"
                            % (cid, desc[:200], at or "-"))
            else:
                # 含「logic_error=true 但 desc 为空」⇒ 按纪律保留（无具体依据不淘汰）
                kept.append(c)
                self.record(ctx, "self_audit",
                            "cid=%s 通过（logic_error=%s）"
                            % (cid, d.get("logic_error")))

        if rejected:
            ctx.candidates = kept
            ctx.self_audit_rejected = list(
                getattr(ctx, "self_audit_rejected", None) or []) + rejected
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", None) or []) + [
                    "[自审逻辑错误] cid=%s: %s"
                    % (r["id"], r["error_desc"]) for r in rejected]

        ctx.self_audit = {
            "n": len(cands),
            "n_rejected": len(rejected),
            "n_unparsed": len(unparsed),
            "n_llm_fail": llm_fail,
            "rejected_ids": [r["id"] for r in rejected],
        }
        self.record(
            ctx, "self_audit",
            "4.1 自审：%d 候选 ⇒ 淘汰 %d / 保留 %d"
            "（不可解析 %d、LLM 故障 %d）"
            % (len(cands), len(rejected), len(kept), len(unparsed), llm_fail))

        # 淘汰后池空 ⇒ 汇总错误点交下游（与 4.0/旧链同一兜底，纯留痕）
        try:
            from .orchestrator__verify import _pool_empty_fallback as _pef
            _pef(self, ctx, "4.1_self_audit")
        except Exception:  # noqa: BLE001  兜底检查失败不影响主流程
            pass
    except Exception as _e:  # noqa: BLE001  增益环节绝不阻断主链
        self.record(ctx, "self_audit",
                    f"4.1 自审异常（跳过，不阻断）: "
                    f"{type(_e).__name__}: {str(_e)[:120]}")
