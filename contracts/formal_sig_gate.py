# -*- coding: utf-8 -*-
"""形式签名的三道门 —— 契约层零依赖，主流程与回放床共用同一份口径。

## 先纠正上一轮的建议：「禁止 sorry 入库」是错的

`prompts/blueprint.py` 明确要求蓝图只**陈述命题**、证明体留给求解侧，
`formal_sig` 的合法形态就是 `example ... := by sorry`。禁掉它等于禁掉整个
「证什么 / 怎么证」的分工。E29 说的「sorry 是双重遮蔽」，遮蔽的不是签名本身，
而是**把带 sorry 的编译通过当成「已形式化」的证据**。

`sorry` 在三个位置，语义完全不同：

===== ============================= ==========================================
位置   含义                          处置
===== ============================= ==========================================
S1     蓝图签名尾部 `:= by sorry`    声明占位，**设计如此**，不该禁；
                                     但必须真编译确认「命题可陈述」
S2     求解侧补的证明体              没证出来 ⇒ **作弊**，必须禁
S3     最终拼接代码的编译            `_lean_block_verify` 用 `allow_sorry=True`
                                     让它算 pass ⇒ 「工具说通过」的假凭证
===== ============================= ==========================================

⇒ 门 A 检查 **S1 的命题**（保留 sorry 编译，只校验 elaboration）；
  门 B 检查**命题非平凡**（挡 `True` / `A=A` / `∈ Set.univ`）；
  门 C 检查 **S2/S3 的证明凭证**（不许 sorry / axiom）。

## ★ 门 A 与「能否证明」必须分开

`replay_lean_close.classify()` 把 sorry 换成自动策略，判的是「能不能证出」，
失败里混着「命题非法」和「策略不够」两类。本模块的 `classify_stated()` 保留
`by sorry` 原样编译：Lean 仍会 elaborate 命题（未定义符号/语法错照样报错），
但证明体被 sorry 直接结束 ⇒ **不会**产生 unsolved goals。
这才是「命题是否可陈述」的纯净判据，也是唯一能零成本挡住
E29 里那 37% 编造记号（`Φ` / `rotate_cw` / `path_length`）的办法。
两者**不得混用**，也不得共用一个分类函数。

## ★★ 影子模式（默认）

`evaluate()` 只产出 verdict，**不执行编译、不丢弃签名、不阻断任何流程**。
理由：
  1. E29 实测闸门后有效硬闭合 = 0（151 条形式签名，PASS 0）。此刻真接门，
     等于把所有产出一次性砍光，得不到任何可比较的信号。
  2. E27（符号表）/ E29（四分类）两次证明：**未经抽验的判据直接接进生产，
     必然被下一轮抽验打回并回滚**。
调用方当前只把 verdict 写进诊断字段。真正启用前必须：
  - 在留出集上跑「若生效会砍谁」，逐条人工抽验；
  - 显式登记开关（四表同步 + LIFECYCLE），不得靠默认开启。

## ★ compile_result 缺失 ≠ 放行

`compile_result is None` ⇒ stage `UNVERIFIED`，`allowed=False`。
E27 的教训是「静默放行会让分母塌掉、数字好看但没有任何判定」；
项目硬约束「宁可显式失败留痕」在这里的具体落点就是这一条。

## 判据的能力边界

`is_trivial_prop()` 是**保守下界**：只认 5 种最明确的退化形态，
漏判一律返回空串（= 看不出），**绝不等于「已确认非平凡」**。
不要把它当完备判据报覆盖率；未被识别但可疑的条目必须留给人工抽验。
"""

from __future__ import annotations

import re

__all__ = [
    "SORRY_RE", "TAIL_RE", "TRIVIAL_RULES", "UNTRUSTED_RE",
    "split_sig", "is_trivial_prop", "illegal_kind", "classify_stated",
    "proof_credential", "evaluate",
]

