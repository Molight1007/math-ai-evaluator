from __future__ import annotations
"""
MathPilot — 基于 Intern-S 系列大模型的数学智能体（多智能体版）
==========================================================

赛题：基于 Intern-S 系列大模型的数学智能体设计与推理创新
发榜单位：上海人工智能实验室

架构（多智能体协作 + 推理自主调控）：
    题型识别 Agent → 通用求解 Agent → 过程校验 Agent → 答案规范化 Agent
    由 Orchestrator 通过共享黑板（TaskContext）调度，并按置信度实现自主调控
    （提前退出 / 追加候选 / 自纠错回环），详见 ``agent/`` 包。

硬性接口规范（不可修改）：
    agent = ReasoningAgent(client=official_client)
    result = agent.solve(problem, metadata)  # -> dict

注意事项：
    - 禁止硬编码 API Key，client 由平台统一注入
    - 禁止使用绝对路径，所有文件读取使用相对路径
    - solve 返回的字典必须支持 JSON 序列化
    - final_response 不可为空
"""

import logging
from dataclasses import dataclass

from agent.orchestrator import Orchestrator

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
    policy_sample_times: int = 3       # 候选解答数量（适配20分钟/题限制）
    policy_temperature: float = 0.2    # 策略采样温度
    policy_max_tokens: int = 12288      # 策略最大 token

    # 蓝图分解（LEAP 启发：先拆后解）
    use_blueprint: bool = True         # 是否启用蓝图分解策略

    # 子目标逐步求解（先规划子目标树，再逐步求解每个子目标，最后合并）
    use_subgoal: bool = False        # 是否启用子目标逐步求解策略（与 use_blueprint 互斥，优先使用子目标）

    # 验证模型（评判）
    verifier_voting_times: int = 2     # 每个候选的投票次数（聚类替代重复投票）
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类（可选）
    enable_domain_hint: bool = True    # 是否启用领域提示增强

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（多智能体核心增量）----
    conf_high: float = 0.75             # 高置信度阈值：直接提前退出（降低以加速）
    conf_low: float = 0.40              # 低置信度阈值：触发自纠错回环（提高以减少无用revise）
    max_revise_rounds: int = 1         # 自纠错回环最大轮数（限1轮，节省时间）
    revise_sample_times: int = 1       # 每轮纠错重解生成的候选数（降低）
    max_total_calls: int = 40          # LLM 调用预算硬上限（40次×~15s≈10分钟，安全余量充足）

    # ---- 时间限制（适配竞赛新规则）----
    max_time_per_question: int = 1100  # 单题壁钟时间上限（秒，~18.3分钟，留安全余量）
    max_total_time_seconds: int = 21000  # Agent总运行时间上限（秒，~5.8小时，留安全余量）

    # ---- 智能体补充部件配置 ----
    max_tokens: int = 4096             # 单次最大 token 数
    max_tokens_cap: int = 4096         # 内部 token 裁剪上限（BUG-6/7 修复）
    max_workers: int = 3               # 并发验证线程数（匹配系统并发度=3）
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 新功能开关 ----
    use_scoring: bool = True           # Verifier 启用多维评分模式
    by_enable_fast_path: bool = True   # 启用 SymPy 快车道求解（需安装 sympy）
    use_proof_channel: bool = True     # 启用证明题专用求解通道
    use_lemma_accumulation: bool = True # 启用引理积累（跨轮复用子结论）


# ============================================================
# ReasoningAgent 平台入口（薄壳）
# ============================================================
class ReasoningAgent:
    """
    MathPilot 数学智能体主类（平台固定入口）。

    solve() 的内部实现已委托给多智能体 Orchestrator，本类仅负责：
    - 接收平台注入的 client；
    - 组装配置；
    - 透传 solve 调用并维持返回格式不变。
    """

    def __init__(self, client, *args, **kwargs):
        self.client = client
        self.config = AgentConfig()

        # 允许通过 kwargs 覆盖配置（向后兼容 local_test.py 的传参）
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "use_blueprint", "extraction_mode",
            "conf_high", "conf_low", "max_revise_rounds",
<<<<<<< HEAD:user_agent.py
            "revise_sample_times", "max_total_calls",
            "max_time_per_question", "max_total_time_seconds",
=======
            "revise_sample_times", "max_total_calls", "use_subgoal",
>>>>>>> 67990f0c90579497998e2434f83e005d4b712edb:submit/user_agent.py
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])

        self.orchestrator = Orchestrator(client, self.config)

        logger.info(
            "MathPilot ReasoningAgent (multi-agent) initialized: "
            "samples=%d, verify_votes=%d, domain_hint=%s, blueprint=%s, "
            "conf=[%.2f,%.2f], revise=%d, budget=%d",
            self.config.policy_sample_times,
            self.config.verifier_voting_times,
            self.config.enable_domain_hint,
            self.config.use_blueprint,
            self.config.conf_high, self.config.conf_low,
            self.config.max_revise_rounds,
            self.config.max_total_calls,
        )

    def solve(self, problem: str, metadata: dict) -> dict:
        """
        求解单道数学题（平台固定调用入口）。

        参数:
            problem: 原始数学题目文本
            metadata: 题目元数据，必含 idx 字段

        返回:
            {"final_response": str, "trace": list[dict]}
        """
        return self.orchestrator.run(problem, metadata)


