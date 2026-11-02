"""第 4 步 裁决 —— 一条义务到底成没成立。

★ 这个模块**永不调用语言模型**。工具通过 `checker` 注入，因此：
  - 离线回放可以注入「历史产物里的判定结果」，零配额跑通全链；
  - 主流程注入真实符号检查 / 形式检查；
  - 两者走同一套裁决语义，不会各写一份。

★ 新内核**不产出 SOFT_CLOSED**。
  SOFT 的含义是「模型说这条对了」，而同源评审正是旧链的死因 —— 把模型
  意见当事实往下游搬，等于把失效模式复制一层。所以这里只产出三种：
      HARD_CLOSED  工具真跑过且未判失败（唯一可达闭合）
      OPEN         未闭合 / 被判失败 / 判不出
      UNMAPPED     根本没有求解产出
  账本里仍保留 SOFT 一级，**只是为了如实回放历史产物**，不作为新产出。

判定顺序（顺序即语义，不可交换）
--------------------------------
  1. 无产出            → UNMAPPED
  2. 结论是提问形态    → OPEN（求解器没给结论，只把目标又抄了一遍）
  3. 工具跑过且通过    → HARD（evidence 必须非空，否则无法复核）
  4. 工具跑过但失败    → OPEN
  5. 规则判失败        → OPEN
  6. 其余              → OPEN(undecidable) —— 判不出不等于错误
"""

from contracts.closure import (
    CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_UNMAPPED, FAIL_WORDS,
)
from utils.claim_form import FORM_GOAL, classify_claim

from .types import Judgement, PlanNode, SolveOutcome

__all__ = ["judge", "make_checker_result", "CHECKER_CONTRACT"]


CHECKER_CONTRACT = """checker(node, outcome) -> dict:
    verdict   "pass" | "fail" | "unknown"
    tool_ran  bool   是否真的执行了外部工具（决定能否达到 HARD）
    evidence  str    工具输出摘要（HARD 必填，否则视为不可复核）
"""


def make_checker_result(verdict, tool_ran=False, evidence=""):
    """构造 checker 返回值 —— 给回放台和测试用的统一形状。"""
    return {"verdict": verdict, "tool_ran": bool(tool_ran),
            "evidence": "%s" % (evidence or "")}


def _claim_is_question(text) -> bool:
    """结论写成了提问形态 ⇒ 这一步没有给出结论。

    典型：求解器把目标原样抄回来（"证明存在 n 使得…"），旧链会把它当
    推导正文往下传，下游再拿它去拼上下文 —— 于是「目标」一路被当成
    「已证事实」。
    """
    s = ("%s" % (text or "")).strip()
    if not s:
        return False
    try:
        return classify_claim(s).get("form") == FORM_GOAL
    except Exception:  # noqa: BLE001  判定失败不得阻断裁决
        return False


def _tool_failed(verdict, evidence) -> bool:
    """工具是否判了失败。verdict 优先，其次看输出里的失败词。"""
    v = ("%s" % (verdict or "")).strip().lower()
    if v in ("fail", "failed", "reject", "rejected", "error"):
        return True
    ev = ("%s" % (evidence or "")).lower()
    return any(w in ev for w in FAIL_WORDS)


def judge(node: PlanNode, outcome, checker=None) -> Judgement:
    """裁决一条义务。纯函数：同样的输入永远给同样的结论。"""
    nid = getattr(node, "nid", "") or getattr(outcome, "nid", "")

    # 1) 根本没有产出
    if outcome is None:
        return Judgement(nid, CLOSURE_UNMAPPED, "none", "no_output")
    if not (outcome.claim or "").strip() and not (outcome.action or "").strip():
        return Judgement(nid, CLOSURE_UNMAPPED, "none", "empty_output")

    # 2) 结论是提问形态 —— 没有给结论
    if _claim_is_question(outcome.claim):
        return Judgement(nid, CLOSURE_OPEN, "none", "claim_is_question")

    # 3~4) 工具裁决
    if checker is not None:
        try:
            r = checker(node, outcome) or {}
        except Exception as e:  # noqa: BLE001  工具异常不得升级成通过
            return Judgement(nid, CLOSURE_OPEN, "tool", "checker_error: %s" % e)
        verdict = r.get("verdict")
        evidence = "%s" % (r.get("evidence") or "")
        if r.get("tool_ran"):
            if _tool_failed(verdict, evidence):
                return Judgement(nid, CLOSURE_OPEN, "tool",
                                 "tool_rejected", evidence)
            # ★ 工具说通过但**没有任何输出** ⇒ 无法复核，不认。
            #   这不是保守，是防「跑了个空动作就当证完」。
            if not evidence.strip():
                return Judgement(nid, CLOSURE_OPEN, "tool",
                                 "tool_passed_without_evidence", "")
            return Judgement(nid, CLOSURE_HARD, "tool", "tool_passed", evidence)
        # 非工具判定（纯规则）：判失败有效（确定性），判通过**不构成闭合**
        if _tool_failed(verdict, evidence):
            return Judgement(nid, CLOSURE_OPEN, "symbol",
                             "rule_rejected", evidence)

    # 5) 判不出 —— 不等于错误
    return Judgement(nid, CLOSURE_OPEN, "none", "undecidable")
