# -*- coding: utf-8 -*-
"""固定策略表 —— 118 个历史开关在 2026-11-04 全量论证后的收敛结果。

与「开关」的三点根本区别（这不是换名字）：
  1. **不可覆盖**：没有环境变量、没有 CLI/kwargs、没有 config 覆盖、没有 bind。
     整个进程里每个值从头到尾只有一个来源，就是本文件。
  2. **无来源分层**：不再有 env > config > default 的优先级，也不再有
     `source_of()` / `snapshot().source` —— 报告里不存在「当时谁把它改了」。
  3. **无生命周期**：没有 experiment / 到期日 / pending 决策，也没有
     「先加个开关回头再删」这回事。新增策略项必须先写清论证。

论证依据（逐条见每个常量后的注释 + `contracts/policy_ledger.json`）：
  · 服务器 103 题次 `diag.switch_snapshot` 全量回放：133 个历史字段里，
    7 个现存字段真变过值（已排除 2 个已删字段与 `revise_min_candidates`
    的 `'3'` vs `3` 类型脏值）；其余全部恒定；
  · 取值口径是「**实际生效值**」而非注册表 default：注册表 default 与
    `DEFAULT_AGENT_OVERRIDES` / `AgentConfig` 并不一致（本轮复核揪出
    `enable_numeric_lean_verify`、`lemma_domains` 两处）；
  · `deploy/cloud_run.env` 的覆盖逐条给了去向（applied / reverted），
    没有「按最新 env 一把抄」——「融合」只做等价收敛，不夹带功能变更；
  · E14：历史 A/B 对错结论全部作废（8 题一致率 38%、p=1.000、power 0.54）；
  · E19：注册 118 / 现存 101 恒定 / 真正做过布尔 A/B 仅 4 个；
  · 3 个负结果实验（E09/E10/E13）已删除功能分支，不在本表；
  · 13 个零消费者开关 + 1 个评测臂标签已删除登记，不在本表。

★ `MappingProxyType` 是刻意选的：运行期连「手滑写回」都做不到。
★ 门禁 `tests/test_no_runtime_switches.py` 锁死「不得重新引入开关」。
"""
from types import MappingProxyType

