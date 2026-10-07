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
    # ---- 2026-10-04 开关注册制补齐（9 项：新增 2 + 补登记 7）----
    # ⚠ 下列默认值均与 `user_agent.py::AgentConfig` 同名字段的**当前默认值**逐条核对一致
    #   （否则 `bind_config` 会把两者绑成不一致的值）。本批**只登记，不翻转任何既有默认值**。
    # ---- agent/sub_goal_solver.py（K11 注入点守卫，消费方已存在）----
    "k11_mask_statement": (
        "K11_MASK_STATEMENT", "bool", True,
        "K11 注入点守卫：把子目标描述/蓝图结论里被断言的数值掩为占位符（=0 关闭）"),
    "sub_goal_oracle_check": (
        "SUB_GOAL_ORACLE_CHECK", "bool", False,
        "子目标逐步 oracle 校验（AnswerOracle sanity check，返回非空则重试该步；"
        "默认关 —— 2026-09-03 老师口径：oracle 是同源自评、价值低耗时高）"),
    # ---- agent/final_selector.py 候选池（研究期口径）----
    "candidate_pool_limit": (
        "CANDIDATE_POOL_LIMIT", "num", 6.0,
        "候选池上限（默认 6，与旧行为一致；0 = 不限，内部安全上界 12。"
        "⚠ 该值同时是本次生成数量，勿设天文数字）"),
    # ---- user_agent.py / agent/sub_goal_solver.py（多 agent 求解）----
    "enable_subgoal_multi_agent": (
        "ENABLE_SUBGOAL_MULTI_AGENT", "bool", True,
        "子目标内部多采样取多数（2026-10-04 默认 True；=0 取回单次调用旧基线）"),
    # ---- user_agent.py / agent/solver.py（LeanSearch 引理检索）----
    "use_leansearch": (
        "USE_LEANSEARCH", "bool", False,
        "LeanSearch 检索总开关（**默认关**：本项目「未验证不上」纪律 + "
        "2026-10-01 显式范围决策，非缺陷；要开请显式设 env 或走 A/B）"),
    # ---- agent/dag_reviewer.py（求解前 DAG 强制评审门）----
    "dag_replan_gate": (
        "DAG_REPLAN_GATE", "bool", False,
        "求解前 DAG 强制评审门（2026-10-04 默认 True = **复测**：旧负面结论"
        "「拦得住修不好」是在时间墙 + 重生成未写回 bug 下得出的，两条均已修复；"
        "=0 取回旧基线做 A/B）"),
    # ---- agent/skeleton_reviewer.py（骨架编排层评审循环）----
    "enable_skeleton_review": (
        "ENABLE_SKELETON_REVIEW", "bool", False,
        "骨架编排层评审循环（2026-10-04 默认 True = **复测**：旧结论"
        "「71% 走满 2 轮从未收敛」的根因是**根节点参与评审**（必然 replan）"
        "+ 重生成未写回，两条均已修复；=0 取回旧基线）"),
    # ---- agent/sub_goal_solver.py（求解后 DAG 复盘重规划，2026-10-04 补登记）----
    "enable_dag_replan": (
        "ENABLE_DAG_REPLAN", "bool", False,
        "求解**后**（候选已入池）再评审 DAG 并重写（2026-10-04 默认 True = 复测；"
        "旧结论「2/3 白跑」同属时间墙下产物；=0 取回旧基线）"),
    # ---- agent/blueprint_planner.py（OR 节点展开策略，2026-10-04 补登记）----
    "blueprint_or_expand_all": (
        "BLUEPRINT_OR_EXPAND_ALL", "bool", False,
        "蓝图 OR 节点是否展开**全部**备选分支（默认 False = 只取首分支/保持历史行为；"
        "置 True 会显著放大子目标规模，需 A/B）"),
    # ---- agent/sub_goal_solver.py 引理记忆（2026-10-04 补登记）----
    "use_lemma_accumulation": (
        "USE_LEMMA_ACCUMULATION", "bool", True,
        "引理积累/注入总开关（默认 True；实际注入还受 `lemma_domains` 领域路由约束）"),
    "lemma_domains": (
        "LEMMA_DOMAINS", "str", "Number theory,数论",
        "引理注入的**领域白名单**（逗号分隔）。默认仅数论 —— 依据本项目 A/B"
        "「数论 +23pp、代数/组合被拖累」；而 LEAP Table 6 认为代数也该受益 ⇒"
        "**两来源冲突，靠 `arm4` 裁决**。"
        "⚠ 消费方按**列表**读 `config.lemma_domains` ⇒ 走 `--arm`/AgentConfig 覆盖；"
        "env 路径需再补转换（当前 arm 驱动）"),
    # ---- agent/falsifier.py（单题证伪次数上限）----
    "falsify_max_per_q": (
        "FALSIFY_MAX_PER_Q", "num", 0.0,
        "单题最多证伪次数（**0 = 不限**；2026-10-04 默认 0。"
        "⚠ 语义已由旧的「0 = 禁用证伪」统一为「0 = 不限」）"),
    # ---- agent/orchestrator.py（阶段时间预算总开关）----
    "phase_budget_enabled": (
        "PHASE_BUDGET_ENABLED", "bool", False, "阶段时间预算总开关（默认关）"),
    # ---- user_agent.py / agent/orchestrator.py（题型惰性分类）----
    "enable_question_type": (
        "ENABLE_QUESTION_TYPE", "bool", True, "题型惰性分类总开关"),
    # ---- agent/orchestrator.py（零多样性补采，2026-10-06 新增）----
    "diversity_resample_enabled": (
        "DIVERSITY_RESAMPLE", "bool", True,
        "候选**零多样性**（全题只有 1 种答案）时是否触发**高温度补充采样**。"
        "实测题 000：5 个候选答案全同 ⇒ 置信度被刷到 1.00 ⇒ 直接放行（答案错）。"
        "「答案一致」在采样无多样性时是**采样失败信号**而非可靠性证据 ⇒ 应去创造分歧。"
        "置 False 回退旧行为（直接按高置信放行）做 A/B"),
    "diversity_resample_count": (
        "DIVERSITY_RESAMPLE_COUNT", "int", 3,
        "零多样性时补充采样的候选数（默认 3），用高温度 0.8/0.9/1.0 求差异"),
    # ---- agent/orchestrator.py（门全拒的处置策略，2026-10-06 新增）----
    "strict_all_rejected": (
        "STRICT_ALL_REJECTED", "bool", False,
        "Lean/Audit 门把候选**全部拒掉**时的处置：默认 False = 只显式留痕、"
        "不再静默保留（原实现 `if kept:` 在全拒时不更新候选池 ⇒ 门等于没作用）；"
        "置 True = 进一步清空候选池，触发下游兜底/重生成链"),
    # ---- agent/solver.py（revise 候选数下限，2026-10-06 新增）----
    "revise_min_candidates": (
        "REVISE_MIN_CANDIDATES", "int", 3,
        "revise（纠错重解）每轮的**候选数下限**。原 count = 池剩余容量 ⇒ 随池增长单调递减"
        "（实测逐轮 4→2→1，最后一轮只试 1 个）⇒ 越到后面改对机会越少。设下限杜绝此退化。"
        "置 1 可回退旧行为做 A/B"),
    # ---- agent/solver.py（候选入池门槛，2026-10-06 新增）----
    "require_answer_in_pool": (
        "REQUIRE_ANSWER_IN_POOL", "bool", True,
        "候选入池前是否要求它**真的含一个最终答案**。默认 True：不含则不入池并留痕"
        "（实测 59% 的候选 `answer` 是推理句/元话语，入池后污染投票/检错/修正）。"
        "置 False 可回退旧行为（全部入池）做 A/B"),
    # ---- agent/verifier.py（2026-10-04 B 折中：投票放开完整推理的档位）----
    "verifier_vote_reasoning": (
        "VERIFIER_VOTE_REASONING", "str", "disagree",
        "投票是否放开完整推理（不 prefill）：off=全部 prefill（旧行为，0.8s/票但"
        "「看一眼就点头」）/ **disagree=默认**（仅候选分歧时放开，把算力花在拿不准的题上）"
        " / always=每票都放开完整推理（最准，约 70s/票）。用户口径：先试 disagree，"
        "效果不理想即切 always（正确率第一位）"),
    # ---- agent/orchestrator.py（Step 4 反馈复核的两处修复，2026-10-06 新增）----
    # 背景（审计已确认）：① 一次实测灌入 157,550 字符反馈（`:2759`
    #   `_review_bug_feedback` 把模型裸输出不加限直接当反馈返回）；
    #   ② 该函数把 verifier 保留的深复核推理**整段重新摘要成短清单**再覆盖
    #   `ctx.revise_feedback` ⇒ 两处修复互相抵消、推理始终没到模型手上。
    "feedback_review_append": (
        "FEEDBACK_REVIEW_APPEND", "bool", True,
        "Step 4 复核产物**附加**而非覆盖（默认 True = 修好后行为）："
        "复核只做「是否属实」的判定与标注，以 `【复核意见】` 段并入原反馈，"
        "不摘要掉 verifier 保留的深复核推理；=0 回退旧行为（整段覆盖）做 A/B"),
    "feedback_review_max_chars": (
        "FEEDBACK_REVIEW_MAX_CHARS", "num", 8000,
        "Step 4 复核产物长度上限（默认 8000，与 verifier 复核反馈同口径："
        "`verifier.py:1821` 结构化分支 `[:8000]`；**保头**截断，末尾加「…（已截断）」）。"
        "治实测 157,550 字符裸输出灌进提示词；=0 不截断（回退旧行为）"),
    "feedback_review_clip": (
        "FEEDBACK_REVIEW_CLIP", "bool", True,
        "Step 4 复核产物**越权结论/重做正文清洗**（默认 True = 修好后行为，复用 "
        "`verifier._clip_review_prose`）：实测题 000 复核者输出「正确答案应为 0。"
        "下面给出严谨证明。…（2000+ 字符重做正文）」被模型整段照抄，最终答 0 而"
        "标准 20460。=0 回退旧行为（不清洗）做 A/B"),
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
    """读布尔开关（env > config 覆盖 > 默认值）。

    ★ 2026-10-04 修（D28）：`config 覆盖` 分支原为 `bool(_overrides[field])`，
    于是经 `bind_field` 传入**字符串** `"0"` 时 `bool("0") is True`
    ⇒ **"关"被读成"开"**（且 `get_str` 对空串的口径也不同）。
    现对**字符串**覆盖复用与 env 同一套 `_OFF` 语义；非字符串仍按 truthiness
    （`bind_config` 绑进来的是真 bool，行为不变）。
    """
    raw = _raw(field)
    if raw is not None:
        return raw.lower() not in _OFF
    if field in _overrides:
        ov = _overrides[field]
        if isinstance(ov, str):
            return ov.strip().lower() not in _OFF
        return bool(ov)
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
