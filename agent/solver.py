from __future__ import annotations
"""
通用求解智能体（SolverAgent）
============================

把原 ``ReasoningAgent._generate_candidates`` 迁移为独立 Agent，并新增
**自纠错重解（revise）模式**：

- 初始求解：蓝图分解（LEAP 启发）+ 领域提示注入（复用 prompts/policy）；
- 重解模式：当 ``ctx.revise_feedback`` 非空且处于 revise 轮次时，改用
  ``prompts/revise`` 的纠错提示词，针对验证器指出的错误定向修正；
- 追加候选：中置信度分支调用 ``add_candidates`` 补充采样。
- 直接求解：当所有候选都失败时（last-resort），使用简化提示词直接求解。

性能优化：
- 候选生成和纠错重解改为串行请求（每次间隔 0.3s），避免 API 请求风暴。
"""


import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import (
    BaseAgent, TaskContext, Candidate,
    detect_hallucination, detect_truncated,
    detect_template_leak,
    next_candidate_id,           # 2026-09-17：候选 id 单一来源（防腾位后 id 冲突）
    pick_best_candidates,        # 2026-09-17：腾位按票数选优（单一来源）
)
from prompts.policy import (
    SELF_IMPROVE_USER,
    get_policy_system,
    get_domain_hint,
    build_blueprint_user_message,
)
from prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
from prompts.proof import PROOF_SYSTEM, PROOF_TEMPLATE
from prompts.symbolic_model import (
    SYMBOLIC_MODEL_SYSTEM, SYMBOLIC_MODEL_USER, SYMBOLIC_JSON_SEED,
    SYMBOLIC_SOLVE_SYSTEM, SYMBOLIC_SOLVE_USER, SYMBOLIC_SOLVE_SEED,
    SYMBOLIC_SOLVE_RETRY_SYSTEM, SYMBOLIC_SOLVE_RETRY_USER,
    SYMBOLIC_FEEDBACK_SYSTEM, SYMBOLIC_FEEDBACK_USER,
)

try:
    from .symbolic_model import parse_symbolic_payload, evaluate_payload
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from symbolic_model import parse_symbolic_payload, evaluate_payload
    except ImportError:
        parse_symbolic_payload = None
        evaluate_payload = None

# 2026-09-12 符号化方程求解通道：数值剥离 → 符号建模 → 硬校验 → 工具求解。
# 模型只交方程，数值一律由本地 SymPy 算出（模型不参与计算）。
try:
    from .symbolic_solve import (
        strip_given_numbers, parse_symbolic_solve, validate_payload,
        solve_with_tool)
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from symbolic_solve import (
            strip_given_numbers, parse_symbolic_solve, validate_payload,
            solve_with_tool)
    except ImportError:
        strip_given_numbers = None
        parse_symbolic_solve = None
        validate_payload = None
        solve_with_tool = None

try:
    from .calc_tool import (
        resolve_all_calcs, audit_calc_fallbacks, find_naked_numeric_asserts,
        has_hard_op, to_exact_number, collect_calc_results, extract_calc_blocks)
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from calc_tool import (
            resolve_all_calcs, audit_calc_fallbacks, find_naked_numeric_asserts,
            has_hard_op, to_exact_number, collect_calc_results,
            extract_calc_blocks)
    except ImportError:
        resolve_all_calcs = None
        audit_calc_fallbacks = None
        # 2026-09-10 修复：原兜底漏了这一项 → 两个 import 都失败时
        # _maybe_calc_rewrite 里的 `find_naked_numeric_asserts is None`
        # 会抛 NameError（而非安全跳过）。
        find_naked_numeric_asserts = None
        # 2026-09-12 计算分档：高危算子痕迹判定（兜底 None = 安全跳过）
        has_hard_op = None
        to_exact_number = None
        # 2026-09-13 方案 A：上文精确值汇总（兜底 None = 安全跳过该注入段）
        collect_calc_results = None
        # 2026-09-13 方案 B：算式预计算（兜底 None = 安全跳过该步）
        extract_calc_blocks = None
from utils.extract import (
    extract_final_answer,
    smart_fallback_answer,
    rescue_final_answer,
    is_valid_final_answer,
)
from utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot")

# ------------------------------------------------------------------
# 拒绝回答的检测模式
# ------------------------------------------------------------------
_REFUSAL_PATTERNS = [
    r"无法求解",
    r"无法解决",
    r"不能解决",
    r"无法解答",
    r"我无法",
    r"我没办法",
    r"很抱歉.{0,10}(?:无法|不能)",
    r"抱歉.{0,10}(?:无法|不能)",
    r"超出.{0,5}能力",
    r"暂时无法",
    r"(?:不|没有)足够.{0,5}(?:信息|条件|数据)",
    r"题目.{0,5}(?:有误|不完整|不清晰)",
    r"(?:I\s)?can'?t\s+solve",
    r"no\s+solution",
    r"unable\s+to\s+solve",
]

_REINFORCED_SYSTEM = (
    "你是一名顶尖的数学竞赛选手，必须对每道题给出明确的解答。"
    "即使题目看起来困难或信息不全，也要尽力推理并给出你最好的答案。"
    "绝对不能回答'无法求解'或'不能解决'。请务必在【最终答案】中给出一个确定的答案。"
)


# ------------------------------------------------------------------
# 2026-09-13 计算纪律引导（<calc> 标记）——**主链单一同源常量**。
#
# 背景：此前该文案内联在 `_generate_initial` 里，只注入到初始生成一条路径；
# 实测 revise / self-improve / 证明通道 / 兜底直答 / 续写 五条生成路径的 prompt
# 全文都没有 <calc> 字样，且 revise 与自改进会把子目标链已产出的精确计算痕迹
# **重写洗掉**（同一机制多处注入、口径不一致的老问题）。
# 现提为模块级常量，供上述各路径**复用同一份文案**——禁止再复制第二份。
# 注：子目标链（sub_goal_solver）用的 system 侧 `_CALC_GUIDE` 与本常量同口径，
# 两者刻意保持一致的措辞（步进/合并见该文件 :91）。
_CALC_GUIDE = (
    "\n\n**【计算纪律 · 分档执行】**\n"
    "1. **易错运算 → 必须写 <calc>表达式</calc> 交系统精确求值（严禁心算）**："
    "开方/根式 sqrt、对数 ln（log 即自然对数，其他底请用换底写成 ln 之比）、"
    "指数 exp 与自然常数 e（写 exp(1)）、组合数 comb(n,k)、排列 perm(n,k)、"
    "阶乘 ! 或 fact(n)、幂运算 ** 或 ^、取模（**必须写 `a % b`**，不要写 `a mod b`）、"
    "求和 sum(f,x,a,b)、"
    "积分 integral(f,x[,a,b])、圆周率 pi。"
    "这些运算心算极易出错，**即使你确信数值正确也必须交工具确认**；"
    "注意**工具只认上述函数名**：组合数请写 comb（勿写 C(n,k)/choose/ncr），"
    "排列请写 perm（勿写 P(n,k)/npr），阶乘请写 fact 或 n!；\n"
    "2. **工具能力外 → 换核验方式，不要写 <calc>**：三角函数 sin/cos/tan"
    "（含反三角 asin/acos/atan、双曲 sinh 等）、求积 prod/product、以 2/10 为底"
    "的对数 log2/log10、开立方 cbrt/root **均不在工具能力内**（写了只会拿到 "
    "WARN、白费一轮）：特殊角请**直接写精确式**（sin(pi/6)=1/2、"
    "cos(pi/4)=sqrt(2)/2），一般角与求积请把断言写成 <check> 或 "
    "```lean example``` 交编译器验算，禁止拿心算近似当精确结论；\n"
    "3. **简单四则 → 你可以自己算**：整数/小数的加、减、乘、除、括号与"
    "比较，直接写出结果即可，不必包 <calc>（包了也无害）；\n"
    "4. **由易错运算得出的数值型最终答案，必须能在你前面的 <calc> 记录中"
    "找到来源**：查不到工具来源的会被系统打回重写（多花一轮时间）；"
    "纯四则得出的答案不受此限。\n"
    "5. **★ 易错运算请「先符号、后代入」** —— 与上面的最终答案格式要求"
    "**不冲突**：你仍须给出**完全求值**的【最终答案】，本项只是**额外**"
    "提供算式，供系统用精确计算器复核。当最终答案由第 1 条的易错运算得出时，"
    "请在【最终答案】**之前**先列出这两行：\n"
    "   ```\n"
    "   【变量赋值】x=5, y=3           ← 题目中每个量的具体数值，一行列全\n"
    "   【最终表达式】2*x + y          ← 只含符号的算式，不必自己算\n"
    "   ```\n"
    "   系统会代入数值精确求值，用于**校验**你给出的答案：不一致时**以工具值"
    "为准**（这正是防心算漂移的兜底），一致则你的答案原样保留。简单四则不必"
    "给这两行。\n"
    "\n**节奏示范**：“求组合数 C(50,3)”→写 <calc>comb(50,3)</calc>→回填 "
    "[计算] comb(50,3) = 19600→引用 19600；“把 sqrt(45) 化为最简根式”→写 "
    "<calc>sqrt(45)</calc>→回填 3*sqrt(5)；“25×4+1”→纯四则，可直接写 = 101。"
    "易错计算拆成 ≤3 个 <calc>（每步一个表达式），不要一步吞一大串。\n"
    "\n\n计算环节请用 <calc>表达式</calc> 标记（例如 <calc>comb(50,3)*2**10</calc>、"
    "<calc>1/2+1/3</calc>、<calc>sqrt(45)</calc>、<calc>integral((1-x)^n,x,0,1)</calc>、<calc>sum(k^2,k,1,n)</calc>），"
    "系统会自动求值并回填结果。涉及上述易错运算时务必使用该标记，不要心算；"
    "纯四则（加减乘除）可直接写出结果。\n"
    "**<calc> 与 </calc> 之间必须且只能是数学表达式**"
    "（数字/字母符号 x n k…、+ - * / **（或 ^）% //、括号、函数 "
    "fact/comb/perm/gcd/lcm/abs/sqrt/floor/ceil/min/max/ln/log/exp/"
    "integral(f,x[,a,b]) 积分、sum(f,x,a,b) 求和（可省略变量）、pi 常量（回填≈近似））；隐式乘 2(x+1)/2x 自动识别，分式分母含变量请写 1/(2*x)形式。禁止出现中文、文字解释或换行。<calc> 只接受**单个数学表达式**：不要写代码/多语句/赋值（a=7 或跨行）、不要调 simplify()/solve() 等命令——要化简 x+1 就写 <calc>x+1</calc> 由系统自动回填。\n"
    "回填结果形态：①精确值（整数/分数/精确根式如 3*sqrt(5)）可直接信任；"
    "②符号化简式（含变量如 1/(n+1)、x**2-1）是 SymPy 化简的恒等式，可核对符号推导"
    "（含变量者落地数值时请代入具体值再 <calc> 自检）；"
    "③带 ≈ 的近似值（sqrt 无平方因子、ln、exp 等）只能核对量级，不是精确结论；"
    "④以 WARN: 开头表示该表达式超出工具能力（三角函数/求积 prod/带底对数 "
    "log2·log10/开立方等能力外算子、符号整除取模、化简超时）——"
    "**禁止拿它硬算或当作已确认结论**：请代入具体数值用 <calc> 自检（如 <calc>(2+3)**2</calc>），"
    "三角等特殊角请写精确式（sin(pi/6)=1/2、cos(pi/4)=sqrt(2)/2），一般角把断言写成 <check> 或 lean example 交编译器验算；自然常数 e 请写 exp(1)。若在 deep 档且断言可形式化，"
    "可把关键代数等式写成 ```lean example ... := by ring/norm_num ``` 代码块，"
    "系统会用本地 Lean 编译器自动核验。"
)

# revise / 自改进**专用**追加段（2026-09-13）：这两条路径的输入里带着子目标链
# 已回填的 [计算] 精确值（如 [计算] comb(50,3) = 19600）。若不显式约束"沿用"，
# 模型会整段重写时把工具结果换成新的心算值 —— 正是要治的心算污染。
#
# 2026-09-13 方案 A：「把数值给大模型，但不让它计算危险数值」——
# 光有"不得重算"的口头约束还不够：模型仍要在长文本里**自己找**那些 [计算] 行，
# 找不到就会心算（revise 更彻底：REVISE_USER_TEMPLATE 只有题目+反馈，
# **连上一轮解答全文都不给**，[计算] 行根本不在视野里）。
# 故新增「系统已算出的精确值」汇总段：把上文 [计算] 行**实打实列出来**前置给模型。
# 与"不得重算"约束**合并为同一段**（`_calc_trace_block`）：有值则"值清单+引用纪律"，
# 无值则退回纯纪律段（`_CALC_KEEP_TRACE`）——避免两段话各说一遍"禁止重算"。
_CALC_KEEP_RULE = (
    "上面列出的算式结果（由系统精确回填、或生成前预计算的）都是**可信的精确值**"
    "（形如 comb(50,3) = 19600、sqrt(45) = 3*sqrt(5)）："
    "**原样引用，严禁重新心算、改写、删除，或「顺手验算一遍」**。"
    "只有当你要在它们之上做**新的**易错运算时，才为新算式另写 <calc>表达式</calc>。"
)
_CALC_KEEP_TRACE = (
    "\n\n**【上文已有的 <calc> 结果必须沿用，不得重算】**" + _CALC_KEEP_RULE
)


def _calc_trace_block(trace_text, extra_items=None) -> str:
    """方案 A/B：把已算出的精确值汇总成"前置值清单"段。

    - 扫到 ≥1 条（含 `extra_items` = 方案 B 的预计算结果）：返回**汇总段
      （值清单 + 沿用纪律）**——模型直接引用，不必翻长文、更不必重算；
    - 一条也没扫到：返回原 `_CALC_KEEP_TRACE` 纯纪律段（**不注入空标题**制造噪音，
      行为与改动前完全一致）；
    - `collect_calc_results` 不可用（提交包兜底）时同样退回纯纪律段。
    """
    items = [str(x) for x in (extra_items or [])]
    if collect_calc_results:
        for it in collect_calc_results(trace_text):
            if it not in items:
                items.append(it)
    if not items:
        return _CALC_KEEP_TRACE
    return (
        "\n\n**【系统已算出的精确值 —— 直接引用，禁止重算或改写】**\n"
        + "\n".join(f"- {it}" for it in items)
        + "\n" + _CALC_KEEP_RULE
    )

# 时间紧迫/结构简单的路径（兜底直答、续写、答案前置重问）用的一行版：
# 塞整段 _CALC_GUIDE 会把本就短的 prompt 撑失衡，故只留最短要求。
_CALC_SHORT_HINT = (
    "\n\n涉及开方/对数/指数/组合数/幂等易错运算时，请用 <calc>表达式</calc> "
    "交系统精确求值，不要心算；上文已回填的 [计算] 精确结果直接沿用。"
)

# ==================================================================
# 2026-09-13 方案 B（用户选定）：**生成前算式预计算**（算式供给，非"等模型写"）
# ------------------------------------------------------------------
# 动机（official112-016 单题实测）：`calc_tool_calls=[]` 且 `calc_fallback=0`
# ⇒ 模型**压根不写 <calc>**（不是"写了被拒"）。于是所有"写在前面才生效"的防线
# （多行降级解析 / 计算分档 / 方案 A 的值汇总）**全部空转** —— 因为它们都建立在
# 「模型会先写 <calc>」这个**不成立**的前提上。故改为**主动把值算好摆到模型面前**。
#
# 实证（Intern-S2-Preview-397B，2026-09-13 真调用，见交付报告）：
#   · 原样 prompt（无 prefill）→ **失败**：模型无视"只列算式/不要解题"，
#     016 输出 36 行英文解题推理、**零 <calc>**、被 max_tokens 截断；
#   · 同 prompt + prefill 种子 `"<calc>"`（项目 v2.4.1 既有机制）→ **成功**：
#     016 → `20/10`(2.3s)、000 → `2 * 19 * (19**18)`(125s)、005 → `1 + 1 + 1`(7.9s)。
#     ⇒ 可稳定列出算式且 256 token 足够；但**相关性弱**（解题前猜不出真正需要的
#     算式，偶发纯四则噪音）⇒ 用 `has_hard_op` 过滤掉纯四则、上限 6 条。
#
# ⚠⚠ **`_CALC_PREWARM_PREFILL` 是方案 B 生效的必要条件，不是冗余参数，勿删** ⚠⚠
#   实证对比（同 prompt、同模型、同日）：
#     · 去掉 prefill → 016 输出 36 行英文解题推理、**零 <calc>**、被截断；000 同样失败；
#     · 保留 prefill → 016 `20/10`、000 `2 * 19 * (19**18)`、005 `1 + 1 + 1`，全部成功。
#   原因：无 prefill 时模型走自由 CoT，宁可"思考"也不受"只列算式"约束；
#   种子 `"<calc>"` 把第 1 个 token 钉死在标记上，等于把任务退化成"续写算式"。
#   删掉这一行 ⇒ 整个方案 B 静默失效（仍会跑一次 LLM，但列不出算式）。
#   成本告警：000 那次 prewarm 实测 125s（≈ 单题 1000s 预算的 12.5%），
#   而产出相关性弱 ⇒ 目前**默认全量触发**（覆盖 87.5%），收窄触发条件
#   （题型 ∈ {计算/计数}）需先有 A/B 数据，暂不实施。
_CALC_PREWARM_SYSTEM = (
    "你是一名数学竞赛助手的**计算调度器**：只列出需要精确计算的算式，不解题。")
