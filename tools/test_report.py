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
    D:/python/python.exe tools/test_report.py \
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
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from deepseek_error_analyst import (  # noqa: E402
    _as_dict, _as_list, classify_validity, load_jsonl, PLACEHOLDERS,
)
from gen_test_report import safe  # noqa: E402

# ★ 2026-09-30（截图 #10）：子目标失败判据的**唯一来源** = `agent.gap_analyzer`。
#   本文件的四维仪表盘需要判断"子目标主链是否达标"，必须与
#   `tools/analyze_errors.py` / `gap_analyzer` 同口径 —— 否则同一事实两套判据
#   （本项目已踩过：曾内联一套「result 为空 or 以 '[子目标' 开头」，
#    漏了「未产出有效结论」「仍为空转占位」两条，统计偏小）。
#   导入失败时降级为最小实现（**不抛异常**，报告仍能出）。
try:  # noqa: E402
    from agent.gap_analyzer import is_subgoal_failed as _is_sg_failed
except Exception:  # noqa: BLE001
    def _is_sg_failed(result_text):
        """降级兜底：与 gap_analyzer 同口径的**最小**实现。"""
        t = str(result_text or "")
        return (not t.strip()) or t.startswith("[子目标")


def is_subgoal_failed(result_text):
    """模块级薄包装（保持调用点简洁，同时把降级逻辑收在一处）。"""
    try:
        return bool(_is_sg_failed(result_text))
    except Exception:  # noqa: BLE001
        return False


MK = r"C:\Users\35174\_mkdocx.py"
PY = r"D:\python\python.exe"
OUT_DIR_DEFAULT = os.path.join(ROOT, "测试结果")
TESTSEET_DEFAULT = os.path.join(ROOT, "题库", "official112_本地测试题库", "official112_full.jsonl")
CORE_DEFAULT = os.path.join(ROOT, "results", "_112_core_table.jsonl")

# 阶段显示顺序（未列出的按字母序追加）
# ★ 2026-10-02 移除 `0_paper_pacer` / `1_classify` / `2.5_difficulty`（阶段已删）；此前报告仍含之。
STAGE_ORDER_test_report = [
    # ★ 2026-10-02 移除 `2.65_calc_prewarm`（calc 板块删除时漏网残留）；此前报告仍含之。
    "2.6_pre_audit",
    "2.7_subgoal_main", "3_solve", "3.2_complete", "3.3_improve", "3.4_collab",
    "3.5_subgoal_sup", "3.6_audit_filter", "4_verify", "4.5_oracle", "4.6_adv",
    "5.5_low_conf", "5_revise_or_fallback",
]

# 机制埋点普查表：键 → （期望触发强度，说明）
MECH_EXPECT = [
    ("subgoal_stats", "必", "子目标统计"),
    ("subgoal_trace", "必", "子目标轨迹"),
    ("exhaust_diag", "必", "穷尽性检查触发记录"),
    ("value_attack", "常", "数值攻击证伪"),
    ("leansearch", "必", "Lean 定理检索"),
    ("audit_gate", "必", "候选审核闸门"),
    ("preverify_trace", "常", "预验证轨迹"),
    ("lean_gate", "必", "Lean 候选闸门"),
    ("pick_diag", "必", "选答诊断"),
    ("blueprint_nodes", "必", "蓝图节点数"),
    ("formal_spec", "常", "形式化规格"),
    ("lemma_repo", "条件", "引理积累（仅数论域开）"),
    ("symbolic_solve_events", "条件", "符号求解（开关默认关）"),
    ("numericize_events", "条件", "数值化改写"),
    ("expression_eval_events", "条件", "表达式求值"),
    ("objective_check_events", "条件", "客观复核"),
    ("toolcall_text_detected", "异常", "工具调用被文本通道吞掉（>0 即异常）"),
    ("dag_review", "常", "DAG 评审"),
    ("skeleton_review_events", "常", "骨架评审"),
    ("revise_events", "必", "重解事件"),
    ("answer_form_events", "常", "答案形态闸门"),
    ("oracle_review_events", "常", "AnswerOracle 复核"),
    ("adversarial_events", "条件", "对抗检查"),
    ("subgoal_replan_needed_events", "条件", "子目标重规划"),
    ("symbolic_crosscheck_events", "条件", "符号交叉校验"),
    ("lean_feedback_revise_events", "条件", "Lean 反馈重解"),
    ("final_postprocess_change_events", "异常", "终答被后处理改写（>0 需查）"),
    ("subgoal_recover_events", "条件", "子目标恢复"),
]

