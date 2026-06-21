"""
数学智能体评测器 - 主入口模块
================================
功能：
- 支持 PDF/Word/PPT/Markdown/Excel/JSON/CSV 文件自动识别并转化
- 执行并发评测流水线（Intern-S1 推理 → DeepSeek 评判 → Lean 验证）
- 支持从题库随机选题评测，自动使用答案库辅助评判
- 支持命令行答案导入和统计查询

用法:
    python 测试工具/main.py -i <file> [--concurrency N] [--max N]
    python 测试工具/main.py --import-answers 答案.pptx --bank 我的题库
"""

# ===== 标准库导入 =====
import argparse
import asyncio
import datetime
import glob
import json
import logging
import os
import shutil
import sys
from typing import Optional

# 将当前目录添加到 import 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 确保 Lean 4 (elan) 在 PATH 中
_ELAN_BIN = os.path.join(os.path.expanduser("~"), ".elan", "bin")
if os.path.isdir(_ELAN_BIN) and _ELAN_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ELAN_BIN + os.pathsep + os.environ.get("PATH", "")

# ===== 项目模块导入 =====
from config import load_config, validate_config, ConfigError
from loader import load_problems
from intern_s1 import run_inference
from deepseek import run_judge, run_judge_batch
from aggregator import merge_result
from reporter import generate_json_report, generate_html_report, print_summary
from models import JudgeResult, InferenceResult
from lean_verifier import (
    should_verify_lean,
    run_lean_verification_batch,
)

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 评测结果输出目录配置（所有输出统一存放在项目根目录的"测试结果"子目录下）
_RESULT_BASE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "测试结果"
)
DIR_DISPLAY = os.path.join(_RESULT_BASE, "测试结果展示")      # HTML 报告
DIR_OUTPUT = os.path.join(_RESULT_BASE, "原始输出和推理过程")  # JSON 原始数据
DIR_PROBLEMS = os.path.join(_RESULT_BASE, "原始问题")         # 题目文件副本

# 终端输出安全截断长度
_SAFE_STR_MAXLEN = 50

# Lean 验证并发数（避免 LLM API 限流）
_LEAN_VERIFY_CONCURRENCY = 3


def clear_all_results() -> dict:
    """
    清除所有评测结果文件（HTML/JSON/临时题目）。

    返回:
        {"测试结果展示": N, "原始输出和推理过程": N, "原始问题": N}
    """
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


def _safe_str(s, maxlen: int = _SAFE_STR_MAXLEN) -> str:
    """
    截断字符串并确保 UTF-8 编码安全，用于终端输出（避免乱码）。

    参数:
        s: 原始字符串
        maxlen: 最大显示长度

    返回:
        安全的截断字符串
    """
    s = str(s)[:maxlen]
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return repr(s)


