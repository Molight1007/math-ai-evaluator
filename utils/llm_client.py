from __future__ import annotations
"""
轻量级 OpenAI 兼容 LLM 客户端
==============================

用于本地测试时连接任意兼容 OpenAI Chat Completions API 的 LLM 服务。
支撑 ReasoningAgent 调用链：BaseAgent.llm() → client.chat()。

配置方式（优先级从高到低）：
1. 直接传参: LLMClient(api_key=..., base_url=..., model=...)
2. 环境变量: OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL
3. 默认: http://localhost:8000/v1, gpt-3.5-turbo

修改影响:
- 修改 LLMClient.__init__ 签名时需同步检查: agent/orchestrator.py, user_agent.py, test_quick.py
- 修改 chat() 返回值格式时需同步检查: agent/base.py (BaseAgent.llm() 调用者)
- 被 agent/ 目录下所有 BaseAgent 子类通过 BaseAgent.llm() 间接引用
"""

import json
import logging
import os
import random
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("MathPilot.LLMClient")

_DEFAULT_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))  # 秒
# 2026-09-13 晚（4 题实测复盘）：超时后**重试**才是真正的成本黑洞。
# 实测 4 题里 `failed after 2 attempts` 出现 5 次、5/5 全败，而单次故障 =
# 180s × 2 + 退避 ≈ **365s** —— 010/016 两题各被两轮 365s 烧光整题预算，
# 最终连答案都没生成（`predicted` 退化成 `[生成失败] 调用受限或模型拒绝回答`）。
# ⇒ 两处收紧：
#   ① 读超时 180 → 120（`LLM_TIMEOUT` 可覆盖；实测正常调用 1–3s，长推理留 120s 富余）
#   ② 超时类故障**默认不重试**（`LLM_RETRY_ON_TIMEOUT=1` 可恢复旧行为）——
#      "拿同样的请求再赌一次"，实测 5/5 全败，纯亏 timeout 秒。
# 单次故障成本：365s → 120s。
_RETRY_ON_TIMEOUT = os.getenv("LLM_RETRY_ON_TIMEOUT", "0") == "1"
_CONNECT_TIMEOUT = 30  # 秒（2026-09-03：45→30。connect/TLS 握手黑洞探测更快）
_MAX_RETRIES = 1      # 2026-09-03：2→1。持续网络问题时 3 次重试纯浪费；
                       # 瞬时抖动 1 次重试足够，配合调用方 is_time_critical 兜底
                       # （⚠ 仅对非超时故障生效，见 `_RETRY_ON_TIMEOUT`）
_RETRY_BACKOFF = 2.0
# 2026-09-11 限流专项退避（依据 Bug清单_团队提交de90cedc_0911.md §5）：
# 服务端 `-20048 请求过于频繁` 实测 176 次，且 5 个 revise 候选并发发起 →
# 固定 2s 退避（实测两次失败间隔仅 2.1s）等于没有退避，且无抖动 → 自激放大。
# 限流单独给更大基数 + 抖动 + 上限；并发线程因此错峰，不再同步撞墙。
_RETRY_BACKOFF_RATE = 8.0   # 限流场景退避基数（秒）
_RETRY_BACKOFF_MAX = 24.0   # 单次退避上限（秒）
_RETRY_JITTER = 0.5         # 抖动比例：wait += U(0, wait*JITTER)
_RATE_LIMIT_MARKERS = ("-20048", "429", "too many requests", "请求过于频繁", "rate limit")

# ============================================================
# 真实截断信号（2026-09-01 SU-01 优化 0）
# ------------------------------------------------------------
# agent/base.py 已有启发式「疑似截断」埋点（resp_len >= max_tokens*0.95），
# 但服务端明确返回 finish_reason=length 才算**真实截断**。这里在
# 流式/非流式两条路径捕获真实 finish_reason，模块级统计 + listener 回调，
# 由调用方（agent/base.py）合并进截断日志，支撑截断率 <5% 健康阈值。
# 修改影响：chat() 返回值不变，纯增量。
# ============================================================
_TRUNCATION_STATS = {"calls": 0, "truncated": 0}
_TRUNCATION_STATS_LOCK = threading.Lock()
_TRUNCATION_LISTENER = None


def set_truncation_listener(fn) -> None:
    """注册截断回调 fn(model: str, max_tokens: Optional[int], finish_reason: str)。

    在每次响应结束且 finish_reason=="length" 时被调用；异常被吞掉，零行为影响。
    """
    global _TRUNCATION_LISTENER
    _TRUNCATION_LISTENER = fn