TOOL_SWITCHES = [
    ("enable_web_search", "联网检索"),
    ("use_leansearch", "LeanSearch 定理检索"),
    ("use_lemma_accumulation", "引理积累"),
    ("use_proof_channel", "证明通道"),
    ("use_scoring", "打分"),
    ("enable_dag_replan", "DAG 重规划"),
    ("enable_skeleton_review", "骨架评审"),
    ("blueprint_or_expand_all", "蓝图全展开"),
    ("dag_replan_gate", "DAG 重规划门控"),
    ("symbolic_solve_enabled", "符号求解"),
    ("enable_numeric_lean_verify", "数值型 Lean 验证"),
    ("verifier_deep_final_enabled", "深度终审"),
    ("verifier_diversify_enabled", "验证多样化"),
    ("by_enable_fast_path", "快路径"),
]

# 上限类（撞顶才构成能力削减；须同时看 param_usage 的 capped 与 exact）
TOOL_LIMITS = [
    ("max_answer_tokens", "单次回答 token 上限"),
    ("max_total_calls", "单题调用次数上限（已确认纯记账、不阻断）"),
    ("max_revise_rounds", "重解轮数上限"),
    ("preverify_max_rounds", "预验证轮数上限"),
    ("leansearch_top_k", "检索返回条数"),
    ("max_time_per_question", "单题时间上限"),
    ("max_workers", "并发"),
]


