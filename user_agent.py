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
    policy_sample_times: int = 2       # 候选解答数量
    policy_temperature: float = 0.3    # 策略采样温度（提高以增加多样性）
    policy_max_tokens: int = 24576     # 策略最大 token（上限，模型实际用 3-7K）

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
    max_tokens: int = 24576            # 单次最大 token 数（匹配 policy_max_tokens）
    max_tokens_cap: int = 24576        # 内部 token 裁剪上限（对齐 ICMA reasoning 24576）
    max_workers: int = 3               # 并发验证线程数（匹配系统并发度=3）
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 自纠错参数 ----
    max_answer_tokens: int = 8192      # solver 单次调用最大 token 数
    revise_sample_times: int = 2       # 自纠错重解候选数

    # ---- 新功能开关（简化）----
    use_scoring: bool = False          # Verifier 不用多维评分（简化，减少误判）
    enable_deterministic: bool = True  # 确定性硬否决（v2.8）：SymPy 代入回验 fail 淘汰候选、unknown 放行
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

    # ---- 难题深度求解通道（v2.5）----
    # 三级档位资源分配：fast（快答）/ standard（标准，== 现状）/ deep（深度）
    enable_difficulty_router: bool = True   # 总开关；关闭则全卷走 standard（回归现状）
    enable_llm_difficulty: bool = True      # 难题识别第二层：LLM 自评难度（1 次小调用）
    # 2026-08-30 Algebra 专项：实测无效已回滚（45 题 Algebra 仍 1/11，
    # v3 33.3% < ab_review 35.6%），保留开关但默认关闭
    algebra_force_deep: bool = False
    tier_sample_times: dict = None          # 每档候选数 {fast:1, standard:2, deep:4}
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
    collab_max_rounds: int = 6              # 协作验证循环最大轮数（未通过则反复审查修正，时间充裕时保证高正确率）
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

    # ---- Lean 形式化硬验证（deep 档证明题门禁，v2.5+LeanBridge）----
    # 仅对 deep 档且 domain∈{证明,证明题} 的候选执行；fast/standard 档不触发。
    # verdict=proof_valid → 候选计入有效；proof_invalid → 淘汰并注入 revise 反馈；
    # unknown（Lean 环境缺失/超时/翻译错误）→ 按 lean_gate_strict 决定降级放行或保守拒绝。
    enable_lean_verify: bool = True         # 总开关：证明题启用 Lean 硬验证（v2.8 扩展到全部档位）
    lean_gate_all_proofs: bool = True       # v2.8：扩展到全部证明题（含 standard 档）；False=仅 deep 档
    lean_gate_nonproof_deep_only: bool = False  # 2026-09-01：非证明题（解答题）是否仅 deep 档走 Lean；
                                                # False=全档启用（用户要求所有题过 Lean）
    lean_gate_strict: bool = False          # unknown 时是否保守拒绝；False=降级放行（不损失分数）
    lean_timeout: float = 60.0              # 单次 Lean 编译超时（秒）
    lean_executable: str = ""               # Lean 可执行文件名（默认自动探测本地工具链）
    lean_project_dir: str = ""              # 带 Mathlib 依赖的 Lean 工程目录（默认自动探测 <root>/lean下载版/test_mathlib）
    # ---- Lean 前置形式化验证 + 子目标主路径（v2.9）----
    enable_lean_preverify: bool = True      # 前置形式化验证开关：解题前把题目转 Lean 声明校验理解
    preverify_max_rounds: int = 2           # 前置形式化失败后的修正重试上限
    preverify_timeout: float = 60.0         # 前置形式化单轮超时（秒）
    # 前置形式化只在哪些档位执行（2026-08-29 新增，08-30 二次修正）
    # D5 实测 preverify 挤占求解预算；08-30 debug15 实测：**全档位反而更差**
    # （21% vs 按档位 36% vs Step2 50%）——standard 加 formal_spec 提示干扰
    # 求解。**回滚到只 deep 档**（难题 Lean 价值最大）。
    # 2026-09-01 用户明确：比赛几乎只有证明题+解答题，两者都要走 Lean 两阶段
    # （阶段一 preverify 题目理解→Lean 编译→失败带错误重新理解；阶段二
    #  lean_gate 答案审核→失败定位修正）。故选档 deep+standard 全档执行
    # （fast 快车道跳过）；如 A/B 数据证明 standard 干扰求解再回退。
    lean_preverify_tiers: list = field(default_factory=lambda: ["deep", "standard"])
    # 跨题定理记忆（2026-08-29 新增）
    # 记录 lean_gate"编译验证通过"的定理按域持久化，同域新题注入复用，
    # 跳过重复检索+翻译试错。应对"定理调用复用性高、反复检索浪费"。
    theorem_memory_enable: bool = True
    theorem_memory_path: str = ""      # 空 = 默认 data/theorem_memory.json
    theorem_memory_top_k: int = 5      # 每题注入的高频定理数
    enable_subgoal_main_path: bool = True   # 子目标细化作为主路径（前置验证后统一跑一次）
    # ---- 骨架 Lean 语法审核 + leansearch（#28 / #31）----
    enable_sketch_audit: bool = True        # 题目前置形式化后，生成骨架并用 Lean 审核严谨性（#28）
    # 2026-08-30：默认开启。官方语义 API（leansearch.net）质量高 + 空集信号
    # + 子目标级查询后，证明类题目真实受益；计算题检索无害（如无结果显式告知）
    use_leansearch: bool = True
    # ---- Blueprint DAG 分解（LEAP Stage 1，#27）----
    use_blueprint_dag: bool = True          # 子目标规划先用 BlueprintPlanner 生成 AND-OR DAG 再求解（失败自动回退原规划）
    # ---- Stage 3 迭代精炼 + lemma 记忆（#29/#30/#32/#33）----
    lemma_storage_path: str = ""            # LemmaMemory 跨题持久化路径（空=仅内存）
    use_refiner: bool = False               # 整树搭桥后执行 Stage 3 sorry 迭代精炼（#32，默认关闭先试）

    def __post_init__(self):
        """初始化三级档位配置表默认值（平台提交版默认关闭 LLM 自评? 否，默认开启）。"""
        if self.tier_sample_times is None:
            self.tier_sample_times = {"fast": 1, "standard": 2, "deep": 4}
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

        # 平台 Lean 环境探测（2026-08-31，零重量）：仅当仓库存在 deploy/.probe
        # 标记时执行 deploy/probe_lean.sh，输出 PROBE| 前缀日志（进评测日志）。
        # 目的：用下一次正式提分提交顺带回答"平台能否跑 Lean/Mathlib"——
        #   关0 预装？关1 GitHub/tuna 网络？关2 自带二进制能否执行？
        # 任何异常都吞掉，绝不阻塞主流程（评测成绩不受影响）。
        self._maybe_run_lean_probe()

        # 允许通过 kwargs 覆盖配置（向后兼容 run_eval.py 的传参）
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "enable_question_type", "extraction_mode",
            "enable_calc_tool",  # 2026-09-01 calc_tool 确定性计算
            "max_total_calls", "max_time_per_question",
            "max_total_time_seconds", "max_tokens_cap",
            "by_enable_fast_path", "use_scoring",
            "max_revise_rounds", "max_workers",
            "use_proof_channel", "use_lemma_accumulation",
            "lemma_domains",
            "max_answer_tokens", "revise_sample_times",
            "use_blueprint", "use_blueprint_dag", "use_sub_goal",
            # 难题深度求解通道
            "enable_difficulty_router", "enable_llm_difficulty",
            # Algebra 专项
            "algebra_force_deep",
            "tier_sample_times", "tier_temperatures", "tier_voting_times",
            "tier_max_completions", "tier_max_calls", "tier_budget",
            "paper_target_time", "paper_min_soft", "paper_total_questions",
            "deep_use_sub_goal", "deep_revise_rounds", "deep_use_playoff",
            "enable_collaborative_deep", "collab_max_rounds",
            # 时间预算（2026-08-28 新增：让动态预算真正生效）
            "critical_tail_seconds", "deep_critical_tail_seconds",
            "deep_quota_ratio",
            # L1 验证优先（2026-08-31）
            "verify_only_seconds",
            # 结构化 bug report 反馈
            "use_bug_report_feedback",
            # Step 2 无条件自改进（IMO2025 论文）
            "enable_self_improve", "self_improve_max",
            # Step 4 bug report 复核
            "enable_feedback_review",
            # 对抗式验证（#16）
            "enable_adversarial_verify", "adversarial_tiers",
            "adversarial_min_confidence", "adversarial_max_tokens",
            "adversarial_max_reasoning",
            # Lean 硬验证
            "enable_lean_verify", "lean_gate_strict", "lean_timeout", "lean_executable",
            "lean_gate_nonproof", "lean_gate_nonproof_deep_only",
            "enable_sketch_audit", "use_leansearch",
            # 前置形式化验证（rounds 影响预算消耗：每次编译 ~21s）
            "preverify_max_rounds", "preverify_timeout",
            # 前置形式化按档位开关
            "lean_preverify_tiers",
            # 跨题定理记忆
            "theorem_memory_enable", "theorem_memory_path",
            "theorem_memory_top_k",
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

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 平台 Lean 环境探测（零重量，2026-08-31）
    # ------------------------------------------------------------------
    def _maybe_run_lean_probe(self) -> None:
        """deploy/.probe 标记存在时跑探测脚本，输出 PROBE| 日志。

        探测结果只进 stderr（评测日志会捕获），**不改任何求解行为**：
        - 平台无 lean → 探测打印 not_found，主流程照常走 AI 判分降级
        - 平台有 lean → 探测打印预装版本，后续提交可接入 lean_gate
        全程 try/except + 30s 超时，任何失败静默。
        """
        try:
            marker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "deploy", ".probe")
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "deploy", "probe_lean.sh")
            if not (os.path.exists(marker) and os.path.exists(script)):
                return
            import subprocess
            proc = subprocess.run(
                ["bash", script],
                capture_output=True, text=True, timeout=30,
            )
            out = (proc.stdout or "").strip()
            if out:
                # 打印到 stderr 走评测日志；同时进 logger 便于本地排查
                sys.stderr.write(out + "\n")
                for line in out.splitlines():
                    if line.startswith("PROBE|"):
                        logger.info("[lean-probe] %s", line)
        except Exception as exc:  # noqa: BLE001 - 探测失败绝不影响主流程
            logger.warning("[lean-probe] 探测跳过（异常）: %s", str(exc)[:120])

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
