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

try:
    from agent.orchestrator import Orchestrator
except ImportError:  # 作为 submit 子包导入时（如评测器以项目根为 sys.path）
    from submit.agent.orchestrator import Orchestrator

logger = logging.getLogger("MathPilot")


# ============================================================
# 配置
# ============================================================
@dataclass
class AgentConfig:
    """智能体可调参数（选手可自由优化）"""
    # 策略模型（解题）
    policy_sample_times: int = 4       # 候选解答数量
    policy_temperature: float = 0.6    # 策略采样温度
    policy_max_tokens: int = 4096      # 策略最大 token

    # 蓝图分解（LEAP 启发：先拆后解）
    use_blueprint: bool = True         # 是否启用蓝图分解策略

    # 验证模型（评判）
    verifier_voting_times: int = 2     # 每个候选的投票次数
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类（可选）
    enable_domain_hint: bool = True    # 是否启用领域提示增强

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（多智能体核心增量）----
    conf_high: float = 0.8             # 高置信度阈值：直接提前退出
    conf_low: float = 0.4              # 低置信度阈值：触发自纠错回环
    max_revise_rounds: int = 2         # 自纠错回环最大轮数
    revise_sample_times: int = 2       # 每轮纠错重解生成的候选数
    max_total_calls: int = 60          # LLM 调用预算硬上限（防超时/超额）


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
            "revise_sample_times", "max_total_calls",
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
