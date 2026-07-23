"""
Word (.docx) → JSON 转换工具
将数学题集 Word 文档转换为评测器可用的 JSON 格式。

用法:
    python 转化工具/docx_to_json.py <docx路径> [-o 输出.json] [--max N]

输出 JSON 格式:
[
  {
    "id": "ch01_001",
    "question": "题目完整内容（含选项）",
    "domain": "函数极限与连续",
    "reference_answer": ""
  }
]

支持格式:
  - 标题样式 → 章节/领域
  - 数字序号开头 → 新题目
  - 选择题 A/B/C/D 选项 → 合并到题目
  - 参考答案区域 → 自动跳过
"""
import argparse
import json
import os
import re
import sys

try:
    from docx import Document
except ImportError:
    print("请先安装 python-docx: pip install python-docx")
    sys.exit(1)


def is_chapter_paragraph(para):
    """判断是否是章节标题"""
    text = para.text.strip()
    if not text:
        return False
    # 标题样式
    if para.style and para.style.name and para.style.name.startswith('Heading'):
        return True
    # 匹配 "第X章"
    if re.match(r'^第[零一二三四五六七八九十\d]+章\s', text):
        return True
    # 粗体 + 短文本 + 章/节关键词
    if len(text) < 30:
        for run in para.runs:
            if run.bold and any(kw in text for kw in ['章', '节', '部分', '单元']):
                return True
    return False


def is_section_header(text):
    """判断是否是部分标题（基础部分/强化部分）"""
    return bool(re.match(r'^(基础部分|强化部分|提高部分|基础篇|强化篇|提高篇)', text.strip()))


def is_answer_section(text):
    """判断是否是答案/解析区域"""
    return bool(re.match(r'^(参考答案|答案解析|答案[：:]|解析[：:]|参考答案与解析|习题答案)', text.strip()))


def is_problem_start(text):
    """判断是否是新题目的开始"""
    # 匹配 "1." "1、" "1 " 等开头
    return bool(re.match(r'^\d+[\.\、\s]', text.strip()))


def is_choice_line(text):
    """判断是否是选择题选项行"""
    return bool(re.match(r'^[A-D][\.\、\s\)）]', text.strip()))


def is_page_number(text):
    """判断是否是页码"""
    return bool(re.match(r'^\d{1,3}$', text.strip()))


def clean_text(text):
    """清理文本"""
    # 移除多余空白
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_paragraphs(doc):
    """提取所有有效段落文本"""
    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        paragraphs.append({
            "text": text,
            "style": para.style.name if para.style else "",
            "is_heading": is_chapter_paragraph(para),
        })
    return paragraphs


def parse_problems(paragraphs):
    """解析题目"""
    problems = []
    current_chapter = "未知章节"
    current_problem = None
    in_answer = False
    chapter_counter = {}

    for item in paragraphs:
        text = clean_text(item["text"])

        # 跳过页码
        if is_page_number(text):
            continue

        # 检测答案区域（一旦进入就跳过后续所有内容）
        if is_answer_section(text):
            in_answer = True
            continue
        if in_answer:
            continue

        # 检测章节标题（已由 extract_paragraphs 标记）
        if item["is_heading"]:
            if re.match(r'^第[零一二三四五六七八九十\d]+章', text):
                current_chapter = text
                continue
            if any(kw in text for kw in ['函数', '极限', '导数', '积分', '微分', '级数', '方程', '概率', '统计', '代数', '几何', '数论']):
                current_chapter = text
                continue

        # 跳过 section 标题
        if is_section_header(text):
            continue

        # 检测新题目
        if is_problem_start(text):
            # 保存上一题
            if current_problem and current_problem["question"].strip():
                problems.append(current_problem)

            match = re.match(r'^(\d+)', text)
            num = int(match.group(1)) if match else 0
            question_text = re.sub(r'^\d+[\.\、\s]+', '', text).strip()

            # 章节简称
            ch_short = re.sub(r'第?[\s章]', '', current_chapter)
            ch_short = re.sub(r'^\d+\s*', '', ch_short)
            if not ch_short or ch_short == "未知章节":
                ch_short = "unknown"

            if ch_short not in chapter_counter:
                chapter_counter[ch_short] = 0
            chapter_counter[ch_short] += 1

            problem_id = f"{ch_short}_{num:03d}" if num > 0 else f"{ch_short}_{chapter_counter[ch_short]:03d}"

            current_problem = {
                "id": problem_id,
                "question": question_text,
                "domain": ch_short,
                "reference_answer": ""
            }
        elif current_problem:
            # 续行：拼接选项或续文
            current_problem["question"] += " " + text

    # 保存最后一题
    if current_problem and current_problem["question"].strip():
        problems.append(current_problem)

    # 后处理
    for p in problems:
        p["question"] = re.sub(r'\s+', ' ', p["question"]).strip()
        p["question"] = p["question"].rstrip(' .,;，。；')
        p["domain"] = re.sub(r'^\d+\s*', '', p["domain"]).strip()

    return problems


def convert_docx(docx_path, max_problems=0):
    """主转换函数"""
    print(f"正在读取 Word 文档: {docx_path}")
    doc = Document(docx_path)
    paragraphs = extract_paragraphs(doc)
    print(f"共 {len(paragraphs)} 个段落")

    problems = parse_problems(paragraphs)
    print(f"解析出 {len(problems)} 道题目")

    if max_problems > 0:
        problems = problems[:max_problems]
        print(f"限制为前 {max_problems} 道")

    return problems


def main():
    parser = argparse.ArgumentParser(description="Word (.docx) → JSON 题目转换器")
    parser.add_argument("docx", help="Word 文档路径 (.docx)")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--max", type=int, default=0, help="最多提取题目数 (0=全部)")
    args = parser.parse_args()

    docx_path = args.docx
    if not os.path.exists(docx_path):
        print(f"文件不存在: {docx_path}")
        sys.exit(1)

    problems = convert_docx(docx_path, max_problems=args.max)

    # 默认输出路径：测试结果/原本问题/
    if args.output is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, "测试结果", "原本问题")
        os.makedirs(output_dir, exist_ok=True)
        docx_name = os.path.splitext(os.path.basename(docx_path))[0]
        args.output = os.path.join(output_dir, f"{docx_name}.json")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)

    print(f"\n已保存到: {args.output}")
    print(f"共 {len(problems)} 道题目")

    from collections import Counter
    domain_counts = Counter(p["domain"] for p in problems)
    if domain_counts:
        print("\n章节分布:")
        for domain, count in domain_counts.most_common():
            print(f"  {domain}: {count} 题")


if __name__ == "__main__":
    main()
