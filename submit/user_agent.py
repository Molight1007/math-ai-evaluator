"""
MathPilot — 基于 Intern-S 系列大模型的数学智能体
==================================================
赛题：基于 Intern-S 系列大模型的数学智能体设计与推理创新
发榜单位：上海人工智能实验室

架构：题型分类 → 多候选生成 → 多重验证 → 最优选择

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
import traceback
from dataclasses import dataclass
from typing import Optional

from prompts.policy import (
    POLICY_SYSTEM, get_domain_hint,
    get_policy_system, build_blueprint_user_message, USE_BLUEPRINT_DEFAULT,
)
from prompts.verifier import VERIFIER_SYSTEM, VERIFIER_USER_TEMPLATE
from utils.extract import extract_final_answer, format_response, safe_json_serialize

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


# ============================================================
# 题型分类常量
# ============================================================
CLASSIFY_PROMPT = """你是一位数学题目分类专家。请判断以下题目属于哪个数学领域。

可选领域：偏微分方程、复分析、拓扑学、运筹学、代数、数论、几何、概率论、统计学、泛函分析、常微分方程、组合数学、图论、数值分析、实分析、离散数学、数学物理、抽象代数

请只输出领域名称，不要输出任何其他内容。"""

# 已知有效领域（与 prompts/policy.py 中 DOMAIN_HINTS 键保持一致）
_KNOWN_DOMAINS: frozenset[str] = frozenset({
    "偏微分方程", "复分析", "拓扑学", "运筹学", "代数", "数论",
    "几何", "概率论", "统计学", "泛函分析", "常微分方程", "组合数学",
    "图论", "数值分析", "实分析", "离散数学", "数学物理", "抽象代数",
})


# ============================================================
# ReasoningAgent 核心类
# ============================================================
class ReasoningAgent:
    """
    MathPilot 数学智能体主类。

    平台调用方式：
        from user_agent import ReasoningAgent
        agent = ReasoningAgent(client=official_client)
        result = agent.solve(problem, metadata)

    client 由评测平台统一注入，提供 chat 方法：
        client.chat(messages, temperature, max_tokens) -> str
    """

    def __init__(self, client, *args, **kwargs):
        """
        初始化智能体。

        参数:
            client: 平台注入的 LLM 客户端，提供 chat 方法调用 Intern-S API
            *args, **kwargs: 可扩展参数（当前未使用）
        """
        self.client = client
        self.config = AgentConfig()

        # 允许通过 kwargs 覆盖配置
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "use_blueprint",
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])

        logger.info(
            "MathPilot ReasoningAgent initialized: "
            "samples=%d, verify_votes=%d, domain_hint=%s, blueprint=%s",
            self.config.policy_sample_times,
            self.config.verifier_voting_times,
            self.config.enable_domain_hint,
            self.config.use_blueprint,
        )

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def solve(self, problem: str, metadata: dict) -> dict:
        """
        求解单道数学题（平台固定调用入口）。

        参数:
            problem: 原始数学题目文本
            metadata: 题目元数据，必含 idx 字段

        返回:
            {"final_response": str, "trace": list[dict]}
        """
        idx = metadata.get("idx", "unknown")
        trace: list[dict] = []

        try:
            # 第 0 步：题型分类（可选）
            domain = None
            if self.config.enable_domain_hint:
                domain = self._classify_domain(problem)
                logger.info("[%s] Domain classified: %s", idx, domain)
                trace.append({
                    "step": "classify",
                    "content": f"题型分类结果: {domain}" if domain else "分类失败，使用通用策略",
                })

            # 第 1 步：生成候选解答
            candidates = self._generate_candidates(problem, domain)
            logger.info("[%s] Generated %d candidates", idx, len(candidates))
            trace.append({
                "step": "generate",
                "content": f"生成 {len(candidates)} 个候选解答",
                "candidates": [
                    {"id": c["id"], "summary": c["answer"][:100]}
                    for c in candidates
                ],
            })

            # 第 2 步：验证候选
            verified = self._verify_candidates(problem, candidates)
            logger.info("[%s] Verified candidates: best conf=%.2f", idx,
                       verified[0]["confidence"] if verified else 0)
            trace.append({
                "step": "verify",
                "content": "验证候选解答",
                "verification": [
                    {"id": v["id"], "confidence": v["confidence"]}
                    for v in verified
                ],
            })

            # 第 3 步：选择最优解答
            best = verified[0] if verified else None
            if best is None:
                # 极端回退：直接返回第一个候选
                best = candidates[0] if candidates else {
                    "answer": "无法求解",
                    "confidence": 0.0,
                }

            final_response = format_response(best["answer"])
            logger.info("[%s] Final answer: %s", idx, final_response)
            trace.append({
                "step": "finalize",
                "content": f"最终答案: {final_response} (置信度: {best.get('confidence', 0):.2f})",
            })

            return safe_json_serialize({
                "final_response": final_response,
                "trace": trace,
            })

        except Exception as e:
            logger.error("[%s] Solve failed: %s", idx, e)
            logger.debug(traceback.format_exc())
            return {
                "final_response": "",
                "trace": trace + [{
                    "step": "error",
                    "content": f"求解异常: {type(e).__name__}: {str(e)}",
                }],
            }

    # ----------------------------------------------------------
    # 题型分类
    # ----------------------------------------------------------
    def _classify_domain(self, problem: str) -> Optional[str]:
        """
        识别题目的数学领域（18 选 1 或 None）。

        使用 Intern-S 自身进行分类，temperature=0 保证稳定性。
        解析失败的边界情况返回 None，后续使用通用策略。
        """
        try:
            response = self.client.chat(
                messages=[
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": problem},
                ],
                temperature=0.0,
                max_tokens=64,
            )
            domain = response.strip()
            if domain in _KNOWN_DOMAINS:
                return domain
            logger.debug("Unknown domain classification: %s", domain)
            return None
        except Exception as e:
            logger.warning("Domain classification failed: %s", e)
            return None

    # ----------------------------------------------------------
    # 候选解答生成
    # ----------------------------------------------------------
    def _generate_candidates(self, problem: str,
                             domain: Optional[str] = None) -> list[dict]:
        """
        生成多个候选解答。

        对同一题目多次采样（temperature > 0），利用 LLM 的多样性
        产生不同视角的解答。每个候选包含完整推理过程和答案。

        返回: [{"id": 0, "answer": "...", "reasoning": "..."}, ...]
        """
        candidates = []
        for i in range(self.config.policy_sample_times):
            try:
                # 构建消息
                if self.config.use_blueprint:
                    system_prompt = get_policy_system(use_blueprint=True)
                    domain_hint_text = get_domain_hint(domain) if domain else ""
                    user_content = build_blueprint_user_message(
                        problem, domain_hint_text
                    )
                else:
                    system_prompt = POLICY_SYSTEM
                    user_content = problem
                    if domain:
                        hint = get_domain_hint(domain)
                        user_content = hint + "\n" + problem

                response = self.client.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=self.config.policy_temperature,
                    max_tokens=self.config.policy_max_tokens,
                )

                answer = extract_final_answer(response)
                candidates.append({
                    "id": i,
                    "answer": answer,
                    "reasoning": response,
                })
                logger.debug("Candidate %d: answer='%s'", i, answer)

            except Exception as e:
                logger.warning("Candidate %d generation failed: %s", i, e)
                candidates.append({
                    "id": i,
                    "answer": "",
                    "reasoning": f"[生成失败] {e}",
                })

        # 如果所有候选都失败，添加应急回退
        if not candidates or all(c["answer"] == "" for c in candidates):
            return [{"id": 0, "answer": "无法求解", "reasoning": "全部候选生成失败"}]

        return candidates

    # ----------------------------------------------------------
    # 候选解答验证
    # ----------------------------------------------------------
    def _verify_candidates(self, problem: str,
                           candidates: list[dict]) -> list[dict]:
        """
        对每个候选解答进行多次投票验证并返回按置信度降序排列的结果。
        """
        verified = []
        for candidate in candidates:
            if not candidate["answer"]:
                verified.append({
                    "id": candidate["id"],
                    "answer": candidate["answer"],
                    "reasoning": candidate["reasoning"],
                    "confidence": 0.0,
                    "correct_votes": 0,
                    "total_votes": 0,
                })
                continue
            verified.append(self._vote_on_candidate(problem, candidate))

        verified.sort(key=lambda x: x["confidence"], reverse=True)
        return verified

    def _vote_on_candidate(self, problem: str, candidate: dict) -> dict:
        """对单个候选解答进行多轮投票，返回带置信度的验证结果。"""
        correct_votes = 0
        total_votes = self.config.verifier_voting_times

        for _ in range(total_votes):
            try:
                user_msg = VERIFIER_USER_TEMPLATE.format(
                    problem=problem,
                    candidate_answer=candidate["reasoning"][:3000],
                )
                response = self.client.chat(
                    messages=[
                        {"role": "system", "content": VERIFIER_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=self.config.verifier_temperature,
                    max_tokens=256,
                )
                if self._is_correct_vote(response):
                    correct_votes += 1
            except Exception as e:
                logger.warning("Verification vote failed: %s", e)
                total_votes -= 1

        total = max(total_votes, 1)
        return {
            "id": candidate["id"],
            "answer": candidate["answer"],
            "reasoning": candidate["reasoning"],
            "confidence": round(correct_votes / total, 4),
            "correct_votes": correct_votes,
            "total_votes": total,
        }

    @staticmethod
    def _is_correct_vote(response: str) -> bool:
        """
        解析验证器的投票结果。

        支持多种输出格式：
        - VERDICT: A / VERDICT: B
        - 纯输出 A / B
        - CORRECT / INCORRECT
        - 正确 / 错误
        """
        text = response.strip().upper()
        # VERDICT 格式
        if "VERDICT: A" in text or "VERDICT:A" in text:
            return True
        if "VERDICT: B" in text or "VERDICT:B" in text:
            return False
        # 中英文肯定/否定关键词（中文不受 upper() 影响）
        if "CORRECT" in text or "正确" in text:
            return True
        if "INCORRECT" in text or "错误" in text or "WRONG" in text:
            return False
        # 模糊匹配：最后一行以 A 或 B 结尾
        lines = response.strip().split("\n")
        last = lines[-1].strip().upper() if lines else ""
        if last in ("A", "B"):
            return last == "A"
        # 默认：保守判对
        return True
