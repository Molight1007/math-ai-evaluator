"""
Intern-S1 推理模块（多候选 + 自剪枝版）。

核心策略：一次 API 调用，让模型内部完成：
  1. 从 3 个不同角度独立推理 → 生成 3 个候选答案
  2. 对每个候选自我评估（信心度 + 优缺点）
  3. 比较后选出最优答案作为最终输出

相比多次并行调用：
  - 节省 API 调用次数（1 次 vs N 次）
  - 模型在生成过程中即完成比较和剪枝
  - 适合追求答案质量的场景
"""
import asyncio
import json
import logging
import re
import time
from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import Problem, InferenceResult

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 推理参数
_INFERENCE_TEMPERATURE = 0.6      # 适中温度，保证多样性又不失稳定性
_INFERENCE_MAX_TOKENS = 6144      # 多候选输出需要更多 token

# 自审核参数
_REVIEW_TEMPERATURE = 0.2         # 低温度保证审核一致性
_REVIEW_MAX_TOKENS = 2048         # 审核输出长度限制

# 重试参数
_RETRY_TEMPERATURE_FACTOR = 0.8   # 重试时温度下调系数，使输出更聚焦

# 多样本并行调用备选方案参数（run_inference_multi）
_DEFAULT_MULTI_TEMPERATURES = [0.5, 0.7, 0.9]

# ==================== 系统提示词 ====================

SYSTEM_PROMPT = """You are an expert mathematical problem solver. For each problem, you must:

STEP 1 — MULTI-PATH REASONING
Generate THREE independent candidate solutions. Each candidate must:
- Use a different perspective, method, or starting point
- Include complete step-by-step reasoning
- End with a clear final answer

STEP 2 — SELF-EVALUATION
For each candidate, assign:
- confidence: a number 0.0–1.0 indicating how likely this answer is correct
- strength: one sentence describing what makes this approach reliable
- weakness: one sentence describing potential flaw or uncertainty

STEP 3 — PRUNING & SELECTION
- Compare all 3 candidates
- Select the one with the most solid reasoning and highest confidence
- Explain your selection logic

OUTPUT FORMAT (JSON only, no extra text):
{
  "candidates": [
    {
      "index": 0,
      "answer": "final answer for candidate 0",
      "reasoning": "complete step-by-step reasoning",
      "confidence": 0.95,
      "strength": "why this is likely correct",
      "weakness": "potential issue or uncertainty"
    },
    {
      "index": 1,
      "answer": "final answer for candidate 1",
      "reasoning": "complete step-by-step reasoning",
      "confidence": 0.85,
      "strength": "why this is likely correct",
      "weakness": "potential issue or uncertainty"
    },
    {
      "index": 2,
      "answer": "final answer for candidate 2",
      "reasoning": "complete step-by-step reasoning",
      "confidence": 0.70,
      "strength": "why this is likely correct",
      "weakness": "potential issue or uncertainty"
    }
  ],
  "final_answer": "the selected best answer",
  "selected_index": 0,
  "selection_reasoning": "why this candidate is better than the others"
}

CRITICAL RULES:
- The three candidates MUST use genuinely different reasoning paths
- confidence must reflect your honest assessment; do NOT assign all high scores
- The answer field MUST contain only the mathematical result, not explanation
- Output raw JSON only — no markdown code fences, no extra text"""


# ==================== 自审核提示词 ====================

REVIEW_SYSTEM_PROMPT = """You are a rigorous mathematical solution reviewer.

Your job: critically examine an AI-generated mathematical solution and determine if it has real flaws that would affect correctness or completeness.

REVIEW CRITERIA (check each one):
1. COMPLETENESS — Is the answer present and complete? Is the JSON structure parseable? Any truncation or cut-off?
2. CORRECTNESS — Is the mathematical reasoning logically sound? Are there calculation errors, wrong assumptions, or invalid deductions?
3. RELEVANCE — Does the final answer directly and fully address the question that was asked?
4. FORMAT — Is the output valid JSON with all expected fields (candidates, final_answer, selected_index, selection_reasoning)?

OUTPUT ONLY valid JSON (no markdown, no code fences, no extra text):
{
  "verdict": "pass" or "fail",
  "scores": {
    "completeness": 0.0-1.0,
    "correctness": 0.0-1.0,
    "relevance": 0.0-1.0,
    "format": 0.0-1.0
  },
  "issues": ["specific issue 1", "specific issue 2"],
  "suggestions": "actionable, concrete suggestions to fix ALL issues listed above — be specific about what to change and how",
  "summary": "one-sentence verdict"
}

IMPORTANT RULES:
- Give "fail" ONLY for REAL, SIGNIFICANT issues that affect answer correctness or completeness
- Do NOT fail for minor formatting quirks if the content is mathematically correct
- If the response is truncated / JSON is unparseable / fields are missing → always fail
- If the mathematical reasoning contains clear logical gaps or errors → fail
- Be strict about content errors, lenient about formatting
- If the answer is correct, complete, and well-reasoned → pass"""


