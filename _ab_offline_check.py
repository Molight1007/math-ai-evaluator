"""离线验证 P1 judger_friendly：对基线 final_response 应用规范化后重算匹配。

不需要 API。对比三组：
A) 基线原始 final_response 的匹配结果（应与 ab_baseline.jsonl 的 correct 一致）
B) 应用 _judger_friendly 后的匹配结果
C) P1 实际运行的结果（ab_p1.jsonl）

如果 B ≈ A 且 B > C 的差异无法解释 → 说明 P1 运行差异主要来自模型采样噪声而非 judger_friendly。
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.formatter import FormatterAgent
from run_eval import answers_match


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


base = load("outputs/ab_baseline.jsonl")
p1 = load("outputs/ab_p1.jsonl")

# A) 基线原始匹配（应与文件 correct 一致）
a_correct = sum(1 for r in base if r.get("correct"))
# 重算确认
a_recalc = sum(1 for r in base if answers_match(r.get("predicted", ""), r.get("gold", "")))
print(f"A) 基线原始匹配: 文件={a_correct}/30, 重算={a_recalc}/30")

# B) judger_friendly 后匹配
b_correct = 0
b_diff = []
for r in base:
    cleaned = FormatterAgent._judger_friendly(r.get("predicted", ""))
    ok = answers_match(cleaned, r.get("gold", ""))
    if ok:
        b_correct += 1
    orig_ok = bool(r.get("correct"))
    if ok != orig_ok:
        b_diff.append((r["id"], orig_ok, ok, r.get("predicted", "")[:40], cleaned[:40]))
print(f"B) judger_friendly 后匹配: {b_correct}/30")
print(f"   翻转 {len(b_diff)} 题:")
for pid, o, n, raw, cleaned in b_diff:
    print(f"   {pid}: {o}→{n}\n      raw={raw!r}\n      cleaned={cleaned!r}")

# C) P1 实际运行
c_correct = sum(1 for r in p1 if r.get("correct"))
print(f"C) P1 实际运行: {c_correct}/30")

# 翻转明细（基线 vs P1 实际运行）
bmap = {r["id"]: r for r in base}
flips = []
for r in p1:
    b = bmap.get(r["id"])
    if b and b.get("correct") is not None and r.get("correct") is not None \
            and b["correct"] != r["correct"]:
        flips.append((r["id"], b["correct"], r["correct"],
                      b.get("predicted", "")[:40], r.get("predicted", "")[:40]))
print(f"\n基线 vs P1 实际翻转 {len(flips)} 题:")
for pid, bc, pc, bp, pp in flips:
    print(f"   {pid}: 基线={bc} P1={pc}\n      基线pred={bp!r}\n      P1 pred={pp!r}")
