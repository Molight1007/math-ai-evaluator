# -*- coding: utf-8 -*-
"""doc-typeset：Markdown → business-report HTML（填充模板占位符）。"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"C:\Users\35174\.workbuddy\plugins\cache\workbuddy-builtin\tencent-docx\5.5.6-wb.38337834.g5f969292.h4918b5ced607\skills\doc-typeset"
BASE = r"D:\挑战杯\output\20260915-cuoti-guiyin"

md = io.open(os.path.join(BASE, "stage1", "final_draft.md"), encoding="utf-8").read()
tpl = io.open(os.path.join(ROOT, "templates", "business-report.html"), encoding="utf-8").read()

# ---------- 1) Markdown → HTML ----------
def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def inline(s):
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s

lines = md.split("\n")
out, i = [], 0
h2n = 0
while i < len(lines):
    ln = lines[i].rstrip()
    if not ln.strip():
        i += 1
        continue
    # 表格
    if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
        head = [c.strip() for c in ln.strip("|").split("|")]
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            rows.append([c.strip() for c in lines[i].strip("|").split("|")])
            i += 1
        t = ['<table class="doc-table"><thead><tr>']
        t += ["<th>%s</th>" % inline(c) for c in head]
        t.append("</tr></thead><tbody>")
        for r in rows:
            t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
        t.append("</tbody></table>")
        out.append("".join(t))
        continue
    # 标题
    if ln.startswith("### "):
        out.append("<h3>%s</h3>" % inline(ln[4:]))
        i += 1
        continue
    if ln.startswith("## "):
        h2n += 1
        out.append('<h2 id="sec%d">%s</h2>' % (h2n, inline(ln[3:])))
        i += 1
        continue
    if ln.startswith("# "):
        i += 1  # 文档标题已作封面标题
        continue
    # 列表
    if re.match(r"^\s*[-*]\s+", ln):
        items = []
        while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i].rstrip()):
            items.append(re.sub(r"^\s*[-*]\s+", "", lines[i].rstrip()))
            i += 1
        out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in items) + "</ul>")
        continue
    if re.match(r"^\s*\d+\.\s+", ln):
        items = []
        while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i].rstrip()):
            items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i].rstrip()))
            i += 1
        out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in items) + "</ol>")
        continue
    out.append("<p>%s</p>" % inline(ln))
    i += 1

body_html = "\n".join(out)

# 重点数据标红（用 data-emphasis，引用 CSS 变量，不写裸值）
def mark_key(m):
    return '<span class="data-emphasis">%s</span>' % m.group(0)

body_html = re.sub(r"\*\*(\d[\d,\.]*\s*(?:%|题|秒|倍)?)\*\*", mark_key, body_html)

# ---------- 2) 目录 ----------
toc = "\n".join(
    '<li><a href="#sec%d">%s</a></li>' % (n + 1, t.replace("## ", ""))
    for n, t in enumerate(re.findall(r"^## .+$", md, re.M))
)

# ---------- 3) 执行摘要 data-cards ----------
cards = [
    ("计算执行错误", "4.2%", "仅 2 / 48 题"),
    ("思路 / 建模错误", "43.8%", "21 / 48 题"),
    ("计数 / 枚举错误", "29.2%", "14 / 48 题"),
    ("对题 vs 错题耗时", "946 / 992s", "几乎相同"),
]
cards_html = "\n".join(
    '<div data-component="data-card" data-title="%s">'
    '<span class="card-value">%s</span>'
    '<span class="card-unit">%s</span></div>' % (t, v, u)
    for t, v, u in cards
)

summary_text = """
<p>本报告对全量 112 道测试题中 89 道错题做了错误机理归因。核心发现是：<strong>推理与思维层面的错误是主体，计算几乎不是瓶颈</strong>——真正的计算执行错误仅占 <span class="data-emphasis">4.2%</span>，而思路／建模错误占 <span class="data-emphasis">43.8%</span>。</p>
<p>进一步把"计数类错误"细分后可见：<strong>数学结构选错的占 60%，"结构对了、数错了"仅占 40%</strong>，说明多数错误发生在"把问题转化成数学模型"这一步。</p>
<p>此外，数据显示<strong>方向错误并不会带来明显的额外耗时</strong>（对题与错题耗时分别为 946 秒与 992 秒，相差约 5%），模型表现为沿错误方向一致地推导到结束，而非卡住空转。</p>
<p>据此建议：<strong>优先攻克可工程化的"技巧类"问题</strong>（占 56.2%），"方向类"问题（43.8%）作为中期课题。</p>
"""

# ---------- 4) 填充模板 ----------
html = tpl
rep = {
    "{{report_title}}": "MathPilot 错题错误类型归因分析报告",
    "{{report_subtitle}}": "基于 89 道错题的三维机理分解与改进方向建议",
    "{{report_category}}": "技术分析报告",
    "{{org_name}}": "MathPilot 项目组",
    "{{report_date}}": "2026 年 9 月 15 日",
    "{{report_version}}": "v1.0",
    "{{toc_items}}": toc,
    "{{summary_data_cards}}": cards_html,
    "{{summary_text}}": summary_text,
    "{{report_content}}": body_html,
    "{{appendix_content}}": "<h2>附录：数据来源</h2><p>全量跑批结果记录与错题攻克台账（2026-09-13 版）；逐题归因明细见配套表格文件。</p>",
}
for k, v in rep.items():
    html = html.replace(k, v)

left = re.findall(r"\{\{[^}]+\}\}", html)
print("剩余未替换占位符:", left if left else "无 ✓")

outp = os.path.join(BASE, "stage2", "formatted-错题归因分析.html")
os.makedirs(os.path.dirname(outp), exist_ok=True)
io.open(outp, "w", encoding="utf-8").write(html)
print("HTML 已写:", outp, "| 大小: %.0f KB" % (os.path.getsize(outp) / 1024))
print("表格数:", html.count("<table"), "| H2 数:", html.count("<h2"), "| data-card:", html.count("data-card"))
