# -*- coding: utf-8 -*-
"""`cli/test_report.py` 的**共享常量与工具层**（2026-10-09 拆分 批6-1）。

从 `cli/test_report.py` 逐字搬出：阶段顺序 / 机制普查表 / 开关清单 / 上限清单，
以及报告全篇复用的判据与格式化工具（`is_subgoal_failed` / `_num_or_zero` /
`pct` / `med` / `fmt` / `hhmmss` / `local_attribution`）。

依赖方向：本模块**只被** `cli/test_report.py` 与 `cli/test_report__sections.py`
导入，**不反向导入**二者 ⇒ 无包级环。`cli/` 属上层入口，依赖
`agent.gap_analyzer` / `cli.deepseek_error_analyst` 属正常方向。
"""
from __future__ import annotations

import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:  # noqa: E402
    sys.path.insert(0, ROOT)

from cli.deepseek_error_analyst import _as_dict, _as_list, PLACEHOLDERS  # noqa: E402


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


# ================================================================
# 常量（阶段顺序 / 机制普查 / 开关 / 上限）
# ================================================================
# 阶段显示顺序（未列出的按字母序追加）
# ★ 2026-10-02 移除 `0_paper_pacer` / `1_classify` / `2.5_difficulty`（阶段已删）；此前报告仍含之。
STAGE_ORDER_test_report = [
    # ★ 2026-10-02 移除 `2.65_calc_prewarm`（calc 板块删除时漏网残留）；此前报告仍含之。
    "2.6_pre_audit",
    "2.7_subgoal_main", "3_solve", "3.2_complete", "3.3_improve", "3.4_collab",
    "3.5_subgoal_sup", "3.6_audit_filter", "4_verify", "4.5_oracle", "4.6_adv", "4.7_lean",
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
# 工具（判据 / 格式化）
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


def selection_pool_answers(rec):
    """返回 (选择池答案列表, 来源标签)。

    ★★ 2026-10-12 修（判读失真 #1）：**选择池 ≠ 导出字段 `candidates`**。
      · 导出 `candidates`（`run_eval__engine` 落盘）是「终裁后剩余」，且**不含**终选真正
        面对的池；真实池在 `diag.pick_diag.divergent_clusters`，其 size 之和 ==
        `diag.counts_reconciliation.selection_pool_size`（选择池口径，见其 note）。
      · 实测 `official112-010`：导出 candidates 全为 `\\boxed{0}`、**无 gold `\\boxed{2}`**，
        但 `divergent_clusters` 里**有** `\\boxed{2}`（size=1）且 `final_selection.branch=model_compare`
        ⇒ 旧实现把**选答失败误报成求解失败**（本报告的核心失真，会引错优化方向）。
    优先取 `divergent_clusters`，取不到再退导出字段（老结果文件兼容）。
    """
    diag = _as_dict(rec.get("diag"))
    clusters = _as_list(_as_dict(diag.get("pick_diag")).get("divergent_clusters"))
    ans = [c.get("answer") for c in clusters
           if isinstance(c, dict) and c.get("answer")]
    if ans:
        return ans, "diag.pick_diag.divergent_clusters"
    ans = [c.get("answer") for c in _as_list(rec.get("candidates"))
           if isinstance(c, dict) and c.get("answer")]
    return ans, "导出 candidates"


def local_attribution(rec, judge):
    """本地启发式归因（不依赖 DeepSeek）。

    返回 `(环节, 类型, 依据, gold_in_pool)`；`gold_in_pool` 为 `True/False/None`，
    供报告「gold 在候选池」列直接使用（此前该列恒为 `—`，等于**用空值下结论**）。
    """
    diag = _as_dict(rec.get("diag"))
    gold = rec.get("gold")
    pred = rec.get("predicted")
    if str(pred or "").strip() in PLACEHOLDERS:
        return ("—", "无效数据", "落盘占位符，未产出真实解答", None)
    picked = _as_dict(diag.get("pick_diag")).get("picked")
    pool, pool_src = selection_pool_answers(rec)
    pool_hit = any(judge(a, gold) for a in pool)
    if not pool_hit:
        st = "3_solve"
        sig = _as_dict(diag.get("blueprint_merge")) or diag.get("blueprint_merge")
        if sig:
            st = "2.7_subgoal_main"
        return (st, "求解失败", "选择池（%s）内无与 gold 等价的答案" % pool_src, False)
    if picked and judge(picked, gold) and not judge(pred, gold):
        return ("终答落定", "终答改写", "pick_diag 已选对，predicted 被改写", True)
    return ("选答", "选答失败", "选择池（%s）有正解但未被选中" % pool_src, True)
