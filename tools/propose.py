# -*- coding: utf-8 -*-
"""L3 提案器 —— 读账本与参数层，**只出 A 档候选**（不评测、不判准入、不碰 B/C 档）。

在三体架构里的位置
==================
    L0 参数层（205 个 A 键） + L5 账本（改过什么、有没有用）
      ↓  本模块：读账本 + 未试清单 → LLM 出一份候选 JSON
    L4 critic 三条硬规则（本模块会**先过一遍**，不过就打回重提）
      ↓  候选文件（可 diff），交给评测与四道门

为什么是"单轮出 JSON"，不是 RRSI 那套 40 轮动作协议
==================================================
编辑面只有一个 JSON 文件、且已收敛到 205 个标量键 ⇒ 提案器不需要"读文件/逐步改码"的动作空间。
它只要看：当前值 + 值域 + 历史 Δ + 未试清单，然后写一份 patch。

三条硬约束（写进 prompt，也写进代码）
====================================
1. **只碰 A 档**：列表与 value 都来自 `params.json` 的 a 段；
2. **不评测、不算分**：本模块永远不读评测结果自己算 Δ；
3. **必须写清四件事**：假设 / 为什么不用更省力的改法 / 预期影响谁 / 事后怎么验
   （对应账本 `why_not_lower_lever` `predicted_affected` `retroactive_check`）。

用法
====
    # 真跑（需要 LLM 环境变量：OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL）
    python tools/propose.py

    # 冒烟：不调 LLM，用确定性桩产一份候选（证明链路通）
    python tools/propose.py --dry-run

    # 看提示词长什么样（不调用、不落盘）
    python tools/propose.py --print-prompt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from contracts.params_guard import review_edits  # noqa: E402
from contracts.params_guard import domain_of  # noqa: E402
from contracts.params_io import load as load_params  # noqa: E402

SCHEMA = "candidate/1"
OUT_DIR = os.path.join(_ROOT, "results", "_candidates")
EFFECT = os.path.join(_ROOT, "results", "_edit_ledger", "effectiveness.json")

_SYSTEM = """你是数学解题智能体的「参数提案器」。你只做一件事：
从给定的**可编辑参数**里挑 1-3 个，改值，并写清为什么。

硬约束（违反即被自动拒绝）：
1. 只能改下面列表里出现过的 key，不许发明新参数；
2. 值必须与当前值**同类型**，且落在给定域内；
3. 不许提到任何题号、标准答案、题库文件名（候选会被自动判为泄漏）；
4. 不许提议"改提示词/改代码/改阶段顺序"——那些不在你的编辑面里。

