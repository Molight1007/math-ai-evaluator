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
# 2026-10-02 DeepSeek 适配：env 默认 512 ⇒ 8192。原值基于「直答只需一行 + prefill
# 抑制思维块」的 Intern-S 时代假设，对 reasoning 模型必然截断（reasoning 先吃满
# 预算、正文为空）。仍可用 EMERGENCY_ANSWER_MAX_TOKENS 覆盖。
_EMERGENCY_ANSWER_MAX_TOKENS = int(os.getenv("EMERGENCY_ANSWER_MAX_TOKENS", "8192"))

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

# ★ 2026-09-21 新增：**段首叙述形态**（受控、锚定串首，避免误杀答案中的连接词）。
#   实测 0921 arm2c2t：6.5 重做循环把过程叙述推成最终答案并提交 ——
#     · `因此a_{2025} = 2026。`（003；含 `{}` ⇒ 触发 has_math 跳过代码/英文判定，
#        而「因此」不在 `_REASONING_CONNECTIVE_RE` 的 7 个词里 ⇒ 全链漏检）
#     · `最终正确的上界证明：考虑 $2|F|$ 个"端点"（…`（004，187 字长段）
#     · `所以对手（选5个数的人）会试图构造5个数…`（002）
#   规则 = 段首连接词 ∨ 段首"结论文档标签"（…证明： / 结论： / 思路： …）。
#   ⚠ 只锚定**串首**（无 re.MULTILINE）⇒ 答案中段出现「因此」不受影响。
#   ⚠ 实测对照集 16 条合法答案（各题 gold + 正常候选 + `解：x=1` / `答：42` /
#     `无解` / 区间 / 分数 / 中文列举）**零误杀**。
#   ⚠ 刻意**不**拦纯数值（`20`）与数学碎片（`p=1：f(f(d)) = f(2) + 1。`）——
#     形态上与合法答案难分，判错代价高于收益；这两类由 orchestrator 6.5 的
#     「未过审核 → 回滚到重做前答案」（2026-09-21）兜住。
_LEAD_NARRATIVE_RE = re.compile(
    r"^\s*(?:因此|所以|于是|从而|因而|由此|进而|继而|这样一来|这表明|这说明"
    r"|也就是说|换句话说|综上)"
    r"|^\s*.{0,14}(?:证明|论证|推导|结论|思路|分析|讨论)\s*[:：]")
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
    #    ★ 2026-09-21 增加 `_LEAD_NARRATIVE_RE`（段首连接词 / 结论文档标签）。
    try:
        if (_STEP_LABEL_RE.search(t) or _REASONING_CONNECTIVE_RE.search(t)
                or _PROCESS_NARRATIVE_RE.search(t)
                or _LEAD_NARRATIVE_RE.search(t)):
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


def _answer_form_score(ans) -> int:
    """答案「形态分」—— 与正确性相关；**推理长度与正确性无因果关系**。

    ★ 2026-09-22（用户口径：「制定正确的逻辑，删去原本不合理的逻辑」）：
    本项目已三次修复「按推理长度选答案」（09-16 枚举分支、09-17 簇内分支、
    09-20 长答案重提取），但**仍有三处遗漏**（本文件 259 / 510 / 876 行）。
    实测 011：票数与置信度**完全并列**的两个候选，交给「推理更长者」裁决
    （18015 vs 6938 字符），选中错答 —— 正确候选就在池里。
    ⇒ 判据改为「答案形态」：像答案的（boxed / 短数值表达式）优于散文。
    """
    s = str(ans or "").strip()
    if not s:
        return 0
    if "\\boxed" in s:
        return 3
    if len(s) <= 40 and not re.search(r"[\u4e00-\u9fff]{6,}", s):
        return 2
    if len(s) <= 40:
        return 1
    return 0


def _rank_key(c):
    """候选择优的**统一**排序键。

    ★ 2026-09-30（截图 #9）扩为五项：
        ① `correct_votes`   —— 验证器给该候选投了几张对票；
        ② **`_support_n`**  —— ★新增：池里有几个**独立候选**写出了同一结论；
        ③ `confidence`      —— 正确票 / 有效票；
        ④ `_answer_form_score` —— 「最像答案」（boxed > 短数学式 > 短文本 > 散文）；
        ⑤ 答案更短（仅确定性收尾）。

    ② 的插入位置有意在 `confidence` **之前**：用户口径「候选数量与逻辑通顺度
    都要是指标」，而 `support` 正是"候选数量"在单候选身上的投影。
    为什么它该压过 `confidence`：
      · 一条结论被 3 个独立候选复现 ⇒ 是 self-consistency 意义上的**共识**；
      · 单个候选自评 3/3 票 ⇒ 只是"验证器没看出它错"（本项目实测验证器误报率 56%）。
    历史上本项目已三次因"只看单一指标"丢过正确答案（003/011/014），故此处
    刻意**新增指标而非替换指标** —— 票数仍是第 1 键，`support` 只在票数相同时起作用，
    属零风险加性改动。

    ⚠ `_support_n` 由调用方（`_pick_best` 等）按**当前候选池**预先算好并挂到候选对象上；
    未挂时 `getattr` 兜底为 1（= "它自己就是一票"，不罚也不奖），
    这样所有既有调用点不传 support 时行为与改动前**完全一致**。

    全项目凡需在候选间择优处**一律复用本函数**，禁止再出现「只看推理长度」的
    局部实现（历史上已因此丢掉过正确答案：003 的 `\\boxed{0,2026}` 曾输给 0 票的
    `\\boxed{0,1,2,\\ldots}`；011 的正确候选曾输给更啰嗦的错答）。
    末项取「答案更短者优先」仅为**确定性收尾**（避免退化成插入序/随机），
    不代表长答案更差或更好。
    """
    ans = str(getattr(c, "answer", "") or "")
    return (
        int(getattr(c, "correct_votes", 0) or 0),
        int(getattr(c, "_support_n", 1) or 1),
        float(getattr(c, "confidence", 0.0) or 0.0),
        _answer_form_score(ans),
        -len(ans),
    )


