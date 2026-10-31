# -*- coding: utf-8 -*-
"""2.7 蓝图「拆法约束」：按**目标种类**约束子目标拆解方式。

================================================================================
为什么要加这一层（2026-10-28，服务器 16 条实测）
================================================================================
同一道存在性题 `omni-3556`（`Find an integer n …`）在两臂里被拆成两种形状：

  · **判对那臂**：证 n 为偶数 → 化归 → **搜索 m** → 验证整除 → 验证区间 → 作答（6 步、1 轮）
  · **池空那臂**：三轮都要「证明所有奇数 m 满足 m|15」/「建立 lifting 引理」（22 步、3 轮）

三轮三个假引理（`5m|2^{10m-1}+1` / `m 奇 ⇒ m|15` / `pm|2^{2pm-1}+1`），m=33 即反例
⇒ 4.1/4.2/4.4 判死整池。**4 判得对**，问题在拆法。

根因是倒推机制的必然产物：倒推要求先知道结论 ⇒ 先猜出 946 ⇒ 要让 946「从推导里
长出来」⇒ 只能造一个能从 3 生成 946 的 lifting 引理。
**当目标只是一个具体对象时，"刻画一整类" 这条路本身就该被排除。**

================================================================================
两层约束（这是本模块的核心设计）
================================================================================
① **无条件层（对所有题目一律注入）**
   只讲一件事：**不得把有限次验证写成全称命题**。全称节点必须说明证明方法。
   这一层在任何题型上都成立（最值/分类题也要能说清自己是怎么证的），
   所以无条件注入不承担误伤风险。

② **条件层（仅 ``goal_kind == instance`` 时注入）**
   目标只是一个具体对象 ⇒ 拆法只允许「化归 / 搜索构造 / 逐条验证」，
   禁止产出全称命题与 lifting 引理节点。

================================================================================
判据：只看**目标从句**，且**故意收窄**
================================================================================
题面里的 `for all positive integers n,m`、`Every pair of communities` 是**条件**，
不是**目标**。直接扫全段会把 4 道题全误判成"求所有"⇒ 先切目标从句再判。

``instance`` 的触发条件刻意很窄（宁可漏，不可误伤）：
  · 正向：`find an …` / `find the value|sum|ratio|number` / `what is the sum|value` /
          `find f(` / `求…值` / `给出一个` / `找出一个` / `构造一个`
  · 排除：**最值**（largest/smallest/max/min/最大/最小/最多/最少）、
          **计数**（number of / how many / count / 个数 / 多少种）、
          **分类**（family）
  ⇒ 最值题与计数题**本来就依赖全称论证**，要求它"只做构造验证"会帮倒忙。
    实测排除后 `omni-3593`（largest number）、`omni-2163`（minimum number）、
    `omni-1322`/`omni-1633`（number of）都不再触发；本轮 4 道池空题里
    **3556 / 3876 / 1352 三题命中**（3593 被排除，保守放弃）。

================================================================================
本模块**不改判据、不删节点**
================================================================================
``scope_leak_nodes`` 只做**观测**（检出呈全称/引理形态的节点），不拦截、不改 DAG。
理由：`omni-3556` 判对那臂的第 1 步「满足 n|2^n+2 的 n 必为偶数」也是全称命题，
但它**是对的、必要的**化归约束 ⇒ 文本层分不开，一律拒会打坏好路径。
⇒ 行为改变只由**提示词**承担；检测结果进 trace 供统计（先观测、后定判据）。
"""
from __future__ import annotations

import re

KIND_FAMILY = "family"
KIND_INSTANCE = "instance"

# ---- 目标从句切分 ----------------------------------------------------------
_SENT_SPLIT_RE = re.compile(r"(?<=[.?!。？！])\s+|\n+")

# 「求所有的」：需要完整刻画一整类对象
_FAMILY_RE = re.compile(
    r"所有(?:的)?可能|求所有|全部(?:的)?解|列出所有|所有满足|一切满足|"
    r"所有(?:这样的)?(?:函数|多项式|整数|数列|集合|元组|对|值)|"
    r"完整(?:地)?(?:分类|刻画)|"
    r"\bfind\s+all\b|\ball\s+(?:such|possible|solutions)\b|"
    r"\bdetermine\s+all\b|\bclassify\b|\blist\s+all\b",
    re.I)

