"""
DeepSeek 评判模块。
将 Intern-S1 的推理过程和答案发送给 DeepSeek 进行正确性评估。
支持利用题库中已匹配的参考答案辅助评判，提高准确率。
支持单题评判和批量评判两种模式。
"""
import asyncio
import json
import logging
import re
import time
from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import InferenceResult, JudgeResult

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 评判模型参数
_JUDGE_TEMPERATURE = 0.1       # 低温度以获得更一致的评价
_JUDGE_MAX_TOKENS = 2048       # 单题评判最大 token（基础值，会按输入长度动态放大）
_JUDGE_BATCH_MAX_TOKENS = 8192 # 批量评判最大 token（按题目数动态扩展）
_JUDGE_BATCH_TOKEN_PER_ITEM = 2048  # 批量评判每道题预留 token

# 回退关键词检测：无法解析 JSON 时使用的正/负向关键词
_POSITIVE_KEYWORDS = ("correct", "true", "正确")
_FALLBACK_CONFIDENCE = 0.3     # 回退时的默认置信度

# 批量评判缺失时的默认置信度
_BATCH_MISSING_CONFIDENCE = 0.3

# ==================== token 估算与文本精简 ====================
# 项目不引入 tiktoken，用字符数保守估算 token 数（1 token ≈ 3 字符）。
# 中英混合 / LaTeX 场景下该估算偏保守（高估），避免输出超限被截断。
_TOKENS_PER_CHAR_DIVISOR = 3

# 送审前精简上限（按估算 token 数）
_ANSWER_MAX_TOKENS = 1024            # 答案文本保留上限
_REASONING_MAX_TOKENS = 3000         # 计算题推理保留上限
_REASONING_PROOF_MAX_TOKENS = 6000   # 证明题推理保留上限（放宽，推理是判题核心）

# 动态分批：单批输入总 token 上限（题目 + 答案 + 推理）
_MAX_BATCH_INPUT_TOKENS = 6000

# 判题输出 token 上限（截断重试时的硬顶）
_JUDGE_SINGLE_MAX_TOKENS = 8192     # 单题评判输出上限
_JUDGE_BATCH_MAX_TOKENS_CAP = 16384 # 批量评判输出上限

_PROOF_QUESTION_RE = re.compile(
    r"证明|证\s*明|prove\b|show\s+that|demonstrate|derive\b|explain\s+why|"
    r"说明\s*为什么|为何|why\b",
    re.IGNORECASE,
)

_VALID_ERROR_TYPES = frozenset({
    "mathematical_error",
    "incomplete",
    "reasoning_error",
    "formatting_error",
    "calculation_error",
    "logic_error",
    "other",
})

# ==================== Prompt 模板 ====================

JUDGE_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator aligned with international math reasoning benchmarks.\n\n"
    "You will receive:\n"
    "1. The math problem\n"
    "2. The model's final answer (conclusion)\n"
    "3. The model's proof / reasoning / steps\n"
    "4. (Optional) A reference answer from the answer bank\n\n"
    "EVALUATION PROCEDURE (execute in strict order):\n\n"
    "Step 1 — CONCLUSION CORRECTNESS (highest priority):\n"
    "  Check whether the final mathematical conclusion is correct.\n"
    "  If the conclusion is WRONG → is_correct=false.\n"
    "  If the conclusion is CORRECT → proceed to Step 2.\n\n"
    "Step 2 — LOGIC ERROR CHECK:\n"
    "  Examine the reasoning process for SERIOUS mathematical logic errors.\n"
    "  A serious logic error means: circular reasoning, wrong theorem/method,\n"
    "  invalid deduction that coincidentally produces the right answer.\n"
    "  If a serious logic error exists → is_correct=false, error_type=reasoning_error.\n"
    "  If no serious logic error → the answer is MATHEMATICALLY CORRECT.\n"
    "  Proceed to Step 3.\n\n"
    "Step 3 — PROOF COMPLETENESS (lowest priority):\n"
    "  Check whether the problem requires proof/derivation/explanation/calculation\n"
    "  and whether the model provided sufficient process.\n"
    "  If process is missing or insufficient → error_type=incomplete.\n"
    "  IMPORTANT: incomplete is NOT a mathematical error.\n"
    "  incomplete does NOT override is_correct.\n"
    "  A correct conclusion with insufficient proof → is_correct=true, error_type=incomplete.\n\n"
    "CRITICAL RULES:\n"
    "- Correct conclusion → is_correct MUST be true. Non-negotiable.\n"
    "- Wrong conclusion → is_correct MUST be false.\n"
    "- Short but valid proof → is_correct=true (may set error_type=incomplete).\n"
    "- NEVER use mathematical_error, calculation_error, or logic_error\n"
    "  when the conclusion is correct and there is no core logic flaw.\n"
    "- For Chinese-language proofs, a single sentence with mathematical\n"
    "  reasoning keywords (设/令/因为/因此/所以/推出/可得) counts as having\n"
    "  proof content. Do NOT require lengthy proofs.\n\n"
    "error_type values:\n"
    "- mathematical_error: wrong final conclusion or fatal math mistake\n"
    "- calculation_error: arithmetic mistake (wrong conclusion)\n"
    "- incomplete: conclusion correct but proof/derivation missing or insufficient\n"
    "- reasoning_error: core logic error in derivation (conclusion may be coincidental)\n"
    "- logic_error: synonym for reasoning_error (core logic flaw)\n"
    "- formatting_error: format/LaTeX issues only, math essentially correct\n"
    "- null: fully correct with adequate support\n\n"
    "Output JSON only:\n"
    "{\n"
    '  "is_correct": true/false,\n'
    '  "confidence": 0.0-1.0,\n'
    '  "explanation": "brief Chinese explanation",\n'
    '  "error_type": "mathematical_error"|"calculation_error"|"incomplete"|'
    '"reasoning_error"|"logic_error"|"formatting_error"|null,\n'
    '  "correct_answer": null or string,\n'
    '  "conclusion_correct": true/false\n'
    "}\n"
    "Output ONLY the JSON object."
)

JUDGE_BATCH_SYSTEM_PROMPT = (
    "You are a rigorous math evaluator. Judge MULTIPLE problems independently.\n\n"
    "EVALUATION PROCEDURE (same 3-step process for each problem):\n"
    "Step 1: Is the final mathematical conclusion correct?\n"
    "  Wrong → is_correct=false. Correct → proceed.\n"
    "Step 2: Does reasoning contain a SERIOUS logic error?\n"
    "  Yes → is_correct=false, error_type=reasoning_error. No → proceed.\n"
    "Step 3: Is the proof/derivation complete?\n"
    "  Missing/insufficient → error_type=incomplete (NOT a math error).\n"
    "  incomplete does NOT make is_correct=false.\n\n"
    "CRITICAL RULES:\n"
    "- Correct conclusion → is_correct=true ALWAYS.\n"
    "  If proof insufficient → error_type=incomplete (NOT mathematical_error).\n"
    "- Wrong conclusion → is_correct=false (error_type=mathematical_error or calculation_error).\n"
    "- Correct conclusion + core logic error → is_correct=false (error_type=reasoning_error).\n"
    "- NEVER use mathematical_error, calculation_error, or logic_error when conclusion is correct.\n"
    "- For Chinese proofs, a single sentence with reasoning keywords counts as proof.\n\n"
    "You will receive {count} problems labeled as P1, P2, P3...\n\n"
    'Output a JSON ARRAY where each element has:\n'
    '- "problem_index": "P1" or "P2" or "P3"... (MUST match the label exactly)\n'
    '- "is_correct": boolean,\n'
    '- "confidence": 0.0-1.0,\n'
    '- "explanation": Chinese,\n'
    '- "error_type": mathematical_error|calculation_error|incomplete|reasoning_error|logic_error|formatting_error|null,\n'
    '- "correct_answer": string or null,\n'
    '- "conclusion_correct": boolean\n\n'
    "Output ONLY the JSON array, same order as input."
)


