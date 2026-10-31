# -*- coding: utf-8 -*-
"""推导「可复核性」审计（0-LLM，纯函数 + 一个 ctx 账本）。

================================================================
它治的是什么（都是实测铁证，不是推测）
================================================================
铁证 A（假验证声明，可精确判定）——`omni-3556` / E09 三题跑批
`results/20261028-215738/qfaed7d35/04_subgoal_results.jsonl` 第 6 步原文：

    由子目标5已验证 $n=666$ 满足 $666\\mid2^{666}+2$ 且 $100\\le666\\le1997$。
    ……且已分别验证 $2^{666}+2\\equiv0\\pmod2$、$\\pmod3$、$\\pmod9$、$\\pmod{37}$

而精确整数运算给出：`(2^666+2) mod 9 = **3**`、`mod 37 = **1**`
⇒ 这两条「已分别验证」是**假的**。同一份文件的第 5 步自己写着
「模 9 不满足……确实不整除」，第 6 步照样声称验过。
这类东西不是「判断分歧」，是**算术错误**，机械可判。

铁证 B（结论与推导自相矛盾）——同上第 5 步
步骤头部结构化结论是 `本步结论: 值 = 666`，正文却在**最后一次**提到 666 时
写「模 9 不满足」「$n=666$ 已失败」⇒ 结论不是从推导来的。
（这是「本步结果」与「推导过程」两段由不同来源拼接的直接后果。）

铁证 C（跨轮结论冲突无人裁决）——`results/20261027-232401/qfaed7d35/`
同一题在**同一次运行内**跑了 3 轮（子目标编号从 1 重启 3 次）：
  · 第 1 轮末步结论：`n = 66`，还写了「66 不在区间内……区间内无解」；
  · 第 2 轮末步结论：`n = 946`（正确）；
  · 第 3 轮又给 66 / 946 / 「不存在」三说并存。
最终靠某一轮蒙对。既有 `sub_goal_solver__merge._cross_conflicts` 只比
**同一轮内跨子目标**的同名变量（且要求 LHS 是标识符，`值 = 666` 直接跳过）
⇒ 跨轮冲突**根本没有消费者**。

================================================================
口径（为什么这样切）
================================================================
· 判据只用**精确整数运算**与**文本结构**，不含题库文本、题号、具体数值的
  白名单/黑名单 ⇒ 换题库不失效，没有可调参的空间。
· `false_claims` 是**可判定为假**的断言 ⇒ 可以硬打回重解（不违反「宁可放过」：
  放过的是「判断分歧」，不是「算术错」）。
· `conclusion_refuted` / 跨轮冲突是**文本启发式** ⇒ 只做 advisory：进 trace、
  进 merge 提示词要求显式裁决，**不直接淘汰**候选。
"""

from __future__ import annotations

import ast
import re

__all__ = [
    "audit_step",
    "conclusion_value",
    "conclusion_refuted",
    "enabled",
    "note_step",
    "pass_conflicts",
    "reset_ledger",
    "scan_false_claims",
    "verify_note_for_merge",
]

_SWITCH = "step_verification_audit"


def enabled(config=None) -> bool:
    """开关 `step_verification_audit`（默认 True）；读不到时按开处理。"""
    try:
        from .switch_registry import get_bool
        return bool(get_bool(_SWITCH))
    except Exception:  # noqa: BLE001
        return bool(getattr(config, _SWITCH, True))


# ---------------------------------------------------------------- 安全求值
class _Uneval(Exception):
    """表达式无法安全求值（含字母 / 复杂运算 / 超限）——按「不判」处理。"""


_MAX_EXP = 20000          # 指数上限（2^666 合法，2^2^100 拒）
_MAX_BITS = 200000        # 普通求值结果位宽上限

_TEX_SUBS = (
    ("\\left", ""), ("\\right", ""), ("\\!", ""), ("\\,", ""),
    ("\\;", ""), ("\\ ", ""), ("\\cdot", "*"), ("\\times", "*"),
    ("{,}", ""),
)

_ALLOWED = re.compile(r"^[0-9+\-*/%().]+$")


