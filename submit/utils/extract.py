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
    patterns = [
        r"【最终答案】\s*\n?\s*(.+?)(?:\n\n|\n(?:[#*=]|$)|$)",
        r"最终答案[:：]\s*(.+?)(?:\n\n|\n(?:[#*=]|$)|$)",
        r"答案[:：]\s*(.+?)(?:\n\n|\n(?:[#*=]|$)|$)",
        r"[Ff]inal\s*[Aa]nswer[:：]\s*(.+?)(?:\n\n|\n(?:[#*=]|$)|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            answer = match.group(1).strip()
            if (answer and len(answer) > 2
                    and not _is_meta_line(answer)
                    and not _is_incomplete_answer(answer)):
                return clean_answer(answer)

    # 策略 2：\\boxed{...} 格式
    boxed_match = re.search(r"\\boxed\{([^}]+)\}", text)
    if boxed_match:
        ans = boxed_match.group(1).strip()
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
