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


def _ensure_local_llm_env() -> None:
    """本地评测用：组装 LLM 端点配置（显式环境变量优先）。

    - API Key：读 ~/.math_evaluator/.env 的 INTERN_S1_API_KEY（与 GUI 共用）
    - 主端点：chat.intern-ai.org.cn + Intern-S2-Preview-397B（prefill 可靠）
    - 备用端点：.env 的 INTERN_S1_BASE_URL/MODEL（puyu/intern-s1）
    """
    env_path = os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env")
    env_values = {}
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    env_values[key.strip()] = value.strip().strip('"').strip("'")
        except OSError:
            logger.warning("无法读取 %s，请用 --api_key/--base_url/--model 手动指定", env_path)

    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = env_values.get("INTERN_S1_API_KEY", "not-needed")
    if not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = "https://chat.intern-ai.org.cn/api/v1"
    if not os.getenv("LLM_MODEL"):
        os.environ["LLM_MODEL"] = "Intern-S2-Preview-397B"
    if not os.getenv("OPENAI_FALLBACK_BASE_URL"):
        os.environ["OPENAI_FALLBACK_BASE_URL"] = env_values.get(
            "INTERN_S1_BASE_URL", "").rstrip("/")
    if not os.getenv("OPENAI_FALLBACK_MODEL"):
        os.environ["OPENAI_FALLBACK_MODEL"] = env_values.get("INTERN_S1_MODEL", "")
    if not os.getenv("LLM_TIMEOUT") and env_values.get("LLM_TIMEOUT"):
        os.environ["LLM_TIMEOUT"] = env_values["LLM_TIMEOUT"]
    if not os.getenv("LLM_MAX_RETRIES") and env_values.get("LLM_MAX_RETRIES"):
        os.environ["LLM_MAX_RETRIES"] = env_values["LLM_MAX_RETRIES"]

# ===========================================================================
# 答案规范化与匹配
# ===========================================================================

# LaTeX 常见符号 → Unicode（用于答案归一化，如 \pi → π）
_LATEX_SYMBOL_MAP = {
    r"\pi": "π", r"\infty": "∞", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
    r"\Delta": "Δ", r"\lambda": "λ", r"\sqrt": "√",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\pm": "±",
}


def _clean_answer(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    # 剥行内公式包裹 \( \) \[ \]（2026-08-20：模型常输出带包裹的 LaTeX）
    t = re.sub(r"\\[\(\[]", "", t)
    t = re.sub(r"\\[\)\]]", "", t)
    # \dfrac / \tfrac / \cfrac → \frac（统一分数命令）
    t = re.sub(r"\\(?:dfrac|tfrac|cfrac)", r"\\frac", t)
    # 剥 \left \right 定界符
    t = re.sub(r"\\left", "", t)
    t = re.sub(r"\\right", "", t)
    t = t.replace("$", "").replace(" ", "")
    t = t.replace("\\displaystyle", "")
    t = t.replace("\\,", "").replace("\\;", "").replace("\\!", "")
    # 中文字符→英文标点（便于后续比较）
    t = t.replace("，", ",").replace("。", ".").replace("；", ";")
    # 去尾部标点（. ; , ！ ？ 等）
    t = re.sub(r"[.;;,!！?？:：\s]+$", "", t)
    for cmd, uni in _LATEX_SYMBOL_MAP.items():
        t = t.replace(cmd, uni)
    return t


def _norm_candidate(text: str) -> str:
    """候选答案规范化（LaTeX 分数 → 除法表达 + 隐式乘法补全供 SymPy）。"""
    cleaned = _clean_answer(text)
    # 隐式乘法补全（2026-08-20）："e^x(x-1)" → "e^x*(x-1)"，供 sympify 解析
    cleaned = re.sub(r"(\d)([a-zA-Zα-ω])", r"\1*\2", cleaned)   # 5x → 5*x
    cleaned = re.sub(r"(\d)\(", r"\1*(", cleaned)                # 2( → 2*(
    cleaned = re.sub(r"\)\s*([a-zA-Zα-ω])", r")*\1", cleaned)   # )x → )*x
    cleaned = re.sub(r"\)\s*\(", r")*(", cleaned)                # )( → )*(
    return _laTeX_to_py_frac(cleaned)


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
    # 兜底：parse_expr 支持隐式乘法与函数识别（2026-08-20）
    # 解决 "e^x(x-1)+C" ≡ "xe^x-e^x+C"（sympify 无法解析隐式乘法）
    try:
        import sympy as _sp
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations,
            implicit_multiplication_application, convert_xor,
        )
        _trans = standard_transformations + (convert_xor, implicit_multiplication_application)
        a = parse_expr(pred_f, transformations=_trans)
        b = parse_expr(gold_f, transformations=_trans)
        return _sp.simplify(a - b) == 0
    except Exception:
        pass
    return False


