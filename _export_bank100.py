"""从题库数据库导出 100 题测试集（新高数题库，固定随机种子可复现）。"""
import json
import random
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = "题库/question_bank.db"
BANK = "新高数"
TARGET = 100
SEED = 20260819
OUT = "sample_data/bank100.jsonl"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT problem_id, question, domain, reference_answer FROM problems WHERE bank_name=?",
    (BANK,),
).fetchall()
conn.close()
print(f"题库 [{BANK}] 共 {len(rows)} 题")

rng = random.Random(SEED)
pool = list(rows)
rng.shuffle(pool)
picked = pool[:TARGET]

os.makedirs("sample_data", exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for r in picked:
        item = {
            "id": r["problem_id"],
            "question": r["question"],
            "domain": r["domain"] or "未知",
            "answer": r["reference_answer"] or "",
        }
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

has_ans = sum(1 for r in picked if (r["reference_answer"] or "").strip())
print(f"导出 {len(picked)} 题 -> {OUT}（含参考答案 {has_ans} 题）")
domains = {}
for r in picked:
    d = r["domain"] or "未知"
    domains[d] = domains.get(d, 0) + 1
print("领域分布:", domains)
