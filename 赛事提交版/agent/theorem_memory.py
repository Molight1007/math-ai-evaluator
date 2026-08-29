# -*- coding: utf-8 -*-
"""
TheoremMemory —— 跨题定理复用记忆（2026-08-29 新增）
=====================================================

回应观察"定理调用复用性很高、反复检索浪费"：
- 把 **lean_gate 编译验证通过** 的定理名（强证据，非检索命中）按领域持久化
- 同域新题开始时，注入"本域高频可用定理"清单，跳过重复检索 + 翻译试错

与 LemmaMemory（#30，记引理陈述/证明全文）的区别：
- TheoremMemory 只记「定理名 + 命中次数」的轻量统计，专为"跨题复用检索结果"
  设计，不承载证明内容；两者互补，不冲突。

并发安全（LemmaMemory 无锁的教训）：
- 进程内：threading.Lock 串行化内存修改
- 跨进程：**原子写**（写临时文件 + os.replace），Windows 上 os.replace 原子，
  读方永远看到完整文件（最多略旧），不会读到写了一半的 JSON

存储结构（JSON）：
{
  "_meta": {"version": 1},
  "Number theory": {
    "gcd_dvd": {"hits": 5, "first_seen": 1724900000, "last_seen": 1724903600},
    ...
  }
}
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time

logger = logging.getLogger("MathPilot")

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "theorem_memory.json")


class TheoremMemory:
    """跨题定理复用记忆（按域统计 + 原子持久化）。"""

    def __init__(self, storage_path: str = ""):
        self.storage_path = storage_path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._data: dict = {"_meta": {"version": 1}}
        self._load()

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    self._data = raw
        except Exception as exc:  # noqa: BLE001
            logger.warning("[theorem_memory] 读取失败（容忍，重建）: %s", exc)
            self._data = {"_meta": {"version": 1}}

    def _save(self) -> None:
        """原子写：临时文件 + os.replace（跨进程安全）。"""
        d = os.path.dirname(self.storage_path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".theorem_mem_", dir=d or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.storage_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[theorem_memory] 写入失败: %s", exc)
            try:
                os.remove(tmp)
            except OSError:
                pass

    def record_hit(self, domain: str, theorem: str) -> None:
        """记录一次"编译验证通过"（lean_gate proof_valid 时调用）。"""
        theorem = (theorem or "").strip()
        if not theorem or domain in ("", "unknown"):
            return
        with self._lock:
            bucket = self._data.setdefault(domain, {})
            now = int(time.time())
            entry = bucket.get(theorem)
            if entry is None:
                bucket[theorem] = {"hits": 1, "first_seen": now, "last_seen": now}
            else:
                entry["hits"] = entry.get("hits", 0) + 1
                entry["last_seen"] = now
            self._save()

    def top_theorems(self, domain: str, k: int = 5) -> list[str]:
        """返回某域命中次数最多的 k 个定理名（按 hits 降序）。"""
        with self._lock:
            bucket = self._data.get(domain, {})
            ranked = sorted(bucket.items(), key=lambda kv: -kv[1].get("hits", 0))
            return [name for name, _ in ranked[:k]]

    def domain_summary(self) -> dict:
        """各域定理数与总命中数（诊断/回填资料库用）。"""
        with self._lock:
            out = {}
            for dom, bucket in self._data.items():
                if dom == "_meta":
                    continue
                out[dom] = {
                    "theorems": len(bucket),
                    "total_hits": sum(e.get("hits", 0) for e in bucket.values()),
                }
            return out
