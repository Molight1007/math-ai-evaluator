# -*- coding: utf-8 -*-
"""E21 回放：蓝图节点「许可证机制」违规率，及其对最终失败的预测力。

背景（为什么做这个）
------------------
诊断 P0：系统把「搜索」当「演绎」做 —— 蓝图节点可以直接写下
`a_n = n+1` / `必须等于 2026` 这种**已被断言的值**，然后下游所有阶段
都把它当已知事实使用。文献侧（Saparov & He 2022 "greedy reasoners"；
Lean 系的 `have h : P := by sorry` 许可证机制）给出的修法是：

    节点只能声明「命题 + 未闭合前提清单」，
    下游只能引用**已闭合**的节点。

本脚本**不改生产代码**，只在历史产物上做 δ=0 确定性回放（0 LLM / 0 配额），
回答两个问题：

  Q1 按许可证规则重放，多少节点会被标红？（违规率）
  Q2 标红率能否区分判对 / 判错的题？（预测力）

数据来源（服务器，只读）
--------------------
    results/<run_id>/<qid>/02_blueprint.json       蓝图（nodes[]）
    results/<run_id>/<qid>/03_subgoals.json        子目标（plan.subgoals[]）
    results/<run_id>/<qid>/04_subgoal_results.jsonl 求解结果（含 objective_verdict）
    results/<run_id>/<qid>/08_final.json           最终回应（常为空）
    results/*.jsonl                                 判对标记 correct

★ qid 规则：`"q" + md5(question)[:8]`（见 agent/artifact_store.py::_qid_from_problem）
★ run 目录 ↔ jsonl 的配对：run 目录内**最晚文件 mtime** 与 jsonl mtime 相差 <1s
  （实测 20261027-232401 的最晚文件 10:32:09.701 ↔ ab_on mtime 10:32:09.970），
  仅用文件名时间戳是配不上的（on/off 两臂同时起跑）。

违规类型（标红口径，全部是确定性文本/结构判定，不含任何模型判断）
------------------------------------------------------------
  R1_REF_UNKNOWN     inputs 引用了蓝图里不存在的节点 id
  R2_DOWNSTREAM_UNCLOSED
                     inputs 引用了**未闭合**节点 —— 「用了没证出来的东西」
                     （★ 核心违规，等价于 Lean 里引用一个还是 sorry 的引理）
  R3_SILENT_DEP      statement 正文提到 `n<数字>` 引用，但 inputs 没列出来
                     （蓝图在偷偷使用别的东西，依赖没进清单）
  R4_VALUE_ASSERT    statement 直接断言具体值（`X = 数字`），不带推导动词
                     —— 这就是「把搜索当演绎」在文本上的指纹
  R5_NO_HARD_CLOSE   题级：整道题**没有任何一个**节点是强闭合的
                     （强闭合 = 工具真跑过并判通过，即 tool_ran=True）

闭合层级（三级，严格程度递减）
--------------------------
  HARD_CLOSED   tool_ran=True 且 tool_verdict 非失败  ← 唯一不可贿赂的
  SOFT_CLOSED   objective_verdict == "correct" 且有推导正文（LLM 判 LLM）
  OPEN          incorrect / undecided / None / 无对应子目标

用法
----
  python replay_blueprint_license.py                     # 汇总
  python replay_blueprint_license.py --json out.json     # 落盘明细
  python replay_blueprint_license.py --show q10a65b3d    # 单题逐节点
  python replay_blueprint_license.py --bad               # 只看有违规的题

首次回放结果（2026-10-31，109 题次 / 919 节点，服务器历史产物）
------------------------------------------------------------
1. **HARD_CLOSED = 0 / 448**（能配上子目标的节点里），`R5_NO_HARD_CLOSE`
   **109/109 = 100%** ⇒ 系统从未产生过一次「工具跑过并判通过」的闭合。
   这是 P0 的实体，且是构造性事实，不需要统计检验。
2. **时序断点在 10-15**：那天之前 46 题次没有 `03_subgoals.json`
   （`子=0`），闭合状态**不可判定**；那天起 R2 覆盖率 76~100%。
   ⇒ **不能把 109 题次合并统计**，否则 0% 与 90% 会被平均成 34%。
3. 合并统计时所有指标都不显著（标红率 31.5 vs 38.3，p=0.125）；
   **只在可判定的 54 题次上**才出现信号：标红率 36.5 vs 55.5，
   Mann-Whitney 单侧 p=0.004（Bonferroni×8 后 0.032）；R2 个数 1.9 vs 3.4，p=0.004。
   ★ 但这是**事后分层**（先看到不显著、再去找分层依据）⇒ 只能当
   **待复现假设**，不能当结论。预注册复现后才能用于判断。
4. R4「直接断言值」对口径极度敏感：严口径（整句无推导词）4.5%，
   宽口径（剥掉推导词）32.4%。**7 倍差** ⇒ 任何引用单一百分比的说法都站不住。
   ★ 这直接影响历史结论：此前记录的「25.7% 蓝图节点直接断言值」
   是宽口径且含题设方程假阳性（`由 x^2+y^2+z^2=3 建立…` 曾被算成断言），
   **不应再作为证据引用**。
"""

