# -*- coding: utf-8 -*-
"""统一工具调用门面（ToolGateway）—— 2026-09-30（截图 #10 用户要求）

用户原话
--------
「调用工具的方法有没有写成**规范性的类函数**，需要 Lean 检测时直接调用，适配各阶段」

问题（改动前实测）
------------------
Lean / 计算 / 检索三类工具在各阶段**各自为政**：

    · `orchestrator.py:470`  自建 `LeanGate`
    · `answer_falsifier.py:363` `from tools.lean_local.lean_bridge import LeanBridge`
                              + `LeanBridge(self.client, self.config)` 现场实例化
    · `sub_goal_solver._lean_dag_logic_check()` 又一次自己拿桥
    · `value_attack` / `lean_pre_verifier` / `theorem_hint` 各写一套 try/except

后果（本项目已实测踩到的三类）
  ① **可用性判断不一致**：有的地方查 `lean_available()`，有的只查 `_lean_active()`，
     还有的干脆不查 → 同一轮里"某阶段说 Lean 不可用、另一阶段却在调它"；
  ② **异常处理深浅不一**：`answer_falsifier` 吞 `AttributeError`（曾掩盖真实故障），
     而 orchestrator 会记录 → 同一故障有的地方报、有的地方不报；
  ③ **缓存 / 预算 / 埋点各写一遍**：无法回答"本轮 Lean 一共被调了几次"。

本模块的定位
------------
**单一入口 + 统一契约**，不改任何调用方的判定逻辑：

    gw = ToolGateway.for_ctx(ctx, client, config)      # 取（进程内复用）门面
    r  = gw.lean_compile(code)                        # 需要 Lean 时直接调
    if r.ok: ...
    gw.calc("123*456")                                # 计算
    gw.search_mathlib("Cauchy-Schwarz")               # 检索

统一契约（所有方法返回 `ToolResult`，**绝不抛异常**）：

    ToolResult.ok           是否成功拿到可用结果
    ToolResult.value        结果本体（编译诊断 / 计算值 / 命中定理列表）
    ToolResult.reason       未成功的原因码（见 REASON_*，**闭合集合**）
    ToolResult.detail       人读细节（日志与诊断报告用）
    ToolResult.available    该工具在本环境是否可用（False = 环境缺失，非调用失败）
    ToolResult.elapsed      本次耗时（秒）
    ToolResult.to_dict()    直接可落进 diag 的 JSON 结构

为什么 `reason` 用**闭合原因码**而不是自由文本
----------------------------------------------
本项目做归因时反复吃亏：「Lean 没跑」与「Lean 跑了但判 unknown」在日志里
长得几乎一样（都只有一行 warning），导致"假阴性"被读成"没问题"。
闭合码强制区分三态，`to_dict()` 落盘后可直接聚合统计。

设计纪律
--------
· **纯加性**：本模块不修改任何既有调用点。既有代码继续按原路走；
  需要"规范性调用"的地方（新代码 / 报告 / 需要统一遥测的地方）用本门面。
· **绝不抛异常**：工具问题绝不能阻断主流程（沿用本项目既有铁律）。
· **不重复实现**：所有实际动作都委托给既有类（`LeanBridge` / `LeanGate` /
  `lean_search`），本模块只做路由 + 契约统一 + 遥测。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("MathPilot")

# ----------------------------------------------------------------------
# 闭合原因码（★ 归因可用性的关键：三态必须可区分）
# ----------------------------------------------------------------------
REASON_OK = "ok"                       # 成功
REASON_DISABLED = "disabled"           # 配置关闭（开关为 False）
REASON_UNAVAILABLE = "unavailable"     # 环境缺失（无 Lean 可执行体 / 无 mathlib）
REASON_NOT_APPLICABLE = "not_applicable"  # 该题不适用（豁免题 / 非数学对象）
REASON_BUDGET = "budget"               # 预算/时间不足，未发起
REASON_TIMEOUT = "timeout"             # 发起了但超时
REASON_ERROR = "error"                 # 调用抛异常
REASON_EMPTY = "empty"                 # 调用成功但结果为空
REASON_UNKNOWN = "unknown"             # 工具明确答复"无法判定"
REASON_REJECT = "reject"               # 工具明确判否（如 Lean 编译失败）

_ALL_REASONS = (REASON_OK, REASON_DISABLED, REASON_UNAVAILABLE,
                REASON_NOT_APPLICABLE, REASON_BUDGET, REASON_TIMEOUT,
                REASON_ERROR, REASON_EMPTY, REASON_UNKNOWN, REASON_REJECT)


@dataclass
class ToolResult:
    """所有工具调用的**统一返回契约**（见模块 docstring）。"""

    tool: str = ""
    step: str = ""
    ok: bool = False
    value: Any = None
    reason: str = REASON_UNKNOWN
    detail: str = ""
    available: bool = True
    elapsed: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """落盘结构（**必须可 JSON 序列化** → `value` 只保留摘要）。"""
        _v = self.value
        try:
            if isinstance(_v, (str, int, float, bool)) or _v is None:
                _v_out = _v if not isinstance(_v, str) or len(_v) <= 300 else _v[:300]
            elif isinstance(_v, (list, tuple)):
                _v_out = f"<list len={len(_v)}>"
            elif isinstance(_v, dict):
                _v_out = {k: _v[k] for k in list(_v)[:8]}
            else:
                _v_out = f"<{type(_v).__name__}>"
        except Exception:  # noqa: BLE001
            _v_out = "<unserializable>"
        return {
            "tool": self.tool,
            "step": self.step,
            "ok": bool(self.ok),
            "reason": self.reason,
            "available": bool(self.available),
            "elapsed": round(float(self.elapsed or 0.0), 3),
            "detail": str(self.detail or "")[:300],
            "value": _v_out,
            "meta": self.meta or {},
        }

    @property
    def ran(self) -> bool:
        """★ 三态判据：**真的跑了**（区别于"没跑"与"跑了失败"）。

        本项目的假阴性模式：把「没跑」当成「没问题」。`ran` 为 False 时，
        `ok` 恒为 False，但二者**语义完全不同** —— 归因时先看 `ran`。
        """
        return self.reason not in (REASON_DISABLED, REASON_UNAVAILABLE,
                                   REASON_NOT_APPLICABLE, REASON_BUDGET)


class ToolGateway:
    """跨阶段统一工具门面（Lean / 计算 / 检索）。

    典型用法（**任何阶段都长一样**）：:

        gw = ToolGateway.for_ctx(ctx, self.client, self.config)
        r = gw.lean_compile(code, step="2.7_subgoal_main")
        if r.ok and r.value.get("ok"):
            ...

    门面**按 ctx 缓存**在 ctx 上（`ctx._tool_gateway`），同一题内各处调用
    拿到的是同一个实例 ⇒ 遥测（调用计数 / 缓存）天然跨阶段共享。
    """

    # ---- 进程级单例锁（ctx 缓存是主路径，这里只防并发首建）----
    _lock = threading.Lock()

    def __init__(self, ctx: Any = None, client: Any = None, config: Any = None):
        self.ctx = ctx
        self.client = client
        self.config = config
        # 惰性实例（首次真正用到才建，避免无谓 import / 环境探测）
        self._bridge = None
        self._bridge_tried = False
        self._gate = None
        self._searcher_inst = None
        self._calls: list = []
        self._counts: dict = {}

    # ------------------------------------------------------------------
    # 构造入口
    # ------------------------------------------------------------------
    @classmethod
    def for_ctx(cls, ctx, client=None, config=None) -> "ToolGateway":
        """取（必要时创建）**绑定到该 ctx** 的门面实例。

        缓存位置 = `ctx._tool_gateway`。为什么缓存在 ctx 上而不是全局：
        同一道题的多个阶段要共享遥测；不同题之间必须隔离（否则调用计数串台）。
        `client` / `config` 缺省时从既有实例回填（ctx 上通常拿不到，故优先用传入值）。
        """
        try:
            gw = getattr(ctx, "_tool_gateway", None)
            if isinstance(gw, cls):
                # 补齐后到的 client / config（首建时可能还没就绪）
                if gw.client is None and client is not None:
                    gw.client = client
                if gw.config is None and config is not None:
                    gw.config = config
                return gw
        except Exception:  # noqa: BLE001
            pass
        gw = cls(ctx=ctx, client=client, config=config)
        try:
            setattr(ctx, "_tool_gateway", gw)
        except Exception:  # noqa: BLE001
            pass
        return gw

    # ------------------------------------------------------------------
    # 可用性（**统一判据**，供所有阶段复用）
    # ------------------------------------------------------------------
    def pure_lean_available(self) -> bool:
        """Lean 可执行体是否可用（**不涉及题面适用性**）。

        判据来源单一化：`LeanBridge.lean_available()`。此前各阶段各写一套
        （有的查环境变量、有的查实例），本条把它收敛成一处。
        探测结果缓存到实例上（探测本身要跑子进程，不该每阶段都做）。
        """
        if self._bridge_tried:
            return bool(getattr(self, "_lean_ok", False))
        self._bridge_tried = True
        self._lean_ok = False
        try:
            b = self.bridge()
            if b is None:
                return False
            self._lean_ok = bool(b.lean_available())
        except Exception as e:  # noqa: BLE001
            logger.debug("ToolGateway: Lean 可用性探测失败: %s", e)
            self._lean_ok = False
        return bool(self._lean_ok)

    def lean_available(self) -> bool:
        """Lean 在本阶段是否可用 = 环境可用 ∧ 开关打开 ∧ 题面适用。"""
        try:
            if self.config is not None and not bool(
                    getattr(self.config, "enable_lean_verify", True)):
                return False
        except Exception:  # noqa: BLE001
            pass
        return self.pure_lean_available()

    def _lean_applicable(self) -> bool:
        """题面是否适用 Lean（豁免题 = 答案非数学对象，交 AuditGate 兜底）。"""
        try:
            if self.ctx is None:
                return True
            for attr in ("_lean_applicable_override",):
                v = getattr(self.ctx, attr, None)
                if v is not None:
                    return bool(v)
            # 复用既有判据（避免再造一套口径）：LeanGate._not_applicable 是静态方法
            try:
                from tools.lean_local.lean_gate import LeanGate as _LG
                na, _why = _LG._not_applicable(self.ctx)
                return not bool(na)
            except Exception:  # noqa: BLE001
                return True
        except Exception:  # noqa: BLE001
            return True

    # ------------------------------------------------------------------
    # 惰性实例
    # ------------------------------------------------------------------
    def bridge(self):
        """LeanBridge 实例（惰性；不可用时返回 None，**不抛异常**）。"""
        if self._bridge is not None:
            return self._bridge
        try:
            from tools.lean_local.lean_bridge import LeanBridge
            self._bridge = LeanBridge(self.client, self.config)
        except Exception as e:  # noqa: BLE001
            logger.debug("ToolGateway: LeanBridge 不可用: %s", e)
            self._bridge = None
        return self._bridge

    def gate(self):
        """LeanGate 实例（惰性）。优先复用 orchestrator 已建的实例，
        避免重复建（LeanGate 构造会做环境探测）。"""
        if self._gate is not None:
            return self._gate
        try:
            _og = getattr(self.ctx, "_orchestrator", None)
            g = getattr(_og, "lean_gate", None) if _og is not None else None
            if g is not None:
                self._gate = g
                return g
        except Exception:  # noqa: BLE001
            pass
        try:
            from tools.lean_local.lean_gate import LeanGate
            self._gate = LeanGate(self.client, self.config)
        except Exception as e:  # noqa: BLE001
            logger.debug("ToolGateway: LeanGate 不可用: %s", e)
            self._gate = None
        return self._gate

    # ------------------------------------------------------------------
    # 遥测
    # ------------------------------------------------------------------
    def _searcher(self):
        """MathlibTheoremSearcher 实例（惰性；构造会读语料，故只建一次）。"""
        return self._searcher_inst

    def _record(self, res: ToolResult) -> ToolResult:
        """统一埋点：实例内累计 + 可选写入 ctx trace（诊断报告可直接聚合）。"""
        self._calls.append(res)
        self._counts[res.tool] = self._counts.get(res.tool, 0) + 1
        try:
            if self.ctx is not None and res.reason != REASON_OK:
                # 只在"非成功"时写 trace，避免刷屏；成功次数由 counts 汇总
                _rec = getattr(self.ctx, "trace", None)
                if isinstance(_rec, list):
                    _rec.append({
                        "step": res.step or f"tool:{res.tool}",
                        "message": f"[{res.tool}] {res.reason}: {res.detail}"[:300],
                        "tool": res.tool,
                        "reason": res.reason,
                        "available": res.available,
                    })
        except Exception:  # noqa: BLE001
            pass
        return res

    def stats(self) -> dict:
        """本 ctx 内所有工具调用统计（供诊断报告「工具使用」维度取用）。"""
        _by_reason: dict = {}
        for c in self._calls:
            _by_reason[c.reason] = _by_reason.get(c.reason, 0) + 1
        return {
            "total": len(self._calls),
            "by_tool": dict(self._counts),
            "by_reason": _by_reason,
            "elapsed_total": round(sum(c.elapsed for c in self._calls), 2),
        }

    # ------------------------------------------------------------------
    # Lean：编译 / 挖空检测 / 门禁
    # ------------------------------------------------------------------
    def lean_compile(self, code: str, step: str = "",
                     timeout: float = 120.0) -> ToolResult:
        """编译一段 Lean 代码（**各阶段需要 Lean 检测时直接调这个**）。

        返回 `ToolResult.value` = LeanBridge `_compile` 的原始 dict
        （含 success / error / diagnostics 等既有字段），**不做二次加工** ——
        加工逻辑仍留在调用方，本门面只保证"契约一致 + 可用性判断一致"。

        ★ 与既有调用的唯一差别：**先统一判可用性**。此前若某阶段跳过判可用性
        直接调，会在无 Lean 的环境里每次白等一次超时。
        """
        t0 = time.time()
        if not self.lean_available():
            _r = (REASON_UNAVAILABLE if not self.pure_lean_available()
                  else REASON_DISABLED)
            return self._record(ToolResult(
                tool="lean.compile", step=step, reason=_r, available=False,
                detail="Lean 不可用（环境缺失或开关关闭）", elapsed=time.time() - t0))
        if not self._lean_applicable():
            return self._record(ToolResult(
                tool="lean.compile", step=step, reason=REASON_NOT_APPLICABLE,
                available=True, detail="题面不适用 Lean（豁免题）",
                elapsed=time.time() - t0))
        try:
            b = self.bridge()
            if b is None:
                return self._record(ToolResult(
                    tool="lean.compile", step=step, reason=REASON_UNAVAILABLE,
                    available=False, detail="LeanBridge 构造失败",
                    elapsed=time.time() - t0))
            # 复用 bridge 既有编译入口；不同版本签名可能是 (code) 或 (code, work_dir)
            try:
                res = b._compile(code, b._lean_project_dir())
            except TypeError:
                res = b._compile(code)
            _ok = bool(isinstance(res, dict) and res.get("success"))
            return self._record(ToolResult(
                tool="lean.compile", step=step, ok=_ok,
                value=res,
                reason=REASON_OK if _ok else REASON_REJECT,
                detail=("编译通过" if _ok
                        else str((res or {}).get("error", ""))[:200]),
                elapsed=time.time() - t0))
        except Exception as e:  # noqa: BLE001
            return self._record(ToolResult(
                tool="lean.compile", step=step, reason=REASON_ERROR,
                detail=f"{type(e).__name__}: {str(e)[:200]}",
                elapsed=time.time() - t0))

    def lean_check_statement(self, stmt: str, step: str = "") -> ToolResult:
        """★ **挖空检测**：判断一个数学命题**本身**是否成立。

        机制（本项目既有且已验证）：把命题写成

            example : (<stmt>) := by sorry

        再交 Lean 编译。`by sorry` 把"证明"这一步挖空 ⇒ **编译失败只可能来自
        命题本身**（语法/类型/前提不成立）。这正是用户 #6 问的
        「能不能用 Lean 检测 sorry 的地方，缺失的逻辑点是不是大模型需要推理出来的点」
        —— 本方法把该机制变成**任何阶段一行可调**的规范接口。

        与 `lean_compile` 的区别：本方法**主动构造** `example ... := by sorry`，
        调用方只需给命题字符串，不必自己拼 Lean 代码（拼错会导致假阴性）。
        """
        _s = str(stmt or "").strip()
        if not _s:
            return self._record(ToolResult(
                tool="lean.check_statement", step=step, reason=REASON_EMPTY,
                detail="命题为空，未发起编译"))
        # 已有 `example` 前缀则原样用（兼容调用方自己写好完整代码的情形）
        if _s.lstrip().startswith(("example", "theorem", "lemma")):
            code = _s
        else:
            code = f"example : ({_s}) := by sorry"
        return self.lean_compile(code, step=step or "lean.check_statement")

    # ------------------------------------------------------------------
    # Lean：mathlib 定理检索（老师重点关注：定理对大模型的帮助效果）
    # ------------------------------------------------------------------
    def search_mathlib(self, query: str, limit: int = 5,
                       step: str = "") -> ToolResult:
        """在 mathlib 里检索定理（复用 `lean_search.MathlibTheoremSearcher`，
        不另造检索）。

        ★ 入口已核实（2026-09-30）：`tools/lean_local/lean_search.py` 的
        `MathlibTheoremSearcher.search(query, limit) -> dict`（返回 dict，
        **不是 list** —— 命中列表在其内部键里）。此处把 dict 归一成
        `{"results": [...]}` 形态，并把 `n_hits` 提取出来供统计。
        """
        t0 = time.time()
        _q = str(query or "").strip()
        if not _q:
            return self._record(ToolResult(
                tool="lean.search", step=step, reason=REASON_EMPTY,
                detail="查询为空"))
        try:
            from tools.lean_local.lean_search import MathlibTheoremSearcher
            searcher = self._searcher()
            if searcher is None:
                searcher = MathlibTheoremSearcher()
                self._searcher_inst = searcher
            raw = searcher.search(_q, limit)
            hits = []
            if isinstance(raw, dict):
                for _k in ("results", "hits", "items", "theorems", "result"):
                    _v = raw.get(_k)
                    if isinstance(_v, list):
                        hits = _v
                        break
            elif isinstance(raw, (list, tuple)):
                hits = list(raw)
            _n = len(hits)
            return self._record(ToolResult(
                tool="lean.search", step=step, ok=_n > 0,
                value={"results": hits, "raw_keys": (
                    sorted(raw.keys())[:10] if isinstance(raw, dict) else None)},
                reason=REASON_OK if _n else REASON_EMPTY,
                detail=f"命中 {_n} 条", elapsed=time.time() - t0,
                meta={"query": _q[:120], "limit": limit, "n_hits": _n}))
        except Exception as e:  # noqa: BLE001
            return self._record(ToolResult(
                tool="lean.search", step=step, reason=REASON_ERROR,
                detail=f"{type(e).__name__}: {str(e)[:200]}",
                elapsed=time.time() - t0))

    # ------------------------------------------------------------------
    # 计算工具
    # ------------------------------------------------------------------
    def calc(self, expr: str, step: str = "") -> ToolResult:
        """精确计算一个表达式（复用 `utils.math_eval`，不另造计算）。

        ★ 用户 #9 问「Lean 真能审核数值代入吗（需实践证明）」——
        数值代入的**第一来源应是本方法**（SymPy 精确），Lean 用于形如
        `example : (代入后的命题) := by sorry` 的**命题级**核验。两者分工，
        不要混用（Lean 不适合做纯算术求值）。
        """
        t0 = time.time()
        _e = str(expr or "").strip()
        if not _e:
            return self._record(ToolResult(
                tool="calc", step=step, reason=REASON_EMPTY, detail="表达式为空"))
        try:
            # ★ 入口已核实（2026-10-01）：`utils/math_eval.py` 的
            #   `safe_eval(expr) -> str`（安全求值，失败返回错误说明串而非抛异常）。
            from utils.math_eval import safe_eval as _safe_eval
            val = _safe_eval(_e)
            _sval = str(val or "").strip()
            # `safe_eval` 失败时返回的是**中文错误说明**，不是数值 —— 必须区分，
            # 否则"算不出来"会被当成"算出来了一个字符串结果"（典型假阳性）。
            _is_err = (not _sval) or any(
                k in _sval for k in ("错误", "不支持", "失败", "无法", "Error",
                                     "error", "invalid", "Invalid"))
            _ok = not _is_err
            return self._record(ToolResult(
                tool="calc", step=step, ok=_ok, value=_sval,
                reason=REASON_OK if _ok else REASON_UNKNOWN,
                detail=_sval[:200] if _ok else f"求值失败: {_sval[:160]}",
                elapsed=time.time() - t0, meta={"expr": _e[:200]}))
        except Exception as e:  # noqa: BLE001
            return self._record(ToolResult(
                tool="calc", step=step, reason=REASON_ERROR,
                detail=f"{type(e).__name__}: {str(e)[:200]}",
                elapsed=time.time() - t0))

    # ------------------------------------------------------------------
    # 汇总（供诊断报告「工具使用」维度）
    # ------------------------------------------------------------------
    @staticmethod
    def summarize(ctx) -> dict:
        """从 ctx 取本门面的统计；无门面时返回零值结构（**不抛异常**）。

        诊断报告直接调它即可拿到"本轮工具到底用没用起来"，
        无需再自己遍历 trace 猜。
        """
        try:
            gw = getattr(ctx, "_tool_gateway", None)
            if isinstance(gw, ToolGateway):
                return gw.stats()
        except Exception:  # noqa: BLE001
            pass
        return {"total": 0, "by_tool": {}, "by_reason": {}, "elapsed_total": 0.0}
