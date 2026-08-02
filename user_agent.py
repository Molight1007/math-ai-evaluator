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
    """智能体可调参数（v2.2 简化版，借鉴 ss-main）
    
    适配竞赛规则 v3（2026-07-31）：
    - 并发=3，单题最长=20分钟，Agent最长=6小时
    - 简洁流水线：Classifier → Solver → Verifier → Formatter（无回环）
    """
    # 策略模型（解题）
    policy_sample_times: int = 3       # 候选解答数量
    policy_temperature: float = 0.3    # 策略采样温度（提高以增加多样性）
    policy_max_tokens: int = 12288     # 策略最大 token（确保思考流+答案完整输出）

    # 蓝图分解（已关闭，对 Intern-S 思维流不友好）
    use_blueprint: bool = False

    # 子目标逐步求解（已关闭）
    use_subgoal: bool = False

    # 验证模型（评判）
    verifier_voting_times: int = 1     # 每候选只投 1 票（避免重复投票浪费）
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类
    enable_domain_hint: bool = True

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 简化版控制 ----
    max_total_calls: int = 10          # LLM 调用总上限（从40降至10）

    # ---- 时间限制 ----
    max_time_per_question: int = 300   # 单题时间上限（秒）
    max_total_time_seconds: int = 21000  # Agent总运行时间上限

    # ---- 智能体核心配置 ----
    max_tokens: int = 12288            # 单次最大 token 数
    max_tokens_cap: int = 12288        # 内部 token 裁剪上限（关键：之前 4096 会截断）
    max_workers: int = 3               # 并发验证线程数
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 功能开关（简化）----
    use_scoring: bool = False          # 关闭多维评分
    by_enable_fast_path: bool = True   # 启用 SymPy 快车道


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
            "enable_domain_hint", "extraction_mode",
            "max_total_calls", "max_time_per_question",
            "max_total_time_seconds", "max_tokens_cap",
            "by_enable_fast_path", "use_scoring",
            "use_subgoal",
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])

        self.orchestrator = Orchestrator(client, self.config)

        logger.info(
            "MathPilot v2.2 simplified: samples=%d, votes=%d, budget=%d, "
            "max_tokens_cap=%d",
            self.config.policy_sample_times,
            self.config.verifier_voting_times,
            self.config.max_total_calls,
            self.config.max_tokens_cap,
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


