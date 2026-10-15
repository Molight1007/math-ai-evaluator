from __future__ import annotations

"""
Lean 前置形式化验证智能体（LeanPreVerifier）
===========================================

在解题开始前，把题目转化为 Lean 4 定理声明（证明 sorry 占位），用声明模式
编译校验「题目理解是否准确」；声明 well-typed 即视为理解正确。若验证失败，
把编译错误回传书生，要求重新理解题目并修正形式化，循环至通过或达到上限。

与后置 LeanGate 的区别：
- LeanPreVerifier（前置）：验证「题目命题声明」是否 well-typed，校准题意理解；
- LeanGate（后置）：验证「解答推理」是否正确，二者互补。

安全降级：Lean 环境缺失 / 编译超时 / 转化失败 / 预算不足 → 记 trace 后跳过
前置验证（formal_spec 留空），绝不阻断主流程。

依赖：
- agent/lean_bridge.py（LeanBridge.formalize_problem 声明模式编译）
- agent/base.py（BaseAgent / TaskContext）

★ 2026-10-14（第二次收敛，用户决策「直接删掉」）：**`run()` 的调用点已从 2.6 主流水线
撤除**（三条原始理由全失效 + 平台/本地无 Lean 时从未跑过 ⇒ 零行为变化；详见
`agent/orchestrator__prep.py` 内同文说明）。本类自此**只服务本地 LEAP 三阶段证据链
脚本** `cli/leap_eval.py::run_single`（它独立构造 `LeanPreVerifier` 并调 `run()`）。

2026-10-12 新增（用户设计 D1–D4，方案 v4 §3.5）；★ 2026-10-14 收敛：
- `run_understanding_chain()` —— 与 `run()` **并列**的另一条前置理解通道：
  只确定「题目要我们做什么」—— 建「题目完成后的终态」（答案用**符号槽**，禁写具体值；
  且由代码**机械剥离**任何被写死的数值）→ 缺口强制二分 A（题面没给）/ B（题面给了没读到）。
  ★ 2026-10-14 收敛：删除「逻辑链 `chain` + 一致性复推 + 链的 Lean 自检」——
  链式分解与 2.7 蓝图 AND-OR DAG 同层同义（属「整体理解」，归蓝图），保留即重复劳动；
  配套开关 `understanding_refine_rounds` / `understanding_no_gain_stop` /
  `understanding_chain_lean_check` 一并撤除（用户口径：「题意理解只做让模型注意到
  我们所需要求解的部分，对题目整体的理解则到蓝图构建部分」）。
- ⚠ `run()` 的既有行为**一字未改**（两条通道互不影响）。
"""

import logging
import os
import re
import time

# ★ 2026-10-07 架构解耦（阶段 B1）：`TaskContext` 仅作类型注解 ⇒ 改从零依赖的
# `contracts/protocols.py`（Protocol）导入。`BaseAgent` 保留（本类**真继承**它）。
from agent.base import BaseAgent
from contracts.protocols import TaskContext
from tools.lean_local.lean_bridge import (
    LeanBridge, hint_for_compile_error,
    _parse_analysis_json, _strip_code_fence)

logger = logging.getLogger("MathPilot")


def _hint_for_error(err: str) -> str:
    """按 Lean 编译器错误的特征给出**具体可执行的修法**（而非笼统"重新审题"）。

    2026-09-12 实测驱动：2.6 前置形式化在 3 题上「2 轮重试 0 成功」，根因是失败
    反馈让模型**重新审题**，而实际错误全部是 **Lean 语言层面**（API 不存在 / 把值
    当类型用 / 语法），重审题改不到点子上。

    实现上**委托**给共享的 `lean_bridge.hint_for_compile_error`（3.6 候选淘汰
    同样复用它，避免两处重复实现出现行为分叉）；本函数只额外提供"未识别特征时"
    的兜底文案（2.6 的场景必须给出非空反馈）。
    """
    if "sorry" in (err or "").lower():
        return "声明阶段允许 `sorry`，此项无需处理。"
    return hint_for_compile_error(err) or (
        "请**逐条针对上面的编译错误修正 Lean 写法**"
        "（数学含义保持不变，只改 Lean 的表达方式）。")


