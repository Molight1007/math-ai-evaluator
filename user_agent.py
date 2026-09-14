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
import re
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
# 2026-09-14：子目标结果的「像不像最终答案」判据
# ------------------------------------------------------------
# 背景（实测发现）：`_rescue_answer` 的来源②原先**直接把** `subgoal_trace[i].result`
# 当答案返回，而子目标结果是**中间推导步**，不是最终答案。实况 official112-016
# 交出去的是：
#   「（该步含未用 <calc> 的易错运算结果，未经系统确认）|10 - sqrt(9.9)| < 1
#     19.9 + (10 - sqrt(9.9))^2 = 20」
# 它避开了「生成失败」占位符，却**伪装成答案**：判分同样是 0，但归因时极易误判成
# "模型答的"，而且把系统提示串塞进了交给平台的答案字段。
# ⇒ 只认两种"明确"形态，其余交给直答兜底。
# ============================================================
_SG_NOTICE_RE = re.compile(r"^\s*[（(][^）)]{0,120}[）)]\s*")   # 行首提示前缀
_SG_NOTICE_HINT = ("未经系统确认", "该步含", "未用 <calc>", "系统提示", "未经验证")
_SG_BOXED_RE = re.compile(r"\\boxed\s*\{([^{}]*)\}")
_SG_SHORT_VALUE_MAX = 60