def _attach_support(candidates) -> dict:
    """把「独立复现数」挂到每个候选的 `_support_n` 上，返回 support 表。

    ★ 2026-09-30（截图 #9）：「候选数量」作为指标的**落地方式**。
    调用点在 `_pick_best` 开头（择优之前），因此后续所有走 `_rank_key` 的
    排序（逐项判定优先、簇内择优、verdict 兜底、兜底池）都自动受益。

    刻意**不**改 `_rank_key` 的签名 —— 它是模块级纯函数、无池上下文，
    且全项目多处直接调用（含单元测试）。把"池"的知识留在调用方，
    是本次实现的最小侵入路径。

    ⚠ 幂等：重复调用只覆盖同值，无副作用。任何异常一律忽略（择优绝不能被埋点搞挂）。
    """
    try:
        _m = _answer_support(candidates)
        for _c in (candidates or []):
            try:
                setattr(_c, "_support_n", _support_of(_c, _m))
            except Exception:  # noqa: BLE001
                pass
        return _m
    except Exception:  # noqa: BLE001
        return {}


# ----------------------------------------------------------------------
# 2026-09-30（截图 #9）：**「最像答案」+ 证据量 + 可信度门槛**
# ----------------------------------------------------------------------
# 用户原话：「投票要选出里面最像答案的一个，候选数量与逻辑通顺度都要是指标，
#           同时要有可信度要求（太低＝全军覆没）」。
#
# 现状拆解（已核验）：
#   · 「最像答案」⇒ `_answer_form_score`（boxed 3 分 / 短数学式 2 分 / 短文本 1 分
#     / 散文 0 分）已在 `_rank_key` 第 3 位生效 —— **该项已有基础**；
#   · 「候选数量」⇒ **完全没有**被当作指标。原 `_rank_key` 只看「该候选拿到几票」，
#     不看「这个结论在池里被**几个不同候选独立复现**」。
#     二者语义不同：一条结论若只被 1 个候选写出（哪怕它自评 3/3 票），
#     与「3 个独立候选都写出同一答案」相比，后者证据强得多
#     （self-consistency 的原始口径就是"独立采样间的一致性"，不是"单候选自评"）。
#   · 「可信度要求」⇒ 散落在 `accept_confidence=0.6`（AcceptGate）与硬编码 `< 0.5`
#     （5.5 低置信度复核），**没有**在"选答"这个动作上做统一闸门。
#
# 设计纪律（遵守"一次只改一项"与"宁缺勿滥"）：
#   ① 只做**加性**指标：`_answer_support` 是新增的第 2 排序键，不删除任何既有键；
#   ② 所有新闸门默认**不改变行为**（`pick_confidence_floor` 默认 0.0 = 关闭）；
#   ③ 每个新函数都是纯函数，可被单元测试直接覆盖，绝不抛异常。
def _answer_support(candidates, key_of=None) -> dict:
    """统计**答案归一化后**每个结论被多少个**独立候选**复现。

    返回 ``{归一化答案: 候选个数}``。用途 = 给"候选数量"这个指标提供口径。

    ⚠ 与本文件既有的"票数"区别：
      · 票数（`correct_votes`）= **验证器对同一个候选投了几张对票**；
      · 本函数 = **池里有几个不同候选写出了这个结论**（独立复现）。
    两者都是指标，不是替代关系 —— 故本函数只新增排序键，不覆盖票数。

    归一化走 `AnswerOracle.strip_wrappers`（剥 `\\boxed{}` 等外壳）后 `strip().lower()`
    —— 与 `_are_answers_equivalent` 同源口径，避免 `\\boxed{5}` 与 `5` 被算成两个结论。
    任何异常一律返回空 dict（绝不阻断选答）。
    """
    out: dict = {}
    try:
        if not candidates:
            return out
        try:
            from .answer_oracle import AnswerOracle as _AO
        except Exception:  # noqa: BLE001
            _AO = None
        for _c in candidates:
            _a = ((key_of(_c) if key_of else getattr(_c, "answer", "")) or "")
            _a = str(_a).strip()
            if not _a or _looks_like_non_answer(_a):
                continue
            if _AO is not None:
                try:
                    _a = _AO.strip_wrappers(_a) or _a
                except Exception:  # noqa: BLE001
                    pass
            _k = _a.strip().lower()
            if not _k:
                continue
            out[_k] = out.get(_k, 0) + 1
    except Exception:  # noqa: BLE001
        return {}
    return out


