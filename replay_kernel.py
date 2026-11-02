"""离线回放：把历史产物喂进六步内核，只跑裁决 / 投影 / 交付。

为什么只跑后三步
----------------
前三步（理解 / 规划 / 求解）需要模型调用。历史产物里已经有它们的输出
（03 的节点、04 的求解结论），所以回放复用这些输出，把新内核的**判定与
结构**部分单独跑一遍。这样零模型调用、零配额，可以反复重跑。

两档必须分开报
--------------
honest   只用真实的工具执行痕迹。历史数据里工具级验证 0 条 ⇒ 本档的
         proven 必然为 0。这个 0 不是在说「新内核不行」，它是在说
         「过去一次都没真验过」，与 E21 的 HARD_CLOSED=0/448 同一件事。
ceiling  反事实上界：把「模型判对」当作工具通过。**这是上界，不是估计**
         —— 它的用途是回答「如果所有模型判对都是真对，最多能证出几题」，
         绝不能当成预期值引用。

用法：
    python replay_kernel.py --results results [--json out.json]
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import replay_blueprint_license as RBL  # noqa: E402  复用标签配对逻辑
from agent.kernel import (  # noqa: E402
    DELIVERY_NONE, DELIVERY_PROVEN, DELIVERY_UNPROVEN, Kernel, PlanNode,
    SolveOutcome, topo_order,
)
from agent.kernel.judge import make_checker_result  # noqa: E402
from contracts.closure import (  # noqa: E402
    CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_SOFT, CLOSURE_UNMAPPED,
)
from contracts.proof_ledger import ADMIT_HARD, ADMIT_SOFT  # noqa: E402


def load_cases(results_dir):
    """遍历 run 目录，取有 03 + 04 的题次，并配判对标签。"""
    by_qid, by_jsonl_qid, run_to_jsonl = RBL.build_label_index(results_dir)
    cases = []
    for run_dir in sorted(glob.glob(os.path.join(results_dir, "2026*"))):
        if not os.path.isdir(run_dir):
            continue
        run_name = os.path.basename(run_dir)
        for qdir in sorted(glob.glob(os.path.join(run_dir, "q*"))):
            if not os.path.isdir(qdir):
                continue
            p3 = os.path.join(qdir, "03_subgoals.json")
            p4 = os.path.join(qdir, "04_subgoal_results.jsonl")
            if not (os.path.isfile(p3) and os.path.isfile(p4)):
                continue
            qid = os.path.basename(qdir)
            label, src = RBL.label_for(
                by_qid, by_jsonl_qid, run_name, qid,
                run_to_jsonl.get(run_name, ""))
            cases.append({
                "run": run_name, "qid": qid, "qdir": qdir,
                "label": label, "label_src": src,
            })
    return cases


def build_nodes(path3):
    """03 的子目标 → PlanNode。goal 用 description（比 title 完整）。"""
    d = RBL._load_json(path3) or {}
    sgs = ((d.get("plan") or {}).get("subgoals") or [])
    nodes = []
    for sg in sgs:
        nid = "%s" % (sg.get("id") or "")
        if not nid:
            continue
        deps = sg.get("depends_on") or []
        if isinstance(deps, str):
            deps = [deps]
        nodes.append(PlanNode(
            nid=nid,
            goal="%s" % (sg.get("description") or sg.get("title") or ""),
            deps=tuple("%s" % x for x in deps if x),
            statement="%s" % (sg.get("description") or ""),
            tool="%s" % (sg.get("tool") or ""),
        ))
    return nodes


def build_outcomes(path4):
    """04 的每行 → SolveOutcome，按 id 分组（多轮/多候选都在里面）。

    ★ 账本自己会处理「多条里只有升级被接受」，这里**不预先挑最优**
      —— 预先挑就把账本的单调语义绕过去了。
    """
    rows = RBL._load_jsonl(path4) or []
    by_id = {}
    for r in rows:
        nid = "%s" % (r.get("id") or "")
        if not nid:
            continue
        by_id.setdefault(nid, []).append(SolveOutcome(
            nid=nid,
            goal="%s" % (r.get("description") or r.get("title") or ""),
            claim="%s" % (r.get("conclusion") or ""),
            derivation="%s" % (r.get("result") or ""),
            raw="",
            evidence={
                "tool_ran": bool(r.get("tool_ran")),
                "tool_verdict": "%s" % (r.get("tool_verdict") or ""),
                "objective_verdict": "%s" % (r.get("objective_verdict") or ""),
            },
        ))
    return by_id


def pick_root(nodes):
    """汇点（没有下游依赖它）→ 取最后一个；没有则取最后一个节点。"""
    if not nodes:
        return ""
    depended = set()
    for n in nodes:
        for d in n.deps:
            depended.add(d)
    sinks = [n.nid for n in nodes if n.nid not in depended]
    return (sinks or [nodes[-1].nid])[-1]


def make_checker(mode):
    """两档 checker。honest 只看真实工具痕迹；ceiling 把模型判对当工具通过。"""
    def chk(node, outcome):
        ev = getattr(outcome, "evidence", None) or {}
        if mode == "honest":
            if ev.get("tool_ran"):
                return make_checker_result(
                    "pass", tool_ran=True,
                    evidence="%s" % (ev.get("tool_verdict") or ""))
            return make_checker_result("unknown", tool_ran=False)
        # ceiling：模型判对 ⇒ 假装工具跑过并通过（**上界**）
        if ev.get("objective_verdict") == "correct":
            return make_checker_result(
                "pass", tool_ran=True,
                evidence="[ceiling] objective_verdict=correct")
        if ev.get("objective_verdict") == "incorrect":
            return make_checker_result("fail", tool_ran=True,
                                       evidence="objective_verdict=incorrect")
        return make_checker_result("unknown", tool_ran=False)

    return chk


def run_case(case, mode):
    nodes = build_nodes(os.path.join(case["qdir"], "03_subgoals.json"))
    outcomes = build_outcomes(os.path.join(case["qdir"],
                                           "04_subgoal_results.jsonl"))
    if not nodes:
        return None
    root = pick_root(nodes)
    k = Kernel(checker=make_checker(mode), break_cycles=True)
    try:
        r = k.run_solved(nodes, outcomes, root_oid=root)
    except Exception as e:  # noqa: BLE001  单个题次失败不得终止整批
        return {"error": "%s: %s" % (type(e).__name__, e), "label": case["label"]}
    st = r.ledger.stats()
    # 目标漂移：求解器复述的目标与节点声明不一致的节点数。
    # 这是「偷换命题」的量化 —— 旧链完全看不到这个数。
    by_id = {n.nid: n for n in nodes}
    drift = 0
    for nid, outs in outcomes.items():
        node = by_id.get(nid)
        if node is None:
            continue
        for o in outs:
            if (o.goal or "").strip() and (node.goal or "").strip() \
                    and o.goal.strip() != node.goal.strip():
                drift += 1
                break
    return {
        "label": case["label"],
        "run": case["run"],
        "qid": case["qid"],
        "n_nodes": len(nodes),
        "n_deps": sum(1 for n in nodes if n.deps),
        "n_external": len(r.external_deps),
        "hard": st["hard"],
        "soft": st["soft"],
        "open": st["open"],
        "unmapped": st["unmapped"],
        "regressions": st["regressions"],
        "retargets": st["retargets"],
        "tier": r.delivery.tier if r.delivery else DELIVERY_NONE,
        "blocked": len(r.ledger.blocked_by()),
        "goal_drift": drift,
        "cycle_broken": len(r.external_deps),
    }


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


def summarize(rows, mode, level):
    ok = [r for r in rows if "error" not in r]
    err = [r for r in rows if "error" in r]
    print("\n== %s（放行档 %s）==" % (mode, level))
    print("  题次 %d（失败 %d）" % (len(ok), len(err)))
    for e in err[:5]:
        print("    ! %s" % e["error"])
    if not ok:
        return
    n = len(ok)
    tiers = {}
    for r in ok:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    print("  交付  proven=%d (%.1f%%)  unproven=%d  none=%d"
          % (tiers.get(DELIVERY_PROVEN, 0),
             pct(tiers.get(DELIVERY_PROVEN, 0), n),
             tiers.get(DELIVERY_UNPROVEN, 0),
             tiers.get(DELIVERY_NONE, 0)))
    print("  裁决  hard=%d  open=%d  unmapped=%d"
          % (sum(r["hard"] for r in ok), sum(r["open"] for r in ok),
             sum(r["unmapped"] for r in ok)))
    print("  结构  平均节点 %.1f  有依赖节点 %.1f  外部依赖题次 %d"
          % (1.0 * sum(r["n_nodes"] for r in ok) / n,
             1.0 * sum(r["n_deps"] for r in ok) / n,
             sum(1 for r in ok if r["n_external"])))
    print("  账本  降级写入 %d  下游被阻断题次 %d"
          % (sum(r["regressions"] for r in ok),
             sum(1 for r in ok if r["blocked"])))
    print("  规划  目标漂移节点 %d（题次 %d）  破环题次 %d"
          % (sum(r["goal_drift"] for r in ok),
             sum(1 for r in ok if r["goal_drift"]),
             sum(1 for r in ok if r["cycle_broken"])))
    # 按判对标签分组 —— 关键：新结构有没有区分度
    for lb in (True, False, None):
        sub = [r for r in ok if r["label"] is lb]
        if not sub:
            continue
        proven = sum(1 for r in sub if r["tier"] == DELIVERY_PROVEN)
        name = {True: "判对", False: "判错", None: "无标签"}[lb]
        print("    %s %3d 题次 → proven %3d = %5.1f%%"
              % (name, len(sub), proven, pct(proven, len(sub))))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    cases = load_cases(args.results)
    print("载入题次：%d（有 03+04 的）" % len(cases))

    out = {}
    for mode, level in (("honest", ADMIT_HARD), ("ceiling", ADMIT_HARD)):
        rows = [r for r in (run_case(c, mode) for c in cases) if r]
        out[mode] = rows
        summarize(rows, mode, level)

    print("\n★ 读法：honest 档 proven=0 是「历史上工具从未真跑过」的直接投影，"
          "不是新内核的缺陷；\nceiling 档是**反事实上界**（把模型判对当工具通过），"
          "不得作为预期值引用。")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("已写 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
