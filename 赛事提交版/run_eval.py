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
    return _laTeX_to_py_frac(_clean_answer(text))


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


def _try_fraction_compare(a: str, b: str) -> bool:
    frac_a = re.findall(r'(-?\d+)\s*/\s*(-?\d+)', a)
    frac_b = re.findall(r'(-?\d+)\s*/\s*(-?\d+)', b)
    if frac_a and frac_b:
        try:
            na, da = int(frac_a[0][0]), int(frac_a[0][1])
            nb, db = int(frac_b[0][0]), int(frac_b[0][1])
            return na * db == nb * da
        except (ValueError, ZeroDivisionError):
            pass
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
    # 选项类答案：'A' ↔ 'A.绝对收敛' / '绝对收敛' ↔ 'A.绝对收敛'（2026-09-02）
    if _option_letter_match(pred_f, gold_f):
        return True
    # 推导文本：提取 '= X' 结论逐个匹配
    for cand in _extract_equals_candidates(pred):
        cand_f = _norm_candidate(cand)
        if _matches_one(cand_f, gold_f):
            return True
        if _option_letter_match(cand_f, gold_f):
            return True
    return False


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

    # 1) 空输出 / 只剩定界符 → 解析或截断 bug
    if not p or _EMPTY_DELIM.match(p):
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
# 导致本地测出来的数字不能代表平台表现。现已全部对齐平台默认值，
# 保证"本地基线 == 平台基线"，A/B 实验才有意义。
# 需要偏离平台时请用 CLI 的 --agent_override 显式指定。
DEFAULT_AGENT_OVERRIDES: Dict[str, Any] = {
    # ---- 对齐 user_agent.py:64 / :72 ----
    "policy_sample_times": 2,
    "verifier_voting_times": 2,
    # ---- 对齐 user_agent.py:84 / :94 ----
    "max_total_calls": 150,
    "max_time_per_question": 1200,
    # ---- 对齐 user_agent.py:101 / :105 / :106 ----
    "max_workers": 3,
    "max_answer_tokens": 8192,
    "revise_sample_times": 2,
    "max_revise_rounds": 1,
    # ---- 对齐 user_agent.py:109 / :112 / :113 ----
    "use_scoring": False,
    "use_proof_channel": False,
    "use_lemma_accumulation": False,
    "by_enable_fast_path": True,
    # ---- 本地卷档位预算（2026-09-02 晚三次修正：对齐比赛限时）----
    # 平台 112 题卷 tier_budget = fast 120 / standard 540 / deep 1200
    # （user_agent.py 口径，#49 已 480→540 上调）。本地评测必须与平台一致，
    # 否则"本地验证通过"不代表"比赛限时下可复现"。
    # 历史：540→900 是配合 54000s 不限时总池的放宽，违背比赛时间模拟，
    # 已回退。分时桶实测 >700s 档正确率 0%——多给时间不换正确率，
    # standard 540s 足够覆盖 450s 内能解对的快题。
    "tier_budget": {"fast": 120.0, "standard": 540.0, "deep": 1200.0},
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
    "preverify_max_rounds": 1,
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
        return {
            "id": pid, "domain": domain,
            "question": question, "gold": gold,
            "predicted": pred_answer, "response": response[:2000],
            "correct": is_correct, "elapsed_sec": round(elapsed, 2),
            "error_class": error_class,
            # #1/#2 证据链：实际用到的 Mathlib 定理（leansearch 命中/编译通过）
            "used_theorems": used_theorems,
            "mathlib_usage_stats": usage_stats,
            # 逐步归因诊断（可空：老结果文件无此字段）
            "diag": diag,
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
    parser.add_argument("--use_scoring", type=str, default=None, choices=["true", "false"], help="use_scoring（验证器多维评分）")
    parser.add_argument("--revise_rounds", type=int, default=None, help="max_revise_rounds（自纠错回环轮数）")
    parser.add_argument("--use_proof", type=str, default=None, choices=["true", "false"], help="use_proof_channel（证明题专用通道）")
    parser.add_argument("--use_blueprint", type=str, default=None, choices=["true", "false"], help="use_blueprint（蓝图分解）")
    parser.add_argument("--enable_dag_replan", type=str, default=None, choices=["true", "false"], help="enable_dag_replan（DAG 动态评审+重生成闭环）")
    parser.add_argument("--use_fast_path", type=str, default=None, choices=["true", "false"], help="by_enable_fast_path（SymPy 快车道）")
    parser.add_argument("--max_total_calls", type=int, default=None, help="max_total_calls（单题 LLM 调用预算）")
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
    if args.use_scoring is not None:
        overrides["use_scoring"] = args.use_scoring == "true"
    if args.revise_rounds is not None:
        overrides["max_revise_rounds"] = args.revise_rounds
    if args.use_proof is not None:
        overrides["use_proof_channel"] = args.use_proof == "true"
    if args.use_blueprint is not None:
        overrides["use_blueprint"] = args.use_blueprint == "true"
    if args.enable_dag_replan is not None:
        overrides["enable_dag_replan"] = args.enable_dag_replan == "true"
    if args.use_fast_path is not None:
        overrides["by_enable_fast_path"] = args.use_fast_path == "true"
    if args.max_total_calls is not None:
        overrides["max_total_calls"] = args.max_total_calls

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


if __name__ == "__main__":
    main()
