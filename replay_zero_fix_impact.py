# -*- coding: utf-8 -*-
"""重判「符号零判定」分支，重算闸门代价（修复前 vs 修复后）。零 LLM、零配额。

为什么只挑一部分行重判
----------------------
`_judge_subgoal_objective` 有多个分支（多候选符号多数 / 契约等式 / <check> 断言）。
本次修复只动了**零判定**，所以只重判落在下面两类判词上的行：

    本步结论等式经 SymPy 客观判定…
    结果中 <check> 断言…

其余行（多 agent 多数、undecided 等）原样保留 —— 全量重判会改变别的分支口径，
让对比混入无关变化。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

import replay_gate_sim as G  # noqa: E402
from agent import sub_goal_solver__lean as LN  # noqa: E402
from agent import sub_goal_solver__contract as CT  # noqa: E402

_TARGET_REASON = re.compile(r"^(本步结论等式经 SymPy|结果中 <check> 断言)")


class _Shim(object):
    _sympy_judge = LN._sympy_judge
    _extract_check_asserts = LN._extract_check_asserts
    _parse_step_contract = CT._parse_step_contract
    _verify_candidates_objective = staticmethod(CT._verify_candidates_objective)
    _judge_subgoal_objective = CT._judge_subgoal_objective
    _pow_to_python = staticmethod(CT._pow_to_python)
    _tail_after_conclusion = CT._tail_after_conclusion
    _extract_derivation_block = staticmethod(CT._extract_derivation_block)
    _answer_from_raw = CT._answer_from_raw
    _CONCL_LINE_RE = re.compile(r"本步结论\s*[:：]\s*(值|等式|判定)\s*=\s*(.+)")
    _SUPPORT_LINE_RE = re.compile(r"本步依据\s*[:：]\s*(.+)")
    _CHECK_RE = re.compile(r"<check>(.*?)</check>", re.DOTALL)
    _L2_EXPR_CHARS = re.compile(r"^[0-9a-zA-Z^*/+\-() ]+$")
    _MIN_DERIVATION_CHARS = 20


def load_rows(qdir):
    p = os.path.join(qdir, "04_subgoal_results.jsonl")
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def rejudge(rows, shim):
    """返回 (新行列表, 改判统计)。"""
    new_rows = []
    stat = {"in_scope": 0, "incorrect_to_other": 0, "other_to_incorrect": 0,
            "same": 0, "parse_err": 0, "by_new": {}}
    for r in rows:
        reason = str(r.get("objective_reason") or "")
        if not _TARGET_REASON.match(reason):
            new_rows.append(r)
            continue
        stat["in_scope"] += 1
        res = str(r.get("result") or "")
        answers = [str(x) for x in (r.get("candidate_answers") or [])]
        try:
            contract = shim._parse_step_contract(res)
            _, v, reason2 = shim._judge_subgoal_objective(
                {}, contract, res, answers, existing_idx=-1)
        except Exception:  # noqa: BLE001
            stat["parse_err"] += 1
            new_rows.append(r)
            continue
        stat["by_new"][v] = stat["by_new"].get(v, 0) + 1
        old = str(r.get("objective_verdict") or "")
        if old == "incorrect" and v != "incorrect":
            stat["incorrect_to_other"] += 1
        elif old != "incorrect" and v == "incorrect":
            stat["other_to_incorrect"] += 1
        else:
            stat["same"] += 1
        nr = dict(r)
        nr["objective_verdict"] = v
        nr["objective_reason"] = reason2
        new_rows.append(nr)
    return new_rows, stat


def gate_stats(qs, rows_fn, level):
    n = tail = passed = 0
    for q in qs:
        rows = rows_fn(q)
        if not rows:
            continue
        r = G.simulate(rows, level)
        n += 1
        tail += 1 if r["reached_tail"] else 0
        passed += 1 if r["tail_passes"] else 0
    return n, tail, passed


def main():
    idx = sys.argv[1]
    qs = G.load_qdirs(idx)
    qs = [q for q in qs if str(q.get("run_id") or "")[:8] >= "20261015"]
    shim = _Shim()

    cache = {}
    total = {"in_scope": 0, "incorrect_to_other": 0, "other_to_incorrect": 0,
             "same": 0, "parse_err": 0}
    by_new = {}
    for q in qs:
        rows = load_rows(q["qdir"])
        nr, st = rejudge(rows, shim)
        cache[q["qdir"]] = (rows, nr)
        for k in total:
            total[k] += st[k]
        for k, v in st["by_new"].items():
            by_new[k] = by_new.get(k, 0) + v

    print("== 重判范围（只含符号零判定分支）==")
    print("  后期题次 %d，纳入重判的行 %d" % (len(qs), total["in_scope"]))
    print("  判词未变 %d / incorrect→其它 %d / 其它→incorrect %d / 解析失败 %d"
          % (total["same"], total["incorrect_to_other"],
             total["other_to_incorrect"], total["parse_err"]))
    print("  重判后判词分布:", by_new)

    print("\n== 闸门代价：修复前 vs 修复后（后期题次）==")
    for lv in G.LEVELS:
        n0, t0, p0 = gate_stats(qs, lambda q: cache[q["qdir"]][0], lv)
        n1, t1, p1 = gate_stats(qs, lambda q: cache[q["qdir"]][1], lv)
        print("  %s（%s）" % (lv, G.LEVEL_DESC[lv]))
        print("     修复前 走完 %3d/%3d=%5.1f%%   达标 %3d=%5.1f%%"
              % (t0, n0, 100.0 * t0 / max(n0, 1), p0, 100.0 * p0 / max(n0, 1)))
        print("     修复后 走完 %3d/%3d=%5.1f%%   达标 %3d=%5.1f%%"
              % (t1, n1, 100.0 * t1 / max(n1, 1), p1, 100.0 * p1 / max(n1, 1)))


if __name__ == "__main__":
    main()
