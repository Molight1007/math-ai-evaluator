import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from lagent.agents import Agent
from lagent.schema import AgentMessage

from llm_client import InternChatClient
from react_agent import run_react


# ==================== PARTICIPANT DESIGN AREA START ====================

POLICY_PROMPT = """你是一个严谨的数学推理智能体。
请解决用户给出的数学问题，并给出清晰推理与最终答案。

要求：
1. 先分析题意和关键条件。
2. 给出必要的推导步骤。
3. 在最后明确写出最终答案，并使用 \\boxed{} 包裹最终答案。

格式要求：最终答案必须以 \\boxed{答案} 的形式给出，例如 \\boxed{72} 或 \\boxed{-1}。
"""


VERIFIER_PROMPT = """你是一个严谨的数学答案验证器。
请对候选解答给出 0-10 的独立打分（整数或一位小数），并简述理由（≤2 句）。

打分标准：
- 10 = 完全正确（最终答案与正确答案一致，推理无误）
- 7-9 = 基本正确（答案正确但有小瑕疵，或推理大致正确答案略有偏差）
- 4-6 = 部分正确（思路对但答案错，或答案对但推理严重缺陷）
- 1-3 = 基本错误（思路错或答案错，但有少量可取之处）
- 0 = 完全错误（答案与正确答案无关或解答完全错误）

输出格式（严格遵循，不要加额外行）：
SCORE: <0-10 的数字>
REASON: <≤2 句理由>
"""


@dataclass
class AgentConfig:
    policy_sample_times: int = 3
    verifier_voting_times: int = 2
    policy_temperature: float = 0.6
    verifier_temperature: float = 0.0
    max_tokens: int = 4096

    # ReAct 配置（融合 DeepMath）
    react_max_steps: int = 30
    react_code_timeout: int = 20
    react_temperature: float = 0.6
    react_max_tokens: int = 8192
    react_enable_thinking: bool = False
    react_wall_clock_timeout: int = 600
    fallback_to_plain_policy: bool = True
    react_is_proof_problem: bool = False


