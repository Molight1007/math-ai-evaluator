# -*- coding: utf-8 -*-
"""E44 · prover 接入契约层（纯函数，零项目依赖，可单测）

定位
----
方向 1 = 把专用 Lean prover（Goedel-Prover-V2-8B）作为**工具**接进来。
本模块只负责「输入签名 → 官方 prompt → 回复 → 服务器可编译代码」这一段
纯文本变换，**不调用任何模型、不跑 Lean、不 import 项目任何包**。
因此它可以离线单测，也可以在拿到 endpoint 后直接被 run_prover.py 使用。

三处必须适配（都来自实探，不是猜）
----------------------------------
1. Goedel 官方环境是 `import Mathlib` + `import Aesop`，且 pin 在
   **Lean 4.9 + Mathlib d1d1e4b**（ModelScope 模型卡 / arXiv 2508.03613）；
   本服务器是 **Lean 4.31 / Mathlib fabf563a**，且**没有顶层 Mathlib.olean**，
   只能用 `import Mathlib.Tactic`（MEMORY 已记）。
2. 官方输入是 `theorem NAME ... := by sorry`，而 L2 探针的 formal_sig 是
   `example ... := by sorry`。
3. 官方 `set_option maxHeartbeats 0` = 不限心跳；批量验证必须换成有限值，
   否则一条坏证明能把整轮拖死。

★ 这些适配只解决**环境**差异，不解决**语义**差异（引理改名、tactic 行为
  变化）。后者正是接上 prover 之后要用 verify_proofs.py 量出来的东西。

★ 本模块是**探针**，不是生产代码。endpoint / model 由调用方以参数传入，
  不提供 env / config 覆盖链 —— 项目铁律「不准用开关」仍然成立；
  将来真要接进智能体，必须先论证并登记策略项。
"""
import re

__all__ = [
    "PROMPT_TEMPLATE", "STATEMENT_HEADER", "SERVER_IMPORT",
    "SERVER_MAX_HEARTBEATS", "to_formal_statement", "build_prompt",
    "extract_lean_block", "adapt_to_server", "has_sorry",
    "build_verify_unit",
]

# 官方 prompt（Goedel-Prover-V2 模型卡 / viai957 README 逐字复刻）
PROMPT_TEMPLATE = """Complete the following Lean 4 code:
```lean4 {}```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.
""".strip()

# 官方 statement 头（保持原样喂给模型；送编译前由 adapt_to_server 改写）
STATEMENT_HEADER = """import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat
"""

SERVER_IMPORT = "import Mathlib.Tactic"
SERVER_MAX_HEARTBEATS = 200000

_FENCE_RE = re.compile(r"```(?:lean4|lean|Lean4)?[ \t]*\r?\n?(.*?)```", re.S)
_IMPORT_EXACT = re.compile(r"^import\s+Mathlib\s*$")
_IMPORT_AESOP = re.compile(r"^import\s+Aesop\s*$")
_HB_ZERO = re.compile(r"^set_option\s+maxHeartbeats\s+0\s*$")
_ANY_MATHLIB_IMPORT = re.compile(r"^\s*import\s+Mathlib")
_SORRY_WORD = re.compile(r"\bsorry\b")


def to_formal_statement(sig, name):
    """把 L2 的 `example ... := by sorry` 变成 Goedel 要的 `theorem NAME ...`。

    只改第一行的声明关键字；命题正文一字不动（避免悄悄改语义）。
    """
    s = str(sig or "").strip()
    if not re.match(r"^\s*(example|theorem|lemma)\b", s):
        raise ValueError("formal_sig 不是 example/theorem 声明: %r" % s[:80])
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(name)):
        raise ValueError("theorem 名不是合法 Lean 标识符: %r" % name)
    s = re.sub(r"^\s*example\b", "theorem %s" % name, s, count=1)
    return STATEMENT_HEADER + "\n" + s + "\n"


def build_prompt(formal_statement):
    """套官方模板。注意 ```lean4 与 statement 之间**没有**额外换行（官方原文）。"""
    return PROMPT_TEMPLATE.format(str(formal_statement).strip())


def extract_lean_block(reply):
    """从 prover 回复里抽 Lean 代码块。

    Goedel 会先写一段 proof plan 再给 ```lean4 块；取**最后一个**含
    `:= by` 或 theorem/example 的块（若都没有则取最后一个块）。
    抽不到返回 ""，由 build_verify_unit 记为 NO_LEAN_BLOCK，不算闭合。
    """
    text = str(reply or "")
    blocks = [b.strip() for b in _FENCE_RE.findall(text) if b.strip()]
    if not blocks:
        return ""
    rich = [b for b in blocks
            if re.search(r":=\s*by\b|\b(?:theorem|example)\b", b)]
    return (rich or blocks)[-1]


def adapt_to_server(code):
    """把 Goedel 输出改写成服务器 Lean 4.31 能编译的形式。

    - `import Mathlib` -> `import Mathlib.Tactic`（顶层 olean 不存在）
    - 删 `import Aesop`（Mathlib.Tactic 已含）
    - `maxHeartbeats 0` -> 有限值
    - 若整段没有 Mathlib import（模型只给了 proof body），补一行
    """
    out, seen = [], False
    for ln in str(code or "").strip().splitlines():
        st = ln.strip()
        if _IMPORT_EXACT.match(st):
            out.append(SERVER_IMPORT)
            seen = True
            continue
        if _IMPORT_AESOP.match(st):
            continue
        if _HB_ZERO.match(st):
            out.append("set_option maxHeartbeats %d" % SERVER_MAX_HEARTBEATS)
            continue
        if _ANY_MATHLIB_IMPORT.match(st):
            seen = True
        out.append(ln)
    if not seen:
        out.insert(0, SERVER_IMPORT)
    return "\n".join(out).strip() + "\n"


def has_sorry(code):
    """源码里出现裸 `sorry` 即为未闭合（不依赖 Lean 的 warning 措辞）。"""
    return bool(_SORRY_WORD.search(str(code or "")))


def build_verify_unit(sig, reply, name):
    """一条样本 -> 待编译单元。返回 dict，形状固定，便于落盘/统计。

    precheck 取值：
      OK             有代码块、有 by、无 sorry -> 送编译
      NO_LEAN_BLOCK  没抽到代码块
      NO_PROOF_BODY  代码块里没有 `:= by`（多半只抄了题面）
      SORRY_IN_CODE  仍带 sorry（含原样抄回 `by sorry`）
    """
    block = extract_lean_block(reply)
    if not block:
        pre, code = "NO_LEAN_BLOCK", ""
    else:
        code = adapt_to_server(block)
        if not re.search(r":=\s*by\b", code):
            pre = "NO_PROOF_BODY"
        elif has_sorry(code):
            pre = "SORRY_IN_CODE"
        else:
            pre = "OK"
    return {
        "name": name,
        "sig": str(sig or ""),
        "code": code,
        "precheck": pre,
        "reply_len": len(str(reply or "")),
    }