# ==================== 解析函数 ====================

def parse_multi_candidate_response(text: str) -> dict:
    """
    解析多候选推理的 JSON 响应。

    参数:
        text: API 返回的原始文本

    返回:
        结构化字典，包含 candidates / answer / reasoning / selection 等信息。
        解析失败时返回带有 error 字段的字典。
    """
    try:
        data = extract_json_from_text(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"JSON parse failed, trying regex extraction: {e}")
        data = _fallback_parse(text)

    if not data or not isinstance(data, dict):
        return _make_error_result("Failed to parse JSON from response")

    # 提取最终答案
    final_answer = (
        data.get("final_answer", "")
        or data.get("answer", "")
    )
    if isinstance(final_answer, (int, float)):
        final_answer = str(final_answer)

    # 提取候选列表
    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list) or len(raw_candidates) == 0:
        # 降级：没有 candidates 时，尝试用旧格式解析
        logger.warning("No candidates field found, falling back to single-result format")
        return {
            "answer": final_answer,
            "reasoning": data.get("selection_reasoning", data.get("reasoning", "")),
            "steps": data.get("steps", []),
            "verification": "",
            "candidates": None,
            "selected_index": None,
            "selection_reasoning": data.get("selection_reasoning", ""),
        }

    # 标准化候选列表
    candidates = []
    for i, c in enumerate(raw_candidates):
        if not isinstance(c, dict):
            continue
        ans = c.get("answer", "")
        if isinstance(ans, (int, float)):
            ans = str(ans)
        candidates.append({
            "index": c.get("index", i),
            "answer": ans,
            "reasoning": c.get("reasoning", ""),
            "confidence": float(c.get("confidence", 0.0)),
            "strength": c.get("strength", ""),
            "weakness": c.get("weakness", ""),
        })

    selected_index = data.get("selected_index", None)
    if selected_index is not None:
        selected_index = int(selected_index)

    return {
        "answer": final_answer,
        "reasoning": data.get("selection_reasoning", ""),
        "steps": [],
        "verification": "",
        "candidates": candidates,
        "selected_index": selected_index,
        "selection_reasoning": data.get("selection_reasoning", ""),
    }


def _fallback_parse(text: str) -> dict | None:
    """当主解析失败时，尝试用正则提取 JSON 子串。"""
    # 尝试匹配 {...} 中最长的 JSON 对象
    json_candidates = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if not json_candidates:
        # 尝试跨行匹配
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_candidates = [match.group()]
    for candidate in sorted(json_candidates, key=len, reverse=True):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and ("candidates" in data or "final_answer" in data or "answer" in data):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _make_error_result(message: str) -> dict:
    """构造解析失败时的结果。"""
    return {
        "answer": "",
        "reasoning": f"Parse error: {message}",
        "steps": [],
        "verification": "",
        "candidates": None,
        "selected_index": None,
        "selection_reasoning": "",
        "error": message,
    }


# ==================== 旧格式解析（向后兼容） ====================