_CALC_PREWARM_USER = (
    "本题涉及需要精确计算的运算。请**只**输出算式，禁止任何其他文字。\n\n"
    "【输出格式 —— 必须严格遵守】\n"
    "1. 一个算式一行，每行形如：<calc>算式</calc>；\n"
    "2. 第一行直接就是 <calc>，不要写任何开头语、编号、解释、答案或推理过程；\n"
    "3. 不要 Markdown、不要代码块、不要标题；\n"
    "4. 只列**真正需要工具去算**的式子：不要列题目里已直接给出的数字或常数，"
    "不要列仅含加减乘除（口算即可）的式子；\n"
    "5. 若本题确实无需此类计算，只输出一行：NONE\n\n"
    "【函数名必须写工具认识的记法】\n"
    "组合数 comb(n,k)、排列 perm(n,k)、阶乘 fact(n)、开方 sqrt(x)、"
    "对数 ln(x)、指数 exp(x)、\n"
    "幂 a**b（**不要写 ^**）、取模 a % b、求和 sum(f,x,a,b)、"
    "积分 integral(f,x,a,b)、圆周率 pi。\n"
    "**根号一律写 sqrt(x)，禁止写 x**0.5 / x**(1/2) / √x**"
    "（工具只接受整数指数的 **，小数指数会被拒）。\n"
    "**不要**写 C(n,k) / P(n,k) / \\frac 等工具不认的记法（更不要用 LaTeX）。\n\n"
    "【示例一】\n"
    "题目：从 50 人中选 3 人，有多少种选法？并求 sqrt(45) 的化简值。\n"
    "正确输出：\n"
    "<calc>comb(50,3)</calc>\n"
    "<calc>sqrt(45)</calc>\n\n"
    "【示例二】\n"
    "题目：求证：任意三角形的内角和为 180°。\n"
    "正确输出：\n"
    "NONE\n\n"
    "【题目】\n{problem}"
)
_CALC_PREWARM_PREFILL = "<calc>"   # ⚠ 方案 B 生效的必要条件，见上方实证说明，勿删
_CALC_PREWARM_MAX_TOKENS = 256     # 只需列算式（实证 256 足够，成本可控）
_CALC_PREWARM_ITEM_LIMIT = 6       # 注入上游的条目上限（防 prompt 膨胀）
# 2026-09-13 晚：预计算的**独立时间下限**（秒）。原判据只有"剩 150s 就别开"，
# 实测 010 的预计算吃掉 364s（≈ 全题预算 36%），把后面的生成/验证全挤没了。
# 预计算只是"锦上添花"的前置步骤，不该占用超过约 1/3 预算 ⇒ 剩余不足本值
# 时不再发起。`CALC_PREWARM_MIN_REMAIN` 可覆盖（设 0 恢复旧的 150s 行为）。
_CALC_PREWARM_MIN_REMAIN = float(os.getenv("CALC_PREWARM_MIN_REMAIN", "300"))
# 题面"有数学内容"判据（从宽）：出现 `$` / 反斜杠 / 数字即算。
# ⚠ 刻意**不做**"高危算子关键词"白名单式判定 —— 实测它会在**解答题**上误杀：
#   加 "\sqrt|comb|sum|number of|compute…" 一类关键词后，official112 里仍有
#   002/005/039/063/064/066/069/070/080 等 10 道**需要计算**的题判成"无需计算"
#   （关键词只覆盖 80.4%，且漏掉的正是要治的那批）；而**漏做 = 回到"模型不写
#   <calc>"的现状**，误做只是一次 ≤256 token 的短调用 ⇒ 宁可从宽。
_PREWARM_MATH_TEXT_RE = re.compile(r"[$\\]|\d")


def _is_refusal(text: str) -> bool:
    """检测模型输出是否为拒绝回答"""
    if not text or not text.strip():
        return True
    # 去掉推理过程，只看结尾 500 字符和开头 200 字符
    start = text.strip()[:200]
    end = text.strip()[-500:]
    for pat in _REFUSAL_PATTERNS:
        if re.search(pat, end) or re.search(pat, start):
            return True
    # 纯拒绝（全文很短且无数学内容）
    if len(text.strip()) < 200:
        has_math = bool(re.search(r"[$\\=+\-*/^()]|\d{2,}", text))
        if not has_math:
            return True
    return False


def _needs_followup(content: str) -> bool:
    """检测是否需要追问中文答案。
    注意：Intern-S 模型天然倾向英文输出，但数学答案（数字/表达式）无所谓语言。
    目前暂时禁用追问机制，避免无限循环。英文答案同样可以通过正则提取。"""
    return False  # 禁用：Intern-S 英文输出不影响答案提取


# 2026-09-06 易错点记忆（A 档轻量经验注入）：prompts/error_lessons 惰性加载，
# 由 orchestrator/solver 在初始生成与 revise 时拼接（命中才注入）。
_LESSON_MOD = None


def _lesson_module():
    global _LESSON_MOD
    if _LESSON_MOD is None:
        from prompts.error_lessons import match_lessons, lesson_ids  # noqa: PLC0415
        _LESSON_MOD = (match_lessons, lesson_ids)
    return _LESSON_MOD


def error_lessons_block(ctx) -> str:
    """命中当前题的自查清单片段（无命中=空串，零噪音）。"""
    if getattr(ctx, "state", None) is not None and getattr(
            getattr(ctx, "state", None), "emergency", False):
        return ""  # 应急模式不注入，把预算全给解题
    match_lessons, _ = _lesson_module()
    return match_lessons(domain=getattr(ctx, "domain", "") or "",
                         question_type=getattr(ctx, "question_type", "") or "",
                         problem=ctx.problem or "")


def error_lesson_ids(ctx) -> list:
    """命中的 lesson id 列表（record 诊断用）。"""
    _, lesson_ids = _lesson_module()
    return lesson_ids(domain=getattr(ctx, "domain", "") or "",
                      question_type=getattr(ctx, "question_type", "") or "",
                      problem=ctx.problem or "")


