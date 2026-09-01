# -*- coding: utf-8 -*-
"""全卷时间预算仿真：验证「难题用满 20 分钟」不会把全卷拖爆。

背景（计划 §4.1）：
    平台并发 3、单题 ≤1200s（平台硬限）、Agent 总 ≤6.5h=23400s
    → 总「题·秒」预算 = 3 × 23400 = 70200

deep 档放开到 1320s 后，若不封顶，全卷必然超时。本脚本用仿真验证两道防线
（deep 配额闸 + PaperPacer 动态收紧）是否足够。

模型：
- 112 题按并发 3 分批推进，每批的墙钟 = 该批 3 题中最慢的那题
- 每题实际耗时 = min(档位设计帽, PaperPacer 给出的软预算)
  （即"题目会用满分配给它的时间"，这是最坏情况假设）

用法：
    python tools/simulate_paper_budget.py
    python tools/simulate_paper_budget.py --deep-ratio 0.40 --quota 0.25
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import time
from types import SimpleNamespace

sys.path.insert(0, _ROOT)
from agent.paper_pacer import PaperPacer

TOTAL_QUESTIONS = 112
CONCURRENCY = 3
AGENT_TOTAL_SECONDS = 23400.0    # 6.5 小时硬限（2026-08-30 #49：原 6h=21600）
# 2026-08-30 #49 同步：必须与 user_agent.py:243 的 tier_budget 一致，
# 否则仿真会低估 10%（standard 480→540 / deep 1200→1320）。
TIER_CAPS = {"fast": 120.0, "standard": 540.0, "deep": 1200.0}
# PaperPacer 的瞄准点（user_agent.py:paper_target_time）
TARGET_SECONDS = 21000.0


def simulate(deep_ratio: float, std_ratio: float, quota: float,
             total: int = TOTAL_QUESTIONS,
             concurrency: int = CONCURRENCY,
             enable_quota: bool = True,
             enable_tighten: bool = True) -> dict:
    """跑一遍全卷仿真，返回统计结果。"""
    cfg = SimpleNamespace(
        paper_target_time=TARGET_SECONDS,
        paper_min_soft=120.0,
        paper_total_questions=total,
        tier_budget=dict(TIER_CAPS),
        deep_quota_ratio=quota,
        paper_inflight=concurrency,
    )
    pacer = PaperPacer(cfg)

    n_deep = int(total * deep_ratio)
    n_std = int(total * std_ratio)
    # 期望档位分布：deep → standard → 其余 fast
    desired = (["deep"] * n_deep
               + ["standard"] * n_std
               + ["fast"] * (total - n_deep - n_std))

    # 用真实 pacer 的状态推进；墙钟以虚拟时间累积（不真的 sleep）
    virtual_now = time.time()
    pacer.start_time = virtual_now

    wall = 0.0
    tier_count = {"fast": 0, "standard": 0, "deep": 0}
    over_hard = 0          # 单题超过 1200s 的次数（平台硬限）
    batches = [desired[i:i + concurrency]
               for i in range(0, len(desired), concurrency)]

    for batch in batches:
        durations = []
        for tier in batch:
            pacer.begin()
            actual = tier
            if tier == "deep" and enable_quota and not pacer.allow_deep():
                actual = "standard"
            elif tier == "deep" and enable_quota:
                pacer.note_deep()
            soft = pacer.budget_for(actual)
            dur = TIER_CAPS[actual] if not enable_tighten else min(
                TIER_CAPS[actual], soft)
            if dur > 1200.0:
                over_hard += 1
            tier_count[actual] += 1
            durations.append(dur)
        # 推进虚拟时间（批次中最慢的一题决定本批墙钟）
        batch_wall = max(durations) if durations else 0.0
        wall += batch_wall
        pacer.start_time -= batch_wall      # 等价于虚拟时间前进
        for _ in batch:
            pacer.end()

    return {
        "wall_clock_sec": round(wall, 1),
        "over_agent_limit": wall > AGENT_TOTAL_SECONDS,
        "agent_utilization": round(wall / AGENT_TOTAL_SECONDS, 3),
        "tier_count": tier_count,
        "deep_used": pacer.deep_used,
        "deep_quota_cap": round(total * quota, 1),
        "over_hard_1200": over_hard,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="全卷时间预算仿真")
    ap.add_argument("--deep-ratio", type=float, default=0.30,
                    help="期望进 deep 的题目占比（模拟难度分布）")
    ap.add_argument("--std-ratio", type=float, default=0.50,
                    help="期望进 standard 的题目占比")
    ap.add_argument("--quota", type=float, default=0.25,
                    help="deep 档全卷配额上限占比")
    args = ap.parse_args()

    print(f"仿真条件：{TOTAL_QUESTIONS} 题、并发 {CONCURRENCY}、"
          f"Agent 总限 {AGENT_TOTAL_SECONDS / 3600:.1f}h、"
          f"pacer 瞄准点 {TARGET_SECONDS / 3600:.2f}h、"
          f"deep 期望占比 {args.deep_ratio:.0%}、配额 {args.quota:.0%}")
    print()

    scenarios = [
        ("无防线（配额关 + 动态收紧关）", False, False),
        ("仅配额闸", True, False),
        ("配额闸 + 动态收紧（实际配置）", True, True),
    ]
    for label, q, t in scenarios:
        r = simulate(args.deep_ratio, args.std_ratio, args.quota,
                     enable_quota=q, enable_tighten=t)
        flag = "❌ 超时" if r["over_agent_limit"] else "✅ 通过"
        print(f"--- {label} ---")
        print(f"  全卷墙钟 {r['wall_clock_sec']:>8.0f}s "
              f"({r['wall_clock_sec'] / 3600:.2f}h)  "
              f"占 6.5h 限的 {r['agent_utilization']:.0%}；"
              f"占瞄准点的 {r['wall_clock_sec'] / TARGET_SECONDS:.0%}  {flag}")
        print(f"  档位分布 {r['tier_count']}  "
              f"deep 实际占用 {r['deep_used']}/{r['deep_quota_cap']}")
        if r["over_hard_1200"]:
            print(f"  ⚠️ {r['over_hard_1200']} 题超过单题 1200s 硬限")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
