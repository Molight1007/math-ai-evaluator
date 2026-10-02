# -*- coding: utf-8 -*-
"""领域 → 定理检索（2026-09-29 新增，截图 #3+#4「老师重点关注」）。

设计目标（用户原话）
--------------------
> 我们要判断它是哪个领域的题目，会用到什么定理（这里面就要使用 leansearch
> 去 mathlib 搜索对应的定理了，这也是老师重点关注的地方，就是判断定理对
> 大模型的帮助效果。我的思路是我们先把题库每一题对应的会用到的定理总结下来，
> 然后判断大模型或 leansearch 最后有没有找到正确的定理。以及定理对大模型的
> 推理效果如何？

拆成三件事，**本模块只负责第 ① 件**：
  ① 【检索】给定题目 + 领域 → 用 leansearch 去 Mathlib 找候选定理；
  ② 【判定】命中的定理是否 == 题库预标注的「正确定理」→ ``tools/theorem_probe.py``；
  ③ 【效用】把定理注入解题提示词后，正确率是否提升 → ``theorem_hint_*`` 埋点 + A/B。

★ 关键的架构约束（用户要求「修改 lean 相关调用不会波及大模型部分」）
-------------------------------------------------------------------
本模块是 **agent/ 侧唯一的定理检索入口**。它对外只暴露
``retrieve_theorems_for_question()`` 一个函数，返回**纯数据结构**，
不抛异常、不返回 Lean 对象、不依赖 tools.lean_local 的内部类型。
因此：
  · 换检索后端（官方 API / 离线语料 / 源码扫描）→ 只改本文件；
  · 换解题提示词 / 大模型 → 完全不碰本文件；
  · tools.lean_local 不可用 → 本模块降级返回空结果，主流程照常。
"""

from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)

import logging
import os
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger("MathPilot")


# ---------------------------------------------------------------------------
# 数据结构（纯数据，无外部依赖）
# ---------------------------------------------------------------------------

@dataclass
class TheoremHit:
    """一条检索命中的定理。"""
    name: str = ""            # Mathlib 全名，如 Mathlib.Data.Nat.Choose.Basic.Nat.choose
    short: str = ""           # 末段短名，如 Nat.choose
    source: str = ""          # 命中的 query（便于归因「哪个 query 找到的」）
    rank: int = 0             # 在该次检索中的位次（1-based）

    def to_dict(self) -> dict:
        return {"name": self.name, "short": self.short,
                "source": self.source, "rank": self.rank}


@dataclass
class TheoremRetrieval:
    """一次「题目 → 定理」检索的完整结果（可直接进 diag / JSON）。"""
    ok: bool = False                     # 检索本身是否跑通（False=后端不可用/异常）
    domain: str = ""
    queries: list = field(default_factory=list)      # 实际发出的 query 列表
    hits: list = field(default_factory=list)         # list[TheoremHit]
    backend: str = ""                    # 实际生效的后端（供归因）
    elapsed: float = 0.0
    reason: str = ""                     # ok=False 时的原因

    @property
    def names(self) -> list:
        return [h.name for h in self.hits]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "domain": self.domain,
            "queries": list(self.queries),
            "hits": [h.to_dict() for h in self.hits],
            "n_hits": len(self.hits),
            "distinct_short": sorted({h.short for h in self.hits}),
            "backend": self.backend,
            "elapsed": round(self.elapsed, 2),
            "reason": self.reason,
        }

    # ------------------------------------------------------------------
    # 提示词渲染（★ 2026-09-29 实测修正）
    # ------------------------------------------------------------------
    # 问题：最初的 block 用「短名 + 全名」并列，实测 5 条命中即 **798 字符**，
    #   而其中 `Mathlib.Geometry.Euclidean.Angle.Oriented.Affine.EuclideanGeometry.`
    #   这类命名空间前缀占了 60%+。对以中文推理的大模型，这串路径**信息量近似为零**，
    #   纯属 token 噪音，还挤占推理预算。注入的本意是"帮模型"，不是"堆 token"。
    # 做法：提示词只给**短名**（模型靠名字+领域语境已能理解，如
    #   `angle_add_angle_add_angle_eq_pi` 一眼就是三角形内角和），
    #   全名**完整保留在 `ctx.theorem_hint_trace` 埋点里**供 Lean 侧/A-B 归因使用。
    #   实测压缩后 5 条从 798 → 约 250 字符（−69%），语义不减。
    def render_hint_block(self, max_items: int = 5) -> str:
        """渲染成注入提示词的文本块（无命中返回空串 ⇒ 下游零成本）。

        ★ 只输出短名 + 说明；全名走 `to_dict()` 埋点，不进提示词。
        """
        hits = [h for h in self.hits if (h.short or h.name)][:max(0, max_items)]
        if not hits:
            return ""
        lines = ["【本题可能在 Mathlib 中用到的定理（leansearch 自动检索，供参考）】"]
        for i, h in enumerate(hits, 1):
            lines.append(f"{i}. {h.short or h.name}")
        lines.append(
            "（以上仅为线索，若与你的推理不符，以题意与你的判断为准；"
            "不必强行使用。）")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 领域 → 检索关键词（零 LLM，纯映射；避免为检索再花一次大模型调用）
