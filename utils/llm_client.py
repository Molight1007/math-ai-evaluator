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

_DEFAULT_TIMEOUT = 120  # 秒
_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0

# 进程级请求节流：限制相邻请求最小间隔（秒），避免突发触发 API 限流
# （实测该 Intern API 对突发/并发请求返回 -20048"请求过于频繁"）
_MIN_REQUEST_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "5"))
_throttle_lock = threading.Lock()
_last_request_ts = [0.0]


def _throttle() -> None:
    """全局节流：所有 chat 请求经此串行化，保证请求间隔 ≥ LLM_MIN_INTERVAL。"""
    global _last_request_ts
    if _MIN_REQUEST_INTERVAL <= 0:
        return
    with _throttle_lock:
        now = time.time()
        wait = _MIN_REQUEST_INTERVAL - (now - _last_request_ts[0])
        if wait > 0:
            time.sleep(wait)
        _last_request_ts[0] = time.time()


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
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "not-needed")
        # 防御：空/仅空白 token 会构造出 `Authorization: Bearer `（空 Bearer 头），
        # 触发 `Illegal header value b'Bearer '`，导致推理/判题全部失败、无答案返回。
        if not self.api_key or not str(self.api_key).strip():
            raise LLMError(
                "LLM API Key 为空，无法发起请求。请在设置中配置 API Key "
                "(OPENAI_API_KEY 或直接传入 api_key)。"
            )
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1"))
        # 规范化 URL：去尾部 /，确保以 /v1 结尾
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        # 超时/重试可从环境变量覆盖（与 GUI 共用 ~/.math_evaluator/.env 的 LLM_TIMEOUT/LLM_MAX_RETRIES）
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "120"))
        self.max_retries = max_retries or int(os.getenv("LLM_MAX_RETRIES", "2"))
        # 备用端点故障转移（仅本地评测；平台 client 由官方注入，不涉及）：
        # 主端点重试耗尽后，改走备用端点 + 备用模型再试一轮，抵抗 API 偶发挂起。
        self.fallback_base_url = os.getenv("OPENAI_FALLBACK_BASE_URL", "").rstrip("/")
        self.fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "") or self.model

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
        # 端点优先级：主端点 → 备用端点（故障转移，各带完整重试）
        endpoints = [(self.base_url, self.model)]
        if self.fallback_base_url and self.fallback_base_url != self.base_url:
            endpoints.append((self.fallback_base_url, self.fallback_model))

        for url_idx, (endpoint, endpoint_model) in enumerate(endpoints):
            url = f"{endpoint}/chat/completions"
            payload["model"] = endpoint_model
            endpoint_label = "fallback" if url_idx > 0 else "primary"
            for attempt in range(self.max_retries + 1):
                _throttle()  # 全局节流：平缓请求节奏，规避突发限流
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
                            content = _consume_stream(resp, logger, endpoint_model)
                            return content
                        data = resp.json()
                        content = _extract_content(data)
                        logger.debug(
                            "LLM chat OK [model=%s, tokens=%s, len=%d]",
                            endpoint_model,
                            data.get("usage", {}).get("total_tokens", "?"),
                            len(content),
                        )
                        return content

                    # 非 200：记录错误并重试
                    last_error = (
                        f"HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                    logger.warning(
                        "LLM chat [%s] attempt %d/%d failed: %s",
                        endpoint_label, attempt + 1, self.max_retries + 1, last_error,
                    )

                except requests.exceptions.Timeout:
                    last_error = f"Request timeout after {self.timeout}s"
                    logger.warning(
                        "LLM chat [%s] timeout (attempt %d/%d)",
                        endpoint_label, attempt + 1, self.max_retries + 1,
                    )
                except requests.exceptions.ConnectionError as e:
                    last_error = f"Connection error: {e}"
                    logger.warning("LLM chat [%s] connection error: %s", endpoint_label, e)
                except Exception as e:
                    last_error = f"Unexpected error: {e}"
                    logger.warning("LLM chat [%s] unexpected error: %s", endpoint_label, e)

                # 限流感知退避：HTTP 429 或 -20048"请求过于频繁" → 睡 15s 再试，
                # 避免重试风暴进一步触发限流
                rate_limited = bool(last_error) and (
                    "429" in str(last_error) or "-20048" in str(last_error)
                    or "请求过于频繁" in str(last_error))
                if attempt < self.max_retries:
                    wait = 15.0 if rate_limited else _RETRY_BACKOFF * (2 ** attempt)
                    logger.warning(
                        "LLM chat [%s] %s，%.0fs 后重试 (attempt %d/%d)",
                        endpoint_label,
                        "触发限流" if rate_limited else "失败",
                        wait, attempt + 1, self.max_retries + 1,
                    )
                    time.sleep(wait)

        raise LLMError(
            f"LLM call failed after {len(endpoints)} endpoint(s) x "
            f"{self.max_retries + 1} attempts: {last_error}"
        )

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model}, base_url={self.base_url})"


def _consume_stream(resp, logger, model: str) -> str:
    """消费 SSE 流式响应，累积 content + reasoning_content 直到 [DONE] 或结束。

    返回与 chat() 一致的纯文本：优先拼接 content；若 content 为空（纯推理模型
    如 DeepSeek-R1/Intern-S1 的推理全部在 reasoning_content），则回退拼接
    reasoning_content。这样调用方无需区分两种通道。
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
