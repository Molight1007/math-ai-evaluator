#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""研究台账：把 DeepSeek 逐题分析结论 + 云端轮次数据，聚合成「优化计划候选清单」。

设计口径
--------
- 输入 ① 逐题分析：`results/_deepseek_audit/*.jsonl`（由 tools/deepseek_error_analyst.py 逐题追加）
- 输入 ② 云端轮次：评测结果 jsonl（`results/run_*.jsonl` 或仓库外只读快照）
- 输出 ① `results/_research/ledger.jsonl`  ── 规范化逐题台账（累积、按 tag+id 去重、幂等）
- 输出 ② `results/_research/research_ledger.md` ── 轮次概览 + 归因直方图 + 优化计划候选
- 状态    `results/_research/backlog_status.json` ── 人工维护的候选状态（pending/doing/done/verified/dropped）

本工具**只读**输入、**只写** `--out-dir`，不触碰运行中的评测目录。

用法
----
  python tools/research_ledger.py
  python tools/research_ledger.py --cloud results/run_2026-09-22_0922_1955.jsonl
  python tools/research_ledger.py --cloud-dir C:/Users/35174/_cloud_snap_0923_2217
"""
# 2026-10-01 去同名：write_text -> write_text_mkdir（写文本**并建父目录**（另一处同名的不建），加 _mkdir 区分）
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import warnings
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore")  # run_eval/sympy 的 deprecation 噪音会淹没台账输出

# ---------------------------------------------------------------- io helpers


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return rows


def write_text_mkdir(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def md_cell(s: Any, n: int = 60) -> str:
    if s is None:
        return ""
    t = str(s).replace("|", "\\|").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def median(xs: List[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else (ys[m - 1] + ys[m]) / 2


# ---------------------------------------------------------------- normalizers


def norm_stage(s: Any) -> str:
    """`3_solve` / `选答（formatter_pick_best）` → 机制段名。"""
    if not s:
        return "(未标注)"
    t = str(s).strip()
    for sep in ("（", "("):
        if sep in t:
            t = t.split(sep)[0]
    t = t.strip()
    return t or "(未标注)"


def norm_target(t: Any) -> str:
    """改动目标：取首个分号段、去括注，作为 backlog 归一键。"""
    if not t:
        return "(未标注)"
    s = str(t).strip()
    for sep in ("；", ";", "。"):
        if sep in s:
            s = s.split(sep)[0]
    for sep in ("（", "("):
        if sep in s:
            s = s.split(sep)[0]
    s = s.strip()
    if len(s) > 48:
        s = s[:47] + "…"
    return s or "(未标注)"


def norm_issue(v: Any) -> str:
    s = str(v or "").strip()
    if s in ("", "-", "None", "null", "无", "N/A"):
        return "-"
    return s


def backlog_key(issue: str, target: str) -> str:
    return f"{issue} | {target}" if issue != "-" else target


# 机制族：把碎成 n=1 的改动目标收敛成**可执行的工作项**。
# 顺序即优先级（先命中先归族）；关键词对 target + error_stage + root_cause 全文匹配。
FAMILIES = [
    ("蓝图/子目标锁值（K11）", ["blueprint", "蓝图", "subgoal", "子目标"]),
    ("工具调用文本通道（K3）", ["toolcall", "tool_call", "tool call", "文本通道"]),
    ("calc 工具与数值自检", ["calc_tool", "enable_calc", "calc 工具", "calc_inconsistent", "sympy"]),
    ("Lean 守卫/闸门（K1）", ["lean_gate", "lean 守卫", "preverify", "formal_gap"]),
    ("候选审核 rubric（K2）", ["audit_gate", "rubric", "level2"]),
    ("零票兜底回滚（K6）", ["zero_vote_fallback", "兜底"]),
    ("选答/聚合排序（K10）", ["pick_diag", "formatter_pick_best", "finalize", "选答", "聚合"]),
    ("穷尽性门禁（K8）", ["exhaust"]),
    ("答案形态闸门（B0/answer_form）", ["answer_form", "b0", "形态闸门"]),
    ("revise/重解上限", ["revise", "max_revise"]),
    ("题库标注与数据质量", ["gold 标注", "标注源", "数据集", "配额"]),
]


def family_of(*texts: Any) -> str:
    blob = " ".join(str(t or "") for t in texts).lower()
    for name, kws in FAMILIES:
        for kw in kws:
            if kw in blob:
                return name
    return "(未归类)"


# ★★★ 2026-09-25 新增：**已被人工否证**的分析结论。
# 为什么必须在这里显式登记：台账每次都由 `results/_deepseek_audit/*.jsonl` 重新生成，
# DeepSeek 的**旧错误结论会自动「复活」**，下一轮又会被当成有效发现。
# 实测案例：`cloud112_0920d`（checker 模式）判 `official112-021` 为
# `error_type=无效数据 / error_stage=invalid_data`，理由是「gold=21 与题面矛盾、正解应为 39」——
# 该结论**已由构造性证明否证**（见下方 note）。这类「怪题库」的结论是**最高危的假阳性**：
# 它会把「模型误读题意」记成「基准有缺陷」，且无法用 `answers_match` 复核。
DISPROVEN_FINDINGS: List[Dict[str, Any]] = [
    {
        "id": "official112-021",
        # ★ 必须带「签名关键词」：同一道题在不同轮次有不同结论 ——
        # 09-22 的「蓝图把值锁死为 39」是**成立的 K11 发现**（描述模型的错误），
        # 09-23c 的「题意误读」也成立；只有「怪题库 / 怪 gold 标注」这一类才是否证对象。
        "match": ["无效数据", "invalid_data", "gold 与题面", "gold 标注", "题库标注"],
        "note": (
            "【gold=21 已证明正确，原判「应为 39」作废】"
            "设 a 轮后未用边构成 H，H 为 (39-a)-正则图；a≤20 ⇒ deg(H)=39-a≥19。"
            "Tutte 计数：奇分量 C 有 |C|(deg+1-|C|) ≤ e(C,S)；|C|≤deg 的分量每条至少贡献 deg 条出边"
            "（|C|=1 与 |C|=deg 两端均取 deg），|C|≥deg+1 的分量至少贡献 1 条；"
            "而 |C|≥deg+1≥20 的「大分量」至多 2 个（3×21>40），由 q=|S|+2 可推出需要 ≥3 个大分量，矛盾 "
            "⇒ 奇分量数 ≤ |S| ⇒ H 必有完美匹配 ⇒ a 轮赛程总能再加一轮。"
            "a=21 时取 H = K_19 ⊕ (21 点 18-正则图，其补为 21-圈)，两分量皆奇数阶 ⇒ H 无完美匹配 ⇒ 不可再加。"
            "故最小 a = 21。**错因：把「最小的 a 使 a 轮不可再加」误读成「最多能排几轮」。**"
        ),
    },
]
FAMILY_DISPROVEN = "已否证结论（不得据此改动）"


def _disproven_note(rid: Any, *texts: Any) -> str:
    """返回该条记录的否证说明；签名关键词不命中则返回空串（结论仍按正常口径统计）。"""
    blob = " ".join(str(t or "") for t in texts).lower()
    for d in DISPROVEN_FINDINGS:
        if str(rid) != d["id"]:
            continue
        if any(kw.lower() in blob for kw in d["match"]):
            return d["note"]
    return ""


# ---------------------------------------------------------------- collect


def _analyst_compat(a: Dict[str, Any]) -> Dict[str, Any]:
    """★ 2026-09-25 新增：analyst 模式（09-23 起的默认模式）的产物字段名与 checker 不同 ——
    它输出 `break_step / break_quote / break_type / what_is_wrong / correct_step /
    gap_to_gold / self_corrections`，**没有** `error_stage / error_type / target /
    known_issue / gold_in_candidates`。
    ⇒ 不做映射的话，analyst 记录会整批落进「(未归类) / 未标注」，台账的机制族分组对新轮次**失效**
    （实测：`run_2026-09-23c` 的 21 条全落 (未归类)）。
    这里只做**字段名对齐**（不编造结论），把 analyst 语义等价字段映射到台账使用的键上。
    """
    if "break_type" not in a and "what_is_wrong" not in a:
        return a
    out = dict(a)
    if not out.get("error_type"):
        out["error_type"] = a.get("break_type")
    if not out.get("root_cause"):
        out["root_cause"] = a.get("what_is_wrong")
    if not out.get("fix_suggestion"):
        out["fix_suggestion"] = a.get("gap_to_gold")
    # `break_step` 是自由文本（"id=11 的【错误分析】段…"），**不能**当作 error_stage 统计，
    # 也**不能**当 `target`（否则每题生成一个 n=1 的新 backlog 键，键名噪音会爆炸）。
    # 它是机制族关键词的最好来源之一 ⇒ 单独放在 `step_hint`，只交给 family_of 用。
    out["step_hint"] = a.get("break_step")
    return out


def collect_audit(audit_dir: str) -> List[Dict[str, Any]]:
    """累积所有逐题分析文件（排除 *_summary.md 之类非 jsonl）。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for path in sorted(glob.glob(os.path.join(audit_dir, "*.jsonl"))):
        for r in load_jsonl(path):
            a = r.get("analysis") or {}
            if not isinstance(a, dict):
                a = {}
            a = _analyst_compat(a)
            rid = r.get("id")
            tag = r.get("tag") or os.path.basename(path).replace(".jsonl", "")
            key = (tag, rid)
            if key in seen:
                continue
            seen.add(key)
            fam = family_of(a.get("target"), a.get("error_stage"),
                            a.get("root_cause"), a.get("step_hint"))
            disproven = _disproven_note(rid, a.get("error_type"), a.get("error_stage"),
                                        a.get("root_cause"), a.get("target"))
            if disproven:
                fam = FAMILY_DISPROVEN
            rows.append(
                {
                    "tag": tag,
                    "id": rid,
                    "tier": r.get("tier"),
                    "elapsed_sec": r.get("elapsed_sec"),
                    "data_quality": r.get("data_quality"),
                    "data_quality_reason": r.get("data_quality_reason"),
                    "analyse_model": r.get("model"),
                    "analysed_at": r.get("analysed_at"),
                    "evidence_sha": r.get("evidence_sha"),
                    "source": r.get("source"),
                    "gold": r.get("gold"),
                    "predicted": r.get("predicted"),
                    # ---- DeepSeek 结论 ----
                    "gold_in_candidates": a.get("gold_in_candidates"),
                    "error_stage": a.get("error_stage"),
                    "error_stage_key": norm_stage(a.get("error_stage")),
                    "error_type": a.get("error_type"),
                    "target": a.get("target"),
                    "target_key": norm_target(a.get("target")),
                    "family": fam,
                    "disproven": disproven,
                    "known_issue": norm_issue(a.get("known_issue")),
                    "confidence": a.get("confidence"),
                    "needs_human": a.get("needs_human"),
                    "root_cause": a.get("root_cause"),
                    "fix_suggestion": a.get("fix_suggestion"),
                    "data_valid": a.get("data_valid"),
                }
            )
    rows.sort(key=lambda x: (str(x["tag"]), str(x["id"])))
    return rows


