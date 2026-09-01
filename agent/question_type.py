from __future__ import annotations
"""题型识别与差异化策略（v2.6）。

基于关键词识别题型：证明题 / 选择题 / 判断题 / 填空题 / 解答题。
不同题型采用差异化解题策略：
- 选择题：利用选项逆推验证；
- 判断题：不确定时合理猜测；
- 证明题：对每一步证明步骤反复校验；
- 解答题：附带答案进行结果检测。
"""

import re

# ---------------------------------------------------------------------------
# 题型名称常量
# ---------------------------------------------------------------------------
QT_PROOF = "证明题"
QT_CHOICE = "选择题"
QT_JUDGE = "判断题"
QT_FILL = "填空题"
QT_SOLUTION = "解答题"

_QUESTION_TYPES = (QT_PROOF, QT_CHOICE, QT_JUDGE, QT_FILL, QT_SOLUTION)


# ---------------------------------------------------------------------------
# 关键词信号表
# ---------------------------------------------------------------------------
# 选项标记：A. / (A) / A、/ A） / 【A】 等（选择题强信号）
# 2026-09-01 修复（系统根因）：原正则含 [\s:：]|$ 分隔符，把数学正文里的
# (b - a)、(a, b)、 a 、(a) 误判成选项 → PB 证明题 39/60 被判选择题，
# 模型被误导只输出选项字母，且 Lean 门禁（is_proof）被挡在门外。
# 新规则：① 字母必须紧跟标点（. 、 ) 】 等），空格不算分隔符；
#         ② 命中标记数 ≥2 才算选择题（杜绝孤立 (a) / (b-a) 误判）；
#         ③ 选项关键词（选择/选项/选出…）仍为强信号，1 个即判选择题。
_OPTION_MARK_RE = re.compile(
    r"(?:^|[\s(（\[【])([A-Da-d])(?:[\.、\)）\]】]|[：:])",
    re.MULTILINE,
)

# 数学正文信号：标记后紧跟这些字符 → 是数学表达式不是选项
_MATH_AFTER = ("\\", "$", ",", "，", "-", "=", "\\in", "\\neq", "\\leq", "\\geq")


def _count_option_marks(text: str) -> int:
    """统计真实选项标记数（排除数学正文误判）。

    数学正文里的 (b - a) / (a, b) / (a)f / \\item[(a)] / K (\\neq D) 等
    会被过滤：标记后紧跟数学符号、或前导是 \\item 分点列表 → 不算选项。
    """
    n = 0
    for m in _OPTION_MARK_RE.finditer(text):
        # 1) 前导 \\item[(a)] 分点列表（LaTeX enumerate）
        pre = text[max(0, m.start() - 12):m.start()]
        if "item[" in pre or "\\item" in pre:
            continue
        # 2) 标记后紧跟数学符号/公式起始 → 数学正文
        after = text[m.end():m.end() + 4].lstrip()
        if after.startswith(_MATH_AFTER):
            continue
        # 3) 括号式标记 (a) 后紧跟字母/数字/括号/右括号（如 f(a))、(b-a)f(f(a))）
        #    → 数学调用/嵌套，不是选项
        if m.group(0).strip().endswith((")", "）", "]", "】")):
            nxt = text[m.end():m.end() + 1]
            if nxt and (nxt.isalnum() or nxt in "([{（)"):
                continue
        n += 1
    return n

# 填空题空白占位：___ / ＿ / 【空】 / ()
_UNDERSCORE_BLANK_RE = re.compile(r"_{2,}|＿{2,}|\[空\]|【空】")


