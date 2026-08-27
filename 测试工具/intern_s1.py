"""
Intern-S1 推理模块（多候选 + 自剪枝 + 双重审核版）。

核心策略：一次 API 调用，让模型内部完成：
  1. 从 3 个不同角度独立推理 → 生成 3 个候选答案
  2. 对每个候选自我评估（信心度 + 优缺点）
  3. 比较后选出最优答案作为最终输出

双重审核机制（并行执行）：
  1. Intern-S1 自审核 — 从完整性/正确性/相关性/格式四维度审查
  2. Lean 形式化验证 — 将逻辑链转化为 Lean 4 代码并编译验证

决策逻辑：
  - 两者都通过 → 接受答案
  - 任一不通过 → Intern-S1 二次复核，判断是真错还是误判
  - 真错 → 重新生成；误判 → 保留答案
  - 最终正确性仅由 DeepSeek 判定
"""
import asyncio
import json
import logging
import re
import time
from collections import Counter
from typing import Optional

from config import get_config
from llm_client import LLMClient, extract_json_from_text
from models import Problem, InferenceResult

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 推理参数
_INFERENCE_TEMPERATURE = 0.6      # 适中温度，保证多样性又不失稳定性
_INFERENCE_MAX_TOKENS = 16384      # 推理最大输出 token（IMO 复杂题需要更长上下文）
_TRUNCATION_RETRY_MAX_TOKENS = 24576  # 截断后重试/续写的最大 token
_CONTINUATION_MAX_TOKENS = 8192      # continuation 续写最大 token

# 自审核参数
_REVIEW_TEMPERATURE = 0.2         # 低温度保证审核一致性
_REVIEW_MAX_TOKENS = 1024         # 审核输出长度限制（原 2048）

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
- "reasoning" field: ALWAYS include complete step-by-step reasoning (for downstream verification). This is the MOST important field.
- "answer" field format (per question type):
  * 选择题(single/multi choice): ONLY the option letter(s), e.g. "C" or "ABD"
  * 判断题(true/false): ONLY "正确" or "错误"  
  * 填空题(fill-in-blank): ONLY the expression/value, e.g. "3.14" or "x=2"
  * 解答题(solution)/证明题(proof): complete solution/proof with final conclusion
- "final_answer" field: follow the same format as "answer" based on question type
- Output raw JSON only — no markdown code fences, no extra text
- NEVER split your response into multiple paragraphs before the JSON. Start directly with the opening brace {
- If the answer is long, keep candidate reasoning concise to avoid truncation"""


# ==================== 跨模型答案提取器提示词 ====================
# 当 Intern-S1 输出未以标准格式给出最终答案时，由 DeepSeek 作为独立
# 提取器从已有推理中挑出最终答案。提取器只负责读取已有结论，不参与解题。

_EXTRACT_SYSTEM_PROMPT = (
    "You are a STRICT answer extractor for a math competition. "
    "Read the reasoning below. It may contain the answer explicitly "
    "(e.g. 'N=3 is a candidate', 'the answer is X', a \\boxed{{...}}), "
    "or the answer may be implied by the final conclusion. "
    "Your ONLY output must be the final answer wrapped as \\boxed{{...}}. "
    "Output NOTHING else — no explanation, no analysis, no comments. "
    "If the reasoning is incomplete, output your best guess based on the last conclusion."
)

_EXTRACT_USER_PROMPT = (
    "Based ONLY on the reasoning above, output the final answer as \\boxed{{...}}. "
    "No other text."
)


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


# ==================== 二次复核提示词 ====================
# 当 Intern-S1 自审核与 Lean 验证结果不一致时，
# 由 Intern-S1 再次审查，判断是真正错误还是误判。

SECONDARY_REVIEW_SYSTEM_PROMPT = """You are a mathematical dispute arbitrator. Your job is to re-examine an AI-generated solution when two independent reviewers disagree.

You will receive:
1. The original math problem
2. The AI model's generated answer and reasoning
3. The Intern-S1 self-review result (what the model thinks of its own answer)
4. The Lean formal verification result (what the Lean compiler found)

The Intern-S1 self-review says: {self_review_verdict}
The Lean formal verification says: {lean_verdict}

Your task: Determine the TRUTH.

Two possible scenarios:
A) The Lean error is a FALSE POSITIVE — it's due to translation/formalism issues, not actual math errors. The original reasoning is still correct.
B) The Lean error reveals a REAL mathematical/logical error in the reasoning. The answer needs to be regenerated.

CRITICAL RULES:
- Be OBJECTIVE — don't trust either reviewer blindly
- If Lean found a genuine logical flaw → confirm it's a real error
- If Lean's failure is due to formalization difficulties (not math errors) → classify as false_positive
- If self-review found issues and Lean agrees → confirm real error
- If self-review passed but Lean failed → carefully examine whether Lean is right

OUTPUT ONLY valid JSON (no markdown, no code fences, no extra text). You MUST include ALL 8 fields, even if empty:

{{
  "consensus": "real_error",
  "confidence": 0.8,
  "reasoning": "详细的判断理由（中文）",
  "error_location": "推理中出错的具体位置（无则留空字符串）",
  "error_explanation": "正确的做法（无则留空字符串）",
  "lean_misinterpretation": "Lean 误判的原因（无则留空字符串）",
  "action": "regenerate",
  "improvement_suggestions": "对下一轮生成的改进建议（中文，无则留空字符串）"
}}

Allowed values:
- "consensus": "real_error" | "false_positive" | "both_correct" | "uncertain"
- "action": "regenerate" | "accept" | "accept_with_warning"
- "confidence": a number between 0.0 and 1.0