def _load_answers_match():
    """软加载 run_eval.answers_match，用于本地复核「候选池是否含 gold」。"""
    try:
        sys.path.insert(0, os.getcwd())
        from run_eval import answers_match  # type: ignore

        return answers_match
    except Exception:
        return None


def collect_cloud(paths: List[str], use_local_match: bool = True) -> List[Dict[str, Any]]:
    match = _load_answers_match() if use_local_match else None
    rounds = []
    for p in paths:
        rows = load_jsonl(p)
        if not rows:
            continue
        tag = None
        for r in rows:
            if r.get("tag"):
                tag = r["tag"]
                break
        tag = tag or os.path.basename(p).split("_0922")[0].replace(".jsonl", "")

        n = len(rows)
        n_correct = sum(1 for r in rows if r.get("correct") is True)
        elapsed = [float(r.get("elapsed_sec") or 0) for r in rows]

        stage_tot: Dict[str, float] = defaultdict(float)
        stage_nz: Dict[str, int] = Counter()
        tools: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"calls": 0.0, "ok": 0.0, "fail": 0.0, "seconds": 0.0}
        )
        leansearch = {"calls": 0, "hits": 0, "topk_capped": 0, "maxcalls_capped": 0, "q": 0}
        llm = {"calls": 0, "truncated": 0}
        branches: Counter = Counter()
        n_pool_has_gold = 0
        n_pool_has_gold_local = 0
        n_lean_valid = 0
        port_incorrect = 0  # 池内有 gold 但判错
        consistency = 0

        for r in rows:
            d = r.get("diag") or {}
            st = d.get("stage_timers") or {}
            if isinstance(st, dict):
                for k, v in st.items():
                    try:
                        fv = float(v)
                    except Exception:
                        continue
                    stage_tot[k] += fv
                    if fv > 0.5:
                        stage_nz[k] += 1
            tc = r.get("tool_calls") or {}
            if isinstance(tc, dict):
                for name, cfg in tc.items():
                    if not isinstance(cfg, dict):
                        continue
                    t = tools[name]
                    for f in ("calls", "ok", "fail", "seconds"):
                        try:
                            t[f] += float(cfg.get(f) or 0)
                        except Exception:
                            pass
            ls = d.get("leansearch") or {}
            if isinstance(ls, dict):
                leansearch["calls"] += int(ls.get("calls") or 0)
                leansearch["hits"] += int(ls.get("hits") or 0)
                leansearch["q"] += int(ls.get("n_queries") or 0)
                leansearch["topk_capped"] += 1 if ls.get("top_k_capped") else 0
                leansearch["maxcalls_capped"] += 1 if ls.get("calls_capped") else 0
            lc = r.get("llm_calls") or {}
            if isinstance(lc, dict):
                llm["calls"] += int(lc.get("calls") or 0)
                llm["truncated"] += int(lc.get("truncated") or 0)
            pd_ = d.get("pick_diag") or {}
            if isinstance(pd_, dict) and pd_.get("branch"):
                branches[pd_["branch"]] += 1
            if d.get("lean_active") and [x for x in (d.get("lean_gate") or []) if _lean_ok(x)]:
                n_lean_valid += 1

            cands = r.get("candidates") or []
            gold = r.get("gold") or ""
            has_gold = None
            if match is not None and gold:
                try:
                    has_gold = any(match(str(c.get("answer") or ""), str(gold)) for c in cands)
                    if has_gold:
                        n_pool_has_gold_local += 1
                        if r.get("correct") is not True:
                            port_incorrect += 1
                except Exception:
                    has_gold = None
            # 与错误字段口径交叉校验（本地重算 vs 记录值）
            try:
                if match is not None and r.get("predicted") is not None and gold:
                    recalc = bool(match(str(r.get("predicted") or ""), str(gold)))
                    if recalc != bool(r.get("correct")):
                        consistency += 1
            except Exception:
                pass

        rounds.append(
            {
                "file": p,
                "tag": tag,
                "n": n,
                "n_correct": n_correct,
                "acc": (n_correct / n) if n else 0.0,
                "elapsed_mean": (sum(elapsed) / n) if n else 0.0,
                "elapsed_med": median(elapsed),
                "elapsed_max": max(elapsed) if elapsed else 0.0,
                "stage_tot": dict(stage_tot),
                "stage_nz": dict(stage_nz),
                "tools": {k: dict(v) for k, v in tools.items()},
                "leansearch": leansearch,
                "llm": llm,
                "branches": dict(branches),
                "n_lean_valid": n_lean_valid,
                "n_pool_has_gold_local": n_pool_has_gold_local,
                "n_pool_has_gold_but_wrong": port_incorrect,
                "correct_field_mismatch": consistency,
            }
        )
    return rounds


