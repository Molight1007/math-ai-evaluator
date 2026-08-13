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
    policy_sample_times: int = 3       # 候选解答数量
    policy_temperature: float = 0.3    # 策略采样温度（提高以增加多样性）
    policy_max_tokens: int = 12288     # 策略最大 token（确保思考流+答案完整输出）

    # 蓝图分解（简化版：关闭蓝图，直接用最简 prompt）
    use_blueprint: bool = False        # 蓝图太长，Intern-S 思维流先被蓝图占满

    # 验证模型（评判）
    verifier_voting_times: int = 1     # 每个候选只投 1 票（避免无效重复投票）
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类（可选）
    enable_domain_hint: bool = True    # 是否启用领域提示增强

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（大幅缩减）----
    max_revise_rounds: int = 1         # 自纠错 1 轮（A/B 验证 6/6 无损失，输出更易读）
    max_total_calls: int = 15          # LLM 调用预算硬上限（revise=1 需额外 1-3 次）

    # ---- 时间限制（适配竞赛新规则）----
    max_time_per_question: int = 300   # 单题壁钟时间上限（秒，省下的时间给后面的题）
    max_total_time_seconds: int = 21000  # Agent总运行时间上限

    # ---- 智能体补充部件配置 ----
    max_tokens: int = 12288            # 单次最大 token 数（匹配 policy_max_tokens）
    max_tokens_cap: int = 12288        # 内部 token 裁剪上限（修复：之前 4096 截断严重）
    max_workers: int = 3               # 并发验证线程数（匹配系统并发度=3）
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 自纠错参数 ----
    max_answer_tokens: int = 8192      # solver 单次调用最大 token 数
    revise_sample_times: int = 2       # 自纠错重解候选数

    # ---- 新功能开关（简化）----
    use_scoring: bool = False          # Verifier 不用多维评分（简化，减少误判）
    by_enable_fast_path: bool = True   # 启用 SymPy 快车道求解
    use_proof_channel: bool = False    # 关闭证明题专用通道（简化）
    use_lemma_accumulation: bool = False  # 关闭引理积累（省 token）
    use_sub_goal: bool = False         # 子目标分解补充候选（候选不足/证明题时触发）


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

        # 允许通过 kwargs 覆盖配置（向后兼容 run_eval.py 的传参）
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "extraction_mode",
            "max_total_calls", "max_time_per_question",
            "max_total_time_seconds", "max_tokens_cap",
            "by_enable_fast_path", "use_scoring",
            "max_revise_rounds", "max_workers",
            "use_proof_channel", "use_lemma_accumulation",
            "max_answer_tokens", "revise_sample_times",
            "use_blueprint", "use_sub_goal",
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])

        self.orchestrator = Orchestrator(client, self.config)

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