def _support_of(candidate, support_map) -> int:
    """取某候选的「独立复现数」；查不到记 1（它自己就是一票，不该被罚成 0）。"""
    try:
        if not support_map:
            return 1
        ans = str(getattr(candidate, "answer", "") or "").strip()
        if not ans:
            return 1
        try:
            from .answer_oracle import AnswerOracle as _AO
            ans = _AO.strip_wrappers(ans) or ans
        except Exception:  # noqa: BLE001
            pass
        return int(support_map.get(ans.strip().lower(), 1) or 1)
    except Exception:  # noqa: BLE001
        return 1


def _passes_confidence_floor(candidate, floor: float) -> tuple:
    """★ 可信度门槛：低于底线的候选**不得**被选为终答（返回 ``(是否放行, 原因)``）。

    用户口径：「可信度要求（太低＝全军覆没）」——
    即"低可信度答案提交出去几乎必错，等于整题白做"，所以宁可**显式记录**
    "本次无候选达线"也不要静默地挑一个最弱的交上去。

    判定用**双指标**（两条都看，任一条成立即放行）：
      ① `confidence`（= 正确票/有效票）≥ floor；
      ② `correct_votes` ≥ 1 且 `total_votes` ≥ 1 —— 即"**至少有一张真实的正确票**"。
         为什么要加 ②：`confidence` 在 total_votes=0（全弃权票）时被定义为 0.0，
         但那是**基础设施故障**（LLM 超时/输出不可解析），不是"被判错"
         —— 与 `Verdict.abstain` 的既有三态口径一致（故障不是反证）。
         若只按 ① 判，故障轮次的候选会被全部打成"不可信"，触发无谓的回退。

    `floor <= 0` ⇒ 恒放行（= 默认关闭，行为与改动前逐字一致）。
    """
    try:
        if float(floor or 0.0) <= 0.0:
            return True, "floor_disabled"
        _cv = int(getattr(candidate, "correct_votes", 0) or 0)
        _tv = int(getattr(candidate, "total_votes", 0) or 0)
        if _tv <= 0:
            # 全弃权票 = 故障，不是反证 ⇒ 放行并如实说明（不伪装成"可信"）
            return True, "no_effective_votes"
        _conf = float(getattr(candidate, "confidence", 0.0) or 0.0)
        if _conf >= float(floor):
            return True, "confidence_ok"
        if _cv >= 1:
            return True, "has_correct_vote"
        return False, "below_floor"
    except Exception:  # noqa: BLE001
        return True, "judge_error"


_CJK_PROSE_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
_ENUM_ITEM_MAX = 40


def _is_real_enumeration(core: str) -> bool:
    """core 是否为**真枚举答案**（而非"含逗号的散文 / 推导片段"）。

    ★ 2026-09-22 修复（"删去原本不合理的逻辑"）：原判据仅是
    `re.search(r"[,，;；、]")` ⇒ **任何含逗号的中文散文**都会被当成"枚举答案"，
    并在 `enum_preferred` 分支里**优先返回**（该分支直接 `return`，绕过后面全部
    选答逻辑）。实测 014：正确答案 995018（票数最高 2/3、置信度 0.667）
    被一条 **0 票的散文候选** 顶掉，只因后者含逗号 ⇒ 终答以散文输出，判分必错。

    现在的判据：按逗号/分号/顿号拆分后
      ① 至少 2 项；
      ② **每一项都必须是短数学对象** —— 长度 ≤ 40 且不含 4 个以上连续汉字
         （长中文短语 ⇒ 是句子而非数学对象）；
      ③ 项末不得是句末标点。
    宁缺勿滥：判否只是放弃"枚举优先"这条捷径，仍会走正常选答，不会更差。
    """
    s = str(core or "").strip()
    if len(s) < 3:
        return False
    parts = [p.strip() for p in re.split(r"[,，;；、]", s) if p.strip()]
    if len(parts) < 2:
        return False
    for p in parts:
        if len(p) > _ENUM_ITEM_MAX:
            return False
        if _CJK_PROSE_RE.search(p):
            return False
        if re.search(r"[。！？：]$", p):
            return False
    return True


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
        if isinstance(getattr(ctx, "_pick_diag", None), dict):
            _picked_final = str(ctx.final_response or "")
            if _picked_final and _picked_final != ctx._pick_diag.get("picked"):
                ctx._pick_diag["picked_pre_repair"] = ctx._pick_diag.get("picked")
                ctx._pick_diag["picked"] = _picked_final[:60]
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
