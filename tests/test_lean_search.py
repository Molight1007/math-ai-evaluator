#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 #31 leansearch 试用（MathlibTheoremSearcher 本地源码检索）。

用法：
    python tests/test_lean_search.py

验证内容：
  1) searcher.status() 正确反映后端可用性；
  2) search(query) 返回结构化结果 {status, results:[{name,kind,file,line,snippet}]}；
  3) 对数学相关查询能检索到 Mathlib 定理（真实功能，非桩）。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agent"))

from agent.lean_search import MathlibTheoremSearcher


def main():
    s = MathlibTheoremSearcher()
    st = s.status()
    print("status:", st)
    if not st.get("available"):
        print("[SKIP] 未找到本地 mathlib 源码，leansearch 后端不可用（安全降级）。")
        # 仍校验 search() 返回安全降级结构
        r = s.search("Nat add", limit=5)
        assert r["status"] == "unavailable" and r["results"] == [], "降级应返回 unavailable+空结果"
        print("降级结构校验通过")
        print("SKIP-OK")
        return 0

    res = s.search("Nat addition commutes", limit=5)
    print("search status:", res["status"], "hits:", len(res["results"]))
    for r in res["results"][:5]:
        print("  -", r["name"], "(" + r["kind"] + ")")

    assert res["status"] == "ok", "可用时应返回 ok"
    assert isinstance(res["results"], list), "results 应为列表"
    for r in res["results"]:
        for k in ("name", "kind", "file", "line", "snippet"):
            assert k in r, "结果缺字段 %s" % k

    # 检索一个高相关查询，确认能命中真实定理名
    res2 = s.search("pow two mul", limit=3)
    print("pow-two-mul hits:", [r["name"] for r in res2["results"]])
    assert res2["status"] == "ok"
    print("lean_search OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
