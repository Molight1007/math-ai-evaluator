import sqlite3, json
conn=sqlite3.connect('题库/示例题库.db')
cur=conn.cursor()
cur.execute('SELECT COUNT(*) FROM problems')
t=cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM problems WHERE reference_answer IS NOT NULL AND reference_answer!=''")
a=cur.fetchone()[0]
print(f'题库状态: 总数={t}, 有答案={a}, 无答案={t-a}')
conn.close()

with open('题库审核日志/audit_log_20260728_204109.json', encoding='utf-8') as f:
    data=json.load(f)
print(f'审核结果: {data["summary"]}')
print(f'修正了 {len(data["corrected"])} 题:')
for i, c in enumerate(data['corrected'][:10]):
    print(f'  {c["pid"]}: "{c["old"][:50]}" -> "{c["new"][:50]}" | {c["reason"][:60]}')
if len(data['corrected'])>10: print(f'  ...还有{len(data["corrected"])-10}条')
