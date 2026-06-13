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


def load_problems(filepath: str) -> list[Problem]:
    """统一加载入口：根据文件扩展名自动选择 JSON 或 CSV 加载器"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".json":
        return load_problems_from_json(filepath)
    elif ext == ".csv":
        return load_problems_from_csv(filepath)
    raise ValueError(f"Unsupported format: {ext}")
