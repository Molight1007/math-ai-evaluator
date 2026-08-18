"""生成新高数 30 题分层快筛子集（P1 A/B 用，可复现）"""
import json
import random
from collections import defaultdict

SRC = "sample_data/新高数.jsonl"
DST = "sample_data/新高数_quick30.jsonl"
SEED = 20260815
PER_DOMAIN = 3
TARGET = 30

items = []
with open(SRC, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            items.append(json.loads(line))

by_domain = defaultdict(list)
for it in items:
    by_domain[it.get("domain", "未知")].append(it)

rng = random.Random(SEED)
for dom in by_domain:
    rng.shuffle(by_domain[dom])

picked = []
for dom, lst in by_domain.items():
    picked.extend(lst[:PER_DOMAIN])

if len(picked) < TARGET:
    rest = [it for it in items if it not in picked]
    rng.shuffle(rest)
    picked.extend(rest[: TARGET - len(picked)])
else:
    rng.shuffle(picked)
    picked = picked[:TARGET]

with open(DST, "w", encoding="utf-8") as f:
    for it in picked:
        f.write(json.dumps(it, ensure_ascii=False) + "\n")

print(f"写出 {len(picked)} 题 -> {DST}")
print("领域分布:", dict(sorted((d, sum(1 for i in picked if i.get('domain') == d)) for d in set(i.get('domain') for i in picked))))
