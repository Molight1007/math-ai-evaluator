"""P3 仲裁决策表 + 视角采样 冒烟测试（临时脚本，mock，验证后可删除）"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from user_agent import ReasoningAgent, AgentConfig
from agent.base import TaskContext, Budget, Verdict
from agent.orchestrator import Orchestrator
from agent.verifier import AnswerCluster


class DummyClient:
    def chat(self, messages=None, temperature=None, max_tokens=None, **kwargs):
        return ""


def make_ctx():
    return TaskContext(
        problem="解方程：x^2-5x+6=0", metadata={},
        budget=Budget(max_calls=30),
        start_time=time.time(), deadline=time.time() + 300,
        total_start_time=time.time(), total_deadline=time.time() + 21000,
    )


cfg = AgentConfig()
orch = Orchestrator(DummyClient(), cfg)

# 1) 决策表：高置信 → accept
cl = AnswerCluster("2")
cl.vote_correct, cl.vote_total = 4, 5   # conf=0.8
ctx = make_ctx()
print("1 conf=0.80 →", orch._arbitrate(ctx, {"best_cluster": cl}), "→ 期望 accept")

# 2) 决策表：低置信且轮次未耗尽 → revise
cl2 = AnswerCluster("5")
cl2.vote_correct, cl2.vote_total = 1, 3   # conf≈0.33
ctx2 = make_ctx()
print("2 conf=0.33 →", orch._arbitrate(ctx2, {"best_cluster": cl2}), "→ 期望 revise")

# 3) 决策表：低置信但轮次耗尽 → accept
ctx3 = make_ctx()
ctx3.revise_round = 1  # max_revise_rounds=1 已耗尽
print("3 conf=0.33+轮次耗尽 →", orch._arbitrate(ctx3, {"best_cluster": cl2}), "→ 期望 accept")

# 4) 决策表：无簇 → fallback
print("4 无簇 →", orch._arbitrate(make_ctx(), {"best_cluster": None}), "→ 期望 fallback")

# 5) 视角采样开关接线：config 可覆盖
agent = ReasoningAgent(client=DummyClient(), use_view_sampling=True, use_arbitration=True)
print("5 开关覆盖: view_sampling=%s arbitration=%s → 期望 True True" % (
    agent.config.use_view_sampling, agent.config.use_arbitration))

# 6) 视角采样在 _generate_initial 不崩溃（dummy 空响应 → 占位候选）
agent2 = ReasoningAgent(client=DummyClient(), use_view_sampling=True)
r = agent2.solve("解方程：x^2-5x+6=0", {"idx": 0})
print("6 solve(view) OK | final_response=%r" % (r["final_response"][:30],))
steps = [t for t in r.get("trace", []) if t.get("step") == "solve" and "视角采样" in str(t.get("content", ""))]
print("6b 视角采样 trace:", "有" if steps else "无")

print("\nP3 冒烟完成")
