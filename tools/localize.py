# -*- coding: utf-8 -*-
"""L2 三级定位（机械化那一半）—— 环节 → 候选可编辑单元，逐档列出当前值。

图上那个节点叫「定位到具体参数：哪个环节 → 哪一类 → 哪个参数」。
完整的三级要 LLM 读轨迹判"错在五维的哪一维"；这里把**能机械化的部分**做掉：

    给定环节（如 4.1） → 该环节**全部**可编辑单元（参数 / 提示词 / 工具 / 上下文切片）
    → 每个单元标注 A/B/C 档 + 当前值 + 可观测键

于是"定位"退化成在**一个有界集合里挑一个**，而不是在 6.7 万行里翻。
这既是给人用的（出 bug 了先看这张表），也是将来 LLM 定位器的输入域。

诚实边界
========
· 本工具**不判断哪一处错**，只列"这个环节允许被改的地方有哪些"；
· `错题 → 环节` 这一步仍靠 `tools/analyze_errors.py` 的历史归因（76/99 能定到阶段）；
· `错题 → 五维/单元` 这一步要 digest + 判断，本工具只提供候选集。

用法
====
    python tools/localize.py --list                 # 14 个环节一览
    python tools/localize.py --stage 4.1            # 该环节的候选单元表
    python tools/localize.py --stage 4.1 --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.stage_card as sc  # noqa: E402
from contracts.params_io import load as load_params  # noqa: E402

PARAMS = os.path.join(_ROOT, "params.json")


def _params() -> dict:
    try:
        return load_params(PARAMS)
    except Exception:  # noqa: BLE001  没参数层也要能列提示词/工具
        return {"a": {}, "b": {}, "c": {}}


def _ctx_slices(impl_file: str, limit: int = 8) -> tuple:
    """该实现文件里的硬编码切片（C 档，改它=改代码）。"""
    try:
        from tools.eu_inventory import _load_corpus, scan_context  # noqa: PLC0415
        _load_corpus()
        rows = [x for x in scan_context() if impl_file in str(x.get("source", ""))]
    except Exception:  # noqa: BLE001
        rows = []
    return len(rows), rows[:limit]


def _trace_steps(impl_file: str, limit: int = 6) -> list:
    """该实现文件写入的 trace step 名。

    为什么要有这一栏：本项目的观测有两条路 —— `diag`（汇总导出）与 `ctx.trace`（逐事件）。
    有些环节只写 trace 不写 diag，此时说它「没有可观测键」是错的（会误导人去补埋点）。
    """
    import re  # noqa: PLC0415
    try:
        with open(os.path.join(_ROOT, impl_file), encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return []
    names = set(re.findall(r'step\s*[=:]\s*["\']([A-Za-z0-9_.\-]+)["\']', src))
    names |= set(re.findall(r'["\']step["\']\s*:\s*["\']([A-Za-z0-9_.\-]+)["\']', src))
    # 本项目更常见的写法：self.record(ctx, "<step>", ...) ⇒ 由 agent/diag_export.py 汇总成 diag
    names |= set(re.findall(r'record\(\s*ctx\s*,\s*["\']([A-Za-z0-9_.\-]+)["\']', src))
    return sorted(names)[:limit]


def locate(stage_prefix: str) -> dict:
    """环节 → 候选单元。`stage_prefix` 可以是 '4.1' 或 '4.1_self_audit'。"""
    rows = [r for r in sc.STAGES if r[0].startswith(stage_prefix)]
    if not rows:
        raise KeyError("没有匹配的环节：%r（用 --list 看全部）" % stage_prefix)
    card = sc.analyze(rows[0])
    doc = _params()
    a, b, c = doc.get("a") or {}, doc.get("b") or {}, doc.get("c") or {}

    cfg_rows = []
    for key in card.get("config") or []:
        if key in a:
            cfg_rows.append({"eu": "flow.%s" % key, "key": key, "tier": "A",
                             "value": a[key].get("value"),
                             "type": a[key].get("type"), "editable": True})
        elif "flow.%s" % key in b:
            e = b["flow.%s" % key]
            cfg_rows.append({"eu": "flow.%s" % key, "key": key, "tier": "B",
                             "value": None, "type": e.get("type"),
                             "editable": False, "why": e.get("reason", "")})
        else:
            cfg_rows.append({"eu": "flow.%s" % key, "key": key, "tier": "?",
                             "value": None, "type": "", "editable": False,
                             "why": "不在 params.json（可能已删或未扫到）"})

    prompt_rows = []
    for const in card.get("prompts") or []:
        hit = [k for k, v in b.items()
               if k.startswith("prompt.") and str(v.get("source", "")).endswith("::" + const)]
        if hit:
            e = b[hit[0]]
            prompt_rows.append({"eu": hit[0], "const": const, "tier": "B",
                                "chars": e.get("chars"), "placeholders": e.get("placeholders")})
        else:
            prompt_rows.append({"eu": "prompt.?." + const.lower(), "const": const,
                                "tier": "B", "chars": None, "placeholders": [],
                                "why": "params.json 未收录（可能不是模块级常量）"})

    tool_rows = [{"eu": "tool.%s" % t, "name": t, "tier": "C",
                  "in_params": ("tool.%s" % t) in c} for t in card.get("tools") or []]

    impl_file = str(card.get("impl") or "").split("::")[0]
    n_ctx, ctx_sample = _ctx_slices(impl_file)

    named = card.get("caps_named") or {}
    bare = card.get("caps_bare") or []
    return {
        "stage": card.get("stage"), "name": card.get("name"),
        "impl": card.get("impl"), "nlines": card.get("nlines"),
        "role": card.get("role"), "fail_policy": card.get("fail_policy"),
        "observable": ["diag.%s" % k for k in (card.get("diag_keys") or [])],
        "trace_steps": _trace_steps(impl_file),
        "reads": card.get("reads") or [], "writes": card.get("writes") or [],
        "config": cfg_rows, "prompts": prompt_rows, "tools": tool_rows,
        "context": {"named_consts": named, "n_hardcoded_slices": n_ctx,
                    "slices_sample": [{"source": x.get("source"), "limit": x.get("extra", {}).get("limit")}
                                      for x in ctx_sample]},
        "max_tokens": card.get("max_tokens") or [],
        "temperature": card.get("temperature") or [],
        "delegates": card.get("delegates") or [],
        "counts": {"A": sum(1 for r in cfg_rows if r["tier"] == "A"),
                   "B_prompt": len(prompt_rows),
                   "C_tool": len(tool_rows),
                   "C_slices": n_ctx,
                   "delegate_files": len(card.get("delegates") or []),
                   "delegate_A": sum(len(d.get("config") or [])
                                     for d in (card.get("delegates") or [])),
                   "delegate_prompts": sum(len(d.get("prompts") or [])
                                           for d in (card.get("delegates") or []))},
    }


def render(doc: dict) -> str:
    lines = ["# %s · %s" % (doc["stage"], doc["name"]), "",
             "实现：`%s`（%s 行）" % (doc["impl"], doc["nlines"]),
             "职责：%s" % (doc["role"] or "-"),
             "失败语义：%s" % (doc["fail_policy"] or "-"), ""]
    c = doc["counts"]
    lines.append("可编辑面：**A 档 %d 个参数 ｜ B 档 %d 段提示词 ｜ C 档 %d 个工具 / %d 处硬编码切片**"
                 % (c["A"], c["B_prompt"], c["C_tool"], c["C_slices"]))
    lines.append("")
    lines.append("## ① 控制流参数（A 档，机器可改）")
    if doc["config"]:
        lines.append("| 单元 | 当前值 | 类型 | 可机改 |")
        lines.append("|---|---|---|---|")
        for r in doc["config"]:
            lines.append("| `%s` | %s | %s | %s |"
                         % (r["eu"], "-" if r["value"] is None else "`%r`" % (r["value"],),
                            r["type"] or "-", "✅" if r["editable"] else "❌ " + (r.get("why") or "")))
    else:
        lines.append("（该环节没有可识别参数）")
    lines.append("")
    lines.append("## ② 提示词（B 档，需人审）")
    if doc["prompts"]:
        for r in doc["prompts"]:
            lines.append("- `%s`（%s 字，占位符 %s）"
                         % (r["eu"], r["chars"] if r["chars"] is not None else "?",
                            ", ".join(r["placeholders"]) or "无"))
    else:
        lines.append("（该环节不注入提示词）")
    lines.append("")
    lines.append("## ③ 工具（C 档，机器永不碰）")
    lines.append("；".join("`%s`" % r["eu"] for r in doc["tools"]) if doc["tools"] else "（无）")
    lines.append("")
    lines.append("## ⑤ 上下文（%d 处硬编码切片）" % c["C_slices"])
    if doc["context"]["named_consts"]:
        lines.append("模块常量（未参数化，改它=改代码）：%s"
                     % "；".join("%s=%s" % (k, v) for k, v in doc["context"]["named_consts"].items()))
    for s in doc["context"]["slices_sample"][:5]:
        lines.append("- `%s` 截断到 %s" % (s["source"], s["limit"]))
    lines.append("")
    lines.append("## 实现在哪（薄壳环节特别看这里）")
    if doc["delegates"]:
        lines.append("该环节是**薄壳**：真实逻辑在 %d 个模块里（%d 行起）—— 只改上面那张参数表会改错地方。"
                     % (len(doc["delegates"]),
                        sum(int(d.get("lines") or 0) for d in doc["delegates"])))
        lines.append("")
        lines.append("| 模块 | 行数 | 参数 | 提示词 |")
        lines.append("|---|---:|---|---|")
        for d in doc["delegates"]:
            lines.append("| `%s` | %s | %s | %s |"
                         % (d.get("rel"), d.get("lines"),
                            ", ".join("`%s`" % x for x in (d.get("config") or [])) or "-",
                            ", ".join("`%s`" % x for x in (d.get("prompts") or [])) or "-"))
    else:
        lines.append("（该环节逻辑就在实现函数里，没有下挂模块）")
    lines.append("")
    lines.append("## 可观测（改完看这里，别只看日志说「调用了」）")
    obs = "；".join("`%s`" % k for k in doc["observable"]) if doc["observable"] else "（文件里没有直接写 diag）"
    lines.append("diag：%s" % obs)
    if doc["trace_steps"]:
        lines.append("trace step：%s" % "；".join("`%s`" % k for k in doc["trace_steps"]))
    if not doc["observable"] and not doc["trace_steps"]:
        lines.append("⚠ 两条观测路都为空 —— 这个环节改完**无法验证**，是真缺口。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L2 机械定位：环节 → 候选可编辑单元")
    ap.add_argument("--stage", default="", help="环节前缀，如 4.1 或 2.7")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    if args.list or not args.stage:
        for r in sc.STAGES:
            print("%-18s %s" % (r[0], r[1]))
        return 0
    try:
        doc = locate(args.stage)
    except KeyError as e:
        print("❌ %s" % e)
        return 2
    print(render(doc))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        print("\n已写 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
