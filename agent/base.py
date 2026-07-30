from __future__ import annotations
"""
多智能体基础组件
================

提供：
- ``Candidate`` / ``Verdict``：候选解答与验证结果的数据结构
- ``Budget``：LLM 调用预算（防止竞赛平台超时 / 超额）
- ``TaskContext``：共享黑板（Blackboard），所有 Agent 读写同一上下文，全程可追溯
- ``BaseAgent``：抽象基类，统一封装 LLM 安全调用、预算扣减、trace 记录
"""

import logging
import re
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Optional, Iterator

logger = logging.getLogger("MathPilot")


# ============================================================
# 数据结构
# ============================================================
@dataclass
class Candidate:
    """一个候选解答"""
    id: int
    answer: str                 # 提取出的简洁最终答案
    reasoning: str              # 完整推理过程（含文本）
    revised: bool = False       # 是否由自纠错回环产生


@dataclass
class Verdict:
    """一个候选解答的验证结果"""
    id: int
    answer: str
    reasoning: str
    confidence: float           # 置信度 = 正确票数 / 总票数
    correct_votes: int
    total_votes: int
    feedback: str = ""          # 失败时由验证器提取的错误原因


@dataclass
class Budget:
    """LLM 调用预算控制器（线程安全）"""
    max_calls: int
    used_calls: int = 0
    _lock: RLock = field(default_factory=RLock, repr=False)

    def can_spend(self, n: int = 1) -> bool:
        """是否还有余额"""
        with self._lock:
            return self.used_calls + n <= self.max_calls

    def spend(self, n: int = 1) -> None:
        with self._lock:
            self.used_calls += n

    def refund(self, n: int = 1) -> None:
        """调用失败/异常时回退预算"""
        with self._lock:
            self.used_calls = max(0, self.used_calls - n)

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_calls - self.used_calls)


@dataclass
class TaskContext:
    """黑板：所有 Agent 共享的推理上下文"""
    problem: str
    metadata: dict
    domain: Optional[str] = None               # ClassifierAgent 写入
    candidates: list = field(default_factory=list)   # SolverAgent 写入
    verdicts: list = field(default_factory=list)     # VerifierAgent 写入
    revise_feedback: list = field(default_factory=list)  # 回传给 Solver 的错误原因
    trace: list = field(default_factory=list)        # 全程决策轨迹
    budget: Optional[Budget] = None            # 预算控制器
    revise_round: int = 0                       # 已触发的自纠错轮数
    final_response: str = ""
    lemma_repo: list[str] = field(default_factory=list)  # 已验证的子结论（引理积累）

    def verified_ids(self) -> set:
        """已验证过的候选 id 集合（避免重复验证）"""
        return {v.id for v in self.verdicts}


