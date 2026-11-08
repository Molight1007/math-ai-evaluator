# -*- coding: utf-8 -*-
"""E44 · 端到端 mock 自测：不连模型，真连服务器 Lean 4.31 编译

目的：证明「prover 回复 -> 代码块抽取 -> 环境适配 -> 服务器编译 ->
严格分类」这条管线判定正确，而不是只测了几个字符串函数。
5 条人工构造的回复分别应落在 CLOSED / ERROR(漂移) / ERROR(sorry) /
UNSOLVED / NO_LEAN_BLOCK 上，任何一条判错都说明管线不可信。

跑法：python mock_selftest.py
产物：mock_units.json / mock_results.json / lean/ / out/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prover_gate import adapt_to_server  # noqa: E402
import verify_proofs as V  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HEAD = """import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat

"""


def unit(name, body, precheck="OK"):
    return {"name": name, "sig": "(mock)", "code": body,
            "precheck": precheck, "reply_len": len(body),
            "tag": name, "qid": "(mock)"}


def main():
    units = [
        # 1 合法证明：adapt 后应 CLOSED
        unit("mock_closed", adapt_to_server(
            HEAD + "theorem mock_closed : (1:ℝ) + 1 = 2 := by norm_num\n")),
        # 2 版本漂移候选：不存在的引理名 -> 硬错 + drift=True
        unit("mock_drift", adapt_to_server(
            HEAD + "theorem mock_drift : (1:ℝ) + 1 = 2 := by "
                   "exact NoSuchLemma.this_does_not_exist\n")),
        # 3 源码带 sorry（绕过 precheck，验证严格判据的 sorry 分支）
        unit("mock_sorry", adapt_to_server(
            HEAD + "theorem mock_sorry : (1:ℝ) + 1 = 2 := by sorry\n")),
        # 4 空 proof body -> unsolved goals
        unit("mock_open", adapt_to_server(
            HEAD + "theorem mock_open (n : ℕ) : n = n := by\n")),
        # 5 没抽到代码块 -> 预检直接拦下，不送编译
        unit("mock_noblock", "", precheck="NO_LEAN_BLOCK"),
    ]
    with open(os.path.join(HERE, "mock_units.json"), "w",
              encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)

    compiled = V.compile_units(units, srv_tag="mock")
    summary = V.report(units, compiled,
                       os.path.join(HERE, "mock_results.json"))
    rows = {r["name"]: r for r in
            json.load(open(os.path.join(HERE, "mock_results.json"),
                           encoding="utf-8"))["rows"]}

    expect = {
        "mock_closed": ("CLOSED", False),
        "mock_drift": ("ERROR", True),
        "mock_sorry": ("ERROR", False),
        "mock_open": ("UNSOLVED", False),
        "mock_noblock": ("NO_LEAN_BLOCK", False),
    }
    ok = True
    print("\n=== 端到端断言 ===")
    for name, (want_status, want_drift) in expect.items():
        got = rows[name]["status"]
        drift = rows[name]["drift"]
        good = (got == want_status and drift == want_drift)
        ok &= good
        print("  %-14s want=%-13s got=%-13s drift=%-5s %s" %
              (name, want_status, got, drift, "PASS" if good else "FAIL"))
        if got == "ERROR":
            print("       first_error: %s" % (rows[name]["hard"][:1] or ""))
    print("\nSELFTEST=%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
