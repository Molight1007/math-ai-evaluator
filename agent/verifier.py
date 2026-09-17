from __future__ import annotations
"""
过程校验智能体（VerifierAgent）
================================

功能演进：
  - v1: 二元投票（VERDICT A/B）+ 等价答案分组（未启用）
  - v2: 二元投票 + 评分模式 + 跨候选共识聚类 + 证明步骤验证

借鉴 ss-main 的投票共识与 Intern-MO 的 step 级验证，
但保持 MathPilot 多智能体 + 共享黑板的架构主线。
"""

import concurrent.futures
import json
import logging
import re
import time

from .base import BaseAgent, TaskContext, Verdict
from prompts.verifier import (
    VERIFIER_SYSTEM,
    VERIFIER_USER_TEMPLATE,
    VERIFIER_SCORING_SYSTEM,
    VERIFIER_SCORING_TEMPLATE,
    VERIFIER_FEEDBACK_SYSTEM,
    VERIFIER_FEEDBACK_TEMPLATE,
    VERIFIER_BUGREPORT_SYSTEM,
    VERIFIER_BUGREPORT_TEMPLATE,
    VERIFIER_RUBRIC_SYSTEM,
    VERIFIER_RUBRIC_TEMPLATE,
    VERIFIER_CHALLENGE_SYSTEM,
    VERIFIER_CHALLENGE_TEMPLATE,
    # 2026-09-15：带推理复核的专用提示词（强制写出检查过程）
    VERIFIER_DEEP_REVIEW_SYSTEM,
    VERIFIER_DEEP_REVIEW_TEMPLATE,
)
from prompts.proof import PROOF_VERIFY_SYSTEM, PROOF_VERIFY_TEMPLATE
from utils.extract import smart_fallback_answer
from utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot.Verifier")

# ---------------------------------------------------------------------------
# 辅助数据类
# ---------------------------------------------------------------------------

class AnswerCluster:
    """答案等价簇，用于跨候选多数投票。"""
    __slots__ = ("answer_norm", "candidate_ids", "vote_correct", "vote_total")

    def __init__(self, answer_norm: str):
        self.answer_norm = answer_norm
        self.candidate_ids: list[int] = []
        self.vote_correct: int = 0
        self.vote_total: int = 0

    @property
    def confidence(self) -> float:
        if self.vote_total == 0:
            return 0.0
        return self.vote_correct / self.vote_total

    @property
    def size(self) -> int:
        return len(self.candidate_ids)


# ===========================================================================
# VerifierAgent
# ===========================================================================

# ★ 2026-09-15（用户要求"测试时把错误暴露得更具体"）：
# 与 `prompts/verifier.py` 的 VERIFIER_SYSTEM 约定的**封闭标签集**。
# 解析时只认这些标签 ⇒ 既能结构化统计，又避免模型自造新词污染归因。
ERROR_TYPE_TAGS = (
    "符号错", "计算错", "边界遗漏", "定义域错", "跳步", "循环论证",
    "方法不适用", "前提不成立", "方向反了", "漏分支", "其它",
    # ★ 2026-09-15 补：10 题实测里**真实出现但标签集里没有**的两类错法。
    # 099「只答一个方法、正解多个」与 103「答 ABCD 漏 E」都无处归类，
    # 只能塞进"其它"⇒ 归因失真。（题型提示词里早就写了"按问法定项数"，
    # 但没有任何标签能记录它是否被遵守。）
    "漏项", "多项",
)
# 标签出现形态：VERDICT: B（A, B）或 VERDICT: B(A)
_ERR_TAG_RE = re.compile("|".join(ERROR_TYPE_TAGS))


def _extract_error_type(text: str) -> str:
    """从投票原文里抽出结构化错误类型标签，返回逗号分隔串（无则空串）。

    只在**判 B 的票**上调用（A 票没有错误类型）。命中多个标签时按标签集
    在文中的**出现顺序**去重拼接，便于统计"最常见的错误组合"。
    """
    if not text:
        return ""
    hits, seen = [], set()
    for m in _ERR_TAG_RE.finditer(text):
        tag = m.group(0)
        if tag not in seen:
            seen.add(tag)
            hits.append(tag)
    return ",".join(hits)


# 带推理复核专用：优先取**开头**的 VERDICT 行（新格式），否则取**最后**一个（旧格式）。
# ⚠ 背景（2026-09-16 实测，两题同时命中）：
#   旧模板要求「四步逐条书写检查过程，**最后**用单独一行给出 VERDICT」，
#   而 `verifier_deep_review_max_tokens` 默认 **16384** ⇒ 模型把预算全用在推理上，
#   **还没写到 VERDICT 就被截断**（日志里大量 `finish_reason=length, max_tokens=16384`）
#   ⇒ 判定为"无法解析" ⇒ 复核被跳过。实测两题输出 **43,960 / 37,633 字符**却都无 VERDICT。
#   现改为「**VERDICT 写在最前面**」⇒ 无论是否截断，判定一定拿得到。
# 保留取末尾的分支是为了向后兼容旧格式与意外顺序。
_VERDICT_ANY_RE = re.compile(
    r"VERDICT\s*[:：]\s*(?:\\boxed\s*\{\s*)?([AB])", re.IGNORECASE)
# 判定行是否**位于输出最前**（允许前导空白/加粗标记）。
# ⚠ 不能用"前 N 字符内"这种宽松窗口：实测文本
#   「先看看：如果前提不成立则 VERDICT: B。\n但独立重算后一致，最终 VERDICT: A」
#   的首个 VERDICT 就落在前 20 字符内，宽松窗口会误取**假设句**。
#   锚定行首才能真正对上提示词「第 0 步 · 必须是输出的第一行」的语义。
_VERDICT_HEAD_RE = re.compile(
    r"^\s*(?:\*\*)?VERDICT\s*[:：]\s*(?:\\boxed\s*\{\s*)?([AB])",
    re.IGNORECASE)


def _last_verdict_ab(text: str):
    """解析带推理复核的判定。返回 True(A)/False(B)/None(无法解析)。

    策略：
      · VERDICT **出现在输出最前**（新格式：判定置顶，防截断）⇒ 取**首个**；
      · 否则取**最后一个**（旧格式：判定在末尾；同时避免误采推理中的假设句）。
    """
    if not text:
        return None
    m = _VERDICT_HEAD_RE.match(text)
    if m:
        return m.group(1).upper() == "A"
    hits = _VERDICT_ANY_RE.findall(text)
    if not hits:
        return None
    return hits[-1].upper() == "A"


# ★★ 2026-09-16：深复核的**第二段收敛调用**专用系统提示词。
# 背景：第一段自由推理**实测 8/8 不给 VERDICT**（模型无视格式要求，写英文 CoT），
# 且会陷入复读退化（同长度 26749 字符、尾部 `a_{a_1} = a_{a_1} = ...` 无限重复）。
# 故追加一次极小成本的收敛调用，只让它把已有分析**压成一行判定**。
_DEEP_VERDICT_CONDENSE_SYS = (
    "你刚刚完成了一次数学解答复核（上文是你的分析）。"
    "现在只需把结论压缩成**一行**，严禁输出任何其它文字、解释或标点修饰。\n"
    "格式（二选一，必须严格照抄形状）：\n"
    "VERDICT: A\n"
    "VERDICT: B（错误类型标签）\n"
    "其中 A = 候选答案与你的独立重算完全一致且未发现问题；"
    "B = 发现任何错误、不一致或无法确认之处。\n"
    "错误类型标签只能从这个集合里选（可多选、逗号分隔、不得自造）："
    "符号错 / 计算错 / 边界遗漏 / 定义域错 / 跳步 / 循环论证 / "
    "方法不适用 / 前提不成立 / 方向反了 / 漏分支 / 漏项 / 多项 / 其它\n"
    "**必须以上述 `VERDICT:` 开头，这是唯一允许的输出形式。**"
)


# 收敛调用用的 prefill 前缀（结构性保证输出以 `VERDICT: ` 开头，见调用处注释）
_DEEP_VERDICT_PREFIX = "VERDICT: "