class SolverAgent(BaseAgent):
    name = "Solver"

    def run(self, ctx: TaskContext) -> TaskContext:
        """根据当前上下文状态决定初始求解还是纠错重解"""
        # 2026-09-02 老师需求：候选池统一封顶（无论初始/revise/自改进/playoff 从哪条路径追加）。
        # 历史：13→8→5→8（003 退步分析——cap5 曾砍掉好候选后 0 票直答退化成
        # No such function，改回 8 保好候选）。
        # 2026-09-04：cap 8→6（deep 候选 4→3 配套，验证成本 -25%）。此时初始池
        # 只到 3、revise 补 ≤3，总量天然 ≤6，封顶不再主动砍候选，无 003 式风险。
        # count 只传 remaining 上限，adaptive 缩小在 _generate_initial 内部做。
        remaining = 6 - len(getattr(ctx, 'candidates', None) or [])
        # ★ 2026-09-17（M1）：池满时**不要在这里 return**。
        # 腾位逻辑写在 `_generate_revise` 内部（其 `_room <= 0` 分支），而本函数
        # 在 `remaining <= 0` 时直接返回 ⇒ **那段腾位结构性不可达**。
        # 实测后果：official112-003 的 `revise_round=4`，但 6 个候选
        # `revised` **全为 False** —— 4 轮修订一个候选都没生成，却烧掉
        # `5_revise_or_fallback 688.5s + 5.5_low_conf 805.6s = 1494s`。
        # 修法：仅"非修订轮且池满"才早退；修订轮池满时把 cap 置 None，
        # 交给 `_generate_revise` 自行腾位后决定 count。
        _is_revise = bool(ctx.revise_round > 0 and ctx.revise_feedback)
        if remaining <= 0 and not _is_revise:
            return ctx
        if _is_revise:
            self._generate_revise(ctx, cap=(remaining if remaining > 0 else None))
        else:
            self._generate_initial(ctx, count=remaining)
        return ctx

    def add_candidates(self, ctx: TaskContext, count: int = None) -> TaskContext:
        """中置信度分支：补充生成普通候选（默认与初始采样数一致）"""
        self._generate_initial(ctx, count or self.config.policy_sample_times)
        return ctx

    @staticmethod
    def _adaptive_count(ctx: TaskContext, default_count: int) -> int:
        """根据题目领域自适应调整候选数量"""
        domain = (ctx.domain or "").lower()
        # 难题深度通道：deep 档保持多候选（3 候选，不做缩减）
        if getattr(ctx, 'tier', 'standard') == 'deep':
            return default_count
        # 证明题 → 减少候选（精确推演比广度采样更重要）
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in domain for k in proof_keywords):
            return max(1, default_count // 3)
        # P0-4 修复：不再为高难度题提高候选数——3 候选 × 3 重试曾耗尽单题
        # 300s 预算导致 45 error。保持 default_count（配置=2），省预算保产出。
        # 2026-09-12 定型前审核精简：此处原本有一段 hard_signals 判定
        # （题长 / 微分方程 / 级数 / 积分 / 客观题 → 意图给高难题更多候选），
        # 但上面的 P0-4 修复已取消"难题多给候选"策略，使该块的
        # **三个分支全部 `return default_count`** —— 计算了 12 行却零效果，
        # 属典型的"逻辑堆叠后残留"。整块删除（零行为变化）。
        return default_count

    @staticmethod
    def _adaptive_max_tokens(ctx: TaskContext, base_tokens: int) -> int:
        """2026-09-04：比赛不限制模型 token → 各档统一返回 base_tokens（=policy_max_tokens=65536）。

        原分级（简单题 8192 / 难题 24576）在平台单题 1200s 时间墙下大量
        finish_reason=length 答案被腰斩（2534334 平台实测 truncated 238 次、
        64 题 invalid）——截断比多花时间更丢分。上限只作保险，prefill 压缩下
        模型实际输出仍克制；真正边界是 1200s 时间墙而非 token 帽。
        """
        return base_tokens

    def _use_lemma(self, ctx: TaskContext) -> bool:
        """判断当前题是否启用 lemma 累积（按领域路由，2026-08-29）。

        A/B 实测：lemma 全领域开 = 净 0.0pp（代数/组合被噪声拖累，数论 +23pp）。
        因此默认按领域路由：lemma_domains 命中才注入，把数论的收益变成
        确定收益，同时避免拖累其他领域。
        """
        if not getattr(self.config, 'use_lemma_accumulation', False):
            return False
        domains = list(getattr(self.config, 'lemma_domains', []) or [])
        if not domains:
            return True  # 空列表 = 全领域开启
        d = str(getattr(ctx, 'domain', '') or '')
        return any(k in d for k in domains)

    def _collect_lemma_context(self, ctx: TaskContext) -> str:
        """收集已验证的子结论（引理库），作为解题上下文注入。"""
        if not self._use_lemma(ctx):
            return ""
        lemmas = getattr(ctx, 'lemma_repo', [])
        if not lemmas:
            return ""
        recent = lemmas[-5:]  # 最多注入 5 条
        return "【已验证的中间结论】\n" + "\n".join(f"- {l}" for l in recent) + "\n\n"

    # ----------------------------------------------------------
    # 证明题专用通道
    # ----------------------------------------------------------
    # ----------------------------------------------------------
    # #51 答案定型：疑似推理文本的定向重问
    # ----------------------------------------------------------
    # 判定阈值取 60：基线 45 题中，答案长度 >60 的 5 条经人工核对均为
    # "整段计算步骤"或"结论句"，而非答案本身。
    _SUSPICIOUS_ANSWER_LEN = 60

    # 叙述性措辞：出现在答案里说明抽到的是句子而非结论。
    # 刻意不含"是/为"等通用系动词，避免误伤 "x = 2" 这类合法答案。
    _NARRATIVE_PAT = (
        r"因此|所以|由于|于是|综上|可得|由此|进而|注意到|显然",
        r"步骤\s*\d", r"^第\s*[一二三四五六七八九十\d]+\s*[步点、]",
        r"其中|其[中次]|这里|我们|可以[看得]出|答案[是为]|故[，,]",
        r"\\sum|\\int|\\lim|\\prod|\\oint",
    )

    # P1-1 主链覆盖（2026-09-09 B：calc_mandatory 只挂子目标链是漏洞——
    # 主链响应同样含心算数值行）。
    # 2026-09-12 精准化（用户要求）：只抓**高危算子**的心算痕迹
    # （开方/根式、log·ln、exp 与 e、组合数/排列/阶乘、幂运算、取模、
    # 求和/积分）；纯四则（加减乘除）允许模型自算，不再打断。
    # 2026-09-13 能力对齐：三角/prod/log2 等工具算不了的算子已从
    # _HARD_FUNC_NAMES 摘除（见 calc_tool 该常量注释），不再触发本重问。
    # 判据 = calc_tool.find_naked_numeric_asserts(hard_only=calc_hard_only)。
    def _backfill_calc(self, ctx: TaskContext, text: str) -> str:
        """只做 <calc> → 精确值回填（供新注入 calc 引导的路径复用）。

        2026-09-13：proof / self-improve / direct_solve / 续写 这几条路径
        此前既无 <calc> 引导、也无回填。补上引导后必须同步回填——否则模型
        写出的 `<calc>…</calc>` 会以**裸标记**形态留在解答甚至最终答案里
        （既有教训见 `_generate_initial` 处 2026-09-12 机制闭合注释）。
        **刻意不做** `_maybe_calc_rewrite` 的强制重问：这些路径多为时间紧迫的
        兜底/续写，额外一轮 LLM 成本不划算；且它们本身是"补救"性质，重问
        的收益低于直接前移的风险。
        """
        if (resolve_all_calcs is None
                or not getattr(self.config, 'enable_calc_tool', True)
                or not text):
            return text
        out, resolved = resolve_all_calcs(text)
        self.record_calc_successes(ctx, resolved)
        if audit_calc_fallbacks is not None:
            for _ex, _rs in audit_calc_fallbacks(resolved):
                self.record(ctx, "calc_fallback", f"<calc>{_ex}</calc> → {_rs}",
                            expr=_ex, reason=_rs)
        return out

    def _maybe_calc_rewrite(self, ctx: TaskContext, resp: str) -> str:
        if (find_naked_numeric_asserts is None
                or not getattr(self.config, "calc_mandatory", True)):
            return resp
        try:
            _hard_only = bool(getattr(self.config, "calc_hard_only", True))
            naked = find_naked_numeric_asserts(resp, hard_only=_hard_only)
            if not naked:
                if _hard_only and find_naked_numeric_asserts(
                        resp, hard_only=False):
                    # 埋点：区分"没有数值断言"与"被分档放行的纯四则行"
                    self.record(ctx, "calc_easy_pass",
                                "响应仅含纯四则数值断言（加减乘除），按分档放行")
                return resp
            bad = naked[0]
            self.record(ctx, "solver_calc_rewrite",
                        f"主链响应含未用 <calc> 的高危运算（{bad[:50]}），定向重问")
            tail = resp[-1200:] if len(resp) > 1200 else resp
            system = (
                "你是数学解题助手。你上一条输出里含有**易错运算**"
                "（开方/根式、对数 log·ln、指数 exp 与自然常数 e、组合数/排列/"
                "阶乘、幂运算、取模、求和/积分）是**心算**的，没有"
                "经过外部计算工具——这是禁止的。加减乘除这类简单四则你可以"
                "自己算，但上述易错运算必须写成 <calc>表达式</calc> 标记"
                "（如 <calc>comb(50,3)</calc>、<calc>sqrt(45)</calc>、"
                "<calc>ln(2)</calc>、<calc>2**10</calc>、<calc>e**2</calc>），"
                "系统会自动精确求值并回填。**即使你确信数值正确也必须让系统"
                "计算确认，禁止心算易错运算。**"
                "注意工具算不了的算子（三角 sin/cos/tan、求积 prod、"
                "log2/log10、cbrt/root）不要写 <calc>：特殊角直接写精确值"
                "（如 sin(pi/6)=1/2），其余用 <check> 或 lean example 断言。"
            )
            user = (
                f"题目解答片段：\n{tail}\n\n"
                f"其中以下这一行是心算结果（未用 <calc> 工具）：{bad}\n"
                "请重写整个解答：把该类易错运算改写成 <calc>…</calc> 标记，"
                "其他推理保留，最后仍用【最终答案】给出结论。"
            )
            raw = self._compressed_solve(
                ctx, system, user,
                temperature=0.0,
                max_tokens=int(getattr(self.config, 'max_answer_tokens', 4096)),
            )
            if raw and len(raw.strip()) > 20:
                return raw
            return resp
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] calc 定向重问失败，保留原输出: %s", str(exc)[:120])
            return resp

    # ============================================================
    # 2026-09-13 方案 B：生成前算式预计算（见上方 `_CALC_PREWARM_*` 常量注释）
    # ------------------------------------------------------------
    # 落点：orchestrator 在**首个生成阶段（2.7 子目标主路径）之前**调用一次；
    # 产出写入 `ctx.calc_prewarm_block`（list[str]），由 `_calc_trace_block`
    # （revise / 自改进）与 `sub_goal_solver._calc_results_block`（step / merge）
    # 一并前置注入 ⇒ 四条上下文回灌路径自动覆盖。
    # ⚠ 该字段按本仓既有做法**动态挂载**（同 `ctx._subgoal_main_done`），
    #   不改 base.py 的 dataclass 定义；读取方一律 `getattr(ctx, ..., None)`。
    # ============================================================
    def _prewarm_applicable(self, ctx: TaskContext, tier: str = "") -> bool:
        """预计算触发判据（从宽）：档位 ∈ {standard, deep} 且题面可能有高危运算。"""
        if os.environ.get("CALC_PREWARM", "1") == "0":
            return False
        if not getattr(self.config, "enable_calc_prewarm", True):
            return False
        if (resolve_all_calcs is None or extract_calc_blocks is None
                or not getattr(self.config, "enable_calc_tool", True)):
            return False
        if getattr(getattr(ctx, "state", None), "emergency", False):
            return False
        t = str(tier or getattr(ctx, "tier", "") or "")
        if t not in ("standard", "deep"):
            return False
        # 时间护栏：单次预计算实测 2~125s（最坏 = client timeout，2026-09-13 晚起
        # 超时不再重试，见 `utils/llm_client.py`，单次故障从 365s 降到 120s）。
        # 尾声/应急一律不开新调用（宁可回到现状也不冒穿预算的风险）。
        if ctx.gen_time_up() or ctx.is_time_critical():
            return False
        _hd = float(getattr(ctx, "deadline", 0.0) or 0.0)
        if _hd >= 10**8 and _hd - time.time() < _CALC_PREWARM_MIN_REMAIN:
            self.record(ctx, "calc_prewarm",
                        f"剩余不足 {_CALC_PREWARM_MIN_REMAIN:.0f}s → 跳过预计算"
                        "（它是锦上添花，不能挤掉主生成）")
            return False
        # 题面判据（从宽）：只跳过"确定不需要计算"的两类 ——
        #   ① 客观题（选择题/判断题）：答案是选项字母，不需要工具计算；
        #   ② 题面完全没有数学内容（无 $、无 \、无数字）。
        # 其余一律做：漏做 = 回到"模型不写 <calc>"的现状（正是要治的病），
        # 误做只是一次 ≤256 token 的短调用。实测关键词白名单会误杀解答题
        # （000/002/005/080 等 10 道需要计算的题），故不用白名单。
        if str(getattr(ctx, "question_type", "") or "") in ("选择题", "判断题"):
            self.record(ctx, "calc_prewarm", "客观题（选择题/判断题）→ 跳过预计算")
            return False
        _prob = str(getattr(ctx, "problem", "") or "")
        if not _PREWARM_MATH_TEXT_RE.search(_prob):
            self.record(ctx, "calc_prewarm", "题面无数学内容 → 跳过预计算")
            return False
        return True

    def prewarm_calcs(self, ctx: TaskContext, tier: str = "") -> int:
        """生成前发一次短调用，让模型**只列**需要工具算的算式，系统算好存 ctx。

        返回写入 `ctx.calc_prewarm_block` 的条目数（0 = 未产出/已跳过）。

        graceful（硬性要求）：无响应 / 超时 / 全 NONE / 只列纯四则 / 异常
        ⇒ **不写 block、不阻断主流程**，一律留 `calc_prewarm` 埋点便于事后统计。
        """
        if not self._prewarm_applicable(ctx, tier):
            return 0
        t0 = time.time()
        try:
            msgs = prefill_messages(
                [{"role": "system", "content": _CALC_PREWARM_SYSTEM},
                 {"role": "user",
                  "content": _CALC_PREWARM_USER.format(problem=ctx.problem)}],
                _CALC_PREWARM_PREFILL)
            raw = self.llm(ctx, msgs, 0.0, _CALC_PREWARM_MAX_TOKENS)
            if not raw or not str(raw).strip():
                self.record(ctx, "calc_prewarm",
                            f"预计算无响应（{time.time() - t0:.0f}s）→ 跳过")
                return 0
            raw = str(raw)
            raw = stitch(_CALC_PREWARM_PREFILL, raw)
            if not extract_calc_blocks(raw):
                _body = raw.replace(_CALC_PREWARM_PREFILL, "", 1).strip()
                if _body.upper().startswith("NONE"):
                    self.record(ctx, "calc_prewarm",
                                f"模型判定本题无需工具计算（NONE，"
                                f"{time.time() - t0:.0f}s）")
                else:
                    self.record(ctx, "calc_prewarm",
                                f"预计算未产出 <calc> 算式（{time.time() - t0:.0f}s）："
                                f"{_body[:120]}")
                return 0
            resolved, _ = resolve_all_calcs(raw)
            items = collect_calc_results(resolved) if collect_calc_results else []
            # 只留**高危运算**条目：模型在解题前凭题面猜的算式里，纯四则
            # （实证见过 `20/10`、`1 + 1 + 1`）既非本题所需、也无信息量。
            # rsplit：表达式本身可能含 `=`（多行 <calc> 的赋值回填），取最后一个。
            if has_hard_op is not None:
                items = [it for it in items if has_hard_op(it.rsplit("=", 1)[0])]
            items = items[:_CALC_PREWARM_ITEM_LIMIT]
            if not items:
                self.record(ctx, "calc_prewarm",
                            f"预计算仅得纯四则/无效算式（{time.time() - t0:.0f}s）→ 不注入")
                return 0
            ctx.calc_prewarm_block = items
            self.record(ctx, "calc_prewarm",
                        f"预计算 {len(items)} 条（{time.time() - t0:.0f}s）："
                        + "；".join(items)[:200],
                        items=items)
            return len(items)
        except Exception as exc:  # noqa: BLE001  失败不阻断主流程
            self.record(ctx, "calc_prewarm",
                        f"预计算异常（已跳过，不阻断）: "
                        f"{type(exc).__name__}: {str(exc)[:120]}")
            return 0

    # ============================================================
    # 2026-09-10 L1：答案级工具自洽核验（默认关，answer_selfcheck_enabled 开）
    # ------------------------------------------------------------
    # 共识（2026-09-12 修订）：**易错运算**（开方/对数/组合数/幂/自然常数 e…）
    # 的数值结论必须由工具产出，禁止心算；纯四则（加减乘除）允许模型自算。
    # 本关卡只抓一种**确定**情形：抽取到的最终答案是纯数值、解答中出现过高危
    # 算子（has_hard_op），而响应里所有 <calc> 工具结果都不等于它 ——
    # 这个数没有工具来源（心算产物）。
    # 触发后定向重问一次，要求把**得出最终答案的算式**写成 <calc>；
    # 采纳新输出**仅当**其中确实出现了与新答案数值一致的工具结果（有来源）。
    # 其余情况一律保留原输出（零后悔）。
    # ============================================================
    def _maybe_expression_eval(self, ctx: TaskContext, resp: str,
                               answer: str) -> tuple[str, str]:
        """表达式范式（2026-09-12，用户要求「默认生成方程式、不心算」）。

        解析模型输出的两行（见 `_CALC_GUIDE` 第 4 条）：
            【变量赋值】x=5, y=3
            【最终表达式】2*x + y
        把赋值代入表达式 → **用本地 calc_tool 求值** → **答案取工具值**
        （模型原先写的数值被丢弃，仅在 reasoning 里留痕）。

        设计要点：模型**只负责建模**（设符号、给出算式），数值代入与运算
        全部由本地完成 —— 与"剥离"通道互补：剥离适用于题面有具体数据的题，
        本通道适用于参数是变量的题（B 类）。
        无这两行 / 求值失败 / 开关关闭 → 原样返回（零风险）。
        """
        try:
            if not getattr(self.config, "symbolic_solve_adopt", True):
                return resp, answer
            # 2026-09-12 逻辑堆叠治理③：客观题（选择/判断）的答案是选项字母或
            # 判断值，不是数值 —— 本关"工具代入求值"根本不适用。若模型按
            # _CALC_GUIDE 误写了【最终表达式】，会把选项答案改写成数值而丢分。
            _qt = getattr(ctx, "question_type", "") or ""
            # 2026-09-12 补漏：填空题同属客观题 —— 多空答案形如 `1, 2`，
            # 被本关覆盖成单个工具值会丢分（选择/判断上一轮已设防，填空漏了）。
            if _qt in ("选择题", "判断题", "填空题"):
                return resp, answer
            if not resp or "【最终表达式】" not in resp:
                return resp, answer
            import re as _re3
            m_e = _re3.search(r"【最终表达式】\s*(.+?)(?:\n|$)", resp)
            if not m_e:
                return resp, answer
            expr = m_e.group(1).strip().strip("$").strip().rstrip("。.")
            if not expr or len(expr) > 300:
                return resp, answer
            assigns: dict = {}
            m_v = _re3.search(r"【变量赋值】\s*(.+?)(?:\n|$)", resp)
            if m_v:
                for part in _re3.split(r"[,，;；、]", m_v.group(1)):
                    if "=" in part:
                        _k, _v = part.split("=", 1)
                        _k = _k.strip().strip("$").strip()
                        _v = _v.strip().strip("$").strip().rstrip("。.")
                        if _k and _v:
                            assigns[_k] = _v
            # ============================================================
            # 2026-09-13 修复（q3_mcp 实测实锤）：符号答案不得被数值代入覆盖。
            # 实况（official112 #001）：gold `2-2m`，模型原答 `\boxed{-2(m-1)}`
            # —— 二者恒等，**答案是对的**；但响应里同时写了自造的
            # 【变量赋值】m=3 与【最终表达式】-2*(3-1)，本关遂以工具值 -4
            # **覆盖**模型答案 → 判 expr_wrong。根因：参数题的答案含自由变量，
            # 对变量代一个具体值只是"特例"，根本不是题目要的答案。
            # 判据（零后悔）：模型自己的答案若**不是纯数值**（即符号式/含自由变量）
            # → 代入求值不可能产出答案 → 弃权，保留模型原答案，交下游既有把关。
            # 开关 EXPR_EVAL_GROUNDING_GUARD=0 可恢复旧行为（A/B 对照用）。
            # ============================================================
            if (os.environ.get("EXPR_EVAL_GROUNDING_GUARD", "1") != "0"
                    and answer and to_exact_number is not None
                    and to_exact_number(str(answer)) is None):
                self.record(
                    ctx, "expression_eval_skip",
                    f"表达式范式：模型答案为符号式（{str(answer)[:24]}），"
                    f"代入求值不适用，弃权保留模型原答案")
                return resp, answer
            # 符号 → 数值 代入（整词匹配，避免 x 误伤 exp）
            sub = expr
            for _k, _v in assigns.items():
                sub = _re3.sub(
                    r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % _re3.escape(_k),
                    "(%s)" % _v, sub)
            exec_fn = getattr(self, "_calc_tool_exec", None)
            if exec_fn is None:
                return resp, answer
            raw = str(exec_fn(sub) or "")
            # 2026-09-12 定型前审核修复：**只采纳纯数值结果**。
            # 原实现用 findall 抓"最后一个数字"，当工具结果不是纯数值时会抓
            # 到碎片 —— `3*sqrt(5)`（精确根式）→ 取到 "5"、`2*x+3`（含变量）
            # → 取到 "3"、`WARN: …12…` → 取到 "12"；而本函数会把该值**直接
            # 写进【最终答案】**，等于把答案覆盖成一个错数。必须整串是数值才
            # 采纳，否则零后悔弃权（保留模型原答案）。
            _val_txt = raw.strip()
            for _pre in ("≈", "~", "="):
                _val_txt = _val_txt.lstrip(_pre).strip()
            if to_exact_number is None or to_exact_number(_val_txt) is None:
                self.record(ctx, "expression_eval_skip",
                            f"表达式范式：{expr[:60]} 工具结果非纯数值"
                            f"（{raw[:40]}），弃权保留模型原答案")
                return resp, answer
            val = _val_txt
            # 2026-09-12 逻辑堆叠治理（定型前审核）：本关已用本地计算器产出答案，
            # 登记标记让下游**不再重复处理**同一次计算：
            #   · _maybe_answer_selfcheck 不会再以"看不到 <calc> 工具来源"为由
            #     打回重问（本关的工具调用不写 <calc> 标记，它无从知晓）；
            #   · _maybe_symbolic_solve 不会再重复建模/求解一遍并覆盖该答案。
            # 两者都是"答案取工具值"的同族机制，叠加只会白烧 LLM 时间与互相覆盖。
            if ctx is not None:
                try:
                    setattr(ctx, "_expr_eval_adopted", True)
                except Exception:  # noqa: BLE001  标记失败不影响主流程
                    pass
            self.record(ctx, "expression_eval",
                        f"表达式范式：{expr[:60]} 代入 {assigns} → {val}"
                        f"（答案取工具值，模型不参与计算；原答 {str(answer)[:24]}）")
            # 2026-09-12 逻辑堆叠治理②：resp 里若**已有**最终答案区块，必须
            # **替换**而不是在末尾追加 —— 否则会留下两个互相矛盾的【最终答案】
            # 标记，而下游 extract_final_answer 的正则取的是**第一个**（模型的
            # 心算旧值），本关刚采纳的工具值会被完全架空（已实测该正则行为：
            # `re.search(r"【最终答案】\s*\n?\s*([\s\S]+)")` 命中首个标记，
            # 且 first_line 分支直接返回其首行）；reasoning 注入下游时也会歧义。
            _new_resp = resp
            if "【最终答案】" in _new_resp:
                _new_resp = _re3.sub(r"【最终答案】[\s\S]*$",
                                     "【最终答案】" + str(val), _new_resp)
            else:
                _new_resp = _new_resp + "\n\n【最终答案】" + str(val)
            return _new_resp, val
        except Exception as exc:  # noqa: BLE001
            logger.debug("[solver] expression_eval 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

    def _maybe_answer_selfcheck(self, ctx: TaskContext, resp: str,
                                answer: str, resolved: list) -> tuple[str, str]:
        try:
            if not getattr(self.config, "answer_selfcheck_enabled", False):
                return resp, answer
            # ★★★ 2026-09-16 修复（实测驱动的"老逻辑打架"）：
            #   本关的判据是"答案涉高危运算却**无 `<calc>` 工具来源**"，
            #   而 `<calc>` 的**引导注入**（`_CALC_GUIDE`）与**标记解析**
            #   （`resolve_all_calcs` → `resolved`）**全部**受
            #   `enable_calc_tool` 门控（见 :1536 / :1779 / :1976 / :2105 /
            #   :2191 / :2371）。默认 `enable_calc_tool=False`（2026-09-15 用户
            #   指示"没有解决计算问题就关掉"关闭）。
            #   ⇒ **`resolved` 恒为空** ⇒ 任何含高危算子的答案**结构性无法满足**
            #   本关要求 ⇒ 必然触发"定向重问"，而重问本身**也拿不到工具来源**
            #   ⇒ **注定徒劳**，且会把好答案改坏。
            #   实测代价（official112-003）：
            #     `answer_selfcheck_events` 记 3 次重问，
            #     答案被越改越差 `\boxed{2026} → \boxed{1013} → \boxed{0}`
            #     （2026 是**正确答案之一**）；且 orchestrator.py:1821 会据此
            #     把 `g_ok` 置 False → 进**重做循环**（deep 最多 3 轮）
            #     ⇒ 3 次重问 + 3 轮重做，是该题 184 次 LLM 调用/69 分钟的大头。
            #   修法：工具关闭时本关**整体跳过**——要求不可能被满足，
            #   继续检查只会白烧调用并劣化答案。
            if not getattr(self.config, "enable_calc_tool", False):
                # ⚠ 2026-09-17（L4）：本早退**同时**使下方的「计算冲突」检测
                #   （`ctx.calc_inconsistent = True`）**结构性不可达**，进而使
                #   `orchestrator` 6.5 那条「计算冲突优先于 Lean answer_valid」的裁决
                #   永不生效。此处显式记录，避免读 diag 时误以为它在工作。
                self.record(ctx, "answer_selfcheck_skip",
                            "enable_calc_tool=False ⇒ `<calc>` 引导与标记解析均未启用，"
                            "本关要求结构性无法满足 → 整体跳过（不再徒劳重问）；"
                            "**连带 calc_inconsistent 检测不可达**（L4 2026-09-17）")
                return resp, answer
            # 2026-09-12 逻辑堆叠治理（定型前审核）：答案已由表达式范式（本地
            # 计算器）产出 —— 本关不再以"看不到 <calc> 来源"为由重复打回，
            # 否则同一题会白烧一次定向重问（该关的工具调用不写 <calc> 标记）。
            if ctx is not None and getattr(ctx, "_expr_eval_adopted", False):
                self.record(ctx, "answer_selfcheck_skip",
                            "答案已由表达式范式（本地计算器）产出，跳过重复核验")
                return resp, answer
            # 2026-09-14 **幂等短路**（沙箱实测 #003：同一答案被 adopt 2 次、重问 3 次）。
            # 根因：`resolved` 只含**本轮** response 的 `<calc>`，而上一轮重问采纳的工具值
            # 没有跨轮保存 ⇒ 下一轮又判"无工具来源" ⇒ 反复重问，白烧 2–3 次 LLM 调用
            # （实测 569s / 561s 各来一遍）。
            # 修法：把「已核验过的数值」与「已就同一答案重问过」记在 ctx 上，跨轮生效。
            # 纯短路，**只会减少重问、不会改变答案**。
            _verified, _reasked = set(), set()
            if ctx is not None:
                _verified = set(getattr(ctx, "_selfcheck_verified_vals", None) or ())
                _reasked = set(getattr(ctx, "_selfcheck_reasked_ans", None) or ())
            if to_exact_number is not None and answer:
                _w0 = to_exact_number(answer)
                if _w0 is not None and str(_w0) in _verified:
                    self.record(ctx, "answer_selfcheck_skip",
                                f"答案 {str(answer)[:30]} 已在先前轮次经工具核验"
                                "（幂等短路，不再重问）")
                    return resp, answer
                if str(answer)[:60] in _reasked:
                    self.record(ctx, "answer_selfcheck_skip",
                                f"已就答案 {str(answer)[:30]} 重问过一次且未变"
                                "（幂等短路，不再重问）")
                    return resp, answer
            if to_exact_number is None or not answer:
                return resp, answer
            want = to_exact_number(answer)
            if want is None:                    # 非纯数值答案 → 不在本关卡范围
                return resp, answer
            # 2026-09-12 计算分档（用户要求）：只有当解答中出现过**高危算子**
            # （开方/对数/组合数/幂/e/阶乘…）时，才要求最终答案有工具来源；
            # 全程纯四则（加减乘除）的答案允许模型自算，不再重问。
            if has_hard_op is not None and not has_hard_op(resp):
                self.record(ctx, "answer_selfcheck_skip",
                            "解答未出现高危算子（纯四则），按分档放行心算答案 "
                            f"{str(answer)[:30]}")
                return resp, answer
            tool_vals = []
            for _ex, _rs in (resolved or []):
                got = to_exact_number(_rs)
                if got is not None:
                    tool_vals.append((_ex, _rs, got))
            if any(g == want for _e, _r, g in tool_vals) or str(want) in _verified:
                # 2026-09-14：命中即记入跨轮已核验集合（供上方幂等短路使用）。
                if ctx is not None:
                    try:
                        _v = set(getattr(ctx, "_selfcheck_verified_vals", None) or ())
                        _v.add(str(want))
                        ctx._selfcheck_verified_vals = _v
                    except Exception:  # noqa: BLE001
                        pass
                return resp, answer             # 已有工具来源 → 放行
            # 2026-09-13（用户方案 C-A）：**有工具值但对不上答案** ⇒ 计算不一致。
            # 这是比"没有工具来源"更强的信号：答案与它自己的计算矛盾。
            # 由**本地精确计算器**（calc_tool，SymPy）判定，**不经 Lean** ——
            # 因为 Lean 只能验证"命题可证"，无法验证"命题 = 题目"，让它判数值
            # 会在题面无 ≥3 位数字时退化为自证放行（实测 010）。
            # 标记后交 6.5 闸门拒绝放行（orchestrator 侧消费）。
            if tool_vals:
                _vals = [str(g) for _e, _r, g in tool_vals][:3]
                self.record(ctx, "calc_consistency",
                            f"最终答案 {str(answer)[:30]} 与工具计算值 {_vals} "
                            "不一致 → 标记为计算冲突，6.5 闸门将拒绝放行")
                if ctx is not None:
                    try:
                        ctx.calc_inconsistent = True
                    except Exception:  # noqa: BLE001
                        pass
                return resp, answer
            if not (resp or "").strip():
                return resp, answer
            # 2026-09-13 修复（实测驱动）：原实现用 `gen_time_up()`（生成侧软截止
            # = deadline − verify_reserve ≈ 780s）判"时间到" ⇒ **过早放弃重问**。
            # 实测三轮（v1/v2/v5）在 010 上都记为"生成侧时间到，跳过重问"，而
            # 它恰恰是**唯一能救回错答案的机制**（Lean 的 answer_valid 会因自证
            # 而放行，见 lean_bridge._cross_check_problem_symbols 注释）。
            # 现改为按**剩余总预算**判断：>=300s 就做重问。
            # 代价（刻意接受）：会消耗一部分 verify_reserve；但"提交错答案"比
            # "验证时间紧"严重得多——宁可挤验证，也要先纠正答案。
            # 兼容性：ctx 无 time_remaining（测试桩）时退回原 gen_time_up 判定。
            _remain = None
            if ctx is not None:
                _tr = getattr(ctx, "time_remaining", None)
                if callable(_tr):
                    try:
                        _remain = float(_tr())
                    except Exception:  # noqa: BLE001
                        _remain = None
            if _remain is None:
                _timeup = bool(ctx is not None
                               and getattr(ctx, "gen_time_up", lambda: False)())
                _budget = ""
            else:
                _timeup = _remain < 300.0
                _budget = f"（剩余 {_remain:.0f}s）"
            # 先 record 再判时间：A/B 归因需要"机制本可触发但被时间墙挡下"
            # 的证据（否则无法区分"没触发"与"触发了但没重问"）。
            self.record(ctx, "answer_selfcheck",
                        f"最终答案 {str(answer)[:40]} 涉高危运算却无 <calc> 工具来源"
                        + ("（剩余不足 300s，跳过重问）" if _timeup
                           else "，定向重问" + _budget))
            if _timeup:
                # 2026-09-13：打标记供 6.5 闸门联动。理由：该答案"涉高危运算却
                # 无工具来源"，而 2.6/6.5 的 Lean answer_valid **只证明"LLM 写的
                # 命题可证"**，在题面无 ≥3 位数字时会退化为"自证放行"
                # （见 lean_bridge._cross_check_problem_symbols 注释）。
                # 故此处标记后，闸门将**不接受** answer_valid，改按需重做。
                if ctx is not None:
                    try:
                        ctx.selfcheck_unverified_answer = str(answer)[:60]
                    except Exception:  # noqa: BLE001
                        pass
                return resp, answer             # 剩余确实不足 → 不再加开销
            hints = [f"- <calc>{e}</calc> = {r}" for e, r, _g in tool_vals[:5]]
            tail = resp[-1200:] if len(resp) > 1200 else resp
            system = (
                "你是数学解题助手。你的最终答案涉及**易错运算**（开方/根式、"
                "对数 log·ln、指数 exp 与自然常数 e、组合数/阶乘、幂运算、"
                "取模等）却是**心算**的，没有经过外部计算器——这违反计算"
                "纪律。请修正：**只输出**得出该答案的完整计算表达式，写成 "
                "<calc>表达式</calc>（如 <calc>comb(50,3)*2**10</calc>、"
                "<calc>sqrt(45)</calc>、<calc>ln(2)</calc>）。"
                "**不要自己给出数值结果**——系统会精确计算，并把工具算出的值"
                "作为最终答案。可以写一行简短说明，但不得出现任何未经 <calc> 的数值。"
            )
            user = f"题目解答片段：\n{tail}\n\n"
            if hints:
                user += ("你已用工具算出的中间结果（注意：它们都不是最终答案）：\n"
                         + "\n".join(hints) + "\n\n")
            user += ("请**只输出**得出最终答案的计算表达式（写在 <calc>…</calc> 内），"
                     "不要自行给出数值答案。")
            # 2026-09-14：重问前登记，使同一答案**只重问一次**（幂等短路依据）。
            if ctx is not None:
                try:
                    _rq = set(getattr(ctx, "_selfcheck_reasked_ans", None) or ())
                    _rq.add(str(answer)[:60])
                    ctx._selfcheck_reasked_ans = _rq
                except Exception:  # noqa: BLE001
                    pass
            raw = self._compressed_solve(
                ctx, system, user, temperature=0.0,
                max_tokens=int(getattr(self.config, 'max_answer_tokens', 4096)),
            )
            if not raw or len(raw.strip()) < 10:
                return resp, answer
            new_ans = extract_final_answer(raw)
            new_val = to_exact_number(new_ans)
            if new_val is None:
                return resp, answer
            _raw2, new_resolved = (resolve_all_calcs(raw)
                                   if resolve_all_calcs is not None else (raw, []))
            ok = any(to_exact_number(r) == new_val
                     for _e, r in (new_resolved or [])
                     if to_exact_number(r) is not None)
            if not ok:
                # 2026-09-12 用户要求「绝对用工具算」：重问后仍无工具来源 → 不采纳，
                # 并把"该答案是心算产物"写进 revise_feedback，让下游修订链强制重写，
                # 避免这类答案静默通过（此前是纯静默 return，无法观测也无法纠正）。
                self.record(ctx, "answer_selfcheck_fail",
                            f"重问后仍无 <calc> 工具来源（答案 "
                            f"{str(new_ans)[:30]}）→ 不采纳")
                try:
                    ctx.revise_feedback = list(
                        getattr(ctx, "revise_feedback", []) or []) + [
                        f"最终答案 {str(answer)[:30]} 是心算产物、没有 <calc> 工具"
                        "来源：重写时必须把得出该答案的算式写成 <calc>表达式</calc> "
                        "由系统精确求值后再给结论"]
                except Exception:  # noqa: BLE001
                    pass
                return resp, answer             # 仍无工具来源 → 不采纳
            # ★ 2026-09-12 通用表达式通道（覆盖 B 类：不可剥离但需数值计算的题）：
            # 重问后若模型给出了 <calc>，**答案直接取工具算出的值**，而不是取
            # 模型自己写的那个数——否则模型仍然"先心算、再补一个 <calc> 装饰"。
            # 这样即使题面不可剥离（走不了符号化通道），最终数值也由本地计算器产生。
            _tool_vals = []
            for _e, _r in (new_resolved or []):
                _gv = to_exact_number(_r)
                if _gv is not None:
                    _tool_vals.append((_e, _gv))
            if _tool_vals and getattr(self.config, "symbolic_solve_adopt", True):
                # 2026-09-12 修复（取值口径一致）：应取**与重问后新答案 `new_val`
                # 相等**的那个工具值。原实现取 `_tool_vals[-1]`（列表最后一个），
                # 当一次重问里出现多个 `<calc>` 时，会把中间量当成最终答案写回去
                # —— 与本函数前面 `ok` 判定所用口径（`to_exact_number(r)==new_val`）
                # 不一致。
                _te, _tv = next(
                    ((_e, _v) for _e, _v in reversed(_tool_vals) if _v == new_val),
                    _tool_vals[-1])
                self.record(ctx, "answer_selfcheck_adopt",
                            f"答案改用工具值 {_tv}（表达式 {str(_te)[:40]}；"
                            f"模型原答 {str(new_ans)[:30]}）")
                # 2026-09-14：采纳的工具值记入跨轮已核验集合 —— 否则下一轮
                # `resolved` 看不到它，会再判"无工具来源"并重复重问（#003 实测 2 次 adopt）。
                if ctx is not None:
                    try:
                        _v = set(getattr(ctx, "_selfcheck_verified_vals", None) or ())
                        _v.add(str(_tv))
                        ctx._selfcheck_verified_vals = _v
                    except Exception:  # noqa: BLE001
                        pass
                return (_raw2 if _raw2 else raw), str(_tv)
            if new_val != want:
                self.record(ctx, "answer_selfcheck_fix",
                            f"最终答案经工具核验修正：{str(answer)[:30]} → "
                            f"{str(new_ans)[:30]}")
            else:
                self.record(ctx, "answer_selfcheck_ok",
                            f"最终答案 {str(answer)[:30]} 经工具复核一致")
            # 采纳前先回填 <calc>（否则 reasoning 里留着未求值的标签，
            # 会污染下游 revise/验证器看到的文本）
            return (_raw2 if _raw2 else raw), new_ans
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] answer selfcheck 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

    # ============================================================
    # 2026-09-10 L2：独立符号建模复核（默认关，symbolic_crosscheck_enabled 开）
    # ------------------------------------------------------------
    # 用户 9/10 思路 + 李平老师 9/9 建议合并：让模型当"数学问题拆解助手"，
    # 把题面**给定的具体数值**抽象成变量、只输出**目标量的表达式**（禁止自算），
    # 再由本地精确计算器代入求真值，与主链答案比对。
    #   - 一致   → 记 pass（独立路径旁证，增强置信）
    #   - 不一致 → 打回一次（带上独立建模真值）；采纳新答案**仅当**它落回该真值
    #   - 求不出 / 无法建模 / 证明题 / 时间紧 → 直接放行（宁漏勿误）
    # 与 L1 正交：L1 查"答案有没有工具来源"（输出纪律），L2 用**独立于解答**的
    # 一次建模重建"关系式→精确值"（推理旁证）。每题最多触发一次（ctx 标记）。
    # 求值走 calc_tool（毫秒级精确）而非 Lean —— 纯算术不必付 21s/次的 Lean 前置。
    # ============================================================
    def _maybe_symbolic_crosscheck(self, ctx: TaskContext, resp: str,
                                   answer: str) -> tuple[str, str]:
        try:
            if not getattr(self.config, "symbolic_crosscheck_enabled", False):
                return resp, answer
            if (parse_symbolic_payload is None or evaluate_payload is None
                    or to_exact_number is None):
                return resp, answer
            if getattr(ctx, "_sym_cross_checked", False):
                return resp, answer
            want = to_exact_number(answer)
            if want is None:                    # 非纯数值答案 → 本关卡不适用
                return resp, answer
            problem = (getattr(ctx, "problem", "") or "").strip()
            if not problem:
                return resp, answer
            try:
                from .question_type import classify_question_type
            except ImportError:
                from question_type import classify_question_type
            if classify_question_type(problem) == "证明题":
                return resp, answer             # 证明题无数值答案，不适用
            if ctx is not None and ctx.gen_time_up():
                self.record(ctx, "symbolic_crosscheck", "跳过：生成侧时间到")
                return resp, answer
            setattr(ctx, "_sym_cross_checked", True)   # 每题只做一次
            raw = self._compressed_solve(
                ctx, SYMBOLIC_MODEL_SYSTEM,
                SYMBOLIC_MODEL_USER.format(problem=problem[:3000]),
                temperature=0.0,
                max_tokens=int(getattr(self.config, "symbolic_max_tokens", 512)),
                prefill_seed=SYMBOLIC_JSON_SEED,
            )
            payload = parse_symbolic_payload(raw or "")
            value, why = (evaluate_payload(payload) if payload
                          else (None, "未解析出建模结果"))
            if value is None:
                self.record(ctx, "symbolic_crosscheck", f"跳过：{why}")
                return resp, answer
            got = to_exact_number(value)
            if got == want:
                self.record(ctx, "symbolic_crosscheck_pass",
                            f"独立建模复核一致：{why}；与答案 {str(answer)[:30]} 相符")
                return resp, answer
            self.record(ctx, "symbolic_crosscheck_mismatch",
                        f"独立建模得 {value}（{why}），与答案 "
                        f"{str(answer)[:30]} 不符，定向重问")
            if ctx is not None and ctx.gen_time_up():
                return resp, answer
            system = (
                "你是数学解题助手。有人**只依据题目条件**独立建模，把给定数值"
                f"抽象为变量后算出目标量应为 {value}，与你的最终答案不一致。"
                "请核对：若你的答案错了，请修正推导并给出新答案；"
                "若你认为独立建模有误，请指出其建模错在哪里，并维持你的答案。"
                "涉及易错运算（开方/对数/组合数/幂等）时必须写成 "
                "<calc>表达式</calc>，最后用【最终答案】给出结论。"
            )
            user = (f"题目：\n{problem[:2000]}\n\n"
                    f"你的解答片段：\n{(resp[-1200:] if len(resp) > 1200 else resp)}\n\n"
                    f"独立建模给出的目标量值为：{value}（依据：{why}）\n"
                    "请核对后重写解答并给出【最终答案】。")
            new_raw = self._compressed_solve(
                ctx, system, user, temperature=0.0,
                max_tokens=int(getattr(self.config, 'max_answer_tokens', 4096)),
            )
            if not new_raw or len(new_raw.strip()) < 10:
                return resp, answer
            new_ans = extract_final_answer(new_raw)
            if to_exact_number(new_ans) != got:
                self.record(ctx, "symbolic_crosscheck_keep",
                            "重问结果未落到独立建模真值 → 保留原答案")
                return resp, answer
            self.record(ctx, "symbolic_crosscheck_fix",
                        f"答案经独立建模修正：{str(answer)[:30]} → {value}")
            if resolve_all_calcs is not None:
                new_raw, _ = resolve_all_calcs(new_raw)
            return new_raw, new_ans
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] symbolic crosscheck 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

    # ============================================================
    # 2026-09-12 符号化方程求解通道（默认关，symbolic_solve_enabled 开）
    # ------------------------------------------------------------
    # 用户 9/11 需求：模型根据题目逻辑推导出**方程式类型**的答案，具体数值由
    # 智能体调用工具执行计算 —— 智能体把数据剥离存本地，给模型的是"未知数
    # 类型"题面，模型只交方程（组）+ 目标，数值一律由本地 SymPy 回代算出。
    #
    # 省时间设计（用户 9/12 硬要求："为模型减少浪费时间而不是加时间"）：
    #   - 剥离 / 校验 / 求解 **全部本地**（毫秒~秒级，daemon 线程 5s 超时）；
    #   - 只加 **1 次短建模调用**（≈120 tokens，不是完整求解调用）；
    #   - 工具值与主链答案**一致** → 记 pass 直接放行，**0 额外调用**；
    #   - 仅当**分歧**时才追加 1 次短回传（把工具结果交回模型定稿，即
    #     "将计算方程式给工具并接收工具返回的结果"）；
    #   - **不新增候选** → 不触发下游验证/Lean 闸门的任何额外成本。
    # 硬性保证（用户 9/12）：最终答案的数值必须与工具返回一致 —— 模型不参与计算。
    # ============================================================
    def _maybe_symbolic_solve(self, ctx: TaskContext, resp: str,
                              answer: str) -> tuple[str, str]:
        try:
            if not getattr(self.config, "symbolic_solve_enabled", False):
                return resp, answer
            if (strip_given_numbers is None or parse_symbolic_solve is None
                    or validate_payload is None or solve_with_tool is None
                    or to_exact_number is None):
                return resp, answer
            if getattr(ctx, "_sym_solve_done", False):
                return resp, answer
            # 2026-09-12 逻辑堆叠治理（定型前审核）：答案已由表达式范式（本地
            # 计算器）产出 —— 不再重复做一次符号建模 + 求解，避免同一答案被
            # 两条同族机制先后覆盖（谁生效取决于顺序，且白烧一次建模调用）。
            if getattr(ctx, "_expr_eval_adopted", False):
                self.record(ctx, "symbolic_solve_skip",
                            "答案已由表达式范式（本地计算器）产出，跳过重复建模求解")
                return resp, answer
            problem = (getattr(ctx, "problem", "") or "").strip()
            if not problem:
                return resp, answer
            # 只对"数值型答案"题目生效（证明题/文字结论不适用）
            want = to_exact_number(answer)
            if want is None:
                return resp, answer
            try:
                from .question_type import classify_question_type
            except ImportError:
                from question_type import classify_question_type
            if classify_question_type(problem) == "证明题":
                return resp, answer
            if ctx.gen_time_up():
                self.record(ctx, "symbolic_solve", "跳过：生成侧时间到")
                return resp, answer
            setattr(ctx, "_sym_solve_done", True)   # 每题只做一次

            # ① 数值剥离（本地，零 LLM）：题面 → 符号题面 + 本地参数表
            strip = strip_given_numbers(problem)
            if strip is None:
                self.record(ctx, "symbolic_solve_skip",
                            "题面无「显式给定参数」可剥离，本通道不适用")
                return resp, answer

            # ② 符号建模（1 次短调用；不合格带**具体原因**重试 1 次）
            max_tok = int(getattr(self.config, "symbolic_solve_max_tokens", 384))
            payload, reason, previous = None, "", ""
            for attempt in range(2):
                if attempt == 0:
                    sys_p = SYMBOLIC_SOLVE_SYSTEM
                    usr_p = SYMBOLIC_SOLVE_USER.format(
                        problem=strip.problem[:3000])
                else:
                    sys_p = SYMBOLIC_SOLVE_RETRY_SYSTEM
                    usr_p = SYMBOLIC_SOLVE_RETRY_USER.format(
                        problem=strip.problem[:3000],
                        previous=(previous or "")[:600], reason=reason)
                if ctx.gen_time_up():
                    self.record(ctx, "symbolic_solve", "跳过：建模前生成侧时间到")
                    return resp, answer
                raw = self._compressed_solve(
                    ctx, sys_p, usr_p, temperature=0.0, max_tokens=max_tok,
                    prefill_seed=SYMBOLIC_SOLVE_SEED,
                )
                previous = raw or ""
                payload = parse_symbolic_solve(previous)
                ok, reason = validate_payload(payload, strip.params)
                if ok:
                    break
                self.record(ctx, "symbolic_solve_validate_fail",
                            f"第 {attempt + 1} 次建模不合格：{reason}")
                if payload is None:
                    break
            if payload is None:
                return resp, answer
            ok, reason = validate_payload(payload, strip.params)
            if not ok:
                self.record(ctx, "symbolic_solve_reject",
                            f"建模两次不合格，弃权：{reason}")
                return resp, answer

            # ③/④ 工具求解（本地，零 LLM）：数值回代 → 解方程（组）→ 精确值
            value, why = solve_with_tool(payload, strip.params)
            if value is None:
                self.record(ctx, "symbolic_solve_reject",
                            f"工具求解未成功：{why}")
                return resp, answer
            got = to_exact_number(value)
            if got is None:
                self.record(ctx, "symbolic_solve_reject",
                            f"工具结果非精确数值，弃权：{value}")
                return resp, answer
            self.record(ctx, "symbolic_solve_solved",
                        f"符号建模+工具求解成功：{why}")

            # ★ 2026-09-12 用户要求「把计算从模型手里拿走」（方案④正解）：
            # **工具求解成功 → 答案直接取工具值**，模型不参与计算。
            # 原设计只在"一致"时放行、"分歧"时才回传 → 最终答案仍可能是模型
            # 心算出来的值（工具只是事后核对，没有"接管"计算）。
            # 现改为：只要本地 SymPy 求出精确值，该值**就是**最终答案，
            # 模型原先给的数值被丢弃（保留在 reasoning 里供追溯）。
            # 回退：`--symbolic_solve_adopt false`（恢复"仅比对/回传"旧行为）。
            if getattr(self.config, "symbolic_solve_adopt", True):
                _tgt = str(payload.get("target") or "")
                _note = (f"\n\n【工具精确计算】{_tgt} = {value}"
                         "（该数值由本地计算器代入求解得出，非模型心算）")
                new_raw = ((resp or "") + _note) if (resp or "") else _note.strip()
                self.record(ctx, "symbolic_solve_adopt",
                            f"答案改用工具精确计算值 {value}"
                            f"（原答案 {str(answer)[:30]}；模型不参与计算）")
                return new_raw, value

            if got == want:
                self.record(ctx, "symbolic_solve_pass",
                            f"工具值与答案一致（{value}），模型未参与计算")
                return resp, answer

            # 分歧 → 1 次短回传（可关：symbolic_solve_feedback=0）
            if not getattr(self.config, "symbolic_solve_feedback", True):
                self.record(ctx, "symbolic_solve_mismatch",
                            f"工具值 {value} 与答案 {str(answer)[:30]} 不一致"
                            "（未回传）")
                return resp, answer
            if ctx.gen_time_up():
                self.record(ctx, "symbolic_solve_mismatch",
                            f"工具值 {value} 与答案不一致，但生成侧时间到，"
                            "保留原答案")
                return resp, answer
            eqs_txt = "\n".join(payload.get("equations") or []) or "（以 TARGET 为准）"
            new_raw = self._compressed_solve(
                ctx, SYMBOLIC_FEEDBACK_SYSTEM,
                SYMBOLIC_FEEDBACK_USER.format(
                    problem=problem[:1500], equations=eqs_txt,
                    target=payload.get("target") or "", value=value),
                temperature=0.0,
                max_tokens=int(getattr(self.config, "max_answer_tokens", 4096)),
            )
            if not new_raw or len(new_raw.strip()) < 10:
                self.record(ctx, "symbolic_solve_mismatch",
                            f"回传结果为空，保留原答案（工具值 {value}）")
                return resp, answer
            new_ans = extract_final_answer(new_raw)
            # 三重保险（防"盲从工具值"造成掉分）：
            #   ① 模型必须**显式确认建模正确**（ADOPT）；REJECT/无标记一律维持原答案
            #   ② 新答案的数值必须**正好落在工具值上**（模型不得改动数值）
            upper = new_raw.upper()
            if "ADOPT" not in upper:
                self.record(ctx, "symbolic_solve_keep",
                            f"模型未确认建模正确"
                            f"（{'REJECT' if 'REJECT' in upper else '无标记'}）"
                            f" → 保留原答案（工具值 {value}）")
                return resp, answer
            if to_exact_number(new_ans) != got:
                self.record(ctx, "symbolic_solve_keep",
                            f"回传后答案未落到工具值 {value} → 保留原答案")
                return resp, answer
            self.record(ctx, "symbolic_solve_fix",
                        f"答案按工具结果修正：{str(answer)[:30]} → {value}")
            if resolve_all_calcs is not None:
                new_raw, _ = resolve_all_calcs(new_raw)
            return new_raw, new_ans
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] symbolic solve 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

    def _reask_final_answer(self, ctx: TaskContext, reasoning: str,
                            answer: str) -> str:
        """答案疑似推理文本时，向模型定向重问一次"仅输出最终答案"。

        只在**抽取结果不可信**时触发（空 / 超长 / 含多步推导痕迹），
        正常答案直接原样返回，不增加任何开销。

        失败一律返回原答案——兜底动作不能让情况变得更糟。
        """
        if not self._answer_looks_suspicious(answer):
            return answer
        try:
            # 只喂推理尾部，避免长上下文拖慢这次短调用
            tail = reasoning[-1200:] if len(reasoning) > 1200 else reasoning
            system = (
                "你是数学答案格式化助手。只输出最终答案，不要解释、不要推导、"
                "不要任何多余文字。"
            )
            user = (
                "下面是某题的解答过程（可能不完整）。\n\n"
                f"{tail}\n\n"
                "请只输出这道题的最终答案，满足：\n"
                "1) 用 \\boxed{...} 包裹，例如 \\boxed{42}\n"
                "2) 下一行给出不含公式标记的最简形式，例如：最简形式：42\n"
                "3) 不要输出推导过程、单位说明或任何解释性文字\n"
                "4) 若答案是多个值，用逗号分隔放在同一个 \\boxed{} 内"
            )
            raw = self._compressed_solve(
                ctx, system, user,
                temperature=0.0,
                max_tokens=int(getattr(self.config, 'answer_reask_max_tokens', 256)),
            )
            if not raw:
                return answer
            new_ans = extract_final_answer(raw)
            if not new_ans:
                return answer
            # 重问结果必须"比原来更像答案"才采纳
            if self._answer_looks_suspicious(new_ans):
                return answer
            self.record(ctx, "answer_reask",
                        f"答案疑似推理文本（{len(answer)} 字符），定向重问后收敛为 "
                        f"{len(new_ans)} 字符")
            return new_ans
        except Exception as exc:  # noqa: BLE001
            logger.debug("[solver] 答案定向重问失败，保留原答案: %s", str(exc)[:120])
            return answer

    @classmethod
    def _answer_looks_suspicious(cls, answer: str) -> bool:
        """判断抽取出的答案是否"疑似推理文本"而非答案本身。

        判定按「长度 → 句式 → 结构」三级，且刻意保守：
        **误判的代价是一次短调用**，但把合法答案判成可疑会导致重问，
        所以 `{1, 3, 5}`、`x = 2, y = 3` 这类列表/多值答案必须放过。
        """
        a = (answer or "").strip()
        if not a:
            return True
        # 1) 过长：答案是短语，不是段落
        if len(a) > cls._SUSPICIOUS_ANSWER_LEN:
            return True
        # 2) 成句：出现句号或推理连接词，说明抽到的是叙述而非结论
        if "。" in a or "．" in a:
            return True
        for pat in cls._NARRATIVE_PAT:
            if re.search(pat, a):
                return True
        # 3) 推导链：**链式等号** `a = b = c`（两个等号之间没有被逗号分隔）。
        #    用"中间无逗号"把推导链与并列赋值区分开：
        #      - "S = 1 + 2 + 3 = 6"  → 链式，是计算过程
        #      - "x = 2, y = 3"       → 并列，是合法的多值答案
        if re.search(r"=[^,，]*=", a):
            return True
        return False

    def _generate_proof(self, ctx: TaskContext) -> Candidate | None:
        """使用证明题专用提示词生成分步编号的完整证明。"""
        from .base import Candidate, next_candidate_id
        conditions = "见题目"
        strategy_hint = "选择最合适的证明方法（直接证明/反证法/归纳法/构造法）"
        user = PROOF_TEMPLATE.format(
            problem=ctx.problem, conditions=conditions, strategy_hint=strategy_hint
        )
        # 2026-09-13：证明通道此前全文无 <calc> 字样 → 证明里的组合数/根式/幂
        # 只能心算。与主链同源复用 _CALC_GUIDE（user 侧，与主链风格一致）。
        if getattr(self.config, 'enable_calc_tool', True):
            user = user + _CALC_GUIDE
        # v2.4.1：证明通道同样走 prefill（完整 CoT 在本环境必然超时）
        raw = self._compressed_solve(
            ctx, PROOF_SYSTEM, user,
            temperature=0.3, max_tokens=self.config.max_answer_tokens,
        )
        if not raw or len(raw) < 30:
            return None
        raw = self._backfill_calc(ctx, raw)   # 与引导配套，防裸标记进答案
        answer = extract_final_answer(raw)
        if not answer or len(answer) > 300:
            answer = rescue_final_answer(raw)[0]
        if not answer:
            answer = smart_fallback_answer(raw)
        if not is_valid_final_answer(answer) and len(raw) > 0:
            # 2026-09-17：与文件内其它答案路径统一口径 —— **切片前先剥壳**。
            # 否则 `raw[-500:]` 会把尾部工具残留（实测 official112-025：
            # `</tool_call>`）当作答案落盘。惰性 import + 兜底：剥壳失败退回原切片。
            _raw_clean = raw
            try:
                from utils.extract import (_strip_calc_markers,
                                           _strip_toolcall_markers)
                _raw_clean = _strip_toolcall_markers(_strip_calc_markers(raw))
            except Exception:  # noqa: BLE001  剥壳失败不阻断
                pass
            answer = _raw_clean.strip()[-500:]
        cid = next_candidate_id(ctx.candidates)
        return Candidate(id=cid, reasoning=raw, answer=answer)

    def _compressed_solve(self, ctx: TaskContext, system: str, user: str,
                          temperature: float = 0.1,
                          max_tokens: int = 8192,
                          prefill_seed: str = "## 问题分析\n") -> str | None:
        """ICMA 同款压缩求解：prefill 种子抑制 CoT，快速产出答案。

        v2.4.1 起为本环境**主求解路径**：诊断实测完整 CoT 单次调用 >200s 不返回
        （780s 仍读超时），而 prefill 压缩求解 36.7s 即返回 ~2000 tokens 结构化解答。
        prefill 答案前置：即使输出被截断，也只损失思考、不损失答案。

        2026-09-04：prefill_seed 改为可配参数（默认 "## 问题分析\n" 适配主求解/证明
        四章节格式；revise 传 "【错误分析】\n"、self-improve 传 "【第一步：诊断】\n"
        与各自 system 要求的输出开头对齐，避免格式错位）。
        """
        try:
            msgs = prefill_messages(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                prefill_seed,
            )
            # 2026-09-09 试点：tool_calc_enabled=True 时走原生工具循环
            resp = self._maybe_tool_llm(ctx, msgs, temperature, max_tokens)
            if resp:
                return stitch(prefill_seed, resp)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("Compressed solve failed: %s", e)
            return None

    # ----------------------------------------------------------
    # 初始求解（蓝图分解 + 领域提示）
    # ----------------------------------------------------------
    def _generate_initial(self, ctx: TaskContext, count: int = None,
                          temperatures: list = None) -> None:
        """生成初始候选。

        参数:
            count: 候选数；None 时回退 config.policy_sample_times
                   （难题深度通道由 orchestrator 按档位传入）
            temperatures: 温度分层列表；None 时用默认 [0.1, 0.3, 0.5]
        """
        # 档位候选数：ctx.state.sample_times 优先（RunState 应急覆盖），config 兜底
        if count is None:
            if getattr(ctx.state, 'sample_times', None) is not None:
                count = ctx.state.sample_times
            else:
                tier_tbl = getattr(self.config, 'tier_sample_times', None)
                if tier_tbl:
                    count = tier_tbl.get(getattr(ctx, 'tier', 'standard'),
                                         self.config.policy_sample_times)
                else:
                    count = self.config.policy_sample_times
        # 领域自适应候选数
        count = self._adaptive_count(ctx, count)

        # 证明题专用通道（若启用）
        is_proof = False
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in (ctx.domain or "").lower() for k in proof_keywords):
            is_proof = True
        if is_proof and getattr(self.config, 'use_proof_channel', False):
            proof_cand = self._generate_proof(ctx)
            if proof_cand:
                ctx.candidates.append(proof_cand)
                self.record(ctx, "generate", f"证明题专用通道生成候选 #{proof_cand.id}")
                return
            self.record(ctx, "generate", "证明题专用通道未产出有效候选，回退通用求解")

        # lemma 上下文注入
        lemma_ctx = self._collect_lemma_context(ctx)

        if self.config.use_blueprint:
            system_prompt = get_policy_system(use_blueprint=True)
            domain_hint = get_domain_hint(ctx.domain) if ctx.domain else ""
            user_content = build_blueprint_user_message(ctx.problem, domain_hint)
        else:
            system_prompt = get_policy_system(use_blueprint=False)
            user_content = ctx.problem
            if ctx.domain:
                user_content = get_domain_hint(ctx.domain) + "\n" + ctx.problem

        # 注入 lemma 上下文
        if lemma_ctx:
            system_prompt = lemma_ctx + system_prompt

        # ICMA 对齐（v2.4.0）：末尾追加章节输出引导。系统 prompt 已要求四章节
        # 结构化输出并禁止思考过程，这里仅强调【最终答案】章节必须明确，不引导自由 CoT。
        #
        # 2026-08-30（#51 答案定型）：基线 45 题实测——**仅 7/45（15.6%）的推理里
        # 出现 \boxed{}**，5 题抽出的答案超过 60 字符（明显抽到了推理文本），
        # 且 `reference_matched` 精确匹配 45/45 全 False。本地宽松 LLM 判分能"看懂"，
        # 平台判分看不懂——这是「本地 46.7% vs 平台 20%」落差里可控性最高的一块。
        # 模型本身具备给出简洁答案的能力（#21 材料结论：模型可到 90 分），
        # 缺的是**强制定界**，故在提示词侧要求 \boxed{}，而非让抽取器去猜。
        _ANSWER_GUIDE = (
            "\n\n请严格按系统提示的四章节格式输出完整解答，"
            "确保【最终答案】章节给出明确、简洁的最终结论。"
        )
        if getattr(self.config, 'enable_answer_boxed', True):
            _ANSWER_GUIDE += (
                "\n【最终答案】章节中，最终结论必须且只能用 \\boxed{...} 包裹，"
                "并在其后另起一行给出不含任何公式标记的最简形式"
                "（例如：\\boxed{42}；最简形式：42）。"
                "\\boxed{} 内只放答案本身，不要放推导过程、单位说明或多余文字。"
            )
        user_content = user_content + _ANSWER_GUIDE

        # 2026-09-06 易错点记忆注入（A 档轻量经验，prompts/error_lessons.py）：
        # 命中题型/关键词才注入自查清单（无命中返回空串=零噪音）。
        # 放 user 侧题目之后、_make_one 并行之前——只拼一次，retry 不加倍。
        if getattr(self.config, 'enable_error_lessons', True):
            lessons_block = error_lessons_block(ctx)
            if lessons_block:
                user_content = user_content + "\n\n" + lessons_block
                self.record(ctx, "error_lesson",
                            f"注入历史易错自查清单 {error_lesson_ids(ctx)}")

        # 2026-09-01 calc_tool 集成（治 value_wrong）：告知模型计算环节可用
        # <calc>表达式</calc> 标记（精确分数算术 + SymPy 符号化简，白名单安全求值），
        # 系统会把标记替换为结果，避免模型算术错误污染推理与最终答案。
        # 2026-09-08 两轮扩容：sqrt/ln/log/exp + integral/符号变量/根式化简。
        if getattr(self.config, 'enable_calc_tool', True):
            user_content = user_content + _CALC_GUIDE

        # 题型差异化策略注入（v2.6）：
        #   选择题→选项逆推验证；判断题→不确定时合理猜测；
        #   证明题→逐步反复校验；解答题→附带答案结果检测；填空题→只输出结果。
        #
        # 2026-08-30（#45）：老师要求移除按题型分流、让 AI 按自身流程作答
        # （IMO 基本全为证明题，题型分支实测反而拉低证明题正确率）。
        # 此处改为 `enable_question_type_hint` 控制，**默认关闭**；需要 A/B
        # 对比或回归旧行为时置 True 即可，无需改代码。
        # 注：选择题的选项格式化属"输入信息补全"而非策略分流，故始终保留。
        # 2026-09-12 客观题特化（用户要求"保证能检测到题型并采取特化解题技巧"）：
        #   · 客观题（选择 / 判断 / 填空）与证明题的解题流程互斥，给它们注入
        #     特化纪律不触碰上面"证明题不分流"的既有结论；
        #   · 实测依据（official112 基线）：15 道客观题仅对 4 道——093/103 漏读
        #     E 项而缺项、101/111 判断方向反、102/106/110 概念题凭印象作答；
        #   · 开关 `objective_tactic_enabled`（默认 True）可一键回退旧行为，
        #     `enable_question_type_hint`（默认 False）仍可全题型强制开启。
        if getattr(ctx, 'question_type', ''):
            from .question_type import objective_injection
            _is_obj = ctx.question_type in ("选择题", "判断题", "填空题")
            _hint_on = bool(
                getattr(self.config, 'enable_question_type_hint', False)
                or (_is_obj and getattr(self.config, 'objective_tactic_enabled', True))
            )
            _inj = objective_injection(ctx.problem, ctx.question_type, _hint_on)
            if _inj:
                user_content = user_content + _inj
            # 埋点：客观题路由证据（题型 / 是否注入特化纪律 / 注入文本长度）。
            # 目的：让"是否真的走了特化策略"可被事后核验，而不是靠日志反推。
            try:
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["objective_route"] = {
                        "type": ctx.question_type,
                        "hint_injected": bool(_inj),
                        "injection_len": len(_inj),
                    }
                if _is_obj:
                    logger.info("[客观题路由] 题型=%s 注入=%d字符",
                                ctx.question_type, len(_inj))
            except Exception:  # noqa: BLE001
                pass

        # ★ 2026-09-15 补：**答案形态要求此前只注入子目标 / 蓝图路径，solver 主路径缺失**。
        # 本项目教训「只改一处路径 = 没改」：solver 是一条**独立的生成路径**，
        # 而上面注入的 `objective_injection` 只覆盖客观题（选择/判断/填空），
        # 于是解答题的形态要求（求所有→必须枚举 / 具体值→禁条件式 / 极值→严格性 /
        # 2026-09-15 新增的「哪些→完备性」）在**纯 solver 路径下根本没注入**。
        # 实测对应错题：099（"…离散化方法**有哪些**"，正解为多个，只答了一个）。
        # ⚠ 位置刻意放在 objective 注入之后、_ANSWER_GUIDE 之前：既不在提示词最末尾
        #   （避免模型进入续写模式），也不与客观题特化冲突（该函数对选择题/证明题返回空串）。
        try:
            from .question_type import answer_form_requirement as _afr_sv
            _afr_txt = _afr_sv(ctx.problem, getattr(ctx, 'question_type', '') or '')
            if _afr_txt:
                user_content = user_content + _afr_txt
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["answer_form_injected_solver"] = len(_afr_txt)
                self.record(ctx, "answer_form",
                            "solver 主路径注入答案形态要求 %d 字符" % len(_afr_txt))
        except Exception:  # noqa: BLE001
            pass

        # ★ 2026-09-17（M4）：id 基线改为 `max(已有 id)+1`。
        # 原用 `len(ctx.candidates)`，而腾位会让 len 变小 ⇒ 新 id 与旧 id 重叠
        # （实测 013 出现**两个 id=3**、025 出现 id=7）。下游按 id 匹配的地方
        # （`orchestrator` 的 `_gate_tried`、`formatter` 的簇内候选匹配）随之错位。
        base_cid = next_candidate_id(ctx.candidates)
        if temperatures is None:
            tier_tbl = getattr(self.config, 'tier_temperatures', None)
            temperatures = (tier_tbl.get(getattr(ctx, 'tier', 'standard'), [0.1, 0.3, 0.5])
                            if tier_tbl else [0.1, 0.3, 0.5])
        _STRATIFIED_TEMPS = temperatures

        def _make_one(i: int):
            cid = base_cid + i
            # 温度分层：按索引轮转取值（count>=3 时生效；deep 档 4 温度 0.1/0.3/0.5/0.7）
            base_temp = _STRATIFIED_TEMPS[i % len(_STRATIFIED_TEMPS)] if count >= 3 else self.config.policy_temperature
            # 候选 2+ 追加微扰动提示，引导不同解题思路
            _perturb_hints = [
                "",  # 候选 0: 无扰动（直接求解）
                "\n请特别注意计算过程中的每一步细节，确保数值精确。",  # 候选 1: 精度
                "\n如果可以，尝试用另一种方法重新审视这个问题。",  # 候选 2: 换方法
                "\n请先列出解题关键思路与可能用到的定理/公式，再逐步求解。",  # 候选 3: 计划先行
            ]

            # v2.4.1 主路径：prefill 压缩求解（诊断实测 37s 返回，答案前置不受截断影响）。
            # 本环境完整 CoT >200s 不返回（780s 仍读超时），prefill 是唯一保证
            # 300s 单题预算内出答案的路径。最多重试 2 次（原始 + 1 次重试）。
            resp = None
            template_leak_retry = False  # 标记是否为模板泄露后的重试
            for retry in range(2):
                # 2026-09-13 循环时间检查（防卡死）：单题上限已从 1200s 放开到
                # 3600s，必须在循环边界查时间，否则"单次 LLM 200-300s × 多次重试"
                # 会悄悄穿掉整题预算（实测 3_solve 曾超预算 1.7×）。
                # 只对"重试"生效（retry>0），保证首轮一定被尝试。
                if retry > 0 and ctx.gen_time_up():
                    self.record(ctx, "solver",
                                f"候选 {cid} 生成重试因时间到点提前停止")
                    break
                current_temp = base_temp
                current_system = system_prompt
                # 模板泄露重试时使用简化prompt（不覆盖）
                if template_leak_retry:
                    current_user = f"请直接解答以下数学问题，只输出解答过程和最终答案：\n\n{ctx.problem}"
                    current_system = _REINFORCED_SYSTEM
                    current_temp = max(self.config.policy_temperature, 0.7) + 0.1 * retry
                    template_leak_retry = False
                else:
                    current_user = user_content + (_perturb_hints[i % len(_perturb_hints)] if retry == 0 else "")
                    if retry > 0:
                        current_system = _REINFORCED_SYSTEM
                        current_temp = max(self.config.policy_temperature, 0.7) + 0.1 * retry

                # 主求解 = prefill（无完整 CoT 尝试；prefill 模式下模型输出克制，
                # max_tokens 上限 16384 已远超实测用量 ~2K token）
                resp = self._compressed_solve(
                    ctx, current_system, current_user,
                    temperature=current_temp,
                    # 9/4：平台不限 token，去 16384 帽（截断=腰斩丢分），收敛到 policy_max_tokens
                    max_tokens=self._adaptive_max_tokens(
                        ctx, self.config.policy_max_tokens),
                )
                # 空响应 -> 重试
                if resp is None or not resp.strip():
                    if retry < 1:
                        logger.warning("Candidate %d empty response (retry %d/1)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 模板泄露检测 → 重试
                if detect_template_leak(resp):
                    if retry < 1:
                        logger.warning("Candidate %d template leak (retry %d/1)", cid, retry + 1)
                        template_leak_retry = True
                        time.sleep(0.5)
                        continue
                # 英文think泄露 → 追问中文答案
                if _needs_followup(resp) and retry < 1:
                    logger.warning("Candidate %d English think leak → followup", cid)
                    # v2.4.1：followup 也走 prefill，防止完整 CoT 超时
                    followup_resp = self._compressed_solve(
                        ctx,
                        _REINFORCED_SYSTEM,
                        f"请用中文重新表达你的解答过程，并给出【最终答案】。\n\n上轮回答：\n{resp[-1500:]}\n\n请用中文写出完整解答和最终答案：",
                        temperature=0.3,
                        max_tokens=self._adaptive_max_tokens(
                            ctx, self.config.policy_max_tokens),
                    )
                    if followup_resp and followup_resp.strip():
                        if not detect_template_leak(followup_resp) and not _needs_followup(followup_resp):
                            resp = followup_resp
                            break  # 追问成功，跳出重试循环
                    time.sleep(0.5)
                    continue
                # 幻觉检测
                hallu = detect_hallucination(resp)
                if hallu:
                    logger.warning("Candidate %d hallucination detected: %s", cid,
                                   ", ".join(f"{h[0]}({h[1]:.0%})" for h in hallu))
                    # 42 兜底 → 尝试重试
                    if any("42" in h[0] for h in hallu) and retry < 1:
                        logger.warning("Candidate %d 42-dodge, retry", cid)
                        time.sleep(1)
                        continue
                # 截断检测 → 记录但不拒绝（后续由 orchestrator 续写）
                if detect_truncated(resp):
                    logger.info("Candidate %d truncated; will attempt completion", cid)
                # 拒绝回答 -> 重试
                if _is_refusal(resp):
                    if retry < 1:
                        logger.warning("Candidate %d refused to answer (retry %d/1)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 有效回答
                return cid, resp, False
            # 全部重试失败，返回最后一次响应
            return cid, resp, True

        # 并行生成候选（用线程池提高吞吐，限制最大并发防止 API 过载）
        # P0-4 修复：并行度 6→2，降低并发 API 超时/限流风险
        results = []
        max_workers = min(count, 2)
        # 2026-09-13 修复（实测"单题预算被跨墙 421s"的根因）：
        # 原实现**一次性把 count(6) 个候选全部 submit**，而线程池只有 2 个 worker
        # ⇒ 6 / 2 × 单次最坏 360s（`LLMClient` 180s × 重试 1）= **最坏 1080s**；
        # 且 `as_completed` 循环内**没有任何时间检查**、已提交任务**无法取消**
        # ⇒ 生成侧软截止 `gen_time_up()` 在这一整段**完全失效**。
        # 实测后果：004 实耗 1171s 而其 `soft_budget` 只有 750s（**超 421s**）、
        # 010 超 182s、016 超 87s —— 每题都越过自己的软预算。
        # 改为**分批提交 + 批间检查**：每批 `max_workers` 个，批间查生成侧截止，
        # 到点即停止提交剩余候选；**已产出的候选照常进入后续验证**（既有语义不变）。
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            _pending = list(range(count))
            while _pending:
                if results and ctx.gen_time_up():
                    self.record(ctx, "solver",
                                f"生成侧时间到，跳过剩余 {len(_pending)} 个候选"
                                f"（已完成 {len(results)}/{count}）")
                    break
                _batch, _pending = _pending[:max_workers], _pending[max_workers:]
                _futs = [pool.submit(_make_one, i) for i in _batch]
                for _f in as_completed(_futs):
                    results.append(_f.result())
        results.sort(key=lambda x: x[0])

        for cid, resp, is_fallback in results:
            if resp is None or (is_fallback and _is_refusal(resp)):
                # 2026-09-13 晚（用户硬要求「无论超没超时都要把答案生成出来」）：
                # 原实现在此 append 一个
                #   Candidate(id=cid, answer="",
                #             reasoning="[生成失败] 调用受限或模型拒绝回答")
                # 的**占位候选**，造成两个后果（4 题实测里 010/016 全中）：
                #   ① `ctx.candidates` 因此**非空** ⇒ orchestrator 的
                #      「Solver 未产出候选 → 触发兜底直接求解」（orchestrator.py:1158）
                #      永不触发；`_emergency_direct_solve` 那一整条路被绕开；
                #   ② formatter 的 `_REFUSAL_RE` 旧版不含这几个词 ⇒ 占位文本被当作
                #      合法答案直接提交，`predicted` 就是这串占位符。
                # 现改为：先尽力从残缺响应里抢救一个真实答案；抢救不到就**不 append**，
                # 让 `ctx.candidates` 保持空，把控制权交给下游兜底链
                # （orchestrator `_fallback_direct` → formatter `_emergency_answer`
                #  → user_agent 最终兜底）。
                _salvaged = ""
                if resp is not None and str(resp).strip():
                    _txt = str(resp)
                    try:
                        _salvaged = extract_final_answer(_txt) or ""
                        if not _salvaged and rescue_final_answer is not None:
                            _salvaged = rescue_final_answer(_txt)[0] or ""
                        if not _salvaged and smart_fallback_answer is not None:
                            _salvaged = smart_fallback_answer(_txt) or ""
                    except Exception:  # noqa: BLE001
                        _salvaged = ""
                _salvaged = (_salvaged or "").strip()
                if _salvaged and not _is_refusal(_salvaged) and len(_salvaged) <= 300:
                    ctx.candidates.append(Candidate(
                        id=cid, answer=_salvaged, reasoning=str(resp)))
                    logger.warning(
                        "Candidate %d 生成失败但抢救到答案: %s", cid, _salvaged[:60])
                else:
                    logger.warning(
                        "Candidate %d generation failed/skipped（无可用答案，"
                        "交由下游兜底）", cid)
                continue
            # 2026-09-01 calc_tool 回填：<calc>表达式</calc> → 精确值
            # （在答案抽取之前，让精确结果参与 answer 提取）
            _resolved = []          # 2026-09-10 L1：供答案自洽核验使用
            if resolve_all_calcs is not None and getattr(
                    self.config, 'enable_calc_tool', True):
                resp, _resolved = resolve_all_calcs(resp)
                self.record_calc_successes(ctx, _resolved)
                if audit_calc_fallbacks is not None:
                    for _ex, _rs in audit_calc_fallbacks(_resolved):
                        self.record(ctx, "calc_fallback",
                                    f"<calc>{_ex}</calc> → {_rs}",
                                    expr=_ex, reason=_rs)
                resp = self._maybe_calc_rewrite(ctx, resp)
                # 2026-09-12 修复（机制闭合）：_maybe_calc_rewrite 重写出的
                # `<calc>` 必须**立即回填**。原实现只在重写**之前**回填过一次，
                # 重写产生的标记无人求值 → `extract_final_answer` 读到的是未求值
                # 的标记文本，模型的心算值直接成为答案 —— 即"强制走工具"这一关
                # 白花一次 LLM 重问，目的完全落空。
                resp, _re2 = resolve_all_calcs(resp)
                self.record_calc_successes(ctx, _re2)
                if audit_calc_fallbacks is not None:
                    for _ex, _rs in audit_calc_fallbacks(_re2):
                        self.record(ctx, "calc_fallback",
                                    f"<calc>{_ex}</calc> → {_rs}",
                                    expr=_ex, reason=_rs)
            answer = extract_final_answer(resp)
            # 如果提取不到答案 / 答案过长（>300字符大概率是推理文本），
            # 先试 rescue 兜底（嵌套 boxed / 中段强模式结论），再取尾部
            if not answer or len(answer) > 300 and resp.strip():
                rescued = rescue_final_answer(resp)[0]
                if rescued:
                    answer = rescued
                else:
                    fallback = smart_fallback_answer(resp)
                    if fallback and (not answer or len(fallback) < len(answer)):
                        answer = fallback
            # 2026-08-30（#51）：上述兜底仍拿到"疑似推理文本"时，做一次**定向重问**，
            # 而不是把长文本当答案交给判分器。
            # 依据：基线 45 题有 5 题抽出的答案 >60 字符（含整段计算步骤与结论句），
            # 本地宽松判分能看懂、平台判分看不懂。模型具备给出简洁答案的能力，
            # 缺的是一次明确要求——成本仅一次短调用，收益是消除平台侧的格式性丢分。
            if (getattr(self.config, 'enable_answer_reask', True)
                    and not ctx.gen_time_up()):
                answer = self._reask_final_answer(ctx, resp, answer)
            # 2026-09-10 L1：数值答案工具自洽核验（默认关，见 AgentConfig）
            # ★ 表达式范式（默认形态，9/12 用户要求）：模型只建模（设符号+给算式），
            # 数值代入与运算由本地完成 → 答案取工具值。放在 selfcheck 之前，
            # 命中即可省掉一次"打回重写"。
            resp, answer = self._maybe_expression_eval(ctx, resp, answer)
            resp, answer = self._maybe_answer_selfcheck(ctx, resp, answer, _resolved)
            # 2026-09-10 L2：独立符号建模复核（默认关；每题最多一次）
            resp, answer = self._maybe_symbolic_crosscheck(ctx, resp, answer)
            # 2026-09-12 符号化方程求解通道（默认关）：模型只交方程（组）+ 目标，
            # 数值一律由本地 SymPy 回代求出（模型不参与计算），异议时回传工具结果。
            resp, answer = self._maybe_symbolic_solve(ctx, resp, answer)
            ctx.candidates.append(Candidate(
                id=cid,
                answer=answer,
                reasoning=resp,
                revised=False,
            ))
            logger.debug("Candidate %d generated (len=%d)", cid, len(resp))

        self.record(
            ctx, "solve",
            f"生成 {len(ctx.candidates)} 个候选解答 "
            f"(蓝图={self.config.use_blueprint}, 领域={ctx.domain})",
            count=len(ctx.candidates),
        )

    # ----------------------------------------------------------
    # 纠错重解（revise 模式）
    # ----------------------------------------------------------
    def _generate_revise(self, ctx: TaskContext, cap: int = None) -> None:
        feedback_text = "\n".join(f"- {fb}" for fb in ctx.revise_feedback)
        # 2026-09-06 易错点记忆注入（revise 补救侧）：修订时同步带上同类题
        # 历史易错自查清单（命中才注入），让重解不只针对反馈、也避开已知坑。
        if getattr(self.config, 'enable_error_lessons', True):
            lessons_block = error_lessons_block(ctx)
            if lessons_block:
                feedback_text = feedback_text + "\n" + lessons_block
                self.record(ctx, "error_lesson",
                            f"revise 注入历史易错自查清单 {error_lesson_ids(ctx)}")
        count = cap if cap is not None else self.config.revise_sample_times
        # ⚠ A 修复（2026-09-12）：**候选池满时先腾位，而不是静默 return**。
        # 依据：6.5 的「拒绝 → 换候选 / 重解」是唯一的纠错回路，但 candidates
        # 常态就是 6 个 → `6 - len(candidates)` = 0 → count=0 → return
        # → **最需要重解时反而重解不了**（实测 revise_round 恒为 0，反馈白给）。
        _room = 6 - len(getattr(ctx, "candidates", None) or [])
        if _room <= 0 and getattr(ctx, "revise_feedback", None):
            # ★ 2026-09-17（M3）：腾位改为**按验证票数保留最优 3 个** ——
            # 口径与实现统一在 `base.pick_best_candidates`（可被单测直接覆盖）。
            # 原规则 `[-3:]` 按 id 尾部保留"最新"的 3 个，与正确性无关：若新追加
            # 的候选恰好最差，就会留下最差 3 个、丢掉初始解（通常较好）。
            _keep = pick_best_candidates(ctx.candidates,
                                         getattr(ctx, "verdicts", None), k=3)
            self.record(ctx, "revise",
                        f"候选池满（{len(ctx.candidates)} 个）→ 腾位至 3 个，"
                        f"为重解让出槽位（A 修复 2026-09-12）")
            ctx.candidates = _keep
            _room = 6 - len(ctx.candidates)
        count = max(0, min(count, _room))
        # B 埋点（2026-09-12）：把「重解到底跑没跑、为什么没跑」全部记下来——
        # 此前三处静默路径（候选满 / 时间不足 / 反馈空）无法区分，
        # 导致「反馈给了模型却仍答错」无法定位。
        if count <= 0:
            self.record(ctx, "revise",
                        f"重解**未启动**：可用槽位 {count}"
                        f"（候选 {len(getattr(ctx, 'candidates', None) or [])} 个、"
                        f"反馈 {len(getattr(ctx, 'revise_feedback', None) or [])} 条、"
                        f"cap={cap}）")
            return
        self.record(ctx, "revise",
                    f"重解**启动**：count={count}、"
                    f"反馈 {len(ctx.revise_feedback)} 条、"
                    f"revise_round={getattr(ctx, 'revise_round', 0)}、"
                    f"报文首 {str(feedback_text)[:80]}")

        # ★ 2026-09-17（M4）：id 基线改为 `max(已有 id)+1`。
        # 原用 `len(ctx.candidates)`，而腾位会让 len 变小 ⇒ 新 id 与旧 id 重叠
        # （实测 013 出现**两个 id=3**、025 出现 id=7）。下游按 id 匹配的地方
        # （`orchestrator` 的 `_gate_tried`、`formatter` 的簇内候选匹配）随之错位。
        base_cid = next_candidate_id(ctx.candidates)

        # 2026-09-13 方案 A（revise 的**唯一**数值来源）：REVISE_USER_TEMPLATE
        # 只含「题目 + 反馈」，**不含上一轮解答全文** ⇒ 被 revise 的那批候选的
        # `reasoning` 里的 [计算] 行根本不在新 prompt 视野内，模型只能重算。
        # 故在提交前先把**候选池现有候选的 reasoning** 汇总一次（revise 是**批量**
        # 重解、不针对单个候选对象，故数据源 = 现有候选 reasoning 的并集，
        # 与上方"腾位"后的候选池保持一致），再拼进每条 revise 报文。
        _trace_src = "\n".join(
            str(getattr(c, "reasoning", "") or "")
            for c in (getattr(ctx, "candidates", None) or []))
        _trace_block = _calc_trace_block(
            _trace_src, getattr(ctx, "calc_prewarm_block", None))

        # ★ 2026-09-17（M7）：把「上一轮解答」**真正**喂给 revise。
        # REVISE_SYSTEM 第 1/3 条明确要求“认真阅读【上一轮错误解答】”「保留正确的
        # 推理部分」，但 user 模板此前**只有题目 + 反馈** ⇒ 模型无从保留，只能整题
        # 重解。这正是 revise 越改越差的机制之一（013 蓝图 d=50 → revise 改成 19、
        # 025 蓝图 4 → 直答 509040-2*169680）。此处给出上一轮各候选的答案清单
        # 与主推理尾部，使“保留正确部分”成为可执行指令。
        _prev_lines = []
        for _pc in (getattr(ctx, "candidates", None) or [])[:6]:
            _pa = str(getattr(_pc, "answer", "") or "").strip()
            if _pa:
                _prev_lines.append("· 候选#%s 答案：%s"
                                   % (getattr(_pc, "id", "?"), _pa))
        _cs_all = list(getattr(ctx, "candidates", None) or [])
        _main_reasoning = ""
        if _cs_all:
            _main_reasoning = max(
                (str(getattr(_c2, "reasoning", "") or "") for _c2 in _cs_all),
                key=len)
        _prev_block = "\n".join(_prev_lines) or "（无——本轮无既有候选答案）"
        if _main_reasoning:
            _prev_block += ("\n\n（上一轮主推理尾部 1200 字，供沿用正确结论）\n"
                            + _main_reasoning[-1200:])

        def _make_one(i: int):
            cid = base_cid + i
            user_content = REVISE_USER_TEMPLATE.format(
                problem=ctx.problem, feedback=feedback_text,
                prev_answer=_prev_block)
            # 2026-09-13：revise 此前无 calc 引导，且整段重写会把子目标链已回填
            # 的 [计算] 精确值洗成新的心算值 → 同源追加引导 + 显式"沿用痕迹"要求。
            # 方案 A：再前置「系统已算出的精确值」清单（扫不到 [计算] 行时，
            # `_trace_block` 退回纯纪律段，不留空标题）。
            if getattr(self.config, 'enable_calc_tool', True):
                user_content = user_content + _CALC_GUIDE + _trace_block
            for retry in range(3):
                # 2026-09-13 循环时间检查（防卡死）：同 _generate_initial 处说明。
                # 本函数在线程池内并行执行，到点即 break，避免"重试 × 并行"叠加穿预算。
                if retry > 0 and ctx.gen_time_up():
                    self.record(ctx, "revise",
                                f"revise 候选 {cid} 重试因时间到点提前停止")
                    break
                # v2.4.1：revise 也走 prefill（完整 CoT 在本环境必然超时）
                # 2026-09-04：prefill 种子与 REVISE_SYSTEM 五段格式对齐——【错误分析】开头
                resp = self._compressed_solve(
                    ctx, REVISE_SYSTEM, user_content,
                    temperature=self.config.policy_temperature,
                    max_tokens=self._adaptive_max_tokens(
                        ctx, self.config.policy_max_tokens),
                    prefill_seed="【错误分析】\n",
                )
                if resp is not None and resp.strip():
                    # 幻觉/拒绝检测（与 _generate_initial 一致）
                    hallu = detect_hallucination(resp)
                    if any("42" in h[0] for h in hallu) and retry < 2:
                        logger.warning("Revise %d 42-dodge (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                        continue
                    if _is_refusal(resp) and retry < 2:
                        logger.warning("Revise %d refused (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                        continue
                    if detect_truncated(resp):
                        logger.info("Revise %d truncated; will attempt completion", cid)
                    return cid, resp
                if retry < 2:
                    logger.warning("Revise candidate %d empty response (retry %d/2)", cid, retry + 1)
                    time.sleep(1)
            return cid, resp

        # 并行生成修正候选
        results = []
        max_workers = min(count, 6)
        # 2026-09-13：与 `_generate_initial` 同款修复 —— 改**分批提交 + 批间检查**。
        # 原实现一次性提交全部候选且 `as_completed` 内无任何时间检查、已提交任务无法取消
        # ⇒ 生成侧软截止 `gen_time_up()` 在这段失效（该病理已在 3_solve 实测造成
        # 单题超出软预算 421s，见 `_generate_initial` 处注释）。
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            _pending = list(range(count))
            while _pending:
                if results and ctx.gen_time_up():
                    self.record(ctx, "revise",
                                f"生成侧时间到，跳过剩余 {len(_pending)} 个修正候选"
                                f"（已完成 {len(results)}/{count}）")
                    break
                _batch, _pending = _pending[:max_workers], _pending[max_workers:]
                _futs = [pool.submit(_make_one, i) for i in _batch]
                for _f in as_completed(_futs):
                    results.append(_f.result())
        results.sort(key=lambda x: x[0])

        for cid, resp in results:
            if resp is None:
                ctx.candidates.append(Candidate(
                    id=cid, answer="", reasoning="[重解失败] 调用受限"))
                logger.warning("Revise candidate %d failed/skipped", cid)
                continue
            # 2026-09-01 calc_tool 回填（与 _generate_initial 一致）
            if resolve_all_calcs is not None and getattr(
                    self.config, 'enable_calc_tool', True):
                resp, _resolved = resolve_all_calcs(resp)
                self.record_calc_successes(ctx, _resolved)
                if audit_calc_fallbacks is not None:
                    for _ex, _rs in audit_calc_fallbacks(_resolved):
                        self.record(ctx, "calc_fallback",
                                    f"<calc>{_ex}</calc> → {_rs}",
                                    expr=_ex, reason=_rs)
                resp = self._maybe_calc_rewrite(ctx, resp)
                # 2026-09-12 修复（机制闭合）：_maybe_calc_rewrite 重写出的
                # `<calc>` 必须**立即回填**。原实现只在重写**之前**回填过一次，
                # 重写产生的标记无人求值 → `extract_final_answer` 读到的是未求值
                # 的标记文本，模型的心算值直接成为答案 —— 即"强制走工具"这一关
                # 白花一次 LLM 重问，目的完全落空。
                resp, _re2 = resolve_all_calcs(resp)
                self.record_calc_successes(ctx, _re2)
                if audit_calc_fallbacks is not None:
                    for _ex, _rs in audit_calc_fallbacks(_re2):
                        self.record(ctx, "calc_fallback",
                                    f"<calc>{_ex}</calc> → {_rs}",
                                    expr=_ex, reason=_rs)
            answer = extract_final_answer(resp)
            if not answer or len(answer) > 300:
                answer = rescue_final_answer(resp)[0]
            if not answer:
                answer = smart_fallback_answer(resp)
            ctx.candidates.append(Candidate(
                id=cid,
                answer=answer,
                reasoning=resp,
                revised=True,
            ))

        self.record(
            ctx, "revise",
            f"纠错重解 第{ctx.revise_round}轮：生成 {count} 个修正候选",
            round=ctx.revise_round,
        )

    # ----------------------------------------------------------
    # Step 2 无条件自改进（IMO2025 验证-精炼论文，2026-08-29）
    # ----------------------------------------------------------
    def improve_candidates(self, ctx: TaskContext) -> int:
        """对已有候选做一遍 review+improve（论文流水线 Step 2）。

        论文（Huang & Yang 2025）观测：初始解质量普遍低，Step 2 给模型
        注入第二段推理预算后输出显著改进。与 revise 的关键区别：
        revise 是**验证失败才修正**（有条件），自改进是**无条件先做一遍**。

        成本：每候选 1 次 LLM 调用，默认最多 self_improve_max=3 个候选
        （fast 档与应急模式由调用方跳过）。改进成功返回候选数。

        2026-09-01（SU-01 优化 2，论文 §3.3 防递归）：
        跳过已 self_improved=True 的候选（防"对同一候选循环调用 Step2"，
        论文 SU-01 不递归入队失败精炼，对齐此约束）。
        """
        def _needs_improve(c) -> bool:
            """A2（2026-09-11）：只在候选「看起来有问题」时才自改进。

            依据：smoke6_v3 实测「无条件改进」只有成本没有收益 ——
            3.3 占单题 29~45% 耗时（总耗时 +34%），而正确率 1/6 完全不变，
            且 098 被从正确答案改错。故改为**条件触发**：仅当候选存在
            明显缺陷（答案缺失/过短、推理被截断、推理过短）才值得花一次调用。
            开关：SELF_IMPROVE_CONDITIONAL（默认 1；设 0 = 恢复无条件旧行为，便于 A/B）。
            """
            if os.environ.get("SELF_IMPROVE_CONDITIONAL", "1") == "0":
                return True
            _ans = str(getattr(c, "answer", "") or "").strip()
            _rs = str(getattr(c, "reasoning", "") or "")
            if not _ans or len(_ans) < 2:                     # ① 答案缺失/过短
                return True
            if any(k in _rs for k in ("...", "[已截断]", "未完成", "待续")):
                return True                                    # ② 推理被截断
            if len(_rs) < 400:                                 # ③ 推理过短（未充分展开）
                return True
            return False                                       # 看起来完整 → 不改

        cands = [c for c in ctx.candidates
                 if getattr(c, "reasoning", "")
                 and not c.reasoning.startswith("[")
                 and not getattr(c, "self_improved", False)
                 and _needs_improve(c)]
        limit = int(getattr(self.config, "self_improve_max", 3))
        targets = cands[:limit]
        if not targets:
            return 0

        n_ok = 0
        _imp_min_remaining = float(
            getattr(self.config, "improve_min_remaining", 0.0) or 0.0)
        for cand in targets:
            # 2026-09-06：升级 gen_time_up——仅 is_time_critical 会在单候选
            # 300s 级 LLM 调用前放行最后 1-2 个候选，烧穿剩余预算（冒烟
            # nt-031 3.3=595s / algebra-003 3.3=325s 实证），须按生成侧软截止停。
            # N1''（2026-09-11 修正）：**改回硬墙口径**。原因：外层（orchestrator）
            # 已判定 3.3 该跑（用 time_remaining 门槛放行），但 3.3 排在 2.7/3_solve
            # 之后，而 gen_time_up() 用的是 _gen_deadline(=deadline−480s)=720s——
            # 走到这里必然已越过 → 内层立刻 break → 外层放行被作废（smoke6_v2
            # 六题 3.3 恒为 0s 的最终原因）。改为只防"逼近 1200s 硬墙"。
            if ctx.is_time_critical():
                break
            # 2026-09-07（A，冒烟 alg-060 3.3=640s 烧穿实证）：单候选改进
            # 是一次 200-300s 不可打断的 LLM 调用——仅靠 gen_time_up（=烧到
            # 生成软截止才停）会让"正在跑的最后一个候选"把验证预留吃光，
            # 6.5 终局 Lean/Audit 闸门 time_critical 饿死。
            # 预留 single-call 最坏成本：距生成软截止不足 improve_min_remaining
            # （默认 300s）即停手不再开新候选，把验证预算完整留给 4_verify+6.5。
            # N1''（2026-09-11 修正）：**基准改为硬墙 deadline，而非 _gen_deadline**。
            # 原因同 L37：_gen_deadline(720s) 是"生成类"的统一截止，3.3 走到这里
            # 必然已越过，用它做差会出现负值 → 恒 break（第三层拦截，实测默认
            # improve_min_remaining=300 时 100% 触发）。改用 deadline(1200s) 起算，
            # 语义仍是"给单候选最坏成本留够余量"，但不会在 3.3 处必然失败。
            _hd = float(getattr(ctx, "deadline", 0.0) or 0.0)
            if (_imp_min_remaining > 0 and _hd >= 10**8
                    and _hd - time.time() < _imp_min_remaining):
                self.record(ctx, "paper_pacer",
                            f"Step2 自改进停手：距硬墙 {_hd - time.time():.0f}s < "
                            f"{_imp_min_remaining:.0f}s（单候选最坏成本预留），"
                            f"不再改进剩余候选")
                break
            user_content = SELF_IMPROVE_USER.format(
                problem=ctx.problem,
                candidate_solution=cand.reasoning,
            )
            # 2026-09-13：【当前解答】里含子目标链回填的 [计算] 精确值，自改进
            # 若整段重写极易把它们换回心算值 → 同源追加引导 + 显式"沿用痕迹"要求。
            # 方案 A：数据源即**被改进候选的 reasoning**（[当前解答] 全文），
            # 把其中的 [计算] 行汇总前置为值清单（扫不到则退回纯纪律段）。
            if getattr(self.config, 'enable_calc_tool', True):
                user_content = (
                    user_content + _CALC_GUIDE
                    + _calc_trace_block(getattr(cand, "reasoning", ""),
                                        getattr(ctx, "calc_prewarm_block", None)))
            # 2026-09-04：prefill 种子与 SELF_IMPROVE_USER 三步法对齐——【第一步：诊断】开头
            resp = self._compressed_solve(
                ctx,
                get_policy_system(use_blueprint=getattr(self.config, "use_blueprint", True)),
                user_content,
                temperature=0.1,
                max_tokens=self._adaptive_max_tokens(
                    ctx, self.config.policy_max_tokens),
                prefill_seed="【第一步：诊断】\n",
            )
            if not resp or not resp.strip():
                # 观测埋点（2026-09-11）：3.3 此前只报"完成 N 个"，失败出口
                # （空/拒绝/过短）**全部静默 continue** → 跑了几百秒却看到 n_imp=0
                # 却无从定位（smoke6_v3 实证：3.3=365s 但"自改进完成"0 条）。
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：空响应")
                continue
            if _is_refusal(resp):
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：模型拒绝作答")
                continue
            # 改进版比原版还差（明显更短/空壳）则丢弃
            _thr = max(40, len(cand.reasoning) // 3)
            if len(resp.strip()) < _thr:
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：输出过短"
                            f"（{len(resp.strip())} < 门槛 {_thr}）")
                continue
            resp = self._backfill_calc(ctx, resp)   # 与 _CALC_GUIDE 注入配套
            answer = extract_final_answer(resp)
            if not answer or len(answer) > 300:
                answer = rescue_final_answer(resp)[0]
            if not answer:
                answer = smart_fallback_answer(resp)
            # B 方案（2026-09-11，本地实验）：**覆盖前先把原版保留为独立候选**。
            # 依据：smoke6_v3 实证 098 原候选答 B（正确），3.3 自改进后被改成 D
            # （错误）——「无条件替换」会把好答案直接改坏，且没有任何回退机制。
            # 现在改为"原版 + 改进版并存"，交由下游验证/投票择优（不改变下游逻辑）。
            # 开关：SELF_IMPROVE_KEEP_ORIGINAL（默认 1）。
            if os.environ.get("SELF_IMPROVE_KEEP_ORIGINAL", "1") != "0":
                try:
                    import copy as _copy
                    _orig = _copy.copy(cand)
                    _orig.id = 1 + max(
                        [int(getattr(c, "id", 0) or 0) for c in ctx.candidates] or [0])
                    _orig.self_improved = True      # 防对同一份再改进
                    _orig.source = (getattr(cand, "source", "") or "") + "+pre_improve"
                    ctx.candidates.append(_orig)
                    self.record(ctx, "self_improve",
                                f"Step2 保留原版候选#{_orig.id}"
                                f"（答案 {str(getattr(_orig, 'answer', ''))[:30]}），"
                                f"改进版写入#{getattr(cand, 'id', '?')}")
                except Exception as _ce:  # noqa: BLE001
                    self.record(ctx, "self_improve",
                                f"Step2 保留原版失败（{type(_ce).__name__}）→ 走覆盖")
            cand.reasoning = resp
            if answer:
                cand.answer = answer
            # 2026-09-01（SU-01 优化 2）：标记 self_improved，下次再调 Step2 跳过此候选
            cand.self_improved = True
            n_ok += 1
            time.sleep(0.3)  # 速率限制

        if n_ok:
            self.record(ctx, "self_improve",
                        f"Step2 自改进 {n_ok}/{len(targets)} 个候选")
        return n_ok

    # ----------------------------------------------------------
    # 兜底直接求解（所有候选都失败时的 last-resort）
    # ----------------------------------------------------------
    def direct_solve(self, ctx: TaskContext) -> str:
        """
        用最简提示词直接求解（跳过蓝图分解和领域提示），
        要求模型必须输出【最终答案】。适用于所有多智能体候选均失败时兜底。
        返回最终答案字符串。
        """
        direct_system = _REINFORCED_SYSTEM + "\n\n请直接在【最终答案】中给出答案，不要省略任何步骤。"
        user_content = f"请仔细求解以下数学问题，必须给出确定的答案。\n\n题目：\n{ctx.problem}"
        # 2026-09-13：兜底直答此前无 calc 引导。这里是"最后防线"，**只加一行**
        # 短要求（_CALC_SHORT_HINT），不塞整段 _CALC_GUIDE 把短 prompt 撑失衡。
        if getattr(self.config, 'enable_calc_tool', True):
            user_content = user_content + _CALC_SHORT_HINT
        # P0-4 修复：兜底场景用 prefill 让答案前置——时间紧时优先保答案而非推理
        # 2026-09-13 修复（截断重试提示从未生效）：消息必须**每轮现建** —— 原先
        # 循环外先建好 base_msgs，下面的截断重试只改了 user_content，实际发出的
        # 仍是 base_msgs，续写提示从未进入模型调用。

        for attempt in range(3):
            # 2026-09-13 循环时间检查（防卡死）：兜底路径是"最后防线"，故用**最
            # 宽松**口径 —— 只在**单题硬超时**时才停（而非生成侧软截止），保证
            # "无论如何先出一个答案"的兜底价值不被削弱；同时防止 3 次重试
            # （单次可达 180s+）叠加穿掉单题上限。
            if attempt > 0 and ctx.is_timed_out():
                self.record(ctx, "direct_solve", "单题已超时，停止兜底重试")
                break
            try:
                _msgs = [
                    {"role": "system", "content": direct_system},
                    {"role": "user", "content": user_content},
                ]
                resp = self.llm(
                    ctx,
                    prefill_messages(_msgs, "最终答案："),
                    0.1 if attempt == 0 else 0.4,   # 首次低温，重试时提高温度
                    8192,
                )
                if resp:
                    resp = stitch("最终答案：", resp)
            except Exception:  # noqa: BLE001
                resp = None

            if resp and resp.strip() and not _is_refusal(resp):
                # 幻觉检测：42 兜底 → 重试
                hallu = detect_hallucination(resp)
                if any("42" in h[0] for h in hallu) and attempt < 2:
                    logger.warning("Direct solve %d 42-dodge (retry)", attempt + 1)
                    time.sleep(1)
                    continue
                # 截断检测 → 要求模型补充
                if detect_truncated(resp):
                    logger.warning("Direct solve %d truncated → retry with continuation prompt", attempt + 1)
                    if attempt < 2:
                        user_content = (
                            f"上一轮你的回答被截断在：{resp[-200:]}\n\n"
                            f"请从截断处续写，给出完整的最终答案。原题目：\n{ctx.problem}"
                        )
                        self.record(ctx, "direct_solve", f"截断重试 (attempt {attempt + 2})")
                        continue
                resp = self._backfill_calc(ctx, resp)   # 与 _CALC_SHORT_HINT 配套
                answer = extract_final_answer(resp)
                if answer:
                    self.record(ctx, "direct_solve", f"兜底直接求解成功 (attempt {attempt + 1})")
                    return answer
                # 常规提取失败 → rescue 兜底（嵌套 boxed / 中段强模式）
                rescued = rescue_final_answer(resp)[0]
                if rescued:
                    self.record(ctx, "direct_solve",
                               f"兜底求解成功但常规提取失败，rescue 截取 (attempt {attempt + 1})")
                    return rescued
                # 仍失败，取全文作为答案
                self.record(ctx, "direct_solve",
                           f"兜底求解成功但提取失败，使用全文 (attempt {attempt + 1})")
                return smart_fallback_answer(resp)
            logger.warning("Direct solve attempt %d/3 returned empty or refused", attempt + 1)
            time.sleep(1)

        self.record(ctx, "direct_solve", "兜底直接求解失败")
        return ""

    # ----------------------------------------------------------
    # 截断候选批量续写（P0-3）
    # ----------------------------------------------------------
    def complete_truncated_candidates(self, ctx: TaskContext, max_count: int = 1) -> int:
        """对截断的候选发起续写，把完成的候选放回列表。返回续写成功数量。

        P0-4 修复：默认只续写"最有希望恢复"的 1 个截断候选（reasoning 最长的
        即信息最全、最接近完成的），避免 3 候选 × 多轮续写耗尽单题预算 → 45 error。
        修复：此前 orchestrator 只在日志里记录 truncated，从不真正续写，
        导致 65% 被截断的候选答案丢失 → invalid。
        """
        truncated = [c for c in ctx.candidates
                     if c.reasoning and c.reasoning.strip() and detect_truncated(c.reasoning)]
        if not truncated:
            return 0
        # 选信息最全的截断候选优先续写
        truncated.sort(key=lambda c: len(c.reasoning), reverse=True)
        chosen = truncated[:max_count]

        completed = 0
        new_list = []
        for c in ctx.candidates:
            if c not in chosen:
                new_list.append(c)
                continue
            # 预算允许才续写（2026-09-06 升级 gen_time_up）
            if not ctx.gen_time_up():
                new_c = self.complete_answer(ctx, c)
                if new_c is not c and new_c.answer and len(new_c.answer) > 1:
                    new_list.append(new_c)
                    completed += 1
                    self.record(ctx, "complete", f"候选 #{c.id} 截断续写成功")
                    continue
            new_list.append(c)
        ctx.candidates = new_list
        return completed

    # ----------------------------------------------------------
    # 答案完整性检查与续写
    # ----------------------------------------------------------
    def is_answer_complete(self, reasoning: str, answer: str) -> bool:
        """
        检查推理是否完整（未被截断、有明确结论）。
        返回 True 表示完整，False 表示可能不完整。
        """
        if not reasoning or not reasoning.strip():
            return False
        text = reasoning.strip()
        # 1) 推理过短 → 可能不完整
        if len(text) < 400:
            # 有明确答案 → 仍然算完整
            # ★ 2026-09-16 审计修复：`len(answer) > 3` → 非空即可。
            #   单字母/个位数是合法完整答案（选择 A、判断 T、填空 7）。
            if answer and answer.strip() and not _is_refusal(text):
                return True
            return False
        # 2) 末尾是否完整结束
        tail = text[-200:]
        complete_endings = re.compile(
            r"([。！？\.!\?\)）】」』\"'']\s*$|\\boxed\{.+\}\s*$|"
            r"最终答案|【最终答案】|答案为|故选|因此|综上)",
        )
        if complete_endings.search(tail):
            return True
        # 3) 末尾是否像被截断（以逗号/and/or/且/并结尾）
        truncation_hints = re.compile(
            r"([,，\s]$|and\s*$|or\s*$|且\s*$|并\s*$|然后\s*$|"
            r"还有\s*$|此外\s*$|另外\s*$|以及\s*$)",
        )
        if truncation_hints.search(text[-50:]):
            logger.debug("Answer appears truncated at end")
            return False
        # 4) 最后一行特别短且无结束标点 → 可能被截断
        last_line = text.split("\n")[-1].strip()
        if last_line and len(last_line) < 30 and not re.search(r"[。！？\.!\?\)）】」』]", last_line):
            # 但如果包含答案关键词 / LaTeX，可能正常
            if re.search(r"\$|答案|boxed|[=＝]", last_line):
                return True
            return False
        return True

    _COMPLETE_SYS = (
        "你是数学解题专家，正在完成一段被中断的推理。"
        "请直接续写剩下的推导并给出最终答案。"
    )
    _ANSWER_PREFIX_SYS = (
        "你是数学解题专家。根据下面被截断的推理，直接给出最终答案。"
        "只输出答案本身（数值、表达式或选项字母），不要解释、不要推理过程。"
    )

    def complete_answer(self, ctx: TaskContext, candidate: Candidate) -> Candidate:
        """
        对不完整的推理进行续写。

        P0-2/P0-3 强化：先尝试续写推理；若仍提取不到答案，
        再用【答案前置】紧急重问（prefill 精神：答案在前，截断不丢）。
        """
        if not candidate.reasoning or not candidate.reasoning.strip():
            return candidate

        reasoning = candidate.reasoning.strip()
        # 取尾部 1500 字符作为续写上下文
        context_tail = reasoning[-1500:]

        continue_prompt = (
            "你的推理在下面中断了，请直接从断点处继续完成推理，"
            "并在最后给出【最终答案】。不要重复之前的内容，直接接着写：\n\n"
            f"--- 断点 ---\n{context_tail}\n--- 请继续 ---"
        )
        # 2026-09-13：续写此前无 calc 引导；此处只加一行短要求（断点原文里
        # 已有 [计算] 回填值，故 _CALC_SHORT_HINT 同时要求沿用，不重算）。
        if getattr(self.config, 'enable_calc_tool', True):
            continue_prompt = continue_prompt + _CALC_SHORT_HINT

        # P0-4 修复：续写仅 1 次（2+1→1+1），压缩调用链防超时
        for attempt in range(1):
            try:
                # v2.4.1：续写也走 prefill（断点种子抑制 CoT，防 4096 token 超时）
                continuation = self.llm(
                    ctx,
                    prefill_messages(
                        [
                            {"role": "system", "content": self._COMPLETE_SYS},
                            {"role": "user", "content": continue_prompt},
                        ],
                        "--- 请继续 ---\n",
                    ),
                    0.2,
                    4096,
                )
                if continuation:
                    continuation = stitch("--- 请继续 ---\n", continuation)
            except Exception:
                continuation = None

            if continuation and continuation.strip():
                continuation = self._backfill_calc(ctx, continuation)
                # 合并推理
                full_reasoning = reasoning + "\n\n[续写]\n" + continuation.strip()
                new_answer = extract_final_answer(full_reasoning)
                if not new_answer:
                    new_answer = rescue_final_answer(full_reasoning)[0]
                if not new_answer:
                    new_answer = smart_fallback_answer(continuation)
                if new_answer:
                    self.record(ctx, "complete",
                               f"答案续写成功 (attempt {attempt + 1})")
                    return Candidate(
                        id=candidate.id,
                        answer=new_answer,
                        reasoning=full_reasoning,
                        revised=candidate.revised,
                    )
            logger.warning("Answer completion attempt %d returned empty", attempt + 1)
            time.sleep(0.5)

        # 答案前置紧急重问（P0-4：正式 prefill）：即使推理不全，也要把答案抢救出来。
        # 用 assistant 前缀"最终答案："抑制 CoT 开启，答案从开头生成——截断不丢答案。
        # 2026-09-13：该路径此前无 calc 引导。因其 system 明确要求"只输出答案本身"，
        # 这里**只加一句**位置在末行之前的短许可（不塞 _CALC_GUIDE，防破坏答案格式）。
        _emergency_calc_hint = (
            "\n\n若该答案由开方/对数/组合数/幂等易错运算得出，可先用 "
            "<calc>表达式</calc> 给出算式（系统会精确求值）；"
            "但**最后一行仍只写答案本身**。"
            if getattr(self.config, 'enable_calc_tool', True) else ""
        )
        try:
            _prefill_msgs = prefill_messages(
                [
                    {"role": "system", "content": self._ANSWER_PREFIX_SYS},
                    {"role": "user",
                     "content": f"被截断的推理片段：\n{context_tail}"
                                f"{_emergency_calc_hint}"},
                ],
                "最终答案：",
            )
            direct = self.llm(ctx, _prefill_msgs, 0.0, 32768)
            if direct:
                direct = self._backfill_calc(ctx, stitch("最终答案：", direct))
            if direct and direct.strip():
                direct_ans = smart_fallback_answer(direct)
                if direct_ans:
                    self.record(ctx, "complete", "答案前置重问成功")
                    return Candidate(
                        id=candidate.id,
                        answer=direct_ans,
                        reasoning=reasoning + "\n\n[答案重问]\n" + direct.strip(),
                        revised=candidate.revised,
                    )
        except Exception as e:
            logger.warning("Answer prefill retry failed: %s", e)

        self.record(ctx, "complete", "答案续写失败，使用原始答案")
        return candidate
