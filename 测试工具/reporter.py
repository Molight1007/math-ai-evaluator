"""
报告生成器 - 生成 JSON、CSV、终端和 HTML 格式的评测报告。
"""
import csv
import json
import logging
import os
import datetime
from models import EvaluationResult
from aggregator import compute_summary

logger = logging.getLogger(__name__)


def generate_json_report(results, output_path):
    """生成 JSON 格式报告，包含摘要统计和逐题详情"""
    data = {
        "generated_at": datetime.datetime.now().isoformat(),
        "summary": compute_summary(results),
        "results": [r.to_dict() for r in results],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON report saved to {output_path}")
    return output_path


def generate_csv_report(results, output_path):
    """生成 CSV 格式报告，使用 utf-8-sig 编码以兼容 Excel"""
    if not results:
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("")
        return output_path
    fieldnames = [
        "problem_id", "domain", "question", "reference_answer",
        "intern_answer", "is_correct", "confidence",
        "judge_explanation", "error_type", "correct_answer_judge",
        "inference_tokens", "judge_tokens",
        "inference_latency", "judge_latency",
        "inference_error", "judge_error",
    ]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "problem_id": r.problem_id,
                "domain": r.domain or "",
                "question": r.question,
                "reference_answer": r.reference_answer or "",
                "intern_answer": r.intern_answer,
                "is_correct": r.is_correct,
                "confidence": r.confidence,
                "judge_explanation": r.judge_explanation,
                "error_type": r.error_type or "",
                "correct_answer_judge": r.correct_answer_judge or "",
                "inference_tokens": r.inference_tokens,
                "judge_tokens": r.judge_tokens,
                "inference_latency": r.inference_latency,
                "judge_latency": r.judge_latency,
                "inference_error": r.inference_error or "",
                "judge_error": r.judge_error or "",
            })
    logger.info(f"CSV report saved to {output_path}")
    return output_path


def print_summary(results):
    """在终端打印评测摘要，包含总体统计、错误分布和分域准确率"""
    summary = compute_summary(results)
    print("\n" + "=" * 60)
    print("  MATH AGENT EVALUATION REPORT")
    print("=" * 60)
    print(f"  Total Problems:    {summary['total']}")
    print(f"  Correct:           {summary['correct']}")
    print(f"  Accuracy:          {summary['accuracy']}%")
    print(f"  Avg Confidence:    {summary['avg_confidence']}")
    print(f"  Avg Inf. Latency:  {summary['avg_inference_latency']}s")
    print(f"  Avg Judge Latency: {summary['avg_judge_latency']}s")
    print(f"  Total Tokens:      {summary['total_inference_tokens'] + summary['total_judge_tokens']}")
    print("-" * 60)
    if summary["error_types"]:
        print("  Error Distribution:")
        for etype, count in summary["error_types"].items():
            print(f"    {etype}: {count}")
    if summary["domain_stats"]:
        print("-" * 60)
        print("  Domain Accuracy:")
        for domain, stats in summary["domain_stats"].items():
            print(f"    {domain}: {stats['accuracy']}% ({stats['correct']}/{stats['total']})")
    print("-" * 60)
    print("  Per-Problem Results:")
    for i, r in enumerate(results, 1):
        status = "PASS" if r.is_correct else "FAIL"
        print(f"  [{i}] {status} | {r.problem_id}: {r.intern_answer[:60]}")
    print("=" * 60)


def _escape_html(text):
    """HTML 转义：防止 XSS 和标签破坏"""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")


