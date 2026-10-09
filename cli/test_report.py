# -*- coding: utf-8 -*-
"""一次测试 → 一个 Word 文档（2026-09-22 用户确立的新口径）。

口径（用户 2026-09-22 明确）
--------------------------
- 输出目录：`测试结果/`（**不再用 xin测试结果 子目录**）
- **一次测试只出一个文档**，不多加
- 文件名：`日期-题目数量-正确的题数.docx`
- 内容必须覆盖用户点名的监测项：
  1. 测试的具体数据
  2. 每题消耗的时间
  3. 各环节消耗的时间
  4. 各环节哪里错了
  5. 哪里没有达到预期目标
  6. 哪些工具没有使用起来
  7. 大模型的推理错误与计算错误出在哪里
  8. 其余已监测项（闸门、候选项、参数撞顶、资源、已知缺陷）

用法
----
    D:/python/python.exe cli/test_report.py \
        --results results/_cloud/results/results/arm2c2full2_0921_2136.jsonl

自动发现同名产物：<results 同目录> 下的 `.env` / `.arm.json` / `.log`，
`results/_cloud/logs/logs/monitor_<name>.csv`，题库与 core 表，以及
`results/_deepseek_audit/<name>.jsonl`（若已跑过检错）。

输出：`测试结果/2026-09-21-112-0.docx`（md 中间产物写系统临时目录，不落地）
"""
# 2026-10-01 去同名：num -> _num_or_zero（转 float，失败返回 0.0；原名 num 太泛）


from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from cli.deepseek_error_analyst import (  # noqa: E402
    _as_dict, _as_list, load_jsonl,
)
from tools.gen_test_report import safe  # noqa: E402
# 2026-10-09 拆分 批6-1/6-2：共享常量与工具搬入 `__common`；报告分节搬入 `__sections`。
from cli.test_report__common import (  # noqa: E402
    _num_or_zero, fmt, hhmmss, is_subgoal_failed, med, pct,
)
from cli.test_report__sections import (  # noqa: E402
    sec_conclusion, sec_infra, sec_overview, sec_perq_time, sec_reasoning_vs_calc,
    sec_result, sec_stage_error, sec_stage_time, sec_tools, sec_unmet,
)


# ================================================================
# 路径 / 可执行文件常量
# ================================================================
MK = r"C:\Users\35174\_mkdocx.py"
PY = r"D:\python\python.exe"
OUT_DIR_DEFAULT = os.path.join(ROOT, "测试结果")
TESTSEET_DEFAULT = os.path.join(ROOT, "题库", "official112_本地测试题库", "official112_full.jsonl")
CORE_DEFAULT = os.path.join(ROOT, "results", "_112_core_table.jsonl")


# ================================================================
# 伴生产物发现与开关解析（仅 build_test_report 使用；`local_attribution` 已搬 __common）
# ================================================================
def discover(results_path):
    """从 results 路径自动发现同名伴生产物。"""
    d = os.path.dirname(results_path)
    base = os.path.basename(results_path)
    stem = base[:-6] if base.endswith(".jsonl") else base
    out = {"env": None, "arm": None, "log": None, "monitor": None, "audit": None}
    for suf, key in ((".env", "env"), (".arm.json", "arm"), (".log", "log")):
        p = os.path.join(d, stem + suf)
        if os.path.exists(p):
            out[key] = p
    for cand in [
        os.path.join(ROOT, "results", "_cloud", "logs", "logs", "monitor_%s.csv" % stem),
        os.path.join(ROOT, "results", "_cloud", "logs", "monitor_%s.csv" % stem),
    ]:
        if os.path.exists(cand):
            out["monitor"] = cand
            break
    audit_dir = os.path.join(ROOT, "results", "_deepseek_audit")
    if os.path.isdir(audit_dir):
        # ★ 2026-09-25 修复：旧判据只要求文件名含 `stem.split("_")[0]`（对 run_* 就是含
        #   "run"，等于不过滤）并取体积最大者 ⇒ **必然命中上一轮**的检错文件。
        # ⇒ 先按**会话名**（去掉尾部的 `_MMDD_HHMM`）精确匹配，取不到才退回宽松匹配
        #   （main 里还会按记录的 `tag` 兜底过滤）。
        _run = re.sub(r"_\d{4}_\d{4}$", "", stem)
        cands = [f for f in os.listdir(audit_dir)
                 if f.endswith(".jsonl") and stem.split("_")[0] in f]
        exact = [f for f in cands if f.startswith(_run)]
        best = None
        for f in (exact or cands):
            p = os.path.join(audit_dir, f)
            if best is None or os.path.getsize(p) > os.path.getsize(best):
                best = p
        out["audit"] = best
    return out