def auto_convert(file_path: str, max_problems: int = 0) -> str:
    """
    智能文件格式转化：PDF/Word/PPT/Markdown/Excel → JSON，JSON/CSV 直接返回原路径。

    转化后的 JSON 保存到「原始问题」目录供后续使用。

    参数:
        file_path: 输入文件路径
        max_problems: 最大转化题目数（0 表示全部）

    返回:
        转化后的 JSON 文件路径

    异常:
        ValueError: 不支持的文件格式或未解析出题目
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".json", ".csv"):
        return file_path

    if ext == ".pdf":
        print("\n[转化] 检测到 PDF 文件，正在转化...")
        from 转化工具.pdf_to_json import convert_pdf
        problems = convert_pdf(file_path, max_problems=max_problems)
    elif ext == ".docx":
        print("\n[转化] 检测到 Word 文件，正在转化...")
        from 转化工具.docx_to_json import convert_docx
        problems = convert_docx(file_path, max_problems=max_problems)
    elif ext in (".pptx", ".ppt"):
        print("\n[转化] 检测到 PowerPoint 文件，正在转化...")
        from 转化工具.ppt_to_json import convert_ppt
        problems = convert_ppt(file_path, max_problems=max_problems)
    elif ext == ".md":
        print("\n[转化] 检测到 Markdown 文件，正在转化...")
        from 转化工具.md_to_json import convert_md
        problems = convert_md(file_path, max_problems=max_problems)
    elif ext == ".xlsx":
        print("\n[转化] 检测到 Excel 文件，正在转化...")
        from 转化工具.xlsx_to_json import convert_xlsx
        problems = convert_xlsx(file_path, max_problems=max_problems)
    else:
        raise ValueError(
            f"不支持的文件格式: {ext}"
            f"（支持 .pdf / .docx / .pptx / .ppt / .md / .xlsx / .json / .csv）"
        )

    if not problems:
        raise ValueError("未解析出任何题目，请检查文件内容。")

    # 保存为 JSON 到「原始问题」目录
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    json_path = os.path.join(DIR_PROBLEMS, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)
    print(f"[转化] 完成，{len(problems)} 道题目 -> {json_path}")
    return json_path


# ==================== 答案查找辅助函数 ====================

def _lookup_reference_answer(bank_name: str, problem_id: str) -> tuple:
    """
    从答案库查找某道题的参考答案。

    参数:
        bank_name: 题库名称
        problem_id: 题目 ID

    返回:
        (reference_answer, source) 元组，未找到时返回 (None, None)
    """
    if not bank_name:
        return None, None
    try:
        from question_bank import get_db
        db = get_db()
        mapping = db.get_answer_for_problem(bank_name, problem_id)
        if mapping:
            ref_answer = mapping["answer_text"]
            ref_source = mapping.get("source_file", "")
            logger.info(
                f"[{problem_id}] 使用参考答案 "
                f"(来源: {ref_source}, 置信度: {mapping['confidence']})"
            )
            return ref_answer, ref_source
    except Exception as e:
        logger.debug(f"[{problem_id}] 获取参考答案失败: {e}")
    return None, None


# ==================== 逐题评测模式 ====================

async def evaluate_single(problem, semaphore, bank_name=None):
    """
    评测单道题目的完整流程（逐题模式）：
    1. 调用 Intern-S1 进行数学推理
    2. 推理失败时构造失败结果，否则获取参考答案（若有）
    3. 调用 DeepSeek 进行正确性评判
    4. 合并推理和评判为最终 EvaluationResult

    参数:
        problem: Problem 对象
        semaphore: asyncio.Semaphore 控制并发
        bank_name: 题库名称（用于查找参考答案）

    返回:
        EvaluationResult 对象
    """
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
            ref_answer, ref_source = _lookup_reference_answer(
                bank_name, problem.id
            )
            judge = await run_judge(
                inference,
                reference_answer=ref_answer,
                answer_source=ref_source,
            )
        return merge_result(problem, inference, judge)


# ==================== 批量评测模式 ====================

async def _run_inference_stage(problems, concurrency, bank_name=None):
    """
    阶段一：并发执行 Intern-S1 推理，同时收集每道题的参考答案。

    参数:
        problems: 题目列表
        concurrency: 最大并发数
        bank_name: 题库名称（可选）

    返回:
        [(Problem, InferenceResult, ref_answer, ref_source), ...] 列表
    """
    semaphore = asyncio.Semaphore(min(concurrency, len(problems)))

    async def _inference_task(problem):
        async with semaphore:
            inference = await run_inference(problem)
            ref_answer, ref_source = _lookup_reference_answer(
                bank_name, problem.id
            ) if bank_name and not inference.error else (None, None)
            return problem, inference, ref_answer, ref_source

    tasks = [_inference_task(p) for p in problems]
    return await asyncio.gather(*tasks)


async def _run_judge_batch_stage(inference_results):
    """
    阶段二：将推理结果分批进行 DeepSeek 批量评判。

    分离成功推理和失败推理：失败的直接生成失败评判结果，
    成功的收集后统一批量评判。

    参数:
        inference_results: _run_inference_stage 的输出

    返回:
        EvaluationResult 列表
    """
    success_items = []
    failed_results = []

    for problem, inference, ref_answer, ref_source in inference_results:
        if inference.error:
            failed_results.append(merge_result(
                problem, inference,
                JudgeResult(
                    problem_id=problem.id,
                    is_correct=False,
                    confidence=0.0,
                    explanation=f"Inference error: {inference.error}",
                    error=inference.error,
                ),
            ))
        else:
            success_items.append(
                (problem, inference, ref_answer, ref_source)
            )

    if not success_items:
        return failed_results

    # 构建参考答案映射
    reference_map = {}
    for _, inf, ref_ans, ref_src in success_items:
        if ref_ans:
            reference_map[inf.problem_id] = (ref_ans, ref_src)

    # 批量评判
    inferences_to_judge = [inf for _, inf, _, _ in success_items]
    count = len(inferences_to_judge)
    print(f"\n  [Batch Judging] Sending {count} problems together...")
    judge_results = await run_judge_batch(
        inferences_to_judge,
        reference_map=reference_map if reference_map else None,
    )

    # 合并结果
    batch_eval_results = []
    for (problem, inference, _, _), judge in zip(
        success_items, judge_results
    ):
        batch_eval_results.append(merge_result(problem, inference, judge))

    return failed_results + batch_eval_results


async def evaluate_batch_mode(problems, concurrency=10, bank_name=None):
    """
    批量评测模式（两阶段流水线）：
    阶段一：并发执行 Intern-S1 推理
    阶段二：收集全部推理结果后，一次性调用 DeepSeek 批量评判

    相比逐题模式减少约 45% 的 API 调用次数。

    参数:
        problems: 题目列表
        concurrency: 推理并发数
        bank_name: 题库名称（可选）

    返回:
        EvaluationResult 列表
    """
    total = len(problems)
    print(
        f"\nEvaluating {total} problems "
        f"(batch mode, concurrency={concurrency})..."
    )
    print(
        f"  Stage 1/2: Running {total} inferences "
        f"with concurrency={concurrency}..."
    )

    inference_results = await _run_inference_stage(
        problems, concurrency, bank_name=bank_name
    )

    success_count = sum(
        1 for _, inf, _, _ in inference_results if not inf.error
    )
    print(
        f"  Stage 1/2 complete: {success_count}/{total} succeeded, "
        f"{total - success_count} failed"
    )

    print(f"  Stage 2/2: Batch judging {success_count} results...")
    return await _run_judge_batch_stage(inference_results)


# ==================== Lean 验证阶段 ====================

def _build_inference_for_verify(eval_result) -> InferenceResult:
    """
    从 EvaluationResult 构建用于 Lean 验证的 InferenceResult。

    参数:
        eval_result: 评测最终结果

    返回:
        提取了关键字段的 InferenceResult
    """
    return InferenceResult(
        problem_id=eval_result.problem_id,
        question=eval_result.question,
        answer=eval_result.intern_answer,
        reasoning=eval_result.intern_reasoning,
        steps=eval_result.intern_steps,
        verification=eval_result.intern_verification,
    )


def _print_lean_summary(candidates, verify_results) -> None:
    """
    打印 Lean 验证阶段的统计摘要。

    参数:
        candidates: 候选验证的题目数量
        verify_results: LeanVerificationResult 列表
    """
    verified_count = sum(1 for v in verify_results if v.verified)
    compile_pass = sum(1 for v in verify_results if v.compile_passed is True)
    compile_fail = sum(1 for v in verify_results if v.compile_passed is False)
    not_compiled = sum(1 for v in verify_results if v.compile_passed is None)
    logic_errors = sum(
        1 for v in verify_results if v.error_category == "logic_error"
    )

    print(f"  [Lean] Stage 3/3 complete:")
    print(f"    Verified: {verified_count}/{candidates}")
    if compile_pass + compile_fail + not_compiled > 0:
        print(
            f"    Compilation: {compile_pass} passed, {compile_fail} failed, "
            f"{not_compiled} not compiled"
        )
    print(f"    Logic errors found: {logic_errors}")


async def _run_lean_verification_stage(results: list) -> list:
    """
    阶段三（可选）：对评判为错误或低置信度的题目执行 Lean 形式化验证。

    筛选出需要验证的题目，并发执行 Lean 验证，将结果写入
    EvaluationResult.lean_verification 字段。

    参数:
        results: EvaluationResult 列表

    返回:
        更新后的 results 列表（原地修改）
    """
    # 筛选需要验证的题目
    candidates = []
    candidate_indices = []
    for i, r in enumerate(results):
        if should_verify_lean(r):
            candidates.append(r)
            candidate_indices.append(i)

    if not candidates:
        print(
            "\n  [Lean] No problems need verification "
            "(all correct with high confidence)"
        )
        return results

    print(
        f"\n  [Lean] Stage 3/3: Verifying {len(candidates)} "
        f"suspicious problems..."
    )

    # 构建 InferenceResult 列表
    inferences_to_verify = [
        _build_inference_for_verify(r) for r in candidates
    ]

    # 并发执行 Lean 验证
    verify_results = await run_lean_verification_batch(
        inferences_to_verify, concurrency=_LEAN_VERIFY_CONCURRENCY
    )

    # 将验证结果写回原始结果
    for idx, verify_result in zip(candidate_indices, verify_results):
        results[idx].lean_verification = verify_result.to_dict()

    _print_lean_summary(len(candidates), verify_results)
    return results


# ==================== 报告保存辅助函数 ====================

def _save_reports(results, problems_path, ts: str) -> str:
    """
    保存 JSON 和 HTML 报告，并复制题目文件到「原始问题」目录。

    参数:
        results: EvaluationResult 列表
        problems_path: 原始题目文件路径
        ts: 时间戳字符串

    返回:
        HTML 报告路径
    """
    os.makedirs(DIR_OUTPUT, exist_ok=True)
    json_path = os.path.join(DIR_OUTPUT, f"report_{ts}.json")
    generate_json_report(results, json_path)

    os.makedirs(DIR_DISPLAY, exist_ok=True)
    html_path = os.path.join(DIR_DISPLAY, f"report_{ts}.html")
    generate_html_report(results, html_path)

    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    problems_copy = os.path.join(
        DIR_PROBLEMS, os.path.basename(problems_path)
    )
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

    return html_path


# ==================== 主评测流水线 ====================

async def _print_problem_results(results: list) -> None:
    """
    按题目 ID 排序后打印逐题结果。

    参数:
        results: EvaluationResult 列表
    """
    sorted_results = sorted(results, key=lambda r: r.problem_id)
    for i, result in enumerate(sorted_results, 1):
        status = "PASS" if result.is_correct else "FAIL"
        print(
            f"  [{i}/{len(results)}] {status} "
            f"{result.problem_id}: {_safe_str(result.intern_answer)}"
        )


async def run_evaluation(
    problems_path,
    concurrency=3,
    progress_callback=None,
    bank_name=None,
    use_batch_judge=True,
    enable_lean=True,
):
    """
    执行完整评测流水线：
    1. 从 JSON/CSV 加载题目列表
    2. 检查答案库覆盖率
    3. 执行推理 + 评判（批量或逐题模式）
    4. Lean 形式化验证（可选）
    5. 生成 JSON + HTML 报告

    参数:
        problems_path: 题目文件路径
        concurrency: 最大并发数
        progress_callback: 进度回调 (current, total) — 暂未使用
        bank_name: 题库名称（可选，用于答案库辅助评判）
        use_batch_judge: 是否使用批量评判模式（默认 True）
        enable_lean: 是否启用 Lean 验证阶段（默认 True）

    返回:
        HTML 报告路径，加载失败返回 None
    """
    problems = load_problems(problems_path)
    if not problems:
        logger.error("No problems loaded!")
        return None
    logger.info(f"Loaded {len(problems)} problems. Starting evaluation...")

    # 检查答案库覆盖率
    _check_answer_coverage(bank_name)

    actual_concurrency = min(concurrency, len(problems))

    # 选择评测模式并执行
    if use_batch_judge and len(problems) > 1:
        results = await evaluate_batch_mode(
            problems, actual_concurrency, bank_name=bank_name
        )
        await _print_problem_results(results)
    else:
        results = await _run_single_mode(
            problems, actual_concurrency, bank_name
        )

    results.sort(key=lambda r: r.problem_id)

    # Lean 验证阶段
    if enable_lean:
        try:
            results = await _run_lean_verification_stage(results)
        except Exception as e:
            logger.warning(
                f"Lean verification stage failed (non-fatal): {e}"
            )
            print(
                f"\n  [Lean] Verification stage error "
                f"(continuing without Lean results): {e}"
            )

    # 保存报告
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_reports(results, problems_path, ts)


def _check_answer_coverage(bank_name: str) -> None:
    """
    检查并打印答案库覆盖率。

    参数:
        bank_name: 题库名称
    """
    if not bank_name:
        return
    try:
        from question_bank import get_db
        db = get_db()
        stats = db.get_answer_mapping_stats(bank_name)
        if stats["covered_problems"] > 0:
            logger.info(
                f"题库 {bank_name} 已有答案映射: "
                f"{stats['covered_problems']}/{stats['total_problems']} "
                f"道题有参考答案"
            )
            print(
                f"\n[答案库] {bank_name}: "
                f"{stats['covered_problems']}/{stats['total_problems']} "
                f"道题有参考答案 (覆盖率 {stats['coverage_rate']}%)"
            )
    except Exception as e:
        logger.debug(f"检查答案映射失败: {e}")


async def _run_single_mode(problems, concurrency, bank_name=None):
    """
    逐题评测模式：每道题独立推理 + 评判。

    参数:
        problems: 题目列表
        concurrency: 并发数
        bank_name: 题库名称

    返回:
        EvaluationResult 列表
    """
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        evaluate_single(p, semaphore, bank_name=bank_name) for p in problems
    ]
    print(
        f"\nEvaluating {len(problems)} problems "
        f"(concurrency={concurrency})...\n"
    )
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        status = "PASS" if result.is_correct else "FAIL"
        print(
            f"  [{i}/{len(problems)}] {status} "
            f"{result.problem_id}: {_safe_str(result.intern_answer)}"
        )
    return results


# ==================== 题库随机评测 ====================

async def run_evaluation_from_bank(
    bank_name: str,
    count: int,
    concurrency: int = 10,
    domain: Optional[str] = None,
    progress_callback=None,
) -> Optional[str]:
    """
    从题库随机选题并评测的完整流程。

    流程：验证题库 → 随机选题 → 写入临时 JSON → 评测 → 重命名临时文件

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

    # 写入临时 JSON 文件
    os.makedirs(DIR_PROBLEMS, exist_ok=True)
    temp_path = os.path.join(
        DIR_PROBLEMS, f"_bank_temp_{bank_name}.json"
    )
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

    logger.info(
        f"从题库 {bank_name} 随机选取 {len(problems)} 道题目，开始评测..."
    )

    # 复用现有评测流水线（传入 bank_name 以启用答案库辅助评判）
    html_path = await run_evaluation(
        temp_path, concurrency,
        progress_callback=progress_callback, bank_name=bank_name,
    )

    # 将临时文件重命名为有意义的名字
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = os.path.join(
        DIR_PROBLEMS,
        f"bank_{bank_name}_{ts}_{count}questions.json",
    )
    try:
        shutil.move(temp_path, final_path)
        logger.info(f"原始问题已保存: {final_path}")
    except OSError:
        logger.warning(
            f"无法重命名临时问题文件，保留原文件: {temp_path}"
        )

    return html_path


