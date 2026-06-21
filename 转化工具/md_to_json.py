"""
Markdown (.md) → JSON 题目转换工具。

将 Markdown 格式的数学题集转换为评测器可用的 JSON 格式。
识别规则：
- ## 标题 → 章节/领域
- 数字序号开头（如 "1. "、"1、"）→ 新题目
- 选择题 A/B/C/D 选项 → 合并到题目
- 参考答案区域（以 "答案" 开头）→ 跳过

用法:
    python 转化工具/md_to_json.py <md路径> [-o 输出.json] [--max N]

输出 JSON 格式:
[
  {
    "id": "ch01_001",
    "question": "题目完整内容（含选项）",
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


def _is_heading(line: str) -> bool:
    """判断是否为 Markdown 标题行（# 开头，用作章节/领域标识）"""
    return bool(re.match(r'^#{1,3}\s+', line.strip()))


def _is_problem_start(line: str) -> bool:
    """判断是否为题目起始行（数字序号开头）"""
    return bool(re.match(r'^\d+[\.\、\s]', line.strip()))


def _is_answer_section(line: str) -> bool:
    """判断是否为答案区域起始行"""
    return bool(re.match(
        r'^(?:#{1,3}\s+)?(?:参考答案|答案解析|答案[：:]|解析[：:]|习题答案)',
        line.strip(),
    ))


def _clean_md_line(line: str) -> str:
    """
    清理 Markdown 行：去除 Markdown 标记符号，保留纯文本内容。

    参数:
        line: 原始 Markdown 行

    返回:
        清理后的纯文本行
    """
    # 去除标题标记（## → 空）
    line = re.sub(r'^#{1,6}\s+', '', line)
    # 去除加粗/斜体标记
    line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
    line = re.sub(r'\*([^*]+)\*', r'\1', line)
    # 去除行内代码标记
    line = re.sub(r'`([^`]+)`', r'\1', line)
    return line.strip()


def convert_md(md_path: str, max_problems: int = 0) -> list[dict]:
    """
    将 Markdown 文件转换为题目列表。

    按标题分段识别章节，按数字序号分割题目，
    选项行自动拼接到上一题题干中。

    参数:
        md_path: Markdown 文件路径
        max_problems: 最大提取题目数（0 表示全部）

    返回:
        题目字典列表，每项含 id/question/domain/reference_answer
    """
    if not os.path.exists(md_path):
        raise FileNotFoundError(f"文件不存在: {md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    problems = []
    current_chapter = "未知章节"
    current_problem = None
    in_answer_section = False
    chapter_counter: dict[str, int] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 检测答案区域（一旦进入就跳过后续所有内容）
        if _is_answer_section(line):
            in_answer_section = True
            continue
        if in_answer_section:
            continue

        # 检测章节标题
        if _is_heading(line):
            heading_text = _clean_md_line(line)
            # 如果标题包含数学领域关键词，视为章节
            math_keywords = {"函数", "极限", "导数", "积分", "微分",
                             "级数", "方程", "概率", "统计", "代数",
                             "几何", "数论", "向量", "矩阵", "行列式"}
            if any(kw in heading_text for kw in math_keywords):
                current_chapter = heading_text
            continue

        # 检测新题目起始
        if _is_problem_start(line):
            # 保存上一题
            if current_problem and current_problem["question"].strip():
                problems.append(current_problem)

            match = re.match(r'^(\d+)', line)
            num = int(match.group(1)) if match else 0
            question_text = re.sub(r'^\d+[\.\、\s]+', '', line).strip()

            # 生成章节简称（用于题目 ID 前缀）
            ch_short = re.sub(r'[第章节\s]', '', current_chapter)
            ch_short = re.sub(r'^\d+\s*', '', ch_short)
            if not ch_short or ch_short == "未知章节":
                ch_short = "md"

            if ch_short not in chapter_counter:
                chapter_counter[ch_short] = 0
            chapter_counter[ch_short] += 1

            problem_id = (
                f"{ch_short}_{num:03d}" if num > 0
                else f"{ch_short}_{chapter_counter[ch_short]:03d}"
            )

            current_problem = {
                "id": problem_id,
                "question": question_text,
                "domain": ch_short,
                "reference_answer": "",
            }
        elif current_problem is not None:
            # 续行：选项或题干续文拼接到当前题目
            cleaned = _clean_md_line(line)
            if cleaned:
                current_problem["question"] += " " + cleaned

    # 保存最后一题
    if current_problem and current_problem["question"].strip():
        problems.append(current_problem)

    # 后处理：清理空白和多余空格
    for p in problems:
        p["question"] = re.sub(r'\s+', ' ', p["question"]).strip()
        p["question"] = p["question"].rstrip(" .,;，。；")
        p["domain"] = re.sub(r'^\d+\s*', '', p["domain"]).strip()

    print(f"从 Markdown 解析出 {len(problems)} 道题目")

    if max_problems > 0:
        problems = problems[:max_problems]
        print(f"限制为前 {max_problems} 道")

    return problems


def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Markdown (.md) → JSON 题目转换器")
    parser.add_argument("md", help="Markdown 文件路径 (.md)")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--max", type=int, default=0, help="最多提取题目数 (0=全部)")
    args = parser.parse_args()

    md_path = args.md
    if not os.path.exists(md_path):
        print(f"文件不存在: {md_path}")
        sys.exit(1)

    problems = convert_md(md_path, max_problems=args.max)

    # 默认输出路径
    if args.output is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, "测试结果", "原本问题")
        os.makedirs(output_dir, exist_ok=True)
        md_name = os.path.splitext(os.path.basename(md_path))[0]
        args.output = os.path.join(output_dir, f"{md_name}.json")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)

    print(f"\n已保存到: {args.output}")
    print(f"共 {len(problems)} 道题目")


if __name__ == "__main__":
    main()
