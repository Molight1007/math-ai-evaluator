"""
agent/replay_buffer.py
经验回放最小实现（SU-01 §3.3 Eq.2 简化版）
========================================

论文 SU-01 在 refined RL 用 ExGRPO 简化版经验回放：
  - 准入 0 < n+(q) < 2（唯一成功 = hard positive）
  - 退休 n+(q) >= 4（策略已能稳定复现 → 移除最早）
  - 重放比 rho=0.25
  - 最低熵优先（论文用 SGLang top-16 log probs 估计熵）

MathPilot 是推理期工程，本模块作为「推理期经验库」：
  - 成功解题的 (problem, reasoning, answer) 三元组入池
  - 同题再来时，回放最低「score」历史成功解作参考
  - 满 4 条触发「退休」（移除最早）
  - 持久化到 runs/replay_buffer.json（跨 run 累积）

最低熵的轻量代理：用 reasoning 长度作「稳定性」代理。短而稳的解更可能
再次有效（与论文最低熵优先同向但更便宜；真实熵需 token 级 log probs）。

集成点（待 orchestrator 接入，注释形式给出，避免硬改 928 行 orchestrator）：
    from agent.replay_buffer import ReplayBuffer
    buffer = ReplayBuffer()

    # Step 2 前：注入同题历史成功解作参考
    replay = buffer.get_replay(ctx.problem)
    if replay:
        prefix = f"【参考解（历史成功）】{replay.answer}\\n\\n"
        user_content = prefix + user_content  # 拼到 Step2 prompt 前

    # 验证通过 / 判分成功后：入池
    if verdict_is_correct:
        buffer.add(ctx.problem, candidate.reasoning, candidate.answer)
        buffer.save()
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict

_LOCK = threading.Lock()
_DEFAULT_PATH = "runs/replay_buffer.json"
_MAX_ENTRIES_PER_QUERY = 4  # 论文 n+>=4 退休；满 4 条移最早


def _problem_id(problem: str) -> str:
    """题目指纹（SHA1 前 16 位，足够区分类）。"""
    norm = re.sub(r"\s+", " ", problem.strip().lower())[:500]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


@dataclass
class ReplayEntry:
    problem_id: str
    problem: str
    reasoning: str
    answer: str
    success_count: int = 1     # 入池时 1；同题再成功 +1；满 4 触发退休
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def score(self) -> float:
        """越低越「稳定」（论文最低熵优先的轻量代理）。"""
        return float(len(self.reasoning))


class ReplayBuffer:
    """线程安全的推理期经验回放池。"""

    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = path
        self._entries: Dict[str, List[ReplayEntry]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for pid, lst in (data.get("entries") or {}).items():
                self._entries[pid] = [ReplayEntry(**e) for e in lst]
        except Exception:  # noqa: BLE001  损坏文件静默跳过
            pass

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with _LOCK:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "entries": {
                            pid: [asdict(e) for e in lst]
                            for pid, lst in self._entries.items()
                        },
                    },
                    f, ensure_ascii=False, indent=2,
                )

    def add(self, problem: str, reasoning: str, answer: str) -> Optional[ReplayEntry]:
        """记录一次成功解题。同题已有 → 更新 last_seen / success_count，
        满 _MAX_ENTRIES_PER_QUERY 触发「退休」（移除最早）。
        返回入池的 entry，便于 caller 拿到稳定版本作重放候选。
        """
        if not (problem and reasoning and answer):
            return None
        pid = _problem_id(problem)
        with _LOCK:
            lst = self._entries.setdefault(pid, [])
            if lst:
                # 已存在 → 命中「唯一成功」思想，更新末条
                e = lst[-1]
                e.success_count += 1
                e.last_seen = time.time()
                # 满 4 移最早（退休）
                if len(lst) >= _MAX_ENTRIES_PER_QUERY:
                    lst.pop(0)
                return e
            entry = ReplayEntry(
                problem_id=pid, problem=problem,
                reasoning=reasoning, answer=answer,
            )
            lst.append(entry)
            return entry

    def get_replay(self, problem: str) -> Optional[ReplayEntry]:
        """查询同题的回放候选（最低 score 优先 = 论文最低熵优先）。"""
        pid = _problem_id(problem)
        with _LOCK:
            lst = self._entries.get(pid) or []
            if not lst:
                return None
            return min(lst, key=lambda e: e.score())

    def stats(self) -> dict:
        """统计：题目数、条目总数、平均每题条目。"""
        with _LOCK:
            n_problems = len(self._entries)
            n_entries = sum(len(v) for v in self._entries.values())
            return {
                "problems": n_problems,
                "entries": n_entries,
                "avg_per_problem": (
                    round(n_entries / n_problems, 2) if n_problems else 0.0
                ),
            }

    def clear(self) -> None:
        """清空（仅测试 / 重置用）。"""
        with _LOCK:
            self._entries.clear()
