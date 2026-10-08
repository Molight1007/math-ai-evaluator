from __future__ import annotations
"""
答案规范化智能体（FormatterAgent）
==================================

把原 ``ReasoningAgent`` 末尾的答案抽取 / 兜底逻辑迁移为独立 Agent：
- 从 ``ctx.verdicts``（按置信度最高）或 ``ctx.candidates`` 选择最优答案；
- 通过 ``format_response`` 确保 ``final_response`` 非空且可序列化；
- 结果写入 ``ctx.final_response``，Orchestrator 负责封装返回字典。

BUG 修复：
  - 绝不输出"无法求解"等拒绝语（评测判 0）
  - _pick_best 启用共识加权（等价答案簇 → 更大簇更可信）
  - 增加 _is_valid_final_answer 终检
"""

import logging
import os
import re

from .base import BaseAgent, TaskContext
from utils.extract import format_response, is_truncated_answer

# 2026-10-08 拆分批：以下符号已整段迁至独立模块，此处**原位 re-export**
# 以保外部 import 契约（orchestrator / final_selector / 多处测试）。
from .formatter__nonanswer import _looks_like_non_answer  # noqa: F401
from .formatter__rank import (  # noqa: F401
    _answer_form_score, _answer_support, _attach_support,
    _passes_confidence_floor, _rank_key, _support_of, _is_real_enumeration,
)

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
# ★ 2026-10-07（fix-tail-gaps）：本文件两处选择题判据原为裸
#   `_os.environ.get("OBJECTIVE_*", ...) == "1"`，改走本注册制实时读
#   （默认值与注册表逐条核对一致，见 switch_registry.SWITCHES）。
try:
    from agent.switch_registry import get_bool as _sw_bool
except ImportError:
    from switch_registry import get_bool as _sw_bool

logger = logging.getLogger("MathPilot")

# 2026-09-13 晚：紧急直答（最终兜底）所需的最小剩余时间（秒）。
# 这是"无论超没超时都要产出答案"的最后一环 —— 留 45s 让它有机会跑完一次
# 短直答（prefill 答案前置 + 小 max_tokens，实测正常 1–3s）。
#
# ★★ 2026-10-07 修复（B 类裸 env 登记 · C）：原为**模块级 import 期求值**
#   `_FINAL_ANSWER_MIN_SEC = float(os.getenv(...))`，本函数下方同类常量亦如此。
#   两个隐患：① 报告要还原"当时用的默认值"得靠 diag 快照，而 import 期求值后
#   快照**看不到**它；② 仓库里存在「先 import 模块、再 os.environ.update」的写法
#   （cli/run_phase0_eval.py / debug_one_trace.py / run_small_ds.py）⇒ import 期
#   求值会让后设的环境变量**静默失效**。改为**调用时实时读**，默认值不变（45 / 8192）。
_DEFAULT_FINAL_ANSWER_MIN_SEC = 45.0
_DEFAULT_EMERGENCY_ANSWER_MAX_TOKENS = 8192


def _final_answer_min_sec() -> float:
    """调用时实时读「紧急直答最小剩余时间」（秒）。

    读取优先级：switch_registry（env > config > default）> 直接读 env > 默认 45。
    该字段**尚未登记**进 switch_registry（登记属共享文件，由主理人统一处理），
    故当前走 env 分支；登记后自动切换到注册表口径（默认值保持 45）。
    """
    try:
        from .switch_registry import SWITCHES, get_num as _sw_num
        if "final_answer_min_sec" in SWITCHES:
            return float(_sw_num("final_answer_min_sec"))
    except Exception:  # noqa: BLE001  未登记 / 导入失败 → 回退直读 env
        pass
    try:
        return float(os.getenv("FINAL_ANSWER_MIN_SEC",
                               str(_DEFAULT_FINAL_ANSWER_MIN_SEC)))
    except (TypeError, ValueError):
        return _DEFAULT_FINAL_ANSWER_MIN_SEC


def _emergency_answer_max_tokens() -> int:
    """调用时实时读「紧急直答输出上限（token）」。默认值保持 8192（2026-10-02 DeepSeek 适配）。"""
    try:
        from .switch_registry import SWITCHES, get_num as _sw_num
        if "emergency_answer_max_tokens" in SWITCHES:
            return int(_sw_num("emergency_answer_max_tokens"))
    except Exception:  # noqa: BLE001  未登记 / 导入失败 → 回退直读 env
        pass
    try:
        return int(float(os.getenv("EMERGENCY_ANSWER_MAX_TOKENS",
                                   str(_DEFAULT_EMERGENCY_ANSWER_MAX_TOKENS))))
    except (TypeError, ValueError):
        return _DEFAULT_EMERGENCY_ANSWER_MAX_TOKENS

# 拒绝回答/不完整答案的模式（2026-09-02 加"子目标求解失败"占位符：
# 占位符直接当最终答案 = 50% 错题（009/053/004/022 等），必须触发换候选兜底）
# 2026-09-13 晚补：新增 solver 的「生成失败」占位符族。实测 4 题里 010/016 的
# `predicted` 就是 `[生成失败] 调用受限或模型拒绝回答` —— 它从 solver 的占位
# 候选流到这里时**不被旧正则识别**，于是被当成合法答案直接提交（formatter:115）。
# `生成失败`/`调用受限`/`拒绝回答`/`未给出有效解答`/`无法作答` 一律视为无效答案，
# 触发 `_pick_fallback` → 换候选 → 最终 `_emergency_answer` 直答兜底。
_REFUSAL_RE = re.compile(
    r"无法求解|无法解决|不能解决|无法解答|我无法|暂无|无解|子目标求解失败|"
    r"生成失败|调用受限|拒绝回答|未给出有效解答|无法作答",
    re.IGNORECASE,
)

# 2026-09-13 晚：「答案缺失/占位」判据（**窄口径**，用于决定"要不要推翻现有答案
# 重新求一次"）。与上面的 `_REFUSAL_RE` 的区别是**刻意不含** `无解` / `暂无` ——
# 它们是合法答案（「该方程无解」就是正确答案），用它们触发 `_emergency_answer`
# 会让直答**覆盖正确解**（独立验证者实测：answer='无解' 被覆盖成 '7'）。
# `_REFUSAL_RE` 的宽松口径仅用于"换个候选试试"（第 89 行），语义不同故分开。
# ⚠ 本常量与 `agent/orchestrator.py::_DEGRADED_ANSWER_RE`、
#   `user_agent.ReasoningAgent._DEGRADED_ANSWER_RE` **必须保持同一口径**。
_MISSING_ANSWER_RE = re.compile(
    r"生成失败|调用受限|拒绝回答|未给出有效解答|无法作答|子目标求解失败|"
    r"我无法|无法求解|无法解决|不能解决|无法解答",
    re.IGNORECASE,
)

# 明显截断/不完整的 LaTeX 环境或元语句
_INCOMPLETE_RE = re.compile(
    r"\\begin\{[^}]*\}\s*$|\\begin\{[^}]*\}\s*\\end\{[^}]*\}\s*$|"
    r"通解为\s*：\s*$|最终答案\s*：\s*$|答案为\s*$|选\s*$|"
    r"不过.{0,30}$|然而.{0,30}$|但是.{0,30}$|这可能不是",
    re.IGNORECASE,
)


# ★ 2026-09-16 新增：**伪枚举**识别（枚举优先分支专用）。
# 背景：`enum_preferred` 原先只判"含逗号即枚举"，于是把 `0,1,2,3,\ldots`
# 这类**省略号糊弄式答案**当成合法枚举，还因为"推理最长"而胜出
# （实测 003：conf=0.667 的正确候选 `\boxed{2026}` 输给了 conf=0.000 的它）。
# 真正的枚举答案必须**逐项列出具体值**，出现省略号即说明未写全 ⇒ 排除。
_PSEUDO_ENUM_RE = re.compile(
    r"\\ldots|\\cdots|\\dots|\.\.\.|…|⋯|"
    r"等等|其余|以此类推|依此类推|以下省略|"
    r"such\s+that|and\s+so\s+on",
    re.IGNORECASE,
)


