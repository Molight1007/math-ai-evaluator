# -*- coding: utf-8 -*-
"""LLM 客户端。

只依赖标准库（urllib），避免在用户环境里装包。

三个关键点：
1. **推理模型兼容**：DeepSeek 这类推理模型把思维链放在 `reasoning_content`，
   正文在 `content`；且 max_tokens 给少了会 `finish_reason=length` 被截断，
   正文直接是空串。这里显式处理并暴露 `truncated` 标志。
2. **磁盘缓存**：同一 (model, messages, params) 只花一次钱，重跑实验可复现。
3. **dry-run**：不联网，返回固定样例，用于纯跑通管线。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import config

# dry-run 用的固定返回：恰好是 A1 源题的正解，便于冒烟时把 Lean 判据也跑通
MOCK_CONTENT = """思路：把不等式移项后配成完全平方。

```lean
import Mathlib.Tactic

example (a b : ℝ) : (a + b)^2 ≥ 4 * a * b := by
  nlinarith [sq_nonneg (a - b)]
```

答案：恒成立。
"""

MOCK_REASONING = "（dry-run 模式，未真实调用模型）"


@dataclass
class Reply:
    """一次对话结果。"""

    content: str = ""
    reasoning: str = ""
    finish_reason: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    error: str = ""
    cached: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.content.strip())


class LLMClient:
    """OpenAI Chat Completions 兼容客户端。"""

    def __init__(
        self,
        model_key: str | None = None,
        dry_run: bool = False,
        use_cache: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        config.load_main_env()
        self.model_key = model_key or config.DEFAULT_MODEL
        if self.model_key not in config.MODELS:
            raise KeyError(
                f"未知模型 {self.model_key!r}，可选：{list(config.MODELS)}"
            )
        self.spec = config.MODELS[self.model_key]
        self.dry_run = dry_run
        self.use_cache = use_cache
        self.max_tokens = max_tokens or int(self.spec["max_tokens"])
        self.temperature = (
            self.spec["temperature"] if temperature is None else temperature
        )
        self._cache_dir = config.CACHE_DIR / "llm"
        if use_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 公开
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        tag: str = "",
    ) -> Reply:
        """发一轮对话。messages 为 [{"role":..., "content":...}] 列表。"""
        mt = max_tokens or self.max_tokens
        tp = self.temperature if temperature is None else temperature

        if self.dry_run:
            return Reply(
                content=MOCK_CONTENT,
                reasoning=MOCK_REASONING,
                finish_reason="stop",
                model=f"dry-run/{self.model_key}",
            )

        payload: dict[str, Any] = {
            "model": self.spec["model"],
            "messages": messages,
            "max_tokens": mt,
            "temperature": tp,
            "stream": False,
        }

        cache_key = self._hash(payload)
        cached = self._cache_get(cache_key)
        if cached is not None:
            rep = Reply(**cached)
            rep.cached = True
            return rep

        url = self.spec["base_url"].rstrip("/") + "/chat/completions"
        api_key = os.environ.get(self.spec["api_key_env"], "")
        if not api_key:
            return Reply(
                model=self.spec["model"],
                error=f"缺少环境变量 {self.spec['api_key_env']}（主项目 .env 已只读加载，"
                f"确认该 key 是否仍有效）",
            )

        last_err = ""
        for attempt in range(1, config.MAX_RETRY + 1):
            try:
                raw = self._post(url, api_key, payload)
                break
            except Exception as exc:  # 网络/5xx/429 → 退避重试
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt >= config.MAX_RETRY:
                    return Reply(model=self.spec["model"], error=last_err)
                time.sleep(config.RETRY_SLEEP * attempt)
        else:  # pragma: no cover
            return Reply(model=self.spec["model"], error=last_err or "未知错误")

        rep = self._parse(raw)
        if rep.error and "retry" not in rep.error:
            # JSON 结构异常不重试（重试也还是异常），直接返回
            return rep
        self._cache_set(cache_key, rep)
        return rep

    def ask(self, prompt: str, system: str = "", **kw) -> Reply:
        """便捷方法：单轮提问。"""
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return self.chat(msgs, **kw)

    # ------------------------------------------------------------ 内部
    def _post(self, url: str, api_key: str, payload: dict) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            # 401/403/余额/过期类错误重试无意义，直接抛出带原因
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"返回非 JSON: {body[:300]}") from exc

    def _parse(self, raw: dict) -> Reply:
        try:
            choice = raw["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError):
            return Reply(
                model=self.spec["model"],
                error=f"响应结构异常: {str(raw)[:300]}",
            )

        # 业务层错误（如 Intern 的 "user token expired"）在此显式暴露
        if raw.get("success") is False:
            return Reply(
                model=self.spec["model"],
                error=f"API 返回失败: {raw.get('msg')} (code={raw.get('msgCode')})",
            )

        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        finish = choice.get("finish_reason", "") or ""
        truncated = finish == "length"

        # 推理模型被截断时正文可能为空：退而用思维链尾部，保证下游有东西可判
        if not content.strip() and reasoning.strip():
            content = reasoning[-4000:]
        elif truncated and not content.strip():
            content = ""

        return Reply(
            content=content,
            reasoning=reasoning,
            finish_reason=finish,
            model=raw.get("model", self.spec["model"]),
            usage=raw.get("usage", {}) or {},
            truncated=truncated,
        )

    # ------------------------------------------------------------ 缓存
    def _hash(self, payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str):
        return self._cache_dir / f"{key}.json"

    def _cache_get(self, key: str) -> dict | None:
        if not self.use_cache:
            return None
        p = self._cache_path(key)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _cache_set(self, key: str, rep: Reply) -> None:
        if not self.use_cache:
            return
        data = {
            "content": rep.content,
            "reasoning": rep.reasoning,
            "finish_reason": rep.finish_reason,
            "model": rep.model,
            "usage": rep.usage,
            "truncated": rep.truncated,
            "error": rep.error,
        }
        try:
            self._cache_path(key).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass
