from __future__ import annotations
"""答案提取与格式化工具"""

import re

# ------------------------------------------------------------------
# 元语句模式：模型推理的收尾/自我怀疑/格式化提示，不是答案
# ------------------------------------------------------------------
_META_PATTERNS = [
    # 收尾/整理语句
    r"(?:现在|接下来|然后|最后|最终)\s*[,，]?\s*(?:将|请|可以|需要)\s*.{0,20}(?:整理|结构化|格式化|呈现|表达|写出|总结|组织)",
    r"(?:将|请|可以|需要)\s*(?:上述|这些|以上|以上内容|这些步骤|上述步骤)\s*.{0,10}(?:整理|结构化|总结|写成|转化为|表示为)",
    # 自我怀疑/不确定/转折
    r"^或[者许]?[,，]?\s*可能.{0,30}(?:错[了误]|不对|有问题)",
    r"^(?:我(?:可能|好像|似乎|不确定|不太确定|怀疑)|可能我|或许我)",
    r"(?:我(?:需要|应该|还得|还要|再)|让我(?:们?))(?:重新.{0,10}(?:检查|验证|思考|计算|推导)|再.{0,10}(?:想|算|检查|看|确认))",
    r"^(?:等[等下下]|稍等|嗯+|唔+|呃+)[,，]?\s*",
    r"^(?:不过|但是|然而|可是|只是|然而)[,，]?\s*.{0,40}(?:不是|可能|也许|应该|需要|应该|想|考虑)",
    r"(?:这(?:可能|也许|应该|似乎)\s*.{0,20}(?:不是|不对|有误|有问题)|(?:不|没有).{0,5}(?:效|完整|确定|充分))",
    # 追问/反问（不含答案）
    r"^(?:为什么|怎么|如何|怎么样|是什么|这样可以吗|对吗|是吗|正确吗)",
    r"[?？]\s*$",  # 以问号结尾（通常在提问，不是给出答案）
    # 格式化占位/空答案前缀
    r"^(?:\[|\（|【).{0,5}(?:答案|最终答案|结果|解答|请在此|此处).{0,5}(?:\]|\）|】)",
    r"^(?:答案|结果|解答|最终答案|通解|特解|解集)[:：]?\s*$",
    r"^(?:通解|特解|解集|一般解)[:：]\s*$",
    # 纯结构/格式行
    r"^\s*(?:步骤\s*\d+|第\s*\d+\s*步|Step\s*\d+)\s*[：:：]*\s*$",
    # 被截断的 LaTeX 环境开头
    r"^\\begin\{[^}]+\}\s*$",
    r"^\\begin\{[^}]+\}\s*\\[a-zA-Z]+\s*$",
]

_META_RE = re.compile("|".join(_META_PATTERNS))


def _is_meta_line(line: str) -> bool:
    """判断一行文本是否是元语句（非答案内容）"""
    stripped = line.strip()
    if not stripped:
        return True
    # 纯标点
    if re.fullmatch(r"[\s,，。.、；;：:！!？?…\-—=_]+", stripped):
        return True
    # 匹配已知元模式
    if _META_RE.search(stripped):
        return True
    # 没有数学符号也没有数字/字母 → 大概率是叙述，不是答案
    has_math = bool(re.search(r"[$\\=<>≤≥→⇒]|\b[a-zA-Z]{2,}\b|[α-ωΑ-Ω]", stripped))
    has_number = bool(re.search(r"\d", stripped))
    has_answer_kw = bool(re.search(r"(?:[选选]项\s*[A-D]|正确[的选项]|答案[是为]|故选|故[选为])", stripped))
    # 超过50字符且没有数学符号/数字 → 极可能是叙述
    if len(stripped) > 50 and not has_math and not has_number and not has_answer_kw:
        return True
    return False


def _is_incomplete_answer(text: str) -> bool:
    """判断一个候选答案是否明显不完整，应被拒绝"""
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    # 以这些词结尾 → 只是前缀，不是完整答案
    if re.search(r"(?:通解|特解|解集|答案|最终答案|结果|应选|故)[为是:]\s*$", stripped, re.IGNORECASE):
        return True
    # 以 \begin{xxx} 结尾 → LaTeX 被截断
    if re.search(r"\\begin\{[^}]+\}\s*$", stripped):
        return True
    # 纯数学公式但非常短（< 10 字符）且没有答案标识 → 可能只是中间步骤
    if len(stripped) < 10 and not re.search(r"(?:=|答案|为|选)", stripped):
        return False  # 短公式不一定错，保留
    # 包含"但是""不过"等转折词且没有等号/答案标识 → 元叙述
    if re.search(r"(?:不过|但是|然而|可是|只是).{0,30}$", stripped) and not re.search(r"[=$＝]", stripped):
        return True
    return False


