"""
LLM 客户端 - OpenAI 兼容的异步 HTTP 客户端。
支持自动重试、超时控制和 JSON 提取。
"""
import json
import logging
import asyncio
import re
from typing import Optional

import httpx

from config import LLMConfig

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """LLM 客户端通用异常"""
    pass


class APITimeoutError(LLMClientError):
    """API 请求超时异常"""
    pass


class APIResponseError(LLMClientError):
    """API 响应错误异常"""
    pass


class LLMClient:
    """OpenAI 兼容的异步 LLM 客户端，封装 chat 请求、重试和错误处理"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> dict:
        """发送聊天请求到 LLM API，返回包含 content、tokens_used、finish_reason 的字典"""
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        # 指数退避重试：每次重试等待 2^attempt 秒
        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as c:
                    resp = await c.post(self._url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    return {
                        "content": choice["message"]["content"],
                        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
                        "finish_reason": choice.get("finish_reason", "unknown"),
                    }
            except httpx.TimeoutException as e:
                last_error = APITimeoutError(str(e))
                logger.warning(str(last_error))
            except httpx.HTTPStatusError as e:
                last_error = APIResponseError(f"HTTP {e.response.status_code}")
                logger.warning(str(last_error))
                # 4xx 客户端错误不重试，直接抛出
                if 400 <= e.response.status_code < 500:
                    raise last_error
            except Exception as e:
                last_error = LLMClientError(str(e))
                logger.warning(str(last_error))
            # 指数退避延迟
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        raise last_error or LLMClientError("unknown error")


def extract_json_from_text(text: str) -> Optional[dict]:
    """从 LLM 响应文本中提取 JSON 对象，使用三级回退策略"""
    text = text.strip()

    # 第一级：直接解析整个文本为 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第二级：从 markdown 代码块中提取 JSON（```json ... ``` 或 ``` ... ```）
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 第三级：通过括号匹配，找到文本中第一个完整的 JSON 对象
    i = text.find("{")
    if i == -1:
        return None
    d = 0  # 括号嵌套深度计数器
    for j in range(i, len(text)):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:  # 找到匹配的闭合括号
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    return None
    return None