class LeanPreVerifier(BaseAgent):
    """题目前置形式化验证智能体（v2.9）。"""

    name = "LeanPreVerifier"

    def __init__(self, client, config):
        super().__init__(client, config)
        self._bridge: LeanBridge | None = None

    @property
    def _bridge_inst(self) -> LeanBridge | None:
        """懒加载 LeanBridge（budget 在 run 时才按 ctx 注入，故此处为占位）。"""
        if self._bridge is None:
            try:
                # budget 参数为 None：正式调用在 run 里按 ctx.budget 重新构造，
                # 确保前置形式化的 LLM 转化计入当前题的预算。
                self._bridge = LeanBridge(self.client, self.config, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("LeanPreVerifier: LeanBridge 初始化失败: %s", e)
                self._bridge = None
        return self._bridge

    def _build_bridge(self, ctx: TaskContext) -> LeanBridge | None:
        """构造绑定当前题预算的 LeanBridge（LLM 转化计入 ctx.budget）。"""
        try:
            return LeanBridge(self.client, self.config, ctx.budget)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanPreVerifier: LeanBridge 构造失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext) -> TaskContext:
        """前置形式化验证 + 骨架 Lean 审核 + 失败修正循环，写
        ctx.formal_spec / ctx.preverify_trace / ctx.sketch_audit。"""
        cfg = self.config
        if not getattr(cfg, "enable_lean_preverify", True):
            ctx.preverify_trace = {"enabled": False}
            return ctx
        if not ctx.problem:
            ctx.preverify_trace = {"verdict": "unknown", "error": "题目为空"}
            return ctx

        bridge = self._build_bridge(ctx)
        if bridge is None:
            ctx.preverify_trace = {"verdict": "unknown", "error": "LeanBridge 初始化失败"}
            self.record(ctx, "lean_preverify", "LeanBridge 初始化失败，前置形式化降级跳过")
            return ctx

        max_rounds = max(0, int(getattr(cfg, "preverify_max_rounds", 2)))
        timeout = float(getattr(cfg, "preverify_timeout", 60.0) or 60.0)

        final = {"verdict": "unknown", "rounds": 0,
                 "lean_code": "", "formal_spec": "", "error": ""}
        feedback = ""
        for r in range(max_rounds + 1):
            final["rounds"] = r
            # 时间护栏：紧迫则跳过（降级，不阻断主流程）。
            # 2026-09-03 审核：原来这里连写两个 is_time_critical() 分支
            # （"预算不足"在前、"时间紧张"在后），后者永远不可达——预算闸门
            # 删除时的清理遗漏。现只保留一个时间判断。
            if ctx.is_time_critical():
                final["error"] = "时间紧迫，跳过前置形式化"
                break

            result = bridge.formalize_problem(
                ctx.problem, ctx.domain or "", timeout=timeout, feedback=feedback)
            final["verdict"] = result["verdict"]
            final["lean_code"] = result["lean_code"]
            final["formal_spec"] = result["formal_spec"]
            final["error"] = result["error"]
            # 缺口（缺失定义/引理/模块/类型）：供子目标规划优先拆解
            final["gaps"] = result.get("gaps", [])
            ctx.formal_gaps = result.get("gaps", [])

            if result["verdict"] == "ok":
                ctx.formal_spec = result["formal_spec"]
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化通过（第 {r + 1} 轮）: "
                            f"{result['formal_spec'][:80]}")
                break  # 通过理解，进入骨架审核阶段

            if result["verdict"] == "fail":
                # 2026-09-02 老师拍板：错了就重新理解直到对才通过。
                # 反馈不只是 Lean 编译错误——加"重新审题"强指令，逼迫 LLM 重读
                # 题目原文而非重复同样的错误翻译。
                error_summary = (result.get("error") or "")[:200]
                # 2026-09-12 改动（实测驱动）：原反馈只让模型「**重新审题**」，
                # 但实测 3 题的失败全在 Lean 语言层面（API 不存在 / 值当类型用 /
                # 语法），重审题改不到点上 ⇒ 2 轮重试 0 成功。现改为按错误类型
                # 给**写法层面的具体修法**，同时保留"数学含义不变"的约束
                # （实测表明模型对题意的理解原本是正确的）。
                feedback = (
                    f"上轮形式化编译失败：\n{error_summary}\n\n"
                    "**请针对上述 Lean 编译错误修正代码写法**"
                    "（题目理解与数学含义保持不变，只改 Lean 的表达方式）：\n"
                    f"{_hint_for_error(error_summary)}\n"
                    "（若你判断上轮确实读错了题意，请一并说明并修正。）\n"
                )
                self.record(ctx, "lean_preverify",
                            f"题目前置形式化失败（第 {r + 1} 轮），强制重新理解重试: "
                            f"{error_summary[:120]}")
                continue

            # unknown（环境缺失/转化失败/超时）→ 不重试，直接降级
            break

        # ---- 骨架阶段 Lean 语法审核（#28）----
        # 2026-09-04 时间优化（老师：砍环节内重复、不砍环节本身）：
        # 此处"无 DAG 轻量骨架审核"与 2.7 subgoal 的 Blueprint DAG 整树审核
        # （sub_goal_solver._audit_blueprint_tree → LeanTranslator，写
        # ctx.sketch_tree 供 lean_refiner 消费）功能重叠，且 ctx.sketch 无下游
        # 消费者 → 默认关闭（enable_preverify_sketch_audit=True 可追溯重开）。
        # Lean 证据链不受损：DAG 级整树审核由 enable_sketch_audit（默认 True）
        # 驱动，完整保留。省下 ~150-200s/题给 3.5/3.6/6.5 候选 Lean 验证。
        if getattr(cfg, "enable_preverify_sketch_audit", False):
            if not ctx.is_time_critical():  # 预算已无限制（9/3）
                self.generate_and_audit_sketch(ctx)

        # 2026-09-02 老师拍板：rounds 用尽仍 fail → 标记"理解未确认"（让下游 Solver
        # 知道题目理解未经 Lean 校验，谨慎推理）。不阻断主流程（避免题目难时死锁），
        # 但 final_response 仍可能错（理解错了求解也跟着错）。
        if final.get("verdict") == "fail":
            ctx.formal_spec = ""  # 清除可能部分写的 spec
            # ★ 2026-10-14：`ctx._preverify_unconfirmed = True` **已删** ——
            #   全仓无读取方（只在 contracts/protocols.py 有声明注释）⇒ 死字段。
            self.record(
                ctx, "lean_preverify",
                "preverify 多次重试仍 fail，标记理解未确认——下游推理需谨慎",
            )

        # 未通过/降级：formal_spec 可能留空，但不阻断主流程
        ctx.preverify_trace = final
        self.record(ctx, "lean_preverify",
                    f"前置形式化结束: verdict={final.get('verdict')}；"
                    f"{final.get('error', '')[:120]}")
        return ctx

    # ------------------------------------------------------------------
    # 骨架生成 + Lean 语法审核（#28）
    # ------------------------------------------------------------------
    def _generate_sketch(self, ctx: TaskContext) -> str:
        """让书生(Intern-S1)生成题目骨架/Proof Body Outline（Informal Blueprint）。

        返回自然语言骨架（编号子目标列表）；生成失败返回空串（调用方降级）。
        """
        from tools.lean_local.prompts.lean_pre_verify import LEAN_SKETCH_SYSTEM, LEAN_SKETCH_USER
        formal_spec_block = ""
        if ctx.formal_spec:
            formal_spec_block = ("## 题目的形式化理解（已知条件→结论）\n"
                                + ctx.formal_spec + "\n\n")
        user_msg = LEAN_SKETCH_USER.format(
            problem=ctx.problem, domain=ctx.domain or "未知",
            formal_spec=formal_spec_block)
        raw = self.llm(
            ctx,
            [
                {"role": "system", "content": LEAN_SKETCH_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.2, 32768,
        )
        if not raw:
            return ""
        parsed = _parse_analysis_json(raw)
        outline = (parsed or {}).get("outline") or raw
        return _strip_code_fence(str(outline)).strip()

    def generate_and_audit_sketch(self, ctx: TaskContext, sketch_text: str = "") -> TaskContext:
        """生成（若未提供）并用 Lean 审核题目骨架，写 ctx.sketch / ctx.sketch_audit。

        审核发现的缺口并入 ctx.formal_gaps，供子目标规划优先拆解
        （即"骨架哪一步不严谨"→ 成为要先解决/拆解的子目标）。
        """
        bridge = self._build_bridge(ctx)
        if bridge is None:
            ctx.sketch_audit = {"verdict": "unknown", "error": "LeanBridge 初始化失败", "gaps": []}
            return ctx

        timeout = float(getattr(self.config, "preverify_timeout", 60.0) or 60.0)

        # 1) 生成骨架（若未提供）
        if not sketch_text:
            if ctx.is_time_critical():
                ctx.sketch_audit = {"verdict": "unknown", "error": "预算不足，跳过骨架生成", "gaps": []}
                return ctx
            sketch_text = self._generate_sketch(ctx)
        ctx.sketch = sketch_text or ""
        if not ctx.sketch:
            ctx.sketch_audit = {"verdict": "unknown", "error": "骨架生成失败", "gaps": []}
            return ctx

        # 2) 用 Lean 审核骨架（语法/类型严谨性）
        result = bridge.audit_sketch(ctx.sketch, ctx.problem, ctx.domain or "", timeout=timeout)
        ctx.sketch_audit = result

        # 3) 骨架缺口并入 formal_gaps（去重），供子目标规划优先拆解
        sg = result.get("gaps", []) or []
        if sg:
            existing = {g.get("detail") for g in ctx.formal_gaps}
            for g in sg:
                if g.get("detail") and g.get("detail") not in existing:
                    ctx.formal_gaps.append(g)
                    existing.add(g.get("detail"))

        self.record(ctx, "lean_sketch_audit",
                    f"骨架 Lean 审核: verdict={result.get('verdict')}; 缺口 {len(sg)} 个")
        return ctx

    # ------------------------------------------------------------------
    # 题意前置理解：终态 + 答案槽（纯符号）+ 缺口 A/B
    # （2026-10-12 用户设计 D1–D4；★ 2026-10-14 收敛，见本文件头说明）
    # ------------------------------------------------------------------
    def run_understanding_chain(self, ctx: TaskContext) -> None:
        """确定「题目要我们做什么」：**终态 + 答案槽（纯符号）+ 缺口 A/B**。

        与 `run()` 的区别（`run()` 是"声明 well-typed 即当理解正确"）：
          · 只看「所求」：建**终态**（答案用符号槽，**禁写具体值**）+ **答案槽**；
          · 缺口强制二分：A = 题面没给；B = 题面给了但本轮没读到。

        ★ 2026-10-14 收敛（用户口径：「题意理解只做让模型注意到我们所需要求解的
          部分，整体理解归蓝图」）：
            · **删逻辑链 `chain` 及无条件一致性复推** —— 链式分解与 2.7 蓝图
              AND-OR DAG 同层同义（属「整体理解」）⇒ 单轮即定案；
            · **删链的 Lean 自检** —— 它只为编译"链"服务，链删后即无对象；
            · **answer_slot / terminal_state 机械剥离数值** —— 提示词的软禁令
              实测被忽略（official112-002 把错值 `T=(√5−1)/2` 写进答案槽，
              经 `problem_goal` → 蓝图 → 最终答案泄漏）⇒ 代码兜底。

        产出：`ctx.understanding_chain` / `ctx.understanding_gaps` / `ctx.understanding_rounds`。
        失败 / 超时一律降级，**绝不阻断主流程**。
        """
        cfg = self.config
        # ⚠ 兜底值须与 AgentConfig 声明（True）一致 —— 见 orchestrator__prep.py 同名说明。
        if not getattr(cfg, "enable_understanding_chain", True):
            ctx.understanding_chain = {"enabled": False}
            return
        if not str(getattr(ctx, "problem", "") or "").strip():
            ctx.understanding_chain = {"verdict": "unknown", "reason": "题目为空"}
            return

        out = {"verdict": "unknown", "rounds": 0,
               "terminal_state": "", "answer_slot": "",
               "gaps_a": [], "gaps_b": [], "reason": ""}
        if ctx.is_time_critical():
            out["reason"] = "时间紧迫，提前结束"
            ctx.understanding_chain = out
            ctx.understanding_rounds = 0
            return

        out["rounds"] = 1
        payload = self._understanding_round(ctx)
        if payload is None:
            # ★ 2026-10-13 修正（实测 2/3 题首轮即不可解析、却已烧 613–716 s）：
            #   首轮失败**不允许直接放弃** —— 用更严格的 JSON 指令**降级重试 1 次**。
            out["retry_used"] = True
            payload = self._understanding_round(ctx, force_json=True)
        if payload is None:
            out["reason"] = "LLM 输出不可解析（含降级重试）"
        else:
            # ★ 2026-10-14（item ②）：**机械化剥离**被写死的数值。答案槽用激进口径
            #   （连 `T = \frac{...}` 这类赋值也掩掉），终态用 K11 既有口径（只掩
            #   「…为/是/等于 N」形态，避免误伤符号等式）。
            out["terminal_state"] = _mask_answer_values(
                str(payload.get("terminal_state") or ""))
            out["answer_slot"] = _mask_answer_values(
                str(payload.get("answer_slot") or ""), aggressive=True)
            a_gaps, b_gaps = split_gaps(payload.get("gaps"))
            out["gaps_a"], out["gaps_b"] = a_gaps, b_gaps
            ctx.understanding_gaps = a_gaps + b_gaps
            self.record(
                ctx, "understanding_chain",
                "题意理解：终态 %d 字、答案槽 %s、缺口 A%d/B%d"
                % (len(out["terminal_state"]),
                   ("（" + out["answer_slot"][:60] + "）")
                   if out["answer_slot"] else "（空）",
                   len(a_gaps), len(b_gaps)))

        out["verdict"] = ("ok" if (out["terminal_state"] or out["answer_slot"])
                          else "unknown")
        ctx.understanding_chain = out
        ctx.understanding_rounds = out["rounds"]
        self.record(ctx, "understanding_chain",
                    "题意理解结束：verdict=%s%s"
                    % (out["verdict"],
                       ("（" + out["reason"] + "）") if out["reason"] else ""))

    def _understanding_round(self, ctx, force_json: bool = False):
        """单轮：只看"题目要什么" ⇒ 终态 + 答案槽 + 缺口（单轮即定案）。

        ★ 2026-10-13：新增 `force_json` —— 降级重试用。实测首轮有 2/3 题产出不可解析
          （疑因契约复杂 + 模型先吐大段解释）⇒ 重试时**把 JSON 要求前置并加硬约束**。
        ★ 2026-10-14：删「复推」分支（原 `prev` 参数与 `UNDERSTANDING_REFINE_USER`）。
        """
        try:
            from tools.lean_local.prompts.lean_pre_verify import (
                UNDERSTANDING_TERMINAL_SYSTEM as _SYS,
                UNDERSTANDING_TERMINAL_USER as _U0)
        except ImportError:
            from .prompts.lean_pre_verify import (  # type: ignore
                UNDERSTANDING_TERMINAL_SYSTEM as _SYS,
                UNDERSTANDING_TERMINAL_USER as _U0)
        domain = getattr(ctx, "domain", "") or "未知"
        user_msg = _U0.format(problem=ctx.problem, domain=domain)
        # ★ 2026-10-14（任务列表 #2「定理检索移到后面子目标求解过程中」）：
        #   **原此处的 `render_for_stage(ctx, "pre_audit")` 注入已撤除**。
        #   检索从 1.2 下移到 2.7 子目标求解，而题意理解跑在 2.6（更早）⇒ 此处
        #   恒取不到结果（保留即静默死代码）。`DEFAULT_TOPK_BY_STAGE["pre_audit"]`
        #   键位仍保留，供外部脚本/历史 jsonl 取到确定性条数。
        if force_json:
            user_msg = (
                "⚠ 只输出**一个 JSON 对象**，不要任何解释、推导过程或 markdown 围栏。\n"
                "必需字段：terminal_state / answer_slot / gaps。\n"
                "gaps 是数组，每项 {\"kind\": \"A\"|\"B\", \"detail\": \"...\"}。\n\n"
                + user_msg)
        try:
            raw = self.llm(ctx, [
                {"role": "system", "content": _SYS},
                {"role": "user", "content": user_msg},
            ], 0.2, 32768)
        except Exception as e:  # noqa: BLE001
            logger.warning("[understanding_chain] LLM 调用异常: %s", str(e)[:120])
            return None
        if not raw:
            self.record(ctx, "understanding_chain", "本轮 LLM 返回空")
            return None
        parsed = _parse_analysis_json(raw)
        if not isinstance(parsed, dict):
            # ★ 2026-10-13：把**原始响应片段**留痕 —— 否则「不可解析」无法定位
            #   （是 JSON 被截断？还是模型先输出大段解释？）
            self.record(ctx, "understanding_chain",
                        "本轮输出不可解析（原始片段）：" + str(raw)[:300])
            return None
        return parsed


# ---------------------------------------------------------------------------
# 题意前置理解（2026-10-12 用户设计 D1–D4；★ 2026-10-14 收敛：删链与复推）
# ---------------------------------------------------------------------------

# 被**写死的数值**的机械剥离（K11 防泄漏；2026-10-14 题意理解收敛时新增）
# 实证：official112-002 的 answer_slot 被写成 `T = \frac{\sqrt{5}-1}{2}`（gold = 1/2），
#   提示词里"禁止写具体数值"的软禁令被忽略 ⇒ 错值经 problem_goal → 蓝图 → 最终答案。
_VALUE_ASSIGN_RES = (
    # 赋值给 LaTeX 分式/根式：`= \frac{...}` / `= \sqrt{...}`
    re.compile(r"=[^\S\n]*(?:\\?frac|\\?dfrac|\\?sqrt|\\?tfrac)\b[^\n；;]*",
               re.IGNORECASE),
    # 赋值给裸数值：`= 42` / `= -3.5` / `= 3/4`
    re.compile(r"=[^\S\n]*[-+]?\d[\d,]*(?:\.\d+)?"
               r"(?:[^\S\n]*/[^\S\n]*[-+]?\d[\d,]*(?:\.\d+)?)?"),
)
_MASK_LOCKED_VALUE = "[待求解值：由过程现场确定]"


def _mask_answer_values(text: str, aggressive: bool = False) -> str:
    """把答案槽 / 终态里**被写死的具体数值**换成占位符（K11 防泄漏，机械兜底）。

    · 基础口径（两处都跑）：复用 `agent/sub_goal_solver._mask_asserted_values`
      （既有 K11 掩码，覆盖中英「…为/是/等于 N」形态）；
      import 失败（缺依赖 / 循环）时静默跳过，不影响理解链本身。
    · ``aggressive=True``（**只给 answer_slot**）：额外掩掉「赋值给具体值」的形态
      —— 含实测泄漏原句 `T = \\frac{\\sqrt{5}-1}{2}`。

    为什么只对 answer_slot 用激进口径：终态是自然语言描述，激进口径会误伤其中的
    符号等式（如 `n² - n = 2k`）；而 answer_slot 按契约本就只该是符号，掩错代价极低。
    """
    t = str(text or "")
    if not t:
        return ""
    try:
        from agent.sub_goal_solver import _mask_asserted_values as _m
        t, _n = _m(t)
    except Exception:  # noqa: BLE001  掩码是增益，取不到不阻断
        pass
    if aggressive:
        for pat in _VALUE_ASSIGN_RES:
            t = pat.sub("= " + _MASK_LOCKED_VALUE, t)
    return t.strip()


def split_gaps(gaps) -> tuple:
    """把缺口清单按 kind 二分：返回 ``(A 类, B 类)``。

    - **A 类**：题面确实没有给（需假设才能推进）⇒ 进蓝图作风险项；
    - **B 类**：题面给了但本轮没提取到（"我没读到"）⇒ 供蓝图/子目标重点回查。
    kind 缺失/非法一律归 A（保守：宁可标成"需假设"，不要谎称"已给"）。
    """
    a, b = [], []
    for g in (gaps or []):
        if isinstance(g, dict):
            kind = str(g.get("kind") or "").strip().upper()
            detail = str(g.get("detail") or "").strip()
        else:
            kind, detail = "", str(g or "").strip()
        if not detail:
            continue
        (b if kind == "B" else a).append({"kind": kind or "A", "detail": detail})
    return a, b