# 占位证明（sorry / admit）。★ 与 contracts.closure.FAIL_WORDS 同口径：
# 带 sorry 的证明**编译能通过**，不识别就会把骨架当成已闭合。
SORRY_RE = re.compile(r"\b(sorry|admit|sorryAx)\b")
TAIL_RE = re.compile(r":=\s*by\s*(?:sorry|admit)\s*$", re.S)

# 证明体里的其它不可信构造。★ 保守：只列明确等价于「没证」的几种，
# 不猜语义、不做词法剥离（注释里出现 sorry 会误伤 ⇒ 宁可显式失败留痕，
# 由调用方决定要不要复核，而不是悄悄放行）。
UNTRUSTED_RE = re.compile(
    r"\b(sorry|admit|sorryAx|axiom|implemented_by|unsafe)\b")

# 非法命题的原因细分（顺序即优先级）。★ 大小写不敏感：
# Lean 同时会写 `unknown identifier` 与 `Unknown constant`。
ILLEGAL_KINDS = (
    ("未定义符号", r"unknown (identifier|constant|namespace|free variable)"),
    ("语法/括号", r"unexpected token|expected token|expected '|unexpected identifier"),
    ("类型实例缺失", r"failed to synthesize|synthInstanceFailed"),
    ("字段/应用不存在", r"Function expected|Application type mismatch|Invalid field|unknown field"),
)

# 退化命题的**保守**识别（E29 抽验出的 5 种形态，6/6 覆盖）。
TRIVIAL_RULES = (
    ("命题就是True", re.compile(r"^True\s*$")),
    ("A=A重言式", re.compile(r"^\s*(.+?)\s*=\s*\1\s*$")),
    ("属于Set.univ", re.compile(r"∈\s*\(?\s*Set\.univ")),
    ("存在性直接取等", re.compile(
        r"^∃\s*\(?\s*([A-Za-z]\w*)\s*(?::[^,)]+)?\s*\)?\s*,\s*\1\s*=", re.U)),
    ("恒等函数", re.compile(r"\(fun\s+(\w+)\s*:[^)]*=>\s*\1\s*\)", re.U)),
)


def split_sig(sig):
    """拆出 (声明头, 命题)。失败返回 None。

    先剥掉尾部 `:= by sorry`，再取**括号深度为 0 的第一个冒号**作分隔。
    ★ 三种错法都实测过：非贪婪 `^(.*?):` 会切开类型标注；从右往左找最后一个
    冒号会在 `∀ k : ℕ` 处切开；平扫不看深度又会在 `(x : ℝ)` 处切开。
    """
    m = TAIL_RE.search((sig or "").strip())
    if not m:
        return None
    core = (sig or "").strip()[:m.start()].rstrip()
    depth = 0
    for i, ch in enumerate(core):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            if i == 0:
                return None
            return core[:i].rstrip(), core[i + 1:].strip()
    return None


def is_trivial_prop(prop):
    """保守判「命题是不是空的」。返回原因串；空串 = 看不出（≠ 非平凡）。"""
    s = (prop or "").strip()
    for name, pat in TRIVIAL_RULES:
        if pat.search(s):
            return name
    return ""


def illegal_kind(full_err):
    """非法命题的原因细分。回放床与主流程共用，避免两份正则漂移。"""
    for name, pat in ILLEGAL_KINDS:
        if re.search(pat, full_err or "", re.I):
            return name
    return "其它"