def _extract_last_valid_answer(text: str) -> str:
    """从文本尾部向前找第一个非元语句的有效行"""
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    # 策略 A：从后往前找第一个包含 LaTeX/数学符号/选项标识的非元行
    for i in range(len(lines) - 1, max(len(lines) - 20, -1), -1):
        line = lines[i]
        if _is_meta_line(line):
            continue
        # 高优先级：明确答案标识
        if re.search(r"(?:[选选]项\s*[A-D]|正确[的选项]|故[选为]|答案为?|最终答案|答案[是为]|应选|综上[,，]?\s*[A-D])", line):
            return clean_answer(line)
    # 策略 B：找第一个含数学内容的非元行
    for i in range(len(lines) - 1, max(len(lines) - 20, -1), -1):
        line = lines[i]
        if _is_meta_line(line):
            continue
        if re.search(r"[$\\=]|\d", line):
            return clean_answer(line)
    # 策略 C：最后一道防线 — 找第一个非元行
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not _is_meta_line(line):
            return clean_answer(line)
    return ""


def extract_final_answer(text: str) -> str:
    """
    从模型输出中提取最终答案。

    多级提取策略：
    1. 查找【最终答案】/ \\boxed{} 等显式标记
    2. 从文本尾部跳过元语句向前扫描
    3. LaTeX 表达式兜底
    4. 数字表达式兜底
    5. 全文兜底
    """
    if not text:
        return ""

    # 策略 1：【最终答案】/ 答案: / Final answer: 等显式标记
    # BUG-10 修复：多行答案用贪婪匹配到明确的节标记或文本末尾
    patterns = [
        (r"【最终答案】\s*\n?\s*([\s\S]+)", False),
        (r"最终答案[:：]\s*([\s\S]+)", False),
        (r"答案[:：]\s*([\s\S]+)", False),
        (r"[Ff]inal\s*[Aa]nswer[:：]\s*([\s\S]+)", False),
    ]
    for pattern, is_boxed in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            captured = match.group(1).strip()
            # 裁剪到第一个节标记（【...】/ #### / --- / == ）
            captured = re.split(r'\n\n(?:【|####|---|==|答案|最终答案)', captured)[0].strip()
            if (captured and len(captured) > 1
                    and not _is_meta_line(captured)
                    and not _is_incomplete_answer(captured)):
                return clean_answer(captured)

    # 策略 2：\\boxed{...} 格式（支持任意嵌套深度）
    ans = _extract_boxed_nested(text)
    if ans and not _is_incomplete_answer(ans):
        return ans

    # 策略 3：从尾部跳过元语句向前找有效答案行（核心修复）
    last_valid = _extract_last_valid_answer(text)
    if last_valid and len(last_valid) > 1 and not _is_incomplete_answer(last_valid):
        return last_valid

    # 策略 4：扫描全文找 LaTeX $...$ / $$...$$ / \(...\) 取最后一个
    latex_match = re.findall(
        r"(?:\$\$?\s*)(.+?)(?:\s*\$?\$)|(?:\$)([^\$]+)(?:\$)|(?:\\\()(.+?)(?:\\\))",
        text,
    )
    if latex_match:
        candidates = []
        for groups in latex_match:
            for g in groups:
                if g and g.strip() and not _is_meta_line(g.strip()) and not _is_incomplete_answer(g.strip()):
                    candidates.append(g.strip())
        if candidates:
            return clean_answer(candidates[-1])

    # 策略 5：找最后一个数字/表达式结果
    num_match = re.findall(
        r"(?:[=＝]|结果是?|得到|求得|解得|答案为?)\s*"
        r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?"
        r"(?:\s*[-+*/×÷]\s*[-+]?\d*\.?\d+)*"
        r"(?:\s*[πeabeixyABXY𝜋]\^?\d*)*)",
        text,
    )
    if num_match:
        last = num_match[-1].strip()
        if not _is_meta_line(last) and not _is_incomplete_answer(last):
            return last

    # 策略 6：尝试忽略元语句后重新取倒数几行
    if lines := [l.strip() for l in text.strip().split("\n") if l.strip()]:
        clean_lines = [l for l in lines if not _is_meta_line(l) and not _is_incomplete_answer(l)]
        if clean_lines:
            return clean_answer(clean_lines[-1])

    # 兜底：返回全文（确保验证器有内容可评估）
    return text.strip()