def get_truncation_stats() -> dict:
    """返回 {"calls": N, "truncated": M}（真实 finish_reason 口径，跨所有调用方累计）。"""
    with _TRUNCATION_STATS_LOCK:
        return dict(_TRUNCATION_STATS)


def _mark_response(model: str, finish_reason: Optional[str],
                   max_tokens: Optional[int]) -> None:
    """每次 LLM 响应结束计数一次；finish_reason=='length' 时计截断并通知 listener。"""
    with _TRUNCATION_STATS_LOCK:
        _TRUNCATION_STATS["calls"] += 1
    if finish_reason != "length":
        return
    with _TRUNCATION_STATS_LOCK:
        _TRUNCATION_STATS["truncated"] += 1
    logger.warning(
        "LLM response truncated (finish_reason=length, model=%s, max_tokens=%s)",
        model, max_tokens,
    )
    fn = _TRUNCATION_LISTENER
    if fn is not None:
        try:
            fn(model, max_tokens, finish_reason)
        except Exception:  # noqa: BLE001  listener 异常绝不外泄
            pass


class LLMError(Exception):
    """LLM 调用错误"""
    pass


class LLMClient:
    """OpenAI Chat Completions 兼容客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "not-needed")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1"))
        # 规范化 URL：去尾部 /，确保以 /v1 结尾
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.timeout = timeout
        self.max_retries = max_retries

    # ── 主接口：与 BaseAgent.llm() 签名兼容 ──
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        stream: bool = False,
        tools: Optional[list] = None,
    ):
        """
        2026-09-09：新增 tools 支持（原生工具调用试点）——透传 tools 到 API；
        模型返回 tool_calls 时返回完整 assistant 消息 dict（供工具循环读取），
        否则保持原文本返回（兼容既有调用方）。
        """
        """
        发送 chat completion 请求，返回模型回复文本。

        参数:
            messages: [{"role": "system", "content": "..."}, ...]
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            stream: 是否使用流式输出。流式模式下逐步累积直到服务端
                自然结束（finish_reason=stop），可避免 max_tokens 截断
                导致推理不完整。默认 False 保持兼容。

        返回:
            模型回复的纯文本

        异常:
            LLMError: 所有重试耗尽后仍然失败
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
        if tools is not None:
            payload["tools"] = tools

        last_error = None
        _tried = 0
        for attempt in range(self.max_retries + 1):
            _tried = attempt + 1
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(_CONNECT_TIMEOUT, self.timeout),
                    stream=stream,
                )
                if resp.status_code == 200:
                    if stream:
                        content = _consume_stream(resp, logger, self.model, max_tokens)
                        return content
                    data = resp.json()
                    # 2026-09-09：模型请求工具调用 → 返回完整 assistant 消息
                    # （含 tool_calls），由调用方工具循环读取；普通回答仍取文本
                    try:
                        _msg = (data.get("choices") or [{}])[0].get("message") or {}
                        if "tool_calls" in _msg and _msg["tool_calls"]:
                            return {
                                "role": "assistant",
                                "content": _msg.get("content") or "",
                                "tool_calls": _msg["tool_calls"],
                            }
                    except Exception:  # noqa: BLE001
                        pass
                    content = _extract_content(data)
                    # 真实截断信号：非流式响应的 finish_reason（部分代理可能缺失）
                    fr = None
                    try:
                        choices = data.get("choices") or []
                        if choices and isinstance(choices[0], dict):
                            fr = choices[0].get("finish_reason")
                    except Exception:  # noqa: BLE001
                        fr = None
                    _mark_response(self.model, fr, max_tokens)
                    logger.debug(
                        "LLM chat OK [model=%s, tokens=%s, len=%d]",
                        self.model,
                        data.get("usage", {}).get("total_tokens", "?"),
                        len(content),
                    )
                    return content

                # 非 200：记录错误并重试
                last_error = (
                    f"HTTP {resp.status_code}: {resp.text[:300]}"
                )
                logger.warning(
                    "LLM chat attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries + 1, last_error,
                )

            except requests.exceptions.Timeout as e:
                last_error = f"Request timeout after {self.timeout}s"
                logger.warning("LLM chat timeout (attempt %d/%d)", attempt + 1, self.max_retries + 1)
                # 2026-09-13：**读超时**默认不重试。服务端挂住时重试是"同样的请求
                # 再赌一次"——实测 5/5 全败，每次白烧 self.timeout 秒，直接把单题
                # 预算烧穿（365s/次）。调用方（solver/orchestrator/formatter）已有
                # 各自的降级与兜底路径，交给它们比在这里重试更划算。
                # ⚠ 必须排除 `ConnectTimeout`：它同时继承 `ConnectionError` 与 `Timeout`
                # （`except Timeout` 在前会先命中它），而**连接**超时走的是 30s 的
                # `_CONNECT_TIMEOUT`、失败很快，重试仍有正收益（探测服务端抖动）。
                # 只有**读**超时（`self.timeout`，即 120s 那种）才值得放弃重试。
                if (not _RETRY_ON_TIMEOUT
                        and not isinstance(e, requests.exceptions.ConnectTimeout)):
                    break
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning("LLM chat connection error: %s", e)
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.warning("LLM chat unexpected error: %s", e)

            if attempt < self.max_retries:
                # 2026-09-11 修正三处缺陷：
                #  ① 原判据 `attempt < _MAX_RETRIES` 用的是**模块常量**而非
                #     `self.max_retries` → 调用方传非默认 max_retries 时
                #     "重试循环次数"与"退避守卫"不一致（潜伏 bug）。
                #  ② 限流（-20048）未单独识别 → 固定 2s 退避对服务端节流无效。
                #  ③ 无抖动 → 并发候选同步重试，放大限流。
                _low = (last_error or "").lower()
                _is_rate = any(mk in _low for mk in _RATE_LIMIT_MARKERS)
                base = _RETRY_BACKOFF_RATE if _is_rate else _RETRY_BACKOFF
                wait = min(base * (2 ** attempt), _RETRY_BACKOFF_MAX)
                wait += random.uniform(0.0, wait * _RETRY_JITTER)
                logger.warning(
                    "LLM chat 重试 %d/%d（%s，退避 %.1fs）: %s",
                    attempt + 1, self.max_retries,
                    "限流" if _is_rate else "故障", wait, (last_error or "")[:160],
                )
                time.sleep(wait)

        # 实际尝试次数而非 max_retries+1：超时短路（break）时两者不等，
        # 报真实次数才能让日志/归因不被误导（旧写法会让"只试了 1 次"显示成 2 次）。
        raise LLMError(f"LLM call failed after {_tried} attempts: {last_error}")

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model}, base_url={self.base_url})"


