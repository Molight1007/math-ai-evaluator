# -*- coding: utf-8 -*-
"""赋值形态的「答案值」掩码（2.7 / 3 共用的纯函数，无 LLM、无外部数据）。

================================================================
它治的是什么
================================================================
`prompts/blueprint.py` 的硬性禁令第 1/3/4 条早就写明：

  · 「禁止在蓝图的任何字段里写出最终答案」；
  · 「`merge_strategy` 只回答"如何组合"……**不得给出合并后的数值或表达式**」；
  · 「收尾节点只承担归并动作，**不得内嵌归并结果**」。

但既有掩码 `sub_goal_solver._mask_asserted_values` 只覆盖**带断言词**的形态
（「最小值/答案/取值 + 为/是/等于 + 数字」以及若干英文句式），
**抓不到纯赋值** `T = (√5-1)/2`，而这正是实测最高频的泄漏形态：

    铁证 official112-002：`merge_strategy` 写 `T=(√5-1)/2`（gold = 1/2），
      5/5 次运行都写该值，服务器 7 次跑 002 全给该值；
    铁证 official112-001：`merge_strategy` 写 `T(m) = -4`（gold = 2-2m），
      且句尾贴「具体值由 n1/n2/n3 现场给出，本处不预设」的免责声明。

================================================================
为什么只看这两处、不看中间节点
================================================================
中间节点里的值**可能是合法骨架**：夹逼法要求把候选值写出来才能表达
「证明 d=90 可行 / d=89 不可行」（实测 official112 多题如此）。
对中间节点一律掩码会破坏可解信息，而代码无法区分「合法骨架」与「泄漏」
—— 这个区分只能由 4.x 的语义审核做，不是文本层能解决的。

⇒ 本模块只作用于 prompt 契约**明确规定不该有值**的两处：
  ① `merge_strategy`（"只回答如何组合"）；
  ② 收尾/归并节点的 `statement`（"只承担归并动作"）。

⚠ 判据是**结构位置 + 句式**，不含任何题库文本、题号、具体数值的白名单/
   黑名单 ⇒ 对任意题目一致适用，不存在针对某题调参的空间。
⚠ 只改**投影**（下传给求解/合并的文本），`ctx.blueprint` 里保留原文，
   可审计、可回滚（`存储不降级、投影显式`）。
"""

import re

# 值表达式允许出现的字符：ASCII 数学符号 + 常用希腊/根号 + 括号。
# 中文与全角标点一律作终止符 —— 「-4（所有 Sparkling 元组…）」只取到 `-4`。
_VALUE_CHARS = frozenset(
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ".+-*/^_()[]{}|\\,√π∞"
    "θαβγδλμσφω"
)

# 等号：排除 <= >= == != :=
_EQ_RE = re.compile(r"(?<![<>=!:])=(?!=)")

# 值里至少要有一个「数」的来源，否则视为裸变量（`T = x`）而非值断言
_HAS_NUM_RE = re.compile(r"[0-9√π∞θαβγδλμσφω]")

# 值长度上限（超过即整段话，不是值）
_MAX_VALUE_LEN = 48

# 「下界 -4」这类**无等号**的边界/答案断言（prompts/blueprint.py 反例的写作惯例：
#   ✗ `"statement": "由 n1、n2 得最终答案 1012"`、✗ `"上界为 floor((n-1)/2)=1012"`）。
# 只给**锚点**，值本体由 `_scan_value` 统一扫（等号后与锚点后走同一套判据）。
_NAMED_RE = re.compile(
    r"(?:最终答案|答案为|最终取值|最小取值|最大取值|答案|结果"
    r"|下界|上界|最小值|最大值|最优值|最小整数|最大常数)"
    r"(?:\s*(?:为|是|等于|即|[:：])\s*|\s+)")

MASK_PLACEHOLDER = "[待求解值：由子目标结果现场确定]"


def _is_value_char(ch: str) -> bool:
    """值表达式允许出现的字符（中文/全角标点一律作终止符）。"""
    return ch in _VALUE_CHARS


# LaTeX 命令词（含拉丁字母，但属排版记号，不算"自由变量"）
_LATEX_CMD_RE = re.compile(
    r"\\(?:[dt]?frac|sqrt|cdot|times|pi|infty|left|right"
    r"|text|mathrm|boxed|displaystyle|,|;|!|quad)")


