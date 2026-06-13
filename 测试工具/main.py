"""
Main entry point for the Math Agent Evaluator.
支持直接输入 PDF / Word (.docx) / JSON / CSV，自动识别并转化。
Usage: python 测试工具/main.py -i <file> [--concurrency N] [--max N]
"""
import argparse
import asyncio
import logging
import os
import sys
import datetime
import io
import tempfile

# Add current dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, validate_config, ConfigError, save_config, has_config
from loader import load_problems
from intern_s1 import run_inference
from deepseek import run_judge
from aggregator import merge_result
from reporter import generate_json_report, generate_html_report, print_summary
from models import JudgeResult

logger = logging.getLogger(__name__)

# Output sub-directories under 测试结果
BASE_RESULT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "测试结果")
DIR_DISPLAY = os.path.join(BASE_RESULT, "测试结果展示")      # HTML
DIR_OUTPUT = os.path.join(BASE_RESULT, "原始输出和推理过程")  # JSON
DIR_PROBLEMS = os.path.join(BASE_RESULT, "原始问题")         # copy of problems file


def _safe_str(s, maxlen=50):
    s = str(s)[:maxlen]
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return repr(s)


def auto_convert(file_path: str, max_problems: int = 0) -> str:
    """智能转化：PDF/Word -> JSON，JSON/CSV 直接返回原路径"""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".json", ".csv"):
        return file_path  # 无需转化

    if ext == ".pdf":
        print(f"\n[转化] 检测到 PDF 文件，正在转化...")
        from 转化工具.pdf_to_json import convert_pdf
        problems = convert_pdf(file_path, max_problems=max_problems)
    elif ext == ".docx":
        print(f"\n[转化] 检测到 Word 文件，正在转化...")
        from 转化工具.docx_to_json import convert_docx
        problems = convert_docx(file_path, max_problems=max_problems)
    else:
        raise ValueError(f"不支持的文件格式: {ext}（支持 .pdf / .docx / .json / .csv）")

    if not problems:
        raise ValueError("未解析出任何题目，请检查文件内容。")

    # 保存为临时 JSON 并复制到原始问题
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    import json
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    json_path = os.path.join(DIR_PROBLEMS, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)
    print(f"[转化] 完成，{len(problems)} 道题目 -> {json_path}")
    return json_path


async def evaluate_single(problem, semaphore):
    async with semaphore:
        inference = await run_inference(problem)
        if inference.error:
            judge = JudgeResult(
                problem_id=problem.id,
                is_correct=False,
                confidence=0.0,
                explanation=f"Inference error: {inference.error}",
                error=inference.error,
            )
        else:
            judge = await run_judge(inference)
        return merge_result(problem, inference, judge)


async def run_evaluation(problems_path, concurrency=3, progress_callback=None):
    problems = load_problems(problems_path)
    if not problems:
        logger.error("No problems loaded!")
        return
    logger.info(f"Loaded {len(problems)} problems. Starting evaluation...")
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [evaluate_single(p, semaphore) for p in problems]
    print(f"\nEvaluating {len(problems)} problems (concurrency={concurrency})...\n")
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        status = "PASS" if result.is_correct else "FAIL"
        print(f"  [{i}/{len(problems)}] {status} {result.problem_id}: {_safe_str(result.intern_answer)}")
    results.sort(key=lambda r: r.problem_id)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) JSON -> 原始输出和推理过程
    os.makedirs(DIR_OUTPUT, exist_ok=True)
    json_path = os.path.join(DIR_OUTPUT, f"report_{ts}.json")
    generate_json_report(results, json_path)

    # 2) HTML -> 测试结果展示
    os.makedirs(DIR_DISPLAY, exist_ok=True)
    html_path = os.path.join(DIR_DISPLAY, f"report_{ts}.html")
    generate_html_report(results, html_path)

    # 3) 原始问题 -> copy problems file
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    problems_copy = os.path.join(DIR_PROBLEMS, os.path.basename(problems_path))
    if os.path.abspath(problems_path) != os.path.abspath(problems_copy):
        with open(problems_path, "r", encoding="utf-8") as fsrc:
            content = fsrc.read()
        with open(problems_copy, "w", encoding="utf-8") as fdst:
            fdst.write(content)

    print_summary(results)
    print(f"\nReports saved:")
    print(f"  测试结果展示:  {os.path.basename(html_path)}")
    print(f"  原始输出和推理过程: {os.path.basename(json_path)}")
    print(f"  原始问题:  {os.path.basename(problems_copy)}")

    return html_path  # 返回 HTML 路径供 GUI 打开


def main():
    parser = argparse.ArgumentParser(
        description="Math Agent Evaluator - 支持 PDF/Word/JSON/CSV 自动转化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python 测试工具/main.py -i 题目.pdf
  python 测试工具/main.py -i 题目.docx --max 10
  python 测试工具/main.py -i 题目.json -c 5
        """
    )
    parser.add_argument("-i", "--input", required=True, help="输入文件路径（.pdf / .docx / .json / .csv）")
    parser.add_argument("-c", "--concurrency", type=int, default=3, help="最大并发数（默认 3）")
    parser.add_argument("--max", type=int, default=0, help="最多评测题目数（0=全部，仅 PDF/Word 有效）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load and validate config (fails fast if API keys missing)
    try:
        validate_config(load_config())
    except ConfigError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    # Step 1: 自动转化
    try:
        json_path = auto_convert(args.input, max_problems=args.max)
    except Exception as e:
        print(f"\n[错误] 转化失败: {e}")
        sys.exit(1)

    # Step 2: 评测
    html_path = asyncio.run(run_evaluation(json_path, args.concurrency))

    # Step 3: 自动打开报告
    if html_path:
        try:
            os.startfile(html_path)
            print(f"\n[报告] 已在浏览器中打开。")
        except Exception:
            pass


if __name__ == "__main__":
    main()