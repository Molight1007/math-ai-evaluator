# -*- coding: utf-8 -*-
"""投票执行（从 agent/verifier.py 逐字搬出）。

S2（2026-10-09）：``_vote_one`` / ``_vote_profile`` / ``_vote`` 搬为模块级
函数，原 ``self`` 作为第一个参数 ``owner`` 传入；所有需要走实例级
``mock.patch.object`` 的调用（如 ``owner._vote_one_rubric`` /
``owner._deterministic_check`` / ``owner._prepare_theorem_context`` /
``owner._is_correct_vote`` / ``owner._vote_one`` / ``owner._record_error_types``）
一律经 ``owner`` 解析 ⇒ patch 仍可穿透。
S3（2026-10-09）：``verifier.py`` 顶部已 `from . import verifier__vote as _vv`，
``_vote_one`` / ``_vote_profile`` / ``_vote`` 改为一行委托跳板。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging

from prompts.verifier import VERIFIER_SYSTEM, VERIFIER_USER_TEMPLATE
from utils.prefill import prefill_messages, stitch

from .base import Verdict
from .verifier__review import _extract_error_type

logger = logging.getLogger("MathPilot.Verifier")


def _vote_one(owner, ctx, problem: str, candidate_text: str,
              temperature: float = 0.0, full_reasoning: bool = False) -> str:
    """单次投票（返回原始文本）。

        v2.4.1：prefill「VERDICT: 」抑制 CoT——投票输出只需 A/B，
        实测 prefill 仲裁 0.8s vs 普通 70.2s（140×），杜绝 Intern-S2 推理流占满预算。
        2026-09-15：注入检索到的 Mathlib 定理原文（方案 A，未启用时为空串）。
        2026-09-16：**温度改为参数化**。此前这里硬编码 0.0，导致
        `config.verifier_temperature` 是**死配置**（声明了/进白名单/有 CLI，
        但全仓无人读），且多张票在温度 0 下几乎完全相同 ⇒ **投票没有方差**，
        "多票" 只是同一判断重复 N 次（实测：6 候选 × 3 票对错答**全票投 A**）。

        ★ 2026-10-04（**B 折中**，用户决策「正确率第一位」）：新增 `full_reasoning`。
        为 True 时**不 prefill**，让验证器跑完完整推理再给判定 —— 依据是本文件自己的
        实测记录：「prefill 0.8s 不足以完成系统提示词要求的"**独立重算 + 逐条攻击**"
        ⇒ 投票退化成**"看一眼就点头"**」（10 题中 5 道错题的全部候选被全票判 A）。
        由 `_vote_profile` 在**候选分歧**时置位（折中：把昂贵算力花在真拿不准的题上）；
        开关 `verifier_vote_reasoning` 可切 `off`(C) / `disagree`(B) / `always`(A)。
        """
    messages = [
        {"role": "system", "content": VERIFIER_SYSTEM},
        {"role": "user", "content": VERIFIER_USER_TEMPLATE.format(
            problem=problem,
            candidate_answer=candidate_text,
            theorem_context=(getattr(ctx, "_leansearch_ctx", "") or "(无)"),
        )},
    ]
    if full_reasoning:
        # 不 prefill ⇒ 原样返回完整原文（推理 + 判定行）。
        # ⚠ **不能**过 `stitch`：那会把 "VERDICT: " 种子里**拼到推理前面**，
        #   凭空造出一个空前缀行（虽然 `_last_verdict_ab` 取最后一个匹配仍正确，
        #   但文本被污染、且会给后续解析添乱）。直接返回最干净。
        return owner.llm(ctx, messages, temperature, 32768) or ""
    raw = owner.llm(ctx, prefill_messages(messages, "VERDICT: "),
                   temperature, 32768)
    return stitch("VERDICT: ", raw) if raw else raw


def _vote_profile(owner, ctx, candidates, base_votes=None) -> tuple:
    """返回本次投票的 ``(票数, 温度)``。

        ⚠ ``base_votes`` 必须传入**调用方决定的档位票数**（orchestrator 对 deep 档传 3）。
        2026-09-16 自审发现：本方法最初只读 `config.verifier_voting_times`(=1)，
        而 `run()` 里又无条件 `voting_times = _d_votes` ⇒ **把 deep 档的 3 票压回 1 票**
        （与 `tier_voting_times[deep]=3` 的设计直接矛盾）。现改为**以下限方式合并**：
        分歧时用 `max(档位票数, 分歧票数)`，一致时保留档位票数。
        """
    base_votes = int(
        base_votes if base_votes is not None
        else (getattr(owner.config, "verifier_voting_times", 1) or 1))
    base_temp = float(getattr(owner.config, "verifier_temperature", 0.0) or 0.0)
    _rmode = owner._vote_reasoning_mode()
    if not getattr(owner.config, "verifier_diversify_enabled", True):
        return base_votes, base_temp, (_rmode == "always")
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
        return base_votes, base_temp, (_rmode == "always")
    if len(answers) < 2:
        # 候选答案一致 ⇒ 加票/加温都无意义（只会重复同一判断）
        return base_votes, base_temp, (_rmode == "always")
    n = max(base_votes, int(
        getattr(owner.config, "verifier_disagreement_votes", 3) or 1))
    t = float(getattr(
        owner.config, "verifier_disagreement_temperature", 0.7) or 0.0)
    owner.record(ctx, "vote_diversify",
                "候选答案存在 %d 种分歧 → 票数 %d、温度 %.2f"
                "（温度 0 下多票无方差，等于重复同一判断）"
                % (len(answers), n, t))
    return n, t, (_rmode != "off")


def _vote(
    owner, ctx, problem: str, candidate, total_votes: int = 5,
    proportional: bool = True, use_scoring: bool = False,
    temperature: float = 0.0, full_reasoning: bool = False,
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
    text = owner._candidate_text(candidate)
    verdicts: list[Verdict] = []

    # ★ 2026-09-15 方案 A：**在启动投票线程之前**完成检索（单线程、每题一次），
    # 避免 6 候选 × 3 票 = 18 次并发重复检索。未启用/失败时注入为空串，
    # 验证器行为与改动前完全一致。
    owner._prepare_theorem_context(ctx, problem)

    # 二元投票
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(total_votes, owner.config.max_workers)
    ) as executor:
        futures = [executor.submit(owner._vote_one, ctx, problem, text,
                                   temperature, full_reasoning)
                   for _ in range(total_votes)]
        for f in concurrent.futures.as_completed(futures):
            try:
                raw = f.result()
                ok = owner._is_correct_vote(raw)
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
    if use_scoring and owner.config.use_scoring:
        try:
            scoring = owner._vote_one_scoring(ctx, problem, text)
            if scoring:
                verdicts.append(Verdict(
                    correct=scoring.get("overall", "B") == "A",
                    raw=json.dumps(scoring, ensure_ascii=False),
                    score=scoring,
                ))
        except Exception as e:
            logger.debug(f"Scoring vote failed: {e}")

    owner._record_error_types(ctx, verdicts)
    return verdicts
