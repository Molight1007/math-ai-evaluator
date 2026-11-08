# -*- coding: utf-8 -*-
"""L2 hammer 扫描 —— 结果解析（E42）

判定顺序（严格，宁可剔除不可误算）：
  1. 哨兵 MARK_<idx> 必须出现 ⇒ 该 example 确实被解析执行；
  2. 按行号区间把 error 归属到 example；
  3. V_base（模型原 tactic）只许出现「状态类」错误（unsolved goals /
     No goals to be solved / 战术失败）；一旦出现「构造类」错误
     （unexpected token / unknown identifier / expected term ...）
     ⇒ 该前缀本身是坏的，整点从统计中剔除；
  4. 在可信点里，hammer 文件零 error ⇒ CLOSED；
  5. 出现 `declaration uses 'sorry'` 的 CLOSED 一律作废。
"""
import collections
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "out")

# Lean 4.31 两种格式都要认：`error: ...` 与 `error(lean.unknownIdentifier): ...`
ERR_RE = re.compile(r"^.*?:(\d+):\d+: error(?:\([^)]*\))?: ?(.*)$")
MARK_RE = re.compile(r"MARK_(\d+)")

# 构造类：说明这段代码不是探针以为的那个 goal state
BROKEN_PAT = re.compile(
    r"unexpected|unknown identifier|unknown constant|unknown tactic|"
    r"expected term|expected '|invalid |parse|unexpected end|"
    r"maximum number of errors|failed to synthesize|application type mismatch|"
    r"function expected|type mismatch", re.I)
# 状态类：目标还开着 / 战术没证出来，属于正常「未闭合」
OPEN_PAT = re.compile(
    r"unsolved goals|No goals to be solved|Tactic .* failed|"
    r"made no progress|could not prove|failed|not a .* goal|"
    r"maximum recursion|heartbeats", re.I)


def parse_log(path, entries):
    """→ {idx: {"marks": bool, "errs": [str], "n_err": int}}"""
    text = open(path, encoding="utf-8", errors="replace").read()
    marks = set(int(x) for x in MARK_RE.findall(text))
    errs = collections.defaultdict(list)
    sorry = set()
    unmatched = []
    for line in text.splitlines():
        m = ERR_RE.match(line)
        if m:
            ln, msg = int(m.group(1)), m.group(2)
            hit = [e for e in entries
                   if e["start"] - 1 <= ln <= e["mark_line"]]
            if hit:
                errs[hit[0]["idx"]].append(msg)
            else:
                unmatched.append((ln, msg[:80]))
            continue
        if "declaration uses" in line and "sorry" in line:
            mw = re.match(r"^.*?:(\d+):\d+:", line)
            if mw:
                ln = int(mw.group(1))
                hit = [e for e in entries
                       if e["start"] - 1 <= ln <= e["mark_line"]]
                if hit:
                    sorry.add(hit[0]["idx"])
    out = {}
    for e in entries:
        i = e["idx"]
        out[i] = {"mark": i in marks,
                  "errs": errs.get(i, []),
                  "sorry": i in sorry}
    return out, marks, unmatched


def classify(rec):
    if not rec["mark"]:
        return "INVALID_MARK"
    msgs = rec["errs"]
    if any(BROKEN_PAT.search(x) for x in msgs):
        return "BROKEN"
    if not msgs:
        return "CLOSED" if not rec["sorry"] else "SORRY"
    return "OPEN"


