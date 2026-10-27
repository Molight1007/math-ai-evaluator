# -*- coding: utf-8 -*-
"""L4 critic —— 候选 diff 的三条硬规则（评测前拦，越界的候选不花一次评测）。

在三体架构里的位置
==================
    L3 提案（只出 A 档候选）→ **L4 critic（本模块）** → 评测 → δ/四道门 → L5 账本

`docs/三体架构_v1.md` §5：因为我们的编辑面是**结构化参数**（不是代码 diff），
泄漏筛可以砍成三条**确定性规则**，不需要 RRSI 那套 LLM 六条 REJECT：
既快（毫秒级）、又确定（同一候选永远同一结论）、还不花钱。

三条规则（任何一条不过 ⇒ 拒绝，且**必须给出理由**，禁静默）
==========================================================
  R1 `key_whitelist`  key 必须在 `params.json` 的 a 段里（防模型发明参数；
                      发明出来的键注进去也会被覆盖白名单静默丢弃 = 假 A/B）
  R2 `value_domain`   类型必须一致 + 落在声明域内（域只收「语义上不可能对」的边界，
                      不是"我猜的合理区间"；没声明域的按类型+非负性兜底）
  R3 `no_task_leak`   候选全文不得出现题号/标准答案/数据集痕迹（对应 R6）——
                      否则候选可以「记住这道题」，评测分虚高并污染后续轮次

边界诚实说明
============
R3 是**预筛**，不是证明：它挡的是明显的题号/答案/题库名泄漏。
真正的保证靠两件事：① B 档改动必须人审；② 账本记 `predicted_affected` +
`retroactive_check`，事后可核"它是不是只对某几道题有效"。

用法
====
    from contracts.params_guard import review_edits, review_candidate, diff_edits

    base = load("params.json")
    verdict = review_edits([{"key": "policy_sample_times", "to": 3}], base)
    if not verdict["passed"]:
        ...  # verdict["violations"] 逐条带 rule/key/msg

    # 或者直接比两份 params.json（候选 = 打过 patch 的文件）
    verdict = review_candidate(base, load("cand.json"))
"""
from __future__ import annotations

import json
import re

SCHEMA = "params_guard/1"

# ---------------------------------------------------------------- 值域
# 只写「越过去在语义上就不成立」的边界，不写"我猜的合理区间"。
_COUNT_RE = re.compile(
    r"(rounds|times|calls|attempts|votes|retry|retries|regen|rework|depth|limit|stop|count)$"
    r"|(^|_)max(_|$)|_n$")
_BUDGET_RE = re.compile(r"(tokens|seconds|secs|sec|chars|timeout|budget|remaining)")


def _num_domain(key: str, current) -> dict:
    """按名字给数值域。返回 {min, max, why, source}；未命中给 None 边界（只查类型）。"""
    k = key.lower()
    if "temperature" in k:
        return {"min": 0.0, "max": 2.0, "why": "温度语义上限 2.0", "source": "semantic"}
    if any(t in k for t in ("ratio", "confidence", "threshold", "alpha", "beta")) \
            and isinstance(current, (int, float)) and not isinstance(current, bool) \
            and 0 <= current <= 1:
        return {"min": 0.0, "max": 1.0, "why": "比例/置信度/阈值在 [0,1]", "source": "semantic"}
    if _COUNT_RE.search(k):
        return {"min": 0, "max": None, "why": "计数/轮数/上限不能为负", "source": "semantic"}
    if _BUDGET_RE.search(k):
        return {"min": 0, "max": None, "why": "token/时间/字符预算不能为负", "source": "semantic"}
    if isinstance(current, (int, float)) and not isinstance(current, bool) and current >= 0:
        return {"min": 0, "max": None, "why": "当前值非负 ⇒ 该参数不接受负数", "source": "inferred"}
    return {"min": None, "max": None, "why": "未声明域，仅校验类型", "source": "type_only"}


def domain_of(key: str, current) -> dict:
    """公开给提案器/报告用的域描述（同一份口径，避免两处不一致）。"""
    if isinstance(current, bool):
        return {"kind": "bool", "min": None, "max": None,
                "why": "布尔开关", "source": "semantic"}
    if isinstance(current, (int, float)):
        d = dict(_num_domain(key, current))
        d["kind"] = "number"
        return d
    if isinstance(current, str):
        return {"kind": "str", "min": None, "max": None,
                "why": "字符串，未声明枚举（只能类型校验）", "source": "type_only"}
    return {"kind": type(current).__name__, "min": None, "max": None,
            "why": "非标量不该出现在 A 段", "source": "type_only"}


def _type_ok(current, new) -> bool:
    """bool 与 int 在 Python 里是子类关系，必须显式区分（否则 True→1 会被放过）。"""
    if isinstance(current, bool):
        return isinstance(new, bool)
    if isinstance(current, int):
        return isinstance(new, int) and not isinstance(new, bool)
    if isinstance(current, float):
        return isinstance(new, (int, float)) and not isinstance(new, bool)
    return type(new) is type(current)