def _key_values(text: str) -> frozenset:
    """提取文本答案中的关键数值/赋值对集合（2026-08-20）。

    处理"极大值点为 x = -1，极小值点为 x = 1" 这类文本答案：
    提取所有 `变量=数值` 对（含 f(-1)=3 函数值形式）与孤立数值。
    零误报原则：仅当两侧提取集合非空且完全相等才判对。
    """
    vals = set()
    # 函数值形式：f(-1)=3 / f(1)=-1
    for m in re.finditer(
        r"([a-zA-Zα-ω])\s*\(\s*([^()]*?)\s*\)\s*[=＝]\s*(-?\d+(?:\.\d+)?)", text):
        vals.add(f"{m.group(1)}({m.group(2)})={m.group(3)}")
    # 变量=数值 对（x=-1、极大值=3）
    for m in re.finditer(r"([a-zA-Zα-ω])\s*[=＝]\s*(-?\d+(?:\.\d+)?)", text):
        vals.add(f"{m.group(1)}={m.group(2)}")
    # 孤立数值（-1, 3, 1.5）
    for m in re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", text):
        vals.add(f"#{m.group()}")
    return frozenset(vals)


# 判定词白名单：短结论（收敛/发散等）出现在 gold 文本中即视为等价
_JUDGEMENT_WORDS = frozenset({
    "收敛", "发散", "条件收敛", "绝对收敛", "一致收敛", "无解", "有解",
    "不收敛", "可导", "不可导", "连续", "不连续", "递增", "递减",
})


def _judgement_contains(pred: str, gold: str) -> bool:
    """短判定词匹配（2026-08-20）：
    pred 是白名单判定词且 gold 文本包含该词 → 判对。
    """
    p = pred.strip()
    if p in _JUDGEMENT_WORDS and p in gold:
        return True
    return False


def answers_match(pred: str, gold: str) -> bool:
    """多级答案匹配：字符串相等 → 分数等价 → 浮点近似 → SymPy 符号等价。

    2026-08-20 增强：
    - 清洗支持 \\( \\) 包裹、\\dfrac 统一、尾部标点归一；
    - 推导文本 '= X' 结论提取；
    - 文本答案去标点比较；关键数值/赋值对一致；短判定词包含匹配。
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
    # 文本答案：去所有非字母数字/中文符号后比较（"条件收敛" vs "条件收敛。"）
    pred_text = re.sub(r"[^\w\u4e00-\u9fff\-+]", "", pred_f)
    gold_text = re.sub(r"[^\w\u4e00-\u9fff\-+]", "", gold_f)
    if (pred_text and gold_text and pred_text == gold_text
            and len(pred_text) >= 2 and len(gold_text) >= 2):
        return True
    # 关键数值/赋值对完全一致（长文本答案，如极大值点/区间）
    pv, gv = _key_values(pred_f), _key_values(gold_f)
    if pv and gv and pv == gv and len(pv) >= 2:
        return True
    # 短判定词包含匹配（pred="发散" vs gold 长解析含"发散"）
    if _judgement_contains(pred, gold):
        return True
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


# ===========================================================================
# 评测引擎
# ===========================================================================

# 本地评测默认参数（对应"全开"版本，用于 A/B 对比的基线）
# 与平台默认（user_agent.py AgentConfig 保守配置）不同，本地可自由实验。
DEFAULT_AGENT_OVERRIDES: Dict[str, Any] = {
    "policy_sample_times": 3,
    "verifier_voting_times": 2,
    "max_total_calls": 40,
    "max_revise_rounds": 1,
    "max_workers": 3,
    "use_scoring": True,
    "by_enable_fast_path": True,
    "use_proof_channel": False,
    "use_lemma_accumulation": True,
    "max_time_per_question": 1100,
    "max_answer_tokens": 8192,
    "revise_sample_times": 2,
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
        return {
            "id": pid, "domain": domain,
            "question": question, "gold": gold,
            "predicted": pred_answer, "response": response[:2000],
            "correct": is_correct, "elapsed_sec": round(elapsed, 2),
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
    # ---- v3 P1 零风险组件 A/B 开关 ----
    parser.add_argument("--judger_friendly", type=str, default=None, choices=["true", "false"], help="judger_friendly（Formatter 黑盒 Judger 友好输出）")
    parser.add_argument("--use_deterministic", type=str, default=None, choices=["true", "false"], help="use_deterministic（Verifier 确定性旁证，0 LLM 预算）")
    args = parser.parse_args()

    if args.list_banks:
        list_banks()
        return

    # 本地评测配置：优先显式环境变量，其次 ~/.math_evaluator/.env（GUI 共用）
    _ensure_local_llm_env()

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
    if args.judger_friendly is not None:
        overrides["judger_friendly"] = args.judger_friendly == "true"
    if args.use_deterministic is not None:
        overrides["use_deterministic"] = args.use_deterministic == "true"

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