_POLICY = {
    'answer_form_gate': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'answer_shape_strict': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'artifact_store_enabled': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'attention_focus_enabled': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'audit_gate_rubric_nonproof': False,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'audit_obligation_ledger': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'blueprint_lean_sig': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'blueprint_merge_value_mask': True,  # E08：从未比对开关前后同一批蓝图的断言率，无有效性证据 ⇒ 无结论即无实验身份，按生产现值固化，不再可切
    'blueprint_multi_gen_rounds': 3,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'blueprint_node_contract': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'blueprint_or_expand_all': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'blueprint_self_review': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'blueprint_self_review_reject_ratio': 0.4,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'blueprint_tool_exec': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'candidate_pool_limit': 12.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'check_protocol_guard': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'cross_model_falsify': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'cross_model_timeout': 90,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'deterministic_solution_check': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'deterministic_timeout_sec': 5.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'enable_final_answer_selection': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_lean_tools': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    # ★ 2026-11-05 留出集复核修正：注册表默认 False，但生产评测引擎的
    #   DEFAULT_AGENT_OVERRIDES 显式打开为 True；103 题次里 57 次带字段者
    #   **全部为 True**（source=config）。固化成 False 会静默关掉数值 Lean
    #   核验 ⇒ 必须按「实际生效值」而非「注册表 default」固化。
    'enable_numeric_lean_verify': True,  # 生产实证值（评测引擎默认覆盖），非注册表 default
    'enable_preverify_sketch_audit': False,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_question_type': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_subgoal_findings': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_subgoal_multi_agent': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_theorem_query_llm': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_type_llm': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'enable_understanding_chain': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'eval_alpha_equiv': False,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'eval_split_cn': True,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'expr_eval_grounding_guard': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'falsify_max_per_q': 0.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'final_answer_single_source': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'final_select_verify_aware': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'five_gate_falsify': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_lean_check': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_lean_check_tool': False,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_math_check': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_math_check_calcverify': False,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_normalize': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    # ★ 2026-11-05 二次复核（推翻本轮第一次判断）：`FIVE_GATE_REWRITE=0`
    #   是 **2026-10-31 已应用**的生产决策，不是待决临时版本。
    #   证据（deploy/cloud_run.env 注释，434 题次全量回放、非抽样）：
    #     跑过 4.6 的 23 题次判对 0/23；4.6 占这些题 49.4% 耗时。
    #     4.6 只在池空/低置信触发且从不产出判对 ⇒ 移除后**判对集合严格不变**，
    #     这是结构性论证，不是 A/B 分数推断（E14 作废的是显著性结论）。
    #   ★ 103 题次快照止于 10-30、全部为 True，是因为**数据早于配置变更**，
    #     不能据此反推「该值从未生效」。这正是「别拿历史数据拟合当前配置」
    #     的反例：见到 0 次生效应先查时间截断点，而不是直接判回退。
    'five_gate_rewrite': False,  # applied：值已固化，env 覆盖行随之删除
    'five_gate_self_audit': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'five_gate_vote': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'k11_mask_statement': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_check_normalize_imports': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_crosscheck_as_unknown': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_gate_parallel': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_gate_strict_unknown': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_hammer': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_mcp_autolake': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_mcp_goal_loc': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_mcp_hover_check': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_mcp_multi_attempt': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_mcp_timeout_floor': 300.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'lean_mcp_verify_axioms': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_verify': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'lean_xcheck_numeric': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    # ★ 2026-11-05 留出集复核修正：注册表 default 是逗号分隔的**字符串**，
    #   但 AgentConfig 与 103 题次快照里的实际值都是**二元素序列**
    #   `["Number theory", "数论"]`；读取点用 `list(POLICY[...])` 展开，
    #   若固化成字符串会被逐字符拆成 17 个元素 ⇒ 领域路由整体失效。
    #   MappingProxyType 只禁写键，值用不可变 tuple 才真正锁死。
    'lemma_domains': ('Number theory', '数论'),  # 生产实证形态（序列），非注册表 default 字符串
    'llm_retry_on_timeout': False,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'llm_timeout': 900.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'minimal_mode': False,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'numericize_final': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'objective_itemwise_plan': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'objective_itemwise_priority': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'objective_majority_vote': False,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'objective_selfcheck': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'phase_budget_enabled': False,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'pool_empty_clear': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'pool_gate_v2': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'problem_goal_emit_answer_slot': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'require_answer_in_pool': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'revise_min_candidates': 3,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'rewrite_conf_threshold': 0.0,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'rewrite_on_low_conf': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'self_improve_keep_original': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'self_improve_objective_skip': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'self_improve_stage': False,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'smt_falsify': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'strict_all_rejected': False,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'sub_goal_oracle_check': False,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'subgoal_backward_max_depth': 2,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'subgoal_collab_mode': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'subgoal_collab_regen_rounds': 3,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'subgoal_conclusion_contract': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'subgoal_dynamic_backward': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'subgoal_final_answer_anchor': True,  # doc 套话自称可做 A/B，但 103 题次取值从未变过、实际 0 次实验（E19：承诺 26、兑现 4）⇒ 注销实验身份，按生产值固化
    'subgoal_inputs_validation': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'subgoal_objective_judge': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'subgoal_regen_self_review': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'subgoal_self_improve_rounds': 3,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'subgoal_theorem_search': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'theorem_hint': True,  # 应急闸刀/策略分支；103 题次取值从未变过 ⇒ 固化为生产值，删掉可关能力
    'theorem_hint_backend': 'leanexplore',  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'theorem_hint_block_max_chars': 2500,  # 数值/口径参数，不是策略分支 ⇒ 固化为常量参数
    'theorem_hint_top_k_by_stage': '{"pre_audit": 4, "blueprint": 12, "subgoal": 25, "solve": 25, "revise": 25}',  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'toolcall_text_fallback': True,  # 历史变过值（False,True）；按当前生产值固化，A/B 结论按 E14 全部作废
    'use_leansearch': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'use_lemma_accumulation': True,  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
    'verifier_vote_reasoning': 'disagree',  # 无 A/B 结论、103 题次取值恒定 ⇒ 按生产现值固化为策略常量
}

# 只读视图：任何赋值都抛 TypeError，运行期不存在「临时改一下」。
POLICY = MappingProxyType(_POLICY)

__all__ = ["POLICY"]
