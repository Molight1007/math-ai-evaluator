"""
报告生成器 - 生成 JSON、CSV、终端和 HTML 格式的评测报告。
"""
import csv
import datetime
import json
import logging
import os
from models import EvaluationResult
from aggregator import compute_summary

logger = logging.getLogger(__name__)

# ==================== 模块级常量 ====================

# 终端显示的字符串截断长度
_TERMINAL_ANSWER_MAXLEN = 60
_HTML_QUESTION_MAXLEN = 80
_HTML_ANSWER_MAXLEN = 60


def generate_json_report(results: list[EvaluationResult], output_path: str) -> str:
    """
    生成 JSON 格式报告，包含摘要统计和逐题详情。

    参数:
        results: 评测结果列表
        output_path: 输出 JSON 文件路径

    返回:
        output_path
    """
    data = {
        "generated_at": datetime.datetime.now().isoformat(),
        "summary": compute_summary(results),
        "results": [r.to_dict() for r in results],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON report saved to {output_path}")
    return output_path


def generate_csv_report(results: list[EvaluationResult], output_path: str) -> str:
    """
    生成 CSV 格式报告，使用 utf-8-sig 编码以兼容 Excel。

    参数:
        results: 评测结果列表
        output_path: 输出 CSV 文件路径

    返回:
        output_path
    """
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


def print_summary(results: list[EvaluationResult]) -> None:
    """
    在终端打印评测摘要，包含总体统计、Lean 验证统计、错误分布和分域准确率。

    参数:
        results: 评测结果列表
    """
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
    total_tokens = summary["total_inference_tokens"] + summary["total_judge_tokens"]
    print(f"  Total Tokens:      {total_tokens}")
    print("-" * 60)
    if summary["error_types"]:
        print("  Error Distribution:")
        for etype, count in summary["error_types"].items():
            print(f"    {etype}: {count}")

    # Lean 验证统计
    _print_lean_terminal_summary(results)

    if summary["domain_stats"]:
        print("-" * 60)
        print("  Domain Accuracy:")
        for domain, stats in summary["domain_stats"].items():
            print(
                f"    {domain}: {stats['accuracy']}% "
                f"({stats['correct']}/{stats['total']})"
            )
    print("-" * 60)
    print("  Per-Problem Results:")
    for i, r in enumerate(results, 1):
        status = "PASS" if r.is_correct else "FAIL"
        answer = r.intern_answer[:_TERMINAL_ANSWER_MAXLEN]
        print(f"  [{i}] {status} | {r.problem_id}: {answer}")
    print("=" * 60)


def _print_lean_terminal_summary(results: list[EvaluationResult]) -> None:
    """
    在终端打印 Lean 验证统计摘要。

    参数:
        results: 评测结果列表
    """
    lean_verified = sum(
        1 for r in results
        if r.lean_verification and r.lean_verification.get("verified")
    )
    lean_logic_errors = sum(
        1 for r in results
        if r.lean_verification
        and r.lean_verification.get("error_category") == "logic_error"
    )
    lean_incomplete = sum(
        1 for r in results
        if r.lean_verification
        and r.lean_verification.get("has_incomplete_proof")
    )
    if lean_verified > 0:
        print("-" * 60)
        print("  Lean Verification:")
        print(f"    Verified: {lean_verified}")
        print(f"    Logic errors found: {lean_logic_errors}")
        if lean_incomplete > 0:
            print(f"    Proof incomplete (sorry): {lean_incomplete}")


# ==================== HTML 报告生成 ====================

def _escape_html(text: str) -> str:
    """
    HTML 转义：防止 XSS 和标签破坏。

    参数:
        text: 原始文本

    返回:
        转义后的安全文本
    """
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_lean_badge_html(eval_result) -> str:
    """
    根据 Lean 验证结果生成表格中的状态标记 HTML。

    参数:
        eval_result: EvaluationResult 对象

    返回:
        Lean 状态标记的 HTML 字符串，无需验证时返回空字符串
    """
    lv = eval_result.lean_verification
    if not lv or not lv.get("verified"):
        return ""

    if lv.get("compile_passed") is True:
        if lv.get("has_incomplete_proof"):
            sc = lv.get("sorry_count", 0)
            return (
                '<span class="lean-badge lean-incomplete" '
                f'title="Proof incomplete: {sc} sorry detected">L!不完整</span>'
            )
        return (
            '<span class="lean-badge lean-pass" '
            'title="Lean compilation passed">L✓</span>'
        )
    elif lv.get("compile_passed") is False:
        cat = lv.get("error_category", "")
        if cat == "logic_error":
            return (
                '<span class="lean-badge lean-logic-err" '
                'title="Logic error detected">L✗逻辑</span>'
            )
        elif cat == "translation_error":
            return (
                '<span class="lean-badge lean-trans-err" '
                'title="Translation error">L✗转化</span>'
            )
        else:
            return (
                '<span class="lean-badge lean-unknown" '
                'title="Compilation failed">L✗</span>'
            )
    elif lv.get("analysis_performed"):
        return (
            '<span class="lean-badge lean-review" '
            'title="LLM logic review">L审</span>'
        )
    return ""


def _build_table_rows(results: list[EvaluationResult]) -> str:
    """
    构建 HTML 报告中的逐题表格行。

    参数:
        results: 评测结果列表

    返回:
        表格行 HTML 字符串
    """
    rows_html = ""
    for r in results:
        status_class = "pass" if r.is_correct else "fail"
        status_text = "Correct" if r.is_correct else "Wrong"
        error_html = (
            f'<span class="error-type">{_escape_html(r.error_type)}</span>'
            if r.error_type else ""
        )
        domain_html = (
            f'<span class="domain-tag">{_escape_html(r.domain)}</span>'
            if r.domain else ""
        )
        lean_html = _build_lean_badge_html(r)

        detail_data = {
            "problem_id": r.problem_id,
            "domain": r.domain or "",
            "question": r.question,
            "reference_answer": r.reference_answer or "",
            "intern_answer": r.intern_answer,
            "intern_reasoning": r.intern_reasoning,
            "intern_steps": r.intern_steps,
            "intern_verification": r.intern_verification,
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
            "lean_verification": r.lean_verification,
        }
        detail_json = json.dumps(detail_data, ensure_ascii=False)
        detail_escaped = (
            detail_json.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        rows_html += f"""
        <tr class="{status_class} detail-row" data-detail="{detail_escaped}" onclick="showDetail(this)" style="cursor:pointer">
            <td>{_escape_html(r.problem_id)}</td>
            <td>{domain_html}</td>
            <td class="question-cell clickable-question" title="点击查看详情">{_escape_html(r.question[:_HTML_QUESTION_MAXLEN])}...</td>
            <td>{_escape_html(r.intern_answer[:_HTML_ANSWER_MAXLEN])}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td>{r.confidence:.2f}</td>
            <td>{error_html}</td>
            <td>{lean_html}</td>
            <td>{r.inference_latency}s</td>
            <td>{r.judge_latency}s</td>
            <td>{r.inference_tokens + r.judge_tokens}</td>
        </tr>"""
    return rows_html


def _build_domain_cards(summary: dict) -> str:
    """
    构建分域统计卡片的 HTML。

    参数:
        summary: compute_summary 返回的统计字典

    返回:
        分域卡片 HTML 字符串，无数据时返回空字符串
    """
    parts = []
    for domain, stats in summary.get("domain_stats", {}).items():
        parts.append(f"""
        <div class="domain-stat">
            <span class="domain-name">{domain}</span>
            <span class="domain-acc">{stats['accuracy']}%</span>
            <span class="domain-count">({stats['correct']}/{stats['total']})</span>
        </div>""")
    if not parts:
        return ""
    return (
        '<h2 class="section-title">Domain Performance</h2>'
        f'<div class="domain-stats">{"".join(parts)}</div>'
    )


# ==================== HTML 模板（CSS 内联） ====================

_HTML_CSS = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
        h1 { font-size: 28px; margin-bottom: 8px; color: #1a1a2e; }
        .subtitle { color: #666; margin-bottom: 24px; }
        .summary-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }
        .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .card-label { font-size: 13px; color: #888; margin-bottom: 4px; }
        .card-value { font-size: 32px; font-weight: 700; color: #1a1a2e; }
        .card-value.green { color: #10b981; }
        .card-value.red { color: #ef4444; }
        .section-title { font-size: 20px; font-weight: 600; margin: 32px 0 16px; color: #1a1a2e; }
        .domain-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
        .domain-stat { background: white; border-radius: 8px; padding: 12px 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
        .domain-name { font-weight: 600; margin-right: 8px; }
        .domain-acc { color: #6366f1; font-weight: 700; }
        .domain-count { color: #999; font-size: 13px; }
        table { width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        th { background: #f8fafc; padding: 12px 16px; text-align: left; font-size: 13px; color: #666; font-weight: 600; border-bottom: 2px solid #e5e7eb; }
        td { padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #f3f4f6; }
        tr:hover { background: #f8fafc; }
        tr.fail { background: #fef2f2; }
        .status-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .status-badge.pass { background: #d1fae5; color: #065f46; }
        .status-badge.fail { background: #fee2e2; color: #991b1b; }
        .error-type { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; background: #fef3c7; color: #92400e; }
        .domain-tag { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; background: #e0e7ff; color: #3730a3; margin-right: 4px; }
        .lean-badge { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 10px; font-weight: 700; }
        .lean-badge.lean-pass { background: #D1FAE5; color: #065F46; }
        .lean-badge.lean-logic-err { background: #FEE2E2; color: #991B1B; }
        .lean-badge.lean-trans-err { background: #FEF3C7; color: #92400E; }
        .lean-badge.lean-unknown { background: #F1F5F9; color: #64748B; }
        .lean-badge.lean-review { background: #E0E7FF; color: #3730A3; }
        .lean-badge.lean-incomplete { background: #FEF3C7; color: #92400E; border: 1px solid #F59E0B; }
        .section-heading.lean { color: #059669; border-color: #A7F3D0; }
        .section-heading .icon-dot.lean { background: #10B981; }
        .lean-status { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }
        .lean-status.pass { background: #D1FAE5; color: #065F46; }
        .lean-status.fail { background: #FEE2E2; color: #991B1B; }
        .lean-status.pending { background: #F1F5F9; color: #64748B; }
        .lean-status.warn { background: #FFFBEB; color: #92400E; border: 1px solid #FDE68A; }
        .content-box.lean-code { background: #1E293B; color: #E2E8F0; border-color: #334155; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 12px; }
        .content-box.lean-error { background: #FEF2F2; border-color: #FECACA; color: #991B1B; font-size: 12px; }
        .lean-insight { background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 10px; padding: 14px 16px; margin-top: 12px; }
        .lean-insight .insight-title { font-size: 13px; font-weight: 700; color: #92400E; margin-bottom: 8px; }
        .question-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .clickable-question { color: #2563EB; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 3px; }
        .detail-row:hover { background: #eff6ff !important; }
        .detail-row:hover .clickable-question { color: #1D4ED8; text-decoration-style: solid; }
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(15,23,42,0.55); backdrop-filter: blur(4px); z-index: 1000; animation: fadeIn 0.25s ease; }
        .modal-overlay.active { display: flex; align-items: center; justify-content: center; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .modal-card { background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); border-radius: 16px; width: 90%; max-width: 820px; max-height: 88vh; box-shadow: 0 25px 60px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.5) inset; display: flex; flex-direction: column; animation: slideUp 0.3s ease; }
        .modal-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 28px 16px; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; }
        .modal-header-left { display: flex; align-items: center; gap: 12px; }
        .modal-title { font-size: 17px; font-weight: 700; color: #1E293B; }
        .modal-status { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .modal-status.pass { background: #D1FAE5; color: #065F46; }
        .modal-status.fail { background: #FEE2E2; color: #991B1B; }
        .modal-confidence { font-size: 13px; color: #64748B; }
        .modal-confidence span { font-weight: 700; color: #3B82F6; }
        .modal-close { width: 32px; height: 32px; border-radius: 50%; border: none; background: #f1f5f9; color: #64748B; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; flex-shrink: 0; }
        .modal-close:hover { background: #ef4444; color: white; }
        .modal-body { padding: 20px 28px 28px; overflow-y: auto; flex: 1; }
        .modal-body::-webkit-scrollbar { width: 6px; }
        .modal-body::-webkit-scrollbar-track { background: transparent; }
        .modal-body::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        .detail-section { margin-bottom: 20px; }
        .detail-section:last-child { margin-bottom: 0; }
        .section-heading { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 2px solid; }
        .section-heading.ai { color: #2563EB; border-color: #BFDBFE; }
        .section-heading.judge { color: #7C3AED; border-color: #DDD6FE; }
        .section-heading.info { color: #475569; border-color: #E2E8F0; }
        .section-heading .icon-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .section-heading .icon-dot.ai { background: #3B82F6; }
        .section-heading .icon-dot.judge { background: #7C3AED; }
        .section-heading .icon-dot.info { background: #94A3B8; }
        .content-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; color: #334155; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', 'Microsoft YaHei', monospace; }
        .content-box.highlight { background: #FFF7ED; border-color: #FED7AA; }
        .content-box.correct-answer { background: #F0FDF4; border-color: #BBF7D0; color: #166534; }
        .steps-list { list-style: none; padding: 0; margin: 0; }
        .steps-list li { padding: 10px 14px; margin-bottom: 4px; background: #F8FAFC; border-radius: 8px; border-left: 3px solid #3B82F6; font-size: 13px; line-height: 1.6; color: #334155; }
        .steps-list li:nth-child(even) { background: #EFF6FF; }
        .steps-list li .step-num { display: inline-block; min-width: 28px; font-weight: 700; color: #2563EB; }
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .info-item { background: #F8FAFC; border-radius: 8px; padding: 10px 14px; }
        .info-item .info-label { font-size: 11px; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
        .info-item .info-value { font-size: 14px; font-weight: 600; color: #1E293B; }
        .info-item.full { grid-column: 1 / -1; }
        .detail-tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-right: 6px; }
        .detail-tag.error { background: #FEF3C7; color: #92400E; }
        .detail-tag.domain { background: #E0E7FF; color: #3730A3; }
        .perf-bar { display: flex; gap: 12px; margin-top: 16px; padding: 14px 18px; background: linear-gradient(135deg, #F1F5F9 0%, #E2E8F0 100%); border-radius: 10px; }
        .perf-item { flex: 1; text-align: center; }
        .perf-item .perf-val { font-size: 18px; font-weight: 700; color: #1E293B; }
        .perf-item .perf-label { font-size: 11px; color: #64748B; }
"""

# HTML 模板：页面结构（不含 CSS，CSS 内联注入）
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Math Agent Evaluation Report</title>
    <style>
{css}
    </style>
</head>
<body>
    <div class="container">
        <h1>Math Agent Evaluation Report</h1>
        <p class="subtitle">Generated at {now_str}</p>
        <div class="summary-cards">
            <div class="card"><div class="card-label">Total</div><div class="card-value">{total}</div></div>
            <div class="card"><div class="card-label">Correct</div><div class="card-value green">{correct}</div></div>
            <div class="card"><div class="card-label">Accuracy</div><div class="card-value {accuracy_class}">{accuracy}%</div></div>
            <div class="card"><div class="card-label">Avg Confidence</div><div class="card-value">{avg_confidence}</div></div>
            <div class="card"><div class="card-label">Avg Inf. Latency</div><div class="card-value">{avg_inference_latency}s</div></div>
            <div class="card"><div class="card-label">Avg Judge Latency</div><div class="card-value">{avg_judge_latency}s</div></div>
        </div>
        {domain_section}
        <h2 class="section-title">Detailed Results</h2>
        <table>
            <thead><tr><th>ID</th><th>Domain</th><th>Question</th><th>Answer</th><th>Status</th><th>Conf.</th><th>Error</th><th>Lean</th><th>Inf. Time</th><th>Judge Time</th><th>Tokens</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
{modal_js}
</body>
</html>"""

# Modal + JS 模板（独立注入，避免 Python 字符串中大括号问题）
_MODAL_JS = r"""
    <!-- Modal Overlay -->
    <div class="modal-overlay" id="modalOverlay" onclick="hideDetail(event)">
        <div class="modal-card" id="modalCard" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-header-left">
                    <span class="modal-title" id="modalTitle">---</span>
                    <span class="modal-status" id="modalStatus">---</span>
                    <span class="modal-confidence">Confidence: <span id="modalConf">--</span></span>
                </div>
                <button class="modal-close" onclick="hideDetail()" title="Close (Esc)">&times;</button>
            </div>
            <div class="modal-body" id="modalBody"></div>
        </div>
    </div>

    <script>
    function showDetail(row) {
        var raw = row.getAttribute('data-detail');
        var d = JSON.parse(raw);
        var overlay = document.getElementById('modalOverlay');
        var body = document.getElementById('modalBody');

        // Header
        document.getElementById('modalTitle').textContent = d.problem_id;
        var statusEl = document.getElementById('modalStatus');
        if (d.is_correct) {
            statusEl.className = 'modal-status pass';
            statusEl.innerHTML = '&#10003; Correct';
        } else {
            statusEl.className = 'modal-status fail';
            statusEl.innerHTML = '&#10007; Wrong';
        }
        document.getElementById('modalConf').textContent = (d.confidence * 100).toFixed(0) + '%';

        // Build body
        var tags = '';
        if (d.domain) tags += '<span class="detail-tag domain">' + esc(d.domain) + '</span>';
        if (d.error_type) tags += '<span class="detail-tag error">' + esc(d.error_type) + '</span>';

        var stepsHtml = '';
        if (d.intern_steps && d.intern_steps.length > 0) {
            stepsHtml = '<ul class="steps-list">';
            d.intern_steps.forEach(function(step, idx) {
                stepsHtml += '<li><span class="step-num">#' + (idx+1) + '</span>' + renderLatex(esc(step)) + '</li>';
            });
            stepsHtml += '</ul>';
        }

        var html = '';
        if (tags) html += '<div style="margin-bottom:16px">' + tags + '</div>';

        // Info section
        html += buildInfoSection(d);

        // AI reasoning section
        html += buildReasoningSection(d);

        // Judge analysis section
        html += buildJudgeSection(d);

        // Lean verification section
        html += buildLeanSection(d);

        // Performance bar
        html += buildPerfBar(d);

        body.innerHTML = html;
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        body.scrollTop = 0;
    }

    function buildInfoSection(d) {
        var h = '<div class="detail-section">';
        h += '<div class="section-heading info"><span class="icon-dot info"></span>&#39064;&#30446;&#20449;&#24687;</div>';
        h += '<div class="info-grid">';
        h += '<div class="info-item full"><div class="info-label">&#39064;&#24178;</div><div class="content-box" style="max-height:160px;font-family:inherit">' + esc(d.question) + '</div></div>';
        h += '<div class="info-item"><div class="info-label">&#21442;&#32771;&#31572;&#26696;</div><div class="content-box correct-answer" style="max-height:120px">' + esc(d.reference_answer || '&#26242;&#26080;') + '</div></div>';
        h += '<div class="info-item"><div class="info-label">AI &#26368;&#32456;&#31572;&#26696;</div><div class="content-box" style="max-height:120px">' + esc(d.intern_answer || '&#26242;&#26080;') + '</div></div>';
        if (d.inference_error) h += '<div class="info-item full"><div class="info-label">&#25512;&#29702;&#38169;&#35823;</div><div class="content-box highlight">' + esc(d.inference_error) + '</div></div>';
        if (d.judge_error) h += '<div class="info-item full"><div class="info-label">&#21028;&#39064;&#38169;&#35823;</div><div class="content-box highlight">' + esc(d.judge_error) + '</div></div>';
        h += '</div></div>';
        return h;
    }

    function buildReasoningSection(d) {
        var h = '<div class="detail-section">';
        h += '<div class="section-heading ai"><span class="icon-dot ai"></span>&#20070;&#29983;AI &#24605;&#32771;&#36807;&#31243;</div>';
        if (d.intern_reasoning) {
            h += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#23436;&#25972;&#25512;&#29702;&#36807;&#31243;</div>';
            h += '<div class="content-box">' + renderLatex(esc(d.intern_reasoning)) + '</div></div>';
        }
        if (d.intern_steps && d.intern_steps.length > 0) {
            h += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#20998;&#27493;&#25512;&#29702;</div>';
            var stepsHtml = '<ul class="steps-list">';
            d.intern_steps.forEach(function(step, idx) {
                stepsHtml += '<li><span class="step-num">#' + (idx+1) + '</span>' + renderLatex(esc(step)) + '</li>';
            });
            h += stepsHtml + '</ul></div>';
        }
        if (d.intern_verification) {
            h += '<div><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#33258;&#39564;&#35777;&#32467;&#35770;</div>';
            h += '<div class="content-box highlight">' + renderLatex(esc(d.intern_verification)) + '</div></div>';
        }
        if (!d.intern_reasoning && (!d.intern_steps || d.intern_steps.length === 0) && !d.intern_verification) {
            h += '<div style="color:#94A3B8;font-size:13px;padding:12px">&#26242;&#26080;AI&#25512;&#29702;&#25968;&#25454;</div>';
        }
        h += '</div>';
        return h;
    }

    function buildJudgeSection(d) {
        var h = '<div class="detail-section">';
        h += '<div class="section-heading judge"><span class="icon-dot judge"></span>DeepSeek &#21028;&#39064;&#20998;&#26512;</div>';
        if (d.judge_explanation) {
            h += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#21028;&#39064;&#35814;&#32454;&#35299;&#37322;</div>';
            h += '<div class="content-box">' + renderLatex(esc(d.judge_explanation)) + '</div></div>';
        }
        if (d.error_type) {
            h += '<div style="margin-bottom:12px"><span style="font-size:12px;color:#64748B;font-weight:600">&#38169;&#35823;&#31867;&#22411;: </span><span class="detail-tag error">' + esc(d.error_type) + '</span></div>';
        }
        if (d.correct_answer_judge) {
            h += '<div><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#21028;&#39064;&#32473;&#20986;&#30340;&#27491;&#30830;&#31572;&#26696;</div>';
            h += '<div class="content-box correct-answer">' + esc(d.correct_answer_judge) + '</div></div>';
        }
        if (!d.judge_explanation && !d.error_type && !d.correct_answer_judge) {
            h += '<div style="color:#94A3B8;font-size:13px;padding:12px">&#26242;&#26080;&#21028;&#39064;&#20998;&#26512;&#25968;&#25454;</div>';
        }
        h += '</div>';
        return h;
    }

    function buildLeanSection(d) {
        var lv = d.lean_verification;
        if (!lv || !lv.verified) return '';
        var h = '<div class="detail-section">';
        h += '<div class="section-heading lean"><span class="icon-dot lean"></span>Lean 4 &#24418;&#24335;&#21270;&#39564;&#35777;</div>';

        if (lv.compile_passed === true) {
            if (lv.has_incomplete_proof) {
                h += '<div><span class="lean-status warn">&#9888; &#32534;&#35793;&#36890;&#36807; &mdash; &#35777;&#26126;&#19981;&#23436;&#25972;&#65288;&#26816;&#27979;&#21040; ' + (lv.sorry_count || 0) + ' &#22788; sorry&#65289;</span></div>';
            } else {
                h += '<div><span class="lean-status pass">&#10003; &#32534;&#35793;&#36890;&#36807; &mdash; &#25512;&#29702;&#36923;&#36753;&#19968;&#33268;</span></div>';
            }
        } else if (lv.compile_passed === false) {
            var catLabel = lv.error_category || 'unknown';
            var catMap = {'logic_error': '&#36923;&#36753;&#38169;&#35823;', 'translation_error': '&#36716;&#21270;&#38169;&#35823;', 'both': '&#36716;&#21270;+&#36923;&#36753;&#38169;&#35823;', 'uncertain': '&#24453;&#30830;&#23450;'};
            h += '<div><span class="lean-status fail">&#10007; &#32534;&#35793;&#22833;&#36133; &mdash; ' + (catMap[catLabel] || catLabel) + '</span></div>';
        } else {
            h += '<div><span class="lean-status pending">&#8856; &#26410;&#32534;&#35793; &mdash; &#38477;&#32423;&#20026; LLM &#36923;&#36753;&#23457;&#26597;</span></div>';
        }

        if (lv.formalized_claim) {
            h += '<div style="margin-bottom:10px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#24418;&#24335;&#21270;&#21629;&#39064;</div>';
            h += '<div class="content-box" style="max-height:80px">' + esc(lv.formalized_claim) + '</div></div>';
        }
        if (lv.lean_code) {
            h += '<div style="margin-bottom:10px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">Lean 4 &#20195;&#30721;</div>';
            h += '<div class="content-box lean-code" style="max-height:200px">' + esc(lv.lean_code) + '</div></div>';
        }
        if (lv.compile_passed === false && lv.compile_output) {
            h += '<div style="margin-bottom:10px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#32534;&#35793;&#38169;&#35823;&#36755;&#20986;</div>';
            h += '<div class="content-box lean-error" style="max-height:150px">' + esc(lv.compile_output) + '</div></div>';
        }

        if (lv.analysis_performed) {
            h += '<div class="lean-insight">';
            h += '<div class="insight-title">&#128269; &#38169;&#35823;&#26681;&#22240;&#20998;&#26512;</div>';
            if (lv.human_readable_error) {
                h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#92400E;">&#38169;&#35823;&#35299;&#37322;&#65306;</span>' + esc(lv.human_readable_error) + '</div>';
            }
            if (lv.root_cause) {
                h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#92400E;">&#26681;&#22240;&#65306;</span>' + esc(lv.root_cause) + '</div>';
            }
            if (lv.error_category === 'logic_error' || lv.error_category === 'both') {
                if (lv.logic_flaw_location) {
                    h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#DC2626;">&#36923;&#36753;&#26029;&#28857;&#65306;</span>' + esc(lv.logic_flaw_location) + '</div>';
                }
                if (lv.logic_flaw_why) {
                    h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#DC2626;">&#38169;&#35823;&#21407;&#22240;&#65306;</span>' + esc(lv.logic_flaw_why) + '</div>';
                }
                if (lv.correct_approach) {
                    h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#059669;">&#27491;&#30830;&#20570;&#27861;&#65306;</span>' + esc(lv.correct_approach) + '</div>';
                }
            }
            if (lv.error_category === 'translation_error' || lv.error_category === 'both') {
                if (lv.translation_issue) {
                    h += '<div style="margin-bottom:8px"><span style="font-weight:600;color:#D97706;">&#36716;&#21270;&#38382;&#39064;&#65306;</span>' + esc(lv.translation_issue) + '</div>';
                }
            }
            if (lv.fix_prompt_for_ai) {
                h += '<div style="margin-top:12px;padding:10px;background:#F0FDF4;border-radius:8px;border-left:3px solid #10B981;">';
                h += '<div style="font-weight:700;color:#065F46;margin-bottom:4px;">&#128221; &#20462;&#27491;&#25552;&#31034;&#35789;&#65288;&#21487;&#21453;&#39304;&#32473;&#20070;&#29983;AI&#65289;</div>';
                h += '<div style="font-size:12px;color:#166534;white-space:pre-wrap">' + esc(lv.fix_prompt_for_ai) + '</div></div>';
            }
            h += '</div>';
        }

        h += '<div style="margin-top:12px;font-size:11px;color:#94A3B8">';
        h += '&#36716;&#21270;: ' + (lv.conversion_latency || 0).toFixed(1) + 's / ';
        h += '&#32534;&#35793;: ' + (lv.compile_latency || 0).toFixed(1) + 's';
        if (lv.analysis_latency) h += ' / &#20998;&#26512;: ' + (lv.analysis_latency || 0).toFixed(1) + 's';
        h += ' | Token: ' + ((lv.conversion_tokens || 0) + (lv.analysis_tokens || 0));
        if (lv.lean_available === false) h += ' | (Lean &#19981;&#21487;&#29992;&#65292;&#38477;&#32423;&#20026; LLM &#23457;&#26597;)';
        h += '</div>';
        h += '</div>';
        return h;
    }

    function buildPerfBar(d) {
        var h = '<div class="perf-bar">';
        h += '<div class="perf-item"><div class="perf-val">' + d.inference_latency.toFixed(2) + 's</div><div class="perf-label">&#25512;&#29702;&#32791;&#26102;</div></div>';
        h += '<div class="perf-item"><div class="perf-val">' + d.judge_latency.toFixed(2) + 's</div><div class="perf-label">&#21028;&#39064;&#32791;&#26102;</div></div>';
        h += '<div class="perf-item"><div class="perf-val">' + (d.inference_tokens + d.judge_tokens) + '</div><div class="perf-label">&#24635; Token</div></div>';
        h += '</div>';
        return h;
    }

    function hideDetail(e) {
        if (e && e.target !== document.getElementById('modalOverlay')) return;
        var overlay = document.getElementById('modalOverlay');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    function esc(s) {
        if (!s) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // LaTeX to readable unicode text conversion
    function renderLatex(text) {
        if (!text) return '';
        var s = text;
        s = s.replace(/\$([^$]+)\$/g, function(m, inner) { return _latexToReadable(inner.trim()); });
        s = s.replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '($1)/($2)');
        s = s.replace(/\\partial ([a-zA-Z])/g, '\u2202$1');
        s = s.replace(/\\ln /g, 'ln '); s = s.replace(/\\log /g, 'log ');
        s = s.replace(/\\sin /g, 'sin '); s = s.replace(/\\cos /g, 'cos ');
        s = s.replace(/\\tan /g, 'tan '); s = s.replace(/\\cdot /g, '\u00b7');
        s = s.replace(/\\times /g, '\u00d7'); s = s.replace(/\\div /g, '\u00f7');
        s = s.replace(/\\pm /g, '\u00b1'); s = s.replace(/\\leq ?/g, '\u2264');
        s = s.replace(/\\geq ?/g, '\u2265'); s = s.replace(/\\neq ?/g, '\u2260');
        s = s.replace(/\\approx ?/g, '\u2248'); s = s.replace(/\\infty/g, '\u221e');
        s = s.replace(/\\sum/g, '\u2211'); s = s.replace(/\\int/g, '\u222b');
        s = s.replace(/\\sqrt\{([^}]*)\}/g, '\u221a($1)');
        s = s.replace(/\^(\{([^}]*)\}|(.))/g, function(m, g1, g2, g3) { return '^' + (g2 || g3 || ''); });
        s = s.replace(/_(\{([^}]*)\}|(.))/g, function(m, g1, g2, g3) { return '_' + (g2 || g3 || ''); });
        s = s.replace(/\\left/g, ''); s = s.replace(/\\right/g, '');
        s = s.replace(/\\[a-zA-Z]+/g, '');
        return s;
    }

    function _latexToReadable(expr) {
        var s = expr;
        s = s.replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '($1)/($2)');
        s = s.replace(/\^\{([^}]*)\}/g, '^($1)'); s = s.replace(/_\{([^}]*)\}/g, '_($1)');
        s = s.replace(/\^(\w)/g, '^$1'); s = s.replace(/_(\w)/g, '_$1');
        s = s.replace(/\\alpha/g, '\u03b1'); s = s.replace(/\\beta/g, '\u03b2');
        s = s.replace(/\\gamma/g, '\u03b3'); s = s.replace(/\\delta/g, '\u03b4');
        s = s.replace(/\\epsilon/g, '\u03b5'); s = s.replace(/\\theta/g, '\u03b8');
        s = s.replace(/\\lambda/g, '\u03bb'); s = s.replace(/\\pi/g, '\u03c0');
        s = s.replace(/\\sigma/g, '\u03c3'); s = s.replace(/\\phi/g, '\u03c6');
        s = s.replace(/\\omega/g, '\u03c9'); s = s.replace(/\\rho/g, '\u03c1');
        s = s.replace(/\\partial/g, '\u2202'); s = s.replace(/\\nabla/g, '\u2207');
        s = s.replace(/\\ln(?![a-zA-Z])/g, 'ln'); s = s.replace(/\\log(?![a-zA-Z])/g, 'log');
        s = s.replace(/\\sin(?![a-zA-Z])/g, 'sin'); s = s.replace(/\\cos(?![a-zA-Z])/g, 'cos');
        s = s.replace(/\\tan(?![a-zA-Z])/g, 'tan'); s = s.replace(/\\cdot/g, '\u00b7');
        s = s.replace(/\\times/g, '\u00d7'); s = s.replace(/\\div/g, '\u00f7');
        s = s.replace(/\\pm/g, '\u00b1'); s = s.replace(/\\leq/g, '\u2264');
        s = s.replace(/\\geq/g, '\u2265'); s = s.replace(/\\neq/g, '\u2260');
        s = s.replace(/\\approx/g, '\u2248'); s = s.replace(/\\infty/g, '\u221e');
        s = s.replace(/\\sum/g, '\u2211'); s = s.replace(/\\int/g, '\u222b');
        s = s.replace(/\\sqrt\{([^}]*)\}/g, '\u221a($1)');
        s = s.replace(/\\sqrt([a-zA-Z0-9])/g, '\u221a$1');
        s = s.replace(/\\left/g, ''); s = s.replace(/\\right/g, '');
        s = s.replace(/\\,[ ]*/g, ', '); s = s.replace(/\\;[ ]*/g, '  ');
        s = s.replace(/\\[a-zA-Z]+/g, '');
        return s;
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            hideDetail({target: document.getElementById('modalOverlay')});
        }
    });
    </script>
"""


def generate_html_report(
    results: list[EvaluationResult], output_path: str
) -> str:
    """
    生成内联 CSS 的 HTML 可视化报告。

    报告包含：
    - 顶部摘要卡片（总数、正确数、准确率、置信度、耗时）
    - 分域统计
    - 详细结果表格（可点击查看弹窗详情，含 Lean 验证结果）
    - 点击弹窗展示完整推理过程、评判分析和 Lean 验证详情

    参数:
        results: 评测结果列表
        output_path: 输出 HTML 文件路径

    返回:
        output_path
    """
    summary = compute_summary(results)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accuracy_class = "green" if summary["accuracy"] >= 60 else "red"
    domain_section = _build_domain_cards(summary)
    rows_html = _build_table_rows(results)

    html = _HTML_TEMPLATE.format(
        css=_HTML_CSS,
        now_str=now_str,
        total=summary["total"],
        correct=summary["correct"],
        accuracy=summary["accuracy"],
        accuracy_class=accuracy_class,
        avg_confidence=summary["avg_confidence"],
        avg_inference_latency=summary["avg_inference_latency"],
        avg_judge_latency=summary["avg_judge_latency"],
        domain_section=domain_section,
        rows_html=rows_html,
        modal_js=_MODAL_JS,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"HTML report saved to {output_path}")
    return output_path