def read_env(path):
    d = {}
    if not path or not os.path.exists(path):
        return d
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def parse_overrides(log_path):
    """从日志抓 `EvalEngine init: ... overrides={...}` —— 开关的**权威口径**。

    只看 .env 会误判：大量开关是 AgentConfig 字段，不写进环境变量。
    """
    if not log_path or not os.path.exists(log_path):
        return {}
    try:
        txt = io.open(log_path, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        return {}
    m = re.search(r"EvalEngine init:.*?overrides=(\{.*\})\s*$", txt, re.M)
    if not m:
        return {}
    try:
        import ast
        d = ast.literal_eval(m.group(1))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def agent_defaults():
    """读 AgentConfig 的字段默认值（用于不在 overrides 里的开关）。"""
    try:
        sys.path.insert(0, ROOT)
        from user_agent import AgentConfig
        c = AgentConfig()
        return {k: getattr(c, k) for k in dir(c) if not k.startswith("_")}
    except Exception:  # noqa: BLE001
        return {}


def make_judge():
    """只读借用官方判分器做等价性检验；失败则退化为字符串归一化。"""
    try:
        import run_eval
        f = run_eval.answers_match

        def j(a, b):
            try:
                return bool(f(a, b))
            except Exception:  # noqa: BLE001
                return False
        return j
    except Exception:  # noqa: BLE001
        def j(a, b):
            def n(x):
                return re.sub(r"[\s\\${}()\[\]]|boxed", "", str(x or "")).replace("，", ",").strip()
            return bool(n(a)) and n(a) == n(b)
        return j


# ★ 2026-09-30（截图 #10）：**四维仪表盘**的阶段定义。
#   用户原话：「最后的诊断要详细，要对**每个过程消耗的时间**诊断，
#              有耗时 / 结果 / 是否达标 三维 + 关注工具使用」。
#
#   为什么要**单开一张表**而不是扩充既有分表：
#     既有分表各自只答一个问题（耗时在四、错在哪在五、达标在六、工具在七），
#     用户要的是**把同一环节的四个问题放在一行**回答 —— 否则要翻四张表才能
#     拼出"2.7 子目标这一环节到底怎么样"。
#   实现纪律：本表**只做汇总**，每个单元格的数据源都写在下方注释里，
#     不新造判据（避免与既有分表出现两套口径 —— 本项目已踩过多次）。
_STAGE_DASHBOARD = [
    # (阶段键, 显示名, 达标判据说明, 达标信号取值函数名)
    ("1_classify", "① 题型领域识别", "分类结果非空", "classify"),
    ("2.6_pre_audit", "② Lean 前置理解", "verdict != fail", "preverify"),
    ("2.7_subgoal_main", "③ 子目标主链", "子目标未被判失败", "subgoal"),
    ("3_solve", "④ 求解生成", "产出 ≥1 个可用候选", "solve"),
    ("3.3_improve", "⑤ 无条件自改进", "有候选被改进", "self_improve"),
    ("3.6_audit_filter", "⑥ 候选审核闸门", "无 reject", "audit_gate"),
    ("4_verify", "⑦ 多票验证", "获得 ≥1 张正确票", "verify"),
    ("4.5_oracle", "⑧ Oracle 客观复核", "未判错", "oracle"),
    ("4.6_adv", "⑨ 对抗式验证", "未检出错误", "adv"),
    ("5.5_low_conf", "⑩ 低置信度复核", "未触发（已高置信）", "low_conf"),
    ("5_revise_or_fallback", "⑪ 修订/兜底", "未走兜底", "revise"),
]


def _dashboard_preagg(recs):
    # 预聚合：阶段耗时
    t_agg: dict = collections.defaultdict(list)
    # 预聚合：工具门面按阶段的调用数（`step` 里含阶段键的才算）
    tool_by_stage: dict = collections.defaultdict(collections.Counter)
    for r in recs:
        d = _as_dict(r.get("diag"))
        st = _as_dict(d.get("stage_timers"))
        for k, v in st.items():
            t_agg[k].append(_num_or_zero(v))
        g = _as_dict(d.get("tool_gateway"))
        for tk, tv in (_as_dict(g.get("by_tool")) or {}).items():
            # 门面的 step 一般写成目标阶段名；取不到就归到"未标注"
            tool_by_stage["*"][str(tk)] += int(_num_or_zero(tv))
    return t_agg, tool_by_stage


def _stage_dashboard_rows(recs):
    """汇总每个阶段的**四维**：耗时 / 结果 / 是否达标 / 工具使用。

    数据源（**全部复用既有 diag 字段，不新造判据**）：
      · 耗时     ← `diag.stage_timers[stage]`（同第四节的源）
      · 结果     ← 各阶段既有的结果埋点（下见每行 `raw`）
      · 是否达标 ← 由 `raw` 按该阶段的**既有**判据推出（判据写在 `_STAGE_DASHBOARD`）
      · 工具使用 ← `diag.tool_gateway.by_tool` 中与该阶段相关的工具调用数

    返回 `[(阶段键, 显示名, 耗时秒, 结果摘要, 达标判定, 工具摘要)]`。
    """
    n = len(recs) or 1
    t_agg, tool_by_stage = _dashboard_preagg(recs)

    # 各阶段的"结果"取值（尽量取既有的、信息量最大的字段）
    def _raw_for(stage, r):
        d = _as_dict(r.get("diag"))
        if stage == "1_classify":
            return str(r.get("domain") or "")
        if stage == "2.6_pre_audit":
            pv = _as_dict(d.get("preverify_trace"))
            return str(pv.get("verdict") or "")
        if stage == "2.7_subgoal_main":
            # ⚠ 真实键是 n_subgoals / dep_edges（**没有** n_failed）。
            #   原写法硬取 `n_failed` 恒得 0.0 ⇒ 报告里显示 "fail=0.0"，
            #   读者会以为"零失败"，实际是"该字段根本不存在"。
            _tr = _as_list(d.get("subgoal_trace"))
            _nf = sum(1 for _sg in _tr
                      if is_subgoal_failed(_as_dict(_sg).get("result")))
            return "子目标=%d 失败=%d" % (len(_tr), _nf)
        if stage == "3_solve":
            return "cands=%d" % len(_as_list(r.get("candidates")))
        if stage == "3.3_improve":
            return "improved=%s" % _num_or_zero(d.get("n_self_improved"))
        if stage == "3.6_audit_filter":
            ag = _as_list(d.get("audit_gate"))
            _vs = collections.Counter(str(_as_dict(x).get("verdict") or "") for x in ag)
            return "reject=%d accept=%d" % (_vs.get("reject", 0), _vs.get("accept", 0))
        if stage == "4_verify":
            vs = _as_list(d.get("verdicts"))
            _cv = sum(1 for x in vs if _num_or_zero(_as_dict(x).get("correct_votes")) > 0)
            return "有正确票=%d/%d" % (_cv, len(vs))
        if stage in ("4.5_oracle", "4.6_adv"):
            k = "oracle_review" if stage == "4.5_oracle" else "adversarial"
            v = _as_dict(d.get(k))
            return "found=%s" % (v.get("found") if v else "—")
        if stage == "5.5_low_conf":
            bc = _as_dict(d.get("best_cluster"))
            return "conf=%s" % (bc.get("confidence") if bc else "—")
        if stage == "5_revise_or_fallback":
            # ⚠ `r` 是 dict（records），不是对象 —— 必须用 r.get 而非 getattr。
            return "revise_round=%s" % _num_or_zero(
                (r.get("revise_round") if isinstance(r, dict) else None))
        return ""

    def _pass_for(stage, r):
        """是否达标（判据写在 `_STAGE_DASHBOARD` 注释里）。

        ★ 返回三态：`True`（达标）/ `False`（跑了但没达标）/ `None`（**没跑到**）。
        调用方按 `None` 剔出分母 —— 这是本节的口径红线（见 `_stage_reached`）。
        """
        d = _as_dict(r.get("diag"))
        # 先判"本题到底跑到这一阶段没有"：耗时 0 ⇒ 视为没跑到 ⇒ 不计入分母。
        # 例外：`1_classify` 这类每題必过且可能 0 秒的阶段，用其自身字段判（见下）。
        _t = _num_or_zero(_as_dict(d.get("stage_timers")).get(stage))
        if stage == "1_classify":
            return bool(str(r.get("domain") or "").strip()), "分类非空"
        if _t <= 0:
            return None, "未跑到（耗时 0）"
        if stage == "2.6_pre_audit":
            v = str(_as_dict(d.get("preverify_trace")).get("verdict") or "")
            if not v:
                # ⚠ 与"耗时 0"**不同**：这里耗时 >0（阶段跑了）但**没留下 verdict**
                #   ⇒ 是"跑了但没产出可比结论"（如预验证被跳过/降级）。
                #   既不计入"达标"也不计入"不达标"，单列出来让人看得见。
                return None, "跑了但无 verdict"
            return v != "fail", "verdict=%s" % v
        if stage == "2.7_subgoal_main":
            ss = _as_dict(d.get("subgoal_stats"))
            if not ss:
                return None, "未触发"
            # ★ 判据 = **所有子目标都没失败**（口径来自 agent.gap_analyzer，
            #   见本文件顶部 import 的 `is_subgoal_failed`）。
            #   ⚠ 原写法读 `ss["n_failed"]` —— 该键**不存在**（真实键是
            #     n_subgoals / dep_edges / avg_indegree / dep_free），
            #     恒取 0 ⇒ 恒判"100% 达标"，是个假达标。
            #   现改为遍历 `subgoal_trace` 的 result 逐个判 —— 这才是真信号。
            _tr = _as_list(d.get("subgoal_trace"))
            if not _tr:
                return None, "无子目标轨迹"
            _nf = sum(1 for _sg in _tr
                      if is_subgoal_failed(_as_dict(_sg).get("result")))
            return _nf == 0, "失败子目标 %d/%d" % (_nf, len(_tr))
        if stage == "3_solve":
            nc = len(_as_list(r.get("candidates")))
            return nc > 0, "候选 %d 个" % nc
        if stage == "3.6_audit_filter":
            ag = _as_list(d.get("audit_gate"))
            if not ag:
                return None, "未触发"
            nr = sum(1 for x in ag if str(_as_dict(x).get("verdict")) == "reject")
            return nr == 0, "reject=%d" % nr
        if stage == "4_verify":
            vs = _as_list(d.get("verdicts"))
            if not vs:
                return None, "未触发"
            cv = sum(_num_or_zero(_as_dict(x).get("correct_votes")) for x in vs)
            return cv > 0, "总正确票=%d" % cv
        return None, "—"

    out = []
    for key, disp, passdesc, _sig in _STAGE_DASHBOARD:
        tlist = t_agg.get(key) or []
        tsum = sum(tlist)
        tnz = sum(1 for x in tlist if x > 0)
        # 结果摘要：**只统计"跑到该阶段"的题**（耗时 >0），否则众数会被
        # "没跑到"的题主导 —— 实测 `3_solve` 会显示 `cands=0（83 题）`，
        # 而 83 题恰恰是**上游早退根本没进求解**的题，读起来像"83 题没产出候选"。
        _reached = []
        for _r in recs:
            _t = _num_or_zero(_as_dict(_as_dict(_r.get("diag")).get("stage_timers")).get(key))
            if key == "1_classify" or _t > 0:
                _reached.append(_r)
        raws = [_raw_for(key, r) for r in _reached]
        raws = [x for x in raws if x]
        raw_top = collections.Counter(raws).most_common(1)
        raw_txt = ("%s（%d 题）" % (raw_top[0][0], raw_top[0][1])
                   if raw_top else "—")
        # 达标统计
        oks = [_pass_for(key, r) for r in recs]
        ok_vals = [o for o, _ in oks if o is not None]
        if ok_vals:
            n_ok = sum(1 for o in ok_vals if o)
            pass_txt = "%d/%d（%s%%）" % (n_ok, len(ok_vals), fmt(pct(n_ok, len(ok_vals))))
        else:
            pass_txt = "未触发"
        # 工具使用：该阶段相关工具调用（当前门面 step 未按阶段细分，故给全局提示）
        tsum_txt = "—"
        if tool_by_stage.get("*"):
            s = sum(tool_by_stage["*"].values())
            tsum_txt = "门面 %d 次（全局）" % s
        out.append((key, disp, tsum, tnz, len(tlist), raw_txt, pass_txt,
                    passdesc, tsum_txt))
    return out


def _stage_reached(recs, stage) -> int:
    """★ 该阶段**实际跑到了**的题数（判定口径的分母）。

    ★★ 为什么必须单独算分母（本项目反复吃亏的口径陷阱）：
      `stage_timers` 里**每个阶段键在所有题上都存在**（含 0 秒），
      若直接拿 `len(recs)` 当分母，那么"因为上游没产出候选而根本没进 4_verify"
      的题，会被算成"4_verify 没达标" —— 这是把**没跑**当成**跑失败**，
      与"没跑≠没问题"是同一类假阴性，只不过方向相反。
      实测（official112，run_2026-09-23c）：`3_solve` 只在 29 题上有候选，
      其余 83 题是上游早退；若按 112 当分母会得出"求解达标率 25.9%"，
      而真实含义是"**能跑到求解的 29 题里，29 题都产出了候选**"。

    判据：该题在该阶段**耗时 > 0** ⇒ 认为跑到了。
      ⚠ 有意的窄口径：0 秒也可能是"跑了但极快"。但这在本项目不成立 ——
      各阶段最小耗时也在秒级（LLM 调用），实测 0 秒题与"无候选/无记录"题
      在数据上完全重合。若将来出现亚秒级阶段，此处需改为读显式到达标记。
    """
    n = 0
    for r in recs:
        try:
            t = _as_dict(_as_dict(r.get("diag")).get("stage_timers")).get(stage)
            if _num_or_zero(t) > 0:
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def sec_stage_dashboard(recs):
    """★ 2026-09-30（截图 #10）：**四维阶段仪表盘**（耗时 / 结果 / 达标 / 工具）。

    用户原话：「最后的诊断要详细，要对每个过程消耗的时间诊断
              —— 耗时 / 结果 / 是否达标 三维 + 关注工具使用」。
    """
    L = ["## 三'、分阶段四维体检（耗时 / 结果 / 是否达标 / 工具使用）", ""]
    if not recs:
        L.append("（无数据）")
        L.append("")
        return L
    L.append("本表把同一环节的四个问题**放在一行**回答，避免翻四张表才能拼出结论。")
    L.append("")
    L.append("> ⚠ **达标率的分母 = 该阶段实际跑到的题数**（耗时 >0），"
             "不是总题数 —— 否则「上游早退、没进到这一阶段」会被误算成"
             "「本阶段没达标」，那是把**没跑**当成**跑失败**。")
    L.append("")
    L.append("| 阶段 | 耗时(累计/中位) | 跑到题数 | 结果（众数） | **是否达标** | 达标判据 | 工具使用 |")
    L.append("|---|---|---|---|---|---|---|")
    rows = _stage_dashboard_rows(recs)
    for (key, disp, tsum, tnz, ntot, raw_txt, pass_txt, passdesc,
         tool_txt) in rows:
        # ⚠ 必须用 `_as_dict` 包一层：`stage_timers` 在脏数据里可能是字符串
        #   （`.get(k, {})` 只在**键缺失**时返回默认值，键存在但值非 dict 时
        #    会原样返回 ⇒ 直接 `.get(key)` 崩 AttributeError）。
        _tl = [_num_or_zero(_as_dict(_as_dict(r.get("diag")).get("stage_timers")).get(key))
               for r in recs]
        _med = med(_tl) if _tl else 0
        L.append("| %s（`%s`） | %s / %ss | %d/%d | %s | **%s** | %s | %s |" % (
            disp, safe(key, 24), hhmmss(tsum), fmt(_med, 0), tnz, ntot,
            raw_txt, pass_txt, passdesc, tool_txt))
    L.append("")
    # ── 自动判读：把"耗时高但达标率低"的环节挑出来（这才是真问题）
    _bad = []
    for (key, disp, tsum, tnz, ntot, _r, pass_txt, _pd, _t) in rows:
        try:
            if "/" in pass_txt:
                _a, _b = pass_txt.split("（")[0].split("/")
                _rate = float(_a) / float(_b)
                if _rate < 0.5 and tsum > 0:
                    _bad.append((disp, key, tsum, pass_txt))
        except Exception:  # noqa: BLE001
            continue
    if _bad:
        _bad.sort(key=lambda x: -x[2])
        L.append("**★ 需优先关注（耗时高且达标率 <50%）**：")
        L.append("")
        for disp, key, tsum, ptxt in _bad:
            L.append("- **%s**（`%s`）：累计耗时 %s，达标率 **%s** —— "
                     "时间花在这里却没买到效果，是最该优化的环节。"
                     % (disp, key, hhmmss(tsum), ptxt))
        L.append("")
    else:
        L.append("> 未发现「耗时高且达标率低」的环节（或本轮数据不足）。")
        L.append("")
    L.append("> **判读纪律**：「未触发」与「触发了但没达标」**必须分开看** ——"
             "前者要查开关/门控可达性，后者才是该环节本身的问题。"
             "把二者混为一谈会让优化改错地方（本项目已多次踩坑）。")
    L.append("")
    return L


# ================================================================
def build_test_report(args):
    results = args.results
    if not os.path.isabs(results):
        results = os.path.join(ROOT, results)
    recs = load_jsonl(results)
    if not recs:
        raise SystemExit("结果文件为空：%s" % results)
    disc = discover(results)
    audit = load_jsonl(args.audit or disc["audit"] or "")
    # ★ 2026-09-25 修复（第二道防线）：无论检错文件是怎么选出来的，**跨轮记录一律剔除**。
    #   判据优先级：① 记录的 `tag` 必须等于本轮会话名（analyst/checker 都会写 tag）；
    #   ② 没有 tag 时退回「题号必须出现在本轮结果里」。
    #   ⚠ 只用题号交集**不够**：相邻轮的题号区间常常重叠（09-22 是 000–047、09-23c 是 000–111），
    #     实测 run_2026-09-22 的 37 条可以整批通过题号过滤。
    _audit_n = len(audit)
    _run_name = args.name or re.sub(r"_\d{4}_\d{4}$", "", os.path.basename(results).replace(".jsonl", ""))
    _known_runs = {str(_run_name), os.path.basename(results).replace(".jsonl", "")}
    _has_tag = [a for a in audit if str(a.get("tag") or "").strip()]
    if _has_tag:
        audit = [a for a in audit if str(a.get("tag")) in _known_runs]
    else:
        _rec_ids = {str(r.get("id")) for r in recs}
        audit = [a for a in audit if str(a.get("id")) in _rec_ids]
    if _audit_n and len(audit) != _audit_n:
        print("[warn] 检错文件含跨轮记录：%d 条中剔除 %d 条（tag/题号不属于本轮 %s）"
              % (_audit_n, _audit_n - len(audit), _run_name))
    if _audit_n and not audit:
        print("[warn] 检错文件与本轮无任何交集，已全部剔除 ⇒ 报告改用本地启发式归因")
    core = load_jsonl(args.core or CORE_DEFAULT)
    env = read_env(args.env or disc["env"])
    arm = {}
    ap = args.arm_json or disc["arm"]
    if ap and os.path.exists(ap):
        try:
            arm = json.load(io.open(ap, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            arm = {}
    judge = make_judge()
    ov = parse_overrides(disc["log"])
    defs = agent_defaults()

    stem = os.path.basename(results)
    stem = stem[:-6] if stem.endswith(".jsonl") else stem
    run = args.name or re.sub(r"_\d{4}_\d{4}$", "", stem)
    # 结束时间
    ended = "—"
    try:
        ended = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(results)))
    except Exception:  # noqa: BLE001
        pass
    meta = {"run": run, "arm": arm, "ended_at": ended}

    n = len(recs)
    ok = sum(1 for r in recs if r.get("correct"))

    # ★★ 日期口径（用户 2026-09-22 确认）：**取该轮的「起始日」**，不取结束日。
    #   优先级：显式 `--date` > `arm.json.started_at` > 会话名里的 `_MMDD_HHMM`
    #           > 结果文件 mtime（⚠ 仅兜底，且它其实是**结束/落地时刻**，需告警）
    #   注意：旧实现的兜底直接取 mtime ⇒ 与"起始日"口径相反（本轮会得 09-22 而非 09-21）。
    date, date_src = None, ""
    if args.date:
        date, date_src = args.date, "--date 显式指定"
    if not date and arm.get("started_at"):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(arm["started_at"]))
        if m:
            date, date_src = m.group(0), "arm.json.started_at"
    if not date:
        m = re.search(r"_(\d{2})(\d{2})_\d{4}$", stem)
        if m:
            _y = int(time.strftime("%Y"))
            _mo, _d = int(m.group(1)), int(m.group(2))
            # 跨年护栏：若解析出的月日比今天"晚了 6 个月以上"，判定为上一年的轮次
            _t = time.localtime()
            if (_mo, _d) > (int(time.strftime("%m")) + 6, int(time.strftime("%d"))):
                _y -= 1
            date, date_src = "%04d-%02d-%02d" % (_y, _mo, _d), "会话名（起始）"
    if not date:
        date = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(results)))
        date_src = "结果文件 mtime（⚠ 实为结束/落地时刻）"
    if args.date:
        date_src = "--date 显式指定"
    print("[日期] %s  来源：%s" % (date, date_src))
    if args.suffix:
        fname = "%s-%s-%d题.docx" % (date, args.suffix, n)
    else:
        fname = "%s-%d-%d.docx" % (date, n, ok)

    files = {"results": results, "log": disc["log"], "monitor": disc["monitor"],
             "audit": disc["audit"], "testset": TESTSEET_DEFAULT,
             "date_src": date_src, "fname": fname}
    amap = {str(a.get("id")): a for a in audit}

    L, vc = sec_overview(recs, meta, files, env)
    L += sec_result(recs, core)
    L += sec_perq_time(recs)
    # ★ 2026-09-30（截图 #10）：四维仪表盘插在"逐题耗时"与"分阶段耗时"之间 ——
    #   先给**汇总视角**（一行看一个环节的全貌），再给**分项明细**。
    L += sec_stage_dashboard(recs)
    L += sec_stage_time(recs)
    se, by_stage, by_type, _rows = sec_stage_error(recs, audit, judge)
    L += se
    L += sec_unmet(recs, vc)
    L += sec_tools(recs, env, disc["log"], ov, defs)
    L += sec_reasoning_vs_calc(recs, judge, amap)
    L += sec_infra(recs, disc["monitor"], disc["log"])
    L += sec_conclusion(recs, vc, by_type, amap)

    md = "\n".join(L)
    out_dir = args.out_dir or OUT_DIR_DEFAULT
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(ROOT, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_docx = os.path.join(out_dir, fname)

    tmpd = tempfile.mkdtemp(prefix="report_")
    tmp_md = os.path.join(tmpd, fname[:-5] + ".md")
    with io.open(tmp_md, "w", encoding="utf-8") as fh:
        fh.write(md)
    print("[md] %s（%d 字符，临时）" % (tmp_md, len(md)))
    r = subprocess.run([PY, MK, tmp_md, out_docx, "%s 评测报告" % run],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-2200:] if r.stdout else "")
    if r.returncode != 0:
        print(r.stderr[-1500:])
        raise SystemExit("docx 构建失败")
    print("[docx] %s（%d bytes）" % (out_docx, os.path.getsize(out_docx)))
    return out_docx


def main():
    ap = argparse.ArgumentParser(description="一次测试 → 一个 Word 文档")
    ap.add_argument("--results", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--name", default=None, help="会话名（默认从文件名推断）")
    ap.add_argument("--date", default=None, help="文件名日期 YYYY-MM-DD（默认取 arm.json 起始日）")
    ap.add_argument("--suffix", default=None,
                    help="文件名后缀标签（如 `进度巡检`），用于**运行中**巡检报告与终轮报告区分；"
                         "给定后文件名变为 `日期-<suffix>-N题.docx`")
    ap.add_argument("--audit", default=None, help="DeepSeek 检错 jsonl（默认自动发现）")
    ap.add_argument("--core", default=None)
    ap.add_argument("--env", default=None)
    ap.add_argument("--arm-json", default=None)
    a = ap.parse_args()
    build_test_report(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