def main():
    m = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
    items = m["items"]
    files = m["files"]
    parsed = {}
    for fname, meta in files.items():
        stem = os.path.splitext(fname)[0]
        p = os.path.join(LOGS, stem + ".log")
        if not os.path.exists(p):
            print("MISSING", p)
            continue
        rec, marks, unmatched = parse_log(p, meta["entries"])
        parsed[stem] = rec
        c = collections.Counter(classify(rec[i]) for i in rec)
        print("%-14s marks=%3d/%d  %s  unmatched_err=%d" %
              (stem, len(marks), len(items), dict(c), len(unmatched)))
        if unmatched[:2]:
            print("   unmatched:", unmatched[:2])

    # ★ 可信判据用「纯前缀」对照：V_base 里的硬错误可能来自模型本步 tactic，
    #   而不是这个 goal state 的前缀，拿它剔除会过严（独立复现已证实）。
    pmap = json.load(open(os.path.join(HERE, "prefix_control_map.json"),
                          encoding="utf-8"))
    vp, pmarks, punmatched = parse_log(
        os.path.join(LOGS, "V_prefix.log"), pmap)
    parsed["V_prefix"] = vp
    pc = collections.Counter(classify(vp[i]) for i in vp)
    print("V_prefix      marks=%3d/%d  %s  unmatched_err=%d" %
          (len(pmarks), len(items), dict(pc), len(punmatched)))

    vb = parsed.get("V_base", {})
    trusted, rejected = [], collections.Counter()
    for it in items:
        i = it["idx"]
        s = classify(vp[i]) if i in vp else "NO_CONTROL"
        if s in ("CLOSED", "OPEN"):
            trusted.append(i)
        else:
            rejected[s] += 1
    print("\n可信点 %d / %d；剔除 %s" % (len(trusted), len(items),
                                     dict(rejected)))
    vb_bad = sum(1 for i in trusted
                 if i in vb and classify(vb[i]) == "BROKEN")
    print("其中 V_base 判坏但纯前缀合法（即模型本步 tactic 写坏）: %d" % vb_bad)

    # 各 hammer 在可信点上的闭合
    table = []
    hits = collections.defaultdict(list)
    for fname, meta in files.items():
        if meta["kind"] != "hammer":
            continue
        stem = os.path.splitext(fname)[0]
        rec = parsed.get(stem, {})
        if not rec:
            continue
        closed = [i for i in trusted if classify(rec[i]) == "CLOSED"]
        for i in closed:
            hits[meta["tactic"]].append(i)
        table.append((meta["tactic"], len(closed),
                      sum(1 for i in closed if items[i]["prefix_len"] == 0)))
    print("\n%-12s %8s %10s" % ("tactic", "闭合点", "其中整题基线"))
    for tac, n, base in table:
        print("%-12s %8d %10d" % (tac, n, base))

    # 题级聚合
    saved = {}
    for tac, idxs in hits.items():
        for i in idxs:
            it = items[i]
            for tag, qid, ok in zip(it["tags"], it["qids"], it["orig_pass"]):
                if ok:            # 原题本来过了，不算救回
                    continue
                # 同一点可来自多臂，按 (idx, tactic) 去重，别把 3 臂算成 3 次
                rec = saved.setdefault(tag, {"qids": set(), "hits": [],
                                             "_seen": set()})
                rec["qids"].add(qid)
                if (i, tac) in rec["_seen"]:
                    continue
                rec["_seen"].add((i, tac))
                rec["hits"].append(
                    {"tactic": tac, "idx": i, "prefix_len": it["prefix_len"],
                     "goal": it["goal"][:200], "arms": sorted(set(it["arms"]))})
    print("\n可被 hammer 闭合的原本失败题：%d" % len(saved))
    for tag in sorted(saved):
        hs = sorted(saved[tag]["hits"], key=lambda x: x["prefix_len"])
        print("  %-5s %2d 个闭合点；最短前缀 %d；tactics=%s" %
              (tag, len(hs), hs[0]["prefix_len"],
               sorted(set(h["tactic"] for h in hs))))

    json.dump({"trusted": trusted, "rejected": dict(rejected),
               "table": table,
               "hits": {k: v for k, v in hits.items()},
               "saved": {t: {"qids": sorted(v["qids"]), "hits": v["hits"]}
                         for t, v in saved.items()},
               "classify": {stem: {str(i): classify(r[i]) for i in r}
                            for stem, r in parsed.items()}},
              open(os.path.join(HERE, "hits.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n→ hits.json")


if __name__ == "__main__":
    main()
