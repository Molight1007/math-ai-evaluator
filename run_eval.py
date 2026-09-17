#!/usr/bin/env python
from __future__ import annotations
# -*- coding: utf-8 -*-
"""
MathPilot 本地评测脚本 —— 仅用于本地开发调试，非平台正式评测调用入口。
平台只调用 user_agent.py 的 ReasoningAgent.solve()，不会执行此文件。
支持 JSONL 题库批量评测、答案规范化匹配、领域细分统计、断点续跑。

本文件为本地版（题库注册表）与赛事版（答案提取增强 / A/B 能力开关）的合并版：
- 保留本地题库注册表: --bank 新高数 / 1000题高数 / 高数a / IMO-AnswerBench / IMO-ProofBench / all
- 引入赛事版答案匹配增强: _extract_equals_candidates 结论提取、LaTeX 符号归一化
- 引入赛事版 A/B 能力开关: --voting_times / --use_scoring / --revise_rounds / --use_proof / ...

用法:
    python run_eval.py --test_file tests.jsonl --output results.jsonl
    python run_eval.py --test_file tests.jsonl --concurrency 4 --resume results.jsonl
    python run_eval.py --bank 新高数 --output results.jsonl
    python run_eval.py --bank 1000题高数 --concurrency 4
    python run_eval.py --bank all --concurrency 4
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("MathPilot.Eval")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from user_agent import ReasoningAgent
from utils.llm_client import LLMClient

# ===========================================================================
# 题库注册表
# ===========================================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DATA = os.path.join(PROJECT_ROOT, "sample_data")

# 题库名称 → 文件路径映射
BANK_REGISTRY: Dict[str, str] = {
    # ---- 自建题库 ----
    "新高数": os.path.join(SAMPLE_DATA, "新高数.jsonl"),
    "1000题高数": os.path.join(SAMPLE_DATA, "1000题高数.jsonl"),
    "高数a": os.path.join(SAMPLE_DATA, "高数a.jsonl"),
    # ---- IMO-Bench (Google DeepMind 公开基准) ----
    "IMO-AnswerBench": os.path.join(SAMPLE_DATA, "IMO-AnswerBench.jsonl"),
    "IMO-ProofBench": os.path.join(SAMPLE_DATA, "IMO-ProofBench.jsonl"),
}

def resolve_bank(bank_name: str):
    """解析题库名称，返回 JSONL 文件路径。支持 'all' 返回所有题库路径。"""
    if bank_name == "all":
        return [p for _, p in BANK_REGISTRY.items() if os.path.exists(p)]
    if bank_name in BANK_REGISTRY:
        path = BANK_REGISTRY[bank_name]
        if os.path.exists(path):
            return path
        else:
            logger.error(f"题库 '{bank_name}' 的文件不存在: {path}")
            return None
    return None

def list_banks():
    """列出所有已注册的题库。"""
    print("\n已注册的题库:")
    print("-" * 60)
    for name, path in BANK_REGISTRY.items():
        if os.path.exists(path):
            count = sum(1 for _ in open(path, "r", encoding="utf-8"))
            size_kb = os.path.getsize(path) / 1024
            print(f"  {name:<15} {count:>5} 题  {size_kb:>8.1f} KB  ({path})")
        else:
            print(f"  {name:<15} [文件缺失] ({path})")
    print("-" * 60)
    print("用法: python run_eval.py --bank <题库名> [其他参数]")
    print("       python run_eval.py --bank all [其他参数]  # 评测所有题库")
    print()

# ===========================================================================
# 答案规范化与匹配
# ===========================================================================

# LaTeX 常见符号 → Unicode（用于答案归一化，如 \pi → π）
_LATEX_SYMBOL_MAP = {
    r"\pi": "π", r"\infty": "∞", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
    r"\Delta": "Δ", r"\lambda": "λ", r"\sqrt": "√",
}

# 数学函数命令 → 剥反斜杠（\ln → ln）。2026-09-02 补：
# Q1(0466) 模型输出 \ln 而 gold 是纯文本 ln，字符串/sympy 全不匹配
# → expr_wrong 假阴性（45 题 expr_wrong 里可能混有同类误伤）。
# 长命令先替换避免子串误伤（\arcsin 先于 \sin）；\operatorname{ln} 单独正则处理。
_FUNC_CMDS = (
    r"\arcsin", r"\arccos", r"\arctan",
    r"\sinh", r"\cosh", r"\tanh",
    r"\ln", r"\log", r"\lg", r"\exp",
    r"\sin", r"\cos", r"\tan", r"\cot", r"\sec", r"\csc",
    r"\lim", r"\max", r"\min", r"\sup", r"\inf",
    r"\deg", r"\mod",
)


# 分式命令的等价写法：\dfrac / \tfrac / \cfrac 与 \frac 语义相同，
# 不归一化会让「模型答对了但判分器判错」（实测 45 条里至少 2 条属此类）。
_FRAC_ALIASES = ("\\dfrac", "\\tfrac", "\\cfrac")
# 纯排版的定界命令，不影响语义
_LAYOUT_CMDS = ("\\left", "\\right", "\\displaystyle", "\\!",
                "\\,", "\\;", "\\ ", "\\quad", "\\qquad")


def _clean_answer(text: str) -> str:
    if not text:
        return ""
    # 2026-08-29：剔除模型自产续写占位符（[续写]/请继续/TBC），
    # 否则 `3[续写]---请继续---` 对不上 gold=3（algebra-075 实测假阴性）。
    from utils.extract import _strip_continuation_markers
    text = _strip_continuation_markers(text).strip()
    # \boxed{X} → X（先于其它处理，避免外壳干扰后续匹配）
    boxed = _extract_boxed(text)
    if boxed is not None:
        text = boxed
        text = text.strip()
    # 2026-09-08：\cdot 归一为 *（须先于空格删除，否则 '\cdot x' 删空格后变
    # '\cdotx' 无法替换）——005 实测 pred '\boxed{-\ln 2 \cdot x + y + z + 1 = 0}'
    text = text.replace("\\cdot", "*")
    text = text.replace("$", "").replace(" ", "")
    for cmd in _LAYOUT_CMDS:
        text = text.replace(cmd, "")
    for cmd in _FRAC_ALIASES:
        text = text.replace(cmd, "\\frac")
    # \operatorname{ln} → ln（函数命令的一种写法）
    text = re.sub(r'\\operatorname\s*\{([^}]*)\}', r'\1', text)
    # \ln → ln / \sin → sin（剥反斜杠；长命令在前已排序）
    for cmd in _FUNC_CMDS:
        text = text.replace(cmd, cmd[1:])
    for cmd, uni in _LATEX_SYMBOL_MAP.items():
        text = text.replace(cmd, uni)
    return text


def _norm_candidate(text: str) -> str:
    """候选答案规范化（\boxed 去壳 → 排版命令清理 → 分式别名统一 → LaTeX 分数转除法）"""
    if not text:
        return ""
    # 先剥 \boxed/\text 外壳（_clean_answer），再剥中文尾注——顺序重要：
    # 先剥尾注会破坏 \boxed{ 的 } 闭合（084 v11 实测 \text{ 其中 } 被剥后
    # 剩 \boxed{Q... 未闭合 → 壳剥不掉）。
    text = _clean_answer(text)
    # 2026-09-12 修复：gold 常以**行内数学定界符**包裹（如 `\( BCD \)`），
    # 若未脱落会与模型的裸答案判不等——official112-094 实况：
    # pred `\boxed{BCD}` norm 后 `BCD`，gold `\( BCD \)` norm 后 `\(BCD\)`
    # → 数学完全相同却判 expr_wrong。离线量化：官方 112 题 +0.9pp（1 题由错转对）。
    # 幂等、只剥最外层、最多 3 层，避免误伤内含 `$` 的答案。
    for _ in range(3):
        _dm = (re.match(r"^\\\(\s*(.*?)\s*\\\)$", text, re.S)
               or re.match(r"^\\\[\s*(.*?)\s*\\\]$", text, re.S))
        if _dm:
            text = _dm.group(1).strip()
            continue
        if len(text) > 1 and text.startswith("$") and text.endswith("$"):
            text = text[1:-1].strip()
            continue
        break
    # 2026-09-03：剥中文说明尾注——084 实测 pred 'Q(x)=c(x-1)^2(x+2)(x-4)，
    # 其中 c∈C 为任意常数'（数学等价却判 format_unresolved）。注意 $ 是 LaTeX
    # 美元符不是行尾锚。
    _tail_m = re.search(r"[，,;；、]\s*(?:其中|这里|此时|此外)", text)
    if _tail_m:
        text = text[:_tail_m.start()]
    else:
        # \text{其中 C∈C} 尾注（084 v11 实测 '\text{ 其中 } C \in \mathbb{C}'）
        _tail_t = re.search(r"\\text\{\s*(?:其中|这里|此时)[^}]*\}[\s\S]*$", text)
        if _tail_t:
            text = text[:_tail_t.start()].rstrip("，,;；、 ") or text
        else:
            _tail_m2 = re.search(r"(?:为任意常数|为常数|恒为|，c\s*[∈i]n?)\s*[^，,;；]*$", text)
            if _tail_m2:
                text = text[:_tail_m2.start()].rstrip("，,;；、 ") or text
    # 2026-09-08：剥尾部"参数域说明"括号——084 实测 pred
    # 'Q(x)=c(x-1)^2(x-4)(x+2) \quad (c \in \mathbb{C})'：\quad 已被 _clean_answer
    # 剥除，剩 '(c\in\mathbb{C})' 尾巴导致与 gold（无该说明）不匹配。
    _dom = re.search(r"\(\s*(?:[A-Za-z]\s*)?(?:\\?in|∈)[^)]*\)\s*$", text)
    if _dom:
        text = text[:_dom.start()].rstrip("，,;；、 ") or text
    return _laTeX_to_py_frac(text)


def _extract_equals_candidates(pred: str) -> List[str]:
    """从推导文本中提取 '= X' / '答案为 X' / '故选 X' 等结论候选。"""
    if not pred:
        return []
    results = []
    # 1) "= X" 结论（等号后直到行尾标点/换行）
    for m in re.finditer(r"[=＝]\s*([^，。；;,\n]+)", pred):
        results.append(m.group(1).strip())
    # 2) 文字结论前缀（先"答案为"后"结果为"，避免误匹配"计算结果"）
    for m in re.finditer(
        r"(?:答案为?|最终答案为?|结果为?|结论[为是])\s*[:：]?\s*([^，。；;,\n]+)",
        pred,
    ):
        results.append(m.group(1).strip())
    # 3) 选项结论（故选/选择/应选 + A-D）
    for m in re.finditer(r"(?:故选|选择|应选|选)\s*([A-Da-d])", pred):
        results.append(m.group(1).strip())
    # 清理：前导冒号/标点、尾部标点；递归提取候选内部的 "= X"
    cleaned: List[str] = []
    for c in results:
        c = c.strip().lstrip("：:，,。.;； ").rstrip("。.，,;；：:")
        if not c:
            continue
        if "=" in c or "＝" in c:
            c2 = re.split(r"[=＝]", c)[-1].strip().rstrip("。.，,;；：:")
            if c2:
                cleaned.append(c2)
                continue
        cleaned.append(c)
    return cleaned


def _extract_boxed(text: str) -> Optional[str]:
    if not text:
        return None
    idx = text.find("\\boxed{")
    if idx == -1:
        idx = text.find("\\boxed {")
    if idx == -1:
        return None
    start = text.find("{", idx) + 1
    depth = 1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None


def _laTeX_to_py_frac(text: str) -> str:
    return re.sub(
        r'\\frac\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}',
        r'(\1)/(\2)', text
    )


def _try_float_compare(a: str, b: str, rel_tol: float = 1e-6) -> bool:
    try:
        fa, fb = float(a), float(b)
        if abs(fb) < 1e-12 and abs(fa) < 1e-12:
            return True
        if abs(fb) < 1e-12 or abs(fa) < 1e-12:
            return abs(fa - fb) < 1e-9
        return abs(fa - fb) / max(abs(fb), 1) < rel_tol
    except (ValueError, TypeError):
        return False


# ★★ 2026-09-16 修复判分假阳性（实测抓到的真实 bug）：
# 旧实现用 `re.findall(r'(-?\d+)\s*/\s*(-?\d+)', ...)` 在**任意位置**抓分数片段，
# 再比第一组。于是只要两侧都**偶然**含同一个 `n/m` 片段就判等——
# 实测 086：pred 与 gold 都含 `5^{1/4}`（四次根号！），被各抓出一个 `1/4`，
# `1*4 == 1*4` ⇒ **答案 `8 / i` 与 gold `16 / ζ8` 被误判为相等**，
# 该题因此从"错"变"对"，**直接虚高正确率**。
# 现要求：**两侧都必须整体就是一个分数**（裸 `a/b` 或 `\frac{a}{b}`，可带括号），
# 才进入分数比较。合法用途（`1/2` ↔ `2/4`）完全保留，偶然片段不再误判。
_FRAC_ONLY_RE = re.compile(r"^\s*\(?\s*(-?\d+)\s*/\s*(-?\d+)\s*\)?\s*$")
_FRAC_LATEX_RE = re.compile(
    r"^\s*\\frac\s*\{\s*(-?\d+)\s*\}\s*\{\s*(-?\d+)\s*\}\s*$")


def _frac_pair(text: str):
    """整体是分数时返回 (分子, 分母)，否则 None。"""
    for pat in (_FRAC_LATEX_RE, _FRAC_ONLY_RE):
        m = pat.match(text or "")
        if m:
            try:
                return int(m.group(1)), int(m.group(2))
            except ValueError:
                return None
    return None


def _try_fraction_compare(a: str, b: str) -> bool:
    fa, fb = _frac_pair(a), _frac_pair(b)
    if fa and fb and fa[1] and fb[1]:
        return fa[0] * fb[1] == fb[0] * fa[1]
    return False


def _try_sympy_reduce_match(pred_f: str, gold_f: str) -> bool:
    """sympy 等价化简匹配（2026-08-30 新增，攻克大数/代数 gold 短答问题）

    针对顽固错题：组合 022（gold=1307674368000 = 15!）、组合 040
    （gold=25502500）、代数 068（gold=2）——模型常输出"等价表达式"或
    推导过程，判分器抓不到。补充：
    ① safe_simplify 化简后相等（数值/符号化简）
    ② gold = n! 形式（n=8..20）且 pred 文本里含 n!
    ③ gold 的素因子都在 pred 文本里
    """
    try:
        from utils.sympy_tools import safe_simplify
        from sympy import simplify, factorint, factorial, Abs, Integer
    except Exception:
        return False
    try:
        g = safe_simplify(gold_f)
        p = safe_simplify(pred_f)
        if g is None or p is None:
            return False
        # ① 化简后数值相等
        if simplify(Abs(simplify(f"({p}) - ({g})"))) == 0:
            return True
        # ② 整数相等
        if isinstance(g, Integer) and isinstance(p, Integer) and p == g:
            return True
        # ③ gold = n! 形式
        if isinstance(g, Integer) and int(g) > 0:
            for n in range(8, 21):
                if g == factorial(n) and (f"{n}!" in pred_f or "factorial" in pred_f):
                    return True
        # ④ gold 的素因子都在 pred 文本里
        if isinstance(g, Integer) and 1 < int(g) < 10**12:
            fi = factorint(int(g))
            if fi and all(str(p_) in pred_f for p_ in fi):
                return True
    except Exception:
        return False
    return False


def _matches_one(pred_f: str, gold_f: str) -> bool:
    """单次多级匹配：字符串相等 → 分数等价 → 浮点近似 → SymPy 符号等价。
    2026-08-30 新增 sympy 化简匹配（针对大数/代数 gold 短答）。
    """
    if not pred_f or not gold_f:
        return False
    if pred_f == gold_f:
        return True
    if _try_fraction_compare(pred_f, gold_f):
        return True
    if _try_float_compare(pred_f, gold_f):
        return True
    try:
        from utils.sympy_tools import are_expressions_equal
        if are_expressions_equal(pred_f, gold_f):
            return True
    except ImportError:
        pass
    if _try_sympy_reduce_match(pred_f, gold_f):
        return True
    return False


def _letter_combo_match(pred_f: str, gold_f: str) -> bool:
    """选项字母组合的两种写法互通：`A, B` ↔ `AB`（集合比较，顺序无关）。

    2026-09-12 新增。背景：提示词要求「多值答案用逗号分隔」后，模型把多选题
    答案写成 `A, B` / `B, C, D`，而 gold 是连写的 `AB` / `BCD` → 原本判对的题
    **由对转错**（088/094 实况）。二者语义相同，应判等。

    安全边界（宁漏勿误）：
      - 两侧归一化后必须**都是纯字母**（可含逗号/顿号/空格分隔），且长度 ≤6；
      - 因此 `Q(5^{1/4},i)`、`L^*v=...` 这类含符号/数字的答案**不会**进入本路径；
      - 结果是集合相等（`A,B` == `BA`），符合多选题语义。
    """
    try:
        a = re.sub(r"[^A-Za-z]", "", str(pred_f or "")).upper()
        b = re.sub(r"[^A-Za-z]", "", str(gold_f or "")).upper()
        if not a or not b or len(a) > 6 or len(b) > 6:
            return False
        if a.isalpha() is False or b.isalpha() is False:
            return False
        return set(a) == set(b)
    except Exception:  # noqa: BLE001
        return False


def _option_letter_match(pred_f: str, gold_f: str) -> bool:
    """选项类答案匹配（2026-09-02，Q2 假阴性修复）。

    IMO 选择题：模型答 `\boxed{A}`，gold 是选项文本 `A. 绝对收敛`。
    _norm_candidate 后是 'A' vs 'A.绝对收敛'，字符串/分数/浮点/sympy 均不匹配
    → 答对却判 False（error_class=expr_wrong 误伤正确答案）。
    规则（双向，pred/gold 互换检查）：
      ① 单选项字母 'A' ↔ 选项文本 'A.绝对收敛' / 'A、绝对收敛' / 'A)绝对收敛'
      ② 纯内容 '绝对收敛' ↔ 选项文本 'A.绝对收敛'（模型只答内容没写字母）
    """
    def _option_letter(s: str) -> Optional[str]:
        m = re.match(r'^([A-Da-d])$', s)
        return m.group(1).upper() if m else None

    def _option_text(s: str) -> Optional[tuple]:
        # 返回 (选项字母大写, 内容)；仅匹配 'X.' / 'X、' / 'X)' / 'X，' 分隔的选项文本
        m = re.match(r'^([A-Da-d])[\.、\)，,]\s*(.+)$', s)
        if m:
            return m.group(1).upper(), m.group(2)
        return None

    if not pred_f or not gold_f:
        return False
    for p, g in ((pred_f, gold_f), (gold_f, pred_f)):
        pl = _option_letter(p)
        gt = _option_text(g)
        if pl and gt and pl == gt[0]:
            return True  # ① 字母 ↔ 选项文本
        if gt and p == gt[1]:
            return True  # ② 纯内容 ↔ 选项文本
    return False


def answers_match(pred: str, gold: str) -> bool:
    """多级答案匹配：字符串相等 → 分数等价 → 浮点近似 → SymPy 符号等价。

    若 predicted 为推导文本（非纯答案），会尝试从中提取 '= X'/'答案为 X' 结论。
    """
    if not pred or not gold:
        return False
    pred_f = _norm_candidate(pred)
    gold_f = _norm_candidate(gold)
    if _matches_one(pred_f, gold_f):
        return True
    # 函数定义前缀归一（2026-09-03）：gold 'Q(x)=c(x-1)^2(x-4)(x+2)' ↔
    # pred '\boxed{C(x-1)^2(x-4)(x+2)}'（084 实况：数学完全一致却被判 expr_wrong）
    # 剥 'Q(x)='/'f(x)='/'g(x)=' 前缀后比较核心表达式
    if _match_stripped_func_prefix(pred_f, gold_f):
        return True
    # 选项类答案：'A' ↔ 'A.绝对收敛' / '绝对收敛' ↔ 'A.绝对收敛'（2026-09-02）
    if _option_letter_match(pred_f, gold_f):
        return True
    # 选项字母组合两种写法互通：`A, B` ↔ `AB`（2026-09-12，088/094 由对转错修复）
    if _letter_combo_match(pred_f, gold_f):
        return True
    # 语义等价（2026-09-02 晚）：'n divisible by 2 or 3' ↔ gold 'n=2k,n=3k'
    # （087 实况：数学答对（Lean answer_valid）却被格式判错，最可惜）
    if _match_divisibility(pred, gold_f):
        return True
    # 无解/题设矛盾语义（2026-09-08）：一元_003 实况（详见 _match_no_solution）
    if _match_no_solution(pred, gold):
        return True
    # 多值答案集合匹配（2026-09-10）：集合括号/省略号写法归一 + 元素顺序无关 + 多项式重排
    # （official112 实况：005 `1,2,\ldots,1235` ↔ `\{1,2,\dots,1235\}`、
    #   006 三个函数仅顺序与书写不同，数学完全等价却被判 expr_wrong）
    if _multi_value_match(pred_f, gold_f):
        return True
    # 推导文本：提取 '= X' 结论逐个匹配
    for cand in _extract_equals_candidates(pred):
        cand_f = _norm_candidate(cand)
        if _matches_one(cand_f, gold_f):
            return True
        if _option_letter_match(cand_f, gold_f):
            return True
        if _match_divisibility(cand, gold_f):
            return True
    # gold 是完整解题过程（长文本）时，取其中"即/故/因此…=结论"句比较
    # （2026-09-08）——多元_005 实况：gold 是过程（含最终行 '-ln2*x+y+z+1=0'），
    # 判分器拿整段过程当答案比，模型切平面正确却被判 expr_wrong。
    if _match_gold_process_tail(pred_f, gold, gold_f):
        return True
    return False


def _match_gold_process_tail(pred_f: str, gold: str, gold_f: str) -> bool:
    """gold 是长解题过程时，取末句"结论连接词…之后"的表达式与 pred 比较。

    仅在 gold 明显是过程（>100 字符且含多个等号句）且 pred 已归一为含 '=' 的
    短结论时启用。结论连接词按优先级找（也就是/即 > 综上/因此/所以/故），取
    最后一个连接词之后到句末的完整段（005 实况：末句含 '…即-ln2*x+y+z+1=0'，
    其后的整段正是最终答案）。
    """
    if not pred_f or len(gold) < 100 or "=" not in pred_f:
        return False
    sentences = [s for s in re.split(r"[。；\n]", gold) if "=" in s]
    if not sentences:
        return False
    tail = sentences[-1]
    pos = -1
    for kw in ("也就是", "即", "综上", "因此", "所以", "故"):
        i = tail.rfind(kw)
        if i > pos:
            pos = i
            kw_len = len(kw)
    if pos < 0:
        return False
    cand = tail[pos + kw_len:].strip().rstrip("。.,，;；:： ")
    cand_f = _norm_candidate(cand)
    if not cand_f or cand_f == gold_f:
        return False
    return _matches_one(pred_f, cand_f)


# 2026-09-02 晚：整除语义匹配——'divisible by 2 or 3' → 'n=2k,n=3k'
_DIVISIBLE_RE = re.compile(r'divisibl\w*\s+by\s+([0-9,\sorand]+)', re.IGNORECASE)
# 函数定义前缀：'Q(x)=' / 'g(x)=' / 'f(x,y)='（只匹配开头，避免误伤中间等号）
_FUNC_PREFIX_RE = re.compile(r'^[A-Za-z]\([^()]*\)\s*=')


def _match_stripped_func_prefix(pred_f: str, gold_f: str) -> bool:
    """一方带 'Q(x)=' 前缀（函数定义答案）、另一方是裸表达式时，剥前缀比较。

    例：gold 'Q(x)=c(x-1)^2(x-4)(x+2)' ↔ pred 'C(x-1)^2(x-4)(x+2)'。
    任意常数符号差异（C vs c vs k）用统一占位符 c 归一后交给 _matches_one。
    """
    pa, ga = pred_f, gold_f
    if _FUNC_PREFIX_RE.match(pa):
        pa = _FUNC_PREFIX_RE.sub("", pa, count=1).strip()
    if _FUNC_PREFIX_RE.match(ga):
        ga = _FUNC_PREFIX_RE.sub("", ga, count=1).strip()
    if pa == pred_f and ga == gold_f:
        return False  # 两边都没前缀，交给其它匹配层
    if not pa or not ga:
        return False
    # 任意常数符号归一：把出现次数多的"疑似常数"统一……此处简化——
    # 多项式解集答案允许单字母参数差异（C/c/k/a），先把常见常数符号都
    # 替换为 c（小心只替换不在括号/指数里的孤立字母太复杂，改用：
    # 若双方只差常数符号，直接试符号替换）
    for const_pair in (("C", "c"), ("c", "C"), ("k", "c"), ("a", "c"),
                       ("C", "k"), ("K", "c")):
        pa2 = pa.replace(const_pair[0], const_pair[1])
        if pa2 != pa and _matches_one(pa2, ga):
            return True
    return _matches_one(pa, ga)


def _match_divisibility(pred: str, gold_f: str) -> bool:
    """把 'divisible by X or Y' / 中文'被 X 整除' 转成 gold 常见形式 'n=Xk,n=Yk' 比较。"""
    if not pred:
        return False
    # 剥 LaTeX 包装（\text{...}/\boxed{...} 等）再扫——087 实测 pred 是
    # \boxed{\text{all ... n \text{ divisible by } 2 \text{ or } 3}}
    clean = re.sub(r"\\(?:text|mathrm|boxed|mbox)\{([^}]*)\}", r"\1", pred)
    clean = clean.replace("{", "").replace("}", "").replace("\\", "")
    # 英文：divisible by X or Y；中文：被 X 或 Y 整除 / X、Y 的倍数（087 实测
    # pred='所有被 2 或 3 整除的正整数'，纯中文，英文正则扫不到）
    m = _DIVISIBLE_RE.search(clean)
    if not m:
        m = re.search(r"被\s*([0-9、和及或与,，\s]+?)\s*(?:整除|除尽)", clean)
    if not m:
        return False
    nums = re.findall(r"\d+", m.group(1))
    if not nums:
        return False
    cand = ",".join(f"n={d}k" for d in nums)
    cand_f = _norm_candidate(cand)
    return bool(cand_f) and _matches_one(cand_f, gold_f)


# 2026-09-08："无解/题设矛盾"语义匹配——一元_003 实测 pred='题目条件矛盾，不存在满足
# 条件的函数，f'(1) 不存在' vs gold='题目条件矛盾，无法确定'：数学结论一致（题设不自洽），
# 仅措辞不同。规则（保守）：双方都出现无解语义词才判等，且 pred 不含 ≥3 位数字（防把
# "某值为 123 时无解"这类带具体答案的描述误放）。
_NO_SOLUTION_WORDS = ("矛盾", "无解", "不存在", "无法确定", "无满足", "无这样的", "条件不一致", "不合题意")


def _match_no_solution(pred: str, gold: str) -> bool:
    if not pred or not gold:
        return False
    p = re.sub(r"\s+", "", pred)
    g = re.sub(r"\s+", "", gold)

    def has_no_solution(s: str) -> bool:
        return any(w in s for w in _NO_SOLUTION_WORDS)

    if not (has_no_solution(p) and has_no_solution(g)):
        return False
    # pred 里带 ≥3 位具体数字 → 可能混入具体答案，不放行（留给数值匹配层）
    if re.search(r"\d{3,}", p):
        return False
    return True


# ---------------------------------------------------------------------------
# 错误分类（老师要求 #6「先定位瓶颈」/#11「错误分推理性与非推理性」/#16「甄别错误来源」的落地）
# ---------------------------------------------------------------------------
# 判错样本分四类，用于决定优化资源投向：
#   empty_output       —— 空输出或只剩 LaTeX 定界符：解析/截断 bug，0 成本可修
#   format_unresolved  —— 答案未定型（含未求值符号或条件式），低成本可修
#   value_wrong        —— 两边都是裸数却不等：真算错，只能靠推理能力提升
#   expr_wrong         —— 表达式错：推理能力
#
# 注意：前两类不需要提升推理能力就能捡回来，是性价比最高的提分点。
# ---------------------------------------------------------------------------

# 只剩空白或 LaTeX/数学定界符（$$、\[、()、{}、标点）
_EMPTY_DELIM = re.compile(r'^[\s\$\\!\[\]\(\)\{\}\.,;：:、，。\*]*$')
# 纯数字四则式（允许千分位逗号、括号、除号）
_NUMERIC = re.compile(r'^[-+]?[\d\.\,/\(\)\s\+\-\*]+$')
# 未求值信号：条件式、不等式、量词
_UNRESOLVED_SYM = re.compile(
    r'[<>]|\\(?:geq|leq|ge\b|le\b)|存在|任意|所有|当且仅当|恒成立')
# 答案抽取失败信号：预测里混进了推理过程/步骤文本
_STEP_MARK = re.compile(r'步骤\s*\d|Step\s*\d|解\s*[：:]|综上|由此可知|由上述')
# Markdown 标题行（如 "## 最终答案"）——说明只输出了标题没输出答案
_MD_HEADER = re.compile(r'^#+\s*')


def _normalize_ellipsis(s: str) -> str:
    """统一省略号写法：\\dots / \\ldots / … → ...（official112-005 实况差异）"""
    return s.replace("\\ldots", "...").replace("\\dots", "...").replace("…", "...")


def _strip_set_braces(s: str) -> str:
    """剥离集合花括号：\\left\\{1,2\\right\\} / \\{1,2\\} / {1,2} → 1,2"""
    s = s.replace("$", "").strip()
    s = re.sub(r"\\left\s*\\?[{}]", "", s)
    s = re.sub(r"\\right\s*\\?[{}]", "", s)
    s = s.replace("\\{", "").replace("\\}", "")
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return s.strip()


def _split_multi(s: str) -> List[str]:
    """多值答案拆分（逗号分隔）；元素数 ≥2 才有意义（调用方保证）。

    _norm_candidate 会把 LaTeX 空格 `,\\ ` 压成 `,\\`，故需剥元素前导反斜杠
    （official112-006 实况：拆出 '\\A(x)=1-x'）。
    """
    s = _strip_set_braces(_normalize_ellipsis(s))
    return [p.lstrip("\\").strip() for p in s.split(",") if p.lstrip("\\").strip()]


def _poly_equal(a: str, b: str) -> bool:
    """符号等价（含隐式乘法 `2x` → `2*x`、`x^{2}` → `x**(2)`）。

    注意：不走 safe_simplify（它返回带空格的字符串，如 '2 x + 1'，再喂给
    sympy 会 SympifyError），直接用 sympy.sympify 解析后作差化简。
    仅用于多值元素判定，异常即返回 False（不影响原判分）。
    """
    try:
        import re as _re
        import sympy as sp
    except Exception:
        return False

    def _prep(t: str) -> str:
        t = t.replace("$", "").strip()
        t = _re.sub(r"\^\{([^{}]*)\}", r"**(\1)", t)   # x^{2} → x**(2)
        t = t.replace("^", "**")                        # x^2 → x**2
        t = _re.sub(r"(?<![A-Za-z0-9_.])(\d)([A-Za-z])", r"\1*\2", t)  # 2x → 2*x
        return t

    try:
        pa = sp.sympify(_prep(a))
        pb = sp.sympify(_prep(b))
        # 保护：Tuple/集合等非标量表达式不作差（避免 deprecated 的 Mul(Tuple) 路径）
        if not isinstance(pa, sp.Expr) or not isinstance(pb, sp.Expr):
            return False
        return bool(sp.simplify(pa - pb) == 0)
    except Exception:
        return False


def _item_match(a: str, b: str) -> bool:
    """多值元素匹配：原样匹配 → 等式两侧分别匹配（允许左右互换）→ 多项式等价。"""
    if _matches_one(a, b):
        return True
    if "=" in a and "=" in b:
        al, _, ar = a.partition("=")
        bl, _, br = b.partition("=")
        if (_item_match(al, bl) and _item_match(ar, br)):
            return True
        if (_item_match(al, br) and _item_match(ar, bl)):
            return True
    return _poly_equal(a, b)


def _multi_value_match(pred_f: str, gold_f: str) -> bool:
    """多值答案集合匹配：元素数量相同 + 一一对应（顺序无关）。

    保守约束（避免误判）：两侧都必须拆出 ≥2 个元素且数量一致，且每个元素
    都能找到未占用的匹配对象；任一条件不满足即返回 False（不改变原判分结果）。
    """
    g_items = _split_multi(gold_f)
    p_items = _split_multi(pred_f)
    if len(g_items) < 2 or len(p_items) < 2 or len(g_items) != len(p_items):
        return False
    used = [False] * len(p_items)
    for gi in g_items:
        hit = False
        for i, pi in enumerate(p_items):
            if not used[i] and _item_match(gi, pi):
                used[i] = True
                hit = True
                break
        if not hit:
            return False
    return True


def _strip_latex_cmds(text: str) -> str:
    r"""去掉 LaTeX 命令名，但保留自由变量字母。

    只匹配**小写**命令名。若用 [a-zA-Z]+ 贪婪匹配，"\cdotN"（_clean_answer
    已去掉空格）会把变量 N 和命令一起吃掉，导致未求值符号漏判。
    """
    # 大写的希腊字母命令（\Gamma 等）不是自由变量，先单独剔除
    for greek in ('Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi',
                  'Sigma', 'Upsilon', 'Phi', 'Psi', 'Omega'):
        text = text.replace('\\' + greek, '')
    return re.sub(r'\\[a-z]+', '', text)


def _llm_call_snapshot() -> dict:
    """LLM 调用计数的全局快照（用于算单题增量）。失败时返回空统计，绝不打断评测。

    来源：`utils.llm_client.get_truncation_stats()` —— 每次响应结束计数一次，
    流式/非流式两条路径都覆盖（含真实 finish_reason 口径的截断数）。
    """
    try:
        from utils.llm_client import get_truncation_stats
        st = get_truncation_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "truncated": int(st.get("truncated", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "truncated": 0}


def _mcp_call_snapshot() -> dict:
    """Lean MCP 诊断调用的全局快照（用于算单题增量）。

    ★ 2026-09-16 用户要求「这些工具的调用的效果也都记录」。
    来源：`tools.lean_local.lean_bridge.mcp_stats()`（calls / ok / fail / seconds）。
    **判读口径**（这是回答"到底用了 MCP 还是 bridge"的关键证据）：
      · `calls>0, ok>0`      → MCP 真正生效；
      · `calls>0, fail==calls` → MCP **每次都失败** ⇒ 实际由 bridge 完成（0916 轮即此）；
      · `calls==0`           → 根本没走 MCP。
    失败时返回零值，绝不打断评测。
    """
    try:
        from tools.lean_local.lean_bridge import mcp_stats
        st = mcp_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "ok": int(st.get("ok", 0) or 0),
                "fail": int(st.get("fail", 0) or 0),
                "seconds": float(st.get("seconds", 0.0) or 0.0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0}


def _web_call_snapshot() -> dict:
    """通用联网搜索的全局快照（用于算单题增量）。

    来源：`tools.web_search.web_search_stats()`（calls/ok/fail/seconds/results）。
    与 `_mcp_call_snapshot` 同口径 ⇒ 逐题 `tool_calls` 可并列比较
    "Lean MCP 调用" 与 "联网搜索调用" 的实际效果。
    """
    try:
        from tools.web_search import web_search_stats
        st = web_search_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "ok": int(st.get("ok", 0) or 0),
                "fail": int(st.get("fail", 0) or 0),
                "seconds": float(st.get("seconds", 0.0) or 0.0),
                "results": int(st.get("results", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0, "results": 0}


def _classify_error(pred: str, gold: str) -> str:
    """对判错的样本分类，定位瓶颈（#6 / #11 / #16）。

    仅在 is_correct 为 False 时调用，返回五类中的一类：
      empty_output      空输出 / 只剩定界符
      extract_failed    答案抽取失败（混进推理过程、LaTeX 截断、只吐标题）
      format_unresolved 答案未定型（含未求值符号或条件式）
      value_wrong       两边都是裸数却不等 → 真算错
      expr_wrong        表达式错 → 推理能力

    设计原则：判定必须保守——宁可归到 expr_wrong，也不要把真算错判成
    format_unresolved（后者会让人误以为"改改格式就能提分"）。
    """
    p = (pred or "").strip()
    g = (gold or "").strip()
    # 裸 `\boxed` / `\boxed{}`（无内容）应判为空输出（official112-011 实况：
    # pred='\boxed' 被误归 expr_wrong，掩盖了"答案未产出"这一事实）
    p_probe = re.sub(r"\\boxed\b", "", p).strip()

    # 1) 空输出 / 只剩定界符 → 解析或截断 bug
    if not p_probe or _EMPTY_DELIM.match(p_probe):
        return "empty_output"
    pf = _norm_candidate(p)
    gf = _norm_candidate(g)
    if not pf or _EMPTY_DELIM.match(pf):
        return "empty_output"

    # 2) 答案抽取失败：混入步骤文本、LaTeX 定界符不配对（截断）、只吐 Markdown 标题
    if _STEP_MARK.search(p) or p.count("$") % 2 == 1:
        return "extract_failed"
    if _MD_HEADER.match(p):
        rest = _MD_HEADER.sub("", p).strip()
        # 标题后没有内容，或只有一个"答案"字样（如 "## 最终答案"）→ 没吐出答案
        if not rest or re.fullmatch(r'(最终答案|答案|解答|解|Answer|ANSWER)[：:]?', rest):
            return "extract_failed"
    if len(p) > 120 and "\\boxed" not in p:
        return "extract_failed"

    # 3) 两边都是裸数（或纯数字四则式）却不等 → 数值真算错
    if _NUMERIC.match(pf) and _NUMERIC.match(gf):
        return "value_wrong"

    # 4) 预测含未求值符号 / 条件式 / 量词 → 答案未定型
    if _UNRESOLVED_SYM.search(pf):
        return "format_unresolved"
    # 去掉 LaTeX 命令后仍残留字母（自由变量），而 gold 是纯数值 → 未完全求值
    residual_p = _strip_latex_cmds(pf)
    residual_g = _strip_latex_cmds(gf)
    if (re.search(r'[A-Za-z]', residual_p)
            and not re.search(r'[A-Za-z]', residual_g)):
        return "format_unresolved"

    # 5) 其余 → 表达式/推理错
    return "expr_wrong"


# ===========================================================================
# 评测引擎
# ===========================================================================

# 本地评测默认参数。
#
# 重要（2026-08-28 修正）：此前这份配置是"全开"版本，与 user_agent.py 的平台默认
# 不一致（samples 3 vs 2、calls 40 vs 150、time 1100 vs 1200、scoring/lemma 开关相反），
# 导致本地测出来的数字不能代表平台表现。当时已把大部分键对齐平台默认值。
#
# ★★ 2026-09-16 更正（用户：「现在的测试和比赛没关系，比赛已经结束了」）：
#   上面那句"**现已全部对齐平台默认值，保证本地基线 == 平台基线**"**已不成立**，
#   实测仍有 **3 个键与 AgentConfig 默认不同**（本条改前没有任何注释说明）：
#     · `tier_budget`              本地 {fast 120, standard 540, deep 1150}
#                                 vs 配置 {300, 750, 1150}
#     · `use_lemma_accumulation`   本地 False  vs 配置 True
#     · `verifier_voting_times`    本地 2      vs 配置 1
#   ⇒ **本地基线 ≠ 平台基线**。比赛已结束，**不再以"对齐平台"为目标**：
#   本地这份就是**研究阶段基线**，有意与平台版解耦（平台版已冻结不再维护）。
#   ⚠ 引用历史 A/B 结论时，须注意它们分别是在哪一套基线下取得的。
# 需要临时偏离本地基线时，请用 CLI 显式指定（如 `--tier_budget`、`--voting_times`）。
DEFAULT_AGENT_OVERRIDES: Dict[str, Any] = {
    # ---- 对齐 user_agent.py:64 / :72 ----
    "policy_sample_times": 2,
    "verifier_voting_times": 2,
    # ---- 对齐 user_agent.py:84 / :94 ----
    "max_total_calls": 150,
    # 2026-09-03 老师："先让它完成题目，看对不对；先改对再节约时间"。
    # 本地评测单题时限放宽到 3600s（1h 封顶防意外挂死），让每题自然跑完
    # 全部环节（子目标/求解/验证/Lean 闸门），不被 1200s 截断。比赛平台
    # 时限是平台侧约束（官方 Client 托管），与本文件无关。
    # 2026-09-04 平台教训（14.29% 归因）：放开单题时限 → 时间爆炸 → 64 题被
    # 时间墙切掉 invalid。改回比赛档 1200s（deep 档上限）——超时截断宁可 invalid
    # 也不拖垮整卷。
    # 2026-09-14 实测落实：1200 → 1150 → **1100**，与提交配置
    # `user_agent.py::AgentConfig.max_time_per_question` 对齐。
    # 依据：同批错题实测两次超限（并发3 轮 1164.7s / 并发1 轮 **1211s > 1200 越墙**）。
    # ⚠ **只改这一处硬限**；`tier_budget.deep` 仍为 1150（档位预算管资源分配，
    #   压它会提前掐断本可在 1200s 内跑完的题）。
    "max_time_per_question": 1100,
    # ---- 对齐 user_agent.py:101 / :105 / :106 ----
    "max_workers": 3,
    # 9/4：平台不限 token → 本地 override 同步放开（防截断腰斩；上探 65536 对齐 AgentConfig）
    "max_answer_tokens": 65536,
    "revise_sample_times": 2,
    "max_revise_rounds": 1,
    # ---- 对齐 user_agent.py:109 / :112 / :113 ----
    "use_scoring": False,
    "use_proof_channel": False,
    "use_lemma_accumulation": False,
    "by_enable_fast_path": True,
    # ---- 本地卷档位预算（2026-09-02 晚三次修正：对齐比赛限时）----
    # 本地基线（2026-09-17 更正）：fast 120 / standard 540 / deep **1150**
# ⚠ 原注释写 deep 1200，与本文件 :887 的实际值 1150 不符（Audit-2）。
    # （user_agent.py 口径，#49 已 480→540 上调）。本地评测必须与平台一致，
    # 否则"本地验证通过"不代表"比赛限时下可复现"。
    # 历史：540→900 是配合 54000s 不限时总池的放宽，违背比赛时间模拟，
    # 已回退。分时桶实测 >700s 档正确率 0%——多给时间不换正确率，
    # standard 540s 足够覆盖 450s 内能解对的快题。
    "tier_budget": {"fast": 120.0, "standard": 540.0, "deep": 1150.0},
    # ---- 全卷调度：本地 45 题小卷（2026-09-02 三次修正：恢复比赛折算）----
    # 用户要求：测试时间限制必须符合比赛要求，不能"不限时"。
    # 折算口径（题·秒守恒）：平台 112 题卷 target 21000s × 并发 3 =
    # 63000 题·秒 → 题均 562.5 题秒。45 题应得 45 × 562.5 = 25313 题秒，
    # 本地 pacer 并发假设同为 3 → target = 25313 / 3 ≈ 8438s（≈2.34h）。
    # 进度正常（elapsed/target ≤ 完成比例）时每题仍拿满档位预算；
    # 全卷拖沓时自动收紧（MIN_SOFT=120s 保底防占位符）——与平台同机制。
    # 历史：54000s（45×1200）="进度恒正常、每题吃满档"= 不限时，已废弃；
    # 8680s 是旧平台 18000s 时代口径（×1.2 余量），现版平台 21000s 更新为 8438s。
    "paper_total_questions": 45,
    "paper_target_time": 8438,
    # 前置验证最多 2 次尝试（原默认 2 轮 = 3 次，每次 21s 编译 + LLM 调用，
    # 单题可烧掉 3-5 分钟；preverify 是「检查理解」不是「写论文」，1 轮足够）
    # 2026-09-11：#13 前置验证修复——轮数 1→2（即最多 3 轮尝试）。
    # 依据：112 题实测 13 题 preverify fail，全部是「形式化代码编译错误」
    # （臆造 API/类型不匹配/语法错/引用未定义谓词），而原配置仅 2 轮机会；
    # 配合 prompt 增补的「常见错误规避」清单，给修正留出足够轮次。
    "preverify_max_rounds": 2,
    # 2026-09-11（B1 独立化）：启用"子目标数值断言的 Lean 核验"。
    # 此前该开关默认 False → B1 只能靠 P2 数值化间接触发，覆盖面过窄（实测 0/10）。
    # 打开后由 _numeric_lean_verify 对子目标里的数值断言做 Lean 复核
    # （走当前后端 mcp；每题次数受 lean_numeric_max_per_q 限制，默认 2 → 成本可控）。
    "enable_numeric_lean_verify": True,
}


class EvalEngine:
    def __init__(self, concurrency: int = 1, resume: bool = False,
                 api_key: str = "", base_url: str = "", model: str = "",
                 verbose: bool = False, agent_overrides: Optional[Dict[str, Any]] = None):
        self.concurrency = concurrency
        self.resume = resume
        self.verbose = verbose
        # 创建 LLM 客户端（通过环境变量或参数配置）
        self.llm_client = LLMClient(
            api_key=api_key or None,
            base_url=base_url or None,
            model=model or None,
        )
        # 配置覆盖：先取本地评测默认值，再叠加 CLI 传入的 A/B 开关
        overrides = dict(DEFAULT_AGENT_OVERRIDES)
        if agent_overrides:
            overrides.update(agent_overrides)
        # 保存生效覆盖（小样本自适应要用），避免二次重建时丢失
        self._effective_overrides = overrides
        self.agent = ReasoningAgent(self.llm_client, **overrides)
        logger.info("EvalEngine init: %s, overrides=%s", self.llm_client, overrides)
        self.domain_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "correct": 0}
        )

    def load_tests(self, filepath: str) -> List[Dict[str, Any]]:
        tests = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"第 {line_no} 行 JSON 解析失败")
                    continue
                if "question" not in item and "problem" not in item:
                    logger.warning(f"第 {line_no} 行缺少 question/problem")
                    continue
                # 统一规范化字段名（本地题库兼容：problem/question、subject/domain、idx/id）
                if "question" not in item:
                    item["question"] = item["problem"]
                if "domain" not in item and "subject" in item:
                    item["domain"] = item["subject"]
                if "id" not in item and "idx" in item:
                    item["id"] = item["idx"]
                item["_line_no"] = line_no
                tests.append(item)
        logger.info(f"加载 {len(tests)} 道测试题")
        return tests

    def solve_one(self, test: Dict[str, Any]) -> Dict[str, Any]:
        question = test["question"]
        gold = test.get("answer", "")
        domain = test.get("domain", "unknown")
        pid = test.get("id", str(test.get("_line_no", "?")))
        start = time.time()
        # ★ 2026-09-16 用户要求「极为详细的数据」：记录本题的 LLM 调用增量。
        # 全局计数器是进程累计的，必须做前后快照求差才等于"本题用了多少次"。
        _llm_before = _llm_call_snapshot()
        _mcp_before = _mcp_call_snapshot()
        _web_before = _web_call_snapshot()
        # ★★ 2026-09-16 修既有 bug（由 tests/test_result_detail_export.py 抓到）：
        # `result` 原先**只在 try 内赋值**，一旦 `agent.solve()` 抛异常，
        # 紧随其后的 `isinstance(result, dict)` 会抛 `UnboundLocalError`
        # ⇒ 整个 `solve_one` 崩溃、**该题在结果里彻底消失**（不是记为错，是丢失），
        # 批量评测时可能直接打断整轮。此处先给默认值。
        result: Dict[str, Any] = {}
        try:
            result = self.agent.solve(question, {})
            elapsed = time.time() - start
            pred_answer = result.get("final_response", "") if isinstance(result, dict) else ""
            response = result.get("final_response", "") if isinstance(result, dict) else str(result) if result else ""
        except Exception as e:
            logger.error(f"题目 {pid} 求解异常: {e}", exc_info=True)
            elapsed = time.time() - start
            pred_answer = ""
            response = f"ERROR: {e}"
            result = {}
        _llm_after = _llm_call_snapshot()
        llm_calls = {k: (_llm_after.get(k, 0) - _llm_before.get(k, 0))
                     for k in set(_llm_before) | set(_llm_after)}
        # ★ 工具级埋点（用户 2026-09-16 要求）：本题 Lean MCP 的调用次数/成功/失败/耗时。
        _mcp_after = _mcp_call_snapshot()
        mcp_calls = {
            "calls": _mcp_after["calls"] - _mcp_before["calls"],
            "ok": _mcp_after["ok"] - _mcp_before["ok"],
            "fail": _mcp_after["fail"] - _mcp_before["fail"],
            "seconds": round(_mcp_after["seconds"] - _mcp_before["seconds"], 2),
        }
        # 派生判读：MCP 是否真正生效（否则实际由 bridge 完成）
        if mcp_calls["calls"] == 0:
            mcp_calls["verdict"] = "未走 MCP"
        elif mcp_calls["ok"] > 0:
            mcp_calls["verdict"] = "MCP 生效"
        else:
            mcp_calls["verdict"] = "MCP 全部失败 → 实际由 bridge 完成"
        # ★ 联网搜索埋点（用户 2026-09-16 要求「这些工具的调用的效果也都记录」）
        _web_after = _web_call_snapshot()
        web_calls = {
            "calls": _web_after["calls"] - _web_before["calls"],
            "ok": _web_after["ok"] - _web_before["ok"],
            "fail": _web_after["fail"] - _web_before["fail"],
            "results": _web_after["results"] - _web_before["results"],
            "seconds": round(_web_after["seconds"] - _web_before["seconds"], 2),
        }
        web_calls["verdict"] = ("未调用" if web_calls["calls"] == 0
                                else "成功" if web_calls["ok"] > 0
                                else "全部失败")
        is_correct = answers_match(pred_answer, gold) if pred_answer and gold else None
        if not gold:
            is_correct = None
        # 错误分类：仅对判错样本分类（#6/#11/#16），用于定位瓶颈与决定优化投向
        error_class = ""
        if is_correct is False:
            error_class = _classify_error(pred_answer, gold)
        # Mathlib 使用证据（2026-08-29）：AI 检索/验证用到的定理 + 使用统计
        used_theorems = []
        if isinstance(result, dict):
            used_theorems = list(result.get("used_theorems") or [])
        usage_stats = {}
        if isinstance(result, dict):
            usage_stats = result.get("mathlib_usage_stats") or {}
        # 逐步归因诊断（2026-09-02）：orchestrator 已打包各阶段中间状态，
        # 这里落盘为结果行 diag 字段（错题可定位到理解/蓝图/子目标/验证等环节）
        diag = {}
        if isinstance(result, dict):
            diag = result.get("diag") or {}
        # ★ 2026-09-16 用户要求「极为详细的数据：大模型的解答过程 / 时间消耗 / 各环节效果」。
        # 此前只落盘 response[:2000] 与有限 diag，**候选的解答过程、全量事件流都没导出**
        # ⇒ 事后无法复盘"模型到底怎么想的、在哪一步跑偏"。以下四项把过程完整留痕：
        #   · response_full  最终回答**全文**（不再截断）
        #   · candidates     每个候选的 answer + **reasoning（解答过程）** + 得票
        #   · trace          全量事件流（各 agent/step 的顺序与内容）
        #   · verdicts/cluster 验证裁决与共识簇
        #   · llm_calls      本题 LLM 调用次数（全局计数前后快照之差）
        # ⚠ 体积可控：单题约几十 KB，10 题 ~1MB（此前每行只存 2KB 摘要）。
        cand_out: list = []
        verd_out: list = []
        cluster_out = None
        trace_out: list = []
        if isinstance(result, dict):
            _verds = result.get("verdicts") or []
            for i, c in enumerate(result.get("candidates") or []):
                if not isinstance(c, dict):
                    continue
                v = _verds[i] if i < len(_verds) and isinstance(_verds[i], dict) else {}
                cand_out.append({
                    "id": c.get("id", i),
                    "answer": c.get("answer", ""),
                    "reasoning": c.get("reasoning", ""),     # ★ 解答过程
                    "revised": bool(c.get("revised")),
                    "confidence": v.get("confidence"),
                    "correct_votes": v.get("correct_votes"),
                    "total_votes": v.get("total_votes"),
                    "feedback": v.get("feedback", ""),
                })
            for v in _verds:
                if isinstance(v, dict):
                    verd_out.append({
                        "id": v.get("id"),
                        "answer": v.get("answer", ""),
                        "confidence": v.get("confidence"),
                        "correct_votes": v.get("correct_votes"),
                        "total_votes": v.get("total_votes"),
                    })
            cluster_out = result.get("cluster")
            trace_out = result.get("trace") or []
        return {
            "id": pid, "domain": domain,
            "question": question, "gold": gold,
            "predicted": pred_answer, "response": response[:2000],
            # ★ 最终回答全文（不截断）
            "response_full": response,
            "correct": is_correct, "elapsed_sec": round(elapsed, 2),
            "error_class": error_class,
            # #1/#2 证据链：实际用到的 Mathlib 定理（leansearch 命中/编译通过）
            "used_theorems": used_theorems,
            "mathlib_usage_stats": usage_stats,
            # 逐步归因诊断（可空：老结果文件无此字段）
            "diag": diag,
            # ★ 2026-09-16 新增：过程留痕（候选解答过程 / 事件流 / 裁决 / 调用次数）
            "candidates": cand_out,
            "verdicts": verd_out,
            "cluster": cluster_out,
            "trace": trace_out,
            "llm_calls": llm_calls,
            # ★ 工具级埋点：Lean MCP + 通用联网搜索（calls/ok/fail/seconds + 派生判读）
            "tool_calls": {"lean_mcp": mcp_calls, "web_search": web_calls},
        }

    def run(self, test_file: str, output_file: str) -> Dict[str, Any]:
        tests = self.load_tests(test_file)
        done_ids = set()
        results = []
        if self.resume and os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            r = json.loads(line)
                            done_ids.add(r.get("id"))
                            results.append(r)
                            domain = r.get("domain", "unknown")
                            self.domain_stats[domain]["total"] += 1
                            if r.get("correct"):
                                self.domain_stats[domain]["correct"] += 1
                        except json.JSONDecodeError:
                            pass
            logger.info(f"断点续跑：跳过 {len(done_ids)} 道已完成")
        pending = [t for t in tests if str(t.get("id", t.get("_line_no"))) not in done_ids]
        logger.info(f"待评测: {len(pending)} / 总计: {len(tests)}")
        # ---- 小样本自适应（2026-09-02，DAG 冒烟 2 题全败根因）----
        # PaperPacer 用 paper_total_questions（45/112 全卷数）评估"卷面进度"，
        # 小卷（--test_file 2 题）第 1 题一完成就误判"卷面落后"→ 单题软预算被
        # 收紧到 ~200-500s → DAG 全链路（蓝图+评审+重写+子目标求解）跑不完
        # → llm() budget_skip → [子目标求解失败]。
        # 修正：待评测题数 < 配置全卷数时，按待评测题数重建 agent：
        #   paper_total_questions = 待评测题数；paper_target_time = 题数 ×
        #   (全卷 target / 全卷题数)，保证小卷的"题均可用时间"与全卷一致。
        # 2026-09-02 晚修复：判定基准从 len(tests) 改为 len(pending)——
        # --resume 断点续跑时 tests 仍是全卷（45），若按全卷判定不触发自适应，
        # 剩余 36 题继续吃 45 题紧预算（~540s/题）→ 占位符重演。
        # 2026-09-02 三次修正：target 由 54000 恢复比赛折算 8438（45/112×21000），
        # 题均墙钟 8438/45 ≈ 187.5s（× 并发 3 = 562 题秒，与平台题均一致）。
        if pending:
            cfg_total = int(self._effective_overrides.get(
                "paper_total_questions", 0) or 0)
            cfg_target = float(self._effective_overrides.get(
                "paper_target_time", 0) or 0)
            actual = len(pending)
            if cfg_total and actual < cfg_total:
                per_q = cfg_target / max(1, cfg_total)
                # 2026-09-02 晚方案 A（老师拍板）：小卷放宽——题均预算下限提到
                # standard 档满值 540s。原 187.5s/题 折算假设"全卷 45 题平均分"，
                # 小卷（10 题）deep 难题占比高（实测 4/10），1875s 池被
                # 4×1200s 挤爆 → 后续题被 PaperPacer 压到 120s 保底 → 占位符重演。
                # 540s/题 下限让小卷的 deep 题能跑满，难题有时间，测试才反映
                # 真实单题能力（不是被时间池结构性饿死）。
                per_q = max(per_q, 540.0)
                adapted = dict(self._effective_overrides)
                adapted["paper_total_questions"] = actual
                adapted["paper_target_time"] = max(120.0, int(actual * per_q))
                self.agent = ReasoningAgent(self.llm_client, **adapted)
                self._effective_overrides = adapted
                logger.info(
                    "小样本自适应: 待评测 %d 题 < 全卷 %d 题，重建 agent "
                    "(paper_total_questions=%d, paper_target_time=%d, per_q=%.1fs)",
                    actual, cfg_total, actual,
                    int(adapted["paper_target_time"]), per_q)
        with ThreadPoolExecutor(max_workers=max(1, self.concurrency)) as executor:
            future_map = {executor.submit(self.solve_one, t): t for t in pending}
            for future in as_completed(future_map):
                row = future.result()
                results.append(row)
                domain = row.get("domain", "unknown")
                self.domain_stats[domain]["total"] += 1
                if row.get("correct"):
                    self.domain_stats[domain]["correct"] += 1
                # 增量落盘（2026-08-28 新增）：每题完成立即追加写盘。
                # 此前全部跑完才写一次文件，中途 Ctrl-C / 杀进程 / 超时
                # 会丢掉所有已完成题目的结果。增量写 + --resume 断点续跑，
                # 保证任何时刻中断都能保留进度。
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.sort(key=lambda r: str(r.get("id", "")))
        with open(output_file, "w", encoding="utf-8") as f:
            for row in results:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info(f"结果已写入 {output_file}")
        return self._build_summary(results)

    def _build_summary(self, results: List[Dict]) -> Dict[str, Any]:
        total = len(results)
        scored = [r for r in results if r["correct"] is not None]
        correct = sum(1 for r in scored if r["correct"])
        accuracy = correct / len(scored) if scored else 0.0
        avg_elapsed = sum(r.get("elapsed_sec", 0) for r in results) / max(total, 1)
        summary = {
            "total": total, "scored": len(scored),
            "correct": correct, "accuracy": round(accuracy, 4),
            "avg_elapsed_sec": round(avg_elapsed, 2),
            "per_domain": {},
        }
        for domain, stats in sorted(self.domain_stats.items()):
            tot = stats["total"]
            cor = stats["correct"]
            summary["per_domain"][domain] = {
                "total": tot, "correct": cor,
                "accuracy": round(cor / tot, 4) if tot else 0.0,
            }

        # 错误分类分布（#6/#11/#16）——决定下一轮资源投向的核心依据
        wrong = [r for r in results if r.get("correct") is False]
        err_dist: Dict[str, int] = {}
        for r in wrong:
            k = r.get("error_class") or "unclassified"
            err_dist[k] = err_dist.get(k, 0) + 1
        n_wrong = len(wrong)
        summary["error_distribution"] = {
            "wrong_total": n_wrong,
            "counts": err_dist,
            "ratios": {k: round(v / n_wrong, 4) for k, v in err_dist.items()} if n_wrong else {},
        }
        # 决策提示：按计划 §2 P0.5 的决策规则给出建议，避免每次人工判读
        ratio = summary["error_distribution"]["ratios"]
        # 非推理类（不需要提升推理能力就能修）：空输出 + 抽取失败 + 答案未定型
        cheap = (ratio.get("empty_output", 0.0)
                 + ratio.get("extract_failed", 0.0)
                 + ratio.get("format_unresolved", 0.0))
        if n_wrong:
            if cheap >= 0.25:
                summary["recommendation"] = (
                    f"先做答案定型（Phase 1-A）：非推理类错误占比 {cheap:.0%}，"
                    "不动推理即可提分，风险最低")
            elif ratio.get("value_wrong", 0.0) >= 0.55:
                summary["recommendation"] = (
                    f"主攻答案题推理深度：value_wrong 占比 {ratio['value_wrong']:.0%}，"
                    "瓶颈在推理能力，投多候选/投票/revise")
            else:
                summary["recommendation"] = (
                    "天花板在推理深度，投 deep 通道扩容（多候选 + 预算生效）")
        return summary


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="MathPilot 本地评测工具")
    parser.add_argument("--test_file", default="", help="JSONL 测试文件路径")
    parser.add_argument("--bank", default="", help="题库名称（如 新高数、1000题高数、高数a、IMO-AnswerBench、all）")
    parser.add_argument("--list_banks", action="store_true", help="列出所有已注册题库")
    parser.add_argument("--output", default="eval_results.jsonl", help="输出结果文件")
    parser.add_argument("--concurrency", type=int, default=2, help="并发数")
    parser.add_argument("--resume", action="store_true", help="断点续跑")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    parser.add_argument("--api_key", default="", help="LLM API Key（或设置 OPENAI_API_KEY 环境变量）")
    parser.add_argument("--base_url", default="", help="LLM Base URL（或设置 OPENAI_BASE_URL 环境变量）")
    parser.add_argument("--model", default="", help="模型名（或设置 LLM_MODEL 环境变量）")
    # ---- A/B 能力开关（None 表示使用本地评测默认值）----
    parser.add_argument("--voting_times", type=int, default=None, help="verifier_voting_times（每个候选验证票数）")
    parser.add_argument("--verifier_deep_final_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="verifier_deep_final_enabled（带推理的最终复核，默认 false）")
    # ★ 2026-09-16 审计修复：以下两个键此前**只有 getattr 兜底**，
    #   AgentConfig 未声明、白名单未列、CLI 也没有 ⇒ 注释承诺的
    #   "回退/AB 开关"实际不可用（假开关）。现补全三处。
    parser.add_argument("--enable_question_type_hint", type=str, default=None,
                        choices=["true", "false"],
                        help="全题型强制注入题型特化纪律（默认 false；"
                             "仅客观题默认由 objective_tactic_enabled 控制）")
    parser.add_argument("--verify_reserve_seconds", type=float, default=None,
                        help="生成侧预留秒数（_gen_deadline = deadline − 此值）；"
                             "0/缺省 = 按档位默认（deep 540 / 其他 480）")
    parser.add_argument("--enable_web_search", type=str, default=None,
                        choices=["true", "false"],
                        help="启用联网搜索工具（web_search，默认 false；"
                             "经原生 tool_calls 调用，效果见 tool_calls.web_search）")
    parser.add_argument("--verifier_deep_final_min_remaining", type=float, default=None,
                        help="verifier_deep_final_min_remaining（剩余秒数低于此值则跳过复核）")
    # ★ 2026-09-15 审计补漏：以下两键原先**只有配置与白名单、没有 CLI 参数**
    # ⇒ 命令行根本传不进去（与"有 CLI 没白名单"是同一类坑的镜像）。
    parser.add_argument("--verifier_deep_review_temperature", type=float, default=None,
                        help="verifier_deep_review_temperature（复核采样温度，默认 0.0）")
    parser.add_argument("--verifier_deep_review_min_chars", type=int, default=None,
                        help="verifier_deep_review_min_chars（复核最短输出字数，低于此值视为未完成；0=关闭该护栏）")
    # ★ 2026-09-17 补：该键此前**有 AgentConfig 声明、有白名单、有读取点，却唯独没有 CLI**
    #   （同批的 temperature/min_chars 都有）⇒ 属审核列的"半假开关"，
    #   命令行无法调。实测需要它：默认 16384 过大，深复核产出 26k–42k 字符、
    #   VERDICT 出现 0 次且出现复读退化（两样本 chars 完全相同=26749）。
    parser.add_argument("--verifier_deep_review_max_tokens", type=int, default=None,
                        help="verifier_deep_review_max_tokens（复核单次最大 token，默认 16384；"
                             "建议 ≤6144 以缩短退化窗口）")
    # 2026-09-16 投票方差（候选分歧 → 提高票数 + 非零温度）
    parser.add_argument("--verifier_diversify_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="verifier_diversify_enabled（候选有分歧时提高票数+温度，默认 true）")
    parser.add_argument("--verifier_disagreement_votes", type=int, default=None,
                        help="verifier_disagreement_votes（有分歧时的每候选票数，默认 3）")
    parser.add_argument("--verifier_disagreement_temperature", type=float, default=None,
                        help="verifier_disagreement_temperature（有分歧时的采样温度，默认 0.7）")
    parser.add_argument("--use_scoring", type=str, default=None, choices=["true", "false"], help="use_scoring（验证器多维评分）")
    parser.add_argument("--revise_rounds", type=int, default=None, help="max_revise_rounds（自纠错回环轮数）")
    parser.add_argument("--use_proof", type=str, default=None, choices=["true", "false"], help="use_proof_channel（证明题专用通道）")
    parser.add_argument("--use_blueprint", type=str, default=None, choices=["true", "false"], help="use_blueprint（蓝图分解）")
    parser.add_argument("--blueprint_deps_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="blueprint_deps_enabled（DAG 依赖边；false=复现'依赖恒空'旧行为做 A/B）")
    # 2026-09-13：为 A/B 对比新增两个开关（此前只能改代码才能切换）。
    # 背景：`3.3_improve`(单Agent自审自改) 与 `3.4_collab`(三Agent协作改进)
    # 语义重叠，需要实测"哪个更高效"才能决定舍去哪一个。
    parser.add_argument("--enable_self_improve", type=str, default=None,
                        choices=["true", "false"],
                        help="enable_self_improve（3.3 Step2 无条件自改进）")
    parser.add_argument("--enable_collaborative_deep", type=str, default=None,
                        choices=["true", "false"],
                        help="enable_collaborative_deep（3.4 deep档三Agent协作）")
    parser.add_argument("--enable_dag_replan", type=str, default=None, choices=["true", "false"],
                        help="enable_dag_replan（DAG 动态评审+重生成闭环）")
    # 2026-09-08：求解前 DAG 强制门独立开关（默认关=去掉门）
    parser.add_argument("--dag_replan_gate", type=str, default=None, choices=["true", "false"], help="dag_replan_gate（求解前 DAG 强制评审门，默认 false）")
    # 2026-09-08：L2 子目标数值/代数断言 Lean 验证（lean-lsp-mcp norm_num/ring）
    parser.add_argument("--enable_numeric_lean_verify", type=str, default=None, choices=["true", "false"], help="enable_numeric_lean_verify（子目标数值断言 Lean 验证）")
    parser.add_argument("--lean_numeric_max_per_q", type=int, default=None, help="lean_numeric_max_per_q（每题数值 Lean 验证限额，默认 2）")
    # 2026-09-09 P1/P2：计算强制纪律 + 子目标类型路由（A/B 开关）
    parser.add_argument("--calc_mandatory", type=str, default=None, choices=["true", "false"], help="calc_mandatory（裸数值断言打回=计算必须走工具）")
    parser.add_argument("--calc_hard_only", type=str, default=None, choices=["true", "false"], help="calc_hard_only（计算分档：只强制易错算子 [根号/对数/组合数/幂/e…] 走工具，纯四则可自算）")
    parser.add_argument("--subgoal_calc_router", type=str, default=None, choices=["true", "false"], help="subgoal_calc_router（计算型子目标 terminal 专用路径）")
    parser.add_argument("--tool_calc_enabled", type=str, default=None, choices=["true", "false"], help="tool_calc_enabled（原生 calc_eval 工具调用试点）")
    # 2026-09-10 L1/L2：计算核验关卡（默认关，A/B 用）
    parser.add_argument("--answer_selfcheck_enabled", type=str, default=None, choices=["true", "false"], help="answer_selfcheck_enabled（L1：数值答案无 <calc> 工具来源 → 定向重问）")
    parser.add_argument("--symbolic_crosscheck_enabled", type=str, default=None, choices=["true", "false"], help="symbolic_crosscheck_enabled（L2：独立符号建模求真值 → 与答案比对，不符则打回）")
    # 2026-09-12 符号化方程求解通道：模型只交方程（组）+ 目标，数值由本地工具算
    parser.add_argument("--symbolic_solve_enabled", type=str, default=None, choices=["true", "false"], help="symbolic_solve_enabled（数值剥离→模型符号建模→工具求解，模型不参与计算）")
    parser.add_argument("--symbolic_solve_feedback", type=str, default=None, choices=["true", "false"], help="symbolic_solve_feedback（工具值与答案分歧时回传工具结果给模型定稿）")
    parser.add_argument("--symbolic_solve_adopt", type=str, default=None, choices=["true", "false"], help="symbolic_solve_adopt（方案④：工具求解成功后答案直接取工具值，模型不参与计算）")
    parser.add_argument("--use_fast_path", type=str, default=None, choices=["true", "false"], help="by_enable_fast_path（SymPy 快车道）")
    parser.add_argument("--max_total_calls", type=int, default=None, help="max_total_calls（单题 LLM 调用预算）")
    # ---- 2026-09-13 诊断模式：时间限制放开（默认不传 = 保持比赛口径，行为不变）----
    # 用途：服务端高延迟时（实测单次 LLM 60–180s），比赛口径会让每题被"预算不足"
    # 中途截断（budget_skips 飙升），**看不到完整的失败路径**。诊断跑分时放开，
    # 只为定位"错在哪一步"；⚠ 放宽口径的成绩**不得对外报数**。
    parser.add_argument("--max_time_per_question", type=int, default=None,
                        help="单题壁钟上限秒（诊断用；不传=1200 比赛口径）")
    parser.add_argument("--tier_budget", type=str, default=None,
                        help="三档预算 'fast,standard,deep'（诊断用；不传=120,540,1150）")
    parser.add_argument("--paper_target_time", type=int, default=None,
                        help="全卷墙钟目标秒（诊断用；放大后 PaperPacer 不再收紧单题预算）")
    # ---- 2026-09-15 赛后无约束评测：补齐此前**没有 CLI 入口**的旋钮 ----
    # 背景：上述 4 个诊断参数只覆盖了一部分约束，`max_total_time_seconds` /
    # 子目标阶段预算 / `max_subgoals` / `improve_min_remaining` / `deep_quota_ratio`
    # 此前只能改代码，导致"解除比赛限制"做不彻底（改了单题上限，全卷仍被 20700 卡）。
    # 全部默认 None = 不传即保持比赛口径，行为与改动前逐字节一致。
    parser.add_argument("--max_total_time_seconds", type=int, default=None,
                        help="Agent 总运行上限秒（诊断用；不传=20700 比赛口径）")
    parser.add_argument("--subgoal_stage_budget_sec", type=float, default=None,
                        help="deep 档子目标阶段预算秒（诊断用；不传=750）")
    parser.add_argument("--subgoal_stage_budget_sec_std", type=float, default=None,
                        help="standard/fast 档子目标阶段预算秒（诊断用；不传=450）")
    parser.add_argument("--max_subgoals", type=int, default=None,
                        help="子目标规划数上限（诊断用；不传=6 比赛口径；<=0 表示不截断）")
    # ---- LeanSearch 引理检索（2026-09-15 重启；A/B 用）----
    parser.add_argument("--use_leansearch", type=str, default=None,
                        choices=["true", "false"],
                        help="use_leansearch（LeanSearch 引理检索总开关，默认关）")
    parser.add_argument("--leansearch_top_k", type=int, default=None,
                        help="leansearch_top_k（每次检索返回条数，默认 5；老师 #46 要求扫 3/5/10）")
    parser.add_argument("--leansearch_max_calls_per_q", type=int, default=None,
                        help="leansearch_max_calls_per_q（单题检索次数上限，默认 2）")
    parser.add_argument("--leansearch_inject_verifier", type=str, default=None,
                        choices=["true", "false"],
                        help="leansearch_inject_verifier（方案 A：把定理原文注入验证器，默认 true）")
    parser.add_argument("--improve_min_remaining", type=float, default=None,
                        help="3.3 改进停手预留秒（诊断用；不传=300；0=关闭该护栏）")
    parser.add_argument("--deep_quota_ratio", type=float, default=None,
                        help="deep 档全卷占比上限（诊断用；不传=0.25；1.0=不限制）")
    parser.add_argument("--paper_total_questions", type=int, default=None,
                        help="全卷题数（PaperPacer 分摊基准；不传=45 本地默认）")
    args = parser.parse_args()

    if args.list_banks:
        list_banks()
        return

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 解析 test_file：--bank 优先
    test_files: List[str] = []
    if args.bank:
        resolved = resolve_bank(args.bank)
        if resolved is None:
            print(f"错误: 未知题库 '{args.bank}'。使用 --list_banks 查看可用题库。")
            sys.exit(1)
        if isinstance(resolved, list):
            test_files = resolved
        else:
            test_files = [resolved]
    elif args.test_file:
        test_files = [args.test_file]
    else:
        print("错误: 请指定 --test_file 或 --bank。使用 --list_banks 查看可用题库。")
        sys.exit(1)

    # 收集 A/B 能力开关
    overrides: Dict[str, Any] = {}
    if args.voting_times is not None:
        overrides["verifier_voting_times"] = args.voting_times
    if args.verifier_deep_final_enabled is not None:
        overrides["verifier_deep_final_enabled"] = (
            args.verifier_deep_final_enabled == "true")
    # ★ 2026-09-16 审计补全：让这两个键的 CLI 真正生效
    #   （此前只有 getattr 兜底，注释承诺的回退/AB 开关是假的）
    if getattr(args, "enable_question_type_hint", None) is not None:
        overrides["enable_question_type_hint"] = (
            args.enable_question_type_hint == "true")
    if getattr(args, "verify_reserve_seconds", None) is not None:
        overrides["verify_reserve_seconds"] = args.verify_reserve_seconds
    if getattr(args, "enable_web_search", None) is not None:
        overrides["enable_web_search"] = (args.enable_web_search == "true")
    if args.verifier_deep_final_min_remaining is not None:
        overrides["verifier_deep_final_min_remaining"] = (
            args.verifier_deep_final_min_remaining)
    if args.verifier_deep_review_temperature is not None:
        overrides["verifier_deep_review_temperature"] = (
            args.verifier_deep_review_temperature)
    if args.verifier_deep_review_min_chars is not None:
        overrides["verifier_deep_review_min_chars"] = (
            args.verifier_deep_review_min_chars)
    if getattr(args, "verifier_deep_review_max_tokens", None) is not None:
        overrides["verifier_deep_review_max_tokens"] = (
            args.verifier_deep_review_max_tokens)
    if args.verifier_diversify_enabled is not None:
        overrides["verifier_diversify_enabled"] = (
            args.verifier_diversify_enabled == "true")
    if args.verifier_disagreement_votes is not None:
        overrides["verifier_disagreement_votes"] = args.verifier_disagreement_votes
    if args.verifier_disagreement_temperature is not None:
        overrides["verifier_disagreement_temperature"] = (
            args.verifier_disagreement_temperature)
    if args.use_scoring is not None:
        overrides["use_scoring"] = args.use_scoring == "true"
    if args.revise_rounds is not None:
        overrides["max_revise_rounds"] = args.revise_rounds
    if args.use_proof is not None:
        overrides["use_proof_channel"] = args.use_proof == "true"
    if args.use_blueprint is not None:
        overrides["use_blueprint"] = args.use_blueprint == "true"
    if args.blueprint_deps_enabled is not None:
        overrides["blueprint_deps_enabled"] = (
            args.blueprint_deps_enabled == "true")
    if args.enable_dag_replan is not None:
        overrides["enable_dag_replan"] = args.enable_dag_replan == "true"
    if args.enable_self_improve is not None:
        overrides["enable_self_improve"] = args.enable_self_improve == "true"
    if args.enable_collaborative_deep is not None:
        overrides["enable_collaborative_deep"] = \
            args.enable_collaborative_deep == "true"
    if args.dag_replan_gate is not None:
        overrides["dag_replan_gate"] = args.dag_replan_gate == "true"
    if args.enable_numeric_lean_verify is not None:
        overrides["enable_numeric_lean_verify"] = \
            args.enable_numeric_lean_verify == "true"
    if args.lean_numeric_max_per_q is not None:
        overrides["lean_numeric_max_per_q"] = args.lean_numeric_max_per_q
    if args.calc_mandatory is not None:
        overrides["calc_mandatory"] = args.calc_mandatory == "true"
    if args.calc_hard_only is not None:
        overrides["calc_hard_only"] = args.calc_hard_only == "true"
    if args.subgoal_calc_router is not None:
        overrides["subgoal_calc_router"] = args.subgoal_calc_router == "true"
    if args.tool_calc_enabled is not None:
        overrides["tool_calc_enabled"] = args.tool_calc_enabled == "true"
    # 2026-09-10 L1/L2 计算核验关卡
    if args.answer_selfcheck_enabled is not None:
        overrides["answer_selfcheck_enabled"] = args.answer_selfcheck_enabled == "true"
    if args.symbolic_crosscheck_enabled is not None:
        overrides["symbolic_crosscheck_enabled"] = args.symbolic_crosscheck_enabled == "true"
    # 2026-09-12 符号化方程求解通道
    if args.symbolic_solve_enabled is not None:
        overrides["symbolic_solve_enabled"] = args.symbolic_solve_enabled == "true"
    if args.symbolic_solve_feedback is not None:
        overrides["symbolic_solve_feedback"] = args.symbolic_solve_feedback == "true"
    if args.symbolic_solve_adopt is not None:
        overrides["symbolic_solve_adopt"] = args.symbolic_solve_adopt == "true"
    if args.use_fast_path is not None:
        overrides["by_enable_fast_path"] = args.use_fast_path == "true"
    if args.max_total_calls is not None:
        overrides["max_total_calls"] = args.max_total_calls
    # 2026-09-13 诊断模式：时间限制放开
    if args.max_time_per_question is not None:
        overrides["max_time_per_question"] = args.max_time_per_question
    if args.tier_budget:
        _tb = [float(x) for x in args.tier_budget.split(",")]
        if len(_tb) == 3:
            overrides["tier_budget"] = {"fast": _tb[0], "standard": _tb[1], "deep": _tb[2]}
    if args.paper_target_time is not None:
        overrides["paper_target_time"] = args.paper_target_time
    # 2026-09-15 赛后无约束评测：补齐 7 个旋钮（默认 None ⇒ 不改变比赛口径）
    if args.max_total_time_seconds is not None:
        overrides["max_total_time_seconds"] = args.max_total_time_seconds
    if args.subgoal_stage_budget_sec is not None:
        overrides["subgoal_stage_budget_sec"] = args.subgoal_stage_budget_sec
    if args.subgoal_stage_budget_sec_std is not None:
        overrides["subgoal_stage_budget_sec_std"] = args.subgoal_stage_budget_sec_std
    if args.max_subgoals is not None:
        overrides["max_subgoals"] = args.max_subgoals
    # ---- LeanSearch 引理检索（2026-09-15 重启）----
    if args.use_leansearch is not None:
        overrides["use_leansearch"] = args.use_leansearch == "true"
    if args.leansearch_top_k is not None:
        overrides["leansearch_top_k"] = args.leansearch_top_k
    if args.leansearch_max_calls_per_q is not None:
        overrides["leansearch_max_calls_per_q"] = args.leansearch_max_calls_per_q
    if args.leansearch_inject_verifier is not None:
        overrides["leansearch_inject_verifier"] = (
            args.leansearch_inject_verifier == "true")
    if args.improve_min_remaining is not None:
        overrides["improve_min_remaining"] = args.improve_min_remaining
    if args.deep_quota_ratio is not None:
        overrides["deep_quota_ratio"] = args.deep_quota_ratio
    if args.paper_total_questions is not None:
        overrides["paper_total_questions"] = args.paper_total_questions

    engine = EvalEngine(
        concurrency=args.concurrency, resume=args.resume,
        api_key=args.api_key, base_url=args.base_url, model=args.model,
        verbose=args.verbose, agent_overrides=overrides,
    )

    # 支持多题库评测
    all_summaries = []
    base_output = args.output
    for i, test_file in enumerate(test_files):
        # 多题库时自动命名输出文件
        if len(test_files) > 1:
            bank_name = os.path.splitext(os.path.basename(test_file))[0]
            stem, ext = os.path.splitext(base_output)
            output_file = f"{stem}_{bank_name}{ext}"
        else:
            output_file = base_output

        print(f"\n{'='*60}")
        print(f"题库 [{i+1}/{len(test_files)}]: {os.path.basename(test_file)}")
        print(f"输出文件: {output_file}")
        print(f"{'='*60}")

        summary = engine.run(test_file, output_file)
        all_summaries.append((test_file, summary))

    # 打印汇总报告
    for test_file, summary in all_summaries:
        print("\n" + "=" * 60)
        print(f"MathPilot 评测报告 - {os.path.basename(test_file)}")
        print("=" * 60)
        print(f"题目总数:   {summary['total']}")
        print(f"可判分题:   {summary['scored']}")
        print(f"正确数:     {summary['correct']}")
        print(f"准确率:     {summary['accuracy']:.2%}")
        print(f"平均耗时:   {summary['avg_elapsed_sec']} 秒")
        print("-" * 60)
        print(f"{'领域':<25} {'总数':<6} {'正确':<6} {'准确率':<8}")
        print("-" * 60)
        for domain, stats in summary.get("per_domain", {}).items():
            print(f"{domain:<25} {stats['total']:<6} {stats['correct']:<6} {stats['accuracy']:<8.2%}")
        print("=" * 60)

    # 多题库时打印总汇总
    if len(all_summaries) > 1:
        total_q = sum(s['total'] for _, s in all_summaries)
        total_correct = sum(s['correct'] for _, s in all_summaries)
        total_scored = sum(s['scored'] for _, s in all_summaries)
        print("\n" + "=" * 60)
        print("全部题库汇总")
        print("=" * 60)
        print(f"题库数:     {len(all_summaries)}")
        print(f"题目总数:   {total_q}")
        print(f"可判分题:   {total_scored}")
        print(f"正确数:     {total_correct}")
        print(f"总准确率:   {total_correct/total_scored:.2%}" if total_scored else "总准确率:   N/A")
        print("=" * 60)

    # ---- LeanSearch 检索埋点落盘（2026-09-15，老师 #44）----
    # 只在**真正发生过检索**时写文件，避免生成空文件误导后续聚合。
    # 输出：每行一个事件（call / adopted），末尾一行 summary，便于离线按题统计漏斗。
    try:
        from tools.lean_local.lean_search import get_stats as _ls_stats
        _ls = _ls_stats()
        _ls_sum = _ls.summary()
        if _ls_sum.get("calls"):
            _ls_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "results", "leansearch_calls.jsonl")
            if _ls.flush(_ls_path):
                print("LeanSearch 埋点已落盘:", _ls_path)
                print("  汇总:", json.dumps(_ls_sum, ensure_ascii=False))
            else:
                print("LeanSearch 埋点落盘失败（不影响评测结果）")
    except Exception as _e:  # noqa: BLE001
        print("LeanSearch 埋点落盘跳过:", str(_e)[:160])


if __name__ == "__main__":
    main()
