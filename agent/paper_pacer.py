from __future__ import annotations
"""
全卷时间池（PaperPacer）
=======================

在竞赛 6.5h 硬限内把全卷总耗时控制在约 5.83 小时（target=21000s），并把省下的预算集中投入难题。

核心机制（借鉴 math_competition_agent 的 paper_pacer 思想，适配本版）：
- 每档位有设计预算帽（tier_cap）：fast=120s / standard=540s / deep=1200s；
  （deep 上限 = 平台单题硬限 max_time_per_question=1200s，不可再抬）
- 动态收紧：paper_cap = 剩余目标时间 / 剩余题数；
- 软预算：soft_budget = min(tier_cap, max(paper_cap, MIN_SOFT))；
  —— 卷面进度落后时自动收紧（paper_cap 变小），
  —— 但保底 MIN_SOFT=120s，绝不把单题压到无法完成一次求解。

线程安全：平台并发=3，同一 agent 实例会并发调用 solve()，
所有状态用锁保护，budget 计算基于"已开始题数 / 已完成题数"两个计数。

说明：平台逐题调用，无法获知未来题目总数，total_questions 由配置指定
（默认 112，可经 metadata['total'] 覆盖）。即使估计偏差，MIN_SOFT 保底
与 max_time_per_question 硬限仍能保证 6.5h 内必然完成。
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
        # 墙钟目标总时长（秒）：2026-08-30 #49 对齐竞赛 6.5h 限时。
        # 默认 21000（5.83h），仅为无配置时的兜底；实际取 config.paper_target_time。
        self.target_seconds = float(getattr(config, 'paper_target_time', 21000))
        self.min_soft = float(getattr(config, 'paper_min_soft', DEFAULT_MIN_SOFT))
        # 「放开时间」系数（2026-09-13 新增）：卷面进度正常时，单题预算可放宽到
        # `sustainable × normal_relax`。1.0 = 严格按平均线（不超支）；1.5（默认）
        # = 允许前期用掉后期额度（拿时间换单题质量），代价是全卷最多超支 50%，
        # 由 `ratio` 熔断兜底。设 1.0 即"完全不放开、只看平均线"。
        self.normal_relax = float(
            getattr(config, 'pacer_normal_relax', 1.5) or 1.5)
        # 总题数：config 优先，其次构造参数，最后默认值
        self.total_questions = int(
            total_questions
            or getattr(config, 'paper_total_questions', 0)
            or DEFAULT_TOTAL_QUESTIONS
        )
        self.tier_caps = dict(getattr(
            config, 'tier_budget',
            # 与 user_agent.tier_budget 保持一致；deep 上限 = 平台单题硬限 1200s
            {"fast": 120.0, "standard": 540.0, "deep": 1200.0},
        ))
        # ---- deep 档全卷配额（2026-08-28 新增）----
        # 时间账：平台并发 3、Agent 总 ≤6.5h → 总"题·秒"预算 = 3 × 23400 = 70200。
        # deep（1320s）占 30% 需 112×0.3×1320 = 44352 题·秒，25% 封顶才安全。
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
        # 2026-09-02 老师需求「时间动态分配」：每题省下的时间累积，
        # 后续题可在收紧时加回去（盈余→难题加时间）。
        self.bonus_pool = 0.0
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

    def end(self, tier: str = None, duration: float = None,
            soft: float = None) -> None:
        """记录一道题处理完成。

        soft: 该题分配到的软预算帽（秒）。若 soft > duration，
        盈余累入 bonus_pool，供后续题收紧时加回（动态分配）。
        """
        with self._lock:
            self.done += 1
            if soft is not None and duration is not None:
                surplus = max(0.0, float(soft) - float(duration))
                self.bonus_pool += surplus
            self.history.append({"tier": tier, "duration": duration,
                                 "soft": soft,
                                 "at": time.time() - self.start_time})

    # ------------------------------------------------------------------
    # 预算查询
    # ------------------------------------------------------------------
    def budget_for(self, tier: str) -> float:
        """返回某档位的当前软预算帽（秒）。

        ── 2026-09-13 重写（「放开时间」+「防卡死」同时成立）──────────────
        背景（已实测确认）：单题 1200s **纯属自设**（`user_agent.py:169` 注释
        自陈"ICMA 同款"，平台日志 `deadline_seconds: 0`，平台不设单题硬限）；
        而全卷时钟此前是**死的**（`orchestrator.run()` 每题把 total_deadline
        重置为 `now + 6.25h` ⇒ ratio 恒 0 ⇒ 应急/收紧分支永不触发）。两者叠加
        = 唯一约束只剩单题那道 1200s 顶，等于**没有任何人在管全卷**。

        新口径：单题预算 = `min(档位帽, 全卷可持续值 × 系数)`，其中

            sustainable = concurrency × 剩余目标时间 / 剩余题数
                        （= 余下题目"平均每题可花"的题·秒，已含并发折算）

        - **进度正常**（时间消耗比例 ≤ 完成比例）→ 给 `sustainable × relax`
          （relax 默认 1.5，来自 config.pacer_normal_relax）。**这就是"放开
          时间"的入口**：卷面有余量时单题能拿更多——本地少量题测试时
          sustainable 很大，实际会拿满档位帽；平台 112 题时自动回落到平均线。
        - **卷面落后** → 只给 `sustainable`（系数 1.0）。
        - 两者都受 `tier_cap` 封顶、受 `min_soft` 保底。

        ⚠ 与旧版的关键差别：**进度正常不再无脑 `return tier_cap`**。旧写法在
        档位帽被放开（如 deep 3600）之后，会让前几题各自吃满 3600s 把全卷烧穿
        ——这正是"卡在某题上导致写不完"的机理。现在任何一题的单题预算都不可
        超过 `concurrency × 剩余/剩余题数 × relax`，全卷因此始终收敛在 target
        附近（最坏超支幅度由 relax 决定）。
        """
        elapsed = time.time() - self.start_time
        with self._lock:
            answered = max(self.done, self.started - self._inflight_window)
        tier_cap = float(self.tier_caps.get(tier, 480.0))

        # 全卷可持续单题预算（含并发折算）——「不写不完」的数学护栏。
        remaining_target = max(1.0, self.target_seconds - elapsed)
        remaining_q = max(1, self.total_questions - answered)
        sustainable = self.concurrency * remaining_target / remaining_q
        bonus_per_q = self.bonus_pool / remaining_q

        # 开题宽容：并发尚未回填（answered 偏小），"落后"判定不可靠。
        # 但仍受 sustainable × relax 约束——否则前几题会把全卷烧穿。
        if answered < self._inflight_window:
            return min(tier_cap,
                       max(sustainable * self.normal_relax, self.min_soft))

        # 进度判定：时间消耗比例 ≤ 完成比例 → 正常/超前，放开到 relax 倍
        budget_frac = answered / max(1, self.total_questions)
        time_frac = elapsed / max(1.0, self.target_seconds)
        if time_frac <= budget_frac:
            cap = sustainable * self.normal_relax + bonus_per_q
        else:
            # 落后 → 回到平均线；已完成题省下的盈余按剩余题数摊还
            cap = sustainable + bonus_per_q
        return min(tier_cap, max(cap, self.min_soft))

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
            "bonus_pool": round(self.bonus_pool, 1),
            # deep 配额诊断：验收时用 deep_used ≤ total × ratio 校验
            "deep_used": self.deep_used,
            "deep_quota_cap": round(
                self.total_questions * self.deep_quota_ratio, 1),
        }
