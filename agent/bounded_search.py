# -*- coding: utf-8 -*-
"""有界存在性命题的机械搜索：穷举 + 精确验证 + 排除记录（0-LLM）。

问题背景
--------
2.7 蓝图把「找一个满足条件的对象」当成「证明一堆引理」来拆。铁证 `omni-3556`
（`100 ≤ n ≤ 1997`，求 `(2^n+2)/n ∈ ℤ`）：**关臂 6 步判对（946，2.0h）**、
开臂 22 步 + 3 个假引理 ⇒ 池空 5.7h。而本题用 Python 穷举 1898 个候选
**只需 0.63 ms**。

根因不是提示词写得不好，而是**系统里根本没有搜索器**：「存在一个 n」这类命题
只能靠猜，猜错就再造一个生成该猜测的引理 —— 机制上必然产物。

本模块补的正是这一块：**有限域上可判定的存在性命题，用代码穷举给出
① 命中值 ② 可独立复核的证书 ③ 排除记录**。三个出口都必须是诚实的：

- 命中 ⇒ 命中值 + 每个命中值的逐素数幂余数证书（任何模幂实现都能复算，
  不需要相信生成者）；
- 全不命中 ⇒「已逐个检验 N 个值、全部不满足」的**排除记录**（系统一直缺的
  就是这份记录，所以模型只能靠「我觉得没有别的了」来收尾）；
- 判不了（表达式含未支持运算 / 定义域太大 / 有候选求值失败 / 超时）⇒
  **显式 refuse 并写明理由**，绝不把部分结果冒充完整结果。

★★ 定位（2026-10-29 E13 定调，读本文件前必读）
--------------------------------------------------
本模块**不是一个通用搜索器**，它由三件性质完全不同的东西拼成，不要整体理解：

| 部件 | 性质 | 是否过拟合 | 处置 |
|---|---|---|---|
| `detect()` + `_find_condition` / `_find_domain` | **特例白名单**：只认下面三种题面形态 | **是**（见下） | 保留可用，**禁止再增形态** |
| `run_search()` / `_certificate()` / `_factor()` | **通用执行器**：接受「域 + 可求值谓词」，逐个精确验证并出证 | 否（与题型无关） | **保留**，未来 spec 执行器直接复用 |
| `render_block()` / `exclusive` 语义 | **结论格式**：命中值 / 证书 / 排除记录 / refuse | 否 | **保留**，这是系统最缺的东西 |

`detect()` 的实测覆盖率（2026-10-29，评估床 `probe_search_expressible.py`）：

- omni 全量 4428 题：**认出 1 道 = 0.02%**（`omni-3556`）；该题 `run_search` 成功、
  唯一命中 946 = gold。
- 客观筛出的同类语义域「有界量词 ∧ (整除 | is an integer)」= **46 / 4428 = 1.0%**，
  ⇒ 本模块在语义域内只覆盖 **1/46 = 2.2%**。
- official112 = **0/112**（该库无「有界 ∃ + 整除」形态，是题库分布，不是缺陷）。

⚠ **因此**：`detect()` 的命中率**不得**作为「系统具备搜索能力」的证据；
`omni8 1/8` 那种数字是在 `P(答案纯整数)=1` 的**条件样本**内取得的（全量仅 45.7%），
属条件概率冒充边际概率。**任何「给新题型族再写一个检测器」的改动都是过拟合，一律不批**——
通用性只能来自「通用执行器 + 模型产出 spec」，届时 `detect()` 降级为一个无 LLM 的 spec 生成器。

保留它进生产链路的理由（三条，都不是「覆盖率」）：
① 误命中率为 0（唯一命中的那道 gold 正确）；② 命中时收益极大（3556：7ms 得解，
   对比实跑 209min 池空）；③ 不命中时 `ensure()` 返回 `None`、提示词逐字不变，成本≈0。

v1 覆盖的条件形态（一律归约为「`den(k)` 整除 `num(k)`」）
----------------------------------------------------------
★ 这是**特例白名单**，不是能力清单。
  a) `\\frac{num}{den}` 后跟 `is an integer` / `是整数` / `\\in\\mathbb{Z}`
  b) `den \\mid num`（含 `|`、`divides`）
  c) `num \\equiv 0 \\pmod{den}`

刻意**不收**：符号多于一个、定义域非区间、含 `\\sqrt`/三角函数/取整/未支持运算。
宁可少认，不可错认 —— 一个错误的「已穷举」比没有搜索器更坏。

复用 `agent/verification_audit.py` 里的受限整数求值器（`_tex_to_expr` /
`_eval_int` / `_Uneval`），保证与 E10 的算术复核同一套口径：只用精确整数，
指数 ≤ 2e4、位宽 ≤ 2e5，`mod` 模式走 `pow(b, e, m)`。
"""
from __future__ import annotations