def clean_answer(text: str) -> str:
    """清理答案文本，去除多余符号"""
    text = text.strip()
    # 去除编号前缀
    text = re.sub(r"^[\d]+[\.\、\)）]\s*", "", text)
    # 去除 markdown 格式
    text = text.replace("**", "").replace("__", "")
    return text


def format_response(answer: str) -> str:
    """确保 final_response 非空且可序列化"""
    if answer is None:
        return ""
    answer = str(answer).strip()
    return answer


def smart_fallback_answer(text: str) -> str:
    """
    当 extract_final_answer 返回空或不理想时的智能回退。
    从文本尾部找最后一个有实质内容（数学/答案关键词）的行，
    优于盲目的 [-500:] 截取——避免长 CoT 中取到验证/总结文字而非答案。
    """
    if not text or not text.strip():
        return ""
    text = text.strip()

    # 先试 extract_final_answer，有时它内部的多级策略能命中
    ans = extract_final_answer(text)
    if ans and len(ans) > 1 and not _is_incomplete_answer(ans) and ans != text.strip():
        return ans

    lines = text.split('\n')

    # 策略 1：从后往前找第一个含数学符号/答案关键词的非元行
    for i in range(len(lines) - 1, max(len(lines) - 30, -1), -1):
        line = lines[i].strip()
        if not line or _is_meta_line(line):
            continue
        if re.search(r'[$\\=]|\d{2,}|答案|故选|boxed|正确|选项', line):
            return clean_answer(line)

    # 策略 2：从后往前找第一个有实质内容的非空行
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line and len(line) > 2 and not _is_meta_line(line):
            return clean_answer(line)[:500]

    # 兜底：取尾部但限制长度
    return clean_answer(text[-500:])


def safe_json_serialize(obj: dict) -> dict:
    """
    安全地将字典转为 JSON 可序列化格式。
    递归处理所有值，将不可序列化的对象转为字符串。
    """
    result = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            result[key] = safe_json_serialize(value)
        elif isinstance(value, (list, tuple)):
            result[key] = [
                safe_json_serialize(v) if isinstance(v, dict)
                else str(v) if not isinstance(v, (str, int, float, bool, type(None)))
                else v
                for v in value
            ]
        elif isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value
        else:
            result[key] = str(value)
    return result


# ============================================================
# 答案有效性校验（BUG-12 修复）
# ============================================================

_REFUSAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:无法|不能|没办法|不擅长|抱歉|对不起|sorry|cannot|unable)", re.IGNORECASE),
    re.compile(r"(?:as an AI|I cannot|I don't have)", re.IGNORECASE),
    re.compile(r"^(?:\s|[{[(（])*$"),  # 纯空白/括号
    re.compile(r"^(?:未知|unknow|n/?a|none)\s*$", re.IGNORECASE),
    re.compile(r"^(?:\[|【|\\begin).{0,20}(?:答案|最终答案).{0,20}(?:\]|】|\\end)"),
]


def is_valid_final_answer(text: str) -> bool:
    """
    检查 final_answer 是否为有效的数学解答（非拒绝语、非空模板、非占位符）。
    BUG-12 修复：供 formatter 最终输出前校验，不合法则回退下一候选。
    """
    if not text or not text.strip():
        return False
    s = text.strip()
    if len(s) < 2:
        return False
    for pat in _REFUSAL_PATTERNS:
        if pat.search(s):
            return False
    return True


# ============================================================
# 答案规范化管道 (Normalization Pipeline)
# ============================================================

# 单位后缀模式（按优先级排序，长模式优先）
_UNIT_PATTERNS = [
    re.compile(r"\s*(?:厘米|cm|毫米|mm|米|m|千米|km|公里)\s*$", re.IGNORECASE),
    re.compile(r"\s*(?:千克|kg|克|g|吨|吨|斤|磅|lb)\s*$", re.IGNORECASE),
    re.compile(r"\s*(?:秒|s|分钟|min|小时|h|小时|天|d|年|year)\s*$", re.IGNORECASE),
    re.compile(r"\s*(?:度|°|°C|°F|开尔文|K|弧度|rad)\s*$", re.IGNORECASE),
    re.compile(r"\s*(?:元|美元|USD|欧元|EUR|日元|JPY|英镑|GBP)\s*$", re.IGNORECASE),
    re.compile(r"\s*(?:人|个|次|倍|%|％|百分比)\s*$", re.IGNORECASE),
]


