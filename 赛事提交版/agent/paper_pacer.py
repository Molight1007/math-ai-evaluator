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
        # ---- deep 档全卷配额（2026-08-28 新增）----
        # 时间账：平台并发 3、Agent 总 ≤6h → 总"题·秒"预算 = 3 × 21600 = 64800。
        # deep 占 30% 需 70080 题·秒，超 5280 → 全卷必爆；25% 封顶才安全。
        # 不封顶的话"难题用满 20 分钟"会把简单题的时间全部吃掉。
        # 注意：必须用 `is not None` 判断，不能用 `or 0.25` ——
        # 0.0 是合法取值（表示完全禁用 deep 档），但 `0.0 or 0.25` 会得到 0.25。
        _ratio = getattr(config, 'deep_quota_ratio', None)
        self.deep_quota_ratio = 0.25 if _ratio is None else float(_ratio)
        # 并发=3 时最多 3 题在途，进度按"已开始 - 在途"计更贴近真实剩余
        _inflight = getattr(config, 'paper_inflight', None)
        self._inflight_window = 3 if _inflight is None else int(_inflight)
        # 平台并发度（决定单题时长预算的换算，见 budget_for）
        _conc = getattr(config, 'max_workers', None)
        self.concurrency = 3 if _conc is None else max(1, int(_conc))

        self.start_time = time.time()
        self._lock = threading.Lock()
        self.started = 0      # 已开始处理的题数
        self.done = 0         # 已完成的题数
        self.deep_used = 0    # 已占用 deep 档的题数
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

        两处 2026-08-28 修复：

        1) **漏乘并发数（关键）**：target_seconds 是**墙钟**预算（全卷 5h），
           而 soft_budget 是**单题时长**。并发=3 时 3 道题同时跑，
           全卷墙钟 = 总时长 / 3，即可用总时长 = 并发 × 剩余墙钟。
           原式 paper_cap = 剩余墙钟 / 剩余题数，把墙钟当成了单题时长预算，
           导致单题预算被压到真实可用值的 1/3 —— 全卷只用了 39% 的时间，
           "难题用满 20 分钟" 根本拿不到时间。正确式需乘并发数。

        2) 剩余题数改用 max(done, started - 并发数)：并发=3 时 done 最多滞后
           3 题，用 done 会高估剩余题数、把预算放得过松。
        """
        elapsed = time.time() - self.start_time
        remaining_target = max(1.0, self.target_seconds - elapsed)
        with self._lock:
            answered = max(self.done, self.started - self._inflight_window)
        remaining_q = max(1, self.total_questions - answered)
        # 并发换算：墙钟预算 → 单题时长预算
        paper_cap = self.concurrency * remaining_target / remaining_q
        tier_cap = float(self.tier_caps.get(tier, 480.0))
        soft = min(tier_cap, max(paper_cap, self.min_soft))
        return soft

    # ------------------------------------------------------------------
    # deep 档配额（防止全卷超时）
    # ------------------------------------------------------------------
    def allow_deep(self) -> bool:
        """是否还允许本题进入 deep 档。

        渐进释放：随卷面推进逐步放开配额，避免开局把名额烧光
        （前几题就放满的话，后面的真难题反而分不到时间）。
        """
        with self._lock:
            total = max(1, self.total_questions)
            hard_cap = total * self.deep_quota_ratio
            # 按进度等比例释放 + 开局初始额度。
            # 初始额度取 hard_cap 的 25%（而非固定 2），否则卷面前几题出现的
            # 真难题会被误拒——难题在卷面上的位置是随机的，不该惩罚靠前的。
            initial = max(2, int(hard_cap * 0.25))
            progress = min(1.0, self.started / total)
            released = initial + int(progress * hard_cap)
            cap = min(hard_cap, released)
            return self.deep_used < cap

    def note_deep(self) -> None:
        """记录一次 deep 档占用（判定通过时调用）。"""
        with self._lock:
            self.deep_used += 1

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
            # deep 配额诊断：验收时用 deep_used ≤ total × ratio 校验
            "deep_used": self.deep_used,
            "deep_quota_cap": round(
                self.total_questions * self.deep_quota_ratio, 1),
        }