def is_proof_problem(question: str) -> bool:
    if not question:
        return False
    return bool(_PROOF_QUESTION_RE.search(question))


# ---- token 估算与文本精简 helper ----

def _estimate_tokens(text: str) -> int:
    """用字符数保守估算 token 数（1 token ≈ 3 字符，中英混合场景高估，避免超限）。"""
    if not text:
        return 0
    return max(1, len(text) // _TOKENS_PER_CHAR_DIVISOR)


def _truncate_by_tokens(text: str, max_tokens: int, head_ratio: float = 0.6) -> str:
    """
    按估算 token 数截断文本，保留头部 head_ratio 与尾部 1-head_ratio 的关键内容，
    中间插入省略标记。未超限时原样返回。
    """
    if not text:
        return text
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * _TOKENS_PER_CHAR_DIVISOR
    head_chars = int(max_chars * head_ratio)
    tail_chars = max_chars - head_chars
    if head_chars <= 0 or tail_chars <= 0:
        return text[:max_chars]
    marker = "\n...[中间部分已省略]...\n"
    return text[:head_chars] + marker + text[-tail_chars:]


def _prepare_item_text(
    answer_text: str, reasoning_text: str, is_proof: bool
) -> tuple[str, str]:
    """
    送审前精简答案与推理文本（按 token 数），供单题与批量评判共用。

    答案保留较大上限；推理文本按题型决定上限：
    - 证明题：放宽上限（推理是判题核心依据）
    - 计算题：收紧上限（答案为主，推理可精简）

    返回 (精简后的 answer_text, 精简后的 reasoning_text)。
    """
    answer_text = answer_text or ""
    reasoning_text = reasoning_text or ""
    answer_text = _truncate_by_tokens(
        answer_text, _ANSWER_MAX_TOKENS, head_ratio=0.5
    )
    reasoning_limit = (
        _REASONING_PROOF_MAX_TOKENS if is_proof else _REASONING_MAX_TOKENS
    )
    reasoning_text = _truncate_by_tokens(
        reasoning_text, reasoning_limit, head_ratio=0.6
    )
    return answer_text, reasoning_text


def _build_dynamic_batches(
    inferences: list, max_batch_input_tokens: int = _MAX_BATCH_INPUT_TOKENS
) -> list[list]:
    """
    按每道题估算的输入 token 数动态分批。

    贪心累加每道题精简后的输入 token（题目 + 答案 + 推理），超过上限即开新批；
    单题超限自动单独成批。

    参数:
        inferences: InferenceResult 列表
        max_batch_input_tokens: 单批输入总 token 上限

    返回:
        list[list[InferenceResult]] — 分批后的结果
    """
    batches: list[list] = []
    current: list = []
    current_tokens = 0
    for inf in inferences:
        is_proof = is_proof_problem(inf.question)
        answer_text, reasoning_text = _prepare_item_text(
            inf.answer, inf.reasoning, is_proof
        )
        item_tokens = (
            _estimate_tokens(inf.question)
            + _estimate_tokens(answer_text)
            + _estimate_tokens(reasoning_text)
        )
        if current and current_tokens + item_tokens > max_batch_input_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(inf)
        current_tokens += item_tokens
    if current:
        batches.append(current)
    return batches


# ---- 中文数学证明模式识别 ----

# 证明关键词：出现任意一个即表明有推理/证明意图
# 注意：不含"利用"、"根据"等过于泛化的词
_PROOF_KEYWORDS = (
    "证明", "因为", "由于", "设", "令", "假设", "由此", "因此",
    "所以", "推出", "得到", "可得", "可知", "故",
    "则", "即", "亦即", "等价", "化简", "代入", "整理得",
    "采用", "构造", "反证", "矛盾",
)

# 数学推导结构标记
_DERIVATION_MARKERS = (
    "→", "=>", "⟹", "推导", "导出", "推得",
)

# 步骤编号正则：1. / 2. / (1) / [1] / Step 1 / 第一步
_STEP_NUMBER_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"\d+[\.\)、]"           # 1. 2) 3、
    r"|\(\d+\)"              # (1) (2)
    r"|\[\d+\]"              # [1] [2]
    r"|Step\s*\d+"            # Step 1
    r"|第[一二三四五六七八九十]+步"  # 第一步
    r")",
    re.IGNORECASE,
)

# 公式推导正则：含等号链或不等式推导
_FORMULA_RE = re.compile(
    r"[a-zA-Z\u4e00-\u9fff\)\]]\s*[=<>≤≥≈≠]\s*"  # x = ... / f(x) ≥ ...
)

# 裸答案正则：只有最终结论，无推理标记
_BARE_ANSWER_RE = re.compile(r"^[\s\d\.\,\-\+/=\u4e00-\u9fff\(\)]{3,}$")


def _collect_proof_text(inference: InferenceResult) -> str:
    """汇总推理相关文本，用于证明模式识别。"""
    parts = []
    if inference.reasoning:
        parts.append(inference.reasoning)
    if inference.verification:
        parts.append(inference.verification)
    if inference.steps:
        parts.extend(inference.steps)
    # 多候选：取选中候选的 proof/reasoning
    candidates = inference.candidates or []
    sel = inference.selected_candidate_index
    for c in candidates:
        if sel is not None:
            try:
                if int(c.get("index", -1)) != int(sel):
                    continue
            except (ValueError, TypeError):
                continue
        for key in ("proof", "reasoning"):
            val = c.get(key)
            if val:
                parts.append(str(val))
        if c.get("steps"):
            parts.extend(c.get("steps"))
    # 如果没有选中候选，也检查所有候选
    if candidates and not sel:
        for c in candidates:
            for key in ("proof", "reasoning"):
                val = c.get(key)
                if val:
                    parts.append(str(val))
            if c.get("steps"):
                parts.extend(c.get("steps"))
    return "\n".join(parts)


def _detect_proof_features(text: str) -> dict:
    """
    分析文本中的证明特征，返回特征字典。

    返回:
        {
            "has_keywords": bool,       # 含证明关键词
            "has_derivation": bool,     # 含数学推导结构
            "has_steps": bool,          # 含步骤编号
            "has_formula": bool,        # 含公式推导
            "keyword_count": int,       # 关键词出现次数
            "step_count": int,          # 步骤编号数量
        }
    """
    if not text or not text.strip():
        return {
            "has_keywords": False,
            "has_derivation": False,
            "has_steps": False,
            "has_formula": False,
            "keyword_count": 0,
            "step_count": 0,
        }

    # 关键词检测
    keyword_count = sum(1 for kw in _PROOF_KEYWORDS if kw in text)
    has_keywords = keyword_count >= 1

    # 推导结构检测
    has_derivation = any(marker in text for marker in _DERIVATION_MARKERS)

    # 步骤编号检测
    step_matches = _STEP_NUMBER_RE.findall(text)
    step_count = len(step_matches)
    has_steps = step_count >= 2  # 至少两步才算有步骤

    # 公式推导检测
    formula_matches = _FORMULA_RE.findall(text)
    has_formula = len(formula_matches) >= 1

    return {
        "has_keywords": has_keywords,
        "has_derivation": has_derivation,
        "has_steps": has_steps,
        "has_formula": has_formula,
        "keyword_count": keyword_count,
        "step_count": step_count,
    }