def classify_stated(returncode, full_err):
    """门 A：**命题可陈述**判定。返回 (类别, 原因)。

    输入是「保留 `:= by sorry` 原样编译」的结果：
      - `STATABLE` 命题能被 Lean elaborate（未定义符号/类型/语法都没问题）
      - `ILLEGAL` 命题根本写不出来（编造记号、括号、类型实例缺失）
      - `TIMEOUT` 编译器超时，不算通过

    ★ Lean 4 把 `declaration uses 'sorry'` 记为 **warning**，returncode 仍为 0。
      这正是本判据能工作的原因：sorry 跳过证明，但**不跳过命题 elaboration**。
    ★★ 不要复用 `replay_lean_close.classify()`：那个判的是「自动策略能否证出」，
      会把「策略不够」与「命题非法」混在一起（E29 已在此栽过一次）。
    """
    err = full_err or ""
    # ★ 不能写 `int(returncode or 1)`：0 是 falsy ⇒ 编译成功会被算成失败。
    rc = int(0 if returncode is None else returncode)
    if "TIMEOUT" in err and rc != 0:
        return "TIMEOUT", "编译超时"
    fatal = [ln for ln in err.splitlines()
             if "error" in ln and "warning" not in ln.lower()]
    if rc == 0 and not fatal:
        return "STATABLE", ""
    if fatal:
        return "ILLEGAL", illegal_kind("\n".join(fatal))
    return "ILLEGAL", "编译非零退出但无结构化 error 行"


def proof_credential(code):
    """门 C：**证明凭证**判定。返回 (类别, 原因)。

      - `EMPTY`  没有证明体
      - `SORRY`  仍是占位（sorry / admit / axiom / unsafe）⇒ 不算证出
      - `OK`     未见不可信构造（**不等于已编译通过**，编译是另一道门）

    ★ 传入的必须是 `_compose_formal_sig` 之后的**最终代码**：签名尾部的
      `:= by sorry` 已被剥掉，此时再出现 sorry 只可能来自求解侧证明体。
    """
    s = code or ""
    if not s.strip():
        return "EMPTY", "无证明体"
    m = UNTRUSTED_RE.search(s)
    if m:
        return "SORRY", "含不可信构造 %r" % m.group(1)
    return "OK", ""


def evaluate(sig, compile_result=None, proof_code=None):
    """三道门按序短路，产出**影子** verdict（dict，不阻断任何流程）。

    参数
      sig             蓝图给的形式签名（可为空）
      compile_result  (returncode, full_err)，来自「保留 by sorry」的编译；
                      None ⇒ stage=UNVERIFIED，**不放行**
      proof_code      最终拼接代码（签名 + 证明体）；None ⇒ stage=NO_PROOF

    返回 dict：
      stage     ABSENT / SHAPE / NONTRIVIAL / UNVERIFIED / STATED /
                NO_PROOF / PROOF / READY
      allowed   bool（只有 READY 为 True）
      reasons   list[str]
      prop      拆出的命题全文（供人工抽验）

    ★ 顺序刻意把零成本门放前面：影子模式下多数被拒条目不需要编译。
    ★ 本函数**不执行编译**。编译由调用方注入，契约层保持零依赖、可单测。
    """
    def _v(stage, reasons, prop=""):
        return {"stage": stage, "allowed": stage == "READY",
                "reasons": list(reasons), "prop": prop}

    if not (sig or "").strip():
        return _v("ABSENT", ["该步未形式化（不是被拒，是没给签名）"])
    got = split_sig(sig)
    if not got:
        return _v("SHAPE", ["签名不是 `theorem/example ... := by sorry` 形态"])
    _head, prop = got
    trivial = is_trivial_prop(prop)
    if trivial:
        return _v("NONTRIVIAL", ["退化命题：%s" % trivial], prop)
    if compile_result is None:
        return _v("UNVERIFIED", ["未提供命题编译结果 ⇒ 不认「可陈述」"], prop)
    rc, full_err = compile_result
    stated, why = classify_stated(rc, full_err)
    if stated != "STATABLE":
        return _v("STATED", ["命题不可陈述：%s / %s" % (stated, why)], prop)
    if proof_code is None:
        return _v("NO_PROOF", ["尚未交付证明体"], prop)
    cred, why2 = proof_credential(proof_code)
    if cred != "OK":
        return _v("PROOF", ["证明凭证不成立：%s / %s" % (cred, why2)], prop)
    return _v("READY", [], prop)
