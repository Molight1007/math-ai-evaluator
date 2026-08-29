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


def _matches_one(pred_f: str, gold_f: str) -> bool:
    """单次多级匹配：字符串相等 → 分数等价 → 浮点近似 → SymPy 符号等价。"""
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
    # 推导文本：提取 '= X' 结论逐个匹配
    for cand in _extract_equals_candidates(pred):
        if _matches_one(_norm_candidate(cand), gold_f):
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
    # ---- 全卷调度：本地 45 题小卷，按 112 题全卷的题均配额折算 ----
    # 平台：112 题 / 18000s（5h 墙钟，并发 3）
    # 45 题应得 45/112 × 18000 ≈ 7232s；再给 20% 余量 ≈ 8680s
    # （2026-08-28 修正：5400s 会让 paper_cap 只有 360s/题，而 Lean 前置
    #   验证在本地真编译 mathlib（每次 ~21s）+ 子目标求解就超过预算，
    #   表现为「剩余时间不足，跳过 LLM」→ 全部输出 [子目标求解失败]）
    "paper_total_questions": 45,
    "paper_target_time": 8680,
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
        return {
            "id": pid, "domain": domain,
            "question": question, "gold": gold,
            "predicted": pred_answer, "response": response[:2000],
            "correct": is_correct, "elapsed_sec": round(elapsed, 2),
            "error_class": error_class,
            # #1/#2 证据链：实际用到的 Mathlib 定理（leansearch 命中/编译通过）
            "used_theorems": used_theorems,
            "mathlib_usage_stats": usage_stats,
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