class ReasoningAgent:
    """A simple lagent-based generate-verify-select baseline agent."""

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig()
        self.policy_agent = Agent(
            llm=client,
            template=POLICY_PROMPT,
            name="policy_agent",
        )
        self.verifier_agent = Agent(
            llm=client,
            template=VERIFIER_PROMPT,
            name="verifier_agent",
        )

    def solve(self, problem: str, metadata: Dict) -> Dict:
        # 证明题识别：若 problem 含证明题关键词，设置运行时标志
        proof_keywords = re.compile(
            r"(?i)\b(Prove|Disprove|Show\s+that|Does\s+there\s+exist|Is\s+it\s+true)\b"
            r"|证明|证伪"
        )
        is_proof = bool(proof_keywords.search(problem or ""))
        self.config.react_is_proof_problem = is_proof

        idx = metadata.get("idx", 0)
        candidates, trace = self._generate_candidates(problem, idx)

        if is_proof:
            trace.insert(0, {
                "step": "proof_problem_detected",
                "content": "Problem matched proof keywords; react_is_proof_problem=True",
            })

        scored_candidates = []

        for candidate_id, candidate in enumerate(candidates):
            confidence, verify_trace = self._verify_candidate(
                problem,
                candidate,
                idx,
                candidate_id,
            )
            scored_candidates.append(
                {
                    "content": candidate,
                    "confidence_score": confidence,
                }
            )
            trace.extend(verify_trace)

        best = max(scored_candidates, key=lambda item: item["confidence_score"])
        trace.append(
            {
                "step": "select_final_response",
                "content": f"Selected candidate with confidence {best['confidence_score']:.3f}.",
            }
        )

        # 后处理：确保 final_response 含 \\boxed{}
        final_response = best["content"]
        if "\\boxed{" not in final_response:
            # 尝试从 trace 中提取最后一个 \\boxed{...}
            boxed_matches = re.findall(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", final_response)
            if not boxed_matches:
                # 搜索整个 trace 中的 boxed
                for trace_item in reversed(trace):
                    content = trace_item.get("content", "")
                    if isinstance(content, dict):
                        content = str(content.get("final_response", "")) + str(content.get("react_trace", ""))
                    elif not isinstance(content, str):
                        content = str(content)
                    matches = re.findall(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", content)
                    if matches:
                        boxed_matches = matches
                        break
            if boxed_matches:
                final_response = final_response + f"\n\n\\boxed{{{boxed_matches[-1]}}}"
            else:
                # 最终兜底：用候选末尾片段包裹
                tail = final_response[-50:].strip().replace("\n", " ")
                final_response = final_response + f"\n\n\\boxed{{{tail}}}"

        return {
            "final_response": final_response,
            "trace": trace,
        }

    def _generate_candidates(self, problem: str, idx: int) -> Tuple[List[str], List[Dict]]:
        candidates = []
        trace = []
        for sample_id in range(self.config.policy_sample_times):
            # 主路径：调用 ReAct + Python 沙箱生成候选
            try:
                react_final, react_trace, code_executed = run_react(
                    self.client, problem, self.config
                )
                candidate = react_final
                trace.append({
                    "step": f"react_candidate_{sample_id}",
                    "content": {
                        "code_executed": code_executed,
                        "num_steps": len(react_trace),
                        "final_response": react_final[:500],
                        "react_trace": react_trace,
                    },
                })
            except Exception as exc:  # noqa: BLE001
                candidate = ""
                trace.append({
                    "step": f"react_candidate_{sample_id}_error",
                    "content": f"ReAct failed: {exc}",
                })

            # 兜底：若 ReAct 未产出 \\boxed{} 且开启 fallback，用 lagent policy_agent 生成
            if self.config.fallback_to_plain_policy and "\\boxed{" not in (candidate or ""):
                user_message = AgentMessage(
                    sender="user",
                    content=f"题目：\n{problem}\n\n请给出完整解答。候选编号：{sample_id}",
                )
                response = self.policy_agent(
                    user_message,
                    session_id=f"{idx}:policy:{sample_id}",
                    temperature=self.config.policy_temperature,
                    max_tokens=self.config.max_tokens,
                )
                if candidate:
                    # ReAct 有输出但无 boxed，合并 ReAct 推理 + policy 兜底
                    candidate = response.content + "\n\n" + candidate
                else:
                    candidate = response.content
                trace.append({
                    "step": f"policy_fallback_{sample_id}",
                    "content": {
                        "message": user_message.content,
                        "response": response.content[:500],
                    },
                })

            candidates.append(candidate or "")
        return candidates, trace

    def _verify_candidate(
        self,
        problem: str,
        candidate: str,
        idx: int,
        candidate_id: int,
    ) -> Tuple[float, List[Dict]]:
        scores = []
        trace = []
        for vote_id in range(self.config.verifier_voting_times):
            user_message = AgentMessage(
                sender="user",
                content=(
                    "题目：\n"
                    f"{problem}\n\n"
                    "候选解答：\n"
                    f"{candidate}\n\n"
                    "请对候选解答给出 0-10 打分（10=完全正确，0=完全错误）。\n"
                    "严格按以下两行格式输出：\n"
                    "SCORE: <0-10 的数字>\n"
                    "REASON: <≤2 句理由>"
                ),
            )
            response = self.verifier_agent(
                user_message,
                session_id=f"{idx}:verify:{candidate_id}:{vote_id}",
                temperature=self.config.verifier_temperature,
                max_tokens=1024,
            )
            verdict = response.content
            scores.append(self._parse_score(verdict))
            trace.append(
                {
                    "step": f"verifier_call_{candidate_id}_{vote_id}",
                    "content": {
                        "candidate_id": candidate_id,
                        "message": user_message.content,
                        "response": verdict,
                    },
                }
            )

        confidence = sum(scores) / len(scores) if scores else 0.0
        return confidence, trace

    @staticmethod
    def _parse_score(verdict: str) -> float:
        """从 verifier 响应中解析 0-10 分数，归一化为 [0, 1] 的 confidence。

        解析优先级：
        1. SCORE: N 模式（首选）
        2. 明确短语回退（仅匹配 "完全正确"/"完全错误"/"部分正确" 等明确判定短语，
           不匹配孤立的 "correct"/"incorrect" 以免误判 prompt 描述）
        3. 兜底 0.5（中性 confidence）
        """
        if not verdict:
            return 0.5  # 默认中等 confidence，避免 0/1 极端值

        # 优先解析 SCORE: N 模式
        score_match = re.search(
            r"SCORE\s*[:：]\s*(\d+(?:\.\d+)?)",
            verdict,
            flags=re.IGNORECASE,
        )
        if score_match:
            try:
                raw = float(score_match.group(1))
                # 限制到 [0, 10] 再归一化
                raw = max(0.0, min(10.0, raw))
                return raw / 10.0
            except ValueError:
                pass

        # 明确短语回退（仅匹配高置信度判定短语，不匹配 prompt 中描述的孤立词）
        verdict_lower = verdict.lower()
        if "完全正确" in verdict or "completely correct" in verdict_lower or "fully correct" in verdict_lower:
            return 1.0
        if "完全错误" in verdict or "completely wrong" in verdict_lower or "fully wrong" in verdict_lower:
            return 0.0
        if "部分正确" in verdict or "partially correct" in verdict_lower:
            return 0.5

        # 兜底：无法解析，返回中等 confidence（不根据 "correct"/"incorrect" 猜测，
        # 因为这些词可能出现在 prompt 描述或模型 reasoning 中，不代表最终判定）
        return 0.5


# ===================== PARTICIPANT DESIGN AREA END =====================