def parse_intern_response(text: str) -> dict:
    """
    解析旧格式单答案响应。

    参数:
        text: API 返回的原始文本

    返回:
        包含 answer / reasoning / steps / verification 的字典
    """
    try:
        data = extract_json_from_text(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse intern response as JSON; using raw text")
        return {
            "answer": text.strip(),
            "reasoning": text.strip(),
            "steps": [],
            "verification": "",
        }
    if not data or not isinstance(data, dict):
        return {"answer": text.strip(), "reasoning": text.strip(), "steps": [], "verification": ""}
    return {
        "answer": str(data.get("answer", "")),
        "reasoning": data.get("reasoning", "") or data.get("thought", ""),
        "steps": data.get("steps", []),
        "verification": data.get("verification", "") or data.get("logic_check", ""),
    }


# ==================== 审核解析函数 ====================

def parse_review_response(raw: str, latency: float = 0.0, tokens: int = 0) -> dict:
    """
    解析自审核响应，返回标准化的审核结果字典。

    对模型返回的审核 JSON 做容错解析：
    - JSON 解析失败时通过关键词推断 verdict
    - 输出非字典类型时回退为默认 pass

    参数:
        raw: 审核模型返回的原始文本
        latency: 审核 API 调用耗时（秒）
        tokens: 审核消耗的 token 数

    返回:
        {
            "verdict": "pass"|"fail",
            "scores": {"completeness": float, "correctness": float, ...},
            "issues": [str, ...],
            "suggestions": str,
            "summary": str,
            "tokens_used": int,
            "latency": float,
        }
    """
    try:
        data = extract_json_from_text(raw)
    except (json.JSONDecodeError, ValueError):
        text_lower = raw.lower()
        has_pass = "pass" in text_lower and "fail" not in text_lower
        return {
            "verdict": "pass" if has_pass else "fail",
            "scores": {"completeness": 0.5, "correctness": 0.5, "relevance": 0.5, "format": 0.5},
            "issues": [] if has_pass else ["Failed to parse review JSON"],
            "suggestions": "",
            "summary": raw.strip()[:200],
            "tokens_used": tokens,
            "latency": latency,
        }
    if not isinstance(data, dict):
        return {
            "verdict": "pass",
            "scores": {"completeness": 0.5, "correctness": 0.5, "relevance": 0.5, "format": 0.5},
            "issues": [],
            "suggestions": "",
            "summary": "Could not parse review as JSON dict",
            "tokens_used": tokens,
            "latency": latency,
        }
    verdict = data.get("verdict", "pass").lower()
    if verdict not in ("pass", "fail"):
        verdict = "pass"
    return {
        "verdict": verdict,
        "scores": data.get("scores", {}),
        "issues": data.get("issues", []) if isinstance(data.get("issues"), list) else [],
        "suggestions": data.get("suggestions", ""),
        "summary": data.get("summary", ""),
        "tokens_used": tokens,
        "latency": latency,
    }


# ==================== 内部推理辅助 ====================

def _build_feedback_user_content(problem: Problem, review_feedback: dict) -> str:
    """
    构建带审核反馈的用户消息内容。

    将自审核发现的问题和改进建议注入到 prompt 中，引导模型在重试时有针对性地修正。

    参数:
        problem: 原始题目
        review_feedback: 审核结果字典（含 issues / suggestions）

    返回:
        包含原始题目和审核反馈的完整用户消息字符串
    """
    issues = review_feedback.get("issues", [])
    suggestions = review_feedback.get("suggestions", "")
    if issues:
        issues_text = "\n".join(f"  - {issue}" for issue in issues)
    else:
        issues_text = "  (no specific issues listed)"
    return (
        f"请解决以下数学证明题，严格按系统提示的格式输出JSON。\n\n"
        f"{problem.question}\n\n"
        f"---\n"
        f"[自我审核反馈] 你上一次的回答存在问题：\n"
        f"{issues_text}\n\n"
        f"改进建议：{suggestions}\n\n"
        f"请修正以上所有问题，重新生成完整的答案。"
    )


async def _do_inference(
    problem: Problem,
    client: LLMClient,
    review_feedback: Optional[dict] = None,
    temperature: Optional[float] = None,
    sample_index: int = 0,
) -> InferenceResult:
    """
    核心推理逻辑：单次 API 调用，生成多候选答案。

    合并了初始推理、审核反馈重试、多样本三种场景，通过可选参数区分行为。

    参数:
        problem: 需要解答的数学题目
        client: LLM 客户端实例
        review_feedback: 审核反馈字典（用于重试时注入问题）
        temperature: 推理温度，None 则使用默认值 _INFERENCE_TEMPERATURE
        sample_index: 样本编号（多样本模式下使用）

    返回:
        InferenceResult
    """
    if temperature is None:
        temperature = _INFERENCE_TEMPERATURE
    if review_feedback is not None:
        temperature *= _RETRY_TEMPERATURE_FACTOR
        user_content = _build_feedback_user_content(problem, review_feedback)
    else:
        user_content = problem.question

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    label = "Retry" if review_feedback else "Inference"
    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=_INFERENCE_MAX_TOKENS,
        )
        latency = round(time.time() - start_time, 2)
        raw_text = response["content"]
        parsed = parse_multi_candidate_response(raw_text)

        logger.info(
            f"{label} completed for [{problem.id}]: "
            f"final_answer={parsed.get('answer', '?')}, "
            f"candidates={len(parsed.get('candidates') or [])}, "
            f"tokens={response.get('tokens_used', 0)}, "
            f"latency={latency}s"
        )

        return InferenceResult(
            problem_id=problem.id,
            question=problem.question,
            answer=parsed.get("answer", ""),
            reasoning=parsed.get("reasoning", ""),
            steps=parsed.get("steps", []),
            verification=parsed.get("verification", ""),
            raw_response=raw_text,
            tokens_used=response.get("tokens_used", 0),
            latency_seconds=latency,
            sample_index=sample_index,
            candidates=parsed.get("candidates"),
            selected_candidate_index=parsed.get("selected_index"),
            selection_reasoning=parsed.get("selection_reasoning", ""),
        )
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(f"{label} failed for [{problem.id}]: {e}")
        return InferenceResult(
            problem_id=problem.id,
            question=problem.question,
            answer="",
            reasoning="",
            sample_index=sample_index,
            latency_seconds=latency,
            error=str(e),
        )