import re
import time

from .verification_audit import _tex_to_expr, compile_expr, eval_expr

# ---------------------------------------------------------------- 常量
SWITCH = "bounded_search"

SEARCH_CAP = 200_000        # 候选个数上限（超出即 refuse，不猜"够用"）
TIME_BUDGET_S = 2.0         # 单题搜索墙钟上限
_FRAC_TAIL = 80             # `\frac{}{}` 之后看多少字符找 "is an integer"

_INT_WORDS = (
    "is also an integer", "are also integers", "is an integer", "are integers",
    "is integer", "is a positive integer",
    "是整数", "为整数", "均为整数", "都是整数",
    "\\in\\mathbb{z}", "\\in \\mathbb{z}", "\\in\\mathbf{z}",
)

# `100 \leq n \leq 1997` 一类（含 ≤ / <= / <）
_RANGE2 = re.compile(
    r"(?P<lo>-?\d+)\s*(?P<op1>\\leq?|\\le|≤|<=|<|\\lt)\s*\$?\s*"
    r"(?P<var>[A-Za-z])\s*\$?\s*"
    r"(?P<op2>\\leq?|\\le|≤|<=|<|\\lt)\s*(?P<hi>-?\d+)"
)
_RANGE_HI = re.compile(
    r"(?P<var>[A-Za-z])\s*(?P<op>\\leq?|\\le|≤|<=|<|\\lt)\s*\$?\s*(?P<hi>\d+)"
)
_POSITIVE = ("positive integer", "positive integers", "正整数", "正整數")

_SLASH = re.compile(r"\(\s*([^()]{1,40}?)\s*\)\s*/\s*([A-Za-z0-9]{1,10})")

_STRICT = ("<", "\\lt")


# ---------------------------------------------------------------- LaTeX 小工具
def _match_brace(s: str, i: int) -> int:
    """`s[i] == '{'`，返回配对 `}` 的下标；不配对返回 -1。"""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _find_fracs(text: str) -> list:
    """取出所有 `\\frac{num}{den}`，返回 [(num, den, 结束下标)]。"""
    out = []
    for m in re.finditer(r"\\frac\s*", text):
        i = m.end()
        if text[i:i + 1] != "{":
            continue
        j = _match_brace(text, i)
        if j < 0:
            continue
        num = text[i + 1:j]
        k = j + 1
        while k < len(text) and text[k] in " \t":
            k += 1
        if text[k:k + 1] != "{":
            continue
        l = _match_brace(text, k)
        if l < 0:
            continue
        out.append((num, text[k + 1:l], l + 1))
    return out


def _letters(expr: str) -> list:
    """表达式里出现的**变量字母**（按出现顺序去重；纯数字返回空）。"""
    seen = []
    for ch in expr:
        if ch.isalpha() and ch not in seen:
            seen.append(ch)
    return seen