def _tex_to_expr(src: str) -> str:
    """把一小段 LaTeX 算术式转成可解析的 Python 表达式（不做语义替换）。"""
    t = str(src or "").replace("$", "")
    for a, b in _TEX_SUBS:
        t = t.replace(a, b)
    t = re.sub(r"\^\s*\{([^{}]*)\}", r"**(\1)", t)
    t = re.sub(r"\^\s*(-?\d+)", r"**\1", t)
    # ★ 2026-10-29：`2^n` 这种**裸变量指数**。Python 里 `2^n` 是 BitXor 而非幂，
    #   不转会被求值器判成 `_Uneval`（`bounded_search` 首跑 1898 个候选全
    #   `unevaluated` 就是这么来的）。转换后仍受 `_MAX_EXP` 约束。
    t = re.sub(r"\^\s*([A-Za-z])", r"**\1", t)
    t = t.replace(",", "")
    return re.sub(r"\s+", "", t)


def _ev(node, mod, env=None):
    """受限 AST 求值：只允许整数四则与幂；`mod` 非空时全程模运算。

    ★ 2026-10-29：新增 `env` —— 允许 `Name` 节点按 `{变量名: 整数值}` 取值。
    之所以加上它，是为了让 `agent/bounded_search.py` 的穷举**编译一次、取值多次**
    （字符串逐值替换 + 重新 parse 在 1898 个候选上要 23ms，带 env 后 ~2ms）。
    语义一字未变：`env=None` 时 Name 一律 `_Uneval`，与改动前完全一致。
    """
    if isinstance(node, ast.Expression):
        return _ev(node.body, mod, env)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, int) or isinstance(node.value, bool):
            raise _Uneval
        return node.value % mod if mod else node.value
    if isinstance(node, ast.Name):
        if env is None or node.id not in env:
            raise _Uneval
        v = int(env[node.id])
        return v % mod if mod else v
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise _Uneval
        v = _ev(node.operand, mod, env)
        return (-v) % mod if (mod and isinstance(node.op, ast.USub)) else v
    if isinstance(node, ast.BinOp):
        op = node.op
        if isinstance(op, ast.Pow):
            b = _ev(node.left, mod if mod else None, env)
            e = _ev(node.right, None, env)
            if e is None or abs(e) > _MAX_EXP or e < 0:
                raise _Uneval
            if mod:
                return pow(b, e, mod)
            v = pow(b, e)
            if v.bit_length() > _MAX_BITS:
                raise _Uneval
            return v
        if isinstance(op, (ast.FloorDiv, ast.Mod)) and mod:
            # 模运算下 // % 与整体取模不可交换 ⇒ 拒判（宁漏勿误报）
            raise _Uneval
        a = _ev(node.left, mod, env)
        b = _ev(node.right, mod, env)
        if isinstance(op, ast.Add):
            return (a + b) % mod if mod else a + b
        if isinstance(op, ast.Sub):
            return (a - b) % mod if mod else a - b
        if isinstance(op, ast.Mult):
            return (a * b) % mod if mod else a * b
        if isinstance(op, ast.FloorDiv):
            if b == 0:
                raise _Uneval
            return a // b
        if isinstance(op, ast.Mod):
            if b == 0:
                raise _Uneval
            return a % b
        raise _Uneval
    raise _Uneval