# ==================== 命令行入口 ====================

def main():
    """
    命令行入口 — 支持三种模式：
    1. 文件评测：-i <文件> → 转化 → 评测 → 打开报告
    2. 答案导入：--import-answers <文件> --bank <题库名> → 提取+匹配+入库
    3. 统计查询：--bank-stats <题库名> → 显示答案覆盖率
    """
    parser = argparse.ArgumentParser(
        description=(
            "Math Agent Evaluator - "
            "支持 PDF/Word/PPT/Markdown/Excel/JSON/CSV 自动转化 + 答案导入匹配"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python 测试工具/main.py -i 题目.pdf
  python 测试工具/main.py -i 题目.docx --max 10
  python 测试工具/main.py -i 题目.json -c 5
  python 测试工具/main.py -i 题目.xlsx --max 50
  python 测试工具/main.py --import-answers 答案.pptx --bank 我的题库
  python 测试工具/main.py --import-answers 答案.pdf --bank 我的题库
  python 测试工具/main.py --import-answers 答案.xlsx --bank 我的题库 --batch 20
  python 测试工具/main.py --bank-stats 我的题库
        """,
    )
    parser.add_argument(
        "-i", "--input", required=False,
        help="输入文件路径（.pdf / .docx / .pptx / .ppt / .md / .xlsx / .json / .csv）",
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=3,
        help="最大并发数（默认 3）",
    )
    parser.add_argument(
        "--max", type=int, default=0,
        help="最多评测题目数（0=全部，仅 PDF/Word 有效）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="详细日志",
    )
    parser.add_argument(
        "--no-lean", action="store_true",
        help="跳过 Lean 形式化验证阶段",
    )

    # 答案导入相关参数
    parser.add_argument(
        "--import-answers",
        help="导入答案文档（.pptx / .ppt / .docx / .txt / .md / .pdf / .csv / .xlsx / .json）"
             "并智能匹配到题库",
    )
    parser.add_argument(
        "--bank", default=None,
        help="目标题库名称（与 --import-answers 配合使用）",
    )
    parser.add_argument(
        "--batch", type=int, default=15,
        help="匹配批处理大小（默认 15）",
    )
    parser.add_argument(
        "--bank-stats", help="查看指定题库的答案映射统计",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 命令: 查看答案映射统计
    if args.bank_stats:
        _handle_bank_stats(args.bank_stats)
        return

    # 命令: 导入答案文档
    if args.import_answers:
        _handle_import_answers(args)
        return

    # 原有评测流程
    if not args.input:
        parser.print_help()
        sys.exit(1)

    # 加载并验证配置
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
    html_path = asyncio.run(
        run_evaluation(
            json_path, args.concurrency,
            enable_lean=not args.no_lean,
        )
    )

    # 步骤3: 自动打开报告
    if html_path:
        try:
            os.startfile(html_path)
            print("\n[报告] 已在浏览器中打开。")
        except Exception:
            pass


def _handle_bank_stats(bank_name: str) -> None:
    """处理 --bank-stats 命令：显示答案映射统计"""
    from question_bank import get_db
    db = get_db()
    stats = db.get_answer_mapping_stats(bank_name)
    print(f"\n题库「{bank_name}」答案映射统计:")
    print(f"  总映射数: {stats['total_mappings']}")
    print(
        f"  已覆盖题目: "
        f"{stats['covered_problems']}/{stats['total_problems']}"
    )
    print(f"  覆盖率: {stats['coverage_rate']}%")


def _handle_import_answers(args) -> None:
    """处理 --import-answers 命令：导入答案文档"""
    if not args.bank:
        print("[ERROR] --import-answers 需要同时指定 --bank 题库名称")
        sys.exit(1)

    validate_config(load_config())

    from question_bank import get_db
    db = get_db()

    if not db.bank_exists(args.bank):
        print(f"[ERROR] 题库不存在: {args.bank}，请先在 GUI 中创建")
        sys.exit(1)

    print(f"\n{'='*50}")
    print("  答案导入与智能匹配")
    print(f"  答案文件: {args.import_answers}")
    print(f"  目标题库: {args.bank}")
    print(f"{'='*50}\n")

    def cli_progress(current, total, message):
        """CLI 进度条回调"""
        pct = int(current / total * 100) if total > 0 else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(
            f"\r  [{bar}] {pct:3d}% {message}", end="", flush=True
        )

    try:
        result = db.import_answers_from_file(
            args.import_answers,
            args.bank,
            batch_size=args.batch,
            progress_callback=cli_progress,
        )
        print()  # 换行
        print(f"\n{'='*50}")
        print("  导入完成！")
        print(f"  提取答案: {result['extracted_count']} 条")
        print(f"  成功匹配: {result['matched_count']} 条")
        print(f"  已入库:   {result['imported_count']} 条")
        print(f"  题库覆盖率: {result['coverage_rate']}%")
        print(f"  Token 消耗: {result['tokens_used']}")
        print(f"  总耗时:    {result['latency']}s")
        if result["errors"]:
            print(f"  错误: {len(result['errors'])} 条")
            for e in result["errors"][:3]:
                print(f"    - {e}")
        print(f"{'='*50}")
    except Exception as e:
        print(f"\n[ERROR] 导入失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
