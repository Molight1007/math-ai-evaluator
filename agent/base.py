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

import json
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
    deterministic: dict | None = None  # 确定性验证旁证（verifier 使用，0 LLM 预算）


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
class RunState:
    """运行期可变状态（与不可变 RunConfig 解耦）

    B6（god-config 不可变）：PaperPacer 等运行时调控不得改写共享 config，
    统一把"生效覆盖值"写入本对象，各 Agent 通过 ``ctx.state`` 读取，
    从而消除 orchestrator 早期对 ``self.config`` 的运行时改写（状态不安全）。
    """
    emergency: bool = False            # 应急模式：候选/投票降至 1，跳过续写/复算
    playoff_enabled: bool = False      # 是否启用 playoff 确定性复算
    voting_times: Optional[int] = None  # 生效投票数（None=用 config 默认）
    sample_times: Optional[int] = None  # 生效采样数（None=用 config 默认）


class RunConfig:
    """不可变配置快照（B6 / god-config 落地）

    构造时从用户传入的 dataclass config 拷贝一份只读快照，运行期任何写属性
    操作都会抛 ``AttributeError``，杜绝 orchestrator / solver / verifier 在
    运行时改写共享配置导致的跨 Agent 状态污染。

    运行时需要覆盖的值请写入 ``ctx.state``（RunState），由各 Agent 在读取处
    做"生效覆盖"判断。
    """
    def __init__(self, config):
        # 浅拷贝快照：config 为 dataclass，字段均为值类型/不可变容器，浅拷贝即隔离
        object.__setattr__(self, "_store", dict(vars(config)))
        object.__setattr__(self, "_locked", True)

    def __getattr__(self, name: str):
        try:
            return object.__getattribute__(self, "_store")[name]
        except KeyError:
            raise AttributeError(
                f"RunConfig 无字段 '{name}'（请确认已在 config dataclass 定义）")

    def __setattr__(self, name: str, value):
        if object.__getattribute__(self, "_locked"):
            raise AttributeError(
                f"RunConfig 不可变：禁止运行时改写 '{name}'（请改用 ctx.state）")
        object.__setattr__(self, name, value)

    def __getitem__(self, name: str):
        """兼容 config['key'] 式访问。"""
        return self._store[name]


# ============================================================
# 接口契约（P2-P7，由求解工程师起草，供 QA 按契约写测试）
# ============================================================

# ------------------------------------------------------------
# P2：LemmaEntry / LemmaRepo（引理库）
# ------------------------------------------------------------
@dataclass
class LemmaEntry:
    """一条已验证引理（结构化条目，P2）

    用于跨题/跨轮复用已验证的中间结论，减少重复推理。
    """
    text: str                     # 引理内容
    source_problem: str = ""      # 来源题目
    verified: bool = True         # 是否经 Verifier 验证通过
    created_round: int = 0        # 创建时的自纠错轮次
    usage_count: int = 0          # 被复用的次数
    created_at: float = 0.0       # 创建时间戳


class LemmaRepo:
    """线程安全的引理库（P2）

    支持增删查，可存结构化条目（LemmaEntry），供 Solver / Summarizer 复用。
    契约：
      - ``add(lemma, **meta) -> bool``：追加并去重，返回是否新加入；
      - ``query(problem, limit) -> list[str]``：按关键词相关度检索可复用引理；
      - ``remove(text) -> bool``：删除指定引理；
      - ``__len__`` / ``to_list()``：遍历。
    线程安全：内部用 RLock 保证并发增查不冲突。
    """
    def __init__(self, max_entries: int = 500):
        self._entries: list[LemmaEntry] = []
        self._lock = RLock()
        self._max_entries = max_entries

    def add(self, lemma: str, **meta) -> bool:
        """追加一条引理，去重后返回是否真正新增。"""
        if not lemma or not lemma.strip():
            return False
        with self._lock:
            for e in self._entries:
                if e.text == lemma:
                    return False
            entry = LemmaEntry(text=lemma, created_at=time.time(), **meta)
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries.pop(0)
            return True

    def query(self, problem: str = "", limit: int = 5) -> list[str]:
        """按关键词相关度检索可复用引理，返回引理文本列表。

        简单打分：与题目词共现越多越靠前；无题目时按时间倒序返回最近。
        """
        with self._lock:
            if not problem:
                return [e.text for e in self._entries[-limit:]]
            scored = [(self._score(problem, e), e) for e in self._entries]
            scored.sort(key=lambda x: (-x[0], x[1].created_at), reverse=False)
            return [e.text for _, e in scored[:limit]]

    def remove(self, text: str) -> bool:
        """删除指定引理，成功返回 True。"""
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.text == text:
                    self._entries.pop(i)
                    return True
            return False

    def to_list(self) -> list[str]:
        """返回全部引理文本（按加入顺序）。"""
        with self._lock:
            return [e.text for e in self._entries]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __iter__(self):
        with self._lock:
            return iter(list(self._entries))

    @staticmethod
    def _tokenize(text: str) -> set:
        """把文本切分为小写 token 集合（中文按字、英文按词）。"""
        words = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
        # 中文：提取连续汉字簇
        for ch in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            words.add(ch)
        return words

    @classmethod
    def _score(cls, problem: str, entry: LemmaEntry) -> int:
        """引理与题目的关键词共现打分。"""
        p_tokens = cls._tokenize(problem)
        e_tokens = cls._tokenize(entry.text)
        if not p_tokens or not e_tokens:
            return 0
        return len(p_tokens & e_tokens)