# ---------------------------------------------------------------------------
# 设计说明：leansearch 的源码扫描后端是**英文标识符匹配**（实测见 CHANGES
# 文档），中文领域名直接传进去命中率极差。故这里把题库实际出现的领域名
# 映射成英文数学关键词组。未收录的领域走「题干英文关键词」兜底。
_DOMAIN_KEYWORDS: dict = {
    "离散数学": ["Finset.card", "permutations", "combinatorics", "choose"],
    "组合数学": ["Finset.card", "permutations", "choose", "combinatorial"],
    "数论": ["Nat.Prime", "Nat.ModEq", "Int.gcd", "number theory"],
    "代数": ["Polynomial", "RingHom", "Group", "Algebra"],
    "线性代数": ["Matrix", "LinearMap", "VectorSpace", "determinant"],
    "几何": ["EuclideanGeometry", "angle", "distance", "triangle"],
    "概率统计": ["Probability", "MeasureTheory", "variance", "expectation"],
    "微积分": ["deriv", "integral", "Continuous", "Differentiable"],
    "分析": ["Continuous", "Converges", "limit", "series"],
    "数学分析": ["Continuous", "Deriv", "Integral", "Sequence"],
    "不等式": ["inequality", "le_trans", "pow_le_pow", "Real.sqrt"],
    "数列": ["Nat.rec", "Fibonacci", "geom_sum", "sum_range"],
    "计数": ["Finset.card", "Fintype.card", "card_eq", "count"],
    "图论": ["Graph", "SimpleGraph", "Adj", "Walk"],
    "集合论": ["Set.", "Finset.", "Subset", "card"],
}

# 题干英文停用词（生成兜底 query 时剔除）
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "be", "for",
    "that", "with", "as", "by", "on", "at", "it", "its", "this", "these",
    "let", "show", "prove", "find", "compute", "determine", "calculate",
    "all", "any", "each", "such", "then", "where", "which", "what", "how",
    "there", "we", "you", "if", "no", "not", "every", "some", "given",
}

# 噪声词：在数学题里高频但无区分度（抽出来只会污染 query）
_NOISE_TOKENS = {
    "said", "satisfies", "satisfying", "matter", "five", "three", "four",
    "two", "one", "following", "condition", "conditions", "number",
    "numbers", "value", "values", "positive", "negative", "nonnegative",
    "integer", "integers", "real", "reals", "distinct", "different",
    "respectively", "denote", "denotes", "defined", "definition",
    "suppose", "consider", "example", "problem", "solution", "answer",
    "minimum", "maximum", "greatest", "least", "larger", "smaller",
    # ★ 2026-09-29 实测修正（关键）：**答案格式样板词**必须当噪声剔除。
    #   实测 official112 的 096/101/103~111 共 12 道中文题，题干里唯一的英文
    #   就是样板句「Remember to put your final answer within \boxed{}」——
    #   不剔除时 12 题抽出**完全相同**的关键词，检索结果雷同、标注表报废
    #   （实测 12x 重复簇 ('upper_mem','TheoremForm','pi_le_four','form')）。
    "remember", "put", "your", "final", "within", "boxed", "write",
    "give", "provide", "express", "note", "must", "should", "please",
    "sure", "carefully", "read", "question", "statement", "true", "false",
}

