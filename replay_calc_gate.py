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

``hard_kill`` 依赖 gold，而 gold 本身并非总可信 ⇒ 它是**代理指标**，
``true_kill = rejected - hard_kill`` 只是**上界**。人工标注流程把上界变成实测：

    python replay_calc_gate.py --label-out results/calc_gate_labels_1026.json   # 出待标清单
    #   …人工/审阅者填 "label": "wrong" | "false_alarm"…
    python replay_calc_gate.py --labels results/calc_gate_labels_1026.json      # 读回算实测

标注口径（只看**被工具判死的那一步**算得对不对，不看最终答案对不对）：
- ``wrong``       : 被判死的那条式子在推理语境里确实算错/断言不成立 ⇒ 杀对了
- ``false_alarm`` : 该步推理正确；或所谓"判别式"只是解析残片（原文无此断言）⇒ 杀错了
- ``unclear``     : 语境不足以判定（如实记录，不进准确率分母）

为什么必须人工过一遍：``hard_kill`` 拿 ``answer_matches_gold`` 当代理，只看得见
「答案对不对」，看不见「判死理由对不对」。历史样本上代理报 0 起误杀，实测 30 起 ——
被杀候选的最终答案本来就错，所以代理永久看不见这类错误。

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
import re
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



def _reason_fp(text):
    """reasoning 全文指纹 —— 标注主键的一部分。

    不能只用 ``qid|cid``：同一题在不同代码版本下重跑，cid 编号会复用而 reasoning 不同，
    两者的「这一步算错没算错」是**独立判断**，必须能分别标注。
    """
    import hashlib
    return hashlib.md5(text.encode("utf-8", "replace")).hexdigest()[:10]


def _kill_key(k):
    return "%s|%s|%s" % (k.get("qid"), k.get("cid"), k.get("rfp"))


_OP_TXT = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<"}


def _excerpt(reason, expr, op="", width=200):
    """截取触发式在原文（归一化后）附近的上下文 —— 标注者判断「这步对不对」必须看到它。

    只按 ``expr`` 做 ``str.find`` 是**不可靠的**：``expr='2'`` 会命中文档里第一个 `2`，
    标注者看到的是无关段落。改成先按「表达式 + 关系符」定位（这正是提取时的边界），
    找不到才退回裸串搜索 —— 定位错了会直接污染标注结论。
    """
    from agent.math_check_gate import _normalize_math
    s = _normalize_math(reason)
    if not expr:
        return s[: width * 2].strip()
    rel = _OP_TXT.get(op or "", "=") if op else "="
    alt = "(?:<>|<=|>=|!=|==|=|<|>)" if rel == "=" else "(?:%s)" % re.escape(rel)
    m = re.search(re.escape(expr) + r"\s*" + alt, s)
    i = m.start() if m else s.find(expr)
    if i < 0:
        return s[: width * 2].strip()
    a = max(0, i - width)
    return ("…" if a else "") + s[a: i + width].strip() + "…"


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
        # ★ 必须与 ``math_check_stage`` 的取词规则**逐字一致**：先取「算错/不成立」
        #   的项，取不到才退回首条非 ok。此前的实现只取首条非 ok，于是把一堆
        #   「表达式无法解析（未做判定）」当成了判死理由 —— 那些项属 n_err，
        #   本身并不淘汰，标注者看到的理由是假的。
        rows = rv.get("results") or []
        idx = next((i for i, x in enumerate(rows)
                    if (not x.get("ok"))
                    and ("不成立" in str(x.get("detail"))
                         or "算错" in str(x.get("detail")))), None)
        if idx is None:
            idx = next((i for i, x in enumerate(rows) if not x.get("ok")), None)
        first = rows[idx] if idx is not None else {}
        _item = items[idx] if idx is not None and idx < len(items) else {}
        try:
            answer_ok = bool(gold) and answers_match(ans, gold)
        except Exception:  # noqa: BLE001  判分器异常 ⇒ 保守认为不是误杀
            answer_ok = False
        expr = str(first.get("expr") or "")[:80]
        out.append({
            "file": rec.get("_file"),
            "qid": rec.get("id"),
            "cid": c.get("id"),
            "rfp": _reason_fp(reason),
            "answer": ans[:120],
            "gold": gold[:120],
            "n_bad": n_bad,
            "n_items": len(items),
            "n_cond": len(conds),
            "expr": expr,
            "op": str(_item.get("op") or ""),
            "claimed": str(first.get("claimed") or "")[:40],
            "actual": str(first.get("actual") or "")[:40],
            "detail": str(first.get("detail") or "")[:120],
            "answer_matches_gold": answer_ok,
            "excerpt": _excerpt(reason, expr, str(_item.get("op") or "")),
            "question": problem[:300],
        })
    return out


VALID_LABELS = ("wrong", "false_alarm", "unclear")


