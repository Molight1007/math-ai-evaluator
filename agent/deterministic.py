from __future__ import annotations
"""
确定性验证通道（DeterministicChecker）
=====================================

纯本地、零 LLM 预算的答案旁证/硬否决验证器（v2.8，自 sq 分支增量移植）。设计来源：
- DeepSeek-Harness 的 code-runner 判分哲学：用确定性计算（而非模型直觉）验证答案
- Intern-MO 的自验证思想：多证据汇审，确定性证据权重最高

能力：
1. verify_by_substitution — 等式/恒等式代入采样验证（随机采样变量组，数值核对）
2. search_counterexample — 反例搜索（对一般性命题尝试数值反例；LLM 只生成候选、程序只判定）
3. numerical_backtrack — 数值回溯（把可解析的答案转为数值串，供一致性旁证）
4. check_answer — 高层入口：对单个候选答案做综合确定性旁证/硬否决

安全原则（宁可 unknown 绝不误杀）：
- 一切解析失败/计算失败都返回 unknown；
- 代入回验只作用于「等式一侧为纯常量」的方程（防止定义式/求值式的误杀）；
- 反例必须经程序数值验证才生效；
- 无 SymPy 时全部优雅降级为 unknown。
"""

import logging
import random
import re

logger = logging.getLogger("MathPilot.Deterministic")

try:
    import sympy as sp
    _HAS_SYMPY = True
except ImportError:  # pragma: no cover - 环境缺依赖时的降级路径
    sp = None
    _HAS_SYMPY = False
    logger.warning("SymPy 未安装，确定性验证通道不可用")

# 代入回验的容差（浮点噪声）
_SUBSTITUTION_TOL = 1e-4


def _safe_parse(text: str):
    """安全解析表达式 → SymPy 表达式；失败返回 None（永不抛异常）。

    数学文本常见隐式乘法（"2x"、"(x+1)(x-1)"），sympify 原生不支持，
    这里先做保守的补全（不做 letter( 规则，避免破坏 sin(x)/f(x) 函数调用）。
    """
    if not _HAS_SYMPY or not text or not text.strip():
        return None
    try:
        from utils.sympy_tools import _try_parse
        processed = _fix_implicit_multiplication(text.strip())
        parsed, _err = _try_parse(processed)
        return parsed
    except Exception:  # pragma: no cover - 防御性兜底
        return None


def _fix_implicit_multiplication(text: str) -> str:
    """为 sympify 补全隐式乘法：5x→5*x、2(→2*(、)x→)*x、)(→)*(。

    不做「字母+(」规则——"sin(x)" 会被误改成 "sin*(x)"。
    """
    t = text
    t = re.sub(r"(\d)([a-zA-Zα-ω])", r"\1*\2", t)  # 5x → 5*x
    t = re.sub(r"(\d)\(", r"\1*(", t)              # 2( → 2*(
    t = re.sub(r"\)\s*([a-zA-Zα-ω])", r")*\1", t)  # )x → )*x
    t = re.sub(r"\)\s*\(", r")*(", t)              # )( → )*(
    return t


# 数学主体字符集（用于修剪等式两侧的中文叙述前缀/后缀）
_MATH_CHARS = r"0-9a-zA-Zα-ωΑ-Ω\\\^\(\)\+\-\*/=.,，≤≥<>!%"


def _math_trim(text: str) -> str:
    """去掉表达式两侧的中文叙述（如"解方程："），保留数学主体。"""
    if not text:
        return ""
    t = text.strip()
    m = re.search(rf"[{_MATH_CHARS}]", t)
    if m:
        t = t[m.start():]
    m = re.search(rf"[{_MATH_CHARS}]+$", t)
    if m:
        t = t[:m.end()]
    return t.strip()


