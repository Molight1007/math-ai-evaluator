"""节点声明的形态判定：这是「提问」还是「宣告」。

背景（2026-11-02）
------------------
蓝图节点只有一个语句槽位，而它同时承载三种语义不同的东西：

    ① 计划期的「要证什么」        —— 目标，**允许错、允许是猜的**
    ② 求解期的「我猜结果是这个」   —— 猜想，未判定
    ③ 入库期的「这已经是事实」     —— 结论，必须已验证

三者共用一个槽 ⇒ 下游拿到每句话时无法区分权威性 ⇒
「先证明、再声明」这条纪律在结构上**无法执行**（只能靠提示词约定，
而历史反复证明提示词禁令没有代码执行）。

本模块只做一件事：给定一段自然语言，判定它更像**提问**还是**宣告**，
并给出它能否被翻译成形式命题的粗估等级。

刻意不做的事
------------
- **不判数学对错**。对错由检查器裁决，本模块无权置喙。
- **不判死任何节点**。结果是诊断量，不是闸门。
- **不引入 LLM 调用**。纯字符串规则 ⇒ 可离线全量回放，零配额。

★ 口径声明（引用时必须带上）
    formality 是**机械分类的粗估**，不是人工核验的形式化成功率。
    它只给「上界」：被判 full 的节点也可能根本形式化不出来，
    但被判 none 的节点基本不可能形式化。**不得**把它当成功率引用。

设计要点：判定顺序即防假阳性的全部
----------------------------------
必须先问「有没有提问动词」，再问「像不像赋值等式」。
反过来会把「证明 x = 42」判成结论（它是目标）——这正是历史宽口径
值断言检测 32.4% 的假阳性来源（题设方程被判断言）。
"""

import re

__all__ = [
    "FORM_GOAL", "FORM_RESULT", "FORM_AMBIGUOUS",
    "FORMALITY_FULL", "FORMALITY_PARTIAL", "FORMALITY_NONE",
    "classify_claim", "is_question_form", "formality_of", "summarize",
]

FORM_GOAL = "goal"              # 提问 / 待证
FORM_RESULT = "result"          # 宣告 / 已断言
FORM_AMBIGUOUS = "ambiguous"    # 两者都不像（多为推导片段或条件陈述）

FORMALITY_FULL = "full"         # 含关系符或量词，可写成单条形式命题
FORMALITY_PARTIAL = "partial"   # 需要补定义/辅助结构
FORMALITY_NONE = "none"         # 作图 / 算法 / 程序描述，基本不可形式化

# ---------------------------------------------------------------------------
# 提问标记：区分「强标记」与「弱动词」
# ---------------------------------------------------------------------------
# ★ 为什么必须分级（2026-11-02 实测出来的）：
#   「代入后化简得到剩余部分」里的「化简」是**过程描述**，不是提问。
#   若把所有动词一视同仁地按 14 字窗口匹配，这句话会被判成目标形态。
#   强标记本身语义就指向「待完成」（证明 / 是否 / 多少），出现在句中
#   仍成立；弱动词（求 / 计算 / 化简）只有出现在**句首**才是祈使句
#   —— 数学题的目标句几乎都以动词起头。
_ASK_STRONG = (
    "是否存在", "是否", "能否", "证明", "求证", "试证", "反证",
    "是否有", "有多少", "多少种", "是不是",
)
_ASK_WEAK = (
    "求", "确定", "找出", "求出", "构造", "判断", "讨论", "计算",
    "验证", "检验", "给出", "推导", "估计", "比较", "说明", "展示",
    "举出", "列举", "化简", "展开", "解方程", "解不等式", "求值",
)
# 兼容旧名（本模块内部只用上面两个）
_ASK_ZH = _ASK_STRONG

# 英文。用词边界避免 "prove" 命中 "proven" 的误伤（实际影响很小，保守处理）。
_ASK_EN = (
    "prove", "show that", "show the", "find", "determine", "construct",
    "compute", "calculate", "evaluate", "verify", "derive", "estimate",
    "whether", "how many", "does there exist", "is there", "solve",
)

