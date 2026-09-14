# -*- coding: utf-8 -*-
"""指标汇总：把 Record 列表压成论文可直接引用的数字。"""
from __future__ import annotations

from collections import defaultdict

from record import Record


def _mean(xs: list[float]) -> float:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def _rate(xs: list[int]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


# ---------------------------------------------------------------- A 组
def summarize_A(recs: list[Record]) -> dict:
    by_pid: dict[str, dict[str, Record]] = defaultdict(dict)
    for r in recs:
        by_pid[r.item_id][r.variant] = r

    per_pair: list[dict] = []
    for pid, d in by_pid.items():
        src = d.get("source")
        tw = d.get("target_with_source")
        tb = d.get("target_baseline")

        def ok(r: Record | None) -> int:
            return int(r.lean_ok) if r else 0

        def mv(r: Record | None, k: str) -> float:
            return float((r.metrics.get(k) if r else 0) or 0)

        per_pair.append({
            "pid": pid,
            "kind": (src.metrics.get("kind") if src else ""),
            "core": (src.metrics.get("core") if src else ""),
            "source_ok": ok(src),
            "with_ok": ok(tw),
            "base_ok": ok(tb),
            # 迁移增益：做过源题后，目标题正确率的提升
            "transfer_gain": ok(tw) - ok(tb),
            # 核心结构迁移率：目标题证明是否用上了共享结构
            "core_cov_with": mv(tw, "core_coverage"),
            "core_cov_base": mv(tb, "core_coverage"),
            "core_cov_delta": round(
                mv(tw, "core_coverage") - mv(tb, "core_coverage"), 3),
            # 方法继承率：目标题沿用源题方法的比例
            "inherit_with": mv(tw, "src_tgt_inherit"),
            "inherit_base": mv(tb, "src_tgt_inherit"),
            "jaccard_with": mv(tw, "src_tgt_jaccard"),
            "jaccard_base": mv(tb, "src_tgt_jaccard"),
        })

    agg = {
        "source_correct_rate": _rate([p["source_ok"] for p in per_pair]),
        "with_source_correct_rate": _rate([p["with_ok"] for p in per_pair]),
        "baseline_correct_rate": _rate([p["base_ok"] for p in per_pair]),
        "mean_transfer_gain": _mean([p["transfer_gain"] for p in per_pair]),
        "mean_core_cov_with": _mean([p["core_cov_with"] for p in per_pair]),
        "mean_core_cov_base": _mean([p["core_cov_base"] for p in per_pair]),
        "mean_core_cov_delta": _mean([p["core_cov_delta"] for p in per_pair]),
        "mean_inherit_with": _mean([p["inherit_with"] for p in per_pair]),
        "mean_inherit_base": _mean([p["inherit_base"] for p in per_pair]),
    }
    return {"per_pair": per_pair, "aggregate": agg}


# ---------------------------------------------------------------- B 组
def summarize_B(recs: list[Record]) -> dict:
    per_item = []
    for r in recs:
        per_item.append({
            "tid": r.item_id,
            "label": r.metrics.get("label", ""),
            "escaped": r.metrics.get("escaped", 0),
            "trapped": r.metrics.get("trapped", 0),
            "lean_ok": int(r.lean_ok),
            "gold_answer": r.metrics.get("gold_answer", ""),
            "trap_hits": r.metrics.get("trap_hits", []),
            "gold_hits": r.metrics.get("gold_hits", []),
            "has_lean": r.metrics.get("has_lean", 1),
        })
    labels = [p["label"] for p in per_item]
    # 组合/分析类陷阱题无 Lean 判据，统计 Lean 指标时必须排除，否则会人为拉低通过率
    lean_items = [p for p in per_item if p["has_lean"]]
    n_lean = len(lean_items) or 1
    agg = {
        "n_items": len(per_item),
        "n_with_lean": len(lean_items),
        "escaped_rate": _rate([p["escaped"] for p in per_item]),
        "trapped_rate": _rate([p["trapped"] for p in per_item]),
        "mixed_count": labels.count("mixed"),
        "other_count": labels.count("other"),
        "lean_ok_rate": _rate([p["lean_ok"] for p in lean_items]),
        # 关键交叉指标：识破了陷阱，但拿不出形式化验证 = "说对了但没证出来"
        "escaped_and_lean_ok": sum(
            1 for p in lean_items if p["escaped"] and p["lean_ok"]) / n_lean,
    }
    return {"per_item": per_item, "aggregate": agg}


# ---------------------------------------------------------------- C 组
def summarize_C(recs: list[Record]) -> dict:
    art = [r for r in recs if r.metrics.get("task") == "articulate"]
    rev = [r for r in recs if r.metrics.get("task") == "reverse_lean"]

    per_item = [{
        "sid": r.item_id,
        "task": "articulate",
        "gold": r.metrics.get("gold", ""),
        "pick": r.metrics.get("pick", ""),
        "correct": r.metrics.get("correct", 0),
        "ambiguous": r.metrics.get("ambiguous", 0),
    } for r in art]
    per_item += [{
        "sid": r.item_id,
        "task": "reverse_lean",
        "structure": r.metrics.get("structure", ""),
        "family_hit": r.metrics.get("family_hit", 0),
        "lean_ok": int(r.lean_ok),
        "fingerprint": r.fingerprint,
    } for r in rev]

    # 随机基线：12 个选项盲猜
    random_baseline = round(1 / 12, 3) if art else 0.0
    agg = {
        "articulate_n": len(art),
        "articulate_accuracy": _rate([r.metrics.get("correct", 0) for r in art]),
        "random_baseline": random_baseline,
        "articulate_ambiguous": sum(
            r.metrics.get("ambiguous", 0) for r in art),
        "reverse_n": len(rev),
        # 反向任务的"结构命中率"：是否真的用上了该结构对应的 tactic/引理
        "reverse_family_hit_rate": _rate(
            [r.metrics.get("family_hit", 0) for r in rev]),
        # 反向任务的"编译通过率"：构造出来的东西是否真的成立
        "reverse_lean_ok_rate": _rate([int(r.lean_ok) for r in rev]),
    }
    return {"per_item": per_item, "aggregate": agg}


# ---------------------------------------------------------------- D 组
def summarize_D(recs: list[Record]) -> dict:
    per_item = [{
        "aid": r.item_id,
        "direction": r.metrics.get("direction", ""),
        "pattern_hit": r.metrics.get("pattern_hit", 0),
        "lean_ok": int(r.lean_ok),
        "gold": r.metrics.get("gold", ""),
    } for r in recs]
    agg = {
        "n_items": len(recs),
        "abstraction_hit_rate": _rate(
            [r.metrics.get("pattern_hit", 0) for r in recs]),
        "lean_ok_rate": _rate([int(r.lean_ok) for r in recs]),
        # 最强判据：抽象正确 **且** Lean 验证通过
        "both_ok_rate": _rate([
            int(r.metrics.get("pattern_hit", 0) and r.lean_ok) for r in recs
        ]),
    }
    return {"per_item": per_item, "aggregate": agg}


# ---------------------------------------------------------------- E 组
def summarize_E(recs: list[Record]) -> dict:
    """E 组：定理陈述完整性。

    两个判据分开统计，避免"无 Lean 判据的题"人为拉低 Lean 通过率：
      - condition_completeness：文本条件完整率（全部 E 题都算）
      - lean_*：只在 has_lean 的题上算
    另按 dimension 分子维度看，定位模型到底漏哪一类条件。
    """
    per_item: list[dict] = []
    for r in recs:
        m = r.metrics
        per_item.append({
            "eid": r.item_id,
            "theorem": m.get("theorem", ""),
            "dimension": m.get("dimension", ""),
            "n_cond": len(m.get("key_conditions", [])),
            "n_hit": sum(m.get("cond_hits", [])),
            "completeness": m.get("condition_completeness", 0.0),
            "full": m.get("full_conditions", 0),
            "missing": m.get("missing_conditions", []),
            "has_lean": m.get("has_lean", 0),
            "lean_ok": m.get("lean_ok", 0),
            "both_pass": m.get("both_pass", 0),
        })

    lean_items = [p for p in per_item if p["has_lean"]]
    n_lean = len(lean_items) or 1

    # 按子维度聚合：定位"漏的是哪一类条件"
    by_dim: dict[str, list[dict]] = defaultdict(list)
    for p in per_item:
        by_dim[p["dimension"] or "未标注"].append(p)

    agg = {
        "n_items": len(per_item),
        "n_with_lean": len(lean_items),
        # ① 文本条件完整率：平均每条定理说出了多少比例的关键条件
        "condition_completeness_rate": _mean(
            [p["completeness"] for p in per_item]),
        # ② 完全陈述率：一条条件都没漏的比例（最严格）
        "full_statement_rate": _rate([p["full"] for p in per_item]),
        # ③ Lean 特例编译率（只在有判据的题上统计）
        "lean_special_ok_rate": _rate([p["lean_ok"] for p in lean_items]),
        # ④ 双通过率：条件说全 **且** 特例编译过（无判据题只看条件）
        "both_pass_rate": _rate([p["both_pass"] for p in per_item]),
    }
    by_dim_out = {
        dim: {
            "n": len(v),
            "completeness": _mean([p["completeness"] for p in v]),
            "full_rate": _rate([p["full"] for p in v]),
        }
        for dim, v in sorted(by_dim.items())
    }
    return {"per_item": per_item, "by_dimension": by_dim_out, "aggregate": agg}


def summarize_all(records: list[Record]) -> dict:
    by_probe: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by_probe[r.probe].append(r)

    # 整体 Lean 通过率只统计**真正走过编译器**的记录，
    # 否则无判据的题（组合/分析/纯陈述）会被算成 0 而人为拉低数字。
    checked = [r for r in records if r.lean_checked]
    out = {
        "counts": {k: len(v) for k, v in sorted(by_probe.items())},
        "total": len(records),
        "errors": sum(1 for r in records if r.error),
        "truncated": sum(1 for r in records if r.truncated),
        "lean_checked": len(checked),
        "lean_ok_rate_all": _rate([int(r.lean_ok) for r in checked]),
        "mean_elapsed": _mean([r.elapsed for r in records]),
    }
    if by_probe.get("A"):
        out["A"] = summarize_A(by_probe["A"])
    if by_probe.get("B"):
        out["B"] = summarize_B(by_probe["B"])
    if by_probe.get("C"):
        out["C"] = summarize_C(by_probe["C"])
    if by_probe.get("D"):
        out["D"] = summarize_D(by_probe["D"])
    if by_probe.get("E"):
        out["E"] = summarize_E(by_probe["E"])
    return out