def generate_html_report(results, output_path):
    """生成内联 CSS 的 HTML 可视化报告"""
    summary = compute_summary(results)

    # 构建逐题表格行
    rows_html = ""
    for r in results:
        status_class = "pass" if r.is_correct else "fail"
        status_text = "Correct" if r.is_correct else "Wrong"
        error_html = f'<span class="error-type">{r.error_type}</span>' if r.error_type else ""
        domain_html = f'<span class="domain-tag">{r.domain}</span>' if r.domain else ""
        rows_html += f"""
        <tr class="{status_class}">
            <td>{r.problem_id}</td>
            <td>{domain_html}</td>
            <td class="question-cell" title="{_escape_html(r.question)}">{_escape_html(r.question[:80])}...</td>
            <td>{_escape_html(r.intern_answer[:60])}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td>{r.confidence:.2f}</td>
            <td>{error_html}</td>
            <td>{r.inference_latency}s</td>
            <td>{r.judge_latency}s</td>
            <td>{r.inference_tokens + r.judge_tokens}</td>
        </tr>"""

    # 构建分域统计卡片
    domain_html = ""
    for domain, stats in summary.get("domain_stats", {}).items():
        domain_html += f"""
        <div class="domain-stat">
            <span class="domain-name">{domain}</span>
            <span class="domain-acc">{stats['accuracy']}%</span>
            <span class="domain-count">({stats['correct']}/{stats['total']})</span>
        </div>"""

    # 完整 HTML 模板（内联 CSS）
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Math Agent Evaluation Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #333; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; color: #1a1a2e; }}
        .subtitle {{ color: #666; margin-bottom: 24px; }}
        .summary-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
        .card-label {{ font-size: 13px; color: #888; margin-bottom: 4px; }}
        .card-value {{ font-size: 32px; font-weight: 700; color: #1a1a2e; }}
        .card-value.green {{ color: #10b981; }}
        .card-value.red {{ color: #ef4444; }}
        .section-title {{ font-size: 20px; font-weight: 600; margin: 32px 0 16px; color: #1a1a2e; }}
        .domain-stats {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
        .domain-stat {{ background: white; border-radius: 8px; padding: 12px 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }}
        .domain-name {{ font-weight: 600; margin-right: 8px; }}
        .domain-acc {{ color: #6366f1; font-weight: 700; }}
        .domain-count {{ color: #999; font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
        th {{ background: #f8fafc; padding: 12px 16px; text-align: left; font-size: 13px; color: #666; font-weight: 600; border-bottom: 2px solid #e5e7eb; }}
        td {{ padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #f3f4f6; }}
        tr:hover {{ background: #f8fafc; }}
        tr.fail {{ background: #fef2f2; }}
        .status-badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        .status-badge.pass {{ background: #d1fae5; color: #065f46; }}
        .status-badge.fail {{ background: #fee2e2; color: #991b1b; }}
        .error-type {{ display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; background: #fef3c7; color: #92400e; }}
        .domain-tag {{ display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; background: #e0e7ff; color: #3730a3; margin-right: 4px; }}
        .question-cell {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Math Agent Evaluation Report</h1>
        <p class="subtitle">Generated at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <div class="summary-cards">
            <div class="card"><div class="card-label">Total</div><div class="card-value">{summary['total']}</div></div>
            <div class="card"><div class="card-label">Correct</div><div class="card-value green">{summary['correct']}</div></div>
            <div class="card"><div class="card-label">Accuracy</div><div class="card-value {'green' if summary['accuracy'] >= 60 else 'red'}">{summary['accuracy']}%</div></div>
            <div class="card"><div class="card-label">Avg Confidence</div><div class="card-value">{summary['avg_confidence']}</div></div>
            <div class="card"><div class="card-label">Avg Inf. Latency</div><div class="card-value">{summary['avg_inference_latency']}s</div></div>
            <div class="card"><div class="card-label">Avg Judge Latency</div><div class="card-value">{summary['avg_judge_latency']}s</div></div>
        </div>
        {f'<h2 class="section-title">Domain Performance</h2><div class="domain-stats">{domain_html}</div>' if domain_html else ''}
        <h2 class="section-title">Detailed Results</h2>
        <table>
            <thead><tr><th>ID</th><th>Domain</th><th>Question</th><th>Answer</th><th>Status</th><th>Conf.</th><th>Error</th><th>Inf. Time</th><th>Judge Time</th><th>Tokens</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"HTML report saved to {output_path}")
    return output_path