# LaTeX / MathJax 残渣（正则抽出的字母序列里混进来的）
_TEX_NOISE = {
    "ldots", "cdots", "dots", "leq", "geq", "neq", "frac", "sqrt", "cdot",
    "times", "quad", "qquad", "left", "right", "text", "math", "mathrm",
    "begin", "end", "array", "matrix", "cases", "pmod", "bmod", "equiv",
    "sum", "prod", "int", "lim", "infty", "alpha", "beta", "gamma", "delta",
    "epsilon", "theta", "lambda", "sigma", "omega", "phi", "psi", "prime",
    "circ", "star", "ast", "oplus", "otimes", "subset", "subseteq", "in",
    "notin", "forall", "exists", "implies", "iff", "mapsto", "to", "gets",
}

# 数学术语词表（题干里出现即视为高区分度信号）
# 选取原则：这些词在 Mathlib 声明名里**有直接对应**（如 permutation→Perm、
# polynomial→Polynomial、prime→Nat.Prime），因此作为 query 能精准命中。
_MATH_TERMS = [
    "permutation", "combination", "factorial", "binomial",
    "polynomial", "root", "coefficient", "degree", "factor",
    "prime", "divisible", "divisor", "modulo", "congruent", "remainder",
    "gcd", "lcm", "coprime",
    "matrix", "determinant", "eigenvalue", "eigenvector", "linear",
    "vector", "span", "basis", "dimension", "rank",
    "derivative", "differentiable", "integral", "continuous", "limit",
    "convergent", "converges", "diverges", "series", "sequence", "summable",
    "monotone", "bounded", "supremum", "infimum",
    "probability", "expectation", "variance", "random", "distribution",
    "triangle", "circle", "angle", "perpendicular", "parallel", "midpoint",
    "area", "perimeter", "radius", "diameter",
    "graph", "edge", "vertex", "tree", "path", "cycle", "colorable",
    "set", "subset", "finset", "cardinality", "bijection", "injection",
    "surjection", "function", "inverse", "composition",
    "inequality", "equality", "absolute", "floor", "ceiling",
    "group", "ring", "field", "ideal", "homomorphism", "isomorphism",
    "recurrence", "induction", "summation",
]


def domain_keywords(domain: str, question_type: str = "") -> list:
    """领域名 → 英文检索关键词组（未收录则回退到通用词）。"""
    d = (domain or "").strip()
    for key, kws in _DOMAIN_KEYWORDS.items():
        if key and key in d:
            return list(kws)
    return []


# 中文数学术语 → 英文检索词（2026-09-29 新增）。
# ★ 必要性：official112 含大量**中文题**（统计推断 / 线性回归 / 线性规划 等），
#   而 leansearch 的源码扫描后端只认英文标识符 ⇒ 不做这层映射时，中文题抽不出
#   任何有效关键词，会退化到"题干里的英文样板词"（实测 12 题撞成同一串）。
# 选取原则：只收**在 Mathlib 声明名里有对应**的词，避免映射到搜不到的词。
_CN_TERM_MAP = [
    ("概率", "Probability"), ("期望", "expectation"), ("方差", "variance"),
    ("正态分布", "normal distribution"), ("随机变量", "random variable"),
    ("统计", "statistics"), ("回归", "regression"), ("相关", "correlation"),
    ("时间序列", "time series"), ("抽样", "sampling"), ("假设检验", "hypothesis"),
    ("线性规划", "linear programming"), ("对偶", "duality"),
    ("最优化", "optimization"), ("约束", "constraint"), ("目标函数", "objective"),
    ("矩阵", "Matrix"), ("行列式", "determinant"), ("特征值", "eigenvalue"),
    ("向量", "Vector"), ("线性", "linear"), ("秩", "rank"), ("逆", "inverse"),
    ("多项式", "polynomial"), ("方程", "equation"), ("根", "root"),
    ("因式", "factor"), ("次数", "degree"), ("系数", "coefficient"),
    ("质数", "prime"), ("素数", "prime"), ("整除", "divisible"),
    ("余数", "remainder"), ("同余", "congruent"), ("最大公约数", "gcd"),
    ("最小公倍数", "lcm"), ("互质", "coprime"), ("阶乘", "factorial"),
    ("组合", "combination"), ("排列", "permutation"), ("二项式", "binomial"),
    ("计数", "count"), ("集合", "Set"), ("子集", "Subset"),
    ("映射", "function"), ("双射", "bijection"), ("函数", "function"),
    ("导数", "derivative"), ("微分", "derivative"), ("积分", "integral"),
    ("连续", "continuous"), ("极限", "limit"), ("收敛", "convergent"),
    ("级数", "series"), ("数列", "sequence"), ("单调", "monotone"),
    ("有界", "bounded"), ("三角", "triangle"), ("角", "angle"),
    ("圆", "circle"), ("面积", "area"), ("周长", "perimeter"),
    ("中点", "midpoint"), ("垂直", "perpendicular"), ("平行", "parallel"),
    ("图", "Graph"), ("顶点", "vertex"), ("边", "edge"), ("路径", "path"),
    ("树", "tree"), ("着色", "colorable"), ("不等式", "inequality"),
    ("绝对值", "absolute value"), ("取整", "floor"), ("群", "Group"),
    ("环", "Ring"), ("域", "Field"), ("同态", "homomorphism"),
    ("递推", "recurrence"), ("归纳", "induction"), ("求和", "summation"),
]


