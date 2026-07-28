"""
从评测 JSON 提取判错题目，生成 HTML 判错列表表格。

用法：
    python _gen_error_table.py <json_path> [output_path]
    若不提供 output_path，默认输出到 json_path 同目录下的 error_analysis_list.html
"""
import argparse
import json
import os
import sys

from utils import escape_html

# 错误类型中文映射
ERROR_MAP = {
    "incomplete": "解答不完整",
    "logic_error": "逻辑错误",
    "calculation_error": "计算错误",
    "other": "其他错误",
    None: "未分类",
}


def _esc(s: str) -> str:
    """对 HTML 特殊字符进行转义，防止 XSS。

    委托给统一的 escape_html，补上此前遗漏的 & 转义（代码要求 1.2）。
    """
    return escape_html(s)


def _build_error_bars(summary: dict, errors: list) -> str:
    """构建错误类型分布柱状图的 HTML"""
    bar_html = ""
    for etype, count in summary["error_types"].items():
        pct = round(count / len(errors) * 100)
        label = ERROR_MAP.get(etype, etype)
        bar_html += (
            f'<div class="error-bar-item"><span class="bar-label">{label}</span>'
            f'<span class="bar-outer"><span class="bar-inner {etype}" style="width:{pct}%">{count}</span></span>'
            f'<span class="bar-count">{pct}%</span></div>\n'
        )
    return bar_html


def _build_table_rows(errors: list) -> str:
    """构建错误题目表格行的 HTML"""
    rows_html = ""
    for i, e in enumerate(errors):
        pid = _esc(e["problem_id"])
        domain = e.get("domain") or "未知"
        question = _esc(e.get("question", ""))
        answer = _esc(e.get("intern_answer", ""))[:200]
        reasoning = _esc(e.get("intern_reasoning", ""))[:250]
        explanation = _esc(e.get("judge_explanation", ""))[:300]
        error_type = e.get("error_type")
        conf = e.get("confidence", 0)
        inf_lat = e.get("inference_latency", 0)
        judge_lat = e.get("judge_latency", 0)

        dcls = "d-unknown" if domain == "未知" else ""
        etype_css = error_type or "other"
        etype_label = ERROR_MAP.get(error_type, error_type or "未分类")
        conf_cls = "conf-high" if conf >= 0.8 else "conf-low"

        rows_html += (
            f"<tr>\n"
            f'<td class="num">{i + 1}</td>\n'
            f'<td class="id-cell">{pid}</td>\n'
            f'<td><span class="domain-tag {dcls}">{domain}</span></td>\n'
            f'<td class="question-text">{question}</td>\n'
            f'<td class="answer-text">{answer[:150]}</td>\n'
            f'<td class="reasoning-text" title="{reasoning}">{reasoning}</td>\n'
            f'<td class="explanation-text">{explanation}</td>\n'
            f'<td><span class="error-tag et-{etype_css}">{etype_label}</span></td>\n'
            f'<td><span class="conf-badge {conf_cls}">{conf:.2f}</span></td>\n'
            f'<td class="latency-cell">{inf_lat}s</td>\n'
            f'<td class="latency-cell">{judge_lat}s</td>\n'
            f"</tr>\n"
        )
    return rows_html