def compile_expr(src: str, env_keys):
    """把一段 LaTeX 算术式编译成可反复求值的 AST（变量名必须 ⊆ `env_keys`）。

    编译失败或出现未允许的标识符 ⇒ 返回 None。**只编译，不求值**。
    """
    t = _tex_to_expr(src)
    if not t:
        return None
    try:
        tree = ast.parse(t, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in env_keys:
                return None
    return tree


def eval_expr(tree, env=None, mod=None):
    """对 `compile_expr` 的产物求值；无法确定时返回 None。"""
    if tree is None:
        return None
    try:
        return _ev(tree, mod, env)
    except (_Uneval, SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _eval_int(src: str, mod=None):
    """求值；无法确定时返回 None（调用方一律按「不判」处理）。"""
    t = _tex_to_expr(src)
    if not t or not _ALLOWED.match(t):
        return None
    try:
        return _ev(ast.parse(t, mode="eval"), mod)
    except (_Uneval, SyntaxError, ValueError, RecursionError, MemoryError):
        return None


# ---------------------------------------------------------------- 假断言扫描
_CJK_TAIL = re.compile(r"[^\u4e00-\u9fff]*$")
_EXPLICIT_CONG = re.compile(
    r"\\equiv\s*([^\\$]{1,40}?)\s*\\pmod\s*\{?\s*(\d{1,9})\s*\}?")
_PMOD_ANY = re.compile(r"\\pmod\s*\{?\s*(\d{1,9})\s*\}?")
_DIVIS = re.compile(
    r"(?<![0-9A-Za-z_.])(\d{1,9})\s*(?:\\mid|\\nmid|∣|\|)\s*"
    r"\$?([0-9][^\s$，。；、,]{0,40})")


def _lhs_of(prefix: str) -> str:
    r"""从 `\equiv` 之前的文本里切出左侧表达式（取最后一个数学片段）。"""
    seg = prefix.rsplit("$", 1)[-1]
    seg = re.split(r"[：:，,、。（）()\s]", seg)[-1]
    return seg.strip("$ \\")


_FENCE = re.compile(r"```.*?```", re.DOTALL)
_TICK = re.compile(r"`[^`\n]{0,200}`")


def _strip_code(text: str) -> str:
    """剥掉代码块/行内代码。

    Lean 代码片段里 `have h : 5 ∣ 2 ^ (10 * m - 1) + 1` 是**证法目标**，
    不是数学断言；不剥会把它当断言判假（实测 `5 ∣ 2` 就是这么来的）。
    """
    t = _FENCE.sub(" ", str(text or ""))
    return _TICK.sub(" ", t)


def _split_segments(text: str) -> list:
    """按行与中文句读切成小段（跨段继承 `\\pmod` 会误报，故必须切）。"""
    out = []
    for line in _strip_code(text).split("\n"):
        # markdown 表格行：`| 17 | 110 |` 的竖线是列分隔符，不是整除号。
        # 实测误报（20261013-130346 q5a0b7995）：整张表格被读成 `17 ∣ 110`。
        if line.strip().startswith("|"):
            continue
        for seg in re.split(r"[；;。]", line):
            if seg.count("|") >= 2:
                continue          # 行内表格残留，同样跳过
            out.append(seg)
    return [s for s in out if s.strip()]


_NEG_MARK = ("\\nmid", "\\not\\equiv", "不整除", "不满足", "不成立", "不能整除")


def _negated_elsewhere(text: str, key: str) -> bool:
    """同一表达式在**别处**被显式否定 ⇒ 本处是待验目标而非断言（宁漏勿误报）。"""
    if not key:
        return False
    for m in re.finditer(re.escape(key), text):
        win = text[max(0, m.start() - 60):m.end() + 80]
        if any(k in win for k in _NEG_MARK):
            return True
    return False


def _expr_key(expr: str) -> str:
    """表达式的归一化键（去空白/去 `$`），用于在正文里回找同一式子。"""
    return re.sub(r"\s+", "", str(expr or "").replace("$", ""))


def scan_false_claims(text: str) -> list:
    """返回**可判定为假**的算术断言（人类可读）。空列表 = 未发现假断言。

    只判两类可精确复核的形态：
      ① `A \\equiv B \\pmod{m}`（含紧随其后的 `、\\pmod{m2}` 省略继承）；
      ② `m \\mid E`（m、E 均为具体整数）。
    含字母（符号）的一律不判——那是「未给定」不是「假」。
    """
    bad = []
    for seg in _split_segments(text):
        if "\\not\\equiv" in seg or "\\nmid" in seg:
            continue                      # 显式否定式不是断言
        # ① 同余
        for m in _EXPLICIT_CONG.finditer(seg):
            rhs_raw = m.group(1)
            if "=" in rhs_raw:
                continue                  # `2^6=64\equiv9` 这类链式中段，跳过
            lhs = _lhs_of(seg[:m.start()])
            mod = int(m.group(2))
            lv = _eval_int(lhs, mod)
            rv = _eval_int(rhs_raw, mod)
            if lv is None or rv is None:
                continue
            if (lv - rv) % mod != 0:
                bad.append((
                    "断言 %s ≡ %s (mod %d) 不成立（实算余 %d）"
                    % (lhs, rhs_raw.strip(), mod, (lv - rv) % mod),
                    _expr_key(lhs)))
            # 继承式：`\pmod3`、`\pmod9` 紧随其后、中间无其他同余式
            tail = seg[m.end():]
            for pm in _PMOD_ANY.finditer(tail):
                gap = tail[:pm.start()]
                if "\\equiv" in gap:
                    break
                mod2 = int(pm.group(1))
                if mod2 == mod:
                    continue
                v2 = _eval_int(lhs, mod2)
                r2 = _eval_int(rhs_raw, mod2)
                if v2 is None or r2 is None:
                    continue
                if (v2 - r2) % mod2 != 0:
                    bad.append((
                        "断言 %s ≡ %s (mod %d) 不成立（实算余 %d）"
                        % (lhs, rhs_raw.strip(), mod2, (v2 - r2) % mod2),
                        _expr_key(lhs)))
        # ② 整除
        for m in _DIVIS.finditer(seg):
            if m.group(0).lstrip()[len(m.group(1)):].lstrip().startswith("\\nmid"):
                continue
            try:
                mod = int(m.group(1))
            except ValueError:
                continue
            rhs = m.group(2)
            if mod in (0, 1):
                continue
            v = _eval_int(rhs)
            if v is None:
                continue
            if v % mod != 0:
                bad.append((
                    "断言 %d ∣ %s 不成立（实算余 %d）"
                    % (mod, rhs.strip(), v % mod),
                    _expr_key(rhs)))
    # 去重（同一断言在正文多次出现）
    seen, out = set(), []
    for x, key in bad:
        if _negated_elsewhere(_strip_code(text), key):
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:6]


# ---------------------------------------------------------------- 结论自洽
_CONCL = re.compile(
    r"本步结论\s*[:：]\s*(?:值|答案|结果|数值|最终答案|结论值)\s*=\s*"
    r"([^\n]{1,80})")


def conclusion_value(text: str):
    """从【本步结论】头部取**数值型**结论；非数值（判定/等式/文字）返回 None。"""
    m = _CONCL.search(str(text or ""))
    if not m:
        return None
    raw = m.group(1).strip().strip("$ ")
    if not _ALLOWED.match(_tex_to_expr(raw)):
        return None
    return raw


# 「本步结论的值被自己的正文否掉」——只认**紧邻**形态（V 不满足 / V 已失败 …）。
# 不用「窗口内找关键词」：实测 omni-3556 第 5 步正文里 `\not\equiv` 与 `满足`
# 交替出现，任何窗口式判据都会把「先试错后放弃」读成「验证通过」。
_REFUTE_NEXT = ("不满足", "已失败", "不行", "不成立", "不整除", "无法满足",
                "被排除", "不可行", "均失败")


def conclusion_refuted(text: str, value: str) -> bool:
    """正文是否**紧邻地**判定「本步结论的那个值」不成立。

    判据：`V` 之后 6 个字符内出现否定词（允许中间夹 `$`、空格、全角标点）。
    只认紧邻，是为了不被正文里别的候选值的讨论带偏（宁漏勿误报）。
    """
    if not value:
        return False
    v = value.strip().strip("$")
    if not v:
        return False
    pat = re.compile(
        re.escape(v) + r"[\s$，,：:）)]{0,6}(?:" + "|".join(_REFUTE_NEXT) + r")")
    return bool(pat.search(str(text or "")))


_VERIFY_CLAIM = re.compile(
    r"已(?:经)?(?:分别)?(?:验证|验算|检查|核对)|经验证|容易验证|易验证|"
    r"显然成立|无需验证|证明完毕")


def audit_step(text: str) -> dict:
    """单步审计：返回 `{conclusion, false_claims, conclusion_refuted, unverifiable}`。"""
    t = str(text or "")
    concl = conclusion_value(t)
    false_claims = scan_false_claims(t)
    refuted = bool(concl) and conclusion_refuted(t, concl)
    # 「声称验证过」但整段没有任何可复核算式 ⇒ 不可复核
    unverifiable = []
    if _VERIFY_CLAIM.search(t):
        n_ops = (t.count("\\equiv") + t.count("\\pmod")
                 + t.count("\\mid") + t.count("∣"))
        if n_ops == 0:
            unverifiable.append("声称已验证，但正文无任何可复核的算式（同余/整除/代入）")
    return {
        "conclusion": concl,
        "false_claims": false_claims,
        "conclusion_refuted": refuted,
        "unverifiable": unverifiable,
    }


# ---------------------------------------------------------------- 跨轮账本
def reset_ledger(ctx) -> dict:
    """初始化/清空本题账本（每次 run 起始调用一次，重复调用不得丢数据）。"""
    led = getattr(ctx, "_verify_ledger", None)
    if not isinstance(led, dict) or led.get("run_reset") is not True:
        led = {"pass": 1, "steps": [], "false": [], "refuted": [],
               "unverifiable": [], "answers": [], "run_reset": True}
        try:
            setattr(ctx, "_verify_ledger", led)
        except Exception:  # noqa: BLE001
            pass
    return led


def note_step(ctx, item: dict) -> dict:
    """把一步结果登记进账本；返回该步审计结果（异常一律放行）。

    **轮次判定**：子目标编号回到 1 且账本非空 ⇒ 新一轮（实测 3556 一次运行内
    重启 3 次编号，与 3 遍迭代/重规划一一对应）。
    """
    try:
        led = reset_ledger(ctx)
        sid = item.get("id")
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            sid_int = None
        if sid_int == 1 and led["steps"]:
            led["pass"] += 1
        text = str(item.get("result") or "")
        res = audit_step(text)
        entry = {"pass": led["pass"], "id": sid, "title": str(item.get("title") or "")}
        led["steps"].append(entry)
        if res["false_claims"]:
            led["false"].append(dict(entry, claims=res["false_claims"]))
        if res["conclusion_refuted"]:
            led["refuted"].append(dict(entry, value=res["conclusion"]))
        if res["unverifiable"]:
            led["unverifiable"].append(dict(entry, notes=res["unverifiable"]))
        if res["conclusion"]:
            # 同一轮内后写覆盖前写（末步结论 = 该轮的答案主张）
            while len(led["answers"]) < led["pass"]:
                led["answers"].append(None)
            led["answers"][led["pass"] - 1] = {
                "id": sid, "value": res["conclusion"],
                "title": str(item.get("title") or "")}
        return res
    except Exception:  # noqa: BLE001  审计是增益，绝不阻断求解
        return {"conclusion": None, "false_claims": [],
                "conclusion_refuted": False, "unverifiable": []}


def _equivalent(a: str, b: str) -> bool:
    try:
        from .verifier__cluster import _are_answers_equivalent as _eq
        return bool(_eq(None, a, b))
    except Exception:  # noqa: BLE001  判定不可用时按「不冲突」处理（宁漏勿误报）
        return True


def pass_conflicts(ctx) -> list:
    """跨轮结论冲突清单（人类可读）。空 = 未发现。

    只比**各轮末步结论**，不比中间步：中间步给不同量是正常的（一题多问），
    而「同一题的答案在两轮里不同」必然是错的。
    """
    led = getattr(ctx, "_verify_ledger", None)
    if not isinstance(led, dict):
        return []
    ans = [a for a in (led.get("answers") or []) if a]
    if len(ans) < 2:
        return []
    out = []
    for i in range(len(ans)):
        for j in range(i + 1, len(ans)):
            a, b = ans[i], ans[j]
            if _equivalent(str(a["value"]), str(b["value"])):
                continue
            out.append(
                "第 %d 轮（子目标 #%s）末步结论 %s，与第 %d 轮（子目标 #%s）"
                "末步结论 %s 不等价——同一题不可能同时成立，须显式裁决"
                % (i + 1, a.get("id"), a["value"], j + 1, b.get("id"), b["value"]))
    return out[:4]


def verify_note_for_merge(ctx) -> str:
    """给合并提示词用的审计结论块（无内容返回空串，不污染提示词）。"""
    led = getattr(ctx, "_verify_ledger", None)
    if not isinstance(led, dict):
        return ""
    parts = []
    if led.get("false"):
        lines = []
        for e in led["false"][:4]:
            lines.append(
                "  · 第 %d 轮 子目标 #%s「%s」—— %s"
                % (e.get("pass"), e.get("id"), str(e.get("title"))[:40],
                   "；".join(e.get("claims") or [])[:220]))
        parts.append(
            "【算术复核失败（精确整数运算判定，非评审意见）】\n"
            + "\n".join(lines))
    if led.get("refuted"):
        lines = [
            "  · 第 %d 轮 子目标 #%s 头部结论 `%s` 在正文中被判定不成立"
            % (e.get("pass"), e.get("id"), e.get("value"))
            for e in led["refuted"][:4]]
        parts.append("【本步结论与自身推导冲突】\n" + "\n".join(lines))
    if led.get("unverifiable"):
        lines = [
            "  · 第 %d 轮 子目标 #%s —— %s"
            % (e.get("pass"), e.get("id"),
               "；".join(e.get("notes") or [])[:160])
            for e in led["unverifiable"][:4]]
        parts.append("【验证不可复核（只写「已验证」，无算式）】\n" + "\n".join(lines))
    cfl = pass_conflicts(ctx)
    if cfl:
        parts.append("【跨轮结论冲突】\n" + "\n".join("  · " + c for c in cfl))
    if not parts:
        return ""
    return (
        "\n\n【⚠ 系统推导审计（最高优先级，必须先处理）】\n"
        + "\n".join(parts)
        + "\n上述条目中，**算术复核失败**是精确算出来的（不是意见），"
        "对应结论不得采用；其余条目须在【矛盾检查】里逐条裁决："
        "指出冲突双方主张、依据原题条件复核判定哪一方错误、给出修正值。"
        "**禁止未处理这些条目就直接输出【最终答案】。**")
