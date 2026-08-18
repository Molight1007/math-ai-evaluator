"""P2 rubric 判分逻辑单测（临时脚本，mock LLM，验证后可删除）"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from user_agent import AgentConfig
from agent.base import TaskContext, Budget
from agent.verifier import VerifierAgent


class DummyClient:
    def chat(self, messages=None, temperature=None, max_tokens=None, **kwargs):
        return ""


def make_ctx(problem="解方程：x^2-5x+6=0"):
    return TaskContext(
        problem=problem, metadata={},
        budget=Budget(max_calls=30),
        start_time=time.time(), deadline=time.time() + 300,
        total_start_time=time.time(), total_deadline=time.time() + 21000,
    )


CANDIDATES = [
    {"id": 0, "answer": "2", "reasoning": "x^2-5x+6=0，解得 x=2 或 x=3"},
    {"id": 1, "answer": "5", "reasoning": "x^2-5x+6=0，解得 x=5"},
    {"id": 2, "answer": "", "reasoning": "空答案"},
]

# 场景1：rubric A + 确定性 pass → 2 张正确票
ver = VerifierAgent(DummyClient(), AgentConfig())
ver._vote_one_rubric = lambda ctx, problem, text: {
    "verdict": "A", "confidence": 0.95, "error_type": "无",
    "step_index": None, "reason": "答案正确"}
res = ver.run(make_ctx(), problem="解方程：x^2-5x+6=0", candidates=CANDIDATES[:1],
              use_rubric=True, use_deterministic=True)
v0 = res["verdicts"][0]
print("1 rubric A+det pass:", [(v.correct, v.raw[:20]) for v in v0], "→ 期望 [True, True]")

# 场景2：rubric A 但确定性 fail → 硬否决全 False
ver2 = VerifierAgent(DummyClient(), AgentConfig())
ver2._vote_one_rubric = lambda ctx, problem, text: {
    "verdict": "A", "confidence": 0.95, "error_type": "无",
    "step_index": None, "reason": "答案正确"}
res2 = ver2.run(make_ctx("解方程：x^2-5x+6=0"), problem="解方程：x^2-5x+6=0",
                candidates=[{"id": 0, "answer": "5", "reasoning": "解为 5"}],
                use_rubric=True, use_deterministic=True)
v2 = res2["verdicts"][0]
print("2 rubric A+det fail:", [(v.correct, v.raw[:22]) for v in v2], "→ 期望 [False, False]")

# 场景3：rubric B + 错因定位 → feedback 结构化
ver3 = VerifierAgent(DummyClient(), AgentConfig())
ver3._vote_one_rubric = lambda ctx, problem, text: {
    "verdict": "B", "confidence": 0.8, "error_type": "计算错误",
    "step_index": 3, "reason": "第3步代入符号错误，应取负号分支"}
res3 = ver3.run(make_ctx(), problem="解方程：x^2-5x+6=0", candidates=CANDIDATES[:1],
                use_rubric=True, use_deterministic=False)
fb = res3["verdicts"][0][0].feedback
print("3 rubric B feedback:", repr(fb), "→ 期望含 步骤3/计算错误/代入符号错误")

# 场景4：rubric 解析失败 → 保守放行
ver4 = VerifierAgent(DummyClient(), AgentConfig())
res4 = ver4.run(make_ctx(), problem="解方程：x^2-5x+6=0", candidates=CANDIDATES[:1],
                use_rubric=True, use_deterministic=False)
v4 = res4["verdicts"][0][0]
print("4 rubric parse fail:", v4.correct, v4.raw, "→ 期望 True rubric_parse_failed")

# 场景5：反例挑战 hard_fail → 全错 + 追加 counterexample 票
ver5 = VerifierAgent(DummyClient(), AgentConfig())
ver5._vote_one_rubric = lambda ctx, problem, text: {
    "verdict": "B", "confidence": 0.6, "error_type": "结论错误",
    "step_index": None, "reason": "结论可疑"}
ver5._challenge_counterexample = lambda ctx, problem, text, ans: {
    "hard_fail": True, "evidence": "反例验证成功: n^2<n 在 {n: -10} 处不成立"}
res5 = ver5.run(make_ctx(), problem="证明 n^2<n 恒成立", candidates=[
    {"id": 0, "answer": "n^2<n", "reasoning": "因为 n 是正数所以成立"}],
    use_rubric=True, use_deterministic=False, use_challenge=True)
v5 = res5["verdicts"][0]
print("5 challenge hard_fail:", [(v.correct, v.raw[:22]) for v in v5],
      "→ 期望 rubric B False + counterexample False")

print("\nP2 单测完成")
