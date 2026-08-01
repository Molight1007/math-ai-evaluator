import sqlite3
conn=sqlite3.connect("d:/挑战杯/题库/示例题库.db")
cur=conn.cursor()
fixes=[
    ("Microsoft Word - 高等数学下册练习册_0026","9x - z - 38 = 0"),
    ("一元函数积分学的应用(一)--几何应用_013","3\u03c0/4"),
    ("【A4基础强化合并】1000题数一高数篇_0149","A"),
]
for pid,ans in fixes:
    cur.execute("SELECT reference_answer FROM problems WHERE problem_id=?",(pid,))
    old=cur.fetchone()
    cur.execute("UPDATE problems SET reference_answer=? WHERE problem_id=?",(ans,pid))
    print(f"{pid}: {old[0] if old else 'N/A'} -> {ans}")
conn.commit()
conn.close()
print("Done")