def _lean_ok(v: Any) -> bool:
    if isinstance(v, dict):
        return bool(v.get("lean_valid") or v.get("answer_valid") or v.get("compile_valid"))
    return False


# ---------------------------------------------------------------- aggregate


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    by_type = Counter(r["error_type"] or "(未标注)" for r in rows)
    by_stage = Counter(r["error_stage_key"] or "(未标注)" for r in rows)
    by_issue = Counter(r["known_issue"] for r in rows)
    by_tier = Counter(r["tier"] or "(未知)" for r in rows)
    by_family = Counter(r["family"] for r in rows)
    by_tag = Counter(r["tag"] for r in rows)
    # 轮次 × 族 交叉表
    tag_family: Dict[str, Counter] = defaultdict(Counter)
    tag_pool: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        tag_family[r["tag"]][r["family"]] += 1
        v = r.get("gold_in_candidates")
        tag_pool[r["tag"]]["含gold" if v is True else ("无gold" if v is False else "未判")] += 1
    pool = Counter()
    for r in rows:
        v = r.get("gold_in_candidates")
        pool["池内含 gold" if v is True else ("池内无 gold" if v is False else "未判")] += 1
    need = sum(1 for r in rows if r.get("needs_human"))
    dq = Counter(r.get("data_quality") or "(未知)" for r in rows)

    def _mkgroup(k: str, issue: str, target: str, r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "key": k, "issue": issue, "target": target,
            "ids": [], "confs": [], "roots": Counter(), "fixes": Counter(),
            "stages": Counter(), "families": Counter(),
        }

    groups: Dict[str, Dict[str, Any]] = {}
    fams: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        # ★ 已否证结论**既不生成工作项、也不生成族工作项**（它仍出现在「一、错题归因总览」
        # 的族分布里，但不得作为优化计划候选 —— 否则会诱导下一轮去"修题库"）。
        if r["family"] == FAMILY_DISPROVEN:
            continue
        k = backlog_key(r["known_issue"], r["target_key"])
        g = groups.setdefault(k, _mkgroup(k, r["known_issue"], r["target_key"], r))
        f = fams.setdefault(r["family"], _mkgroup(r["family"], "-", r["family"], r))
        for tgt in (g, f):
            tgt["ids"].append(f'{r["tag"]}:{r["id"]}')
            if isinstance(r.get("confidence"), (int, float)):
                tgt["confs"].append(float(r["confidence"]))
            if r.get("root_cause"):
                tgt["roots"][md_cell(r["root_cause"], 120)] += 1
            if r.get("fix_suggestion"):
                tgt["fixes"][md_cell(r["fix_suggestion"], 200)] += 1
            tgt["stages"][r["error_stage_key"]] += 1
        g["families"][r["family"]] += 1
        f["families"][r["known_issue"]] += 1

    for d in (groups, fams):
        for g in d.values():
            g["n"] = len(g["ids"])
            g["conf_avg"] = (sum(g["confs"]) / len(g["confs"])) if g["confs"] else None
            g["uniq_ids"] = len(set(g["ids"]))
    ordered = sorted(groups.values(), key=lambda g: (-g["n"], g["key"]))
    fam_ordered = sorted(fams.values(), key=lambda g: (-g["n"], g["key"]))
    return {
        "n": n,
        "by_type": by_type,
        "by_stage": by_stage,
        "by_issue": by_issue,
        "by_tier": by_tier,
        "by_family": by_family,
        "by_tag": by_tag,
        "tag_family": {k: dict(v) for k, v in tag_family.items()},
        "tag_pool": {k: dict(v) for k, v in tag_pool.items()},
        "pool": pool,
        "need_human": need,
        "data_quality": dq,
        "groups": ordered,
        "families": fam_ordered,
    }


