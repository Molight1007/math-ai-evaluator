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

logger = logging.getLogger("MathPilot")

# 2026-09-13 晚：紧急直答（最终兜底）所需的最小剩余时间（秒）。
# 这是"无论超没超时都要产出答案"的最后一环 —— 留 45s 让它有机会跑完一次
# 短直答（prefill 答案前置 + 小 max_tokens，实测正常 1–3s）。
_FINAL_ANSWER_MIN_SEC = float(os.getenv("FINAL_ANSWER_MIN_SEC", "45"))
# 紧急直答的输出上限（token）。旧值 65536 = 允许它写一整篇论文，
# 与"只要一行答案"的 prefill 语义矛盾，且在 120s 读超时下极易被截断。
# 直答只需一行：512 足够，且能显著提高"一定拿到答案"的成功率。
_EMERGENCY_ANSWER_MAX_TOKENS = int(os.getenv("EMERGENCY_ANSWER_MAX_TOKENS", "512"))

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


# ★ 2026-09-17 新增：工具调用 XML 残留标签（用于判定"这不是答案"）。
# 实测 official112-025：6 个候选里 5 个 answer 就是字面量 `</tool_call>`；
# 而原 `_REFUSAL_RE` / `_MISSING_ANSWER_RE` / `_INCOMPLETE_RE` 全是"拒绝词
# 词表"，对这类结构残留**全部漏检**，脏文本被当合法答案直接提交。
_TOOL_TAG_RE = re.compile(
    r"</?tool_calls?>|</?function\b|<parameter=|</parameter>",
    re.IGNORECASE,
)

# ★★ 2026-09-17 补强：实测发现上面的判据**只拦得住工具标签** —— 配套的
# `utils.extract._looks_like_reasoning_fragment` 对下列全部 5 类真实脏答案
# **都返回 False**（已逐例实测）。故此处按**实测形态**补三类结构信号：
#   · `步骤8：重新思考——正确的下界构造`（002 候选）→ 步骤/思考标签
#   · `从 $N$ 倒推：若从位置 $k`（032 最终答案）→ 推理连接词
#   · `a_wins = analyze_game(N)`（032 候选）→ Python 代码
#   · `subset sum approximation bounded integers ...`（013 候选）→ 英文检索词
# ⚠ 已知未覆盖（有意）：`509040-2*169680` 这类**未求值表达式** —— 它与
#   `\binom{2k}{k}^2` 等合法表达式答案形态难分，判错代价高于收益，故不拦。
_STEP_LABEL_RE = re.compile(
    r"^\s*(?:步骤\s*\d|第\s*[0-9一二三四五六七八九十]+\s*步|Step\s*\d"
    r"|\d+\s*[.、)]\s*【)"
    r"|重新思考|让我们(?:来)?(?:看|想|计算|考虑)",
    re.IGNORECASE,
)
# 推理连接词：正常"答案"不会带"倒推 / 由此 / 综上"这类**过程**措辞。
# 实测 032 提交的最终答案就是 `从 $N$ 倒推：若从位置 $k` 这样的推理碎片。
# 放在 has_math 闸门**之外**：该碎片含 `$`，会被"疑似数学式"跳过。
_REASONING_CONNECTIVE_RE = re.compile(
    r"倒推|由此可见|同理可得|可以看出|注意到|综上|我们需要")
_PY_ASSIGN_CALL_RE = re.compile(r"^[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*\(")
_PY_KEYWORD_RE = re.compile(
    r"(?<![\w.])(?:def|import|return|assert|print|lambda|while|elif)\b")
# 英文检索词：足够长、足够多空格、纯 ASCII 且只含词/数字/连字符/斜杠/加号。
_ENGLISH_QUERY_MIN_LEN = 50
_ENGLISH_QUERY_MIN_SPACES = 7
_ENGLISH_QUERY_ALLOWED = re.compile(r"^[A-Za-z0-9\s\-+/]+$")
# ★★ 2026-09-18 再补强：实测**最终答案**本身是"过程叙述"——模型把
#   "我接下来要做什么"当成答案提交，且因句子含 `$` 而穿过 has_math 闸门：
#     · `搜索已知结论：这个问题看起来像是一个已知的组合数学问题。也许答案是
#        $2^{k+1}$ 或 $2 \\cdot 4^{k-1}$ 之类的。让我用 web_search 查找类似问题。`（020）
#     · `继续找规律，目前 type B：2, 8, 10。`（032）
#     · `步骤11：搜索已知结论`（025）
#     · `让我搜索 $x^4 + 5$ 的分裂域次数。`（086 候选）
#   ⚠ 原 `_STEP_LABEL_RE` 只写了 `让我们`，**漏了 `让我`** —— 这一字之差是本轮
#     020/025/086 三题漏检的直接原因。
#   与 `_REASONING_CONNECTIVE_RE` 同样放在 has_math 闸门**之外**执行。
_PROCESS_NARRATIVE_RE = re.compile(
    r"让我(?:们)?(?:先|再|来)?(?:搜索|用|查|看看|想|计算|考虑|尝试|重新审视|重新思考)"
    r"|搜索(?:一下|已知结论|相关(?:数学)?结论|类似)"
    r"|继续(?:找规律|寻找|搜索)"
    r"|目前\s*(?:type|类型|得到|发现|只)"
    r"|文本提到"
    r"|也许答案(?:是|可能)"
    r"|这个(?:问题|题)看起来"
    r"|看起来像是(?:一个)?已知"
    # ★ 2026-09-18（审计发现，086 实测仍漏）：
    r"|在答案中[，,]?\s*通常接受"
    r"|但通常这类题的标准答案"
    r"|通常这类题的?标准答案"
    r"|对于[^，。]{0,12}类似",
    re.IGNORECASE,
)
# 含这些记号即视为"疑似数学式"，**不再**按代码/英文词串判定，避免误杀。
_MATH_MARKERS = ("\\", "{", "}", "$", "^")


