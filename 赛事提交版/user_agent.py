from __future__ import annotations
"""
MathPilot — 基于 Intern-S 系列大模型的数学智能体（多智能体版）
==========================================================

赛题：基于 Intern-S 系列大模型的数学智能体设计与推理创新
发榜单位：上海人工智能实验室

架构（多智能体协作，简化版 v2）：
    题型识别 → 通用求解 → 过程校验 → 答案规范化
    由 Orchestrator 通过共享黑板（TaskContext）调度，借鉴 ss-main 的简洁流水线。
    不做复杂回环，每道题 LLM 调用控制在 7 次以内。

硬性接口规范（不可修改）：
    agent = ReasoningAgent(client=official_client)
    result = agent.solve(problem, metadata)  # -> dict

注意事项：
    - 禁止硬编码 API Key，client 由平台统一注入
    - 禁止使用绝对路径，所有文件读取使用相对路径
    - solve 返回的字典必须支持 JSON 序列化
    - final_response 不可为空

平台契约防御（v2.3）：
    - sys.path 自举：无论平台以何种 cwd 运行，都能找到本包
    - solve(problem, metadata=None)：metadata 缺失时不崩溃
    - 核心模块导入失败 → 降级到内置直答后端，保证永远有输出
    - client.chat 响应归一化：兼容 str / dict / 对象 / 空值
    - _validate_output：返回前强制校验 final_response 非空
"""

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# sys.path 自举：保证从任何 cwd 都能 import 到本包
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger("MathPilot")


