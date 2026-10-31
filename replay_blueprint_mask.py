#!/usr/bin/env python
"""2.7「归并不带值」掩码的离线评估床（δ=0，纯函数回放，零 LLM 成本）。

用法：
    python replay_blueprint_mask.py --data-dir D:/mp_tmp/bp

数据来源（★ 只在服务器产出；本地 results/ 全是 9 月，不可用于判断当前系统）：
    <data-dir>/<run_id>/<qid>/02_blueprint.json

做什么：把**真实的** `merge_strategy` / 收尾节点 `statement` 喂给
`agent.value_mask.mask_assigned_values`，输出掩码前后对照 + 统计。
`mask_assigned_values` 是纯函数 ⇒ 本床 δ=0，不是近似。

本脚本**只观测**：不改任何文件、不调用 LLM、不产生淘汰。
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.value_mask import mask_assigned_values   # noqa: E402


def _load(files):
    for f in files:
        try:
            yield f, json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def _final_node(dag: dict):
    """收尾节点 = 根 children 列表的**最后一项**（prompts/blueprint.py 明令）。

    退化情形（无 root / 无 children）返回 None，与 `to_subgoal_plan` 的
    拓扑序"最后一步"口径在正常蓝图上一致。
    """
    nodes = [n for n in (dag.get("nodes") or []) if isinstance(n, dict)]
    by_id = {str(n.get("id")): n for n in nodes}
    root = by_id.get(str(dag.get("root_id") or ""))
    if root is not None:
        kids = [str(c) for c in (root.get("children") or [])]
        if kids and kids[-1] in by_id:
            return by_id[kids[-1]]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="D:/mp_tmp/bp")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.data_dir, "*", "*",
                                          "02_blueprint.json")))
    print(f"[data] {len(files)} 份蓝图  ({args.data_dir})")

    n_ms = hit_ms = 0
    n_fin = hit_fin = 0
    rows = []
    for f, dag in _load(files):
        qid = os.path.basename(os.path.dirname(f))

        ms = str(dag.get("merge_strategy") or "")
        if ms:
            n_ms += 1
            new, k = mask_assigned_values(ms)
            if k:
                hit_ms += 1
                rows.append(("merge_strategy", qid, k, ms, new))

        fin = _final_node(dag)
        if fin is not None:
            n_fin += 1
            st = str(fin.get("statement") or "")
            new, k = mask_assigned_values(st)
            if k:
                hit_fin += 1
                rows.append((f"node {fin.get('id')}", qid, k, st, new))

    print("\n" + "=" * 66)
    print(f"merge_strategy : {hit_ms}/{n_ms} 被掩 "
          f"({hit_ms / max(n_ms, 1):.1%})")
    print(f"收尾节点       : {hit_fin}/{n_fin} 被掩 "
          f"({hit_fin / max(n_fin, 1):.1%})")

    if args.show:
        print(f"\n对照（前 {args.show} 条）")
        for where, qid, k, old, new in rows[:args.show]:
            print(f"\n  [{qid}] {where}  n={k}")
            print(f"    原: {_wrap(old)}")
            print(f"    后: {_wrap(new)}")
    return 0


def _wrap(s: str, width: int = 96) -> str:
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= width else s[:width] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