def _consume_stream(resp, logger, model: str, max_tokens: Optional[int] = None) -> str:
    """消费 SSE 流式响应，累积 content + reasoning_content 直到 [DONE] 或结束。

    返回与 chat() 一致的纯文本：优先拼接 content；若 content 为空（纯推理模型
    如 DeepSeek-R1/Intern-S1 的推理全部在 reasoning_content），则回退拼接
    reasoning_content。这样调用方无需区分两种通道。

    结束时上报真实 finish_reason（截断信号）。
    """
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = None
    chunk_count = 0

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        choices = obj.get("choices", [])
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta", {}) or {}
        text = delta.get("content")
        if text:
            content_parts.append(str(text))
        reason = delta.get("reasoning_content")
        if reason:
            reasoning_parts.append(str(reason))
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        chunk_count += 1

    content = "".join(content_parts)
    if content:
        text_out = content
    else:
        text_out = "".join(reasoning_parts)
    # 真实截断信号：流式路径的 finish_reason
    _mark_response(model, finish_reason, max_tokens)
    logger.debug(
        "LLM stream OK [model=%s, chunks=%d, finish=%s, content=%d, reasoning=%d]",
        model, chunk_count, finish_reason, len(content), len("".join(reasoning_parts)),
    )
    return text_out


def _extract_content(data: dict) -> str:
    """从 OpenAI 格式响应中提取文本内容"""
    choices = data.get("choices", [])
    if not choices:
        # 部分代理返回格式不同
        if "response" in data:
            return str(data["response"])
        raise LLMError(f"No choices in response: {json.dumps(data, ensure_ascii=False)[:200]}")
    choice = choices[0]
    # 标准 OpenAI 格式
    message = choice.get("message", {})
    content = message.get("content", "")
    if content:
        return str(content)
    # DeepSeek-R1/V4 等推理模型: 优先 reasoning_content (含完整思考链)
    reasoning = message.get("reasoning_content", "")
    if reasoning:
        return str(reasoning)
    # 部分代理使用 text 字段
    text = choice.get("text", "")
    if text:
        return str(text)
    raise LLMError(f"Empty content in response: {json.dumps(choice, ensure_ascii=False)[:200]}")


# ── 模块自检 ──
def _self_test() -> str:
    """简单的连通性测试，供首次使用时验证配置"""
    client = LLMClient()
    return client.chat(
        messages=[{"role": "user", "content": "Say 'ok' in JSON: {\"status\":\"ok\"}"}],
        temperature=0.0,
        max_tokens=32,
    )