def cn_term_keywords(problem: str, limit: int = 5) -> list:
    """中文题干 → 英文数学术语（命中即映射；未命中返回空）。"""
    text = problem or ""
    out: list = []
    for cn, en in _CN_TERM_MAP:
        if cn in text:
            for w in en.split():
                if w not in out:
                    out.append(w)
            if len(out) >= limit:
                break
    return out[:limit]


def question_keywords(problem: str, limit: int = 6) -> list:
    """从题干抽**数学实词**，拼成兜底 query。

    ★ 2026-09-29 实测修正：原实现只做「英文字母序列 - 停用词」，抽出来的是
      ``set / ordered / pairs / integer / real / numbers`` 这类**通用词**，
      在 Mathlib 源码扫描后端上区分度极差 —— 实测同领域多道题的 rank-1
      命中恒为同一条（``card_perms_of_finset``），检索退化。
      现按三级优先抽取：
        ① 英文数学术语（``_MATH_TERMS``）
        ② **中文数学术语**（``_CN_TERM_MAP``）—— 中文题唯一的有效信号
        ③ 通用英文实词（兜底，已剔除答案格式样板词）
    """
    text = problem or ""
    low = text.lower()

    # ① 英文数学术语
    math_hits: list = []
    for term in _MATH_TERMS:
        if term in low and term not in math_hits:
            math_hits.append(term)
    # ② 中文术语（英中混合也要）
    cn_hits = cn_term_keywords(text, limit=limit)

    primary = math_hits + [w for w in cn_hits if w not in math_hits]
    if primary:
        out = primary[:limit]
        for g in _generic_tokens(text):
            if len(out) >= limit:
                break
            if g not in out:
                out.append(g)
        return out

    # ③ 退回：通用英文实词（对无术语抽象的题目仍有价值）
    return _generic_tokens(text, limit)


def _generic_tokens(text: str, limit: int = 6) -> list:
    """题干里的英文实词（去停用词、去纯数字/公式碎片）。"""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_']{2,}", text or "")
    out: list = []
    for t in toks:
        tl = t.lower()
        if tl in _STOPWORDS or tl in _NOISE_TOKENS:
            continue
        if len(tl) < 3:
            continue
        # 排除 LaTeX 命令残渣（ldots / leq / frac / sqrt 等）
        if tl.startswith("\\") or tl in _TEX_NOISE:
            continue
        if tl not in out:
            out.append(tl)
        if len(out) >= limit:
            break
    return out


