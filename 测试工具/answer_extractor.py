"""
答案文档提取器 — 从 PPT/Word 格式的答案文件中提取「题目-答案」对。

支持格式:
- .pptx (PowerPoint): 按幻灯片逐页提取，每页可能包含题目+答案
- .docx (Word): 按段落提取，识别题号+答案模式
- .txt: 纯文本，按行解析

输出统一格式:
[
  {
    "index": 1,           # 序号
    "question_text": "...", # 题干（可能为空，如果答案文档只有答案）
    "answer_text": "...",   # 答案内容
    "source_page": 1        # 来源页码/幻灯片号
  }
]
"""
import os
import re
import logging

logger = logging.getLogger(__name__)


def extract_from_pptx(pptx_path: str) -> list[dict]:
    """
    从 PowerPoint 文件中提取答案对。
    策略：逐页提取所有文本，用正则匹配「题目+答案」模式。
    """
    try:
        from pptx import Presentation
    except ImportError:
        raise ImportError("请安装 python-pptx: pip install python-pptx")

    prs = Presentation(pptx_path)
    pairs = []

    for slide_idx, slide in enumerate(prs.slides, 1):
        # 提取当前页所有文本
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        texts.append(t)

        if not texts:
            continue

        full_text = "\n".join(texts)

        # 尝试从当前页中提取题目-答案对
        page_pairs = _parse_answer_pairs(full_text, slide_idx)
        pairs.extend(page_pairs)

    logger.info(f"从 PPT 提取了 {len(pairs)} 个答案对 (共 {len(prs.slides)} 页)")
    return pairs


def extract_from_docx(docx_path: str) -> list[dict]:
    """
    从 Word 文档中提取答案对。
    策略：按段落读取，识别题号模式 + 答案标记。
    """
    try:
        from docx import Document
    except ImportError:
        raise ImportError("请安装 python-docx: pip install python-docx")

    doc = Document(docx_path)
    pairs = []
    current_page = 1  # Word 没有明确的页码概念，用段落序号近似

    # 先收集所有段落
    all_paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            all_paragraphs.append(text)

    # 也读取表格中的内容
    for table in doc.tables:
        for row in table.rows:
            row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_texts:
                all_paragraphs.append(" | ".join(row_texts))

    full_text = "\n".join(all_paragraphs)
    pairs = _parse_answer_pairs(full_text, current_page)

    logger.info(f"从 Word 提取了 {len(pairs)} 个答案对 (共 {len(all_paragraphs)} 个段落)")
    return pairs


def extract_from_txt(txt_path: str) -> list[dict]:
    """从纯文本文件提取答案对"""
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()

    pairs = _parse_answer_pairs(content, 1)
    logger.info(f"从文本文件提取了 {len(pairs)} 个答案对")
    return pairs