from __future__ import print_function

import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys

# ------------------------------------------------------------------ 常量

# 推导/承接动词：出现这些说明该节点在「推」而不是「断言」
# ★ 口径要点：只要整句出现推导词，就**不算**直接断言 —— 因为「由 n1 可得
#   a_n=n+1」是推导，「a_n=n+1」才是断言。不做「剥掉推导词再看」，
#   那会把「由 x^2+y^2+z^2=3 建立范围约束」里的**题设方程**误判成断言值
#   （实测 q03d3e039 n1 就是这个假阳性）。
_DERIVE_WORDS = (
    u"证明", u"由", u"设", u"可得", u"推出", u"代入", u"利用", u"根据",
    u"假设", u"令", u"若", u"则", u"因此", u"从而", u"构造", u"归纳",
    u"验证", u"计算", u"求", u"确定", u"讨论", u"分类", u"考虑", u"建立",
    u"考察", u"定义", u"反证", u"已知", u"满足", u"得到", u"汇总", u"合并",
    u"统计", u"枚举", u"检查", u"化简", u"整理",
    # 英文（蓝图有相当比例直接用英文写）
    "derive", "deduce", "prove", "proving", "show", "shows", "using", "use",
    "assume", "let", "set", "compute", "computing", "verify", "classify",
    "establish", "follows", "since", "because", "given", "suppose", "apply",
    "check", "obtain", "yields", "get", "substitute", "rewrite", "consider",
    "determine", "find", "calculate", "evaluate", "confirm", "combine",
)

# 明确的「结论性断言」标记：出现这些，即便带推导词也算断言
_ASSERT_MARKERS = (u"必须等于", u"必为", u"答案就是", u"答案即", "must equal",
                   "must be", "the answer is", "equals exactly")

# 「<简单左式> = <任意非空右式>」= 给一个量赋值。
# 左式必须是**单一符号**（可带参数/下标：`C(1)`、`a_n`、`T`），而不是算式
# （`x^2+y^2+z^2`、`2+2` 不算赋值）。这样 `a_n = n+1` 能抓到，
# 而题设方程 `x^2+y^2+z^2=3` 与算式 `2+2=4` 不会被当成「断言了某个值」。
_LHS = r"(?:[A-Za-z][A-Za-z0-9_]{0,15}(?:\s*\([^()]{0,24}\))?(?:_\{?[A-Za-z0-9]{1,8}\}?)?)"
_VALUE_EQ_RE = re.compile(_LHS + r"\s*=\s*\S")

# statement 里对其它节点的引用（n1, n2, ...；也认 N1 与「节点1」）
_NODE_REF_RE = re.compile(r"(?<![A-Za-z_])(?:n|N)(\d{1,2})(?![\d])")

# 子目标标题前缀「子目标3: 」
_TITLE_PREFIX_RE = re.compile(r"^子目标\s*\d+\s*[:：]\s*")

# 强闭合：tool_ran=True 且 verdict 不是明确的失败
_FAIL_WORDS = (u"fail", u"error", u"失败", u"错", u"unknown", u"timeout")


# ------------------------------------------------------------------ 基础工具

def _norm(s):
    """文本归一化（只做比较用，不改原文）。"""
    if s is None:
        return u""
    s = u"%s" % (s,)
    s = re.sub(r"[\s\u3000]+", u" ", s)
    s = s.replace(u"：", u":").replace(u"，", u",").replace(u"（", u"(").replace(u"）", u")")
    return s.strip()


