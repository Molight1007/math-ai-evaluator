"""错题归因分析：把快筛结果的错题按错误类型分类（零 API 成本）。

类型分类：
- 答错/答非所问：pred 与 gold 数学上确实不同
- 匹配失败：pred 数学上可能对（数值等价/形式不同）但规则匹配失败
- 空答案/拒绝：pred 为空或拒绝语
- 提取失败：pred 是推理片段而非答案
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import answers_match, _norm_candidate


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


rows = load(sys.argv[1] if len(sys.argv) > 1 else "outputs/ab_newbase30.jsonl")

def classify(pred, gold):
    if not pred or not pred.strip():
        return "空答案"
    if re.search(r"无法求解|不能解决|未给出|生成失败", pred, re.I):
        return "拒绝/占位"
    # 数值等价检测（宽松）
    pn = _norm_candidate(pred)
    gn = _norm_candidate(gold)
    if answers_match(pred, gold):
        return "实际匹配成功(不该在这)"
    # 提取失败：pred 太长或含推理文字
    if len(pred) > 120 or re.search(r"因此|所以|步骤|解题|分析|解得|代入|综上", pred):
        return "提取失败(含推理文字)"
    # 形式不同但可能数值等价：尝试数字提取比较
    num_re = r"[-+]?\d*\.?\d+(?:/\d+)?"
    pn_nums = re.findall(num_re, pred.replace("\\", ""))
    gn_nums = re.findall(num_re, gold.replace("\\", ""))
    if pn_nums and gn_nums and pn_nums == gn_nums:
        return "形式不同但数字相同"
    return "答错/答非所问"

from collections import Counter
cats = Counter()
print(f"{'题目ID':<30} {'分类':<22} {'pred前40':<42} gold前40")
print("-" * 140)
for r in rows:
    if r.get("correct"):
        continue
    pred = (r.get("predicted") or "").strip()
    gold = (r.get("gold") or "").strip()
    c = classify(pred, gold)
    cats[c] += 1
    print(f"{str(r.get('id',''))[:28]:<30} {c:<22} {pred[:40]!r:<42} {gold[:40]!r}")

print("\n=== 错题分类统计 ===")
for c, n in cats.most_common():
    print(f"  {c}: {n}")
