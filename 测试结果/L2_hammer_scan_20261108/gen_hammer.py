# -*- coding: utf-8 -*-
"""L2 hammer 扫描 —— 批次生成器（E42，11-08）

动机：E41 量出 n=18 题级 A/B 完全在噪声底内。改做**确定性、零 LLM 配额**的扫描：
把三臂 trace 里每个「模型写 tactic 之前」的 goal state 重建出来，
在已编译通过的前缀后面追加一支 Lean 自带自动化战术，看能否闭合。

严格口径
  - build_code 与 v3 探针逐字一致（含 SORRY_TAIL / 缩进规则），**不关 autoImplicit**
    （E39 只改门A 编译，主编译口径不变）。
  - 只把 verify == UNSOLVED 的 tactic 追加进前缀；遇到 ERROR/CLOSED/EMPTY/BANNED 即停。
  - 每个扫描点另生成 V_base 对照：prefix + 模型原 tactic，
    预期 UNSOLVED ⇒ 只有 unsolved goals；CLOSED ⇒ 零 error。
    不符的扫描点在解析时剔除，绝不当闭合。
  - 每条 example 后跟 `#eval "MARK_<idx>"` 哨兵；
    哨兵缺失 ⇒ 前面的语法灾难吞掉了后续命令，该点判 INVALID。
  - 按 (sig, prefix) 去重；prefix_len == 0 是「整题基线」，单独统计，不算步级救回。
"""
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "lean")
PREV = os.path.join(os.path.dirname(HERE), "L2逐步探针_20261108")
ARMS = [
    ("b_fix", os.path.join(os.path.dirname(HERE), "L2逐步探针_20261107",
                           "l2_step_probe_b_fix.json")),
    ("base2", os.path.join(PREV, "l2_step_probe_b_base2.json")),
    ("rej", os.path.join(PREV, "l2_step_probe_b_rej.json")),
]
SORRY_TAIL = re.compile(r":=\s*by\s+sorry\b")
BANNED = re.compile(r"\b(sorry|admit)\b")
HB = 200000  # 与 Lean 默认一致，避免降低上限误伤探针里已通过的前缀

TACTICS = ["omega", "nlinarith", "linarith", "simp_all", "norm_num",
           "positivity", "ring_nf", "exact?", "aesop"]


def build_body(sig, tactics):
    """逐字复刻 l2_step_probe.py::build_code（去掉文件头 import，由批次统一加）。"""
    body = sig.strip()
    body = SORRY_TAIL.sub(":= by", body)
    if tactics:
        body += "\n" + "\n".join("  " + t.lstrip() if not t.startswith("  ") else t
                                 for t in tactics)
    return body + "\n"


def collect():
    """返回去重后的扫描点。"""
    seen = {}
    stats = {"rows": 0, "points_raw": 0, "stop_at": {}}
    for arm, path in ARMS:
        rows = json.load(open(path, encoding="utf-8"))
        for r in rows:
            stats["rows"] += 1
            sig = r["formal_sig"]
            prefix = []
            for rec in r.get("trace", []):
                tac = (rec.get("tactic") or "").strip()
                verify = rec.get("verify")
                banned = bool(rec.get("banned")) or bool(BANNED.search(tac))
                # 本步之前的 prefix 编译状态必为 UNSOLVED（探针循环前提）
                key = hashlib.md5((sig + "\x00" + "\x00".join(prefix))
                                  .encode("utf-8")).hexdigest()
                stats["points_raw"] += 1
                if key not in seen:
                    seen[key] = {
                        "idx": len(seen),
                        "sig": sig,
                        "prefix": list(prefix),
                        "prefix_len": len(prefix),
                        "goal": rec.get("goal", ""),
                        "model_tac": tac if (tac and not banned) else "",
                        "model_verify": verify,
                        "model_banned": banned,
                        "arms": [],
                        "tags": [],
                        "qids": [],
                        "steps": [],
                        "orig_pass": [],
                    }
                it = seen[key]
                it["arms"].append(arm)
                it["tags"].append(r["tag"])
                it["qids"].append(r.get("qid", ""))
                it["steps"].append(rec.get("step"))
                it["orig_pass"].append(bool(r.get("pass")))
                if tac and not banned and verify == "UNSOLVED":
                    prefix.append(tac)
                else:
                    cause = ("EMPTY" if not tac else
                             "BANNED" if banned else str(verify))
                    stats["stop_at"][cause] = stats["stop_at"].get(cause, 0) + 1
                    break
    items = [seen[k] for k in sorted(seen, key=lambda k: seen[k]["idx"])]
    return items, stats


def render_file(items, tac, is_base=False):
    """生成单个批次文件；返回 (文本, [{idx, start, end, mark_line}])。"""
    # 注意：Lean 4.31 里文件内 `set_option maxErrors N` 不生效（硬上限 100，
    # 第 100 个 error 直接 exiting）；必须由命令行 `lean -DmaxErrors=10000` 放开。
    lines = ["import Mathlib.Tactic", ""]
    entries = []
    for it in items:
        tactics = list(it["prefix"])
        if is_base:
            if it["model_tac"]:
                tactics.append(it["model_tac"])
        else:
            tactics.append(tac)
        body = build_body(it["sig"], tactics)
        lines.append("set_option maxHeartbeats %d in" % HB)
        start = len(lines) + 1
        lines.extend(body.rstrip("\n").split("\n"))
        end = len(lines)
        mark = "%d" % it["idx"]
        lines.append('#eval "MARK_%s"' % mark)
        lines.append("")
        entries.append({"idx": it["idx"], "start": start, "end": end,
                        "mark_line": end + 1})
    return "\n".join(lines) + "\n", entries


def main():
    items, stats = collect()
    print("rows=%d  raw_points=%d  unique_points=%d" %
          (stats["rows"], stats["points_raw"], len(items)))
    print("stop_at:", stats["stop_at"])
    print("prefix_len=0 (整题基线):", sum(1 for x in items if x["prefix_len"] == 0))
    print("原题 pass=False 的点:", sum(1 for x in items
                                     if not any(x["orig_pass"])))
    os.makedirs(OUT, exist_ok=True)
    files = {}
    for tac in TACTICS:
        fname = "H_%s.lean" % tac.replace("?", "q")
        text, entries = render_file(items, tac)
        open(os.path.join(OUT, fname), "w", encoding="utf-8",
             newline="\n").write(text)
        files[fname] = {"tactic": tac, "kind": "hammer", "entries": entries}
    text, entries = render_file(items, None, is_base=True)
    open(os.path.join(OUT, "V_base.lean"), "w", encoding="utf-8",
         newline="\n").write(text)
    files["V_base.lean"] = {"tactic": "(模型原 tactic)", "kind": "control",
                           "entries": entries}
    json.dump({"items": items, "files": files, "hb": HB,
               "tactics": TACTICS, "stats": stats},
              open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for f in files:
        print("  %-18s %5d lines" %
              (f, sum(1 for _ in open(os.path.join(OUT, f), encoding="utf-8"))))
    print("total examples =", len(items) * (len(TACTICS) + 1))


if __name__ == "__main__":
    main()
