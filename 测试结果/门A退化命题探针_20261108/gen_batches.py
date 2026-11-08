# -*- coding: utf-8 -*-
"""门A 退化命题探针 —— 批次生成器（本地跑，产出 .lean + manifest.json）

目的：对 87 条 STATABLE 签名做「单 tactic 秒闭合」双侧扫描
  P 侧（正命题，9 个 tactic）：能闭合 ⇒ 平凡真 / 空真 候选
  ¬ 侧（取负，5 个 tactic）：能闭合 ⇒ 恒假 候选
只给上界候选，不作判据，不写回仓库。

协议要点
  - set_option autoImplicit false 置于文件首行（E39 同一权威做法）
  - 每条 example 前加 `set_option maxHeartbeats 100000 in`，防单条失控
  - 每条 example 独占一行；error 行号 → manifest 反查 (sg_id, side, tactic)
  - 无 error 行 = 该条闭合
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "门A_autoImplicit体检_20261108",
                   "sig_gate_res_after_fix.json")
OUT = os.path.join(HERE, "lean")
HB = 100000

P_TACTICS = ["simp", "omega", "norm_num", "decide", "linarith",
             "positivity", "rfl", "trivial", "tauto"]
N_TACTICS = ["simp", "omega", "norm_num", "linarith", "positivity"]


def split_sig(sig):
    """example <binders> : <prop> := by sorry  ->  (binders, prop)"""
    s = sig.strip()
    tail = ":= by sorry"
    if not s.endswith(tail):
        raise ValueError("unexpected tail: " + s[-40:])
    s = s[: -len(tail)].rstrip()
    if not s.startswith("example"):
        raise ValueError("not example: " + s[:40])
    rest = s[len("example"):].lstrip()
    i = 0
    while True:
        j = i
        while j < len(rest) and rest[j] == " ":
            j += 1
        if j >= len(rest) or rest[j] not in "([{":
            break
        depth = 0
        k = j
        while k < len(rest):
            ch = rest[k]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= len(rest):
            raise ValueError("unbalanced binder: " + rest[:60])
        i = k + 1
    tailpart = rest[i:].lstrip()
    if not tailpart.startswith(":"):
        raise ValueError("no colon after binders: " + rest[:80])
    binders = rest[:i].strip()
    prop = tailpart[1:].strip()
    if not prop:
        raise ValueError("empty prop")
    return binders, prop


def render(binders, prop, tac):
    head = "example " + (binders + " " if binders else "")
    return "%s: %s := by %s" % (head, prop, tac)


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    st = [x for x in data if x.get("stated") == "STATABLE"]

    # 解析 + 往返校验
    items = []
    bad = 0
    for x in st:
        binders, prop = split_sig(x["sig"])
        rt = "example " + (binders + " " if binders else "") + ": " + prop
        orig = x["sig"].strip()[: -len(":= by sorry")].rstrip().replace("  ", " ")
        if rt.replace("  ", " ") != orig:
            bad += 1
            print("ROUNDTRIP-MISMATCH", x["qid"], x["sg_id"])
            print("  orig:", orig[:120])
            print("  ours:", rt[:120])
        items.append({"idx": len(items), "qid": x["qid"], "run": x.get("run"),
                      "sg_id": x["sg_id"], "type": x.get("type"),
                      "binders": binders, "prop": prop, "sig": x["sig"]})
    print("parsed %d, roundtrip mismatch %d" % (len(items), bad))

    # 命题字符串为 False 的直接标注（无需编译）
    literal_false = [it for it in items if it["prop"].strip() == "False"]
    print("prop == 'False' :", len(literal_false),
          [(it["qid"], it["sg_id"]) for it in literal_false])

    os.makedirs(OUT, exist_ok=True)
    manifest = {"items": items, "files": [], "hb": HB,
                "p_tactics": P_TACTICS, "n_tactics": N_TACTICS}

    for side, tacs in (("P", P_TACTICS), ("N", N_TACTICS)):
        for tac in tacs:
            fname = "%s_%s.lean" % (side, tac)
            lines = ["import Mathlib.Tactic", "set_option autoImplicit false"]
            entries = []
            for it in items:
                if side == "P":
                    code = render(it["binders"], it["prop"], tac)
                else:
                    code = render(it["binders"], "¬ (%s)" % it["prop"], tac)
                lines.append("set_option maxHeartbeats %d in" % HB)
                entries.append({"line": len(lines) + 1, "idx": it["idx"],
                                "side": side, "tactic": tac})
                lines.append(code)
            path = os.path.join(OUT, fname)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
            manifest["files"].append({"file": fname, "side": side,
                                      "tactic": tac, "entries": entries})
            print("wrote %s (%d examples)" % (fname, len(entries)))

    with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("manifest ok")


if __name__ == "__main__":
    sys.exit(main())
