"""Lean/MCP 并行度计算与内存护栏（自 `tools/lean_local/lean_bridge.py` 逐字搬出）。

职责：
  · 读取总/可用物理内存（Windows / Linux 双路径）；
  · 计算 MCP/Lean 并行度 K（内存为主、核数为辅，`LEAN_MCP_WORKERS` 可显式覆盖）；
  · 新 MCP 实例的可用内存门槛护栏（防 OOM）。

★ 2026-10-08 拆分（`lean_bridge.py` 上帝类拆分 · 批次2）：本模块由原文件**逐字搬出**，
  原文件改为 re-export（`from tools.lean_local.lean_bridge import X` 契约不变）。
  ★ 分层约束：本模块**零 `agent` 依赖**，不加深 tools→agent 倒置债务。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("MathPilot")


def _total_ram_gb() -> float:
    """物理内存总量（GiB）。取不到 → 按 8.0 保守估（宁小勿大）。"""
    try:
        if os.name == "nt":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return float(m.ullTotalPhys) / float(1 << 30)
        else:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return float(line.split()[1]) / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        pass
    return 8.0


def _avail_ram_gb() -> float:
    """当前**可用**物理内存（GiB）。取不到 → 返回一个大值（不做无谓拦截）。"""
    try:
        if os.name == "nt":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return float(m.ullAvailPhys) / float(1 << 30)
        else:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return float(line.split()[1]) / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        pass
    return 1e6


# 再建一个 Lean server 的内存门槛（GiB）。低于它就不再扩池，宁可回落 bridge ——
# 单个 Lean+Mathlib 常驻 1.5–4 GB，深夜/繁忙机器上硬开会把整台机器拖垮（OOM = 全盘失败）。
# ★ 2026-09-16 用户要求「统一改为可用内存」。原值 1.5 偏低：1.5 GiB 空闲就放行新建，
#   而单实例实测可占 750 MB ~ 4 GB ⇒ 放行了照样可能 OOM。提到 2.5 GiB。
_MIN_FREE_GIB_FOR_NEW = 2.5
_NO_ROOM_WARNED = False


def _mcp_room_for_new_instance() -> bool:
    """是否还有余量再起一个 Lean server（防 OOM 护栏）。"""
    global _NO_ROOM_WARNED
    ok = _avail_ram_gb() >= _MIN_FREE_GIB_FOR_NEW
    if not ok and not _NO_ROOM_WARNED:
        _NO_ROOM_WARNED = True
        logger.warning(
            "[LeanBridge] 可用内存不足 %.1f GiB → 不再扩充 MCP 实例（回落 bridge）",
             _MIN_FREE_GIB_FOR_NEW)
    return ok


def _auto_workers() -> int:
    """自动并行度：**由可用内存定，其次核数**（每个 Lean server 都把 Mathlib 载进内存）。

    K = clamp(1, min(8, 可用内存GiB//4, max(1, 核数//4)))
    - 硬上限 8：与 lean-lsp-mcp 自身的 `_MAX_SHARED_CLIENTS = 8` 对齐；
    - ``//4``：单个 Lean+Mathlib 常驻约 1.5–4 GB，按 4 GB 留量最保守；
      核数按 4 核/实例（Lean 载入 Mathlib 是多线程的）。

    ★★ 2026-09-16 用户要求「统一改为可用内存」。**此前用 `_total_ram_gb()`（总内存）
    定容，而运行期护栏 `_mcp_room_for_new_instance()` 用可用内存 —— 两个口径打架**：
    本机总 15.2 GiB ⇒ K 恒算成 3，但用户侧常驻 B站 1.5 GB + QQ 0.86 GB +
    WorkBuddy 2.1 GB ⇒ 实际可用常低到 1–3 GB，**K 却仍按 15.2 GB 在算**，
    护栏又只会"不再扩"、**不会把 K 调小** ⇒ 结构性超配、触发 OOM 护栏后回落 bridge。

    例：可用 3.4 GiB / 32 核 ⇒ min(8, 0, 8) → clamp 后 = **1**（保守但不会 OOM）。
    取不到可用内存（哨兵值）时**退回总内存口径**，避免误判成"内存无限"。
    """
    try:
        cores = os.cpu_count() or 2
    except Exception:  # noqa: BLE001
        cores = 2
    avail = _avail_ram_gb()
    if avail >= 1e5:            # `_avail_ram_gb` 取不到时返回 1e6 哨兵
        avail = _total_ram_gb()  # → 退回总量口径（宁可保守，不可误放行）
    by_ram = int(avail // 4)
    by_cpu = max(1, int(cores) // 4)
    return max(1, min(8, by_ram, by_cpu))


_WORKERS_LOGGED = False


def lean_parallelism() -> int:
    """MCP/Lean 并行度（``LEAN_MCP_WORKERS``）。

    - 未设置 / ``auto`` / ``0`` → 按内存与核数自动推算（见 ``_auto_workers``）；
    - 显式正整数 → 用该值（``1`` = 旧的单例 + 全局锁，逐字不变）；
    - 非法值 → 自动。
    """
    global _WORKERS_LOGGED
    raw = (os.environ.get("LEAN_MCP_WORKERS", "") or "").strip().lower()
    if raw in ("", "auto", "0"):
        k = _auto_workers()
        auto = True
    else:
        try:
            k = max(1, int(raw))
            auto = False
        except (TypeError, ValueError):
            k = _auto_workers()
            auto = True
    if not _WORKERS_LOGGED:
        _WORKERS_LOGGED = True
        logger.info(
            "[LeanBridge] MCP 并行度 K=%d（%s；内存 %.1f GiB / %s 核）—— "
            "1 = 单例串行，>1 = 实例池并行",
            k, "auto" if auto else "显式", _total_ram_gb(), os.cpu_count())
    return k


def _mcp_workers() -> int:
    """内部别名（保持旧调用点可读）。"""
    return lean_parallelism()