def load_status(out_dir: str) -> Dict[str, Any]:
    p = os.path.join(out_dir, "backlog_status.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def ensure_status_file(out_dir: str, families: List[Dict[str, Any]],
                       groups: List[Dict[str, Any]]) -> str:
    """状态文件：不存在则初始化，已存在则**只补新增 key**，绝不覆盖人工填写的状态。"""
    p = os.path.join(out_dir, "backlog_status.json")
    cur: Dict[str, Any] = {}
    if os.path.exists(p):
        try:
            cur = json.load(open(p, encoding="utf-8")) or {}
        except Exception:
            cur = {}
    added = 0
    for g in list(families) + list(groups):
        if g["key"] not in cur:
            cur[g["key"]] = {"status": "pending", "note": ""}
            added += 1
    write_text_mkdir(p, json.dumps(cur, ensure_ascii=False, indent=2))
    if added:
        print(f"[ledger] backlog_status.json 新增 {added} 个待办 key（已有状态保留）")
    return p


# ---------------------------------------------------------------- render


def render(agg: Dict[str, Any], rounds: List[Dict[str, Any]], status: Dict[str, Any]) -> str:
    L: List[str] = []
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    L.append("# 研究台账 · 优化计划依据")
    L.append("")
    L.append(f"- 生成时间：{ts}")
    L.append(f"- 逐题分析记录：`results/_deepseek_audit/*.jsonl`（**单独维护、可单独读取**）")
    L.append(f"- 台账明细：`results/_research/ledger.jsonl`；候选状态：`results/_research/backlog_status.json`")
    L.append("")
    L.append("> 口径声明：本页是**线索层**，不是结论层。任何据此发起的改动仍须过「配对差异 ≥5pp 且 net≥3」判据。")
    L.append(">")
    L.append("> ⚠ **两种分析模式混在同一份台账里，读「错误类型」时要分层**：")
    L.append("> · `checker` 模式（旧）产出 → 求解错误 / 选答错误 / 机制缺失 / 抽取崩坏（**归因到环节**，"
             "机制族分组只对该模式有意义）；")
    L.append("> · `analyst` 模式（2026-09-23 起默认，产物带 `_analyst` 后缀）产出 → 题意误读 / 未穷尽 / "
             "前提未证 / 引用外部结论 / 漏分支 / 跳步 / 定义域错 / 计算错（**推理断点分类**，不含代码机制名）；")
    L.append("> · 因此 analyst 记录多落 `(未归类)`，**不代表没有缺陷**，而是它描述的是「推理哪一步断」，"
             "不是「哪个代码机制失效」。")
    L.append("")

    # ---------- 〇、已否证结论（防旧结论自动复活）
    L.append("## 〇、★ 已否证结论（**不得再据此改动**）")
    L.append("")
    L.append("台账每次都由 `results/_deepseek_audit/*.jsonl` 重新生成 ⇒ DeepSeek 的**旧错误结论会自动复活**。"
             "下列条目已由人工复核否证：命中「签名关键词」的记录其 `family` 一律改写为「"
             + FAMILY_DISPROVEN + "」，且**不生成优化计划候选**；"
             "同一道题的其它结论（如 K11、题意误读）不受影响，仍按正常口径统计。")
    L.append("")
    if DISPROVEN_FINDINGS:
        L.append("| 题号 | 签名关键词（命中即判否证） | 否证依据 |")
        L.append("|---|---|---|")
        for d in DISPROVEN_FINDINGS:
            L.append(f"| {d['id']} | {' / '.join(d['match'])} | {d['note']} |")
    else:
        L.append("_（暂无）_")
    L.append("")

    # ---------- 一、错题归因总览
    n = agg["n"]
    L.append(f"## 一、错题归因总览（DeepSeek 逐题，n={n}）")
    L.append("")
    if n == 0:
        L.append("_尚无逐题分析记录。_")
        L.append("")
    else:
        L.append("| 维度 | 分布 |")
        L.append("|---|---|")
        L.append("| **机制族** | " + "；".join(f"{k} {v}（{v/n:.1%}）" for k, v in agg["by_family"].most_common()) + " |")
        L.append("| 错误类型 | " + "；".join(f"{k} {v}（{v/n:.1%}）" for k, v in agg["by_type"].most_common()) + " |")
        L.append("| 错误环节 | " + "；".join(f"{k} {v}（{v/n:.1%}）" for k, v in agg["by_stage"].most_common()) + " |")
        L.append("| 已知缺陷 | " + "；".join(f"{k} {v}" for k, v in agg["by_issue"].most_common()) + " |")
        L.append("| 候选池 gold | " + "；".join(f"{k} {v}（{v/n:.1%}）" for k, v in agg["pool"].most_common()) + " |")
        L.append("| 档位 | " + "；".join(f"{k} {v}" for k, v in agg["by_tier"].most_common()) + " |")
        L.append("| 数据质量 | " + "；".join(f"{k} {v}" for k, v in agg["data_quality"].most_common()) + " |")
        L.append(f"| 建议人工复核 | {agg['need_human']}（{agg['need_human']/n:.1%}） |")
        L.append("")
        L.append("### 按轮次分段（跨轮混合会掩盖机制健康度）")
        L.append("")
        L.append("| 轮次 | 错题数 | 池内含 gold | 该轮机制族分布（top3） |")
        L.append("|---|---|---|---|")
        for tag, cnt in agg["by_tag"].most_common():
            fams = sorted(agg["tag_family"][tag].items(), key=lambda x: -x[1])[:3]
            tp = agg["tag_pool"].get(tag, {})
            L.append(
                f"| {tag} | {cnt} | {tp.get('含gold',0)}/{cnt} | "
                + "；".join(f"{k} {v}" for k, v in fams) + " |"
            )
        L.append("")
        L.append("### 机制族分布（文本条形）")
        L.append("")
        L.append("```")
        mx = max(v for _, v in agg["by_family"].most_common()) or 1
        for k, v in agg["by_family"].most_common():
            L.append(f"{k:<30} {'█' * max(1, round(v / mx * 30))} {v}")
        L.append("")
        mx2 = max(v for _, v in agg["by_stage"].most_common()) or 1
        L.append("-- 错误环节 --")
        for k, v in agg["by_stage"].most_common():
            L.append(f"{k:<30} {'█' * max(1, round(v / mx2 * 30))} {v}")
        L.append("```")
        L.append("")

    # ---------- 二、优化计划候选（两层）
    st_alias = {
        "pending": "⬜ 待办",
        "doing": "🟡 进行中",
        "done": "🟦 已改待验",
        "verified": "✅ 已验证",
        "dropped": "⛔ 弃用",
    }

    def _status_of(key: str) -> str:
        st = (status.get(key) or {}).get("status", "pending")
        return st_alias.get(st, st)

    L.append("## 二、优化计划候选")
    L.append("")
    L.append("> `状态` 来自 `backlog_status.json`（人工维护：pending / doing / done / verified / dropped），未标注默认 pending。")
    L.append("> **先看 2.1 选工作项，2.2 只作落地细节查阅。**")
    L.append("")
    L.append("### 2.1 机制族工作项（可执行粒度）")
    L.append("")
    L.append("| # | 机制族 | 命中 | 占比 | 覆盖题号 | 族内缺陷 | 状态 | 族代表根因 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, g in enumerate(agg["families"], 1):
        ids = sorted(set(x.split(":", 1)[1] for x in g["ids"]))
        issues = "；".join(f"{k} {v}" for k, v in g["families"].most_common() if k != "-")
        root = g["roots"].most_common(1)[0][0] if g["roots"] else ""
        L.append(
            f"| {i} | **{g['key']}** | {g['n']} | {g['n']/n:.1%} | {md_cell('、'.join(ids), 70)} | "
            f"{md_cell(issues, 30)} | {_status_of(g['key'])} | {root} |"
        )
    L.append("")
    L.append("### 2.2 族内细化目标（落地细节）")
    L.append("")
    L.append("| # | 族 | 缺陷 | 改动目标 | 命中 | 占比 | 置信均 | 状态 | DeepSeek 建议 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, g in enumerate(agg["groups"], 1):
        conf = f"{g['conf_avg']:.2f}" if g["conf_avg"] is not None else "-"
        fam = g["families"].most_common(1)[0][0] if g["families"] else "-"
        fix = g["fixes"].most_common(1)[0][0] if g["fixes"] else ""
        L.append(
            f"| {i} | {md_cell(fam, 20)} | {g['issue']} | {md_cell(g['target'], 36)} | {g['n']} | "
            f"{g['n']/n:.1%} | {conf} | {_status_of(g['key'])} | {fix} |"
        )
    L.append("")

    # ---------- 三、云端轮次概览
    L.append("## 三、云端轮次概览（环节 / 工具效果）")
    L.append("")
    if not rounds:
        L.append("_未提供云端结果文件（用 `--cloud` 指定）。_")
        L.append("")
    else:
        L.append("| 轮次 | 完成 | 正确 | 正确率 | 耗时均值 | 耗时中位 | 耗时最大 | 判分口径重算不一致 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in rounds:
            L.append(
                f"| {r['tag']} | {r['n']} | {r['n_correct']} | {r['acc']:.1%} | "
                f"{r['elapsed_mean']:.0f}s | {r['elapsed_med']:.0f}s | {r['elapsed_max']:.0f}s | "
                f"{r['correct_field_mismatch']} |"
            )
        L.append("")
        for r in rounds:
            tot = sum(r["stage_tot"].values()) or 1.0
            L.append(f"### {r['tag']} · 阶段耗时占比")
            L.append("")
            L.append("| 阶段 | 占比 | 总时长(s) | 非零题数 |")
            L.append("|---|---|---|---|")
            for k, v in sorted(r["stage_tot"].items(), key=lambda x: -x[1])[:12]:
                L.append(f"| {k} | {v/tot:.1%} | {v:.0f} | {r['stage_nz'].get(k,0)} |")
            L.append("")
            L.append(f"### {r['tag']} · 工具与机制效果")
            L.append("")
            L.append("| 工具/机制 | 调用 | 成功 | 失败 | 耗时(s) |")
            L.append("|---|---|---|---|---|")
            for name, t in sorted(r["tools"].items(), key=lambda x: -x[1]["calls"]):
                L.append(f"| {name} | {int(t['calls'])} | {int(t['ok'])} | {int(t['fail'])} | {t['seconds']:.0f} |")
            ls = r["leansearch"]
            L.append(
                f"| leansearch | {ls['calls']} | hits {ls['hits']} | top_k 撞顶 {ls['topk_capped']} 题 | "
                f"calls 撞顶 {ls['maxcalls_capped']} 题 |"
            )
            L.append(
                f"| LLM 调用 | {r['llm']['calls']} | 截断 {r['llm']['truncated']} | Lean 有效题 {r['n_lean_valid']} | "
                f"池内本地复核含 gold {r['n_pool_has_gold_local']} 题（其中判错 {r['n_pool_has_gold_but_wrong']}） |"
            )
            if r["branches"]:
                L.append("")
                L.append("选答分支分布：" + "；".join(f"`{k}` {v}" for k, v in sorted(r["branches"].items(), key=lambda x: -x[1])))
            L.append("")

    # ---------- 四、逐题明细
    L.append("## 四、逐题明细")
    L.append("")
    L.append("| 题号 | 轮次 | 档位 | 环节 | 类型 | 池内含gold | 缺陷 | 置信 | 需人看 | 数据质量 | 根因 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(agg.get("_rows", []), key=lambda x: (str(x["tag"]), str(x["id"]))):
        L.append(
            f"| {r['id']} | {r['tag']} | {r['tier']} | {md_cell(r['error_stage_key'],24)} | {r['error_type']} | "
            f"{r['gold_in_candidates']} | {r['known_issue']} | {r['confidence']} | {r['needs_human']} | "
            f"{r['data_quality']} | {md_cell(r['root_cause'],110)} |"
        )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-dir", default="results/_deepseek_audit")
    ap.add_argument("--cloud", action="append", default=[], help="云端结果 jsonl（可多次）")
    ap.add_argument("--cloud-dir", default="", help="扫描该目录下 run_*.jsonl")
    ap.add_argument("--out-dir", default="results/_research")
    ap.add_argument("--no-recalc", action="store_true", help="不做本地判分口径复核")
    args = ap.parse_args()

    rows = collect_audit(args.audit_dir)
    paths = list(args.cloud)
    if args.cloud_dir:
        paths += sorted(glob.glob(os.path.join(args.cloud_dir, "*.jsonl")))
    paths = [p for p in paths if os.path.exists(p)]
    rounds = collect_cloud(paths, use_local_match=not args.no_recalc)

    agg = aggregate(rows)
    agg["_rows"] = rows

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "ledger.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    st_path = ensure_status_file(args.out_dir, agg["families"], agg["groups"])
    status = load_status(args.out_dir)

    md = render(agg, rounds, status)
    out_md = os.path.join(args.out_dir, "research_ledger.md")
    write_text_mkdir(out_md, md)

    print(f"[ledger] 逐题分析 {len(rows)} 条 / 云端轮次 {len(rounds)} 个")
    print(f"[ledger] 写 {out_md}")
    print(f"[ledger] 写 {os.path.join(args.out_dir,'ledger.jsonl')}")
    print(f"[ledger] 状态文件 {st_path}")
    print(f"[ledger] 候选目标 {len(agg['groups'])} 组；错误环节 top3 = "
          + "；".join(f"{k} {v}" for k, v in agg["by_stage"].most_common(3)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
