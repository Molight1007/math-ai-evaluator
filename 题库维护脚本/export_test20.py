import sqlite3, json, random

conn = sqlite3.connect('题库/示例题库.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM problems WHERE reference_answer IS NOT NULL AND reference_answer != ''")
rows = [dict(r) for r in cur.fetchall()]
conn.close()

random.seed(42)
selected = random.sample(rows, 20)

problems = []
for r in selected:
    problems.append({
        "id": r["problem_id"],
        "question": r["question"],
        "domain": r.get("domain", ""),
        "reference_answer": r.get("reference_answer", ""),
    })

with open("test_20.json", "w", encoding="utf-8") as f:
    json.dump(problems, f, ensure_ascii=False, indent=2)

import sys
sys.stdout.reconfigure(encoding='utf-8')
print(f"已导出 {len(problems)} 道题到 test_20.json")
for i, p in enumerate(problems):
    q = p['question'][:40].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    print(f"  {i+1}. [{p['domain'][:16]}] {p['id']}: {q}...")