def _subgoal_answer_candidate(text) -> str:
    """从子目标结果里取「明确是最终答案」的值；取不到返回 ""。

    只接受：
      ① 含 `\\boxed{...}`（子目标自己收口的最终值）→ 取括号内内容；
      ② 剥掉行首提示前缀后是个**短值**（≤60 字符且无换行）。
    多行推导、带系统提示、过长的一律拒收。
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    t = text.strip()
    for _ in range(3):                     # 提示前缀可能叠了多层
        m = _SG_NOTICE_RE.match(t)
        if not m:
            break
        t = t[m.end():].strip()
    if not t or any(h in t for h in _SG_NOTICE_HINT):
        return ""
    m = _SG_BOXED_RE.search(t)
    if m:
        return m.group(1).strip()
    if len(t) <= _SG_SHORT_VALUE_MAX and "\n" not in t:
        return t
    return ""


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
    # 2026-09-12 客观题特化解法（用户要求"保证检测到题型并采取特化技巧"）：
    # 选择/判断/填空三类客观题强制注入特化纪律（逐项判真+反例否证+清点选项 /
    # 绝对化措辞找反例+回定义核对 / 按空序逗号分隔），与"证明题不分流"的既有
    # 结论互不冲突（那一条针对 IMO 证明题）。回退：设为 False 即恢复旧行为。
    objective_tactic_enabled: bool = True

    # ---- calc_tool 确定性计算（2026-09-01，治 value_wrong）----
    enable_calc_tool: bool = True      # 提示词引导 <calc> 标记 + 输出精确求值回填
    # 2026-09-09 P1-1（老师拍板"计算必须用工具"）：行级**裸数值断言**
    # （如 `25*4 = 100`，两侧无字母/中文、无 <calc> 来源）→ 判定心算/自算，
    # 带反馈打回重写一次（方程/结论式含变量放行，不打断推导）。
    # 2026-09-12 用户要求「强制、一定、绝对用工具算」→ **默认开启**：
    # 命中"未用 <calc> 的心算数值断言"即定向重问，要求改写成 <calc>。
    # 回退：`--calc_mandatory false`（或 config 覆盖）。
    calc_mandatory: bool = True
    # 2026-09-12 用户要求「不是不让模型算，而是让易错的根号/组合数/log 走工具」：
    # True → 打回判据只认**易错算子**（开方/根式、对数、指数与自然常数 e、
    # 组合数/排列/阶乘、幂运算、三角函数、取模、求和/积分、π），简单加减乘除
    # 允许模型自算；False → 恢复"任何数值计算都必须走工具"的旧行为。
    # 作用点：calc_tool.find_naked_numeric_asserts(hard_only=...) +
    # solver._maybe_answer_selfcheck 的高危算子门槛。
    # 回退：`--calc_hard_only false`。
    calc_hard_only: bool = True
    # 2026-09-14 改为**默认关闭**：实测无价值 + 有明确成本。
    # 关闭依据（12 题错题回归 `results/wrong12_v1_0914_out.jsonl`）：
    #   · 12/12 题都产出了 1 条预计算，但**只有 1 题（015 的 `fact(2)=2`）与答案相关**，
    #     其余全部无关 —— 例：014 的 gold 是三个特定大数，它猜了
    #     `sum((i+1)*i**2, i, 0, 1000)`；016 的 gold 是 21，它猜了 `10+sqrt(10)`。
    #   · 根因：**"让模型在解题前凭题面猜该算什么"这个前提不成立**，猜的算式质量很差。
    #   · 且与方案 A 功能重叠 —— 方案 A 已把**解题过程中真算出来的** `[计算]` 值
    #     前置注入（`collect_calc_results` → 4 条路径），那才是有效的值。
    #   · 成本不低：本批单题 30–111s（API 不稳时），而单题预算只有 1150s。
    # ⇒ 净收益为负，默认关闭。字段保留，随时可开回。
    # 开启方式：`--enable_calc_prewarm true` 或 env `CALC_PREWARM=1`
    # （注意 `_prewarm_applicable` 判据是 `os.environ.get("CALC_PREWARM","1") == "0"`，
    #   故 env 侧只有设 `0` 才关；默认值由本字段决定）。
    enable_calc_prewarm: bool = False
    # 2026-09-12 用户要求「原本完成的子目标要记录，不能重头再来」：
    # True → 同一题的**已完成子目标结果**跨 run() 调用复用（零 LLM）。
    # 背景：orchestrator 会在 3_solve / 3.5 等阶段多次调用 sub_goal_solver.run()，
    # 原实现每次都重新规划 + 重解全部子目标，重复烧掉本就吃紧的单题预算。
    # 设 False 回到旧行为（每次全量重解）。
    subgoal_reuse_done: bool = True
    # 2026-09-12 用户要求：子目标级「失败二选一」处置。
    # True → 某子目标未产出有效结论时，优先**重做该子目标**（≤2 次）；重做仍失败
    # 或失败原因指向规划/依赖前提 → 记 subgoal_replan_needed 并写入 revise_feedback
    # 交上游重规划（不在子目标循环内新建重规划，避免破坏 depends_on 顺序）。
    # 设 False 回到旧行为（失败即占位放行）。
    subgoal_adaptive_recover: bool = True
    # 2026-09-09 用户洞察：原生工具调用试点（同智能体调 WebSearch 逻辑）——
    # 模型生成 tool_call calc_eval → 执行 calc_tool → 回传 → 继续；默认关待验证
    tool_calc_enabled: bool = False
    # 2026-09-10 L1（用户 9/10 + 李平老师建议）：**答案级工具自洽核验**——
    # 最终答案是纯数值、却没有任何 <calc> 工具来源（心算产物）→ 定向重问一次，
    # 要求把得出答案的算式写成 <calc>；仅在重问结果**带工具来源**时采纳。
    # 零后悔（失败/未改善一律保留原输出）。默认关待 A/B（题均 +1 次 LLM 调用）。
    # 2026-09-12 用户要求「强制用工具算」→ **默认开启**：最终答案为纯数值却没有
    # <calc> 工具来源（心算产物）即定向重问；**仅当新答案能在工具回填结果中找到
    # 来源时才采纳**（见 solver._maybe_answer_selfcheck 的 ok 判定）。
    # 回退：`--answer_selfcheck_enabled false`。
    answer_selfcheck_enabled: bool = True
    # 2026-09-10 L2（用户 9/10 思路 + 李平老师 9/9 建议）：**独立符号建模复核**——
    # 让模型当"数学问题拆解助手"，只把给定数值抽象成变量并输出目标量表达式
    # （禁止自算），由 calc_tool 精确代入求真值，与主链答案比对；不一致则打回
    # 一次，仅当新答案落回该真值才采纳。每题最多 1 次调用。默认关待 A/B。
    symbolic_crosscheck_enabled: bool = False
    symbolic_max_tokens: int = 512
    # 2026-09-12 符号化方程求解通道（用户 9/11 需求）：智能体把题面里「显式给定
    # 的具体数值」剥离存本地，给模型的是**未知数类型**题面；模型只输出方程（组）
    # + 求解目标，具体数值由本地 SymPy 回代算出 —— **模型不参与任何计算**，
    # 且"计算方程式交给工具、接收工具返回结果"。
    # 省时间设计（用户 9/12 硬要求）：剥离/校验/求解全部本地（毫秒~秒级）；
    # 只加 1 次**短**建模调用；工具值与主链答案一致时 **0 额外调用**，
    # 仅分歧才追加 1 次短回传；**不新增候选**（不触发下游验证/Lean 额外成本）。
    symbolic_solve_enabled: bool = False
    symbolic_solve_max_tokens: int = 384     # 建模输出很短（EQUATIONS + TARGET）
    symbolic_solve_feedback: bool = True     # 分歧时把工具结果回传模型定稿
    # 2026-09-12 方案④「把计算从模型手里拿走」：工具求解成功后**答案直接取
    # 工具值**（模型原先的数值被丢弃），而不是只做事后比对 —— 这样最终答案
    # 在架构上由本地计算器产生，模型无法心算。设 False 回到"仅比对/回传"旧行为。
    symbolic_solve_adopt: bool = True

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（大幅缩减）----
    max_revise_rounds: int = 1         # 自纠错 1 轮（A/B 验证 6/6 无损失，输出更易读）
    max_total_calls: int = 150         # LLM 调用预算硬上限（v2.6.1：15→60；v2.7：60→150，
                                        # 覆盖 5 题 batch + 限流重试 + deep 档完整流程
                                        # = classifier 1 + 求解 3 + 投票 6 + self_audit 1
                                        # + revise 1 + lean 转换 1 + collab 6 轮
                                        # + sub_goal 规划 1 + N 个子目标 ≈ 25-30 次/题）

    # ---- 时间限制（2026-09-13 按实测重设；旧值 1200 / 22500 已废止）----
    # 【为什么重设】195 题实测（最近三代代码，`results/*.jsonl` 的 `stage_timers`）：
    #   · deep 档各阶段耗时 **p90 合计 = 2454s**，而旧单题硬顶只有 1200s
    #     ⇒ 绝大多数难题跑到一半被硬墙砍断（deep p50 实测 1230s，恰好压在墙上）；
    #   · standard 档 p50=981s / p90=1338s ⇒ 540s 档位帽严重不足；
    #   · fast 档 p50=681s（设计值仅 120s）⇒ 档位帽形同虚设。
    # 【为什么能放开】平台侧已确认**不设单题时限**：平台评测日志 `deadline_seconds: 0`，
    #   且实测整卷跑 8.89h 未被终止。旧注释里"平台单题硬限 20min / ICMA 同款 1200s"
    #   是跨赛事移植的臆测值 —— 全仓无任何平台下发字段支撑（无 deadline_seconds 解析）。
    # 【防卡死】放开的前提是"单题内部不卡死"，由三线兜底：
    #   (a) PaperPacer 全卷动态预算；(b) 每阶段 `_phase_deadline_guard` 上限；
    #   (c) 各生成循环的 `gen_time_up()` 检查（见 2026-09-13 审计修复）。
    # 关系仍须满足：paper_target_time < max_total_time_seconds。
    # ⚠⚠ 2026-09-13 更正（权威出处推翻此前判断）：
    # 单题 1200s 是**平台硬限**，不是我们能放开的。官方 baseline 仓库
    # github.com/InternLM/Challenge-Cup-2026 的 README「正式评测的并发、时限与
    # 计分」原文：
    #   「每道题的独立进程组有 **1200 秒硬时限**，包含选手模块加载、Agent 初始化
    #     和 solve 执行。超时后平台会终止整个进程组，不保证执行 finally、退出钩子
    #     或其它清理逻辑。」
    #   同节配套：Agent 阶段总硬时限 **6 小时**（不含 Judge）、最多同时运行
    #   **3 个**独立题目进程、超时/异常/缺失题**计 C 且分母不变**。
    # 此前"平台不设单题硬限、1200s 系自设"的判断**是错的** —— 错因是：我们代码
    # 里确实没有解析 deadline_seconds，但平台是**硬杀进程组**，无需下发字段；
    # "整卷 8.89h 未终止"那组数据来自**本地评测**（本地无平台限制），不能外推。
    #
    # 由此的硬结论：
    #   ① 单题**必须主动**在 1200s 内交卷 —— 超时 = 进程组被杀、finally 不执行、
    #      答案根本写不出来 ⇒ 该题计 C（0 分）且分母不变；
    #   ② 全卷 6h × 并发 3 = 64800 题·秒 ÷ 112 题 = **578s/题**。单题 1200s 只对
    #      少数难题可用；若每题都用满，只能做完 54 题，其余 58 题全部超时计 C。
    #      **平均 578s 才是真正的约束。**
    #   ③ 故本字段必须严格 < 1200，给"模块加载 + Agent 初始化 + 格式化输出"留余量。
    # 2026-09-14 上调：1000 → **1150**（用户要求："1000s 太少"）。
    # 演化史与依据（三段，务必连着看）：
    #   · 原值 1150。2026-09-13 二轮下调到 1000，触发点是实测 `official112-000`
    #     跑了 **1201s**，**越过平台 1200s 硬限**（平台会终止整个进程组、该题计 C=0）。
    #   · 当时跨墙的根因是 `agent/base.py` 的单次 `client.chat` **不可中断**，
    #     而 `LLMClient` 超时 180s × **重试 1 次** ⇒ 单次调用最坏 **360s**，
    #     阶段/单题截止点只能在"两次调用之间"生效，故必须为在途调用留足空间。
    #   · 2026-09-13 晚已拆掉那个放大器（`utils/llm_client.py`：**超时不再重试**，
    #     读超时 180→120s）⇒ 单次调用最坏从 **360s 降到 120s**，
    #     "上限必须压到 1000" 的前提不再成立，故回调到 1150
    #     （= 平台硬限 1200 − 50s 模块加载/收尾余量，与 `tier_budget.deep` 对齐）。
    # ⚠ 如实记录仍存的风险：单题上限是**在两次调用之间**判定的，无法中断在途调用
    #   ⇒ 理论最坏 1150 + 120 = **1270s > 1200s**（相对地，旧配置 1150+360=1510s）。
    #   缓解：`critical_tail_seconds`（默认 120s）让最后 120s 内不再启动可选步骤。
    max_time_per_question: int = 1150  # 单题壁钟上限（秒）
    max_total_time_seconds: int = 20700  # Agent 总运行上限（秒）= 6h 硬限(21600) − 4% 余量

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
    self_improve_max: int = 2          # A3（2026-09-11 降本）：每题最多自改进候选数 3→2。
    # 依据：3.3 无条件改进实测只有成本没有收益（smoke6_v3：占单题耗时 29~45%、
    # 总耗时 +34%，正确率 1/6 不变）。配合 A2 条件化（只改有缺陷的候选）进一步压成本。
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
    # 2026-09-13 更正后重设：36000（10h，基于错误前提"平台无总时长"）→ **19500**。
    # 依据：平台全卷硬限 **6 小时 = 21600s**（不含 Judge，见上方权威出处）。
    # 取 19500 = 6h 的 90%，给 Judge / 提交 IO / 冷启动留约 35 分钟余量。
    # 摊到全卷：19500 × 并发3 ÷ 112 题 = **522s/题** —— 这是 PaperPacer 的瞄准点，
    # 低于理论上限 578s（6h × 3 ÷ 112），为"部分题超支"留缓冲。
    # 必须与 max_total_time_seconds(20700) 保持 target < hard 关系。
    paper_target_time: int = 19500      # 全卷墙钟目标（秒，5.42 小时 = 6h 硬限的 90%）
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
    # 2026-09-12 **按实测数据关闭**：2.6 前置形式化在冒烟中 **5/5 题全部 fail**
    # （且都用满 2 轮重试），每题白烧 100-150s（其中大部分是"LLM 把题目翻译成
    # Lean"的耗时，Lean 编译本身仅 3s）。实测结论：模型对题意的理解是正确的，
    # 失败全在 Lean 语言层面（API 不存在 / 值当类型用 / 语法）⇒ **该环节零产出**。
    # 注意：关闭它不影响"Lean 参与评测"—— Lean 的价值在 **3.6 候选级淘汰** 与
    # **6.5 最终答案闸门**（验证完整解答），而非 2.6 的"翻译题目"。
    # 回退：置 True 即恢复（debris 保留，便于赛后用改进后的提示词重试）。
    enable_lean_preverify: bool = False     # 2.6 题目前置形式化（题目转 Lean 声明校验理解，deep 档）
    # 2026-09-12 **按实测数据回退**：曾按用户"lean 一定要用"扩到
    # ("deep","standard")，但同日冒烟实测（051/010/000 三题）显示前置形式化
    # **0/3 通过，且三题全部用满 2 轮重试仍 fail**；报错均为 **Lean 代码层面**
    # （Application type mismatch / expected ';' / failed to synthesize instance），
    # 而非数学理解错误 ⇒ standard 扩展属**纯耗时无产出**（每题 100-150s），已回退。
    # 另：2.6 的耗时主要在"LLM 把题目翻译成 Lean"（20-40s/次），Lean 编译本身仅 3s
    # （日志实测）。deep 档是否保留 preverify，待全量数据再评估。
    lean_preverify_tiers: tuple = ("deep",)  # preverify 适用档位
    preverify_max_rounds: int = 2           # preverify 编译失败重试上限（强制重新审题）
    preverify_timeout: float = 60.0         # preverify 单次编译/转化超时（秒）
    lean_gate_all_proofs: bool = True       # 证明题全档 Lean 硬验证（False 回退仅 deep）
    lean_gate_nonproof: bool = True         # 非证明题候选级 Lean（2026-09-10 打开：用户要求全卷过 Lean，按题适用性豁免客观/概念题）
    lean_gate_nonproof_deep_only: bool = False  # True=非证明题 Lean 仅 deep 档（时间墙护栏；默认 False=全档）
    lean_gate_strict: bool = False          # Lean unknown 时严格拒绝（True 保守拒，默认放行保分）
    lean_gate_unknown_stop: int = 2         # 候选级连续 N 个 unknown 止损（0=关；治证明题整题 verify 空转 563s）
    lean_timeout: float = 60.0              # Lean 单次编译超时（秒）
    lean_backend: str = "mcp"               # 2026-09-11 修复后默认 mcp：根因=本机缺 `Mathlib.olean` 聚合入口，裸 import Mathlib 触发 fatalError；现已自动规范化为 `import Mathlib.Tactic`，mcp 诊断正常（精确 行:列 + goal，增量秒回）；env LEAN_BACKEND 可覆盖
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
    # 2026-09-13 补上**显式声明**（此前**未在 dataclass 声明**，而读取处是
    # `sub_goal_solver.py:693` 的 `getattr(config, "enable_dag_replan", True)`
    # ⇒ **恒为 True、恒开且无法配置**，是典型的"静默恒开"）。
    # 默认关，依据（195 题 `stage_timers` + 45 题专项实测）：
    #   · 它排在**候选入池之后**（`sub_goal_solver.py:680` 之后），对本题得分
    #     **无直接影响**，只是"再评审一遍"；
    #   · **2/3 白跑**："达硬上限 2 轮停止" 94 次 vs "通过评审停止" 46 次；
    #   · 有该事件的题 p50 = 606s vs 无 = 218s（**差 388s**）；
    #   · 每轮 `DagReviewer.review` 是**逐节点 LLM**（实测均评审 11.1 节点/题、
    #     上限 30），过阈值再整树重生成。
    # 需 A/B 复测时显式置 True 或 `--enable_dag_replan true`。
    enable_dag_replan: bool = False
    # ---- 骨架编排层评审（老师 9/2 建议：求解前规划质量门）----
    # 蓝图生成后先提交 LLM 审查子目标是否不适定 / 难度>=原题；有问题重生成再确认，
    # 通过后才进语法审核。LLM 失败/预算不足降级放行不阻断。
    # ⚠ 2026-09-13 由"默认开启（老师明确要求）"改为默认**关**。
    # 依据（195 题 / 604 条 `stage_timers` 实测）：
    #   · 112 题中 **80 题（71%）走满 2 轮仍判 replan、从未收敛**；
    #   · 2.7 阶段耗时：**0 轮组中位 162s vs 走满 2 轮组 576s（差 250–390s/题）**；
    #   · 同族 `dag_replan_gate` 已有 45 题实证"拦得住、修不好"——净正确率 ≈0、
    #     耗时 +23%（正是它被默认关掉的理由）；骨架评审是同一模式，且从未收敛；
    #   · 每轮 = 1 次 32768-token 评审 + 1 次整树重生成。
    # 老师原意是"求解前把关"，但实测**不收敛** ⇒ 机制保留、默认关闭；
    # 需要时置 True（或 `--enable_skeleton_review true`）复测。
    enable_skeleton_review: bool = False
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
            # 2026-09-13 更正后重设（{2000,3200,3600} 基于错误前提，已废止）。
            # 硬约束回顾：全卷 6h × 并发 3 ÷ 112 题 = **578s/题**；单题平台硬限 1200s。
            # 档位帽必须让"全卷平均"落在 578s 以内，把有限时间留给少数难题：
            #   fast     120 → 300   （简单题快速出答案，为难题腾时间）
            #   standard 540 → 750   （主力档位，约平均线 578s 的 1.3 倍）
            #   deep    1200 → 1150  （= 单题硬限留加载余量后的值，仅少数题可用）
            # 加权示意（deep 受 25% 配额限制）：0.25×1150 + 0.55×750 + 0.20×300
            # ≈ 760s > 578s 平均 ⇒ 卷面会逐步落后 ⇒ 由 PaperPacer 动态收紧回平均线。
            # 这正是"把时间花在刀刃上"的执行路径。
            # ⚠ 这三个值是**档位帽（上限）**，不是每题的实发预算：实发由
            # PaperPacer.budget_for() 按全卷余量动态决定（有余量才给满）。
            self.tier_budget = {"fast": 300.0, "standard": 750.0, "deep": 1150.0}
            # 2026-09-14：deep 1000 → **1150**，与 `max_time_per_question` 重新对齐
            # （后者从 1000 回调到 1150，理由见该字段注释：超时不再重试后，
            #  单次在途调用最坏只有 120s，"必须压到 1000"的前提已消失）。


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
            "calc_hard_only",  # 2026-09-12 计算分档（只强制易错算子走工具）
            # 2026-09-13 方案 B 生成前算式预计算（不写白名单 ⇒ CLI/kwargs 覆盖
            # 被静默丢弃，回退开关失效，同 enable_dag_replan 那次的坑）
            "enable_calc_prewarm",
            "subgoal_reuse_done",  # 2026-09-12 已完成子目标跨 run() 复用
            "subgoal_adaptive_recover",  # 2026-09-12 子目标失败二选一（重做/重规划）
            "tool_calc_enabled",  # 2026-09-09 原生工具调用试点（calc_eval）
            # 2026-09-12 定型前审核修复：以下 5 个键此前**不在白名单** → 尽管
            # run_eval.py 有对应 argparse，kwargs 覆盖会在 __init__ 里被静默
            # 丢弃（即文档中写的 `--symbolic_solve_adopt false`、
            # `--answer_selfcheck_enabled false` 等回退路径**实际无效**）。
            "answer_selfcheck_enabled", "symbolic_crosscheck_enabled",
            "symbolic_solve_enabled", "symbolic_solve_feedback",
            "symbolic_solve_adopt",
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
            "lean_gate_nonproof_deep_only",
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

    # 2026-09-13 晚：答案"不可用"判据。与 `agent/formatter.py`, `agent/orchestrator.py`
    # 的同名常量同源；**三处必须同步修改**。
    # ⚠ 口径刻意收窄：**不含** `无解` / `暂无` —— 它们是**合法答案**（「该方程无解」
    #   就是正确答案），旧版 `formatter._REFUSAL_RE` 里有，但那是"换个候选试试"的
    #   宽松判据；这里决定的是"要不要推翻答案重新求"，误判会**覆盖正确解**
    #   （独立验证者实测：唯一候选 answer='无解' 时被覆盖成 '7'）。
    _DEGRADED_ANSWER_RE = re.compile(
        r"生成失败|调用受限|拒绝回答|未给出有效解答|无法作答|子目标求解失败|"
        r"我无法|无法求解|无法解决|不能解决|无法解答",
        re.IGNORECASE,
    )

    @classmethod
    def _is_degraded_answer(cls, text) -> bool:
        """空答案 / 拒绝语 / 占位符 → True（视为"没有答案"）。"""
        if not isinstance(text, str) or not text.strip():
            return True
        return bool(cls._DEGRADED_ANSWER_RE.search(text))

    def _rescue_answer(self, problem: str, result: dict) -> str:
        """最终兜底：绕过整条流水线，独立拿一个答案（2026-09-13 晚新增）。

        用户硬要求「无论超没超时都要把答案生成出来」。本方法是最后一道，
        顺序为：
          ① 诊断里已产出的**候选答案残料**（`diag.pick_diag.cand_answers`）
             —— 任何真实答案都比占位符好（占位符在平台必然判错）；
          ② 子目标求解的**中间结果**（`diag.subgoal_trace[*].result`）——
             子目标阶段在候选生成之前跑，若它跑过就有值；当候选全失败时，
             它是唯一还活着的答案来源；
          ③ `_fallback_solve` 直答（短 prompt + 小 max_tokens，一次调用）。
        三者都拿不到返回 ""，由 `_validate_output` 写"未给出有效解答。"。
        """
        try:
            diag = result.get("diag") or {}
        except Exception:  # noqa: BLE001
            diag = {}
        # ① 候选答案残料
        for _a in ((diag.get("pick_diag") or {}).get("cand_answers") or []):
            if isinstance(_a, str) and not self._is_degraded_answer(_a):
                return _a.strip()
        # ② 子目标中间结果 —— ⚠ 2026-09-14 修复：**只接受"明确是最终答案"的取值**。
        # 原实现直接返回 `subgoal_trace[i].result`，实测 016 交出的是一段
        # "中间推导 + 系统提示前缀"，伪装成答案（判分 0，且污染归因）。
        # 现在交给 `_subgoal_answer_candidate` 做形态校验，不合格就跳到来源③。
        for _sg in (diag.get("subgoal_trace") or []):
            if not isinstance(_sg, dict):
                continue
            _c = _subgoal_answer_candidate(_sg.get("result"))
            # ⚠ 形态校验通过后**还必须过内容校验**：`_subgoal_answer_candidate` 只判
            #   "像不像答案的形态"（boxed / 短单行），拒绝语类短串（如
            #   `[子目标求解失败]`、`无法求解`）形态上是"短单行"、能骗过它。
            #   2026-09-14 由集成探针实测抓到：漏这一步时场景 A 会交出
            #   `[子目标求解失败]` —— 等于把占位符问题原样搬了个位置。
            if _c and not self._is_degraded_answer(_c):
                return _c
        # ③ 直答
        try:
            ans = self._fallback_solve(problem)
        except Exception as e:  # pragma: no cover
            logger.error("rescue fallback_solve failed: %s", e)
            ans = ""
        if ans and isinstance(ans, str) and not self._is_degraded_answer(ans):
            return ans.strip()
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
                    result = self._validate_output(result)
                    # 2026-09-13 晚（用户硬要求「无论超没超时都要把答案生成出来」）：
                    # 最后一层兜底，**独立于 orchestrator 内部那条链**。
                    # 依据：4 题实测里 010/016 的 `final_response` 退化成
                    # `[生成失败] 调用受限或模型拒绝回答`，而 `_validate_output`
                    # 只查"非空" ⇒ 占位符被原样放行、平台必然判错。
                    if self._is_degraded_answer(result.get("final_response", "")):
                        rescued = self._rescue_answer(problem, result)
                        if rescued:
                            result["final_response"] = rescued
                            _tr = result.get("trace")
                            if isinstance(_tr, list):
                                _tr.append({
                                    "agent": "ReasoningAgent",
                                    "step": "final_rescue",
                                    "content": "流水线答案不可用 → 最终兜底直答: "
                                               + rescued[:120],
                                })
                        else:
                            # ⚠ 2026-09-13 晚补齐（独立验证者抓到的缺口）：
                            # 原实现这里只追加 trace、**不替换 final_response**
                            # ⇒ `final_response` 仍是那个占位符，直接漏给平台。
                            # 实测复现：mock orchestrator 返回占位符 + mock 直答超时
                            # ⇒ exit 的 final_response 仍是
                            # `[生成失败] 调用受限或模型拒绝回答`。
                            # 现在三条来源（候选残料 / 子目标结果 / 直答）全耗尽时，
                            # 写入**明确表示无答案**的终态文本，而不是流水线占位符。
                            result["final_response"] = "未给出有效解答。"
                            _tr = result.get("trace")
                            if isinstance(_tr, list):
                                _tr.append({
                                    "agent": "ReasoningAgent",
                                    "step": "final_rescue",
                                    "content": "流水线答案不可用且兜底直答失败，"
                                               "返回终态占位文本",
                                })
                    return result
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
