"""
Intern-S1 推理模块（独立生成 → 验证 → 选优 → 格式化）。

核心策略：一次 API 调用，让模型按国际主流数学评测流程完成：
  1. Independent Solution Generation — 三条 genuinely different 解法路径
  2. Solution Verification — 自评数学正确性（非仅文笔）
  3. Final Selection — 按正确性/证明质量/完整度综合选优
  4. Answer Formatting — 统一 JSON 输出
"""
import asyncio
import json
import logging
import re
import time
from typing import Optional

from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import Problem, InferenceResult
from deepseek import _detect_proof_features

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

# Answer Validation Layer：空答案 / 证明题缺证明 时的最大重试次数
_VALIDATION_MAX_RETRIES = 2

# 证明题检测 — 从题型检测模块导入（统一管理 18 种题型规则）
from problem_type_detector import is_proof_problem  # noqa: E402

# 裸答案（仅数字/单字母选项，无过程）
_BARE_ANSWER_RE = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?(?:/[0-9]+)?|[A-Da-d])\s*$"
)

# ==================== 系统提示词 ====================

SYSTEM_PROMPT = """You are an expert mathematical problem solver following an international math-reasoning evaluation pipeline.

PIPELINE (you MUST follow in order):

PHASE 1 — INDEPENDENT SOLUTION GENERATION
Generate exactly THREE candidate solutions. Each candidate MUST use a genuinely DIFFERENT method or starting point (not paraphrases):
- Candidate 0: direct / algebraic / computational approach
- Candidate 1: alternative theorem, substitution, or geometric view
- Candidate 2: third distinct path (contradiction, induction, invariant, etc.)

PHASE 2 — SOLUTION VERIFICATION (per candidate)
For each candidate, verify MATHEMATICAL correctness (not writing style):
- confidence: 0.0–1.0 = your estimate that the FINAL CONCLUSION is mathematically correct
- verification_score: 0.0–1.0 = independent verification of this candidate:
  * Does the final answer satisfy the problem requirements?
  * Are there obvious logic jumps in the reasoning?
  * Are key conditions from the problem statement missing?
  * Is the proof/derivation structure sound?
- verification_confidence: 0.0–1.0 = how confident you are in your verification_score assessment
  (1.0 = very sure the score is accurate, 0.5 = uncertain, 0.0 = no basis to judge)
- proof_quality_score: 0.0–1.0 = quality of the mathematical proof/derivation
  (0.0 = no proof, 0.5 = simple reasoning, 1.0 = complete rigorous proof)
- strength: why the mathematics is sound
- weakness: specific mathematical gap or error risk (if any)

PHASE 3 — FINAL SELECTION
Select the candidate with the best COMBINED mathematical merit:
- Priority 1: highest verification_score (independent verification of correctness)
- Priority 2: likely correct final conclusion (confidence)
- Priority 3: proof / derivation completeness (proof_quality_score)
- Priority 4: clarity
Do NOT select only by fluency of text or highest confidence alone.
The server re-ranks candidates using a proof-aware formula:
  - base = 0.3*confidence + 0.4*verification_score + 0.3*proof_quality_score (proof problems)
  - base = 0.5*confidence + 0.5*verification_score (other problems)
  - final = base * (0.8 + 0.2 * verification_confidence)

PHASE 4 — ANSWER FORMATTING
Emit one unified JSON object (see schema below).

--- REQUIREMENTS BY PROBLEM TYPE ---

COMPUTATION / numeric / solve problems — each candidate MUST include:
- formulas used
- calculation process (not skipped)
- final result in final_answer
FORBIDDEN: bare answers like final_answer: "3" with empty proof/reasoning/steps.

PROOF problems (prove, show that, 证明, derive, explain why) — each candidate MUST include in proof (and/or reasoning + steps):
- proof goal (what is to be shown)
- key idea
- derivation steps (no jump from claim to conclusion)
- conclusion
FORBIDDEN: only a slogan conclusion (e.g. "三条中线交于重心，比例2:1") without derivation.

OUTPUT FORMAT (JSON only, no markdown fences, no extra text):
{
  "candidates": [
    {
      "index": 0,
      "final_answer": "concise final mathematical conclusion",
      "proof": "full proof or derivation (required for proof problems)",
      "reasoning": "supporting narrative and intermediate logic",
      "steps": ["step 1", "step 2"],
      "confidence": 0.0,
      "verification_score": 0.0,
      "verification_confidence": 0.5,
      "proof_quality_score": 0.0,
      "strength": "",
      "weakness": ""
    },
    { "index": 1, "...": "same fields" },
    { "index": 2, "...": "same fields" }
  ],
  "selected_index": 0,
  "selection_reasoning": "why this candidate wins on mathematical correctness and completeness",
  "final_answer": "selected candidate's final_answer"
}

CRITICAL RULES:
- Three candidates = three DIFFERENT mathematical paths
- confidence reflects mathematical correctness of the conclusion, not verbosity
- final_answer is the conclusion only; put derivations in proof / reasoning / steps
- Output raw JSON only"""


