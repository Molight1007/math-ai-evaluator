#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零配额：形式签名「命题保真度」人工抽验清单生成器（只读，不碰生产代码）。

数据来源：服务器 ~/mathpilot/results/2*/q*/03_subgoals.json（蓝图正文只在这里）
          + results/*.jsonl（题目原文 / 题号）

抽样框：plan.subgoals[].formal_sig 非空者，按 (qid, 签名文本 md5) 去重。
分层：L1 当前生产形态（20261105-* 三轮）全量；
      L2 其余历史，按时间前/后各半，各 8 条，且同题最多 2 条。
盲审：发给人的清单不含任何系统判定（stage / tool_verdict / correct / run）；
      答案表单独输出，抽验完成后方可对照。

对应文献：Goedel-Prover-V2 (2508.03613) 未解问题 >80% 形式化写错；
          BEq+ / ShadowBench 的空洞命题检测；E29「编译通过也挡不住语义空洞」。
"""
import collections
import glob
import hashlib
import json
import os
import random

ROOT = os.path.expanduser("~/mathpilot")
OUT = "/tmp/fidelity_picks.json"
SEED = 20261106


def qid_of(q):
    return "q" + hashlib.md5(("%s" % (q,)).encode("utf-8")).hexdigest()[:8]


def load_questions():
    """qid -> (题号, 题目原文, 来源文件)，来自所有 results/*.jsonl。"""
    m = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "results", "*.jsonl"))):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    d = json.loads(line)
                    q = d.get("question")
                    if q:
                        m.setdefault(qid_of(q), (str(d.get("id") or ""), q,
                                                os.path.basename(p)))
        except Exception:
            pass
    return m


def load_rows():
    """全库非空 formal_sig，按 (qid, 签名文本) 去重，保留最早 run。"""
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, "results", "2*", "q*",
                                           "03_subgoals.json"))):
        parts = p.split(os.sep)
        run, qid = parts[-3], parts[-2]
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                d = json.load(f)
        except Exception:
            continue
        for sg in ((d.get("plan") or {}).get("subgoals") or []):
            sig = (sg.get("formal_sig") or "").strip()
            if not sig:
                continue
            shape = sg.get("sig_gate_shape") or {}
            rows.append({
                "run": run, "qid": qid, "sg_id": str(sg.get("id") or ""),
                "sig": sig, "stage": shape.get("stage", "(缺)"),
                "tool": sg.get("tool") or "",
                "goal": (sg.get("goal") or "").strip(),
                "description": (sg.get("description") or "").strip(),
                "expected_output": (sg.get("expected_output") or "").strip(),
                "source": os.path.relpath(p, ROOT),
            })
    uniq = {}
    for r in rows:
        k = (r["qid"], hashlib.md5(r["sig"].encode("utf-8")).hexdigest())
        prev = uniq.get(k)
        if prev is None or (r["run"], r["sg_id"]) < (prev["run"], prev["sg_id"]):
            uniq[k] = r
    return sorted(uniq.values(),
                  key=lambda r: (r["run"], r["qid"],
                                 int(r["sg_id"]) if r["sg_id"].isdigit() else 999))


def pick_layered(hist, half_n):
    """时间前/后各半，各抽 half_n 条；同题最多 2 条；确定性。"""
    rng = random.Random(SEED)
    ordered = sorted(hist, key=lambda r: (r["run"], r["qid"], r["sg_id"]))
    mid = len(ordered) // 2
    halves = [ordered[:mid], ordered[mid:]]
    out, per_q = [], collections.Counter()
    for tag, pool in zip(("EARLY", "LATE"), halves):
        # 题目分层：先打乱题目顺序，再在题内打乱条目，逐轮取，避免单题霸榜
        by_q = collections.defaultdict(list)
        for r in pool:
            by_q[r["qid"]].append(r)
        qkeys = sorted(by_q)
        rng.shuffle(qkeys)
        for v in by_q.values():
            rng.shuffle(v)
        taken = 0
        for round_no in range(3):
            for q in qkeys:
                if taken >= half_n:
                    break
                if per_q[q] >= 2 or round_no >= len(by_q[q]):
                    continue
                r = dict(by_q[q][round_no])
                r["layer"] = "L2/" + tag
                out.append(r)
                per_q[q] += 1
                taken += 1
            if taken >= half_n:
                break
    return out


def main():
    qmap = load_questions()
    rows = load_rows()
    l1 = [r for r in rows if r["run"].startswith("20261105-")]
    hist = [r for r in rows if not r["run"].startswith("20261105-")]
    picks = []
    for r in l1:
        r = dict(r)
        r["layer"] = "L1/PRODUCTION"
        picks.append(r)
    picks += pick_layered(hist, 8)
    picks.sort(key=lambda r: (0 if r["layer"].startswith("L1") else 1,
                              r["qid"], r["sg_id"], r["layer"]))

    blind, answers = [], []
    for i, r in enumerate(picks, 1):
        q = qmap.get(r["qid"], ("", "(题目原文缺失)", ""))
        blind.append({
            "no": i, "layer": r["layer"], "qid": r["qid"],
            "question_id": q[0], "question": q[1],
            "subgoal_id": r["sg_id"],
            "goal": r["goal"], "description": r["description"],
            "expected_output": r["expected_output"],
            "formal_sig": r["sig"],
        })
        answers.append({
            "no": i, "qid": r["qid"], "subgoal_id": r["sg_id"],
            "run": r["run"], "source": r["source"], "layer": r["layer"],
            "question_id": q[0], "question_source": q[2],
            "sig_gate_shape_stage": r["stage"], "tool": r["tool"],
        })

    meta = {
        "title": "形式签名命题保真度人工抽验",
        "generated": "2026-11-06",
        "purpose": ("区分「命题从一开始就写歪/空洞」与「模型证不出」；"
                    "门A 只判可陈述（能不能编译），不判语义保真。"),
        "frame_total": len(rows),
        "frame_questions": len(set(r["qid"] for r in rows)),
        "question_lookup_hit": sum(1 for b in blind
                                   if not b["question"].startswith("(题目原文缺失)")),
        "dedup": "按 (qid, formal_sig 文本 md5) 去重，保留最早 run",
        "seed": SEED,
        "layers": {
            "L1/PRODUCTION": "20261105 三轮真实运行，全量 %d 条" % len(l1),
            "L2/EARLY": "历史样本按时间序前半，8 条，同题≤2",
            "L2/LATE": "历史样本按时间序后半，8 条，同题≤2",
        },
        "picked": len(blind),
        "blind": ("清单不含 stage / tool_verdict / correct / run / 来源文件；"
                  "答案表单独存放，抽验完成后方可对照，防锚定。"),
        "rubric": {
            "A": "忠实 — 签名准确表达该子目标，量词/类型/常数/定义域与原题一致",
            "B": "命题写歪 — 改了题意：量词方向、变量域、常数、把待证结论写成假设、求解题改证明/反证、拆成分类证明",
            "C": "空洞/平凡 — 恒真或前提矛盾：True、A=A、假设直接蕴含结论、ℕ 减法/除法造成的假等式",
            "D": "信息不足 — 题目或签名残缺，无法判定",
        },
        "rules": [
            ":= by sorry 是分工设计（E30），不因出现 sorry 判 B/C",
            "只判「这条签名是否忠于这个子目标 + 原题」，不判能不能证出来",
            "B/C 必须在备注里写出具体错在哪一处",
            "未抽验完毕不得下结论；不作统计推断、不作效果量",
        ],
        "source_note": ("真实数据只在服务器 results/*.jsonl + <run>/q<id>/0X_*.json；"
                        "本地 results/ 为 9 月旧数据，未使用。"),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "blind": blind, "answers": answers},
                  f, ensure_ascii=False, indent=1)
    print("frame=%d questions=%d picked=%d lookup_hit=%d"
          % (meta["frame_total"], meta["frame_questions"],
             meta["picked"], meta["question_lookup_hit"]))
    print("layers:", collections.Counter(b["layer"] for b in blind))
    print("questions covered:", len(set(b["qid"] for b in blind)))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
