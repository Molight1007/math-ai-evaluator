# -*- coding: utf-8 -*-
"""终答五层选择（阶段二-2，2026-10-02）
========================================

背景（用户 2026-10-02 意见 + docs/主链重构方案_2026-10-02.md §三）
------------------------------------------------------------------
用户口径：
  · 「投票应在**最后**，不要一开始就投票」；
  · 「子目标**先按正确率选**，不能靠长度选」；
  · 「把 n 个答案**都给大模型**让它来判断」。

本模块把"终答从 `ctx.candidates` 里选出来"这件事，从「**一开始就投票**」
（`formatter._rank_key` 票数优先 / `objective_majority_vote`）改为**五层顺序**：

    ② **多答案判断**：先问模型"这题是否本来就可能有多个答案"？
       判"可能多个" ⇒ **直接输出多个终答，③④⑤ 全跳过**
       （否则会把"本该输出集合"的题压成单值 ⇒ 直接判错）。
    ③ **客观验证**：只可能一个 ⇒ 用确定性校验淘汰
       （`ctx._falsified_answers` 已证伪答案 + `AnswerOracle` 可解析性）；
       幸存者恰为 1 个 ⇒ 直接采用，**不进 ④⑤**。
    ④ **模型对比**：还剩多个 ⇒ 把所有幸存候选的**推理原文**一次性给模型对比裁决
       （**子目标保留候选作为旁证一起给**）。
    ⑤ **投票兜底**：模型也判不出 ⇒ 归一化后做频次投票。

设计纪律
--------
· 全部逻辑集中在 `select_final_answer()`：`formatter` 与 `orchestrator` 的
  「候选池 → 终答」入口**共用同一个函数**（本项目教训：只改一处 = 没改）。
· **任何异常/判不出 ⇒ `skipped=True`**，调用方**回退既有逻辑**，绝不阻断主链
  （评测判空 = 0 分）。
· 不修改 `formatter._rank_key`（其键序被单测锁定）；本模块的"停用票数优先"
  由**入口短路**实现（开关 ON 时根本不走 `_rank_key` 排序）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, List, Optional, Tuple

try:
    from prompts.final_select import (
        MULTI_ANSWER_JUDGE_SYSTEM, MULTI_ANSWER_JUDGE_USER,
        COMPARE_JUDGE_SYSTEM, COMPARE_JUDGE_USER,
    )
except ImportError:  # 兼容 sys.path 直跑
    from final_select import (  # type: ignore
        MULTI_ANSWER_JUDGE_SYSTEM, MULTI_ANSWER_JUDGE_USER,
        COMPARE_JUDGE_SYSTEM, COMPARE_JUDGE_USER,
    )

logger = logging.getLogger("MathPilot")

# ④ 注入口径：单候选推理原文上限 / 最多注入候选数 / 子目标旁证总上限
_MAX_REASONING_CHARS = 4000
_MAX_CANDIDATES_IN_PROMPT = 6
_MAX_SG_EVIDENCE_CHARS = 3000

# 拒绝/占位答案（与 formatter._REFUSAL_RE 同源窄口径：这些不可能当终答）
_REFUSAL_RE = re.compile(
    r"无法求解|无法解决|不能解决|无法解答|我无法|子目标求解失败|"
    r"生成失败|调用受限|拒绝回答|未给出有效解答|无法作答",
    re.IGNORECASE,
)


class _Cand:
    """轻量候选适配器（供 `AnswerOracle` 消费；仅需 answer/reasoning）。"""

    __slots__ = ("answer", "reasoning")

    def __init__(self, answer: str, reasoning: str = ""):
        self.answer = answer
        self.reasoning = reasoning


class SynthCandidate:
    """合成候选（五层选出的答案若**匹配不到原候选对象**时用它返回）。

    供 `formatter._pick_best` / `orchestrator._pick_best_from_candidates` 的
    调用方读取 `.answer` / `.reasoning` / `.confidence` —— 字段与 `Candidate` 对齐
    （但刻意不依赖 `agent.base.Candidate`，避免循环 import）。
    """

    def __init__(self, answer: str, reasoning: str = "",
                 origin: str = "final_select"):
        self.id = -1
        self.answer = answer
        self.reasoning = reasoning
        self.revised = False
        self.confidence = 0.0
        self.correct_votes = 0
        self.total_votes = 0
        self.origin = origin


# ----------------------------------------------------------------------
# 工具：归一化 / 脏答案 / 解析
# ----------------------------------------------------------------------
def _norm(a: str) -> str:
    """归一化答案（剥 \\boxed{} 外壳 + 去空白 + 小写）—— 与全项目等价口径同源。"""
    s = str(a or "")
    try:
        from agent.answer_oracle import AnswerOracle
        s = AnswerOracle.strip_wrappers(s)
    except Exception:  # noqa: BLE001
        s = s.strip()
    return re.sub(r"\s+", "", s).lower()


def _is_bad_answer(a: str) -> bool:
    """空 / 拒绝词 / 结构化非答案 ⇒ 不能当终答候选。"""
    s = str(a or "").strip()
    if not s:
        return True
    if _REFUSAL_RE.search(s):
        return True
    try:
        from agent.formatter import _looks_like_non_answer
        return bool(_looks_like_non_answer(s))
    except Exception:  # noqa: BLE001
        return False


def _parse_multiple(text) -> Optional[bool]:
    """解析步②输出：{'multiple': true/false}。判不出返回 None（⇒ 按"非多答案"继续）。"""
    t = str(text or "")
    m = re.search(r"\{[^{}]*\}", t)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "multiple" in obj:
                v = obj["multiple"]
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                if isinstance(v, str):
                    return v.strip().lower() in ("true", "yes", "1", "是", "可能")
        except Exception:  # noqa: BLE001
            pass
    if re.search(r'"multiple"\s*:\s*true', t, re.IGNORECASE):
        return True
    if re.search(r'"multiple"\s*:\s*false', t, re.IGNORECASE):
        return False
    return None


def _parse_compare_pick(text, n: int) -> Optional[int]:
    """解析步④输出：首个有效行里的 `候选 N`。判不出/无法判定 ⇒ None。"""
    for raw in str(text or "").splitlines():
        line = raw.strip().strip("`*` ").strip()
        if not line:
            continue
        m = re.search(r"候选\s*[#：:]?\s*(\d+)", line)
        if m:
            i = int(m.group(1)) - 1
            return i if 0 <= i < n else None
        if re.search(r"无法判定|无法判断|无法确定|不确定|unknown|都可以|均无法",
                     line, re.IGNORECASE):
            return None
        # 只看第一个有效行
        return None
    return None


# ----------------------------------------------------------------------
# 五层
# ----------------------------------------------------------------------
def _llm_text(llm: Callable, ctx, system: str, user: str,
              max_tokens: int) -> str:
    """一次 temperature=0 的短调用；失败返回空串（不抛）。"""
    try:
        resp = llm(ctx, [{"role": "system", "content": system},
                         {"role": "user", "content": user}], 0.0, max_tokens)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[final_selector] LLM 调用异常: %s: %s",
                     type(exc).__name__, exc)
        return ""
    if resp is None:
        return ""
    return str(resp)


def _objective_survivors(uniq: List[Tuple[str, str, Any]], ctx) -> Tuple[List, dict]:
    """步③：客观验证淘汰。返回 (幸存列表, diag)。

    客观信号（**只做淘汰、不做证实**，不确定一律放行）：
      ① `ctx._falsified_answers`（orchestrator 证伪器已用 SymPy/Lean 判错的答案）
         —— 数值回带 / 符号反例，等价即淘汰；
      ② `AnswerOracle` 可解析性 —— 明显非法表达式淘汰
         （**仅当还有别的候选可解析**时才淘汰，否则等于全军覆没，放行）。
    """
    diag = {"n_in": len(uniq), "falsified": 0, "unparseable": 0}
    # ① 已证伪
    _fal = list(getattr(ctx, "_falsified_answers", None) or [])
    keep = list(uniq)
    if _fal:
        try:
            from agent.answer_oracle import AnswerOracle
            _k2 = []
            for a, r, c in keep:
                if any(AnswerOracle.answers_equivalent(a, x) for x in _fal):
                    diag["falsified"] += 1
                else:
                    _k2.append((a, r, c))
            if _k2:
                keep = _k2
        except Exception:  # noqa: BLE001
            pass
    # ② 可解析性（只在"仍有可比对象"时淘汰不可解析者）
    try:
        from agent.answer_oracle import AnswerOracle
        _parseable = [i for i, (a, _, _) in enumerate(keep)
                      if AnswerOracle.is_parseable(a)]
        if _parseable and len(_parseable) < len(keep):
            _k3 = [keep[i] for i in _parseable]
            diag["unparseable"] = len(keep) - len(_k3)
            keep = _k3
    except Exception:  # noqa: BLE001
        pass
    diag["n_out"] = len(keep)
    diag["n_eliminated"] = len(uniq) - len(keep)
    return keep, diag


def _vote(survivors: List[Tuple[str, str, Any]]) -> Tuple[str, Any, dict]:
    """步⑤：归一化频次投票；并列取推理更长者（确定性收尾）。"""
    groups: dict = {}
    for a, r, c in survivors:
        groups.setdefault(_norm(a), []).append((a, r, c))
    diag = {"n_distinct": len(groups),
            "dist": {k[:40]: len(v) for k, v in groups.items()}}
    best = max(groups.values(),
               key=lambda g: (len(g), max(len(r) for _, r, _ in g)))
    top = max(best, key=lambda t: (len(t[1]), -len(t[0])))
    return top[0], top[2], diag


def _build_sg_evidence(ctx, cap: int = _MAX_SG_EVIDENCE_CHARS) -> Tuple[str, dict]:
    """子目标保留候选 → 步④旁证块。返回 (文本, diag)。

    ⚠ 复用路径命中的子目标**没有候选**（`candidates=[]`）——此处**显式跳过**，
    并在 diag 计数（`Q2` 处理：不把空旁证混进来，也不阻断）。
    """
    _tr = list(getattr(ctx, "subgoal_trace", None) or [])
    if not _tr:
        return "", {"n_with_candidates": 0, "n_skipped_reuse": 0}
    lines, used, n_with, n_skip = [], 0, 0, 0
    for s in _tr:
        cands = list(s.get("candidates") or [])
        if not cands:
            if s.get("reused"):
                n_skip += 1
            continue
        if len(cands) < 2:      # 单候选无"多解"信息，不进旁证
            continue
        n_with += 1
        seg = "  · 子目标 {}「{}」候选结论：{}".format(
            s.get("id"), (s.get("title") or "")[:24],
            " ｜ ".join(str(x)[:120] for x in cands[:4]))
        if used + len(seg) > cap:
            break
        used += len(seg)
        lines.append(seg)
    if not lines:
        return "", {"n_with_candidates": n_with, "n_skipped_reuse": n_skip}
    block = ("\n【子目标结论旁证（各子目标保留的多个候选结论，供你判断时参考；"
             "不是最终答案）】\n" + "\n".join(lines))
    return block, {"n_with_candidates": n_with, "n_skipped_reuse": n_skip}


def select_final_answer(ctx, candidates, llm: Callable,
                        record: Optional[Callable] = None) -> dict:
    """五层选择终答。返回::

        {"answer": str,           # 选出的终答（空串 = 未能选出 ⇒ 调用方回退）
         "branch": str,           # multi_answer / objective_single / model_compare / vote / <未走完>
         "steps": [str],          # 实际执行到的层（顺序证据）
         "diag": dict,            # 观测数据
         "cand": object | None}   # 命中的原始候选对象（保持 confidence 等字段）

    ★ `skipped=True` ⇒ 调用方**必须回退既有逻辑**（不阻断主链）。
    """
    diag: dict = {"branch": "", "steps": []}
    steps: List[str] = diag["steps"]

    def _rec(content: str, **extra):
        if record is None:
            return
        try:
            record(ctx, "final_select", content, **extra)
        except Exception:  # noqa: BLE001
            pass

    try:
        # ---- 收集可用候选（归一化去重，保留推理更长者）----
        seen: dict = {}
        for c in (candidates or []):
            a = str(getattr(c, "answer", "") or "").strip()
            r = str(getattr(c, "reasoning", "") or "")
            if _is_bad_answer(a):
                continue
            k = _norm(a)
            if k not in seen or len(r) > len(seen[k][1]):
                seen[k] = (a, r, c)
        uniq = list(seen.values())
        diag["n_in"] = len(list(candidates or []))
        diag["n_distinct"] = len(uniq)
        if not uniq:
            diag["branch"] = "no_usable_candidate"
            _rec("五层选择：无可用候选（空/拒绝词），回退既有逻辑")
            return {"answer": "", "branch": "no_usable_candidate",
                    "skipped": True, "steps": steps, "diag": diag, "cand": None}

        problem = str(getattr(ctx, "problem", "") or "")

        # ================= ② 多答案判断 =================
        steps.append("2_multi_answer")
        answers_block = "\n".join("- " + a for a, _, _ in
                                  uniq[:_MAX_CANDIDATES_IN_PROMPT])
        # 2026-10-02 DeepSeek 适配：原 768 ⇒ 8192。原值基于「判一条 JSON + 思维块被
        # 抑制」的假设，对 reasoning 模型必然截断（reasoning 先吃满预算、正文为空）。
        raw2 = _llm_text(llm, ctx, MULTI_ANSWER_JUDGE_SYSTEM,
                         MULTI_ANSWER_JUDGE_USER.format(
                             problem=problem, answers=answers_block), 8192)
        multi = _parse_multiple(raw2)
        diag["multi_answer"] = multi
        if multi is True:
            ans = ", ".join(a for a, _, _ in uniq)
            diag["branch"] = "multi_answer"
            _rec(f"五层选择②：判为多答案题 ⇒ 直接输出 {len(uniq)} 个终答，"
                 f"跳过 ③④⑤：{ans[:80]}")
            return {"answer": ans, "branch": "multi_answer", "skipped": False,
                    "steps": steps, "diag": diag, "cand": None}
        _rec("五层选择②：判为单一答案 ⇒ 进入客观验证（③）"
             + ("" if multi is False else "（判不出，按单一处理）"))

        # ================= ③ 客观验证 =================
        steps.append("3_objective")
        surv, o_diag = _objective_survivors(uniq, ctx)
        diag["objective"] = o_diag
        if not surv:
            surv = uniq          # 全被淘汰 ⇒ 不敢下结论，退回全体（放行）
            diag["objective"]["fallback_all"] = True
        if len(surv) == 1:
            a, r, c = surv[0]
            diag["branch"] = "objective_single"
            _rec(f"五层选择③：客观验证后仅剩 1 个幸存候选 ⇒ 直接采用、不进④⑤：{a[:80]}")
            return {"answer": a, "branch": "objective_single", "skipped": False,
                    "steps": steps, "diag": diag, "cand": c}
        _rec(f"五层选择③：客观验证后仍剩 {len(surv)} 个 ⇒ 进入模型对比（④）")

        # ================= ④ 模型对比 =================
        steps.append("4_model_compare")
        _in = surv[:_MAX_CANDIDATES_IN_PROMPT]
        blocks = []
        for i, (a, r, _c) in enumerate(_in, 1):
            _r = r[:_MAX_REASONING_CHARS] or "（无推理原文）"
            blocks.append(f"【候选 {i}】最终答案：{a}\n推理原文：\n{_r}")
        sg_block, sg_diag = _build_sg_evidence(ctx)
        diag["sg_evidence"] = sg_diag
        # 2026-10-02 DeepSeek 适配：原 1024 ⇒ 8192。原值基于「判一个候选号 + 思维块被
        # 抑制」的假设，对 reasoning 模型必然截断（reasoning 先吃满预算、正文为空）。
        raw4 = _llm_text(llm, ctx, COMPARE_JUDGE_SYSTEM,
                         COMPARE_JUDGE_USER.format(
                             problem=problem,
                             candidates_block="\n\n".join(blocks),
                             sg_evidence=sg_block), 8192)
        pick = _parse_compare_pick(raw4, len(_in))
        diag["model_compare_pick"] = pick
        if pick is not None:
            a, r, c = _in[pick]
            diag["branch"] = "model_compare"
            _rec(f"五层选择④：模型对比后选中 候选 {pick + 1} ⇒ 采用：{a[:80]}")
            return {"answer": a, "branch": "model_compare", "skipped": False,
                    "steps": steps, "diag": diag, "cand": c}
        _rec("五层选择④：模型无法判定 ⇒ 进入投票兜底（⑤）")

        # ================= ⑤ 投票兜底 =================
        steps.append("5_vote")
        a, c, v_diag = _vote(surv)
        diag["vote"] = v_diag
        diag["branch"] = "vote"
        _rec(f"五层选择⑤：投票兜底选中：{a[:80]}")
        return {"answer": a, "branch": "vote", "skipped": False,
                "steps": steps, "diag": diag, "cand": c}
    except Exception as exc:  # noqa: BLE001  五层任何异常都不得阻断主链
        logger.warning("[final_selector] 五层选择异常（回退既有逻辑）: %s: %s",
                       type(exc).__name__, exc)
        diag["branch"] = "exception"
        diag["error"] = f"{type(exc).__name__}: {exc}"
        return {"answer": "", "branch": "exception", "skipped": True,
                "steps": steps, "diag": diag, "cand": None}


def _switch_enabled() -> bool:
    try:
        from agent.switch_registry import get_bool as _swb
    except ImportError:
        from switch_registry import get_bool as _swb
    try:
        return bool(_swb("enable_final_answer_selection"))
    except Exception:  # noqa: BLE001
        return False


def adopt_single(ctx, answer: str, reason: str = "",
                 record: Optional[Callable] = None) -> dict:
    """**单答案快速采纳**（并入五层唯一出口，**不调 LLM**）。

    team-lead 2026-10-02 Q4 裁定：「让 `_set_final_response(direct_answer)` 也经过五层；
    但若传入的只有一个答案 ⇒ 五层直接采用、**不额外调 LLM**（避免兜底路径变慢/变不稳）」。

    用于 `orchestrator._set_final_response` 的**池外直答**路径（零票兜底 / 6.5 重做循环）：
    那里输入只有一个答案 ⇒ 无需 ②多答案判断 / ③客观验证 / ④模型对比 / ⑤投票，
    直接落到"唯一候选 ⇒ 采用"。仍写 `ctx._final_select_exit` / trace ⇒
    「这个终答是谁定的」**可归因**（这也是它存在的意义——消灭旁路）。

    开关 OFF ⇒ `skipped=True` ⇒ 调用方按原逻辑写入（**完全回退**）。
    """
    a = str(answer or "").strip()
    if not _switch_enabled():
        return {"answer": a, "branch": "disabled", "skipped": True,
                "disabled": True, "steps": [], "diag": {}, "cand": None}
    try:
        setattr(ctx, "_final_select_exit", "single_adopt:" + str(reason or ""))
    except Exception:  # noqa: BLE001
        pass
    # ⚠ 只在五层**没跑过**（无 _final_select_diag）时补一个，避免覆盖全量五层的归因。
    try:
        if not isinstance(getattr(ctx, "_final_select_diag", None), dict):
            ctx._final_select_diag = {
                "branch": "single_adopt", "steps": ["single_adopt"],
                "reason": "池外直答：单答案 ⇒ 五层直接采用（不调 LLM）"}
    except Exception:  # noqa: BLE001
        pass
    try:
        ctx.trace.append({
            "agent": "FinalSelector", "step": "final_select",
            "content": "五层选择(单答案快速采纳)：唯一答案直接采用，不调 LLM",
            "branch": "single_adopt", "reason": str(reason or "")})
    except Exception:  # noqa: BLE001
        pass
    return {"answer": a, "branch": "single_adopt", "skipped": False,
            "steps": ["single_adopt"],
            "diag": {"branch": "single_adopt", "steps": ["single_adopt"]},
            "cand": None}


def run_cached(ctx, llm: Callable, record: Optional[Callable] = None) -> dict:
    """带 `ctx` 缓存的五层入口（**formatter 与 orchestrator 共用同一决策**）。

    为什么必须缓存：终答选取在两条路径上都会被触发（`formatter._pick_best` 主路径、
    `orchestrator._pick_best_from_candidates` 超时/零票/异常兜底）。若各跑一遍，
    既有重复 LLM 成本，更糟的是**两次决策可能不一致**（同一 ctx 选出两个终答）。
    故第一次跑完把结果挂 `ctx._final_select_cache`，后续直接复用。

    开关 `enable_final_answer_selection` OFF ⇒ 返回 `disabled`（**不缓存**，便于 A/B）。
    """
    if not _switch_enabled():
        return {"answer": "", "branch": "disabled", "skipped": True,
                "disabled": True, "steps": [], "diag": {}, "cand": None}
    cached = getattr(ctx, "_final_select_cache", None)
    if isinstance(cached, dict):
        return cached
    res = select_final_answer(ctx, getattr(ctx, "candidates", None), llm, record)
    try:
        setattr(ctx, "_final_select_cache", res)
    except Exception:  # noqa: BLE001
        pass
    return res