# ==================== 自审核提示词 ====================

REVIEW_SYSTEM_PROMPT = """You are a rigorous mathematical solution reviewer (international math benchmark style).

REVIEW CRITERIA:
1. MATHEMATICAL CORRECTNESS — Is the final conclusion likely correct? Any fatal calculation or logic error?
2. DERIVATION — For proof problems: is there a real proof chain (not only a slogan conclusion)?
3. COMPLETENESS — For computation: are formulas and calculation steps present (not bare final_answer)?
4. FORMAT — Valid JSON with candidates, final_answer, selected_index, selection_reasoning?

OUTPUT ONLY valid JSON:
{
  "verdict": "pass" or "fail",
  "scores": {
    "completeness": 0.0-1.0,
    "correctness": 0.0-1.0,
    "relevance": 0.0-1.0,
    "format": 0.0-1.0
  },
  "issues": ["..."],
  "suggestions": "...",
  "summary": "one-sentence verdict"
}

RULES:
- fail if JSON broken, truncated, missing final_answer, or proof problem with empty proof/reasoning/steps on ALL candidates
- fail if bare numeric answer with no derivation on a non-trivial problem
- pass if mathematics is sound and derivation adequate (proof may be concise but not empty on proof problems)
- Do NOT fail solely because a correct proof is shorter than an verbose wrong one"""


# ==================== 题型与选优辅助 ====================
# is_proof_problem 已从 problem_type_detector 统一导入，见文件顶部