# ---------------------------------------------------------------------------
# 宣告标记：「结论」「因此」这类词之后跟的通常是已断言的结论
# ---------------------------------------------------------------------------
_ASSERT_ZH = (
    "结论", "因此", "所以", "故", "最终答案", "答案是", "答案：", "答案为",
    "由此可得", "从而得到", "综上", "即证", "得证", "可得",
)
_ASSERT_EN = (
    "therefore", "thus", "hence", "so we get", "the answer is",
    "we conclude", "conclusion",
)

# ---------------------------------------------------------------------------
# 可形式化等级：不可形式化的标志（几何作图、算法/程序描述）
# ---------------------------------------------------------------------------
_NO_FORMAL = (
    "作图", "画出", "画出图形", "辅助线", "作辅助线", "尺规", "描点",
    "算法", "程序", "伪代码", "流程图", "数据结构", "时间复杂度", "空间复杂度",
    "构造一个算法", "写出程序", "编程",
)

# 关系符与量词 —— 有它们才可能写成一条 `P` 形式的命题
_REL_SYMBOLS = ("=", "<", ">", "≤", "≥", "≠", "≡", "∣", "|", "∈", "⊆", "⊂", "∤")
_QUANT_ZH = ("对所有", "对任意", "对一切", "存在", "任意", "每个", "至少", "至多", "唯一")
_QUANT_EN = ("for all", "for every", "for any", "there exists", "exists",
             "at least", "at most", "unique", "∀", "∃")

# 单个赋值等式的左侧：允许 `a`, `a_n`, `a_{n}`, `x_1`, `T'`, `f(x)` 不取（含括号视为表达式）
_LHS_ATOM = re.compile(r"^[A-Za-z\u0370-\u03ff][A-Za-z0-9_'\u0370-\u03ff]*(?:_\{[^}]*\}|_[A-Za-z0-9]+|\^\{?[A-Za-z0-9]+\}?)*\s*$")

# 行内等式切分：只按**单**关系符切一次，避免把 `x^2 + y^2 = 3` 的左侧当成原子
_EQ_SPLIT = re.compile(r"(?<![<>≤≥≠])=(?!=)")

# 句首窗口：强标记（「证明」「是否」）在此窗口内即算「这句在提问」
_HEAD_WINDOW = 14
# 弱动词窗口：必须**紧贴句首**才算祈使句（"代入后化简"里的"化简"不算）
_HEAD_WEAK_WINDOW = 4
# 英文按字符算，词更长，窗口相应放宽
_HEAD_WINDOW_EN = 24


def _norm(text) -> str:
    """归一：去首尾空白、合并空白。**不改动符号**（符号是判定依据）。"""
    if not text:
        return ""
    s = str(text).replace("\u3000", " ").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_any(text: str, needles) -> str:
    """返回第一个命中的标记（空串表示没命中）。"""
    for n in needles:
        if n in text:
            return n
    return ""


def _looks_like_assignment(text: str) -> bool:
    """是否是「单一符号 = 非空右式」的赋值形态。

    ★ 为什么左侧必须是**单一符号**：
      `x^2 + y^2 + z^2 = 3` 是题设方程/条件，不是「断言了某个值」。
      历史检测（宽口径）把它算作值断言，造成 32.4% vs 4.5% 的 7 倍偏差。
      这里要求左侧**不含运算符**，正是为了排除这类假阳性。
    """
    parts = _EQ_SPLIT.split(text, maxsplit=1)
    if len(parts) != 2:
        return False
    lhs, rhs = parts[0].strip(), parts[1].strip()
    if not lhs or not rhs:
        return False
    # 右侧允许带后续说明（如 "a_n = n+1，对所有 n 成立"），取逗号/顿号/句号前
    rhs_head = re.split(r"[，,。；;]", rhs, maxsplit=1)[0].strip()
    if not rhs_head:
        return False
    return bool(_LHS_ATOM.match(lhs))