# 「证明」：目标是命题 ⇒ 不约束拆法（证明题本来就要一般性引理）
_PROOF_RE = re.compile(
    r"(?:证明|求证|试证)|^\s*(?:prove|show\s+that|verify\s+that)\b", re.I)

# 「给出一个具体对象」——**正向词表刻意很窄**
_INSTANCE_RE = re.compile(
    r"\bfind\s+an?\b|"
    r"\bfind\s+the\s+(?:[a-z]+\s+){0,2}(?:value|sum|ratio|product)\b|"
    r"\bwhat\s+is\s+the\s+(?:value|sum|ratio|product)\b|"
    r"\bfind\s+\$?\s*[a-zA-Z]\s*\(|"
    r"求(?:出)?(?:该|这|其)?(?:值|和|积)|给出一个|找出一个|构造一个",
    re.I)

# 排除：最值 / 计数 —— 这两类**必须有全称论证**，不能要求它只做构造验证
_EXCLUDE_RE = re.compile(
    r"\blargest\b|\bsmallest\b|\bmaximum\b|\bminimum\b|\bmaximal\b|\bminimal\b|"
    r"\bbest\s+constant\b|最大|最小|最多|最少|至多|至少|最值|"
    r"\bnumber\s+of\b|\bhow\s+many\b|\bcount\b|个数|多少种|种数|"
    r"\bnumber\s+of\s+possible\b",
    re.I)


def _goal_clause(problem: str) -> str:
    """切出目标从句：取**最后一句**含提问/祈使信号的句子；都不命中取末句。

    ★ 只用 ``goal_kind``，不参与其它逻辑。实测 `omni-3876` 的
      `… $ n,m.$ Find the possible value …` 因 `.` 后紧跟 `$` 不会被切开，
      两段合并成一句 —— 不影响判定（family 不误命中，instance 正常命中）。
    """
    text = str(problem or "").strip()
    if not text:
        return ""
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
    if not sents:
        return text
    probe = re.compile("|".join(p.pattern for p in
                                (_FAMILY_RE, _PROOF_RE, _INSTANCE_RE)), re.I)
    for s in reversed(sents):
        if probe.search(s):
            return s
    return sents[-1][:200]


def goal_kind(ctx) -> str:
    """目标种类：``family`` / ``instance`` / ``""``（判不出 ⇒ 只注入无条件层）。

    判定顺序（在**目标从句**上）：family → 证明 → 最值/计数排除 → instance。
    """
    problem = str(getattr(ctx, "problem", "") or "")
    clause = _goal_clause(problem)
    if not clause:
        return ""
    if _FAMILY_RE.search(clause):
        return KIND_FAMILY
    if _PROOF_RE.search(clause):
        return ""                       # 证明题：目标是命题，不干预拆法
    if _EXCLUDE_RE.search(clause):
        return ""                       # 最值 / 计数：必须有全称论证，不干预
    if _INSTANCE_RE.search(clause):
        return KIND_INSTANCE
    return ""


# ---- 提示词块 --------------------------------------------------------------
_BASE_RULE = """============================================================
陈述纪律（**所有节点一律适用**）
============================================================
节点陈述必须是**你真的证明了的**命题。
- 如果你只**验证了有限个特例**（试了 m=3、5、7 之类），
  就必须把节点写成「**对候选逐一验证**」，**不得**写成「对任意 … 成立」
  「所有 … 都 …」「… 必整除 …」这类全称命题。
- 如果一个节点确实是全称命题，必须在 `rationale` 里写明**证明方法**
  （用了什么归纳 / 反证 / 数论定理），**不许**只写"已验证若干情形"。
- 拿不准某个一般性结论是否成立时，**不要**把它写成节点；
  改为"就当前候选对象计算到底"。
理由：把特例验证写成全称命题会得到一条**假引理**，整条链会在下游被判为无效。
"""

_INSTANCE_BODY = """
============================================================
本题拆法（目标只是一个具体对象，**优先级高于上文通用拆解原则**）
============================================================
本题要的是**一个具体对象 / 一个具体值**，**不是**刻画一整类对象。
⇒ 子目标只允许下面三类：
  ① 把原条件**化归**成关于候选对象的更简条件（如"n 必为偶数，故设 n=2m"）；
  ② **搜索 / 构造**出候选对象（允许试小值、允许猜，但必须写明是怎么得到的）；
  ③ 对候选对象**逐条验证**题目要求的每一项条件（含区间、范围、附加约束）。
⇒ **禁止**产出下列形态的节点：
  · 「建立 / 证明某提升引理（lifting lemma）」「给出完整分类」这类需要刻画整类的引理；
  · 「证明对任意 … 成立」这类与本问无关的全称命题。
⇒ 若某一步看起来"需要一条一般性结论才能推进"，**改写**成
  「对当前候选对象计算到底」或「对候选逐一验证」。
⇒ 一条 5~7 步的「化归 → 找 → 验」短链，**远好于**一条 10 步以上靠引理支撑的长链。
"""