def _domain_ok(key: str, current, new) -> tuple:
    """返回 (ok, 原因)。"""
    if not _type_ok(current, new):
        return False, "类型不符：当前 %s(%r) → 候选 %s(%r)" % (
            type(current).__name__, current, type(new).__name__, new)
    # 有些配置字段声明成 str、实际存的是 JSON（如 theorem_hint_top_k_by_stage）。
    # 这类值给一段坏 JSON 会在运行期炸，且不在类型检查覆盖内 ⇒ 这里先卡形状。
    if isinstance(current, str) and current.strip()[:1] in ("{", "["):
        try:
            base_obj = json.loads(current)
        except ValueError:
            base_obj = None
        if base_obj is not None:
            try:
                new_obj = json.loads(new)
            except ValueError:
                return False, "%s 是 JSON 编码值，候选不是合法 JSON" % key
            if type(new_obj) is not type(base_obj):
                return False, "%s 的 JSON 形状不符（应为 %s）" % (
                    key, type(base_obj).__name__)
    dom = domain_of(key, current)
    if dom["min"] is not None and new < dom["min"]:
        return False, "%s 低于下界 %s（%s）" % (key, dom["min"], dom["why"])
    if dom["max"] is not None and new > dom["max"]:
        return False, "%s 高于上界 %s（%s）" % (key, dom["max"], dom["why"])
    return True, ""


# ---------------------------------------------------------------- 泄漏筛
# 只写「出现就基本可以断定是在写死某道题」的模式；宁可漏，不要误杀正常中文描述。
LEAK_PATTERNS = (
    (r"official[\s_-]*112", "数据集名（official112）"),
    (r"题库|\.jsonl\b", "题库/题单文件痕迹"),
    (r"\bsmoke\d+\b", "题单名（smokeN）"),
    (r"\bq(?:id|uestion)?[\s_:-]*\d{2,}\b", "题号（q123 / qid:123）"),
    (r"题\s*\d{2,}", "题号（题 123）"),
    (r"\bgold\b|标准答案", "金标/标准答案"),
    (r"answer\s*[:=]\s*\S", "答案赋值"),
)
_LEAK_RE = tuple((re.compile(p, re.I), why) for p, why in LEAK_PATTERNS)


def scan_leak(text: str) -> list:
    """返回 [(pattern, 说明, 命中片段)]；空 = 未命中。"""
    out = []
    if not text:
        return out
    for rx, why in _LEAK_RE:
        m = rx.search(text)
        if m:
            out.append((rx.pattern, why, m.group(0)[:60]))
    return out


# ---------------------------------------------------------------- 主入口
def _as_edits(edits) -> list:
    out = []
    for e in edits or []:
        if not isinstance(e, dict):
            continue
        if "key" not in e or "to" not in e:
            continue
        out.append({"key": str(e["key"]), "to": e["to"], "from": e.get("from")})
    return out


def review_edits(edits, base_doc: dict, scan_text: str = "",
                 require_nonempty: bool = True) -> dict:
    """三条硬规则逐条审。返回 {schema, passed, violations, n_edits, noop, empty}。

    `scan_text` 传候选原文（hypothesis/说明等自由文本）时一并做泄漏筛；
    不传则只筛 key 名与字符串值。
    `require_nonempty=True`（提案入口）：空候选视为违规 —— 否则会白烧一次评测。
    `review_candidate` 传 False：候选文件与基线一致是"无改动"，由调用方看 n_edits。
    """
    a = (base_doc or {}).get("a") or {}
    vs = []
    rows = _as_edits(edits)
    if not rows and require_nonempty:
        vs.append({"rule": "key_whitelist", "key": "", "msg": "没有可审的 edit（空候选）"})
    for e in rows:
        key, new = e["key"], e["to"]
        # R1 白名单
        if key not in a:
            vs.append({"rule": "key_whitelist", "key": key,
                       "msg": "不在 params.json 的 A 段（发明参数 / 非机器可改项）"})
            continue
        cur = a[key].get("value")
        # R2 值域
        ok, why = _domain_ok(key, cur, new)
        if not ok:
            vs.append({"rule": "value_domain", "key": key, "msg": why})
        # 同值不算违规，但记一条 note（提案无效，不是泄漏）
        if new == cur:
            e["noop"] = True
    # R3 泄漏
    text = (scan_text or "") + "\n" + "\n".join(
        "%s=%r" % (e["key"], e["to"]) for e in rows if isinstance(e["to"], str))
    for pat, why, hit in scan_leak(text):
        vs.append({"rule": "no_task_leak", "key": "", "msg": "%s —— 命中 %r" % (why, hit)})
    notes = [e["key"] for e in rows if e.get("noop")]
    return {"schema": SCHEMA, "passed": not vs, "violations": vs,
            "n_edits": len(rows), "noop": notes, "empty": not rows}


def diff_edits(base_doc: dict, cand_doc: dict) -> list:
    """两份 params.json 的 A 段差异 → edits 列表（候选 = 打过 patch 的文件时用）。"""
    ao = (base_doc or {}).get("a") or {}
    an = (cand_doc or {}).get("a") or {}
    out = []
    for k in sorted(set(ao) | set(an)):
        if k not in ao:
            out.append({"key": k, "to": (an.get(k) or {}).get("value"), "from": None})
            continue
        if k not in an:
            out.append({"key": k, "to": None, "from": ao[k].get("value")})
            continue
        v0 = ao[k].get("value")
        v1 = an[k].get("value")
        if v0 != v1:
            out.append({"key": k, "to": v1, "from": v0})
    return out


def review_candidate(base_doc: dict, cand_doc: dict) -> dict:
    """候选文件入口：先 diff 再走三条规则。

    ⚠ `to=None`（候选里删掉了某个 A 键）一律拒绝：A 段是白名单，删键等于让
      注入层少一个值，后续 diff 无从解释。
    """
    edits = diff_edits(base_doc, cand_doc)
    bad = [e for e in edits if e["to"] is None]
    v = review_edits([e for e in edits if e["to"] is not None], base_doc,
                     require_nonempty=False)
    for e in bad:
        v["violations"].append({"rule": "key_whitelist", "key": e["key"],
                                "msg": "候选删掉了基线里的 A 键（A 段只能改值，不能删键）"})
    if v["violations"]:
        v["passed"] = False
    return v