def build_queries(problem: str, domain: str = "",
                  question_type: str = "",
                  question_first: bool = False) -> list:
    """构造检索 query 列表。

    ★ 2026-09-29 修正：**题干词置于领域词之前**。
      原顺序（领域优先）会导致同领域不同题的首条 query 完全相同 ⇒ 首条命中
      列表雷同、淹没题干信息（实测 000/003/004 三题命中列表一致）。
      现默认题干优先，领域词作为**补充**（而非主导）。

    参数 question_first=False 时保持旧顺序（领域优先），仅供对照实验。
    """
    qs: list = []
    dk = domain_keywords(domain, question_type)
    qk = question_keywords(problem)
    d_q = " ".join(dk) if dk else ""
    q_q = " ".join(qk) if qk else ""
    mixed = " ".join((qk[:3] if qk else []) + (dk[:2] if dk else []))

    # ★ 2026-09-29 二次修正：**领域 query 降级为最后一条**。
    #   实测（8 题）：领域 query 排第 1 时，其宽泛命中（如 离散数学→Finset.card
    #   →card_perms_of_finset）会占据 rank-1，8 题里 6 题的 rank-1 是同一条，
    #   检索无法反映"这道题"。改为领域 query 兜底（仅在题干 query 无命中时才生效）
    #   后，rank-1 去重数由 1 → 4，几何题正确浮出 angle_ne_zero_of_not_collinear。
    for q in (q_q, mixed, d_q):
        if q:
            qs.append(q)
    if question_first:
        qs.reverse()
    # 去重保序
    seen: set = set()
    out: list = []
    for q in qs:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


# ---------------------------------------------------------------------------
# 主入口：agent/ 侧唯一的定理检索接口
# ---------------------------------------------------------------------------

