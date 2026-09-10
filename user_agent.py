from __future__ import annotations
"""
MathPilot — 基于 Intern-S 系列大模型的数学智能体（多智能体版）
==========================================================

赛题：基于 Intern-S 系列大模型的数学智能体设计与推理创新
发榜单位：上海人工智能实验室

架构（多智能体协作，简化版 v2）：
    题型识别 → 通用求解 → 过程校验 → 答案规范化
    由 Orchestrator 通过共享黑板（TaskContext）调度，借鉴 ss-main 的简洁流水线。
    不做复杂回环，每道题 LLM 调用控制在 7 次以内。

硬性接口规范（不可修改）：
    agent = ReasoningAgent(client=official_client)
    result = agent.solve(problem, metadata)  # -> dict

注意事项：
    - 禁止硬编码 API Key，client 由平台统一注入
    - 禁止使用绝对路径，所有文件读取使用相对路径
    - solve 返回的字典必须支持 JSON 序列化
    - final_response 不可为空

平台契约防御（v2.3）：
    - sys.path 自举：无论平台以何种 cwd 运行，都能找到本包
    - solve(problem, metadata=None)：metadata 缺失时不崩溃
    - 核心模块导入失败 → 降级到内置直答后端，保证永远有输出
    - client.chat 响应归一化：兼容 str / dict / 对象 / 空值
    - _validate_output：返回前强制校验 final_response 非空
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# sys.path 自举：保证从任何 cwd 都能 import 到本包
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger("MathPilot")


# ============================================================
# 配置
# ============================================================
@dataclass
class AgentConfig:
    """智能体可调参数（选手可自由优化）
    
    适配竞赛规则 v3（2026-07-31）：
    - 并发=3，单题最长=20分钟，Agent最长=6小时
    - 反rollout：减少候选数与投票次数，依赖聚类共识而非暴力采样
    """
    # 策略模型（解题）
    # P0-4 修复：候选 3→2（平台并发=3，且 3 候选×3 重试曾耗尽单题预算 → 45 error）
    # v2.4.0：恢复 24576 上限（ICMA 对齐）。ICMA 实测同模型首轮 24576 仅 143-231s，
    # 模型实际只用 3-7K token，24576 只是上限；降上限会牺牲贴上限的奥赛题成功区间。
    # 真正修超时靠：结构化四章节 prompt（抑制自由 CoT）+ 预算感知 + 压缩 prefill 兜底。
    # 2026-09-04：比赛不限制模型 token（单题边界=平台 1200s 时间墙）→ 上限放开 65536
    #   （2534334 平台实测 truncated 238 次答案被腰斩 → 64 invalid；截断比耗时更丢分）。
    policy_sample_times: int = 2       # 候选解答数量
    policy_temperature: float = 0.3    # 策略采样温度（提高以增加多样性）
    policy_max_tokens: int = 65536     # 策略最大 token（上限；9/4 放开，只受 1200s 时间墙）

    # 蓝图分解（简化版：关闭蓝图，直接用最简 prompt）
    use_blueprint: bool = False        # 蓝图太长，Intern-S 思维流先被蓝图占满

    # 验证模型（评判）
    verifier_voting_times: int = 1     # 每个候选只投 1 票（避免无效重复投票）
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类（可选）
    enable_domain_hint: bool = True    # 是否启用领域提示增强
    enable_question_type: bool = True  # 是否启用题型识别（证明/选择/判断/填空/解答）+ 差异化策略

    # ---- calc_tool 确定性计算（2026-09-01，治 value_wrong）----
    enable_calc_tool: bool = True      # 提示词引导 <calc> 标记 + 输出精确求值回填
    # 2026-09-09 P1-1（老师拍板"计算必须用工具"）：行级**裸数值断言**
    # （如 `25*4 = 100`，两侧无字母/中文、无 <calc> 来源）→ 判定心算/自算，
    # 带反馈打回重写一次（方程/结论式含变量放行，不打断推导）。默认关待 A/B。
    calc_mandatory: bool = False
    # 2026-09-09 用户洞察：原生工具调用试点（同智能体调 WebSearch 逻辑）——
    # 模型生成 tool_call calc_eval → 执行 calc_tool → 回传 → 继续；默认关待验证
    tool_calc_enabled: bool = False
    # 2026-09-10 L1（用户 9/10 + 李平老师建议）：**答案级工具自洽核验**——
    # 最终答案是纯数值、却没有任何 <calc> 工具来源（心算产物）→ 定向重问一次，
    # 要求把得出答案的算式写成 <calc>；仅在重问结果**带工具来源**时采纳。
    # 零后悔（失败/未改善一律保留原输出）。默认关待 A/B（题均 +1 次 LLM 调用）。
    answer_selfcheck_enabled: bool = False
    # 2026-09-10 L2（用户 9/10 思路 + 李平老师 9/9 建议）：**独立符号建模复核**——
    # 让模型当"数学问题拆解助手"，只把给定数值抽象成变量并输出目标量表达式
    # （禁止自算），由 calc_tool 精确代入求真值，与主链答案比对；不一致则打回
    # 一次，仅当新答案落回该真值才采纳。每题最多 1 次调用。默认关待 A/B。
    symbolic_crosscheck_enabled: bool = False
    symbolic_max_tokens: int = 512

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（大幅缩减）----
    max_revise_rounds: int = 1         # 自纠错 1 轮（A/B 验证 6/6 无损失，输出更易读）
    max_total_calls: int = 150         # LLM 调用预算硬上限（v2.6.1：15→60；v2.7：60→150，
                                        # 覆盖 5 题 batch + 限流重试 + deep 档完整流程
                                        # = classifier 1 + 求解 3 + 投票 6 + self_audit 1
                                        # + revise 1 + lean 转换 1 + collab 6 轮
                                        # + sub_goal 规划 1 + N 个子目标 ≈ 25-30 次/题）

    # ---- 时间限制（适配竞赛新规则）----
    # P0-5 修复：单题预算 300→1200（平台规则允许单题最长 20 分钟，ICMA 同款 1200s。
    #   此前 300s 对完整 CoT 求解（ICMA 实测中档 77-116s、奥赛 500-552s）是死限，
    #   导致主求解调用被读超时/预算跳过 → 45 error。总时长由 PaperPacer 动态收紧控制。）
    # 2026-08-30 #49 预算对齐：竞赛端限时 **6.5h = 23400s**（此前按 6h 配置）。
    # 三档关系必须满足：paper_target_time < max_total_time_seconds < 平台限时。
    #   target 21000（5.83h）→ 动态收紧的瞄准点；
    #   hard   22500（6.25h）→ 硬熔断，给平台留 15min 提交/IO 余量。
    # 沿用原 6h 配置下的安全比例（target 19500 / 6h = 81%），
    # 6.5h 下等比为 21060 ≈ 21000，故取 21000。
    max_time_per_question: int = 1200  # 单题壁钟时间上限（秒，平台允许 20 分钟）
    max_total_time_seconds: int = 22500  # Agent总运行时间上限（6.25h，平台限 6.5h）

    # ---- 智能体补充部件配置 ----
    # v2.4.0：max_tokens/cap 同步 24576（ICMA reasoning 同款上限，模型实际用 3-7K token）
    # 2026-09-04：平台不限 token → max_tokens 65536；max_tokens_cap=0 关闭 base.llm 二次裁剪
    max_tokens: int = 65536            # 单次最大 token 数（匹配 policy_max_tokens）
    max_tokens_cap: int = 0            # 内部 token 裁剪上限：0=不裁剪（base.llm 语义）
    max_workers: int = 3               # 并发验证线程数（匹配系统并发度=3）
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 自纠错参数 ----
    max_answer_tokens: int = 65536    # solver 单次调用最大 token 数（9/4 放开，防答案腰斩）
    revise_sample_times: int = 2       # 自纠错重解候选数

    # ---- 新功能开关（简化）----
    use_scoring: bool = False          # Verifier 不用多维评分（简化，减少误判）
    enable_deterministic: bool = True  # 确定性硬否决（v2.8）：SymPy 代入回验 fail 淘汰候选、unknown 放行
    # 2026-09-06（移植自 sq 分支，默认关，A/B 验证后开）：
    use_rubric: bool = False           # Verifier rubric 结构化判分（verdict+confidence+错因定位，JSON prefill）
    use_challenge: bool = False        # Verifier 反例挑战（LLM 命题 → SymPy 程序数值验证 → hard_fail 否决）
    by_enable_fast_path: bool = True   # 启用 SymPy 快车道求解
    use_proof_channel: bool = False    # 关闭证明题专用通道（简化）
    use_lemma_accumulation: bool = True  # 引理积累（2026-08-29 起默认开，按领域路由）
    lemma_domains: list = field(default_factory=lambda: ["Number theory", "数论"])  # 领域路由：A/B 实测数论 +23pp、代数/组合被拖累
    use_sub_goal: bool = False         # 子目标分解补充候选（候选不足/证明题时触发）
    # Step 2 无条件自改进（2026-08-29 新增，依据 IMO2025 验证-精炼论文）
    # 论文流水线六步中的 Step 2：初始解生成后**无条件**先 review+improve 一次
    # （注入第二段推理预算），再进入验证。论文实测：初始解质量低，此步显著改进。
    # 区别于 revise（验证失败才修正），自改进对每个候选都做一遍。
    enable_self_improve: bool = True
    self_improve_max: int = 3          # 每题最多自改进候选数（控成本；fast 档跳过）
    improve_min_remaining: float = 300.0  # 3.3 改进停手预留（距生成软截止 < 此值不再开新候选；0=关，治 alg-060 3.3=640s 烧穿）
    # 易错点记忆注入（2026-09-06 A 档轻量经验，prompts/error_lessons.py）：
    # 命中题型/关键词时把历史易错自查清单拼进初始生成与 revise 提示，防重复踩坑。
    # 默认开（本地评测生效）；A/B 对照可 --override enable_error_lessons=False。
    enable_error_lessons: bool = True
    # Step 4 bug report 复核（2026-08-29 晚新增，论文流水线 Step 4）
    # 验证器给出缺陷反馈后，让模型先复核反馈是否属实、可驳回误报——
    # 论文：模型可驳回验证器的错误反馈，避免好答案被误报引导改坏。
    # 仅 deep 档 revise 回环触发（每次 +1 次 LLM 调用，预算可承受）。
    enable_feedback_review: bool = True

    # ---- 对抗式验证（#16，2026-08-30）----
    # 正向验证**通过**后主动证伪：假设答案错误，反向找反例 / 第一个错误步骤。
    # 基线依据：两层复核一致性仅 51%、反向案例 0 条（第二层只是加严不是独立），
    # 且正向验证存在漏检。正向验证问"这对吗"（确认偏误），
    # 对抗式验证问"假设它是错的，错在哪"（证伪 → 反例法）。
    # 与 enable_feedback_review 互补：那个治误杀，这个治漏检。
    enable_adversarial_verify: bool = True
    # 生效档位：fast 是简单题快速通道，跳过以省调用
    adversarial_tiers: list = field(default_factory=lambda: ["deep", "standard"])
    # 低于此置信度的"检出"不采信：宁可漏掉，不可误伤（治误杀优先于治漏检）
    adversarial_min_confidence: float = 0.5
    adversarial_max_tokens: int = 640
    adversarial_max_reasoning: int = 2400
    # ---- 验证增强链时间护栏（2026-09-07：治 4.5_oracle / 4.6_adv 烧穿 6.5）----
    # 冒烟 v2 实证：3.3/3.6 止损省下的时间被 4.5 Oracle(365s)/4.6 对抗(372s)
    # 单次 300s+ 不可打断的复核吸收 → 6.5 Lean 终局仍 time_critical、0 绿点。
    # 4.5/4.6 是可弃增强：放行前要求剩余时间 ≥ 本值 + critical_tail + 30s 缓冲
    # （deep 需 ~450s / standard ~510s），否则跳过直进 6.5——宁少一层深查，
    # 不饿死最终闸门。设 0 = 关闭护栏（旧行为）。对齐 LLMClient 180s×2 重试上限。
    verify_enhance_est_seconds: float = 360.0

    # ---- 难题深度求解通道（v2.5）----
    # 三级档位资源分配：fast（快答）/ standard（标准，== 现状）/ deep（深度）
    enable_difficulty_router: bool = True   # 总开关；关闭则全卷走 standard（回归现状）
    enable_llm_difficulty: bool = True      # 难题识别第二层：LLM 自评难度（1 次小调用）
    # 2026-08-30 Algebra 专项：实测无效已回滚（45 题 Algebra 仍 1/11，
    # v3 33.3% < ab_review 35.6%），保留开关但默认关闭
    algebra_force_deep: bool = False
    tier_sample_times: dict = None          # 每档候选数 {fast:1, standard:2, deep:3}
    tier_temperatures: dict = None          # 每档温度分层（deep 用 4 层）
    tier_voting_times: dict = None          # 每档每候选投票数 {fast:1, standard:1, deep:3}
    tier_max_completions: dict = None       # 每档截断续写数 {fast:0, standard:1, deep:2}
    tier_max_calls: dict = None             # 每档 LLM 调用预算上限
    tier_budget: dict = None                # 每档设计预算帽（秒）{fast:120, standard:540, deep:1320}
    # 2026-08-30 平台实测：112 题 4.65h 完成（6h 限时 78% 利用率），有 1.35h
    # 空余 → 预算小幅上调换正确率：standard 480→540、deep 1200→1320。
    # 保留防超时双防线（deep 配额闸 ≤25% + 动态收紧），硬上限 max_total_time 兜底。
    # 2026-08-30 #49：19500（按 6h 限）→ 21000（按 6.5h 限，占 6.5h 的 81%，
    # 与 6h 时代的安全比例一致）。必须与 max_total_time_seconds(22500) 保持
    # 大小关系：target < hard < 平台限时，否则动态收紧会失效被硬熔断抢先。
    paper_target_time: int = 21000      # 全卷墙钟目标（秒，5.83 小时；原 19500/5.42h）
    # L1 验证优先（2026-08-31）：剩余时间不足该值时进入 verify_only，
    # 不再生成新候选（solver/续写/自改进/协作/子目标/Lean 门禁全跳过），
    # 把最后的时间留给验证投票 → 治 A_base 30 题里 117 次「验证 None 判错」。
    # ⚠ D 组对照实测（30 题）：7/30 = 23.3% vs A_base 8/30 = 26.7%，
    # 净 −1、McNemar p=1.0 → **噪声内，无收益** → 默认关闭（=0 不触发）。
    # 机制与测试保留（tests/test_verify_only.py）；若将来再试，
    # 先补「预算跳过/None 投票计数器」量化验证假设，再调阈值。
    verify_only_seconds: int = 0
    paper_min_soft: int = 120               # PaperPacer 单题软预算保底（秒）
    paper_total_questions: int = 112        # 默认全卷题数（PaperPacer 预算帽估算用）
    deep_use_sub_goal: bool = True          # deep 档强制子目标分解补充候选
    deep_revise_rounds: int = 2             # deep 档 0 票时 revise 自纠错轮数（08-30：1→2，LeanSearch v2 反思循环）
    deep_use_playoff: bool = True           # deep 档 0 票且时间宽裕时 playoff 复算
    enable_collaborative_deep: bool = True  # 难题(deep 档)三Agent协作：解题→审查→整合→验证
    collab_max_rounds: int = 3              # 协作验证循环最大轮数（2026-09-06 P3 用户拍板 6→3：单轮含 3 次 LLM 不可中断、algebra-003 曾烧 535s，收紧省时；时间充裕时停滞检测照常兜底）
    # 子目标阶段预算（2026-09-06 P1 用户拍板按档拆分）：
    # deep 保留 750s（难题深度分解值）；standard/fast 用 450s——
    # 依据：2.7 子目标全档均 ~587s 为最大黑洞，standard 档性价比存疑，
    # 省下预算自然流向 3_solve/verify。原 subgoal_stage_budget_sec 未入
    # AgentConfig（sub_goal_solver getattr 兜底 750），现补全可配。
    subgoal_stage_budget_sec: float = 750.0     # deep 档子目标阶段预算
    subgoal_stage_budget_sec_std: float = 450.0  # standard/fast 档子目标阶段预算
    # 2026-09-06 老师建议（子目标独立性/最小上下文）：子目标上下文注入模式。
    # "deps"（默认）= 按 depends_on 只注入直接依赖结果，无依赖子目标零前序上下文
    # （可独立、可并行校验、不被无关中间量污染）；"all" = 旧行为全量前序注入。
    subgoal_ctx_mode: str = "deps"
    # P2（2026-09-09 老师：计算/推理子目标类型化）：DAG 子目标打标 calc_kind
    # （terminal=纯计算型 / inline=推理型，规则启发，字段总是进 trace 可观测）。
    # router 开启后：terminal 走专用模板（只给表达式→<calc> 回填即结论）+
    # 轻校验（结果须回填形态）。默认关待 A/B。
    subgoal_calc_router: bool = False
    # 2026-09-06 老师建议（S1-lite 0-LLM 校验前移）：子目标结果自带 lean 代码片时
    # 做本地编译校验（L1，仅 deep 档 + lean 环境可用，0 LLM 5-21s，禁网纯本地）。
    # 异常/环境缺失一律放行，绝不阻断；False = 跳过 L1 只留 L0 截断检查（A/B 对照）。
    enable_subgoal_lean_check: bool = True
    # 子目标交叉核对（2026-09-08 老师建议3）——merge 前不让子目标间矛盾
    # 静默流入最终合并。两方向独立开关，可单开/同开做 A/B：
    #  A 确定性冲突闸（0 LLM）：汇总 <calc> 回填 + <check> + L2 断言，
    #    同名 LHS 出现不同常数（x=1 vs x=2）→ 矛盾注入 merge 提示词强制裁决。
    #    抓显式冲突；抓不到隐含矛盾（alg-060：xy=25 与 D=2 不共变量名，纯规则必漏）。
    #  B LLM 交叉核对轮（merge 前 +1 次小调用 1-2K token，60-110s 级）：
    #    各子目标结论行单独抽出集中裁决，能看隐含矛盾（不保证）。
    subgoal_conflict_gate: bool = False     # A 确定性冲突闸（0 LLM）
    subgoal_crosscheck_llm: bool = False    # B LLM 交叉核对轮（+1 调用）
    accept_confidence: float = 0.6          # AcceptGate 可接受置信度阈值（>=该值视为通过，v2.8）
    # 结构化 bug report 驱动的修正（论文依据：IMO 2025 验证-精炼流水线）
    # 验证器改为产出「分类 + 原文定位」的结构化错因，注入 revise 步骤。
    # 论文实测：best-of-32 仅 21.4%~38.1%，加验证-精炼后 85.7%，
    # 说明杠杆在错因质量而非候选数量。
    use_bug_report_feedback: bool = True

    # ---- 时间预算真正生效（2026-08-28 修复）----
    # 此前 base.is_time_critical() 硬编码 300s，且 PaperPacer 算出的
    # ctx.soft_budget 只打日志、无人消费 —— 动态预算形同虚设。
    critical_tail_seconds: float = 120.0      # 剩余不足该值则跳过可选步骤（原硬编码 300）
    deep_critical_tail_seconds: float = 60.0  # deep 档再收紧，把时间用得更尽
    deep_quota_ratio: float = 0.25            # deep 档全卷占比上限（>25% 会导致全卷超时）

    # ---- 检测链（2026-09-06：AuditGate 为主；晚间恢复 Lean 双通道）----
    # AuditGate 多级检测链：Level0 程序硬核验 → Level1 反例搜索 → Level2
    # LLM rubric 判分 → Level3 playoff。硬否决优先、宁 unknown 不误杀、只审不答。
    # Lean 硬验证通道（2026-09-06 晚，lean-toolchain 工具仓离线可跑后恢复）：
    # Lean 环境可用 → 2.6 preverify / 3.6 候选 / 6.5 最终闸门走 LeanGate 硬验证
    # （证明题整题 verify、非证明题 verify_answer），Lean 不可用/异常自动回落
    # AuditGate（AI 判分链），本地评测与平台两种环境同一份代码都正确。
    enable_audit_gate: bool = True          # AuditGate 检测链总开关（lean 不可用时兜底）
    # ---- Lean 双通道开关（2026-09-06 晚恢复；9/6 去 Lean 化前字段全量回归）----
    enable_lean_verify: bool = True         # Lean 通道总开关（配合环境探测，无 Lean 自动回落 AuditGate）
    enable_lean_preverify: bool = True      # 2.6 题目前置形式化（题目转 Lean 声明校验理解，deep 档）
    lean_preverify_tiers: tuple = ("deep",)  # preverify 适用档位
    preverify_max_rounds: int = 2           # preverify 编译失败重试上限（强制重新审题）
    preverify_timeout: float = 60.0         # preverify 单次编译/转化超时（秒）
    lean_gate_all_proofs: bool = True       # 证明题全档 Lean 硬验证（False 回退仅 deep）
    lean_gate_nonproof: bool = False        # 非证明题候选级 Lean（默认关省时；6.5 最终答案仍 verify_answer）
    lean_gate_strict: bool = False          # Lean unknown 时严格拒绝（True 保守拒，默认放行保分）
    lean_gate_unknown_stop: int = 2         # 候选级连续 N 个 unknown 止损（0=关；治证明题整题 verify 空转 563s）
    lean_timeout: float = 60.0              # Lean 单次编译超时（秒）
    lean_backend: str = "bridge"            # bridge(lake env lean) | mcp(lean-lsp-mcp)；env LEAN_BACKEND 优先
    lean_executable: str = ""               # lean.exe 绝对路径（空=自动探测：LEAN_EXE env>elan>vendor/lean-toolchain）
    lean_project_dir: str = ""              # 带 Mathlib 的 lake 工程目录（空=自动探测）
    theorem_memory_enable: bool = False     # 跨题定理记忆（9/6 关闭维持；LeanGate 写入按此开关）
    enable_subgoal_main_path: bool = True   # 子目标细化作为主路径
    # ---- Blueprint DAG 分解（LEAP Stage 1，#27）----
    use_blueprint_dag: bool = True          # 子目标规划先用 BlueprintPlanner 生成 AND-OR DAG 再求解（失败自动回退原规划）
    # ---- 求解前 DAG 强制门（#34；2026-09-08 起默认关闭）----
    # 45 题实证：门"拦得住、修不好"（21/45 触发重写，净正确率贡献≈0，
    # 总耗时 +23%、触发组人均 +245s）。默认去掉前置强制评审-重写循环，
    # 蓝图直接进子目标求解；后置 replan（候选入池后、预算允许时）仍由
    # enable_dag_replan 独立控制。需 A/B 复测门效果时显式置 True。
    dag_replan_gate: bool = False
    # ---- 骨架编排层评审（老师 9/2 建议：求解前规划质量门）----
    # 蓝图生成后先提交 LLM 审查子目标是否不适定 / 难度>=原题；有问题重生成再确认，
    # 通过后才进语法审核。默认开启（老师明确要求）。LLM 失败/预算不足降级放行不阻断。
    enable_skeleton_review: bool = True
    skeleton_review_max_rounds: int = 2     # 评审-重生成循环硬上限（防死循环）
    # ---- lemma 记忆（#30，跨题持久化）----
    lemma_storage_path: str = ""            # LemmaMemory 跨题持久化路径（空=仅内存）

    def __post_init__(self):
        """初始化三级档位配置表默认值（平台提交版默认关闭 LLM 自评? 否，默认开启）。"""
        if self.tier_sample_times is None:
            # 2026-09-04：deep 4→3（配每候选 3 票，验证成本 12→9 票 ≈ -25%；
            # 平台实测堆候选边际收益低，杠杆在验证器错因质量，不在候选数量）
            self.tier_sample_times = {"fast": 1, "standard": 2, "deep": 3}
        if self.tier_temperatures is None:
            self.tier_temperatures = {
                "fast": [0.1],
                "standard": [0.1, 0.3],
                "deep": [0.1, 0.3, 0.5, 0.7],
            }
        if self.tier_voting_times is None:
            self.tier_voting_times = {"fast": 1, "standard": 1, "deep": 3}
        if self.tier_max_completions is None:
            self.tier_max_completions = {"fast": 0, "standard": 1, "deep": 2}
        if self.tier_max_calls is None:
            # v2.6.1：deep 档 30→60
            # deep 档需要：三Agent协作反复验证(每轮 4 次 × max_rounds) + 多候选求解
            #   + 子目标分解 + 验证投票 + revise。collab_max_rounds=6 时单协作链就 24 次
            #   调用，30 次预算不够。60 次才能覆盖协作反复验证场景。
            # v2.8.1：deep 档 60→100（评测日志显示 60 在"协作 6 轮 + 子目标 + Lean +
            #   投票 + revise + oracle" 链路下仍耗尽，触发大量「跳过 LLM 调用」；
            #   100 留出余量，避免因预算紧绷导致的误判/跳过，提升难题正确率）
            # standard 档 15→30（覆盖 colab_max_rounds=4 协作 + 验证 + 多候选求解）
            self.tier_max_calls = {"fast": 6, "standard": 30, "deep": 100}
        if self.tier_budget is None:
            # 08-30：standard 480→540（平台时间有空余）。
            # 2026-08-30 修正：deep **必须 = 1200，不能超过
            # max_time_per_question（平台单题硬限 20min = 1200s）**。
            # a2a2871 曾把 deep 抬到 1320，但 orchestrator 的 deadline 用的是
            # max_time_per_question=1200，1320 那 120s 永远拿不到，
            # 反而让 PaperPacer 高估可用预算、收紧不足（最坏情况有超时风险）。
            # 想给难题更多时间应调 deep_quota_ratio（让更多题进 deep），
            # 而不是抬高单题帽——单题帽受平台规则封顶。
            self.tier_budget = {"fast": 120.0, "standard": 540.0, "deep": 1200.0}


# ============================================================
# 响应归一化工具（P0-1 契约防线核心）
# ============================================================

def _normalize_chat_response(resp: Any) -> str:
    """把 client.chat 的返回值统一成字符串。

    平台注入的 client 实现不定，常见返回形态：
      - str: 直接可用
      - dict: {"content": "...", "choices": [...], "message": {...}}
      - list: [{"content": "..."}, ...]
      - 对象: .content / .text / .message.content
      - bytes: 解码为 UTF-8
      - None / 异常: 返回 ""
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, bytes):
        try:
            return resp.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if isinstance(resp, list):
        # 取第一个元素
        for item in resp:
            text = _normalize_chat_response(item)
            if text:
                return text
        return ""
    if isinstance(resp, dict):
        # 常见的几种字典形态
        for key in ("content", "text", "output", "result"):
            if key in resp and resp[key] is not None:
                val = resp[key]
                if isinstance(val, str):
                    return val
                return _normalize_chat_response(val)
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            choice = resp["choices"][0]
            if isinstance(choice, dict):
                # OpenAI 风格: {"message": {"content": ...}} 或 {"text": ...}
                if "message" in choice and isinstance(choice["message"], dict):
                    msg = choice["message"]
                    for key in ("content", "text"):
                        if key in msg and msg[key] is not None:
                            return str(msg[key])
                if "text" in choice and choice["text"] is not None:
                    return str(choice["text"])
            return _normalize_chat_response(choice)
        if "message" in resp and isinstance(resp["message"], dict):
            msg = resp["message"]
            for key in ("content", "text"):
                if key in msg and msg[key] is not None:
                    return str(msg[key])
        if "data" in resp:
            return _normalize_chat_response(resp["data"])
        return ""
    # 普通对象：尝试 .content / .text / .message
    for attr in ("content", "text", "response"):
        try:
            val = getattr(resp, attr, None)
            if val is not None:
                return _normalize_chat_response(val)
        except Exception:
            pass
    try:
        if hasattr(resp, "message") and resp.message is not None:
            return _normalize_chat_response(resp.message)
    except Exception:
        pass
    # 最后兜底：字符串化
    try:
        s = str(resp)
        if s and s != "None" and not s.startswith("<") and not s.startswith("{"):
            return s
    except Exception:
        pass
    return ""


