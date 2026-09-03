from __future__ import annotations
"""
难度路由智能体（DifficultyRouter）
================================

难题深度求解通道的第一环：在求解前判定题目档位，决定资源分配。

三级档位：
- fast     简单题：1 候选 + 0-1 票验证，预算 60-120s
- standard 标准题：2 候选 + 1 票聚类，预算 300-480s（== 现状）
- deep     难题：4 候选温度分层 + 截断续写 + 子目标分解 + 3 票验证
           + 0 票时 revise 自纠错 + playoff 复算，预算至 1200s

识别方式（双层，不破坏 prefill 一致性）：
1. 静态特征预判（零 LLM 调用）：题型领域 + 题目长度 + 竞赛风格关键词，
   输出 1-5 静态难度分；
2. LLM 自评难度（1 次小调用，prefill「难度评级：」+ max_tokens=128，
   秒级返回）：模型对题目自评 1-5 难度分；
3. 规则融合：加权平均 + 置信度回退 → 最终档位。

全链路复用现有 prefill 压缩调用范式（prefill_messages/stitch），
不引入任何自由 CoT，保证难度自评调用在秒级内返回。
"""

import logging
import re

from .base import BaseAgent, TaskContext
from utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot")

# ---------------------------------------------------------------------------
# 静态特征信号表
# ---------------------------------------------------------------------------

# 题型领域 → 快车道倾向（命中即视为简单）
_FAST_DOMAINS = (
    "选择", "填空", "arithmetic", "算术", "计算", "运算",
    "choice", "fill", "multiple_choice", "计算题",
)

# 题型领域 → 深度通道倾向
_DEEP_DOMAINS = (
    "证明", "证明题", "不等式证明", "几何证明", "数论", "组合数学",
    "组合", "图论", "几何", "不等式", "抽象代数", "拓扑学", "拓扑",
    "复分析", "实分析", "泛函分析", "微分几何", "偏微分方程", "pde",
    "abstract_algebra", "topology", "complex_analysis", "real_analysis",
    "functional_analysis", "differential_geometry", "number_theory",
    "combinatorics", "graph_theory", "inequality", "geometry",
)

# 竞赛风格关键词（命中即视为难题倾向）
_DEEP_KEYWORDS = (
    "imo", "竞赛", "奥数", "奥林匹克", "prove", "proof", "证明",
    "不等式", "同余", "素数", "质数", "费马", "欧拉", "galois", "伽罗瓦",
    "有限域", "勒让德", "构造性", "充分必要条件", "存在性", "唯一性",
    "一般性", "充分性", "必要性", "反证法", "归纳法", "不动点",
)

# 简单风格关键词
_FAST_KEYWORDS = (
    "选择", "单选", "填空", "计算", "求值", "化简", "简算", "evaluate",
    "compute", "simplify", "calculate", "求导", "求积分", "解方程",
)

# 快车道可解的题型标签（与 orchestrator._FAST_PATH_PATTERNS 对齐）
_FAST_PATH_TAGS = ("arithmetic", "derivative", "integral", "determinant",
                   "equation", "quadratic", "limit")

# 档位阈值
_SCORE_FAST_MAX = 2.0      # 静态/融合分 <=2 → fast
_SCORE_DEEP_MIN = 4.0      # 静态/融合分 >=4 → deep

_DIFFICULTY_SYS = (
    "你是一位数学竞赛命题专家。请判断下面这道题的难度等级。"
    "只输出一个整数难度分：1=非常简单，2=简单，3=中等，4=困难，5=非常困难。"
    "不要输出任何解释或推理，只输出整数。"
)


