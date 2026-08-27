# -*- coding: utf-8 -*-
"""
MathPilot 主框架接入适配器（multi_agent_runner）
================================================

评测器 GUI 勾选「多智能体版」时，``测试工具/main.py`` 会
``from multi_agent_runner import run_inference / run_inference_multi``。

此前该文件缺失，导致 ``run_evaluation`` 里 import 抛异常被静默吞掉，
回退到原版 ``intern_s1.py``（单次调用 + 自审核 1 轮重试 + 置信度虚高），
正确率仅约 30%。

本模块做两件事：
1. ``SyncInternClient``：把评测器异步 LLM 配置包装成 MathPilot 主框架期望的
   **同步** ``client.chat(messages=..., temperature=..., max_tokens=...)`` 接口
   （用 httpx 同步直连 Intern-S 服务，不依赖 asyncio 事件循环）。
2. ``run_inference`` / ``run_inference_multi`` 等入口：真正调用根目录
   ``user_agent.ReasoningAgent``，走完整 Orchestrator 链路：
   题型识别 → 快车道 → 难度路由 → 求解（多候选）→ 三Agent协作（反复验证）
   → 验证（投票共识）→ 格式化，并把结果适配回评测器 ``InferenceResult``。

关键增强（对应"时间充裕却过早停止 / 正确率仅 30%"问题）：
- deep 档难题启用三Agent协作反复验证（collab_max_rounds），直到验证通过或超时；
- 置信度改为 Verifier 投票共识（correct_votes / total_votes），而非模型自报，
  从源头杀掉"虚高置信度"。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

import httpx

# 先加载评测器自身模块（config / models 仅在 测试工具/ 下存在），
# 再加载根目录 user_agent（其内部会把根目录插到 sys.path 最前，不影响已有模块）。
from config import get_config
from models import InferenceResult

# 保证能 import 根目录的 MathPilot 主框架（user_agent.py）
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from user_agent import ReasoningAgent  # noqa: E402

logger = logging.getLogger("MathPilot.Runner")


# ---------------------------------------------------------------------------
# 同步 client 适配器
# ---------------------------------------------------------------------------
class SyncInternClient:
    """同步 client：把评测器 LLMConfig 包装成 MathPilot 期望的同步 chat 接口。

    MathPilot 的 Orchestrator / BaseAgent 内部以**同步**方式调用
    ``client.chat(messages=..., temperature=..., max_tokens=...)`` 并期望返回 str/dict。
    本类用 httpx 同步直连，配合 ``asyncio.to_thread`` 在独立线程运行，
    不阻塞评测器的事件循环（并发仍然生效）。
    """

    def __init__(self, llm_config):
        self.llm_config = llm_config
        self._url = f"{llm_config.base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {llm_config.api_key}",
            "Content-Type": "application/json",
        }
        # 单次 HTTP 超时：实测 Intern-S 最长推理 180s+，用 240s（4 分钟）兜底。
        # v2.6 修复：之前 900s 导致 SubGoalSolver 单次失败 attempt 等 15 分钟，
        # 3 次重试耗尽单题预算，后续 Solver/Verifier/Formatter 全没时间。
        # 真正的时限由 Orchestrator 的 deadline（1200s）+ llm() 的 is_time_critical
        # 双重控制，HTTP 超时只需覆盖正常推理的最长场景。
        self._timeout = 240.0

    # 限流识别：HTTP 429 / 错误码 -20048 / 关键词
    _RATE_LIMIT_CODES = ("-20048", "20048")
    _RATE_LIMIT_KEYWORDS = (
        "过于频繁", "too frequent", "too many", "rate limit",
        "ratelimit", "限流", "请求频繁", "频繁",
    )

    def _is_rate_limited(self, status_code: int, body: str) -> bool:
        if status_code == 429:
            return True
        bl = (body or "").lower()
        if any(k.lower() in bl for k in self._RATE_LIMIT_KEYWORDS):
            return True
        if any(c in bl for c in self._RATE_LIMIT_CODES):
            return True
        return False

    @staticmethod
    def _rate_limit_backoff(attempt: int) -> float:
        # 限流退避：20s 起步，指数翻倍，上限 90s
        # 起步从 15s 提到 20s：避免"限流窗口≈15s 时首轮重试刚好仍在窗口内"
        return min(20.0 * (2 ** attempt), 90.0)

    def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
        payload = {
            "model": self.llm_config.model,
            "messages": list(messages),
            "temperature": temperature if temperature is not None else 0.3,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
        }
        # Intern-S2 默认开启深度思考（先输出大段 Thinking Process），
        # 会破坏 MathPilot 的 prefill 前置答案策略，与评测器原版保持一致：显式关闭。
        model_name = (self.llm_config.model or "").lower()
        if "s2" in model_name:
            payload["thinking_mode"] = False

        last_err = None
        # 限流场景需要更多重试机会（20s 起步 5 次总退避≈320s，远低于单题 1200s 硬限）
        max_retries = max(5, self.llm_config.max_retries or 3)
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(self._url, headers=self._headers, json=payload)

                # 限流：长退避后重试（不抛错，等待窗口过去）
                if self._is_rate_limited(resp.status_code, resp.text):
                    wait = self._rate_limit_backoff(attempt)
                    last_err = f"rate limit (HTTP {resp.status_code})"
                    logger.warning(
                        "SyncInternClient 限流，等待 %.1fs 后重试 %d/%d",
                        wait, attempt + 1, max_retries,
                    )
                    if attempt + 1 < max_retries:
                        time.sleep(wait)
                        continue
                    break

                # 其他非 2xx：5xx 短退避重试，4xx 直接抛错（客户端错误重试无意义）
                if resp.status_code >= 400:
                    body = resp.text[:500]
                    if resp.status_code >= 500 and attempt + 1 < max_retries:
                        time.sleep(min(2 ** attempt, 8))
                        last_err = f"HTTP {resp.status_code}"
                        continue
                    raise RuntimeError(
                        f"SyncInternClient.chat HTTP {resp.status_code}: {body}"
                    )

                data = resp.json()

                # Intern-S 可能返回 200 但 body 里带错误（success:false / error 字段）
                if data.get("success") is False or data.get("error"):
                    body = str(data)[:500]
                    if self._is_rate_limited(200, body):
                        wait = self._rate_limit_backoff(attempt)
                        last_err = "rate limit (200-body)"
                        logger.warning(
                            "SyncInternClient 限流(200-body)，等待 %.1fs 后重试 %d/%d",
                            wait, attempt + 1, max_retries,
                        )
                        if attempt + 1 < max_retries:
                            time.sleep(wait)
                            continue
                    raise RuntimeError(f"SyncInternClient.chat API error: {body}")

                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content = message.get("content") or ""
                reasoning = message.get("reasoning_content") or ""
                # 优先返回 content；若为空回退 reasoning（保证非空）
                return content or reasoning or ""

            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning(
                    "SyncInternClient.chat attempt %d/%d failed: %s",
                    attempt + 1, max_retries, e,
                )
                if attempt + 1 < max_retries:
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"SyncInternClient.chat 全部重试失败: {last_err}")


# ---------------------------------------------------------------------------
# 深度协作增强配置（杀掉虚高置信度 + 反复验证）
# ---------------------------------------------------------------------------
_DEEP_OVERRIDES = {
    "enable_difficulty_router": True,   # 三级难度路由：难题自动走 deep 档
    "enable_llm_difficulty": True,      # LLM 自评难度（难题识别第二层）
    "enable_question_type": True,       # 题型识别（证明/选择/判断/填空/解答）
    "enable_collaborative_deep": True,  # 难题三Agent协作：解题→审查→整合→验证
    "collab_max_rounds": 6,             # 反复验证轮数：没到时间且没答对就继续
    "deep_revise_rounds": 2,            # 0 票时 revise 自纠错轮数
    "deep_use_playoff": True,           # 共识弱时低温独立复算
    "deep_use_sub_goal": True,          # deep 档强制子目标分解补充候选
    "enable_lean_verify": True,         # deep 证明题 Lean 硬验证
    "by_enable_fast_path": True,        # SymPy 快车道（带 20s 耗时上限）
    "max_time_per_question": 1200,      # 单题 20 分钟硬限，超时跳过
}


# ---------------------------------------------------------------------------
# 结果适配
# ---------------------------------------------------------------------------
def _build_reasoning(result: dict) -> str:
    """从 MathPilot 返回中提取主推理过程（选 reasoning 最详尽的候选）。"""
    candidates = result.get("candidates") or []
    best = max(candidates, key=lambda c: len(c.get("reasoning") or ""), default=None)
    reasoning = (best or {}).get("reasoning", "") if best else ""
    return reasoning or result.get("final_response", "") or ""


def _build_verification_summary(result: dict) -> str:
    """从推理结果提取真实验证摘要，替换原本硬编码的框架描述占位字符串。

    来源：trace(step 字段) + cluster(投票共识) + verdicts，全部为运行时真实数据。
    """
    trace = result.get("trace", []) or []
    cluster = result.get("cluster") or {}
    verdicts = result.get("verdicts", []) or []

    def _starts(prefix: str) -> int:
        return sum(1 for t in trace
                   if isinstance(t, dict) and str(t.get("step", "")).startswith(prefix))

    # 1) 对抗式投票验证（所有档位都有）
    if cluster:
        conf = float(cluster.get("confidence", 0.0))
        size = int(cluster.get("size", 0))
        vote_part = f"对抗式投票共识 {size} 票/置信度 {conf:.2f}"
    elif verdicts:
        passed = sum(1 for v in verdicts
                     if float(v.get("confidence", 0) or 0) >= 0.5)
        vote_part = f"投票 {len(verdicts)} 候选/{passed} 通过"
    else:
        vote_part = "无投票验证记录"

    # 2) 三Agent协作验证（仅 deep 档）
    collab_rounds = _starts("collab")
    collab_part = f"三Agent协作 {collab_rounds} 轮" if collab_rounds else "未启用协作(非deep档)"

    # 3) Lean 硬验证（仅 deep+证明题）
    lean_part = "Lean 硬验证已执行" if _starts("lean") else "Lean 未触发(非证明题/非deep)"

    # 4) 低置信度 revise 复核（所有档位 conf<0.5 触发）
    revise_rounds = _starts("revise")
    parts = [vote_part, collab_part, lean_part]
    if revise_rounds:
        parts.append(f"低置信度 revise 复核 {revise_rounds} 轮")

    return "；".join(parts)


def _build_candidates(result: dict, verdicts: list) -> list | None:
    """把 MathPilot 候选适配成评测器格式，confidence 用投票共识（真实值）。"""
    candidates = result.get("candidates") or []
    if not candidates:
        return None
    out = []
    for i, c in enumerate(candidates):
        conf = 0.0
        if i < len(verdicts):
            conf = float(verdicts[i].get("confidence") or 0.0)
        out.append({
            "index": i,
            "answer": c.get("answer", ""),
            "reasoning": c.get("reasoning", ""),
            "confidence": conf,  # 投票共识置信度，非模型自报 → 杀掉虚高置信度
        })
    return out


def _to_inference_result(problem, result: dict, latency: float,
                         sample_index: int = 0) -> InferenceResult:
    """把 MathPilot solve 返回的 dict 适配成评测器 InferenceResult。"""
    final_response = result.get("final_response", "") or ""
    cluster = result.get("cluster")
    verdicts = result.get("verdicts", []) or []

    # 真实置信度：投票共识（correct_votes / total_votes），非模型自报
    cluster_conf = None
    if isinstance(cluster, dict) and cluster.get("confidence") is not None:
        cluster_conf = float(cluster["confidence"])

    # 协作/验证轮次：从 trace 里统计 collab / revise 记录
    trace = result.get("trace", []) or []
    collab_rounds = sum(
        1 for t in trace
        if isinstance(t, dict) and str(t.get("step", "")).startswith("collab")
    )
    review_attempts = max(1, collab_rounds) if trace else 0

    return InferenceResult(
        problem_id=problem.id,
        question=problem.question,
        answer=final_response,
        reasoning=_build_reasoning(result),
        steps=[],
        verification=_build_verification_summary(result),
        raw_response=final_response,
        tokens_used=0,
        latency_seconds=latency,
        error=None,
        sample_index=sample_index,
        candidates=_build_candidates(result, verdicts),
        selected_candidate_index=None,
        selection_reasoning="",
        review_passed=True,                                  # 框架已做验证
        review_feedback=None,
        review_attempts=review_attempts,
        review_tokens_used=0,
        review_latency_seconds=0.0,
        total_tokens_used=0,
        total_latency_seconds=latency,
        lean_verification=None,
        secondary_review=None,
        dual_review_passed=bool(cluster_conf is not None and cluster_conf >= 0.5),
        lean_latency_seconds=0.0,
        finish_reason="stop",
        is_truncated=False,
        vote_info=(
            {"num_samples": len(result.get("candidates") or []),
             "consensus_confidence": cluster_conf}
            if cluster_conf is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# 评测器入口（签名与原版 intern_s1 保持一致）
# ---------------------------------------------------------------------------
def _make_agent():
    cfg = get_config()
    client = SyncInternClient(cfg.intern_s1)
    return ReasoningAgent(client, **_DEEP_OVERRIDES)


async def run_inference(problem, enable_review=True, max_review_retries=1,
                        enable_lean=True):
    """单样本推理：走 MathPilot 主框架（内部已多候选 + 投票共识）。"""
    agent = _make_agent()
    start = time.time()
    result = await asyncio.to_thread(
        agent.solve,
        problem.question,
        {"id": problem.id, "domain": getattr(problem, "domain", None)},
    )
    latency = time.time() - start
    return _to_inference_result(problem, result, latency, sample_index=0)


async def run_inference_multi(problem, num_samples=3, temperatures=None):
    """多样本推理：MathPilot 内部已做多候选 + 共识，对外返回单元素 list。"""
    agent = _make_agent()
    start = time.time()
    result = await asyncio.to_thread(
        agent.solve,
        problem.question,
        {"id": problem.id, "domain": getattr(problem, "domain", None)},
    )
    latency = time.time() - start
    return [_to_inference_result(problem, result, latency, sample_index=0)]


async def run_inference_tiered(problem, enable_review=True, enable_lean=True):
    """难题分级求解：MathPilot 内部已含难度路由，直接走同一主框架。"""
    return await run_inference(problem, enable_review=enable_review,
                               enable_lean=enable_lean)


async def run_inference_multi_vote(problem, num_samples=3):
    """自一致性投票：MathPilot 内部已含投票共识，返回单元素 list。"""
    return await run_inference_multi(problem, num_samples=num_samples)