# ==================== 自审核函数 ====================

async def _self_review(
    problem: Problem,
    inference_result: InferenceResult,
) -> dict:
    """
    让模型自审核自己的输出，检测漏洞/不完整/错误。

    使用审核专用 prompt 和低温度参数，从正确性、完整性、相关性、格式四个维度
    审查推理输出。审核 API 调用失败时默认返回 pass，不阻塞主流程。

    参数:
        problem: 原始题目
        inference_result: 推理阶段产出的结果（含 raw_response）

    返回:
        审核结果字典，包含：
        - verdict: "pass" 或 "fail"
        - scores: 四个维度的评分字典
        - issues: 发现的具体问题列表
        - suggestions: 改进建议
        - summary: 审核摘要
        - tokens_used: 消耗 token 数
        - latency: 耗时（秒）
    """
    cfg = get_config()
    client = LLMClient(cfg.intern_s1)

    review_content = (
        f"Original Question:\n{problem.question}\n\n"
        f"Generated Solution (raw output):\n{inference_result.raw_response}"
    )
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": review_content},
    ]

    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=_REVIEW_TEMPERATURE,
            max_tokens=_REVIEW_MAX_TOKENS,
        )
        latency = round(time.time() - start_time, 2)
        raw = response["content"]
        review = parse_review_response(raw, latency, response.get("tokens_used", 0))
        logger.info(
            f"Self-review [{problem.id}]: verdict={review.get('verdict')}, "
            f"summary={review.get('summary')}"
        )
        return review
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.warning(f"Self-review call failed [{problem.id}]: {e}")
        return {
            "verdict": "pass",
            "scores": {"completeness": 0, "correctness": 0, "relevance": 0, "format": 0},
            "issues": [],
            "suggestions": "",
            "summary": "",
            "tokens_used": 0,
            "latency": latency,
            "error": str(e),
        }


# ==================== 主推理函数（含自审核循环） ====================

