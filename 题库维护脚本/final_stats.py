# -*- coding: utf-8 -*-
import sqlite3, io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect("d:/挑战杯/题库/示例题库.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM problems")
total = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM problems WHERE reference_answer IS NOT NULL AND reference_answer != ''")
has_ans = cur.fetchone()[0]

cur.execute("SELECT * FROM problems")
rows = [dict(r) for r in cur.fetchall()]
conn.close()

def is_bad(q):
    if '\ufffd' in q: return True
    if re.search(r'[\uf0b9]', q): return True
    if re.search(r'\(\w\s*\(\s*[a-zA-Z]', q): return True
    d = abs(q.count('(') - q.count(')'))
    return d >= 10

garb = sum(1 for r in rows if is_bad(r.get("question","") or ""))

print(f"总题数: {total}")
print(f"有答案: {has_ans} ({has_ans/total*100:.0f}%)")
print(f"文本正常: {total-garb} ({100-garb/total*100:.1f}%)")
print(f"仍有乱码: {garb}")

if garb:
    for r in rows:
        if is_bad(r.get("question","") or ""):
            print(f"  [{r['problem_id']}]")
