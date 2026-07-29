"""
题目加载器 - 支持 JSON 和 CSV 格式的题目文件读取。
"""
import csv
import json
import logging
import os
from typing import Optional

from models import Problem

logger = logging.getLogger(__name__)

# 字段别名映射：支持多种命名的字段名，提高兼容性
_FIELD_ALIASES = {
    "id": ["id", "ID", "problem_id"],
    "question": ["question", "Question", "problem", "content"],
    "domain": ["domain", "Domain", "category", "type"],
    "reference_answer": ["reference_answer", "ReferenceAnswer", "answer", "Answer", "solution"],
}


def _map_field(row: dict, target: str) -> Optional[str]:
    """按别名映射从行数据中提取字段值，返回第一个非空匹配"""
    for alias in _FIELD_ALIASES.get(target, []):
        if alias in row and row[alias] is not None and str(row[alias]).strip():
            return str(row[alias]).strip()
    return None


def load_problems_from_json(filepath: str) -> list[Problem]:
    """从 JSON 文件加载题目列表，支持直接数组和 {'problems': [...]} 两种格式"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 兼容两种 JSON 结构：直接数组 或 包含 problems 键的对象
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "problems" in data:
        items = data["problems"]
    else:
        raise ValueError("Unsupported JSON format")
    problems = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = _map_field(item, "id")
        q = _map_field(item, "question")
        if not pid or not q:
            continue
        problems.append(Problem(
            id=pid, question=q,
            domain=_map_field(item, "domain"),
            reference_answer=_map_field(item, "reference_answer"),
        ))
    logger.info(f"Loaded {len(problems)} problems from JSON")
    return problems


def load_problems_from_csv(filepath: str) -> list[Problem]:
    """从 CSV 文件加载题目列表，使用 utf-8-sig 编码以兼容 BOM 头"""
    problems = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = _map_field(row, "id")
            q = _map_field(row, "question")
            if not pid or not q:
                continue
            problems.append(Problem(
                id=pid, question=q,
                domain=_map_field(row, "domain"),
                reference_answer=_map_field(row, "reference_answer"),
            ))
    logger.info(f"Loaded {len(problems)} problems from CSV")
    return problems


def load_problems_from_pdf(filepath: str) -> list[Problem]:
    """从 PDF 文件加载题目，先尝试标准解析，失败则用通用试卷解析"""
    try:
        from pdf_to_json import convert_pdf
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber not available, cannot parse PDF")

    # 策略一：标准解析（张宇1000题等格式）
    raw_problems = convert_pdf(filepath)
    if raw_problems:
        problems = []
        for item in raw_problems:
            pid = item.get("id", "")
            q = item.get("question", "")
            if not pid or not q:
                continue
            problems.append(Problem(
                id=pid, question=q,
                domain=item.get("domain"),
                reference_answer=item.get("reference_answer", ""),
            ))
        if problems:
            logger.info(f"Loaded {len(problems)} problems from PDF (standard parser)")
            return problems

    # 策略二：通用试卷解析（竞赛试卷格式）
    logger.info("Standard parser returned 0 problems, trying generic exam parser...")
    return _parse_generic_exam_pdf(filepath)


def _parse_generic_exam_pdf(filepath: str) -> list[Problem]:
    """通用试卷 PDF 解析器，适配竞赛试卷格式"""
    import pdfplumber
    import re

    problems = []
    cn_nums_pattern = re.compile(r"^([一二三四五六七八九十]+)[、.]")

    with pdfplumber.open(filepath) as pdf:
        all_lines = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_lines.extend(text.splitlines())

    # 过滤页码和空行
    merged = []
    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^第\s*\d+\s*页$", line):
            continue
        if re.match(r"^\d+$", line):  # 纯数字（页码）
            continue
        merged.append(line)

    # 策略：按中文数字标题或(数字)拆分为题目
    sub_pattern = re.compile(r"^\((\d+)\)")
    major_pattern = re.compile(r"^[（(]本题\s*\d+\s*分[）)]")

    current_text = []
    problem_counter = 0

    def flush_problem():
        nonlocal problem_counter
        if current_text:
            full_text = " ".join(current_text)
            full_text = re.sub(r"\s+", " ", full_text).strip()
            if len(full_text) > 15:
                problem_counter += 1
                problems.append(Problem(
                    id=f"exam_{problem_counter:03d}",
                    question=full_text,
                    domain="竞赛试卷",
                    reference_answer="",
                ))
            current_text.clear()

    for line in merged:
        # 检测新大题开始（中文数字标题 或 "本题XX分"）
        is_new_major = bool(cn_nums_pattern.match(line)) or bool(major_pattern.match(line))

        if is_new_major:
            flush_problem()
            # 去掉编号前缀
            rest = cn_nums_pattern.sub("", line).strip()
            rest = major_pattern.sub("", rest).strip()
            # 去掉开头的句号/顿号
            rest = re.sub(r"^[.、。]", "", rest).strip()
            if rest:
                current_text = [rest]
            else:
                current_text = []
        elif current_text is not None:
            current_text.append(line)

    flush_problem()

    # 如果仍然没解析到题目，回退：所有文本作为一道题
    if not problems and merged:
        full = " ".join(merged)
        full = re.sub(r"\s+", " ", full).strip()
        if len(full) > 15:
            problems.append(Problem(
                id="exam_001",
                question=full,
                domain="竞赛试卷",
                reference_answer="",
            ))

    logger.info(f"Loaded {len(problems)} problems from PDF (generic exam parser)")
    return problems
def load_problems(filepath: str) -> list[Problem]:
    """统一加载入口：根据文件扩展名自动选择加载器"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".json":
        return load_problems_from_json(filepath)
    elif ext == ".csv":
        return load_problems_from_csv(filepath)
    elif ext == ".pdf":
        return load_problems_from_pdf(filepath)
    raise ValueError(f"Unsupported format: {ext}")