# ---------------------------------------------------------------- 命题识别
def _find_condition(text: str):
    """识别条件形态，返回 (num_src, den_src, tag) 或 None。

    ★ 刻意**不认**英文自然语言 `X divides Y` / `Y is divisible by X`：把
    `n divides 2^n + 2` 的算子边界切错会得到**错的谓词**，而错的「已穷举」
    比没有搜索器更坏（宁可就地 refuse，交给 LLM）。
    """
    low = text.lower()
    # a) \frac{num}{den} is an integer
    for num, den, end in _find_fracs(text):
        tail = low[end:end + _FRAC_TAIL]
        if any(w in tail for w in _INT_WORDS):
            return num, den, "frac_integer"
    # a2) (num)/den is an integer —— 纯斜杠写法（不含 \frac）
    for m in _SLASH.finditer(text):
        tail = low[m.end():m.end() + _FRAC_TAIL]
        if any(w in tail for w in _INT_WORDS):
            return m.group(1), m.group(2), "slash_integer"
    # b) den \mid num（取 \mid 前最后一个词作除数，切到下一个 $/句读作被除数）
    m = re.search(r"\\mid|∣", text)
    if m:
        prefix = re.sub(r"\$", "", text[:m.start()]).rstrip()
        toks = [t for t in re.split(r"[\s,，。;；]+", prefix) if t]
        den = toks[-1].strip(" $\\") if toks else ""
        right = re.split(r"[\$。\.,，;；]|\\\]", text[m.end():], maxsplit=1)[0]
        if den and right.strip():
            return right.strip(" $\\"), den, "divides"
    # c) num \equiv 0 \pmod{den}
    m = re.search(r"(?P<lhs>[^$\s]{1,40})\s*\\equiv\s*0\s*\\pmod\s*\{?(?P<m>\d{1,9})\}?",
                  text)
    if m:
        return m.group("lhs"), m.group("m"), "congruence"
    return None


def _find_domain(text: str, var: str):
    """识别定义域区间，返回 (lo, hi) 或 None。"""
    for m in _RANGE2.finditer(text):
        if m.group("var") != var:
            continue
        lo, hi = int(m.group("lo")), int(m.group("hi"))
        if m.group("op1") in _STRICT:
            lo += 1
        if m.group("op2") in _STRICT:
            hi -= 1
        return lo, hi
    for m in _RANGE_HI.finditer(text):
        if m.group("var") != var:
            continue
        hi = int(m.group("hi"))
        if m.group("op") in _STRICT:
            hi -= 1
        if any(w in text.lower() for w in _POSITIVE):
            return 1, hi
    return None


def detect(problem: str):
    """从题面识别一条可机械搜索的有界存在性命题。

    ★ 特例白名单（E13）：全量 4428 题只命中 0.02%，**不得**把它的命中率当作
    系统搜索能力的证据；**禁止在此增形态**（新增形态 = 把见过的题写进代码）。
    真正要扩的是 `run_search()` 可接受的谓词表达力，不是这里的正则。

    返回 dict：`{var, lo, hi, num, den, tag, predicate}`；识别不到返回 None。
    """
    text = str(problem or "")
    if not text.strip():
        return None
    cond = _find_condition(text)
    if cond is None:
        return None
    num, den, tag = cond
    letters = list(dict.fromkeys(_letters(_tex_to_expr(num))
                                 + _letters(_tex_to_expr(den))))
    if len(letters) != 1:
        # 0 个字母（纯常数条件）或 >1 个字母 ⇒ 本模块不认，交给 LLM
        return None
    var = letters[0]
    dom = _find_domain(text, var)
    if dom is None:
        return None
    lo, hi = dom
    if lo > hi:
        return None
    return {
        "var": var, "lo": lo, "hi": hi,
        "num": num.strip(), "den": den.strip(),
        "tag": tag,
        "predicate": "%s | %s" % (den.strip(), num.strip()),
    }


# ---------------------------------------------------------------- 证书
def _factor(n: int):
    """质因数分解；分解不了返回 None（证书随之降级为「未分解」）。"""
    n = abs(int(n))
    if n < 2:
        return []
    try:
        from sympy import factorint
        return sorted((int(p), int(e)) for p, e in factorint(n).items())
    except Exception:  # noqa: BLE001
        pass
    out, d = [], 2
    while d * d <= n and d <= 1_000_000:
        if n % d == 0:
            e = 0
            while n % d == 0:
                n //= d
                e += 1
            out.append((d, e))
        d += 1 if d == 2 else 2
    if n > 1:
        out.append((n, 1))
    return sorted(out)


