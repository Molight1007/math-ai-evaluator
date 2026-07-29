"""
题目转化工具 — 统一入口
支持 PDF 和 Word (.docx) → JSON 格式转换。

用法:
    python 转化工具/convert.py <文件路径> [-o 输出.json] [--max N] [--start-page N]

自动识别文件类型:
  - .pdf  → 使用 pdf_to_json 模块
  - .docx → 使用 docx_to_json 模块

示例:
    # 转换 PDF
    python 转化工具/convert.py "题目.pdf" --max 50

    # 转换 Word
    python 转化工具/convert.py "题目.docx" --max 100

    # 指定输出路径
    python 转化工具/convert.py "题目.pdf" -o "my_problems.json"
"""
import argparse
import json
import os
import sys
from collections import Counter


def main():
    parser = argparse.ArgumentParser(
        description="题目转化工具 — PDF/Word → JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持格式:
  .pdf  数学题集 PDF（如张宇1000题）
  .docx 数学题集 Word 文档

输出 JSON 格式:
  [{"id": "xxx", "question": "题目内容", "domain": "领域", "reference_answer": ""}]

输出默认保存在: 测试结果/原本问题/
        """
    )
    parser.add_argument("file", help="输入文件路径（.pdf 或 .docx）")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--max", type=int, default=0, help="最多提取题目数（0=全部）")
    parser.add_argument("--start-page", type=int, default=0, help="起始页码/段落（PDF 用，0-based）")
    args = parser.parse_args()

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"[错误] 文件不存在: {file_path}")
        sys.exit(1)

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        from pdf_to_json import convert_pdf
        problems = convert_pdf(file_path, max_problems=args.max, start_page=args.start_page)
    elif ext == ".docx":
        from docx_to_json import convert_docx
        problems = convert_docx(file_path, max_problems=args.max)
    else:
        print(f"[错误] 不支持的文件格式: {ext}")
        print("  支持: .pdf  .docx")
        sys.exit(1)

    if not problems:
        print("[警告] 未解析出任何题目，请检查文件内容格式。")
        sys.exit(1)

    # 默认输出路径：测试结果/原本问题/
    if args.output is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, "测试结果", "原本问题")
        os.makedirs(output_dir, exist_ok=True)
        file_name = os.path.splitext(os.path.basename(file_path))[0]
        args.output = os.path.join(output_dir, f"{file_name}.json")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)

    print(f"\n[完成] 已保存到: {args.output}")
    print(f"  共 {len(problems)} 道题目")

    domain_counts = Counter(p["domain"] for p in problems)
    if domain_counts:
        print("\n章节分布:")
        for domain, count in domain_counts.most_common():
            print(f"  {domain}: {count} 题")


if __name__ == "__main__":
    main()