def load_labels(path):
    """读标注表。返回 {key: {"label","pattern","note"}}，非法 label 一律忽略（宁缺不污染）。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items") if isinstance(data, dict) else data
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = it.get("key") or _kill_key(it)
        lab = str(it.get("label") or "").strip()
        if lab in VALID_LABELS:
            out[key] = {"label": lab,
                        "pattern": str(it.get("pattern") or "").strip(),
                        "note": str(it.get("note") or "").strip()}
    return out


def write_label_sheet(path, kills, summary):
    """出待标清单：每条判死附带判据、触发式、原文上下文，供逐条判断。

    写作目的是**可审阅**：审阅者不必重跑，只看这一份就能判断「这一步到底算错没算错」。
    """
    items = []
    for k in kills:
        items.append({
            "key": _kill_key(k),
            "label": "",
            "qid": k["qid"], "cid": k["cid"], "file": k["file"],
            "answer": k["answer"], "gold": k["gold"],
            "answer_matches_gold": k["answer_matches_gold"],
            "n_bad": k["n_bad"], "n_items": k["n_items"], "n_cond": k["n_cond"],
            "expr": k["expr"], "op": k.get("op") or "",
            "claimed": k["claimed"],
            "actual": k["actual"], "detail": k["detail"],
            "question": k["question"],
            "excerpt": k["excerpt"],
        })
    payload = {
        "schema": "kill-label-sheet/1",
        "legend": {
            "wrong": "该步推理确实算错/断言不成立 ⇒ 杀对了",
            "false_alarm": "该步推理正确，工具读错或越权 ⇒ 杀错了",
            "unclear": "语境不足，不进准确率分母",
        },
        "summary": summary,
        "items": items,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return len(items)


def _report_labels(kills, labels):
    """把上界换成实测，并给出「answer_matches_gold 当代理准不准」的 2x2。"""
    n_lab = n_right = n_wrong = n_unclear = 0
    # 2x2：行=代理指标说的，列=人工标注说的
    cell = Counter()
    pats = Counter()
    stale = 0
    keys = set()
    for k in kills:
        key = _kill_key(k)
        keys.add(key)
        rec = labels.get(key)
        if rec is None:
            continue
        n_lab += 1
        lab = rec["label"]
        if lab == "unclear":
            n_unclear += 1
            continue
        if lab == "wrong":
            n_wrong += 1
        else:
            n_right += 1
            if rec.get("pattern"):
                pats[rec["pattern"]] += 1
        proxy = "answer_ok" if k["answer_matches_gold"] else "answer_bad"
        cell[(proxy, lab)] += 1
    for key, rec in labels.items():
        if key not in keys:
            stale += 1

    print("\n-- 人工标注（%d / %d 条已判）--" % (n_lab, len(kills)))
    if not n_lab:
        print("   （尚无标注，下面的 true_kill 仍是上界）")
        return None
    denom = n_right + n_wrong
    if denom:
        print("   杀对了 wrong        %d" % n_wrong)
        print("   杀错了 false_alarm  %d" % n_right)
        print("   ★ 实测准确率        %.1f%%（%d/%d）"
              % (n_wrong * 100.0 / denom, n_wrong, denom))
    if n_unclear:
        print("   语境不足 unclear    %d（已排除在分母外）" % n_unclear)
    if stale:
        print("   ⚠ 有 %d 条标注在当前样本里找不到对应判死（代码改动后提取式变化）"
              % stale)

    proxy_hard = cell[("answer_ok", "false_alarm")]
    print("\n   代理指标（answer_matches_gold）检验：")
    print("   代理报的硬误杀 %d 起；人工实测杀错 %d 起" % (proxy_hard, n_right))
    if n_right and proxy_hard < n_right:
        print("   ⇒ 代理漏报 %d 起。原因：这些候选的最终答案本来就错，"
              % (n_right - proxy_hard))
        print("     代理只看得见「答案对不对」，看不见「判死理由对不对」")
    if pats:
        print("\n-- 杀错的形态分布（按条数，这就是下一步的修法清单）--")
        for pat, n in pats.most_common():
            print("   %2d x  %s" % (n, pat))
    return {"labelled": n_lab, "wrong": n_wrong, "false_alarm": n_right,
            "unclear": n_unclear, "stale": stale,
            "measured_accuracy": (n_wrong / denom) if denom else None,
            "false_alarm_patterns": dict(pats)}


def main():
    ap = argparse.ArgumentParser(description="4.4 计算检测离线回放床")
    ap.add_argument("--files", nargs="*", default=[DEFAULT_GLOB],
                    help="result jsonl glob（默认 %s）" % DEFAULT_GLOB)
    ap.add_argument("--show", type=int, default=0, help="打印前 N 条硬误杀样例")
    ap.add_argument("--out", default="", help="把逐项明细写到这里（json）")
    ap.add_argument("--label-out", default="", help="生成待人工标注清单（json）")
    ap.add_argument("--labels", default="", help="读入已标注清单，计算实测指标")
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
    print("硬误杀          %d   判死中杀错 %.1f%%   ← 代理指标，只覆盖答案正确的候选"
          % (n_hard, fp_rate * 100))
    # 正反两面：判死里 answer 与 gold 对不上的，视为「真错被抓住」的**上界**。
    # 上界的含义有两条：(1) 答案不匹配也可能来自判分器；(2) 更关键的是被判死的那步
    # 可能根本没算错（提取残片），而答案错在别处。实测须走 --labels。
    print("真错抓住       %d（上界，要实测请用 --labels）" % (n_kill - n_hard))
    print("题面条件注入    %d 条记录带条件" % n_cond_rec)

    summary = {"records": n_rec, "candidates": n_cand, "participate": n_participate,
               "rejected": n_kill, "hard_kill": n_hard, "kill_rate": kill_rate,
               "fp_rate": fp_rate}
    measured = None
    if a.labels:
        measured = _report_labels(kills, load_labels(a.labels))
        summary["measured"] = measured

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
            json.dump({"summary": summary, "kills": kills}, f,
                      ensure_ascii=False, indent=1)
        print("\n明细已写 %s" % a.out)

    if a.label_out:
        n = write_label_sheet(a.label_out, kills, summary)
        print("\n待标清单已写 %s（%d 条，把 label 填成 wrong / false_alarm / unclear）"
              % (a.label_out, n))

    # 退出码：有实测误杀（无标注时退化为硬误杀）即 1，便于 CI/门禁用
    if measured and (measured.get("false_alarm") or 0) > 0:
        return 1
    return 1 if n_hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
