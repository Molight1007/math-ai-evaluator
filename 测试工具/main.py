"""
数学智能体评测器 - 主入口
支持直接输入 PDF / Word (.docx) / JSON / CSV，自动识别并转化。
用法: python 测试工具/main.py -i <file> [--concurrency N] [--max N]
"""
import argparse
import asyncio
import logging
import os
import sys
import datetime
import io
import tempfile
from typing import Optional

# 将当前目录添加到 import 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, validate_config, ConfigError, save_config, has_config
from loader import load_problems
from intern_s1 import run_inference
from deepseek import run_judge
from aggregator import merge_result
from reporter import generate_json_report, generate_html_report, print_summary
from models import JudgeResult

logger = logging.getLogger(__name__)

# 评测结果输出子目录
BASE_RESULT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "测试结果")
DIR_DISPLAY = os.path.join(BASE_RESULT, "测试结果展示")      # HTML 报告
DIR_OUTPUT = os.path.join(BASE_RESULT, "原始输出和推理过程")  # JSON 原始数据
DIR_PROBLEMS = os.path.join(BASE_RESULT, "原始问题")         # 题目文件副本


def clear_all_results() -> dict:
    """清除所有评测结果（HTML/JSON/临时文件），返回各目录删除的文件数"""
    import glob
    counts = {}
    for name, path in [
        ("测试结果展示", DIR_DISPLAY),
        ("原始输出和推理过程", DIR_OUTPUT),
        ("原始问题", DIR_PROBLEMS),
    ]:
        n = 0
        if os.path.isdir(path):
            for f in glob.glob(os.path.join(path, "*")):
                try:
                    os.remove(f)
                    n += 1
                except OSError:
                    pass
        counts[name] = n
    return counts


def _safe_str(s, maxlen=50):
    """截断字符串并确保 UTF-8 安全，用于终端打印"""
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
        return file_path  # JSON/CSV 无需转化

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

    # 保存为临时 JSON 并复制到"原始问题"目录
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    import json
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    json_path = os.path.join(DIR_PROBLEMS, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)
    print(f"[转化] 完成，{len(problems)} 道题目 -> {json_path}")
    return json_path


async def evaluate_single(problem, semaphore):
    """评测单道题目：先推理，再评判，最后合并结果"""
    async with semaphore:
        inference = await run_inference(problem)
        if inference.error:
            # 推理失败时，构造一个"失败"的评判结果
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
    """执行完整评测流水线：加载题目 -> 并发推理+评判 -> 生成报告"""
    problems = load_problems(problems_path)
    if not problems:
        logger.error("No problems loaded!")
        return
    logger.info(f"Loaded {len(problems)} problems. Starting evaluation...")

    # 并发数不应超过实际题目数量
    actual_concurrency = min(concurrency, len(problems))
    semaphore = asyncio.Semaphore(actual_concurrency)
    tasks = [evaluate_single(p, semaphore) for p in problems]

    print(f"\nEvaluating {len(problems)} problems (concurrency={actual_concurrency})...\n")
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        status = "PASS" if result.is_correct else "FAIL"
        print(f"  [{i}/{len(problems)}] {status} {result.problem_id}: {_safe_str(result.intern_answer)}")
    results.sort(key=lambda r: r.problem_id)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) 保存 JSON 报告到"原始输出和推理过程"
    os.makedirs(DIR_OUTPUT, exist_ok=True)
    json_path = os.path.join(DIR_OUTPUT, f"report_{ts}.json")
    generate_json_report(results, json_path)

    # 2) 保存 HTML 报告到"测试结果展示"
    os.makedirs(DIR_DISPLAY, exist_ok=True)
    html_path = os.path.join(DIR_DISPLAY, f"report_{ts}.html")
    generate_html_report(results, html_path)

    # 3) 复制题目文件到"原始问题"
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


async def run_evaluation_from_bank(bank_name: str, count: int, concurrency: int = 10,
                                      domain: Optional[str] = None, progress_callback=None) -> Optional[str]:
    """
    从题库随机选题并评测。

    参数:
        bank_name: 题库名称
        count: 随机选题数量
        concurrency: 并发数
        domain: 可选领域筛选
        progress_callback: 进度回调 (current, total)

    返回:
        HTML 报告路径，失败返回 None
    """
    from question_bank import get_db

    db = get_db()

    if not db.bank_exists(bank_name):
        raise ValueError(f"题库不存在: {bank_name}")

    problems = db.get_random_problems(bank_name, count, domain=domain)
    if not problems:
        raise ValueError(f"题库 {bank_name} 中没有符合条件的题目")

    # 将题目写入临时 JSON 文件
    import json
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    temp_path = os.path.join(DIR_PROBLEMS, f"_bank_temp_{bank_name}.json")
    problems_data = [
        {
            "id": p.id,
            "question": p.question,
            "domain": p.domain or "",
            "reference_answer": p.reference_answer or "",
        }
        for p in problems
    ]
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(problems_data, f, ensure_ascii=False, indent=2)

    logger.info(f"从题库 {bank_name} 随机选取 {len(problems)} 道题目，开始评测...")

    # 复用现有评测流水线
    html_path = await run_evaluation(temp_path, concurrency, progress_callback=progress_callback)

    # 清理临时文件
    try:
        os.remove(temp_path)
    except OSError:
        pass

    return html_path


def main():
    """命令行入口：解析参数 -> 转化文件 -> 评测 -> 自动打开报告"""
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

    # 加载并验证配置（缺少 API Key 时快速失败）
    try:
        validate_config(load_config())
    except ConfigError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    # 步骤1: 自动转化文件
    try:
        json_path = auto_convert(args.input, max_problems=args.max)
    except Exception as e:
        print(f"\n[错误] 转化失败: {e}")
        sys.exit(1)

    # 步骤2: 执行评测
    html_path = asyncio.run(run_evaluation(json_path, args.concurrency))

    # 步骤3: 自动打开报告
    if html_path:
        try:
            os.startfile(html_path)
            print(f"\n[报告] 已在浏览器中打开。")
        except Exception:
            pass


if __name__ == "__main__":
    main()