def normalize_answer(raw: str) -> str:
    """
    6 步规范化管道，将 LLM 输出的答案转为可比较的规范形式。

    步骤:
    1. LaTeX 指令归一化（\\frac → /, \\sqrt → sqrt(), \\times → *）
    2. 隐式乘法补全（2x → 2*x）
    3. 空白与混合标点清洗
    4. 数值格式统一（1/2 → 0.5, 2.0 → 2）
    5. 单位剥离
    6. 集合/区间格式标准化

    返回归一化后的字符串。
    """
    if not raw:
        return ""
    s = raw.strip()

    # 步骤 1: LaTeX 归一化
    # \frac{a}{b} → a/b
    s = re.sub(r"\\frac\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
               r"(\1)/(\2)", s)
    # \sqrt[n]{x} → root(n, x) 或 sqrt(x)
    s = re.sub(r"\\sqrt\s*\[([^\]]+)\]\s*\{([^}]+)\}", r"root(\1,\2)", s)
    s = re.sub(r"\\sqrt\s*\{([^}]+)\}", r"sqrt(\1)", s)
    # \times → *, \div → /, \cdot → *
    s = s.replace("\\times", "*").replace("\\cdot", "*").replace("\\div", "/")
    # \pm → +- ; \mp → -+
    s = s.replace("\\pm", "+-").replace("\\mp", "-+")
    # \infty → inf, \pi → pi, \theta → theta
    for cmd, sub in [("\\infty", "inf"), ("\\pi", "pi"), ("\\theta", "theta"),
                     ("\\alpha", "alpha"), ("\\beta", "beta"), ("\\gamma", "gamma")]:
        s = s.replace(cmd, sub)
    # 清理多余的 LaTeX 命令参数
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s)

    # 步骤 2: 隐式乘法补全
    # 数字后接变量: 2x → 2*x, 3.14r → 3.14*r
    s = re.sub(r"(\d)([a-zA-Zα-ω])", r"\1*\2", s)
    # 右括号后接数字/变量: (x+1)x → (x+1)*x
    s = re.sub(r"\)\s*(\d|[a-zA-Zα-ω])", r")*\1", s)
    # 变量后接左括号: x(x+1) → x*(x+1)
    s = re.sub(r"([a-zA-Zα-ω])\s*(\()", r"\1*\2", s)
    # 右括号后接左括号: (x+1)(x-1) → (x+1)*(x-1)
    s = re.sub(r"\)\s*\(", r")*(", s)

    # 步骤 3: 空白与标点清洗
    s = re.sub(r"\s+", "", s)
    s = s.replace("，", ",").replace("。", ".").replace("；", ";")
    s = s.replace("：", ":").replace("（", "(").replace("）", ")")
    s = s.replace("【", "[").replace("】", "]")
    # 去掉前导标签文字
    s = re.sub(r"^(?:答案|最终答案|结果|选择|选项)[:：=＝]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(?:故|所以|因此|综上)[,:]?\s*", "", s, flags=re.IGNORECASE)

    # 步骤 4: 数值格式统一
    # 分数 a/b → 浮点（当 a 和 b 都是纯数字时）
    def _frac_to_decimal(m):
        try:
            return f"{float(m.group(1)) / float(m.group(2)):.6g}"
        except (ValueError, ZeroDivisionError):
            return m.group()
    s = re.sub(r"\(?(-?\d+(?:\.\d+)?)\)?/\s*\(?(\d+(?:\.\d+)?)\)?", _frac_to_decimal, s)
    # 整数去尾零: 2.0 → 2
    s = re.sub(r"(?<!\d)0(?:\.0+)?(?!\d)", "0", s)  # 零保持
    s = re.sub(r"(?<=\d)\.0+(?!\d)", "", s)

    # 步骤 5: 单位剥离
    for pat in _UNIT_PATTERNS:
        s_new = pat.sub("", s)
        if s_new:
            s = s_new

    # 步骤 6: 集合/区间标准化
    # {1,2,3} → [1,2,3] 统一用方括号
    if s.startswith("{") and s.endswith("}") and not any(ch in s for ch in ":"):
        s = "[" + s[1:-1] + "]"
    # 分隔符统一为逗号
    s = s.replace(";", ",").replace("，", ",")
    # 去除多余逗号
    s = re.sub(r",+", ",", s)

    return s.strip()