def classify_question_type(problem: str) -> str:
    """基于关键词识别题型，返回 证明题/选择题/判断题/填空题/解答题 之一。

    优先级（信号强度由强到弱）：
        选择题 > 证明题 > 判断题 > 填空题 > 解答题(兜底)
    """
    text = problem or ""
    low = text.lower()

    # 1) 选择题：选项标记 ≥2 个 / 选项关键词（信号最专一）
    # 2026-09-01：标记数 ≥2 才判选择题。数学正文里的 (b-a) / (a, b) / (a)f /
    # \item[(a)] 均被排除（见 _is_option_mark），杜绝 PB 证明题 39/60 误判。
    if (_count_option_marks(text) >= 2) or any(
        k in low for k in ("选择", "选项", "选出", "单选", "多选", "下列选项中", "正确的选项")
    ):
        return QT_CHOICE

    # 2) 证明题
    if any(k in low for k in ("证明", "求证", "试证", "prove", "proof", "show that", "verify that")):
        return QT_PROOF

    # 3) 判断题
    if any(k in low for k in ("判断", "对错", "正误", "对还是错", "true or false", "是否正确")):
        return QT_JUDGE

    # 4) 填空题
    if _UNDERSCORE_BLANK_RE.search(text) or any(
        k in low for k in ("填空", "填入", "填上", "blank")
    ):
        return QT_FILL

    # 5) 解答题（兜底）
    return QT_SOLUTION


# ---------------------------------------------------------------------------
# 差异化策略提示（注入求解 prompt）
# ---------------------------------------------------------------------------
_TYPE_HINTS: dict[str, str] = {
    QT_CHOICE: (
        "\n[题型策略] 本题为选择题。请先逐个分析选项，"
        "必要时将候选选项代入原题条件进行逆推验证以排除错误项，"
        "最终答案只输出选项字母（如 A / B / C / D）。"
    ),
    QT_JUDGE: (
        "\n[题型策略] 本题为判断题。请判断命题正误；"
        "若依据不足以完全确定，可基于最合理的推断给出判断，不要留空。"
    ),
    QT_PROOF: (
        "\n[题型策略] 本题为证明题。请逐步严格证明，每一步标注依据，"
        "并对关键步骤进行反复校验，确保逻辑严密、无跳步。"
    ),
    QT_FILL: (
        "\n[题型策略] 本题为填空题。请推导/计算出确切结果填入空白处，"
        "最终答案只输出结果本身。"
    ),
    QT_SOLUTION: (
        "\n[题型策略] 本题为解答题。请完整求解，"
        "并在【最终答案】给出简洁结果以供结果检测。"
    ),
}


def get_question_type_hint(qtype: str) -> str:
    """获取某题型的差异化策略提示片段；未知题型返回空串。"""
    return _TYPE_HINTS.get(qtype, "")


# ---------------------------------------------------------------------------
# 选择题选项提取（用于逆推验证）
# ---------------------------------------------------------------------------
_OPTION_SPLIT_RE = re.compile(
    r"(?:[（(]\s*([A-Da-d])\s*[）)]|([A-Da-d])\s*[\.、:：])\s*"
)


def extract_options(problem: str) -> list[tuple[str, str]]:
    """从选择题题干提取选项文本，返回 [(标签, 内容), ...]。

    支持形态：A. xxx / (A) xxx / A、xxx / A）xxx，选项间以换行或分号分隔。
    提取失败返回空列表（不阻塞主流程，模型仍能看到完整题干）。
    """
    text = problem or ""
    if not _OPTION_MARK_RE.search(text):
        return []

    # 找到选项起始位置：优先从"选项"关键词后，其次从第一个选项标记后
    start = 0
    m_kw = re.search(r"(?:选项|下列|以下|选出)", text)
    if m_kw:
        start = m_kw.end()

    segment = text[start:]
    opts: list[tuple[str, str]] = []
    # 逐项匹配：标签 + 内容（到下一个标签/换行/分号截止）
    for m in _OPTION_SPLIT_RE.finditer(segment):
        label = (m.group(1) or m.group(2)).upper()
        content_start = m.end()
        # 内容到下一个选项标记或行尾/分号截止
        nxt = _OPTION_SPLIT_RE.search(segment, content_start)
        end = nxt.start() if nxt else len(segment)
        content = segment[content_start:end].strip()
        # 去掉行尾残留分隔符
        content = re.split(r"[\n；;]", content)[0].strip()
        if content:
            opts.append((label, content))
        if len(opts) >= 8:  # 安全上限
            break
    return opts


def format_options(problem: str) -> str:
    """把选择题选项格式化为清单文本，注入求解 prompt；无选项返回空串。"""
    opts = extract_options(problem)
    if not opts:
        return ""
    lines = ["\n[已知选项]"]
    for label, content in opts:
        lines.append(f"{label}. {content}")
    return "\n".join(lines)
