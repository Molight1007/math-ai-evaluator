#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""形式签名保真度抽验 · 交叉统计（零配额、只读、不改判据）

用法：
    python 统计脚本_fidelity_tally.py
    python 统计脚本_fidelity_tally.py --judgements <导出的 JSON> --out <报告.md>

自动在抽验目录 / D:/mp_tmp / ~/Downloads 里找最新的
fidelity_judgements*.json（浏览器导出的判定结果）。

口径（项目铁律，不得放宽）：
  · 只报各档条数、分层分布与逐条理由；只报 p̂，不作区间估计/显著性检验
  · 分层抽样 n=26，不得外推到全库 160 条
  · 不作效果量、不宣称等价、不宣称真判有效、不宣称评测通过
  · 未判满全部条目 ⇒ 报告标「未完成，无结论」（E14 铁律③：跑满才看）
  · 判定为单盲单人，未做双人一致率 ⇒ 不做信度结论
"""
import argparse
import collections
import glob
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DETAIL = os.path.join(HERE, "抽验明细_无系统判定.json")
ANSWER = os.path.join(HERE, "答案表_抽验完成后再打开.json")
DEFAULT_OUT = os.path.join(HERE, "抽验结果_交叉统计.md")
KEYS = "ABCD"
LABEL = {"A": "忠实", "B": "命题写歪", "C": "空洞/平凡", "D": "信息不足"}


def find_judgements(explicit):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    pats = [
        os.path.join(HERE, "fidelity_judgements*.json"),
        r"D:\mp_tmp\fidelity_judgements*.json",
        os.path.join(os.path.expanduser("~"), "Downloads",
                     "fidelity_judgements*.json"),
        os.path.join(os.path.expanduser("~"), "Downloads",
                     "fidelity_judgements*.json"),
    ]
    cands = []
    for pat in pats:
        cands += glob.glob(pat)
    cands = sorted(set(cands), key=os.path.getmtime, reverse=True)
    for p in cands:
        try:
            d = json.load(open(p, encoding="utf-8"))
            if isinstance(d.get("items"), list):
                return p
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judgements", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    detail = json.load(open(DETAIL, encoding="utf-8"))
    blind = {b["no"]: b for b in detail["blind"]}
    answers = {x["no"]: x for x in
               json.load(open(ANSWER, encoding="utf-8"))["answers"]}
    total = len(blind)

    jp = find_judgements(a.judgements)
    if not jp:
        print("未找到判定 JSON。请先在抽验台点「导出判定 JSON」，"
              "或用 --judgements 指定路径。")
        return 2
    jd = json.load(open(jp, encoding="utf-8"))
    judge = {}
    for it in jd.get("items", []):
        no = int(it.get("no") or 0)
        if no in blind:
            judge[no] = (it.get("k") or None, (it.get("note") or "").strip())
    for no in blind:
        judge.setdefault(no, (None, ""))

    done = sum(1 for k, _ in judge.values() if k and k in KEYS)
    complete = done == total
    bad_k = [no for no, (k, _) in judge.items() if k and k not in KEYS]
    missing_note = sorted(no for no, (k, n) in judge.items()
                          if k in ("B", "C") and not n)

    cnt = collections.Counter(k for k, _ in judge.values()
                              if k and k in KEYS)
    L = []
    L += ["# 形式签名命题保真度 · 人工抽验结果", "",
          "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
          "- 判定文件：`%s`" % jp,
          "- 抽样框：%d 条去重签名 / %d 题；本单 %d 条 / %d 题"
          % (detail["meta"]["frame_total"], detail["meta"]["frame_questions"],
             total, len(set(b["qid"] for b in blind.values()))),
          "- 固定种子：%d；分层：L1 生产形态 10 + L2 EARLY 8 + L2 LATE 8"
          % detail["meta"]["seed"], ""]
    if not complete:
        L += ["> **状态：未完成（%d / %d），按 E14 铁律③「跑满才看」⇒ 本报告无结论，"
              "以下数字仅供中途查看进度，不得引用。**" % (done, total), ""]
    else:
        L += ["> **状态：%d / %d 已判满。** 单盲单人，未做双人一致率 ⇒ 不作信度结论。"
              % (done, total), ""]
    if bad_k:
        L += ["> 异常判定档位（已忽略）：%s" % bad_k, ""]
    if missing_note:
        L += ["> **B/C 缺备注（须补写具体错在哪一处）**：%s" % missing_note, ""]

    L += ["## 1 总体", "", "| 档 | 含义 | 条数 | 占已判 p̂ |", "|---|---|---:|---:|"]
    for k in KEYS:
        L.append("| **%s** | %s | %d | %s |"
                 % (k, LABEL[k], cnt[k],
                    ("%.1f%%" % (100.0 * cnt[k] / done)) if done else "—"))
    L += ["| 未判 | — | %d | — |" % (total - done), "",
          "（p̂ 只作比例描述，n=%d 且为分层抽样，不作区间估计、不外推全库。）" % done, ""]

    L += ["## 2 分层分布（抽样层，不是效果量）", "",
          "| 层 | 条数 | A | B | C | D | 未判 |", "|---|---:|---:|---:|---:|---:|---:|"]
    layers = collections.defaultdict(list)
    for no, b in blind.items():
        layers[b["layer"]].append(no)
    for lay in sorted(layers):
        nos = layers[lay]
        c = collections.Counter(judge[no][0] for no in nos)
        L.append("| %s | %d | %d | %d | %d | %d | %d |"
                 % (lay, len(nos), c["A"], c["B"], c["C"], c["D"], c[None]))
    L.append("")

    qs = collections.defaultdict(list)
    for no, b in blind.items():
        qs[b["qid"]].append(no)
    hit_q = sorted(q for q, nos in qs.items()
                   if any(judge[n][0] in ("B", "C") for n in nos))
    L += ["## 3 按题目", "",
          "- 覆盖题目：%d；出现 B 或 C 的题目：%d" % (len(qs), len(hit_q)), ""]
    if hit_q:
        L += ["| 题 | 题号 | 条数 | B | C |", "|---|---|---:|---:|---:|"]
        for q in hit_q:
            nos = qs[q]
            c = collections.Counter(judge[n][0] for n in nos)
            L.append("| %s | %s | %d | %d | %d |"
                     % (q, blind[nos[0]]["question_id"], len(nos),
                        c["B"], c["C"]))
    L.append("")

    L += ["## 4 B / C 逐条明细", ""]
    bc = sorted(no for no in blind if judge[no][0] in ("B", "C"))
    if not bc:
        L += ["（本单暂无 B / C 判定。）", ""]
    for no in bc:
        k, note = judge[no]
        b, ans = blind[no], answers[no]
        L += ["### %02d · %s · %s（%s）· 子目标 %s" %
              (no, k, b["question_id"], b["qid"], b["subgoal_id"]), "",
              "- 层：%s｜运行：%s｜门A 预检：%s"
              % (b["layer"], ans["run"], ans["sig_gate_shape_stage"]),
              "- 子目标：%s" % (b["goal"] or b["description"]).replace("\n", " "),
              "- 签名：`%s`" % b["formal_sig"].replace("\n", " ")[:240],
              "- **判定理由**：%s" % (note or "（缺，须补）"), ""]

    L += ["## 5 与系统判定交叉（仅描述，不作推断）", "",
          "| 门A 预检 stage | A | B | C | D | 未判 |", "|---|---:|---:|---:|---:|---:|"]
    stages = collections.defaultdict(list)
    for no, b in blind.items():
        stages[answers[no]["sig_gate_shape_stage"]].append(no)
    for st in sorted(stages):
        c = collections.Counter(judge[no][0] for no in stages[st])
        L.append("| %s | %d | %d | %d | %d | %d |"
                 % (st, c["A"], c["B"], c["C"], c["D"], c[None]))
    L += ["", "> 历史样本大多无 `sig_gate_shape` 字段（规划期预检是后期才加的），"
          "此表不作「门A 判得准不准」的证据。", ""]

    ratio = (100.0 * (cnt["B"] + cnt["C"]) / done) if done else None
    L += ["## 6 口径与不宣称", "",
          "- 判定对象：**这条签名是否忠于该子目标及原题**，不是「能不能证出来」。",
          "- `:= by sorry` 是分工设计（E30），未据此判 B/C。",
          "- 文献参照：Goedel-Prover-V2 (arXiv:2508.03613) 在 Omni-MATH 报告"
          "未解问题里 >80%% 为形式化写错；FormalMATH / BEq+ / ShadowBench 关注空洞命题。"
          "本单 %s 与文献数字**不可直接比较**（题库子集、抽样单元、判定标准都不同）。"
          % (("B+C 占已判 %.1f%%" % ratio) if ratio is not None else "尚无比例"),
          "- 不宣称：真判有效 / 等价 / 效果量 / 评测通过 / 统计显著 / 可外推。",
          "- 本单只作**存在性结论**：能否在本抽样里观察到 misformalization / 空洞命题。", "",
          "## 7 方向提示（条件句，自动脚本不替人下结论）", "",
          "- 若 B/C 集中且理由站得住 ⇒ 后续应转向命题形式化与语义保真，"
          "继续在闸门层或证明层加东西属于修错地方。",
          "- 若绝大多数为 A ⇒ 「模型证不出可编译、无 sorry 的 Lean 证明」"
          "这一归因才在本抽样上站得住；仍不得外推。",
          "- 无论哪种结果，都不改变已证伪的 E26 假设，也不构成任何效果量。", ""]

    out = "\n".join(L)
    open(a.out, "w", encoding="utf-8").write(out)
    print("判定文件:", jp)
    print("完成度: %d/%d %s" % (done, total, "(完整)" if complete else "(未完成⇒无结论)"))
    print("各档:", {k: cnt[k] for k in KEYS}, "未判", total - done)
    print("B/C 缺备注:", missing_note or "无")
    print("报告:", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
