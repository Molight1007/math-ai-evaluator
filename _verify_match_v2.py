"""v2 匹配增强验证（对 ab_real30 离线重算 + 误报检查）。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import answers_match

rows = [json.loads(l) for l in open("outputs/ab_real30.jsonl", encoding="utf-8") if l.strip()]
new = sum(1 for r in rows if answers_match(r.get("predicted", "") or "", r.get("gold", "") or ""))
print(f"v2 匹配: {new}/30 ({new/30:.0%})")

regress = [r["id"] for r in rows
           if r.get("correct") and not answers_match(r.get("predicted", "") or "", r.get("gold", "") or "")]
print(f"误报: {len(regress)} {regress[:3]}")

print("救回明细:")
for r in rows:
    if not r.get("correct") and answers_match(r.get("predicted", "") or "", r.get("gold", "") or ""):
        print(f"  + {str(r['id'])[:26]} pred={r.get('predicted','')[:34]!r}")
