#!/usr/bin/env python
"""4.4 计算检测的离线回放床（确定性评估，δ=0）。

为什么需要它
------------
RRSI 的噪声下限 δ 来自 LLM 采样随机性，测一次要几小时。但**审核链的判定是确定性函数**：
同一份 reasoning 文本 ⇒ 同一组提取式 ⇒ 同一个 ``n_bad``。因此可以在历史运行产出的
``candidates[].reasoning`` 上无限次零成本重跑，δ 恒为 0，任何指标变化都能**完全归因**到代码改动。

指标
----
- ``rejected``   : ``n_bad > 0`` 被判死的候选数
- ``hard_kill``  : 被判死、但该候选 answer 与 gold 匹配的候选数 —— **硬误杀**
- ``kill_rate``  : rejected / 参与工具③的候选数
- ``fp_rate``    : hard_kill / rejected（判死中杀错的比例）

用法
----
    python replay_calc_gate.py                 # 全历史回放
    python replay_calc_gate.py --files results/solution7_0918.jsonl
    python replay_calc_gate.py --show 8        # 打印前 8 条硬误杀样例
    python replay_calc_gate.py --out D:/mp_tmp/replay_1026.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.math_check_gate import (  # noqa: E402
    _extract_conditions,
    _extract_inequalities,
    _extract_numeric_equations,
)
from run_eval__scoring import answers_match  # noqa: E402
from tools.agent_toolkit.calc_verify import calc_verify  # noqa: E402

DEFAULT_GLOB = "results/*.jsonl"


def _content_key(rec):
    """同一批候选的内容指纹 —— 用来识别「同一次运行被复制到多个文件」。

    `results/` 里有真实重复：`verify10_0916.jsonl` 与其 `_rejudged` 版是同一批运行
    （只多一次重新判分），`_修复前基线_10题_0917.jsonl` 与 `solution10_0916_中断4.jsonl`
    字节数完全相同。不去重会把同一批误杀算两遍，指标虚高 —— 违背「证据可信」。

    注意**不能**用 (id, cid) 去重：同一题在不同代码版本下重跑，proposer 采样不同、
    reasoning 不同，那是**独立样本**，必须保留。所以指纹取 reasoning 全文。
    """
    import hashlib
    h = hashlib.md5()
    h.update(str(rec.get("id") or "").encode("utf-8", "replace"))
    for c in rec.get("candidates") or []:
        if isinstance(c, dict):
            h.update(b"\x00")
            h.update(str(c.get("reasoning") or "").encode("utf-8", "replace"))
    return h.hexdigest()


def iter_records(patterns, stats=None):
    """产出 (文件, 记录)。只取含 candidates 的记录（旧格式没有，跳过）。

    ``stats`` 传入 dict 时回填 ``raw`` / ``dup`` 两个计数，供报告如实说明去重前后。
    """
    seen_files = set()
    seen_content = set()
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            key = os.path.normcase(os.path.abspath(path))
            if key in seen_files:
                continue
            seen_files.add(key)
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    cands = rec.get("candidates")
                    if not isinstance(cands, list) or not cands:
                        continue
                    # 老记录里 candidates 只有 id/answer/reasoning，才是我们需要的最小集
                    if not any(isinstance(c, dict) and c.get("reasoning") for c in cands):
                        continue
                    ck = _content_key(rec)
                    if ck in seen_content:
                        if stats is not None:
                            stats["dup"] = stats.get("dup", 0) + 1
                        continue
                    seen_content.add(ck)
                    if stats is not None:
                        stats["raw"] = stats.get("raw", 0) + 1
                    rec["_file"] = os.path.basename(path)
                    yield rec



def replay_record(rec):
    """在一条记录上复刻 4.4 的工具③判定，返回逐候选项。"""
    out = []
    gold = str(rec.get("gold") or "")
    problem = str(rec.get("question") or rec.get("problem") or "")
    conds = _extract_conditions(problem)
    for c in rec.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        reason = str(c.get("reasoning") or "")
        if not reason:
            continue
        ans = str(c.get("answer") or "")
        eqs = _extract_numeric_equations(reason)
        ineq = _extract_inequalities(reason)
        items = [{"expr": a, "claimed": b} for a, b in eqs[:8]]
        items += [{"expr": a, "claimed": b, "op": op} for a, b, op in ineq[:8]]
        if not items:
            continue
        rv = calc_verify(items, constraints=conds)
        n_bad = int(rv.get("n_bad") or 0)
        if n_bad <= 0:
            continue
        # 首条非 ok 项：与 4.4 的「判词退回首条非 ok」一致
        first = next((x for x in (rv.get("results") or []) if not x.get("ok")), {})
        try:
            answer_ok = bool(gold) and answers_match(ans, gold)
        except Exception:  # noqa: BLE001  判分器异常 ⇒ 保守认为不是误杀
            answer_ok = False
        out.append({
            "file": rec.get("_file"),
            "qid": rec.get("id"),
            "cid": c.get("id"),
            "answer": ans[:120],
            "gold": gold[:120],
            "n_bad": n_bad,
            "n_items": len(items),
            "n_cond": len(conds),
            "expr": str(first.get("expr") or "")[:80],
            "claimed": str(first.get("claimed") or "")[:40],
            "actual": str(first.get("actual") or "")[:40],
            "detail": str(first.get("detail") or "")[:120],
            "answer_matches_gold": answer_ok,
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="4.4 计算检测离线回放床")
    ap.add_argument("--files", nargs="*", default=[DEFAULT_GLOB],
                    help="result jsonl glob（默认 %s）" % DEFAULT_GLOB)
    ap.add_argument("--show", type=int, default=0, help="打印前 N 条硬误杀样例")
    ap.add_argument("--out", default="", help="把逐项明细写到这里（json）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    n_rec = n_cand = n_participate = n_cond_rec = 0
    kills = []
    _st = {}
    for rec in iter_records(a.files, stats=_st):
        n_rec += 1
        cands = [c for c in rec["candidates"] if isinstance(c, dict)]
        n_cand += len(cands)
        items = replay_record(rec)
        # participate 口径：至少提取到 1 条式子的候选
        prob = str(rec.get("question") or rec.get("problem") or "")
        if _extract_conditions(prob):
            n_cond_rec += 1
        for c in cands:
            r = str(c.get("reasoning") or "")
            if not r:
                continue
            if _extract_numeric_equations(r)[:8] or _extract_inequalities(r)[:8]:
                n_participate += 1
        kills.extend(items)

    n_kill = len(kills)
    n_hard = sum(1 for k in kills if k["answer_matches_gold"])
    kill_rate = (n_kill / n_participate) if n_participate else 0.0
    fp_rate = (n_hard / n_kill) if n_kill else 0.0

    print("=" * 66)
    print("4.4 工具③ 离线回放 · 确定性（δ=0）")
    print("=" * 66)
    print("记录数          %d%s" % (
        n_rec, ("（%d 条重复批已去重）" % _st["dup"]) if _st.get("dup") else ""))
    print("候选数          %d" % n_cand)
    print("参与工具③      %d（提取到式子）" % n_participate)
    print("判死 rejected   %d   覆盖率 %.1f%%" % (n_kill, kill_rate * 100))
    print("硬误杀          %d   判死中杀错 %.1f%%" % (n_hard, fp_rate * 100))
    # 正反两面：判死里 answer 与 gold 对不上的，视为「真错被抓住」的上界
    # （上界的含义：答案不匹配也可能来自判分器本身，不全是推理算错）
    print("真错抓住       %d（上界，判死里答案与 gold 不符）" % (n_kill - n_hard))
    print("题面条件注入    %d 条记录带条件" % n_cond_rec)

    if kills:
        print("\n-- 判死按题聚集（top 10）--")
        for qid, n in Counter((k["qid"] for k in kills)).most_common(10):
            hard = sum(1 for k in kills if k["qid"] == qid and k["answer_matches_gold"])
            print("  %-38s 判死 %2d  其中误杀 %2d" % (str(qid)[:38], n, hard))

        print("\n-- 首条触发式形态（top 8）--")
        for expr, n in Counter(k["expr"] for k in kills).most_common(8):
            print("  %2d x  %s" % (n, expr or "(空)"))

    if a.show:
        print("\n-- 硬误杀样例前 %d 条 --" % a.show)
        shown = 0
        for k in kills:
            if not k["answer_matches_gold"]:
                continue
            shown += 1
            if shown > a.show:
                break
            print("\n[%d] %s cid=%s  n_bad=%d" % (shown, k["qid"], k["cid"], k["n_bad"]))
            print("    ans=%s  gold=%s" % (k["answer"], k["gold"]))
            print("    首个触发：`%s` = %s (实际 %s)" % (k["expr"], k["claimed"], k["actual"]))
            print("    判词：%s" % k["detail"])

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"summary": {"records": n_rec, "candidates": n_cand,
                                   "participate": n_participate, "rejected": n_kill,
                                   "hard_kill": n_hard, "kill_rate": kill_rate,
                                   "fp_rate": fp_rate},
                       "kills": kills}, f, ensure_ascii=False, indent=1)
        print("\n明细已写 %s" % a.out)

    # 退出码：有硬误杀即 1，便于 CI/门禁用
    return 1 if n_hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
