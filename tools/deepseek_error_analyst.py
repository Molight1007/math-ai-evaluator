# -*- coding: utf-8 -*-
"""DeepSeek 辅助检错：把错题的「证据包」交给 DeepSeek 定位错误环节，结构化落盘。

定位：本工具**不解题、不参与判分**。它只做一件事 ——
读一条评测记录，抽出「这题错在哪一环」所需的证据，交给 DeepSeek 判断，
把结论写成可累积、可复核的 JSON 记录，供人工决策与后续 A/B。

与主链路的关系：
    纯旁路。不改 run_eval / 不改 agent / 不写 .env、不碰题库。
    输出只用于「检错线索」，**不得**直接作为判分依据。

用法：
    python tools/deepseek_error_analyst.py --results <结果.jsonl> --tag <标签>
    python tools/deepseek_error_analyst.py --results r.jsonl --tag t --limit 4
    python tools/deepseek_error_analyst.py --results r.jsonl --tag t \\
        --ids official112-000,official112-001 --include-invalid

输出（默认目录 results/_deepseek_audit）：
    <tag>.jsonl          逐题结论（追加式、幂等去重）
    <tag>_summary.md     按错误环节/类型聚合的汇总

⚠ 有效性闸门（逐题三态判定，见 classify_validity）：
   clean     无 LLM 调用失败步        => 正常分析
   degraded  有失败步但占比 < 50%     => 仍分析，但证据包标注「结论需打折」
   invalid   占位符 / 失败步占比≥50%  => 默认**跳过**（--include-invalid 才分析）
   这类题没有可归因的错误，喂给模型只会得到「模型不会做」的假结论。
   另有 --skip-degraded 可连退化题一起跳过，用于「只要干净样本」的严格跑法。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 复用项目既有的 OpenAI 兼容客户端工厂（读 .env 的 DEEPSEEK_* 凭据）
from tools.lean_local.leap_eval import make_client  # noqa: E402

PLACEHOLDERS = (
    "未给出有效解答。",
    "未给出有效解答",
    "empty response",
    "",
    "None",
)

# ----------------------------------------------------------------
# 已确认的无效轮信号（来自 2026-09-22 账号配额耗尽事件）
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# 本项目已知机制性缺陷（供模型对照，**不要求强行套用**）
# ----------------------------------------------------------------
KNOWN_ISSUES = """
K1  Lean 守卫只检查「数字是否出现在 Lean 代码里」，不检查是否形式化了题目条件
    ⇒ 自证式代码（如 example : (20*19*2 : ℕ) = 760 := by norm_num）会被判 answer_valid。
K2  audit_gate 对「解答题」结构性零输出（Level2 rubric 仅对证明题运行）⇒ 候选审核恒 unknown。
K3  工具调用被文本通道吞掉：模型写了 <tool_call><function=web_search>… 但原生 tool_calls 为空
    ⇒ 未执行、未回填（埋点 diag.toolcall_text_detected 非空即命中）。
K4  LeanSearch 常年 top_k 饱和（每题命中数恰等于 top_k），检索未被有效利用。
K5  档位资源表：standard 档覆盖最多题但配置最弱（票数/候选数/子目标数最少）。
K6  选答分支差异：pick_diag.branch = zero_vote_fallback_direct 时正确率显著偏低。
K7  子目标链锁定错值：首个断言式（断言某个具体数值）子目标一旦错，全链皆错。
K8  穷尽性检查 complete=false（「求所有」类题未真正穷尽），且未被下游强制使用。
K9  抽取崩坏：真实推导在 reasoning 里，answer 字段却是散文/工具标签/空
    ⇒ 表现为 answer 与 reasoning 长度悬殊。
K10 6.5_audit_gate 可能在 Formatter 之后改写终答（合法路径，但会造成 pick_diag 与 predicted 不一致）。
K11 蓝图 merge 锁定了具体值且与 gold 不符 ⇒ 蓝图层已错，revise 会沿错方向修。
K12 环境受限：云端 Mathlib 闭包残缺（缺 Mathlib/Data/Real 等）⇒ 含 ℝ 的 Lean 代码必编译失败。
K13 param_usage 显示某上限 capped=true 且 exact=true ⇒ 该上限真撞顶，构成能力削减。
K14 时间/预算机制：本项目已放开时间预算，故此条一般不成立，除非证据明确。
""".strip()

SYSTEM_PROMPT = """你是数学评测流水线的「错误定位专家」。
你的任务**不是解题**，而是依据给定的证据包回答三件事：
① 这条数据本身是否可用于归因（有没有真正跑起来）；
② 若可用，最早的错误发生在哪个环节、属于哪一类；
③ 有什么最小改动能修掉它（指到文件/开关/机制，不要泛泛而谈）。

判断纪律：
- 只依据证据包内的内容，**不要**凭题面自己推一遍答案来断定 gold 对不对（除非 gold 明显与题面矛盾，此时须明确指出）。
- 区分「求解失败」（候选池里根本没有正确答案）与「选答失败」（候选池里有正确答案但没被挑中）——
  证据包里给了候选池的原文，请据此判断，不要猜。
- 若证据指向的故障是环境/账号/数据采集层面的（配额耗尽、闭包缺失、占位符），
  归类为对应的「环境受限」或「无效数据」，不要归因为模型能力。
- known_issue 字段只填与**根因**直接相关的编号（如 "K1"）；若只是顺带吻合的次要现象则填 null。
  **不要**为了凑而硬套。
