"""
PDF → JSON 转换工具
将张宇1000题等数学题集 PDF 转换为评测器可用的 JSON 格式。

用法:
    python 转化工具/pdf_to_json.py <pdf路径> [-o 输出.json] [--max N] [--start-page N]

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

try:
    import pdfplumber
except ImportError:
    print("请先安装 pdfplumber: pip install pdfplumber")
    sys.exit(1)


# PDF 中常见的乱码字符映射（根据实际 PDF 上下文推断）
PDF_CHAR_MAP = {
    '\uf0ee': '(',   # a∈(0,1
    '\uf0f6': '[',   # 在[0,1
    '\uf0e4': '{',   # 数列{x_n}
    '\uf0f4': '|',   # 绝对值 |x|
    '\uf00a': 'θ',   # 极坐标 x=3x → 实际为 θ
    '\uf0b1': '∑',   # 求和
    '\uf0b6': '∫',   # 积分
    '\uf0cb': '/',   # 分数 1/2
    '\uf0e0': '{',   # 多级括号
    '\uf0e1': '{',
    '\uf0e2': '{',
    '\uf0e3': '{',   # 参数方程 {
    '\uf0e8': '',    # lim 符号（删除，后面正常字符会补上）
    '\uf0e9': '',
    '\uf0ea': '',
    '\uf001': ' ', '\uf020': ' ', '\u200b': '',
}


def fix_pdf_chars(text):
    """修复 PDF 提取文本中的特殊字符"""
    for bad, good in PDF_CHAR_MAP.items():
        text = text.replace(bad, good)
    return text


def clean_text(text):
    """清理 PDF 提取文本"""
    text = fix_pdf_chars(text)
    # 移除水印
    text = re.sub(r'公众号[：:].*?(?=\n|$)', '', text)
    text = re.sub(r'所有题本.*?(?=\n|$)', '', text)
    text = re.sub(r'· 第 \d+ 页，共 \d+ 页 ·', '', text)
    text = re.sub(r'【做题本集结地】', '', text)
    text = re.sub(r'【本本】', '', text)
    text = re.sub(r'张宇\s*1000\s*题[·.·]\s*[\u4e00-\u9fff\d]+', '', text)
    # 合并多余空白
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_chapter_header(line):
    return bool(re.match(r'^第[零一二三四五六七八九十\d]+章\s', line))


def is_section_header(line):
    return line.strip() in ['基础部分', '强化部分'] or bool(re.match(r'^(基础部分|强化部分)', line.strip()))


def is_answer_section(line):
    return bool(re.match(r'^(参考答案|答案解析|答案[：:]|解析[：:]|参考答案与解析)', line.strip()))


def is_problem_start(line):
    return bool(re.match(r'^\d+[\.\、\s]', line.strip()))


def is_continuation_line(line):
    """判断是否是上一题的续行（非新题、非章节标题）"""
    return not is_chapter_header(line) and not is_section_header(line) and not is_problem_start(line) and not is_answer_section(line)


def extract_text_from_pdf(pdf_path, start_page=0):
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < start_page:
                continue
            text = page.extract_text()
            if text:
                pages_text.append(text)
    return pages_text


def parse_problems(pages_text):
    problems = []
    current_chapter = "未知章节"
    current_problem = None
    in_answer = False
    chapter_counter = {}
    problem_num_in_chapter = {}  # 每章的题号计数
    
    for page_text in pages_text:
        lines = page_text.split('\n')
        
        for raw_line in lines:
            line = clean_text(raw_line)
            if not line:
                continue
            
            # 检测答案区域
            if is_answer_section(line):
                in_answer = True
                continue
            if in_answer:
                continue
            
            # 检测章节标题
            if is_chapter_header(line):
                current_chapter = line.strip()
                continue
            
            # 跳过 section 标题行
            if is_section_header(line):
                continue
            
            # 跳过纯页码行
            if re.match(r'^\d+$', line.strip()):
                continue
            
            # 检测新题目
            if is_problem_start(line):
                # 保存上一题
                if current_problem and current_problem["question"].strip():
                    problems.append(current_problem)
                
                match = re.match(r'^(\d+)', line)
                num = int(match.group(1)) if match else 0
                question_text = re.sub(r'^\d+[\.\、\s]+', '', line).strip()
                
                # 章节简称
                ch_short = re.sub(r'[第章节\s]', '', current_chapter)
                ch_short = re.sub(r'^\d+\s*', '', ch_short)  # 去掉开头的数字
                if not ch_short:
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
                # 续行
                current_problem["question"] += " " + line
    
    # 保存最后一题
    if current_problem and current_problem["question"].strip():
        problems.append(current_problem)
    
    # 后处理：清理 question
    for p in problems:
        p["question"] = re.sub(r'\s+', ' ', p["question"]).strip()
        # 去掉 question 末尾多余的符号
        p["question"] = p["question"].rstrip(' .,;，。；')
        # domain 清理
        p["domain"] = re.sub(r'^\d+\s*', '', p["domain"]).strip()
    
    return problems


def convert_pdf(pdf_path, max_problems=0, start_page=0):
    """可导出的 PDF 转换函数"""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"文件不存在: {pdf_path}")
    print(f"正在提取 PDF: {pdf_path}")
    pages_text = extract_text_from_pdf(pdf_path, start_page=start_page)
    print(f"共 {len(pages_text)} 页文本")
    problems = parse_problems(pages_text)
    print(f"解析出 {len(problems)} 道题目")
    if max_problems > 0:
        problems = problems[:max_problems]
        print(f"限制为前 {max_problems} 道")
    return problems


def main():
    parser = argparse.ArgumentParser(description="PDF → JSON 题目转换器")
    parser.add_argument("pdf", help="PDF 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--max", type=int, default=0, help="最多提取题目数 (0=全部)")
    parser.add_argument("--start-page", type=int, default=0, help="起始页码 (0-based)")
    args = parser.parse_args()
    
    problems = convert_pdf(args.pdf, max_problems=args.max, start_page=args.start_page)
    
    # 默认输出路径：测试结果/原本问题/
    if args.output is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, "测试结果", "原本问题")
        os.makedirs(output_dir, exist_ok=True)
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        args.output = os.path.join(output_dir, f"{pdf_name}.json")
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)
    
    print(f"\n已保存到: {args.output}")
    print(f"共 {len(problems)} 道题目")
    
    from collections import Counter
    domain_counts = Counter(p["domain"] for p in problems)
    print("\n章节分布:")
    for domain, count in domain_counts.most_common():
        print(f"  {domain}: {count} 题")


if __name__ == "__main__":
    main()
