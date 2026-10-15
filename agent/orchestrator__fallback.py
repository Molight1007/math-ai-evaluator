# -*- coding: utf-8 -*-
"""兜底/应急职责簇（2026-10-09 批13：从 agent/orchestrator.py 逐字搬出）。

搬出方法：_emergency_direct_solve / _fallback_direct / _fallback

**纯搬迁**：方法体逐字搬入（tokenize-aware 去缩进，多行 docstring 字符串值不变），
签名原样保留；Orchestrator 内保留**同名一行委托** ⇒ 调用点零改。

耦合处理：
  · `TaskContext`/`_normalize_chat_response`(.base)、`safe_json_serialize`
    (utils.extract)、`_artifact_put`(artifact_store)、`re` ⇒ 新模块顶层同名导入
    （以上均不 import orchestrator，无环）；
  · `self._DIRECT_SYS` 是**类级属性** ⇒ 经 self 读取，一行不改；
  · 引用 orchestrator **模块级**函数 `_emergency_direct_max_tokens` ⇒ 函数内**惰性
    import**（本仓既定模式，单一来源仍在 orchestrator，非复制）。
"""
from __future__ import annotations

import re as _re

from .base import TaskContext, _normalize_chat_response
from utils.extract import safe_json_serialize

from agent.artifact_store import put_ctx as _artifact_put

def _emergency_direct_solve(self, problem: str) -> str:
    """紧急直答：用最精简 prompt 逼模型输出答案，绝不返回原题。

        P0-4 修复：集成 prefill 答案前置——时间最紧时优先保答案，
        抑制 CoT 开启，即使截断也只损失思考、不损失答案（ICMA 验证 58-140× 加速）。
        """
    from .orchestrator import _emergency_direct_max_tokens  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    try:
        from utils.prefill import prefill_messages, stitch
        resp = self.client.chat(
            messages=prefill_messages(
                [
                    {"role": "system", "content": self._DIRECT_SYS},
                    {"role": "user", "content": problem},
                ],
                "【最终答案】: ",
            ),
            temperature=0.0,
            max_tokens=_emergency_direct_max_tokens(),
        )
        text = _normalize_chat_response(resp)
        if text:
            text = stitch("【最终答案】: ", text)
        if not text or not text.strip():
            return ""
        # 优先提取【最终答案】行
        m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
        if m:
            ans = m.group(1).strip().split("\n")[0].strip()
            if ans:
                return ans
        # 兜底：最后一个非空行
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if lines:
            return lines[-1][:500]
        return text.strip()[:500]
    except Exception:
        return ""


def _fallback_direct(self, ctx: TaskContext) -> dict:
    """Solver 无候选 → 直接 LLM 求解（紧急直答，绝不返回原题）"""
    from .orchestrator import _emergency_direct_max_tokens  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    answer = self._emergency_direct_solve(ctx.problem)
    if not answer:
        # 2026-09-02 二次尝试：换更强调语气重答（094 实测一次直答失败
        # 即返回"未给出有效解答"——多一次机会，成本仅 1 次调用）
        try:
            from utils.prefill import prefill_messages, stitch
            resp2 = self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": (
                            "直接输出本题最终答案。禁止拒绝、禁止解释。"
                            "若答案是数值给出数值，若需集合/表达式按标准数学格式。")},
                        {"role": "user", "content": ctx.problem},
                    ],
                    "【最终答案】: ",
                ),
                temperature=0.0, max_tokens=_emergency_direct_max_tokens(),
            )
            text = _normalize_chat_response(resp2)
            if text:
                text = stitch("【最终答案】: ", text)
                m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
                if m:
                    ans2 = m.group(1).strip().split("\n")[0].strip()
                    if ans2 and len(ans2) > 1:
                        answer = ans2
        except Exception:  # noqa: BLE001
            pass
    if not answer:
        answer = "未给出有效解答。"
        ctx.trace.append({"agent": self.name, "step": "fallback",
                          "content": "紧急直答失败，返回占位答案"})
    # P2/P5 后处理同样适用于兜底路径（提前返回，绕过统一出口）
    answer = self._final_answer_postprocess(ctx, answer)
    # ★ 2026-10-02 hook 08（Solver 无候选 → 直答兜底）：终答落盘（只加不改）。
    _artifact_put(ctx, "08_final", {"final_response": answer,
                                    "fallback_direct": True})
    return safe_json_serialize({
        "final_response": answer, "trace": ctx.trace,
        "diag": self._collect_diag(ctx),
    })


def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
    trace = list(ctx.trace) if ctx.trace else []
    trace.append({
        "agent": self.name, "step": "error",
        "content": f"求解异常: {type(exc).__name__}: {exc}",
    })
    answer = self._pick_best_from_candidates(ctx)
    if answer:
        trace.append({"agent": self.name, "step": "fallback",
                      "content": "使用已有候选最佳答案作为兜底"})
        # ★ 2026-10-02 hook 08（异常兜底分支）：终答落盘（只加不改）。
        _artifact_put(ctx, "08_final", {"final_response": answer,
                                        "fallback": True})
        return {"final_response": answer, "trace": trace,
                "diag": self._collect_diag(ctx)}
    # 紧急直答
    answer = self._emergency_direct_solve(problem)
    if not answer:
        answer = "未给出有效解答。"
        trace.append({"agent": self.name, "step": "fallback",
                      "content": "紧急直答失败，返回占位答案"})
    # ★ 2026-10-02 hook 08（异常兜底分支，无候选）：终答落盘（只加不改）。
    _artifact_put(ctx, "08_final", {"final_response": answer,
                                    "fallback": True})
    return {"final_response": answer, "trace": trace,
            "diag": self._collect_diag(ctx)}
