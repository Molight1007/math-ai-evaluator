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
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Optional, Iterator

logger = logging.getLogger("MathPilot")


# ============================================================
# 响应归一化（P0-1 契约防线）
# ============================================================
def _normalize_chat_response(resp) -> Optional[str]:
    """把 client.chat 的返回值统一成字符串。

    平台注入的 client 实现不定，常见返回形态：
      - str: 直接可用
      - dict: {"content": "...", "choices": [...], "message": {...}}
      - list: [{"content": "..."}, ...]
      - 对象: .content / .text / .message.content
      - bytes: 解码为 UTF-8
      - None / 异常: 返回 ""
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, bytes):
        try:
            return resp.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if isinstance(resp, list):
        for item in resp:
            text = _normalize_chat_response(item)
            if text:
                return text
        return ""
    if isinstance(resp, dict):
        for key in ("content", "text", "output", "result"):
            if key in resp and resp[key] is not None:
                val = resp[key]
                if isinstance(val, str):
                    return val
                return _normalize_chat_response(val)
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            choice = resp["choices"][0]
            if isinstance(choice, dict):
                if "message" in choice and isinstance(choice["message"], dict):
                    msg = choice["message"]
                    for key in ("content", "text"):
                        if key in msg and msg[key] is not None:
                            return str(msg[key])
                if "text" in choice and choice["text"] is not None:
                    return str(choice["text"])
            return _normalize_chat_response(choice)
        if "message" in resp and isinstance(resp["message"], dict):
            msg = resp["message"]
            for key in ("content", "text"):
                if key in msg and msg[key] is not None:
                    return str(msg[key])
        if "data" in resp:
            return _normalize_chat_response(resp["data"])
        return ""
    # 普通对象：尝试 .content / .text / .message
    for attr in ("content", "text", "response"):
        try:
            val = getattr(resp, attr, None)
            if val is not None:
                return _normalize_chat_response(val)
        except Exception:
            pass
    try:
        if hasattr(resp, "message") and resp.message is not None:
            return _normalize_chat_response(resp.message)
    except Exception:
        pass
    try:
        s = str(resp)
        if s and s != "None" and not s.startswith("<") and not s.startswith("{"):
            return s
    except Exception:
        pass
    return ""


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
    id: int = 0
    answer: str = ""
    reasoning: str = ""
    confidence: float = 0.0     # 置信度 = 正确票数 / 总票数
    correct_votes: int = 0
    total_votes: int = 0
    feedback: str = ""          # 失败时由验证器提取的错误原因
    correct: bool = False       # 本次投票结果是否正确（verifier 使用）
    raw: str = ""               # 原始投票返回文本（verifier 使用）
    score: dict | None = None   # 评分模式的详细分数（verifier 使用）


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

    def set_max_calls(self, new_max: int) -> None:
        """动态调整总调用预算（deep 档位需要更多预算时调用）。"""
        with self._lock:
            self.max_calls = max(self.used_calls, new_max)


# ------------------------------------------------------------
# P3：Finding / BugReport（step 级分级验证报告）
# 供 agent/lean_bridge.py（Lean 形式化验证桥接层）使用。
# ------------------------------------------------------------
@dataclass
class Finding:
    """单个步骤级缺陷（P3）"""
    location: str = ""     # 出错位置（步骤编号/行号/引用）
    kind: str = "Gap"      # Critical（致命）| Gap（缺口/瑕疵）
    severity: int = 0       # 严重度 1-5（5 最严重）
    desc: str = ""         # 缺陷描述


@dataclass
class BugReport:
    """步骤级验证报告（P3 一等公民）

    契约：
      - ``findings``：list[Finding]，含 location / kind(Critical|Gap) / severity / desc；
      - ``verdict``：'proof_valid' | 'proof_invalid' | 'unknown'；
      - ``is_valid()`` / ``has_critical()``；
      - ``to_dict()`` / ``to_json()`` / ``from_dict()``：JSON 可序列化（P6 要求）。
    """
    findings: list = field(default_factory=list)  # list[Finding]
    verdict: str = "unknown"
    # 改造2：可修复性判定（yes/no/partial）+ 修正建议（可选字段，向后兼容）
    repairable: str = ""       # 'yes' | 'no' | 'partial'（空=未判定）
    suggestion: str = ""       # 修正建议文本（空=无）

    def is_valid(self) -> bool:
        return self.verdict == "proof_valid"

    def has_critical(self) -> bool:
        return any(f.kind == "Critical" for f in self.findings)

    def to_dict(self) -> dict:
        d = {
            "findings": [
                {"location": f.location, "kind": f.kind,
                 "severity": f.severity, "desc": f.desc}
                for f in self.findings
            ],
            "verdict": self.verdict,
        }
        # 可选字段仅在非空时序列化，保持旧 JSON 契约兼容
        if self.repairable:
            d["repairable"] = self.repairable
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "BugReport":
        d = d or {}
        findings = [
            Finding(location=f.get("location", ""), kind=f.get("kind", "Gap"),
                    severity=int(f.get("severity", 0)), desc=f.get("desc", ""))
            for f in (d.get("findings", []) or [])
        ]
        return cls(findings=findings, verdict=d.get("verdict", "unknown"),
                   repairable=d.get("repairable", "") or "",
                   suggestion=d.get("suggestion", "") or "")


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
    # ---- Lean 硬验证门禁字段（v2.5+LeanBridge）----
    lean_gate: list = field(default_factory=list)       # 每候选 Lean 验证诊断记录
    lean_reject_feedback: list = field(default_factory=list)  # 被 Lean 淘汰候选的反馈（供 revise）

    # ---- 难题深度求解通道字段 ----
    tier: str = "standard"                      # fast / standard / deep（DifficultyRouter 写入）
    tier_evidence: dict = field(default_factory=dict)  # 档位判定依据（静态分/LLM分/融合说明）
    soft_budget: float = 0.0                    # PaperPacer 分配的当前档位软预算帽（秒）
    pacer_remaining: float = 0.0                # 全卷时间池剩余目标时间（秒，诊断用）

    # ---- 壁钟时间追踪（适配竞赛新规则：单题≤20分钟，总计≤6小时）----
    start_time: float = 0.0                    # 单题壁钟启动时间 (time.time())
    deadline: float = 0.0                      # 单题绝对截止时间戳
    total_start_time: float = 0.0              # Agent总启动时间
    total_deadline: float = 0.0                # Agent总截止时间戳

    def verified_ids(self) -> set:
        """已验证过的候选 id 集合（避免重复验证）"""
        return {v.id for v in self.verdicts}

    # ---- 时间检查方法（适配竞赛新规则）----
    def time_remaining(self) -> float:
        """返回当前题目剩余壁钟时间（秒），负值=已超时"""
        if self.deadline == 0.0:
            return float("inf")
        import time
        return self.deadline - time.time()

    def is_time_critical(self) -> bool:
        """距当前题目超时不足2分钟 → 跳过所有可选步骤"""
        return self.time_remaining() < 120.0

    def is_timed_out(self) -> bool:
        """当前题目是否已超时"""
        return self.time_remaining() <= 0.0

    def total_time_remaining(self) -> float:
        """返回Agent总剩余时间（秒）"""
        if self.total_deadline == 0.0:
            return float("inf")
        import time
        return self.total_deadline - time.time()

    def is_total_timed_out(self) -> bool:
        """Agent总时间是否已用尽"""
        return self.total_time_remaining() <= 0.0


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
        P0-4 修复：新增时间预算感知——剩余不足时跳过/降级，杜绝单题超时（45 error 主因）。
        """
        # 时间预算感知：剩余 < 60s 直接跳过调用（保证有产出优于无产出）
        # 修复：区分「未设置 deadline / 测试 fixture 伪 deadline」与「真实 deadline 已过期」。
        #   - deadline < 1e8（epoch 伪值，如测试 fixture 的 999.0）→ 不启用预算（兼容测试）
        #   - 真实时间戳但已过期 → remaining <= 0 → 跳过，杜绝无界超时重试（45 error/2923s 根因）
        if ctx.deadline:
            if ctx.deadline < 10**8:
                remaining = float("inf")   # 测试 fixture 用 epoch 伪 deadline
            else:
                remaining = ctx.deadline - time.time()
        else:
            remaining = float("inf")
        if remaining < 60:
            logger.warning("[%s] 剩余时间不足 (%.0fs)，跳过 LLM 调用", self.name, remaining)
            ctx.trace.append({"agent": self.name, "step": "budget_skip",
                              "content": f"剩余时间不足 {remaining:.0f}s，跳过 LLM 调用"})
            return None
        # 剩余 < 120s：自动减半 max_tokens，缩短单次调用耗时
        if remaining < 120 and max_tokens and max_tokens > 1024:
            logger.warning("[%s] 剩余时间紧张 (%.0fs)，max_tokens %d → %d",
                           self.name, remaining, max_tokens, max_tokens // 2)
            max_tokens = max(1024, max_tokens // 2)

        # Token 裁剪到安全上限（可配置，默认 4096）
        cap = getattr(self.config, 'max_tokens_cap', 4096)
        if cap and max_tokens:
            max_tokens = min(max_tokens, cap)

        reserved = False
        if ctx.budget is not None:
            with ctx.budget._lock:
                if not ctx.budget.can_spend(1):
                    logger.warning("[%s] 预算耗尽 (剩余 %d)，跳过 LLM 调用", 
                                   self.name, ctx.budget.remaining())
                    return None
                ctx.budget.spend(1)
                reserved = True
        try:
            resp = self.client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            resp = _normalize_chat_response(resp)
            # 诊断：返回空值时记录
            if not resp or not resp.strip():
                logger.warning("[%s] LLM 返回空响应 (len=%d, type=%s)",
                               self.name, len(resp) if resp else 0, type(resp).__name__)
            return resp
        except TypeError:
            # 平台 client 仅接受 positional args → 降级
            logger.warning("[%s] TypeError in chat() kwargs, fallback to positional", self.name)
            try:
                resp2 = self.client.chat(messages)
                resp2 = _normalize_chat_response(resp2)
                if not resp2 or not resp2.strip():
                    logger.warning("[%s] LLM fallback 返回空响应", self.name)
                return resp2
            except Exception as e2:
                logger.warning("[%s] LLM fallback 也失败: %s", self.name, e2)
        except Exception as e:  # noqa: BLE001
            err_str = str(e)[:200]
            if any(kw in err_str.lower() for kw in ('context length', 'too long', 'max token')):
                reduced = (max_tokens // 2) if max_tokens > 512 else 256
                logger.warning("[%s] 上下文超长，降至 %s tokens 重试", self.name, reduced)
                try:
                    resp3 = self.client.chat(messages=messages, temperature=0.0, max_tokens=reduced)
                    return _normalize_chat_response(resp3)
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
# 模板泄露检测（借鉴 math_agent-main 的成功经验）
# Intern-S 模型常会输出 prompt 模板描述而非实际解答，这是致命问题。
# ============================================================
_TEMPLATE_LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r'(?i)Strategy Planning\)?.*specific to this problem'),
    re.compile(r'(?i)Key Insight\)?.*specific to this problem'),
    re.compile(r'(?i)Heuristic Summary\)?.*specific to this problem'),
    re.compile(r'(?i)<Specific mathematical conclusion'),
    re.compile(r'(?i)<Final Answer only'),
    re.compile(r'(?i)1-2 sentences analyzing core'),
    re.compile(r'(?i)1 sentence highlighting the key'),
    re.compile(r'(?i)1-2 sentences explaining broader'),
    re.compile(r'(?i)必须针对本题具体内容.*不要泛泛而谈'),
    re.compile(r'(?i)用1-2句话分析'),
    re.compile(r'(?i)用1句话点出'),
    re.compile(r'(?i)用1-2句话说明'),
    re.compile(r'(?i)解题步骤（摘要）.*Make sure'),
    re.compile(r'你是一位.{1,30}(?:专家|助手|模型)', re.IGNORECASE),
    re.compile(r'请按照.{1,30}格式', re.IGNORECASE),
    re.compile(r'SYSTEM_PROMPT|TEMPLATE_CONTENT'),
]


def detect_template_leak(text: str) -> bool:
    """检测模型是否输出了 prompt 模板描述而非真正解答。"""
    if not text or len(text.strip()) < 20:
        return False
    leak_count = sum(1 for p in _TEMPLATE_LEAK_PATTERNS if p.search(text))
    if leak_count >= 2:
        return True
    # 检测 ANSWER: 后面跟的是模板占位符
    m = re.search(r'(?:ANSWER|答案|最终答案)\s*[：:]\s*(.+)', text, re.IGNORECASE)
    if m:
        ans_text = m.group(1).strip()
        if re.search(r'(?i)<[^>]*(?:Specific|Final Answer|具体数学结论|最终答案)[^>]*>', ans_text):
            return True
        if re.search(r'(?i)(?:must include|no more than|only.*no reasoning)', ans_text):
            return True
    return False