# ================================================================
# 工具
# ================================================================
def _num_or_zero(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


def med(xs):
    return statistics.median(xs) if xs else 0.0


def fmt(v, nd=1):
    try:
        return ("%%.%df" % nd) % float(v)
    except (TypeError, ValueError):
        return str(v)


def hhmmss(sec):
    sec = int(_num_or_zero(sec))
    return "%d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


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


def local_attribution(rec, judge):
    """本地启发式归因（不依赖 DeepSeek）：返回 (环节, 类型, 依据)。"""
    diag = _as_dict(rec.get("diag"))
    gold = rec.get("gold")
    pred = rec.get("predicted")
    if str(pred or "").strip() in PLACEHOLDERS:
        return ("—", "无效数据", "落盘占位符，未产出真实解答")
    cands = _as_list(rec.get("candidates"))
    picked = _as_dict(diag.get("pick_diag")).get("picked")
    pool_hit = any(judge(c.get("answer") if isinstance(c, dict) else c, gold) for c in cands)
    if not pool_hit:
        st = "3_solve"
        sig = _as_dict(diag.get("blueprint_merge")) or diag.get("blueprint_merge")
        if sig:
            st = "2.7_subgoal_main"
        return (st, "求解失败", "候选池内无与 gold 等价的答案")
    if picked and judge(picked, gold) and not judge(pred, gold):
        return ("终答落定", "终答改写", "pick_diag 已选对，predicted 被改写")
    return ("选答", "选答失败", "候选池有正解但未被选中")


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


# ================================================================
# 各章
# ================================================================
def sec_overview(recs, meta, files, env):
    L = ["# %s 评测报告" % meta["run"], ""]
    L.append("生成时间：%s ｜ 报告口径：一次测试一个文档（用户 2026-09-22 确立）"
             % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("")

    L.append("## 一、测试的具体数据")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    arm = meta.get("arm") or {}
    rows = [
        ("会话名", meta["run"]),
        ("起始时间", arm.get("started_at") or "—"),
        ("结束时间", meta.get("ended_at") or "—"),
        ("实验臂", str(arm.get("arm") or "—")),
        ("并发", str(arm.get("concurrency") or "—")),
        ("题单", str(arm.get("test_file") or os.path.basename(files.get("testset") or ""))),
        ("题目数", str(len(recs))),
        ("报告文件名", "%s（日期口径：起始日；来源 %s）"
         % (files.get("fname") or "—", files.get("date_src") or "—")),
        ("override", json.dumps(arm.get("overrides") or {}, ensure_ascii=False) or "{}"),
        ("LLM 模型", env.get("LLM_MODEL") or "—"),
        ("LLM_TIMEOUT", env.get("LLM_TIMEOUT") or "—"),
        ("结果文件", os.path.basename(files["results"])),
        ("日志", os.path.basename(files["log"]) if files.get("log") else "—"),
        ("监控采样", os.path.basename(files["monitor"]) if files.get("monitor") else "—"),
        ("检错结果", os.path.basename(files["audit"]) if files.get("audit") else "未跑"),
    ]
    for k, v in rows:
        L.append("| %s | %s |" % (k, safe(v, 160)))
    L.append("")

    # 有效性闸门
    vc = collections.Counter(classify_validity(r)[0] for r in recs)
    n_ok = len(recs)
    n_clean = vc.get("clean", 0)
    L.append("### 有效性闸门（先判这一项，否则后面的数字不能看）")
    L.append("")
    L.append("判定口径：占位符或缺 trace ⇒ 不可用；LLM 失败步占比 ≥50% ⇒ 无效；"
             "≥2% ⇒ 退化（结论需打折）；<2% ⇒ 干净。")
    L.append("")
    L.append("| 状态 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k in ("clean", "degraded", "invalid", "unknown"):
        if vc.get(k):
            L.append("| %s | %d | %s%% |" % (k, vc[k], fmt(pct(vc[k], n_ok))))
    L.append("")
    if vc.get("invalid", 0) or vc.get("unknown", 0):
        L.append("> ⚠ **本轮存在 %d 题无效 / %d 题无法判定**：正确率读数受基础设施影响，"
                 "不得直接当作模型能力结论。" % (vc.get("invalid", 0), vc.get("unknown", 0)))
        L.append("> 可用样本数为 **%d 题**（干净 + 退化）。" % (n_clean + vc.get("degraded", 0)))
        L.append("")
    return L, vc


def sec_result(recs, core):
    n = len(recs)
    ok = sum(1 for r in recs if r.get("correct"))
    L = ["## 二、总体结果", ""]
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append("| 完成题数 | %d |" % n)
    L.append("| 正确题数 | %d |" % ok)
    L.append("| 正确率 | %s%% |" % fmt(pct(ok, n), 2))
    ec = collections.Counter(str(r.get("error_class") or ("正确" if r.get("correct") else "未标注"))
                             for r in recs)
    L.append("| 错误分类 | %s |" % safe("、".join("%s %d" % (k, v) for k, v in ec.most_common()), 300))
    if core:
        cm = {str(r.get("id")): r for r in core}
        inter = [r for r in recs if str(r.get("id")) in cm]
        if inter:
            won = sum(1 for r in inter if r.get("correct") and not cm[str(r.get("id"))].get("correct"))
            lost = sum(1 for r in inter if not r.get("correct") and cm[str(r.get("id"))].get("correct"))
            L.append("| 与 core 表配对（同题 %d） | 赢 %d / 输 %d / net %d |" % (len(inter), won, lost, won - lost))
    L.append("")
    return L


def sec_perq_time(recs):
    L = ["## 三、每题消耗的时间", ""]
    el = [_num_or_zero(r.get("elapsed_sec")) for r in recs]
    buckets = {"<450s": 0, "450–700s": 0, ">700s": 0}
    for r in recs:
        e = _num_or_zero(r.get("elapsed_sec"))
        if e < 450:
            buckets["<450s"] += 1
        elif e <= 700:
            buckets["450–700s"] += 1
        else:
            buckets[">700s"] += 1
    ok_b = collections.Counter()
    for r in recs:
        if r.get("correct"):
            e = _num_or_zero(r.get("elapsed_sec"))
            ok_b["<450s" if e < 450 else ("450–700s" if e <= 700 else ">700s")] += 1
    L.append("总计 %s ｜ 单题均值 %ss ｜ 中位 %ss ｜ 最长 %ss"
             % (hhmmss(sum(el)), fmt(sum(el) / len(el) if el else 0, 0),
                fmt(med(el), 0), fmt(max(el) if el else 0, 0)))
    L.append("")
    L.append("| 分时桶 | 题数 | 其中正确 | 正确率 |")
    L.append("|---|---|---|---|")
    for k in ("<450s", "450–700s", ">700s"):
        L.append("| %s | %d | %d | %s%% |" % (k, buckets[k], ok_b[k], fmt(pct(ok_b[k], buckets[k]))))
    L.append("")
    L.append("| 题号 | 耗时 | 头号阶段 | 该阶段占比 | 判定 | 候选数 |")
    L.append("|---|---|---|---|---|---|")
    for r in recs:
        st = _as_dict(r.get("diag")).get("stage_timers")
        top, tp = "—", 0.0
        if isinstance(st, dict) and st:
            k = max(st, key=lambda x: _num_or_zero(st[x]))
            top = k
            tp = pct(_num_or_zero(st[k]), sum(_num_or_zero(v) for v in st.values()))
        L.append("| %s | %s | %s | %s%% | %s | %d |" % (
            safe(r.get("id"), 40), hhmmss(r.get("elapsed_sec")), safe(top, 28),
            fmt(tp), "正确" if r.get("correct") else "错误",
            len(_as_list(r.get("candidates")))))
    L.append("")
    L.append("> 分时桶口径沿用 2026-09 的实测结论：<450s 桶正确率最高，>700s 桶基本为 0，"
             "说明单纯延长求解时间没有收益。")
    L.append("")
    return L


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


def sec_stage_time(recs):
    L = ["## 四、各环节消耗的时间", ""]
    agg = collections.defaultdict(list)
    for r in recs:
        st = _as_dict(r.get("diag")).get("stage_timers")
        if isinstance(st, dict):
            for k, v in st.items():
                agg[k].append(_num_or_zero(v))
    if not agg:
        L.append("（本轮 diag 无 stage_timers，无法统计）")
        L.append("")
        return L
    total = sum(sum(v) for v in agg.values())
    keys = [k for k in STAGE_ORDER_test_report if k in agg] + [k for k in sorted(agg) if k not in STAGE_ORDER_test_report]
    L.append("| 阶段 | 累计 | 占比 | 中位 | 最大 | 非零题数 |")
    L.append("|---|---|---|---|---|---|")
    for k in keys:
        v = agg[k]
        nz = sum(1 for x in v if x > 0)
        L.append("| %s | %s | %s%% | %ss | %ss | %d/%d |" % (
            safe(k, 30), hhmmss(sum(v)), fmt(pct(sum(v), total)), fmt(med(v), 0),
            fmt(max(v), 0), nz, len(v)))
    L.append("")
    top = max(keys, key=lambda k: sum(agg[k]))
    zero = [k for k in keys if sum(agg[k]) == 0]
    L.append("- 头号阶段：**%s**（占比 %s%%）。" % (safe(top, 30), fmt(pct(sum(agg[top]), total))))
    if zero:
        L.append("- 全程零耗时阶段：%s（要么未被触发，要么被早退跳过）。" % safe("、".join(zero), 200))
    L.append("")
    return L


def sec_stage_error(recs, audit, judge):
    L = ["## 五、各环节哪里错了", ""]
    amap = {}
    for a in audit:
        amap[str(a.get("id"))] = a
    rows = []
    by_stage = collections.Counter()
    by_type = collections.Counter()
    src_tag = "DeepSeek 检错" if amap else "本地启发式"
    for r in recs:
        if r.get("correct"):
            continue
        rid = str(r.get("id"))
        a = amap.get(rid)
        if a:
            an = _as_dict(a.get("analysis"))
            st = str(an.get("error_stage") or "—")
            ty = str(an.get("error_type") or "—")
            note = str(an.get("root_cause") or "")
            gic = an.get("gold_in_candidates")
        else:
            st, ty, note = local_attribution(r, judge)
            gic = "—"
        by_stage[st] += 1
        by_type[ty] += 1
        rows.append((rid, st, ty, gic, note))
    L.append("归因来源：**%s**（%d 道错题；DeepSeek 覆盖 %d 道，其余用本地启发式补齐）。"
             % (src_tag, len(rows), len(amap)))
    L.append("")
    L.append("### 按错误类型")
    L.append("")
    L.append("| 类型 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k, v in by_type.most_common():
        L.append("| %s | %d | %s%% |" % (safe(k, 30), v, fmt(pct(v, len(rows)))))
    L.append("")
    L.append("### 按错误环节")
    L.append("")
    L.append("| 环节 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k, v in by_stage.most_common():
        L.append("| %s | %d | %s%% |" % (safe(k, 40), v, fmt(pct(v, len(rows)))))
    L.append("")
    L.append("### 逐题归因")
    L.append("")
    L.append("| 题号 | 环节 | 类型 | gold 在候选池 | 根因（摘要） |")
    L.append("|---|---|---|---|---|")
    for rid, st, ty, gic, note in rows:
        L.append("| %s | %s | %s | %s | %s |" % (
            safe(rid, 36), safe(st, 34), safe(ty, 20), safe(gic, 12), safe(note, 200)))
    L.append("")
    return L, by_stage, by_type, rows


def sec_unmet(recs, vc):
    L = ["## 六、哪里没有达到预期目标", ""]
    n = len(recs)
    valid = [r for r in recs if classify_validity(r)[0] in ("clean", "degraded")]
    n_invalid = n - len(valid)
    L.append("### 机制触发普查（分母 = 有效题数 %d，而非总题数）" % len(valid))
    L.append("")
    if n_invalid:
        L.append("> ⚠ 本轮 **%d 题无效**（占位符 / 配额耗尽）。机制埋点的非空数天然不会超过有效题数，"
                 "因此本表的判读基准取「有效题数」，否则会得出「机制没触发」的假结论。"
                 % n_invalid)
        L.append("")
    L.append("| 机制 | 期望 | 全轮存在 | 有效题中非空 | 非空率 | 结论 | 说明 |")
    L.append("|---|---|---|---|---|---|---|")
    silent = []
    over = []
    for key, exp, desc in MECH_EXPECT:
        exist = 0
        for r in recs:
            if key in _as_dict(r.get("diag")):
                exist += 1
        nonempty = sum(1 for r in valid if _as_dict(r.get("diag")).get(key))
        ratio = pct(nonempty, len(valid)) if valid else 0.0
        if exp == "异常":
            verdict = "命中 %d 题" % nonempty if nonempty else "正常"
            if nonempty:
                over.append((key, nonempty, desc))
        elif exp == "必" and valid and ratio < 20.0:
            verdict = "★疑似未达预期"
            silent.append((key, nonempty, len(valid), desc))
        else:
            verdict = "—"
        L.append("| %s | %s | %d | %d | %s%% | %s | %s |" % (
            safe(key, 34), exp, exist, nonempty, fmt(ratio), verdict, safe(desc, 60)))
    L.append("")
    if silent:
        L.append("**疑似未达预期（必触发项在有效题中命中率 <20%%）**：")
        L.append("")
        for k, ne, nv, desc in silent:
            L.append("- `%s`（%s）：有效题 %d 题中仅 %d 题非空 —— 需逐项确认是「开关关着」"
                     "「门控不可达」还是「真的没触发」。" % (k, safe(desc, 40), nv, ne))
        L.append("")
    if silent:
        L.append("**疑似未达预期（必触发项却几乎为空）**：")
        L.append("")
        for k, ne, ex, desc in silent:
            L.append("- `%s`（%s）：存在 %d 题、非空仅 %d 题 —— 需逐项确认是「开关关着」"
                     "「门控不可达」还是「真的没触发」。" % (k, safe(desc, 40), ex, ne))
        L.append("")
    if over:
        L.append("**异常信号命中（>0 即需查）**：")
        L.append("")
        for k, ne, desc in over:
            L.append("- `%s`（%s）：%d 题命中。" % (k, safe(desc, 40), ne))
        L.append("")

    # 闸门有效性
    lg = collections.Counter()
    ag = collections.Counter()
    for r in recs:
        d = _as_dict(r.get("diag"))
        for g in _as_list(d.get("lean_gate")):
            if isinstance(g, dict):
                lg[str(g.get("verdict"))] += 1
        for g in _as_list(d.get("audit_gate")):
            if isinstance(g, dict):
                if g.get("step") == "candidate_audit":
                    ag[str(g.get("verdict"))] += 1
    L.append("### 闸门有效性")
    L.append("")
    L.append("| 闸门 | 判定分布 | 判读 |")
    L.append("|---|---|---|")
    tot = sum(lg.values())
    unk = lg.get("unknown", 0)
    L.append("| LeanGate | %s | %s |" % (
        safe("、".join("%s %d" % (k, v) for k, v in lg.most_common()), 120),
        ("★ unknown 占 %s%% ⇒ 该闸门基本没有判别力" % fmt(pct(unk, tot))) if tot and pct(unk, tot) > 80 else "有区分度"))
    tot2 = sum(ag.values())
    L.append("| AuditGate | %s | %s |" % (
        safe("、".join("%s %d" % (k, v) for k, v in ag.most_common()), 120),
        ("★ 恒 unknown ⇒ 对解答题结构性零输出" if tot2 and ag.get("unknown", 0) == tot2 else "有区分度")))
    L.append("")
    return L


def sec_tools(recs, env, log_path, ov, defs):
    L = ["## 七、哪些工具没有使用起来", ""]
    n = len(recs)
    tt = sum(len(_as_list(_as_dict(r.get("diag")).get("toolcall_text_detected"))) for r in recs)
    ls_calls = 0
    ls_capped = 0
    for r in recs:
        ls = _as_dict(_as_dict(r.get("diag")).get("leansearch"))
        ls_calls += int(_num_or_zero(ls.get("calls")))
        if ls.get("top_k_capped") is True:
            ls_capped += 1
    L.append("### 通道使用量")
    L.append("")
    L.append("| 通道 | 观测值 | 判读 |")
    L.append("|---|---|---|")
    L.append("| 工具调用被文本通道吞掉 | %d 条 | %s |" % (
        tt, "★ 存在被吞掉的调用（写了 <tool_call> 但原生 tool_calls 为空，未执行未回填）" if tt else "正常"))
    L.append("| LeanSearch 检索 | %d 次 | %s |" % (
        ls_calls, "★ 未调用" if ls_calls == 0 else "已调用"))
    L.append("| LeanSearch top_k 饱和题数 | %d / %d | %s |" % (
        ls_capped, n, "★ 命中数恒等于 top_k，检索未被有效利用" if ls_capped > 0.5 * n else "—"))
    L.append("")
    # ★ 2026-09-30（截图 #10）：**统一工具门面遥测**。
    #   用户诉求「调用工具的方法有没有写成规范性的类函数，需要 Lean 检测时
    #   直接调用，适配各阶段」⇒ 落地为 `agent/tool_gateway.py`。
    #   本表回答的是**另一个问题**：走门面的调用，**失败原因分布是什么**。
    #   口径红线（必须写在报告里，否则读者会把全零读成"没调用工具"）：
    #     本表只统计走 ToolGateway 的调用；既有调用点尚未全部迁移。
    gw_total = 0
    gw_by_tool: dict = {}
    gw_by_reason: dict = {}
    for r in recs:
        g = _as_dict(_as_dict(r.get("diag")).get("tool_gateway"))
        gw_total += int(_num_or_zero(g.get("total")))
        for k, v in (_as_dict(g.get("by_tool")) or {}).items():
            gw_by_tool[k] = gw_by_tool.get(k, 0) + int(_num_or_zero(v))
        for k, v in (_as_dict(g.get("by_reason")) or {}).items():
            gw_by_reason[k] = gw_by_reason.get(k, 0) + int(_num_or_zero(v))
    L.append("### 统一工具门面遥测（ToolGateway，2026-09-30 截图 #10）")
    L.append("")
    if gw_total == 0:
        L.append("本轮**没有调用走统一门面**（`agent/tool_gateway.py`）。")
        L.append("")
        L.append("> ⚠ 这**不等于**「本轮没调用工具」—— 既有调用点"
                 "（orchestrator 自建 LeanGate / answer_falsifier 自建 LeanBridge 等）"
                 "尚未全部迁移到门面，其调用量见上表。")
    else:
        L.append("门面累计调用 **%d** 次。**按工具**：" % gw_total)
        L.append("")
        L.append("| 工具 | 调用次数 |")
        L.append("|---|---|")
        for k, v in sorted(gw_by_tool.items(), key=lambda kv: -kv[1]):
            L.append("| %s | %d |" % (safe(k, 40), v))
        L.append("")
        L.append("**按原因码**（★ 归因关键：三态必须分开看）：")
        L.append("")
        L.append("| 原因码 | 次数 | 含义 | 该往哪修 |")
        L.append("|---|---|---|---|")
        _reason_cn = {
            "ok": ("成功", "—"),
            "disabled": ("配置开关关闭", "查 overrides，确认是否为预期关闭"),
            "unavailable": ("环境缺失（无 Lean / 无 mathlib）", "装环境，**不是**代码问题"),
            "not_applicable": ("题面不适用（豁免题）", "正常，交 AuditGate 兜底"),
            "budget": ("时间/预算不足未发起", "看是否被上游阶段吃光"),
            "timeout": ("发起了但超时", "调超时阈值或看 Lean 编译是否卡死"),
            "error": ("调用抛异常", "**查代码**（环境正常但调用炸了）"),
            "empty": ("调用成功但结果为空", "看输入是否为空/查询是否过窄"),
            "unknown": ("工具明确答复无法判定", "增强工具或换后端"),
            "reject": ("工具明确判否（如编译失败）", "看被否的具体内容"),
        }
        for k, v in sorted(gw_by_reason.items(), key=lambda kv: -kv[1]):
            _cn, _fix = _reason_cn.get(k, (k, "—"))
            L.append("| %s | %d | %s | %s |" % (safe(k, 24), v, _cn, _fix))
        L.append("")
        L.append("> **判读要点**：`unavailable` 与 `error` **修法完全相反** ——"
                 "前者是环境没装，后者是环境正常但代码调用出错。"
                 "把二者混为一谈会让优化方向走反。")
    L.append("")
    L.append("### 相关开关（**权威口径 = 日志 EvalEngine init 的 overrides**）")
    L.append("")
    L.append("只看 `.env` 会误判：多数开关是 AgentConfig 字段，不写进环境变量。")
    L.append("")
    L.append("| 开关 | 运行值 | 来源 | 影响的工具 |")
    L.append("|---|---|---|---|")
    for k, desc in TOOL_SWITCHES:
        if k in ov:
            v, src = str(ov[k]), "overrides"
        elif k in defs:
            v, src = str(defs[k]), "代码默认"
        else:
            v, src = "未设置", "—"
        flag = ""
        if v in ("False", "0", "None") and src != "—":
            flag = " ★关闭"
        L.append("| %s | %s%s | %s | %s |" % (
            k, safe(v, 20), flag, src, safe(desc, 46)))
    L.append("")
    if ov:
        L.append("本轮 overrides 共 %d 键；未列入 overrides 的开关按代码默认值执行。" % len(ov))
        L.append("")
    L.append("> 判读要点：「★关闭」且该开关确有代码读取点 ⇒ 对应工具在本轮**不可用**；"
             "但需先确认「是人为关闭」还是「门控不可达」，二者修法完全不同。"
             "另注意：**代码注释常与真实默认值脱节**，一律以本表运行值为准。")
    L.append("")
    if ov:
        L.append("### 本轮运行配置全量（日志 overrides，%d 键）" % len(ov))
        L.append("")
        L.append("| 上限类配置 | 运行值 | 说明 |")
        L.append("|---|---|---|")
        for k, desc in TOOL_LIMITS:
            v = str(ov[k]) if k in ov else (str(defs[k]) if k in defs else "未设置")
            L.append("| %s | %s | %s |" % (k, safe(v, 22), safe(desc, 46)))
        L.append("")
        L.append("| 键 | 值 |")
        L.append("|---|---|")
        for k in sorted(ov):
            L.append("| %s | %s |" % (safe(k, 40), safe(ov[k], 70)))
        L.append("")
    if log_path and os.path.exists(log_path):
        try:
            txt = io.open(log_path, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            txt = ""
        pats = [
            ("走 mcp", "Lean MCP 通道调用"),
            ("回落 bridge", "回落 bridge（应尽量为 0）"),
            ("ok=False", "MCP 返回 ok=False（Lean 编译错误，属正常语义）"),
            ("sorryAx", "检出 sorryAx"),
            ("hover", "hover 查证"),
            ("multi_attempt", "multi-attempt 找到策略"),
            ("限流", "限流提示"),
            ("LLM 调用失败", "LLM 调用失败"),
            ("-20080", "配额超限 -20080"),
            ("-20048", "请求过频 -20048"),
        ]
        if txt:
            L.append("### 日志侧证据")
            L.append("")
            L.append("| 事件 | 计数 |")
            L.append("|---|---|")
            for pat, label in pats:
                L.append("| %s | %d |" % (safe(label, 40), txt.count(pat)))
            L.append("")
    return L


def sec_reasoning_vs_calc(recs, judge, amap):
    L = ["## 八、大模型的推理错误与计算错误出在哪里", ""]
    ERRL = ["前提不成立", "循环论证", "方向反了", "方法不适用", "跳步"]
    reason_rows = []
    calc_rows = []
    by_label = collections.Counter()
    for r in recs:
        if r.get("correct"):
            continue
        d = _as_dict(r.get("diag"))
        ec = str(r.get("error_class") or "")
        et = _as_dict(d.get("error_types"))
        labels = [k for k, v in et.items() if _num_or_zero(v) > 0]
        for k in labels:
            by_label[k] += 1
        tt = len(_as_list(d.get("toolcall_text_detected")))
        if ec in ("value_wrong", "expr_wrong") or tt > 0:
            calc_rows.append((str(r.get("id")), ec or "—", tt))
        if labels:
            reason_rows.append((str(r.get("id")), "、".join(labels), ec or "—"))

    L.append("### 推理错误（策略层：方向、前提、方法、跳步）")
    L.append("")
    if by_label:
        L.append("| 错误标签 | 命中题数 |")
        L.append("|---|---|")
        for k, v in by_label.most_common():
            L.append("| %s | %d |" % (safe(k, 20), v))
        L.append("")
    else:
        L.append("（本轮未产出推理错误标签）")
        L.append("")
    L.append("| 题号 | 推理错误标签 | error_class |")
    L.append("|---|---|---|")
    for rid, lab, ec in reason_rows[:60]:
        L.append("| %s | %s | %s |" % (safe(rid, 36), safe(lab, 40), safe(ec, 20)))
    L.append("")

    L.append("### 计算错误（执行层：数值算错、运算未执行）")
    L.append("")
    L.append("| 题号 | error_class | 被吞掉的工具调用 |")
    L.append("|---|---|---|")
    for rid, ec, tt in calc_rows[:60]:
        L.append("| %s | %s | %d |" % (safe(rid, 36), safe(ec, 20), tt))
    L.append("")
    if calc_rows:
        L.append("> ★ 上表中「被吞掉的工具调用 > 0」的题，其计算错误**不是模型算错**，"
                 "而是**模型写了调用但工具没被执行**——属基础设施/通道问题，不是能力问题。")
        L.append("")

    L.append("### 求解 vs 选答（错题第一分诊）")
    L.append("")
    gic_false = sum(1 for a in amap.values() if _as_dict(a.get("analysis")).get("gold_in_candidates") is False)
    gic_true = sum(1 for a in amap.values() if _as_dict(a.get("analysis")).get("gold_in_candidates") is True)
    if amap:
        L.append("| 分诊 | 题数 | 含义 |")
        L.append("|---|---|---|")
        L.append("| gold 不在候选池 | %d | 求解失败：答案从未被算出 |" % gic_false)
        L.append("| gold 在候选池却答错 | %d | 选答/终答失败：算出来了却没用上 |" % gic_true)
        L.append("")
    L.append("> 这一分诊决定改进方向：前者要动求解与蓝图，后者才要动闸门与选答。"
             "历史三轮 150 道错题中约 96.7%% 属前者。")
    L.append("")
    return L


def sec_infra(recs, monitor, log_path):
    L = ["## 九、基础设施与资源", ""]
    if monitor and os.path.exists(monitor):
        try:
            rows = [l.strip().split(",") for l in io.open(monitor, encoding="utf-8", errors="replace") if l.strip()]
            hdr = rows[0]
            idx = {k: i for i, k in enumerate(hdr)}
            data = [r for r in rows[1:] if len(r) == len(hdr)]
            def col(name):
                return [_num_or_zero(r[idx[name]]) for r in data] if name in idx else []
            mem = col("mem_used_pct")
            avail = col("mem_avail_mb")
            sw = col("swap_used_mb")
            cpu = col("cpu_pct")
            lp = col("lean_procs")
            lr = col("lean_rss_mb")
            L.append("| 指标 | 峰值 / 最低 | 中位 | 判读 |")
            L.append("|---|---|---|---|")
            L.append("| 内存占用 | %s%% | %s%% | %s |" % (
                fmt(max(mem) if mem else 0), fmt(med(mem)),
                "非瓶颈" if mem and max(mem) < 80 else "★ 需关注"))
            L.append("| 可用内存最低 | %s MB | %s MB | — |" % (
                fmt(min(avail) if avail else 0, 0), fmt(med(avail), 0)))
            L.append("| swap 占用峰值 | %s MB | %s MB | %s |" % (
                fmt(max(sw) if sw else 0, 0), fmt(med(sw), 0),
                "正常" if sw and max(sw) < 200 else "★ 偏高"))
            L.append("| CPU 中位 | — | %s%% | 资源不是瓶颈 |" % fmt(med(cpu)))
            L.append("| lean 进程峰值 | %s | %s | — |" % (
                fmt(max(lp) if lp else 0, 0), fmt(med(lp), 0)))
            L.append("| lean RSS 峰值 | %s MB | %s MB | 累加值含共享页重复计 |" % (
                fmt(max(lr) if lr else 0, 0), fmt(med(lr), 0)))
            L.append("| 采样点数 | %d | — | — |" % len(data))
            L.append("")
        except Exception as e:  # noqa: BLE001
            L.append("（监控 CSV 解析失败：%s）" % safe(str(e), 120))
            L.append("")
    else:
        L.append("（无监控 CSV）")
        L.append("")

    # 失败信号
    n_err = 0
    q80 = q48 = 0
    to = 0
    for r in recs:
        tr = _as_list(r.get("trace"))
        for t in tr:
            if isinstance(t, dict) and t.get("step") == "llm_error":
                n_err += 1
        s = json.dumps(_as_dict(r.get("diag")), ensure_ascii=False)
        if "-20080" in s:
            q80 += 1
        if "-20048" in s:
            q48 += 1
        if "timeout" in s.lower() or "读超时" in s:
            to += 1
    L.append("| 失败信号 | 题数 / 次数 |")
    L.append("|---|---|")
    L.append("| LLM 调用失败步（trace） | %d |" % n_err)
    L.append("| 出现配额超限 -20080 | %d 题 |" % q80)
    L.append("| 出现限流 -20048 | %d 题 |" % q48)
    L.append("| 疑似超时 | %d 题 |" % to)
    L.append("")
    if log_path and os.path.exists(log_path):
        try:
            txt = io.open(log_path, encoding="utf-8", errors="replace").read()
            L.append("| 日志计数 | 次数 |")
            L.append("|---|---|")
            for pat in ("-20080", "-20048", "LLM 调用失败", "超时", "MCP", "编译失败"):
                L.append("| %s | %d |" % (safe(pat, 20), txt.count(pat)))
            L.append("")
        except Exception:  # noqa: BLE001
            pass
    return L


def sec_conclusion(recs, vc, by_type, amap):
    L = ["## 十、结论与下一步", ""]
    n = len(recs)
    ok = sum(1 for r in recs if r.get("correct"))
    usable = vc.get("clean", 0) + vc.get("degraded", 0)
    L.append("1. 完成 %d 题、正确 %d 题（%s%%）；可用样本 %d 题（干净 %d、退化 %d）。"
             % (n, ok, fmt(pct(ok, n), 2), usable, vc.get("clean", 0), vc.get("degraded", 0)))
    if vc.get("invalid", 0) or vc.get("unknown", 0):
        L.append("2. ⚠ 本轮有 %d 题无效 / %d 题无法判定 ⇒ **正确率读数不可用作能力结论**，"
                 "应先修复基础设施再重跑。" % (vc.get("invalid", 0), vc.get("unknown", 0)))
    if by_type:
        top = by_type.most_common(1)[0]
        L.append("3. 错题主导类型：**%s**（%d 题，占错题的 %s%%）。"
                 % (safe(top[0], 20), top[1],
                    fmt(pct(top[1], sum(by_type.values())))))
    L.append("")
    L.append("> 本报告由 `tools/test_report.py` 自动生成，"
             "一次测试一个文档；文件名 = 日期-题目数量-正确的题数。")
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
