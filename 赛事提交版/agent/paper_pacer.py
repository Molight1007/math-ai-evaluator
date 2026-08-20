from __future__ import annotations
"""
全卷时间池（PaperPacer）
=======================

在竞赛 6h 硬限内把全卷总耗时控制在约 5 小时，并把省下的预算集中投入难题。

核心机制（借鉴 math_competition_agent 的 paper_pacer 思想，适配本版）：
- 每档位有设计预算帽（tier_cap）：fast=120s / standard=480s / deep=1200s；
- 动态收紧：paper_cap = 剩余目标时间 / 剩余题数；
- 软预算：soft_budget = min(tier_cap, max(paper_cap, MIN_SOFT))；
  —— 卷面进度落后时自动收紧（paper_cap 变小），
  —— 但保底 MIN_SOFT=120s，绝不把单题压到无法完成一次求解。

线程安全：平台并发=3，同一 agent 实例会并发调用 solve()，
所有状态用锁保护，budget 计算基于"已开始题数 / 已完成题数"两个计数。

说明：平台逐题调用，无法获知未来题目总数，total_questions 由配置指定
（默认 112，可经 metadata['total'] 覆盖）。即使估计偏差，MIN_SOFT 保底
与 max_time_per_question 硬限仍能保证 6h 内必然完成。
"""

import logging
import threading
import time

logger = logging.getLogger("MathPilot")

# 单题软预算保底（秒）：落后时也不压到低于此值
DEFAULT_MIN_SOFT = 120.0

# 默认总题数（当配置/metadata 均未给出时）
DEFAULT_TOTAL_QUESTIONS = 112


class PaperPacer:
    """全卷时间池（线程安全）。"""

    def __init__(self, config, total_questions: int | None = None):
        # 墙钟目标总时长（秒）：默认 5h = 18000s
        self.target_seconds = float(getattr(config, 'paper_target_time', 18000))
        self.min_soft = float(getattr(config, 'paper_min_soft', DEFAULT_MIN_SOFT))
        # 总题数：config 优先，其次构造参数，最后默认值
        self.total_questions = int(
            total_questions
            or getattr(config, 'paper_total_questions', 0)
            or DEFAULT_TOTAL_QUESTIONS
        )
        self.tier_caps = dict(getattr(
            config, 'tier_budget',
            {"fast": 120.0, "standard": 480.0, "deep": 1200.0},
        ))

        self.start_time = time.time()
        self._lock = threading.Lock()
        self.started = 0      # 已开始处理的题数
        self.done = 0         # 已完成的题数
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def begin(self) -> int:
        """记录一道题开始处理，返回递增题号（1-based）。"""
        with self._lock:
            self.started += 1
            idx = self.started
        return idx

    def end(self, tier: str = None, duration: float = None) -> None:
        """记录一道题处理完成。"""
        with self._lock:
            self.done += 1
            self.history.append({"tier": tier, "duration": duration,
                                 "at": time.time() - self.start_time})

    # ------------------------------------------------------------------
    # 预算查询
    # ------------------------------------------------------------------
    def budget_for(self, tier: str) -> float:
        """返回某档位的当前软预算帽（秒）。

        soft_budget = min(tier_cap, max(paper_cap, MIN_SOFT))
        """
        elapsed = time.time() - self.start_time
        remaining_target = max(1.0, self.target_seconds - elapsed)
        with self._lock:
            done = self.done
        remaining_q = max(1, self.total_questions - done)
        paper_cap = remaining_target / remaining_q
        tier_cap = float(self.tier_caps.get(tier, 480.0))
        soft = min(tier_cap, max(paper_cap, self.min_soft))
        return soft

    def hard_remaining(self) -> float:
        """目标预算剩余（秒）。"""
        return max(0.0, self.target_seconds - (time.time() - self.start_time))

    def is_urgent(self, threshold_ratio: float = 0.75) -> bool:
        """卷面是否已用掉 target 的 threshold_ratio 以上。"""
        elapsed = time.time() - self.start_time
        return elapsed >= self.target_seconds * threshold_ratio

    # ------------------------------------------------------------------
    # 诊断快照
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "elapsed": round(time.time() - self.start_time, 1),
            "target": self.target_seconds,
            "done": self.done,
            "total": self.total_questions,
            "started": self.started,
        }