# ============================================================
# Agent 抽象基类
# ============================================================
class BaseAgent(ABC):
    """所有智能体的基类"""

    name: str = "base"

    def __init__(self, client, config):
        self.client = client
        self.config = config

    @abstractmethod
    def run(self, ctx: TaskContext) -> TaskContext:
        """处理上下文并返回（可能更新的）上下文"""
        ...

    # ----------------------------------------------------------
    # 通用能力：trace 记录 + 带预算管控的安全 LLM 调用
    # ----------------------------------------------------------
    def record(self, ctx: TaskContext, step: str, content: str, **extra) -> None:
        """向 trace 追加一条决策记录"""
        entry = {"agent": self.name, "step": step, "content": content}
        if extra:
            entry.update(extra)
        ctx.trace.append(entry)

    def llm(self, ctx: TaskContext, messages: list, temperature: float,
            max_tokens: int) -> Optional[str]:
        """
        带预算管控、Token 裁剪、自动重试的安全 LLM 调用（支持并发线程）。
        修复 BUG-6：追加 max_tokens 裁剪、上下文超长自动降级重试、异常写入 trace。
        """
        # Token 裁剪到安全上限（可配置，默认 4096）
        cap = getattr(self.config, 'max_tokens_cap', 4096)
        if cap and max_tokens:
            max_tokens = min(max_tokens, cap)

        reserved = False
        if ctx.budget is not None:
            with ctx.budget._lock:
                if not ctx.budget.can_spend(1):
                    logger.debug("[%s] Budget exhausted, skip LLM call", self.name)
                    return None
                ctx.budget.spend(1)
                reserved = True
        try:
            resp = self.client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp
        except TypeError:
            # 平台 client 仅接受 positional args → 降级
            try:
                return self.client.chat(messages)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            err_str = str(e)[:200]
            if any(kw in err_str.lower() for kw in ('context length', 'too long', 'max token')):
                reduced = (max_tokens // 2) if max_tokens > 512 else 256
                logger.warning("[%s] 上下文超长，降至 %s tokens 重试", self.name, reduced)
                try:
                    return self.client.chat(messages=messages, temperature=0.0, max_tokens=reduced)
                except Exception:
                    pass
            if reserved and ctx.budget is not None:
                ctx.budget.refund(1)
            ctx.trace.append({"agent": self.name, "step": "llm_error",
                              "content": f"LLM 调用失败: {err_str}"})
            logger.warning("[%s] LLM call failed: %s", self.name, e)
            return None


# ============================================================
# 安全防护工具
# ============================================================

class TimeoutError(Exception):
    """wall-clock 超时异常"""


@contextmanager
def wall_clock_timeout(seconds: float, label: str = "") -> Iterator[None]:
    """
    wall-clock 超时上下文管理器。

    在 Windows 上使用 threading.Timer 实现（signal.alarm 不可用），
    超时时会终止当前线程内的阻塞调用。

    用法::

        try:
            with wall_clock_timeout(30, "Solver"):
                resp = client.chat(...)
        except TimeoutError:
            # 超时处理
    """
    timer = [None]  # mutable 闭包

    def _raise():
        import _thread
        _thread.interrupt_main()

    if seconds <= 0:
        yield  # 不限制
        return

    try:
        timer[0] = threading.Timer(seconds, _raise)
        timer[0].daemon = True
        timer[0].start()
        yield
    except KeyboardInterrupt:
        raise TimeoutError(f"{label} timed out after {seconds}s")
    finally:
        if timer[0] is not None:
            timer[0].cancel()


# 模型常见幻觉模式
_HALLUCINATION_PATTERNS = [
    # 孤立的 42/42.0 作为答案（避免误匹配 142、42x 等）
    (re.compile(r"(?:^|(?<=\s))42(?:\.0+)?\s*(?:[，,。.\n]|$)", re.MULTILINE),
     "42 魔法数字兜底"),
    (re.compile(r"I am (?:sorry|unable).*?(?:\n|$)", re.IGNORECASE),
     "英文拒绝回答"),
    (re.compile(r"as an AI.*?(?:\n|$)", re.IGNORECASE),
     "AI 身份声明"),
    (re.compile(r"我(?:无法|不能|没办法|不擅长).{0,20}(?:解|答|计算)", re.IGNORECASE),
     "中文拒绝回答"),
    (re.compile(r"根据.{0,10}安全.{0,10}政策", re.IGNORECASE),
     "安全策略拒绝"),
]


def detect_hallucination(text: str) -> list[tuple[str, float]]:
    """
    检测 LLM 输出中的已知幻觉模式。

    返回: [(模式名, 置信度), ...]，空列表表示无检测。
    """
    if not text:
        return [("空响应", 1.0)]
    findings = []
    for pattern, label in _HALLUCINATION_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            # 置信度基于匹配次数（但不超过 0.9）
            confidence = min(0.5 + 0.15 * len(matches), 0.9)
            findings.append((label, confidence))
    return findings


def detect_truncated(text: str) -> bool:
    """
    检测 LLM 输出是否被 max_tokens 截断（代码/LaTeX 不完整）。

    检测规则:
    - 以不闭合的 LaTeX 环境结尾（\\begin 无 \\end）
    - 以不闭合的 markdown 代码块结尾
    - 以不闭合的大括号/中括号/括号结尾
    - 以行内 $$ 无闭合结尾
    """
    if not text:
        return False
    stripped = text.rstrip()
    # 未闭合 LaTeX 环境
    begins = len(re.findall(r"\\begin\{([^}]+)\}", stripped))
    ends = len(re.findall(r"\\end\{([^}]+)\}", stripped))
    if begins > ends:
        return True
    # 未闭合的代码块
    code_fences = len(re.findall(r"^```", stripped, re.MULTILINE))
    if code_fences % 2 == 1:
        return True
    # 未闭合的括号（排除 LaTeX 转义的 \{ \}）
    bracket_pairs = {"{": "}", "[": "]", "(": ")"}
    stack: list[str] = []
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        # 跳过转义字符（如 \{, \}）
        if ch == "\\" and i + 1 < len(stripped) and stripped[i + 1] in ("{", "}", "[", "]", "(", ")"):
            i += 2
            continue
        if ch in bracket_pairs:
            stack.append(bracket_pairs[ch])
        elif ch in bracket_pairs.values():
            if stack and stack[-1] == ch:
                stack.pop()
        i += 1
    if stack:
        return True
    # 未闭合的 $ 标记（$$ 算作双美元符号，检查偶数对）
    # 移除转义后的 $ 计数
    dollar_count = len(re.findall(r"(?<!\\)\$", stripped))
    if dollar_count % 2 == 1:
        return True
    return False


# ============================================================
# Intern-S1 思考链污染检测（英文 thinking chain 污染）
# ============================================================
# 当使用 Intern-S1 等模型的 thinking_mode 时，英文思考链可能污染中文答案。
# 参考 math_agent-main 的 ENGLISH_THINK_PATTERNS。

_ENGLISH_THINK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"<\|im_start\|>assistant", re.IGNORECASE), "特殊 token 泄露"),
    (re.compile(r"Please respond (in|with)\s", re.IGNORECASE), "英文指令残留"),
    (re.compile(r"Sure[,!]?\s+I.*?(?:\n|$)", re.IGNORECASE), "英文肯定前缀"),
    (re.compile(r"(I think|Let me|First,? let me|Now I will)", re.IGNORECASE), "英文自言自语"),
    (re.compile(r"Here[\'']s the solution:", re.IGNORECASE), "英文解题标记"),
    (re.compile(r"(User:|Assistant:|System:)\s", re.IGNORECASE), "角色标记泄露"),
]


def detect_thinking_contamination(text: str) -> list[str]:
    """检测英文思考链是否污染了中文输出。返回命中的标签列表。"""
    if not text:
        return []
    found: list[str] = []
    for pattern, label in _ENGLISH_THINK_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found


# ============================================================
# 模板泄露检测
# ============================================================
_TEMPLATE_LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"你是一位.{1,30}(?:专家|助手|模型)", re.IGNORECASE),
    re.compile(r"请按照.{1,30}格式", re.IGNORECASE),
    re.compile(r"system role.{0,20}content", re.IGNORECASE),
    re.compile(r"SYSTEM_PROMPT|TEMPLATE_CONTENT", re.IGNORECASE),
]


def detect_template_leak(text: str) -> bool:
    """检测模型是否输出了 prompt 模板而非真正解答。"""
    for pattern in _TEMPLATE_LEAK_PATTERNS:
        if pattern.search(text):
            return True
    return False