# ------------------------------------------------------------
# P3：Finding / BugReport（step 级分级验证报告）
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

    def is_valid(self) -> bool:
        return self.verdict == "proof_valid"

    def has_critical(self) -> bool:
        return any(f.kind == "Critical" for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "findings": [
                {"location": f.location, "kind": f.kind,
                 "severity": f.severity, "desc": f.desc}
                for f in self.findings
            ],
            "verdict": self.verdict,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "BugReport":
        d = d or {}
        findings = [
            Finding(location=f.get("location", ""), kind=f.get("kind", "Gap"),
                    severity=int(f.get("severity", 0)), desc=f.get("desc", ""))
            for f in d.get("findings", []) or []
        ]
        return cls(findings=findings, verdict=d.get("verdict", "unknown"))


# ------------------------------------------------------------
# P4：RoundState（AcceptGate 门控状态）
# ------------------------------------------------------------
@dataclass
class RoundState:
    """AcceptGate 门控状态（P4）

    契约：
      - 连续通过 >= 5 → ACCEPT；
      - 连续重大缺陷 >= 10 → REJECT；
      - 复位逻辑：一次失败复位 pass 计数，一次通过复位 major_defect 计数；
      - ``update(is_pass, has_major_defect) -> str`` 返回最新 decision。
    """
    consecutive_pass: int = 0
    consecutive_major_defect: int = 0
    decision: str = "HOLD"     # HOLD | ACCEPT | REJECT
    rounds: int = 0

    ACCEPT_PASS_THRESHOLD = 5       # 连续通过阈值
    REJECT_DEFECT_THRESHOLD = 10    # 连续重大缺陷阈值

    def update(self, is_pass: bool, has_major_defect: bool = False) -> str:
        """按一轮结果更新门控，返回最新 decision。"""
        self.rounds += 1
        if is_pass:
            self.consecutive_pass += 1
            self.consecutive_major_defect = 0   # 通过即复位缺陷计数
        else:
            self.consecutive_pass = 0            # 失败即复位通过计数
            if has_major_defect:
                self.consecutive_major_defect += 1
        if self.consecutive_pass >= self.ACCEPT_PASS_THRESHOLD:
            self.decision = "ACCEPT"
        elif self.consecutive_major_defect >= self.REJECT_DEFECT_THRESHOLD:
            self.decision = "REJECT"
        else:
            self.decision = "HOLD"
        return self.decision

    def to_dict(self) -> dict:
        return {
            "consecutive_pass": self.consecutive_pass,
            "consecutive_major_defect": self.consecutive_major_defect,
            "decision": self.decision,
            "rounds": self.rounds,
        }


# ------------------------------------------------------------
# P6：Artifact（结构化上下文产物）
# ------------------------------------------------------------
@dataclass
class Artifact:
    """结构化上下文产物（P6）

    把 ``_candidate_text()`` / ``VERIFIER_USER_TEMPLATE`` 的手拼大字符串
    改为结构化渲染，含 reasoning / answer / lemmas / citations 四个字段。
    契约：
      - ``to_dict()`` / ``to_json()`` / ``from_candidate()``；
      - ``render(template, **kw)`` 用模板渲染成提示词文本；
      - schema 校验：``validate()``。
    """
    reasoning: str = ""
    answer: str = ""
    lemmas: list = field(default_factory=list)       # list[str]
    citations: list = field(default_factory=list)    # list[str]

    def to_dict(self) -> dict:
        return {
            "reasoning": self.reasoning,
            "answer": self.answer,
            "lemmas": list(self.lemmas),
            "citations": list(self.citations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_candidate(cls, candidate, lemmas: list = None) -> "Artifact":
        """从候选（dict 或对象）构建 Artifact。"""
        if isinstance(candidate, dict):
            reasoning = candidate.get("reasoning", "")
            answer = candidate.get("answer", "")
        else:
            reasoning = getattr(candidate, "reasoning", "")
            answer = getattr(candidate, "answer", "")
        return cls(reasoning=reasoning or "", answer=answer or "",
                   lemmas=list(lemmas or []))

    def render(self, template: str, **kw) -> str:
        """用模板渲染，缺省键从自身字段补全。"""
        data = {
            "reasoning": self.reasoning,
            "answer": self.answer,
            "lemmas": "\n".join(f"- {l}" for l in self.lemmas),
            "candidate_answer": (self.reasoning + "\n【最终答案】" + self.answer)
                                 if self.reasoning or self.answer else "",
            "problem": kw.get("problem", ""),
        }
        data.update(kw)
        return template.format(**data)

    def validate(self) -> list[str]:
        """schema 校验，返回错误列表（空=合法）。"""
        errs = []
        if not isinstance(self.reasoning, str):
            errs.append("reasoning 必须为 str")
        if not isinstance(self.answer, str):
            errs.append("answer 必须为 str")
        if not isinstance(self.lemmas, list):
            errs.append("lemmas 必须为 list")
        if not isinstance(self.citations, list):
            errs.append("citations 必须为 list")
        return errs


# ------------------------------------------------------------
# P7：ToolSpec / 工具注册表（B10 自发现）
# ------------------------------------------------------------
@dataclass
class ToolSpec:
    """工具规格契约（P7 / B10 注册表自发现）

    注册表通过遍历具备 ``tool_spec`` 属性的模块/对象自发现工具。
    """
    name: str
    description: str
    parameters: dict = field(default_factory=dict)   # JSON-schema 风格
    callable: Optional[object] = None                # 可调用对象

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


class ToolRegistry:
    """工具注册表（P7 / B10）：支持注册 + 自发现。

    契约：
      - ``register(spec: ToolSpec)`` / ``register_obj(obj)``（对象含 tool_spec 属性时自发现）；
      - ``get(name)`` / ``list_tools()``；
      - ``invoke(name, **kw)`` 调用并返回结果。
    """
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec) -> None:
        with self._lock:
            self._tools[spec.name] = spec

    def register_obj(self, obj) -> None:
        """自发现：对象若携带 ``tool_spec`` 属性则自动注册。"""
        spec = getattr(obj, "tool_spec", None)
        if isinstance(spec, ToolSpec):
            self.register(spec)
        # 对象本身即 ToolSpec
        elif isinstance(obj, ToolSpec):
            self.register(obj)

    def get(self, name: str) -> Optional[ToolSpec]:
        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def invoke(self, name: str, **kw):
        spec = self.get(name)
        if spec is None or spec.callable is None:
            raise KeyError(f"Tool '{name}' 未注册或不可调用")
        return spec.callable(**kw)


# ------------------------------------------------------------
# Agent / Verifier 接口协议（预留修订空间，命名不写死）
# ------------------------------------------------------------
try:
    from typing import Protocol as _Protocol

    class AgentProtocol(_Protocol):
        """Agent 接口契约：run(ctx) 处理并返回上下文。"""
        name: str

        def run(self, ctx: TaskContext) -> TaskContext:  # noqa: D102
            ...

    class VerifierStrategy(_Protocol):
        """验证策略契约：对候选产出 verdict / feedback。"""

        def verify(self, ctx: TaskContext, problem: str, candidate) -> Verdict:  # noqa: D102
            ...

except ImportError:  # 极老 Python 无 typing.Protocol
    AgentProtocol = None  # type: ignore
    VerifierStrategy = None  # type: ignore


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
    lemma_repo: LemmaRepo = field(default_factory=LemmaRepo)  # 引理库（P2）
    state: RunState = field(default_factory=RunState)  # 运行期可变覆盖状态（B6）
    round_state: RoundState = field(default_factory=RoundState)  # AcceptGate 门控状态（P4）

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
        # B6：统一包装为不可变快照，杜绝运行时改写共享配置
        self.config = RunConfig(config)

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
