"""简易单题测试脚本 v2.2"""
import sys, json
sys.path.insert(0, ".")
from user_agent import ReasoningAgent, AgentConfig
from utils.llm_client import LLMClient

# 加载第一道题
with open("sample_data/dev.jsonl", "r", encoding="utf-8") as f:
    line = json.loads(f.readline().strip())
problem = line.get("problem", line.get("question", ""))
answer = line.get("answer", "")
metadata = line.get("metadata", {})

print(f"题目: {problem[:200]}")
print(f"参考答案: {answer}")
print("")

config = AgentConfig()
client = LLMClient(config)
agent = ReasoningAgent(client, config)
result = agent.solve(problem, metadata)

final = result.get("final_response", "")
print(f"=== 最终答案 ({len(final)} 字符) ===")
print(final[:1000] if final else "(空)")

trace = result.get("trace", [])
print(f"\n=== Trace 摘要 ({len(trace)} 条记录) ===")
for t in trace:
    print(f"  [{t.get('agent','?')}] {t.get('step','?')}: {str(t.get('content',''))[:150]}")
