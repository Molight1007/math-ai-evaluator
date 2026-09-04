# -*- coding: utf-8 -*-
"""报告输出：raw.jsonl + per_item.csv + summary.json + report.md。"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from record import Record


def _md_table(rows: list[dict], headers: list[tuple[str, str]]) -> str:
    """生成 Markdown 表格。headers 为 (键, 表头) 列表。"""
    if not rows:
        return "_（无数据）_\n"
    out = ["| " + " | ".join(h for _, h in headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        cells = []
        for k, _ in headers:
            v = r.get(k, "")
            if isinstance(v, (list, tuple)):
                v = "、".join(str(x) for x in v)
            cells.append(str(v).replace("|", "/"))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def write_jsonl(path: Path, records: list[Record]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def write_csv(path: Path, records: list[Record]) -> None:
    rows = [r.to_row() for r in records]
    if not rows:
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    # utf-8-sig：Excel 直接打开不乱码
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_report(
    outdir: Path,
    records: list[Record],
    summary: dict,
    meta: dict,
) -> Path:
    path = outdir / "report.md"
    L: list[str] = []

    L.append("# LLM 数学认知探针 · 实验报告\n")
    L.append(f"- 运行时间：{meta.get('time','')}")
    L.append(f"- 模型：**{meta.get('model','')}**（{meta.get('model_label','')}）")
    L.append(f"- 运行模式：{meta.get('mode','')}")
    L.append(f"- 题量：{summary.get('total',0)} 条记录（{summary.get('counts',{})}）")
    L.append(f"- API 错误：{summary.get('errors',0)} 条；截断：{summary.get('truncated',0)} 条")
    L.append(f"- Lean 环境：{meta.get('lean_status','')}")
    L.append(f"- 整体 Lean 验证通过率：{summary.get('lean_ok_rate_all',0)}")
    L.append(f"- 平均单题耗时：{summary.get('mean_elapsed',0)} s\n")

    L.append("> 判据说明：所有「正确」指 **Lean 4 编译器接受该形式化证明**"
             "（无 error、无 sorry），而非 LLM 自评。\n")

    # ---------------- A
    if "A" in summary:
        a = summary["A"]
        ag = a["aggregate"]
        L.append("\n## 探针 A：同构迁移（测「联想」能否发生）\n")
        L.append("**核心指标解读**\n")
        L.append("- `迁移增益` = 做过源题后目标题正确率 − 无源题基线正确率"
                 "（>0 即迁移确实发生了）")
        L.append("- `核心迁移率` = 目标题证明指纹 ∩ 共享结构核心 ÷ 共享结构核心"
                 "（**直接量化「方法有没有搬过去」**，本实验最原创的量）")
        L.append("- `方法继承率` = 目标题指纹 ∩ 源题指纹 ÷ 源题指纹\n")
        L.append("### 汇总\n")
        L.append("| 指标 | 数值 |\n|---|---|")
        for k, v in ag.items():
            L.append(f"| {k} | {v} |")
        L.append("")
        L.append("### 逐题对\n")
        L.append(_md_table(a["per_pair"], [
            ("pid", "题对"), ("kind", "迁移类型"), ("core", "共享结构核心"),
            ("source_ok", "源题✓"), ("with_ok", "带源题✓"), ("base_ok", "基线✓"),
            ("transfer_gain", "迁移增益"),
            ("core_cov_with", "核心迁移(带)"), ("core_cov_base", "核心迁移(基线)"),
            ("inherit_with", "继承(带)"), ("inherit_base", "继承(基线)"),
        ]))

    # ---------------- B
    if "B" in summary:
        b = summary["B"]
        L.append("\n## 探针 B：陷阱题（测类比是否用错地方）\n")
        L.append("`escaped`=识破陷阱给出正解；`trapped`=被表层模板骗；"
                 "`mixed`=两种标记都出现（需人工复核）；`other`=未匹配到任何标记。\n")
        L.append("### 汇总\n")
        L.append("| 指标 | 数值 |\n|---|---|")
        for k, v in b["aggregate"].items():
            L.append(f"| {k} | {v} |")
        L.append("")
        L.append("### 逐题\n")
        L.append(_md_table(b["per_item"], [
            ("tid", "题号"), ("label", "判定"), ("escaped", "识破"),
            ("trapped", "被套路"), ("has_lean", "有Lean判据"), ("lean_ok", "Lean✓"),
            ("gold_answer", "标准答案"),
        ]))

    # ---------------- C
    if "C" in summary:
        c = summary["C"]
        L.append("\n## 探针 C：结构指认（元认知）\n")
        L.append("- 正向：解完题后指认所用结构（可以靠「背名词」蒙对，故必须配合反向任务）")
        L.append("- 反向：**给结构名 → 造最小可编译 Lean 示例**"
                 "（能命名 ≠ 能构造，这是硬判据）\n")
        L.append("### 汇总\n")
        L.append("| 指标 | 数值 |\n|---|---|")
        for k, v in c["aggregate"].items():
            L.append(f"| {k} | {v} |")
        L.append("")
        L.append("### 逐题\n")
        L.append(_md_table(c["per_item"], [
            ("sid", "题号"), ("task", "任务"),
            ("gold", "标注结构"), ("pick", "模型选择"), ("correct", "正确"),
            ("structure", "结构名"), ("family_hit", "结构命中"),
            ("lean_ok", "Lean✓"), ("fingerprint", "指纹"),
        ]))

    # ---------------- D
    if "D" in summary:
        d = summary["D"]
        L.append("\n## 探针 D：抽象 ⇄ 实例化\n")
        L.append("### 汇总\n")
        L.append("| 指标 | 数值 |\n|---|---|")
        for k, v in d["aggregate"].items():
            L.append(f"| {k} | {v} |")
        L.append("")
        L.append("### 逐题\n")
        L.append(_md_table(d["per_item"], [
            ("aid", "题号"), ("direction", "方向"), ("pattern_hit", "抽象命中"),
            ("lean_ok", "Lean✓"), ("gold", "标准答案"),
        ]))

    # ---------------- 局限
    L.append("\n## 结果解读须知（诚实声明）\n")
    L.append("1. **样本量**：当前题库规模小（A 3 对 / B 3 题 / C 6+4 / D 3），"
             "单轮结果只能作**定性信号**，不能作统计结论。")
    L.append("2. **随机性**：老师指出「大模型推理中会随机出现」错误。"
             "正式结论需 `--repeat N` 多轮采样后报告均值与方差。")
    L.append("3. **判据边界**：Lean 判「形式化证明是否成立」，不判「数学洞见是否优雅」。"
             "模型可能写出编译通过但结构笨拙的证明，需结合指纹人工复核。")
    L.append("4. **模型差异**：本框架为多模型可插拔，跨模型对比才谈得上"
             "「LLM 是否有联想能力」这一一般性结论。\n")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


def save_all(
    outdir: Path,
    records: list[Record],
    summary: dict,
    meta: dict,
) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    p_jsonl = outdir / "raw.jsonl"
    p_csv = outdir / "per_item.csv"
    p_sum = outdir / "summary.json"
    write_jsonl(p_jsonl, records)
    write_csv(p_csv, records)
    p_sum.write_text(
        json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    p_report = write_report(outdir, records, summary, meta)
    return {
        "raw": p_jsonl,
        "csv": p_csv,
        "summary": p_sum,
        "report": p_report,
    }


def new_outdir(tag: str = "") -> Path:
    from config import RESULTS_DIR
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"{stamp}_{tag}" if tag else stamp
    p = RESULTS_DIR / name
    p.mkdir(parents=True, exist_ok=True)
    return p