async def run_inference(
    problem: Problem,
    enable_review: bool = True,
    max_review_retries: int = 2,
) -> InferenceResult:
    """对单道题目执行 Intern-S1 推理（多候选 + 自剪枝 + 自审核循环）。

    完整流程：
    1. 推理 → 一次 API 调用，模型生成 3 候选 + 自剪枝选出最优
    2. 自审核 → 调用审核模型检测答案是否存在漏洞 / 不完整 / 错误
    3. 若审核不通过 → 将审核反馈注入 prompt，重新生成（最多 max_review_retries 次）
    4. 审核通过或达到最大重试次数 → 返回最终结果

    参数:
        problem:           需要解答的数学题目
        enable_review:     是否启用自审核（默认 True）
        max_review_retries: 审核不通过时的最大重试次数（默认 2）

    返回:
        InferenceResult，包含审核状态：
        - review_passed:  审核是否通过
        - review_feedback: 审核反馈详情（verdict / scores / issues / suggestions）
        - review_attempts: 审核/重试总次数
        - total_tokens_used / total_latency_seconds: 包含所有阶段的总消耗
    """
    cfg = get_config()
    client = LLMClient(cfg.intern_s1)

    total_tokens = 0
    total_latency = 0.0
    review_tokens = 0
    review_latency = 0.0

    # --- 阶段 1: 推理 ---
    result = await _do_inference(problem, client)
    total_tokens += result.tokens_used
    total_latency += result.latency_seconds

    if not enable_review or result.error:
        result.total_tokens_used = total_tokens
        result.total_latency_seconds = total_latency
        return result

    current_result = result

    # --- 阶段 2: 自审核 + 条件重试 ---
    for attempt in range(max_review_retries + 1):
        review = await _self_review(problem, current_result)
        review_tokens += review.get("tokens_used", 0)
        review_latency += review.get("latency", 0)

        if review.get("verdict") == "pass":
            current_result.review_passed = True
            current_result.review_feedback = review
            current_result.review_attempts = attempt
            logger.info(
                f"Self-review PASSED [{problem.id}] after {attempt} retries"
            )
            break

        # 审核不通过
        summary = review.get("summary", "unknown issues")

        if attempt < max_review_retries:
            logger.info(
                f"Self-review FAILED [{problem.id}], "
                f"retrying ({attempt + 1}/{max_review_retries}): {summary}"
            )
            retry_result = await _do_inference(
                problem, client, review_feedback=review
            )
            total_tokens += retry_result.tokens_used
            total_latency += retry_result.latency_seconds
            current_result = retry_result
        else:
            current_result.review_passed = False
            current_result.review_feedback = review
            current_result.review_attempts = attempt
            logger.warning(
                f"Self-review STILL FAILED after {max_review_retries} retries "
                f"[{problem.id}]: {summary}"
            )

    current_result.review_tokens_used = review_tokens
    current_result.review_latency_seconds = review_latency
    current_result.total_tokens_used = total_tokens
    current_result.total_latency_seconds = total_latency + review_latency
    return current_result


# ==================== 备选：多样本并行调用 ====================

async def _run_inference_with_sample(
    problem: Problem,
    sample_index: int,
    temperature: float,
) -> InferenceResult:
    """
    以指定温度和样本编号执行推理（内部辅助函数）。

    封装 _do_inference，为多样本并行调用提供统一入口，消除重复代码。

    参数:
        problem: MasterProblem 数学题目
        sample_index: 样本编号（0-based，用于区分同一题目的不同答案）
        temperature: 推理温度

    返回:
        InferenceResult（sample_index 已设置）
    """
    cfg = get_config()
    client = LLMClient(cfg.intern_s1)
    return await _do_inference(
        problem, client,
        temperature=temperature,
        sample_index=sample_index,
    )


async def run_inference_multi(
    problem: Problem,
    num_samples: int = 3,
    temperatures: list[float] | None = None,
) -> list[InferenceResult]:
    """
    备选方案：多次并行调用 Intern-S1，每次使用不同温度。

    与 run_inference() 的区别：
    - run_inference():     1 次调用，模型内部生成 3 候选 + 自剪枝
    - run_inference_multi(): N 次并行调用，外部汇总 N 个独立推理结果

    适用场景：需要更多答案多样性、或模型单次调用无法给出 3 个有差异的候选时。
    """
    if temperatures is None:
        if num_samples <= len(_DEFAULT_MULTI_TEMPERATURES):
            temps = _DEFAULT_MULTI_TEMPERATURES[:num_samples]
        else:
            temps = [round(0.4 + i * 0.5 / max(num_samples - 1, 1), 2) for i in range(num_samples)]
    else:
        temps = temperatures[:num_samples]

    logger.info(
        f"Multi-sample inference [{problem.id}]: {num_samples} samples, temps={temps}"
    )
    tasks = [_run_inference_with_sample(problem, i, temps[i]) for i in range(num_samples)]
    results = await asyncio.gather(*tasks)
    return list(results)
