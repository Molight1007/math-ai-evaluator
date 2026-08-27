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

from config import LLMConfig

logger = logging.getLogger(__name__)

# 指数退避初始等待时间（秒）
_RETRY_BASE_DELAY = 1


def _detect_content_truncation(content: str) -> bool:
    """
    检测 LLM 返回内容是否在 JSON 或 markdown 代码块中不完整。

    判断依据：
    1. 对以 { 开头的内容做括号深度检测，深度未归零说明被截断。
    2. 若文本包含未闭合的 markdown 代码块（``` 未配对），也视为截断。
    3. 若文本中第一个 { 之后存在未闭合的 {，同样视为截断。
    非 JSON 开头且不含未闭合代码块的内容返回 False。

    参数:
        content: LLM 返回的文本内容

    返回:
        True 表示内容可能在 JSON 中间被截断
    """
    text = content.strip()

    # 检测未闭合的 markdown 代码块
    code_fence_count = text.count("```")
    if code_fence_count % 2 == 1:
        return True

    # 找到第一个 { 的位置，检测从该位置开始的括号深度
    first_brace = text.find("{")
    if first_brace == -1:
        return False

    depth = 0
    for ch in text[first_brace:]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth != 0


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
            {"content": str, "tokens_used": int, "finish_reason": str,
             "is_truncated": bool, "content_truncated": bool}

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
        # Intern-S2 系列模型（Intern-S2-Preview-397B 等）默认开启深度思考模式，
        # 会先输出大段 "Thinking Process:" 思考内容，导致 max_tokens 耗尽或请求超时，
        # 最终拿不到答案。显式关闭思考模式以获得直接可解析的输出。
        if "S2" in self.config.model or "s2" in self.config.model:
            payload["thinking_mode"] = False
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        # timeout <= 0 时视为 None（httpx 无限制），避免 API 调用被强制中断
        timeout = self.config.timeout if self.config.timeout > 0 else None
        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout
                ) as client:
                    resp = await client.post(
                        self._url, headers=headers, json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    finish_reason = choice.get("finish_reason", "unknown")
                    is_truncated = finish_reason == "length"
                    content_truncated = _detect_content_truncation(
                        content
                    )
                    return {
                        "content": content,
                        "tokens_used": data.get("usage", {}).get(
                            "total_tokens", 0
                        ),
                        "finish_reason": finish_reason,
                        "is_truncated": is_truncated,
                        "content_truncated": content_truncated,
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


def _sanitize_json_for_parsing(json_text: str) -> str:
    """
    预处理 JSON 文本，处理 LLM 返回中常见的格式问题。

    修复策略：
    1. 移除 BOM 头（\\uFEFF）
    2. 修复字符串值内未转义的真实换行符 → 转为 \\n
       （LLM 有时在 JSON 字符串值中输出真实的换行，导致 json.loads 失败）
    3. 修复尾部逗号（JSON 不允许尾随逗号）

    参数:
        json_text: 待预处理的 JSON 字符串

    返回:
        预处理后的 JSON 字符串
    """
    # 1. 移除 BOM
    if json_text.startswith("\uFEFF"):
        json_text = json_text[1:]

    # 2. 处理字符串值内的未转义换行符
    # 策略：识别 JSON 字符串字面量（被 "..." 包裹的部分），
    # 将其中的真实换行符转义为 \\n。
    # 使用状态机而非正则，正确处理嵌套转义字符。
    result = []
    in_string = False
    escape_next = False
    for ch in json_text:
        if escape_next:
            # 前一个字符是反斜杠，当前字符被转义，直接追加
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\" and in_string:
            # 进入转义状态
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            # 字符串边界切换
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch == "\n":
            # 字符串值内的真实换行 → 转义
            result.append("\\n")
            continue
        if in_string and ch == "\r":
            # 移除回车符
            continue
        if in_string and ch == "\t":
            # 保留制表符（合法）
            result.append("\\t")
            continue
        result.append(ch)

    sanitized = "".join(result)

    # 3. 修复尾部逗号（在 } 或 ] 前的逗号）
    sanitized = re.sub(r",(\s*[}\]])", r"\1", sanitized)

    return sanitized


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    从 LLM 响应文本中提取 JSON 对象，使用三级回退策略 + 预处理修复。

    策略：
    1. 直接尝试将整个文本解析为 JSON（含预处理修复）
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

    # 第一级修复：对整段文本做预处理后重试
    try:
        return json.loads(_sanitize_json_for_parsing(text))
    except json.JSONDecodeError:
        pass

    # 第二级：从 markdown 代码块中提取 JSON
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        block_text = match.group(1).strip()
        try:
            return json.loads(block_text)
        except json.JSONDecodeError:
            pass
        # 第二级修复：预处理后重试
        try:
            return json.loads(_sanitize_json_for_parsing(block_text))
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
                candidate = text[start_idx:j + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                # 第三级修复：预处理后重试
                try:
                    return json.loads(_sanitize_json_for_parsing(candidate))
                except json.JSONDecodeError:
                    return None
    return None
