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
    for i, r in enumerate(results):
        status_class = "pass" if r.is_correct else "fail"
        status_text = "Correct" if r.is_correct else "Wrong"
        error_html = f'<span class="error-type">{_escape_html(r.error_type)}</span>' if r.error_type else ""
        domain_html = f'<span class="domain-tag">{_escape_html(r.domain)}</span>' if r.domain else ""

        # 构建完整详情数据 JSON，嵌入 data-detail 属性
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
        }
        detail_json = json.dumps(detail_data, ensure_ascii=False)
        detail_escaped = detail_json.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        rows_html += f"""
        <tr class="{status_class} detail-row" data-detail="{detail_escaped}" onclick="showDetail(this)" style="cursor:pointer">
            <td>{_escape_html(r.problem_id)}</td>
            <td>{domain_html}</td>
            <td class="question-cell clickable-question" title="点击查看详情">{_escape_html(r.question[:80])}...</td>
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

    # 完整 HTML 模板 — 分两段构建以避免 f-string 中 JS 花括号的语法问题
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accuracy_class = 'green' if summary['accuracy'] >= 60 else 'red'
    domain_section = (
        '<h2 class="section-title">Domain Performance</h2>'
        f'<div class="domain-stats">{domain_html}</div>'
    ) if domain_html else ''

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
        .clickable-question {{ color: #2563EB; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 3px; }}
        .detail-row:hover {{ background: #eff6ff !important; }}
        .detail-row:hover .clickable-question {{ color: #1D4ED8; text-decoration-style: solid; }}
        /* Modal overlay */
        .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(15,23,42,0.55); backdrop-filter: blur(4px); z-index: 1000; animation: fadeIn 0.25s ease; }}
        .modal-overlay.active {{ display: flex; align-items: center; justify-content: center; }}
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
        @keyframes slideUp {{ from {{ transform: translateY(30px); opacity: 0; }} to {{ transform: translateY(0); opacity: 1; }} }}
        /* Modal card */
        .modal-card {{ background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); border-radius: 16px; width: 90%; max-width: 820px; max-height: 88vh; box-shadow: 0 25px 60px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.5) inset; display: flex; flex-direction: column; animation: slideUp 0.3s ease; }}
        .modal-header {{ display: flex; align-items: center; justify-content: space-between; padding: 20px 28px 16px; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; }}
        .modal-header-left {{ display: flex; align-items: center; gap: 12px; }}
        .modal-title {{ font-size: 17px; font-weight: 700; color: #1E293B; }}
        .modal-status {{ display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .modal-status.pass {{ background: #D1FAE5; color: #065F46; }}
        .modal-status.fail {{ background: #FEE2E2; color: #991B1B; }}
        .modal-confidence {{ font-size: 13px; color: #64748B; }}
        .modal-confidence span {{ font-weight: 700; color: #3B82F6; }}
        .modal-close {{ width: 32px; height: 32px; border-radius: 50%; border: none; background: #f1f5f9; color: #64748B; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; flex-shrink: 0; }}
        .modal-close:hover {{ background: #ef4444; color: white; }}
        .modal-body {{ padding: 20px 28px 28px; overflow-y: auto; flex: 1; }}
        .modal-body::-webkit-scrollbar {{ width: 6px; }}
        .modal-body::-webkit-scrollbar-track {{ background: transparent; }}
        .modal-body::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
        /* Section blocks */
        .detail-section {{ margin-bottom: 20px; }}
        .detail-section:last-child {{ margin-bottom: 0; }}
        .section-heading {{ display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 2px solid; }}
        .section-heading.ai {{ color: #2563EB; border-color: #BFDBFE; }}
        .section-heading.judge {{ color: #7C3AED; border-color: #DDD6FE; }}
        .section-heading.info {{ color: #475569; border-color: #E2E8F0; }}
        .section-heading .icon-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
        .section-heading .icon-dot.ai {{ background: #3B82F6; }}
        .section-heading .icon-dot.judge {{ background: #7C3AED; }}
        .section-heading .icon-dot.info {{ background: #94A3B8; }}
        /* Content boxes */
        .content-box {{ background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; color: #334155; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', 'Microsoft YaHei', monospace; }}
        .content-box.highlight {{ background: #FFF7ED; border-color: #FED7AA; }}
        .content-box.correct-answer {{ background: #F0FDF4; border-color: #BBF7D0; color: #166534; }}
        /* Steps list */
        .steps-list {{ list-style: none; padding: 0; margin: 0; }}
        .steps-list li {{ padding: 10px 14px; margin-bottom: 4px; background: #F8FAFC; border-radius: 8px; border-left: 3px solid #3B82F6; font-size: 13px; line-height: 1.6; color: #334155; }}
        .steps-list li:nth-child(even) {{ background: #EFF6FF; }}
        .steps-list li .step-num {{ display: inline-block; min-width: 28px; font-weight: 700; color: #2563EB; }}
        /* Info grid */
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
        .info-item {{ background: #F8FAFC; border-radius: 8px; padding: 10px 14px; }}
        .info-item .info-label {{ font-size: 11px; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }}
        .info-item .info-value {{ font-size: 14px; font-weight: 600; color: #1E293B; }}
        .info-item.full {{ grid-column: 1 / -1; }}
        /* Tags */
        .detail-tag {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-right: 6px; }}
        .detail-tag.error {{ background: #FEF3C7; color: #92400E; }}
        .detail-tag.domain {{ background: #E0E7FF; color: #3730A3; }}
        /* Performance bar */
        .perf-bar {{ display: flex; gap: 12px; margin-top: 16px; padding: 14px 18px; background: linear-gradient(135deg, #F1F5F9 0%, #E2E8F0 100%); border-radius: 10px; }}
        .perf-item {{ flex: 1; text-align: center; }}
        .perf-item .perf-val {{ font-size: 18px; font-weight: 700; color: #1E293B; }}
        .perf-item .perf-label {{ font-size: 11px; color: #64748B; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Math Agent Evaluation Report</h1>
        <p class="subtitle">Generated at {now_str}</p>
        <div class="summary-cards">
            <div class="card"><div class="card-label">Total</div><div class="card-value">{summary['total']}</div></div>
            <div class="card"><div class="card-label">Correct</div><div class="card-value green">{summary['correct']}</div></div>
            <div class="card"><div class="card-label">Accuracy</div><div class="card-value {accuracy_class}">{summary['accuracy']}%</div></div>
            <div class="card"><div class="card-label">Avg Confidence</div><div class="card-value">{summary['avg_confidence']}</div></div>
            <div class="card"><div class="card-label">Avg Inf. Latency</div><div class="card-value">{summary['avg_inference_latency']}s</div></div>
            <div class="card"><div class="card-label">Avg Judge Latency</div><div class="card-value">{summary['avg_judge_latency']}s</div></div>
        </div>
        {domain_section}
        <h2 class="section-title">Detailed Results</h2>
        <table>
            <thead><tr><th>ID</th><th>Domain</th><th>Question</th><th>Answer</th><th>Status</th><th>Conf.</th><th>Error</th><th>Inf. Time</th><th>Judge Time</th><th>Tokens</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
"""

    # Modal overlay + JS (raw string to avoid Python escape warnings on JS regex)
    html += r"""
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
        // Tags
        if (tags) html += '<div style="margin-bottom:16px">' + tags + '</div>';

        // Info section
        html += '<div class="detail-section">';
        html += '<div class="section-heading info"><span class="icon-dot info"></span>&#39064;&#30446;&#20449;&#24687;</div>';
        html += '<div class="info-grid">';
        html += '<div class="info-item full"><div class="info-label">&#39064;&#24178;</div><div class="content-box" style="max-height:160px;font-family:inherit">' + esc(d.question) + '</div></div>';
        html += '<div class="info-item"><div class="info-label">&#21442;&#32771;&#31572;&#26696;</div><div class="content-box correct-answer" style="max-height:120px">' + esc(d.reference_answer || '&#26242;&#26080;') + '</div></div>';
        html += '<div class="info-item"><div class="info-label">AI &#26368;&#32456;&#31572;&#26696;</div><div class="content-box" style="max-height:120px">' + esc(d.intern_answer || '&#26242;&#26080;') + '</div></div>';
        if (d.inference_error) html += '<div class="info-item full"><div class="info-label">&#25512;&#29702;&#38169;&#35823;</div><div class="content-box highlight">' + esc(d.inference_error) + '</div></div>';
        if (d.judge_error) html += '<div class="info-item full"><div class="info-label">&#21028;&#39064;&#38169;&#35823;</div><div class="content-box highlight">' + esc(d.judge_error) + '</div></div>';
        html += '</div></div>';

        // AI reasoning section
        html += '<div class="detail-section">';
        html += '<div class="section-heading ai"><span class="icon-dot ai"></span>&#20070;&#29983;AI &#24605;&#32771;&#36807;&#31243;</div>';
        if (d.intern_reasoning) {
            html += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#23436;&#25972;&#25512;&#29702;&#36807;&#31243;</div>';
            html += '<div class="content-box">' + renderLatex(esc(d.intern_reasoning)) + '</div></div>';
        }
        if (d.intern_steps && d.intern_steps.length > 0) {
            html += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#20998;&#27493;&#25512;&#29702;</div>';
            html += stepsHtml;
            html += '</div>';
        }
        if (d.intern_verification) {
            html += '<div><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#33258;&#39564;&#35777;&#32467;&#35770;</div>';
            html += '<div class="content-box highlight">' + renderLatex(esc(d.intern_verification)) + '</div></div>';
        }
        if (!d.intern_reasoning && (!d.intern_steps || d.intern_steps.length === 0) && !d.intern_verification) {
            html += '<div style="color:#94A3B8;font-size:13px;padding:12px">&#26242;&#26080;AI&#25512;&#29702;&#25968;&#25454;</div>';
        }
        html += '</div>';

        // Judge analysis section
        html += '<div class="detail-section">';
        html += '<div class="section-heading judge"><span class="icon-dot judge"></span>DeepSeek &#21028;&#39064;&#20998;&#26512;</div>';
        if (d.judge_explanation) {
            html += '<div style="margin-bottom:12px"><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#21028;&#39064;&#35814;&#32454;&#35299;&#37322;</div>';
            html += '<div class="content-box">' + renderLatex(esc(d.judge_explanation)) + '</div></div>';
        }
        if (d.error_type) {
            html += '<div style="margin-bottom:12px"><span style="font-size:12px;color:#64748B;font-weight:600">&#38169;&#35823;&#31867;&#22411;: </span><span class="detail-tag error">' + esc(d.error_type) + '</span></div>';
        }
        if (d.correct_answer_judge) {
            html += '<div><div style="font-size:12px;color:#64748B;margin-bottom:4px;font-weight:600">&#21028;&#39064;&#32473;&#20986;&#30340;&#27491;&#30830;&#31572;&#26696;</div>';
            html += '<div class="content-box correct-answer">' + esc(d.correct_answer_judge) + '</div></div>';
        }
        if (!d.judge_explanation && !d.error_type && !d.correct_answer_judge) {
            html += '<div style="color:#94A3B8;font-size:13px;padding:12px">&#26242;&#26080;&#21028;&#39064;&#20998;&#26512;&#25968;&#25454;</div>';
        }
        html += '</div>';

        // Performance bar
        html += '<div class="perf-bar">';
        html += '<div class="perf-item"><div class="perf-val">' + d.inference_latency.toFixed(2) + 's</div><div class="perf-label">&#25512;&#29702;&#32791;&#26102;</div></div>';
        html += '<div class="perf-item"><div class="perf-val">' + d.judge_latency.toFixed(2) + 's</div><div class="perf-label">&#21028;&#39064;&#32791;&#26102;</div></div>';
        html += '<div class="perf-item"><div class="perf-val">' + (d.inference_tokens + d.judge_tokens) + '</div><div class="perf-label">&#24635; Token</div></div>';
        html += '</div>';

        body.innerHTML = html;
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        body.scrollTop = 0;
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
        // --- Display math: $...$ → render content ---
        s = s.replace(/\$([^$]+)\$/g, function(m, inner) {
            return _latexToReadable(inner.trim());
        });
        // --- Inline commands without $ wrapper ---
        s = s.replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '($1)/($2)');
        s = s.replace(/\\partial ([a-zA-Z])/g, '∂$1');
        s = s.replace(/\\ln /g, 'ln ');
        s = s.replace(/\\log /g, 'log ');
        s = s.replace(/\\sin /g, 'sin ');
        s = s.replace(/\\cos /g, 'cos ');
        s = s.replace(/\\tan /g, 'tan ');
        s = s.replace(/\\cdot /g, '·');
        s = s.replace(/\\times /g, '×');
        s = s.replace(/\\div /g, '÷');
        s = s.replace(/\\pm /g, '±');
        s = s.replace(/\\leq ?/g, '≤');
        s = s.replace(/\\geq ?/g, '≥');
        s = s.replace(/\\neq ?/g, '≠');
        s = s.replace(/\\approx ?/g, '≈');
        s = s.replace(/\\infty/g, '∞');
        s = s.replace(/\\sum/g, '∑');
        s = s.replace(/\\int/g, '∫');
        s = s.replace(/\\sqrt\{([^}]*)\}/g, '√($1)');
        s = s.replace(/\^(\{([^}]*)\}|(.))/g, function(m, g1, g2, g3) { return '^' + (g2 || g3 || ''); });
        s = s.replace(/_(\{([^}]*)\}|(.))/g, function(m, g1, g2, g3) { return '_' + (g2 || g3 || ''); });
        s = s.replace(/\\left/g, '');
        s = s.replace(/\\right/g, '');
        s = s.replace(/\\[a-zA-Z]+/g, ''); // remove remaining unknown commands
        return s;
    }

    // Core LaTeX expression renderer for content inside $...$
    function _latexToReadable(expr) {
        var s = expr;
        // Fractions
        s = s.replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '($1)/($2)');
        // Subscripts and superscripts with braces
        s = s.replace(/\^\{([^}]*)\}/g, '^($1)');
        s = s.replace(/_\{([^}]*)\}/g, '_($1)');
        // Naked ^ and _
        s = s.replace(/\^(\w)/g, '^$1');
        s = s.replace(/_(\w)/g, '_$1');
        // Greek letters
        s = s.replace(/\\alpha/g, 'α'); s = s.replace(/\\beta/g, 'β'); s = s.replace(/\\gamma/g, 'γ');
        s = s.replace(/\\delta/g, 'δ'); s = s.replace(/\\epsilon/g, 'ε'); s = s.replace(/\\theta/g, 'θ');
        s = s.replace(/\\lambda/g, 'λ'); s = s.replace(/\\pi/g, 'π'); s = s.replace(/\\sigma/g, 'σ');
        s = s.replace(/\\phi/g, 'φ'); s = s.replace(/\\omega/g, 'ω'); s = s.replace(/\\rho/g, 'ρ');
        // Operators & symbols
        s = s.replace(/\\partial/g, '∂');
        s = s.replace(/\\nabla/g, '∇');
        s = s.replace(/\\ln(?![a-zA-Z])/g, 'ln');
        s = s.replace(/\\log(?![a-zA-Z])/g, 'log');
        s = s.replace(/\\sin(?![a-zA-Z])/g, 'sin');
        s = s.replace(/\\cos(?![a-zA-Z])/g, 'cos');
        s = s.replace(/\\tan(?![a-zA-Z])/g, 'tan');
        s = s.replace(/\\cdot/g, '·');
        s = s.replace(/\\times/g, '×');
        s = s.replace(/\\div/g, '÷');
        s = s.replace(/\\pm/g, '±');
        s = s.replace(/\\leq/g, '≤');
        s = s.replace(/\\geq/g, '≥');
        s = s.replace(/\\neq/g, '≠');
        s = s.replace(/\\approx/g, '≈');
        s = s.replace(/\\infty/g, '∞');
        s = s.replace(/\\sum/g, '∑');
        s = s.replace(/\\int/g, '∫');
        s = s.replace(/\\sqrt\{([^}]*)\}/g, '√($1)');
        s = s.replace(/\\sqrt([a-zA-Z0-9])/g, '√$1');
        s = s.replace(/\\left/g, '');
        s = s.replace(/\\right/g, '');
        s = s.replace(/\\,[ ]*/g, ', ');  // thin space
        s = s.replace(/\\;[ ]*/g, '  ');   // thick space
        s = s.replace(/\\[a-zA-Z]+/g, '');   // strip remaining commands
        return s;
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            hideDetail({target: document.getElementById('modalOverlay')});
        }
    });
    </script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"HTML report saved to {output_path}")
    return output_path