def generate_error_table(json_path: str, output_path: str) -> int:
    """从评测 JSON 生成 HTML 判错列表，返回错误题目数"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data["summary"]
    errors = [r for r in data["results"] if not r["is_correct"]]

    bar_html = _build_error_bars(summary, errors)
    rows_html = _build_table_rows(errors)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Intern-S1 评测判错列表 - {len(errors)}题</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:#f5f7fa; color:#333; padding:20px; }}
.container {{ max-width:1400px; margin:0 auto; }}

.header {{ background:linear-gradient(135deg,#667eea,#764ba2); border-radius:16px; padding:32px; margin-bottom:24px; color:white; text-align:center; }}
.header h1 {{ font-size:28px; margin-bottom:12px; }}
.header .meta {{ font-size:14px; opacity:0.85; }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:24px; }}
.stat-card {{ background:white; border-radius:12px; padding:20px; text-align:center; box-shadow:0 2px 8px rgba(0,0,0,0.06); transition:transform .2s; }}
.stat-card:hover {{ transform:translateY(-2px); }}
.stat-card .value {{ font-size:36px; font-weight:700; margin-bottom:4px; }}
.stat-card .label {{ font-size:14px; color:#666; }}
.stat-card.total .value {{ color:#3b82f6; }}  .stat-card.correct .value {{ color:#10b981; }}
.stat-card.wrong .value {{ color:#ef4444; }}   .stat-card.accuracy .value {{ color:#f59e0b; }}

.error-dist {{ background:white; border-radius:12px; padding:20px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
.error-dist h2 {{ font-size:18px; margin-bottom:16px; padding-bottom:12px; border-bottom:2px solid #f0f0f0; }}
.error-bars {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; }}
.error-bar-item {{ display:flex; align-items:center; gap:8px; font-size:14px; }}
.bar-label {{ min-width:90px; }}
.bar-outer {{ width:200px; height:22px; background:#e9ecef; border-radius:11px; overflow:hidden; position:relative; }}
.bar-inner {{ height:100%; border-radius:11px; display:flex; align-items:center; justify-content:center; font-size:12px; color:white; font-weight:600; transition:width .6s ease; }}
.bar-inner.incomplete {{ background:linear-gradient(135deg,#f97316,#ea580c); }}
.bar-inner.logic_error {{ background:linear-gradient(135deg,#8b5cf6,#7c3aed); }}
.bar-inner.calculation_error {{ background:linear-gradient(135deg,#ec4899,#db2777); }}
.bar-inner.other {{ background:linear-gradient(135deg,#64748b,#475569); }}
.bar-count {{ font-weight:700; min-width:30px; text-align:right; }}

.table-section {{ background:white; border-radius:12px; padding:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); overflow-x:auto; }}
.table-section h2 {{ font-size:18px; margin-bottom:16px; padding-bottom:12px; border-bottom:2px solid #f0f0f0; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
thead th {{ background:#f8fafc; padding:12px 10px; text-align:left; font-weight:600; color:#475569; border-bottom:2px solid #e2e8f0; position:sticky; top:0; white-space:nowrap; }}
tbody tr:hover {{ background:#f8fafc; }}
tbody td {{ padding:10px 8px; border-bottom:1px solid #f1f5f9; vertical-align:top; line-height:1.5; }}
.num {{ font-weight:600; color:#94a3b8; width:36px; }}
.id-cell {{ font-family:monospace; color:#0369a1; font-size:11.5px; max-width:220px; word-break:break-all; }}
.domain-tag {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:500; }}
.domain-tag.d-unknown {{ background:#fef3c7; color:#92400e; }}
.question-text {{ max-width:320px; color:#374151; word-break:break-word; }}
.answer-text {{ max-width:220px; color:#059669; font-weight:500; word-break:break-word; }}
.reasoning-text {{ max-width:280px; color:#6b7280; font-size:11.5px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; }}
.explanation-text {{ max-width:280px; color:#dc2626; font-size:11.5px; }}
.error-tag {{ display:inline-block; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; white-space:nowrap; }}
.error-tag.et-incomplete {{ background:#ffedd5; color:#c2410c; }}
.error-tag.et-logic {{ background:#ede9fe; color:#6d28d9; }}
.error-tag.et-calc {{ background:#fce7f3; color:#be185d; }}
.error-tag.et-other {{ background:#f1f5f9; color:#475569; }}
.conf-badge {{ display:inline-block; padding:2px 8px; border-radius:8px; font-size:12px; font-weight:600; }}
.conf-high {{ background:#d1fae5; color:#065f46; }}
.conf-low {{ background:#fee2e2; color:#991b1b; }}
.latency-cell {{ font-variant-numeric:tabular-nums; color:#6b7280; white-space:nowrap; }}

.footer {{ text-align:center; margin-top:24px; padding:16px; color:#94a3b8; font-size:13px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
<h1>Intern-S1 数学推理评测 — 判错列表</h1>
<div class="meta">基于 {summary["total"]} 道数学题目的评测结果 | 生成时间: {data.get("generated_at", "")}</div>
</div>

<div class="stats">
<div class="stat-card total"><div class="value">{summary["total"]}</div><div class="label">总题数</div></div>
<div class="stat-card correct"><div class="value">{summary["correct"]}</div><div class="label">正确数</div></div>
<div class="stat-card wrong"><div class="value">{len(errors)}</div><div class="label">错误数</div></div>
<div class="stat-card accuracy"><div class="value">{summary["accuracy"]}%</div><div class="label">准确率</div></div>
</div>

<div class="error-dist">
<h2>错误类型分布（共 {len(errors)} 题）</h2>
<div class="error-bars">
{bar_html}
</div>
</div>

<div class="table-section">
<h2>详细判错列表</h2>
<table>
<thead>
<tr><th>#</th><th>题目ID</th><th>领域</th><th>题目内容</th><th>模型答案</th><th>推理摘要</th><th>评判解释</th><th>错误类型</th><th>置信度</th><th>推理耗时</th><th>评判耗时</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>

<div class="footer"><p>数据来源：{os.path.basename(json_path)} | Intern-S1 推理 + DeepSeek 评判 | 不推送到 GitHub</p></div>

</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return len(errors)


def main() -> None:
    """命令行入口：解析参数 → 生成 HTML 判错列表"""
    parser = argparse.ArgumentParser(
        description="从评测 JSON 提取判错题目，生成 HTML 判错列表表格"
    )
    parser.add_argument("json_path", help="评测 JSON 文件路径")
    parser.add_argument(
        "output_path", nargs="?", default=None,
        help="输出 HTML 路径（默认输出到 JSON 同目录下的 error_analysis_list.html）"
    )
    args = parser.parse_args()

    if not os.path.isfile(args.json_path):
        print(f"错误: 文件不存在 — {args.json_path}", file=sys.stderr)
        sys.exit(1)

    if args.output_path is None:
        json_dir = os.path.dirname(os.path.abspath(args.json_path))
        args.output_path = os.path.join(json_dir, "error_analysis_list.html")

    error_count = generate_error_table(args.json_path, args.output_path)
    print(f"完成！已生成包含 {error_count} 道错题的判错列表 → {args.output_path}")


if __name__ == "__main__":
    main()
