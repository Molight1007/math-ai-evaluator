# -*- coding: utf-8 -*-
"""E44 · 零 LLM 预检：18 题签名套 Goedel 官方头后，在服务器 Lean 4.31 可陈述吗？

接 prover 之前必须先回答：把 L2 的 `example ... := by sorry` 改成
`theorem NAME` 并套上 Goedel 的 import/heartbeats/open 头之后，这些命题
在**我们的** Lean 4.31 + Mathlib fabf563a 上是否仍是合法声明。
若这里就大面积报错，后面 prover 生成什么都没意义（且会把环境错
误当成模型能力问题）。

判据（复用 E43 严格判据）：
  hard=0 且 sorry=True  -> STATABLE（只有 sorry 警告，声明本身合法）
  hard>0                -> ILLEGAL（环境适配引入了硬错）
零 LLM、确定性、无噪声。
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prover_gate import to_formal_statement, adapt_to_server  # noqa: E402
import verify_proofs as V  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
B_JSON = os.path.join(HERE, "..", "L2逐步探针_20261108",
                      "l2_step_probe_b_base2.json")


def main():
    with open(B_JSON, encoding="utf-8") as f:
        rows = json.load(f)
    units = []
    for r in rows:
        name = "probe_" + str(r["tag"])
        stmt = to_formal_statement(r["formal_sig"], name)
        units.append({
            "name": name, "sig": r["formal_sig"],
            "code": adapt_to_server(stmt),   # 故意保留 by sorry
            "precheck": "OK", "reply_len": 0,
            "tag": r["tag"], "qid": r["qid"],
        })
    compiled = V.compile_units(units, srv_tag="dryrun")
    out, kinds = [], collections.Counter()
    for u in units:
        c = compiled.get(u["name"], {})
        hard, sorry = c.get("n_hard", 0), c.get("has_sorry", False)
        state = "STATABLE" if hard == 0 and sorry else "ILLEGAL"
        if hard:
            kinds[(c.get("hard") or [""])[0][:70]] += 1
        out.append(dict(name=u["name"], tag=u["tag"], qid=u["qid"],
                        state=state, n_hard=hard,
                        first_error=(c.get("hard") or [""])[0],
                        has_sorry=sorry))
    n_st = sum(1 for x in out if x["state"] == "STATABLE")
    summary = {"n": len(out), "statable": n_st, "illegal": len(out) - n_st,
               "statable_rate": round(100.0 * n_st / len(out), 1),
               "hard_error_types": kinds.most_common(10)}
    with open(os.path.join(HERE, "dryrun_results.json"), "w",
              encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": out}, f,
                  ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for x in out:
        if x["state"] == "ILLEGAL":
            print("  ILLEGAL %-4s %s" % (x["tag"], x["first_error"][:100]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
