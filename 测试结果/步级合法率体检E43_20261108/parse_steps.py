# -*- coding: utf-8 -*-
"""E43 解析：按步把「严格编译结果」对齐到探针记录的 verify。

判据（严格）
------------
  INVALID     哨兵缺失（语法灾难吞掉后续命令）
  HARD_ERROR  存在任何非 unsolved-goals 的 error 行（两种 error 格式都认）
  SORRY       仅 sorry 警告
  CLOSED      零 error + 零 sorry
  OPEN        只剩 unsolved goals（合法但未闭合）

三个文件互为单变量：S_full / S_prefix / S_full_ind（后者只改多行缩进）。
按行号区间把诊断归属到条目；归属不上的诊断单独列出，防止静默丢错。
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compile_check_strict import (  # noqa: E402
    DIAG_RE, UNSOLVED_RE, SORRY_RE, STATES, collect_diags, classify_compile)

MARK_RE = re.compile(r"MARK_(\d+)")
FILES = {"full": "S_full.log", "prefix": "S_prefix.log",
         "indent": "S_full_ind.log"}


def parse_log(kind, m):
    """返回 {idx: {cls, errs, hard, warns}}。"""
    path = os.path.join(HERE, "out", FILES[kind])
    text = open(path, encoding="utf-8", errors="replace").read()
    marks = set(int(x) for x in MARK_RE.findall(text))
    entries = m["files"]["S_full.lean" if kind != "prefix" else "S_prefix.lean"]["entries"]
    if kind == "indent":
        entries = m["files"]["S_full_ind.lean"]["entries"]
    buckets = collections.defaultdict(lambda: {"errs": [], "warns": []})
    unmatched = []
    for line in text.splitlines():
        dm = DIAG_RE.match(line)
        if not dm:
            continue
        ln, sev, msg = int(dm.group(1)), dm.group(2), dm.group(3)
        hit = [e for e in entries if e["start"] - 1 <= ln <= e["mark_line"]]
        if not hit:
            unmatched.append((ln, sev, msg[:90]))
            continue
        i = hit[0]["idx"]
        buckets[i]["errs" if sev == "error" else "warns"].append(msg)
    out = {}
    for e in entries:
        i = e["idx"]
        b = buckets[i]
        hard = [x for x in b["errs"] if not UNSOLVED_RE.search(x)]
        sorry = any(SORRY_RE.search(x) for x in b["warns"])
        if i not in marks:
            cls = "INVALID"
        elif hard:
            cls = "HARD_ERROR"
        elif sorry:
            cls = "SORRY"
        elif not b["errs"]:
            cls = "CLOSED"
        else:
            cls = "OPEN"
        out[i] = {"cls": cls, "errs": b["errs"], "hard": hard,
                  "warns": b["warns"]}
    return out, unmatched, len(marks)


def main():
    m = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
    steps = m["steps"]
    parsed = {}
    for kind in FILES:
        parsed[kind], unmatched, nmark = parse_log(kind, m)
        print("%-8s 哨兵 %d / 条目 %d / 未归属诊断 %d" %
              (kind, nmark, len(parsed[kind]), len(unmatched)))
        if unmatched:
            for x in unmatched[:5]:
                print("    ! 未归属:", x)

    compiled = [s for s in steps if s["compiled"]]
    print("\n总步 %d，实际编译 %d，未编译 %d" %
          (len(steps), len(compiled), len(steps) - len(compiled)))

    # ---- 1. 探针记录 vs 严格整体判据 ----
    print("\n=== 1. 探针 verify × 严格 S_full 分类（核心对照）===")
    tab = collections.Counter((s["probe_verify"], parsed["full"][s["idx"]]["cls"])
                              for s in compiled)
    probes = sorted(set(s["probe_verify"] for s in compiled))
    clss = ["OPEN", "CLOSED", "HARD_ERROR", "SORRY", "INVALID"]
    print("%-14s %s" % ("probe\\strict", "".join("%12s" % c for c in clss)))
    for p in probes:
        print("%-14s %s" % (p, "".join("%12d" % tab[(p, c)] for c in clss)))
    pu = [s for s in compiled if s["probe_verify"] == "UNSOLVED"]
    fake = [s for s in pu if parsed["full"][s["idx"]]["cls"] == "HARD_ERROR"]
    print("→ 探针记 UNSOLVED %d 步，其中严格判为 HARD_ERROR %d 步（%.1f%%）" %
          (len(pu), len(fake), 100.0 * len(fake) / max(len(pu), 1)))

    # ---- 2. 前缀归因 ----
    print("\n=== 2. 前缀合法性（S_prefix，探针每步开头会编译它）===")
    pc = collections.Counter(parsed["prefix"][s["idx"]]["cls"] for s in compiled)
    print("  ", dict(pc))
    bad_prefix = [s for s in compiled
                  if parsed["prefix"][s["idx"]]["cls"] in ("HARD_ERROR", "INVALID")]
    print("  前缀本身非法：%d / %d（%.1f%%）" %
          (len(bad_prefix), len(compiled),
           100.0 * len(bad_prefix) / len(compiled)))
    pref_ok = [s for s in compiled
               if parsed["prefix"][s["idx"]]["cls"] in ("OPEN", "CLOSED")]
    step_bad = [s for s in pref_ok
                if parsed["full"][s["idx"]]["cls"] == "HARD_ERROR"]
    print("  前缀合法 %d 步；其中本步 tactic 引入硬错误 %d 步（%.1f%%）" %
          (len(pref_ok), len(step_bad),
           100.0 * len(step_bad) / max(len(pref_ok), 1)))

    # ---- 3. 真实合法步率（两个口径）----
    print("\n=== 3. 合法步率 ===")
    for name, pool in (("全体编译步", compiled),
                       ("仅前缀合法的步", pref_ok)):
        legal = [s for s in pool
                 if parsed["full"][s["idx"]]["cls"] in ("OPEN", "CLOSED")]
        print("  %-16s 严格合法 %3d / %3d = %.1f%%" %
              (name, len(legal), len(pool),
               100.0 * len(legal) / max(len(pool), 1)))
        print("  %-16s 探针口径合法 %3d / %3d = %.1f%%" %
              ("", sum(1 for s in pool if s["probe_verify"] == "UNSOLVED"),
               len(pool),
               100.0 * sum(1 for s in pool if s["probe_verify"] == "UNSOLVED")
               / max(len(pool), 1)))

    # ---- 4. 分层：按臂 / 按步序 / 按题 ----
    print("\n=== 4. 分层（严格合法率，仅前缀合法的步）===")
    for key, label in (("arm", "按臂"), ("step", "按步序")):
        g = collections.defaultdict(list)
        for s in pref_ok:
            g[s[key]].append(s)
        print("  -- %s" % label)
        for k in sorted(g, key=lambda x: (str(type(x)), x)):
            pool = g[k]
            legal = sum(1 for s in pool
                        if parsed["full"][s["idx"]]["cls"] in ("OPEN", "CLOSED"))
            print("     %-10s %3d 步  合法 %3d  %.1f%%" %
                  (str(k), len(pool), legal, 100.0 * legal / len(pool)))
    g = collections.defaultdict(list)
    for s in pref_ok:
        g[s["tag"]].append(s)
    rates = []
    for k, pool in g.items():
        legal = sum(1 for s in pool
                    if parsed["full"][s["idx"]]["cls"] in ("OPEN", "CLOSED"))
        rates.append((k, legal, len(pool), 100.0 * legal / len(pool)))
    print("  -- 按题（%d 个 tag）：合法率 min %.1f%% / 中位 %.1f%% / max %.1f%%" %
          (len(rates), min(x[3] for x in rates),
           sorted(x[3] for x in rates)[len(rates) // 2],
           max(x[3] for x in rates)))

    # ---- 5. 修缩进的单变量对照 ----
    print("\n=== 5. 只修多行缩进（S_full_ind）===")
    multi = [s for s in compiled if "\n" in s["tactic"]]
    saved, newly_bad = [], []
    for s in multi:
        a, b = parsed["full"][s["idx"]]["cls"], parsed["indent"][s["idx"]]["cls"]
        if a == "HARD_ERROR" and b in ("OPEN", "CLOSED"):
            saved.append(s)
        if a in ("OPEN", "CLOSED") and b == "HARD_ERROR":
            newly_bad.append(s)
    print("  多行 tactic 步 %d；修缩进救回 %d（%.1f%%）；反而变坏 %d" %
          (len(multi), len(saved), 100.0 * len(saved) / max(len(multi), 1),
           len(newly_bad)))
    all_hard = [s for s in compiled if parsed["full"][s["idx"]]["cls"] == "HARD_ERROR"]
    all_saved = [s for s in all_hard
                 if parsed["indent"][s["idx"]]["cls"] in ("OPEN", "CLOSED")]
    print("  全体 HARD_ERROR %d 步里，修缩进只救回 %d（%.1f%%）" %
          (len(all_hard), len(all_saved),
           100.0 * len(all_saved) / max(len(all_hard), 1)))

    # ---- 6. 硬错误类型分布 ----
    print("\n=== 6. HARD_ERROR 首条硬错误类型（top 12）===")
    c = collections.Counter()
    for s in all_hard:
        first = parsed["full"][s["idx"]]["hard"][0]
        c[re.sub(r"`[^`]*`", "`X`", first)[:72]] += 1
    for k, v in c.most_common(12):
        print("   %4d  %s" % (v, k))

    # ---- 7. 落盘 ----
    out = {
        "n_steps": len(steps), "n_compiled": len(compiled),
        "probe_unsolved": len(pu), "fake_unsolved": len(fake),
        "bad_prefix": len(bad_prefix), "prefix_ok": len(pref_ok),
        "step_bad": len(step_bad),
        "strict_legal_all": sum(1 for s in compiled
                                if parsed["full"][s["idx"]]["cls"] in ("OPEN", "CLOSED")),
        "strict_legal_pref_ok": sum(1 for s in pref_ok
                                    if parsed["full"][s["idx"]]["cls"] in ("OPEN", "CLOSED")),
        "indent_saved": len(all_saved), "indent_newly_bad": len(newly_bad),
        "classify": {k: {str(i): v["cls"] for i, v in d.items()}
                     for k, d in parsed.items()},
        "fake_idx": [s["idx"] for s in fake],
        "hard_types": dict(c.most_common()),
        "states": sorted(STATES),
    }
    json.dump(out, open(os.path.join(HERE, "results.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写 results.json")


if __name__ == "__main__":
    main()
