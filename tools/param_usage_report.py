#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""param_usage_report.py —— 可调上限「实测 vs 配置」汇总报告（2026-09-21）。

用法（仓库根）：::

    python tools/param_usage_report.py results/arm2c2t_0921_1551.jsonl
    python tools/param_usage_report.py <run.jsonl> --log <run.log> --out <out.md>

为什么要这个脚本
    用户诉求：『对于 leansearch 到底要找多少 mathlib 的定理，检测打回要搞多少次，
    无条件重做要搞多少次，子目标要设立多少，像这种数据你都要找到并记录
    （不止我说的这几个）我们要测试出最合理的数据。』
    单题埋点落在 `diag.param_usage`（见 `agent/param_usage.py`），本脚本把它
    **跨题聚合**成"到底该调哪个参数"的决策表 —— 调参要有分布，不能靠均值拍。

数据来源（三路，缺哪路就少哪节，不报错）
    1. `<run>.jsonl` 行内 `diag.param_usage`   —— 计数类上限（次数/条数/个数）实测
    2. `<run>.jsonl` 行内 `diag.leansearch`    —— 检索需求侧（要找多少定理）
    3. `<run>.log` 内 `LLM response truncated` —— token 类上限实测
       行格式：`... max_tokens=32768, site=Solver@base.py:757 <- solver.py:1437)`

⚠ 输出 md 的约定（与 测试结果/xin测试结果 的 Word 流水线一致）：
   · 不写围栏代码块；· 正文里的竖线一律用 ∣（U+2223）；
   · 表格单元格内不放带 `**` 的行内代码（转换器会漏出星号）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agent.param_usage import aggregate  # noqa: E402

_TRUNC_RE = re.compile(
    r"LLM response truncated .*?max_tokens=(?P<mt>\S+?)[,)]"
    r"(?:\s*site=(?P<site>.+?)\))?\s*$")


# ----------------------------------------------------------------------
# 读数据
# ----------------------------------------------------------------------
def load_rows(path: str) -> list[dict]:
    rows = []
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(r, dict):
                rows.append(r)
    return rows