def _certificate(num_tree, var: str, k: int, den_val: int) -> dict:
    """逐素数幂余数证书：`den(k)` 分解成 ∏ p^e，逐个复算 `num(k) mod p^e`。"""
    fac = _factor(den_val)
    entry = {"n": k, "den": den_val, "factorization": fac, "residues": []}
    if not fac:
        return entry
    for p, e in fac:
        q = p ** e
        entry["residues"].append([q, eval_expr(num_tree, {var: k}, mod=q)])
    return entry


# ---------------------------------------------------------------- 搜索
def run_search(spec: dict, cap: int = SEARCH_CAP,
               budget_s: float = TIME_BUDGET_S) -> dict:
    """在 `[lo, hi]` 上逐个精确验证 `den | num`。

    返回 dict（**所有分支都带 `ok` 与 `reason`，不抛异常**）：
      ok / reason / var / lo / hi / predicate / checked / skipped /
      unevaluated / hits / certificate / exclusive / elapsed_ms
    """
    var, lo, hi = spec["var"], int(spec["lo"]), int(spec["hi"])
    total = hi - lo + 1
    base = {
        "ok": False, "reason": "", "var": var, "lo": lo, "hi": hi,
        "predicate": spec.get("predicate", ""), "tag": spec.get("tag", ""),
        "num": spec.get("num", ""), "den": spec.get("den", ""),
        "checked": 0, "skipped": 0, "unevaluated": 0,
        "hits": [], "certificate": [], "exclusive": False, "elapsed_ms": 0.0,
    }
    if total <= 0:
        base["reason"] = "empty_range"
        return base
    if total > cap:
        base["reason"] = "range_too_large(%d>%d)" % (total, cap)
        return base
    num_tree = compile_expr(spec["num"], {var})
    den_tree = compile_expr(spec["den"], {var})
    if num_tree is None or den_tree is None:
        base["reason"] = "unsupported_expr"
        return base

    t0 = time.perf_counter()
    hits, skipped, uneval, checked = [], 0, 0, 0
    timed_out = False
    for idx, k in enumerate(range(lo, hi + 1)):
        if idx % 512 == 0 and (time.perf_counter() - t0) > budget_s:
            timed_out = True
            break
        den_val = eval_expr(den_tree, {var: k})
        if den_val is None:
            uneval += 1
            continue
        if den_val == 0:
            skipped += 1
            continue
        r = eval_expr(num_tree, {var: k}, mod=abs(den_val))
        if r is None:
            uneval += 1
            continue
        checked += 1
        if r == 0:
            hits.append(k)

    base["checked"] = checked
    base["skipped"] = skipped
    base["unevaluated"] = uneval
    base["hits"] = hits
    base["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    if timed_out:
        base["reason"] = "timeout(%.1fs)" % budget_s
        return base
    if uneval:
        # 有候选求值失败 ⇒ 无法声称"全部检验过"，绝不能冒充完整结果
        base["reason"] = "unevaluated(%d)" % uneval
        return base
    base["certificate"] = [_certificate(num_tree, var, k,
                                        eval_expr(den_tree, {var: k}) or 0)
                           for k in hits[:20]]
    base["ok"] = True
    base["exclusive"] = True
    base["reason"] = "ok"
    return base


# ---------------------------------------------------------------- 渲染
def render_block(res) -> str:
    """把搜索结果渲染成注入提示词的文本块；无结果返回空串。"""
    if not res or not res.get("ok"):
        return ""
    var, lo, hi = res["var"], res["lo"], res["hi"]
    total = hi - lo + 1
    hits = res["hits"]
    head = (
        "【机械搜索结论（代码穷举，可直接引用为已确立事实）】\n"
        "条件：`%s`，即 `%s` 整除 `%s`。\n"
        "搜索域：%s = %d…%d 共 %d 个整数，逐个用**精确整数运算**判定"
        "（用时 %.2f ms，未采样、未近似）。\n"
        % (res.get("predicate", ""), res.get("den", ""), res.get("num", ""),
           var, lo, hi, total, res.get("elapsed_ms", 0.0))
    )
    if hits:
        cert_lines = []
        for c in res.get("certificate") or []:
            fac = c.get("factorization")
            if not fac:
                continue
            fac_txt = " × ".join("%d^%d" % (p, e) for p, e in fac)
            res_txt = "、".join("mod %d 余 %d" % (q, r) for q, r in c["residues"])
            cert_lines.append("  · %s = %s；逐素数幂复算：%s（全为 0）"
                              % (c["n"], fac_txt, res_txt))
        body = ("命中：%s\n" % "、".join(str(h) for h in hits[:40])
                + ("（共 %d 个，此处列前 40）\n" % len(hits) if len(hits) > 40 else ""))
        if cert_lines:
            more = "" if len(cert_lines) <= 6 else "（前 6 个，其余同法）"
            body += ("可独立复核的证书%s：\n" % more
                     + "\n".join(cert_lines[:6]) + "\n")
        rest = total - len(hits)
        body += ("排除记录：**其余 %d 个取值已逐个检验，全部不满足**"
                 "（不是「没找到」，是「已排除」）。\n" % rest)
        tail = (
            "⚠ 因此「是否存在该取值」与「是否唯一」已由机械验证终结：**不要再假设、"
            "猜测或另找其他取值**。后续步骤只需 ① 给出这一取值的显式构造/表达式，"
            "② 按定义逐条复核条件，③ 若题目要求「所有 / 最大」则说明排除依据。\n"
        )
    else:
        body = "命中：**空集**（%d 个取值全部不满足）。\n" % total
        tail = (
            "⚠ 因此若题目要求「存在」，则本题在给定定义域内**无解**；"
            "若题目要求「最大 / 最小」，请回到题面核对定义域是否抄全"
            "（本搜索只覆盖上述区间）。\n"
        )
    return head + body + tail


# ---------------------------------------------------------------- 接线入口
def enabled(config=None) -> bool:
    """开关 `bounded_search`（默认 True）；读不到时按开处理。"""
    try:
        from .switch_registry import get_bool
        return bool(get_bool(SWITCH))
    except Exception:  # noqa: BLE001
        return bool(getattr(config, SWITCH, True))


def ensure(ctx, config=None) -> dict | None:
    """每道题只算一次（缓存在 `ctx.bounded_search`）；识别不到返回 None。"""
    if not enabled(config if config is not None else getattr(ctx, "config", None)):
        return None
    if getattr(ctx, "_bounded_search_done", False):
        return getattr(ctx, "bounded_search", None)
    setattr(ctx, "_bounded_search_done", True)
    res = None
    try:
        spec = detect(getattr(ctx, "problem", "") or "")
        if spec is not None:
            res = run_search(spec)
            if not res.get("ok"):
                res = None          # refuse 不注入，但留痕在 ctx._bounded_search_refuse
                setattr(ctx, "_bounded_search_refuse", spec.get("predicate", ""))
    except Exception:  # noqa: BLE001  搜索是增益，失败绝不阻断主流程
        res = None
    if res:
        setattr(ctx, "bounded_search", res)
    return res


def summary(res) -> str:
    """一行摘要（落 trace / diag 用）。"""
    if not res:
        return "bounded_search: 未命中可机械搜索的有界存在性命题"
    if not res.get("ok"):
        return "bounded_search: refuse (%s)" % res.get("reason", "")
    return ("bounded_search: %s ∈ [%d,%d] 共 %d 值，命中 %d 个 %s（exclusive=%s, %.2fms）"
            % (res["var"], res["lo"], res["hi"], res["hi"] - res["lo"] + 1,
               len(res["hits"]), res["hits"][:5], res["exclusive"],
               res.get("elapsed_ms", 0.0)))