IMPORTANT:
- "both_correct" means the answer is right AND Lean would pass with minor formatting fixes
- "uncertain" defaults to "accept" (don't block the pipeline for uncertain cases)
- When in doubt between real_error and false_positive, lean toward false_positive to avoid unnecessary regeneration
- Never omit a field and never wrap the JSON in additional keys (e.g. do NOT output {{"result": {{...}}}} or {{"consensus": "{{...}}"}})"""


# ==================== Lean 代码生成提示词（审核阶段用） ====================
# 简化版：让 Intern-S1 将推理过程转化为 Lean 代码。
# 相比 lean_verifier.py 中的版本，这个更精简，聚焦于审核用途。

LEAN_FOR_REVIEW_SYSTEM_PROMPT = """You are a mathematical formalization expert. Convert the following mathematical reasoning into Lean 4 code that can be compiled and verified.

INPUT: A math problem and a step-by-step reasoning chain with a final answer.

OUTPUT: A Lean 4 file that states the conclusion as a theorem and provides a proof.

CRITICAL RULES:
- Use `import Mathlib` if needed, or import specific modules
- Use `theorem` (not `example`) with a meaningful name
- Include all necessary hypotheses in the theorem statement
- Use standard tactics: rintro, intro, apply, have, calc, ring, linarith, nlinarith, field_simp, etc.
- If a proof step is too complex, use `sorry` — the GOAL is to formalize the LOGICAL STRUCTURE
- The code MUST be syntactically valid and type-check (even if some sub-proofs use sorry)

COMMON PATTERNS:
- Inequalities: `h : a ≤ b`, `hpos : 0 < x`
- Equations: `calc a = b := by ... _ = c := by ...`
- Existence: `∃ x, P x`
- For all: `∀ x, P x → Q x`
- Set theory: `x ∈ A`, `A ⊆ B`

OUTPUT ONLY valid JSON (no markdown, no code fences, no extra text):
{
  "lean_code": "the complete Lean 4 code as a string",
  "formalized_claim": "description in Chinese of what the Lean code proves",
  "key_assumptions": ["assumption 1", "assumption 2"],
  "completeness": 0.0-1.0
}"""


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
        return _make_error_result("Failed to parse JSON from response", text)

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

    # 提取选中候选的完整推理，注入 reasoning 字段
    selected_reasoning = ""
    if selected_index is not None and selected_index < len(candidates):
        selected_reasoning = candidates[selected_index].get("reasoning", "")
    selection_reasoning = data.get("selection_reasoning", "")

    # reasoning = 选中候选的完整推理过程 + 选择理由
    combined_reasoning = selected_reasoning
    if combined_reasoning and selection_reasoning:
        combined_reasoning += "\n\n【选择理由】" + selection_reasoning
    elif selection_reasoning:
        combined_reasoning = selection_reasoning

    return {
        "answer": final_answer,
        "reasoning": combined_reasoning,
        "steps": [],
        "verification": "",
        "candidates": candidates,
        "selected_index": selected_index,
        "selection_reasoning": selection_reasoning,
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


def _make_error_result(message: str, raw_text: str = "") -> dict:
    """构造解析失败时的结果，保留原始自然语言推理便于展示。"""
    raw_text = (raw_text or "").strip()
    return {
        "answer": "",
        "reasoning": raw_text if raw_text else f"Parse error: {message}",
        "steps": [],
        "verification": "",
        "candidates": None,
        "selected_index": None,
        "selection_reasoning": "",
        "error": message,
    }


# ==================== 答案提取工具（兜底链路） ====================
# 当 JSON 结构化输出解析失败或答案为空时，依次尝试：
#   1) boxed 提取（\\boxed{...}，手写大括号计数，支持任意嵌套）
#   2) 强结论模式（"N=3 is a candidate" / "the answer is X" 等）
#   3) DeepSeek 跨模型提取（从已有推理中挑出最终答案）
#   4) 尾部兜底（最后一行非空内容）
# 移植自 imo_bench_eval/intern_solver.py 与 scorer.py，
# 并按本模块 LLMClient(cfg.xxx) 的异步调用方式适配。

# LaTeX 扩展命令：排版用，不影响数学含义
_LATEX_SPACING = re.compile(
    r"\\displaystyle|\\textstyle|\\scriptstyle|\\scriptscriptstyle"
    r"|\\qquad|\\quad|\\;|\\,|\\!|\\:|\\ |\\enspace"
    r"|\\thinspace|\\medspace|\\thickspace|\\negthinspace|\\negmedspace|\\negthickspace"
)
# 多余空白字符
_WHITESPACE_NORM = re.compile(r"\s+")


def _normalize_answer(text: str) -> str:
    """规范化数学答案文本（移植自 imo_bench_eval/scorer.py）。"""
    if not text:
        return ""
    # 1. 去除 LaTeX 扩展命令
    text = _LATEX_SPACING.sub("", text)
    # 2. 转换 \\frac{a}{b} → a/b
    text = re.sub(r"\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
                  r"\1/\2", text)
    # 3. 去除 \\boxed{...} 包装
    text = re.sub(r"\\boxed\{([^}]*)\}", r"\1", text)
    # 4. 去除 \\text{...} 包装
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    # 5. 去除 $$ 和 $ 定界符
    text = text.replace("$$", "").replace("$", "")
    # 6. 去除 \\left/\\right 定界符命令
    text = re.sub(r"\\left(?=[\\{])", "", text)
    text = re.sub(r"\\right(?=[\\}])", "", text)
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)([()\[\]|{}])", r"\1", text)
    # 7. 统一 \\cdot → *（等价含义）
    text = re.sub(r"\\cdot|\\times", "*", text)
    # 8. 去掉单字符大括号 {a} → a（如 \\log_{2} → \\log_2）
    text = re.sub(r"\{([^}]{1})\}", r"\1", text)
    # 9. 删除所有空白（LaTeX 数学模式中空格无语义）
    text = _WHITESPACE_NORM.sub("", text)
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
    """尝试将文本解析为数字（含分数）。失败返回 None。"""
    if not text:
        return None
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    m = re.match(r"^(-?\d+)\s*/\s*(-?\d+)$", text)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den != 0:
            return num / den
    return None


def _voting_key(answer: str) -> str:
    """生成自一致性投票的归一化键。

    先做文本归一化（LaTeX/空白/分数写法差异），若文本归一化后可解析为数字，
    则再按数值归一化（统一 1/2 与 0.5、3 与 3.0 为同一票）。
    """
    norm = _normalize_answer(answer)
    if not norm:
        return ""
    num = _try_parse_number(norm)
    if num is not None:
        return f"NUM:{num:.10g}"
    return norm


def _extract_boxed(text: str) -> str:
    """从 LLM 输出中提取最终答案：匹配 \\boxed{...}，通过手动计数大括号处理任意嵌套深度"""
    if not text:
        return ""

    # 查找所有 "\boxed{" 出现位置，手动匹配大括号
    marker = r"\boxed{"
    results = []
    idx = 0
    while True:
        pos = text.find(marker, idx)
        if pos == -1:
            break
        start = pos + len(marker)  # 内容起始位置（{ 之后）
        depth = 1
        cursor = start
        while cursor < len(text) and depth > 0:
            ch = text[cursor]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    results.append(text[start:cursor].strip())
                    break
            cursor += 1
        idx = pos + 1

    return results[-1] if results else ""


# 强模式：明确结论句（可靠，可在全文搜索）
_ANSWER_PATTERNS = [
    # "the (final) answer is X" / "answer: X" — 最可靠
    (r"(?i)(?:the\s+(?:final\s+|correct\s+)?answer\s+(?:is\s*[:\s]|:))\s*(.+?)(?:\.\s*$|\.\s|\n\n|\Z)", 1),
    # "X = Y is a candidate / solution / the answer"（Intern-S1 常用）
    (r"(?i)\b([a-zA-Z])\s*=\s*(-?\d+)\s+is\s+(?:a\s+(?:valid\s+)?(?:candidate|solution)|the\s+answer)", 2),
    # "Therefore/Thus/Hence/So, X." — 需要 X 是短答案
    (r"(?i)(?:Therefore|Thus|Hence|So)\s*[,:]\s*(.{1,120}?)(?:\.\s*$|\n\n|\Z)", 1),
    # "which gives X" / "which yields X" / "we conclude X"
    (r"(?i)(?:which\s+(?:gives|yields)|we\s+conclude)\s+(.{1,120}?)(?:\.\s*$|\n\n|\Z)", 1),
    # "result: X" / "conclusion: X"
    (r"(?i)(?:(?:final\s+)?result|conclusion)\s*:\s*(.{1,120}?)(?:\.\s*$|\n\n|\Z)", 1),
]

# 弱模式：行尾变量赋值（如 "N = 3"），只在文本尾部搜索，避免误匹配推理开头
_WEAK_ASSIGN_PATTERN = (r"(?m)^(?:\w)\s*=\s*(.{1,80}?)\s*$", 1)


def _extract_strong_pattern(text: str) -> str:
    """仅使用强结论模式匹配（可靠）：
    1) 强模式全文搜索（候选解如 "N=3 is a candidate" 常出现在推理中段）
    2) 弱赋值模式只在尾部搜索（结论通常在末尾，避免开头误匹配）
    """
    if not text or len(text) < 10:
        return ""

    tail = text[-4000:] if len(text) > 4000 else text

    # 1) 强模式在全文搜索
    for pattern, group in _ANSWER_PATTERNS:
        m = re.search(pattern, text, re.DOTALL | re.MULTILINE)
        if m:
            candidate = m.group(group).strip()
            candidate = _clean_answer(candidate)
            if candidate and 1 <= len(candidate) <= 200:
                return candidate

    # 2) 弱赋值模式只在尾部搜索
    m = re.search(_WEAK_ASSIGN_PATTERN[0], tail, re.MULTILINE)
    if m:
        candidate = m.group(_WEAK_ASSIGN_PATTERN[1]).strip()
        candidate = _clean_answer(candidate)
        if candidate and 1 <= len(candidate) <= 200:
            return candidate

    return ""


def _extract_tail_fallback(text: str) -> str:
    """最后手段：取最后一行非空内容作为答案（误报率高，仅作兜底）"""
    if not text:
        return ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in reversed(lines[-5:]):  # 只看最后5行
        # 跳过代码块/列表/Markdown 标记
        if line.startswith(("```", "-", "*", "+", ">", "|", "#")):
            continue
        # 跳过推理标记、半截句子
        skip_words = ["wait", "let me", "now consider", "for example",
                      "we can", "since", "because", "first", "next", "then",
                      "note that", "assume", "suppose", "let's", "if"]
        if any(line.lower().startswith(w) for w in skip_words):
            continue
        # 跳过以 "(" "[" "{" 开头（通常是公式推导）
        if line and line[0] in "([{":
            continue
        cleaned = _clean_answer(line)
        # 推理片段检测（清理后的内容仍像推理句则跳过）
        if cleaned and not _looks_like_reasoning_fragment(cleaned) and 3 <= len(cleaned) <= 160:
            return cleaned

    return ""


_REASONING_FRAGMENT_WORDS = [
    "if", "since", "because", "as", "let", "suppose", "assume", "note",
    "observe", "recall", "given", "when", "where", "alternatively",
    "moreover", "furthermore", "consequently", "subsequently", "however",
    "consider", "using", "by", "with", "from", "substituting", "plugging",
    "rearranging", "simplifying", "expanding", "combining", "adding",
    "subtracting", "multiplying", "dividing", "taking", "applying",
    "now", "here", "well", "okay", "but", "also", "yet", "wait",
    "for each", "for example", "first", "next", "then", "finally",
    "the number written is", "the set", "term is",
]


def _clean_answer(text: str) -> str:
    """清理提取的答案文本；若清理后仍呈推理片段特征则返回空串"""
    if not text:
        return ""
    # 去掉开头的冒号、空格、破折号
    text = re.sub(r"^[:\s\-–—]+", "", text)
    # 去掉尾部的空格和标点
    text = text.strip().rstrip(".;,，。；:")
    # 去掉开头的小写引导词
    text = re.sub(r"^(?:is|that|it\s+is|the\s+answer\s+is)\s+", "", text, flags=re.IGNORECASE)
    # 去掉编号前缀（如 "1. If we set..."）
    # 注意：必须是编号分隔符后紧跟空白或结尾才删除，避免误删 "3.5" 的小数点
    text = re.sub(r"^\d+[.)](?=\s|$)", "", text).strip()
    # 推理片段特征检测：以引导词开头 → 非独立答案
    if _looks_like_reasoning_fragment(text):
        return ""
    # 保留下划线、反斜杠、花括号等数学符号
    return text.strip()


def _looks_like_reasoning_fragment(text: str) -> bool:
    """判断文本是否像推理片段而非独立答案"""
    if not text:
        return False
    low = text.lower().strip()

    # so/therefore/thus/hence 开头：若后面紧跟结论短语/等式/数字，则视为答案
    m = re.match(r"^(so|therefore|thus|hence)\b", low)
    if m:
        rest = low[len(m.group(0)):].lstrip(" ,")
        conclusion_phrases = [
            "the answer", "final answer", "answer is", "the value",
            "value is", "the result", "result is", "we obtain", "we get",
            "we have", "x =", "y =", "z =", "n =", "k =", "a =", "b =",
            "c =", "is", "are", "=",
        ]
        if any(rest.startswith(p) for p in conclusion_phrases):
            return False
        # 若包含数字或等号，且不含明显推导短语，也视为结论
        if re.search(r"\d|=", rest) and not any(
            p in rest for p in ["can be written as", "we can write", "we have", "we get", "we see"]
        ):
            return False
        return True

    # 开头是典型推理/条件引导词
    for w in _REASONING_FRAGMENT_WORDS:
        if low.startswith(w):
            return True

    # 包含明显推理短语
    reasoning_phrases = [
        "let me note", "let me write", "let me check", "let me compute",
        "let us note", "let us consider", "can be written as",
        "we can write", "we can see", "we can find", "we can get",
        "we have", "we get", "we see", "we find", "we know",
        "it follows that", "this means", "that means", "which means",
        "equation (", "equations (", "eq (", "eq. (",
        "down as equation", "as equation (", "labeled as",
        "substituting", "plugging in", "rearranging", "simplifying",
        "combining", "adding", "subtracting", "multiplying", "dividing",
        "taking the", "applying the", "by the", "from the", "with the",
    ]
    for phrase in reasoning_phrases:
        if phrase in low:
            return True

    # 末尾是冒号（表示后面还有内容）
    if text.rstrip().endswith(":"):
        return True

    # 以 "X=..." 开头但后面跟着推理连词
    if re.match(r"^\w+\s*[:=]", low) and re.search(r"\b(so|then|since|because|thus|hence|therefore)\b", low):
        return True

    return False


def _truncate_reasoning(response: str, max_chars: int = 12000) -> str:
    """截断推理文本：保留开头（题目分析）和结尾（结论），超长时省略中间。

    注意：候选解结论可能出现在推理中段（如 "N=3 is a candidate"），
    因此保留范围要足够大，默认 12000 字符完整覆盖 IMO 级推理。
    """
    if len(response) <= max_chars:
        return response
    head = response[:3000]
    tail = response[-8000:]
    return head + "\n\n... [reasoning middle omitted] ...\n\n" + tail


async def _extract_with_deepseek(question: str, reasoning: str) -> str:
    """用 DeepSeek 从 Intern-S1 的推理中提取最终答案（跨模型兜底）。

    Intern-S1 推理质量高但不遵守 boxed 格式；DeepSeek 作为独立提取器
    从推理中挑出最终答案。提取器只负责读取已有结论，不参与解题。

    注意：本模块 LLMClient 采用 LLMClient(cfg.deepseek) 单 config 方式，
    chat() 为异步调用且返回 dict（含 "content" 键）。
    """
    try:
        cfg = get_config()
        client = LLMClient(cfg.deepseek)
        response = await client.chat(
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Problem:\n{question}\n\nReasoning:\n{_truncate_reasoning(reasoning)}"},
                {"role": "user", "content": _EXTRACT_USER_PROMPT},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        return response.get("content", "")
    except Exception as e:
        logger.warning("DeepSeek extraction failed: %s", e)
        return ""


async def _rescue_answer(
    problem: Problem,
    raw_text: str,
    parsed: dict,
) -> tuple[str, str]:
    """答案兜底提取：当 JSON 结构化输出解析结果为空答案时，依次尝试
    boxed → 强模式 → DeepSeek 跨模型 → 尾部兜底。

    所有 rescued 答案都会经过 `_clean_answer` 与 `_looks_like_reasoning_fragment`
    校验，避免把中间推理片段误判为最终答案。

    参数:
        problem: 当前题目（供 DeepSeek 提取器使用）
        raw_text: LLM 原始输出
        parsed: parse_multi_candidate_response 的解析结果

    返回:
        (提取到的答案, 提取来源)；未提取到返回 ("", "")。
    """
    if not raw_text:
        return "", ""
    text = raw_text

    def _accept(candidate: str) -> tuple[str, bool]:
        cleaned = _clean_answer(candidate)
        if not cleaned:
            return "", False
        if _looks_like_reasoning_fragment(cleaned):
            return "", False
        #  rescued 答案不应是过长的推理段落
        if len(cleaned) > 280:
            return "", False
        return cleaned, True

    # 1) boxed 提取
    answer = _extract_boxed(text)
    cleaned, ok = _accept(answer)
    if ok:
        return cleaned, "boxed"

    # 2) 强结论模式
    answer = _extract_strong_pattern(text)
    cleaned, ok = _accept(answer)
    if ok:
        return cleaned, "strong_pattern"

    # 3) DeepSeek 跨模型提取
    answer = await _extract_with_deepseek(problem.question, text)
    if answer:
        cleaned = _extract_boxed(answer) or _clean_answer(answer)
        cleaned, ok = _accept(cleaned)
        if ok:
            return cleaned, "deepseek"

    # 4) 尾部兜底
    answer = _extract_tail_fallback(text)
    cleaned, ok = _accept(answer)
    if ok:
        return cleaned, "tail_fallback"

    return "", ""


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

        # 截断处理：如果被截断，先尝试 continuation 续写，再尝试更大 token 重试
        if response.get("is_truncated") or response.get("content_truncated"):
            is_trunc = response.get("is_truncated")
            content_trunc = response.get("content_truncated")
            logger.warning(
                f"{label} truncated for [{problem.id}] "
                f"(is_truncated={is_trunc}, content_truncated={content_trunc}). "
                f"Trying continuation..."
            )

            # 策略 1：continuation —— 把已输出内容当作 assistant 消息，要求继续完成 JSON
            cont_messages = messages + [
                {"role": "assistant", "content": raw_text},
                {
                    "role": "user",
                    "content": (
                        "你的输出被截断了。请从截断处继续，"
                        "补全未完成的 JSON 对象，不要重复已经输出的内容。"
                    ),
                },
            ]
            cont_start = time.time()
            cont_response = await client.chat(
                messages=cont_messages,
                temperature=temperature,
                max_tokens=_CONTINUATION_MAX_TOKENS,
            )
            cont_latency = round(time.time() - cont_start, 2)
            cont_text = cont_response["content"]
            combined_text = raw_text + cont_text

            # 如果续写后不再截断且能解析出 JSON，则采用续写结果
            if not (
                cont_response.get("is_truncated") or cont_response.get("content_truncated")
            ):
                parsed_cont = parse_multi_candidate_response(combined_text)
                if parsed_cont.get("answer") or parsed_cont.get("candidates"):
                    raw_text = combined_text
                    response = cont_response
                    latency += cont_latency
                    logger.info(
                        f"{label} continuation succeeded for [{problem.id}] "
                        f"(combined_tokens={response.get('tokens_used', 0)}, "
                        f"combined_latency={latency}s)"
                    )
                else:
                    logger.warning(
                        f"{label} continuation did not yield parseable JSON "
                        f"for [{problem.id}], will try full retry"
                    )
            else:
                logger.warning(
                    f"{label} continuation still truncated for [{problem.id}], "
                    f"will try full retry"
                )

            # 策略 2：用更大的 max_tokens 重新生成一次（避免模型继续发散的推理）
            if (
                response.get("is_truncated") or response.get("content_truncated")
                or not parse_multi_candidate_response(raw_text).get("answer")
            ):
                logger.warning(
                    f"{label} retrying with max_tokens={_TRUNCATION_RETRY_MAX_TOKENS} "
                    f"for [{problem.id}]"
                )
                retry_start = time.time()
                retry_response = await client.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=_TRUNCATION_RETRY_MAX_TOKENS,
                )
                retry_latency = round(time.time() - retry_start, 2)
                if not (
                    retry_response.get("is_truncated") or retry_response.get("content_truncated")
                ):
                    raw_text = retry_response["content"]
                    response = retry_response
                    latency += retry_latency
                    logger.info(
                        f"{label} full retry succeeded for [{problem.id}] "
                        f"with {_TRUNCATION_RETRY_MAX_TOKENS} tokens"
                    )
                else:
                    logger.warning(
                        f"{label} full retry still truncated for [{problem.id}], "
                        f"using best available content"
                    )

        parsed = parse_multi_candidate_response(raw_text)

        # 兜底提取链路：JSON 解析结果为空答案时，依次尝试
        # boxed → 强结论模式 → DeepSeek 跨模型 → 尾部兜底，减少漏提取。
        if not parsed.get("answer"):
            rescued_answer, extract_source = await _rescue_answer(problem, raw_text, parsed)
            if rescued_answer:
                parsed["answer"] = rescued_answer
                logger.info(
                    f"{label} rescued answer via {extract_source} "
                    f"for [{problem.id}]: {rescued_answer[:80]}"
                )

        logger.info(
            f"{label} completed for [{problem.id}]: "
            f"final_answer={parsed.get('answer', '?')}, "
            f"candidates={len(parsed.get('candidates') or [])}, "
            f"tokens={response.get('tokens_used', 0)}, "
            f"latency={latency}s"
        )

        # 诊断：记录解析/截断/空响应错误
        parsed_answer = parsed.get("answer", "")
        parsed_reasoning = parsed.get("reasoning", "")
        is_truncated = bool(
            response.get("is_truncated") or response.get("content_truncated")
        )
        parse_error_msg = None
        if not parsed_answer:
            if is_truncated:
                # 截断且无可用答案：优先标记截断，便于排查长度/模型输出问题
                parse_error_msg = "Response truncated before answer was generated"
            elif parsed.get("error"):
                parse_error_msg = f"Parse error: {parsed['error']}"
            elif not parsed_reasoning or not str(parsed_reasoning).strip():
                parse_error_msg = "Empty response: model returned no answer or reasoning"

        return InferenceResult(
            problem_id=problem.id,
            question=problem.question,
            answer=parsed_answer,
            reasoning=parsed_reasoning,
            steps=parsed.get("steps", []),
            verification=parsed.get("verification", ""),
            raw_response=raw_text,
            tokens_used=response.get("tokens_used", 0),
            latency_seconds=latency,
            error=parse_error_msg,
            finish_reason=response.get("finish_reason"),
            is_truncated=is_truncated,
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

        # 截断检测：审核被截断时不得直接放行，标记 fail 交由二次复核/重试兜底
        if response.get("is_truncated") or response.get("content_truncated"):
            logger.warning(
                f"Self-review truncated [{problem.id}]: "
                f"is_truncated={response.get('is_truncated')}, "
                f"content_truncated={response.get('content_truncated')}. "
                f"Marking fail for secondary review."
            )
            return {
                "verdict": "fail",
                "scores": {"completeness": 0, "correctness": 0, "relevance": 0, "format": 0},
                "issues": [{"type": "truncated", "description": "Self-review response truncated"}],
                "suggestions": "Self-review 输出被截断，需重新复核或重新生成。",
                "summary": "Self-review response truncated, marked fail for secondary review",
                "tokens_used": response.get("tokens_used", 0),
                "latency": latency,
            }

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


# ==================== 审核辅助函数（Lean 检查 + 二次复核） ====================

async def _run_lean_check(problem: Problem, inference: InferenceResult,
                         logger: logging.Logger) -> Optional[dict]:
    """
    在审核阶段运行 Lean 形式化验证（轻量版）。

    流程：
    1. 用 Intern-S1 将推理过程转化为 Lean 4 代码
    2. 调用 Lean 编译器验证
    3. 返回简化的验证结果

    与 lean_verifier.py 的区别：
    - 仅做转化+编译，不做深度分析（深度分析留给二次复核）
    - 使用 Intern-S1 进行转化

    Returns:
        dict: {"verified": bool, "lean_code": str, "compile_output": str,
               "error_message": str, "latency": float}
        None: 如果 Lean 功能不可用
    """
    start = time.time()
    try:
        from lean_verifier import _compile_lean, _get_lean_env

        cfg = get_config()

        # 检查 Lean 环境是否可用
        lean_env = _get_lean_env(cfg)
        if not lean_env.get("available", False):
            logger.info("[Lean审核] Lean 环境不可用，跳过验证")
            return None

        # 步骤1：用 Intern-S1 生成 Lean 代码
        review_client = LLMClient(cfg.intern_s1)

        user_msg = f"""请将以下数学推理转化为 Lean 4 代码：

