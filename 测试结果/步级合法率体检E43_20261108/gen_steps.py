# -*- coding: utf-8 -*-
"""E43 步级合法率体检 —— 批次生成器（11-08）

动机
----
E42 顺带发现：`测试结果/L2逐步探针_20261107/l2_step_probe.py::compile_check`
是「先匹配 `error: unsolved goals` 就 return UNSOLVED」，而 Lean 在硬错误
（unknown constant / type mismatch / 缩进散架）之后做错误恢复，仍会输出
`unsolved goals` => 探针把非法步当成合法步继续往下走。E42 在去重后的 283 个
goal state 上量到 139 个（49.1%）前缀本身非法。

本脚本做的是**按步重判**（E42 是按去重点）：把三臂 54 条轨迹的每一个
非空 tactic 步都重建出来，用严格判据离线重编译，回答：
  1. 探针记为 UNSOLVED 的步里，有多少其实是 HARD_ERROR？
  2. 真实合法步率是多少（按臂 / 按题 / 按步序分层）？
  3. 「前缀本身非法」与「本步 tactic 非法」各占多少？
  4. 修多行缩进能救回多少？（单变量对照）

严格口径
--------
- build_body 与 v3 探针 `build_code` **逐字一致**（含 SORRY_TAIL 替换与
  缩进规则），不关 autoImplicit（E39 只改门A 编译，主编译口径不变）。
- 三个文件、同一批步，互为单变量对照：
    S_full.lean      sig + 前缀 + 本步 tactic（探针当时编译的东西）
    S_prefix.lean    sig + 前缀（探针在每步开头编译的东西）
    S_full_ind.lean  S_full 但多行 tactic 每行补 2 空格（只改缩进）
- 每条 example 后 `#eval "MARK_<idx>"` 哨兵；哨兵缺失 => 语法灾难吞掉了
  后续命令，该步判 INVALID。
- 编译必须 `lean -DmaxErrors=10000`：文件内 `set_option maxErrors N` 在
  Lean 4.31 无效（硬上限 100，第 100 个 error 即 exiting）。
- 诊断格式有两种：`error: ...` 与 `error(lean.unknownIdentifier): ...`，
  解析只认前者会造假闭合（E42 首轮误报 q24）。
"""
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


def build_body(sig, tactics, indent=False):
    """逐字复刻 l2_step_probe.py::build_code（去掉文件头 import，由批次统一加）。

    indent=True 是唯一变量：把多行 tactic 的每一行都补成 >=2 空格。
    """
    body = sig.strip()
    body = SORRY_TAIL.sub(":= by", body)
    if tactics:
        chunks = []
        for t in tactics:
            if indent:
                # 每行统一 +2 空格（原来只有首行有 2 空格，后续行散架）
                chunks.append("\n".join("  " + ln.lstrip() for ln in t.split("\n")))
            else:
                chunks.append("  " + t.lstrip() if not t.startswith("  ") else t)
        body += "\n" + "\n".join(chunks)
    return body + "\n"


def collect():
    """按步收集，返回 steps 列表（每步带探针当时的前缀与本步 tactic）。"""
    steps = []
    for arm, path in ARMS:
        rows = json.load(open(path, encoding="utf-8"))
        for r in rows:
            sig = r["formal_sig"]
            accepted = []          # 探针 tactics[]：只有 verify==UNSOLVED 才 append
            for rec in r.get("trace", []):
                tac = (rec.get("tactic") or "").strip()
                banned = bool(rec.get("banned")) or bool(BANNED.search(tac))
                if not tac or banned:
                    # 空 / 含 sorry：探针提前 return，根本没编译这一步
                    steps.append({
                        "idx": len(steps), "arm": arm, "tag": r["tag"],
                        "qid": r.get("qid", ""), "step": rec.get("step"),
                        "probe_verify": rec.get("verify", "(无)"),
                        "tactic": tac, "prefix": list(accepted),
                        "prefix_len": len(accepted), "compiled": False,
                        "orig_pass": bool(r.get("pass")),
                    })
                    continue
                steps.append({
                    "idx": len(steps), "arm": arm, "tag": r["tag"],
                    "qid": r.get("qid", ""), "step": rec.get("step"),
                    "probe_verify": rec.get("verify", "(无)"),
                    "tactic": tac, "prefix": list(accepted),
                    "prefix_len": len(accepted), "compiled": True,
                    "orig_pass": bool(r.get("pass")),
                    "sig": sig,
                })
                if rec.get("verify") == "UNSOLVED":
                    accepted.append(tac)
    return steps


def render_file(steps, kind, sig_of):
    """生成单个批次；kind in {full, prefix, indent}。"""
    lines = ["import Mathlib.Tactic", ""]
    entries = []
    for s in steps:
        if not s["compiled"]:
            continue
        tactics = list(s["prefix"])
        if kind == "full":
            tactics.append(s["tactic"])
        elif kind == "indent":
            tactics.append(s["tactic"])
        # kind == "prefix"：只有前缀
        body = build_body(sig_of(s), tactics, indent=(kind == "indent"))
        lines.append("set_option maxHeartbeats %d in" % HB)
        start = len(lines) + 1
        lines.extend(body.rstrip("\n").split("\n"))
        end = len(lines)
        lines.append('#eval "MARK_%d"' % s["idx"])
        lines.append("")
        entries.append({"idx": s["idx"], "start": start, "end": end,
                        "mark_line": end + 1})
    return "\n".join(lines) + "\n", entries


def main():
    steps = collect()
    n = sum(1 for s in steps if s["compiled"])
    print("轨迹 %d 条；总步 %d；实际编译过的步 %d；未编译（EMPTY/BANNED）%d" %
          (len(set((s["arm"], s["tag"]) for s in steps)), len(steps), n,
           len(steps) - n))
    os.makedirs(OUT, exist_ok=True)
    sig_of = lambda s: s["sig"]  # noqa: E731
    files = {}
    for kind, fname in (("full", "S_full.lean"),
                        ("prefix", "S_prefix.lean"),
                        ("indent", "S_full_ind.lean")):
        text, entries = render_file(steps, kind, sig_of)
        open(os.path.join(OUT, fname), "w", encoding="utf-8",
             newline="\n").write(text)
        files[fname] = {"kind": kind, "entries": entries}
        print("  %-18s %5d lines / %d examples" %
              (fname, text.count("\n"), len(entries)))
    json.dump({"steps": steps, "files": files, "hb": HB},
              open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("total examples =", sum(len(f["entries"]) for f in files.values()))


if __name__ == "__main__":
    main()
