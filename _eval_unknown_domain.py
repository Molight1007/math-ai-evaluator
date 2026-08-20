"""评估"未知"领域题的现有分类能力（关键词部分，零 API 成本）。"""
import json
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.classifier import _keyword_classify

rows = [json.loads(l) for l in open("sample_data/bank100.jsonl", encoding="utf-8") if l.strip()]
unknown = [r for r in rows if r.get("domain") in ("未知", "", None)]
print(f"bank100 中'未知'题: {len(unknown)} 道\n")

# 1) 关键词分类命中情况
hit = 0
result_domains = Counter()
for r in unknown:
    domain, score = _keyword_classify(r["question"])
    if score >= 2:
        hit += 1
    result_domains[domain or "未命中"] += 1

print(f"关键词分类命中（score>=2）: {hit}/{len(unknown)} ({hit/len(unknown):.0%})")
print("分类结果分布（含未命中）:")
for d, n in result_domains.most_common():
    print(f"  {d}: {n}")

# 2) 未命中的题长什么样（抽 8 道看内容）
print("\n未命中题抽样（前 8 道，看实际是什么领域）:")
missed = [r for r in unknown if _keyword_classify(r["question"])[1] < 2]
for r in missed[:8]:
    q = r["question"].replace("\n", " ")[:90]
    print(f"  [{r['id'][:24]}] {q}")
