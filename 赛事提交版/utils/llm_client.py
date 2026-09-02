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
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("MathPilot.LLMClient")

_DEFAULT_TIMEOUT = 240  # 秒（2026-09-02：120→240。蓝图 DAG 生成 max_tokens=6144，
                        # Intern-S2-397B 服务端生成慢时 >120s，3 次重试链烧 360s+
                        # 直接耗尽单题 standard 档预算 → 子目标全 budget_skip → 占位符）
_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0

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
    ) -> str:
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

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    stream=stream,
                )
                if resp.status_code == 200:
                    if stream:
                        content = _consume_stream(resp, logger, self.model, max_tokens)
                        return content
                    data = resp.json()
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

            except requests.exceptions.Timeout:
                last_error = f"Request timeout after {self.timeout}s"
                logger.warning("LLM chat timeout (attempt %d/%d)", attempt + 1, self.max_retries + 1)
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning("LLM chat connection error: %s", e)
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.warning("LLM chat unexpected error: %s", e)

            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** attempt)
                logger.debug("Retrying in %.1fs...", wait)
                time.sleep(wait)

        raise LLMError(f"LLM call failed after {self.max_retries + 1} attempts: {last_error}")

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
