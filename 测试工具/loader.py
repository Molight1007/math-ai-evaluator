"""
Problem loader - supports JSON and CSV formats.
"""
import csv
import json
import logging
import os
from typing import Optional

from models import Problem

logger = logging.getLogger(__name__)

_FIELD_ALIASES = {
    "id": ["id", "ID", "problem_id"],
    "question": ["question", "Question", "problem", "content"],
    "domain": ["domain", "Domain", "category", "type"],
    "reference_answer": ["reference_answer", "ReferenceAnswer", "answer", "Answer", "solution"],
}


def _map_field(row: dict, target: str) -> Optional[str]:
    for alias in _FIELD_ALIASES.get(target, []):
        if alias in row and row[alias] is not None and str(row[alias]).strip():
            return str(row[alias]).strip()
    return None


def load_problems_from_json(filepath: str) -> list[Problem]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
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
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".json":
        return load_problems_from_json(filepath)
    elif ext == ".csv":
        return load_problems_from_csv(filepath)
    raise ValueError(f"Unsupported format: {ext}")