def _str_field(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return str(val)
    return str(val).strip()


def _normalize_steps(raw_steps) -> list[str]:
    if not raw_steps:
        return []
    if isinstance(raw_steps, list):
        return [_str_field(s) for s in raw_steps if _str_field(s)]
    if isinstance(raw_steps, str) and raw_steps.strip():
        return [raw_steps.strip()]
    return []


def _candidate_final_answer(c: dict) -> str:
    """final_answer 优先于 legacy answer。"""
    return _str_field(
        c.get("final_answer") or c.get("answer") or ""
    )


def _candidate_proof_text(c: dict) -> str:
    """proof 优先于 reasoning；verification 作为补充。"""
    proof = _str_field(c.get("proof") or "")
    if proof:
        return proof
    reasoning = _str_field(c.get("reasoning") or "")
    if reasoning:
        return reasoning
    return _str_field(c.get("verification") or "")


def candidate_has_proof(c: dict) -> bool:
    proof = _str_field(c.get("proof") or "")
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    return bool(proof) or bool(reasoning) or len(steps) > 0


def _proof_quality_score(c: dict, proof_required: bool) -> float:
    """0~1 证明/推导质量启发式。"""
    proof = _candidate_proof_text(c)
    steps = _normalize_steps(c.get("steps"))
    score = 0.0
    if proof:
        score += min(len(proof) / 800.0, 0.55)
    if steps:
        score += min(len(steps) * 0.08, 0.35)
    markers = len(re.findall(
        r"因此|所以|故|证|设|假设|代入|得|推出|∴|Q\.?E\.?D",
        proof,
        re.IGNORECASE,
    ))
    score += min(markers * 0.04, 0.2)
    if proof_required and len(proof) < 80 and not steps:
        score *= 0.4
    return min(score, 1.0)


def _completeness_score(c: dict, proof_required: bool) -> float:
    ans = _candidate_final_answer(c)
    if not ans:
        return 0.0
    if _BARE_ANSWER_RE.match(ans):
        has_work = bool(_candidate_proof_text(c)) or _normalize_steps(c.get("steps"))
        if not has_work:
            return 0.15
    if proof_required:
        if not candidate_has_proof(c):
            return 0.2
        return min(0.5 + len(_candidate_proof_text(c)) / 1200.0, 1.0)
    has_work = bool(_candidate_proof_text(c)) or _normalize_steps(c.get("steps"))
    return 0.85 if has_work else 0.5


# ---- Phase 4: 独立验证评分 ----

# 逻辑连接词正则（用于检测推理连贯性）
_LOGIC_CONNECTORS_RE = re.compile(
    r"因此|所以|故|由此|推出|得到|可得|则|即|亦即|从而|进而|∴|⟹|=>|→"
)

# 证明结构标记正则
_PROOF_STRUCTURE_RE = re.compile(
    r"证明|因为|由于|设|令|假设|由此|因此|所以|推出|得到|可得|可知|故|则|即"
    r"|Q\.?E\.?D|矛盾|归纳|反证|构造"
)

# 计算过程标记正则
_CALC_MARKER_RE = re.compile(
    r"代入|计算|化简|解[得获]|=\s*[\d\-+/]|由.*得"
)

# 条件提取正则（用于检查推理是否覆盖题目条件）
_CONDITION_PATTERNS = [
    re.compile(r'正整数|自然数|非零|非负|大于|小于|不等于|至少|至多|至多'),
    re.compile(r'[a-zA-Z]\s*[><=≤≥≠]\s*\d+'),
    re.compile(r'[a-zA-Z]\s*\|\s*[a-zA-Z]'),
    re.compile(r'设\s+\S+\s+为'),
    re.compile(r'已知\s+[^，。；,;]+'),
    re.compile(r'若\s+[^，。；,;]+'),
    re.compile(r'当\s+[^，。；,;]+时'),
]

# 矛盾标记正则
_CONTRADICTION_RE = re.compile(r'矛盾')
_CONTRADICTION_OK_RE = re.compile(
    r'假设|反证|归谬|矛盾[。，]?(?:因此|所以|故|不|矛盾)'
)
_CONFLICT_NUM_RE = re.compile(r'([a-zA-Z])\s*=\s*(-?\d+(?:\.\d+)?)')
_NO_SOLUTION_RE = re.compile(r'不存在|无解|不能|无法')
_BARE_ANSWER_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?(?:/-?\d+)?')


def _check_answer_match(candidate_answer: str, reference_answer: str) -> float:
    """
    检查候选答案是否与参考答案匹配。

    返回:
        1.0: 完全匹配
        0.7-0.9: 数值匹配（格式不同）
        0.5: 部分匹配
        0.1: 不匹配
    """
    if not candidate_answer or not reference_answer:
        return 0.5

    ca = candidate_answer.strip().lower()
    ra = reference_answer.strip().lower()

    # 完全匹配
    if ca == ra:
        return 1.0

    # 提取数值进行比较
    ca_nums = set(_BARE_ANSWER_NUM_RE.findall(ca))
    ra_nums = set(_BARE_ANSWER_NUM_RE.findall(ra))

    if ca_nums and ra_nums:
        if ca_nums == ra_nums:
            return 0.9
        if ca_nums & ra_nums:  # 有交集
            return 0.6
        return 0.1

    # 子串匹配
    if ca in ra or ra in ca:
        return 0.7

    return 0.1


def _check_condition_satisfaction(
    c: dict, question: str, proof_required: bool
) -> float:
    """
    检查推理是否满足题目条件。

    从题目中提取关键条件（如"正整数"、"n>0"、"若...则..."），
    检查推理文本是否引用了这些条件。

    返回: 0.0 - 1.0
    """
    proof = _candidate_proof_text(c)
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    text = "\n".join([proof, reasoning] + steps).strip()

    if not text:
        return 0.0
    if not question:
        return 0.5

    # 从题目中提取条件
    conditions: list[str] = []
    for pattern in _CONDITION_PATTERNS:
        matches = pattern.findall(question)
        conditions.extend(matches)

    if not conditions:
        # 题目无明显条件约束
        return 0.7

    # 检查条件引用率
    referenced = 0
    for cond in conditions:
        if cond.lower() in text.lower():
            referenced += 1
    coverage = referenced / len(conditions)

    return min(coverage, 1.0)


def _check_contradictions(c: dict, question: str) -> float:
    """
    检查推理中是否存在明显内部矛盾。

    返回: 1.0 = 无矛盾, 0.0 = 有严重矛盾
    """
    proof = _candidate_proof_text(c)
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    text = "\n".join([proof, reasoning] + steps).strip()
    fa = _candidate_final_answer(c)

    if not text:
        return 0.5

    contradictions = 0

    # 检查1: "矛盾"出现但非反证法结构
    if _CONTRADICTION_RE.search(text):
        if not _CONTRADICTION_OK_RE.search(text):
            contradictions += 1

    # 检查2: 同一变量被赋不同值
    var_values: dict[str, str] = {}
    for m in _CONFLICT_NUM_RE.finditer(text):
        var, val = m.group(1), m.group(2)
        if var in var_values and var_values[var] != val:
            contradictions += 1
        var_values[var] = val

    # 检查3: 推理中说"无解/不存在"但final_answer非空且不含否定
    if _NO_SOLUTION_RE.search(text):
        if fa and not _NO_SOLUTION_RE.search(fa):
            contradictions += 1

    # 检查4: 同时出现"成立"和"不成立"且非反证法
    if '成立' in text and '不成立' in text:
        if not any(kw in text for kw in ['假设', '反证', '归谬']):
            contradictions += 1

    if contradictions > 0:
        return max(0.0, 1.0 - contradictions * 0.3)
    return 1.0


def _get_logic_score(c: dict) -> float:
    """提取逻辑连贯性子分数（复用 _compute_verification_score 中 Check 2 的逻辑）。"""
    proof = _candidate_proof_text(c)
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    full_text = "\n".join([proof, reasoning] + steps).strip()

    logic_markers = len(_LOGIC_CONNECTORS_RE.findall(full_text))
    if (steps and len(steps) >= 2) or (logic_markers >= 2 and len(full_text) > 50):
        return 1.0
    elif logic_markers >= 1 or (steps and len(steps) >= 1):
        return 0.5
    elif full_text:
        return 0.2
    else:
        return 0.0


def _detect_verification_disagreement(
    c: dict,
    question: str,
    proof_required: bool,
    reference_answer: Optional[str] = None,
) -> tuple[str, float]:
    """
    Phase 5: 检测验证维度之间的冲突。

    检测3类 disagreement：
    1. reference_match 高但 logic 低 — 答案对了但推理薄弱
    2. proof 高但 answer 错误 — 证明结构好但结论与参考答案不一致
    3. confidence 高但 verification 低 — 模型自评高但独立验证低

    返回: (verification_warning: str, disagreement_severity: float 0-1)
    """
    warnings: list[str] = []

    fa = _candidate_final_answer(c)
    confidence = float(c.get("confidence", 0.0) or 0.0)
    vs = float(c.get("verification_score", 0.5) or 0.5)
    pq = float(c.get("proof_quality_score", 0.0) or 0.0)

    logic_score = _get_logic_score(c)

    # Disagreement 1: reference_match 高但 logic 低
    if reference_answer and fa:
        answer_match = _check_answer_match(fa, reference_answer)
        if answer_match >= 0.7 and logic_score <= 0.3:
            warnings.append("reference_match_high_logic_low")

    # Disagreement 2: proof 高但 answer 错误
    if pq >= 0.7 and reference_answer and fa:
        answer_match = _check_answer_match(fa, reference_answer)
        if answer_match <= 0.1:
            warnings.append("proof_high_answer_wrong")

    # Disagreement 3: confidence 高但 verification 低
    if confidence >= 0.7 and vs <= 0.4:
        warnings.append("confidence_high_verification_low")

    severity = min(len(warnings) / 3.0, 1.0)
    warning_str = "; ".join(warnings) if warnings else ""

    return warning_str, severity


def _compute_verification_confidence(
    c: dict,
    question: str,
    proof_required: bool,
    reference_answer: Optional[str] = None,
    disagreement: str = "",
    disagreement_severity: float = 0.0,
) -> float:
    """
    Phase 5: 计算 verifier 对 verification_score 判断的可信度。

    高 verification_confidence = 验证器对判断有信心，可以安全使用 vs 排序。
    低 verification_confidence = 验证器不确定，不应过度惩罚 candidate。

    因素：
    1. reference_answer 可用 → +0.15（有外部参照）
    2. 验证检查一致（低方差）→ +0.1 / 不一致 → -0.1
    3. 无 disagreement → 不扣分 / 有 disagreement → -0.25 * severity
    4. 候选内容充分 → +0.05 / 内容过少 → -0.05
    5. 模型直接提供了 verification_score → +0.05

    返回: 0.1 - 1.0
    """
    vc = 0.5  # baseline

    # Factor 1: reference_answer 可用
    if reference_answer:
        vc += 0.15

    # Factor 2: 验证检查一致性（低方差 = 高可信度）
    fa = _candidate_final_answer(c)
    proof = _candidate_proof_text(c)
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    full_text = "\n".join([proof, reasoning] + steps).strip()

    check_scores: list[float] = []

    # Answer completeness
    if fa and not (_BARE_ANSWER_RE.match(fa) and not full_text):
        check_scores.append(1.0)
    elif fa:
        check_scores.append(0.3)
    else:
        check_scores.append(0.0)

    # Logic continuity
    check_scores.append(_get_logic_score(c))

    # Answer match (if reference available)
    if reference_answer and fa:
        check_scores.append(_check_answer_match(fa, reference_answer))

    # Condition satisfaction
    check_scores.append(_check_condition_satisfaction(c, question, proof_required))

    # Contradiction
    check_scores.append(_check_contradictions(c, question))

    if len(check_scores) >= 2:
        mean_score = sum(check_scores) / len(check_scores)
        variance = sum((s - mean_score) ** 2 for s in check_scores) / len(check_scores)
        std = variance ** 0.5
        if std < 0.15:
            vc += 0.1   # 检查一致，可信度高
        elif std > 0.35:
            vc -= 0.1   # 检查分歧大，可信度低

    # Factor 3: disagreement severity
    vc -= disagreement_severity * 0.25

    # Factor 4: 内容充分性
    if len(full_text) > 200:
        vc += 0.05
    elif len(full_text) < 30:
        vc -= 0.05

    # Factor 5: 模型直接提供了 verification_score
    if c.get("verification_score") is not None and c.get("_vs_from_model"):
        vc += 0.05

    return max(0.1, min(1.0, vc))


def _compute_verification_score(
    c: dict, question: str, proof_required: bool,
    reference_answer: Optional[str] = None,
) -> float:
    """
    独立验证评分（4-7项检查，每项 0.0-1.0，取平均）。

    基础检查项：
    1. 答案完整性：final_answer 非空且符合题目要求
    2. 逻辑连贯性：推理无明显逻辑跳跃
    3. 条件覆盖：推理文本充分，未遗漏关键条件
    4. 证明/计算结构：证明题有证明结构，计算题有计算过程

    数学一致性检查（Phase 4.1 新增）：
    5. 参考答案匹配：与 reference_answer 比对（仅当 reference_answer 提供时）
    6. 题目条件满足：推理是否引用了题目中的关键条件
    7. 矛盾检测：推理内部是否存在明显矛盾

    返回: 0.0 - 1.0
    """
    fa = _candidate_final_answer(c)
    proof = _candidate_proof_text(c)
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    full_text = "\n".join([proof, reasoning] + steps).strip()

    checks: list[float] = []

    # --- Check 1: Answer completeness ---
    if fa and not (_BARE_ANSWER_RE.match(fa) and not full_text):
        checks.append(1.0)
    elif fa:
        checks.append(0.3)
    else:
        checks.append(0.0)

    # --- Check 2: Logic continuity ---
    logic_markers = len(_LOGIC_CONNECTORS_RE.findall(full_text))
    if (steps and len(steps) >= 2) or (logic_markers >= 2 and len(full_text) > 50):
        checks.append(1.0)
    elif logic_markers >= 1 or (steps and len(steps) >= 1):
        checks.append(0.5)
    elif full_text:
        checks.append(0.2)
    else:
        checks.append(0.0)

    # --- Check 3: Condition coverage ---
    # 启发式：文本长度 + 问题关键词引用率
    text_len = len(full_text)
    coverage = 0.0
    if question and full_text:
        q_keywords = set(re.findall(r"[\u4e00-\u9fff]{2,}", question))
        if q_keywords:
            referenced = sum(1 for kw in q_keywords if kw in full_text)
            coverage = referenced / len(q_keywords)
    if text_len > 300 or (coverage >= 0.3 and text_len > 150):
        checks.append(1.0)
    elif text_len > 150 or coverage >= 0.15:
        checks.append(0.7)
    elif text_len > 80:
        checks.append(0.4)
    elif text_len > 0:
        checks.append(0.1)
    else:
        checks.append(0.0)

    # --- Check 4: Proof/calculation structure ---
    if proof_required:
        markers = len(_PROOF_STRUCTURE_RE.findall(proof or full_text))
        if markers >= 3:
            checks.append(1.0)
        elif markers >= 1:
            checks.append(0.5)
        else:
            checks.append(0.1)
    else:
        calc = len(_CALC_MARKER_RE.findall(full_text))
        if calc >= 2 or (steps and len(steps) >= 2):
            checks.append(1.0)
        elif calc >= 1:
            checks.append(0.5)
        elif full_text:
            checks.append(0.1)
        else:
            checks.append(0.0)

    # --- Check 5: Reference answer matching (Phase 4.1) ---
    if reference_answer:
        checks.append(_check_answer_match(fa, reference_answer))

    # --- Check 6: Condition satisfaction (Phase 4.1) ---
    checks.append(_check_condition_satisfaction(c, question, proof_required))

    # --- Check 7: Contradiction detection (Phase 4.1) ---
    checks.append(_check_contradictions(c, question))

    return sum(checks) / len(checks) if checks else 0.5


def _compute_candidate_pq_score(c: dict, proof_required: bool) -> float:
    """
    基于中文数学证明模式识别计算候选的证明质量分数（0-1）。
    复用 deepseek.py 的 _detect_proof_features 进行模式检测。

    返回值:
        0.0: 无证明特征
        0.5: 有简单推理（关键词或基本推导，但不够完整）
        1.0: 完整证明（关键词 + 结构化推导特征）
    """
    proof = _candidate_proof_text(c)
    steps = _normalize_steps(c.get("steps"))
    text = "\n".join([proof] + steps).strip()

    if not text:
        return 0.0

    features = _detect_proof_features(text)

    score_signals = (
        features["has_keywords"],
        features["has_derivation"],
        features["has_steps"],
        features["has_formula"],
    )
    if not any(score_signals):
        return 0.0

    # 短文本保护
    text_len = len(text)
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

    # 完整证明：关键词 + 结构化推导
    if features["has_keywords"] and any(structural_signals):
        return 1.0
    if features["keyword_count"] >= 3:
        return 1.0
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

    return 0.5


def _ensure_candidate_scores(
    c: dict, question: str, proof_required: bool,
    reference_answer: Optional[str] = None,
) -> dict:
    """
    确保 candidate 包含 verification_score、proof_quality_score、verification_confidence。
    如果模型已返回则直接使用（clamp 0-1），否则启发式计算。

    兼容旧格式：
    - verification_score 缺失 → 计算（默认 0.5 兜底）
    - proof_quality_score 缺失 → 基于模式识别计算
    - verification_confidence 缺失 → 默认 0.5，或基于 disagreement 计算
    - verification_warning 缺失 → 检测后填充
    """
    out = dict(c)

    # --- verification_score ---
    vs_from_model = False
    vs = c.get("verification_score")
    if vs is not None:
        try:
            vs = max(0.0, min(float(vs), 1.0))
            vs_from_model = True
        except (ValueError, TypeError):
            vs = _compute_verification_score(c, question, proof_required, reference_answer)
    else:
        vs = _compute_verification_score(c, question, proof_required, reference_answer)
    out["verification_score"] = vs
    out["_vs_from_model"] = vs_from_model

    # --- proof_quality_score ---
    pq = c.get("proof_quality_score")
    if pq is not None:
        try:
            pq = max(0.0, min(float(pq), 1.0))
        except (ValueError, TypeError):
            pq = _compute_candidate_pq_score(c, proof_required)
    else:
        pq = _compute_candidate_pq_score(c, proof_required)
    out["proof_quality_score"] = pq

    # --- Phase 5: verification_confidence ---
    vc = c.get("verification_confidence")
    if vc is not None:
        try:
            vc = max(0.0, min(float(vc), 1.0))
        except (ValueError, TypeError):
            vc = None
    if vc is None:
        # 先检测 disagreement（需要 vs 和 pq 已计算）
        warning, severity = _detect_verification_disagreement(
            out, question, proof_required, reference_answer
        )
        if warning:
            out["verification_warning"] = warning
        # 再计算 verification_confidence
        vc = _compute_verification_confidence(
            out, question, proof_required, reference_answer,
            warning, severity,
        )
    out["verification_confidence"] = vc

    return out


def score_candidate(c: dict, proof_required: bool) -> float:
    """
    Phase 5.1: 综合评分 = base_score * (0.8 + 0.2 * verification_confidence)

    base_score 使用 Phase 4.1 动态权重公式：
    - 证明题: 0.3*confidence + 0.4*vs + 0.3*pq
    - 非证明题: 0.5*confidence + 0.5*vs

    verification_confidence 对 final_score 的影响：
    - vc=1.0 → 保留 100% base_score
    - vc=0.5 → 保留  90% base_score
    - vc=0.0 → 保留  80% base_score

    vc 的影响被限制在 ±20% 范围内，避免过度惩罚高质量 candidate。
    """
    confidence = float(c.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(confidence, 1.0))

    _vs_raw = c.get("verification_score", 0.5)
    vs = max(0.0, min(float(_vs_raw) if _vs_raw is not None else 0.5, 1.0))

    pq = float(c.get("proof_quality_score", 0.0) or 0.0)
    pq = max(0.0, min(pq, 1.0))

    if proof_required:
        base_score = 0.3 * confidence + 0.4 * vs + 0.3 * pq
    else:
        base_score = 0.5 * confidence + 0.5 * vs

    # Phase 5.1: gentle vc modulation (80%–100% of base_score)
    _vc_raw = c.get("verification_confidence", 0.5)
    vc = max(0.0, min(float(_vc_raw) if _vc_raw is not None else 0.5, 1.0))

    return base_score * (0.8 + 0.2 * vc)


def select_best_candidate_index(
    candidates: list[dict],
    model_selected: Optional[int],
    proof_required: bool,
) -> int:
    """按综合分选优，不用纯 confidence。"""
    if not candidates:
        return 0
    best_idx = 0
    best_score = -1.0
    for c in candidates:
        idx = int(c.get("index", 0))
        s = score_candidate(c, proof_required)
        if s > best_score:
            best_score = s
            best_idx = idx
    if model_selected is not None and best_score >= 0:
        model_c = next(
            (c for c in candidates if int(c.get("index", -1)) == int(model_selected)),
            None,
        )
        if model_c is not None:
            model_score = score_candidate(model_c, proof_required)
            if model_score >= best_score - 0.05:
                return int(model_selected)
    return best_idx


def _verify_selected_candidate(
    selected: dict,
    question: str,
    proof_required: bool,
    reference_answer: Optional[str] = None,
) -> dict:
    """
    Phase 4.1: 选中候选二次验证。

    在 select_best_candidate_index 之后、返回结果之前执行。
    检查选中候选是否存在严重问题，如有则降低 verification_score。

    检查项：
    1. final_answer 是否为空
    2. 是否与 reference_answer 冲突（仅当 reference_answer 提供时）
    3. 是否存在内部矛盾
    4. 证明题是否缺乏证明内容

    返回: 可能修正了 verification_score 的 candidate dict（副本）
    """
    result = dict(selected)
    issues: list[str] = []

    fa = _candidate_final_answer(selected)

    # 检查1: final_answer 为空
    if not fa:
        issues.append("empty_final_answer")

    # 检查2: 与 reference_answer 冲突
    if reference_answer and fa:
        match = _check_answer_match(fa, reference_answer)
        if match <= 0.1:
            issues.append("answer_mismatch")

    # 检查3: 内部矛盾
    contra = _check_contradictions(selected, question)
    if contra < 0.7:
        issues.append("internal_contradiction")

    # 检查4: 证明题缺乏证明内容
    if proof_required and not candidate_has_proof(selected):
        issues.append("missing_proof")

    # 如果有问题，降低 verification_score
    if issues:
        penalty = len(issues) * 0.15
        current_vs = float(result.get("verification_score", 0.5) or 0.5)
        result["verification_score"] = max(0.0, current_vs - penalty)
        result["verification_issues"] = issues
        logger.debug(
            f"Selected candidate verification issues: {issues}, "
            f"vs {current_vs:.2f} -> {result['verification_score']:.2f}"
        )

    return result


def _build_full_reasoning_for_judge(c: dict, selection_reasoning: str) -> str:
    """合并 proof / reasoning / steps，供下游 judge 使用。"""
    parts = []
    proof = _str_field(c.get("proof") or "")
    reasoning = _str_field(c.get("reasoning") or "")
    steps = _normalize_steps(c.get("steps"))
    verification = _str_field(c.get("verification") or "")
    if proof:
        parts.append(f"[Proof]\n{proof}")
    if reasoning and reasoning != proof:
        parts.append(f"[Reasoning]\n{reasoning}")
    if steps:
        parts.append("[Steps]\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)))
    if verification:
        parts.append(f"[Verification]\n{verification}")
    if selection_reasoning:
        parts.append(f"[Selection]\n{selection_reasoning}")
    return "\n\n".join(parts) if parts else selection_reasoning or proof or reasoning


def _validation_failed(parsed: dict, question: str) -> tuple[bool, str]:
    """Answer Validation Layer：是否需重新请求。"""
    proof_required = is_proof_problem(question)
    answer = _str_field(parsed.get("answer") or "")
    if not answer:
        return True, "empty final_answer"
    candidates = parsed.get("candidates") or []
    if not candidates:
        return True, "no candidates"
    sel = parsed.get("selected_index")
    selected = next(
        (c for c in candidates if int(c.get("index", -1)) == int(sel)),
        candidates[0],
    )
    if proof_required and not candidate_has_proof(selected):
        return True, "proof problem but selected candidate has no proof/reasoning/steps"
    if not proof_required:
        ans = _candidate_final_answer(selected)
        if _BARE_ANSWER_RE.match(ans) and not candidate_has_proof(selected):
            return True, "bare final_answer without calculation steps"
    return False, ""


# ==================== 解析函数 ====================

def parse_multi_candidate_response(
    text: str, question: str = "", reference_answer: Optional[str] = None,
) -> dict:
    """
    解析多候选推理 JSON。兼容 final_answer/answer、proof/reasoning/steps/verification。
    服务端按 score 重选 selected_index，并合并 judge 用 reasoning。

    Phase 4.1: 支持 reference_answer 传入，用于 verification_score 的参考答案匹配。
    """
    try:
        data = extract_json_from_text(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"JSON parse failed, trying regex extraction: {e}")
        data = _fallback_parse(text)

    if not data or not isinstance(data, dict):
        return _make_error_result("Failed to parse JSON from response")

    proof_required = is_proof_problem(question)

    final_answer = _str_field(
        data.get("final_answer") or data.get("answer") or ""
    )

    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list) or len(raw_candidates) == 0:
        logger.warning("No candidates field found, falling back to single-result format")
        reasoning = _str_field(
            data.get("proof")
            or data.get("reasoning")
            or data.get("selection_reasoning")
            or ""
        )
        steps = _normalize_steps(data.get("steps"))
        verification = _str_field(data.get("verification") or "")
        return {
            "answer": final_answer,
            "reasoning": reasoning,
            "steps": steps,
            "verification": verification,
            "candidates": None,
            "selected_index": None,
            "selection_reasoning": _str_field(data.get("selection_reasoning") or ""),
            "verification_score": 0.5,
            "verification_confidence": 0.5,
            "proof_quality_score": 0.0,
            "verification_warning": "",
        }

    candidates = []
    for i, c in enumerate(raw_candidates):
        if not isinstance(c, dict):
            continue
        fa = _candidate_final_answer(c)
        proof = _str_field(c.get("proof") or "")
        reasoning = _str_field(c.get("reasoning") or "")
        steps = _normalize_steps(c.get("steps"))
        verification = _str_field(c.get("verification") or "")
        cand = {
            "index": int(c.get("index", i)),
            "final_answer": fa,
            "answer": fa,
            "proof": proof,
            "reasoning": reasoning,
            "steps": steps,
            "verification": verification,
            "confidence": float(c.get("confidence", 0.0) or 0.0),
            "verification_score": c.get("verification_score"),
            "verification_confidence": c.get("verification_confidence"),
            "proof_quality_score": c.get("proof_quality_score"),
            "strength": _str_field(c.get("strength") or ""),
            "weakness": _str_field(c.get("weakness") or ""),
        }
        # Phase 4: 确保 verification_score 和 proof_quality_score 存在
        cand = _ensure_candidate_scores(cand, question, proof_required, reference_answer)
        candidates.append(cand)

    model_selected = data.get("selected_index", None)
    if model_selected is not None:
        model_selected = int(model_selected)

    selected_index = select_best_candidate_index(
        candidates, model_selected, proof_required
    )
    selected = next(
        (c for c in candidates if int(c.get("index")) == selected_index),
        candidates[0],
    )

    # Phase 4.1: 选中候选二次验证
    verified = _verify_selected_candidate(
        selected, question, proof_required, reference_answer
    )
    # 用二次验证后的结果更新 candidates 列表中的选中项
    for i, c in enumerate(candidates):
        if int(c.get("index", -1)) == selected_index:
            candidates[i] = verified
            break
    selected = verified

    if not final_answer:
        final_answer = _candidate_final_answer(selected)

    selection_reasoning = _str_field(data.get("selection_reasoning") or "")
    merged_reasoning = _build_full_reasoning_for_judge(selected, selection_reasoning)
    top_steps = selected.get("steps") or []
    verification = _str_field(selected.get("verification") or "")

    return {
        "answer": final_answer,
        "reasoning": merged_reasoning,
        "steps": top_steps,
        "verification": verification,
        "candidates": candidates,
        "selected_index": selected_index,
        "selection_reasoning": selection_reasoning,
        "verification_score": float(selected.get("verification_score", 0.5) or 0.5),
        "verification_confidence": float(selected.get("verification_confidence", 0.5) or 0.5),
        "proof_quality_score": float(selected.get("proof_quality_score", 0.0) or 0.0),
        "verification_warning": _str_field(selected.get("verification_warning") or ""),
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
        "verification_score": 0.5,
        "verification_confidence": 0.5,
        "proof_quality_score": 0.0,
        "verification_warning": "",
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
        f"请重新解答以下数学题，严格按系统提示输出统一 JSON（含 proof/reasoning/steps）。\n\n"
        f"{problem.question}\n\n"
        f"---\n"
        f"[验证层反馈] 上一次输出不合格：\n"
        f"{issues_text}\n\n"
        f"改进建议：{suggestions}\n\n"
        f"必须补全：final_answer、证明/计算过程（禁止裸答案）。"
    )


async def _call_inference_api(
    problem: Problem,
    client: LLMClient,
    review_feedback: Optional[dict],
    temperature: float,
) -> tuple[str, dict, int]:
    """单次 LLM 调用 + parse。返回 (raw_text, parsed, tokens)。"""
    if review_feedback is not None:
        user_content = _build_feedback_user_content(problem, review_feedback)
    else:
        user_content = problem.question

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    response = await client.chat(
        messages=messages,
        temperature=temperature,
        max_tokens=_INFERENCE_MAX_TOKENS,
    )
    raw_text = response["content"]
    parsed = parse_multi_candidate_response(
        raw_text, question=problem.question,
        reference_answer=problem.reference_answer,
    )
    return raw_text, parsed, response.get("tokens_used", 0)


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

    label = "Retry" if review_feedback else "Inference"
    start_time = time.time()
    total_tokens = 0
    try:
        raw_text = ""
        parsed: dict = {}
        temperature_use = temperature

        for val_attempt in range(_VALIDATION_MAX_RETRIES + 1):
            raw_text, parsed, tok = await _call_inference_api(
                problem, client, review_feedback, temperature_use
            )
            total_tokens += tok
            if parsed.get("error"):
                break
            need_retry, reason = _validation_failed(parsed, problem.question)
            if not need_retry:
                break
            logger.warning(
                f"[{problem.id}] Answer validation failed ({reason}), "
                f"retry {val_attempt + 1}/{_VALIDATION_MAX_RETRIES}"
            )
            if val_attempt >= _VALIDATION_MAX_RETRIES:
                break
            temperature_use = max(0.3, temperature_use * _RETRY_TEMPERATURE_FACTOR)
            review_feedback = {
                "issues": [f"Validation: {reason}"],
                "suggestions": (
                    "Regenerate with full proof or full calculation steps. "
                    "Do not output bare final_answer only."
                ),
            }

        latency = round(time.time() - start_time, 2)

        logger.info(
            f"{label} completed for [{problem.id}]: "
            f"final_answer={parsed.get('answer', '?')}, "
            f"candidates={len(parsed.get('candidates') or [])}, "
            f"selected={parsed.get('selected_index')}, "
            f"tokens={total_tokens}, "
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
            tokens_used=total_tokens,
            latency_seconds=latency,
            sample_index=sample_index,
            candidates=parsed.get("candidates"),
            selected_candidate_index=parsed.get("selected_index"),
            selection_reasoning=parsed.get("selection_reasoning", ""),
            verification_score=parsed.get("verification_score", 0.5),
            proof_quality_score=parsed.get("proof_quality_score", 0.0),
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