def _qid_from_question(q):
    try:
        return "q" + hashlib.md5(("%s" % (q,)).encode("utf-8")).hexdigest()[:8]
    except Exception:
        return "q0"


def _load_json(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(p):
    out = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _newest_mtime(d):
    """目录内最晚文件 mtime；无文件返回 None。"""
    best = None
    for path in glob.glob(os.path.join(d, "*")):
        try:
            m = os.path.getmtime(path)
        except OSError:
            continue
        if best is None or m > best:
            best = m
    return best


# ------------------------------------------------------------------ 索引：qid → correct

def build_label_index(results_dir):
    """qid → [(run_name, id, correct)]；同时给出 run 目录 → jsonl 的配对表。"""
    rows = []
    jsonls = sorted(glob.glob(os.path.join(results_dir, "*.jsonl")))
    for p in jsonls:
        for d in _load_jsonl(p):
            if not d.get("question"):
                continue
            rows.append({
                "jsonl": os.path.basename(p)[:-6],
                "path": p,
                "qid": _qid_from_question(d.get("question")),
                "id": d.get("id"),
                "correct": d.get("correct"),
            })

    by_qid = collections.defaultdict(list)
    by_jsonl_qid = collections.defaultdict(dict)
    for r in rows:
        by_qid[r["qid"]].append(r)
        by_jsonl_qid[r["jsonl"]][r["qid"]] = r

    # run 目录 → jsonl（mtime 最近且差距 < tol）
    run_dirs = []
    for d in sorted(glob.glob(os.path.join(results_dir, "2*"))):
        if not os.path.isdir(d):
            continue
        mt = _newest_mtime(d)
        if mt is not None:
            run_dirs.append((os.path.basename(d), d, mt))

    jsonl_mtime = {}
    for p in jsonls:
        try:
            jsonl_mtime[p] = os.path.getmtime(p)
        except OSError:
            pass

    run_to_jsonl = {}
    for name, d, mt in run_dirs:
        best, bestdiff = None, None
        for p, jm in jsonl_mtime.items():
            diff = abs(jm - mt)
            if bestdiff is None or diff < bestdiff:
                best, bestdiff = p, diff
        if best is not None and bestdiff is not None and bestdiff < 120.0:
            run_to_jsonl[name] = (os.path.basename(best)[:-6], bestdiff)

    return by_qid, by_jsonl_qid, run_to_jsonl


def label_for(by_qid, by_jsonl_qid, run_name, qid, jsonl_name):
    """(correct, source) —— 优先用本 run 精确配对到的 jsonl，再退回稳定标签。

    ★ 不能只按 qid 全局查：同一道题会跨 run 重复出现（ab_on / ab_off 两臂、
      重跑轮次），全局查会把「同一题一次对一次错」判成 mixed 而整题丢弃。
      实测这条让可用标签从 45/109 提高到接近全量。
    """
    # 1) 本 run 精确配到的 jsonl 里直接查
    if jsonl_name:
        hit = (by_jsonl_qid.get(jsonl_name) or {}).get(qid)
        if hit is not None:
            return hit["correct"], "paired:" + jsonl_name
    # 2) 该 qid 全局唯一 → 可信
    cands = by_qid.get(qid) or []
    if len(cands) == 1:
        return cands[0]["correct"], "unique:" + cands[0]["jsonl"]
    # 3) 多臂出现：全部同向才用，混合则弃（不要用多数票，E14 铁律②）
    vals = set(c["correct"] for c in cands)
    if vals == {True}:
        return True, "all_true:%d" % len(cands)
    if vals == {False}:
        return False, "all_false:%d" % len(cands)
    return None, "mixed:%d" % len(cands)


# ------------------------------------------------------------------ 节点 ↔ 子目标配对

def map_nodes_to_subgoals(nodes, subgoals, root_id):
    """返回 {node_id: subgoal_dict or None} 与 match_method 统计。

    优先文本匹配（normalized statement == description 或去前缀后的 title），
    失败则退回落位（去掉 root 后按序），并记录配对方式以供审计。
    """
    by_text = {}
    for s in subgoals:
        for key in (_norm(s.get("description")),
                    _norm(_TITLE_PREFIX_RE.sub("", str(s.get("title") or "")))):
            if key:
                by_text.setdefault(key, s)

    out = {}
    method = collections.Counter()
    n_sg = len(subgoals)
    ordered = [n for n in nodes if n.get("id") != root_id]

    for i, nd in enumerate(ordered):
        st = _norm(nd.get("statement"))
        hit = by_text.get(st) if st else None
        if hit is None:
            method["position"] += 1
            hit = subgoals[i] if i < n_sg else None
            if hit is None:
                method["unmatched"] += 1
        else:
            method["text"] += 1
        out[nd.get("id")] = hit
    return out, method


def closure_of(sg):
    """子目标的闭合层级 + 依据。

    ★ UNMAPPED 单列，**不计入闭合率分母**：早期一批蓝图根本没有
      `03_subgoals.json`（n_subgoals=0），把它们的节点算成「OPEN」会让
      闭合率虚高（实测 109 题次里有 20+ 个 `子=0`）。
    """
    if not sg:
        return "UNMAPPED", "no_subgoal"
    tool_ran = sg.get("tool_ran")
    tv = ("%s" % (sg.get("tool_verdict") or "")).lower()
    if tool_ran is True and not any(w in tv for w in _FAIL_WORDS):
        return "HARD_CLOSED", "tool_ran=True"
    ov = sg.get("objective_verdict")
    has_drv = sg.get("has_derivation")
    if ov == "correct" and has_drv is not False:
        return "SOFT_CLOSED", "objective_verdict=correct"
    return "OPEN", "objective_verdict=%s has_derivation=%s" % (ov, has_drv)


# ------------------------------------------------------------------ 单题分析

def analyze_question(qdir, root_id_override=None):
    bp = _load_json(os.path.join(qdir, "02_blueprint.json"))
    if not bp or not bp.get("nodes"):
        return None
    sgpack = _load_json(os.path.join(qdir, "03_subgoals.json")) or {}
    subgoals = ((sgpack.get("plan") or {}).get("subgoals")) or []

    # 04 覆盖 03（04 是最终落盘结果，字段更全）
    sg_by_id = {}
    for s in _load_jsonl(os.path.join(qdir, "04_subgoal_results.jsonl")):
        sg_by_id[s.get("id")] = s
    if not sg_by_id:
        for s in subgoals:
            sg_by_id[s.get("id")] = s

    root_id = root_id_override or bp.get("root_id") or (bp["nodes"][0].get("id") if bp["nodes"] else None)
    nodes = bp["nodes"]
    sgmap, match_method = map_nodes_to_subgoals(nodes, subgoals, root_id)

    ids = set(n.get("id") for n in nodes)
    order = {n.get("id"): i for i, n in enumerate(nodes)}

    # 先算全部闭合状态（R2 需要跨节点查）
    # ★ 两套数据分工：03_subgoals 只用于**文本匹配**（拿 id），
    #   闭合判定必须用 04_subgoal_results（只有它带 tool_ran / objective_verdict）。
    #   混用会让 HARD_CLOSED 恒为 0（04 才是最终落盘结果）。
    closure = {}
    for nd in nodes:
        nid = nd.get("id")
        sg3 = sgmap.get(nid)
        sg = sg_by_id.get(sg3.get("id")) if sg3 else None
        lvl, why = closure_of(sg)
        closure[nid] = (lvl, why, sg)

    node_rows = []
    value_assert = {}
    value_assert_loose = {}
    for nd in nodes:
        nid = nd.get("id")
        if nid == root_id:
            continue
        st = nd.get("statement") or ""
        inputs = list(nd.get("inputs") or [])
        lvl, why, sg = closure[nid]

        viol = []

        # R1 引用不存在的节点
        for ref in inputs:
            if ref not in ids:
                viol.append("R1_REF_UNKNOWN")

        # R3 正文提到节点但 inputs 未声明
        mentioned = set("n" + m for m in _NODE_REF_RE.findall(st))
        silent = [r for r in mentioned if r not in inputs and r in ids and r != nid]
        if silent:
            viol.append("R3_SILENT_DEP")

        # R4 直接断言值（先算，R6 依赖它）
        # 两个口径**都记**：
        #   严格 —— 整句无任何推导词，只有「X = 数值」⇒ 真·断言
        #   宽松 —— 剥掉推导词后仍剩「X = 数值」⇒ 含「由…可得 X=数值」这类
        #           「形式在推、结论是写死的」，假阳性包括题设方程
        va = False
        va_loose = False
        if st:
            low = st.lower()
            has_marker = any(w.lower() in low for w in _ASSERT_MARKERS)
            if has_marker:
                # 「必须等于 2026」/「must equal 2026」不含 `=`，仍然是断言
                va = True
                va_loose = True
            elif _VALUE_EQ_RE.search(st):
                has_derive = any(w.lower() in low for w in _DERIVE_WORDS)
                if not has_derive:
                    va = True
                body = st
                for w in _DERIVE_WORDS:
                    body = body.replace(w, u" ")
                if _VALUE_EQ_RE.search(body):
                    va_loose = True
        value_assert[nid] = va
        value_assert_loose[nid] = va_loose

        node_rows.append({
            "node": nid,
            "index": order.get(nid),
            "statement": st,
            "inputs": inputs,
            "open_refs": [],
            "false_premise_refs": [],
            "silent_refs": sorted(silent),
            "closure": lvl,
            "closure_why": why,
            "subgoal_id": (sg or {}).get("id"),
            "objective_verdict": (sg or {}).get("objective_verdict"),
            "tool_ran": (sg or {}).get("tool_ran"),
            "value_assert": va,
            "violations": viol,
        })

    # 第二遍：R2（引用未闭合）与 R6（引用了「直接断言的假前提」）
    # ★ R6 是 P0 的精确指纹：节点 A 的结论被节点 B 当作已知前提使用，
    #   而 A 的值是**直接写死的**（不是推出来的）⇒ 错误从蓝图起就被洗成事实。
    by_id = {r["node"]: r for r in node_rows}
    for r in node_rows:
        open_refs = []
        false_prem = []
        for ref in r["inputs"]:
            if ref in closure and closure[ref][0] == "OPEN":
                open_refs.append(ref)
            if value_assert.get(ref):
                # 被引用节点自身就是「直接断言值」，且它未被硬验证
                if not (ref in closure and closure[ref][0] == "HARD_CLOSED"):
                    false_prem.append(ref)
        r["open_refs"] = open_refs
        r["false_premise_refs"] = false_prem
        if open_refs:
            r["violations"].append("R2_DOWNSTREAM_UNCLOSED")
        if false_prem:
            r["violations"].append("R6_FALSE_PREMISE")
        if value_assert.get(r["node"]):
            r["violations"].append("R4_VALUE_ASSERT")
        if value_assert_loose.get(r["node"]):
            r["violations"].append("R4L_VALUE_ASSERT_LOOSE")

    n_nodes = len(node_rows)
    hard = sum(1 for r in node_rows if r["closure"] == "HARD_CLOSED")
    soft = sum(1 for r in node_rows if r["closure"] == "SOFT_CLOSED")
    openn = sum(1 for r in node_rows if r["closure"] == "OPEN")
    unmapped = sum(1 for r in node_rows if r["closure"] == "UNMAPPED")
    cnt = collections.Counter()
    for r in node_rows:
        for v in r["violations"]:
            cnt[v] += 1
    if hard == 0:
        cnt["R5_NO_HARD_CLOSE"] += 1

    failed = [r for r in node_rows
              if [v for v in r["violations"] if v != "R4L_VALUE_ASSERT_LOOSE"]]
    bad_nodes = len(failed)
    return {
        "qdir": qdir,
        "qid": os.path.basename(qdir.rstrip("/\\")),
        "run_id": os.path.basename(os.path.dirname(qdir.rstrip("/\\"))),
        "root_id": root_id,
        "n_nodes": n_nodes,
        "n_subgoals": len(subgoals),
        "match_method": dict(match_method),
        "closure": {"HARD": hard, "SOFT": soft, "OPEN": openn, "UNMAPPED": unmapped},
        "viol": dict(cnt),
        "bad_nodes": bad_nodes,
        "bad_rate": (100.0 * bad_nodes / n_nodes) if n_nodes else 0.0,
        "nodes": node_rows,
    }


# ------------------------------------------------------------------ 统计检验

def _comb(n, k):
    if k < 0 or k > n:
        return 0
    num = 1
    for i in range(k):
        num = num * (n - i) // (i + 1)
    return num


def fisher_two_sided(a, b, c, d):
    """2x2 表 [[a,b],[c,d]] 双侧 Fisher 精确检验 p 值。"""
    n = a + b + c + d
    if n == 0:
        return 1.0

    def prob(a1, b1, c1, d1):
        return (_comb(a1 + b1, a1) * _comb(c1 + d1, c1)) / float(_comb(n, a1 + c1))

    p0 = prob(a, b, c, d)
    total = 0.0
    r1 = a + b
    c1 = a + c
    for x in range(max(0, c1 - (c + d)), min(r1, c1) + 1):
        p = prob(x, r1 - x, c1 - x, (c + d) - (c1 - x))
        if p <= p0 + 1e-12:
            total += p
    return min(1.0, total)


def mann_whitney(xs, ys):
    """Mann-Whitney U 的正态近似（单侧，检验 xs 是否更大）。"""
    if not xs or not ys:
        return None, None
    allv = [(v, 0) for v in xs] + [(v, 1) for v in ys]
    allv.sort()
    ranks = {}
    i = 0
    n = len(allv)
    while i < n:
        j = i
        while j + 1 < n and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    r1 = sum(ranks[k] for k in range(n) if allv[k][1] == 0)
    n1, n2 = len(xs), len(ys)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    sd = (n1 * n2 * (n1 + n2 + 1) / 12.0) ** 0.5
    if sd == 0:
        return u1, None
    z = (u1 - mu) / sd
    # 单侧 p（U 偏大 ⇒ xs 更大）
    p = 1 - 0.5 * (1 + _erf(z / (2 ** 0.5)))
    return u1, p


def _erf(x):
    # Abramowitz & Stegun 7.1.26
    sign = 1 if x >= 0 else -1
    x = abs(x)
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    t = 1.0 / (1.0 + p * x)
    y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * (2.718281828459045 ** (-x * x))
    return sign * y


# ------------------------------------------------------------------ 输出

def pct(x, n):
    return "%.1f%%" % (100.0 * x / n) if n else "-"


def main(argv=None):
    ap = argparse.ArgumentParser(description="蓝图许可证机制回放（δ=0，0 LLM）")
    ap.add_argument("--results", default="/home/ubuntu/mathpilot/results",
                    help="results 目录（默认服务器绝对路径）")
    ap.add_argument("--json", default=None, help="把逐题明细写到该文件")
    ap.add_argument("--show", default=None, help="打印某题（qid 子串）逐节点明细")
    ap.add_argument("--bad", action="store_true", help="只列出有违规的题")
    ap.add_argument("--min", type=int, default=None, help="只用不早于该 run 目录（YYYYMMDD）")
    args = ap.parse_args(argv)

    by_qid, by_jsonl_qid, run_to_jsonl = build_label_index(args.results)
    qdirs = sorted(glob.glob(os.path.join(args.results, "2*", "q*")))
    if args.min:
        qdirs = [q for q in qdirs if os.path.basename(os.path.dirname(q)) >= args.min]

    print("=" * 78)
    print("E21 蓝图许可证机制回放  (δ=0, 0 LLM)")
    print("=" * 78)
    print("蓝图目录数: %d   有判对标签的 qid: %d   run→jsonl 配对: %d"
          % (len(qdirs), len(by_qid), len(run_to_jsonl)))
    print()

    results = []
    skipped = 0
    for q in qdirs:
        r = analyze_question(q)
        if not r:
            skipped += 1
            continue
        r["jsonl"] = (run_to_jsonl.get(r["run_id"]) or (None, None))[0]
        r["label"], r["label_src"] = label_for(
            by_qid, by_jsonl_qid, r["run_id"], r["qid"], r["jsonl"])
        results.append(r)

    print("分析题次: %d   跳过（无蓝图）: %d" % (len(results), skipped))
    if not results:
        return 1

    # ---------------- 节点级总账
    tot_nodes = sum(r["n_nodes"] for r in results)
    agg = collections.Counter()
    for r in results:
        for k, v in r["viol"].items():
            agg[k] += v
    hard = sum(r["closure"]["HARD"] for r in results)
    soft = sum(r["closure"]["SOFT"] for r in results)
    openn = sum(r["closure"]["OPEN"] for r in results)
    unmapped = sum(r["closure"].get("UNMAPPED", 0) for r in results)
    bad_nodes = sum(r["bad_nodes"] for r in results)
    judged = hard + soft + openn

    print()
    print("### 节点级（共 %d 个非根节点，其中 %d 个能配上子目标）" % (tot_nodes, judged))
    print("  闭合层级:  HARD %d (%s)   SOFT %d (%s)   OPEN %d (%s)   UNMAPPED %d"
          % (hard, pct(hard, judged), soft, pct(soft, judged),
             openn, pct(openn, judged), unmapped))
    print("  ★ HARD = 工具真跑过并判通过（唯一不可贿赂的闭合）；"
          "SOFT = LLM 自评 correct（同源失效）")
    print("  标红节点:  %d / %d = %s" % (bad_nodes, tot_nodes, pct(bad_nodes, tot_nodes)))
    print()
    print("  %-26s %8s %8s  %s" % ("违规类型", "节点数", "占节点", "占分析题次"))
    for k in ("R6_FALSE_PREMISE", "R2_DOWNSTREAM_UNCLOSED", "R4_VALUE_ASSERT",
              "R4L_VALUE_ASSERT_LOOSE", "R3_SILENT_DEP", "R1_REF_UNKNOWN",
              "R5_NO_HARD_CLOSE"):
        n = agg.get(k, 0)
        nq = sum(1 for r in results if r["viol"].get(k))
        print("  %-26s %8d %8s  %d/%d (%s)"
              % (k, n, pct(n, tot_nodes), nq, len(results), pct(nq, len(results))))

    # ---------------- 时序漂移（★ 决定能否合并统计）
    # 实测断点就在 10-15：那天起蓝图开始产出 03_subgoals.json，节点才开始有 inputs。
    # 之前的题次「无法判定闭合」而不是「没有违规」，合并会把 0% 和 90% 平均成 34%。
    print()
    print("### 按 run 日期分组（漂移检查）")
    print("  %-9s %4s %6s %7s %7s %6s %5s %7s"
          % ("日期", "题次", "节点", "标红率", "R2率", "R4宽", "子=0", "判对"))
    byday = collections.defaultdict(list)
    for r in results:
        byday[r["run_id"][:8]].append(r)
    for day in sorted(byday):
        grp = byday[day]
        nn = sum(x["n_nodes"] for x in grp) or 1
        bad = sum(x["bad_nodes"] for x in grp)
        r2 = sum(1 for x in grp if x["viol"].get("R2_DOWNSTREAM_UNCLOSED"))
        r4 = sum(1 for x in grp if x["viol"].get("R4L_VALUE_ASSERT_LOOSE"))
        nosg = sum(1 for x in grp if x["n_subgoals"] == 0)
        lab = [x for x in grp if x["label"] is not None]
        okn = sum(1 for x in lab if x["label"])
        print("  %-9s %4d %6d %6.0f%% %6.0f%% %5.0f%% %5d %7s"
              % (day, len(grp), nn, 100.0 * bad / nn,
                 100.0 * r2 / len(grp), 100.0 * r4 / len(grp), nosg,
                 ("%d/%d" % (okn, len(lab)) if lab else "-")))

    # ---------------- 预测力
    # ★ 只在「有子目标」的题次上算：`子=0` 的题闭合状态不可判定（全 UNMAPPED），
    #   把它们算进来等于把「测不出」当成「没违规」。
    labelled = [r for r in results if r["label"] is not None and r["n_subgoals"] > 0]
    print()
    print("### 预测力（有稳定标签 **且** 有子目标的 %d 题次）" % len(labelled))
    pos = [r for r in labelled if r["label"] is True]
    neg = [r for r in labelled if r["label"] is False]
    print("  判对 %d   判错 %d" % (len(pos), len(neg)))
    if pos and neg:
        def col(r, field):
            if field == "bad_rate":
                return r["bad_rate"]
            if field == "n_nodes":
                return r["n_nodes"]
            return r["viol"].get(field, 0)

        for field, name in (("bad_rate", "标红率 %"),
                            ("R6_FALSE_PREMISE", "R6 假前提引用数"),
                            ("R2_DOWNSTREAM_UNCLOSED", "R2 未闭合引用数"),
                            ("R4_VALUE_ASSERT", "R4 直接断言值数(严)"),
                            ("R4L_VALUE_ASSERT_LOOSE", "R4 直接断言值数(宽)"),
                            ("n_nodes", "节点数")):
            xs = [col(r, field) for r in pos]
            ys = [col(r, field) for r in neg]
            mx = sum(xs) / float(len(xs))
            my = sum(ys) / float(len(ys))
            _, p = mann_whitney(ys, xs)  # 检验 判错 > 判对
            print("  %-18s 判对均值 %6.1f   判错均值 %6.1f   p(单侧 错>对)=%s"
                  % (name, mx, my, ("%.3f" % p) if p is not None else "-"))

        for field, name in (("R6_FALSE_PREMISE", "存在 R6(引用直接断言的值)"),
                            ("R2_DOWNSTREAM_UNCLOSED", "存在 R2(引用未闭合)")):
            a = sum(1 for r in pos if r["viol"].get(field))
            b = len(pos) - a
            c = sum(1 for r in neg if r["viol"].get(field))
            d = len(neg) - c
            pv = fisher_two_sided(a, b, c, d)
            print()
            print("  2x2  「%s」" % name)
            print("        %-14s %-10s" % ("有", "无"))
            print("   判对  %-14d %-10d" % (a, b))
            print("   判错  %-14d %-10d" % (c, d))
            print("   Fisher 双侧 p = %.4f" % pv)

        # 用「唯一正确阈值」扫 bad_rate
        print()
        print("  标红率分档（判对 / 判错 题次数）")
        bands = [(0, 0.001), (0.001, 25), (25, 50), (50, 75), (75, 100.1)]
        for lo, hi in bands:
            npos = sum(1 for r in pos if lo <= r["bad_rate"] < hi)
            nneg = sum(1 for r in neg if lo <= r["bad_rate"] < hi)
            print("    %5.0f%% ~ %5.0f%%   %3d / %3d" % (lo, hi, npos, nneg))
    else:
        print("  （判对或判错一侧为空，跳过统计）")

    # ---------------- 逐题
    print()
    print("### 逐题（按标红率降序）")
    print("  %-12s %-11s %3s %3s %12s %4s %4s %5s %6s  %s"
          % ("qid", "run", "节", "子", "H/S/O/U", "R6", "R2", "R4", "标红", "判对"))
    for r in sorted(results, key=lambda x: -x["bad_rate"]):
        if args.bad and r["bad_nodes"] == 0:
            continue
        c = r["closure"]
        print("  %-12s %-11s %3d %3d %12s %4d %4d %5d %5.0f%%  %s"
              % (r["qid"], r["run_id"][-9:], r["n_nodes"], r["n_subgoals"],
                 "%d/%d/%d/%d" % (c["HARD"], c["SOFT"], c["OPEN"], c.get("UNMAPPED", 0)),
                 r["viol"].get("R6_FALSE_PREMISE", 0),
                 r["viol"].get("R2_DOWNSTREAM_UNCLOSED", 0),
                 r["viol"].get("R4_VALUE_ASSERT", 0),
                 r["bad_rate"],
                 "-" if r["label"] is None else ("OK" if r["label"] else "X")))

    # ---------------- 单题明细
    if args.show:
        for r in results:
            if args.show in r["qid"]:
                print()
                print("=" * 78)
                print("逐节点: %s  (%s)  配对方式=%s" % (r["qid"], r["run_id"], r["match_method"]))
                for nd in r["nodes"]:
                    flag = ",".join(nd["violations"]) or "-"
                    print("  %-5s sg=%-3s %-12s in=%-12s %s"
                          % (nd["node"], nd["subgoal_id"], nd["closure"],
                             ",".join(nd["inputs"]) or "-", flag))
                    print("        %s" % ((nd["statement"] or "")[:96],))
                    if nd["open_refs"]:
                        print("        ↳ 引用未闭合: %s" % (",".join(nd["open_refs"]),))
                    if nd["false_premise_refs"]:
                        print("        ↳ ★引用直接断言的值(假前提): %s"
                              % (",".join(nd["false_premise_refs"]),))
                    if nd["silent_refs"]:
                        print("        ↳ 未声明引用: %s" % (",".join(nd["silent_refs"]),))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"summary": {
                "n_q": len(results), "n_nodes": tot_nodes,
                "closure": {"HARD": hard, "SOFT": soft, "OPEN": openn, "UNMAPPED": unmapped},
                "viol": dict(agg), "bad_nodes": bad_nodes,
            }, "questions": results}, f, ensure_ascii=False, indent=1)
        print()
        print("明细已写: %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