class DifficultyRouter(BaseAgent):
    name = "DifficultyRouter"

    def run(self, ctx: TaskContext) -> TaskContext:
        """难度路由主流程：静态预判 → LLM 自评 → 融合 → 写入 ctx.tier。"""
        if not getattr(self.config, 'enable_difficulty_router', True):
            ctx.tier = "standard"
            self.record(ctx, "difficulty_router",
                        "难度路由已禁用，统一使用 standard 档", tier="standard")
            return ctx

        # 1) 静态特征预判（零 LLM 调用）
        static_tier, static_score, evidence = self._static_assess(ctx.problem, ctx.domain)

        # 应急模式：跳过 LLM 自评，直接静态判定（省 1 次调用保预算）
        if getattr(ctx.state, 'emergency', False):
            ctx.tier = static_tier
            ctx.tier_evidence = {
                "static": round(static_score, 2),
                "llm": None,
                "note": "emergency_static_only",
                "evidence": evidence[:6],
            }
            self.record(ctx, "difficulty_router",
                        f"应急模式静态判定: {static_tier} (static={static_score:.1f})",
                        tier=static_tier, static_score=round(static_score, 2))
            return ctx

        # 2) LLM 自评难度（1 次小调用，prefill 抑制 CoT，秒级返回）
        llm_score, llm_note = None, "llm_disabled"
        if (getattr(self.config, 'enable_llm_difficulty', True)
                and not ctx.is_time_critical()
                and not ctx.is_time_critical()):
            llm_score, llm_note = self._llm_assess(ctx)
            if llm_score is None and llm_note != "llm_disabled":
                logger.warning("Difficulty LLM assess failed: %s", llm_note)

        # 3) 规则融合
        tier, note = self._fuse(static_tier, static_score, llm_score, llm_note)
        ctx.tier = tier
        ctx.tier_evidence = {
            "static": round(static_score, 2),
            "llm": llm_score,
            "note": note,
            "evidence": evidence[:6],
        }
        self.record(
            ctx, "difficulty_router",
            f"档位判定: {tier} (static={static_score:.1f}, llm={llm_score})",
            tier=tier,
            static_score=round(static_score, 2),
            llm_score=llm_score,
            note=note,
        )
        return ctx

    # ------------------------------------------------------------------
    # 静态特征预判（零 LLM 调用）
    # ------------------------------------------------------------------
    def _static_assess(self, problem: str, domain: str = None):
        """基于领域 + 长度 + 关键词给出 1-5 静态难度分。

        返回 (tier, score, evidence)。
        """
        text = problem or ""
        d = (domain or "").lower()
        score = 3.0
        evidence: list[str] = []
        n = len(text)

        # 快车道可解题型 → 强 fast 信号
        for tag in _FAST_PATH_TAGS:
            if tag in d:
                score -= 1.0
                evidence.append(f"fast:fastpath:{tag}")
                break

        # fast 领域
        for kw in _FAST_DOMAINS:
            if kw.lower() in d:
                score -= 0.8
                evidence.append(f"fast:domain:{kw}")
                break

        # fast 关键词（短题倾向）
        for kw in _FAST_KEYWORDS:
            if kw.lower() in text.lower():
                score -= 0.4
                evidence.append(f"fast:kw:{kw}")
                break

        # 短题
        if n < 150:
            score -= 0.5
            evidence.append("fast:short_text")

        # deep 领域
        for kw in _DEEP_DOMAINS:
            if kw.lower() in d:
                score += 1.0
                evidence.append(f"deep:domain:{kw}")
                break

        # deep 关键词
        for kw in _DEEP_KEYWORDS:
            if kw.lower() in text.lower():
                score += 0.5
                evidence.append(f"deep:kw:{kw}")
                break

        # 长题
        if n > 500:
            score += 1.0
            evidence.append("deep:long_text")

        # 2026-08-30 Algebra 专项：代数题正确率历史最低（1/11=9%），
        # 强制提升到 deep 档以用更多候选/时间（依赖 config.algebra_force_deep）
        if getattr(self.config, "algebra_force_deep", False) and d == "algebra":
            score += 1.5
            evidence.append("deep:algebra_force")

        score = min(5.0, max(1.0, score))
        tier = self._score_to_tier(score)
        return tier, score, evidence

    # ------------------------------------------------------------------
    # LLM 自评难度（1 次小调用）
    # ------------------------------------------------------------------
    def _llm_assess(self, ctx: TaskContext):
        """prefill「难度评级：」引导模型只输出 1-5 整数，秒级返回。

        返回 (score:int|None, note:str)。
        """
        try:
            raw = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": _DIFFICULTY_SYS},
                        {"role": "user", "content": ctx.problem},
                    ],
                    "难度评级：",
                ),
                0.0,
                128,
            )
            if not raw:
                return None, "llm_empty"
            raw = stitch("难度评级：", raw)
            m = re.search(r"[1-5]", raw.strip())
            if not m:
                return None, "llm_unparsable"
            return int(m.group()), "llm_ok"
        except Exception as e:  # noqa: BLE001
            logger.warning("Difficulty LLM assess exception: %s", e)
            return None, "llm_exception"

    # ------------------------------------------------------------------
    # 规则融合
    # ------------------------------------------------------------------
    def _fuse(self, static_tier: str, static_score: float,
              llm_score: int | None, llm_note: str):
        """融合静态分与 LLM 自评分。

        - LLM 自评失败 → 回退静态判定（置信度优先）。
        - 成功 → 加权平均（static 0.4 + llm 0.6），再按阈值映射档位。
        """
        if llm_score is None:
            tier = static_tier
            note = f"static_only({llm_note})"
            return tier, note
        final = round(0.4 * static_score + 0.6 * float(llm_score), 2)
        tier = self._score_to_tier(final)
        note = f"static={static_score:.1f}+llm={llm_score}->{final}"
        return tier, note

    @staticmethod
    def _score_to_tier(score: float) -> str:
        if score <= _SCORE_FAST_MAX:
            return "fast"
        if score >= _SCORE_DEEP_MIN:
            return "deep"
        return "standard"
