"""
Excel (.xlsx) → JSON 题目转换工具。

将 Excel 格式的数学题集转换为评测器可用的 JSON 格式。
自动识别题目列（question/题目/问题）和领域列（domain/领域/章节），
支持选项列的自动合并。

用法:
    python 转化工具/xlsx_to_json.py <xlsx路径> [-o 输出.json] [--max N]

输出 JSON 格式:
[
  {
    "id": "xlsx_001",
    "question": "题目完整内容",
    "domain": "函数极限与连续",
    "reference_answer": ""
  }
]
"""
import argparse
import json
import os
import re
import sys


def convert_xlsx(xlsx_path: str, max_problems: int = 0) -> list[dict]:
    """
    将 Excel 文件转换为题目列表。

    自动识别列结构：
    - 题目列：列名含 question/题目/问题/题干/problem
    - 领域列：列名含 domain/领域/章节/分类/category
    - 答案列：列名含 answer/答案/解答/solution
    - 如未识别则默认第一列为题目，其余按优先级分配

    参数:
        xlsx_path: Excel 文件路径
        max_problems: 最大提取题目数（0 表示全部）

    返回:
        题目字典列表，每项含 id/question/domain/reference_answer
    """
    try:
        import openpyxl
    except ImportError:
        raise ImportError("请安装 openpyxl: pip install openpyxl")

    if not os.path.exists(xlsx_path):
        raise FileNotFoundError(f"文件不存在: {xlsx_path}")

    # 使用 pandas 读取（自动处理表头和数据类型）
    import pandas as pd

    df = pd.read_excel(xlsx_path, engine="openpyxl")
    if df.empty:
        print("Excel 文件为空，未提取到题目")
        return []

    columns = [str(c).strip() for c in df.columns]
    columns_lower = [c.lower() for c in columns]

    # 自动识别各列索引
    question_col = _find_column(columns_lower, ("question", "题目", "问题", "题干", "problem"))
    domain_col = _find_column(columns_lower, ("domain", "领域", "章节", "分类", "category", "type"))
    answer_col = _find_column(columns_lower, ("answer", "答案", "解答", "解析", "solution", "reference"))

    # 未识别的列默认处理
    if question_col is None:
        question_col = 0  # 默认第一列是题目
    if answer_col is None:
        answer_col = len(columns) - 1  # 默认最后一列是答案

    problems = []
    for idx, row in df.iterrows():
        question = str(row.iloc[question_col]) if pd.notna(row.iloc[question_col]) else ""
        domain = ""
        if domain_col is not None:
            domain = str(row.iloc[domain_col]) if pd.notna(row.iloc[domain_col]) else ""
        answer = ""
        if answer_col is not None and answer_col != question_col:
            answer = str(row.iloc[answer_col]) if pd.notna(row.iloc[answer_col]) else ""

        question = question.strip()
        if not question:
            continue

        # 如果题目列中也包含了选项（如 "A. xxx B. xxx"），保持原样
        # 检查其他列是否包含选项信息
        for col_idx, col_name in enumerate(columns):
            if col_idx in (question_col, domain_col, answer_col):
                continue
            cell_val = str(row.iloc[col_idx]) if pd.notna(row.iloc[col_idx]) else ""
            cell_val = cell_val.strip()
            if cell_val and re.match(r'^[A-D][\.\、\s]', cell_val):
                question += " " + cell_val

        problem_id = f"xlsx_{idx + 1:04d}"
        problems.append({
            "id": problem_id,
            "question": re.sub(r'\s+', ' ', question).strip(),
            "domain": domain.strip() if domain else "",
            "reference_answer": answer.strip() if answer else "",
        })

    print(f"从 Excel 解析出 {len(problems)} 道题目")

    if max_problems > 0:
        problems = problems[:max_problems]
        print(f"限制为前 {max_problems} 道")

    return problems


def _find_column(columns_lower: list[str], keywords: tuple[str, ...]) -> int | None:
    """
    在列名列表中查找包含指定关键词的列索引。

    参数:
        columns_lower: 小写化的列名列表
        keywords: 候选关键词元组

    返回:
        列索引（0-based），未找到返回 None
    """
    for i, col in enumerate(columns_lower):
        if any(kw.lower() in col for kw in keywords):
            return i
    return None


def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Excel (.xlsx) → JSON 题目转换器")
    parser.add_argument("xlsx", help="Excel 文件路径 (.xlsx)")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--max", type=int, default=0, help="最多提取题目数 (0=全部)")
    args = parser.parse_args()

    xlsx_path = args.xlsx
    if not os.path.exists(xlsx_path):
        print(f"文件不存在: {xlsx_path}")
        sys.exit(1)

    problems = convert_xlsx(xlsx_path, max_problems=args.max)

    # 默认输出路径
    if args.output is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, "测试结果", "原本问题")
        os.makedirs(output_dir, exist_ok=True)
        xlsx_name = os.path.splitext(os.path.basename(xlsx_path))[0]
        args.output = os.path.join(output_dir, f"{xlsx_name}.json")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)

    print(f"\n已保存到: {args.output}")
    print(f"共 {len(problems)} 道题目")


if __name__ == "__main__":
    main()