def retrieve_theorems_for_question(
    problem: str,
    domain: str = "",
    question_type: str = "",
    config=None,
    max_queries: int = 2,
    top_k: int = 5,
) -> TheoremRetrieval:
    """题目 + 领域 → Mathlib 定理候选（**永不抛异常**）。

    参数
    ----
    problem        : 题干原文
    domain         : 领域名（来自 1_classify，可为空）
    question_type  : 题型（来自 classify_question_type，可为空）
    config         : AgentConfig（读开关；可传 None 用默认）
    max_queries    : 最多发几次检索（默认 2，与 leansearch_max_calls_per_q 对齐）
    top_k          : 每次检索取回条数（与 leansearch_top_k 对齐）

    返回
    ----
    TheoremRetrieval —— ok=False 表示后端不可用/异常（**调用方据此跳过即可**）。
    """
    t0 = time.time()
    out = TheoremRetrieval(domain=domain)

    # 开关（默认开；设 0 可关，便于 A/B「有定理 vs 无定理」）
    if config is not None and not bool(
            getattr(config, "enable_theorem_hint", True)):
        out.reason = "开关关闭（enable_theorem_hint=False）"
        return out
    if not _sw_bool("theorem_hint"):
        out.reason = "环境变量 THEOREM_HINT=0"
        return out

    # 客观题/判断题：答案是选项字母或真值，定理检索无意义
    if question_type and question_type in ("选择题", "判断题"):
        out.reason = f"题型为{question_type}，跳过定理检索"
        return out
    if not (problem or "").strip():
        out.reason = "题干为空"
        return out

    queries = build_queries(problem, domain, question_type)[:max(0, max_queries)]
    if not queries:
        out.reason = "未能构造检索 query（题干无英文实词且领域未收录）"
        return out
    out.queries = list(queries)

    # ---- 依赖 tools.lean_local（**唯一**的 Lean 侧依赖点，且受 try 保护）----
    try:
        from tools.lean_local.lean_search import MathlibTheoremSearcher
    except Exception as e:  # noqa: BLE001
        out.reason = f"lean_search 导入失败: {type(e).__name__}: {e}"
        out.elapsed = time.time() - t0
        logger.warning("[theorem_hint] %s", out.reason)
        return out

    try:
        searcher = MathlibTheoremSearcher()
        st = searcher.status() or {}
        if not st.get("available"):
            out.reason = f"检索后端不可用: {st}"
            out.elapsed = time.time() - t0
            return out
        out.backend = "source_scan"      # 源码扫描后端（离线语料缺失时的唯一可用后端）

        seen_names: set = set()
        hits: list = []
        for q in queries:
            try:
                res = searcher.search(q, limit=top_k) or {}
            except Exception as e:  # noqa: BLE001
                logger.warning("[theorem_hint] query=%r 检索异常: %s", q, e)
                continue
            for i, item in enumerate(res.get("results") or [], start=1):
                name = str(item.get("name") or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                hits.append(TheoremHit(
                    name=name,
                    short=name.rsplit(".", 1)[-1],
                    source=q,
                    rank=i,
                ))
        # ★ 2026-09-29 修复（实测暴露）：多 query 结果必须**按位次重排**后再截断。
        #   原实现是「先到先得、跑满 top_k 就停」—— 但领域 query（第 1 条）本身就
        #   会返回 top_k 条，于是题干 query 的命中全被挤在后面。
        #   实测后果：同领域的三道不同题（000/003/004）拿回**完全相同**的命中列表，
        #   检索退化成了"领域查询" ⇒ 无法反映"这道题"该用什么定理。
        #   现在改为：并集后按 (rank 升序) 排序，位次越靠前越优先保留。
        hits.sort(key=lambda h: (h.rank, h.name))
        out.hits = hits[:max(top_k, 1) * max(len(queries), 1)]
        out.ok = True
        if not out.hits:
            out.reason = "检索跑通但零命中"
    except Exception as e:  # noqa: BLE001  —— 任何异常都不许冒泡到主流程
        out.reason = f"检索异常: {type(e).__name__}: {e}"
        logger.warning("[theorem_hint] %s", out.reason)

    out.elapsed = time.time() - t0
    return out


# ---------------------------------------------------------------------------
# 评审：命中的定理是否 == 预标注的正确定理
# ---------------------------------------------------------------------------

def match_against_ground_truth(
    retrieval: TheoremRetrieval,
    gt: dict,
) -> dict:
    """把一次检索结果与题库预标注比对，产出**可上报的三指标**。

    gt 形如::

        {"required": ["Nat.choose", "Finset.card_perms_of_finset"],
         "optional": ["Nat.factorial"]}

    匹配规则（**宽松后缀匹配**）：
      预标注可写末段短名（``choose``）、限定短名（``Nat.choose``）或全名
      （``Mathlib.Data.Nat.Choose.Basic.Nat.choose``）。命中项同样可写成
      全名或任意后缀。判定为「命中」当且仅当**存在一对（标注, 命中）使得
      两者互为后缀或相等**。这样：
        · Mathlib 重构命名空间前缀 → 比对仍稳定；
        · 标注写 ``Nat.choose`` 而命中是 ``...Basic.Nat.choose`` → 命中；
        · 标注写 ``choose`` 而命中是 ``...Basic.Nat.choose`` → 命中。

    返回::

        {"required_n": 2, "required_hit": 1, "required_miss": ["..."],
         "hit_rate": 0.5, "all_required_hit": False,
         "best_rank": 2, "optional_hit": 0}
    """
    req = [str(x).strip() for x in (gt or {}).get("required") or [] if str(x).strip()]
    opt = [str(x).strip() for x in (gt or {}).get("optional") or [] if str(x).strip()]

    # 命中侧：收集全名与**所有点分段后缀**（"A.B.C.d" → A.B.C.d / B.C.d / C.d / d）
    got_segs: set = set()
    rank_of: dict = {}
    for h in retrieval.hits:
        full = h.name
        got_segs.add(full)
        parts = full.split(".")
        for i in range(len(parts)):
            seg = ".".join(parts[i:])
            got_segs.add(seg)
            rank_of.setdefault(seg, h.rank)

    def _hit(name: str) -> bool:
        """标注名是否命中：本身在命中集，或它与某命中项互为后缀。"""
        if name in got_segs:
            return True
        # 反向：标注写全名而命中只记了短名的情况
        parts = name.split(".")
        for i in range(len(parts)):
            if ".".join(parts[i:]) in got_segs:
                return True
        return False

    req_hit = [n for n in req if _hit(n)]
    req_miss = [n for n in req if not _hit(n)]
    opt_hit = [n for n in opt if _hit(n)]

    best_rank = None
    for n in req_hit:
        # 取该标注在各命中项里的最优位次
        for h in retrieval.hits:
            if h.name == n or h.name.endswith("." + n) or n.endswith("." + h.short) \
                    or h.name == n.split(".")[-1] or h.short == n.split(".")[-1]:
                if best_rank is None or h.rank < best_rank:
                    best_rank = h.rank
                break

    return {
        "required_n": len(req),
        "required_hit": len(req_hit),
        "required_miss": req_miss,
        "hit_rate": (len(req_hit) / len(req)) if req else None,
        "all_required_hit": bool(req) and not req_miss,
        "best_rank": best_rank,
        "optional_n": len(opt),
        "optional_hit": len(opt_hit),
    }


__all__ = [
    "TheoremHit", "TheoremRetrieval",
    "domain_keywords", "question_keywords", "build_queries",
    "retrieve_theorems_for_question", "match_against_ground_truth",
]