class DeterministicChecker:
    """确定性验证通道：纯本地计算，不消耗 LLM 预算、不触发限流。"""

    def __init__(self, samples: int = 100, attempts: int = 200,
                 tol: float = 1e-6, seed: int = 42) -> None:
        """初始化采样/搜索参数与固定随机种子（可复现）。

        Args:
            samples: 代入采样验证的采样组数。
            attempts: 反例搜索的最大尝试次数。
            tol: 数值比较容差。
            seed: 随机种子（同题多次运行结果一致，便于 A/B 复现）。
        """
        self.samples = samples
        self.attempts = attempts
        self.tol = tol
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # 数值化辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _num(expr) -> float | None:
        """把 SymPy 表达式转为 float；NaN/异常返回 None。"""
        if expr is None:
            return None
        try:
            val = float(sp.N(expr))
            if val != val:  # NaN
                return None
            return val
        except Exception:
            return None

    def _sample_value(self, symbol: str, ranges: dict | None = None) -> float:
        """按范围/默认区间采样一个数值。整型变量名（n/m/k/i/j 等）采整数。"""
        if ranges and symbol in ranges:
            lo, hi = ranges[symbol]
            if symbol in _INT_VARIABLES:
                return float(self._rng.randint(int(lo), int(hi)))
            return self._rng.uniform(float(lo), float(hi))
        if symbol in _INT_VARIABLES:
            return float(self._rng.randint(-20, 20))
        return self._rng.uniform(-10.0, 10.0)

    # ------------------------------------------------------------------
    # 1) 代入采样验证
    # ------------------------------------------------------------------
    def verify_by_substitution(self, expr: str, variables: list | None = None,
                               samples: int | None = None,
                               tol: float | None = None) -> dict:
        """对等式/恒等式做代入采样验证。

        支持两种形态：
        - 含 "="：如 "x^2+2x+1=(x+1)^2"——随机采样变量组，核对两侧数值差。
        - 不含 "="：仅验证表达式可解析且数值有限（弱验证）。

        Returns:
            {"verdict": "pass"|"fail"|"unknown", "evidence": str, "passed": int, "total": int}
        """
        samples = samples or self.samples
        tol = tol or self.tol
        if not _HAS_SYMPY or not expr:
            return {"verdict": "unknown", "evidence": "sympy 不可用或表达式为空",
                    "passed": 0, "total": 0}
        try:
            if "=" in expr:
                left_s, right_s = expr.split("=", 1)
                left, right = _safe_parse(left_s), _safe_parse(right_s)
                if left is None or right is None:
                    return {"verdict": "unknown", "evidence": "等式两侧解析失败",
                            "passed": 0, "total": 0}
                symbols = sorted(
                    {str(s) for s in set(left.free_symbols) | set(right.free_symbols)},
                    key=str,
                )
                if not symbols:
                    # 无变量：直接数值核对
                    diff = self._num(sp.simplify(left - right))
                    if diff is None:
                        return {"verdict": "unknown", "evidence": "常量等式计算失败",
                                "passed": 0, "total": 0}
                    ok = abs(diff) <= tol
                    return {"verdict": "pass" if ok else "fail",
                            "evidence": f"常量等式核对: 差={diff:.6g}",
                            "passed": 1 if ok else 0, "total": 1}
                passed, valid = 0, 0
                for _ in range(samples):
                    subs = {sp.Symbol(s): self._sample_value(s) for s in symbols}
                    val = self._num((left - right).subs(subs))
                    if val is None:
                        continue  # 奇点/无定义点跳过
                    valid += 1
                    if abs(val) <= tol:
                        passed += 1
                if valid == 0:
                    return {"verdict": "unknown", "evidence": "全部采样点无定义，无法判定",
                            "passed": 0, "total": 0}
                ratio = passed / valid
                if ratio >= 0.95:
                    verdict = "pass"
                elif ratio <= 0.5:
                    verdict = "fail"
                else:
                    verdict = "unknown"
                return {"verdict": verdict,
                        "evidence": f"代入采样 {passed}/{valid} 组一致 (比值={ratio:.0%})",
                        "passed": passed, "total": valid}
            # 不含 "="：弱验证（可解析 + 数值有限）
            parsed = _safe_parse(expr)
            if parsed is None:
                return {"verdict": "unknown", "evidence": "表达式解析失败",
                        "passed": 0, "total": 0}
            val = self._num(parsed)
            if val is None:
                return {"verdict": "unknown", "evidence": "表达式求值失败",
                        "passed": 0, "total": 0}
            return {"verdict": "pass",
                    "evidence": f"表达式可解析且有限 (≈{val:.6g})",
                    "passed": 1, "total": 1}
        except Exception as e:  # pragma: no cover - 防御性兜底
            return {"verdict": "unknown", "evidence": f"代入采样异常: {str(e)[:80]}",
                    "passed": 0, "total": 0}

    # ------------------------------------------------------------------
    # 2) 反例搜索
    # ------------------------------------------------------------------
    def search_counterexample(self, statement: str, variables: list | None = None,
                              ranges: dict | None = None,
                              attempts: int | None = None) -> dict:
        """对一般性命题（如 "n^2 >= n"）尝试数值反例。

        只对「可解析成 左式 关系符 右式」的命题有效；无法解析 → unknown/未找到。

        **注意：本方法只负责程序化判定，LLM 生成的候选反例必须经本方法验证后才算数。**

        Returns:
            {"found": bool, "counterexample": dict|None, "attempts": int, "statement": str}
        """
        attempts = attempts or self.attempts
        if not _HAS_SYMPY or not statement:
            return {"found": False, "counterexample": None, "attempts": 0,
                    "statement": statement}
        try:
            m = re.match(r"^\s*(.+?)\s*(>=|<=|>|<|=|≠|!=)\s*(.+?)\s*$", statement)
            if not m:
                return {"found": False, "counterexample": None, "attempts": 0,
                        "statement": statement}
            left_s, op, right_s = m.group(1), m.group(2), m.group(3)
            left, right = _safe_parse(left_s), _safe_parse(right_s)
            if left is None or right is None:
                return {"found": False, "counterexample": None, "attempts": 0,
                        "statement": statement}
            symbols = sorted(
                {str(s) for s in set(left.free_symbols) | set(right.free_symbols)},
                key=str,
            )
            if not symbols:
                return {"found": False, "counterexample": None, "attempts": 0,
                        "statement": statement}
            diff = sp.simplify(left - right)
            for _ in range(attempts):
                subs = {sp.Symbol(s): self._sample_value(s, ranges) for s in symbols}
                val = self._num(diff.subs(subs))
                if val is None:
                    continue
                if op in (">=", "≥"):
                    violated = val < -self.tol
                elif op in ("<=", "≤"):
                    violated = val > self.tol
                elif op == ">":
                    violated = val <= self.tol
                elif op == "<":
                    violated = val >= -self.tol
                elif op in ("≠", "!="):
                    violated = abs(val) <= self.tol
                else:  # "="
                    violated = abs(val) > self.tol
                if violated:
                    return {"found": True,
                            "counterexample": {k: float(v) for k, v in subs.items()},
                            "attempts": attempts, "statement": statement}
            return {"found": False, "counterexample": None, "attempts": attempts,
                    "statement": statement}
        except Exception as e:  # pragma: no cover - 防御性兜底
            return {"found": False, "counterexample": None, "attempts": 0,
                    "statement": statement, "error": str(e)[:80]}

    # ------------------------------------------------------------------
    # 3) 数值回溯
    # ------------------------------------------------------------------
    def numerical_backtrack(self, answer: str) -> str | None:
        """数值回溯：把可解析的答案转为数值串（用于一致性旁证）。失败返回 None。"""
        parsed = _safe_parse(answer)
        if parsed is None:
            return None
        val = self._num(parsed)
        if val is None:
            return None
        return f"{val:.10g}"

    # ------------------------------------------------------------------
    # 4) 高层入口：综合旁证 / 硬否决
    # ------------------------------------------------------------------
    def check_answer(self, ctx, problem: str, answer: str,
                     domain: str | None = None) -> dict:
        """对单个候选答案做确定性旁证/硬否决。

        Args:
            ctx: TaskContext（仅保留参数兼容，可传 None）。
            problem: 题目文本。
            answer: 候选最终答案。
            domain: 领域（预留，暂未使用）。

        Returns:
            {"verdict": "pass"|"fail"|"unknown", "confidence": float,
             "evidence": str, "method": str}
        """
        if not _HAS_SYMPY:
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": "sympy 不可用", "method": "none"}
        if not answer or not answer.strip():
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": "答案为空", "method": "none"}
        answer = answer.strip()
        evidence_parts = []
        # 1) 答案可解析性 + 数值回溯
        parsed = _safe_parse(answer)
        if parsed is None:
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": f"答案无法解析为表达式: {answer[:80]}",
                    "method": "parse"}
        val = self._num(parsed)
        if val is not None:
            evidence_parts.append(f"数值≈{val:.6g}")
        # 2) 题目含「一侧为常量」的等式 → 代入回验
        eq = self._extract_constant_equation(problem)
        if eq is not None:
            check = self._verify_answer_in_equation(eq, answer)
            if check.get("verdict") != "unknown":
                check["confidence"] = check.get("confidence", 1.0)
                return check
            evidence_parts.append(check.get("evidence", ""))
        # 3) 无法进一步验证 → unknown（附可解析证据）
        evidence = "；".join(p for p in evidence_parts if p)
        return {"verdict": "unknown", "confidence": 0.0,
                "evidence": evidence or "答案可解析但无等式可代入",
                "method": "parse_only"}

    # ------------------------------------------------------------------
    # 内部：等式提取与代入回验
    # ------------------------------------------------------------------
    def _extract_constant_equation(self, problem: str) -> str | None:
        """从题目中提取最后一个「一侧为纯常量」的可解析等式（保守策略）。

        只返回一侧无自由符号的等式——例如 "x^2-5x+6=0"（右侧为常量 0）。
        定义式（如 "f(x)=x^2-5x+6"）两侧都含变量 → 跳过，防止把求值题误杀。
        """
        if not problem or not _HAS_SYMPY:
            return None
        try:
            segments = re.split(r"[，。；;\n]", problem)
            candidates = [s.strip() for s in segments if "=" in s]
            for seg in reversed(candidates):
                if seg.count("=") != 1:
                    continue
                left_s, right_s = seg.split("=", 1)
                left = _safe_parse(_math_trim(left_s))
                right = _safe_parse(_math_trim(right_s))
                if left is None or right is None:
                    continue
                left_free = list(left.free_symbols)
                right_free = list(right.free_symbols)
                if not left_free and len(right_free) == 1:
                    return seg
                if not right_free and len(left_free) == 1:
                    return seg
            return None
        except Exception:  # pragma: no cover - 防御性兜底
            return None

    def _verify_answer_in_equation(self, equation: str, answer: str) -> dict:
        """把答案代入等式验证：|LHS-RHS| ≈ 0 → pass；明显不为 0 → fail。"""
        try:
            left_s, right_s = equation.split("=", 1)
            left = _safe_parse(_math_trim(left_s))
            right = _safe_parse(_math_trim(right_s))
            if left is None or right is None:
                return {"verdict": "unknown", "evidence": "等式解析失败",
                        "method": "substitution"}
            free = list(set(left.free_symbols) | set(right.free_symbols))
            if len(free) != 1:
                return {"verdict": "unknown", "evidence": "等式含多变量，跳过代入",
                        "method": "substitution"}
            var = free[0]
            ans_expr = _safe_parse(answer)
            if ans_expr is None:
                return {"verdict": "unknown", "evidence": "答案不可解析",
                        "method": "substitution"}
            diff = sp.simplify(left - right)
            # 答案本身含变量（如 x=2 之外的表达式）→ 尝试符号验证
            if any(s in list(ans_expr.free_symbols) for s in free):
                try:
                    if sp.simplify(diff.subs(var, ans_expr)) == 0:
                        return {"verdict": "pass",
                                "evidence": f"符号代入验证通过: {var}={answer}",
                                "method": "substitution"}
                except Exception:
                    pass
                return {"verdict": "unknown", "evidence": "答案含变量，无法数值代入",
                        "method": "substitution"}
            val = self._num(diff.subs(var, ans_expr))
            if val is None:
                return {"verdict": "unknown", "evidence": "代入数值计算失败",
                        "method": "substitution"}
            if abs(val) <= _SUBSTITUTION_TOL:
                return {"verdict": "pass",
                        "evidence": f"代入验证通过: {equation}，{var}={answer} → 差≈{val:.2e}",
                        "method": "substitution"}
            return {"verdict": "fail",
                    "evidence": f"代入验证失败: {equation}，{var}={answer} → 差={val:.4g}",
                    "method": "substitution"}
        except Exception as e:  # pragma: no cover - 防御性兜底
            return {"verdict": "unknown", "evidence": f"代入验证异常: {str(e)[:80]}",
                    "method": "substitution"}


# 常见整型变量名（采样时采整数，贴近数论/组合题语境）
_INT_VARIABLES: frozenset = frozenset({"n", "m", "k", "i", "j", "p", "q"})