def _has_free_latin(val: str) -> bool:
    """值里是否含**自由拉丁变量**（`2k` / `r^{i-1}` / `2-2m`）。

    含 ⇒ 它是关系式/通项的一片，掩掉会破坏等式（`n²-n = 2k` → `n²-n = [值]`
    丢掉了 `k`），**不掩**。不含（纯数 / 根式 / 分式 / 希腊常量如 `φ-1`）⇒
    是「具体的值」，掩。
    """
    return bool(re.search(r"[A-Za-z]", _LATEX_CMD_RE.sub("", val)))


def _scan_value(text: str, start: int) -> tuple:
    """从 `start` 向右扫一个值表达式，返回 (value, end)。

    `start` 处的**空白先跳过** —— `T = (√5-1)/2` 的等号与值之间有空格，
    不跳就会扫出空串（实测漏掩 002 的主泄漏形态）。
    """
    i = start
    while i < len(text) and text[i] in " \t":
        i += 1
    buf = []
    while i < len(text) and _is_value_char(text[i]):
        buf.append(text[i])
        i += 1
    val = "".join(buf).strip()
    while val and val[-1] in ".+-*/^_\\|,":
        val = val[:-1]
    return val, i


def _looks_like_value(val: str, tail: str) -> bool:
    """`val` 是否是一个「具体的值/表达式」，且未被从更长表达式里截断。

    `tail` 是值后面第一个字符（截断原因），用于排除 `= 2k` 被切成 `= 2`
    后再接 `k` 的情况 —— 那种属于**关系式**的一片，不是独立的值。
    """
    if not val or len(val) > _MAX_VALUE_LEN:
        return False
    if not _HAS_NUM_RE.search(val):
        return False                     # 裸变量 / 占位符，不是值
    if len(val) == 1 and val.isalpha():
        return False
    if "," in val or "，" in val:
        # ★ 2026-10-27（服务器自检发现）：`n=1,2` / `x=1,3,5` 是「验证哪些特例」，
        #   不是答案值。答案值恒为**单个**闭式表达式；逗号列表是枚举。
        #   宁可漏掩（4.x 还有语义审核）也不能把可解信息掩成占位符。
        return False
    if _has_free_latin(val):
        return False                     # 关系式/通项的一片（`2k`/`r^{i-1}`）
    if tail and (tail.isalnum() or tail in "_\\{"):
        return False                     # 被截断了，右侧还有表达式
    return True


# ======================================================================
# 「结果值」掩码（2.6 题意理解的 terminal_state 专用，2026-10-29）
# ======================================================================
# 为什么单独一条：`_mask_asserted_values`（sub_goal_solver）与
# `mask_assigned_values`（本模块上方）都只覆盖**带直接断言词**或**等号赋值**的
# 形态，而题意理解的终态是自然语言，真实句式全是「最小照亮点数为 28」这种
# **锚点与数字之间夹着名词**的形态 ⇒ 旧判据 0 命中。
#
# 实测铁证（2026-10-27/28 服务器真实产物，均被 `render_problem_goal` 下发给
# 蓝图与主求解 prompt）：
#   · omni-3593 `最大社区数为4。存在满足…的4社区配置。`            （答案 4）
#   · omni-2163 `…并集大小为 28，此为所有合法 n 中的最小可能值。`  （答案 28）
#   · omni-3876 `…因此 f(1988) 的值唯一确定为 1988。`              （答案 1988）
#   · omni-1322 `…恰好有 8 个，它们分别是 1, -1, i, -i, …`         （答案 + 全集）
# 旧判据对这 4 条**全部原样放过**（`_ASSERTED_VALUE_RES` 要求「最小/最大」后
# 紧跟「为/是/等于」，中间只允许 `\s*值?\s*`）。
#
# 两级判据（★ 从严口径，用户 2026-10-29 拍板「拿不准时从严」）：
#   ① **强锚点**：措辞本身就在说"这是结果"（唯一确定/恰好有/答案为…）
#      ⇒ 直接掩，**不看题面白名单**（1988 既可能是题面参数也可能是答案）。
#   ② **弱锚点**：量名词 + 为/是/等于（最大…为 N）
#      ⇒ 走**题面白名单**保护（题面里已出现的数不掩，避免把「共有 10 个」这类
#        条件复述抹成占位符）。这是防误伤，不是判「是否答案」的判据。

_STRONG_ANCHOR_RE = re.compile(
    r"(?:唯一确定|确定为|最终答案|最终结果|最终取值|答案为|答案即|结果即"
    r"|恰好有|恰有|恰为|恰等于|共计|合计为|总计数为)"
    r"[^，。；\n]{0,6}?\s*([-+]?\d[\d,]*(?:\.\d+)?)"
)

