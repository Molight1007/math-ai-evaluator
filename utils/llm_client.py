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
"""

import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("MathPilot.LLMClient")

_DEFAULT_TIMEOUT = 120  # 秒
_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0


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
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "not-needed")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1"))
        # 规范化 URL：去尾部 /，确保以 /v1 结尾
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.timeout = timeout

    # ── 主接口：与 BaseAgent.llm() 签名兼容 ──
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """
        发送 chat completion 请求，返回模型回复文本。

        参数:
            messages: [{"role": "system", "content": "..."}, ...]
            temperature: 采样温度
            max_tokens: 最大生成 token 数

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

        last_error = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = _extract_content(data)
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
                    attempt + 1, _MAX_RETRIES + 1, last_error,
                )

            except requests.exceptions.Timeout:
                last_error = f"Request timeout after {self.timeout}s"
                logger.warning("LLM chat timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
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

        raise LLMError(f"LLM call failed after {_MAX_RETRIES + 1} attempts: {last_error}")

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model}, base_url={self.base_url})"


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