def _looks_like_non_answer(text: str) -> bool:
    """2026-09-17 新增：结构化"是否像合法答案"检查（拒绝词表之外的脏答案）。

    背景：本文件原只有三条**拒绝词**正则，实测对下列脏答案全部漏检：
      - `</tool_call>`（official112-025：5/6 候选）；
      - `a_wins = analyze_game(N)`（032：代码片段）；
      - `从 $N$ 倒推：若从位置 $k`（032：推理碎片）；
      - `步骤8：重新思考——正确的下界构造`（002：步骤标签）；
      - `subset sum approximation bounded integers ...`（013：英文搜索词）。
    这里只做"明显不是答案"的**结构**判定：空串 / 工具标签 / 步骤与思考标签 /
    推理连接词 / Python 代码 / 英文检索词串 / 推理碎片。
    刻意**不**使用 `is_valid_final_answer` —— 它会误杀合法中文答案
    （如 gold `有限差分法、有限元法`）。import 惰性化并 try/except 兜底。
    """
    if not text or not str(text).strip():
        return True
    t = str(text).strip()
    try:
        if _TOOL_TAG_RE.search(t):
            return True
    except Exception:  # noqa: BLE001
        pass
    # —— 步骤 / 思考标签 / 推理连接词 / 过程叙述：推理过程的措辞，不可能是答案 ——
    try:
        if (_STEP_LABEL_RE.search(t) or _REASONING_CONNECTIVE_RE.search(t)
                or _PROCESS_NARRATIVE_RE.search(t)):
            return True
    except Exception:  # noqa: BLE001
        pass
    # —— 含 LaTeX 记号（\ { } $ ^）时视为疑似数学式，跳过代码/英文词串判定 ——
    has_math = any(ch in t for ch in _MATH_MARKERS)
    if not has_math:
        try:
            if _PY_ASSIGN_CALL_RE.match(t) or _PY_KEYWORD_RE.search(t):
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if (len(t) >= _ENGLISH_QUERY_MIN_LEN
                    and t.count(" ") >= _ENGLISH_QUERY_MIN_SPACES
                    and _ENGLISH_QUERY_ALLOWED.match(t)):
                return True
        except Exception:  # noqa: BLE001
            pass
    try:
        from utils.extract import _looks_like_reasoning_fragment
        if _looks_like_reasoning_fragment(t):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


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
                    best = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))
                    answer = best.answer if best.answer and len(best.answer) > 2 else (
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
                self.record(ctx, "finalize", f"占位符答案 → 紧急直答: {direct[:120]}")
                answer = direct
            else:
                self.record(ctx, "finalize",
                            "答案不可用（空/占位符）且紧急直答未得，交上层最终兜底")

        # ★ 2026-09-18（审核发现）：**这是 `ctx.final_response` 的第 4 个直写点**。
        # 另外 3 个（零票兜底直答 / 6.5 重做 / 6.5 换候选）已改用
        # `Orchestrator._set_final_response`（带非答案闸门），本行此前是漏网的。
        # 本模块自带 `_looks_like_non_answer`，直接复用，避免跨模块反向 import。
        _fr_txt = format_response(answer)
        if str(_fr_txt or "").strip() and not _looks_like_non_answer(_fr_txt):
            ctx.final_response = _fr_txt
        else:
            self.record(ctx, "finalize",
                        "最终答案被判为非答案形态 → 不覆盖 ctx.final_response，"
                        "交上层最终兜底：%s" % str(_fr_txt)[:80])
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
        """
        选择最优答案（BUG-13 修复：共识加权）。
        优先使用聚类结果中置信度最高且规模最大的簇；其次使用传统 verdict 置信度。
        """
        # 2026-09-13：选择题答案多数投票（OBJECTIVE_MAJORITY_VOTE=1 时）。
        # 必须放在 best_cluster 分支**之前**：best_cluster 是 verifier 聚类，
        # 且簇内再按"推理长度"选（下见 #0），对客观题（答案形态稳定、候选
        # 易因裸字母 `A` 与 `\boxed{A}` 的格式差异被聚类拆散 / 簇内择优失真）
        # 直接做答案频次投票更可靠——这正是 102 候选 4B/2A 却被选 A 的根因。
        import os as _os
        # 2026-09-14：选择题**优先采纳「逐项判定」候选**（origin="itemwise"）。
        # 依据：它是**逐个选项验证过**的结论（有共享基准、有逐项依据），可靠性
        # 高于"整体求解"候选。实测 #107 逐项判定正确得出 D（gold=D），却因候选池
        # 里有 5 个整体求解的 C，被 5:1 多数投票淹没 ⇒ 必须让**有依据的结论**
        # 优先于**数量多数**。置 OBJECTIVE_ITEMWISE_PRIORITY=0 可回退。
        if (_os.environ.get("OBJECTIVE_ITEMWISE_PRIORITY", "1") == "1"
                and getattr(ctx, "question_type", "") == "选择题"):
            _iw = [c for c in (getattr(ctx, "candidates", None) or [])
                   if getattr(c, "origin", "") == "itemwise"
                   and (getattr(c, "answer", "") or "").strip()]
            if _iw:
                _iw.sort(key=lambda c: len(c.reasoning or ""), reverse=True)
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
        if (_os.environ.get("OBJECTIVE_MAJORITY_VOTE", "0") == "1"
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
                        _enum_c.append(_c)
                if _enum_c:
                    # ② 排序：先票数、再置信度、最后推理长度（原实现只看长度）
                    _enum_c.sort(
                        key=lambda c: (
                            int(getattr(c, "correct_votes", 0) or 0),
                            float(getattr(c, "confidence", 0.0) or 0.0),
                            len(getattr(c, "reasoning", "") or ""),
                        ),
                        reverse=True)
                    try:
                        ctx._pick_diag = {
                            "branch": "enum_preferred",
                            "picked": (getattr(_enum_c[0], "answer", "") or "")[:60],
                            "n_enum_candidates": len(_enum_c),
                            "enum_votes": int(getattr(_enum_c[0], "correct_votes", 0) or 0),
                        }
                    except Exception:  # noqa: BLE001
                        pass
                    self.record(ctx, "finalize",
                                "题面要求『所有』→ 枚举形态候选优先"
                                "（{} 个**合法**枚举候选，按票数/置信度/推理长度排序）".format(
                                    len(_enum_c)))
                    return _enum_c[0]
        except Exception:  # noqa: BLE001
            pass
        # 0) 聚类数据（来自 verifier）→ 找最佳簇中第一个候选
        best_cluster = getattr(ctx, '_best_cluster', None)
        if best_cluster:
            cid_set = set(getattr(best_cluster, 'candidate_ids', []))
            matching = [c for c in (ctx.candidates or []) if c.id in cid_set]
            if matching:
                # ★ 2026-09-17（M5）：簇内改为 **(票数, 置信度) 优先，最后才比推理长度**。
                # 原实现只按"推理最长"选，与正确性脱钩 —— 本文件 418-431 已自述
                # 003 曾因此把已正确的 `\boxed{0,2026}` 丢掉、最终只剩 `\boxed{2026}`。
                _vm = {}
                for _v in (getattr(ctx, "verdicts", None) or []):
                    try:
                        _vm[int(getattr(_v, "id", -1))] = (
                            int(getattr(_v, "correct_votes", 0) or 0),
                            float(getattr(_v, "confidence", 0.0) or 0.0))
                    except Exception:  # noqa: BLE001
                        continue
                matching.sort(
                    key=lambda c: (_vm.get(int(getattr(c, "id", -1)), (0, 0.0)),
                                   len(c.reasoning or "")),
                    reverse=True)
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
                        temperature=0.0, max_tokens=512,
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
            for c in sorted(ctx.candidates, key=lambda x: len(x.reasoning or ""), reverse=True):
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
            if ctx.is_timed_out() or ctx.time_remaining() < _FINAL_ANSWER_MIN_SEC:
                self.record(ctx, "finalize",
                            f"紧急直答：余量不足（{ctx.time_remaining():.0f}s < "
                            f"{_FINAL_ANSWER_MIN_SEC:.0f}s），跳过（交上层最终兜底）")
                return ""
            resp = self.client.chat(
                messages=prefill_messages(
                    [{"role": "system", "content": sys_p},
                     {"role": "user", "content": ctx.problem}],
                    "【最终答案】: ",
                ),
                temperature=0.0, max_tokens=_EMERGENCY_ANSWER_MAX_TOKENS,
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