def _dump_deep_review_sample(ctx, raw: str, verdict) -> None:
    """把一次带推理复核的输出样本追加到 ``results/deep_review_samples.jsonl``。

    背景：`diag.deep_review` 只存 `chars`，导致"4 万字符却解析不到 VERDICT"
    **无从诊断**。本函数记录**头部/尾部**样本（不存全文，避免文件膨胀），
    用于回答"模型到底写没写 VERDICT、以什么格式写"。

    统计口径：同时记 `verdict_first_line`（首行是否直接就是 VERDICT），
    便于区分"模型没遵守置顶"与"解析器覆盖不足"两种根因。
    """
    import json as _json
    import os as _os
    import time as _time

    # ⚠ 2026-09-16 实测：跑 pytest 时会走 `fake_output()` 桩，把**测试数据**
    #   写进生产诊断文件（`results/deep_review_samples.jsonl`），污染真实样本
    #   （实测一次回归留下 3 条 273/15/280 字的假样本）。pytest 会设
    #   `PYTEST_CURRENT_TEST` 环境变量，据此跳过测试期落盘。
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return

    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    path = _os.path.join(root, "results", "deep_review_samples.jsonl")
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    head = raw[:1200]
    tail = raw[-400:] if len(raw) > 1600 else ""
    first_line = (raw.split("\n", 1)[0] if raw else "")[:200]
    rec = {
        "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "qid": str(getattr(ctx, "task_id", "") or getattr(ctx, "qid", "") or ""),
        "chars": len(raw),
        "verdict_parsed": ("A" if verdict is True else "B" if verdict is False
                           else "?"),
        "verdict_first_line": first_line,
        # 首行是否就是 VERDICT（模型是否遵守"置顶"要求）
        "first_line_is_verdict": bool(_VERDICT_HEAD_RE.match(raw or "")),
        "n_verdict_tokens": len(_VERDICT_ANY_RE.findall(raw or "")),
        "head": head,
        "tail": tail,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(_json.dumps(rec, ensure_ascii=False) + "\n")


class VerifierAgent(BaseAgent):
    """
    过程校验智能体

    核心职责：
    1. 对每份候选解答进行多票独立验证（A/B 投票）
    2. 将等价答案分组（文本 + SymPy 符号归一化）
    3. 计算簇级置信度（簇内总正确票 / 总票数）
    4. 对证明题启用逐步骤验证
    5. 提取失败原因供自纠错回环使用
    """

    def __init__(self, client, config):
        super().__init__(client, config)

    # ==================================================================
    # 投票与解析
    # ==================================================================

    # VERDICT 行解析（2026-09-11）：放宽带换行 / \boxed{} 壳的写法。
    # 此前拒绝词表里写死 `VERDICT\s*:\s*B`，模型输出 `VERDICT: \n\n\boxed{B}`
    # 时被换行 + 壳打断 → 落入"无法解析" → 判错（实测 9 次）。
    _VERDICT_LINE_RE = re.compile(
        r"VERDICT\s*[:：]\s*(?:\\boxed\s*\{\s*)?([AB])", re.IGNORECASE)

    def _is_correct_vote(self, text: str) -> bool | None:
        """解析 VERDICT 行 → True(判对) / False(判错) / None(弃权)。

        2026-09-11 三态化（依据 `Bug清单_团队提交de90cedc_0911.md` §3）：
        LLM 调用失败（text is None）与输出无法解析，语义上是**基础设施/格式
        故障 = 弃权**，不是"答案错误"。此前一律 `return False`，把 36 张故障票
        （27 次 None 输入 + 9 次解析失败，占票池 ~30%）当成反证计入：
        既压低簇置信度触发无谓 revise（单题白烧 96–158s），也把本可通过的
        候选直接投死。返回 None 的票在聚合时剔出 total_votes 分母。
        """
        if text is None:
            logger.warning("_is_correct_vote 收到 None 输入（LLM 调用失败）→ 弃权")
            return None
        text_upper = text.upper()

        # 0) VERDICT 行优先（权威信号，含换行/壳变体）。
        #    注意：在**原文**上做 IGNORECASE 匹配，不能在 text_upper 上匹配——
        #    upper() 会把 `\boxed` 变成 `\BOXED`，导致壳形态正则失配。
        m = self._VERDICT_LINE_RE.search(text)
        if m:
            return m.group(1).upper() == "A"

        # 1) 拒绝词优先——规避"不正确"包含"正确"的误判
        reject_patterns = [
            r'\bINCORRECT\b', r'\bWRONG\b', r'\bFALSE\b',
            r'不\s*正\s*确', r'错\s*误', r'\bNO\b(?!\s*CHANGE|TE)',
        ]
        for pat in reject_patterns:
            if re.search(pat, text_upper):
                return False

        # 2) 接受词
        accept_patterns = [
            r'\bCORRECT\b', r'\bTRUE\b', r'正\s*确', r'\bYES\b',
        ]
        for pat in accept_patterns:
            if re.search(pat, text_upper):
                return True

        # 3) 无法判断 → 弃权（既不判对也不判错，不参与分母）
        logger.warning("无法从文本中解析 VERDICT，计为弃权票: %s", text[:100])
        return None

    # ==================================================================
    # 答案归一化与等价判定
    # ==================================================================

    def _normalize_answer_text(self, text: str) -> str:
        """文本级归一化：去空白/去 $/浮点舍入/文本分数→数值/LaTeX 分数统一。"""
        if not text:
            return ""
        t = text.strip()
        t = t.replace("$", "").replace(" ", "")
        t = t.replace("\\displaystyle", "")
        t = t.replace("\\,", "").replace("\\;", "").replace("\\!", "")
        # LaTeX 分数统一（与本地 _normalize_answer 一致，无括号便于数值解析）
        t = re.sub(r'\\frac\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}', r'\1/\2', t)
        # 浮点舍入 6 位
        try:
            f = float(t)
            t = f"{f:.6g}"
        except (ValueError, TypeError):
            # 文本分数（如 1/2、(1)/(2)）→ 数值，统一 1/2 与 0.5、3 与 3.0
            stripped = re.sub(r'^\((-?\d+)\)/\((-?\d+)\)$', r'\1/\2', t)
            if re.fullmatch(r'-?\d+/\d+', stripped):
                try:
                    num, den = stripped.split("/")
                    f = int(num) / int(den)
                    t = f"{f:.6g}"
                except (ValueError, ZeroDivisionError):
                    pass
        return t

    def _are_answers_equivalent(self, a: str, b: str) -> bool:
        """三级等价判定：剥壳后文本相同 → 原文相同 → SymPy 符号等价。

        ★★ 2026-09-16 审计修复（与 `AnswerOracle` 那次同一病灶的第二份拷贝）：
        本方法与 `answer_oracle.answers_equivalent` 是**同一逻辑的两份实现**，
        而题目要求答案写成 `\\boxed{...}`。`_preprocess_latex` 会把 `\\boxed{2026}`
        归一成 `\\boxed2026` ⇒ 解析失败 ⇒ 判**不等价**。实测：
            verifier._are_answers_equivalent('\\boxed{2026}', '2026') -> **False**
            AnswerOracle.answers_equivalent ('\\boxed{2026}', '2026') -> True
        ⇒ verifier 自洽共识恒归不了组、playoff 复算对正确答案报"不一致" ⇒ 无谓 revise。
        修法：比较前先 `strip_wrappers`（与 answer_oracle 对齐口径），并保留原文兜底。
        """
        if not a or not b:
            return False
        try:
            from .answer_oracle import AnswerOracle
            ca, cb = AnswerOracle.strip_wrappers(a), AnswerOracle.strip_wrappers(b)
        except Exception:  # noqa: BLE001
            ca, cb = a.strip(), b.strip()
        # Level 1: 剥壳后字符串完全相同
        if ca and cb and ca == cb:
            return True
        # Level 2: 原文完全相同
        if a.strip() == b.strip():
            return True
        # Level 3: SymPy 符号等价（若可用）——剥壳版优先，原文兜底
        try:
            from utils.sympy_tools import are_expressions_equal
            for x, y in ((ca, cb), (a, b)):
                if x and y and are_expressions_equal(x, y):
                    return True
        except ImportError:
            pass
        return False

    def _equiv_group(
        self, candidates: list, answers: list[str]
    ) -> list[list[int]]:
        """等价答案分组：返回候选 ID 列表的列表。（BUG-3 修复：实际使用返回值）"""
        n = len(answers)
        visited = [False] * n
        groups: list[list[int]] = []

        for i in range(n):
            if visited[i]:
                continue
            group = [i]
            visited[i] = True
            for j in range(i + 1, n):
                if visited[j]:
                    continue
                if self._are_answers_equivalent(answers[i], answers[j]):
                    group.append(j)
                    visited[j] = True
            groups.append(group)
        return groups

    # ==================================================================
    # 共识聚类与簇置信度
    # ==================================================================

    def _cluster_candidates(
        self, candidates: list, verdicts: list[list[Verdict]]
    ) -> list[AnswerCluster]:
        """
        基于 Equivalent Answer 聚类 + 跨候选多数投票：
        1. 提取每个候选的答案（归一化）
        2. 等价分组
        3. 每个组统计"组内候选的总体正确票数 / 总票数"
        4. 返回簇列表，按置信度 × 规模排序
        """
        answers = []
        for cand in candidates:
            ans = (cand.get("answer", "") if isinstance(cand, dict)
                   else getattr(cand, "answer", ""))
            answers.append(self._normalize_answer_text(str(ans)))
        groups = self._equiv_group(candidates, answers)

        clusters: list[AnswerCluster] = []
        for g in groups:
            rep_idx = g[0]
            cluster = AnswerCluster(answers[rep_idx])
            for idx in g:
                cid = candidates[idx].get("id", idx) if isinstance(candidates[idx], dict) else idx
                cluster.candidate_ids.append(cid)
                # 统计该候选的所有票（2026-09-11：弃权票不计入分母 ——
                # 故障≠反证，见 _is_correct_vote 三态化说明）
                if idx < len(verdicts):
                    for v in verdicts[idx]:
                        if getattr(v, "abstain", False):
                            continue
                        cluster.vote_total += 1
                        if v.correct:
                            cluster.vote_correct += 1
            clusters.append(cluster)

        # 排序：置信度 × 规模的加权（等价答案人越多且票越对 = 越可信）
        clusters.sort(key=lambda c: c.confidence * c.size + c.confidence, reverse=True)
        return clusters

    # ==================================================================
    # 带推理的最终复核（2026-09-15 新增，回应「验证器偏松」）
    # ==================================================================
    # 实测依据（2026-09-15 的 10 题评测 + 历史记录）：
    #   ① 常规投票走 `prefill_messages(..., "VERDICT: ")` 强制**单行输出**，
    #      等于抑制思维流。代码注释自述实测 prefill 0.8s vs 普通 70.2s（140×）——
    #      **0.8 秒不足以完成系统提示词要求的"独立重算 + 逐条攻击"**，
    #      投票因此退化成"看一眼就点头"，与 6 步验证流程直接矛盾。
    #   ② 后果：10 题中 5 道**错题**的全部候选都是**全票 A**
    #      （086/091/099/101/103），叠加 AuditGate 候选审核 100% `unknown`、
    #      LeanGate 判 `valid`（086）或 `lenient_pass` 降级放行
    #      ⇒ **三道闸门对错答零否决**。
    # 本方法只对**最终选定的答案**做一次**不 prefill**的复核（让模型跑完推理），
    # 成本 1 次调用/题（约占单题 1100s 预算的 6%），是目前最省的"真验证"。
    # ⚠ 默认关（`verifier_deep_final_enabled=False`）⇒ 未 A/B 前行为完全不变。
    # ==================================================================
    def _deep_final_review(self, ctx, problem: str, best_cluster) -> str:
        """对最终选定答案做一次带推理的复核；返回原始文本（未启用/失败返回空串）。"""
        cfg = self.config
        if not getattr(cfg, "verifier_deep_final_enabled", False):
            return ""
        if best_cluster is None:
            return ""
        # 预算护栏：剩余时间不足则不做（复核本身要几十秒）
        # ⚠ TaskContext **没有** remaining_time()，只有 is_time_critical()/is_timed_out()；
        #   剩余秒数须由 deadline 自行推算（写 hasattr 兜底会静默失效，已踩）。
        need = float(getattr(cfg, "verifier_deep_final_min_remaining", 150.0) or 0)
        try:
            _dl = getattr(ctx, "deadline", None)
            remain = (float(_dl) - time.time()) if _dl else None
            if ctx.is_time_critical() or (need and remain is not None and remain < need):
                self.record(ctx, "deep_review",
                            "剩余 %s < %.0fs，跳过带推理复核" % (
                                "?" if remain is None else "%.0fs" % remain, need))
                return ""
        except Exception:  # noqa: BLE001
            pass

        answer = getattr(best_cluster, "answer_norm", "") or ""
        if not answer:
            return ""
        messages = [
            {"role": "system", "content": VERIFIER_DEEP_REVIEW_SYSTEM},
            {"role": "user", "content": VERIFIER_DEEP_REVIEW_TEMPLATE.format(
                problem=problem,
                candidate_answer=f"【最终答案】{answer}",
                theorem_context=(getattr(ctx, "_leansearch_ctx", "") or "(无)"),
            )},
        ]
        try:
            # ★ 不 prefill：允许完整思维流，这才是"独立重算"。
            # ★ 必须走**流式**（见 `_deep_llm`）：实测两例"允许推理"的调用均在
            #   全局 120s 超时（`LLM_TIMEOUT`）处失败、输出 0 字 —— 非流式路径
            #   对"要跑完整推理"的调用必然失败，功能等于不可用。
            raw = self._deep_llm(
                ctx, messages,
                float(getattr(cfg, "verifier_deep_review_temperature", 0.0) or 0.0),
                int(getattr(cfg, "verifier_deep_review_max_tokens", 16384) or 16384))
        except Exception as e:  # noqa: BLE001
            logger.warning("带推理复核调用失败（不影响其余流程）: %s", e)
            return ""
        if not raw:
            return ""
        # ★ 2026-09-15 实测教训：用投票模板时模型只吐 **12 个字**（就是一行
        #   `VERDICT: A`），一个字的检查过程都没有。**短于阈值一律视为未完成复核**，
        #   绝不能当成"检查通过"——否则"没做检查"与"检查通过"无法区分，
        #   正是本项目反复踩的"机制触发 ≠ 效果提升"。
        min_chars = int(getattr(cfg, "verifier_deep_review_min_chars", 200) or 0)
        if min_chars and len(raw) < min_chars:
            self.record(ctx, "deep_review",
                        "复核未按要求输出检查过程（仅 %d 字 < %d），视为未完成"
                        % (len(raw), min_chars),
                        chars=len(raw))
            return ""
        verdict = _last_verdict_ab(raw)
        # ★★★ 2026-09-16 修复（实测驱动的第二段收敛调用）：
        #   诊断落盘（`results/deep_review_samples.jsonl`）8/8 样本显示——
        #     首行 = "We need to verify the answer to the problem: ..."
        #     **VERDICT 出现 0 次**、chars = 26,749 ~ 42,545
        #   ⇒ 模型**完全无视系统提示的格式要求**，直接用英文自由推理，
        #     不写 VERDICT、不按四步写。故"把 VERDICT 置顶"的提示词改动**无效**。
        #   且样本 [4]/[6] 的 chars **完全相同（26749）**、尾部是
        #   `a_{a_1} = a_{a_1} = ...` **无限重复** ⇒ 模型陷入**复读退化循环**。
        #   修法：**两段式**——
        #     ① 第一段保留原样（自由推理，"独立重算"的价值在这里，不 prefill）；
        #     ② 首段没给出可解析判定时，追加一次**廉价收敛调用**：把推理尾部喂回，
        #        要求只输出一行 `VERDICT: A/B（标签）`。成本极小（max_tokens=64），
        #        但把"4 万字符作废"变成"拿到判定"。
        if verdict is None and (raw or "").strip():
            try:
                # ★ 2026-09-17 改进：收敛调用改用 **prefill** 强制以 `VERDICT: ` 开头。
                #   首版（昨天）只靠提示词要求"只输出一行"，实测**11 次只成功 2 次** ——
                #   模型仍可能用英文复述而不是写 `VERDICT:` 字面量。
                #   本仓库在其它"必须单行输出"的场合（如 value_attack 的 JSON 提取）
                #   一直用 `prefill_messages(..., prefix)` + `stitch(prefix, raw)`：
                #   服务端会把 prefix 作为 assistant 回复的开头，**结构性地**保证格式。
                #   这里同样处理：prefix=`VERDICT: `。
                _msgs = [{"role": "system",
                          "content": _DEEP_VERDICT_CONDENSE_SYS},
                         {"role": "user",
                          "content": "【你此前的分析（末尾节选）】\n"
                                     + raw[-6000:]
                                     + "\n\n请只输出一行判定，不要任何其它文字。"}]
                try:
                    from utils.prefill import prefill_messages, stitch
                    _msgs = prefill_messages(_msgs, _DEEP_VERDICT_PREFIX)
                    _conv = self._deep_llm(ctx, _msgs, 0.0, 64)
                    _conv = stitch(_DEEP_VERDICT_PREFIX, _conv) if _conv is not None else ""
                except Exception:  # noqa: BLE001  prefill 不可用则退回原提示词路径
                    _conv = self._deep_llm(ctx, _msgs, 0.0, 64)
                _v2 = _last_verdict_ab(_conv or "")
                if _v2 is not None:
                    verdict = _v2
                    self.record(ctx, "deep_review",
                                "收敛调用补出判定: %s（首段 %d 字符未给 VERDICT）"
                                % ("A" if _v2 else "B", len(raw)),
                                chars=len(_conv or ""))
            except Exception as _e:  # noqa: BLE001
                logger.debug("深复核收敛调用失败（不影响主流程）: %s", _e)
        # ★★ 2026-09-16 诊断落盘（用户要求）：把每次复核输出的**头部样本**存成
        #   jsonl。为什么必须落盘：`diag.deep_review` 只存 `chars`，
        #   于是"输出 4 万字符却解析不到 VERDICT"这件事**只能靠猜**。
        #   实测 003 的 6 次复核里 5 次"无法解析"，而看不到模型到底写了什么，
        #   无法判断是"没写 VERDICT"还是"写法不在解析器覆盖范围内"。
        #   不落全文（会很大），只存前 1200 字符 + 尾部 400 字符 —— 判定通常在首尾。
        try:
            _dump_deep_review_sample(ctx, raw, verdict)
        except Exception:  # noqa: BLE001
            pass
        self.record(
            ctx, "deep_review",
            "带推理复核: %s" % ("A(通过)" if verdict is True
                               else "B(否决)" if verdict is False else "无法解析"),
            verdict=("A" if verdict is True else "B" if verdict is False else "?"),
            error_type=(_extract_error_type(raw) if verdict is False else ""),
            chars=len(raw))
        return raw

    def _deep_llm(self, ctx, messages: list, temperature: float,
                  max_tokens: int) -> str:
        """复核专用 LLM 调用：**优先流式**，失败再退回普通调用。

        为什么不能直接用 `BaseAgent.llm`（非流式）：
        - 全局读超时 `LLM_TIMEOUT` 默认 **120s**（`utils/llm_client._DEFAULT_TIMEOUT`）；
        - 2026-09-15 实测：**"允许推理（不 prefill）"的两例调用均在 120s 处超时、
          输出 0 字**（而同样内容的 prefill 单行版只要 1.3–3.6s）。
        - 流式逐步累积直到服务端自然结束（`finish_reason=stop`），
          只要服务端还在吐 token 就不会被判读超时。
        ⇒ 非流式路径会让"要跑完整推理"的复核**必然失败**，功能等于不可用。
        """
        client = getattr(self, "client", None)
        chat = getattr(client, "chat", None)
        if ctx.budget is not None:
            try:
                ctx.budget.spend(1)
            except Exception:  # noqa: BLE001
                pass
        if callable(chat):
            try:
                out = chat(messages=messages, temperature=temperature,
                           max_tokens=max_tokens, stream=True)
                if out is not None:
                    return str(out)
            except TypeError:
                # 客户端不支持 stream 关键字 → 退回非流式（老实现/桩）
                pass
            except Exception as e:  # noqa: BLE001
                logger.warning("复核流式调用失败，退回非流式: %s", str(e)[:140])
        return self.llm(ctx, messages, temperature, max_tokens) or ""

    # ==================================================================
    # LeanSearch 引理检索（方案 A：定理原文注入，2026-09-15）
    # ==================================================================
    # 目的：把验证流程第 5 步「方法 / 定理适用性核查」从**凭记忆复述定理**
    # 变成**对着检索到的定理原文**判断，直接回应李平老师提出的"硬套定理"。
    #
    # 为什么接在验证器而不是求解侧：
    #   ① 成本最低（**每题只检索一次**，不是每个候选/每张票都检索）；
    #   ② 收益可用现有判分器直接度量（判 B 的准确率变化）；
    #   ③ 实测首题出现"6 候选 × 3 票全部投 A 放行错答"⇒ 验证器才是当前的
    #      薄弱环节，给它原文比给求解器加料更对症。
    #
    # ⚠ 全程默认关（`use_leansearch=False`）⇒ 未做 A/B 前行为与改动前**完全一致**。
    # ⚠ 检索失败/超时/时间紧张 → 返回空串，验证器行为不变（绝不因检索拖垮主流程）。
    # ==================================================================
    def _prepare_theorem_context(self, ctx, problem: str) -> str:
        """检索与本题相关的 Mathlib 定理原文；结果缓存在 ctx 上（一题一次）。"""
        cfg = self.config
        if not getattr(cfg, "use_leansearch", False):
            return ""
        if not getattr(cfg, "leansearch_inject_verifier", True):
            return ""
        cached = getattr(ctx, "_leansearch_ctx", None)
        if cached is not None:
            return cached

        out = ""
        try:
            if ctx.is_time_critical():
                self.record(ctx, "leansearch", "时间紧张，跳过引理检索（注入为空）")
            else:
                # 延迟导入：模块缺失时只影响本功能，不拖垮验证器
                from tools.lean_local.lean_search import MathlibTheoremSearcher
                searcher = getattr(self, "_ls_searcher", None)
                if searcher is None:
                    searcher = MathlibTheoremSearcher()
                    self._ls_searcher = searcher
                limit = max(1, int(getattr(cfg, "leansearch_top_k", 5) or 5))
                max_calls = int(getattr(cfg, "leansearch_max_calls_per_q", 2) or 0)
                n_called = int(getattr(ctx, "_leansearch_calls", 0) or 0)
                if max_calls and n_called >= max_calls:
                    self.record(ctx, "leansearch",
                                "已达单题检索次数上限（%d），跳过" % max_calls)
                else:
                    ctx._leansearch_calls = n_called + 1
                    self.note_mathlib_search(ctx)
                    _t0 = time.perf_counter()
                    res = searcher.search(problem[:800], limit=limit) or {}
                    _ms = (time.perf_counter() - _t0) * 1000.0
                    items = res.get("results") or []
                    # 首次调用播报后端状态（启动门禁）：让"检索到底走没走通"
                    # 一眼可见，而不是又一次静默（2026-09-15 教训）。
                    if not getattr(self, "_ls_status_logged", False):
                        self._ls_status_logged = True
                        try:
                            st = searcher.status()
                            logger.info(
                                "[LeanSearch] 后端状态: available=%s root=%s "
                                "indexed=%s official=%s",
                                st.get("available"), str(st.get("root"))[:90],
                                st.get("indexed_declarations"), st.get("official"))
                        except Exception:  # noqa: BLE001
                            pass
                    if items:
                        out = "\n".join(
                            "- %s (%s): %s" % (
                                r.get("name", ""), r.get("kind", "?"),
                                (r.get("snippet", "") or "").replace("\n", " ")[:200])
                            for r in items)
                        self.add_used_theorems(
                            ctx, [r.get("name", "") for r in items])
                        self.record(
                            ctx, "leansearch",
                            "检索到 %d 条相关定理（root=%s, %.0fms）" % (
                                len(items), str(res.get("root", ""))[:80], _ms),
                            n_hits=len(items), elapsed_ms=round(_ms, 1),
                            root=str(res.get("root", ""))[:120],
                            names=[r.get("name", "") for r in items])
                    else:
                        self.record(ctx, "leansearch",
                                    "未检索到相关定理（注入为空）",
                                    n_hits=0, elapsed_ms=round(_ms, 1))
        except ImportError as e:  # noqa: BLE001
            logger.warning(
                "LeanSearch 不可用（tools.lean_local.lean_search 导入失败）：%s "
                "—— 本次验证注入为空，行为与未启用时一致", e)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanSearch 引理检索失败（注入为空）：%s", e)

        ctx._leansearch_ctx = out
        return out

    # ==================================================================
    # 投票执行
    # ==================================================================

    def _vote_one(self, ctx, problem: str, candidate_text: str,
                  temperature: float = 0.0) -> str:
        """单次投票（返回原始文本）。

        v2.4.1：prefill「VERDICT: 」抑制 CoT——投票输出只需 A/B，
        实测 prefill 仲裁 0.8s vs 普通 70.2s（140×），杜绝 Intern-S2 推理流占满预算。
        2026-09-15：注入检索到的 Mathlib 定理原文（方案 A，未启用时为空串）。
        2026-09-16：**温度改为参数化**。此前这里硬编码 0.0，导致
        `config.verifier_temperature` 是**死配置**（声明了/进白名单/有 CLI，
        但全仓无人读），且多张票在温度 0 下几乎完全相同 ⇒ **投票没有方差**，
        "多票" 只是同一判断重复 N 次（实测：6 候选 × 3 票对错答**全票投 A**）。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": VERIFIER_USER_TEMPLATE.format(
                problem=problem,
                candidate_answer=candidate_text,
                theorem_context=(getattr(ctx, "_leansearch_ctx", "") or "(无)"),
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, "VERDICT: "),
                       temperature, 32768)
        return stitch("VERDICT: ", raw) if raw else raw

    def _vote_one_scoring(self, ctx, problem: str, candidate_text: str) -> dict | None:
        """评分模式投票（返回 JSON 或 None）。

        v2.4.1：prefill「{"」引导直接输出 JSON，抑制 CoT 前置长推理。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SCORING_SYSTEM},
            {"role": "user", "content": VERIFIER_SCORING_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
        if raw:
            raw = stitch('{"', raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
            return None

    # ==================================================================
    # v3 P2（2026-09-06 移植自 sq 分支）：rubric 结构化判分 + 反例挑战
    # ==================================================================
    # sq 分支（平台 ~24 分）的检测资产：rubric 让投票从 A/B 二元升级为
    # verdict+confidence+error_type+step_index+reason（错因质量 → revise
    # 定向性）；反例挑战让"非数值答案"也能被程序化数值验证证伪。

    def _vote_one_rubric(self, ctx, problem: str, candidate_text: str) -> dict | None:
        """一次 rubric 结构化判分（JSON prefill，秒级返回）。

        输出 {"verdict","confidence","error_type","step_index","reason"}，
        借鉴 Intern-MO judge：独立重算 → 对比 → 定位错因。
        """
        messages = [
            {"role": "system", "content": VERIFIER_RUBRIC_SYSTEM},
            {"role": "user", "content": VERIFIER_RUBRIC_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        try:
            raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
            if raw:
                raw = stitch('{"', raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("Rubric 判分调用失败: %s", e)
            return None
        rub = self._parse_json_loose(raw)
        if rub is None:
            logger.warning("Rubric 判分 JSON 解析失败: %s", (raw or "")[:120])
        return rub

    def _vote_rubric(self, ctx, problem: str, candidate,
                     use_deterministic: bool = True) -> list[Verdict]:
        """rubric 判分路径：结构化判分 + 确定性旁证（多证据汇审）。

        - rubric: verdict A/B + confidence + 错因定位（error_type/step_index/reason）
        - 确定性 fail → 硬否决（rubric 票全翻错，绕过 LLM 误判，0 LLM、可复现）
        - 确定性 pass → 追加一张独立正确票（deterministic_pass，非 LLM 客观票）
        - 确定性 unknown → 只挂证据，不改判
        """
        # 超时保护：deadline 已过 → 不判分（与 _vote 路径口径一致，空 verdicts 由上层走兜底）
        if ctx.is_timed_out():
            self.record(ctx, "vote_timeout",
                        "rubric 判分路径：单题 deadline 已过，跳过判分（返回空票）")
            logger.warning("Verifier: 单题 deadline 已过，跳过 rubric 判分")
            return []
        text = self._candidate_text(candidate)
        votes: list[Verdict] = []

        # 1) rubric 判分（1 次 JSON prefill）
        rub = self._vote_one_rubric(ctx, problem, text)
        if rub is None:
            # 2026-09-11 三态化：判分调用/解析失败 = 基础设施故障 → 弃权。
            # 此前记 `correct=True`（"保守放行"）会凭空制造一张**正确票**、
            # 虚抬簇置信度——与"故障计成错票"是同一枚硬币的两面。
            # 改为弃权后既不判对也不判错，不参与 total_votes 分母；若该候选
            # 最终零有效票，orchestrator 的 5.5 低置信度通道仍会兜底复核。
            votes.append(Verdict(correct=False, abstain=True,
                                 raw="rubric_parse_failed",
                                 feedback="rubric 判分解析失败（弃权，不计票）"))
        else:
            correct = str(rub.get("verdict", "B")).upper() == "A"
            feedback = ""
            if not correct:
                parts = []
                step = rub.get("step_index")
                if step is not None:
                    parts.append(f"步骤{step}")
                err = rub.get("error_type", "")
                if err and err != "无":
                    parts.append(err)
                reason = rub.get("reason", "")
                if reason:
                    parts.append(reason)
                feedback = "；".join(parts)
            try:
                conf = float(rub.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            votes.append(Verdict(
                correct=correct,
                raw=json.dumps(rub, ensure_ascii=False),
                feedback=feedback,
                score=rub,
                confidence=(conf if correct else 0.0),
                # ★ 2026-09-15：rubric 路径也回带结构化错误类型，口径与
                #   二元投票一致（同样走封闭标签集，认不出即空串）。
                error_type=(_extract_error_type(
                    f"{rub.get('error_type', '')}；{feedback}") if not correct else ""),
            ))

        # 2) 确定性旁证（0 LLM 预算）：fail 硬否决 / pass 独立正确票 / unknown 挂证据
        if use_deterministic:
            det = self._deterministic_check(ctx, problem, candidate)
            if det.get("verdict") == "fail":
                logger.warning("确定性验证失败 → 硬否决候选: %s",
                               det.get("evidence", "")[:80])
                for v in votes:
                    v.correct = False
                    v.confidence = 0.0
                votes.append(Verdict(correct=False, raw="deterministic_fail",
                                     feedback=f"确定性验证否决: {det.get('evidence', '')[:120]}",
                                     deterministic=det))
            elif det.get("verdict") == "pass":
                votes.append(Verdict(correct=True, raw="deterministic_pass",
                                     deterministic=det))
            else:
                # unknown：只挂证据，不追加票
                for v in votes:
                    v.deterministic = det

        return votes

    def _challenge_counterexample(self, ctx, problem: str,
                                  candidate_text: str, answer: str) -> dict:
        """反例挑战（P2）：LLM 生成候选命题 → 程序数值验证才生效。

        只对非纯数值答案触发（数值答案已走确定性代入验证）。
        返回 {"hard_fail": bool, "evidence": str}。
        """
        if not answer or not str(answer).strip():
            return {"hard_fail": False, "evidence": "无答案可挑战"}
        if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(answer).strip()):
            return {"hard_fail": False, "evidence": "数值答案，跳过命题反例搜索"}
        messages = [
            {"role": "system", "content": VERIFIER_CHALLENGE_SYSTEM},
            {"role": "user", "content": VERIFIER_CHALLENGE_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        try:
            raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
            if raw:
                raw = stitch('{"', raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("反例挑战调用失败: %s", e)
            return {"hard_fail": False, "evidence": "调用异常"}
        parsed = self._parse_json_loose(raw)
        if not parsed or not parsed.get("found"):
            return {"hard_fail": False, "evidence": "模型未提出反例命题"}
        statement = str(parsed.get("statement", "")).strip()
        if not statement:
            return {"hard_fail": False, "evidence": "反例命题为空"}
        try:
            from .deterministic import DeterministicChecker
            checker = DeterministicChecker(attempts=300)
            res = checker.search_counterexample(statement)
        except Exception as e:  # noqa: BLE001
            logger.warning("反例搜索异常: %s", e)
            return {"hard_fail": False, "evidence": f"搜索异常: {str(e)[:80]}"}
        if res.get("found"):
            return {"hard_fail": True,
                    "evidence": f"反例验证成功: {statement} 在 {res.get('counterexample')} 处不成立"}
        return {"hard_fail": False, "evidence": f"反例搜索未找到 ({statement[:80]})"}

    # ==================================================================
    # 投票力度自适应（2026-09-16 新增，针对「零否决」）
    # ==================================================================
    # 实测依据（2026-09-15 的 10 题 + 直接实验）：
    #   · standard 档 `verifier_voting_times=1` ⇒ 每题**只有一次**分类判断；
    #   · 且 `_vote_one` 把温度**硬编码 0.0**（`config.verifier_temperature`
    #     因此是死配置）⇒ 多张票在温度 0 下几乎完全相同，**投票没有方差**，
    #     "多票"只是同一判断重复 N 次；
    #   · 后果：6 道错题中 5 道的**全部候选被全票判 A**（零否决）。
    # 对策：**候选答案之间存在分歧时**（题目本身有争议/易错），自动提高票数
    # 并启用非零温度，让投票产生真实方差；分歧为 0 时保持原样（加票无意义且费时）。
    # ==================================================================
    def _vote_profile(self, ctx, candidates, base_votes=None) -> tuple:
        """返回本次投票的 ``(票数, 温度)``。

        ⚠ ``base_votes`` 必须传入**调用方决定的档位票数**（orchestrator 对 deep 档传 3）。
        2026-09-16 自审发现：本方法最初只读 `config.verifier_voting_times`(=1)，
        而 `run()` 里又无条件 `voting_times = _d_votes` ⇒ **把 deep 档的 3 票压回 1 票**
        （与 `tier_voting_times[deep]=3` 的设计直接矛盾）。现改为**以下限方式合并**：
        分歧时用 `max(档位票数, 分歧票数)`，一致时保留档位票数。
        """
        base_votes = int(
            base_votes if base_votes is not None
            else (getattr(self.config, "verifier_voting_times", 1) or 1))
        base_temp = float(getattr(self.config, "verifier_temperature", 0.0) or 0.0)
        if not getattr(self.config, "verifier_diversify_enabled", True):
            return base_votes, base_temp
        try:
            answers = set()
            # ★ 2026-09-16 审计修复：必须**剥壳后再比较**，否则 `\boxed{2026}` 与
            #   `2026` 会被当成两种答案 ⇒ 误判"候选分歧" ⇒ 无谓加票 + 调 0.7 温度
            #   （多花 LLM 调用）。与 `_are_answers_equivalent` 同口径。
            try:
                from .answer_oracle import AnswerOracle as _AO
            except Exception:  # noqa: BLE001
                _AO = None
            for c in (candidates or []):
                a = (c.get("answer", "") if isinstance(c, dict)
                     else getattr(c, "answer", "")) or ""
                a = str(a).strip()
                if not a:
                    continue
                if _AO is not None:
                    try:
                        a = _AO.strip_wrappers(a) or a
                    except Exception:  # noqa: BLE001
                        pass
                answers.add(a)
        except Exception:  # noqa: BLE001
            return base_votes, base_temp
        if len(answers) < 2:
            # 候选答案一致 ⇒ 加票/加温都无意义（只会重复同一判断）
            return base_votes, base_temp
        n = max(base_votes, int(
            getattr(self.config, "verifier_disagreement_votes", 3) or 1))
        t = float(getattr(
            self.config, "verifier_disagreement_temperature", 0.7) or 0.0)
        self.record(ctx, "vote_diversify",
                    "候选答案存在 %d 种分歧 → 票数 %d、温度 %.2f"
                    "（温度 0 下多票无方差，等于重复同一判断）"
                    % (len(answers), n, t))
        return n, t

    def _vote(
        self, ctx, problem: str, candidate, total_votes: int = 5,
        proportional: bool = True, use_scoring: bool = False,
        temperature: float = 0.0,
    ) -> list[Verdict]:
        """
        批量投票并汇总（BUG-8 修复：用 valid_votes 替代 total_votes）。
        2026-09-02 修复：deadline 已过仍启动投票 → 每票 LLM 全被跳过返回 None，
        _is_correct_vote(None) 全判错 + 疯狂刷日志空转（027 实测超 deadline 137s）。
        """
        # 超时保护：deadline 已过 → 不投票（空 verdicts 由上层走兜底）
        if ctx.is_timed_out():
            logger.warning("Verifier: 单题 deadline 已过，跳过投票（%d 票）",
                           total_votes)
            return []
        text = self._candidate_text(candidate)
        verdicts: list[Verdict] = []

        # ★ 2026-09-15 方案 A：**在启动投票线程之前**完成检索（单线程、每题一次），
        # 避免 6 候选 × 3 票 = 18 次并发重复检索。未启用/失败时注入为空串，
        # 验证器行为与改动前完全一致。
        self._prepare_theorem_context(ctx, problem)

        # 二元投票
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(total_votes, self.config.max_workers)
        ) as executor:
            futures = [executor.submit(self._vote_one, ctx, problem, text,
                                       temperature)
                       for _ in range(total_votes)]
            for f in concurrent.futures.as_completed(futures):
                try:
                    raw = f.result()
                    ok = self._is_correct_vote(raw)
                    verdicts.append(Verdict(
                        correct=bool(ok),
                        abstain=ok is None,   # 故障票 = 弃权，剔出 total_votes 分母
                        raw=raw,
                        # ★ 2026-09-15：判 B 时抽出结构化错误类型（A 票无此项）
                        error_type=(_extract_error_type(raw)
                                    if ok is False else ""),
                    ))
                except Exception as e:
                    logger.warning(f"Vote failed: {e}")
                    # 调用异常同样是基础设施故障 → 弃权，不得当反证
                    verdicts.append(Verdict(correct=False, abstain=True, raw=str(e)))

        # 可选评分模式（补充/校准）
        if use_scoring and self.config.use_scoring:
            try:
                scoring = self._vote_one_scoring(ctx, problem, text)
                if scoring:
                    verdicts.append(Verdict(
                        correct=scoring.get("overall", "B") == "A",
                        raw=json.dumps(scoring, ensure_ascii=False),
                        score=scoring,
                    ))
            except Exception as e:
                logger.debug(f"Scoring vote failed: {e}")

        self._record_error_types(ctx, verdicts)
        return verdicts

    # ------------------------------------------------------------------
    # 结构化错误类型聚合（2026-09-15）
    # ------------------------------------------------------------------
    # 背景：用户要求"之后测试记录大模型的具体答题情况，把错误暴露得更加具体"。
    # 此前 trace 里投票只留 correct/abstain/raw，**错因全埋在自然语言里**，
    # 无法统计 ⇒ 归因只能靠人工读日志（实测"推理错 62 题"就是这么数出来的）。
    # 现在 VERIFIER_SYSTEM 判 B 时必须回带**封闭标签集**（ERROR_TYPE_TAGS），
    # 这里把它们聚合成 {标签: 票数}，`orchestrator._collect_diag()` 可直接取用。
    # 纯埋点，不参与任何判定逻辑。
    # ------------------------------------------------------------------
    @staticmethod
    def _error_type_dist(verdicts) -> dict:
        """统计判 B 票的结构化错误标签分布。返回 {标签: 出现票数}。"""
        dist: dict = {}
        for v in (verdicts or []):
            et = getattr(v, "error_type", "") or ""
            if not et:
                continue
            for tag in et.split(","):
                tag = tag.strip()
                if tag:
                    dist[tag] = dist.get(tag, 0) + 1
        return dist

    def _record_error_types(self, ctx, verdicts,
                            step: str = "vote_error_types") -> dict:
        """把结构化错误类型分布写进 trace，返回该分布字典。"""
        dist = self._error_type_dist(verdicts)
        n_reject = sum(1 for v in (verdicts or [])
                       if v.correct is False and not getattr(v, "abstain", False))
        if n_reject:
            ordered = sorted(dist.items(), key=lambda kv: -kv[1])
            self.record(
                ctx, step,
                "错误类型分布: " + (", ".join(f"{k}×{n}" for k, n in ordered)
                                    or "(模型未回带标签)"),
                error_types=dist, n_reject=n_reject,
            )
        return dist

    # ==================================================================
    # 反馈提取（自纠错用）
    # ==================================================================

    def _extract_feedback(self, ctx, problem: str, candidate) -> str:
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system", "content": VERIFIER_FEEDBACK_SYSTEM},
            {"role": "user", "content": VERIFIER_FEEDBACK_TEMPLATE.format(
                problem=problem, candidate_answer=text
            )},
        ]
        try:
            # v2.4.1：prefill「错因：」抑制 CoT，直接输出错因定位
            raw = self.llm(ctx, prefill_messages(messages, "错因："), 0.0, 32768)
            return stitch("错因：", raw) if raw else "无法提取失败原因。"
        except Exception as e:
            logger.error(f"Feedback extraction failed: {e}")
            return "无法提取失败原因。"

    # ------------------------------------------------------------------
    # 结构化 Bug Report（依据 IMO 2025 验证-精炼流水线论文）
    # ------------------------------------------------------------------
    def _extract_bug_report(self, ctx, problem: str, candidate) -> dict:
        """让验证器产出结构化 bug report（分类 + 精确定位），而非一句话错因。

        论文依据：Huang & Yang (2025) 用「验证 + 精炼」流水线把 IMO 2025
        从 best-of-32 的 21.4%~38.1% 提到 85.7%。关键不在于多采样，而在于
        验证器给出**可执行的错因**（哪一步、什么类型、为什么），
        修正步骤才能有的放矢。

        返回 dict：{verdict, findings:[{location, type, explanation}]}
        解析失败时返回 {"verdict": "unknown", "findings": []}。
        """
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system", "content": VERIFIER_BUGREPORT_SYSTEM},
            {"role": "user", "content": VERIFIER_BUGREPORT_TEMPLATE.format(
                problem=problem, candidate_answer=text
            )},
        ]
        empty = {"verdict": "unknown", "findings": []}
        try:
            # prefill 锚定到 JSON 开头：Intern 无短种子会先吐思维块吃满预算
            raw = self.llm(ctx, prefill_messages(messages, "{"), 0.0, 32768)
            if not raw:
                return empty
            raw = stitch("{", raw)
        except Exception as e:  # noqa: BLE001
            logger.error(f"BugReport extraction failed: {e}")
            return empty

        data = self._parse_json_loose(raw)
        if not isinstance(data, dict):
            return empty
        findings = []
        for f in (data.get("findings") or []):
            if not isinstance(f, dict):
                continue
            loc = str(f.get("location") or "").strip()
            expl = str(f.get("explanation") or "").strip()
            ftype = str(f.get("type") or "").strip().lower()
            if ftype not in ("critical_error", "justification_gap"):
                ftype = "justification_gap"
            if not (loc or expl):
                continue
            findings.append({"location": loc, "type": ftype,
                             "explanation": expl})
        verdict = str(data.get("verdict") or "").strip().lower()
        if verdict not in ("correct", "critical_error", "justification_gap"):
            # 以 findings 反推，比信任模型的自陈更可靠
            verdict = ("critical_error"
                       if any(f["type"] == "critical_error" for f in findings)
                       else "justification_gap" if findings else "unknown")
        return {"verdict": verdict, "findings": findings}

    @staticmethod
    def _parse_json_loose(raw: str):
        """从 LLM 输出里尽力抠出 JSON 对象（去围栏、平衡括号）。"""
        if not raw:
            return None
        import json as _json
        text = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()
        try:
            return _json.loads(text)
        except (_json.JSONDecodeError, ValueError):
            pass
        # 平衡括号：取第一个能完整解析的对象
        depth = 0
        start = -1
        in_str = esc = False
        for i, ch in enumerate(text):
            if esc:
                esc = False
            elif in_str and ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        try:
                            return _json.loads(text[start:i + 1])
                        except (_json.JSONDecodeError, ValueError):
                            start = -1
        return None

    @staticmethod
    def _format_bug_report(report: dict) -> str:
        """把结构化 bug report 渲染成注入 solver 的反馈文本。

        按「关键错误优先」排序：修正步骤应当先修断链的错误，
        论证漏洞其次（否则会先去补一处无关紧要的严谨性，浪费修正预算）。
        """
        findings = report.get("findings") or []
        if not findings:
            return ""
        crit = [f for f in findings if f["type"] == "critical_error"]
        gaps = [f for f in findings if f["type"] == "justification_gap"]
        lines = []
        if crit:
            lines.append("【关键错误（必须修正，否则整条推理链作废）】")
            for i, f in enumerate(crit, 1):
                lines.append(f"{i}. 位置：“{f['location']}”")
                lines.append(f"   问题：{f['explanation']}")
        if gaps:
            lines.append("【论证漏洞（需补充论证，结论可能仍成立）】")
            for i, f in enumerate(gaps, 1):
                lines.append(f"{i}. 位置：“{f['location']}”")
                lines.append(f"   问题：{f['explanation']}")
        return "\n".join(lines)

    def _extract_revise_feedback(self, ctx, problem: str,
                                 candidates: list, best_cluster) -> str:
        """恢复 Reflexion 反馈：仅在需要 revise 时提取错因（受预算约束）。

        触发条件：best_cluster 存在且置信度 < 0.5（正确票未过半，验证器自身
        都不确定）。此时提取 LLM 错因定位，并叠加 AnswerOracle 的客观
        sanity check（纯本地、不消耗预算）。

        返回空串表示无需 revise 或预算不足。
        """
        if best_cluster is None:
            return ""
        if getattr(best_cluster, "confidence", 0.0) >= 0.5:
            return ""
        if ctx.is_time_critical():
            return ""

        # 取 best_cluster 的代表候选（共识簇内第一个候选）
        rep_candidate = None
        cids = getattr(best_cluster, "candidate_ids", []) or []
        if cids and candidates:
            idx = cids[0] if cids[0] < len(candidates) else 0
            rep_candidate = candidates[idx]
        if rep_candidate is None and candidates:
            rep_candidate = candidates[0]
        if rep_candidate is None:
            return ""

        parts = []
        # 1) LLM 错因提取（消耗 1 次预算）
        #    优先用结构化 bug report（分类 + 原文定位，修正时有的放矢）；
        #    解析不出 findings 时回退到原来的一句话错因。二者都只花 1 次调用，
        #    所以这是替换不是叠加。
        llm_feedback = ""
        if getattr(self.config, "use_bug_report_feedback", True):
            report = self._extract_bug_report(ctx, problem, rep_candidate)
            llm_feedback = self._format_bug_report(report)
        if not llm_feedback:
            llm_feedback = self._extract_feedback(ctx, problem, rep_candidate)
            if llm_feedback == "无法提取失败原因。":
                llm_feedback = ""
        if llm_feedback:
            parts.append(llm_feedback)
        # 2) AnswerOracle 客观 sanity check（纯本地，不消耗预算）
        oracle_fb = self._oracle_sanity_feedback(rep_candidate)
        if oracle_fb:
            parts.append(oracle_fb)

        if parts:
            return "\n".join(parts)
        return "所有候选均未获验证通过，请重新审题并纠正推理错误。"

    @staticmethod
    def _oracle_sanity_feedback(candidate) -> str:
        """用 AnswerOracle 做客观 sanity check（纯本地），返回客观反馈。"""
        answer = getattr(candidate, "answer", "") or ""
        if not answer:
            return "候选答案为空，需重新求解。"
        try:
            from .answer_oracle import AnswerOracle
            if not AnswerOracle.is_parseable(answer):
                return "候选答案无法解析为有效数学表达式，可能为幻觉或格式错误。"
        except Exception as exc:  # noqa: BLE001
            # 2026-09-04 审核：异常吞掉 = "可解析性检查"静默跳过 → 全部放行
            # （与 lean_gate 吞 AttributeError 历史同型）。留证据。
            logger.debug("verifier 可解析检查异常（跳过放行）: %s: %s",
                         type(exc).__name__, exc)
        return ""

    # ==================================================================
    # P1-1: Python/SymPy 独立验证通道 + 确定性复算（playoff）
    # ==================================================================

    _PLAYOFF_SYS = (
        "你是数学解题专家。重新独立地解答下面这道题，"
        "只输出最终答案（数值、表达式或选项字母），不要任何推理过程。"
    )

    def _sympy_spot_check(self, answer: str) -> dict:
        """对候选答案做 SymPy 独立 sanity check（不消耗 LLM 预算）。

        返回 {"parseable": bool, "value": str|None, "note": str}。
        仅用于给投票做旁证：可解析的数值/表达式答案可信度更高。
        """
        if not answer:
            return {"parseable": False, "value": None, "note": "empty"}
        try:
            from utils.sympy_tools import _try_parse, eval_expression
            # ★ 2026-09-16 修复：先剥 `\boxed{}` 等外壳再解析。
            #   题面要求用 `\boxed{}` 书写，而 `_try_parse` 会把 `\boxed{2025}`
            #   归一成 `\boxed2025` 而解析失败 ⇒ 此处曾把**正确答案判为不可信**
            #   （本函数是"给投票做旁证"用的）。详见 answer_oracle 同类注释。
            from .answer_oracle import AnswerOracle
            cand = AnswerOracle.strip_wrappers(answer) or answer
            parsed, err = _try_parse(cand)
            if parsed is None:
                # 退回原文再试一次（剥壳可能反而破坏非包裹式答案）
                parsed, err = _try_parse(answer)
            if parsed is None:
                return {"parseable": False, "value": None, "note": err}
            val = eval_expression(cand)
            return {"parseable": True, "value": val, "note": "ok"}
        except Exception as e:
            return {"parseable": False, "value": None, "note": str(e)[:80]}

    def _deterministic_check(self, ctx, problem: str, candidate) -> dict:
        """对候选答案做确定性旁证/否决（0 LLM 预算）。

        返回 DeterministicChecker.check_answer 的结果 dict：
        {"verdict": "pass"|"fail"|"unknown", "confidence": float,
         "evidence": str, "method": str}。
        任何异常一律降级 unknown（宁可 unknown 绝不误杀）。
        """
        answer = (candidate.get("answer", "") if isinstance(candidate, dict)
                  else getattr(candidate, "answer", ""))
        if not answer:
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": "答案为空", "method": "none"}
        try:
            from .deterministic import DeterministicChecker
            checker = DeterministicChecker()
            return checker.check_answer(ctx, problem, answer,
                                        getattr(ctx, "domain", "") or "")
        except Exception as e:  # noqa: BLE001
            logger.warning("Deterministic check failed: %s", e)
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": f"异常: {str(e)[:80]}", "method": "exception"}

    def _playoff_recheck(self, ctx, problem: str, top_answer: str) -> bool:
        """确定性复算（playoff）：用 temperature=0 重新解一遍，比对答案。

        解决"验证器与解题器同源一起错"的问题：低温重解是独立采样，
        若两次独立求解答案一致，则置信度大幅提升。
        """
        try:
            # v2.4.1：playoff 也走 prefill——「答案：」让答案前置，抑制 CoT 推理流
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": self._PLAYOFF_SYS},
                        {"role": "user", "content": problem},
                    ],
                    "答案：",
                ),
                0.0, 32768,
            )
            if resp:
                resp = stitch("答案：", resp)
            if not resp or not resp.strip():
                return False
            recheck_ans = smart_fallback_answer(resp)
            if not recheck_ans:
                return False
            return self._are_answers_equivalent(
                self._normalize_answer_text(top_answer),
                self._normalize_answer_text(recheck_ans),
            )
        except Exception as e:
            logger.warning("playoff recheck failed: %s", e)
            return False

    # ==================================================================
    # 证明步骤验证
    # ==================================================================

    def _verify_proof_step(self, ctx, problem: str, solution: str) -> dict | None:
        messages = [
            {"role": "system", "content": PROOF_VERIFY_SYSTEM},
            {"role": "user", "content": PROOF_VERIFY_TEMPLATE.format(
                problem=problem, solution=solution
            )},
        ]
        try:
            # v2.4.1：prefill「{"」引导 JSON 输出，抑制 CoT 前置长推理
            raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
            if raw:
                raw = stitch('{"', raw)
            m = re.search(r'\{[^{}"]*(?:"[^"]*"[^{}]*)*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
            # fallback: larger match
            m2 = re.search(r'\{[\s\S]*\}', raw)
            if m2:
                return json.loads(m2.group())
            return {"overall": "unknown", "raw": raw[:500]}
        except Exception as e:
            logger.warning(f"Proof step verify failed: {e}")
            return None

    # ==================================================================
    # 主流程
    # ==================================================================

    def run(
        self, ctx: TaskContext, problem: str, candidates: list,
        use_clustering: bool = True,
        use_scoring: bool = False,
        is_proof: bool = False,
        use_playoff: bool = False,
        voting_times: int = None,
        use_deterministic: bool = False,
        use_rubric: bool = False,
        use_challenge: bool = False,
    ) -> dict:
        """
        验证主流程。

        参数:
            voting_times: 每候选投票数；None 时回退 config.verifier_voting_times。
                          （难题深度通道：deep 档传 3，fast/standard 传 1）
            use_rubric: 2026-09-06（移植自 sq）：rubric 结构化判分路径
                        （verdict+confidence+error_type+step_index+reason，
                        内嵌确定性旁证：fail 硬否决 / pass 独立正确票）。
            use_challenge: 2026-09-06（移植自 sq）：反例挑战——对全错票的
                        非数值答案，LLM 生成命题 → 程序数值验证 → hard_fail 硬否决。

        返回:
            {
                "cluster_data": list[AnswerCluster],  # 候选传给 orchestrator
                "feedback": str,                       # 自纠错用
                "verdicts": list[list[Verdict]],       # 原始裁决
                "best_cluster": AnswerCluster | None,
            }
        """
        # 特殊处理证明题
        if is_proof and len(candidates) == 1:
            # 逐步骤验证
            proof_text = self._candidate_text(candidates[0])
            step_result = self._verify_proof_step(ctx, problem, proof_text)
            overall_correct = (step_result.get("overall") == "proof_valid"
                               if step_result else False)
            v = Verdict(correct=overall_correct, raw=json.dumps(step_result or {}))
            cluster = AnswerCluster("proof")
            # 2026-09-12 定型前审核修复：候选是 `Candidate` dataclass（无 `.get`），
            # 原写法 `candidates[0].get("id", 0)` 在证明题单候选通道会抛
            # AttributeError（被外层吞掉 → 该通道静默失效）。
            cluster.candidate_ids = [getattr(candidates[0], "id", 0)]
            cluster.vote_correct = 1 if overall_correct else 0
            cluster.vote_total = 1
            # 2026-09-12 定型前审核修复：`step_verdicts` 键存在但为**空列表**时，
            # 原来的 `[0]` 会 IndexError（同样被外层吞掉 → 静默失效）。
            _sv = (step_result or {}).get("step_verdicts") or [{}]
            feedback = (_sv[0].get("note", "")
                        if step_result and not overall_correct else "")
            return {
                "cluster_data": [cluster],
                "feedback": feedback,
                "verdicts": [[v]],
                "best_cluster": cluster,
            }

        # 常规：每个候选投票（voting_times 参数化：难题深度通道 deep 档 3 票）
        # v2.8：ctx.state.voting_times 优先（RunState 运行时覆盖），config 兜底
        if voting_times is None:
            voting_times = (getattr(ctx.state, 'voting_times', None)
                            or getattr(self.config, 'verifier_voting_times', 1))
        all_verdicts: list[list[Verdict]] = []
        # ★ 2026-09-16：按候选分歧自适应票数与温度（见 _vote_profile）。
        #   **必须把档位票数传进去**——否则 deep 档的 3 票会被压回 1 票（自审发现的回归）。
        _d_votes, _d_temp = self._vote_profile(ctx, candidates,
                                               base_votes=voting_times)
        voting_times = _d_votes
        for i, cand in enumerate(candidates):
            if use_rubric:
                # rubric 结构化判分路径（含确定性旁证：fail 硬否决 / pass 独立票）
                vds = self._vote_rubric(ctx, problem, cand,
                                        use_deterministic=use_deterministic)
            else:
                vds = self._vote(ctx, problem, cand, total_votes=voting_times,
                                 use_scoring=use_scoring, temperature=_d_temp)
            # 反例挑战（P2，sq 语义）：仅"该候选无任何正确票"且非数值答案时触发，
            # LLM 生成命题 → 程序数值验证 → hard_fail 硬否决（客观证伪）。
            # 2026-09-11：若该候选**全是弃权票**（判分链路故障、无任何判定信息），
            # 不再触发挑战——限流风暴中这会逐候选追加 LLM 调用、自激放大（详见
            # Bug清单 §5 的 176 次限流秒级连发）。有真实判定信息时才值得挑战。
            _has_real_vote = any(not getattr(v, "abstain", False) for v in vds)
            if (use_challenge and vds and _has_real_vote
                    and not any(v.correct for v in vds)):
                ans = (cand.get("answer", "") if isinstance(cand, dict)
                       else getattr(cand, "answer", ""))
                chal = self._challenge_counterexample(
                    ctx, problem, self._candidate_text(cand), str(ans))
                if chal.get("hard_fail"):
                    for v in vds:
                        v.correct = False
                        v.confidence = 0.0
                    vds.append(Verdict(correct=False, raw="counterexample_fail",
                                       feedback=f"反例挑战否决: {chal.get('evidence', '')[:120]}"))
                self.record(ctx, "challenge",
                            f"候选#{i} 反例挑战: {chal['evidence'][:100]}")
            all_verdicts.append(vds)

        # v2.8 确定性硬否决：SymPy 代入回验/反例对候选做客观旁证，
        # fail → 该候选全部票判错（淘汰）；unknown/pass → 仅挂证据不改判决。
        # 全部 fail 时回退保留（宁可 unknown 绝不误杀，镜像 LeanGate 降级逻辑）。
        # （use_rubric=True 时确定性已在 _vote_rubric 内处理，此处跳过避免重复）
        if use_deterministic and candidates and not use_rubric:
            det_results = [self._deterministic_check(ctx, problem, c) for c in candidates]
            n_fail = sum(1 for r in det_results if r.get("verdict") == "fail")
            if 0 < n_fail < len(candidates):
                for i, r in enumerate(det_results):
                    if r.get("verdict") == "fail":
                        for v in all_verdicts[i]:
                            v.correct = False
                            v.deterministic = r
                        all_verdicts[i].append(Verdict(
                            correct=False, raw="deterministic_fail", deterministic=r))
                        self.record(ctx, "deterministic",
                                    f"确定性硬否决候选 #{i}: {r.get('evidence', '')[:120]}")
                    else:
                        for v in all_verdicts[i]:
                            if v.deterministic is None:
                                v.deterministic = r
            else:
                for i, r in enumerate(det_results):
                    for v in all_verdicts[i]:
                        if v.deterministic is None:
                            v.deterministic = r
                if n_fail == len(candidates) and n_fail > 0:
                    self.record(ctx, "deterministic",
                                "全部候选确定性否决，回退保留（宁 unknown 不误杀）")

        # 聚类 + 共识
        cluster_data = self._cluster_candidates(candidates, all_verdicts) if use_clustering else []
        best_cluster = cluster_data[0] if cluster_data else None

        # P1-1 确定性复算（playoff）：共识不强或验证全错时，低温独立重解
        # P0-4 修复：默认关闭（use_playoff=False），仅在时间宽裕时由 orchestrator 开启，
        # 避免叠加调用链耗尽单题预算 → 45 error
        if use_playoff and best_cluster is not None and ctx.budget is not None:
            confidence = (best_cluster.vote_correct / best_cluster.vote_total
                          if best_cluster.vote_total else 0.0)
            # 触发条件：置信度低（验证结果不可靠）或投票全否
            # 2026-09-12 定型前审核：原为 `if confidence < 0.5 and True:`
            # （`and True` 是残留死条件，删除后语义完全不变）
            if confidence < 0.5:
                top_ans = best_cluster.answer_norm or ""
                if self._playoff_recheck(ctx, problem, top_ans):
                    best_cluster.vote_correct += 1
                    best_cluster.vote_total += 1
                    self.record(ctx, "playoff", "确定性复算通过，答案可信")
                else:
                    # 复算不一致 → 置信度下调，标记供 orchestrator 走 revise
                    best_cluster.vote_correct = 0
                    best_cluster.vote_total = max(1, best_cluster.vote_total)
                    self.record(ctx, "playoff", "确定性复算不一致，转自纠错")

        # ★ 2026-09-15：带推理的最终复核（默认关）。
        # 判 B ⇒ 把该簇置信度压到 <0.5，**走既有的低置信度 → revise 通道**
        # （不新增任何流程分支），并直接复用它的推理文本当反馈，
        # 省掉一次额外的错因提取调用。
        _deep_reject = False
        _deep_raw = self._deep_final_review(ctx, problem, best_cluster)
        if _deep_raw and _last_verdict_ab(_deep_raw) is False:
            best_cluster.vote_correct = 0
            best_cluster.vote_total = max(1, best_cluster.vote_total)
            _deep_reject = True

        # Reflexion 修复：恢复失败反馈提取。仅在 best_cluster 低置信度/全错时
        # 提取（受预算约束），让 revise 回环拿到真实错误定位，而非空串导致的
        # "请重新审题"泛泛提示。
        if _deep_reject:
            feedback = ("【带推理复核判错｜错误类型：%s】%s" % (
                _extract_error_type(_deep_raw) or "未标注",
                _deep_raw.strip()))[:1500]
        else:
            feedback = self._extract_revise_feedback(
                ctx, problem, candidates, best_cluster)

        # ★ 2026-09-15：跨候选汇总错误类型分布（含 deterministic/playoff 后的终态）。
        # 与 `_vote` 内的同名埋点互补：那里是**单次投票**口径，这里是**整题**口径，
        # 供 diag 统计"这题被判 B 的票里，方法不适用/计算错各占多少"。
        error_types = self._record_error_types(
            ctx, [v for vds in all_verdicts for v in vds],
            step="verify_error_types")

        return {
            "cluster_data": cluster_data,
            "feedback": feedback,
            "verdicts": all_verdicts,
            "best_cluster": best_cluster,
            "error_types": error_types,
        }

    # ==================================================================
    # 辅助
    # ==================================================================

    def _candidate_text(self, candidate) -> str:
        if isinstance(candidate, dict):
            parts = []
            if candidate.get("reasoning"):
                parts.append(candidate["reasoning"])
            if candidate.get("answer"):
                parts.append(f"【最终答案】{candidate['answer']}")
            return "\n".join(parts)
        reasoning = getattr(candidate, "reasoning", "")
        answer = getattr(candidate, "answer", "")
        return f"{reasoning}\n【最终答案】{answer}" if reasoning and answer else str(candidate)

    def check_completeness(self, ctx: TaskContext, candidate) -> bool:
        """
        LLM 确认答案是否完整（是否被截断/未写完）。
        返回 True 表示完整，False 表示不完整。
        """
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system",
             "content": "你是答案完整性检查专家。检查以下解答是否给出了完整结论（没有截断、没有'待续'等）。只输出 COMPLETE 或 INCOMPLETE。"},
            {"role": "user", "content": text + "\n\n这个答案是完整的吗？"},
        ]
        try:
            # v2.4.1：prefill「COMPLETE 」抑制 CoT，秒级返回判定
            raw = self.llm(ctx, prefill_messages(messages, "COMPLETE "), 0.0, 64)
            # ★ 2026-09-16 审计修复：原判据 `"INCOMPLETE" not in raw.upper()
            #   or "COMPLETE" in raw.upper()` **恒为 True** —— "INCOMPLETE" 本身
            #   就含子串 "COMPLETE" ⇒ 任一分支都为真 ⇒ 任何非 None 输出都判"完整"，
            #   完整性校验形同虚设。（本函数当前无调用点，属预防性修复。）
            return "INCOMPLETE" not in (raw or "").upper()
        except Exception:
            return True  # 网络异常时保守当作完整
