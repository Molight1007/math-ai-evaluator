# -*- coding: utf-8 -*-
"""对抗式验证器（#16 改造）：**证伪**而非验证。

为什么要单独做这个
--------------------
基线 45 题暴露了两个互相矛盾的问题：

1. **误杀**：两层复核一致性仅 51%，单层过、双层不过的有 22 题，
   其中 7 题最终判对（误杀率 31.8%），且**反向案例为 0 条** ——
   说明第二层不是"换个角度看"，只是在第一层基础上加严。
2. **漏检**：正向验证顺着作者思路走（确认偏误），错误没被审出来。

这两件事的**共同解**是换一种认知模式：正向验证问"这对吗"，
对抗式验证问"**假设它是错的，错在哪**"。后者在方法论上是证伪
（波普尔），在数学上对应反例法，比"确认正确"更能激发批判性思维。

与现有 Step 4（`Orchestrator._review_bug_feedback`）的分工
--------------------------------------------------------
- Step 4（已有）：验证器**给出负面反馈后**，复核是否误报 → 治误杀
- 本模块（新增）：验证器**判定通过后**，主动去找错     → 治漏检

两者互补，缺一则另一侧的漏洞仍在。

仲裁规则（由 orchestrator 组合使用）::

    正向通过 + 逆向无反例  → 高置信接受（不再被第二层无脑否掉）
    正向通过 + 逆向有反例  → 送 revise（抓漏检）
    正向不通过            → 直接 revise（无需证伪，省一次调用）

设计原则：本模块只做**探测**，不做决策。任何异常一律吞掉并返回
``found=False``——验证器的问题绝不能阻断主流程。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseAgent, TaskContext

logger = logging.getLogger("MathPilot")

# 6 类数学错误 checklist —— 从 45 题真实错误样本提炼，每条都有对应真题：
#   sign_error          algebra-064：答案 −3 写成 3
#   skipped_step        geometry-068："Solving yields s=187/228" 直接跳到结论
#   boundary_missed     number_theory-022：答"所有正奇数"，实际是 {1,3,5}
#   special_case_missed algebra-003：只分析线性解，错误排除三次多项式解
#   calculation_error   geometry-051：121/125 + 25 = 24（应为 25.968）
#   misread_requirement combinatorics-040：给了含 N 的表达式，题目要求数值
ERROR_CHECKLIST = (
    ("sign_error", "符号错误：正负号、不等号方向、分子分母颠倒"),
    ("skipped_step", "跳步：直接给出关键结论但缺少推导过程"),
    ("boundary_missed", "边界遗漏：定义域、退化情形、端点、特殊情况未讨论"),
    ("special_case_missed", "情形遗漏：只分析了一部分情形（如只考虑线性解）"),
    ("calculation_error", "计算错误：算术或代数运算出错"),
    ("misread_requirement", "题意偏差：答非所问，或答案形式不符合题目要求"),
)

_ERROR_TYPES = tuple(k for k, _ in ERROR_CHECKLIST)

# 模型常常用中文或自造词回类型（实测出现过"计算错误"），
# 归一化不了就会污染 #16 的错误类型统计，故给一份中英别名表兜底。
_ERROR_ALIASES = (
    ("符号", "sign_error"), ("正负", "sign_error"), ("不等号", "sign_error"),
    ("跳步", "skipped_step"), ("省略", "skipped_step"), ("缺.*推导", "skipped_step"),
    ("未推导", "skipped_step"),
    ("边界", "boundary_missed"), ("定义域", "boundary_missed"),
    ("退化", "boundary_missed"), ("端点", "boundary_missed"),
    ("范围", "boundary_missed"), ("遗漏", "boundary_missed"),
    ("情形", "special_case_missed"), ("特殊", "special_case_missed"),
    ("分类", "special_case_missed"), ("排除", "special_case_missed"),
    ("计算", "calculation_error"), ("算术", "calculation_error"),
    ("运算", "calculation_error"),
    ("题意", "misread_requirement"), ("答非所问", "misread_requirement"),
    ("形式不符", "misread_requirement"), ("不符合.*要求", "misread_requirement"),
    ("未理解", "misread_requirement"), ("理解.*题目", "misread_requirement"),
    ("答非", "misread_requirement"),
)

_ADVERSARY_SYSTEM = (
    "你是数学解答的**对抗式审查者**。\n"
    "你的任务不是确认答案正确，而是**尽力证明它是错的**。\n"
    "默认立场：给定的答案是错误的，你要找出它错在哪里。\n"
    "只有当你用尽方法仍找不到任何错误时，才承认它可能对。\n"
    "你是严谨的对手，不是附和者——但也不能凭空捏造错误。"
)

_ADVERSARY_TEMPLATE = (
    "【题目】\n{problem}\n\n"
    "【待审查的解答】\n{reasoning}\n\n"
    "【该解答给出的最终答案】\n{answer}\n\n"
    "请按以下 {n} 类错误逐项排查，尽力找出答案的错误：\n{checklist}\n\n"
    "对每一类，判断是否存在该类型错误。若找到错误，必须给出：\n"
    "  - 出错的具体步骤（原文摘录，不要改写）\n"
    "  - 具体错在哪、正确应该是什么\n"
    "  - 若可能，给出一个反例或具体反证\n\n"
    "只输出 JSON，不要任何多余文字：\n"
    '{{"found": <true 表示找到错误 / false 表示未找到>, '
    '"error_type": "<{types} 之一，未找到时为空字符串>", '
    '"error_step": "<出错步骤原文，未找到时为空字符串>", '
    '"counterexample": "<反例或反证，没有则空字符串>", '
    '"confidence": <0到1之间的小数>, '
    '"reasoning": "<一句话说明你的判断依据>"}}'
)

# prefill 种子必须锚定顶层结构（Intern 系列铁律）：
# 只用 '{"' 会让模型以为已进入对象内部、丢掉外层键 → 结构非法
_PREFILL_SEED = '{"found": '

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class AdversarialResult:
    """对抗式验证的探测结果。"""

    found: bool = False                 # 是否找到反例 / 错误
    error_type: str = ""                # 6 类之一（见 ERROR_CHECKLIST）
    error_step: str = ""                # 出错步骤原文
    counterexample: str = ""            # 反例或反证
    confidence: float = 0.0             # 模型自评置信度
    reasoning: str = ""                 # 判断依据
    raw: str = ""                       # 原始返回（排障用）
    parsed: bool = False                # JSON 是否被成功解析
    skipped: str = ""                   # 跳过原因（空 = 正常执行）

    @property
    def is_actionable(self) -> bool:
        """是否足以触发 revise —— 找到错误且有具体位置才可信。"""
        return self.found and bool(self.error_step or self.counterexample)

    def to_feedback(self) -> str:
        """转成可注入 revise 通道的反馈文本。"""
        if not self.is_actionable:
            return ""
        label = dict(ERROR_CHECKLIST).get(self.error_type, self.error_type or "未知类型")
        parts = [f"[对抗式审查] 检出「{label}」"]
        if self.error_step:
            parts.append(f"出错步骤：{self.error_step[:300]}")
        if self.counterexample:
            parts.append(f"反例/反证：{self.counterexample[:300]}")
        if self.reasoning:
            parts.append(f"依据：{self.reasoning[:300]}")
        return "\n".join(parts)


class AdversarialVerifier(BaseAgent):
    """对抗式验证器：假设答案错误，反向寻找反例或第一个错误步骤。"""

    def __init__(self, client, config):
        # 注意：BaseAgent.__init__ 只接 (client, config)，没有 budget 形参
        super().__init__(client, config)
        self._enabled = bool(getattr(config, "enable_adversarial_verify", True))
        self._tiers = tuple(getattr(config, "adversarial_tiers", None) or
                            ("deep", "standard"))
        self._min_conf = float(getattr(config, "adversarial_min_confidence", 0.5))
        self._max_reasoning = int(getattr(config, "adversarial_max_reasoning", 2400))

    # ------------------------------------------------------------------
    # BaseAgent 接口（pipeline 形态入口）
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext, tier: str = "standard") -> TaskContext:
        """对最佳候选做证伪探测，把结果写入 ``ctx.adversarial_result``。

        命中错误时同时把反馈追加进 ``ctx.lean_reject_feedback``，
        由 orchestrator 的 revise 通道消费（与 Lean 反馈同一入口）。
        """
        cand = None
        bc = getattr(ctx, "_best_cluster", None)
        if bc is not None and getattr(bc, "rep_candidate", None) is not None:
            cand = bc.rep_candidate
        if cand is None and getattr(ctx, "candidates", None):
            cand = ctx.candidates[0]
        if cand is None:
            return ctx

        result = self.probe(ctx, cand, tier=tier)
        ctx.adversarial_result = result
        if result.is_actionable:
            fb = getattr(ctx, "lean_reject_feedback", None) or []
            fb.append(result.to_feedback())
            ctx.lean_reject_feedback = fb
        self.record(ctx, "adversarial",
                    ("检出 %s" % (result.error_type or "未知类型"))
                    if result.is_actionable else "未找到错误",
                    adv_found=result.is_actionable,
                    adv_error_type=result.error_type,
                    adv_confidence=result.confidence)
        return ctx

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def probe(self, ctx: TaskContext, candidate,
              tier: str = "standard") -> AdversarialResult:
        """对单个候选做证伪探测；返回 AdversarialResult。

        任何异常都被吞掉并返回 ``found=False`` —— 验证器出问题
        只意味着"这次没抓到错"，不应阻断主流程。
        """
        if not self._enabled:
            return AdversarialResult(skipped="disabled")
        if tier not in self._tiers:
            return AdversarialResult(skipped=f"tier_not_covered:{tier}")

        reasoning = str(getattr(candidate, "reasoning", "") or "")
        answer = str(getattr(candidate, "answer", "") or "")
        if not reasoning.strip():
            return AdversarialResult(skipped="empty_reasoning")

        try:
            raw = self._call_probe(ctx, reasoning, answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[adversarial] 对抗式审查调用失败（降级为未找到）: %s",
                           str(exc)[:120])
            return AdversarialResult(skipped=f"call_failed:{type(exc).__name__}")

        if not raw:
            return AdversarialResult(skipped="empty_response")

        result = self._parse(raw)
        # 低置信度的"找到"不采信：宁可漏掉，不可误伤
        if result.found and result.confidence < self._min_conf:
            logger.debug("[adversarial] 检出但置信度 %.2f < %.2f，不采信",
                         result.confidence, self._min_conf)
            result.found = False
        return result

    # ------------------------------------------------------------------
    # 内部：调用与解析
    # ------------------------------------------------------------------
    def _call_probe(self, ctx: TaskContext, reasoning: str, answer: str) -> str:
        """调用模型做对抗式审查（走 prefill 压缩，避免 CoT 吃满 max_tokens）。"""
        from utils.llm import prefill_messages

        checklist = "\n".join(
            f"{i}. {name}：{desc}" for i, (name, desc) in enumerate(ERROR_CHECKLIST, 1))
        user = _ADVERSARY_TEMPLATE.format(
            problem=str(getattr(ctx, "problem", ""))[:2000],
            reasoning=reasoning[-self._max_reasoning:],
            answer=answer[:300],
            n=len(ERROR_CHECKLIST),
            checklist=checklist,
            types=" / ".join(_ERROR_TYPES),
        )
        msgs = prefill_messages(
            [{"role": "system", "content": _ADVERSARY_SYSTEM},
             {"role": "user", "content": user}],
            _PREFILL_SEED,
        )
        raw = self.llm(ctx, msgs, temperature=0.0,
                       max_tokens=int(getattr(self.config, "adversarial_max_tokens", 640)))
        if not raw:
            return ""
        # prefill 的种子不在返回里，解析前补回去
        return _PREFILL_SEED + raw if not raw.lstrip().startswith("{") else raw

    @staticmethod
    def _try_load(text: str) -> Optional[dict]:
        """尝试从文本里解析出 JSON 对象；失败返回 None。"""
        m = _JSON_RE.search(text or "")
        if not m:
            return None
        frag = m.group(0)
        # 先整体试；不行就逐步回退到最后一个 '}'（尾部有多余内容的情况）
        for cut in range(len(frag), 0, -1):
            if frag[cut - 1] != "}":
                continue
            try:
                obj = json.loads(frag[:cut])
            except Exception:  # noqa: BLE001
                continue
            return obj if isinstance(obj, dict) else None
        return None

    @staticmethod
    def _strip_truncated_tail(text: str) -> str:
        """剥掉末尾被截断的片段并补 '}'，抢救截断输出。

        ``{"found": true, "error_type": "sign_error", "error_step``
        → ``{"found": true, "error_type": "sign_error"}``

        实现：只从**合法的截断边界**（引号 / 逗号）处回退尝试，
        而不是逐字符——否则会把已完整的 `"sign_error"` 值也削掉半截引号。
        """
        frag = (text or "").strip()
        i = frag.find("{")
        if i < 0:
            return ""
        frag = frag[i:]
        for cut in range(len(frag), 0, -1):
            if frag[cut - 1] not in ('"', "'", ",", "，", " "):
                continue
            cand = frag[:cut].rstrip().rstrip(",，") + "}"
            if AdversarialVerifier._try_load(cand):
                return cand
        return ""

    @staticmethod
    def _parse(raw: str) -> AdversarialResult:
        """解析模型输出；解析失败返回 found=False（不可信就当没抓到）。"""
        text = (raw or "").strip()
        data = AdversarialVerifier._try_load(text)
        if data is None:
            # 截断/脏输出：剥掉末尾未闭合的键再补 '}' 重试一次
            data = AdversarialVerifier._try_load(
                AdversarialVerifier._strip_truncated_tail(text))
        if data is None:
            return AdversarialResult(raw=text, parsed=False, skipped="parse_failed")

        raw_type = str(data.get("error_type") or "").strip()
        etype = raw_type
        if etype and etype not in _ERROR_TYPES:
            # 模型自造类型（含中文）：先按英文键名子串匹配，再按中文别名表匹配；
            # 都匹配不上就置空——宁可丢掉类型标注，也不能让脏值污染 #16 的统计。
            # 注意：两轮匹配都必须基于原始 raw_type，用 etype 会被上一轮的空结果污染。
            low = raw_type.lower()
            etype = next((k for k in _ERROR_TYPES if k in low), "")
            if not etype:
                etype = next((v for pat, v in _ERROR_ALIASES
                              if re.search(pat, raw_type)), "")

        try:
            conf = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0

        return AdversarialResult(
            found=bool(data.get("found")),
            error_type=etype,
            error_step=str(data.get("error_step") or "").strip(),
            counterexample=str(data.get("counterexample") or "").strip(),
            confidence=max(0.0, min(1.0, conf)),
            reasoning=str(data.get("reasoning") or "").strip(),
            raw=text,
            parsed=True,
        )
