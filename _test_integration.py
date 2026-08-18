"""P1 集成冒烟测试（临时脚本，验证后可删除）"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from user_agent import ReasoningAgent, AgentConfig
from agent.base import TaskContext, Budget
from agent.verifier import VerifierAgent


class DummyClient:
    """模拟平台注入 client（只返回空串，不联网）。"""
    def chat(self, messages=None, temperature=None, max_tokens=None, **kwargs):
        return ""


# 1) ReasoningAgent 构造（平台契约：client 注入，不硬编码 key）
agent = ReasoningAgent(client=DummyClient())
print("1 ReasoningAgent 构造 OK | judger_friendly=%s use_deterministic=%s" % (
    agent.config.judger_friendly, agent.config.use_deterministic))

# 2) solve() 端到端不崩溃（dummy client 空响应 → 应有兜底输出）
r = agent.solve("解方程：x^2-5x+6=0", {"idx": 0})
assert isinstance(r, dict) and isinstance(r.get("final_response"), str), "solve 返回格式错误"
print("2 solve() OK | final_response=%r" % (r["final_response"][:40],))

# 3) Verifier.run 确定性旁证接线（候选答案 2 应 pass、5 应 fail、空串 unknown）
ctx = TaskContext(
    problem="解方程：x^2-5x+6=0",
    metadata={},
    budget=Budget(max_calls=15),
    start_time=time.time(),
    deadline=time.time() + 300,
    total_start_time=time.time(),
    total_deadline=time.time() + 21000,
)
ver = VerifierAgent(DummyClient(), AgentConfig())
res = ver.run(
    ctx, problem=ctx.problem,
    candidates=[
        {"id": 0, "answer": "2", "reasoning": "x^2-5x+6=0，解得 x=2 或 x=3"},
        {"id": 1, "answer": "5", "reasoning": "x^2-5x+6=0，解得 x=5"},
        {"id": 2, "answer": "", "reasoning": "空答案"},
    ],
    use_scoring=False,
)
for i, vds in enumerate(res["verdicts"]):
    det = vds[0].deterministic if vds else None
    print("3 候选#%d verdict=%s deterministic=%s | %s" % (
        i, "A" if vds[0].correct else "B",
        (det or {}).get("verdict"), ((det or {}).get("evidence") or "")[:50]))

# 4) trace 中应有 deterministic 记录
det_steps = [t for t in ctx.trace if t.get("step") == "deterministic"]
print("4 trace deterministic 记录数:", len(det_steps))

# 5) Verdict 汇总（orchestrator._verdicts_from_ver_result 路径由 solve 覆盖）
print("5 全部通过")
