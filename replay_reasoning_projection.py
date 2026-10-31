# -*- coding: utf-8 -*-
"""评估床：reasoning 投影口径回放（δ=0，确定性）。

为什么要这个
------------
`candidate.reasoning` 是 4.1 自审 / 4.2 证伪 / 4.4 计算检测的**唯一输入**。
它由 `_build_full_reasoning` 从「每步子目标结果」拼成，而每步结果本身
要经过两次投影才能到达审核者：

    LLM 原始响应
      → ① 抽取（`sub_goal_solver__solve.py::_STEP_RESULT_RE`）
      → ② 拼接（`_build_full_reasoning`）
      → ③ 审核侧预算裁剪（4.1 `[:6000]` / 4.2 `[-2400:]`）

①和③都曾经是**硬切片**，而且方向不同：① 从 `【本步结果】` 起遇到任意 `【`
就停（推导整段被切）；③ 4.1 从**头**切、4.2 从**尾**切。三者叠加的结果是
「推理写出来了，审核者看不到」。

这个床只验 ① 和 ③，两者都是**纯函数**：同一份历史原文进去，
同一组判定出来，重跑逐位相同 ⇒ **δ = 0**，不需要真跑评测。

它的边界（必须记住）
--------------------
只验 selector / plumbing，**不验 proposer**。文本形态是模型当时写的；
prompt 一改，形态会变，这个床的代表性下降。分数是否上涨仍要真跑。

用法
----
    python replay_reasoning_projection.py --data-dir D:/mp_tmp/bp
    python replay_reasoning_projection.py --data-dir D:/mp_tmp/bp --out D:/mp_tmp/proj.json
    python replay_reasoning_projection.py --data-dir D:/mp_tmp/bp --strict   # 出现退步即退出码 1

`--data-dir` 指向一个目录，里面递归包含服务器的 `04_subgoal_results.jsonl`
（每题一份，路径形如 `<run_id>/q<id>/04_subgoal_results.jsonl`）。
拉取方式见 `.workbuddy/memory/MEMORY.md` 的「数据来源铁律」。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.sub_goal_solver__format import _build_full_reasoning  # noqa: E402
from agent.sub_goal_solver__solve import _STEP_RESULT_RE  # noqa: E402
from agent.subgoal_result import clip_reasoning  # noqa: E402

#: 抽取口径的历史实现（2026-10 之前）：遇到任意 `【` 即终止。
_OLD_STEP_RESULT_RE = re.compile(r"【本步结果】\s*\n?(.*?)(?:$|【)", re.DOTALL)

#: 审核侧预算（与 `self_auditor._REASONING_MAX`、`adversarial_max_reasoning` 对齐）。
BUDGET_41 = 6000
BUDGET_42 = 2400


def _strip_residue(text: str) -> str:
    """复用调用方的剥壳口径（此处只做最小对齐，避免 import 私有方法）。"""
    return (text or "").strip()


def _load_steps(path: str) -> list[dict]:
    steps = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except Exception:  # noqa: BLE001  单行坏了不影响整批
                continue
            raw = ""
            cands = s.get("candidates") or []
            pick = s.get("candidates_picked_index")
            if isinstance(pick, int) and 0 <= pick < len(cands):
                raw = str(cands[pick] or "")
            if not raw:
                for c in cands:
                    if str(c or "").strip():
                        raw = str(c)
                        break
            steps.append({
                "id": s.get("id"),
                "title": str(s.get("title") or "未命名"),
                "type": str(s.get("type") or "derive"),
                "description": str(s.get("description") or ""),
                "result": str(s.get("result") or ""),
                "raw": raw,
            })
    return steps


def _extract(regex, raw: str) -> str:
    if not raw:
        return ""
    m = regex.search(raw)
    if m:
        return _strip_residue(m.group(1))
    return _strip_residue(raw)[-500:]


def _build(steps: list[dict], key: str) -> str:
    sgs = [{
        "id": s["id"],
        "title": s["title"],
        "type": s["type"],
        "description": s["description"],
        "result": s[key],
    } for s in steps]
    return _build_full_reasoning(
        subgoals=sgs,
        problem_goal={"question_type": "N/A", "task": ""},
        final_answer="（回放：本题最终答案不参与投影）",
    )


def _visible(text: str, steps: list[dict]) -> tuple[int, int]:
    """被投影后仍然露头的步数（以 `### 子目标 #id` 头是否出现为准）。"""
    seen = sum(1 for s in steps if f"### 子目标 #{s['id']}「" in text)
    return seen, len(steps)


def _pct(a: float, b: float) -> float:
    return (a / b * 100.0) if b else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="reasoning 投影口径回放（δ=0）")
    ap.add_argument("--data-dir", required=True, help="含 04_subgoal_results.jsonl 的目录")
    ap.add_argument("--out", default="", help="指标落盘路径（JSON）")
    ap.add_argument("--strict", action="store_true", help="任一口径退步即退出码 1")
    ap.add_argument("--show", type=int, default=5, help="打印最差样例条数")
    args = ap.parse_args(argv)

    paths = []
    for root, _dirs, files in os.walk(args.data_dir):
        if "04_subgoal_results.jsonl" in files:
            paths.append(os.path.join(root, "04_subgoal_results.jsonl"))
    paths.sort()
    if not paths:
        print(f"[ERR] {args.data_dir} 下没有 04_subgoal_results.jsonl", file=sys.stderr)
        return 2

    rows = []
    n_steps = 0
    n_steps_with_raw = 0
    changed = 0
    for p in paths:
        steps = _load_steps(p)
        if not steps:
            continue
        n_steps += len(steps)
        n_steps_with_raw += sum(1 for s in steps if s["raw"])

        # ① 抽取：旧 vs 新
        for s in steps:
            s["old"] = _extract(_OLD_STEP_RESULT_RE, s["raw"])
            s["new"] = _extract(_STEP_RESULT_RE, s["raw"])
            if s["old"] != s["new"]:
                changed += 1

        t_old = _build(steps, "old")
        t_new = _build(steps, "new")

        row = {
            "run": os.path.basename(os.path.dirname(os.path.dirname(p))),
            "qid": os.path.basename(os.path.dirname(p)),
            "steps": len(steps),
            "len_old": len(t_old),
            "len_new": len(t_new),
            # ③ 4.1：从头切 vs 按步分配
            "v41_old": _visible(t_old[:BUDGET_41], steps)[0],
            "v41_new": _visible(clip_reasoning(t_new, BUDGET_41), steps)[0],
            # ③ 4.2：从尾切 vs 按步分配
            "v42_old": _visible(t_old[-BUDGET_42:], steps)[0],
            "v42_new": _visible(clip_reasoning(t_new, BUDGET_42), steps)[0],
        }
        rows.append(row)

    print("[replay] reasoning 投影口径回放（确定性，δ=0）")
    print(f"  运行批次 {len(rows)} 个 / 子目标 {n_steps} 步 / 有原始响应 {n_steps_with_raw} 步")
    print(f"  抽取口径有变化的步：{changed}（其余步新旧逐字相同）")
    print()

    def report(name, old_key, new_key):
        old_cov = [r[old_key] / r["steps"] for r in rows]
        new_cov = [r[new_key] / r["steps"] for r in rows]
        old_full = sum(1 for r in rows if r[old_key] == r["steps"])
        new_full = sum(1 for r in rows if r[new_key] == r["steps"])
        print(f"  {name}")
        print(f"    旧口径：平均可见 {statistics.mean(old_cov) * 100:5.1f}%   "
              f"全步可见 {old_full}/{len(rows)}")
        print(f"    新口径：平均可见 {statistics.mean(new_cov) * 100:5.1f}%   "
              f"全步可见 {new_full}/{len(rows)}")
        worse = [r for r in rows if r[new_key] < r[old_key]]
        print(f"    退步的批次：{len(worse)}")
        return {
            "old_avg_visible_pct": round(statistics.mean(old_cov) * 100, 1),
            "new_avg_visible_pct": round(statistics.mean(new_cov) * 100, 1),
            "old_full_visible": old_full,
            "new_full_visible": new_full,
            "regressed_runs": len(worse),
            "worse_examples": [
                {"run": r["run"], "qid": r["qid"], "steps": r["steps"],
                 "old": r[old_key], "new": r[new_key]}
                for r in sorted(worse, key=lambda x: x[new_key] - x[old_key])[:args.show]
            ],
        }

    m41 = report("4.1 自审（预算 6000）", "v41_old", "v41_new")
    print()
    m42 = report("4.2 证伪（预算 2400）", "v42_old", "v42_new")
    print()

    len_old = [r["len_old"] for r in rows]
    len_new = [r["len_new"] for r in rows]
    print("  文本长度（每题 reasoning）")
    print(f"    旧：中位 {int(statistics.median(len_old))}  均值 {int(statistics.mean(len_old))}")
    print(f"    新：中位 {int(statistics.median(len_new))}  均值 {int(statistics.mean(len_new))}"
          f"  （×{statistics.mean(len_new) / max(statistics.mean(len_old), 1):.1f}）")
    print()

    if args.out:
        payload = {
            "data_dir": args.data_dir,
            "runs": len(rows),
            "steps": n_steps,
            "steps_with_raw": n_steps_with_raw,
            "extraction_changed_steps": changed,
            "audit_41": m41,
            "audit_42": m42,
            "text_len": {"old_median": int(statistics.median(len_old)),
                         "old_mean": int(statistics.mean(len_old)),
                         "new_median": int(statistics.median(len_new)),
                         "new_mean": int(statistics.mean(len_new))},
            "rows": rows,
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"  指标已落盘：{args.out}")

    if args.strict:
        bad = []
        if m41["regressed_runs"]:
            bad.append(f"4.1 有 {m41['regressed_runs']} 个批次退步")
        if m42["regressed_runs"]:
            bad.append(f"4.2 有 {m42['regressed_runs']} 个批次退步")
        if m41["new_full_visible"] < m41["old_full_visible"]:
            bad.append("4.1 全步可见批次减少")
        if m42["new_full_visible"] < m42["old_full_visible"]:
            bad.append("4.2 全步可见批次减少")
        if bad:
            print("[FAIL] " + "；".join(bad))
            return 1
        print("[PASS] 两个预算口径均无退步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