def collect_param_usage_records(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        d = r.get("diag")
        pu = d.get("param_usage") if isinstance(d, dict) else None
        if isinstance(pu, dict) and pu.get("items"):
            out.append(pu)
    return out


def parse_truncations(log_path: str) -> dict:
    """从日志里统计截断：按 max_tokens 与按调用点。"""
    by_mt: Counter = Counter()
    by_site: Counter = Counter()
    n_lines = 0
    if not log_path or not os.path.isfile(log_path):
        return {"by_max_tokens": {}, "by_site": {}, "n_lines": 0,
                "path": log_path or "", "exists": False}
    with io.open(log_path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            if "LLM response truncated" not in raw:
                continue
            n_lines += 1
            m = _TRUNC_RE.search(raw.rstrip("\n"))
            if not m:
                # 极端兜底：连 max_tokens 都取不到
                m2 = re.search(r"max_tokens=(\S+?)[,)]", raw)
                by_mt[m2.group(1) if m2 else "?"] += 1
                by_site["(无法解析的截断行)"] += 1
                continue
            mt = m.group("mt")
            # ⚠ 老格式（无 site= 字段）也会被主正则匹配到，只是 site 组为空 ⇒
            #   必须在**这里**判空，不能指望 `if not m` 分支（0921 实测踩过）。
            site = (m.group("site") or "").strip()
            by_mt[mt] += 1
            by_site[site or "(日志无 site 字段 ⇒ 需新版补丁后的日志)"] += 1
    return {"by_max_tokens": dict(by_mt), "by_site": dict(by_site),
            "n_lines": n_lines, "path": log_path, "exists": True}


# ----------------------------------------------------------------------
# 判读
# ----------------------------------------------------------------------
def verdict_of(item: dict) -> str:
    used = item.get("used") or {}
    cap = item.get("cap")
    rate = item.get("capped_rate")
    if not used.get("n"):
        return "无实测口径 ⇒ 先补埋点"
    if not item.get("exact"):
        return "代理口径 ⇒ 勿据此调参（需补真计数点）"
    if cap is None:
        return "上限取不到 ⇒ 检查配置"
    if rate is not None and rate >= 0.30:
        return "★ 频繁撞顶 ⇒ 优先抬高"
    if rate:
        return "偶发撞顶 ⇒ 观察"
    mx = used.get("max")
    if mx is not None and cap > 0 and mx <= cap * 0.60:
        return "余量充足 ⇒ 维持或收紧"
    return "未触顶 ⇒ 维持"


def _cap_str(item: dict) -> str:
    vals = item.get("cap_values") or []
    if len(vals) > 1:
        return " / ".join(str(v) for v in vals) + "（按档位）"
    return str(item.get("cap")) if item.get("cap") is not None else "-"


def _num(v, nd=2):
    return "-" if v is None else (("%." + str(nd) + "f") % v if isinstance(v, float)
                                  else str(v))


# ----------------------------------------------------------------------
# 报告
# ----------------------------------------------------------------------
def build_report(rows, ag, tr, jsonl_path, log_path, top_k=5) -> str:
    L = []
    A = L.append
    n_q = len(rows)
    n_scored = sum(1 for r in rows if r.get("correct") is not None)
    n_ok = sum(1 for r in rows if r.get("correct") is True)
    A("# 可调上限「实测 vs 配置」汇总")
    A("")
    A("**数据源**：`%s`（%d 行记录，含判定的 %d 题，判对 %d 题）"
      % (os.path.basename(jsonl_path), n_q, n_scored, n_ok))
    A("")
    A("- 含 `diag.param_usage` 的题数：%d" % ag.get("n_questions", 0))
    A("- 截断日志：%s（%s）"
      % (os.path.basename(log_path) if log_path else "未提供",
         "命中 %d 行" % tr["n_lines"] if tr["exists"] else "文件不存在"))
    A("")
    if not ag.get("n_questions"):
        A("> ⚠ 本批结果里没有 `diag.param_usage` —— 说明该轮跑的代码还是旧版，"
          "或本轮未落盘。请用打过 2026-09-21 补丁后的代码重跑一次。")
        A("")
    A("## 一、逐参数：实测 vs 上限")
    A("")
    A("上限 = 配置值（档位化参数会同时列出各档）；实测均值/最大 = 各题 `used` 的分布；"
      "撞顶率 = 该参数 `used >= cap` 的题占比。")
    A("")
    A("| 参数 | 单位 | 上限 | 实测均值 | 实测最大 | 观测题数 | 撞顶题数 | 撞顶率 | 判读 |")
    A("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in sorted(ag.get("items", {})):
        it = ag["items"][name]
        used = it.get("used") or {}
        A("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name, _unit_of(name), _cap_str(it),
            _num(used.get("mean")), _num(used.get("max")),
            _num(used.get("n")), it.get("n_capped"),
            ("%.0f%%" % (100 * it["capped_rate"])) if it.get("capped_rate") is not None else "-",
            verdict_of(it)))
    A("")
    gaps = sorted({g for r in collect_param_usage_records(rows)
                   for g in (r.get("gaps") or [])})
    approx = sorted({g for r in collect_param_usage_records(rows)
                     for g in (r.get("approx") or [])})
    if gaps:
        A("- **无实测口径（要调它就必须先补埋点）**：%s" % "、".join(gaps))
    if approx:
        A("- **只有代理指标（判不了是否撞顶，勿据此调参）**：%s" % "、".join(approx))
    A("")

    A("## 二、LeanSearch：要找多少 Mathlib 定理（需求侧）")
    A("")
    ls = _leansearch_stats(rows, top_k=top_k)
    A("| 指标 | 每题均值 | 每题最大 | 观测题数 |")
    A("| --- | --- | --- | --- |")
    for k, label in (("n_queries", "检索调用次数"),
                     ("hits", "命中定理条数（未去重）"),
                     ("unique", "去重后定理种类数"),
                     ("per_query_max", "单次检索命中条数"),
                     ("skipped_time_critical", "因时间紧张跳过次数"),
                     ("skipped_call_cap", "因达单题次数上限跳过次数")):
        s = ls.get(k) or {}
        A("| %s | %s | %s | %s |" % (label, _num(s.get("mean")),
                                     _num(s.get("max")), _num(s.get("n"))))
    A("")
    A("判读口径：`top_k_capped` 率高 ⇒ 单次命中被 `leansearch_top_k` 截断，"
      "「找不够定理」是**条数上限**的问题；`calls_capped` 率高 ⇒ 单题检索次数"
      "被 `leansearch_max_calls_per_q` 限住。两者要分开调。")
    A("")
    A("- `leansearch_top_k` 撞顶率（精确字段）：%s"
      % _rate_str(ls.get("top_k_capped_rate"), ls.get("top_k_capped_n")))
    A("- `leansearch_max_calls_per_q` 撞顶率（精确字段）：%s"
      % _rate_str(ls.get("calls_capped_rate"), ls.get("calls_capped_n")))
    A("- 命中条数达到 `leansearch_top_k`（假设 = %s）的题占比（**推测口径**）：%s"
      % (ls.get("top_k_assumed"),
         _rate_str(ls.get("hits_at_top_k_rate"), ls.get("hits_at_top_k_n"))))
    A("")
    A("> 推测口径的用途：检索器按 `top_k` 截断，命中条数顶到 `top_k` 就说明候选池"
      "**可能还有定理被切掉**。比例高（≥80%）时，即使老结果没有精确字段，也足以"
      "判断『先抬 `leansearch_top_k` 再看』。")
    A("")

    A("## 三、token 类上限：截断发生在哪一档、哪段代码")
    A("")
    if not tr["exists"] or not tr["by_max_tokens"]:
        A("> 未取到截断日志（或本轮无截断）。")
    else:
        A("| max_tokens（撞顶档） | 次数 | 推论对应参数 |")
        A("| --- | --- | --- |")
        for mt, c in sorted(tr["by_max_tokens"].items(),
                            key=lambda kv: -kv[1]):
            A("| %s | %d | %s |" % (mt, c, _mt_to_param(mt)))
        A("")
        A("| 调用点（栈反查） | 次数 |")
        A("| --- | --- |")
        for site, c in sorted(tr["by_site"].items(), key=lambda kv: -kv[1])[:15]:
            A("| `%s` | %d |" % (site, c))
    A("")
    A("## 四、怎么用这张表")
    A("")
    A("1. 只动「频繁撞顶」的参数，一次一个，跑完再看本表；"
      "撞顶率降到个位数即可停手 —— 继续抬只会让单次调用变长，"
      "对正确率没有证据支撑。")
    A("2. 「余量充足」的参数（实测最大远低于上限）说明当前值并未生效于瓶颈，"
      "调它不会有收益，别浪费一轮。")
    A("3. 标了「只有代理指标」的参数，其 `used` 与 `cap` **不是同一个量**，"
      "本表刻意不判撞顶；要判就得先在代码里补真计数点。")
    A("4. token 类上限看第三节：撞在 6144 是深复核上限、撞在 32768 是"
      "**硬编码**调用点（不跟随 `max_answer_tokens`），改法与改 env 不同。")
    A("")
    return "\n".join(L) + "\n"


_UNIT = {}


def _unit_of(name: str) -> str:
    if name in _UNIT:
        return _UNIT[name]
    try:
        from agent.param_usage import _SPEC
        for row in _SPEC:
            if row[0] == name:
                _UNIT[name] = row[3]
                return row[3]
    except Exception:  # noqa: BLE001
        pass
    return "-"


_MT_PARAM = {
    "65536": "max_answer_tokens（env MAX_ANSWER_TOKENS）",
    "32768": "⚠ 硬编码 32768（verifier / sub_goal_solver 等多处字面量）",
    "16384": "verifier_deep_review_max_tokens 的代码默认值",
    "6144": "verifier_deep_review_max_tokens（run_112.py CLI 设定）",
    "4096": "⚠ 硬编码 4096（需按 site 列定位）",
    "640": "adversarial_max_tokens",
    "512": "symbolic_max_tokens / 硬编码 512",
    "384": "symbolic_solve_max_tokens",
    "256": "⚠ 硬编码 256（需按 site 列定位）",
}


def _mt_to_param(mt: str) -> str:
    return _MT_PARAM.get(str(mt), "⚠ 未登记，按下方 site 列定位")


def _leansearch_stats(rows: list[dict], top_k: int | None = 5) -> dict:
    """LeanSearch 需求侧统计。

    ⚠ 关键防错（0921 实测踩到）：老结果的 `diag.leansearch` **没有**
      `top_k_capped` / `calls_capped` / `n_queries` 这些新字段。若用
      `ls.get(...)` 直接取，缺失会被当成 False ⇒ 撞顶率显示 0%，是**假阴性**
      （实测 44 题每题命中都恰好 5 = top_k，明显饱和）。
      ⇒ 撞顶率的分母只能取"真正带该字段的题数"，无字段时返回 None 并在报告里
        写明"本批无该字段"。
    """
    acc: dict = {}
    n_tk = n_tk_obs = n_cc = n_cc_obs = 0
    n_sat = n_sat_obs = 0
    for r in rows:
        d = r.get("diag") if isinstance(r.get("diag"), dict) else {}
        ls = d.get("leansearch")
        if not isinstance(ls, dict) or not ls:
            continue
        pq = ls.get("per_query") or []
        vals = {
            # 老结果只有 calls（无 n_queries）⇒ 回退，避免整列变成 "-"
            "n_queries": ls.get("n_queries", ls.get("calls")),
            "hits": ls.get("hits"),
            "unique": ls.get("unique"),
            "per_query_max": (max(pq) if pq else None),
            "skipped_time_critical": ls.get("skipped_time_critical"),
            "skipped_call_cap": ls.get("skipped_call_cap"),
        }
        for k, v in vals.items():
            if isinstance(v, int):
                acc.setdefault(k, []).append(v)
        if "top_k_capped" in ls:
            n_tk_obs += 1
            if ls["top_k_capped"]:
                n_tk += 1
        if "calls_capped" in ls:
            n_cc_obs += 1
            if ls["calls_capped"]:
                n_cc += 1
        # 推测口径：命中条数顶到 top_k ⇒ 饱和（无需新字段，老结果也能算）
        h = ls.get("hits")
        if isinstance(h, int) and top_k:
            n_sat_obs += 1
            if h >= top_k:
                n_sat += 1
    n = max((len(v) for v in acc.values()), default=0)
    out = {}
    for k, v in acc.items():
        out[k] = {"n": len(v), "mean": round(sum(v) / len(v), 2), "max": max(v)}
    out["top_k_capped_rate"] = (n_tk / n_tk_obs) if n_tk_obs else None
    out["top_k_capped_n"] = n_tk_obs
    out["calls_capped_rate"] = (n_cc / n_cc_obs) if n_cc_obs else None
    out["calls_capped_n"] = n_cc_obs
    out["hits_at_top_k_rate"] = (n_sat / n_sat_obs) if n_sat_obs else None
    out["hits_at_top_k_n"] = n_sat_obs
    out["top_k_assumed"] = top_k
    return out


def _rate_str(rate, n_obs, what="观测"):
    if rate is None:
        return "-（本批无该字段，需新版代码重跑）"
    return "%.0f%%（%s %s 题）" % (100 * rate, what, n_obs)


# ----------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="可调上限实测 vs 配置 汇总报告")
    ap.add_argument("jsonl", help="run_eval 产出的 jsonl 结果文件")
    ap.add_argument("--log", default=None,
                    help="同一轮的 .log（默认取同名 .log）")
    ap.add_argument("--out", default=None, help="输出 md 路径（默认打印到 stdout）")
    ap.add_argument("--leansearch-top-k", type=int, default=5,
                    help="用于**推测**检索饱和的 top_k（默认 5，与代码默认一致）")
    args = ap.parse_args(argv)

    rows = load_rows(args.jsonl)
    if not rows:
        print("FATAL: %s 里没有可解析的记录" % args.jsonl)
        return 2
    log_path = args.log
    if not log_path:
        cand = re.sub(r"\.jsonl$", ".log", args.jsonl)
        log_path = cand if os.path.isfile(cand) else ""

    ag = aggregate(collect_param_usage_records(rows))
    tr = parse_truncations(log_path)
    md = build_report(rows, ag, tr, args.jsonl, log_path,
                      top_k=args.leansearch_top_k)

    if args.out:
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
        print("报告已写出：%s（%d 字节）" % (args.out, len(md.encode("utf-8"))))
    else:
        sys.stdout.write(md)

    # 控制台补充一句最关键的结论，便于长跑时一眼看到
    tops = [n for n in ag.get("items", {})
            if (ag["items"][n].get("capped_rate") or 0) >= 0.3]
    if tops:
        print("\n[高频撞顶] " + "、".join(sorted(tops)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