# ============================================================
# ReasoningAgent 平台入口（薄壳）
# ============================================================
class ReasoningAgent:
    """
    MathPilot 数学智能体主类（平台固定入口）。

    solve() 的内部实现已委托给多智能体 Orchestrator，本类仅负责：
    - 接收平台注入的 client；
    - 组装配置；
    - 透传 solve 调用并维持返回格式不变；
    - 平台契约防御：核心模块不可用时降级到内置直答后端。
    """

    def __init__(self, client, *args, **kwargs):
        self.client = client
        self.config = AgentConfig()

        # 允许通过 kwargs 覆盖配置（向后兼容 run_eval.py 的传参）
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "enable_question_type", "extraction_mode",
            "enable_calc_tool",  # 2026-09-01 calc_tool 确定性计算
            "calc_mandatory",  # 2026-09-09 P1-1 裸数值断言打回（计算必须走工具）
            "tool_calc_enabled",  # 2026-09-09 原生工具调用试点（calc_eval）
            "max_total_calls", "max_time_per_question",
            "max_total_time_seconds", "max_tokens_cap",
            "by_enable_fast_path", "use_scoring",
            "use_rubric", "use_challenge",  # 2026-09-06 sq 移植（A/B 开关）
            "max_revise_rounds", "max_workers",
            "use_proof_channel", "use_lemma_accumulation",
            "lemma_domains",
            "max_answer_tokens", "revise_sample_times",
            "use_blueprint", "use_blueprint_dag", "use_sub_goal",
            # DAG 动态评审闭环（#34，2026-09-02 补白名单：此前 CLI --enable_dag_replan
            # 等键被静默丢弃，A/B 静态对照组实际仍是动态，开关无效）
            "enable_dag_replan", "dag_review_reject_count", "dag_replan_max_rounds",
            # 求解前 DAG 强制门独立开关（2026-09-08：默认关=去掉门）
            "dag_replan_gate",
            # 骨架编排层评审（老师 9/2 建议：求解前规划质量门，2026-09-02）
            "enable_skeleton_review", "skeleton_review_max_rounds",
            # 难题深度求解通道
            "enable_difficulty_router", "enable_llm_difficulty",
            # Algebra 专项
            "algebra_force_deep",
            "tier_sample_times", "tier_temperatures", "tier_voting_times",
            "tier_max_completions", "tier_max_calls", "tier_budget",
            "paper_target_time", "paper_min_soft", "paper_total_questions",
            "deep_use_sub_goal", "deep_revise_rounds", "deep_use_playoff",
            "enable_collaborative_deep", "collab_max_rounds",
            # 子目标阶段预算（P1 按档拆分）
            "subgoal_stage_budget_sec", "subgoal_stage_budget_sec_std",
            # 子目标上下文注入模式（老师 9/6：deps 最小依赖 | all 全量，A/B）
            "subgoal_ctx_mode",
            # P2 子目标类型路由（老师 9/9：计算型 terminal / 推理型 inline）
            "subgoal_calc_router",
            # 子目标级 0-LLM lean 代码片编译校验（S1-lite L1，deep 档+lean 可用）
            "enable_subgoal_lean_check",
            # 子目标交叉核对（老师 9/8 建议3：A 确定性冲突闸 0-LLM / B LLM 交叉核对轮）
            "subgoal_conflict_gate", "subgoal_crosscheck_llm",
            # L2 子目标数值/代数断言 Lean 验证（2026-09-08 去门后新钩子）
            "enable_numeric_lean_verify", "lean_numeric_max_per_q",
            # 时间预算（2026-08-28 新增：让动态预算真正生效）
            "critical_tail_seconds", "deep_critical_tail_seconds",
            "deep_quota_ratio",
            # L1 验证优先（2026-08-31）
            "verify_only_seconds",
            # 结构化 bug report 反馈
            "use_bug_report_feedback",
            # Step 2 无条件自改进（IMO2025 论文）
            "enable_self_improve", "self_improve_max", "improve_min_remaining",
            # 易错点记忆注入（2026-09-06 A 档轻量经验）
            "enable_error_lessons",
            # Step 4 bug report 复核
            "enable_feedback_review",
            # 对抗式验证（#16）
            "enable_adversarial_verify", "adversarial_tiers",
            "adversarial_min_confidence", "adversarial_max_tokens",
            "adversarial_max_reasoning",
            "verify_enhance_est_seconds",
            # 检测链（2026-09-06 去 Lean 化；顶替原 Lean 硬验证开关）
            "enable_audit_gate",
            # Lean 双通道（2026-09-06 晚恢复：lean-toolchain 离线可用后接入）
            "enable_lean_verify", "enable_lean_preverify", "lean_preverify_tiers",
            "preverify_max_rounds", "preverify_timeout",
            "lean_gate_all_proofs", "lean_gate_nonproof", "lean_gate_strict",
            "lean_gate_unknown_stop",
            "lean_timeout", "lean_backend", "lean_executable", "lean_project_dir",
            "theorem_memory_enable",
            # lemma 记忆
            "lemma_storage_path",
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])
        # 覆盖 dict 型配置后需确保各档键完整
        self.config.__post_init__()

        self.orchestrator = None
        # 核心模块导入失败时不崩溃：置为 None，solve 时走 fallback backend
        try:
            from agent.orchestrator import Orchestrator
            self.orchestrator = Orchestrator(client, self.config)
        except Exception as e:  # pragma: no cover
            logger.warning("Orchestrator 初始化失败，启用内置直答后端: %s", e)

        logger.info(
            "MathPilot ReasoningAgent (v2 simplified) initialized: "
            "samples=%d, votes=%d, domain_hint=%s, "
            "budget=%d, max_tokens_cap=%d, scoring=%s, fast_path=%s",
            self.config.policy_sample_times,
            self.config.verifier_voting_times,
            self.config.enable_domain_hint,
            self.config.max_total_calls,
            self.config.max_tokens_cap,
            self.config.use_scoring,
            self.config.by_enable_fast_path,
        )

    # 内置直答后端（fallback backend）：核心流水线不可用时保证有输出
    # ------------------------------------------------------------------
    def _fallback_solve(self, problem: str) -> str:
        """零依赖直答：直接要求模型给出最终答案，不经过 orchestrator。"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是数学解题专家。请解答下面的数学题，最后一行必须用"
                        "【最终答案】:<答案> 的格式给出最终答案，答案只写数值、"
                        "表达式或选项，不要多余解释。"
                    ),
                },
                {"role": "user", "content": problem},
            ]
            resp = self.client.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=self.config.max_answer_tokens,
            )
            text = _normalize_chat_response(resp)
            if not text:
                return ""
            # 提取【最终答案】行
            import re
            m = re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            if m:
                ans = m.group(1).strip().split("\n")[0].strip()
                if ans:
                    return ans
            # 兜底：返回最后一个非空行
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines[-1][:500]
            return text.strip()[:500]
        except Exception as e:  # pragma: no cover
            logger.error("fallback_solve failed: %s", e)
            return ""

    def _validate_output(self, result: dict) -> dict:
        """返回前强制校验：final_response 非空且可 JSON 序列化。"""
        fr = result.get("final_response", "")
        if not isinstance(fr, str) or not fr.strip():
            result["final_response"] = "未给出有效解答。"
        # 保证 JSON 可序列化
        if not isinstance(result.get("trace"), list):
            result["trace"] = []
        return result

    def solve(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        """
        求解单道数学题（平台固定调用入口）。

        参数:
            problem: 原始数学题目文本
            metadata: 题目元数据（可缺省，含 idx 字段）

        返回:
            {"final_response": str, "trace": list[dict]}
        """
        if metadata is None:
            metadata = {}
        if problem is None or not str(problem).strip():
            return self._validate_output({
                "final_response": "题目为空。",
                "trace": [{"stage": "input", "note": "empty problem"}],
            })

        # 核心流水线可用 → 走 orchestrator
        if self.orchestrator is not None:
            try:
                result = self.orchestrator.run(problem, metadata)
                if result and isinstance(result, dict):
                    return self._validate_output(result)
            except Exception as e:  # pragma: no cover
                logger.error("orchestrator.run failed, fallback to direct backend: %s", e)

        # 降级：内置直答后端
        answer = self._fallback_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
        return self._validate_output({
            "final_response": answer,
            "trace": [{"stage": "fallback_direct", "note": "orchestrator unavailable"}],
        })

    # 兼容平台直接调用 agent(problem, metadata) 的场景
    def __call__(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        return self.solve(problem, metadata, *args, **kwargs)

    # 兼容平台调用 agent.run(problem, metadata) 的场景
    def run(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        return self.solve(problem, metadata, *args, **kwargs)