# ============================================================
# 配置
# ============================================================
@dataclass
class AgentConfig:
    """智能体可调参数（选手可自由优化）
    
    适配竞赛规则 v3（2026-07-31）：
    - 并发=3，单题最长=20分钟，Agent最长=6小时
    - 反rollout：减少候选数与投票次数，依赖聚类共识而非暴力采样
    """
    # 策略模型（解题）
    # P0-4 修复：候选 3→2（平台并发=3，且 3 候选×3 重试曾耗尽单题预算 → 45 error）
    # v2.4.0：恢复 24576 上限（ICMA 对齐）。ICMA 实测同模型首轮 24576 仅 143-231s，
    # 模型实际只用 3-7K token，24576 只是上限；降上限会牺牲贴上限的奥赛题成功区间。
    # 真正修超时靠：结构化四章节 prompt（抑制自由 CoT）+ 预算感知 + 压缩 prefill 兜底。
    policy_sample_times: int = 2       # 候选解答数量
    policy_temperature: float = 0.3    # 策略采样温度（提高以增加多样性）
    policy_max_tokens: int = 24576     # 策略最大 token（上限，模型实际用 3-7K）

    # 蓝图分解（简化版：关闭蓝图，直接用最简 prompt）
    use_blueprint: bool = False        # 旧式一次性蓝图提示词（保持关闭）

    # LEAP Stage 1：Blueprint DAG 依赖驱动分解（#27，接入子目标规划，失败自动回退）
    use_blueprint_dag: bool = True

    # 验证模型（评判）
    verifier_voting_times: int = 1     # 每个候选只投 1 票（避免无效重复投票）
    verifier_temperature: float = 0.0  # 验证温度（贪婪解码）

    # 题型分类（可选）
    enable_domain_hint: bool = True    # 是否启用领域提示增强
    enable_question_type: bool = True  # 是否启用题型识别（证明/选择/判断/填空/解答）+ 差异化策略

    # 解析
    extraction_mode: str = "auto"      # auto | last_line | regex

    # ---- 自主调控（大幅缩减）----
    max_revise_rounds: int = 1         # 自纠错 1 轮（A/B 验证 6/6 无损失，输出更易读）
    max_total_calls: int = 150         # LLM 调用预算硬上限（v2.6.1：15→60；v2.7：60→150，
                                        # 覆盖 5 题 batch + 限流重试 + deep 档完整流程
                                        # = classifier 1 + 求解 3 + 投票 6 + self_audit 1
                                        # + revise 1 + lean 转换 1 + collab 6 轮
                                        # + sub_goal 规划 1 + N 个子目标 ≈ 25-30 次/题）

    # ---- 时间限制（适配竞赛新规则）----
    # P0-5 修复：单题预算 300→1200（平台规则允许单题最长 20 分钟，ICMA 同款 1200s。
    #   此前 300s 对完整 CoT 求解（ICMA 实测中档 77-116s、奥赛 500-552s）是死限，
    #   导致主求解调用被读超时/预算跳过 → 45 error。总时长由 PaperPacer 动态收紧控制。）
    max_time_per_question: int = 1200  # 单题壁钟时间上限（秒，平台允许 20 分钟）
    max_total_time_seconds: int = 21000  # Agent总运行时间上限

    # ---- 智能体补充部件配置 ----
    # v2.4.0：max_tokens/cap 同步 24576（ICMA reasoning 同款上限，模型实际用 3-7K token）
    max_tokens: int = 24576            # 单次最大 token 数（匹配 policy_max_tokens）
    max_tokens_cap: int = 24576        # 内部 token 裁剪上限（对齐 ICMA reasoning 24576）
    max_workers: int = 3               # 并发验证线程数（匹配系统并发度=3）
    temperature: float = 0.3           # 默认 LLM 温度

    # ---- 自纠错参数 ----
    max_answer_tokens: int = 8192      # solver 单次调用最大 token 数
    revise_sample_times: int = 2       # 自纠错重解候选数

    # ---- 新功能开关（简化）----
    use_scoring: bool = False          # Verifier 不用多维评分（简化，减少误判）
    enable_deterministic: bool = True  # 确定性硬否决（v2.8）：SymPy 代入回验 fail 淘汰候选、unknown 放行
    by_enable_fast_path: bool = True   # 启用 SymPy 快车道求解
    use_proof_channel: bool = False    # 关闭证明题专用通道（简化）
    use_lemma_accumulation: bool = False  # 关闭引理积累（省 token）
    use_sub_goal: bool = False         # 子目标分解补充候选（候选不足/证明题时触发）

    # ---- 难题深度求解通道（v2.5）----
    # 三级档位资源分配：fast（快答）/ standard（标准，== 现状）/ deep（深度）
    enable_difficulty_router: bool = True   # 总开关；关闭则全卷走 standard（回归现状）
    enable_llm_difficulty: bool = True      # 难题识别第二层：LLM 自评难度（1 次小调用）
    tier_sample_times: dict = None          # 每档候选数 {fast:1, standard:2, deep:4}
    tier_temperatures: dict = None          # 每档温度分层（deep 用 4 层）
    tier_voting_times: dict = None          # 每档每候选投票数 {fast:1, standard:1, deep:3}
    tier_max_completions: dict = None       # 每档截断续写数 {fast:0, standard:1, deep:2}
    tier_max_calls: dict = None             # 每档 LLM 调用预算上限
    tier_budget: dict = None                # 每档设计预算帽（秒）{fast:120, standard:480, deep:1200}
    paper_target_time: int = 18000          # 全卷墙钟目标（秒，5 小时=18000）
    paper_min_soft: int = 120               # PaperPacer 单题软预算保底（秒）
    paper_total_questions: int = 112        # 默认全卷题数（PaperPacer 预算帽估算用）
    deep_use_sub_goal: bool = True          # deep 档强制子目标分解补充候选
    deep_revise_rounds: int = 1             # deep 档 0 票时 revise 自纠错轮数
    deep_use_playoff: bool = True           # deep 档 0 票且时间宽裕时 playoff 复算
    enable_collaborative_deep: bool = True  # 难题(deep 档)三Agent协作：解题→审查→整合→验证
    collab_max_rounds: int = 6              # 协作验证循环最大轮数（未通过则反复审查修正，时间充裕时保证高正确率）
    accept_confidence: float = 0.6          # AcceptGate 可接受置信度阈值（>=该值视为通过，v2.8）

    # ---- Lean 形式化硬验证（deep 档证明题门禁，v2.5+LeanBridge）----
    # 仅对 deep 档且 domain∈{证明,证明题} 的候选执行；fast/standard 档不触发。
    # verdict=proof_valid → 候选计入有效；proof_invalid → 淘汰并注入 revise 反馈；
    # unknown（Lean 环境缺失/超时/翻译错误）→ 按 lean_gate_strict 决定降级放行或保守拒绝。
    enable_lean_verify: bool = True         # 总开关：证明题启用 Lean 硬验证（v2.8 扩展到全部档位）
    lean_gate_all_proofs: bool = True       # v2.8：扩展到全部证明题（含 standard 档）；False=仅 deep 档
    lean_gate_strict: bool = False          # unknown 时是否保守拒绝；False=降级放行（不损失分数）
    lean_timeout: float = 60.0              # 单次 Lean 编译超时（秒）
    lean_executable: str = ""               # Lean 可执行文件名（默认 "lake"）
    # ---- Lean 前置形式化验证 + 子目标主路径（v2.9）----
    enable_lean_preverify: bool = True      # 前置形式化验证开关：解题前把题目转 Lean 声明校验理解
    preverify_max_rounds: int = 2           # 前置形式化失败后的修正重试上限
    preverify_timeout: float = 60.0         # 前置形式化单轮超时（秒）
    enable_subgoal_main_path: bool = True   # 子目标细化作为主路径（前置验证后统一跑一次）

    def __post_init__(self):
        """初始化三级档位配置表默认值（平台提交版默认关闭 LLM 自评? 否，默认开启）。"""
        if self.tier_sample_times is None:
            self.tier_sample_times = {"fast": 1, "standard": 2, "deep": 4}
        if self.tier_temperatures is None:
            self.tier_temperatures = {
                "fast": [0.1],
                "standard": [0.1, 0.3],
                "deep": [0.1, 0.3, 0.5, 0.7],
            }
        if self.tier_voting_times is None:
            self.tier_voting_times = {"fast": 1, "standard": 1, "deep": 3}
        if self.tier_max_completions is None:
            self.tier_max_completions = {"fast": 0, "standard": 1, "deep": 2}
        if self.tier_max_calls is None:
            # v2.6.1：deep 档 30→60
            # deep 档需要：三Agent协作反复验证(每轮 4 次 × max_rounds) + 多候选求解
            #   + 子目标分解 + 验证投票 + revise。collab_max_rounds=6 时单协作链就 24 次
            #   调用，30 次预算不够。60 次才能覆盖协作反复验证场景。
            # v2.8.1：deep 档 60→100（评测日志显示 60 在"协作 6 轮 + 子目标 + Lean +
            #   投票 + revise + oracle" 链路下仍耗尽，触发大量「跳过 LLM 调用」；
            #   100 留出余量，避免因预算紧绷导致的误判/跳过，提升难题正确率）
            # standard 档 15→30（覆盖 colab_max_rounds=4 协作 + 验证 + 多候选求解）
            self.tier_max_calls = {"fast": 6, "standard": 30, "deep": 100}
        if self.tier_budget is None:
            self.tier_budget = {"fast": 120.0, "standard": 480.0, "deep": 1200.0}


