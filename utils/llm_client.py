
"""
LLM 客户端（仅供 run_eval.py 本地评测使用）
比赛平台会注入自己的 client，此文件不影响平台运行。
"""

import json
import time
import requests


class LLMClient:
    """简单的 OpenAI 兼容客户端，用于本地评测。"""

    def __init__(self, api_key: str | None = None,
                 base_url: str | None = None,
                 model: str | None = None,
                 timeout: int = 600):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model or "gpt-4o"
        self.timeout = timeout

        self._headers = {"Content-Type": "application/json"}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

    def call(self, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 4096, **kwargs) -> str:
        """
        同步调用（比赛平台使用异步 client，本地评测用同步兜底）。
        比赛平台的 client.call 返回单个 str，此处保持一致。
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        retries = 3
        last_error = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    url, headers=self._headers,
                    json=payload, timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用失败（{retries} 次重试后）: {last_error}")

    def chat(self, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 4096, **kwargs) -> str:
        """agent 层统一以 client.chat(messages, temperature, max_tokens) 调用。

        平台 client 提供 chat 接口；本地评测客户端补齐同名方法以对齐。
        """
        return self.call(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