class FormatterAgent(BaseAgent):
    name = "Formatter"

    def run(self, ctx: TaskContext) -> TaskContext:
        # 2026-09-02 bug 修复：0 票兜底路径（orchestrator 5) 段）预设的答案
        # （direct_solve 直答结果）优先——该路径候选全 0 票不可信，重选候选
        # 反而会把直答的好答案换掉。预设答案仍需过拒绝/占位/截断检查。
        # 2026-09-17 补强（实测 10 题中 5 题命中本路径；且 best=None 导致
        # `ctx._pick_diag` 永不写入，答案来源事后无法追溯）：
        #   ① 直答 preset 必须**自身合法**才允许早退 —— 命中 `_looks_like_non_answer`
        #      （工具标签 / 推理碎片 / 空）或拒绝 / 不完整 / 占位正则时，改走 `_pick_best`；
        #   ② 两条分支都保证 `ctx._pick_diag` 有值，来源可追溯。
        preset = (getattr(ctx, 'final_response', '') or '')
        #   ⚠ 判据**有意不含 `_REFUSAL_RE`**：该正则含 `无解` / `暂无`，
        #     而"无解"是**合法**数学答案（见本文件既有口径），纳入会把正确答案
        #     误判为脏答案而改走 _pick_best，属于"修复引入误杀"。
        _preset_ok = bool(preset.strip()) and not (
            _looks_like_non_answer(preset)
            or _INCOMPLETE_RE.search(preset)
            or _MISSING_ANSWER_RE.search(preset)
        )
        if (getattr(ctx, '_zero_vote_fallback', False) and _preset_ok):
            answer = preset
            confidence = 0.0
            best = None
            try:
                ctx._pick_diag = {
                    "branch": "zero_vote_fallback_direct",
                    "picked": (preset or "")[:60],
                }
            except Exception:  # noqa: BLE001
                pass
        else:
            best = self._pick_best(ctx)
            if best is None:
                # BUG-1 修复：绝不输出"无法求解"，也绝不把原题当答案。
                if ctx.candidates:
                    best = max(ctx.candidates, key=_rank_key)
                    # 2026-09-20 修复：删掉 `len(best.answer) > 2` 闸门。
                    # 本文件 247-250 / 487-489 / 814-816 均已论证"单字符是合法且
                    # 完整的答案"，唯此处漏改 ⇒ 答案 `A`/`7` 会被替换成推理尾部
                    # 500 字散文，客观题必然判错。与 251 行统一为"仅空/纯空白才回退"。
                    answer = best.answer if (best.answer or "").strip() else (
                        (best.reasoning or "")[-500:])
                else:
                    answer = ""
                confidence = 0.0
            else:
                answer = getattr(best, "answer", "") or ""
                # 2026-09-12 定型前审核修复：原判据 `not answer or len(answer) < 2`
                # 会把**单字符答案**（选项字母 `A`/`C`、判断题值、个位数）整条丢弃，
                # 换成推理尾部 500 字 → 客观题必然判错（题库中选项字母类答案占比可观）。
                # 单字符是**合法且完整**的答案，只在空（或纯空白）时才回退推理尾部。
                if not answer.strip():
                    answer = (getattr(best, "reasoning", "") or "")[-500:]
                confidence = getattr(best, "confidence", 0.0)
                # 如果来自聚类路径，优先使用簇的置信度（更可靠：基于多票共识）
                best_cluster = getattr(ctx, '_best_cluster', None)
                if best_cluster and getattr(best_cluster, 'confidence', 0.0) > 0:
                    confidence = best_cluster.confidence

        # 2026-09-17：兜底埋点 —— 无论走直答还是 `_pick_best`，都保证 `_pick_diag`
        # 有值，便于事后追溯答案来源（此前零票兜底分支 best=None ⇒ 永不写入）。
        if not getattr(ctx, "_pick_diag", None):
            try:
                ctx._pick_diag = {
                    "branch": "formatter_pick_best",
                    "picked": (answer or "")[:60],
                }
            except Exception:  # noqa: BLE001
                pass

        # ★ 2026-09-17（P1-D）：**多答案题并集**（仅在题面明确要求「所有 / 全部」时启用）。
        _uni = self._maybe_union_enumerated(ctx, answer)
        if _uni:
            try:
                ctx._pick_diag = {
                    "branch": "enum_union",
                    "picked": _uni[:80],
                    "base": (answer or "")[:40],
                }
            except Exception:  # noqa: BLE001
                pass
            self.record(ctx, "format",
                        "多答案并集（P1-D）：%s → %s" % ((answer or "")[:30], _uni[:60]))
            answer = _uni

        # ★ 2026-09-17（P1-C）：把**分歧候选**（各不同答案簇的代表）记入 `_pick_diag`。
        # 用户决策「候选不必要强制不一致，但有不一致的思路一定要保留」——
        # 此处**只保留可见性**：不制造多样性、不改选答逻辑。
        # `ctx._cluster_data` 此前只有写入、**全项目零读取点** ⇒ 分歧信息一直在手边却
        # 从未被使用（025 的 diag 只能看到 1 个簇正是因此）。
        try:
            _cd_all = getattr(ctx, "_cluster_data", None)
            if isinstance(_cd_all, list) and _cd_all:
                _reps = []
                for _cl in _cd_all:
                    _an = str(getattr(_cl, "answer_norm", "") or "").strip()
                    if not _an:
                        continue
                    _reps.append({
                        "answer": _an[:60],
                        "size": int(getattr(_cl, "size", 0) or 0),
                        "confidence": round(
                            float(getattr(_cl, "confidence", 0.0) or 0.0), 3),
                        "correct_votes": int(getattr(_cl, "vote_correct", 0) or 0),
                        "total_votes": int(getattr(_cl, "vote_total", 0) or 0),
                    })
                if _reps and isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag["divergent_clusters"] = _reps[:8]
        except Exception:  # noqa: BLE001
            pass

        # 答案过长检测：如果答案超过300字符，尝试从推理尾部重新提取
        if answer and len(answer) > 300:
            for c in (ctx.candidates or []):
                if c.reasoning and getattr(c, 'answer', '') == answer:
                    from utils.extract import extract_final_answer
                    retry = extract_final_answer(c.reasoning)
                    if retry and len(retry) < len(answer) and len(retry) > 1:
                        self.record(ctx, "finalize",
                                   f"长答案重提取: {len(answer)}→{len(retry)} 字符")
                        answer = retry
                        confidence = max(confidence, 0.5)  # 重提取成功，给默认置信度
                        break

        # 如果最佳答案是拒绝类 / 明显不完整 / 结构上不像答案，尝试从其他候选找更好答案
        # （2026-09-17：并入 `_looks_like_non_answer`，覆盖 `</tool_call>` 等脏答案）
        if (not answer or _looks_like_non_answer(answer)
                or _REFUSAL_RE.search(answer) or _INCOMPLETE_RE.search(answer)):
            fallback = self._pick_fallback(ctx, exclude_answer=answer)
            if fallback:
                answer = fallback
                self.record(ctx, "finalize",
                           "最佳候选答案为拒绝/不完整，改用候选兜底答案")
                confidence = 0.0

        # 答案质量终检 + 自动修复
        answer = self._diagnose_and_repair(answer, ctx)

        # 2026-09-02 老师需求：最终答案截断必解决。
        # 003 题答案 g(x)=-2x^{ 就是生成截断直接提交 → expr_wrong。
        # 修复：检出截断 → 用 LLM 续写补全（最多 2 次），仍失败才原样返回。
        answer = self._repair_truncated(ctx, answer)

        # 2026-09-02 占位符兜底：子目标求解失败的占位符（50% 错题根源）
        # 续写无意义 → 走紧急直答重新求一次最终答案
        # 2026-09-13 晚扩面（用户硬要求「无论超没超时都要把答案生成出来」）：
        # 触发条件从"只认 [子目标求解失败]"扩到「空答案 / 任何拒绝占位符」。
        # 依据：上一轮实测 010/016 的最终答案就是 `[生成失败] 调用受限或模型拒绝回答`，
        # 而这条兜底路径因条件太窄**从未被触发** ⇒ 占位符被原样交出去。
        # 现在只要最终答案不可用，就再博一次直答；直答也拿不到才交给上层最终兜底。
        _ans_txt = (answer or "").strip()
        if ((not _ans_txt) or _looks_like_non_answer(_ans_txt)
                or _MISSING_ANSWER_RE.search(_ans_txt)):
            direct = self._emergency_answer(ctx)
            if direct and not _MISSING_ANSWER_RE.search(direct):
                # ★ 2026-10-02 阶段二-2（team-lead Q4-①）：紧急直答属**池外直答**，
                #   纳入「五层 = 终答唯一出口」（单答案 ⇒ 直接采用、**不调 LLM**；
                #   开关 OFF ⇒ skipped ⇒ 原样，完全回退）。
                try:
                    try:
                        from .final_selector import adopt_single
                    except ImportError:
                        from final_selector import adopt_single
                    _r = adopt_single(ctx, direct, reason="formatter_emergency")
                    if not _r.get("skipped"):
                        _d2 = str(_r.get("answer") or "").strip()
                        if _d2:
                            direct = _d2
                except Exception:  # noqa: BLE001  五层异常不得阻断兜底直答
                    pass
                self.record(ctx, "finalize", f"占位符答案 → 紧急直答: {direct[:120]}")
                answer = direct
            else:
                self.record(ctx, "finalize",
                            "答案不可用（空/占位符）且紧急直答未得，交上层最终兜底")

        # ★ 2026-09-18（审核发现）：**这是 `ctx.final_response` 的第 4 个直写点**。
        # 另外 3 个（零票兜底直答 / 6.5 重做 / 6.5 换候选）已改用
        # `Orchestrator._set_final_response`（带非答案闸门），本行此前是漏网的。
        # 本模块自带 `_looks_like_non_answer`，直接复用，避免跨模块反向 import。
        # ★ 2026-10-02 阶段二-2（team-lead Q4-② 裁定）：**此处只做规范化（format_response
        #   + 非答案闸门），不选答** —— 终答由「五层」在更早的出口决定（`_pick_best` /
        #   `_set_final_response` / 紧急直答的 `adopt_single`）。**不是旁路，勿再改。**
        _fr_txt = format_response(answer)
        if str(_fr_txt or "").strip() and not _looks_like_non_answer(_fr_txt):
            ctx.final_response = _fr_txt
        else:
            self.record(ctx, "finalize",
                        "最终答案被判为非答案形态 → 不覆盖 ctx.final_response，"
                        "交上层最终兜底：%s" % str(_fr_txt)[:80])
        # ★★ 2026-09-21 修复（云端 n=38 逐题复核）：把 `_pick_diag["picked"]`
        #   同步为**实际落盘值**。
        #
        #   缺陷：`_pick_diag` 在本函数**前半段**就已写入（见上方零票兜底分支
        #   与 `formatter_pick_best` 兜底分支），但其后
        #   `_pick_fallback` / `_diagnose_and_repair` / `_repair_truncated` /
        #   `_emergency_answer` **仍会改写 `answer`** ⇒ 埋点记下的是**被丢弃的
        #   中间值**。实测云端快照 20/38 题 `pick_diag.picked` ≠ `predicted`，
        #   其中 8 题终答是散文 —— 使「是选答错了还是终答被覆盖」这一最关键
        #   归因**无法回答**（极易把埋点错位误读成"答案被后写覆盖"）。
        #
        #   修法：此处以 `ctx.final_response`（真正要提交的字符串）为准，
        #   原值移入 `picked_pre_repair` 保留追溯性。此改动**只影响埋点**，
        #   不改变任何选答/修复行为（`_pick_diag` 全项目无功能性读取点，
        #   仅由 `Orchestrator._collect_diag` 落盘进 diag）。
        #   OFF ⇒ 逐字保持改动前（`picked = _picked_final[:60]`）做 A/B。
        _ss_on = False
        try:
            try:
                from .final_selector import _single_source_enabled
            except ImportError:
                from final_selector import _single_source_enabled
            _ss_on = bool(_single_source_enabled())
        except Exception:  # noqa: BLE001
            _ss_on = False
        if isinstance(getattr(ctx, "_pick_diag", None), dict):
            _picked_final = str(ctx.final_response or "")
            if _picked_final:
                if _picked_final != ctx._pick_diag.get("picked"):
                    ctx._pick_diag["picked_pre_repair"] = ctx._pick_diag.get("picked")
                if _ss_on:
                    ctx._pick_diag.setdefault(
                        "picked_decision", ctx._pick_diag.get("picked"))
                    ctx._pick_diag["picked"] = _picked_final
                    ctx._pick_diag["final_submit"] = _picked_final
                    ctx._pick_diag["final_submit_source"] = "formatter"
                    ctx._pick_diag["final_submit_seq"] = int(
                        ctx._pick_diag.get("final_submit_seq", 0) or 0) + 1
                elif _picked_final != ctx._pick_diag.get("picked"):
                    ctx._pick_diag["picked"] = _picked_final[:60]
        # ★ 2026-10-07（问题 2.2）：把 `picked` 归入哪个 cluster 写进记录
        #   （未归入则写明原因）—— 回应「picked 必须能追溯到某个 cluster」。
        try:
            try:
                from .final_selector import record_pick_cluster, _verify_aware_enabled
            except ImportError:
                from final_selector import record_pick_cluster, _verify_aware_enabled
            if _verify_aware_enabled():
                record_pick_cluster(ctx)
        except Exception:  # noqa: BLE001
            pass
        self.record(
            ctx, "finalize",
            f"最终答案: {ctx.final_response[:200]} (置信度: {confidence:.2f})",
            confidence=round(confidence, 4),
        )
        return ctx

    def _maybe_union_enumerated(self, ctx: TaskContext, current: str):
        """2026-09-17（P1-D）：多答案题的**候选并集**。

        用户要求（原话）：「如果大模型能确定多个正确的答案，那就把所有答案都输出。
        但要保证不是什么答案都输出，要保证输出的答案的正确率。」

        硬约束（**宁缺勿滥**，任一不满足即放弃并集、保持原逻辑）：
          ① 仅在题面明确要求「所有 / 全部」时启用（高精度，覆盖"求所有解"型）；
          ② 只并入**无反对票**的簇（`vote_total > 0` 且 `vote_correct == vote_total`）；
          ③ 每簇只取 1 个代表；并入项数上限 **3**（实测 gold 最多 3 项）；
          ④ **加法而非替换** —— 当前答案必须已属某个"全票簇"，否则放弃；
          ⑤ 逐项过 `_looks_like_non_answer` 闸门，并与已有项去重；
          ⑥ 用 **ASCII 逗号 + 空格**连接（对齐 `run_eval._split_multi` **只按 `,` 拆**
             的口径；**不可用顿号**，否则判分器拆不出多项）；
          ⑦ 结果项数 < 2 ⇒ 放弃。

        返回 `None` = 不改（保持原逻辑）。
        """
        try:
            from agent.question_type import asks_all_values as _aav
            if not _aav(getattr(ctx, "problem", "") or ""):
                return None
            _cd = getattr(ctx, "_cluster_data", None)
            if not isinstance(_cd, list) or len(_cd) < 2:
                return None
            _cur = (current or "").strip()
            if not _cur:
                return None

            def _vt(_cl):
                return (int(getattr(_cl, "vote_total", 0) or 0),
                        int(getattr(_cl, "vote_correct", 0) or 0))

            # ④ 当前答案必须已在某个全票簇内，否则放弃（防"什么都输出"）
            _cur_ok = False
            for _cl in _cd:
                _an = str(getattr(_cl, "answer_norm", "") or "").strip()
                _tv, _cv = _vt(_cl)
                if _an and _tv > 0 and _cv == _tv and (_an == _cur or _cur in _an):
                    _cur_ok = True
                    break
            if not _cur_ok:
                return None

            _items, _seen = [], set()
            for _cl in _cd:
                _an = str(getattr(_cl, "answer_norm", "") or "").strip()
                _tv, _cv = _vt(_cl)
                if not _an or _tv <= 0 or _cv != _tv:      # ②
                    continue
                if _looks_like_non_answer(_an):            # ⑤
                    continue
                _k = _an.lower()
                if _k in _seen:
                    continue
                _seen.add(_k)
                _items.append(_an)
                if len(_items) >= 3:                       # ③
                    break
            if len(_items) < 2:                            # ⑦
                return None
            return ", ".join(_items)                       # ⑥
        except Exception:  # noqa: BLE001
            return None

    def _pick_best(self, ctx: TaskContext):
        """择优入口（★ 2026-09-30 截图 #9）：在原始择优之上加**可信度门槛**。

        用户口径：「投票要选出里面最像答案的一个，候选数量与逻辑通顺度都要是指标，
                  同时要**可信度要求**（太低＝全军覆没）」。

        本方法只做一件事：调用 `_pick_best_raw`（= 改动前的全部择优逻辑，逐字未动），
        然后检查被选中的候选**是否达到可信度底线**：
          · 达到 → 原样返回（**绝大多数情形走这里，行为与改动前完全一致**）；
          · 未达到 → 仍然返回它（不能把答案变成空，那是"全军覆没"本身），
            但**在 trace 里显式记一条 `low_confidence_pick`**，并把
            `ctx._pick_diag["below_confidence_floor"] = True` 落盘。

        为什么不"直接拒绝低可信度答案"：
          本项目的地基是"**必须有答案**"（评测判空 = 0 分）。若在此处拒绝，
          等于把单题从"可能答错"改成"必定 0 分"，与用户意图相反。
          「可信度要求」的正确落地是**让优化有据可依**——把"低于底线的题"标出来，
          供后续环节（5.5 强制复核 / 6.5 重做 / 数据闭环归因）定向处理。
          ⚠ `pick_confidence_floor` 默认 **0.0** ⇒ 本门槛默认**不产生任何新记录**，
            亦不改变任何行为；A/B 实验时再显式开启。
        """
        cand = self._pick_best_raw(ctx)
        try:
            floor = float(getattr(self.config, "pick_confidence_floor", 0.0) or 0.0)
        except (TypeError, ValueError):
            floor = 0.0
        if floor <= 0.0 or cand is None:
            return cand
        try:
            _ok, _why = _passes_confidence_floor(cand, floor)
            if not _ok:
                _ans = (getattr(cand, "answer", "") or "")[:60]
                if isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag["below_confidence_floor"] = True
                    ctx._pick_diag["confidence_floor"] = floor
                    ctx._pick_diag["picked_confidence"] = round(
                        float(getattr(cand, "confidence", 0.0) or 0.0), 4)
                self.record(
                    ctx, "finalize",
                    "★ 所选候选低于可信度门槛 %.2f：%s（conf=%.3f, 正确票 %s/%s）"
                    "—— 仍提交（拒绝会使本题必得 0 分），但已标记待后续环节定向复核"
                    % (floor, _ans,
                       float(getattr(cand, "confidence", 0.0) or 0.0),
                       getattr(cand, "correct_votes", 0),
                       getattr(cand, "total_votes", 0)))
            else:
                if isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag["below_confidence_floor"] = False
                    ctx._pick_diag["confidence_gate_reason"] = _why
        except Exception:  # noqa: BLE001
            pass
        return cand

    def _maybe_final_select(self, ctx: TaskContext):
        """★ 2026-10-02 阶段二-2：终答五层选择（开关 ON 时接管；未接管返回 None）。

        用户口径：「投票应在**最后**，不要一开始就投票」。开关
        `enable_final_answer_selection`（默认 True）ON 时，终答由
        `agent/final_selector.select_final_answer` 统一选出（②多答案判断→
        ③客观验证→④模型对比→⑤投票兜底）⇒ **不再走** `_rank_key` 票数优先 /
        `objective_majority_vote`。

        `skipped=True` / 无答案 ⇒ 返回 None ⇒ 调用方**回退既有择优**（不阻断主链）。
        结果经 `run_cached` 缓存 ⇒ 与 `orchestrator._pick_best_from_candidates`
        **共用同一决策**（同一 ctx 不会选出两个终答）。
        """
        try:
            try:
                from .final_selector import SynthCandidate, run_cached
            except ImportError:
                from final_selector import SynthCandidate, run_cached
            res = run_cached(ctx, self.llm, self.record)
            try:
                ctx._final_select_diag = dict(res.get("diag") or {})
                ctx._final_select_diag["branch"] = res.get("branch")
            except Exception:  # noqa: BLE001
                pass
            ans = str(res.get("answer") or "").strip()
            if not ans or res.get("skipped"):
                return None
            cand = res.get("cand")
            if cand is None:
                for c in (getattr(ctx, "candidates", None) or []):
                    if (getattr(c, "answer", "") or "").strip() == ans:
                        cand = c
                        break
            if cand is None:
                cand = SynthCandidate(ans, "（终答五层选择产出）")
            # ★ 2026-10-02 阶段三（team-lead 复核）：此处原先只在 `_pick_diag`
            #   **已是 dict** 时才写 ⇒ 主路径上 `_pick_diag` 尚未创建、写入静默丢失，
            #   随后被 :522 兜底改标成 `formatter_pick_best` ⇒ **A/B 两 arm 看起来
            #   走同一条路**、五层分支不可归因。改为「不是 dict 就先创建」。
            try:
                if not isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag = {}
                ctx._pick_diag["branch"] = "final_select_" + str(res.get("branch"))
                ctx._pick_diag["picked"] = ans[:40]
            except Exception:  # noqa: BLE001
                pass
            return cand
        except Exception as exc:  # noqa: BLE001  五层失败一律回退既有逻辑
            logger.debug("[formatter] 终答五层选择异常（回退）: %s: %s",
                         type(exc).__name__, exc)
            return None

    def _pick_best_raw(self, ctx: TaskContext):
        """
        选择最优答案（BUG-13 修复：共识加权）。
        优先使用聚类结果中置信度最高且规模最大的簇；其次使用传统 verdict 置信度。
        """
        # ★ 2026-10-02 阶段二-2：终答五层选择优先（开关 ON 时此处即返回，
        #   ⇒ 下方的 `_rank_key` 票数优先 / `objective_majority_vote` 全程不执行）。
        _fs = self._maybe_final_select(ctx)
        if _fs is not None:
            return _fs
        # ★★ 2026-09-30（截图 #9）：**择优前先算「独立复现数」**。
        #   用户口径：「候选数量与逻辑通顺度都要是指标」。
        #   本步骤把"池里有几个不同候选写出了同一结论"挂到每个候选的 `_support_n`，
        #   于是下面所有走 `_rank_key` 的排序都变成**五键**（票数→复现数→置信度→
        #   答案形态→紧凑度），"候选数量"由此真正成为择优依据。
        #   必须放在**所有择优分支之前**（含被证伪候选剔除之前会更好，但剔除只减
        #   候选、不产生虚假复现数，故放此处即可）。
        #   纯加性：异常/空池一律退化为 `_support_n=1`，与改动前逐字一致。
        try:
            _sup_map = _attach_support(getattr(ctx, "candidates", None))
            if _sup_map:
                # 埋点：让诊断报告能看出"本次终答背后有几个独立候选复现"
                setattr(ctx, "_support_map", _sup_map)
        except Exception:  # noqa: BLE001
            pass
        # ★ 2026-09-23 新增：**择优时跳过「已被客观证伪」的候选**。
        #   动机：零票兜底已改为"证伪优先"（orchestrator），被证伪的候选不得再参与择优，
        #   否则证伪等于白做。判据仍是"错误答案一定能被证明错误" —— 只剔除
        #   **拿到 SymPy 确认反例**的候选，任何不确定的候选照旧参与。
        #   实现纪律：仅在"过滤后仍有候选"且"确实剔除了东西"时才替换，
        #   否则原样走（零风险回退，不改变既有行为）。
        _fal = getattr(ctx, "_falsified_answers", None)
        if _fal and (getattr(ctx, "candidates", None) or []):
            try:
                from .answer_oracle import AnswerOracle as _AO
                _all = list(ctx.candidates)
                _keep = [c for c in _all
                         if not any(_AO.answers_equivalent(
                             getattr(c, "answer", "") or "", _x) for _x in _fal)]
                if _keep and len(_keep) < len(_all):
                    self.record(ctx, "finalize",
                                "择优前剔除 %d 个已被客观证伪的候选（剩 %d/%d）"
                                % (len(_all) - len(_keep), len(_keep), len(_all)))
                    ctx.candidates = _keep
            except Exception:  # noqa: BLE001
                pass
        # 2026-09-13：选择题答案多数投票（OBJECTIVE_MAJORITY_VOTE=1 时）。
        # 必须放在 best_cluster 分支**之前**：best_cluster 是 verifier 聚类，
        # 且簇内再按"推理长度"选（下见 #0），对客观题（答案形态稳定、候选
        # 易因裸字母 `A` 与 `\boxed{A}` 的格式差异被聚类拆散 / 簇内择优失真）
        # 直接做答案频次投票更可靠——这正是 102 候选 4B/2A 却被选 A 的根因。
        # 2026-09-14：选择题**优先采纳「逐项判定」候选**（origin="itemwise"）。
        # 依据：它是**逐个选项验证过**的结论（有共享基准、有逐项依据），可靠性
        # 高于"整体求解"候选。实测 #107 逐项判定正确得出 D（gold=D），却因候选池
        # 里有 5 个整体求解的 C，被 5:1 多数投票淹没 ⇒ 必须让**有依据的结论**
        # 优先于**数量多数**。置 OBJECTIVE_ITEMWISE_PRIORITY=0 可回退。
        # ★ 2026-10-07（fix-tail-gaps）：原裸读 env `== "1"` 已改走注册制
        #   `_sw_bool("objective_itemwise_priority")`（实时读，默认 True）。
        #   三态核对（未设/"1"/"0"）与原 `== "1"` 逐条一致；仅非标准值
        #   （如 "true"/"yes"）由 registry 口径判为「开」，属已文档化的统一修正。
        if (_sw_bool("objective_itemwise_priority")
                and getattr(ctx, "question_type", "") == "选择题"):
            _iw = [c for c in (getattr(ctx, "candidates", None) or [])
                   if getattr(c, "origin", "") == "itemwise"
                   and (getattr(c, "answer", "") or "").strip()]
            if _iw:
                # ★ 2026-09-22：原为 `key=len(reasoning)`（只看啰嗦程度）。改为统一
                #   `_rank_key`，保留"逐项判定优先"的设计意图，但簇内择优不再抖。
                _iw.sort(key=_rank_key, reverse=True)
                try:
                    ctx._pick_diag = {
                        "branch": "formatter_itemwise_priority",
                        "picked": (_iw[0].answer or "")[:40],
                        "n_itemwise": len(_iw),
                        "n_total": len(getattr(ctx, "candidates", None) or []),
                    }
                except Exception:  # noqa: BLE001
                    pass
                self.record(ctx, "finalize",
                            "选择题优先采纳逐项判定候选：{}"
                            "（逐项 {} 个 / 共 {} 个候选）".format(
                                (_iw[0].answer or "")[:40], len(_iw),
                                len(getattr(ctx, "candidates", None) or [])))
                return _iw[0]
        # ★ 2026-10-07（fix-tail-gaps）：原裸读 env `== "1"` 已改走注册制
        #   `_sw_bool("objective_majority_vote")`（实时读，默认 False）。
        #   与 orchestrator.py 同名开关判据（`_sw_bool("objective_majority_vote")`）保持同源。
        if (_sw_bool("objective_majority_vote")
                and getattr(ctx, "question_type", "") == "选择题"):
            _mv: dict = {}
            for _c in (ctx.candidates or []):
                _a = (getattr(_c, "answer", "") or "").strip()
                # ★ 2026-09-16 审计修复：去掉 `len(_a) > 3` 门槛。本文件 95-98 行
                #   已论证"单字符是**合法且完整**的答案"，且选择题多为 `A`/`AB`/`BCD`
                #   ⇒ 长度门槛会把多数投票的候选答案整条筛掉（客观题必判错）。
                if _a and not _REFUSAL_RE.search(_a):
                    _mv[_a] = _mv.get(_a, 0) + 1
            if _mv:
                # 2026-09-13 用户设计：**平票时做差分检测**——
                # 当多种选项组合并列最高频（如 AB×2 与 ABC×2），用集合差分
                # 定位真正的争议选项（此处 = C），只对争议项做定向验证；
                # 非平票则退回多数投票（取最高频组合）。
                _groups = self._group_option_sets(_mv)
                _fixed = self._objective_diff_probe(ctx, _groups)
                if _fixed:
                    from .base import Candidate as _Cand
                    return _Cand(id=-1, answer=_fixed,
                                 reasoning="[差分检测修正]")
                _top_ans, _top_n = max(_mv.items(), key=lambda kv: kv[1])
                # ⚠ P3 修复（2026-09-14 代码审查）：差分检测失败**且平票**时，
                # 上面的 `max()` 取的是 dict 插入序里第一个候选 ⇒ 等于**随机**。
                # 改为**取交集**：并列组合共同包含的选项 = 无争议的共识部分，
                # 是"争议项无法判定"时唯一有依据的保守选择。
                # （实测：AD×2 vs ACD×2 ⇒ **AD**，即剔除有争议的 C；
                #   A×3 vs B×3 完全对立、交集为空 ⇒ 只能退回最高票）
                _max_v = max(_mv.values())
                _tops_ans = [k for k, v in _mv.items() if v == _max_v]
                if len(_tops_ans) > 1:
                    try:
                        _sets = [set(re.findall(r"[A-E]", _t))
                                 for _t in _tops_ans]
                        _inter = set.intersection(*_sets) if _sets else set()
                        if _inter:
                            _ans_i = "".join(sorted(_inter))
                            try:
                                ctx._pick_diag = {
                                    "branch": "formatter_tie_intersection",
                                    "tops": ["".join(sorted(x)) for x in _sets],
                                    "intersection": _ans_i,
                                    "picked": _ans_i,
                                }
                            except Exception:  # noqa: BLE001
                                pass
                            self.record(ctx, "finalize",
                                        "选择题平票且差分失败 → 取交集 {} ⇒ {}".format(
                                            ["".join(sorted(x)) for x in _sets],
                                            _ans_i))
                            from .base import Candidate as _Cand2
                            return _Cand2(id=-1, answer=_ans_i,
                                          reasoning="[平票取交集]")
                    except Exception:  # noqa: BLE001
                        pass
                # 2026-09-13：埋点写入 ctx._pick_diag（_collect_diag 会落盘），
                # 与 orchestrator 兜底路径共用同一字段，保证"选取来源"可追溯。
                try:
                    _pd = {
                        "branch": "formatter_majority_vote",
                        "picked": _top_ans[:40],
                        "top_n": _top_n,
                        "dist": {k[:40]: v for k, v in _mv.items()},
                        "groups": {"".join(sorted(k)): g["votes"]
                                   for k, g in _groups.items()},
                    }
                    # 保留差分检测的失败原因（否则被本埋点覆盖，事后无法定位
                    # "为什么平票却没走差分检测"）
                    _prev = getattr(ctx, "_pick_diag", None)
                    if isinstance(_prev, dict) and str(
                            _prev.get("branch", "")).startswith("diff_probe"):
                        _pd["diff_probe_failed"] = _prev
                    ctx._pick_diag = _pd
                except Exception:  # noqa: BLE001
                    pass
                for _c in (ctx.candidates or []):
                    if (getattr(_c, "answer", "") or "").strip() == _top_ans:
                        return _c
        # ---- 2026-09-14 枚举优先（题面要求『所有』时）----
        # 实测 003：merge 已正确产出 `\boxed{0,2026}`，但 verdicts **三条全部失效**
        # （LLM 超时 —— 超时阈值被收到 120s 且 max_retries=1），答案选取随之退化，
        # **把正确的枚举丢掉了**，最终只剩 `\boxed{2026}`。
        # 依据：题面明确要求"所有/全部"时，**枚举形态的候选天然优于单值候选**
        # （单值必然不满足题意）。故在常规选答之前先做一次"枚举优先"。
        #
        # ★★★ 2026-09-16 修复（用户直接质问"为什么有正确答案却选了错的"）：
        #   原实现有**三重缺陷**，导致它反而成了错误来源。实测 003：
        #     候选1 `\boxed{2026}` 票 2/3 conf=0.667（**2026 是正确答案之一**）
        #     候选5 `\boxed{0,1,2,3,\ldots}` 票 0/3 conf=0.000（**省略号糊弄式伪答案**）
        #     本分支却选中了后者。
        #   ① "枚举"判据只是**含逗号** ⇒ 伪答案也算枚举；
        #   ② 排序**只看推理长度**，完全不看票数/置信度 ⇒ 0 票的长文本胜过 2 票；
        #   ③ 直接 `return` ⇒ **绕过后面全部正常选答逻辑**（聚类/置信度/多数票）。
        #   修法：加"伪枚举"过滤 + 排序改为 (票数, 置信度, 推理长度) 词典序。
        #   保留原设计意图：枚举形态确实优于单值（单值必然不满足"求所有"）。
        try:
            from .question_type import asks_all_values as _aav2
            if _aav2(ctx.problem or ""):
                _enum_c = []
                for _c in (ctx.candidates or []):
                    _a2 = (getattr(_c, "answer", "") or "").strip()
                    if not _a2 or _REFUSAL_RE.search(_a2):
                        continue
                    _core2 = _a2
                    _mb2 = re.search(r"\\boxed\{([^{}]*)\}", _a2)
                    if _mb2:
                        _core2 = _mb2.group(1)
                    if re.search(r"[,，;；、]", _core2):
                        # ① 伪枚举过滤：省略号 / "等等" / 未写全的形式（如
                        #    `0,1,2,3,\ldots`）**不是**合法枚举答案，必须排除。
                        if _PSEUDO_ENUM_RE.search(_core2):
                            continue
                        # ② ★ 2026-09-22：再加"真枚举"判据 —— 仅含逗号不等于枚举，
                        #    散文（014 的 0 票候选）曾被此分支优先返回。
                        if not _is_real_enumeration(_core2):
                            continue
                        _enum_c.append(_c)
                if _enum_c:
                    # ★ 2026-09-30（截图 #9）：统一改用 `_rank_key`。
                    #   原为**局部实现**的 (票数, 置信度, 推理长度) ——
                    #   ① 漏掉新增的「独立复现数」（候选数量指标在此分支失效）；
                    #   ② 末位仍是「推理长度」（本文件 222 行已论证它与正确性
                    #      无因果关系，且是同一条被修过三次的老毛病）。
                    #   改后与全项目择优口径**单一来源**，不再有第二套排序。
                    _enum_c.sort(key=_rank_key, reverse=True)
                    _top_enum = _enum_c[0]
                    try:
                        ctx._pick_diag = {
                            "branch": "enum_preferred",
                            "picked": (getattr(_top_enum, "answer", "") or "")[:60],
                            "n_enum_candidates": len(_enum_c),
                            "support_n": int(getattr(_top_enum, "_support_n", 1) or 1),
                            "enum_votes": int(getattr(_top_enum, "correct_votes", 0) or 0),
                        }
                    except Exception:  # noqa: BLE001
                        pass
                    self.record(ctx, "finalize",
                                "题面要求『所有』→ 枚举形态候选优先"
                                "（{} 个**合法**枚举候选，按统一 _rank_key：票数→"
                                "独立复现数→置信度→答案形态 排序）".format(
                                    len(_enum_c)))
                    return _top_enum
        except Exception:  # noqa: BLE001
            pass
        # 0) 聚类数据（来自 verifier）→ 找最佳簇中第一个候选
        best_cluster = getattr(ctx, '_best_cluster', None)
        if best_cluster:
            cid_set = set(getattr(best_cluster, 'candidate_ids', []))
            # 2026-09-20 修复（口径错配）：candidate_ids 里存的是**候选在列表中的
            # 下标**，不是 Candidate.id。三处证据：建簇处（verifier.py）对
            # Candidate 对象取的是 idx；两个消费侧 verifier.py:1207 与
            # orchestrator.py:2729 也都写成 `cids[0] < len(candidates)` 后取
            # `candidates[idx]`。原实现用 `c.id in cid_set` 匹配 ⇒ 候选列表一旦
            # 发生位移（3.6 段过滤 / 候选池封顶 6 / 6.5 段换候选），matching 为空、
            # 整条簇分支被静默跳过，下方"按 (票数, 置信度) 择优"的修复失效。
            matching = [c for _i, c in enumerate(ctx.candidates or [])
                        if _i in cid_set]
            if matching:
                # ★ 2026-09-17（M5）：簇内改为 **(票数, 置信度) 优先，最后才比推理长度**。
                # 原实现只按"推理最长"选，与正确性脱钩 —— 本文件 418-431 已自述
                # 003 曾因此把已正确的 `\boxed{0,2026}` 丢掉、最终只剩 `\boxed{2026}`。
                # ★ 2026-09-30（截图 #9）：再统一到 `_rank_key`。原局部键的**末位是
                #   `len(reasoning)`**（M5 时保留了这一项），仍与正确性无因果；
                #   且它读的是候选对象上的 `correct_votes`/`confidence`，而本分支的
                #   票数来源是 `ctx.verdicts`（按 id 索引）—— 两者可能不同源。
                #   现改为：先把 verdict 的票数回填到候选对象（`_rank_key` 读的是
                #   对象属性），再统一排序 ⇒ 全项目择优口径单一来源。
                _vm = {}
                for _v in (getattr(ctx, "verdicts", None) or []):
                    try:
                        _vm[int(getattr(_v, "id", -1))] = (
                            int(getattr(_v, "correct_votes", 0) or 0),
                            float(getattr(_v, "confidence", 0.0) or 0.0))
                    except Exception:  # noqa: BLE001
                        continue
                for _c in matching:
                    _hit = _vm.get(int(getattr(_c, "id", -1)))
                    if _hit is not None:
                        try:
                            _c.correct_votes = int(_hit[0])
                            _c.confidence = float(_hit[1])
                        except Exception:  # noqa: BLE001
                            pass
                matching.sort(key=_rank_key, reverse=True)
                return matching[0]

        # 1) 传统 verdict 置信度
        if ctx.verdicts:
            valid = [v for v in ctx.verdicts if v.total_votes > 0]
            if valid:
                return max(valid, key=lambda v: v.confidence)
            return max(ctx.verdicts, key=lambda v: v.confidence)

        # 2) 候选兜底
        if ctx.candidates:
            for c in ctx.candidates:
                if c.answer:
                    return c
            return ctx.candidates[0]
        return None

    @staticmethod
    def _group_option_sets(mv: dict) -> dict:
        """把 {答案字符串: 频次} 归并成 {选项字母集合: {"answers": [...], "votes": N}}。

        2026-09-13：供选择题「平票检测 + 差分定位」使用。只处理选项字母类答案。

        ⚠ 必须累加**票数**（`votes`），不能用 `len(answers)`——后者是"该集合有
        几种不同写法"（通常就是 1），会把任何分组都算成 1 票 ⇒ 误判平票。
        （实测教训：102 候选 B×4/AB×1/A×1，B 本应绝对多数，却因该口径错误
        触发差分检测，把答案从 B 改成 A，把本可答对的题改错。）
        """
        groups: dict = {}
        for _ans, _n in (mv or {}).items():
            _letters = re.findall(r"[A-E]", _ans)
            if not _letters:
                continue
            _k = frozenset(_letters)
            _g = groups.setdefault(_k, {"answers": [], "votes": 0})
            _g["answers"].append(_ans)
            try:
                _g["votes"] += int(_n)
            except (TypeError, ValueError):
                _g["votes"] += 1
        return groups

    def _objective_diff_probe(self, ctx: TaskContext, groups: dict) -> str:
        """选择题候选平票时的**差分检测**（2026-09-13 用户设计）。

        设计意图：当多种选项组合并列最高频（如 `AB×2` 与 `ABC×2`），
        不要盲目取其一 —— A、B 是共识，**争议只在于 C**。于是：
            争议项 = 并列组合的并集 − 交集（此处 = {C}）
        只对争议项做一次定向 LLM 验证，其余沿用共识，把预算花在真正的分歧点。

        例：
            AB×2  vs ABC×2   → 争议 {C}
            ABD×2 vs ABC×2   → 争议 {C, D}
            A×2   vs B×2     → 争议 {A, B}（交集为空，两个都验）

        返回修正后的答案字母串（共识 ∪ 判为正确的争议项）；
        无平票 / 无争议项 / 调用失败 → ""（调用方回退多数投票）。
        """
        try:
            if len(groups) < 2:
                return ""
            _max_n = max(g["votes"] for g in groups.values())
            _tops = [k for k, g in groups.items() if g["votes"] == _max_n]
            if len(_tops) < 2:
                return ""                       # 无平票（存在唯一最高票）→ 交给多数投票
            _inter = set.intersection(*[set(k) for k in _tops])
            _union = set.union(*[set(k) for k in _tops])
            _diff = sorted(_union - _inter)
            if not _diff:
                return ""
            _opt_text = {}
            try:
                from .question_type import extract_options
                _opt_text = dict(extract_options(ctx.problem or "") or [])
            except Exception:  # noqa: BLE001
                _opt_text = {}
            _diff_lines = [
                "- 选项 {}：{}".format(
                    L, _opt_text.get(L, "(题干未提取到该选项文本)"))
                for L in _diff]
            _sys = (
                "你是选择题审题专家。用户给你一道选择题，以及若干**存在分歧的选项**。"
                "请**只**针对这些分歧选项逐一判定其陈述是否正确，每个选项给出"
                "『正确』或『错误』并附一句理由；最后一行必须输出"
                "『【结论】: <这些选项中所有正确的字母>』（只写字母如 C 或 CD；"
                "若都不正确则写 无）。不要重述题目。"
            )
            _user = ("题目：\n{}\n\n以下选项在候选解答中存在分歧，请逐一判定：\n{}"
                     .format(ctx.problem, "\n".join(_diff_lines)))
            # 2026-09-13 超时护栏（口径照抄 verifier.py:334）：本阶段唯一 LLM 调用
            # 原先 max_tokens=65536 且无任何时间护栏 → 诱导长思考撞 LLMClient
            # 默认 180s 超时 + 1 次重试 ≈363s（实测 352/363/364s，占单题 1200s
            # 硬时限 30%）。deadline / 生成侧软截止已到 → 放弃差分检测，返回 ""
            # 由 _pick_best 回退到现成的多数投票结果。
            # 2026-09-13 修复（关键）：**不能**用 `gen_time_up()` 判断！
            # 它是"生成侧软截止"（= 单题 deadline 前 verify_reserve 秒），而
            # formatter 是流程的**最后一个阶段** ⇒ 走到这里时 `gen_time_up()`
            # **必然为 True** ⇒ 差分检测在 096/102 实测中**从未真正执行过**，
            # 全部静默回退多数投票（平票时 = 随机取第一个，正是用户指出的问题）。
            # 改为：只看"离单题硬限是否还够一次短调用"（max_tokens=512，
            # 约 20–40s；留 120s 余量以容纳一次重试）。
            if ctx.is_timed_out() or ctx.time_remaining() < 120:
                self.record(ctx, "finalize",
                            "选择题差分检测：剩余时间不足一次短调用，"
                            "跳过（回退多数投票）")
                return ""
            from .base import _normalize_chat_response
            # 2026-09-13：单次调用 → **最多 2 次**。原实现只调一次，且只认
            # `【结论】:` 一种写法，任一环节出问题就静默回退多数投票。
            # 现在：空响应/异常/**有输出但无结论**都会重试；失败写埋点。
            _text, _errs, _m = "", [], None
            for _attempt in range(2):
                try:
                    _resp = self.client.chat(
                        messages=[{"role": "system", "content": _sys},
                                  {"role": "user", "content": _user}],
                        # 2026-10-02 DeepSeek 适配：原 512 ⇒ 8192。原值基于「短直答 +
                        # prefill 抑制思维块」的 Intern-S 时代假设，对 reasoning 模型
                        # 必然截断（reasoning 先吃满预算、正文为空）。
                        temperature=0.0, max_tokens=8192,
                    )
                    _text = _normalize_chat_response(_resp) or ""
                    if not _text.strip():
                        _errs.append("attempt{}:empty".format(_attempt + 1))
                        continue
                    _m = (re.search(r"【结论】[:：]?\s*([A-E]+|无)", _text)
                          or re.search(r"(?:结论|答案|正确(?:的)?选项)\s*[:：]?\s*"
                                       r"([A-E]{1,5}|无)", _text))
                    if _m:
                        break
                    _errs.append("attempt{}:no_verdict".format(_attempt + 1))
                except Exception as _e:  # noqa: BLE001
                    _errs.append("attempt{}:{}".format(
                        _attempt + 1, type(_e).__name__))
            if not _m:
                try:
                    ctx._pick_diag = {
                        "branch": "diff_probe_no_verdict",
                        "errs": _errs,
                        "raw_tail": (_text or "")[-200:],
                    }
                except Exception:  # noqa: BLE001
                    pass
                return ""
            _v = _m.group(1)
            _ok = (set(_v) if _v != "无" else set()) & set(_diff)
            _ans = "".join(sorted(_inter | _ok))
            try:
                ctx._pick_diag = {
                    "branch": "formatter_diff_probe",
                    "tops": ["".join(sorted(t)) for t in _tops],
                    "diff": "".join(_diff),
                    "ok": "".join(sorted(_ok)),
                    "picked": _ans,
                }
            except Exception:  # noqa: BLE001
                pass
            self.record(
                ctx, "finalize",
                "选择题差分检测：并列 {} → 争议项 {} → 判对 {} → 修正答案 {}".format(
                    [''.join(sorted(t)) for t in _tops],
                    ''.join(_diff),
                    ''.join(sorted(_ok)) or '无',
                    _ans or '(空)'))
            return _ans
        except Exception:  # noqa: BLE001
            return ""

    def _pick_fallback(self, ctx: TaskContext, exclude_answer: str = "") -> str:
        """当最佳答案是拒绝/不完整回答时，从候选中找到更可靠的答案"""
        exclude = exclude_answer or ""
        # 优先从有效 verdicts 中找非拒绝/非不完整答案（按置信度降序）
        valid_verdicts = [v for v in ctx.verdicts if v.total_votes > 0]
        if valid_verdicts:
            for v in sorted(valid_verdicts, key=lambda x: x.confidence, reverse=True):
                ans = getattr(v, "answer", "") or ""
                # ★ 2026-09-16 审计修复：去掉 `len(ans) > 3`（同 :205 的理由）。
                #   本函数是**兜底换候选**路径，门槛过严会把合法短答案（A/AB/BCD）
                #   全部跳过、退回推理尾部散文 ⇒ 客观题必错。
                if (ans.strip()
                        and ans != exclude
                        and not _REFUSAL_RE.search(ans)
                        and not _INCOMPLETE_RE.search(ans)):
                    return ans
        # 从 candidates 中找非拒绝/非不完整答案
        if ctx.candidates:
            _cs = sorted(ctx.candidates, key=_rank_key, reverse=True)
            # ★ 2026-09-22：把"并列且无判别信号"这件事**显式暴露**出来。
            #   实测 011：两个候选的正确票数、置信度、答案形态**完全并列**
            #   （3/3 vs 3/3、conf 1.0 vs 1.0、都带 `\boxed`），此时**本地没有任何
            #   判别信号** —— 旧逻辑拿"推理更长者"当裁判，等于随机且系统性偏向啰嗦。
            #   本处只做两件事：
            #     ① 判据中性化（末键用答案紧凑度，不再用推理长度）；
            #     ② 把并列事实写进 diag 与 trace，使其**可统计、可追踪**。
            #   ⚠ 这不构成"解决了 011"：真正的解法是对并列候选做**外部验证**
            #   （符号等价 / 代回题设），已列入 CHANGES 待办，尚未实现。
            if len(_cs) >= 2 and _rank_key(_cs[0])[:3] == _rank_key(_cs[1])[:3]:
                self.record(ctx, "finalize",
                            "候选择优出现**无信号并列**（票数 / 置信度 / 答案形态全同）"
                            "→ 已按确定性规则择一，但该选择无证据支撑，标记 tie_unresolved")
                try:
                    _pd = getattr(ctx, "_pick_diag", None)
                    if isinstance(_pd, dict):
                        _pd["tie_unresolved"] = True
                        _pd["tie_pair"] = [(_cs[0].answer or "")[:40],
                                           (_cs[1].answer or "")[:40]]
                except Exception:  # noqa: BLE001
                    pass
            for c in _cs:
                ans = c.answer or ""
                # ★ 2026-09-16 审计修复：去掉 `len(ans) > 3`（同 :493 的理由）。
                if (ans.strip()
                        and ans != exclude
                        and not _REFUSAL_RE.search(ans)
                        and not _INCOMPLETE_RE.search(ans)):
                    return ans
                # 候选答案也是拒绝类，但推理足够长 → 提取尾部
                if c.reasoning and len(c.reasoning) > 200:
                    from utils.extract import extract_final_answer
                    fallback = extract_final_answer(c.reasoning)
                    if (fallback and len(fallback) > 2
                            and fallback != exclude
                            and not _REFUSAL_RE.search(fallback)
                            and not _INCOMPLETE_RE.search(fallback)):
                        return fallback
        return ""

    def _repair_truncated(self, ctx: TaskContext, answer: str) -> str:
        """2026-09-02 老师需求：截断答案续写补全（根治 -2x^{ 型截断）。

        截断信号：is_truncated_answer(answer) 为 True（LaTeX 半截/花括号不配对等）。
        用 LLM 从断点续写补全，最多 2 次；补全后仍截断则原样返回。
        """
        if not answer or not is_truncated_answer(answer):
            return answer
        try:
            from .base import _normalize_chat_response
            from utils.prefill import prefill_messages, stitch
            for attempt in range(2):
                if not is_truncated_answer(answer):
                    break
                # 2026-09-13 超时护栏（既有失败语义 = 原样返回 answer）：
                # deadline / 生成侧软截止已到 → 不再续写，直接落到函数末尾
                # `return answer`，与原有"补全失败不阻断"语义一致。
                # ⚠ 2026-09-16 修复（老逻辑漏改）：本行原先用 `ctx.gen_time_up()`，
                #   而**同文件 414-418 行已明确论证不能这么用** ——
                #   formatter 是流程最后一个阶段，走到这里 `gen_time_up()` **必然为 True**
                #   ⇒ 截断答案续写**从未真正执行过**，只能原样交截断答案。
                #   414-421 与 589-593 两处当时都改了，**这处漏改**，属典型"同一 bug
                #   修了两处漏第三处"。现对齐 421 行的口径：只看硬限与真实剩余时间。
                if ctx.is_timed_out() or ctx.time_remaining() < 120:
                    self.record(ctx, "finalize",
                                "截断答案续写：时间已到，跳过续写（原样返回）")
                    break
                tail = answer[-200:]  # 断点前片段作锚
                msgs = [
                    {"role": "system", "content":
                        "你是数学解答补全器。下面是一段被截断的解答结尾，"
                        "请从断点处继续，把最终答案补全为完整、规范的数学答案。"
                        "只输出续写内容（从断点开始），不要重复已给出的片段。"},
                    {"role": "user", "content": tail},
                ]
                resp = self.client.chat(
                    messages=prefill_messages(msgs, "【续写】: "),
                    temperature=0.0, max_tokens=65536,
                )
                text = _normalize_chat_response(resp)
                if not text:
                    break
                text = stitch("【续写】: ", text)
                m = re.search(r"【续写】[:：]?\s*([\s\S]+)", text)
                piece = m.group(1).strip() if m else text.strip()
                if not piece:
                    break
                # 防重复拼接：piece 若以 answer 尾部开头则剪掉重复段
                for cut in (80, 50, 30):
                    dup = answer[-cut:]
                    if dup and piece.startswith(dup):
                        piece = piece[cut:]
                        break
                answer = (answer + piece).strip()
                self.record(ctx, "finalize",
                            f"截断答案续写补全（第{attempt + 1}次）→ {answer[:120]}")
        except Exception:  # noqa: BLE001  补全失败不阻断，原样返回
            pass
        return answer

    def _emergency_answer(self, ctx: TaskContext) -> str:
        """2026-09-02 占位符兜底：最精简直答（prefill 答案前置，防截断）。

        主流程子目标全失败时 final 可能是占位符，续写救不回；
        直接让模型只输出【最终答案】，一次调用拿可用答案。
        """
        try:
            from .base import _normalize_chat_response
            from utils.prefill import prefill_messages, stitch
            sys_p = ("你是数学解题器。请直接给出题目的最终答案"
                     "（数值/表达式/集合），不要任何解释或推导过程。"
                     "格式：【最终答案】: <答案>")
            # 2026-09-13 超时护栏（既有失败语义 = 返回 ""，调用方原样输出）。
            # 2026-09-13 晚改判据（用户硬要求「无论超没超时都要把答案生成出来」）：
            # 原判据 `is_timed_out() or gen_time_up()` 把这条**最后的答案产出路径**
            # 也一起关掉了 —— 实测 010/016 剩余 -30s / -105s 时必然跳过，只能交占位符。
            # 现改为：
            #   · 硬墙（is_timed_out）已过或余量 < 45s → 仍跳过（跨硬墙会被平台杀
            #     进程组、整题计 C，代价比交白卷更大）；
            #   · 生成侧软截止（gen_time_up）**不再拦截** —— 它是为"验证"预留的余量，
            #     而执行到这里时验证阶段早已结束，没有可牺牲的下游了。
            # ★ 2026-10-07（C）：改为**调用时实时读**（原先 import 期常量）。
            _min_sec = _final_answer_min_sec()
            if ctx.is_timed_out() or ctx.time_remaining() < _min_sec:
                self.record(ctx, "finalize",
                            f"紧急直答：余量不足（{ctx.time_remaining():.0f}s < "
                            f"{_min_sec:.0f}s），跳过（交上层最终兜底）")
                return ""
            resp = self.client.chat(
                messages=prefill_messages(
                    [{"role": "system", "content": sys_p},
                     {"role": "user", "content": ctx.problem}],
                    "【最终答案】: ",
                ),
                temperature=0.0, max_tokens=_emergency_answer_max_tokens(),
            )
            text = _normalize_chat_response(resp)
            if not text:
                return ""
            text = stitch("【最终答案】: ", text)
            m = re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            ans = m.group(1).strip() if m else text.strip()
            # 去掉多余换行/包装，取首个完整行
            ans = ans.split("\n")[0].strip()
            if ans and not is_truncated_answer(ans):
                return ans
            return ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _diagnose_and_repair(answer: str, ctx: TaskContext) -> str:
        """
        答案质量终检 + 自动修复。

        检测项:
        - 42 幻觉兜底（孤立的 42）
        - 截断 LaTeX（未闭合的 $ / { / \\begin）
        - markdown 污染（**...** 残留）
        - 多余包装文字

        返回修复后的答案（或原答案）。
        """
        if not answer or answer == "无法求解":
            return answer

        fixed = answer

        # 1. markdown 污染检测与修复
        if "**" in fixed or "__" in fixed:
            fixed = fixed.replace("**", "").replace("__", "")
            logger.info("Formatter 终检: 移除 markdown 标记")

        # 2. 42 幻觉检测（孤立的 42 / 42.0）
        stripped = fixed.strip()
        if re.fullmatch(r"42(?:\.0+)?", stripped):
            logger.warning("Formatter 终检: 检测到 42 兜底幻觉 → 尝试回溯")
            # 从其他候选中找到非 42 的答案
            for v in (ctx.verdicts or []):
                ans = (getattr(v, "answer", "") or "").strip()
                if ans and not re.fullmatch(r"42(?:\.0+)?", ans) and len(ans) > 1:
                    return ans
            for c in (ctx.candidates or []):
                ans = (c.answer or "").strip()
                if ans and not re.fullmatch(r"42(?:\.0+)?", ans) and len(ans) > 1:
                    return ans

        # 3. 截断 LaTeX 检测
        if re.search(r"\\begin\{[^}]*\}\s*$", fixed):
            logger.warning("Formatter 终检: 答案以 \\begin 结尾（截断）→ 尝试补全")
            # 从 reasoning 找对应的完整表达式
            for c in (ctx.candidates or []):
                if not c.reasoning:
                    continue
                env_match = re.search(
                    r"\\begin\{([^}]+)\}.*?\\end\{\1\}",
                    c.reasoning, re.DOTALL,
                )
                if env_match:
                    return env_match.group().strip()
        # 未闭合的 $ 或 {
        if fixed.count("$") % 2 == 1:
            fixed = fixed.rstrip("$")  # 移除不配对的 $
        open_braces = fixed.count("{") - fixed.count("}")
        if open_braces > 0:
            fixed = fixed + "}" * open_braces  # 补全大括号

        # 4. 多余包装文字剥离（如「因此答案是 x」→「x」）
        wrapped = re.match(
            r"^(?:因此|所以|故|综上[所]?述|答案为?|最终答案[为是]?)[,，:：]?\s*(.+?)\s*(?:。|$)",
            fixed, re.DOTALL | re.IGNORECASE,
        )
        if wrapped and len(wrapped.group(1)) > 1:
            inner = wrapped.group(1).strip()
            if inner != fixed.strip():
                logger.info("Formatter 终检: 剥离包装文字")
                return inner

        return fixed