def inference_has_proof(inference: InferenceResult) -> bool:
    """
    proof-aware：是否有证明/推理/步骤内容。
    不再使用简单长度阈值，改为中文数学证明模式识别。

    判定有证明的条件（满足任意一项）：
    1. 含证明关键词（证明/因为/设/令/因此/所以/推出 等）
    2. 含数学推导结构（→ / => / 推导 / 导出）
    3. 含步骤编号（1. 2. 3. / (1) / Step 1 / 第一步）
    4. 含公式推导（含等号/不等号的推导链）
    5. 有 steps 列表（非空）

    特殊处理：极短文本（<20字符）仅含1个关键词且无结构化推导特征时，
    视为仅引用方法名而非实际证明（如"欧几里得证明法可以证明"）。
    """
    # steps 列表非空 → 有证明
    if inference.steps:
        return True

    text = _collect_proof_text(inference)
    if not text.strip():
        return False

    features = _detect_proof_features(text)

    # 短文本保护：极短文本 + 仅1个关键词 + 无结构化特征 → 不是证明
    text_len = len(text.strip())
    structural_signals = (
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if (
        text_len < 20
        and features["keyword_count"] <= 1
        and not any(structural_signals)
    ):
        return False

    return (
        features["has_keywords"]
        or features["has_derivation"]
        or features["has_steps"]
        or features["has_formula"]
    )


def proof_quality_score(inference: InferenceResult) -> float:
    """
    评估证明质量分数（0-1）。

    返回值:
        0.0: 无证明（无关键词、无推导、无步骤、无公式）
        0.5: 有简单推理（含关键词或基本推导，但不够完整）
        1.0: 完整证明（多维度证据：关键词+推导/步骤/公式）
    """
    text = _collect_proof_text(inference)
    if not text.strip():
        return 0.0

    features = _detect_proof_features(text)

    # 无任何证明特征 → 0
    score_signals = (
        features["has_keywords"],
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if not any(score_signals):
        return 0.0

    # 短文本保护：极短文本 + 仅1个关键词 + 无结构化特征 → 无实际证明
    text_len = len(text.strip())
    structural_signals = (
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if (
        text_len < 20
        and features["keyword_count"] <= 1
        and not any(structural_signals)
    ):
        return 0.0

    # 完整证明：关键词 + 至少一个结构化推导特征
    if features["has_keywords"] and any(structural_signals):
        return 1.0

    # 有多个关键词但无结构化推导 → 较好但仍不完整
    if features["keyword_count"] >= 3:
        return 1.0

    # 有步骤编号但无关键词 → 也算较完整
    if features["has_steps"] and features["step_count"] >= 3:
        return 1.0

    # 有公式推导但无关键词 → 简单推理
    if features["has_formula"] and not features["has_keywords"]:
        return 0.5

    # 有关键词但无结构化推导 → 简单推理
    if features["has_keywords"] and not any(structural_signals):
        return 0.5

    # 有推导结构但无关键词 → 简单推理
    if features["has_derivation"] and not features["has_keywords"]:
        return 0.5

    # 默认：有证据但不够充分
    return 0.5


def _normalize_error_type(raw: str | None) -> str | None:
    if not raw:
        return None
    et = str(raw).strip().lower()
    mapping = {
        "math_error": "mathematical_error",
    }
    et = mapping.get(et, et)
    if et not in _VALID_ERROR_TYPES:
        return "other"
    return et


def apply_proof_aware_evaluation(
    inference: InferenceResult,
    parsed: dict,
) -> dict:
    """
    后处理 judge 结果，执行 3 步判断流程 + 错误分类规则。

    流程（与 JUDGE_SYSTEM_PROMPT 一致）：
    Step 1: 检查最终数学结论正确性
    Step 2: 检查推理过程是否存在严重逻辑错误
    Step 3: 检查证明完整度（incomplete ≠ 数学错误）

    核心原则：
    - 结论正确 → is_correct=true（不可因证明不足而判错）
    - 结论正确 + 证明不足 → error_type=incomplete
    - 结论错误 → is_correct=false
    - 结论正确 + 核心逻辑错误 → is_correct=false, error_type=reasoning_error
    """
    out = dict(parsed)
    out["error_type"] = _normalize_error_type(out.get("error_type"))
    conclusion_ok = out.get("conclusion_correct")
    if conclusion_ok is None:
        conclusion_ok = out.get("is_correct", False)
    out["conclusion_correct"] = bool(conclusion_ok)

    # 计算 proof_quality_score 并注入输出
    pq_score = proof_quality_score(inference)
    out["proof_quality_score"] = pq_score

    proof_required = is_proof_problem(inference.question)
    has_proof = inference_has_proof(inference)

    # ---- Step 1: 结论错误 → is_correct=false ----
    if not conclusion_ok:
        out["is_correct"] = False
        if not out.get("error_type") or out.get("error_type") in (
            "incomplete", "formatting_error"
        ):
            out["error_type"] = "mathematical_error"
        return out

    # ---- Step 2: 结论正确，检查逻辑错误 ----
    # reasoning_error / logic_error 表示核心逻辑有问题
    # 但对于非证明题，如果结论正确，小推理瑕疵不应判错
    if out.get("error_type") in ("reasoning_error", "logic_error"):
        if proof_required and pq_score == 0:
            # 证明题 + 无任何证明 + 逻辑错误标记 → 可能是 judge 把"无证明"误判为逻辑错误
            out["is_correct"] = True
            out["error_type"] = "incomplete"
        elif not proof_required:
            # 计算题 + 结论正确 + 推理瑕疵 → 不判错
            out["is_correct"] = True
            # 保留 reasoning_error 标记但不影响 is_correct
        # 证明题 + 有证明 + 真正的逻辑错误 → 保持 is_correct=false
        return out

    # ---- Step 3: 结论正确 + 无逻辑错误，检查证明完整度 ----

    # Rule A: 结论正确但被判定为 mathematical_error / calculation_error
    # → judge 误判，修正为 incomplete + is_correct=true
    if out.get("error_type") in ("mathematical_error", "calculation_error"):
        out["is_correct"] = True
        if proof_required and pq_score == 0:
            out["error_type"] = "incomplete"
            if not out.get("explanation"):
                out["explanation"] = "数学结论正确，但缺少证明过程。"
        else:
            out["error_type"] = None
            if not out.get("explanation"):
                out["explanation"] = "数学结论正确，不应判定为数学错误。"
        return out

    # Rule B: 证明题 + 结论正确 + 完全无证明（quality=0）
    # → is_correct=true, error_type=incomplete
    if proof_required and pq_score == 0:
        out["is_correct"] = True
        out["error_type"] = "incomplete"
        if not out.get("explanation"):
            out["explanation"] = "数学结论正确，但证明题缺少证明或推导过程。"
        return out

    # Rule C: 结论正确 + incomplete → 确保 is_correct=true
    if out.get("error_type") == "incomplete":
        out["is_correct"] = True
        # 如果有证明内容（quality > 0），可以清除 incomplete 标记
        if pq_score >= 0.5 and not proof_required:
            out["error_type"] = None
        return out

    # Rule D: 结论正确 + formatting_error → is_correct=true
    if out.get("error_type") == "formatting_error":
        out["is_correct"] = True
        return out

    # Rule E: 结论正确 + 无 error_type → is_correct=true
    if not out.get("error_type"):
        out["is_correct"] = True

    # 最终安全网：结论正确 → is_correct 必须为 true
    if conclusion_ok:
        out["is_correct"] = True

    return out


# ==================== 参考答案等价比较（评分宽容化） ====================
# 当参考答案存在时，用归一化文本 / 数值 / SymPy / 候选集合四种方式比较
# 模型答案与参考答案。若等价，则强制判定正确，覆盖 LLM 对等价表述的误判。
# 移植自 imo_bench_eval/scorer.py，SymPy 不可用时静默降级为字符串比较。

# LaTeX 扩展命令：排版用，不影响数学含义
_REF_LATEX_SPACING = re.compile(
    r"\\displaystyle|\\textstyle|\\scriptstyle|\\scriptscriptstyle"
    r"|\\qquad|\\quad|\\;|\\,|\\!|\\:|\\ |\\enspace"
    r"|\\thinspace|\\medspace|\\thickspace|\\negthinspace|\\negmedspace|\\negthickspace"
)
_REF_WHITESPACE_NORM = re.compile(r"\s+")


def _normalize_answer(text: str) -> str:
    """规范化数学答案文本（移植自 imo_bench_eval/scorer.py）。"""
    if not text:
        return ""
    # 0. 去除中文/英文自然语言前缀（答案为、答案是、Answer: 等）
    text = re.sub(
        r"^(?:答案为|答案是|答案[:：]|answer\s*(?:is|:)?"
        r"|final\s*answer\s*(?:is|:)?)\s*",
        "", text, flags=re.IGNORECASE,
    )
    # 1. 去除 LaTeX 扩展命令
    text = _REF_LATEX_SPACING.sub("", text)
    # 1.5 分数变体（\\dfrac / \\tfrac 等）统一为 \\frac，便于后续转换
    text = re.sub(r"\\[dt]frac", r"\\frac", text)
    # 2. 转换 \\frac{a}{b} → a/b（先处理最内层，再处理外层）
    for _ in range(4):
        new = re.sub(r"\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
                     r"\1/\2", text)
        if new == text:
            break
        text = new
    # 3. 去除 \\boxed{...} 包装（支持一层嵌套，如 \\boxed{\\frac{1}{2}}）
    for _ in range(4):
        new = re.sub(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", text)
        if new == text:
            break
        text = new
    # 4. 去除 \\text{...} 包装
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    # 5. 去除 $$ 和 $ 定界符
    text = text.replace("$$", "").replace("$", "")
    # 6. 去除 \\left/\\right 定界符命令（\\left\\lfloor → \\lfloor，不影响含义）
    text = re.sub(r"\\left(?=[\\{])", "", text)
    text = re.sub(r"\\right(?=[\\}])", "", text)
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)([()\[\]|{}])", r"\1", text)
    # 7. 统一 \\cdot → *（等价含义）
    text = re.sub(r"\\cdot|\\times", "*", text)
    # 8. 去掉单字符大括号 {a} → a（如 \\log_{2} → \\log_2）
    text = re.sub(r"\{([^}]{1})\}", r"\1", text)
    # 9. 删除所有空白（LaTeX 数学模式中空格无语义，\\log_2 a ≡ \\log_2a）
    text = _REF_WHITESPACE_NORM.sub("", text)
    # 10. 提取简单等式的右值 (x = 1 → 1)
    text = _extract_equation_rhs(text)
    # 11. 去尾部句号
    text = text.strip().rstrip(".")
    return text.strip()


def _extract_equation_rhs(text: str) -> str:
    """如果形如 'x = 1'，提取右值 '1'"""
    m = re.match(r'^\w+\s*=\s*(.+)$', text.strip())
    if m:
        return m.group(1).strip()
    return text


def _try_parse_number(text: str):
    """尝试将文本解析为数字（含分数、千分位、百分比）。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    # 千分位逗号：1,000 → 1000
    if re.match(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$", text):
        text = text.replace(",", "")
    # 百分比：50% → 0.5
    m = re.match(r"^(-?\d+(?:\.\d+)?)%$", text)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    # 直接数字（float 同时支持科学计数法如 2.048e3）
    try:
        return float(text)
    except ValueError:
        pass
    # 简单分数 a/b
    m = re.match(r"^(-?\d+)\s*/\s*(-?\d+)$", text)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den != 0:
            return num / den
    # 负无穷、∞ 等特殊值（视为不可数值比较）
    if text.lower() in ("inf", "infty", "\\infty", "infinity", "no solution"):
        return None
    return None


def _sympy_equivalent(pred: str, ref: str):
    """用 SymPy 判断两个 LaTeX 数学表达式是否符号等价。

    处理归一化后仍不相同的等价写法，例如：
      \\lfloor \\log_2 a \\rfloor + 1  vs  \\left\\lfloor \\log_{2}a\\right\\rfloor + 1
      \\frac{1}{2} vs 0.5  vs \\tfrac{1}{2}
    若 SymPy 不可用或解析失败，返回 (False, "")。
    """
    if not pred or not ref:
        return False, ""
    try:
        from utils.sympy_tools import are_expressions_equal
    except Exception:
        return False, ""
    if are_expressions_equal(pred, ref):
        return True, "Symbolically equivalent (SymPy)"
    return False, ""


def _compare_alternative_sets(pred: str, ref: str):
    """比较候选答案集合：答案用 or / 逗号分隔多个候选时，逐一匹配。

    返回 (是否匹配, 说明)。任一无法拆分则返回 (False, "")。
    """
    if not pred or not ref:
        return False, ""

    def split_candidates(text: str):
        """把答案拆成候选列表。逗号可能出现在 {a,b} 集合或 (a,b) 坐标中，
        这里只按顶层逗号和 "or" 拆分。"""
        text = re.sub(r"(?i)\bor\b", ",", text)
        text = re.sub(r"for\s+(?:some|any)\s+.*$", "", text)
        text = re.sub(r"with\s+(?:some|any)\s+.*$", "", text)
        parts, depth = [], 0
        cur = []
        for ch in text:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            if ch == "," and depth == 0:
                p = "".join(cur).strip().rstrip(".,;").strip()
                if p:
                    parts.append(p)
                cur = []
            else:
                cur.append(ch)
        p = "".join(cur).strip().rstrip(".,;").strip()
        if p:
            parts.append(p)
        return parts

    sp = split_candidates(pred)
    sr = split_candidates(ref)

    # 如果两边拆出来的候选数都不超过 1，说明没有候选结构，不适用
    if len(sp) <= 1 and len(sr) <= 1:
        return False, ""

    def is_mathy(s: str) -> bool:
        return any(c in s for c in "=^\\{}/") or any(c.isdigit() for c in s)

    sp_math = [p for p in sp if is_mathy(p)]
    sr_math = [r for r in sr if is_mathy(r)]
    if not sp_math or not sr_math:
        return False, ""

    def contained(p: str, r: str) -> bool:
        return p in r or r in p

    for r in sr_math:
        if not any(contained(r, p) or _sympy_equivalent(r, p)[0] or _sympy_equivalent(p, r)[0]
                   for p in sp_math):
            return False, f"参考候选 '{r}' 未在预测中找到"
    for p in sp_math:
        if not any(contained(p, r) or _sympy_equivalent(p, r)[0] or _sympy_equivalent(r, p)[0]
                   for r in sr_math):
            return False, f"预测候选 '{p}' 在参考中不存在"
    return True, "Alternative answer set matched"


def _answers_equivalent(pred: str, ref: str) -> bool:
    """判断模型答案与参考答案是否等价（归一化精确 / 数值 / SymPy / 候选集合）。"""
    if not pred or not ref:
        return False

    np_ = _normalize_answer(pred)
    nr_ = _normalize_answer(ref)
    logger.debug(
        f"[AnswerEquiv] pred_raw={pred!r} ref_raw={ref!r} "
        f"pred_norm={np_!r} ref_norm={nr_!r}"
    )
    if np_ and nr_ and np_ == nr_:
        return True

    # 数值比较
    pn = _try_parse_number(np_)
    rn = _try_parse_number(nr_)
    if pn is not None and rn is not None and abs(pn - rn) < 1e-9:
        return True

    # SymPy 符号等价
    sympy_ok, _ = _sympy_equivalent(pred, ref)
    if sympy_ok:
        return True

    # 候选集合比较
    alt_ok, _ = _compare_alternative_sets(np_, nr_)
    return alt_ok


def apply_reference_leniency(
    inference: InferenceResult,
    parsed: dict,
    reference_answer: str = None,
) -> dict:
    """评分宽容化：有参考答案且模型答案与参考答案等价时，强制判定正确。

    在 apply_proof_aware_evaluation 之后调用，覆盖 LLM 对等价表述的误判：
    - 归一化文本等价（如 LaTeX 写法差异、$ 定界符、空白差异）
    - 数值等价（分数/小数、1/2 vs 0.5）
    - SymPy 符号等价（不同 LaTeX 写法）
    - 候选集合等价（or/逗号分隔的多候选答案）

    与旧版的关键差异：**不再静默覆盖 DeepSeek 原始判分**。
    - 等价匹配时仅把 is_correct / conclusion_correct 置为 True，
      原始 confidence 与 error_type 保持不变（不拉高、不清空）。
    - 新增 reference_matched 标记与 judge_raw 字段，保存兜底前的判分，
      使"参考答案兜底判对"与"DeepSeek 本身判对"可区分、可审计。

    不等价或无参考答案时原样返回（附带默认关闭的兜底标记）。
    """
    out = dict(parsed)
    # 兜底标记默认关闭；judge_raw 保存兜底前的判分（DeepSeek + proof-aware 规则修正）
    if "reference_matched" not in out:
        out["reference_matched"] = False
    if "judge_raw" not in out:
        out["judge_raw"] = {
            "is_correct": bool(out.get("is_correct", False)),
            "confidence": out.get("confidence"),
            "error_type": out.get("error_type"),
        }

    if not reference_answer:
        logger.debug(
            f"[Judge {inference.problem_id}] leniency skipped: no reference_answer"
        )
        return out
    model_answer = inference.answer or ""
    if not model_answer:
        logger.debug(
            f"[Judge {inference.problem_id}] leniency skipped: empty model_answer"
        )
        return out
    if parsed.get("is_correct"):
        return out
    if not _answers_equivalent(model_answer, reference_answer):
        logger.debug(
            f"[Judge {inference.problem_id}] leniency skipped: not equivalent "
            f"model={model_answer!r} ref={reference_answer!r}"
        )
        return out

    # 参考答案等价：最终判定正确，但不静默覆盖原始 confidence / error_type
    out["is_correct"] = True
    out["conclusion_correct"] = True
    out["reference_matched"] = True
    explanation = out.get("explanation") or ""
    note = (
        "[参考答案兜底] 模型答案与参考答案等价，最终判定为正确。"
        "（DeepSeek 原始判分见 judge_raw，未被覆盖。）"
    )
    if explanation:
        out["explanation"] = f"{note}\n{explanation}"
    else:
        out["explanation"] = note
    logger.info(
        f"[Judge {inference.problem_id}] reference answer equivalent match: "
        f"model='{model_answer[:80]}' ref='{reference_answer[:80]}'"
    )
    return out


def _parse_single_result(parsed: dict) -> dict:
    """
    从解析后的评判 JSON 中提取标准化的判定字段。
    """
    conclusion_correct = parsed.get("conclusion_correct")
    if conclusion_correct is None:
        conclusion_correct = parsed.get("is_correct", False)
    return {
        "is_correct": bool(parsed.get("is_correct", False)),
        "confidence": float(parsed.get("confidence", 0.5)),
        "explanation": str(parsed.get("explanation", "")),
        "error_type": _normalize_error_type(parsed.get("error_type")),
        "correct_answer": parsed.get("correct_answer"),
        "conclusion_correct": bool(conclusion_correct),
    }


def parse_judge_response(raw_content: str) -> dict:
    """
    解析 DeepSeek 评判响应，提取正确性判定和置信度。
    """
    parsed = extract_json_from_text(raw_content)
    if parsed and isinstance(parsed, dict):
        return _parse_single_result(parsed)

    lower = raw_content.lower()
    is_correct = any(kw in lower or kw in raw_content for kw in _POSITIVE_KEYWORDS)
    return {
        "is_correct": is_correct,
        "confidence": _FALLBACK_CONFIDENCE,
        "explanation": raw_content[:500],
        "error_type": None,
        "correct_answer": None,
        "conclusion_correct": is_correct,
    }


def _extract_partial_json_objects(text: str) -> list[dict]:
    """
    从可能被截断的文本中尽力恢复多个 JSON 对象。

    用 json.JSONDecoder().raw_decode 从文本开头逐个扫描 "{...}" 对象，
    跳过非 JSON 前缀；解析失败的片段跳过，继续向后扫描。
    """
    if not text:
        return []
    objs: list[dict] = []
    decoder = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n，,;；':
            i += 1
            continue
        if c == "{":
            try:
                obj, end = decoder.raw_decode(text, i)
            except (json.JSONDecodeError, ValueError):
                i += 1
                continue
            if isinstance(obj, dict):
                objs.append(obj)
            i = end
        elif c == "[":
            # 遇到数组，直接尝试解析整个数组（可能是完整 JSON array）
            try:
                arr, end = decoder.raw_decode(text, i)
            except (json.JSONDecodeError, ValueError):
                i += 1
                continue
            if isinstance(arr, list):
                return [it for it in arr if isinstance(it, dict)]
            i = end
        else:
            i += 1
    return objs


def parse_judge_batch_response(
    raw_content: str, expected_ids: list[str]
) -> list[dict]:
    """
    解析 DeepSeek 批量评判响应，返回每道题的判定字典列表。

    匹配策略（层级 fallback）：
    1. 优先按短 ID 匹配：从响应中提取 "problem_index" 字段（如 "P1"/"P2"），
       与预期的 short_id 对照。
    2. short_id 缺失 → 回退到 position_index（按 JSON 数组位置）。
    3. position_index 缺失 → 回退到 problem_id 精确匹配（兼容旧格式）。
    4. 以上都失败 → 标记为空，回到 retry_fallback_ids 等待单题兜底。

    参数:
        raw_content: DeepSeek API 返回的原始文本
        expected_ids: 期望的题目 problem_id 列表（用于按序组装，非匹配用）

    返回:
        ({result_dicts_by_position}, missing_positions_list)
        位置 i 的结果可能为 None（表示需要单题兜底）。
    """
    parsed = extract_json_from_text(raw_content)
    results_map = {}         # "P1" → result_dict
    position_results = {}    # 0 → result_dict (按数组位置)
    pid_results_map = {}     # problem_id → result_dict (旧格式兼容)

    items = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        inner = parsed.get("results") or parsed.get("judgements")
        if isinstance(inner, list):
            items = inner

    # 整体解析失败（如截断/格式偏离）时，尽力恢复部分 JSON 对象
    if not items:
        partial_items = _extract_partial_json_objects(raw_content)
        if partial_items:
            logger.warning(
                f"[Batch Judge Parse] Full parse failed, "
                f"recovered {len(partial_items)} partial JSON object(s)"
            )
            items = partial_items

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        result = _parse_single_result(item)
        # 策略 1: 按 short_id 匹配
        short = item.get("problem_index", "")
        if short:
            results_map[str(short).strip()] = result
        # 策略 2: 按位置（作为 fallback）
        position_results[idx] = result
        # 策略 3: 按 problem_id（旧格式兼容，作为最弱 fallback）
        pid = item.get("problem_id", "")
        if pid:
            pid_results_map[str(pid).strip()] = result

    output = []
    missing = []
    for i, pid in enumerate(expected_ids):
        short_id = f"P{i + 1}"
        if short_id in results_map:
            output.append(results_map[short_id])
        elif i in position_results:
            # 如果模型没有正确输出 problem_index，按位置匹配
            logger.warning(
                f"[Batch Judge Parse] No P{i+1} in response, "
                f"using position-based match for {pid}"
            )
            output.append(position_results[i])
        elif pid in pid_results_map:
            # 最后尝试旧格式 problem_id 精确匹配
            logger.warning(
                f"[Batch Judge Parse] No P{i+1} or position match, "
                f"using pid-based match for {pid}"
            )
            output.append(pid_results_map[pid])
        else:
            logger.warning(
                f"[Batch Judge Parse] No match for P{i+1} ({pid}), "
                f"marking for single-judge fallback"
            )
            output.append(None)
            missing.append(i)
    return output, missing


def _build_judge_user_prompt(
    inference: InferenceResult,
    reference_answer: str = None,
    answer_source: str = None,
) -> str:
    """
    构建单题评判的 user prompt。

    参数:
        inference: 推理结果
        reference_answer: 参考答案（可选）
        answer_source: 参考答案来源说明（可选）

    返回:
        结构化的 user prompt 字符串
    """
    # 送审前按 token 精简答案与推理文本，避免超长推理撑爆输出导致截断
    is_proof = is_proof_problem(inference.question)
    answer_text, reasoning_text = _prepare_item_text(
        inference.answer, inference.reasoning, is_proof
    )

    steps_text = (
        chr(10).join(f"- {s}" for s in inference.steps)
        if inference.steps else "N/A"
    )

    reference_section = ""
    if reference_answer:
        source_info = (
            f"(Source: {answer_source})" if answer_source else ""
        )
        reference_section = f"""
## Reference Answer (Ground Truth)
{reference_answer}

{source_info}

**IMPORTANT**: The reference answer above is from an official solution manual.
Use it as the ground truth when judging correctness.
If the model's answer matches the reference answer
(considering equivalent forms), mark it as correct.
If the model's answer contradicts the reference answer, mark it as incorrect."""

    # 若存在多候选模式，补充选中候选的完整推理作为裁判依据（同样按 token 精简）
    candidate_section = ""
    if (inference.candidates
            and inference.selected_candidate_index is not None
            and inference.selected_candidate_index < len(inference.candidates)):
        sel_candidate = inference.candidates[inference.selected_candidate_index]
        cand_answer = sel_candidate.get("answer", "")
        cand_reasoning = sel_candidate.get("reasoning", "")
        cand_confidence = sel_candidate.get("confidence", "")
        # 精简候选推理文本，避免完整候选证明（可达数千 token）撑爆判题输出
        _, cand_reasoning = _prepare_item_text(
            cand_answer, cand_reasoning, is_proof
        )
        candidate_section = f"""
## Selected Candidate Full Answer
{cand_answer}

## Selected Candidate Full Reasoning
{cand_reasoning}

## Selected Candidate Confidence
{cand_confidence}
"""

    return f"""## Math Problem
{inference.question}
{reference_section}
## Model's Answer
{answer_text}

## Model's Reasoning
{reasoning_text}
{candidate_section}
## Model's Steps
{steps_text}

Please judge whether the answer is correct."""


def _rescue_answer_for_judge(inference: InferenceResult) -> str:
    """判题前答案兜底：answer 为空时从推理文本中提取最终答案（纯规则，不消耗 LLM 预算）。"""
    if inference.answer:
        return inference.answer
    for text in (inference.reasoning, inference.raw_response):
        if not text:
            continue
        try:
            from utils.extract import rescue_final_answer
            answer, _ = rescue_final_answer(text)
            if answer:
                return answer
        except Exception:
            # 导入或解析失败不影响主流程
            pass
    return ""


async def run_judge(
    inference: InferenceResult,
    reference_answer: str = None,
    answer_source: str = None,
) -> JudgeResult:
    """
    对单道推理结果进行评判。

    参数:
        inference: Intern-S1 的推理结果
        reference_answer: 从答案库匹配的参考答案（可选，有则大幅提升准确率）
        answer_source: 参考答案来源说明

    返回:
        JudgeResult 对象
    """
    # 空答案兜底：从推理文本中提取，保证参考答案等价判对可生效
    if not inference.answer:
        rescued_answer = _rescue_answer_for_judge(inference)
        if rescued_answer:
            logger.info(
                f"[Judge {inference.problem_id}] rescued empty answer: "
                f"{rescued_answer!r}"
            )
            inference.answer = rescued_answer
    cfg = get_config()
    client = LLMClient(cfg.deepseek)

    user_content = _build_judge_user_prompt(
        inference, reference_answer, answer_source
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # 动态计算单题输出 token：按精简后输入长度放大，避免长推理撑爆输出被截断
    input_tokens = _estimate_tokens(user_content) + _estimate_tokens(JUDGE_SYSTEM_PROMPT)
    max_tokens = min(max(_JUDGE_MAX_TOKENS, input_tokens), _JUDGE_SINGLE_MAX_TOKENS)

    logger.info(
        f"[Judge {inference.problem_id}] prompt length: "
        f"system={len(JUDGE_SYSTEM_PROMPT)}, user={len(user_content)}, "
        f"max_tokens={max_tokens}"
    )
    start_time = time.time()
    try:
        response = await client.chat(
            messages=messages,
            temperature=_JUDGE_TEMPERATURE,
            max_tokens=max_tokens,
        )
        latency = round(time.time() - start_time, 2)

        # 截断降级链：首次截断 → 用输出上限重试一次；仍截断 → 明确失败，不再基于不完整内容判分
        if response.get("is_truncated") or response.get("content_truncated"):
            logger.warning(
                f"[Judge {inference.problem_id}] truncated "
                f"(is_truncated={response.get('is_truncated')}, "
                f"content_truncated={response.get('content_truncated')}). "
                f"Retrying with max_tokens={_JUDGE_SINGLE_MAX_TOKENS}..."
            )
            retry_start = time.time()
            retry_response = await client.chat(
                messages=messages,
                temperature=_JUDGE_TEMPERATURE,
                max_tokens=_JUDGE_SINGLE_MAX_TOKENS,
            )
            retry_latency = round(time.time() - retry_start, 2)
            if not (retry_response.get("is_truncated") or retry_response.get("content_truncated")):
                response = retry_response
                latency += retry_latency
                logger.info(
                    f"[Judge {inference.problem_id}] retry succeeded "
                    f"with {_JUDGE_SINGLE_MAX_TOKENS} tokens"
                )
            else:
                # 重试仍截断：明确标记为判分失败，绝不基于不完整内容判分
                latency += retry_latency
                logger.error(
                    f"[Judge {inference.problem_id}] retry still truncated, "
                    f"marking judge as failed"
                )
                return JudgeResult(
                    problem_id=inference.problem_id,
                    is_correct=False,
                    confidence=0.0,
                    explanation=(
                        "判题输出在重试后仍被截断，本次判分失败，"
                        "未基于不完整内容给分。请人工复核。"
                    ),
                    error_type=None,
                    correct_answer=None,
                    raw_response=response["content"],
                    tokens_used=response.get("tokens_used", 0),
                    latency_seconds=latency,
                    error="judge truncated after retries",
                )

        parsed = parse_judge_response(response["content"])
        parsed = apply_proof_aware_evaluation(inference, parsed)
        # 评分宽容化：参考答案等价时强制判定正确（不静默覆盖原始判分）
        parsed = apply_reference_leniency(inference, parsed, reference_answer)
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=parsed["is_correct"],
            confidence=parsed["confidence"],
            explanation=parsed["explanation"],
            error_type=parsed.get("error_type"),
            correct_answer=parsed.get("correct_answer"),
            raw_response=response["content"],
            tokens_used=response.get("tokens_used", 0),
            latency_seconds=latency,
            error=None,
            reference_matched=parsed.get("reference_matched", False),
            judge_raw=parsed.get("judge_raw"),
        )
    except asyncio.TimeoutError as te:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Judge timeout for [{inference.problem_id}]: {te}")
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=False,
            confidence=0.0,
            explanation="Judge timeout: answer may be too long or service is slow.",
            raw_response="",
            latency_seconds=latency,
            error=str(te),
        )
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(f"Judge failed for [{inference.problem_id}]: {e}")
        return JudgeResult(
            problem_id=inference.problem_id,
            is_correct=False,
            confidence=0.0,
            explanation=f"Judge error: {e}",
            raw_response="",
            latency_seconds=latency,
            error=str(e),
        )


async def run_judge_batch(
    inferences: list[InferenceResult],
    reference_map: dict[str, tuple[str, str]] | None = None,
    batch_size: int = 3,
) -> list[JudgeResult]:
    """
    对多道推理结果进行批量评判，按 batch_size 分批调用，避免上下文过长
    导致答案被截断或 JSON 解析失败。

    参数:
        inferences: 多个 InferenceResult 列表
        reference_map: {problem_id: (answer_text, source)} 可选参考答案映射
        batch_size: 每批最多评判的题目数，默认 3

    返回:
        与 inferences 等长的 JudgeResult 列表。
        如果某一批调用失败，该批内题目单独走逐题评判作为兜底。
    """
    if not inferences:
        return []

    cfg = get_config()
    client = LLMClient(cfg.deepseek)
    all_results: list[JudgeResult] = []

    # 按推理长度动态分批：长推理题自动单独成批或小批，短题合并，
    # 避免超长推理塞进同一 prompt 导致输出被 max_tokens 截断。
    # batch_size 参数保留以兼容旧调用，但不再作为硬切分依据。
    batches = _build_dynamic_batches(inferences)

    for chunk_index, chunk in enumerate(batches, 1):
        chunk_results = await _run_judge_batch_chunk(
            client, chunk, reference_map, chunk_index
        )
        all_results.extend(chunk_results)

    return all_results


async def _fallback_single_judge(
    inferences: list[InferenceResult],
    reference_map: dict[str, tuple[str, str]] | None,
    latency: float,
) -> list[JudgeResult]:
    """批量判分截断重试失败后，逐题调用单题评判兜底，保证判分完整。"""
    fallback_results = []
    for inf in inferences:
        try:
            ref = reference_map.get(inf.problem_id) if reference_map else None
            ref_answer = ref[0] if ref else None
            ref_source = ref[1] if ref else None
            judge = await run_judge(
                inf,
                reference_answer=ref_answer,
                answer_source=ref_source,
            )
            fallback_results.append(judge)
        except Exception as inner_e:
            logger.error(
                f"[Batch Judge] Single fallback failed for {inf.problem_id}: {inner_e}"
            )
            fallback_results.append(JudgeResult(
                problem_id=inf.problem_id,
                is_correct=False,
                confidence=0.0,
                explanation=f"Judge fallback error: {inner_e}",
                raw_response="",
                latency_seconds=latency,
                error=str(inner_e),
            ))
    return fallback_results


async def _run_judge_batch_chunk(
    client: LLMClient,
    inferences: list[InferenceResult],
    reference_map: dict[str, tuple[str, str]] | None,
    chunk_index: int,
) -> list[JudgeResult]:
    """评判一个批次，失败时自动 fallback 到单题评判。"""
    # 构建批量 prompt：依次列出每道题的信息
    items_text = ""
    for i, inf in enumerate(inferences):
        steps_text = (
            chr(10).join(f"- {s}" for s in inf.steps)
            if inf.steps else "N/A"
        )

        ref_section = ""
        if reference_map and inf.problem_id in reference_map:
            ans, src = reference_map[inf.problem_id]
            source_info = f"(Source: {src})" if src else ""
            ref_section = (
                f"\n### Reference Answer (Ground Truth)\n{ans}\n"
                f"{source_info}\n**Use this as ground truth.**"
            )

        # 送审前按 token 精简答案与推理（按题型区分力度），避免超长推理撑爆整批输出
        is_proof = is_proof_problem(inf.question)
        answer_text, reasoning_text = _prepare_item_text(
            inf.answer, inf.reasoning, is_proof
        )

        items_text += (
            f"\n--- P{i + 1} ---\n"
            f"**Problem ID**: {inf.problem_id}\n\n"
            f"**Question**: {inf.question}\n"
            f"{ref_section}\n\n"
            f"**Model's Answer**: {answer_text}\n\n"
            f"**Model's Reasoning**: {reasoning_text}\n\n"
            f"**Model's Steps**:\n{steps_text}\n"
        )

    system_prompt = JUDGE_BATCH_SYSTEM_PROMPT.format(count=len(inferences))
    user_content = (
        f"Please judge each of the following {len(inferences)} math "
        f"problems independently.\n"
        f"Output a JSON array with one judgment per problem.\n\n"
        f"{items_text}\n\n"
        f"Remember: Output ONLY a JSON array, one object per problem, "
        f"preserving order."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info(
        f"[Batch Judge] Chunk {chunk_index}: prompt length "
        f"system={len(system_prompt)}, user={len(user_content)}"
    )
    start_time = time.time()
    try:
        logger.info(
            f"[Batch Judge] Chunk {chunk_index}: sending {len(inferences)} "
            f"problems together..."
        )
        # 动态计算批量输出 token：按输入长度与题数放大，上限 _JUDGE_BATCH_MAX_TOKENS_CAP
        input_tokens = _estimate_tokens(user_content) + _estimate_tokens(system_prompt)
        max_tokens = min(
            max(
                _JUDGE_BATCH_MAX_TOKENS,
                len(inferences) * _JUDGE_BATCH_TOKEN_PER_ITEM,
                input_tokens,
            ),
            _JUDGE_BATCH_MAX_TOKENS_CAP,
        )
        response = await client.chat(
            messages=messages,
            temperature=_JUDGE_TEMPERATURE,
            max_tokens=max_tokens,
        )
        latency = round(time.time() - start_time, 2)

        # 截断降级链：首次截断 → 用输出上限重试一次；仍截断 → 拆分为单题逐一重判
        truncated = bool(
            response.get("is_truncated") or response.get("content_truncated")
        )
        if truncated:
            logger.warning(
                f"[Batch Judge] Chunk {chunk_index} truncated "
                f"(is_truncated={response.get('is_truncated')}, "
                f"content_truncated={response.get('content_truncated')}). "
                f"Retrying with max_tokens={_JUDGE_BATCH_MAX_TOKENS_CAP}..."
            )
            retry_start = time.time()
            retry_response = await client.chat(
                messages=messages,
                temperature=_JUDGE_TEMPERATURE,
                max_tokens=_JUDGE_BATCH_MAX_TOKENS_CAP,
            )
            retry_latency = round(time.time() - retry_start, 2)
            latency += retry_latency
            if not (retry_response.get("is_truncated") or retry_response.get("content_truncated")):
                response = retry_response
                truncated = False
                logger.info(
                    f"[Batch Judge] Chunk {chunk_index} retry succeeded "
                    f"with {_JUDGE_BATCH_MAX_TOKENS_CAP} tokens"
                )
            else:
                logger.warning(
                    f"[Batch Judge] Chunk {chunk_index} retry still truncated"
                )
                if len(inferences) > 1:
                    # 重试仍截断：拆分为单题逐一重判，绝不基于不完整内容判分
                    logger.info(
                        f"[Batch Judge] Chunk {chunk_index}: splitting into "
                        f"{len(inferences)} single-judge fallbacks..."
                    )
                    return await _fallback_single_judge(
                        inferences, reference_map, latency
                    )
                else:
                    # 单题批量仍截断：明确标记为判分失败
                    logger.error(
                        f"[Batch Judge] Chunk {chunk_index} single-item still "
                        f"truncated, marking judge as failed"
                    )
                    return [JudgeResult(
                        problem_id=inferences[0].problem_id,
                        is_correct=False,
                        confidence=0.0,
                        explanation=(
                            "判题输出在重试后仍被截断，本次判分失败，"
                            "未基于不完整内容给分。请人工复核。"
                        ),
                        error_type=None,
                        correct_answer=None,
                        raw_response=response["content"],
                        tokens_used=response.get("tokens_used", 0),
                        latency_seconds=latency,
                        error="judge truncated after retries",
                    )]

        expected_ids = [inf.problem_id for inf in inferences]
        parsed_list, missing_indices = parse_judge_batch_response(
            response["content"], expected_ids
        )

        # 缺失的题目走单题判题兜底
        if missing_indices:
            logger.warning(
                f"[Batch Judge] Chunk {chunk_index}: "
                f"{len(missing_indices)}/{len(inferences)} problems missing, "
                f"running single-judge fallback..."
            )
            for idx in missing_indices:
                inf = inferences[idx]
                try:
                    ref = reference_map.get(inf.problem_id) if reference_map else None
                    ref_answer = ref[0] if ref else None
                    ref_source = ref[1] if ref else None
                    single_result = await run_judge(
                        inf,
                        reference_answer=ref_answer,
                        answer_source=ref_source,
                    )
                    parsed_list[idx] = {
                        "is_correct": single_result.is_correct,
                        "confidence": single_result.confidence,
                        "explanation": single_result.explanation,
                        "error_type": single_result.error_type,
                        "correct_answer": single_result.correct_answer,
                        "conclusion_correct": single_result.is_correct,
                        "reference_matched": single_result.reference_matched,
                        "judge_raw": single_result.judge_raw,
                    }
                    logger.info(
                        f"[Batch Judge] Fallback succeeded for "
                        f"P{idx + 1} ({inf.problem_id})"
                    )
                except Exception as fallback_err:
                    logger.error(
                        f"[Batch Judge] Fallback failed for "
                        f"P{idx + 1} ({inf.problem_id}): {fallback_err}"
                    )
                    parsed_list[idx] = {
                        "is_correct": False,
                        "confidence": 0.0,
                        "explanation": f"Fallback error: {fallback_err}",
                        "error_type": None,
                        "correct_answer": None,
                        "conclusion_correct": False,
                    }

        judge_results = []
        for inf, parsed in zip(inferences, parsed_list):
            if parsed is None:
                # 兜底也失败，使用默认值
                parsed = {
                    "is_correct": False,
                    "confidence": _BATCH_MISSING_CONFIDENCE,
                    "explanation": "(批量响应缺失且兜底失败)",
                    "error_type": None,
                    "correct_answer": None,
                }
            parsed = apply_proof_aware_evaluation(inf, parsed)
            # 评分宽容化：参考答案等价时强制判定正确（不静默覆盖原始判分）
            ref = reference_map.get(inf.problem_id) if reference_map else None
            ref_answer = ref[0] if ref else None
            parsed = apply_reference_leniency(inf, parsed, ref_answer)
            judge_results.append(JudgeResult(
                problem_id=inf.problem_id,
                is_correct=parsed["is_correct"],
                confidence=parsed["confidence"],
                explanation=parsed["explanation"],
                error_type=parsed.get("error_type"),
                correct_answer=parsed.get("correct_answer"),
                raw_response=response["content"],
                tokens_used=response.get("tokens_used", 0),
                latency_seconds=latency,
                error=None,
                reference_matched=parsed.get("reference_matched", False),
                judge_raw=parsed.get("judge_raw"),
            ))

        logger.info(
            f"[Batch Judge] Chunk {chunk_index}: completed {len(judge_results)} "
            f"judgments in {latency}s"
        )
        return judge_results

    except Exception as e:
        latency = round(time.time() - start_time, 2)
        logger.error(
            f"[Batch Judge] Chunk {chunk_index} failed: {e}. "
            f"Falling back to single judge for {len(inferences)} problems."
        )
        # 该批次失败时，逐题兜底评判
        fallback_results = []
        for inf in inferences:
            try:
                ref = reference_map.get(inf.problem_id) if reference_map else None
                ref_answer = ref[0] if ref else None
                ref_source = ref[1] if ref else None
                judge = await run_judge(
                    inf,
                    reference_answer=ref_answer,
                    answer_source=ref_source,
                )
                fallback_results.append(judge)
            except Exception as inner_e:
                logger.error(
                    f"[Batch Judge] Single fallback failed for {inf.problem_id}: {inner_e}"
                )
                fallback_results.append(JudgeResult(
                    problem_id=inf.problem_id,
                    is_correct=False,
                    confidence=0.0,
                    explanation=f"Judge fallback error: {inner_e}",
                    raw_response="",
                    latency_seconds=latency,
                    error=str(inner_e),
                ))
        return fallback_results