## 题目
{problem.question}

## 解答
{inference.answer}

## 推理过程
{inference.reasoning or "（无详细推理过程）"}

请只输出 JSON，不要加 markdown 代码块标记。"""

        lean_raw = await review_client.chat(
            messages=[
                {"role": "system", "content": LEAN_FOR_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=2048,
        )

        lean_json = extract_json_from_text(lean_raw["content"])
        lean_code = lean_json.get("lean_code", "") if lean_json else ""

        if not lean_code or not lean_code.strip():
            logger.info("[Lean审核] 未能生成 Lean 代码")
            return {
                "verified": False,
                "lean_code": "",
                "compile_output": "",
                "error_message": "无法生成 Lean 代码",
                "latency": time.time() - start,
            }

        # 步骤2：编译 Lean 代码
        compile_result = await _compile_lean(lean_code, cfg)

        latency = round(time.time() - start, 2)
        verified = compile_result.get("passed", False)

        logger.info(
            f"[Lean审核] 验证{'通过' if verified else '失败'}，"
            f"耗时 {latency}s"
        )

        return {
            "verified": verified,
            "lean_code": lean_code,
            "compile_output": compile_result.get("output", ""),
            "error_message": compile_result.get("output", ""),
            "latency": latency,
        }

    except ImportError:
        logger.warning("[Lean审核] lean_verifier 模块不可用")
        return None
    except Exception as e:
        logger.warning(f"[Lean审核] 异常: {e}")
        return {
            "verified": False,
            "lean_code": "",
            "compile_output": str(e),
            "error_message": str(e),
            "latency": round(time.time() - start, 2),
        }


_SECONDARY_REVIEW_DEFAULTS = {
    "consensus": "",
    "action": "accept",
    "reasoning": "",
    "confidence": 0.5,
    "error_location": "",
    "error_explanation": "",
    "lean_misinterpretation": "",
    "improvement_suggestions": "",
}


def _normalize_secondary_review_result(result_json: dict) -> None:
    """
    规范化二次复核结果：补齐缺失字段并约束类型。

    就地修改 result_json，确保调用方安全访问 consensus/action/reasoning/confidence 等字段，
    避免 KeyError 或类型错误污染后续流程。
    """
    if not isinstance(result_json, dict):
        return
    for key, default in _SECONDARY_REVIEW_DEFAULTS.items():
        if key not in result_json or result_json[key] is None:
            result_json[key] = default
    # 枚举约束（与 SECONDARY_REVIEW_SYSTEM_PROMPT 的枚举保持一致）
    if result_json.get("consensus") not in (
        "real_error", "false_positive", "both_correct", "uncertain",
    ):
        result_json["consensus"] = "uncertain"
    if result_json.get("action") not in (
        "accept", "reject", "regenerate", "accept_with_warning",
    ):
        result_json["action"] = "accept"
    # confidence 转为 0-1 浮点
    try:
        conf = float(result_json.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    result_json["confidence"] = min(max(conf, 0.0), 1.0)
    # 字符串字段必须是 str
    for key in ("reasoning", "error_location", "error_explanation",
                "lean_misinterpretation", "improvement_suggestions"):
        if not isinstance(result_json.get(key), str):
            result_json[key] = str(result_json.get(key, "") or "")


async def _secondary_review(problem: Problem, inference: InferenceResult,
                            review: dict, lean_result: Optional[dict],
                            logger: logging.Logger) -> dict:
    """
    当 Intern-S1 自审核与 Lean 验证结果不一致时，
    由 Intern-S1 进行二次复核，判断是真错还是误判。

    Args:
        problem: 原始题目
        inference: 当前的推理结果
        review: Intern-S1 自审核结果
        lean_result: Lean 验证结果（可能为 None）
        logger: 日志记录器

    Returns:
        dict: {"consensus": "real_error"|"false_positive"|"both_correct"|"uncertain",
               "confidence": float, "reasoning": str, "action": "regenerate"|"accept"|"accept_with_warning",
               "error_location": str, "error_explanation": str,
               "lean_misinterpretation": str, "improvement_suggestions": str}
    """
    review_pass = review.get("verdict") == "pass"

    # 如果没有 Lean 结果，只需处理自审核失败的情况
    if lean_result is None:
        if review_pass:
            return {
                "consensus": "both_correct",
                "confidence": 0.9,
                "reasoning": "自审核通过，Lean 不可用，默认接受",
                "action": "accept",
                "error_location": "",
                "error_explanation": "",
                "lean_misinterpretation": "",
                "improvement_suggestions": "",
            }
        else:
            return {
                "consensus": "real_error",
                "confidence": 0.7,
                "reasoning": f"自审核不通过: {review.get('summary', '未提供具体原因')}",
                "action": "regenerate",
                "error_location": json.dumps(review.get("issues", []), ensure_ascii=False),
                "error_explanation": str(review.get("summary", "")),
                "lean_misinterpretation": "",
                "improvement_suggestions": str(review.get("suggestions", "")),
            }

    lean_pass = lean_result.get("verified", True)
    self_review_verdict = "pass" if review_pass else "fail"
    lean_verdict_str = "pass" if lean_pass else "fail"

    # 两者都通过 — 不需要二次复核
    if review_pass and lean_pass:
        logger.info("[二次复核] 双审都通过，无需复核")
        return {
            "consensus": "both_correct",
            "confidence": 0.95,
            "reasoning": "自审核和 Lean 验证都通过，答案质量良好",
            "action": "accept",
            "error_location": "",
            "error_explanation": "",
            "lean_misinterpretation": "",
            "improvement_suggestions": "",
        }

    # 任一不通过 → 需要 Intern-S1 二次判断
    logger.info(
        f"[二次复核] 自审核={self_review_verdict}, Lean={lean_verdict_str}, "
        f"开始复核..."
    )

    try:
        cfg = get_config()
        review_client = LLMClient(cfg.intern_s1)

        # 构建 Lean 错误信息摘要
        lean_summary = ""
        if not lean_pass:
            error_msg = str(lean_result.get("error_message", lean_result.get("compile_output", "(无错误信息)")))[:1000]
            lean_summary = (
                "### Lean 验证结果：失败\n"
                "- 验证状态：未通过编译\n"
                f"- Lean 代码：\n```lean4\n{lean_result.get('lean_code', '(无代码)')[:1500]}\n```\n"
                f"- 编译错误：{error_msg}"
            )
        else:
            lean_summary = "### Lean 验证结果：通过 ✓"

        # 构建自审核摘要
        issues_text = json.dumps(
            review.get("issues", review.get("critical_issues", [])),
            ensure_ascii=False, indent=2,
        )[:1000]
        suggestions_text = str(review.get("suggestions", review.get("improvement_suggestions", "(无)")))[:500]

        review_summary = (
            f"### Intern-S1 自审核结果：{'通过' if review_pass else '不通过'}\n"
            f"- 详细问题：{issues_text}\n"
            f"- 建议：{suggestions_text}"
        )

        user_msg = f"""请对以下解答进行二次复核。自审核和 Lean 验证意见不一致。

