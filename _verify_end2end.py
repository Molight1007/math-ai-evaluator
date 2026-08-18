"""端到端验证：强化后的 _judger_friendly + 升级后的 answers_match。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.formatter import FormatterAgent
from run_eval import answers_match

# 1) formatter 单测
f = FormatterAgent._judger_friendly
cases = [
    (r"\(\frac{\pi}{2}\)", r"\frac{\pi}{2}"),       # 剥 \( \) 包裹（LaTeX 保留）
    (r"\dfrac{1}{6}", r"\frac{1}{6}"),            # dfrac 统一
    (r"条件收敛。", "条件收敛"),                   # 尾标点
    (r"-1/6", r"-1/6"),                            # 负号保护
    (r"\(\pi\)", r"\pi"),                          # 剥包裹（\pi 保留 LaTeX）
]
print("formatter 单测:")
ok = True
for raw, want in cases:
    got = f(raw)
    mark = "✓" if got == want else f"✗ (got {got!r})"
    if got != want:
        ok = False
    print(f"  {raw!r} -> {got!r} 期望 {want!r} {mark}")
print(f"  formatter 全部通过: {ok}")

# 2) 端到端：对 30 题 pred 应用 judger_friendly → 新匹配
rows = [json.loads(l) for l in open("outputs/ab_newbase30.jsonl", encoding="utf-8") if l.strip()]
new = 0
for r in rows:
    pred = f(r.get("predicted", "") or "")
    gold = r.get("gold", "") or ""
    if pred and gold and answers_match(pred, gold):
        new += 1
# 误报检查
regress = [r["id"] for r in rows
           if r.get("correct") and not (lambda pr, g: pr and g and answers_match(pr, g))(f(r.get("predicted", "") or ""), r.get("gold", "") or "")]
print(f"\n端到端（judger_friendly + 新匹配）: {new}/30 ({new/30:.0%})")
print(f"误报: {len(regress)} {regress[:3]}")
