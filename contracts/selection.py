# -*- coding: utf-8 -*-
"""L4 四道门 —— 候选的准入判定（floor → cost → guard → argmax）。

在三体架构里的位置
==================
    L4 判定层：critic（改得对不对）→ **四道门（值不值得采纳）** → L5 账本

critic 管「这个改动是否合法」，四道门管「这个改动是否值得留着」。
两件事分开是因为它们的判据完全不同：前者看 diff 本身，后者要看**测出来的数**。

顺序是硬约束（RRSI `selection.py` 的实证）
==========================================
  ① **噪声地板**  `S' ≥ S* − δ`：候选不能把分数拉到噪声带以下。
     不过直接拒，**后面三道都不看**（否则会在一个明显更烂的候选上讨论成本）。
  ② **成本规则**  两种情形，单位必须说清：
     · `ΔS > δ`（真的涨了）⇒ 要求 `ΔC ≤ β0 + β1·ΔS`
       —— `β0` 是「白送的百分之几成本」，`β1` 是「每 +1pp 分数允许加百分之几成本」，
       **不是每 1 分**（分与 pp 差 100 倍，抄错会放松 100 倍）。
     · `ΔS ≤ δ`（还在噪声带里）⇒ 改用 `w_s·ΔS − w_c·ΔC + w_n·ν > 0`。
       RRSI coding 域实参 `w_s=0` ⇒ **带内的分数一文不值**，只认省成本或新结构组件。
  ③ **领域守卫**  可插入的纯函数（默认不提供）。为什么默认不做判断：
     我们没有 RRSI 那种「9 类组件白名单」，硬编一套只会变成假闸门。
  ④ **argmax**    存活者里取 `(ΔS, −ΔC, ν)` 字典序最大。为什么不是加权和：
     加权和会让一个很大的成本优势盖掉一个真实的小提升，而我们要的是"分数先说话"。

★ 铁律：δ 未标定 ⇒ **拒绝一切候选**，并写明原因
=============================================
没有 δ 就分不清「涨 3 分」是真改进还是采样抖动（温度 0.3，单题实测 ~1087s）。
此时放行任何候选都是在给后续轮次喂噪声，比"什么都不做"更糟。
所以本模块**不提供默认 δ**、也不从别处借数：
  · 配置文件缺 `delta_pp` / `s_star` ⇒ 全部拒；
  · 标定来源不是 `measured`（例如"抄 RRSI 的 β/δ"）⇒ 默认也全部拒，
    只有显式 `allow_borrowed=True` 才放行，且判定结果里会记明用的是借用参数。

用法
====
    from contracts.selection import load_calibration, decide

    cal = load_calibration("results/_calibration/gates.json")
    out = decide([{"id": "c1", "s_hat": 0.37, "delta_s_pp": 3.0, "delta_c_pct": -6.0}], cal)
    if out["selected"] is None:
        ...  # 看 out["rows"] 里每道的拒绝理由
"""
from __future__ import annotations

import json

SCHEMA = "selection/1"
CAL_SCHEMA = "gates/1"

# 成本规则需要的全部参数；缺任何一项都判定为"未标定"
_REQUIRED = ("s_star", "delta_pp", "beta0_pct", "beta1_pct_per_pp", "w_s", "w_c", "w_n")


class SelectionError(Exception):
    """标定文件缺失/字段不全。"""


# ---------------------------------------------------------------- 标定
def load_calibration(path: str) -> dict:
    """读 δ 标定文件。**不做任何兜底默认值** —— 缺就抛，让调用方显式处理。"""
    try:
        with open(path, encoding="utf-8") as fh:
            cal = json.load(fh)
    except OSError as e:
        raise SelectionError("读不到标定文件 %s：%s" % (path, e)) from e
    except ValueError as e:
        raise SelectionError("%s 不是合法 JSON：%s" % (path, e)) from e
    return validate_calibration(cal)


def validate_calibration(cal: dict) -> dict:
    """只校验**格式**（schema + 已知字段是数）。字段齐不齐由 `calibration_usable` 判 ——
    缺字段不是"文件坏了"，而是"还没标定"，应当让四道门拒一切候选，而不是抛异常把调用方逼停。
    """
    if not isinstance(cal, dict):
        raise SelectionError("标定文件顶层不是对象")
    if cal.get("schema") != CAL_SCHEMA:
        raise SelectionError("schema 应为 %r，实际 %r" % (CAL_SCHEMA, cal.get("schema")))
    for k in _REQUIRED:
        v = cal.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SelectionError("%s 应为数值，实际 %r" % (k, v))
    if cal.get("delta_pp") is not None and float(cal["delta_pp"]) <= 0:
        raise SelectionError("delta_pp 必须 > 0（δ=0 等于假设零噪声，与实测矛盾）")
    return cal


def missing_fields(cal: dict) -> list:
    return [k for k in _REQUIRED if (cal or {}).get(k) is None]


def calibration_usable(cal: dict, require_measured: bool = True) -> tuple:
    """返回 (可用, 原因)。`source != "measured"` 视为未标定（借用别人的 β/δ 不算标定）。"""
    if not cal:
        return False, "未提供 δ 标定"
    missing = missing_fields(cal)
    if missing:
        return False, "δ 未标定：缺 %s（先跑基线 k 次重复评测）" % ", ".join(missing)
    src = str(cal.get("source") or "")
    if require_measured and src != "measured":
        return False, ("δ 未实测（source=%r）：没有噪声带就分不清改进与抖动，"
                       "先跑基线的 k 次重复评测并标定" % (src or ""))
    return True, ""