输出必须是**一个 JSON 对象**，不要任何解释文字、不要代码围栏：
{
  "hypothesis": "一句话：改了什么行为、为什么应该有效",
  "why_not_lower_lever": "为什么不用更省力的改法（如调另一个更便宜的参数）",
  "predicted_affected": "预期会影响哪些类型的题（按题型/领域描述，不要写题号）",
  "retroactive_check": "事后怎么验证它真有效（看什么产物、什么字段）",
  "edits": [{"key": "<参数名>", "to": <新值>, "why": "这个值为什么这么取"}]
}"""


def _fmt_domain(key: str, val) -> str:
    d = domain_of(key, val)
    bits = ["kind=%s" % d["kind"]]
    if d["min"] is not None or d["max"] is not None:
        bits.append("域=[%s, %s]" % (d["min"], d["max"]))
    return "%s ｜ %s" % (", ".join(bits), d["why"])


def _load_effect() -> dict:
    if not os.path.isfile(EFFECT):
        return {}
    try:
        with open(EFFECT, encoding="utf-8") as fh:
            return json.load(fh).get("units") or {}
    except (OSError, ValueError):
        return {}


def build_prompt(doc: dict, effect: dict, max_untried: int = 40) -> str:
    """拼提示词：参数清单（含值域）+ 历史状态 + 未试清单。"""
    a = doc.get("a") or {}
    lines = ["## 可编辑参数（%d 个，只能从这里挑）" % len(a), ""]
    for k in sorted(a):
        val = a[k].get("value")
        st = (effect.get(k) or {}).get("status", "untried")
        md = (effect.get(k) or {}).get("max_delta")
        hist = "" if md is None else " ｜ 历史最大Δ=%spp" % md
        lines.append("- `%s` = %r ｜ %s ｜ 状态=%s%s"
                     % (k, val, _fmt_domain(k, val), st, hist))
    untried = sorted(k for k in a
                     if (effect.get(k) or {}).get("status", "untried") == "untried")
    lines += ["", "## 从未改过的参数（%d 个，探索优先；只列前 %d）"
              % (len(untried), min(len(untried), max_untried)), ""]
    for k in untried[:max_untried]:
        lines.append("- `%s` = %r" % (k, a[k].get("value")))
    lines += ["", "现在给出你的候选（JSON，1-3 个 edit）。"]
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def parse_candidate(text: str) -> dict:
    """解析模型输出。要求是**一个 JSON 对象**，容忍代码围栏，不容忍多余文字。"""
    raw = _strip_fence(text)
    try:
        doc = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("输出里找不到 JSON 对象")
        doc = json.loads(raw[start:end + 1])
    if not isinstance(doc, dict) or not isinstance(doc.get("edits"), list):
        raise ValueError("候选缺少 edits 列表")
    return doc


def stub_propose(doc: dict, effect: dict) -> dict:
    """确定性桩：挑第一个未试的数值参数，抬 10%（只为证明链路通，不是"建议"）。"""
    a = doc.get("a") or {}
    for k in sorted(a):
        if (effect.get(k) or {}).get("status", "untried") != "untried":
            continue
        v = a[k].get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        new = round(v * 1.1, 4) if isinstance(v, float) else max(1, int(round(v * 1.1)))
        if new == v:
            continue
        return {"hypothesis": "（桩）抬这个上限，给下游更多空间",
                "why_not_lower_lever": "（桩）没有更省力的改法可选",
                "predicted_affected": "（桩）影响所有用到该上限的题",
                "retroactive_check": "（桩）看 diag 里该参数的实际用量是否触顶",
                "edits": [{"key": k, "to": new, "why": "（桩）+10%"}]}
    raise ValueError("找不到可用的未试数值参数（桩）")


def _call_llm(prompt: str) -> str:
    from utils.llm_client import LLMClient
    client = LLMClient()
    return client.chat([{"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt}],
                       temperature=0.3, max_tokens=4096)


def propose(doc: dict, effect: dict, llm=None, max_rounds: int = 3) -> dict:
    """出候选并过 critic；不过就把违规回喂重提（有界重试）。"""
    prompt = build_prompt(doc, effect)
    rounds, last = [], None
    for i in range(max(1, int(max_rounds))):
        text = llm(prompt) if llm else stub_propose(doc, effect)
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        try:
            cand = parse_candidate(text)
        except ValueError as e:
            rounds.append({"round": i + 1, "ok": False, "why": "解析失败：%s" % e})
            prompt = prompt + "\n\n## 上一轮输出无法解析（%s）\n请只输出一个 JSON 对象。" % e
            continue
        verdict = review_edits(cand["edits"], doc, scan_text=text)
        rounds.append({"round": i + 1, "ok": verdict["passed"],
                       "why": "；".join(v["msg"] for v in verdict["violations"])})
        last = (cand, verdict)
        if verdict["passed"]:
            return {"ok": True, "candidate": cand, "verdict": verdict,
                    "rounds": rounds, "prompt": prompt}
        prompt = prompt + "\n\n## 上一轮候选被 critic 拒绝：\n" + "\n".join(
            "- [%s] %s: %s" % (v["rule"], v["key"], v["msg"]) for v in verdict["violations"]
        ) + "\n请修正后重新给出 JSON。"
    return {"ok": False, "candidate": (last or [None])[0],
            "verdict": (last or [None, {}])[1] if last else {},
            "rounds": rounds, "prompt": prompt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L3 提案器（只出 A 档候选）")
    ap.add_argument("--params", default=os.path.join(_ROOT, "params.json"))
    ap.add_argument("--effect", default=EFFECT)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="用确定性桩，不调 LLM")
    ap.add_argument("--print-prompt", action="store_true", help="只打印提示词")
    args = ap.parse_args(argv)

    doc = load_params(args.params)
    effect = _load_effect()
    if args.print_prompt:
        print(build_prompt(doc, effect))
        return 0

    if args.dry_run:
        llm = None
        src = "stub"
    else:
        llm = _call_llm
        src = "llm"

    try:
        res = propose(doc, effect, llm=llm, max_rounds=args.max_rounds)
    except ValueError as e:
        print("❌ 提案失败：%s" % e)
        return 2

    for r in res["rounds"]:
        print("轮 %d：%s" % (r["round"], "✅ 通过 critic" if r["ok"]
                             else "❌ " + r["why"]))
    if not res["ok"]:
        print("❌ 未产出合格候选（%d 轮）" % len(res["rounds"]))
        return 1

    cand = res["candidate"]
    out = {"schema": SCHEMA, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "proposer": src, "n_edits": len(cand["edits"]),
           "bundle": len(cand["edits"]), "candidate": cand,
           "critic": res["verdict"]}
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "cand-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("\n候选（%d 个 edit，bundle=%d）：" % (out["n_edits"], out["bundle"]))
    for e in cand["edits"]:
        cur = (doc["a"].get(e["key"]) or {}).get("value")
        print("  %-40s %r → %r" % (e["key"], cur, e["to"]))
    print("\n假设：%s" % cand.get("hypothesis", ""))
    print("为什么不更省力：%s" % cand.get("why_not_lower_lever", ""))
    print("预期影响：%s" % cand.get("predicted_affected", ""))
    print("事后怎么验：%s" % cand.get("retroactive_check", ""))
    print("\n已写 %s" % path)
    print("下一步：评测这份候选 → 把 ΔS/ΔC 喂给 tools/gates.py decide。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
