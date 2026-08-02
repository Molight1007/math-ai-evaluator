import json
import os
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Union

import requests


DEFAULT_API_BASE = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
DEFAULT_MODEL = "intern-s2-preview"


def _strip_thinking_process(text: str) -> str:
    """去除 Intern-S 模型的思维流（Thinking Process）前缀，提取实际输出。
    
    Intern-S 的 content 格式为：
        Thinking Process:
        1.  **Analyze the Request:** ...
        ...
        N.  **Final Decision:** CORRECT
        
        CORRECT
    
    实际答案/判决在思维流之后的最末尾位置。
    """
    if not text or not isinstance(text, str):
        return text
    
    # 检测是否以思维流开头
    if not re.search(r'(?:Thinking Process|Thought Process|Let me think|Let\'s think)', text[:200]):
        return text
    
    # 策略1: 提取 "Final Decision: CORRECT" / "Final Decision: INCORRECT"
    fd_match = re.search(
        r'(?:Final|最终)\s*(?:Decision|决策|结论|Answer|答案)[：:]\s*\*?\*?\s*(CORRECT|INCORRECT|TRUE|FALSE|VALID|INVALID|正确|错误)',
        text, re.IGNORECASE,
    )
    if fd_match:
        return fd_match.group(1).upper()
    
    # 策略2: 提取 "CORRECT" / "INCORRECT" 的最后一个独立出现
    verdict_match = re.findall(r'\b(CORRECT|INCORRECT)\b', text)
    if verdict_match:
        return verdict_match[-1].upper()
    
    # 策略3: 提取思维流之后的尾部内容（跳过步骤编号行和 bullet points）
    lines = text.strip().split('\n')
    tail_lines = []
    found_step = False
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            if tail_lines:
                continue
            else:
                continue
        # 跳过步骤标题: "N.  **Title:**"
        if re.match(r'^\d+\.?\s*\*\*', stripped):
            if tail_lines:
                break  # 步骤标题出现在结果内容之上，停止
            continue
        # 跳过 bullet points
        if re.match(r'^\s*\*', stripped) and not re.search(r'[\d=]', stripped):
            continue
        # 跳过最终决策行（已处理）
        if re.match(r'.*(?:Final|最终)\s*(?:Decision|决策|结论)', stripped, re.IGNORECASE):
            continue
        tail_lines.append(stripped)
    
    if tail_lines:
        result = '\n'.join(reversed(tail_lines))
        if len(result.strip()) > 0:
            return result.strip()
    
    return text
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096

ChatMessage = Dict[str, Any]
ChatResponse = Union[str, ChatMessage]


class InternChatClient:
    """Small OpenAI-compatible chat client for the competition sample."""

    def __init__(
        self,
        timeout: int = 120,
        retry: int = 3,
        default_args: Optional[Mapping[str, Any]] = None,
        **request_args: Any,
    ) -> None:
        raw_api_key = os.environ.get("INTERN_API_KEY")
        if not raw_api_key:
            raise RuntimeError("Missing API key. Set INTERN_API_KEY.")
        self.authorization = (
            raw_api_key if raw_api_key.startswith("Bearer ") else f"Bearer {raw_api_key}"
        )
        self.api_base = os.environ.get("INTERN_API_BASE", DEFAULT_API_BASE)
        self.model = os.environ.get("INTERN_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.retry = retry
        self.default_args = dict(default_args or {})
        self.default_args.update(request_args)

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        thinking_mode: Optional[bool] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **request_args: Any,
    ) -> ChatResponse:
        """Create a chat completion.

        Extra request arguments are passed through to the HTTP API. Arguments
        supplied to ``chat`` override client-wide ``default_args``.

        Text completions are returned as strings for backwards compatibility.
        When the model requests a tool call, the complete assistant message is
        returned so that callers can read ``tool_calls`` and append the message
        to the next request.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        payload.update(self.default_args)
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if thinking_mode is not None:
            payload["thinking_mode"] = thinking_mode
        if tools is not None:
            payload["tools"] = tools
        payload.update(request_args)
        # ``messages`` is the only required per-call argument and must not be
        # replaced accidentally by client-wide defaults.
        payload["messages"] = messages

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.authorization,
        }

        last_error = None
        for attempt in range(self.retry):
            try:
                response = requests.post(
                    self.api_base,
                    headers=headers,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                if "tool_calls" in message:
                    return message
                # Intern-S 模型可能将 CoT 放在 reasoning_content，content 可能为空
                reasoning = message.get("reasoning_content", "") or ""
                content = message.get("content", "") or ""
                # 不再全局剥离思维流——solver 需要完整的推理链，
                # verifier 的 _is_correct_vote 自己解析 VERDICT
                if reasoning and content:
                    return reasoning + "\n" + content
                return content or reasoning or ""
            except Exception as exc:  # noqa: BLE001 - keep sample robust and simple.
                last_error = exc
                if attempt + 1 < self.retry:
                    time.sleep(2**attempt)

        raise RuntimeError(f"Chat completion failed after {self.retry} attempts: {last_error}")
