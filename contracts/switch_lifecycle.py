# -*- coding: utf-8 -*-
"""开关**出口制** —— 「加了就要有人收尸」的强制机制。

为什么需要这个文件（2026-10-31）
================================
`contracts/switch_registry.py` 解决了**入口**：新增开关必须四处同步、端到端验通。
它一个字都没规定**出口**。后果是可量化的 —— 用 133 个历史开关 + 103 个题次的
`diag.switch_snapshot` 回放：

  · 历史共出现 133 个开关，真正被删掉 **11 个（8%）**；
  · 现存 118 个（本地）/ 109 个（服务器，已分叉）里，**101 个在全部题次中值从未变过**；
  · 真正做过布尔 A/B 的只有 **4 个**（其中 2 个还是环境兜底，不是策略实验）；
  · 而注册表 doc 里**自己写着「=0 关闭做 A/B」的开关有 26 个** ⇒ 承诺 26、兑现 4。

根因不是执行不力，是**成本不对称 + 两类东西同装一个马甲**：

  · 加一个开关 = 注册表 1 行（30 秒）；删一个 = 改 4 个文件 + 过四表门禁（半小时）
    ⇒ 任何机制在这种梯度下都会单调增长；
  · 「需要 A/B 的实验开关」和「需要随时能关的应急闸刀」走完全相同的注册流程
    ⇒ 无法区分该删谁，于是谁都不删。

本文件引入**三类分治 + 到期强制**：

  ``gate``        应急闸刀。语义是「出问题能立刻关」，**永久保留，无出口义务**。
                  例：``lean_verify``、``five_gate_*``、``llm_timeout``。
  ``experiment``  为验证某个具体假设而加。**必须有出口**：``question``（验什么问题）、
                  ``expires``（什么时候必须给结论）、``decision``（给了没有）。
  ``config``      数值 / 字符串调节参数，不是策略分支。承认它恒定即可，不必假装是开关。

强制力来自两处，都是机械的、不靠自觉：

  1. ``audit()``：算出哪些 experiment 已过期未决、哪些承诺了 A/B 却没登记出口；
     ``tools/switch_lifecycle_audit.py`` 与 ``tests/test_switch_lifecycle_guard.py``
     消费它 ⇒ **过期就是红**。
  2. 存量宽限：``LEGACY_DEADLINE`` 之前只告警（存量大、一次补不完），
     之后转硬错误。**新增开关不受宽限**：过了这条线才加的 experiment，
     缺 ``expires`` 立即红。

设计上的克制（刻意不做的事）
============================
  · **不改** ``SWITCHES`` 的四元组结构。改动它要同步四表 + 全部消费点，
    为了加一个元数据字段冒这种风险不值得。生命周期是**独立表**，按名字关联。
  · **不追求一次归类完**。``infer_kind()`` 用命名与 doc 自动推断，
    ``LIFECYCLE`` 只登记例外 ⇒ 人工成本压在真正需要决策的那几十条上。
  · **不做「自动删开关」**。删代码必须有人看 diff；本文件只负责让"该处置了"
    这件事无法被忽略。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 类别
# ---------------------------------------------------------------------------
KIND_GATE = "gate"                  # 应急闸刀：永久保留，无出口义务
KIND_EXPERIMENT = "experiment"      # 实验：必须有出口
KIND_CONFIG = "config"              # 数值/字符串参数，不是策略分支
KIND_UNCLASSIFIED = "unclassified"  # 推断不出，需人工归类

ALL_KINDS = (KIND_GATE, KIND_EXPERIMENT, KIND_CONFIG, KIND_UNCLASSIFIED)

# 存量开关补登记的截止日。此前只告警，此后转硬错误。
# 选 11-15 的理由：11-01 配额恢复后第一跑，能给出现有实验的第一批真实数据；
# 半个月足够把「该删的删、该转正的转正」，又不至于拖成永久豁免。
LEGACY_DEADLINE = datetime.date(2026, 11, 15)

# experiment 未登记 expires 时的默认寿命（天）。从一个明确的 opened 起算。
DEFAULT_TTL_DAYS = 45

# ---------------------------------------------------------------------------
# 生命周期登记表 —— **只登记需要出口的（experiment）与推断需纠正的**
# ---------------------------------------------------------------------------
# 结构：field -> {
#   "kind":       KIND_*（缺省用 infer_kind 推断）
#   "opened":     "YYYY-MM-DD"  加入日期（= 开始欠出口义务的日期）
#   "question":   这句话在验证什么（必须是可否证的命题，不写"看看有没有用"）
#   "verify_by":  怎么验（实验设计 / 回放床 / 指标），写清"什么结果算哪一边"
#   "expires":    "YYYY-MM-DD"  必须给出结论的截止日
#   "decision":   "pending" | "kept" | "removed" | "superseded"
#   "evidence":   结论文本（decision != pending 时必填）
# }
#
# ★ 新增 experiment 而不登记 expires ⇒ 立刻硬错误（不受 LEGACY_DEADLINE 宽限）。
LIFECYCLE: Dict[str, Dict[str, Any]] = {
    # ---- 2026-10-31 清账：本轮自查出的 4 个「加了但拿不出有效性证据」的开关 ----
    # 全部登记为 pending 且已到期 ⇒ 上线当天就红，逼本轮给出处置。
    "blueprint_goal_kind_guidance": {
        "kind": KIND_EXPERIMENT,
        "opened": "2026-10-28",
        "question": "只判目标从句的 goal_kind 引导，能否减少 instance 题上的全称引理误建",
        "verify_by": "Omni8 / IMO112 固定蓝图回放，比全称引理数与 4.1 淘汰率",
        "expires": "2026-10-30",
        "decision": "pending",
        "evidence": "",
        "note": "账本 E09 实测：命中 Omni8 4 题 / IMO112 0 题，3 题实测与 10-27 一致 ⇒ 边际贡献 0",
    },
    "step_verification_audit": {
        "kind": KIND_EXPERIMENT,
        "opened": "2026-10-28",
        "question": "步级算术复核能否在不误杀的前提下抓到模型真算错",
        "verify_by": "1081 步历史回放，统计干预率与逐条人工复核准确率",
        "expires": "2026-10-30",
        "decision": "pending",
        "evidence": "",
        "note": "账本 E10 实测：干预率 0.28%（1081 步仅 3 次），远低于可观测门槛",
    },
    "bounded_search": {
        "kind": KIND_EXPERIMENT,
        "opened": "2026-10-29",
        "question": "有界 ∃ 机械搜索能否在通用题型上生效（不只 3556 这类整除题）",
        "verify_by": "全量 4428 题上 detect() 命中率 + 语义域覆盖率",
        "expires": "2026-10-30",
        "decision": "pending",
        "evidence": "",
        "note": "账本 E13 实测：detect 仅认 1/4428 = 0.02%，语义域 46/4428 = 1.0% ⇒ 已冻结降级",
    },
    "blueprint_merge_value_mask": {
        "kind": KIND_EXPERIMENT,
        "opened": "2026-10-28",
        "question": "归并/收尾阶段不带值掩码，能否减少蓝图节点直接断言答案值",
        "verify_by": "固定蓝图回放：统计归并节点的值字面量出现率（基线 merge 35/89、收尾 15/89）",
        "expires": "2026-10-30",
        "decision": "pending",
        "evidence": "",
        "note": "账本 E08：开关已上服务器，但从未比对开关前后同一批蓝图的断言率",
    },
}

# ---------------------------------------------------------------------------
# 自动推断（LIFECYCLE 未登记时用）
# ---------------------------------------------------------------------------
# 数值族：这些名字天然是参数，不该被当策略开关追出口。
_NUM_SUFFIX = (
    "_timeout", "_chars", "_rounds", "_limit", "_sec", "_depth", "_votes",
    "_threshold", "_ratio", "_count", "_top_k", "_floor", "_nodes", "_max_chars",
)

# 应急/基建族：名字前缀即语义（能关、关了就换一条已知路径），永久保留。
_GATE_PREFIX = (
    "five_gate_", "lean_", "enable_lean", "llm_", "toolcall_", "enable_",
)

# 评测口径族：影响的是「怎么算分/怎么切题」，不是 agent 运行时行为，
# 没有 A/B 语义（改了只影响判分，不影响解题）⇒ 归参数。
_EVAL_PREFIX = ("eval_",)
_EVAL_EXACT = {"mp_arm"}


def _has_ab_claim(doc: str) -> bool:
    """doc 里是否自称可做 A/B —— 注册表自己的承诺，出口制据此追账。"""
    d = doc or ""
    return ("A/B" in d) or ("a/b" in d) or ("A／B" in d)


def infer_kind(field: str, kind: str, default: Any, doc: str) -> str:
    """按 字段类型 / 命名 / doc 推断类别（不含 LIFECYCLE 人工登记）。

    ``kind`` 是注册表里的取值类型（bool / num / int / str），不是生命周期类别。

    判定顺序（★ 顺序本身是设计：越靠前越硬，不依赖 doc 的自由文本）：

      1. 数值类型 / 数值命名 ⇒ ``config``（参数不是策略分支）
      2. 评测口径族（``eval_*`` / ``mp_arm``）⇒ ``config``（只影响判分，不影响解题）
      3. 应急/基建命名族（``five_gate_*`` / ``lean_*`` / ``enable_*`` / 名字含 ``_gate``）
         ⇒ ``gate``
      4. doc 自称可做 A/B ⇒ ``experiment``
      5. doc 自述可回退/关闭 ⇒ ``gate``
      6. 其余 ⇒ ``unclassified``（人工指定）

    ★ 为什么第 3 步在「自称 A/B」之前：闸刀族的 doc 里几乎都带一句「=0 关闭做 A/B」，
      那是**注册模板的套话**，不是真的验证承诺（实测 36 个带此句，真做过 4 个）。
      语义上闸刀就是闸刀 —— 它的用途是出问题能立刻关，不是为了验证假设。
      真正该被追账的是**非闸刀族里自称要 A/B 的功能改动**（如 ``blueprint_merge_value_mask``）。
    """
    # 1) 数值类型直接是参数
    if kind in ("num", "int"):
        return KIND_CONFIG
    if field.endswith(_NUM_SUFFIX):
        return KIND_CONFIG
    # 2) 评测口径族
    if field.startswith(_EVAL_PREFIX) or field in _EVAL_EXACT:
        return KIND_CONFIG
    # 3) 应急/基建族（先于「自称 A/B」：闸刀的 doc 套话不算验证承诺）
    if field.startswith(_GATE_PREFIX) or "_gate" in field:
        return KIND_GATE
    # 4) 自称可做 A/B ⇒ 这是实验（★ 追账主来源）
    if _has_ab_claim(doc):
        return KIND_EXPERIMENT
    # 5) doc 自述可回退 ⇒ 当闸刀
    d = doc or ""
    if "回退" in d or "关闭" in d:
        return KIND_GATE
    return KIND_UNCLASSIFIED


def lifecycle_of(field: str, switches: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """取某开关的生命周期条目：LIFECYCLE 登记的优先，否则纯推断。

    返回字典恒含 ``kind`` / ``registered``（是否人工登记过）/ ``source``（human|inferred）。
    """
    if switches is None:
        from contracts.switch_registry import SWITCHES as switches  # 延迟导入，避免环

    if field not in switches:
        # 幽灵条目：登记了但注册表里没有
        entry = dict(LIFECYCLE.get(field) or {})
        entry.update({"field": field, "kind": entry.get("kind", KIND_UNCLASSIFIED),
                      "registered": field in LIFECYCLE, "source": "ghost",
                      "in_registry": False})
        return entry

    _env, val_kind, default, doc = switches[field]
    inferred = infer_kind(field, val_kind, default, doc)
    reg = LIFECYCLE.get(field)
    out: Dict[str, Any] = {
        "field": field,
        "in_registry": True,
        "registered": reg is not None,
        "inferred_kind": inferred,
        "source": "human" if reg else "inferred",
    }
    if reg:
        out.update(reg)
        out.setdefault("kind", inferred)
    else:
        out["kind"] = inferred
    return out


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def _parse_date(s: Any) -> Optional[datetime.date]:
    if not s:
        return None
    if isinstance(s, datetime.date):
        return s
    try:
        return datetime.date.fromisoformat(str(s).strip())
    except (TypeError, ValueError):
        return None


def audit(today: Optional[datetime.date] = None,
          switches: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """全量审计，返回结构化报告（**不抛异常**，便于门禁/报告复用）。

    报告字段：
      ``counts``     各类别数量
      ``expired``    已过期且 decision==pending 的 experiment（每条含天数）
      ``incomplete`` experiment 缺 question / verify_by / expires / opened
      ``ghosts``     LIFECYCLE 有、注册表已无（删了开关但没销账）
      ``unclassified`` 推断不出类别的开关
      ``ab_claimed_untracked`` doc 自称 A/B 但未登记出口的 experiment
      ``errors`` / ``warnings``  最终判定用的字符串列表
    """
    if switches is None:
        from contracts.switch_registry import SWITCHES as switches  # noqa: F811

    today = today or datetime.date.today()

    counts: Dict[str, int] = {k: 0 for k in ALL_KINDS}
    expired: List[Dict[str, Any]] = []
    incomplete: List[Dict[str, Any]] = []
    ghosts: List[str] = []
    unclassified: List[str] = []
    ab_untracked: List[str] = []

    for field in sorted(switches):
        lc = lifecycle_of(field, switches)
        kind = lc.get("kind") or KIND_UNCLASSIFIED
        counts[kind] = counts.get(kind, 0) + 1

        if kind == KIND_UNCLASSIFIED:
            unclassified.append(field)
            continue
        if kind != KIND_EXPERIMENT:
            continue

        # --- experiment 的出口义务 ---
        missing = [k for k in ("opened", "question", "verify_by", "expires")
                   if not lc.get(k)]
        decision = str(lc.get("decision") or "pending").lower()

        if lc.get("registered") and missing:
            incomplete.append({"field": field, "missing": missing})
            continue

        if not lc.get("registered"):
            # 推断出来的实验、没登记 ⇒ 承诺了 A/B 却没出口
            ab_untracked.append(field)
            continue

        if decision == "pending":
            exp = _parse_date(lc.get("expires"))
            if exp is None:
                incomplete.append({"field": field, "missing": ["expires"]})
            elif exp < today:
                expired.append({
                    "field": field,
                    "expires": exp.isoformat(),
                    "overdue_days": (today - exp).days,
                    "question": lc.get("question") or "",
                })
        elif not str(lc.get("evidence") or "").strip():
            # 有结论但没留证据 ⇒ 等于没结
            incomplete.append({"field": field, "missing": ["evidence(decision!=pending)"]})

    # 幽灵：登记了但注册表已无
    for field in sorted(LIFECYCLE):
        if field not in switches:
            ghosts.append(field)

    errors: List[str] = []
    warnings: List[str] = []

    for e in expired:
        errors.append(
            "实验开关已过期未决：%s（expires %s，逾期 %d 天）—— 验的是「%s」"
            % (e["field"], e["expires"], e["overdue_days"], e["question"])
        )
    for it in incomplete:
        errors.append("实验开关出口登记不全：%s 缺 %s" % (it["field"], "、".join(it["missing"])))
    for g in ghosts:
        errors.append("幽灵登记：%s 已在注册表删除，但 LIFECYCLE 未销账" % g)

    for f in ab_untracked:
        warnings.append("doc 自称可做 A/B 但未登记出口：%s" % f)
    for f in unclassified:
        warnings.append("无法自动归类，需人工指定 kind：%s" % f)

    # 存量宽限：截止日之前，未登记的 experiment 只告警；之后转硬错误
    legacy_passed = today >= LEGACY_DEADLINE
    if legacy_passed:
        for f in ab_untracked:
            errors.append("存量宽限已过（%s），实验开关必须登记出口：%s"
                          % (LEGACY_DEADLINE.isoformat(), f))

    return {
        "today": today.isoformat(),
        "legacy_deadline": LEGACY_DEADLINE.isoformat(),
        "legacy_passed": legacy_passed,
        "total": len(switches),
        "counts": counts,
        "expired": expired,
        "incomplete": incomplete,
        "ghosts": ghosts,
        "unclassified": unclassified,
        "ab_claimed_untracked": ab_untracked,
        "errors": errors,
        "warnings": warnings,
    }


def format_report(report: Dict[str, Any], limit: int = 200) -> str:
    """人读报告（CLI 与失败信息共用，保证两处口径一致）。"""
    c = report["counts"]
    lines = [
        "开关出口审计 · %s（存量宽限截止 %s，%s）"
        % (report["today"], report["legacy_deadline"],
           "已过" if report["legacy_passed"] else "未到"),
        "总计 %d 个：闸刀 %d / 实验 %d / 参数 %d / 待归类 %d"
        % (report["total"], c.get(KIND_GATE, 0), c.get(KIND_EXPERIMENT, 0),
           c.get(KIND_CONFIG, 0), c.get(KIND_UNCLASSIFIED, 0)),
    ]
    if report["expired"]:
        lines.append("")
        lines.append("■ 过期未决（%d）" % len(report["expired"]))
        for e in report["expired"][:limit]:
            lines.append("  ✗ %-40s 逾期 %3d 天  「%s」"
                         % (e["field"], e["overdue_days"], e["question"][:40]))
    if report["incomplete"]:
        lines.append("")
        lines.append("■ 出口登记不全（%d）" % len(report["incomplete"]))
        for it in report["incomplete"][:limit]:
            lines.append("  ✗ %-40s 缺 %s" % (it["field"], "、".join(it["missing"])))
    if report["ghosts"]:
        lines.append("")
        lines.append("■ 幽灵登记（%d）" % len(report["ghosts"]))
        for g in report["ghosts"][:limit]:
            lines.append("  ✗ %s" % g)
    if report["ab_claimed_untracked"]:
        lines.append("")
        lines.append("■ 自称可 A/B 但无出口（%d）" % len(report["ab_claimed_untracked"]))
        for f in report["ab_claimed_untracked"][:limit]:
            lines.append("  ! %s" % f)
    if report["unclassified"]:
        lines.append("")
        lines.append("■ 待归类（%d）" % len(report["unclassified"]))
        for f in report["unclassified"][:limit]:
            lines.append("  ! %s" % f)
    lines.append("")
    lines.append("结论：%d 个错误 / %d 个告警" % (len(report["errors"]), len(report["warnings"])))
    return "\n".join(lines)
