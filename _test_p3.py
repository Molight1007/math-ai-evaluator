"""P3 视角采样冒烟测试（临时脚本，mock；use_arbitration 决策表已被
origin/main 的 revise 闭环取代，不再测试 _arbitrate）。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from user_agent import ReasoningAgent


class DummyClient:
    def chat(self, messages=None, temperature=None, max_tokens=None, **kwargs):
        return ""


# 1) 视角采样开关接线：config 可覆盖
agent = ReasoningAgent(client=DummyClient(), use_view_sampling=True)
print("1 开关覆盖: view_sampling=%s → 期望 True" % (agent.config.use_view_sampling,))

# 2) 视角采样在 _generate_initial 不崩溃（dummy 空响应 → 占位候选）
r = agent.solve("解方程：x^2-5x+6=0", {"idx": 0})
print("2 solve(view) OK | final_response=%r" % (r["final_response"][:30],))
steps = [t for t in r.get("trace", []) if t.get("step") == "solve" and "视角采样" in str(t.get("content", ""))]
print("2b 视角采样 trace:", "有" if steps else "无")

# 3) 默认关（不显式开启时）
agent2 = ReasoningAgent(client=DummyClient())
print("3 默认: view_sampling=%s rubric=%s challenge=%s → 期望 False False False" % (
    agent2.config.use_view_sampling, agent2.config.use_rubric, agent2.config.use_challenge))

print("\nP3 冒烟完成")