_FAMILY_BODY = """
============================================================
本题拆法（目标需要完整刻画一整类对象）
============================================================
⇒ 允许分类讨论与一般性命题，但每个一般性命题必须同时写明：
  ① 它的**适用范围**（对哪些参数成立）；② 已**逐项验证**过的特例清单。
⇒ 每个分类分支都必须有人**证明其穷尽性**（为什么没有别的分支）。
"""

def _guidance_on() -> bool:
    """`blueprint_goal_kind_guidance` 开关（默认 True）。

    走 `contracts.switch_registry`（环境变量 > 配置 > 默认）；注册表不可用退回 True
    （与 `_lean_sig_on` 同口径）。关 ⇒ 提示词逐字回到改动前（A/B 对照组）。
    """
    try:
        from contracts.switch_registry import get_bool
        return bool(get_bool("blueprint_goal_kind_guidance"))
    except Exception:  # noqa: BLE001  注册表不可用 → 按默认启用
        return True


def guidance_block(kind: str) -> str:
    """返回要注入系统提示词的约束块。

    ★ 无条件层 + 条件层两段拼接：``""`` 也返回无条件层（只是不追加条件层），
      因为「不得把特例写成全称命题」在任何题型上都成立。
    """
    out = _BASE_RULE
    if kind == KIND_INSTANCE:
        out += _INSTANCE_BODY
    elif kind == KIND_FAMILY:
        out += _FAMILY_BODY
    return out


# 插入锚点：系统提示词里「输出格式」小节的标题。**必须插在它之前** ——
# 追加到末尾会破坏「只输出 JSON」的收尾结构、诱使模型进入续写模式
# （al-075 纪律，与 `problem_goal.render_problem_goal` 同一约束）。
_OUTPUT_SECTION_ANCHOR = (
    "============================================================\n"
    "输出格式（必须严格遵循，只输出 JSON）")


def inject_into_system(base: str, kind: str) -> str:
    """把约束块插到系统提示词的「输出格式」小节之前。锚点缺失则原样返回。

    锚点缺失不抛异常：提示词是内容资产，改版时不该让主链崩掉；
    由 `tests/test_blueprint_decomposition.py::test_anchor_present` 兜住。
    """
    if not base or _OUTPUT_SECTION_ANCHOR not in base:
        return base
    block = guidance_block(kind)
    return base.replace(_OUTPUT_SECTION_ANCHOR,
                        block.rstrip() + "\n\n" + _OUTPUT_SECTION_ANCHOR, 1)


# ---- 观测：检出呈全称/引理形态的节点（**advisory，不拦截**）--------------
_SCOPE_LEAK_RE = re.compile(
    r"对任意|对所有|对一切|任意.{0,16}(?:都|均|恒)|所有.{0,16}(?:都|均|必)|"
    r"必整除|必能整除|恒成立|完整分类|"
    r"提升引理|lifting\s+lemma|\bfor\s+all\b|\bfor\s+every\b|\bfor\s+any\b",
    re.I)


def scope_leak_nodes(dag) -> list:
    """返回呈全称/引理形态的节点 ``[(id, statement)]``；只做观测，不改 DAG。

    ★ 不用于拦截：`omni-3556` 判对那臂的第 1 步「满足 n|2^n+2 的 n 必为偶数」
      也是全称命题，但它是**正确且必要**的化归约束。文本层分不开两者。
    """
    out = []
    try:
        nodes = getattr(dag, "nodes", None) or {}
        root = getattr(dag, "root_id", None)
        for nid, node in nodes.items():
            if nid == root:
                continue
            st = str(getattr(node, "statement", "") or "")
            if st and _SCOPE_LEAK_RE.search(st):
                out.append((nid, st))
    except Exception:  # noqa: BLE001  观测逻辑绝不阻断
        return []
    return out