# ---------------------------------------------------------------- 四道门
def _floor(c: dict, cal: dict) -> tuple:
    """① 噪声地板：S' ≥ S* − δ。"""
    delta_pp = float(cal["delta_pp"])
    s_star = cal["s_star"]
    if c.get("s_hat") is not None:
        floor_val = float(s_star) - delta_pp
        ok = float(c["s_hat"]) >= floor_val
        return ok, ("S'=%.2f vs 地板 %.2f（S*=%.2f, δ=%.2f）"
                    % (float(c["s_hat"]), floor_val, float(s_star), delta_pp))
    d = c.get("delta_s_pp")
    if d is None:
        return False, "没有 s_hat 也没有 delta_s_pp，无法判噪声地板"
    ok = float(d) >= -delta_pp
    return ok, "ΔS=%.2fpp vs 地板 −δ=−%.2fpp" % (float(d), delta_pp)


def _cost(c: dict, cal: dict) -> tuple:
    """② 成本规则：涨了看成本上限，没涨（带内）看净收益是否为正。"""
    d = c.get("delta_s_pp")
    if d is None:
        # 只给了 s_hat 时用 s_hat − s_star 反推
        if c.get("s_hat") is None:
            return False, "没有 ΔS，无法判成本规则"
        d = float(c["s_hat"]) - float(cal["s_star"])
    d = float(d)
    dc = float(c.get("delta_c_pct") or 0.0)
    delta_pp = float(cal["delta_pp"])
    if d > delta_pp:
        cap = float(cal["beta0_pct"]) + float(cal["beta1_pct_per_pp"]) * d
        ok = dc <= cap
        return ok, ("ΔS=%.2fpp > δ ⇒ ΔC=%.1f%% 需 ≤ β0+β1·ΔS=%.1f%%"
                    % (d, dc, cap))
    nu = float(c.get("novelty") or 0.0)
    score = (float(cal["w_s"]) * d - float(cal["w_c"]) * dc
             + float(cal["w_n"]) * nu)
    return score > 0, ("ΔS=%.2fpp ≤ δ（带内）⇒ w_s·ΔS − w_c·ΔC + w_n·ν = %.2f "
                       "需 > 0（带内分数只按 w_s 计价）" % (d, score))


def _guard(c: dict, guard) -> tuple:
    """③ 领域守卫：由调用方给的纯函数决定；没给就如实记 skipped。"""
    if guard is None:
        return True, "skipped（未提供领域守卫）"
    try:
        ok, why = guard(c)
    except Exception as e:  # noqa: BLE001  守卫自己炸了不能当成"通过"
        return False, "guard 异常：%s: %s" % (type(e).__name__, e)
    return bool(ok), str(why)


def _rank_key(c: dict):
    """④ argmax 的排序键：分数优先，其次省成本，最后新意（字典序，非加权和）。"""
    d = c.get("delta_s_pp")
    if d is None and c.get("s_hat") is not None:
        d = float(c["s_hat"])
    return (float(d if d is not None else float("-inf")),
            -float(c.get("delta_c_pct") or 0.0),
            float(c.get("novelty") or 0.0))


def decide(cands, cal: dict, guard=None, require_measured: bool = True) -> dict:
    """四道门 + 取最优。返回 {schema, calibration, usable, reason, rows, selected}。

    `rows` 每行 = {id, gate, passed, reason}，**逐道留痕**（禁用"被拒但不说为什么"）。
    """
    rows, notes = [], []
    usable, why_unusable = calibration_usable(cal, require_measured=require_measured)
    out = {"schema": SCHEMA,
           "calibration": {k: (cal or {}).get(k) for k in
                           _REQUIRED + ("source", "beta_source", "method",
                                        "n_repeats", "measured_at")},
           "usable": usable, "reason": why_unusable,
           "rows": rows, "selected": None, "ranking": []}
    if not cands:
        notes.append("没有候选")
        out["notes"] = notes
        return out

    survivors = []
    for c in cands:
        cid = str(c.get("id") or "")
        if not usable:
            # ★ 未标定 ⇒ 一律拒，且理由统一（不要给"差一点就过了"的错觉）
            rows.append({"id": cid, "gate": "floor", "passed": False,
                         "reason": "拒绝：%s" % why_unusable})
            continue
        ok, why = _floor(c, cal)
        rows.append({"id": cid, "gate": "floor", "passed": ok, "reason": why})
        if not ok:
            continue
        ok, why = _cost(c, cal)
        rows.append({"id": cid, "gate": "cost", "passed": ok, "reason": why})
        if not ok:
            continue
        ok, why = _guard(c, guard)
        rows.append({"id": cid, "gate": "guard", "passed": ok, "reason": why})
        if not ok:
            continue
        survivors.append(c)

    out["ranking"] = [str(c.get("id") or "") for c in
                      sorted(survivors, key=_rank_key, reverse=True)]
    if out["ranking"]:
        out["selected"] = out["ranking"][0]
        rows.append({"id": out["selected"], "gate": "argmax", "passed": True,
                     "reason": "存活者中排序第一（ΔS → −ΔC → ν）"})
    elif usable:
        notes.append("全部候选未过前三道门")
    out["notes"] = notes
    return out