# ============================================================
# 兜底提取增强（同步自 测试工具/intern_s1.py，纯规则、不耗 LLM 预算）
# ============================================================


def _extract_boxed_nested(text: str) -> str:
    """匹配 \\boxed{...}，通过手动计数大括号处理任意嵌套深度。"""
    if not text:
        return ""

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
            candidate = _clean_extracted_answer(candidate)
            if candidate and 1 <= len(candidate) <= 200:
                return candidate

    # 2) 弱赋值模式只在尾部搜索
    m = re.search(_WEAK_ASSIGN_PATTERN[0], tail, re.MULTILINE)
    if m:
        candidate = m.group(_WEAK_ASSIGN_PATTERN[1]).strip()
        candidate = _clean_extracted_answer(candidate)
        if candidate and 1 <= len(candidate) <= 200:
            return candidate

    return ""


def _extract_tail_fallback(text: str) -> str:
    """最后手段：取最后一行非空内容作为答案（误报率高，仅作兜底）"""
    if not text:
        return ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in reversed(lines[-5:]):  # 只看最后5行
        # 跳过推理标记、半截句子
        skip_words = ["```", "wait", "let me", "now consider", "for example",
                      "we can", "since", "because", "first", "next", "then",
                      "note that", "assume", "suppose", "let's"]
        if any(line.lower().startswith(w) for w in skip_words):
            continue
        # 跳过以 "(" "[" "{" 开头（通常是公式推导）
        if line and line[0] in "([{":
            continue
        cleaned = _clean_extracted_answer(line)
        # 推理片段检测（清理后的内容仍像推理句则跳过）
        if cleaned and not _looks_like_reasoning_fragment(cleaned) and 3 <= len(cleaned) <= 200:
            return cleaned

    return ""


_REASONING_FRAGMENT_WORDS = [
    "if we", "we set", "let us", "we have", "we can", "we get", "we need",
    "so best", "it is decreasing", "note that", "assume", "suppose",
    "since", "because", "first", "next", "then", "wait", "for each",
    "for example", "the number written is", "the set", "term is",
]


def _clean_extracted_answer(text: str) -> str:
    """清理提取的答案文本；若清理后仍呈推理片段特征则返回空串"""
    if not text:
        return ""
    # 去掉开头的冒号、空格、破折号
    text = re.sub(r"^[:\s\-–—]+", "", text)
    # 去掉尾部的空格和标点
    text = text.strip().rstrip(".;,，。；")
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
    low = text.lower()
    for w in _REASONING_FRAGMENT_WORDS:
        if low.startswith(w):
            return True
    # 以 "X=..." 开头但后面跟着推理连词（如 "2: π(2)=3 ≤2, so floor=1"）
    if re.match(r"^\w+\s*[:=]", low) and re.search(r"\b(so|then|since|because|thus)\b", low):
        return True
    return False


def rescue_final_answer(text: str) -> tuple[str, str]:
    """答案兜底提取（纯规则、不消耗 LLM 预算）：依次尝试
    嵌套 boxed → 强结论模式 → 尾部兜底。

    同步自 测试工具/intern_s1.py::_rescue_answer，但去掉了 DeepSeek 跨模型
    通道（赛事提交版只有平台注入的单一 client，竞赛禁止硬编码 API Key）。

    参数:
        text: LLM 原始输出

    返回:
        (提取到的答案, 提取来源)；未提取到返回 ("", "")。
    """
    if not text:
        return "", ""
    text = text.strip()

    # 1) 嵌套 boxed 提取
    answer = _extract_boxed_nested(text)
    if answer:
        cleaned = _clean_extracted_answer(answer)
        if cleaned:
            return cleaned, "boxed"

    # 2) 强结论模式（可在全文截获中段结论）
    answer = _extract_strong_pattern(text)
    if answer:
        return answer, "strong_pattern"

    # 3) 尾部兜底
    answer = _extract_tail_fallback(text)
    if answer:
        return answer, "tail_fallback"

    return "", ""
