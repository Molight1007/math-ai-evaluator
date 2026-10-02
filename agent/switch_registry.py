# -*- coding: utf-8 -*-
"""开关注册表 —— 「配置开关唯一注册制」的唯一权威来源。

背景（2026-10-01 代码审查 A 级第 2 条）
======================================
`agent/` 核心逻辑里有 29 个 gate 型开关，直接用裸 `os.environ.get` 读取：
既不在 `AgentConfig` 声明、也不在白名单、也不在启动统计 ⇒
**改了不生效、生效查不到、报告还原不出来**。

本模块提供三件事：
  1. `SWITCHES`：29 个开关的**集中登记**（字段名 / 环境变量 / 默认值 / 语义 / 说明）；
  2. `get_bool() / get_num() / get_str()`：**统一读取器**，调用点不再直接碰 `os.environ`；
  3. `snapshot()`：当前**生效值快照**，挂进 `diag` ⇒ 报告可还原。

读取优先级（★ 关键，保证既有行为不变）
=====================================
    环境变量  >  AgentConfig 覆盖（CLI / kwargs）  >  默认值

把**环境变量放在最前**是刻意的：本项目既有的跑法（`X=0 python run_eval.py`、
`deploy/run_112.py` 里的 env）全部依赖 env，若改成 config 优先，现有命令会静默失效。

取值语义统一
============
现状有四种写法混用：`== "1"` / `!= "0"` / `== "0"` 关 / `in ("0","false","no")` 关。
本模块统一为：**`"0"/"false"/"no"/"off"/""`（忽略大小写）= 关，其余 = 开**。
对默认值与常规 `"0"/"1"` 用法，行为与改前**完全一致**；只对 `"yes"/"true"` 之类的
非常规值有差异（改前视作关，现在视作开）—— 属修正而非回归。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

# field: (env_key, kind, default, doc)
#   kind: "bool" | "num" | "str"
SWITCHES: Dict[str, Tuple[str, str, Any, str]] = {
    # ---- agent/base.py ----
    "toolcall_text_fallback": (
        "TOOLCALL_TEXT_FALLBACK", "bool", False,
        "文本工具调用兜底（直接改主链生成行为，默认关）"),
    # ---- agent/deterministic.py ----
    "deterministic_timeout_sec": (
        "DETERMINISTIC_TIMEOUT_SEC", "num", 5.0,
        "确定性验证通道的单次超时（秒）"),
    # ---- agent/orchestrator.py ----
    "lean_verify": (
        "LEAN_VERIFY", "bool", True, "Lean 通道总开关（=0 一键关闭）"),
    "numericize_final": (
        "NUMERICIZE_FINAL", "bool", True, "终答数值化（把精确式转小数）"),
    "objective_selfcheck": (
        "OBJECTIVE_SELFCHECK", "bool", True, "客观题自查"),
    "answer_form_gate": (
        "ANSWER_FORM_GATE", "bool", True, "答案形态闸门（非答案形态不放行）"),
    "lean_xcheck_numeric": (
        "LEAN_XCHECK_NUMERIC", "bool", True, "数值答案的 Lean 交叉校验"),
    "self_improve_objective_skip": (
        "SELF_IMPROVE_OBJECTIVE_SKIP", "bool", True,
        "客观题跳过无条件自改进（=0 则也跑）"),
    "objective_majority_vote": (
        "OBJECTIVE_MAJORITY_VOTE", "bool", False, "客观题多数投票（默认关）"),
    # ---- agent/solver.py ----
    "expr_eval_grounding_guard": (
        "EXPR_EVAL_GROUNDING_GUARD", "bool", True, "表达式求值接地护栏"),
    "enable_subgoal_findings": (
        "ENABLE_SUBGOAL_FINDINGS", "bool", True,
        "主求解注入子目标结论（阶段一信息流：初始/证明/重解三路径；=0 关闭）"),
    # ★ 2026-10-01：`SELF_IMPROVE_CONDITIONAL` **不纳入注册表** ——
    #   `AgentConfig.self_improve_conditional` 已存在（默认 False），而 env 语义是
    #   `!= "0"` 的取反分支（默认 "1" ⇒ 该分支不执行），两者语义不一致。
    #   待厘清后再决定是「统一到配置字段」还是「保持 env」，此处不重复定义。
    "self_improve_keep_original": (
        "SELF_IMPROVE_KEEP_ORIGINAL", "bool", True, "自改进保留原答案"),
    # ---- agent/sub_goal_solver.py ----
    "objective_itemwise_priority": (
        "OBJECTIVE_ITEMWISE_PRIORITY", "bool", True, "客观题逐项优先策略"),
    # ---- agent/theorem_hint.py ----
    "theorem_hint": (
        "THEOREM_HINT", "bool", True, "定理检索注入（=0 关闭）"),
    # ---- utils/llm_client.py ----
    "llm_retry_on_timeout": (
        "LLM_RETRY_ON_TIMEOUT", "bool", False, "LLM 超时是否重试（默认不重试）"),
    # ---- tools/lean_local/lean_bridge.py ----
    "lean_mcp_autolake": (
        "LEAN_MCP_AUTOLAKE", "bool", True, "MCP 自动 lake 环境准备"),
    "lean_mcp_timeout_floor": (
        "LEAN_MCP_TIMEOUT_FLOOR", "num", 300.0, "MCP 调用超时下限（秒）"),
    "lean_mcp_goal_loc": (
        "LEAN_MCP_GOAL_LOC", "bool", False, "MCP 回报 goal 位置（默认关）"),
    "lean_mcp_multi_attempt": (
        "LEAN_MCP_MULTI_ATTEMPT", "bool", False, "MCP 多次尝试（默认关）"),
    "lean_mcp_hover_check": (
        "LEAN_MCP_HOVER_CHECK", "bool", False, "MCP hover 检查（默认关）"),
    "lean_mcp_verify_axioms": (
        "LEAN_MCP_VERIFY_AXIOMS", "bool", True, "MCP 校验公理使用"),
    # ---- tools/lean_local/lean_gate.py ----
    "lean_gate_parallel": (
        "LEAN_GATE_PARALLEL", "bool", True, "Lean 门禁并行预取（=0 串行）"),
    "lean_gate_strict_unknown": (
        "LEAN_GATE_STRICT_UNKNOWN", "bool", True, "Lean 门禁对 unknown 从严"),
    # ---- run_eval.py ----
    "eval_split_cn": (
        "EVAL_SPLIT_CN", "bool", True, "中文答案分隔符切分"),
    "eval_alpha_equiv": (
        "EVAL_ALPHA_EQUIV", "bool", False, "字母等价（A/a）判定（默认关）"),
    # ---- deploy/run_112.py ----
    "mp_arm": (
        "MP_ARM", "str", "baseline", "实验臂名称（deploy 用）"),
    # ---- agent/artifact_store.py（2026-10-02 中间结果存储层）----
    "artifact_store_enabled": (
        "ARTIFACT_STORE_ENABLED", "bool", True,
        "中间结果落盘（results/<run_id>/<qid>/，append-only，默认开）"),
    # ---- user_agent.py（2026-10-02 最小基础模式）----
    "minimal_mode": (
        "MINIMAL_MODE", "bool", False,
        "最小基础模式：只留主链（题意理解→子目标→求解→形式化验证），"
        "关闭与推导无关的旁支（默认关）"),
    # ---- agent/final_selector.py（2026-10-02 阶段二-2 终答五层选择）----
    "enable_final_answer_selection": (
        "ENABLE_FINAL_ANSWER_SELECTION", "bool", True,
        "终答五层选择（②多答案判断→③客观验证→④模型对比→⑤投票兜底；"
        "ON 时终答不再走 _rank_key 票数优先 / objective_majority_vote，"
        "由 agent/final_selector.select_final_answer 统一选出；=0 全部回退改动前）"),
}

_OFF = {"0", "false", "no", "off", ""}
_overrides: Dict[str, Any] = {}


def bind_config(cfg) -> None:
    """把 AgentConfig 的**当前取值**绑定进注册表（在 Agent 初始化时调一次）。

    ★ 必须**每次覆盖**（不再"等于默认值就跳过"）：
    同一进程内会先后构造多个 Agent（单测尤其常见）；若跳过默认值，前一实例
    绑定过的**非默认值会残留**在 `_overrides` 里、污染后一实例
    ⇒ 表现为「后一实例静默地用了前一实例的开关值」（2026-10-02 实测踩到）。

    每次覆盖后：单次绑定语义**不变**（默认值绑进去 ⇒ 取值仍等于默认值），
    只是把「多实例泄漏」修正为「正确」——属修复，非回归。

    读取优先级始终是 **环境变量 > 覆盖值 > 默认值**（env 最高优先，行为不变）。
    """
    if cfg is None:
        return
    for field in SWITCHES:
        val = getattr(cfg, field, None)
        if val is None:
            continue
        _overrides[field] = val


def bind_field(field: str, value: Any) -> None:
    """把**单个字段**的当前值绑定进注册表（供按字段读取的模块使用）。

    与 `bind_config` **同口径**：每次都覆盖 `_overrides[field]`（`value is None` 除外）。
    因为它是被**逐实例反复调用**的（同一进程内可能先后构造多个 Agent / 多次读取），
    必须支持「后一次把前一次的值重置回默认」，否则上一实例的值会**泄漏到下一实例**
    （实测踩到：`minimal_mode=True` 的实例会污染随后构造的默认实例）。

    读取优先级始终是 **环境变量 > 覆盖值 > 默认值**，本函数不会抬高 config 的优先级。
    """
    if field not in SWITCHES:
        return
    if value is None:
        return
    _overrides[field] = value


def _raw(field: str) -> Optional[str]:
    env_key = SWITCHES[field][0]
    v = os.environ.get(env_key)
    return None if v is None else str(v).strip()


def get_bool(field: str) -> bool:
    raw = _raw(field)
    if raw is not None:
        return raw.lower() not in _OFF
    if field in _overrides:
        return bool(_overrides[field])
    return bool(SWITCHES[field][2])


def get_num(field: str) -> float:
    raw = _raw(field)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    if field in _overrides:
        try:
            return float(_overrides[field])
        except (TypeError, ValueError):
            pass
    return float(SWITCHES[field][2])


def get_str(field: str) -> str:
    raw = _raw(field)
    if raw:
        return raw
    if field in _overrides and _overrides[field]:
        return str(_overrides[field])
    return str(SWITCHES[field][2])


def source_of(field: str) -> str:
    """该开关的生效值来自哪里：env / config / default。"""
    if _raw(field) is not None:
        return "env"
    if field in _overrides:
        return "config"
    return "default"


def snapshot() -> Dict[str, Dict[str, Any]]:
    """当前全部开关的生效值快照（挂进 diag ⇒ 报告可还原）。"""
    out = {}
    for field, (env_key, kind, default, doc) in SWITCHES.items():
        if kind == "bool":
            eff: Any = get_bool(field)
        elif kind == "num":
            eff = get_num(field)
        else:
            eff = get_str(field)
        out[field] = {
            "env": env_key,
            "value": eff,
            "source": source_of(field),
            "default": default,
            "doc": doc,
        }
    return out


def summary_line() -> str:
    """一行摘要，便于写进 trace/日志。"""
    env_n = sum(1 for f in SWITCHES if source_of(f) == "env")
    cfg_n = sum(1 for f in SWITCHES if source_of(f) == "config")
    return (f"注册开关 {len(SWITCHES)} 个："
            f"来自环境变量 {env_n}、来自配置覆盖 {cfg_n}、"
            f"其余 {len(SWITCHES) - env_n - cfg_n} 用默认值")