def extract_answers(filepath: str) -> list[dict]:
    """
    统一入口：根据文件扩展名自动选择提取器。
    返回 list[dict]，每个 dict 包含 index, question_text, answer_text, source_page
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pptx":
        pairs = extract_from_pptx(filepath)
    elif ext == ".docx":
        pairs = extract_from_docx(filepath)
    elif ext == ".txt":
        pairs = extract_from_txt(filepath)
    else:
        raise ValueError(f"不支持的答案文件格式: {ext}（支持 .pptx / .docx / .txt）")

    # 重新编号，确保 index 连续
    for i, pair in enumerate(pairs):
        pair["index"] = i + 1

    return pairs


def _parse_answer_pairs(text: str, page: int) -> list[dict]:
    """
    从文本中解析「题目-答案」对。
    支持多种常见格式：

    格式1: 题号 + 题干 + 答案
        1. 求函数 f(x)=x² 的导数
        答案: 2x

    格式2: 题号 + 答案（无题干）
        1. B
        2. C

    格式3: 表格形式
        1 | 求导数 | 2x

    格式4: 答案列表
        一、1. A  2. B  3. C

    格式5: 题号. 题干 （多行）答案: xxx
    """
    pairs = []

    # ---- 策略1：按题号分段 ----
    # 匹配各种题号格式: "1.", "1、", "1)", "(1)", "第1题", "Q1.", "问题1"
    problem_pattern = re.compile(
        r'(?:^|\n)\s*'
        r'(?:第\s*)?(\d+)\s*[\.\、\)）题]?\s*'
        r'(?![\d\.\、\)）])',  # 后面不能紧跟数字（排除 1.2.3 这种情况）
        re.MULTILINE
    )

    # 找到所有题号的位置
    matches = list(problem_pattern.finditer(text))

    if len(matches) >= 1:
        for i, match in enumerate(matches):
            num = int(match.group(1))
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment = text[start:end].strip()

            # 在 segment 中分离题干和答案
            question_text, answer_text = _split_question_answer(segment)

            pairs.append({
                "index": num,
                "question_text": question_text,
                "answer_text": answer_text,
                "source_page": page,
            })

        return pairs

    # ---- 策略2：按「答案」关键词分割 ----
    answer_pattern = re.compile(
        r'(?:^|\n)\s*(?:答案|解答|解析|参考答案)[：:\s]*(.*?)(?=\n\s*(?:答案|解答|解析|参考答案|\d+[\.\、\)）])|\Z)',
        re.DOTALL | re.MULTILINE
    )
    answer_matches = list(answer_pattern.finditer(text))

    if answer_matches:
        idx = 1
        for m in answer_matches:
            answer_text = m.group(1).strip()[:500]  # 截断过长答案
            pairs.append({
                "index": idx,
                "question_text": "",
                "answer_text": answer_text,
                "source_page": page,
            })
            idx += 1
        return pairs

    # ---- 策略3：按行分割，每行一个答案 ----
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # 如果每行都很短（<100字符），可能每行是一个独立答案
    if lines and all(len(l) < 200 for l in lines):
        for idx, line in enumerate(lines, 1):
            # 尝试分离题号和内容
            q, a = _split_question_answer(line)
            pairs.append({
                "index": idx,
                "question_text": q,
                "answer_text": a or line,
                "source_page": page,
            })

    return pairs


def _split_question_answer(segment: str) -> tuple[str, str]:
    """
    从一段文本中分离题干和答案。
    返回 (question_text, answer_text)
    """
    segment = segment.strip()

    # 模式1: 明确的「答案: xxx」
    ans_patterns = [
        r'\n\s*(?:答案|解答|解析|参考答案)[：:\s]+(.*)',
        r'(?:答案|解答|解析|参考答案)[：:\s]+(.*)',
    ]

    for pat in ans_patterns:
        m = re.search(pat, segment, re.DOTALL)
        if m:
            answer = m.group(1).strip()
            question = segment[:m.start()].strip()
            # 限制答案长度
            answer = answer[:1000]
            return question, answer

    # 模式2: 最后一行是答案（以 "故选" "因此" "答案为" 开头）
    lines = segment.split("\n")
    if len(lines) >= 2:
        last_line = lines[-1].strip()
        if re.match(r'^(故选|因此|所以|答案为|故|综上)', last_line):
            answer = last_line
            question = "\n".join(lines[:-1]).strip()
            return question, answer

    # 模式3: 选择题答案（单独一个字母 A/B/C/D）
    if re.match(r'^[A-Da-d]$', segment):
        return "", segment.upper()

    # 模式4: 选择题答案行（如 "1-5: ABCDD"）
    multi_choice = re.match(r'^[\d\-\s,，]+[：:]\s*([A-Da-d\s]+)$', segment)
    if multi_choice:
        return "", multi_choice.group(1).strip()

    # 模式5: 短文本整体当作答案
    if len(segment) < 80:
        return "", segment

    # 默认：全部当题干，答案为空
    return segment, ""


# _clean_answer 已移除（当前未被使用），如需要可从 git 历史恢复
