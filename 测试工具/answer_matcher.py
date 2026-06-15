"""
答案匹配引擎 — 使用 DeepSeek 将提取的答案与题库题目进行语义匹配。

核心流程:
1. 从答案文档提取「题目-答案」对
2. 批量调用 DeepSeek，让它判断每个答案对应题库中的哪道题
3. 将匹配结果存储到数据库 answer_mapping 表
4. 后续评测时，DeepSeek 评判可以同时拿到参考答案，准确率更高
"""
import asyncio
import json
import logging
import time
from typing import Optional, Callable

from models import Problem
from llm_client import LLMClient, extract_json_from_text
from config import get_config

logger = logging.getLogger(__name__)

# 匹配系统提示词
MATCH_SYSTEM_PROMPT = (
    "你是一个数学题目匹配专家。你的任务是将「答案文档中提取的答案」与「题库中的题目」进行匹配。\n\n"
    "你会收到：\n"
    "1. 一批答案文档中的条目（可能包含题干片段 + 答案）\n"
    "2. 题库中的所有题目（含 ID、题干、领域）\n\n"
    "你需要为每个答案条目找到最匹配的题库题目，或者判定「无法匹配」。\n\n"
    "匹配原则（按优先级）：\n"
    "1. 如果答案条目的题干与题库题目的题干高度相似 → 直接匹配\n"
    "2. 如果答案条目的答案内容与题库题目的考查点一致 → 推断匹配\n"
    "3. 如果答案条目只有答案没有题干 → 根据答案反推可能对应的题目\n"
    "4. 如果无法确定匹配 → 标记为 unmatched\n\n"
    "输出严格的 JSON 格式。"
)


def build_match_prompt(
    answer_pairs: list[dict],
    bank_problems: list[Problem],
) -> str:
    """构建匹配 prompt"""

    # 答案条目描述
    answers_text = ""
    for ap in answer_pairs:
        answers_text += (
            f"\n【答案条目 {ap['index']}】\n"
            f"题干片段: {ap.get('question_text', '') or '(无题干，仅有答案)'}\n"
            f"答案内容: {ap.get('answer_text', '')}\n"
            f"来源页码: {ap.get('source_page', '?')}\n"
        )

    # 题库题目描述
    problems_text = ""
    for i, p in enumerate(bank_problems):
        problems_text += (
            f"\n【题库题目 {i+1}】\n"
            f"ID: {p.id}\n"
            f"领域: {p.domain or '未分类'}\n"
            f"题干: {p.question[:200]}\n"
        )

    return f"""## 答案文档条目（共 {len(answer_pairs)} 条）
{answers_text}

## 题库题目（共 {len(bank_problems)} 道）
{problems_text}

## 匹配任务

请为每个「答案条目」找到最匹配的「题库题目」。

对于每个答案条目，输出：
- matched_problem_id: 匹配到的题库题目 ID（如果无法匹配则为 null）
- confidence: 匹配置信度 0.0-1.0
- match_reason: 简短说明匹配依据（中文）
- matched_answer: 从答案条目中提取的最终答案（只保留核心答案，去除冗余文字）

## 输出格式（严格 JSON）
```json
{{
  "matches": [
    {{
      "answer_index": 1,
      "matched_problem_id": "题目ID 或 null",
      "confidence": 0.95,
      "match_reason": "题干高度相似，考查的都是...",
      "matched_answer": "提取的核心答案"
    }}
  ],
  "summary": {{
    "total_answers": {len(answer_pairs)},
    "matched_count": 0,
    "unmatched_count": 0
  }}
}}
```

注意：
- answer_index 必须与答案条目的 index 一致
- 每个答案条目最多匹配一道题
- 多道答案条目可以匹配同一道题（如一题多解）
- confidence 低于 0.5 的匹配请标记为 null（无法匹配）
- 只输出 JSON，不要其他文字"""


def parse_match_response(raw_content: str) -> dict:
    """解析 DeepSeek 匹配响应"""
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        return {
            "matches": parsed.get("matches", []),
            "summary": parsed.get("summary", {}),
            "raw": raw_content,
        }
    logger.warning(f"无法解析匹配响应，原始长度={len(raw_content)}")
    return {"matches": [], "summary": {}, "raw": raw_content}


async def _match_batch_async(
    answer_pairs: list[dict],
    bank_problems: list[Problem],
) -> dict:
    """异步调用 DeepSeek 匹配一批答案"""
    cfg = get_config()
    client = LLMClient(cfg.deepseek)

    prompt = build_match_prompt(answer_pairs, bank_problems)

    messages = [
        {"role": "system", "content": MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    start = time.time()
    response = await client.chat(
        messages=messages,
        temperature=0.1,
        max_tokens=4096,
    )
    elapsed = time.time() - start
    logger.info(f"匹配 API 调用完成，耗时 {elapsed:.1f}s，tokens={response.get('tokens_used', 0)}")

    result = parse_match_response(response["content"])
    result["tokens_used"] = response.get("tokens_used", 0)
    result["latency"] = round(elapsed, 2)
    return result


def match_answers_to_bank(
    answer_pairs: list[dict],
    bank_problems: list[Problem],
    batch_size: int = 15,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """
    将答案对批量匹配到题库题目。

    参数:
        answer_pairs: 从答案文档提取的条目列表
        bank_problems: 题库中的所有题目
        batch_size: 每批处理的答案数量
        progress_callback: 进度回调 (current, total, message)

    返回:
        {
            "matches": [...],       # 所有匹配结果
            "total_answers": int,   # 答案总数
            "matched_count": int,   # 成功匹配数
            "unmatched_count": int, # 未匹配数
            "tokens_used": int,     # 总 token 消耗
            "latency": float,       # 总耗时
            "errors": [...],        # 错误列表
        }
    """
    total = len(answer_pairs)
    if total == 0:
        return {
            "matches": [],
            "total_answers": 0,
            "matched_count": 0,
            "unmatched_count": 0,
            "tokens_used": 0,
            "latency": 0,
            "errors": ["没有可匹配的答案"],
        }

    all_matches = []
    total_tokens = 0
    total_latency = 0.0
    errors = []

    # 分批处理（复用事件循环，避免每批都创建/销毁 asyncio.run 的开销）
    loop = asyncio.new_event_loop()
    try:
        for batch_start in range(0, total, batch_size):
            batch = answer_pairs[batch_start: batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total)

            if progress_callback:
                progress_callback(
                    batch_start, total,
                    f"正在匹配第 {batch_start+1}-{batch_end} 条答案..."
                )

            try:
                result = loop.run_until_complete(_match_batch_async(batch, bank_problems))

                matches = result.get("matches", [])
                all_matches.extend(matches)
                total_tokens += result.get("tokens_used", 0)
                total_latency += result.get("latency", 0)

                matched_in_batch = sum(1 for m in matches if m.get("matched_problem_id"))
                logger.info(
                    f"批次 {batch_start//batch_size + 1}: "
                    f"{len(matches)} 条答案, {matched_in_batch} 条匹配成功"
                )

            except Exception as e:
                error_msg = f"批次 {batch_start//batch_size + 1} 失败: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
    finally:
        loop.close()

    # 统计
    matched_count = sum(1 for m in all_matches if m.get("matched_problem_id"))
    unmatched_count = len(all_matches) - matched_count

    return {
        "matches": all_matches,
        "total_answers": total,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "tokens_used": total_tokens,
        "latency": round(total_latency, 2),
        "errors": errors,
    }
