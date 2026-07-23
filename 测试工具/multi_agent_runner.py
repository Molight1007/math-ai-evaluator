"""
多智能体版推理接入评测器（--multi-agent 开关）
==============================================

把 ``submit/user_agent.py`` 的 ``ReasoningAgent``（多智能体协作 + 推理自主调控）
接入 ``测试工具/main.py`` 的评测流水线，复用 DeepSeek 评判 / Lean 验证 / 报告。

接口错配处理
------------
- 评测器的 ``LLMClient.chat`` 是 **async** 且返回 dict ``{content, tokens_used}``；
  而 ``ReasoningAgent.solve`` 是 **sync** 且把 ``client.chat`` 返回值当 **字符串**。
- 本模块用 ``EvalSyncClient`` 包一层**同步** HTTP 客户端（语义对齐 ``LLMClient``），
  让多智能体代码零改动即可接入；并用 ``run_in_executor`` 维持评测器的并发语义。

注意：多智能体版内置 VerifierAgent 投票验证，故评测器自身的「自审核循环」
不再重复执行（InferenceResult.review_passed 置为 None，报告中按“未启用”统计）。
"""

import asyncio
import os
import sys
import time
from typing import List, Optional

import httpx

# 让项目根进入 sys.path，以 ``submit.user_agent`` 形式导入多智能体包。
# submit 下顶层名（agent / prompts / utils / user_agent）会与 测试工具 同名模块冲突，
# 故统一改用 submit.* 命名空间导入，避免遮蔽彼此。
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import get_config                                   # 测试工具/config.py
from llm_client import LLMClientError                           # 测试工具/llm_client.py
from models import InferenceResult, Problem                     # 测试工具/models.py

from submit.user_agent import ReasoningAgent                    # submit/user_agent.py


# ============================================================
# 同步 HTTP 客户端（对齐 LLMClient 的入参与重试语义，返回字符串）
# ============================================================
class EvalSyncClient:
    """同步包装：把 LLMClient 的 async+dict 接口转成 ReasoningAgent 需要的
    sync+str 接口。返回结果累计 ``total_tokens`` 供报告统计。"""

    def __init__(self, config):
        self.config = config
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"
        self.total_tokens = 0

    def chat(self, messages, temperature=0.3, max_tokens=4096):
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
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                with httpx.Client(timeout=self.config.timeout) as client:
                    resp = client.post(self._url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    self.total_tokens += int(
                        data.get("usage", {}).get("total_tokens", 0) or 0
                    )
                    return choice["message"]["content"] or ""
            except httpx.HTTPStatusError as e:
                last_error = e
                # 4xx 客户端错误不重试
                if 400 <= e.response.status_code < 500:
                    raise LLMClientError(f"HTTP {e.response.status_code}") from e
            except Exception as e:  # noqa: BLE001
                last_error = e
            # 指数退避
            if attempt < self.config.max_retries - 1:
                time.sleep(1 * (2 ** attempt))
        raise LLMClientError(str(last_error) if last_error else "unknown error")


# ============================================================
# 报告辅助
# ============================================================
def _format_trace(trace: List[dict]) -> str:
    """把 trace 转成可读的问题求解过程文本。"""
    lines = []
    for item in trace:
        if not isinstance(item, dict):
            continue
        agent = item.get("agent", "?")
        step = item.get("step", "")
        content = item.get("content", "")
        if isinstance(content, dict):
            content = str(content)
        content = (content or "").strip()
        if content:
            # 截断超长内容，避免报告爆炸
            if len(content) > 800:
                content = content[:800] + " …[截断]"
            lines.append(f"[{agent}/{step}] {content}")
    return "\n".join(lines)


def _format_verification(verdicts: List[dict]) -> str:
    """把投票验证结果转成文本。"""
    if not verdicts:
        return ""
    lines = []
    for v in verdicts:
        conf = v.get("confidence", 0.0)
        cv = v.get("correct_votes", 0)
        tv = v.get("total_votes", 0)
        lines.append(
            f"候选#{v.get('id')}: 置信度 {conf:.2f}（{cv}/{tv} 票判定正确）"
        )
    return "\n".join(lines)


# ============================================================
# 推理入口（签名对齐 intern_s1.run_inference / run_inference_multi）
# ============================================================
async def run_inference(
    problem: Problem,
    enable_review: bool = True,
    max_review_retries: int = 2,
) -> InferenceResult:
    """多智能体版单题推理（async，保持评测器并发语义）。"""
    cfg = get_config()
    client = EvalSyncClient(cfg.intern_s1)
    agent = ReasoningAgent(client)
    metadata = {
        "idx": getattr(problem, "id", 0),
        "domain": getattr(problem, "domain", "") or "",
    }
    loop = asyncio.get_running_loop()
    start = time.time()
    try:
        # ReasoningAgent.solve 为同步调用，放进线程池以保持异步并发
        result = await loop.run_in_executor(
            None, agent.solve, problem.question, metadata
        )
        error = None
    except Exception as e:  # noqa: BLE001
        result = {"final_response": "", "trace": [],
                  "candidates": [], "verdicts": []}
        error = f"{type(e).__name__}: {e}"
    latency = round(time.time() - start, 2)

    final_response = (result.get("final_response") or "").strip() or "无法求解"
    trace = result.get("trace", []) or []
    candidates = result.get("candidates", []) or []
    verdicts = result.get("verdicts", []) or []

    # 组装候选列表（list[dict]，键与 InferenceResult.candidates 字段约定一致）
    verdict_map = {v.get("id"): v for v in verdicts}
    cand_objs: List[dict] = []
    for c in candidates:
        v = verdict_map.get(c.get("id"))
        cand_objs.append({
            "index": c.get("id", 0),
            "answer": c.get("answer", ""),
            "reasoning": c.get("reasoning", ""),
            "confidence": v.get("confidence") if v else None,
        })

    selected_index: Optional[int] = None
    selection_reasoning = "多智能体编排：分类→求解→验证→自主调控选出最高置信度候选"
    if verdicts:
        best = max(verdicts, key=lambda v: v.get("confidence", 0.0))
        selected_index = best.get("id")
        sel_feedback = (best.get("feedback") or "").strip()
        if sel_feedback:
            selection_reasoning = sel_feedback

    return InferenceResult(
        problem_id=problem.id,
        question=problem.question,
        answer=final_response,
        reasoning=_format_trace(trace),
        steps=[],
        verification=_format_verification(verdicts),
        raw_response="",
        tokens_used=client.total_tokens,
        latency_seconds=latency,
        candidates=cand_objs,
        selected_candidate_index=selected_index,
        selection_reasoning=selection_reasoning,
        # 多智能体版已内置验证，评测器自审核不重复执行
        review_passed=None,
        review_attempts=0,
        error=error,
    )


async def run_inference_multi(
    problem: Problem,
    num_samples: int = 3,
    temperatures: Optional[List[float]] = None,
) -> List[InferenceResult]:
    """多样本并行（多智能体版：多次独立运行，结果聚合）。"""
    tasks = [run_inference(problem) for _ in range(max(1, num_samples))]
    return await asyncio.gather(*tasks)