- 拿不准就在 confidence 上如实降低，并把 needs_human 置为 true。

只输出一个 JSON 对象，不要任何解释性前后缀、不要 Markdown 代码围栏。结构严格如下：
{
  "id": "题号",
  "data_valid": true,
  "error_stage": "环节名或 invalid_data",
  "error_type": "求解错误|选答错误|抽取崩坏|机制缺失|环境受限|无效数据|其它",
  "gold_in_candidates": true,
  "root_cause": "一句话根因",
  "evidence": ["证据1（须引用证据包中的具体字段与值）", "证据2"],
  "fix_suggestion": "一句话可操作建议",
  "target": "文件:行 或 开关名 或 机制名；无法判断则填 未知",
  "known_issue": "K1 或 null",
  "confidence": 0.0,
  "needs_human": true
}"""


# ================================================================
# ★★★ 分析师模式（2026-09-23 新建，用户口径）
# ================================================================
# 用户明确：「deepseek 不是检错 —— 检错可以直接对照答案；deepseek 是要分析出
# 大模型哪里错了、推理过程哪里有漏洞、计算哪里错了。deepseek 是作为一个
# **分析师**来工作的，不是检错人。」
#
# 因此 analyst 模式与 checker 模式的差别是**结构性的**，不只是换个说法：
#   1. 证据包必须带**推理全文**（checker 模式只给 reasoning_len，等于没有推理）；
#   2. 输出契约是「断点定位 + 该步应怎么做」，不是「归类 + 对拍 gold」；
#   3. 明确禁止用"候选池里有没有 gold"这类对照结论充当分析。
ANALYST_SYSTEM_PROMPT = """你是数学推理的「分析师」。你的交付物**不是**对错判定，
而是**把解题者的推理逐段读一遍，指出它在哪里断裂、为什么断裂、正确的走法是什么**。

判断纪律：
- **禁止**用「候选池里没有正确答案」「答案是错值」这类**对照式结论**充当分析 ——
  那是检错，不是分析。你必须指出**推理的哪一步**出了问题。
- 必须**引用推理原文**（摘录原句或步骤号）作为每个结论的锚点；引用不到的结论不要写。
- 断裂类型（break_type）只能取下列之一：
  跳步|循环论证|前提未证|计算错|符号错|定义域错|漏分支|未穷尽|引用外部结论|自相矛盾|中途改口后未收敛|题意误读|无法定位
- 若推理里存在**中途改口**（"实际上/重新审视/不对"），要判断它**最终有没有收敛**：
  收敛到正确方向 = 正常自纠（写进 `self_corrections`）；反复改口仍未收敛 = `中途改口后未收敛`。
- 若证据不足以定位到具体某一步，`break_type` 填「无法定位」并把 needs_human 置 true，
  **不要编造步骤**。

只输出一个 JSON 对象，不要解释性前后缀、不要 Markdown 围栏。结构严格如下：
{
  "id": "题号",
  "data_valid": true,
  "break_step": "断点定位：第几步/哪一段（引用推理原文的步骤号或原句片段）",
  "break_quote": "原文摘录（≤120字，必须是推理里真实存在的句子）",
  "break_type": "跳步|循环论证|前提未证|计算错|符号错|定义域错|漏分支|未穷尽|引用外部结论|自相矛盾|中途改口后未收敛|题意误读|无法定位",
  "what_is_wrong": "这一步到底错在哪（要说清是前提错、推理无效、还是结论不成立）",
  "correct_step": "这一步正确的做法是什么（可操作到具体算式或论证结构）",
  "gap_to_gold": "从这一步到正确结果 gold 还差什么",
  "self_corrections": ["改口后的收敛情况（最多 3 条）"],
  "evidence": ["引用证据包中的推理原文/字段作为锚点"],
  "confidence": 0.0,
  "needs_human": true
}"""


# ================================================================
# IO
# ================================================================
def load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _dedupe_by_id(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 (source, id) 只保留最后一次分析（审计日志语义：最新覆盖）。

    需要它是因为 --force 会用「新的证据包」重跑同一题，从而在追加式日志里
    留下同一题号的多条记录；汇总若不去重会出现重复行与自相矛盾的结论。
    """
    seen: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        seen[(r.get("source"), r.get("id"))] = r
    return list(seen.values())


def load_core(path: str) -> Dict[str, Dict[str, Any]]:
    """本地历史总表（用于判断该题历史上是否做对过）。"""
    d: Dict[str, Dict[str, Any]] = {}
    for rec in load_jsonl(path):
        key = str(rec.get("id") or rec.get("qid") or "")
        if key:
            d[key] = rec
    return d


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cut(s: Any, n: int) -> str:
    t = "" if s is None else str(s)
    t = t.replace("\n", " ⏎ ")
    return t if len(t) <= n else t[:n] + " …[截断]"


