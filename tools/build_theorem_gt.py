# -*- coding: utf-8 -*-
"""题库定理预标注表生成器（2026-09-29，截图 #3+#4）。

用户原话
--------
> 我的思路是我们先把题库每一题对应的会用到的定理总结下来，然后判断大模型或
> leansearch 最后有没有找到正确的定理。

本脚本产出**前半句**：为题库每题生成「应当用到的 Mathlib 定理」候选表，
落盘 ``data/theorem_ground_truth/``，**人工校正后**作为评测基准。

★★★ 为什么不用大模型生成（2026-09-29 实测决策）
------------------------------------------------
原计划用 DeepSeek 逐题标注，**实测否决**：
  · `deepseek-v4-flash` 强制开启 reasoning，实测单题 **38–54s**、
    reasoning 占满 max_tokens（8192 仍被 `finish_reason=length` 截断，
    输出里根本没有 JSON，只有思考过程）；
  · 112 题 × ~50s ≈ **93 分钟**，且 5 题里 2 题产出为空；
  · 喂 assistant-prefill 种子也压不住（实测仍 44.7s / 27k 字符 thinking）。
⇒ 改用**确定性检索**产候选表：`agent.theorem_hint` 的 leansearch 后端。

★ 非循环性（这条最关键，否则评测毫无意义）
------------------------------------------
若"标注基准"与"被评测的检索"用**同一套 query 构造逻辑**，则评测退化成
恒等式。故本脚本做了两件独立化处理：
  1. **标注侧**用 `--annot-queries`（默认 3 条，含领域词 + 题干词 + 组合）；
  2. **评测侧**（`tools/theorem_probe.py`）默认只用 2 条。
  两者的 query 集合**不完全相同**，因此"检索能否找到标注"是真实信息。
  进一步地，标注表是**人可编辑的 JSONL** —— 老师/我们校正后即为权威基准。

用法
----
    python tools/build_theorem_gt.py                       # 全量（快，纯本地检索）
    python tools/build_theorem_gt.py --limit 10            # 先看 10 题
    python tools/build_theorem_gt.py --top-n 4             # 每题取前 4 条作 required
    python tools/build_theorem_gt.py --overwrite           # 覆盖已有（默认增量保留人工编辑）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

DEFAULT_BANK = os.path.join(
    _REPO_ROOT, "题库", "official112_本地测试题库", "official112_full.jsonl")
DEFAULT_OUT = os.path.join(
    _REPO_ROOT, "data", "theorem_ground_truth", "official112_theorems.jsonl")

# 标注头（写进 JSONL 首行，供人工识别与回滚）
_HEADER = (
    "# MathPilot 题库定理预标注表\n"
    "# 每行一题：{id, domain, required[], optional[], source, note}\n"
    "# required = 解本题**必须**用到的 Mathlib 定理（评测的召回基准）\n"
    "# optional = 辅助定理（不参与命中率，仅供参考）\n"
    "# ★ 可人工编辑：改完直接存，theorem_probe.py 会按此评测。\n"
    "# ★ 本表由 tools/build_theorem_gt.py 确定性生成（非大模型），生成逻辑见脚本 docstring。\n"
)


def _load_jsonl(path: str) -> list:
    if not os.path.isfile(path):
        return []
    out: list = []
    for l in io.open(path, encoding="utf-8", errors="replace"):
        s = l.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append(json.loads(s))
        except Exception:  # noqa: BLE001
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="题库定理预标注表生成器（确定性检索）")
    ap.add_argument("--bank", default=DEFAULT_BANK, help="题库 jsonl 路径")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 jsonl 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全量）")
    ap.add_argument("--top-n", type=int, default=4,
                    help="每题取前 N 条命中作 required（默认 4）")
    ap.add_argument("--annot-queries", type=int, default=3,
                    help="标注侧检索 query 数（默认 3；评测侧用 2 以保持非循环）")
    ap.add_argument("--fetch", type=int, default=8,
                    help="每次检索取回条数（默认 8）")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已有标注（默认保留已有行 = 人工编辑不丢）")
    ap.add_argument("--specificity-max", type=int, default=5,
                    help="一条定理横跨超过 N 题即视为「泛化命中」，降级到 "
                         "optional（默认 5；0 = 关闭该过滤）")
    args = ap.parse_args()

    bank = _load_jsonl(args.bank)
    if not bank:
        print(f"题库为空或不存在: {args.bank}")
        return 1
    if args.limit:
        bank = bank[:args.limit]

    from agent.theorem_hint import retrieve_theorems_for_question

    # 增量：保留已有（人工可能已改过）
    existing: dict = {}
    if os.path.isfile(args.out) and not args.overwrite:
        for r in _load_jsonl(args.out):
            if r.get("id"):
                existing[str(r["id"])] = r

    rows_out: list = []
    n_new = 0
    t0 = time.time()
    print(f"题库 {len(bank)} 题 | required 取前 {args.top_n} 条 | "
          f"标注 query 数 {args.annot_queries}")
    for i, row in enumerate(bank, 1):
        rid = str(row.get("id") or row.get("qid") or f"idx{i-1}")
        domain = str(row.get("domain") or "")
        if rid in existing:
            rows_out.append(existing[rid])
            print(f"[{i}/{len(bank)}] 跳过（已有）{rid}", flush=True)
            continue

        problem = str(row.get("question") or row.get("problem") or "")
        r = retrieve_theorems_for_question(
            problem, domain=domain, question_type="",
            max_queries=args.annot_queries, top_k=args.fetch)

        req = [h.short for h in r.hits[:max(1, args.top_n)]]
        opt = [h.short for h in r.hits[max(1, args.top_n):]]
        rec = {
            "id": rid,
            "domain": domain,
            "required": req,
            "optional": opt,
            "source": "auto:leansearch" + ("" if r.ok else f":FAILED({r.reason})"),
            "note": "",
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        rows_out.append(rec)
        n_new += 1
        print(f"[{i}/{len(bank)}] {rid} req={req[:3]} "
              f"({len(r.hits)}条 {r.elapsed:.1f}s)", flush=True)

    # ------------------------------------------------------------------
    # ★ 2026-09-29 修正：**特异性过滤**（治"泛化命中污染 required"）
    # ------------------------------------------------------------------
    # 问题（实测暴露）：最初把「检索结果前 N 条」直接当 required，但检索是
    #   **关键词泛化匹配**——只要题干含 card/choose/permutation，就会命中
    #   `card_perms_of_finset` 之类。实测后果：
    #     · `card_perms_of_finset`    出现在 **49 题** 的 required
    #     · `card_sym_fin_eq_multichoose` 出现在 **36 题**
    #     · `permsOfFinset`           出现在 **30 题**
    #   三条合计占 448 个 required 槽位的 **26%**。
    #
    #   致命之处：这等于**用检索结果定义标准答案**，评测侧与标注侧同源 ⇒
    #   「命中率 86.6%」是循环自证，不具判别力（此为最隐蔽的一条）。
    #
    # 修法：一条定理若横跨题数 > 阈值，说明它**不区分题目**（谁都能命中），
    #   不具作为"本题必用定理"的资格 ⇒ **降级到 optional**（不删，保留线索）。
    #   这不是删除信息，而是把"泛化命中"与"题目特异定理"分开计分。
    #
    # 阈值取 5：112 题中横跨 >5 题（即 >4.5%）的定理已难称为"本题特有"。
    #   ⚠ 该阈值是启发式，不是定理 —— 若后续证据表明应放宽/收紧，改这里一处即可。
    if args.specificity_max and len(rows_out) >= 20:
        _cnt: dict = {}
        for rec in rows_out:
            for nm in set(rec.get("required") or []):
                _cnt[nm] = _cnt.get(nm, 0) + 1
        _too_common = {nm for nm, c in _cnt.items()
                       if c > args.specificity_max}
        if _too_common:
            _moved = 0
            for rec in rows_out:
                req = list(rec.get("required") or [])
                kept, demoted = [], []
                for nm in req:
                    (demoted if nm in _too_common else kept).append(nm)
                if demoted:
                    rec["required"] = kept
                    # 降级项进 optional（去重，不丢信息）
                    _opt = list(rec.get("optional") or [])
                    for nm in demoted:
                        if nm not in _opt:
                            _opt.append(nm)
                    rec["optional"] = _opt
                    _moved += len(demoted)
            print(f"\n[特异性过滤] 横跨 >{args.specificity_max} 题的定理 "
                  f"{len(_too_common)} 条 → 降级到 optional（共 {_moved} 处）：")
            for nm in sorted(_too_common, key=lambda x: -_cnt[x]):
                print(f"    {nm}（{_cnt[nm]} 题）")
            print("  ⇒ 这些是**泛化命中**而非题目特异定理；"
                  "保留在 optional 不丢信息，但不再污染 required 计分。")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        f.write(_HEADER)
        for rec in rows_out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    n_req = sum(1 for r in rows_out if r.get("required"))
    print(f"\n完成：新增 {n_new} 题，累计 {len(rows_out)} 题"
          f"（{n_req} 题有 required），耗时 {time.time() - t0:.0f}s")
    print(f"已写出: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