_WEAK_ANCHOR_RE = re.compile(
    r"(?:最小|最大|最多|最少|并集大小|面积|周长|长度|距离|高度|比值|时刻"
    r"|个数|数量|点数|总数|总和|取值|下界|上界"
    r"|min(?:imum)?|max(?:imum)?|union\s+size|\bsize\b|\bcount\b)"
    r"[^，。；\n]{0,10}?"
    # ★ 等号必须排除比较运算符：`总和 >= 1810` / `0 <= x_i <= 100` 是题面条件，
    #   不是赋值（实测误伤样本：official112-013 的终态复述）。
    r"(?:为|是|等于|(?<![<>=!:=])=(?!=)|is|equals|of)\s*"
    r"([-+]?\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

# 题面里的数字（含 LaTeX 里的、带千分位的）—— 弱锚点命中这些值时**不掩**。
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def problem_numbers(problem: str) -> frozenset:
    """题面出现过的所有数字（去掉千分位逗号后的规范串）。用于弱锚点白名单。"""
    t = str(problem or "")
    return frozenset(m.group(0).replace(",", "") for m in _NUM_RE.finditer(t))


def _num_hit_in_whitelist(raw: str, allow: frozenset) -> bool:
    return raw.replace(",", "") in allow


def mask_result_values(text: str, problem: str = "") -> tuple:
    """把**结果值**换成占位符（2.6 终态 / 答案槽专用）。返回 ``(新文本, 替换处数)``。

    ``problem`` 传入题面时启用白名单保护（弱锚点命中题面已有数字则不掩）；
    传空串则不做白名单保护（从严）。

    ⚠ 只换值本体，句子结构逐字保留（与 `mask_assigned_values` 同一惯例）。
    ⚠ 含自由拉丁变量的表达式（`f(n) = n`）不在本函数射程内 —— 它由锚点正则
      直接要求「后面是纯数字」，天然不会命中。
    """
    t = str(text or "")
    if not t:
        return "", 0
    allow = problem_numbers(problem) if problem else frozenset()

    spans = []          # (start, end, raw) —— 记录要替换的**数字本体**区间
    for m in _STRONG_ANCHOR_RE.finditer(t):
        spans.append((m.start(1), m.end(1), m.group(1)))
    for m in _WEAK_ANCHOR_RE.finditer(t):
        raw = m.group(1)
        if allow and _num_hit_in_whitelist(raw, allow):
            continue
        spans.append((m.start(1), m.end(1), raw))

    if not spans:
        return t, 0

    spans.sort()
    out, pos, n = [], 0, 0
    for start, end, _raw in spans:
        if start < pos:                 # 与已替换区间重叠 ⇒ 跳过
            continue
        # 数字后面紧跟字母/中文量词属正常（`8 个`），但紧跟 `k`/`n` 等变量字母
        # 说明它是更长表达式的一片（`= 2k`）⇒ 不掩。
        tail = t[end] if end < len(t) else ""
        if tail and (tail.isascii() and tail.isalpha()):
            continue
        out.append(t[pos:start])
        out.append(MASK_PLACEHOLDER)
        pos = end
        n += 1
    out.append(t[pos:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip(), n


def mask_assigned_values(text: str) -> tuple:
    """把赋值形态的答案值换成占位符。返回 ``(新文本, 替换处数)``。

    覆盖两类（都只保留结构，不丢句子）：

    * `X = <闭式值>`  —— `T = (√5-1)/2` / `T(m) = -4` / `N = 1012`
    * `上界/下界 -4`  —— 无等号的边界断言

    原文其余部分逐字保留；`=` 与空格保留，只换值本体。
    """
    t = str(text or "")
    if not t:
        return "", 0

    n = 0
    # 两类锚点统一处理：`=` 右侧、以及「下界/最终答案/…」之后。按位置排序后
    # 顺序替换，已替换区间跳过（避免同一段值被掩两次）。
    spots = [(m.end(), m.start()) for m in _EQ_RE.finditer(t)]
    spots += [(m.end(), m.start()) for m in _NAMED_RE.finditer(t)]
    spots.sort()

    out, pos, last_anchor = [], 0, -1
    for start, anchor in spots:
        if start < pos or anchor < last_anchor:
            continue
        val, end = _scan_value(t, start)
        tail = t[end] if end < len(t) else ""
        if not _looks_like_value(val, tail):
            continue
        out.append(t[pos:start])
        out.append(MASK_PLACEHOLDER)
        pos = end
        last_anchor = anchor
        n += 1
    out.append(t[pos:])
    t = "".join(out)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip(), n