# ================================================================
# 有效性闸门
# ================================================================
def classify_validity(rec: Dict[str, Any]) -> tuple:
    """三态判定数据质量：(level, reason)。

    level ∈ {"clean", "degraded", "invalid", "unknown"}。
    判据取自 2026-09-22 配额耗尽事件的实测分布：LLM 失败步数 / trace 总步数。
    实测：000 = 0/176、001 = 0/118、002 = 7/168（4.2%）、003 = 52/176（29.5%）。
    —— 只看日志首现时刻会把 002/003 误判为「健康」，故必须逐题按比例判。

    阈值（2026-09-22 晚修订）：
      · 噪声线 2%：偶发单步失败（如 1/108 ≈ 0.9%）属瞬时限流，重试即成，不算退化。
        实测 cloud112_0920d 的 32 道错题：21 道 0%，11 道 0–1.1%，无一超过 2%
        ⇒ 不设噪声线会让「退化」标记几乎恒亮，失去信息量。
      · 无效线 50%。
      · 无 trace ⇒ "unknown"：**不可判为 clean**。0910/0908 等老记录整轮无 trace，
        若按 0 步失败记为 clean 就是假阴性（无法证明健康 ≠ 健康）。
    """
    pred = str(rec.get("predicted") or "").strip()
    trace = _as_list(rec.get("trace"))
    n_step = len(trace)
    n_err = sum(1 for t in trace if isinstance(t, dict) and t.get("step") == "llm_error")
    ratio = (n_err / n_step) if n_step else 0.0
    if pred in PLACEHOLDERS:
        return "invalid", "占位符答案（未产出真实解答）"
    if n_step == 0:
        return "unknown", "无 trace，无法判定 LLM 健康度（不得据此视为干净）"
    if ratio >= 0.5:
        return "invalid", ("LLM 调用失败步占 %.0f%%（%d/%d），数据被配额/限流主导"
                           % (100 * ratio, n_err, n_step))
    if ratio >= 0.02:
        return "degraded", ("存在 %d 步 LLM 调用失败（占 %.0f%%），结论需打折看待"
                            % (n_err, 100 * ratio))
    return "clean", None


def detect_invalid(rec: Dict[str, Any]) -> Optional[str]:
    """兼容旧调用点：仅当 level == invalid 时返回原因，否则 None。"""
    level, reason = classify_validity(rec)
    return reason if level == "invalid" else None


# ================================================================
# 证据包
# ================================================================
def build_evidence(rec: Dict[str, Any], core: Optional[Dict[str, Any]],
                   source: str, mode: str = "checker") -> Dict[str, Any]:
    d = rec.get("diag") or {}
    st = d.get("stage_timers"); st = st if isinstance(st, dict) else {}
    tot = sum(v for v in st.values() if isinstance(v, (int, float))) or 1.0

    # 阶段耗时（top 8）
    stages = [
        {"stage": k, "sec": round(v, 1), "pct": round(100.0 * v / tot, 1)}
        for k, v in sorted(st.items(), key=lambda x: -(x[1] or 0))
        if isinstance(v, (int, float)) and v > 0.5
    ][:8]

    # lean_gate 摘要
    lg = _as_list(d.get("lean_gate"))
    lg_counts: Dict[str, int] = {}
    for e in lg:
        if isinstance(e, dict):
            lg_counts[str(e.get("verdict"))] = lg_counts.get(str(e.get("verdict")), 0) + 1
    lg_head = [
        {
            "verdict": e.get("verdict"),
            "reason": e.get("verdict_reason"),
            "compiled": e.get("compiled"),
            "cross_check": e.get("cross_check"),
            "code": _cut(e.get("lean_code"), 180),
        }
        for e in lg[:6] if isinstance(e, dict)
    ]

    # audit_gate 摘要
    ag = _as_list(d.get("audit_gate"))
    ag_counts: Dict[str, int] = {}
    for e in ag:
        if isinstance(e, dict):
            ag_counts[str(e.get("verdict"))] = ag_counts.get(str(e.get("verdict")), 0) + 1

    # 候选池
    cands = []
    for c in _as_list(rec.get("candidates"))[:8]:
        if isinstance(c, dict):
            cands.append({"id": c.get("id"), "answer": _cut(c.get("answer"), 220),
                          "reasoning_len": len(str(c.get("reasoning") or ""))})
        else:
            cands.append({"raw": _cut(c, 220)})

    # pick_diag
    pd = d.get("pick_diag"); pd = pd if isinstance(pd, dict) else {}
    clusters = [
        {"answer": _cut(c.get("answer"), 120), "size": c.get("size"),
         "confidence": c.get("confidence"),
         "votes": "%s/%s" % (c.get("correct_votes"), c.get("total_votes"))}
        for c in _as_list(pd.get("divergent_clusters"))[:5] if isinstance(c, dict)
    ]

    tc = rec.get("tool_calls"); tc = tc if isinstance(tc, dict) else {}
    llm = rec.get("llm_calls"); llm = llm if isinstance(llm, dict) else {}

    ev = {
        "source": source,
        "id": rec.get("id"),
        "domain": d.get("domain") or rec.get("domain"),
        "question_type": d.get("question_type"),
        "tier": d.get("tier"),
        "correct": rec.get("correct"),
        "error_class": rec.get("error_class"),
        "elapsed_sec": round(rec.get("elapsed_sec") or 0, 1),
        "placeholder": d.get("placeholder"),
        "invalid_reason": detect_invalid(rec),
        "data_quality": classify_validity(rec)[0],
        "data_quality_reason": classify_validity(rec)[1],
        "question": _cut(rec.get("question"), 1000),
        "gold": _cut(rec.get("gold"), 200),
        "predicted": _cut(rec.get("predicted"), 300),
        "candidates": cands,
        "pick_diag": {"branch": pd.get("branch"), "picked": _cut(pd.get("picked"), 160),
                      "clusters": clusters},
        "lean_gate": {"n": len(lg), "verdict_counts": lg_counts, "head": lg_head,
                      "applicable": d.get("lean_applicable"),
                      "skip_reason": d.get("lean_skip_reason")},
        "audit_gate": {"n": len(ag), "verdict_counts": ag_counts,
                       "note": _cut((ag[0] or {}).get("note") if ag else None, 200)},
        "stages": stages,
        "mechanics": {
            "subgoal_stats": d.get("subgoal_stats"),
            "exhaust_result": d.get("exhaust_result"),
            "blueprint_nodes": _count(d.get("blueprint_nodes")),
            "blueprint_merge": _cut(d.get("blueprint_merge"), 200),
            "toolcall_text_detected": _count(d.get("toolcall_text_detected")),
            "leansearch": d.get("leansearch"),
            "toolcall_exec": _count(d.get("toolcall_exec")),
            "preverify_trace": (
                {"verdict": (d.get("preverify_trace") or {}).get("verdict"),
                 "rounds": (d.get("preverify_trace") or {}).get("rounds")}
                if isinstance(d.get("preverify_trace"), dict) else None),
            "revise_round": d.get("revise_round"),
            "degraded_flags": d.get("degraded_flags"),
            "capped_params": _capped(d.get("param_usage")),
        },
        "tool_calls": {
            "lean_mcp": (tc.get("lean_mcp") or {}).get("calls"),
            "lean_mcp_fail": (tc.get("lean_mcp") or {}).get("fail"),
            "web_search": (tc.get("web_search") or {}).get("calls"),
        },
        "llm_calls": {"calls": llm.get("calls"), "truncated": llm.get("truncated")},
        "trace_tail": [
            {"step": t.get("step"), "content": _cut(t.get("content"), 170)}
            for t in _as_list(rec.get("trace"))[-8:] if isinstance(t, dict)
        ],
        "local_history": (
            {"correct_before": core.get("correct"), "tier_before": core.get("tier"),
             "elapsed_before": core.get("elapsed_sec")} if core else None),
    }
    # ★ 2026-09-23 分析师模式专用：**推理全文**。
    #   checker 模式只给 reasoning_len（等于没给推理）⇒ 模型只能做"池里有没有
    #   gold"的对照题。分析师模式必须把推理原文喂进去，否则"分析推理漏洞"
    #   无从谈起（用户 2026-09-23 口径）。
    #   ⚠ **只在 analyst 模式注入**：checker 模式保持字段集不变，
    #   否则 `evidence_sha` 全变 ⇒ 既有轮次的幂等去重全部失效、37 题会被重跑。
    if mode == "analyst":
        ev["candidate_reasoning"] = _reasoning_excerpt(rec)
        ev["subgoal_results"] = _subgoal_excerpt(rec)
    return ev


