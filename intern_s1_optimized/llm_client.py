"""
LLM 客户端 - OpenAI 兼容的异步 HTTP 客户端。
支持自动重试（指数退避）、超时控制和三级 JSON 提取。
"""
import asyncio
import json
import logging
import re
from typing import Optional

import httpx

from .config import LLMConfig

logger = logging.getLogger(__name__)

# 指数退避初始等待时间（秒）
_RETRY_BASE_DELAY = 1


class LLMClientError(Exception):
    """LLM 客户端通用异常，所有 LLM 相关错误的基类"""
    pass


class APITimeoutError(LLMClientError):
    """API 请求超时异常"""
    pass


class APIResponseError(LLMClientError):
    """API 响应错误异常（HTTP 非 2xx）"""
    pass


class LLMClient:
    """
    OpenAI 兼容的异步 LLM 客户端。

    封装 chat 请求的发送、重试和错误处理。
    支持指数退避重试（最多 config.max_retries 次），
    对 4xx 客户端错误不重试直接抛出。
    """

    def __init__(self, config: LLMConfig):
        """
        初始化 LLM 客户端。

        参数:
            config: LLMConfig 配置对象（含 api_key, base_url, model 等）
        """
        self.config = config
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> dict:
        """
        发送聊天请求到 LLM API。

        使用指数退避重试策略处理网络错误和服务端错误（5xx），
        对于客户端错误（4xx）直接抛出异常，因为重试无意义。

        参数:
            messages: 消息列表 [{"role": "...", "content": "..."}]
            temperature: 生成温度（0~2，默认 0.3）
            max_tokens: 最大输出 token 数（默认 4096）
            response_format: 可选的响应格式（如 {"type": "json_object"}）

        返回:
            {"content": str, "tokens_used": int, "finish_reason": str}

        异常:
            APITimeoutError: 请求超时
            APIResponseError: API 返回错误状态码
            LLMClientError: 其他 LLM 调用错误
        """
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
        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout
                ) as client:
                    resp = await client.post(
                        self._url, headers=headers, json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    return {
                        "content": choice["message"]["content"],
                        "tokens_used": data.get("usage", {}).get(
                            "total_tokens", 0
                        ),
                        "finish_reason": choice.get(
                            "finish_reason", "unknown"
                        ),
                    }
            except httpx.TimeoutException as e:
                last_error = APITimeoutError(str(e))
                logger.warning(str(last_error))
            except httpx.HTTPStatusError as e:
                last_error = APIResponseError(
                    f"HTTP {e.response.status_code}"
                )
                logger.warning(str(last_error))
                # 4xx 客户端错误不重试
                if 400 <= e.response.status_code < 500:
                    raise last_error
            except Exception as e:
                last_error = LLMClientError(str(e))
                logger.warning(str(last_error))

            # 指数退避延迟：2^attempt 秒
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** attempt))

        raise last_error or LLMClientError("unknown error")


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    从 LLM 响应文本中提取 JSON 对象，使用三级回退策略。

    策略：
    1. 直接尝试将整个文本解析为 JSON
    2. 从 markdown 代码块（```json ... ``` 或 ``` ... ```）中提取
    3. 通过括号匹配找到文本中第一个完整的 JSON 对象

    参数:
        text: LLM 返回的原始文本

    返回:
        解析后的 dict，无法提取时返回 None
    """
    text = text.strip()

    # 第一级：直接解析整个文本为 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第二级：从 markdown 代码块中提取 JSON
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 第三级：括号匹配找到第一个完整的 JSON 对象
    start_idx = text.find("{")
    if start_idx == -1:
        return None

    depth = 0  # 括号嵌套深度
    for j in range(start_idx, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start_idx:j + 1])
                except json.JSONDecodeError:
                    return None
    return None