def is_question_form(text) -> bool:
    """这段文字是否在**要求**做某事（而非宣布某事成立）。

    判定用两档窗口：
      · 强标记（证明 / 是否 / 多少）—— 出现在句首 14 字内即成立；
      · 弱动词（求 / 计算 / 化简）—— 必须紧贴句首 4 字内才算祈使句。
    分档的理由见 `_ASK_WEAK` 上方注释（"代入后化简"不能判成提问）。
    """
    s = _norm(text)
    if not s:
        return False
    if _has_any(s[:_HEAD_WINDOW], _ASK_STRONG):
        return True
    if _has_any(s[:_HEAD_WEAK_WINDOW], _ASK_WEAK):
        return True
    if _has_any(s.lower()[:_HEAD_WINDOW_EN], _ASK_EN):
        return True
    # 疑问句尾
    if s.endswith(("?", "？")):
        return True
    return False


def _ask_evidence(s: str) -> str:
    """返回命中的提问标记（空串 = 没命中）。"""
    ev = _has_any(s[:_HEAD_WINDOW], _ASK_STRONG)
    if ev:
        return ev
    ev = _has_any(s[:_HEAD_WEAK_WINDOW], _ASK_WEAK)
    if ev:
        return ev
    return _has_any(s.lower()[:_HEAD_WINDOW_EN], _ASK_EN)


def formality_of(text) -> str:
    """粗估：这段文字能否写成一条形式命题。

    full    —— 含关系符或量词，且不是作图/算法类
    partial —— 其余（需要补定义或辅助结构才能形式化）
    none    —— 明确的作图 / 算法 / 程序描述
    """
    s = _norm(text)
    if not s:
        return FORMALITY_NONE
    if _has_any(s, _NO_FORMAL):
        return FORMALITY_NONE
    has_rel = _has_any(s, _REL_SYMBOLS) != ""
    has_quant = (_has_any(s, _QUANT_ZH) != "") or (_has_any(s.lower(), _QUANT_EN) != "")
    if (has_rel or has_quant) and len(s) <= 240:
        return FORMALITY_FULL
    return FORMALITY_PARTIAL


def classify_claim(text) -> dict:
    """判定一段节点声明的形态。

    返回 dict：
        form       goal / result / ambiguous
        evidence   命中的证据标记（空串 = 无）
        formality  full / partial / none
        text_len   归一后长度

    ★ 判定顺序不可交换：先问「是不是提问」，再问「像不像赋值等式」。
      反序会把「证明 x = 42」判成结论。
    """
    s = _norm(text)
    out = {
        "form": FORM_AMBIGUOUS,
        "evidence": "",
        "formality": FORMALITY_NONE,
        "text_len": len(s),
    }
    if not s:
        return out
    out["formality"] = formality_of(s)

    # ① 提问优先
    if is_question_form(s):
        out["form"] = FORM_GOAL
        out["evidence"] = _ask_evidence(s) or "?"
        return out

    # ② 显式宣告词（「结论」「因此」）—— 只认句首，正文中段出现不算
    ev = _has_any(s[:_HEAD_WINDOW], _ASSERT_ZH)
    if ev:
        out["form"] = FORM_RESULT
        out["evidence"] = ev
        return out
    ev = _has_any(s.lower()[:_HEAD_WINDOW_EN], _ASSERT_EN)
    if ev:
        out["form"] = FORM_RESULT
        out["evidence"] = ev
        return out

    # ③ 单一赋值等式
    if _looks_like_assignment(s):
        out["form"] = FORM_RESULT
        out["evidence"] = "assignment"
        return out

    return out


def summarize(rows) -> dict:
    """把一串 classify_claim 结果汇总成计数表。

    rows: list[dict]（每项至少含 form / formality）
    """
    forms = {FORM_GOAL: 0, FORM_RESULT: 0, FORM_AMBIGUOUS: 0}
    forms_by = {FORM_GOAL: {}, FORM_RESULT: {}, FORM_AMBIGUOUS: {}}
    formality = {FORMALITY_FULL: 0, FORMALITY_PARTIAL: 0, FORMALITY_NONE: 0}
    n = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        f = r.get("form")
        if f not in forms:
            continue
        n += 1
        forms[f] += 1
        fm = r.get("formality")
        if fm in formality:
            formality[fm] += 1
            by = forms_by[f]
            by[fm] = by.get(fm, 0) + 1
    return {
        "n": n,
        "forms": forms,
        "forms_by_formality": forms_by,
        "formality": formality,
    }
