# -*- coding: utf-8 -*-
"""开关注册表 —— 「配置开关唯一注册制」的唯一权威来源。

背景（2026-10-01 代码审查 A 级第 2 条）
======================================
`agent/` 核心逻辑里有 29 个 gate 型开关，直接用裸 `os.environ.get` 读取：
既不在 `AgentConfig` 声明、也不在白名单、也不在启动统计 ⇒
**改了不生效、生效查不到、报告还原不出来**。

本模块提供三件事：
  1. `SWITCHES`：**全部开关的集中登记**（字段名 / 环境变量 / 默认值 / 语义 / 说明）；
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

★ 2026-10-07 架构解耦（阶段 B2）：本模块由 `agent/switch_registry.py` **下沉**至此。
它**零依赖**（只 import `os` / `typing`），却曾被 `utils/`（`llm_client.py`）与
`tools/lean_local/`（`lean_bridge.py` / `lean_gate.py`）导入 ⇒ 形成 `utils→agent`、
`tools→agent` 的跨层边。下沉到零依赖的 `contracts/` 后，这些边改走 `contracts/`（合法）。
`agent/switch_registry.py` 保留为**纯 re-export shim** ⇒ 全仓
`from agent.switch_registry import ...` **一行不改**（同一份状态、同一批函数对象，
见 shim 文件与 `tests/test_decouple_stage_a_1007.py`）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

# field: (env_key, kind, default, doc)
#   kind: "bool" | "num" | "str"
SWITCHES: Dict[str, Tuple[str, str, Any, str]] = {
    # ---- agent/base.py ----
    # ★ 2026-10-07 默认值 False → **True**（本轮唯一一处默认翻转，理由如下）。
    #   依据（2026-10-06 smoke10 实测，`results/_cloud/.../run_2026-10-06_...jsonl`）：
    #     · 10 题里 `toolcall_text_detected` 共 **93 条**（题 000=18、007=16、003=15、
    #       004=11、001=13…），而 `tool_calls.web_search.calls` 多数题为 **0**
    #       ⇒ 模型把工具调用写在正文/推理里、平台不填原生 `tool_calls`
    #       ⇒ 这些调用**一次都没执行**，前面的散文被 `extract_final_answer` 当答案。
    #     · 题 000 最强证据：模型自己写道「上一轮解答中，我错误地假设水平移动只能单向
    #       …最终推出矛盾得到答案 0。但题目条…」并随即发出 `web_search` 去核对自纠错
    #       —— **这条自纠错/验证请求被整条丢弃**（该题最终答 0，标准答案 20460）。
    #   风险评估（"误解析模型的举例说明文本"）：**低**。
    #     · 93/93 抽样到的实例都是**真实调用意图**（`<function=web_search>` +
    #       `<parameter=query>…检索式…`），未见"讲解语法"式的举例；
    #     · 系统提示已明令禁止手写这些标签（`base.py::llm_with_tools` 的 `_tool_hint`），
    #       仍出现的即为真实调用意图；
    #     · 执行侧有**硬白名单**（仅 `web_search`）+ 必填参数非空校验 + 幂等去重 +
    #       `max_rounds` 限流，且只有 `enable_web_search=True`（默认已 True）时
    #       工具循环才会走到这里 ⇒ 不放宽任何权限。
    #   收益 ≥ 风险 ⇒ 翻转。`=0` 仍可一键回退旧行为做 A/B。
    "toolcall_text_fallback": (
        "TOOLCALL_TEXT_FALLBACK", "bool", True,
        "文本工具调用兜底（默认开，2026-10-07）：模型在正文/推理里手写 "
        "`<tool_call><function=web_search><parameter=query>…` 时，解析 → 白名单校验 "
        "→ 真正执行 → 结果以 role=user 回填后继续。依据 smoke10：10 题共 93 次"
        "文本调用被丢弃（含题 000 的自纠错检索请求）。=0 回退旧行为做 A/B"),
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
    # ---- tools/lean_local/lean_bridge.py（verify_answer 的 cross_check/自证守卫）----
    # ★ 2026-10-07（语义分离）：「形式化不充分」≠「命题为假」。
    #   实测 smoke10 `lean_gate` 123 条 = proof_invalid 73 / unknown 41 /
    #   answer_valid 1，其中 51 条 cross_check_failed **全部 compiled=true**；
    #   铁证 official112-004：`example : (2025 : ℕ) / 2 = 1012 := by norm_num`
    #   （真命题、编译通过）被判 `proof_invalid` —— 把「无法核验」误当成「证明失败」。
    #   本开关=True 时 cross_check/自证拦截落 `unknown`（**无法核验，非答案错**）；
    #   =False 回退旧语义（一律 `proof_invalid`），用于 A/B 对照。
    # ---- utils/llm_client.py（2026-10-07 补齐：原为模块级常量且未登记）----
    "llm_timeout": (
        "LLM_TIMEOUT", "num", 120,
        "LLM 调用读超时（秒）。原为 utils/llm_client.py 的**模块级常量**"
        "`_DEFAULT_TIMEOUT_llm_client = int(os.getenv('LLM_TIMEOUT','120'))` —— "
        "① import 期求值，遇'先 import 后改 env'（cli/run_phase0_eval.py 等正是此写法）会静默失效；"
        "② 不入注册表 ⇒ diag 的 switch_snapshot 看不到、config/CLI 覆盖读不到。"
        "现改为调用时经注册表读（显式传入的 timeout 仍最高优先）"),
    "lean_crosscheck_as_unknown": (
        "LEAN_CROSSCHECK_AS_UNKNOWN", "bool", True,
        "cross_check/自证拦截命中时落 unknown（形式化不充分=无法核验，非答案错）；"
        "=0 回退旧语义（一律 proof_invalid）做 A/B"),
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
    # ---- agent/sub_goal_solver.py（子目标交付重写 2026-10-06）----
    "subgoal_conclusion_contract": (
        "SUBGOAL_CONCLUSION_CONTRACT", "bool", True,
        "子目标**结论契约**（默认 True = 修好后行为）：step 提示词强制每步产出"
        "`本步结论: 值=/等式=/判定=` + `本步依据:` + 验算段，"
        "并把结构化结论/推导长度/「仅断言」标记写进 trace。"
        "依据（smoke10 2026-10-06，两轮实测一致）：73 个子目标里 64 个交付 <120 字、"
        "59 个 expected_output 为空、客观判定 0/73、题 007 子目标只给结论无推导却被"
        "主求解采信 ⇒ 答错。=0 回退旧行为（只给自由文本结论）做 A/B"),
    "subgoal_objective_judge": (
        "SUBGOAL_OBJECTIVE_JUDGE", "bool", True,
        "子目标结论**客观判定**（默认 True = 修好后行为）：对每个子目标结论做 0-LLM "
        "客观判定（SymPy 判等式真伪 / 多候选符号多数），判不出时**显式留痕说明原因**"
        "（不再静默计 -1）。依据：原实现只在多 agent 路径且候选全可解析时才判，"
        "实测 `n_judged = 0/73`。=0 回退旧行为"),
    # ---- agent/final_selector.py 候选池（研究期口径）----
    "candidate_pool_limit": (
        "CANDIDATE_POOL_LIMIT", "num", 12.0,
        "候选池上限（**默认 12**；2026-10-09 用户拍板由 6 抬到 12：「先 12 试试」，"
        "原 6 = 与旧行为逐字一致。0 = 不限（受内部安全上界 12 约束）。"
        "⚠ 该值同时是本次生成数量，勿设天文数字 —— 设成天文数字会让 "
        "`_generate_initial` 尝试生成天量候选而跑飞；抬到 12 后 `0=不限` 与 `=12` "
        "行为等价，见 `agent/solver__pool._POOL_UNLIMITED_ROOM`）"),
    # ---- agent/final_selector.py（终答选择两条阻断级修复，2026-10-07 smoke10）----
    "final_answer_single_source": (
        "FINAL_ANSWER_SINGLE_SOURCE", "bool", True,
        "终答记录**单一来源**（默认 True = 修好后行为）：把 `_pick_diag.picked` 同步为"
        "**逐字提交值**（`ctx.final_response`）。依据：实测 official112-002 的 "
        "`pick_diag.picked`=计划句、而被评分的 `predicted`=`\\boxed{...}` —— 6.5 "
        "闸门在 formatter 之后经 `_set_final_response`→`adopt_single` 改写提交值却不"
        "动记录 ⇒ 决策与产出不同源、选择器结论无法验证。=0 回退改动前（picked 仍是"
        "决策值/截断值）做 A/B"),
    "final_select_verify_aware": (
        "FINAL_SELECT_VERIFY_AWARE", "bool", True,
        "终答选择**识别未验证候选**（默认 True = 修好后行为）：依 `ctx.verdicts[*]."
        "answer` 建答案级验证索引；有已验证候选时 ④模型对比/⑤投票只在已验证候选里选"
        "（跳过无验证记录者），全部未验证时显式留痕 all_unverified 且不得仅凭未验证"
        "胜出；⑤投票并列收尾不再用推理长度。依据：实测 official112-007 的 `\\boxed{0}`"
        "（gold=1）**无任何验证记录**（confidence/correct_votes/total_votes 全 None）"
        "却参与投票并在 1:1 平票后胜出。=0 回退改动前做 A/B"),
    # ---- user_agent.py / agent/sub_goal_solver.py（多 agent 求解）----
    "enable_subgoal_multi_agent": (
        "ENABLE_SUBGOAL_MULTI_AGENT", "bool", True,
        "子目标内部多采样取多数（2026-10-04 默认 True；=0 取回单次调用旧基线）"),
    # ---- user_agent.py / agent/solver.py（LeanSearch 引理检索）----
    "use_leansearch": (
        "USE_LEANSEARCH", "bool", True,
        "LeanSearch 检索总开关（★ 2026-10-12 用户决策 Q3：**纳入研究期必用清单，默认由 False 改为 True**）。"
        "注：实际评测入口（deploy/run_112.py:274 / run_research.py:69）此前已显式传 `--use_leansearch true`，"
        "故对云端评测**无行为变化**；本改动的作用是让「裸跑 run_eval」也默认开启，并消除「默认关」的误读。"),
    # ---- agent/dag_reviewer.py（求解前 DAG 强制评审门）----
    "dag_replan_gate": (
        "DAG_REPLAN_GATE", "bool", False,
        "求解前 DAG 强制评审门（**默认 False**；机制已就绪但**未翻默认值** —— 项目已为"
        "此设专臂 `deploy/run_112.py::arm2`，翻默认会与对照臂重合；复测请走 `--arm arm2`。"
        "旧负面结论「拦得住修不好」是在时间墙 + 重生成未写回 bug 下得出的，两条均已修复："
        "置 True 复测、置 False 取回旧基线做 A/B）"),
    # ---- 2026-10-12 补齐：以下 3 个此前只被裸 `getattr` 读取 —— 未声明、
    #      不在白名单、不在注册表 ⇒「假开关」（传参被静默丢弃）。现登记为注册制。
    "dag_replan_lean_check": (
        "DAG_REPLAN_LEAN_CHECK", "bool", True,
        "求解前 Lean 逻辑检查：把 DAG 节点陈述翻译为 Lean Prop 编译，"
        "失败节点硬升级 reject（**只判逻辑/形式层，不判方向**；=0 关闭）"),
    "dag_lean_max_nodes": (
        "DAG_LEAN_MAX_NODES", "num", 50,
        "求解前 Lean 逻辑检查的节点数上限。★ 2026-10-13：6 → **50**（= MAX_DAG_NODES，"
        "事实上覆盖全图）—— 原 6 是「省资源」型抽样，与研究期「不裁剪能力」冲突；"
        "用户口径：每题都跑、耗时不用愁。=6 可一键回退旧行为"),
    "enable_preverify_sketch_audit": (
        "ENABLE_PREVERIFY_SKETCH_AUDIT", "bool", False,
        "预验证阶段的骨架 Lean 审核（与 2.7 DAG 整树审核功能重叠，默认关）"),
    # ---- 2026-10-12 批次 1：题意理解链（终态 + 逻辑链 + 一致性复推）----
    "enable_understanding_chain": (
        "ENABLE_UNDERSTANDING_CHAIN", "bool", True,
        "题意理解链：终态构建 + 逻辑链 + Lean 自检 + 无条件反复理解"
        "（用户 2026-10-12 决策：本轮直接启用以便测试；=0 回退）"),
    "understanding_refine_rounds": (
        "UNDERSTANDING_REFINE_ROUNDS", "num", 3,
        "题意理解链的**无条件**复推轮数（每轮带上一轮成果重推）"),
    "understanding_chain_lean_check": (
        "UNDERSTANDING_CHAIN_LEAN_CHECK", "bool", True,
        "题意理解链的 Lean 自检（把链编译一次，只判形式自洽）"),
    "understanding_no_gain_stop": (
        "UNDERSTANDING_NO_GAIN_STOP", "bool", True,
        "题意理解链的无增益早停（链与上一轮相同即停）"),
    # ---- 2026-10-12 批次 2：蓝图多次生成（迭代式自改进）+ 自审 ----
    "blueprint_multi_gen_rounds": (
        "BLUEPRINT_MULTI_GEN_ROUNDS", "num", 3,
        "蓝图生成轮数：1 次初始 + (N-1) 次在上一轮基础上的无条件自改进"
        "（=1 等价于单次生成；用户 Q11 决策默认 3）"),
    "blueprint_self_review": (
        "BLUEPRINT_SELF_REVIEW", "bool", True,
        "第 4 次自审：LLM 审一遍蓝图（DagReviewer），按建议重写 1 轮即停"),
    "blueprint_self_review_reject_ratio": (
        "BLUEPRINT_SELF_REVIEW_REJECT_RATIO", "num", 0.4,
        "自审触发重写的拒收比例阈值（与 dag_replan_gate 同口径 40%）"),
    # ---- 2026-10-12 批次 3：子目标 inputs 机械校验（R1/R2）----
    "subgoal_inputs_validation": (
        "SUBGOAL_INPUTS_VALIDATION", "bool", True,
        "子目标 inputs 机械校验（R1 叶子判据 / R2 断链检测；零 LLM）"),
    # ---- 2026-10-12 批次 4：验证链重排（用户 Q29–Q33）----
    "enable_type_llm": (
        "ENABLE_TYPE_LLM", "bool", True,
        "**题型 LLM 判题**（§3 方案 A）：阶段 `1.1_type_understanding` 用 LLM 判题型，"
        "**与规则基线交叉校验**（规则强信号优先、低置信不覆盖）；失败完全回退规则"),
    "subgoal_self_improve_rounds": (
        "SUBGOAL_SELF_IMPROVE_ROUNDS", "num", 3,
        "子目标级**无条件**自改进轮数（用户 E24：「让大模型反复写一道题」）；"
        "同轮产出与上轮相同/为空即提前停；=0 关闭"),
    "enable_theorem_query_llm": (
        "ENABLE_THEOREM_QUERY_LLM", "bool", True,
        "**LLM 辅助 query**（用户 A1）：先让大模型给出 2–3 条检索方向（只给关键词、"
        "不给定理名，防幻觉），再交检索器出事实；失败自动回退纯规则 query"),
    "enable_lean_before_vote": (
        "ENABLE_LEAN_BEFORE_VOTE", "bool", False,
        "**4.7_lean**：把候选级 Lean 硬验证前移到投票之前（用户 Q30）。"
        "默认 False —— 主链改动，先 A/B 验证再考虑翻默认；开时会把不通过者投票前淘汰，"
        "并把淘汰反馈注入 revise"),
    "enable_verify_chain_reorder": (
        "ENABLE_VERIFY_CHAIN_REORDER", "bool", True,
        "4_verify 的**候选判定强度**：True（默认）= 多票（tier_votes=3，强度=基线）；"
        "False = 单票（**A/B 对照组**）。"
        "⚠ 2026-10-13 更正：票数**不参与终选**（终选由 final_selector 独立完成，"
        "它只看证伪结果与可解析性）⇒ 2026-10-12「降为 1 票」的默认已回滚 —— "
        "实测该降法让「全 0 票 ⇒ 强制重解」不再触发（5_revise 5805s→306s），"
        "致 official112-008 由对变错"),
    "pool_empty_clear": (
        "POOL_EMPTY_CLEAR", "bool", True,
        "候选全被滤掉时**清空池并走兜底**（用户 Q32）；=0 回退 2026-09-18 "
        "「不清空池」旧行为"),
    # ---- 2026-10-12 批次 5：定理注入块长上限 ----
    "theorem_hint_block_max_chars": (
        "THEOREM_HINT_BLOCK_MAX_CHARS", "num", 2500,
        "定理注入块的字符上限（超限按相关度截断并标注未展开条数；"
        "用户 §5.3「注意力预算」）"),
    # ---- 2026-10-12 批次 5 剩余：「分环节条数」（用户 §5.2）----
    #   ⚠ 注册表**只支持 bool/int/num/str**（无 dict）⇒ 用 **JSON 字符串**承载；
    #     读取侧 `orchestrator__lean` 解析为 dict 后写入 `ctx._theorem_topk_by_stage`。
    "theorem_hint_top_k_by_stage": (
        "THEOREM_HINT_TOP_K_BY_STAGE", "str",
        '{"pre_audit": 4, "blueprint": 12, "subgoal": 8, "solve": 25, "revise": 25}',
        "分环节定理注入条数（JSON：前置理解 4 / 蓝图 12 / 子目标 8 / 主求解 25 / 修订 25）"),
    # ---- agent/skeleton_reviewer.py（骨架编排层评审循环）----
    "enable_skeleton_review": (
        "ENABLE_SKELETON_REVIEW", "bool", False,
        "骨架编排层评审循环（**默认 False**；机制已就绪但**未翻默认值** —— 复测请走 "
        "`--arm arm2`。旧结论「71% 走满 2 轮从未收敛」的根因是**根节点参与评审**"
        "（必然 replan）+ 重生成未写回，两条均已修复：置 True 复测、置 False 取回旧基线）"),
    # ---- agent/sub_goal_solver.py（求解后 DAG 复盘重规划，2026-10-04 补登记）----
    "enable_dag_replan": (
        "ENABLE_DAG_REPLAN", "bool", False,
        "求解**后**（候选已入池）再评审 DAG 并重写（**默认 False**；机制已就绪但"
        "**未翻默认值** —— 复测请走 `--arm arm2`。旧结论「2/3 白跑」同属时间墙下产物："
        "置 True 复测、置 False 取回旧基线）"),
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
    # ---- agent/orchestrator.py（AcceptGate 真实生效，2026-10-07 新增）----
    # 背景（fix-gate-timing-diag 问题 2.3）：`base.RoundState` 契约阈值
    # ACCEPT_PASS=5 / REJECT_DEFECT=10 按"无上限连续回环"标定；但 `_update_accept_gate`
    # 唯一调用点在 `_deep_revise_loop_inner` 的每轮复验，受 `max_revise_rounds`(=5)
    # 约束 ⇒ 单题最多调用 ≤5 次（smoke10 实测 ≤2）⇒ 阈值**结构性不可达**、
    # decision 恒为 HOLD（10/10 题只出现 HOLD）⇒ AcceptGate 是空闸门；且 ACCEPT
    # 分支当时无消费者。本组开关把它变成可达且被消费的真闸门。
    "accept_gate_enforce": (
        "ACCEPT_GATE_ENFORCE", "bool", True,
        "让 AcceptGate 真正生效（默认 True = 修好后行为）：阈值改为可达口径且 "
        "ACCEPT/REJECT 均改变 revise 行为。=0 回退旧行为（阈值 5/10、恒 HOLD、无约束）做 A/B"),
    "accept_gate_pass_threshold": (
        "ACCEPT_GATE_PASS_THRESHOLD", "num", 1.0,
        "连续通过达 N 次 → ACCEPT（默认 1；仅在 accept_gate_enforce 打开时生效）"),
    "accept_gate_reject_defect_threshold": (
        "ACCEPT_GATE_REJECT_DEFECT_THRESHOLD", "num", 2.0,
        "连续重大缺陷达 N 次 → REJECT（默认 2；仅在 accept_gate_enforce 打开时生效）"),
    # ---- agent/orchestrator.py（revise 耗时归属，2026-10-07 新增）----
    "stage_timer_reassign_revise": (
        "STAGE_TIMER_REASSIGN_REVISE", "bool", True,
        "把 revise 回环墙钟从调用方阶段（4_verify/4.6/5.5）改归到 "
        "`5_revise_or_fallback`（默认 True，纯可观测性、不改行为）。"
        "依据 smoke10：题 001 revise_round=4 却记 `4_verify=5546s` 而 "
        "`5_revise_or_fallback=7.4e-06s`；题 000 同机制却记 3683s ⇒ 归属不一致。"
        "=0 回退旧埋点做 A/B"),
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
    # ---- 候选入池门槛 v2（2026-10-07，问题 2.4 第二轮）----
    # 上一轮门槛只覆盖 `_generate_initial`/`_generate_revise` 主路径 → 实测仍有漏网：
    #   题 002 `'证明这个最小值就是所求的 $T$，并验证其最优性'` 入池并成唯一幸存候选
    #   （被 final_select③ 直接采用、predicted=该句）；题 000 `'子问题4：计算满足条件
    #   的路径总数'`（自改进覆盖）/`'{(x,y)|…}，共 20 × 3 = 60 个元素'`（revise 主路径
    #   判据漏网）；题 007 `'- 子问题4：求和并验证结果'`。同时**误杀**真答案：
    #   题 087 的 `BD`（gold `B, D`）、题 088 的 `AB` 各被拒 4/5 次（trace 实证）。
    # 本开关 = 「穷举全部 6 处写入入口 + 判据升级（补漏网/修误杀）」的**总闸**。
    "pool_gate_v2": (
        "POOL_GATE_V2", "bool", True,
        "候选入池门槛 v2（默认 True = 修好后行为）：① 判据换 `looks_like_pool_answer`"
        "（补 4 条规划/设定句漏网：题 000/002/007；修 9 次多字母选项误杀：题 087/088；"
        "修判断题 gold `正确`/`错误` 误杀：题 101/111）；② 穷举全部 6 处写入 "
        "`ctx.candidates` 的入口（证明通道 / 生成失败抢救 / 自改进覆盖 / 截断续写 / "
        "子目标候选 / 三 Agent 协作），不再只覆盖主路径。"
        "⚠ 仍有 5/112 条**自然语言 gold**（填空题/论述题：037/095/104/105/108）会被判 "
        "False，需题型感知改造（本次未做，见交付说明）。=0 完全回退上一轮口径做 A/B"),
    # ---- agent/sub_goal_solver.py（`<check>` 协议守卫，2026-10-07 问题 2.9）----
    "check_protocol_guard": (
        "CHECK_PROTOCOL_GUARD", "bool", True,
        "`<check>` **协议守卫**（默认 True = 修好后行为）：模型把**中文句子**塞进 "
        "`<check>`（实测题 000 大量 `<check>图 G 是弱连通的</check>`）⇒ 不可解析 "
        "⇒ 客观判定一条都出不来（`n_judged = 0/73` 的直接原因之一）。打开后："
        "① 判定 `<check>` 内容是否为可核验对象（纯数学等式）；② 违反则**留痕**"
        "（trace `check_protocol` + sg 字段进 diag，不再静默落 undecided）；"
        "③ **触发一次定向重问**（带正确写法反馈）。=0 回退旧行为（静默跳过）做 A/B"),
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
    # ---- agent/deterministic.py（2026-10-07「审计闸门对解答题结构性无输出」修复）----
    "deterministic_solution_check": (
        "DETERMINISTIC_SOLUTION_CHECK", "bool", True,
        "解答题确定性判别重写总开关。=1（默认，修好后的行为）：① 解析前归一答案"
        "（剥 `\\boxed{}`/`$`/LaTeX 外壳 —— 实测 smoke10 有 7/10 题因带壳在 method=\"parse\" "
        "即返回 unknown，Level0 根本没进入判据）；② 常量等式回代由「只取最后一条」"
        "改为「全量等式合取判定」；③ 新增**函数方程回代**判据（覆盖「求满足函数方程的"
        "函数」这一解答题子类，对候选函数做符号代入 + 恒等判定）。=0 完全回退改动前"
        "（raw parse、只取最后一条等式、无函数方程判据）做 A/B"),
    # ---- agent/audit_gate.py（2026-10-07 同上）----
    "audit_gate_rubric_nonproof": (
        "AUDIT_GATE_RUBRIC_NONPROOF", "bool", False,
        "是否允许 AuditGate 的 Level2 rubric 结构化判分对**解答题**（非证明题）运行。"
        "旧行为：rubric 仅对证明题运行 ⇒ 解答题 Level2 结构性不适用。经查 rubric 提示词"
        "（VERIFIER_RUBRIC_SYSTEM）为通用「数学解答评审」，并无证明专用假设 ⇒ 原限制缺少"
        "依据。**默认 False（保守）**：rubric 系 LLM 同源自评（价值低、耗时高），且候选级"
        "投票链本已可选跑 rubric；开启前应做 A/B。=1 则解答题也走 Level2（仍沿用高置信 B "
        "才否决的阈值）"),
    # ---- 2026-10-07 开关注册制补齐（fix-switch-debt：6 个账外 gate 型 env）----
    # 背景（问题总账 §2.6 / 原代码审查 A 级第 2 条）：下列 6 个 env 此前仍以裸
    # `os.environ.get` / `os.getenv` 读取（读取处见各条注释），既不在本注册表、也不在
    # `AgentConfig` / 白名单 ⇒ **改了不生效、生效查不到**。本批**只接线，不改默认值、
    # 不改行为** —— 每条的默认值**逐字照抄现存 env 读取处的字面默认**。
    # ⚠ 「读取侧」大多不在本次改动范围内（见交付清单）：读取处若仍是 `os.environ.get`
    #   或模块级常量，env 能生效（优先级不变）但 config 覆盖读不到，需改为实时读注册表。
    "emergency_direct_max_tokens": (
        "EMERGENCY_DIRECT_MAX_TOKENS", "num", 8192,
        "紧急直答分支的单次 max_tokens 上限。读取处 agent/orchestrator.py:89"
        "（模块级常量 `_EMERGENCY_DIRECT_MAX_TOKENS`，需改为实时读）"),
    "emergency_answer_max_tokens": (
        "EMERGENCY_ANSWER_MAX_TOKENS", "num", 8192,
        "终答紧急兜底分支的单次 max_tokens 上限。读取处 agent/formatter.py:36"
        "（模块级常量 `_EMERGENCY_ANSWER_MAX_TOKENS`，需改为实时读）"),
    "final_answer_min_sec": (
        "FINAL_ANSWER_MIN_SEC", "num", 45.0,
        "终答紧急直答触发前要求的最小剩余秒数（低于则跳过、交上层兜底）。"
        "读取处 agent/formatter.py:29（模块级常量 `_FINAL_ANSWER_MIN_SEC`，需改为实时读）"),
    "rework_reserve_sec": (
        "REWORK_RESERVE_SEC", "num", 300.0,
        "6.5 终审重做循环为「一次重做 + 复验」预留的秒数（防跨硬墙）。"
        "读取处 agent/orchestrator.py:2497"),
    "deep_max_rework": (
        "DEEP_MAX_REWORK", "num", -1,
        "6.5 审核重做的候选数上限（deep 档）。**-1 = 无上限**（研究期默认；比赛期曾为 3）。"
        "standard 档恒为 2，不受本开关影响。"
        "读取处 agent/orchestrator.py:2508；param_usage.gate_max_rework 亦消费本开关"),
    # ---- 2026-10-14 五道审核链（用户定案：规范化前置→①自审→②证伪→③Lean
    #      代回→④计算检测→⑤投票；旧审核链同批删除）----
    #      每道独立子开关 ⇒ 评测后可逐道 A/B 归因（「一次只改一项」纪律）。
    "five_gate_normalize": (
        "FIVE_GATE_NORMALIZE", "bool", True,
        "4.0 答案规范化前置（五道审核链第 0 道）：候选进验证链前统一归一，"
        "挂 answer_norm/answer_kind 供 Lean/计算工具/投票消费；"
        "不改 c.answer（旧链行为零变化）；=0 关闭做 A/B"),
    "five_gate_self_audit": (
        "FIVE_GATE_SELF_AUDIT", "bool", True,
        "4.1 AI 自审逻辑错误（五道审核链第 1 道）：逐候选 LLM 逻辑自审"
        "（只审逻辑不审数值），能指出具体逻辑错误者淘汰并反馈；"
        "输出不可解析/LLM 故障一律保留候选（防误杀）；=0 关闭做 A/B"),
    "objective_itemwise_plan": (
        "OBJECTIVE_ITEMWISE_PLAN", "bool", True,
        "子目标**规划**阶段的客观题逐项策略（=0 关闭）。"
        "读取处 agent/sub_goal_solver.py:1376"),
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


def apply_env_to_config(cfg) -> None:
    """把**环境变量里确实存在**的开关写回 config，兑现「env > config > 默认值」。

    为什么必须有这一层（2026-10-09 缺陷复现）
    =========================================
    本模块白纸黑字承诺读取优先级 **env > AgentConfig 覆盖 > 默认值**，但此前只做了
    两段接线：
      · `kwargs → config`   （`ReasoningAgent.__init__`）
      · `config → registry` （`bind_config`）
    **缺 env → config 这一段** ⇒ 对**只被 `getattr(self.config, X)` 读取的开关**，
    env 完全无效（注册表认了 env，消费方却读 config 的旧值）：
        env DIVERSITY_RESAMPLE=0 → 注册表 False、`config.diversity_resample_enabled` True
    连带的第二处缺陷：`agent/param_usage.py::_SPEC` 的 cap_fn 全是
    `getattr(cfg, _f, _d)` ⇒ 上报的是 **config 值而非生效值**（同一份 diag 内
    `switch_snapshot` 与 `param_usage` 自相矛盾）。

    本函数即补上缺失的那一层：env 存在时把值写回 config 字段，使
    `getattr(config, 字段)` 恒等于注册表的生效值（两层缺陷一并消解）。

    ★ 只写 env 里**真实存在**的项 ⇒ env 缺失时 config 的显式值原样保留，
      不破坏「config > 默认值」这一半语义。
    ★ 必须**直接读 os.environ**，不走 `get_bool/get_num/get_str` —— 后者会先看
      进程级 `_overrides`，而在 `__post_init__` 时 `bind_config` 还没跑，残留的
      `_overrides`（同一进程内多次构造 AgentConfig 时会串味）会污染结果。
    ★ 整段 try/except 包住，**绝不抛异常** —— 构造 AgentConfig 绝不能因 env 脏而失败。
    ★ 按 kind 做**类型正确**的转换；`str` 型字段若当前值是 list/tuple（如
      `lemma_domains`），按逗号切分为列表，否则 `list("A,B")` 会退化成逐字符列表。
    """
    try:
        for field, meta in SWITCHES.items():
            env_key, kind = meta[0], meta[1]
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            if not hasattr(cfg, field):
                continue
            try:
                if kind == "bool":
                    # 与 get_bool 同口径：0/false/no/off/""（忽略大小写）= 关。
                    val: Any = str(raw).strip().lower() not in _OFF
                elif kind == "int":
                    # ★ 落在 config 上的值必须是 **int**（`getattr(config, 字段)`
                    #   的消费点按整数用：池上限/候选数下限等；且 `snapshot()` 对
                    #   kind=="int" 也返回 int）。失败（非数字）→ 跳过，保留 config 现值。
                    val = int(float(str(raw).strip()))
                elif kind == "num":
                    val = float(str(raw).strip())
                else:  # "str"
                    s = str(raw)
                    if not s:
                        # 与 get_str 一致：空串视作「未设置」，保留 config 现值。
                        continue
                    cur = getattr(cfg, field)
                    if isinstance(cur, (list, tuple)):
                        val = [p.strip() for p in s.split(",") if p.strip()]
                    else:
                        val = s
            except (TypeError, ValueError):
                continue
            try:
                setattr(cfg, field, val)
            except Exception:  # noqa: BLE001  单个字段写失败不影响其余
                continue
    except Exception:  # noqa: BLE001  桥整体失败绝不冒泡
        return


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
        elif kind == "int":
            # ★ 2026-10-09 修（同源另一处类型错误）：`int` 型开关此前落进 `else`
            #   走 `get_str` ⇒ `switch_snapshot.value` 是**字符串** `"3"` 而非整数 `3`。
            #   危害：`switch_snapshot` 是运维/复盘判断"开关当时生效成什么"的唯一权威
            #   读数，类型错了会让 `value == 3` 恒为假、或被当字符串拼进报告。
            #   此处显式取数值并**保持 int 类型**（`get_num` 走 float 分支再 `int()`，
            #   不会把 `bool` 混进来 —— bool 虽为 int 子类，但不经此路径）。
            eff = int(get_num(field))
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
