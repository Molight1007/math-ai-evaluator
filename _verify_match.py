"""验证 run_eval 升级后的 answers_match（收益 + 误报 + 改进明细）。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import answers_match

rows = [json.loads(l) for l in open("outputs/ab_newbase30.jsonl", encoding="utf-8") if l.strip()]

new = sum(1 for r in rows if answers_match(r.get("predicted", "") or "", r.get("gold", "") or ""))
print(f"升级后匹配: {new}/{len(rows)} ({new/len(rows):.0%})")

flips = [r["id"] for r in rows
         if r.get("correct") and not answers_match(r.get("predicted", "") or "", r.get("gold", "") or "")]
print(f"误报(原来对→现在错): {len(flips)} {flips[:3]}")

print("改进明细:")
for r in rows:
    if not r.get("correct") and answers_match(r.get("predicted", "") or "", r.get("gold", "") or ""):
        print(f"  + {str(r['id'])[:28]} pred={r.get('predicted','')[:40]!r}")