# ★ 分析师模式的推理预算：推理原文总字符上限（超出则按候选均分截断）
REASONING_BUDGET = 24000
SUBGOAL_BUDGET = 8000


def _reasoning_excerpt(rec: Dict[str, Any], budget: int = REASONING_BUDGET) -> List[Dict[str, Any]]:
    """抽取候选推理**原文**（分析师模式的核心输入）。

    按候选均分字符预算；单条至少给 1200 字符、最多 12000 字符。
    截断处显式标注 `[后文截断]`，让模型知道它没看到全文（防"此处无异常"的误判）。
    """
    cands = [c for c in _as_list(rec.get("candidates")) if isinstance(c, dict)]
    if not cands:
        return []
    per = max(1200, min(12000, budget // max(1, len(cands))))
    out = []
    for c in cands:
        r = str(c.get("reasoning") or "")
        if not r:
            continue
        item = {
            "id": c.get("id"),
            "answer": _cut(c.get("answer"), 160),
            "reasoning": _cut(r, per),
            "reasoning_len": len(r),
        }
        if len(r) > per:
            item["reasoning"] = item["reasoning"] + "……[后文截断，原文共 %d 字符]" % len(r)
        out.append(item)
    return out


def _subgoal_excerpt(rec: Dict[str, Any], budget: int = SUBGOAL_BUDGET) -> List[Dict[str, Any]]:
    """抽取子目标的**产出原文**（子目标推理）。"""
    d = rec.get("diag") or {}
    sgs = [s for s in _as_list(d.get("subgoal_trace")) if isinstance(s, dict)]
    if not sgs:
        return []
    per = max(200, min(3000, budget // max(1, len(sgs))))
    out = []
    for s in sgs:
        out.append({
            "id": s.get("id"),
            "title": _cut(s.get("title"), 80),
            "type": s.get("type"),
            "expected_output": _cut(s.get("expected_output"), 120),
            "result": _cut(s.get("result"), per),
        })
    return out


def _as_list(v: Any) -> List[Any]:
    """埋点类型在轮次间漂移（list / dict / int / None）⇒ 一律安全降级为 list。"""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def _as_dict(v: Any) -> Dict[str, Any]:
    """同上：把非 dict 的埋点安全降级成空 dict，避免 .get 崩。"""
    return v if isinstance(v, dict) else {}


def _count(v: Any) -> Any:
    """埋点可能是 list / dict / int ⇒ 统一成「条目数」或原值。"""
    if v is None:
        return None
    if isinstance(v, (list, dict, str)):
        return len(v)
    return v


def _capped(param_usage: Any) -> List[str]:
    """挑出真正撞顶的上限（capped=true 且 exact=true）。"""
    if not isinstance(param_usage, dict):
        return []
    out = []
    for k, v in (param_usage.get("items") or {}).items():
        if isinstance(v, dict) and v.get("capped") and v.get("exact"):
            out.append("%s(%s/%s)" % (k, v.get("used"), v.get("cap")))
    return out


def render_evidence(ev: Dict[str, Any]) -> str:
    # 去掉逐题不变的信源字段再渲染，让哈希只反映本题内容
    body = {k: v for k, v in ev.items() if k != "source"}
    return json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True)


# ----------------------------------------------------------------
# 证据包收缩（防止长上下文 / 长推理导致调用中断）
# ----------------------------------------------------------------
_EV_KEEP = ("id", "question_type", "tier", "correct", "error_class", "elapsed_sec",
            "question", "gold", "predicted", "candidates", "pick_diag",
            "lean_gate", "audit_gate", "stages", "mechanics", "tool_calls",
            "llm_calls", "data_quality",
            # ★ 分析师模式必须保留的字段：丢了就等于丢了分析对象
            "candidate_reasoning", "subgoal_results")


def _ev_size(o: Dict[str, Any]) -> int:
    """与真正发送的文本同口径计长（render_evidence 的缩进/排序一致）。"""
    return len(render_evidence(o))


def _trim_to_budget(e: Dict[str, Any], budget: int) -> Dict[str, Any]:
    """兜底强制裁剪：按「信息密度从低到高」依次削，直到进入预算。"""
    import copy
    o = copy.deepcopy(e)
    steps = (
        lambda x: x.pop("trace_tail", None),
        lambda x: x.pop("stages", None),
        lambda x: x.pop("llm_calls", None),
        lambda x: x.pop("tool_calls", None),
        lambda x: x.pop("audit_gate", None),
        lambda x: x.get("mechanics") and x["mechanics"].pop("blueprint_merge", None),
        lambda x: x.__setitem__("question", _cut(x.get("question"), 120)),
        lambda x: x.__setitem__("gold", _cut(x.get("gold"), 60)),
        lambda x: x.pop("mechanics", None),
        lambda x: x.pop("pick_diag", None),
        lambda x: x.pop("lean_gate", None),
        lambda x: x.__setitem__(
            "candidates",
            [{"id": c.get("id"), "answer": _cut(c.get("answer"), 60)}
             for c in (x.get("candidates") or [])]),
        lambda x: x.__setitem__("candidates", (x.get("candidates") or [])[:3]),
    )
    for fn in steps:
        if _ev_size(o) <= budget:
            return o
        try:
            fn(o)
        except Exception:  # noqa: BLE001
            pass
    return o


def _ev_levels(ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    """由大到小的证据包收缩阶梯，每级都自洽、都保留判错所需的核心字段。

    L0 原样 → L1 去 trace_tail → L2 再砍 Lean 代码/候选答案/题面 → L3 只留核心键。
    用途有二：① 按预算裁剪；② 失败重试时逐级换更小的输入。
    """
    import copy
    lv: List[Dict[str, Any]] = [copy.deepcopy(ev)]

    a = copy.deepcopy(ev)
    a.pop("trace_tail", None)
    lv.append(a)

    b = copy.deepcopy(a)
    lg = b.get("lean_gate")
    if isinstance(lg, dict):
        for h in (lg.get("head") or []):
            if isinstance(h, dict):
                h.pop("code", None)
        lg["head"] = (lg.get("head") or [])[:2]
    for c in (b.get("candidates") or []):
        if isinstance(c, dict) and "answer" in c:
            c["answer"] = _cut(c.get("answer"), 120)
    b["question"] = _cut(b.get("question"), 300)
    # ★ 分析师模式：L2 只压缩推理到一半，**不删** —— 推理是分析对象，不是装饰
    for c in (b.get("candidate_reasoning") or []):
        if isinstance(c, dict) and c.get("reasoning"):
            c["reasoning"] = _cut(c.get("reasoning"), 4000)
    for s in (b.get("subgoal_results") or []):
        if isinstance(s, dict) and s.get("result"):
            s["result"] = _cut(s.get("result"), 800)
    lv.append(b)

    c = {k: b[k] for k in _EV_KEEP if k in b}
    if isinstance(c.get("lean_gate"), dict):
        c["lean_gate"] = {k: v for k, v in c["lean_gate"].items()
                          if k in ("n", "verdict_counts", "applicable")}
    lv.append(c)
    return lv


def fit_evidence(ev: Dict[str, Any], budget: int) -> Dict[str, Any]:
    """返回「不超过 budget 字符」的最大可用证据包；都不超则原样返回。"""
    lv = _ev_levels(ev)
    for e in lv:
        if _ev_size(e) <= budget:
            return e
    return _trim_to_budget(lv[-1], budget)


# ================================================================
# 调用与解析
# ================================================================
def extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # 退一步：抓最外层花括号
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _build_msgs(ev_text: str, mode: str = "checker") -> List[Dict[str, str]]:
    if mode == "analyst":
        # ★ 分析师模式：不给 KNOWN_ISSUES 对照表 —— 给了会把模型往"归类"上带，
        #   而用户要的是"读出推理在哪一步断"。只给纪律 + 推理原文。
        return [
            {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
            {"role": "user",
             "content": "【证据包】\n%s\n\n请按要求只输出一个 JSON 对象。" % ev_text},
        ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",
         "content": "【本项目已知机制性缺陷（供对照）】\n%s\n\n【证据包】\n%s\n\n"
                    "请按要求只输出一个 JSON 对象。" % (KNOWN_ISSUES, ev_text)},
    ]


def analyse_one(client, ev_text: str, max_tokens: int,
                ev_small: str = "", mode: str = "checker") -> Dict[str, Any]:
    """调用 DeepSeek 分析。

    重试阶梯：失败时**同时**放大输出预算（换取 reasoning 空间）与收缩输入
    （规避长上下文导致的超时/空响应），避免推理模型把 max_tokens 全烧在
    reasoning 上或长输入直接把调用撑断。
    """
    ladder = [(max_tokens, ev_text)]
    ladder.append((max_tokens * 2, ev_small if ev_small else ev_text))
    last = ""
    for attempt, (mt, body) in enumerate(ladder):
        t0 = time.time()
        try:
            last = client.chat(_build_msgs(body, mode), temperature=0.0,
                               max_tokens=mt)
        except Exception as e:  # noqa: BLE001
            last = ""
            print("    LLM 异常: %s" % str(e)[:200], flush=True)
        obj = extract_json(last)
        if obj is not None:
            obj["_elapsed_sec"] = round(time.time() - t0, 1)
            obj["_attempt"] = attempt + 1
            obj["_ev_chars"] = len(body)
            obj["_max_tokens"] = mt
            obj["_mode"] = mode
            return obj
        print("    JSON 解析失败（第 %d 次, max_tokens=%d, 输入 %d 字符, 返回 %d 字符）"
              "，原文前 160: %r"
              % (attempt + 1, mt, len(body), len(last), last[:160]), flush=True)
    fail = {"id": None, "data_valid": None,
            "root_cause": "模型未返回可解析 JSON", "evidence": [last[:400]],
            "confidence": 0.0, "needs_human": True, "_elapsed_sec": 0,
            "_attempt": len(ladder), "_ev_chars": len(ev_text),
            "_max_tokens": max_tokens, "_mode": mode}
    if mode == "analyst":
        fail.update({"break_step": "", "break_quote": "", "break_type": "无法定位",
                     "what_is_wrong": "模型未返回可解析 JSON",
                     "correct_step": "", "gap_to_gold": ""})
    else:
        fail.update({"error_stage": "PARSE_FAILED", "error_type": "其它",
                     "gold_in_candidates": None, "fix_suggestion": "", "target": "",
                     "known_issue": None})
    return fail



# ================================================================
# 汇总
# ================================================================
def write_summary(path: str, tag: str, source: str, rows: List[Dict[str, Any]]) -> None:
    n = len(rows)
    by_type: Dict[str, int] = {}
    by_stage: Dict[str, int] = {}
    by_issue: Dict[str, int] = {}
    by_break: Dict[str, int] = {}          # ★ 分析师模式：断裂类型分布
    analyst_mode = False
    for r in rows:
        a = r.get("analysis") or {}
        if str(a.get("_mode")) == "analyst":
            analyst_mode = True
        by_type[str(a.get("error_type"))] = by_type.get(str(a.get("error_type")), 0) + 1
        by_stage[str(a.get("error_stage"))] = by_stage.get(str(a.get("error_stage")), 0) + 1
        ki = a.get("known_issue")
        if ki:
            by_issue[str(ki)] = by_issue.get(str(ki), 0) + 1
        if str(a.get("_mode")) == "analyst":
            bt = str(a.get("break_type") or "未标注")
            by_break[bt] = by_break.get(bt, 0) + 1

    L = []
    L.append("# DeepSeek 辅助检错汇总 · %s" % tag)
    L.append("")
    L.append("- 结果文件：`%s`" % os.path.basename(source))
    L.append("- 分析题数：%d" % n)
    L.append("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("")
    L.append("> 本汇总为**线索**，不是结论。任何据此发起的改动仍须过「配对差异 ≥5pp 且 net≥3」判据。")
    L.append("")

    if analyst_mode:
        L.append("## 零、断裂类型分布（分析师模式）")
        L.append("")
        L.append("| 断裂类型 | 题数 | 占比 |")
        L.append("|---|---|---|")
        for k, v in sorted(by_break.items(), key=lambda x: -x[1]):
            L.append("| %s | %d | %.1f%% |" % (k, v, 100.0 * v / max(n, 1)))
        L.append("")
        L.append("## 零乙、逐题断点")
        L.append("")
        L.append("| 题号 | 断裂类型 | 断点位置 | 错在哪 | 应怎么做 | 置信 |")
        L.append("|---|---|---|---|---|---|")
        for r in rows:
            a = r.get("analysis") or {}
            L.append("| %s | %s | %s | %s | %s | %.2f |" % (
                r.get("id"), a.get("break_type"),
                str(a.get("break_step"))[:70].replace("|", "/"),
                str(a.get("what_is_wrong"))[:110].replace("|", "/"),
                str(a.get("correct_step"))[:110].replace("|", "/"),
                a.get("confidence") or 0))
        L.append("")

    if analyst_mode:
        # ★ 分析师模式只出「断点」相关段：checker 的按类型/按环节/known_issue
        #   字段在本模式下不存在，照旧输出会得到满屏 None，误导读者。
        with io.open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        return

    L.append("## 一、按错误类型")
    L.append("")
    L.append("| 错误类型 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
        L.append("| %s | %d | %.1f%% |" % (k, v, 100.0 * v / max(n, 1)))
    L.append("")

    L.append("## 二、按错误环节")
    L.append("")
    L.append("| 环节 | 题数 |")
    L.append("|---|---|")
    for k, v in sorted(by_stage.items(), key=lambda x: -x[1]):
        L.append("| %s | %d |" % (k, v))
    L.append("")

    if by_issue:
        L.append("## 三、命中的已知缺陷编号")
        L.append("")
        L.append("| 编号 | 命中题数 |")
        L.append("|---|---|")
        for k, v in sorted(by_issue.items(), key=lambda x: -x[1]):
            L.append("| %s | %d |" % (k, v))
        L.append("")

    L.append("## 四、逐题结论")
    L.append("")
    L.append("| 题号 | 数据质量 | 环节 | 类型 | gold 在候选池 | 根因 | 建议 | 目标 | 缺陷 | 置信 | 需人看 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        a = r.get("analysis") or {}
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r.get("id"), r.get("data_quality") or "-", a.get("error_stage"),
            a.get("error_type"), a.get("gold_in_candidates"),
            _md(a.get("root_cause"), 160), _md(a.get("fix_suggestion"), 160),
            _md(a.get("target"), 60), a.get("known_issue") or "-",
            a.get("confidence"), "是" if a.get("needs_human") else "否"))
    L.append("")

    L.append("## 五、高置信根因（confidence ≥ 0.7）")
    L.append("")
    hi = [r for r in rows if (r.get("analysis") or {}).get("confidence", 0) >= 0.7]
    if not hi:
        L.append("（无）")
    for r in hi:
        a = r["analysis"]
        L.append("### %s · %s" % (r.get("id"), a.get("error_type")))
        L.append("")
        L.append("- 根因：%s" % a.get("root_cause"))
        L.append("- 建议：%s" % a.get("fix_suggestion"))
        L.append("- 目标：%s" % a.get("target"))
        L.append("- 证据：")
        for e in (a.get("evidence") or [])[:4]:
            L.append("  - %s" % _md(e, 300))
        L.append("")

    L.append("## 六、需人工确认（原样记录，未做判断）")
    L.append("")
    L.append("> 这些条目置信度低或涉及跨机制推断，**不得**直接据此改代码，"
             "需先做 A/B 或人工复核。")
    L.append("")
    need = [r for r in rows if _as_dict(r.get("analysis")).get("needs_human")]
    if not need:
        L.append("（无）")
    for r in need:
        a = _as_dict(r["analysis"])
        L.append("- **%s** [%s / %s / conf=%s]：%s"
                 % (r.get("id"), a.get("error_stage"), a.get("error_type"),
                    a.get("confidence"), _md(a.get("root_cause"), 220)))
    L.append("")

    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def _md(s: Any, n: int) -> str:
    """md 单元格安全化：去竖线、去换行。"""
    t = "" if s is None else str(s)
    t = t.replace("|", "∣").replace("\n", " ").replace("**", "")
    return t if len(t) <= n else t[:n] + "…"


# ================================================================
# main
# ================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="DeepSeek 辅助检错")
    ap.add_argument("--results", required=True, help="评测结果 jsonl")
    ap.add_argument("--tag", required=True, help="本次分析标签（决定输出文件名）")
    ap.add_argument("--core", default="results/_112_core_table.jsonl",
                    help="本地历史总表（判断该题曾否做对）")
    ap.add_argument("--out-dir", default="results/_deepseek_audit")
    ap.add_argument("--ids", default="", help="逗号分隔题号，只分析这些")
    ap.add_argument("--limit", type=int, default=0, help="最多分析 N 题（0=不限）")
    ap.add_argument("--include-correct", action="store_true", help="连做对的也分析")
    ap.add_argument("--include-invalid", action="store_true",
                    help="连「无效数据」题也分析（默认跳过，见模块 docstring）")
    ap.add_argument("--skip-degraded", action="store_true",
                    help="连「退化数据」题也跳过（默认保留，但在证据包里标注）")
    ap.add_argument("--model", default="deepseek-v4-flash",
                    help="分析用模型（默认 deepseek-v4-flash）")
    ap.add_argument("--max-tokens", type=int, default=16384,
                    help="推理模型需留足空间给 reasoning，过小会导致 content 为空")
    ap.add_argument("--timeout", type=int, default=300,
                    help="单次 LLM 调用超时秒数（长推理/长输入需留足，防止调用被截断）")
    ap.add_argument("--evidence-budget", type=int, default=0,
                    help="单题证据包字符预算；0=按模式取默认"
                         "（checker 14000 / analyst 40000）；超出则分级收缩")
    ap.add_argument("--mode", default="analyst", choices=("analyst", "checker"),
                    help="analyst=分析推理漏洞（默认，带推理全文）；"
                         "checker=对照式检错（旧模式，输出 <tag>.jsonl）")
    ap.add_argument("--force", action="store_true", help="忽略幂等去重，重跑全部")
    args = ap.parse_args()

    src = args.results
    rows = load_jsonl(src)
    if not rows:
        print("[error] 结果文件为空或不存在：%s" % src, file=sys.stderr)
        return 1
    # ★ 分析师模式默认给更大的证据预算（推理全文很占字符）
    if not args.evidence_budget:
        args.evidence_budget = 40000 if args.mode == "analyst" else 14000
    core = load_core(args.core)
    wanted = {x.strip() for x in args.ids.split(",") if x.strip()}

    os.makedirs(args.out_dir, exist_ok=True)
    # ★ 分析师模式另存 `_analyst.jsonl`，不覆盖既有 checker 产物
    out_jsonl = os.path.join(
        args.out_dir,
        "%s%s.jsonl" % (args.tag, "" if args.mode == "checker" else "_analyst"))

    # 幂等：已分析过的证据哈希
    done = set()
    if not args.force:
        for old in load_jsonl(out_jsonl):
            if old.get("evidence_sha"):
                done.add(old["evidence_sha"])
    print("[载入] 结果 %d 条 | core %d 条 | 已完成 %d 条"
          % (len(rows), len(core), len(done)))

    todo = []
    skipped = {"correct": 0, "invalid": 0, "degraded": 0, "degraded_kept": 0, "dup": 0}
    for r in rows:
        rid = str(r.get("id"))
        if wanted and rid not in wanted:
            continue
        if not args.include_correct and r.get("correct"):
            skipped["correct"] += 1
            continue
        level, reason = classify_validity(r)
        if level == "invalid" and not args.include_invalid:
            skipped["invalid"] += 1
            continue
        if level == "degraded":
            if args.skip_degraded:
                skipped["degraded"] += 1
                continue
            skipped["degraded_kept"] += 1
        bad = reason if level == "invalid" else None
        try:
            ev = build_evidence(r, core.get(rid), src, args.mode)
        except Exception as e:  # noqa: BLE001
            print("    证据包构建失败，跳过：%s" % str(e)[:160], flush=True)
            continue
        ev_text = render_evidence(ev)
        if len(ev_text) > args.evidence_budget:
            raw = len(ev_text)
            ev = fit_evidence(ev, args.evidence_budget)
            ev_text = render_evidence(ev)
            tail = ""
            if len(ev_text) > args.evidence_budget:
                # 分析师模式下 `candidate_reasoning` 是**分析对象**，收缩阶梯
                # 保护它不被删除 ⇒ 可能仍超预算。此处显式标注，不静默超限。
                tail = "（★仍超预算：推理属分析对象，受保护不删）"
            print("    [收缩] %s 证据包 %d → %d 字符（预算 %d）%s"
                  % (rid, raw, len(ev_text), args.evidence_budget, tail), flush=True)
        sha = _sha(ev_text)
        if sha in done:
            skipped["dup"] += 1
            continue
        ev_small = render_evidence(_ev_levels(ev)[-1])
        todo.append((r, ev, ev_text, sha, bad, ev_small))
    if args.limit:
        todo = todo[:args.limit]
    print("[筛选] 待分析 %d 题 | 跳过：做对 %d / 无效 %d / 退化 %d / 已完成 %d"
          " | 含退化数据 %d 题"
          % (len(todo), skipped["correct"], skipped["invalid"], skipped["degraded"],
             skipped["dup"], skipped["degraded_kept"]))
    if not todo:
        print("[完成] 没有需要分析的题。")
        return 0

    client = make_client("deepseek", args.model)
    client.min_max_tokens = 0  # 由 --max-tokens 精确控制
    client.timeout = args.timeout
    print("[后端] deepseek model=%s max_tokens=%d timeout=%ds 证据预算=%d字符 模式=%s\n"
          % (client.model, args.max_tokens, client.timeout, args.evidence_budget,
             args.mode))

    written = []
    t_all = time.time()
    for i, (rec, ev, ev_text, sha, bad, ev_small) in enumerate(todo, 1):
        print("=== [%d/%d] %s%s ===" % (i, len(todo), rec.get("id"),
                                        "（无效数据）" if bad else ""), flush=True)
        ana = analyse_one(client, ev_text, args.max_tokens, ev_small,
                          mode=args.mode)
        ana.setdefault("id", rec.get("id"))
        out = {
            "id": rec.get("id"),
            "source": src,
            "tag": args.tag,
            "evidence_sha": sha,
            "invalid_reason": bad,
            "data_quality": classify_validity(rec)[0],
            "data_quality_reason": classify_validity(rec)[1],
            "analysed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": client.model,
            "gold": _cut(rec.get("gold"), 200),
            "predicted": _cut(rec.get("predicted"), 200),
            "tier": (rec.get("diag") or {}).get("tier"),
            "elapsed_sec": round(rec.get("elapsed_sec") or 0, 1),
            "analysis": ana,
        }
        written.append(out)
        if args.mode == "analyst":
            print("    → 断点[%s] %s | 置信 %.2f | %s"
                  % (ana.get("break_type"), str(ana.get("break_step"))[:90],
                     ana.get("confidence") or 0,
                     str(ana.get("what_is_wrong"))[:110]), flush=True)
        else:
            print("    → %s | %s | 置信 %.2f | %s"
                  % (ana.get("error_stage"), ana.get("error_type"),
                     ana.get("confidence") or 0, str(ana.get("root_cause"))[:110]),
                  flush=True)
        # 逐题落盘：中断也不丢已得结论
        with io.open(out_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    all_rows = load_jsonl(out_jsonl)
    raw_n = len(all_rows)
    all_rows = _dedupe_by_id(all_rows)
    if len(all_rows) != raw_n:
        # 同一 (source,id) 保留最新一条，回写日志消除 --force 造成的重复
        with io.open(out_jsonl, "w", encoding="utf-8") as f:
            for r in all_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("[去重] 日志 %d → %d 条（同题保留最新）" % (raw_n, len(all_rows)))
    # 稳定排序：按题号
    all_rows.sort(key=lambda r: str(r.get("id")))
    sum_path = os.path.join(args.out_dir, "%s_summary.md" % args.tag)
    write_summary(sum_path, args.tag, src, all_rows)
    print("\n[完成] 本次 %d 题，用时 %.1fs | 累计 %d 条"
          % (len(written), time.time() - t_all, len(all_rows)))
    print("[落盘] %s" % out_jsonl)
    print("[汇总] %s" % sum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