## 原题目
{problem.question}

## 模型解答
{inference.answer}

## 推理过程
{(inference.reasoning or '(无详细推理过程)')[:2000]}

{review_summary}

{lean_summary}

请客观判断：Lean 发现的问题是真实错误还是误判（形式化翻译问题）？输出 JSON 格式结果。"""

        prompt = SECONDARY_REVIEW_SYSTEM_PROMPT.format(
            self_review_verdict=self_review_verdict,
            lean_verdict=lean_verdict_str,
        )

        review_messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ]
        raw = await review_client.chat(
            messages=review_messages,
            temperature=0.1,
            max_tokens=2048,
        )

        # 截断检测：二次复核输出被截断时，用更大 token 重试一次
        if raw.get("is_truncated") or raw.get("content_truncated"):
            logger.warning(
                f"[二次复核] 输出被截断 "
                f"(is_truncated={raw.get('is_truncated')}, "
                f"content_truncated={raw.get('content_truncated')})，"
                f"用更大 max_tokens 重试一次"
            )
            raw = await review_client.chat(
                messages=review_messages,
                temperature=0.1,
                max_tokens=4096,
            )

        result_json = extract_json_from_text(raw["content"])
        if isinstance(result_json, dict):
            logger.info(
                f"[二次复核] 结论={result_json.get('consensus')}, "
                f"行动={result_json.get('action')}, "
                f"信心={result_json.get('confidence', 'N/A')}"
            )
            _normalize_secondary_review_result(result_json)
            return result_json
        else:
            logger.warning(
                f"[二次复核] 无法解析复核结果 JSON"
                f"（类型={type(result_json).__name__ if result_json is not None else 'None'}）"
            )
            return {
                "consensus": "uncertain",
                "confidence": 0.5,
                "reasoning": "无法解析复核结果，默认接受（避免阻塞流程）",
                "action": "accept",
                "error_location": "",
                "error_explanation": "",
                "lean_misinterpretation": "",
                "improvement_suggestions": "",
            }

    except Exception as e:
        # 截断异常消息（最多200字符），防止 \n 等原始字符污染 HTML 报告
        err_msg = repr(e)[:200]
        logger.warning(f"[二次复核] 异常: {err_msg}")
        return {
            "consensus": "uncertain",
            "confidence": 0.5,
            "reasoning": f"复核异常({type(e).__name__})，默认接受以避免阻塞",
            "action": "accept",
            "error_location": "",
            "error_explanation": "",
            "lean_misinterpretation": "",
            "improvement_suggestions": "",
        }


def _build_combined_feedback(problem: Problem, review: dict,
                             lean_result: Optional[dict],
                             secondary: dict) -> str:
    """
    构建用于重新生成的综合反馈。

    结合自审核问题 + Lean 发现的问题 + 二次复核的改进建议，
    形成一条清晰的反馈信息传递给下一轮生成。
    """
    parts = ["## 上一轮解答存在的问题：\n"]

    # 自审核发现的问题
    if review.get("verdict") != "pass":
        issues = review.get("issues", review.get("critical_issues", []))
        if isinstance(issues, list) and issues:
            parts.append("### 自审核发现的问题：")
            for issue in issues:
                if isinstance(issue, dict):
                    parts.append(
                        f"- {issue.get('type', '问题')}: "
                        f"{issue.get('description', '')}"
                    )
                else:
                    parts.append(f"- {issue}")
        summary = review.get("summary", "")
        if summary:
            parts.append(f"\n自审核总结：{summary}")
        suggestions = review.get(
            "suggestions", review.get("improvement_suggestions", "")
        )
        if suggestions:
            parts.append(f"\n改进建议：{suggestions}")

    # Lean 发现的问题
    if lean_result and not lean_result.get("verified", True):
        error_msg = lean_result.get("error_message", "")
        if error_msg:
            parts.append("\n### Lean 形式化验证发现的问题：")
            parts.append(f"- 编译错误：{error_msg[:500]}")
            parts.append(
                "\nLean 验证未能通过编译，请检查逻辑是否有漏洞。"
            )

    # 二次复核的改进建议
    if secondary and secondary.get("action") == "regenerate":
        improvements = secondary.get("improvement_suggestions", "")
        if improvements:
            parts.append(f"\n### 改进方向：")
            parts.append(str(improvements))
        error_loc = secondary.get("error_location", "")
        if error_loc:
            parts.append(f"\n需要修正的地方：{error_loc}")
        error_exp = secondary.get("error_explanation", "")
        if error_exp:
            parts.append(f"\n正确的做法：{error_exp}")

    parts.append(f"\n\n## 原题目\n{problem.question}")
    parts.append("\n请认真修正上述问题，重新生成完整的解答。")

    return "\n".join(parts)


# ==================== 主推理函数（双重审核循环） ====================

async def run_inference(
    problem: Problem,
    enable_review: bool = True,
    max_review_retries: int = 1,
    enable_lean: bool = True,
) -> InferenceResult:
    """对单道题目执行 Intern-S1 推理（多候选 + 自剪枝 + 双重审核循环）。

    完整流程：
    1. 推理 → 一次 API 调用，模型生成 3 候选 + 自剪枝选出最优
    2. 双重审核（并行执行）：
       a. Intern-S1 自审核 — 从完整性/正确性/相关性/格式四维度审查
       b. Lean 形式化验证 — 将逻辑链转化为 Lean 4 代码并编译验证
    3. 决策逻辑：
       - 两者都通过 → 接受答案
       - 任一不通过 → Intern-S1 二次复核，判断是真错还是误判
       - 真错 → 重新生成（最多 max_review_retries 次）
       - 误判 → 保留答案
    4. 最终正确性由 DeepSeek 独立判定

    参数:
        problem:           需要解答的数学题目
        enable_review:     是否启用自审核（默认 True）
        max_review_retries: 审核不通过时的最大重试次数（默认 1）
        enable_lean:       是否启用 Lean 形式化验证（默认 True）

    返回:
        InferenceResult，包含：
        - review_passed:      Intern-S1 自审核是否通过
        - dual_review_passed: 双重审核是否都通过
        - lean_verification:  Lean 验证结果
        - secondary_review:   二次复核结果（如果执行了）
        - review_feedback:    自审核反馈详情
        - review_attempts:    审核/重试总次数
        - total_tokens_used / total_latency_seconds
    """
    cfg = get_config()
    client = LLMClient(cfg.intern_s1)

    total_tokens = 0
    total_latency = 0.0
    review_tokens = 0
    review_latency = 0.0
    lean_latency = 0.0

    # --- 阶段 1: 推理 ---
    result = await _do_inference(problem, client)
    total_tokens += result.tokens_used
    total_latency += result.latency_seconds

    if not enable_review or result.error:
        result.total_tokens_used = total_tokens
        result.total_latency_seconds = total_latency
        return result

    current_result = result

    # --- 阶段 2: 双重审核（并行） + 条件重试 ---
    for attempt in range(max_review_retries + 1):
        # ========== 并行执行：Intern-S1 自审核 + Lean 形式化验证 ==========
        review_task = _self_review(problem, current_result)
        lean_task = _run_lean_check(problem, current_result, logger) if enable_lean else None

        if lean_task is not None:
            results = await asyncio.gather(review_task, lean_task, return_exceptions=True)
            review = results[0] if not isinstance(results[0], Exception) else {
                "verdict": "pass", "scores": {}, "issues": [], "suggestions": "",
                "summary": f"自审核异常: {results[0]}",
                "tokens_used": 0, "latency": 0,
            }
            lean_result = results[1] if not isinstance(results[1], Exception) else None
        else:
            review = await review_task
            lean_result = None

        review_tokens += review.get("tokens_used", 0)
        review_latency += review.get("latency", 0)
        if lean_result:
            lean_latency += lean_result.get("latency", 0)

        review_pass = review.get("verdict") == "pass"
        lean_pass = lean_result.get("verified") if lean_result else True

        logger.info(
            f"[双重审核] [{problem.id}] 自审核={'通过' if review_pass else '不通过'}, "
            f"Lean={'通过' if lean_pass else '不通过' if lean_result else '未执行'}"
        )

        # ========== 情况 1: 两者都通过 → 直接接受 ==========
        if review_pass and lean_pass:
            current_result.review_passed = True
            current_result.dual_review_passed = True
            current_result.review_feedback = review
            current_result.lean_verification = lean_result
            current_result.review_attempts = attempt
            logger.info(f"[双重审核] [{problem.id}] 双审通过，接受答案")
            break

        # ========== 情况 2: 任一不通过 → 二次复核 ==========
        logger.info(
            f"[双重审核] [{problem.id}] 意见不一致/不通过，启动二次复核..."
        )
        secondary = await _secondary_review(
            problem, current_result, review, lean_result, logger
        )

        consensus = secondary.get("consensus", "uncertain")
        action = secondary.get("action", "accept")

        if action == "regenerate" and attempt < max_review_retries:
            # ========== 确认真实错误 → 重新生成 ==========
            logger.info(
                f"[双重审核] [{problem.id}] 确认真实错误 "
                f"({consensus}), 重新生成 ({attempt + 1}/{max_review_retries})"
            )
            combined_feedback = _build_combined_feedback(
                problem, review, lean_result, secondary
            )

            retry_result = await _do_inference(
                problem, client, review_feedback={"issues": [combined_feedback],
                                                  "suggestions": secondary.get("improvement_suggestions", "")}
            )
            total_tokens += retry_result.tokens_used
            total_latency += retry_result.latency_seconds
            current_result = retry_result

        else:
            # ========== 误判或无法确定 → 保留答案 ==========
            current_result.review_passed = (
                action == "accept" or action == "accept_with_warning"
            )
            current_result.dual_review_passed = False
            current_result.review_feedback = review
            current_result.lean_verification = lean_result
            current_result.secondary_review = secondary
            current_result.review_attempts = attempt

            if action == "accept_with_warning":
                logger.warning(
                    f"[双重审核] [{problem.id}] 保留答案（带警告）: {consensus}"
                )
            else:
                logger.info(
                    f"[双重审核] [{problem.id}] 判定为误判 ({consensus}), "
                    f"保留答案"
                )
            break

        # 如果重试已耗尽且没有 break
        if attempt >= max_review_retries:
            current_result.review_passed = False
            current_result.dual_review_passed = False
            current_result.review_feedback = review
            current_result.lean_verification = lean_result
            current_result.secondary_review = secondary
            current_result.review_attempts = attempt
            logger.warning(
                f"[双重审核] [{problem.id}] 已达最大重试次数，返回当前结果"
            )

    current_result.review_tokens_used = review_tokens
    current_result.review_latency_seconds = review_latency
    current_result.lean_latency_seconds = lean_latency
    current_result.total_tokens_used = total_tokens
    current_result.total_latency_seconds = total_latency + review_latency + lean_latency
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


async def run_inference_multi_vote(
    problem: Problem,
    num_samples: int = 3,
    temperatures: list[float] | None = None,
) -> InferenceResult:
    """自一致性投票：并行采样 N 个结果，归一化答案后多数投票选出胜出答案。

    与 run_inference_multi() 的区别：
    - run_inference_multi():   返回 N 个独立结果，每个样本单独评判
    - run_inference_multi_vote(): 返回 1 个投票胜出结果，只评判一次

    投票策略：
    1. 并行采样 N 个结果（温度微扰动，确保路径差异）
    2. 用 _normalize_answer 归一化各样本答案（LaTeX/空白/分数差异）
    3. Counter 多数投票，同票时取首个达到该票数的样本（确定性）
    4. 全部失败（无答案）时回退为第一条样本（带错误信息）

    返回:
        InferenceResult：胜出样本的 answer/reasoning/raw_response，
        tokens_used 为各样本之和，投票统计写入 vote_info。
    """
    if temperatures is None:
        if num_samples <= len(_DEFAULT_MULTI_TEMPERATURES):
            temps = _DEFAULT_MULTI_TEMPERATURES[:num_samples]
        else:
            temps = [round(0.4 + i * 0.5 / max(num_samples - 1, 1), 2) for i in range(num_samples)]
    else:
        temps = temperatures[:num_samples]

    logger.info(
        f"Self-consistency vote [{problem.id}]: {num_samples} samples, temps={temps}"
    )
    tasks = [_run_inference_with_sample(problem, i, temps[i]) for i in range(num_samples)]
    results = await asyncio.gather(*tasks)

    # 归一化答案 → 投票
    # 用 _voting_key：文本归一化后若可解析为数字再按数值归一化（统一 1/2 与 0.5）
    keys = [_voting_key(r.answer) for r in results]
    vote_counts = Counter(keys)

    # 找最高票数；同票时取首个达到该票数的样本（保持确定性）
    winner_index = 0
    max_votes = -1
    seen_votes = {}
    for i, key in enumerate(keys):
        if key:
            seen_votes.setdefault(key, 0)
            seen_votes[key] += 1
            if seen_votes[key] > max_votes:
                max_votes = seen_votes[key]
                winner_index = i

    winner = results[winner_index]

    # 若胜出样本无答案（全部失败），回退为第一条错误信息
    fallback_error = None
    if not _voting_key(winner.answer):
        for r in results:
            if r.error:
                fallback_error = r.error
                break

    # tokens 汇总（不含审核 token，多采样模式未启用审核）
    total_tokens = sum(r.tokens_used for r in results)
    total_latency = round(sum(r.latency_seconds for r in results), 2)

    # 组装 vote_info（复制结果避免影响原始字典，Counter 需先转普通 dict 便于 JSON 序列化）
    winner.vote_info = {
        "vote_counts": dict(vote_counts),
        "num_samples": num_samples,
        "sampled_answers": [r.answer for r in results],
        "winner_temperature": temps[winner_index],
        "tie_broken": sum(1 for v in vote_counts.values() if v == max_votes) > 1 if max_votes > 0 else False,
        "fallback_used": not _voting_key(winner.answer),
    }
    if fallback_error:
        winner.error = fallback_error
    winner.tokens_used = total_tokens
    winner.total_tokens_used = total_tokens
    winner.latency_seconds = total_latency
    winner.total_latency_seconds = total_latency

    logger.info(
        f"Self-consistency vote [{problem.id}] -> winner #{winner_index} "
        f"(temp={temps[winner_index]}): {winner.answer[:80]} | votes={dict(vote_counts)}"
    )
    return winner


# ═══════════════════════════════════════════════════════════════════
# 难题分级求解（tiered）：适配主版本与赛事提交版同构逻辑
# ═══════════════════════════════════════════════════════════════════

# 题型领域 → 快车道倾向
_TIER_FAST_DOMAINS = (
    "选择", "填空", "arithmetic", "算术", "计算", "运算",
    "choice", "fill", "multiple_choice", "计算题",
)

# 题型领域 → 深度通道倾向
_TIER_DEEP_DOMAINS = (
    "证明", "证明题", "不等式证明", "几何证明", "数论", "组合数学",
    "组合", "图论", "几何", "不等式", "abstract_algebra", "topology",
    "complex_analysis", "real_analysis", "functional_analysis",
    "differential_geometry", "number_theory", "combinatorics",
    "graph_theory", "inequality", "geometry",
)

# 竞赛风格关键词
_TIER_DEEP_KEYWORDS = (
    "imo", "竞赛", "奥数", "奥林匹克", "prove", "proof", "证明",
    "不等式", "同余", "素数", "质数", "费马", "欧拉", "galois",
    "有限域", "勒让德", "构造性", "充分必要条件", "存在性", "唯一性",
    "一般性", "充分性", "必要性", "反证法", "归纳法", "不动点",
)

# 简单风格关键词
_TIER_FAST_KEYWORDS = (
    "选择", "单选", "填空", "计算", "求值", "化简", "简算",
    "evaluate", "compute", "simplify", "calculate", "求导", "求积分", "解方程",
)

_TIER_FAST_MAX = 2.0
_TIER_DEEP_MIN = 4.0


def _tier_static_assess(problem_text: str, domain: str = None):
    """静态特征预判（零 LLM 调用）。返回 (tier, score, evidence)。"""
    text = problem_text or ""
    d = (domain or "").lower()
    score = 3.0
    evidence: list[str] = []
    n = len(text)

    for kw in _TIER_FAST_DOMAINS:
        if kw.lower() in d:
            score -= 0.8
            evidence.append(f"fast:domain:{kw}")
            break
    for kw in _TIER_FAST_KEYWORDS:
        if kw.lower() in text.lower():
            score -= 0.4
            evidence.append(f"fast:kw:{kw}")
            break
    if n < 150:
        score -= 0.5
        evidence.append("fast:short_text")

    for kw in _TIER_DEEP_DOMAINS:
        if kw.lower() in d:
            score += 1.0
            evidence.append(f"deep:domain:{kw}")
            break
    for kw in _TIER_DEEP_KEYWORDS:
        if kw.lower() in text.lower():
            score += 0.5
            evidence.append(f"deep:kw:{kw}")
            break
    if n > 500:
        score += 1.0
        evidence.append("deep:long_text")

    score = min(5.0, max(1.0, score))
    tier = "fast" if score <= _TIER_FAST_MAX else (
        "deep" if score >= _TIER_DEEP_MIN else "standard")
    return tier, score, evidence


async def run_inference_tiered(
    problem: Problem,
    enable_review: bool = True,
    enable_lean: bool = True,
) -> InferenceResult:
    """难题分级求解：静态预判 → fast/standard/deep 资源分配。

    与赛事提交版 DifficultyRouter 同构：
    - fast:     单次推理，关闭审核（最快）
    - standard: 标准推理 + 1 轮审核（默认）
    - deep:     3 采样投票 + 额外审核回环（覆盖更多推理路径）
    """
    tier, static_score, evidence = _tier_static_assess(
        problem.question, getattr(problem, "domain", None))

    if tier == "fast":
        result = await run_inference(
            problem,
            enable_review=enable_review,
            max_review_retries=0,
            enable_lean=enable_lean,
        )
    elif tier == "deep":
        # deep 档：多采样投票 + 温度分层
        result = await run_inference_multi_vote(
            problem,
            num_samples=3,
            temperatures=[0.3, 0.5, 0.7],
        )
        # 额外做一次审核，若不通过则重试 1 轮
        if enable_review and not result.error:
            review = await _self_review(problem, result)
            if review.get("verdict") != "pass":
                retry = await run_inference(
                    problem,
                    enable_review=enable_review,
                    max_review_retries=1,
                    enable_lean=enable_lean,
                )
                if not retry.error:
                    result = retry
    else:
        result = await run_inference(
            problem,
            enable_review=enable_review,
            max_review_retries=1,
            enable_lean=enable_lean,
        )

    result.extra = dict(result.extra or {})
    result.extra.update({
        "tier": tier,
        "tier_static_score": round(static_score, 2),
        "tier_evidence": evidence[:6],
    })
    logger.info(
        "Tiered[%s] %s solved in %.1fs, evidence=%s",
        tier, problem.id, result.latency_seconds, evidence[:3],
    )
    return result
