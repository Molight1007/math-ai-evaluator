# -*- coding: utf-8 -*-
"""L4 评测聚合 —— k 次 trial 的分数口径（缺失记 0 / pass^k / 基础设施失败单列）。

为什么不能"跑几次取平均"了事
============================
同一道题跑 k 次，会有三种缺口，处理方式**必须不同**：

| 情形 | 记法 | 理由 |
|---|---|---|
| 跑了但答错 | `r=0` | 正常失分 |
| **压根没跑**（预算/中断/超时未重试） | **`r=0` 且分母不减** | 否则"少跑几题"就能把均分抬高——这是最容易被无意中利用的作弊面 |
| **基础设施失败**（docker/网络/Lean 环境坏、编译链崩） | **整题从分母剔除**，单列 `infra` | 那是环境故障，不是模型能力；混进均分会把"今天机器坏了"读成"模型退步" |

`pass^k` vs `pass@k`
====================
`pass@k`（任一成功）衡量"有没有能力"，会随 k 单调上升；`pass^k`（全部成功）衡量
"稳不稳定"。研究期关心的是后者：温度 0.3 下单次答对可能只是采样运气。

所以每个候选同时报三个数：`score`（k 次平均）、`pass_at_k`、`pass_hat_k`。

用法
====
    from contracts.trials import aggregate

    rewards = {"q1": [1, 1], "q2": [0, 0], "q3": [1]}      # q3 第二 trial 缺失 ⇒ 记 0
    out = aggregate(rewards, k=2)
    out["score"], out["pass_hat_k"], out["n_missing"]
"""
from __future__ import annotations

SCHEMA = "trials/1"


def _norm_trial(t) -> tuple:
    """单个 trial → (reward, infra)。支持 0/1、bool、{"r":..,"infra":..}。"""
    if isinstance(t, dict):
        return float(t.get("r") or 0), bool(t.get("infra") or t.get("infra_failure"))
    return (1.0 if t else 0.0), False


def aggregate(rewards: dict, k: int) -> dict:
    """按 k 次口径聚合。

    `rewards`：{task_id: [trial, ...]}，列表长度可以 < k（缺失按 0 计）。
    `k`：额定试次（**分母**，不随实际跑到几次变化）。
    """
    if k is None or int(k) < 1:
        raise ValueError("k 必须 >= 1（它是分母，不能自适应）")
    k = int(k)

    rows, infra_tasks = {}, []
    n_missing = 0
    sum_score = 0.0
    n_scored = n_passed_any = n_passed_all = 0

    for tid, trials in (rewards or {}).items():
        trials = list(trials or [])
        vals = [_norm_trial(t) for t in trials[:k]]
        if any(inf for _r, inf in vals):
            infra_tasks.append(str(tid))
            rows[str(tid)] = {"present": len(vals), "reward_sum": None, "infra": True}
            continue
        present = len(vals)
        n_missing += max(0, k - present)
        # ★ 缺失不补位、不缩分母：直接按 0 参与（但保留 missing 计数供报告）
        s = sum(r for r, _inf in vals)
        frac = s / k
        sum_score += frac
        n_scored += 1
        if s > 0:
            n_passed_any += 1
        if present == k and s == k:
            n_passed_all += 1
        rows[str(tid)] = {"present": present, "reward_sum": s, "infra": False}

    score = (sum_score / n_scored) if n_scored else 0.0
    return {
        "schema": SCHEMA,
        "k": k,
        "n_tasks": len(rewards or {}),
        "n_scored": n_scored,
        "n_infra": len(infra_tasks),
        "n_missing": n_missing,
        "score": score,                       # 0..1
        "score_pct": round(score * 100, 4),   # 与四道门/报告的 pp 口径一致
        "pass_at_k": (n_passed_any / n_scored) if n_scored else 0.0,
        "pass_hat_k": (n_passed_all / n_scored) if n_scored else 0.0,
        "infra_tasks": sorted(infra_tasks),
        "tasks": rows,
    }


def delta_pp(before: dict, after: dict) -> float:
    """两次聚合的分数差（pp）。口径不同（k 或题集不同）直接抛，避免比出假差异。"""
    if before.get("k") != after.get("k"):
        raise ValueError("k 不同（%r vs %r），Δ 不可比" % (before.get("k"), after.get("k")))
    if before.get("n_scored") != after.get("n_scored"):
        raise ValueError("计分题数不同（%r vs %r），Δ 不可比（先对齐题集，别让缺题变成涨分）"
                         % (before.get("n_scored"), after.get("n_scored")))
    return round(float(after.get("score_pct", 0)) - float(before.get("score_pct", 0)), 4)