# ============================================================
# 响应归一化工具（P0-1 契约防线核心）
# ============================================================

def _normalize_chat_response(resp: Any) -> str:
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
        # 取第一个元素
        for item in resp:
            text = _normalize_chat_response(item)
            if text:
                return text
        return ""
    if isinstance(resp, dict):
        # 常见的几种字典形态
        for key in ("content", "text", "output", "result"):
            if key in resp and resp[key] is not None:
                val = resp[key]
                if isinstance(val, str):
                    return val
                return _normalize_chat_response(val)
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            choice = resp["choices"][0]
            if isinstance(choice, dict):
                # OpenAI 风格: {"message": {"content": ...}} 或 {"text": ...}
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
    # 最后兜底：字符串化
    try:
        s = str(resp)
        if s and s != "None" and not s.startswith("<") and not s.startswith("{"):
            return s
    except Exception:
        pass
    return ""


# ============================================================
# ReasoningAgent 平台入口（薄壳）
# ============================================================
class ReasoningAgent:
    """
    MathPilot 数学智能体主类（平台固定入口）。

    solve() 的内部实现已委托给多智能体 Orchestrator，本类仅负责：
    - 接收平台注入的 client；
    - 组装配置；
    - 透传 solve 调用并维持返回格式不变；
    - 平台契约防御：核心模块不可用时降级到内置直答后端。
    """

    def __init__(self, client, *args, **kwargs):
        self.client = client
        self.config = AgentConfig()

        # 允许通过 kwargs 覆盖配置（向后兼容 run_eval.py 的传参）
        for key in (
            "policy_sample_times", "policy_temperature", "policy_max_tokens",
            "verifier_voting_times", "verifier_temperature",
            "enable_domain_hint", "enable_question_type", "extraction_mode",
            "max_total_calls", "max_time_per_question",
            "max_total_time_seconds", "max_tokens_cap",
            "by_enable_fast_path", "use_scoring",
            "max_revise_rounds", "max_workers",
            "use_proof_channel", "use_lemma_accumulation",
            "max_answer_tokens", "revise_sample_times",
            "use_blueprint", "use_sub_goal",
            # 难题深度求解通道
            "enable_difficulty_router", "enable_llm_difficulty",
            "tier_sample_times", "tier_temperatures", "tier_voting_times",
            "tier_max_completions", "tier_max_calls", "tier_budget",
            "paper_target_time", "paper_min_soft", "paper_total_questions",
            "deep_use_sub_goal", "deep_revise_rounds", "deep_use_playoff",
            "enable_collaborative_deep", "collab_max_rounds",
            # Lean 硬验证
            "enable_lean_verify", "lean_gate_strict", "lean_timeout", "lean_executable",
        ):
            if key in kwargs:
                setattr(self.config, key, kwargs[key])
        # 覆盖 dict 型配置后需确保各档键完整
        self.config.__post_init__()

        self.orchestrator = None
        # 核心模块导入失败时不崩溃：置为 None，solve 时走 fallback backend
        try:
            from agent.orchestrator import Orchestrator
            self.orchestrator = Orchestrator(client, self.config)
        except Exception as e:  # pragma: no cover
            logger.warning("Orchestrator 初始化失败，启用内置直答后端: %s", e)

        logger.info(
            "MathPilot ReasoningAgent (v2 simplified) initialized: "
            "samples=%d, votes=%d, domain_hint=%s, "
            "budget=%d, max_tokens_cap=%d, scoring=%s, fast_path=%s",
            self.config.policy_sample_times,
            self.config.verifier_voting_times,
            self.config.enable_domain_hint,
            self.config.max_total_calls,
            self.config.max_tokens_cap,
            self.config.use_scoring,
            self.config.by_enable_fast_path,
        )

    # ------------------------------------------------------------------
    # 内置直答后端（fallback backend）：核心流水线不可用时保证有输出
    # ------------------------------------------------------------------
    def _fallback_solve(self, problem: str) -> str:
        """零依赖直答：直接要求模型给出最终答案，不经过 orchestrator。"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是数学解题专家。请解答下面的数学题，最后一行必须用"
                        "【最终答案】:<答案> 的格式给出最终答案，答案只写数值、"
                        "表达式或选项，不要多余解释。"
                    ),
                },
                {"role": "user", "content": problem},
            ]
            resp = self.client.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=self.config.max_answer_tokens,
            )
            text = _normalize_chat_response(resp)
            if not text:
                return ""
            # 提取【最终答案】行
            import re
            m = re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            if m:
                ans = m.group(1).strip().split("\n")[0].strip()
                if ans:
                    return ans
            # 兜底：返回最后一个非空行
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines[-1][:500]
            return text.strip()[:500]
        except Exception as e:  # pragma: no cover
            logger.error("fallback_solve failed: %s", e)
            return ""

    def _validate_output(self, result: dict) -> dict:
        """返回前强制校验：final_response 非空且可 JSON 序列化。"""
        fr = result.get("final_response", "")
        if not isinstance(fr, str) or not fr.strip():
            result["final_response"] = "未给出有效解答。"
        # 保证 JSON 可序列化
        if not isinstance(result.get("trace"), list):
            result["trace"] = []
        return result

    def solve(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        """
        求解单道数学题（平台固定调用入口）。

        参数:
            problem: 原始数学题目文本
            metadata: 题目元数据（可缺省，含 idx 字段）

        返回:
            {"final_response": str, "trace": list[dict]}
        """
        if metadata is None:
            metadata = {}
        if problem is None or not str(problem).strip():
            return self._validate_output({
                "final_response": "题目为空。",
                "trace": [{"stage": "input", "note": "empty problem"}],
            })

        # 核心流水线可用 → 走 orchestrator
        if self.orchestrator is not None:
            try:
                result = self.orchestrator.run(problem, metadata)
                if result and isinstance(result, dict):
                    return self._validate_output(result)
            except Exception as e:  # pragma: no cover
                logger.error("orchestrator.run failed, fallback to direct backend: %s", e)

        # 降级：内置直答后端
        answer = self._fallback_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
        return self._validate_output({
            "final_response": answer,
            "trace": [{"stage": "fallback_direct", "note": "orchestrator unavailable"}],
        })

    # 兼容平台直接调用 agent(problem, metadata) 的场景
    def __call__(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        return self.solve(problem, metadata, *args, **kwargs)

    # 兼容平台调用 agent.run(problem, metadata) 的场景
    def run(self, problem: str, metadata: dict = None, *args, **kwargs) -> dict:
        return self.solve(problem, metadata, *args, **kwargs)
