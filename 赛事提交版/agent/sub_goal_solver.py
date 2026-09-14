"""
子目标求解智能体（SubGoalSolverAgent）
===================================

将数学问题分解为有序子目标，逐步求解后合并结论。

与 SolverAgent 的关系：
- SolverAgent：一次性生成多个候选解答（含蓝图分解在内的一步式求解）
- SubGoalSolverAgent：先规划子目标树，再逐步求解每个子目标，最后合并

流程：
  1. 子目标规划 (plan)  →  结构化 JSON 子目标列表
  2. 逐步求解 (step)    →  按依赖顺序依次求解每个子目标
  3. 结论合并 (merge)   →  组装最终答案并输出 Candidate
"""

import json
import logging
import os
import re
import time

from .base import BaseAgent, TaskContext, Candidate

try:
    from prompts.sub_goal import (
        SUBGOAL_PLAN_SYSTEM,
        SUBGOAL_PLAN_USER_TEMPLATE,
        SUBGOAL_STEP_SYSTEM,
        SUBGOAL_STEP_USER_TEMPLATE,
        SUBGOAL_MERGE_SYSTEM,
        SUBGOAL_MERGE_USER_TEMPLATE,
        SUBGOAL_CROSSCHECK_SYSTEM,
        SUBGOAL_CROSSCHECK_USER_TEMPLATE,
    )
    from prompts.policy import get_domain_hint
    from utils.extract import extract_final_answer, smart_fallback_answer
    from utils.prefill import prefill_messages, stitch
except ImportError:
    from submit.prompts.sub_goal import (
        SUBGOAL_PLAN_SYSTEM,
        SUBGOAL_PLAN_USER_TEMPLATE,
        SUBGOAL_STEP_SYSTEM,
        SUBGOAL_STEP_USER_TEMPLATE,
        SUBGOAL_MERGE_SYSTEM,
        SUBGOAL_MERGE_USER_TEMPLATE,
        SUBGOAL_CROSSCHECK_SYSTEM,
        SUBGOAL_CROSSCHECK_USER_TEMPLATE,
    )
    from submit.prompts.policy import get_domain_hint
    from submit.utils.extract import extract_final_answer, smart_fallback_answer
    from submit.utils.prefill import prefill_messages, stitch

# calc_tool（2026-09-04 下沉）：与 Solver 主链同款确定性计算器。
# 子目标步骤/合并原先完全靠模型心算（无 <calc> 纪律、无回填），
# 是数值错的高发且无防线处。此处导入与 solver.py:39-45 同构。
# 2026-09-09 P1：追加 find_naked_numeric_asserts（裸数值断言/心算痕迹检测）
# 与 audit_calc_fallbacks（工具失败审计，P1-2）。
try:
    from .calc_tool import (
        resolve_all_calcs,
        find_naked_numeric_asserts,
        audit_calc_fallbacks,
        collect_calc_results,
    )
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from calc_tool import (
            resolve_all_calcs,
            find_naked_numeric_asserts,
            audit_calc_fallbacks,
            collect_calc_results,
        )
    except ImportError:
        resolve_all_calcs = None
        find_naked_numeric_asserts = None
        audit_calc_fallbacks = None
        collect_calc_results = None

logger = logging.getLogger("MathPilot")

# 单选信号（2026-09-13）：题干出现这些**明确指向唯一答案**的措辞时，
# 选择题按"单选"汇总（取唯一/最优），否则按多选（全取判真项）。
# ⚠ 不可用“下列正确的是”判断单选——087/093/094 都是该措辞却为**多选**，
#   096 也是该措辞却为**单选**；只有下列措辞才可靠。
_SINGLE_CHOICE_RE = re.compile(
    r"哪一项|哪一种|哪一类|哪一个|最为?合适|最恰当|最符合|最适合"
    r"|分别是?|定义是|通常采用|应采用|应选择|最好采用")

# 计算纪律引导（与 solver 主链同文案，2026-09-04 下沉子目标/合并；
# 2026-09-08 扩容：新函数 + 三态结果 + 符号断链处理引导）。
# 追加到 STEP/MERGE 的 system 提示词（不追加 user 末尾——v2.10 教训：
# 收尾结构后追加会诱发模型"续写模式"）。
_CALC_GUIDE = (
    "\n\n**【计算纪律 · 分档执行】**\n"
    "· **易错运算 → 必须写 <calc>表达式</calc> 交系统精确求值（严禁心算）**："
    "开方/根式 sqrt、对数 ln（log 即自然对数，其他底请用换底写成 ln 之比）、"
    "指数 exp 与自然常数 e（写 exp(1)）、组合数 comb(n,k)、排列 perm(n,k)、"
    "阶乘 ! 或 fact(n)、幂运算 ** 或 ^、取模 mod、求和 sum(f,x,a,b)、"
    "积分 integral(f,x[,a,b])、圆周率 pi。"
    "注意**工具只认这些函数名**：组合数写 comb（勿写 C(n,k)/choose/ncr）、"
    "排列写 perm（勿写 P(n,k)/npr）、阶乘写 fact 或 n!；\n"
    "· **工具能力外 → 换核验方式，不要写 <calc>**：三角函数 sin/cos/tan"
    "（含反三角 asin/acos/atan、双曲 sinh 等）、求积 prod/product、以 2/10 为底"
    "的对数 log2/log10、开立方 cbrt/root **均不在工具能力内**（写了只会拿到 "
    "WARN、白费一轮）：特殊角请**直接写精确式**（sin(pi/6)=1/2、"
    "cos(pi/4)=sqrt(2)/2），一般角与求积请把断言写成 <check> 或 "
    "```lean example``` 交编译器验算，禁止拿心算近似当精确结论；\n"
    "· **简单四则 → 你可以自己算**：整数/小数的加、减、乘、除与括号、比较，"
    "直接写出结果即可，不必包 <calc>（包了也无害）。\n"
    "**节奏示范**：“求组合数 C(50,3)”→写 <calc>comb(50,3)</calc>→回填 "
    "[计算] comb(50,3) = 19600→引用 19600；“把 sqrt(45) 化为最简根式”→写 "
    "<calc>sqrt(45)</calc>→回填 3*sqrt(5)；“25×4+1”→纯四则，可直接写 = 101。"
    "易错计算拆成 ≤3 个 <calc>（每步一个表达式），不要一步吞一大串。\n"
    "\n\n计算环节请用 <calc>表达式</calc> 标记（例如 <calc>comb(50,3)*2**10</calc>、"
    "<calc>sqrt(45)</calc>、<calc>integral((1-x)^n,x,0,1)</calc>、<calc>sum(k^2,k,1,n)</calc>），"
    "系统会自动求值并回填结果。涉及上述易错运算时务必使用该标记，不要心算。\n"
    "**<calc> 与 </calc> 之间必须且只能是数学表达式**"
    "（数字/字母符号 x n k…、+ - * / **（或 ^）% //、括号、函数 "
    "fact/comb/perm/gcd/lcm/abs/sqrt/floor/ceil/min/max/ln/log/exp/"
    "integral(f,x[,a,b]) 积分、sum(f,x,a,b) 求和（可省略变量）、pi 常量（回填≈近似））；隐式乘 2(x+1)/2x 自动识别，分式分母含变量请写 1/(2*x)形式。禁止出现中文、文字解释或换行。<calc> 只接受**单个数学表达式**：不要写代码/多语句/赋值（a=7 或跨行）、不要调 simplify()/solve() 等命令——要化简 x+1 就写 <calc>x+1</calc> 由系统自动回填。\n"
    "回填结果形态：①精确值（整数/分数/精确根式如 3*sqrt(5)）可直接信任；"
    "②符号化简式（含变量如 1/(n+1)、x**2-1）是 SymPy 化简的恒等式，可核对符号推导"
    "（含变量者落地数值时请代入具体值再 <calc> 自检）；"
    "③带 ≈ 的近似值（sqrt 无平方因子、ln、exp 等）只能核对量级，不是精确结论；"
    "④以 WARN: 开头表示该表达式超出工具能力（三角 sin/cos 等无通用精确值、符号整除取模、化简超时）——"
    "**禁止拿它硬算或当作已确认结论**：请代入具体数值用 <calc> 自检（如 <calc>(2+3)**2</calc>），"
    "三角等特殊角请写精确式（sin(pi/6)=1/2、cos(pi/4)=sqrt(2)/2），一般角把断言写成 <check> 或 lean example 交编译器验算；自然常数 e 请写 exp(1)。若在 deep 档且断言可形式化，"
    "可把关键代数等式写成 ```lean example ... := by ring/norm_num ``` 代码块，"
    "系统会用本地 Lean 编译器自动核验。"
)


# 2026-09-13 方案 A（用户："把数值给大模型，但不让它计算危险数值"）：
# 子目标 step / merge 两处的上文（`previous_results` / `all_results` / `lemma_repo`）
# 里带着**系统已回填**的 [计算] 行，但此前只给模型一句"不得重算"的口头约束，
# 模型仍要自己在长文本里翻找。此处把那些行**汇总成值清单前置**到 system 侧
# （与 `_CALC_GUIDE` 同处 system，不动 user 模板收尾结构——v2.10 教训）。
# 2026-09-13 方案 B：`extra_items` = `ctx.calc_prewarm_block`（生成前预计算产出），
# 排在回填条目之前 —— 子目标链是最早的生成阶段，预计算值在这里最该被看见。
_CALC_RESULTS_RULE = (
    "上述算式结果（由系统精确回填、或生成前预计算的）都是**可信的精确值**："
    "**原样引用，严禁重新心算、改写、删除，或「顺手验算一遍」**；"
    "只有当你要在它们之上做**新的**易错运算时，才为新算式另写 <calc>表达式</calc>。"
)


def _calc_results_block(text, extra_items=None) -> str:
    """把已算出的精确值（回填 + 预计算）汇总成"前置值清单"段。

    **扫不到任何条目 → 返回空串（不注入，不留空标题制造噪音）。**
    """
    items = [str(x) for x in (extra_items or [])]
    if collect_calc_results:
        for it in collect_calc_results(text):
            if it not in items:
                items.append(it)
    if not items:
        return ""
    return (
        "\n\n**【系统已算出的精确值 —— 直接引用，禁止重算或改写】**\n"
        + "\n".join(f"- {it}" for it in items)
        + "\n" + _CALC_RESULTS_RULE
    )



# P2（2026-09-09）：纯计算子目标专用 system 段——模型零计算面：只给表达式，
# 工具回填即结论（不写过程/不手写等号结果/不拆步骤）。
_TERMINAL_GUIDE = (
    "\n\n【本子目标为纯计算子目标】期望输出是单个数值/表达式。请**只**在"
    "【本步结果】给出一个 <calc>表达式</calc>（例如 <calc>comb(50,3)*2**10</calc>、"
    "<calc>sum(k^2,k,1,n)</calc>、<calc>integral((1-x)^n,x,0,1)</calc>），"
    "系统回填的精确值即本步结论。不要写推理过程、不要手写等号结果、不要拆分步骤。"
)


class SubGoalSolverAgent(BaseAgent):
    """子目标逐步求解智能体"""

    name = "SubGoalSolver"

    # ---------- JSON 提取 ----------
    @staticmethod
    def _extract_json(text: str) -> dict | None:
        r"""从 LLM 输出中提取 JSON 对象。

        v2.6 修复：原实现对最外层一对花括号到另一对花括号做贪婪匹配，会被 LaTeX /
        中文解释 / 嵌套 JSON 干扰（LaTeX 里的左花括号、右花括号、解释文字里的成对
        花括号都会被吃进 JSON 段导致解析失败）。改为**平衡括号匹配**：从每个左
        花括号出发，用栈找匹配的右花括号，并正确处理字符串内花括号与反斜杠转义。
        """
        if not text:
            return None
        # 1) 优先 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass  # 代码块不合法，回退到平衡括号匹配

        # 2) 平衡括号匹配：扫描每个 {，用深度栈找到对应的 }。
        #    关键：正确处理字符串字面量（跳过字符串内的 { 和 }）
        def _try_parse(candidate: str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 尝试修复常见错误：尾随逗号
                try:
                    fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    return None

        for i, c in enumerate(text):
            if c != '{':
                continue
            depth, j, in_str, esc = 1, i + 1, False, False
            while j < len(text):
                ch = text[j]
                if esc:
                    esc = False
                elif in_str and ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            parsed = _try_parse(text[i:j + 1])
                            if parsed is not None:
                                return parsed
                            break  # 该 { 不是合法 JSON 起点，继续找下一个
                j += 1
        return None

    # ---------- P2 子目标类型路由（2026-09-09 老师：计算/推理类型化）----------
    # calc_kind: "terminal"=整体计算型子目标（期望输出=单个数值/表达式 → 专用
    # 模板只翻译表达式，工具回填即结论，模型零计算面）；"inline"=推理/证明型
    # （步骤级 <calc> 截断）。规则启发先行，宁 inline 勿误 terminal（防把推理
    # 子目标截成表达式翻译）。字段总是打标进 trace（0 成本可观测分布）；
    # 专用模板/校验由 config.subgoal_calc_router 控制（默认关待 A/B）。
    _TERM_ACTION_KW = ("代入", "求和", "化简", "展开", "求值", "积分",
                       "乘积", "计算", "算得")

    @staticmethod
    def _calc_kind_of(sg_type: str, title: str, expected_output: str) -> str:
        blob = f"{title} {expected_output}".strip()
        if sg_type == "compute":
            if any(k in blob for k in SubGoalSolverAgent._TERM_ACTION_KW):
                return "terminal"
            eo = (expected_output or "").strip()
            # expected_output 为短数值/表达式形态（数字/负号/等号/左括号开头）
            if eo and len(eo) <= 60 and (eo[0].isdigit() or eo[0] in "-=("):
                return "terminal"
        return "inline"

    @staticmethod
    def _parse_subgoal_plan(raw: dict, max_subgoals: int = 6) -> list[dict] | None:
        """验证并规范化子目标规划，返回按拓扑序排列的子目标列表。

        v2.6 宽容性增强：LLM 实际输出常省略字段（如用 step/name/task 代替
        id/title/description）、或把列表字段命名为 plan/steps/subproblems/tasks
        等。本方法兼容多种字段名，单个条目缺失字段时也能构造出可用条目，
        而不再直接放弃。
        """
        # 1) 宽容多种列表字段名
        subgoals = None
        for key in ("subgoals", "subproblems", "sub_problems",
                    "plan", "steps", "tasks", "items"):
            v = raw.get(key)
            if isinstance(v, list) and v:
                subgoals = v
                break
        if subgoals is None:
            # 兜底：找任何非空 list[dict] 字段
            for v in raw.values():
                if (isinstance(v, list) and v
                        and all(isinstance(x, dict) for x in v)):
                    subgoals = v
                    break
        if subgoals is None:
            return None
        # 2026-09-03 老师：子目标是**简化求解**的，不是把题目拆得更复杂。
        # 原上限 10（deep 实测 8 步 × 110s = 882s 吃掉 73% 时间）。
        # 改为可配置 max_subgoals（默认 6）：少而精，每步都是真正必要的
        # 简化步骤；省下的时间留给验证器与 Lean 闸门（老师核心诉求）。
        # 注意：这是"规划时少拆几步"，**不是执行到一半强制中断**——
        # 已规划的子目标一定会跑完（老师："强制结束就等于错误"）。
        # 2026-09-03 审核修复：原实现在 @staticmethod 里写 `self.config` /
        # `self.record(ctx, ...)` → 每次调用必抛 NameError（本方法无 self/ctx），
        # 且该分支无条件执行 = 子目标规划 100% 崩溃。改为**上限走参数**，
        # 调用方从 config 读取后传入，静态方法保持无状态（测试可直接调用）。
        _max_sg = int(max_subgoals or 6)
        if len(subgoals) > _max_sg:
            logger.info("SubGoal plan: 子目标 %d 个 > 上限 %d，保留前 %d 个"
                        "（简化求解，非中断）", len(subgoals), _max_sg, _max_sg)
            subgoals = subgoals[:_max_sg]

        valid_types = {"compute", "prove", "derive", "verify"}
        seen_ids = set()
        parsed = []
        for sg in subgoals:
            # 宽容 id 字段名：id / step / index / number
            raw_id = sg.get("id", sg.get("step", sg.get("index",
                          sg.get("number", len(parsed) + 1))))
            try:
                sg_id = int(raw_id)
            except (TypeError, ValueError):
                sg_id = len(parsed) + 1
            if sg_id in seen_ids:
                continue
            seen_ids.add(sg_id)

            # 宽容 title/description/expected_output/depends_on/type 字段名
            title = str(sg.get("title",
                       sg.get("name",
                       sg.get("step_name",
                       sg.get("task_name", f"子目标{sg_id}")))))
            description = str(sg.get("description",
                            sg.get("task",
                            sg.get("content",
                            sg.get("detail", "")))))
            sg_type = sg.get("type", sg.get("kind", "compute"))
            if sg_type not in valid_types:
                sg_type = "compute"
            deps_raw = sg.get("depends_on",
                       sg.get("deps",
                       sg.get("dependencies", [])))
            if not isinstance(deps_raw, list):
                deps_raw = []
            expected_output = str(sg.get("expected_output",
                                   sg.get("output",
                                   sg.get("expected",
                                   sg.get("result", "")))))
            parsed.append({
                "id": sg_id,
                "title": title,
                "description": description,
                "type": sg_type,
                "depends_on": [d for d in deps_raw
                               if isinstance(d, int) and d in seen_ids],
                "expected_output": expected_output,
                # P2（2026-09-09）：计算/推理类型化标签（宁 inline 勿误 terminal）
                "calc_kind": SubGoalSolverAgent._calc_kind_of(
                    sg_type, title, expected_output),
                "result": "",
            })
        return parsed if parsed else None

    # ---------- 主流程 ----------
    def run(self, ctx: TaskContext) -> TaskContext:
        """执行子目标规划 → 逐步求解 → 结论合并 全流程，结果追加到 ctx.candidates"""
        # 预算闸门：连规划所需的 1 次 LLM 调用都负担不起时，整体跳过、不追加候选
        # 2026-09-06：升级 gen_time_up（生成侧软截止，未设时回退 is_time_critical）
        if ctx.gen_time_up():
            self.record(ctx, "subgoal", "预算耗尽，跳过子目标求解")
            return ctx

        # 2026-09-04 子目标阶段预算（老师：砍环节内重复、不砍环节本身；
        # 且不止加限制，还要保证体系在规定时间内跑完、强制收尾产出）。
        # 背景：preverify 提速省下的 ~300s 全被子目标贪婪 re-plan/re-review
        # 吃掉（bridge sub 529-717s → mcp sub 780-1112s），merge 被挤进
        # is_time_critical 区 → 走 fallback 而非真合并 → 060 对变错
        # （答案停在 S(1)..S(12) 枚举、未合成 2617/2618）。
        # 依据（bridge 18 题实测）：正确题 sub 全在 661-717s，失控题 780-1112s。
        # 预算取 750s：保住已知正确深度、刹住失控；可配 subgoal_stage_budget_sec。
        # 时钟挂 ctx（⚠ 不能挂 self：EvalEngine 的 agent 是共享单例，
        # ThreadPoolExecutor 并发 2 时同一实例同时服务多题，self 属性会竞态；
        # ctx 每题独立）。orchestrator 可能多次调用 run()（2.7 / deep 3_solve /
        # 3.5），共享 ctx._subgoal_stage_start，避免"每次调用重置预算"把总时间再吃一遍。
        # 2026-09-06 P1（用户拍板）：子目标预算按档拆分——deep 保留 750s
        # （难题深度分解值），standard/fast 用 450s（省下预算流向 solve/verify）。
        # 依据：2.7 子目标全档均 ~587s 是最大黑洞，standard 档 geom-051 曾 1073s
        # 仍错（post-fix 靠 3_solve 做对）——standard 题子目标分解性价比存疑。
        # 兼容：config 未显式设 std 档字段（测试 SimpleNamespace）→ 回退主字段
        # 语义（主字段=0 表示停用固定预算，仅 tail_reserve 兜底）。
        _tier_now = str(getattr(ctx, "tier", "standard") or "standard")
        if _tier_now == "deep":
            _raw_budget = getattr(self.config, "subgoal_stage_budget_sec", 750.0)
        else:
            _raw_budget = getattr(self.config, "subgoal_stage_budget_sec_std", None)
            if _raw_budget is None:
                _raw_budget = getattr(self.config, "subgoal_stage_budget_sec", 750.0)
        stage_budget = float(_raw_budget or 0.0)
        stage_start = float(getattr(ctx, "_subgoal_stage_start", 0.0) or 0.0)
        if not stage_start:
            stage_start = time.time()
            ctx._subgoal_stage_start = stage_start
        ctx._subgoal_stage_budget = stage_budget
        # 2026-09-04 第二层保险（老师：不止加限制，还要保证体系在规定时间跑完）：
        # 固定预算之外，子目标最迟必须在 `全局 deadline - subgoal_tail_reserve`
        # 前结束 —— 给 3_solve 收尾 + 6_format + 6.5_lean_gate 留底线时间。
        # reserve 取 180s 的理由（2026-09-04 审查修正）：必须 > critical_tail
        # （standard 120s / deep 60s）且覆盖 merge（最坏 ~90s 一次 LLM）+
        # format(<5s) + gate(≤2 次 ~40s)。若 reserve 只留 90s，子目标吃到
        # stage_end 时全局剩 90s < 120s → merge 前 is_time_critical() 为真 →
        # 真 merge 被全局 critical 抢走、退回 fallback —— "强制收尾"失效。
        # 180s 保证 break 发生时全局仍 > critical_tail，merge 在非 critical 区真跑。
        # 注意：tail_reserve 与固定预算**解耦独立**——即便 subgoal_stage_budget_sec
        # 显式设 0（放弃固定上限），deadline 前 reserve 的硬约束依然生效，
        # 这是"保证体系跑得完"的底线，不受固定预算开关影响。
        _hard_end = float(getattr(ctx, "deadline", 0.0) or 0.0)
        _tail_reserve = float(
            getattr(self.config, "subgoal_tail_reserve_sec", 180.0) or 0.0)
        _fixed_end = (stage_start + stage_budget
                      if stage_budget > 0 else float("inf"))
        if _hard_end > 10 ** 8 and _tail_reserve > 0:
            ctx._subgoal_stage_end = min(_fixed_end, _hard_end - _tail_reserve)
        elif stage_budget > 0:
            ctx._subgoal_stage_end = _fixed_end
        else:
            ctx._subgoal_stage_end = 0.0

        def _stage_left() -> float:
            """子目标阶段剩余秒数（0 = 未启用阶段预算，返回 inf）"""
            if not ctx._subgoal_stage_end:
                return float("inf")
            return ctx._subgoal_stage_end - time.time()

        # 阶段一：子目标规划
        plan_data = self._plan_subgoals(ctx)
        if plan_data is None:
            self.record(ctx, "subgoal", "子目标规划失败，回退到标准求解")
            return ctx

        subgoals = plan_data.get("subgoals", [])
        merge_strategy = plan_data.get("merge_strategy", "")
        problem_analysis = plan_data.get("problem_analysis", {})
        # ---- 2026-09-14 穷尽性搜索机制（B0 遗留课题）----
        # 实测 003（漏 `2030`）与 074（漏取整解族）的失败**不是形态问题**：
        # 模型自信地认为"只有一个解"，因此"必须枚举"的形态要求对它无效。
        # 现由代码**强制追加**一个「解族穷尽性检查」子目标，逼迫模型按解族
        # 分类穷举（常数/线性/周期/取整/分段…）并回答"是否还有其他解族"。
        # 追加发生在规划**之后** ⇒ 不会被 max_subgoals 截断，且覆盖全部规划路径
        # （选择题 / Blueprint DAG / LLM 规划）。
        try:
            from .question_type import asks_all_values as _aav
            if _aav(ctx.problem or "") and subgoals:
                _max_id = max(int(sg.get("id", 0) or 0) for sg in subgoals)
                subgoals.append({
                    "id": _max_id + 1,
                    "title": "解族穷尽性检查",
                    "description": (
                        "本题问『所有 / 全部』取值，前面的子目标**可能只找到了一部分解**。"
                        "现在专门做一次穷尽性检查：\n"
                        "1. 先列出本题**所有可能的解族类型**（如：常数解 / 线性解 / "
                        "多项式解 / 周期解 / 取整型解（⌈x⌉、⌊x⌋）/ 分段定义解 / "
                        "特殊函数解 / 指数对数型解 …）—— 这一步要**尽量列全**；\n"
                        "2. 对每一类逐一判定『该类是否存在满足条件的解』，给出结论与"
                        "理由（**排除某类必须给出反证或构造性论证**，不得只写"
                        "“不可能”“显然无解”）；\n"
                        "3. 最后必须明确回答：**除前面已找到的解之外，是否还存在"
                        "其他解族？** 若有，写出该解族的具体形式（含参数）。\n"
                        "⚠ 宁可多列一类再排除，也不得因“看起来不可能”而跳过；"
                        "给出结论时必须注明依据。"
                    ),
                    "type": "verify",
                    # ⚠ **必须依赖全部已有子目标**：执行期 `_format_dep_results`
                    # 只注入**直接依赖**的结果 —— 若只依赖最后一个，穷尽性检查就
                    # 看不到前面找到的任何解，而它的任务恰恰是"检查是否遗漏解族"。
                    "depends_on": [sg["id"] for sg in subgoals],
                    "expected_output": "各解族存在性判定 + 是否存在遗漏解族 + 遗漏解的具体形式",
                    "result": "",
                })
                # merge 必须把「解族穷尽性检查」的结论纳入最终答案（否则子目标白跑）
                _exh_note = (
                    "\n【穷尽性要求（必须遵守）】最终答案**必须综合『解族穷尽性检查』"
                    "子目标的结论**：把检查中确认存在的**所有解族**全部列出"
                    "（含该检查新发现的遗漏解族的具体形式），"
                    "**不得**只采用前面子目标找到的部分解；"
                    "若检查结论与前面矛盾，以穷尽性检查为准并说明理由。"
                )
                merge_strategy = (merge_strategy or "直接给出最终答案") + _exh_note
                self.record(ctx, "subgoal",
                            "穷尽性搜索：追加『解族穷尽性检查』子目标"
                            "（题面要求『所有』，共 {} 个子目标）".format(len(subgoals)))
                # 埋点落 diag（2026-09-14）：trace 不进结果文件 ⇒ 此前无法确认
                # 机制是否真的生效，只能靠猜。写入 ctx 供 _collect_diag 落盘。
                try:
                    ctx._exhaust_diag = {
                        "appended": True,
                        "n_before": len(subgoals) - 1,
                        "n_after": len(subgoals),
                        "trigger": "asks_all_values",
                    }
                except Exception:  # noqa: BLE001
                    pass
            else:
                try:
                    ctx._exhaust_diag = {
                        "appended": False,
                        "reason": ("非『求所有』题" if not _aav(ctx.problem or "")
                                   else "无子目标可追加"),
                    }
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            logger.debug("[穷尽性] 子目标追加失败: %s", _e)
            try:
                ctx._exhaust_diag = {"appended": False,
                                     "reason": "异常: {}".format(type(_e).__name__)}
            except Exception:  # noqa: BLE001
                pass

        _sg_stats = self._subgoal_stats(subgoals)
        ctx.subgoal_stats = _sg_stats   # S4-lite：落 ctx 供 _collect_diag 进结果文件（A/B 对照）
        self.record(ctx, "subgoal", f"子目标规划完成: {len(subgoals)} 个子目标",
                    subgoal_titles=[sg["title"] for sg in subgoals],
                    merge_strategy=merge_strategy,
                    subgoal_stats=_sg_stats)

        # 阶段二：逐步求解每个子目标
        subgoal_plan_summary = self._format_plan_summary(subgoals, merge_strategy)
        results_map = {}  # subgoal_id → result_text
        _ctx_inject_chars = 0  # S4-lite 指标：累计前序注入字符数（近似上下文量）
        # 2026-09-12 新增（用户要求「原本完成的子目标要记录，不能重头再来」）：
        # 以**子目标指纹**为键，跨 run() 调用复用已完成结果。
        # 为何需要：orchestrator 会在 3_solve / 3.5 等阶段**多次**调用本 run()，
        # 原实现每次都重新规划并**重解全部子目标**（每个都是一次完整 LLM 轮），
        # 重复烧掉本就吃紧的单题预算（冒烟实测 700-1200s 的主要浪费源之一）。
        # 关闭 `subgoal_reuse_done` 即回到旧行为（每次全量重解）。
        _reuse_on = bool(getattr(self.config, "subgoal_reuse_done", True))
        _done = getattr(ctx, "_subgoal_done", None)
        if not isinstance(_done, dict):
            _done = {}
            try:
                setattr(ctx, "_subgoal_done", _done)
            except Exception:  # noqa: BLE001  个别 ctx 实现可能禁写
                pass
        _n_reuse = 0

        for sg in subgoals:
            # ★ 复用命中：上一轮已完成的**同一子目标** → 直接取结果，零 LLM 调用。
            # 指纹用 title+description+type（重新规划后 id 可能重排，语义内容不变）。
            _fp = "|".join(str(sg.get(_k, "")) for _k in
                           ("title", "description", "type"))[:240]
            if _reuse_on and _fp in _done:
                step_result = _done[_fp]
                results_map[sg["id"]] = step_result
                sg["result"] = step_result
                ctx.subgoal_trace.append({
                    "id": sg["id"],
                    "title": sg["title"],
                    "description": sg["description"],
                    "type": sg["type"],
                    "calc_kind": sg.get("calc_kind", "inline"),
                    "depends_on": sg["depends_on"],
                    "expected_output": sg["expected_output"],
                    "result": step_result,
                    "reused": True,
                })
                _n_reuse += 1
                continue
            # 2026-09-06：升级 gen_time_up——只查 is_time_critical（=deadline-120/60s）
            # 挡不住"750s stage_budget 之外 for-sg 主循环一路烧到临界点"
            # （冒烟 geom-051 2.7=1073s 实证），必须更早停手给验证留预算。
            if ctx.gen_time_up():
                self.record(ctx, "subgoal", f"预算不足，跳过剩余子目标 (当前={sg['id']}/{len(subgoals)})")
                break
            # 2026-09-04 阶段预算闸：子目标阶段超预算 → 停解新子目标，
            # 但**不 return**，保留已解结果进入 merge 收尾（见阶段三）。
            if _stage_left() <= 0:
                self.record(ctx, "subgoal",
                            f"子目标阶段预算 {stage_budget:.0f}s 用尽，"
                            f"停止求解剩余子目标 (当前={sg['id']}/{len(subgoals)})，"
                            "强制收尾 merge")
                break

            # 2026-09-06 老师建议：子目标独立性 + 最小上下文依赖。
            # subgoal_ctx_mode = "deps"（默认）：按 depends_on 只注入直接依赖结果，
            # 无依赖子目标零前序上下文（可独立/并行，不被无关中间量污染）；
            # = "all"：回退旧行为全量前序注入（A/B 对照/兜底）。
            _ctx_mode = str(getattr(
                self.config, "subgoal_ctx_mode", "deps") or "deps").lower()
            if _ctx_mode == "all":
                prev_results = self._format_previous_results(
                    results_map, subgoals)
            else:
                prev_results = self._format_dep_results(
                    results_map, subgoals, sg)
            _ctx_inject_chars += len(prev_results or "")
            ctx.subgoal_ctx_inject_chars = _ctx_inject_chars  # 每步累计（预算中断也留痕）
            step_result = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results)
            # 2026-09-02 老师方案 B：蓝图评审 OK 但子目标失败 → 重做子目标
            # （不重画蓝图）。一次失败常是瞬时 LLM 错误/预算抖动，带已解
            # 子目标上下文重试一次；仍失败才记为占位（留给外层占位符兜底）。
            # 2026-09-04 阶段预算：重试 = 一次完整 LLM 轮（60-110s），
            # 阶段预算剩余不足时不再重试（省下的时间留给 merge 收尾）。
            if step_result.startswith("[子目标") and _stage_left() > 120:
                self.record(ctx, "subgoal",
                            f"子目标 #{sg['id']}「{sg['title']}」失败，带上下文重试一次")
                if _ctx_mode == "all":
                    prev_results2 = self._format_previous_results(
                        results_map, subgoals)
                else:
                    prev_results2 = self._format_dep_results(
                        results_map, subgoals, sg)
                retry = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results2)
                if retry and not retry.startswith("[子目标"):
                    step_result = retry
            elif step_result.startswith("[子目标") and _stage_left() <= 120:
                self.record(ctx, "subgoal",
                            f"子目标 #{sg['id']}「{sg['title']}」失败，"
                            f"阶段预算剩余 {_stage_left():.0f}s 不足，放弃重试，强制收尾")

            # S1-lite（2026-09-06 老师建议）：子目标级 0-LLM 校验前移——
            # 便宜且确定的校验先跑（截断/lean 代码片编译），过了才认结果，
            # 不让脏结果流进 merge 与后续子目标（验证-精炼下沉到子目标级）。
            # 校验全部 0-LLM；失败且预算足 → 带反馈重解一次；仍失败用原结果。
            if (not step_result.startswith("[子目标")
                    and not ctx.gen_time_up() and _stage_left() > 90):
                _hint = self._subgoal_light_check(ctx, sg, step_result)
                if _hint:
                    self.record(
                        ctx, "subgoal_step",
                        f"子目标 #{sg['id']}「{sg['title']}」0-LLM 校验未过: "
                        f"{_hint[:80]}，带反馈重解一次")
                    retry3 = self._solve_subgoal(
                        ctx, sg, subgoal_plan_summary, prev_results,
                        extra_hint=_hint)
                    if retry3 and not retry3.startswith("[子目标"):
                        # 重解结果仍疑似占位（二次空转）→ 显式失败标记，
                        # 让 merge 明确知道该子目标无产出，不再用原占位糊弄。
                        if (retry3 != step_result
                                and self._looks_placeholder(retry3)):
                            step_result = (
                                f"（子目标 #{sg['id']} 重解后仍为空转占位，"
                                "未产出有效结论；合并时请忽略并基于其余子目标求解）")
                        else:
                            step_result = retry3
                            # P1-1 二次校验（2026-09-09：漏洞2修复——重解后仍
                            # 裸算 = 模型拒用工具，仅记录并标注，不无限重试）
                            if (find_naked_numeric_asserts is not None
                                    and getattr(self.config, "calc_mandatory",
                                                True)
                                    and find_naked_numeric_asserts(step_result)):
                                self.record(
                                    ctx, "subgoal_step",
                                    f"子目标 #{sg['id']} 重解后仍含未工具化数值"
                                    "运算（二次裸算，保留结果并标注）")
                                step_result = (
                                    f"（该步含未用 <calc> 的易错运算结果，未经"
                                    f"系统确认）{step_result}")
                    else:
                        self.record(
                            ctx, "subgoal_step",
                            f"子目标 #{sg['id']} 校验重解失败/超时，用原结果兜底")
                        if self._looks_placeholder(step_result):
                            step_result = (
                                f"（子目标 #{sg['id']} 求解失败未产出有效结论，"
                                "请基于其余子目标完成合并）")
            # ── 2026-09-12 新增（用户要求）：子目标级"失败二选一"处置 ──────────
            # 判据（主审定）：
            #   · **优先「重做该子目标」**：代价 1 次短调用，且**不破坏已完成成果**；
            #     多数子目标失败是局部性的（算错 / 格式 / 占位）。
            #   · 仅当重做达上限仍失败，**或**失败原因指向规划本身（依赖前提
            #     不成立 / 缺少前置条件），才升级为「重规划后续子目标」——
            #     该操作代价高（后续子目标全部重解），故只在最后才用。
            #   · 无论如何最终**保留占位兜底放行**，绝不阻断 merge；
            #     已完成子目标一律保留、不参与重算（见上方 _done 复用）。
            # 稳妥性：真正的"重规划"**不在此循环内新建实现**，而是把失败原因写入
            # ctx.revise_feedback、并由上游既有重规划能力（_review_and_maybe_replan
            # / dag_replan_gate）处理，避免破坏 depends_on 顺序与阶段预算。
            if (getattr(self.config, "subgoal_adaptive_recover", True)
                    and not ctx.gen_time_up() and _stage_left() > 150):
                _failed_now = (self._looks_placeholder(step_result)
                               or step_result.startswith("[子目标")
                               or "未产出有效结论" in step_result
                               or "仍为空转占位" in step_result)
                if _failed_now:
                    _tries = int(getattr(ctx, "_sg_recover_tries", 0) or 0)
                    _plan_err = any(_k in str(step_result) for _k in
                                    ("依赖", "前提", "缺少", "不成立", "无法确定"))
                    if _tries < 2 and not _plan_err:
                        try:
                            setattr(ctx, "_sg_recover_tries", _tries + 1)
                        except Exception:  # noqa: BLE001
                            pass
                        self.record(
                            ctx, "subgoal_recover",
                            f"子目标 #{sg['id']}「{sg['title']}」未产出有效结论 "
                            f"→ 重做该子目标（第 {_tries + 1}/2 次）")
                        _retry2 = self._solve_subgoal(
                            ctx, sg, subgoal_plan_summary, prev_results,
                            extra_hint=(
                                "上一次该子目标未产出可用的结论（"
                                + str(step_result)[:120] +
                                "）。请**重新推导**本子目标，给出可独立核验的结论；"
                                "涉及开方/对数/组合数/幂等易错运算必须写成 "
                                "<calc>表达式</calc> 由系统精确求值。"))
                        if (_retry2 and not _retry2.startswith("[子目标")
                                and not self._looks_placeholder(_retry2)):
                            step_result = _retry2
                    else:
                        # 升级：重规划**后续**子目标（只记录 + 交上游，不在循环内新建）
                        self.record(
                            ctx, "subgoal_replan_needed",
                            f"子目标 #{sg['id']} 重做 {_tries} 次仍失败"
                            + ("（失败指向规划/依赖前提）" if _plan_err else "")
                            + " → 建议重规划后续子目标")
                        try:
                            ctx.revise_feedback = list(
                                getattr(ctx, "revise_feedback", []) or []) + [
                                f"子目标 #{sg['id']}「{sg['title']}」反复失败"
                                f"（{str(step_result)[:80]}）：该子目标的规划粒度或"
                                "依赖前提可能有误，请重规划后续子目标后重做"]
                        except Exception:  # noqa: BLE001
                            pass
            # 2026-09-08：剥 <check> 验证标签（去标签留内容）——校验已在上面
            # 消费过 <check> 断言，存盘/注入下游（merge/lemma/后续子目标）时
            # 不得再带协议标记，防污染提示词与最终答案。
            step_result = self._strip_check_tags(step_result)
            # P1-1 兜底标注（2026-09-09：trace 前最后闸，绕过 light_check 全部
            # 前置条件——若裸数值断言仍进入结果，标注"未经系统确认"供 merge 与
            # 分析可见；不阻断流程只留痕）
            if (find_naked_numeric_asserts is not None
                    and getattr(self.config, "calc_mandatory", True)
                    and not step_result.startswith("（该步含未用")
                    and find_naked_numeric_asserts(step_result)):
                self.record(ctx, "subgoal_step",
                            f"子目标 #{sg['id']} trace 前仍含裸数值断言，兜底标注")
                step_result = (
                    f"（该步含未用 <calc> 的易错运算结果，未经系统确认）"
                    f"{step_result}")
            results_map[sg["id"]] = step_result
            sg["result"] = step_result
            if _reuse_on:
                _done[_fp] = step_result     # 写回 ctx，供**后续 run() 调用**复用
            # v2.9：结构化输出每步子目标的过程与中间结果
            ctx.subgoal_trace.append({
                "id": sg["id"],
                "title": sg["title"],
                "description": sg["description"],
                "type": sg["type"],
                "calc_kind": sg.get("calc_kind", "inline"),
                "depends_on": sg["depends_on"],
                "expected_output": sg["expected_output"],
                "result": step_result,
            })

            # 引理积累（D6）：子目标求解成功后把结论写入 ctx.lemma_repo，
            # 供后续子目标与最终求解复用。
            # 2026-08-29 修复：此前 lemma_repo **全流水线无人写入**，
            # use_lemma_accumulation=True 等于读空列表（假钥匙，开了也是空转）。
            # 2026-08-29 二次修复：按领域路由（_use_lemma），数论开、其他关。
            if self._use_lemma(ctx):
                self._accumulate_lemma(ctx, sg, step_result)

            self.record(ctx, "subgoal_step",
                       f"子目标 #{sg['id']}「{sg['title']}」求解完成: {step_result[:80]}")
            time.sleep(0.2)  # 速率限制间隔

        # 阶段三：结论合并
        # 2026-09-04 保护：预算已尽且一个子目标都没解出（典型：或chestrator 后续
        # 调用 run() 时预算早已耗尽）→ 空 merge 只产垃圾，直接 return 不追加候选。
        if not results_map and _stage_left() <= 0:
            self.record(ctx, "subgoal",
                        "子目标阶段预算已尽且无已解子目标，跳过空 merge")
            return ctx
        if ctx.gen_time_up():
            # 生成侧软截止/全局逼近 deadline（2026-09-06 升级 gen_time_up；
            # 正常 750s stage_budget 结束于 ~760s < gen_deadline，merge 仍真跑，
            # 只有跑超到 gen_deadline 才兜底）→ 连 1 次 merge LLM 调用都挤不出
            # 时，用最后一个子目标结果兜底（不空手返回）。
            self.record(ctx, "subgoal", "全局预算不足，跳过合并阶段")
            # 使用最后一个子目标的结果作为最终答案
            final_answer = self._fallback_from_last_subgoal(subgoals)
        else:
            # 2026-09-04：即使子目标阶段预算已用尽（_stage_left()<=0），
            # 只要全局未 critical 就**必须真 merge**——这是"强制收尾产出"的关键：
            # 此前阶段预算用尽直接 return / 或 merge 被全局 critical 挤掉，
            # 答案停在子目标枚举（060: S(1)..S(12)）而没合成最终结论。
            final_answer = self._merge_results(ctx, subgoals, subgoal_plan_summary,
                                               results_map, merge_strategy)

        # v2.9：结构化输出最终整合方案
        ctx.subgoal_merge_plan = (
            f"合并策略: {merge_strategy or '将各子目标结果按逻辑顺序组合'}\n"
            f"最终答案: {final_answer}"
        )

        # 构造 Candidate
        full_reasoning = self._build_full_reasoning(subgoals, problem_analysis, final_answer)
        # 2026-09-02 老师需求：候选池统一封顶（与 solver.run 同口径）。
        # 2026-09-04：cap 8→6（deep 候选 4→3 配套，验证成本 -25%）
        if len(getattr(ctx, 'candidates', None) or []) >= 6:
            self.record(ctx, "subgoal", "候选池已达上限 6，跳过子目标候选入池")
            return
        candidate = Candidate(
            id=len(ctx.candidates),
            answer=final_answer,
            reasoning=full_reasoning,
            revised=False,
        )
        ctx.candidates.append(candidate)
        self.record(ctx, "subgoal", "子目标求解完成，已生成候选解答",
                    subgoal_stats=self._subgoal_stats(subgoals),
                    ctx_inject_chars=_ctx_inject_chars)
        # -------- #34 阶段四：DAG 评审 + 整树重生成 --------
        # 老师要求："dag 框架错了要重新构建"。判定标准（DagReviewer）：
        # - reject >= 3 个（绝对阈值）
        # - reject 比例 >= 40%（相对阈值）
        # 满足任一 → 注入失败反馈让 BlueprintPlanner.regenerate_with_feedback 重写 DAG。
        # 硬上限 MAX_REPLAN_ROUNDS 防死循环；预算耗尽或 DAG 不可改进即停。
        # 2026-09-04 阶段预算：replan 是"候选已入池后"的改进环节（评审+重生成
        # 每轮 2-3 次 LLM），budget 用尽时跳过——不影响已产出的 merge 答案，
        # 把时间留给 orchestrator 后续 3_solve/lean 验证/答案闸门。
        if (getattr(self.config, "enable_dag_replan", True)
                and _stage_left() > 0):
            self._review_and_maybe_replan(ctx, dag=ctx.blueprint)
        elif getattr(self.config, "enable_dag_replan", True):
            self.record(ctx, "dag_replan",
                        f"子目标阶段预算用尽（剩 {_stage_left():.0f}s），跳过 DAG replan")
        return ctx

    def _review_and_maybe_replan(self, ctx, dag=None, max_replan_rounds: int = 2) -> bool:
        """评审 DAG + 三级动态修复（#34 老师要求："dag 蓝图不能是死的"）。

        三级漏斗（由精准到全局，LEAP 2.5 子树回溯 + 5.3 reviewer 信号）：
          1. 子树级局部重写：只重写 reject 节点所在子树（LCA），其余保留
          2. 整树重生成：子树修不动 / 波及根 → 全图重写（带全部 hint）
          3. 硬上限防死循环

        判定信号（DagReviewer）：
          - reject_count >= 5（绝对，9/1 由 3 调高）或 reject_ratio >= 40%（相对）→ 触发修复
        返回是否触发了任何修复。
        """
        from .dag_reviewer import DagReviewerAgent
        from .blueprint_planner import BlueprintDAG
        reviewer = DagReviewerAgent(self.client, self.config)
        # 1) 评审当前 DAG：兼容 BlueprintDAG 与 dict 两种入参
        if dag is None and ctx.blueprint:
            dag = ctx.blueprint
        if dag is None:
            return False
        if isinstance(dag, dict):
            try:
                dag = BlueprintDAG.from_dict(dag)
            except Exception as exc:  # noqa: BLE001
                self.record(ctx, "dag_replan", f"DAG 解析失败: {exc}")
                return False
        if not dag.nodes:
            return False
        results_map = {sg["id"]: sg.get("result", "")
                       for sg in getattr(ctx, "subgoal_trace", []) or []}
        report = reviewer.review(ctx, dag, results_map=results_map)
        if not report.should_replan():
            return False
        # 2) 应修复：聚合 hint + rejected 节点（"错误的地方 + 原因"）
        from .blueprint_planner import (
            BlueprintPlannerAgent, BlueprintDAG)
        planner = BlueprintPlannerAgent(self.client, self.config)
        rejected_ids = report.rejected_nodes()
        hints = report.merge_from_hints()
        feedback_lines = hints.split("\n") if hints else []
        if not feedback_lines:
            feedback_lines.append(
                "请提供粒度更细、子目标间无循环、可独立证明的 DAG")
        # 3) 硬上限 + budget 闸
        replan_rounds = int(getattr(self.config, "dag_replan_max_rounds",
                                    max_replan_rounds) or max_replan_rounds)
        replan_rounds = max(1, replan_rounds)
        for round_idx in range(replan_rounds):
            # 2026-09-13 循环时间闸（单题上限 1200→3600s 放开后的必备兜底）：
            # 本循环每轮 = 评审 + 子树/整树重生成（2-3 次 LLM，以生成为主），
            # 属 LLM 生成类；评审始终不放行时会反复重建 → 必须查生成侧软截止。
            # 用 gen_time_up()（与同族 _dag_replan_gate:1239 同口径；未设
            # _gen_deadline 时自动回退 is_time_critical）。到点跳出，保留已产出
            # 候选，不空转烧穿验证预算。
            if ctx.gen_time_up():
                self.record(ctx, "dag_replan",
                            f"生成侧时间已到，提前退出 DAG 修复循环 "
                            f"(round={round_idx + 1}/{replan_rounds})")
                break
            # 2026-09-12 定型前审核：原为 `if not ctx.budget or not True:`
            # （`or not True` 恒为 False，`A or False ≡ A`，删除属恒等变换，
            #  语义与行为完全不变）
            if not ctx.budget:
                self.record(ctx, "dag_replan",
                            f"DAG 修复预算不足，提前停止 (round={round_idx + 1})")
                return False
            # 3a) 先试子树级局部重写（精准修改，不动好的部分）
            # 9/1 冒烟 10 题实锤：reject 波及根（LCA=根）时子树重写全白费
            # （013 子树77%>整树44%、029 71%>64%、028 80%≈80%），且 3a 的
            # 退化转发会多生成一次整树 → 直接跳过子树走 3b，省一轮 LLM+评审
            if rejected_ids:
                lca = dag._lca(rejected_ids)
                if lca is not None and lca != dag.root_id:
                    new_dag = planner.regenerate_subtree(
                        ctx, prior_dag=dag, rejected_ids=rejected_ids,
                        feedback_lines=feedback_lines)
                    if new_dag is not None:
                        dag = new_dag
                        self.record(ctx, "dag_replan",
                                    f"DAG 子树重写: {len(dag.nodes)} 节点, "
                                    f"rejected={rejected_ids[:5]}")
                        # 重写后再评审一次：通过则停，否则升级整树
                        report2 = reviewer.review(ctx, dag, results_map={})
                        if not report2.should_replan():
                            self.record(ctx, "dag_replan",
                                        "子树重写后 DAG 通过评审，停止修复")
                            return True
                        feedback_lines = (report2.merge_from_hints().split("\n")
                                          if report2.merge_from_hints() else feedback_lines)
                        rejected_ids = report2.rejected_nodes()
                        continue  # 子树修不动 → 下一轮升级整树
            # 3b) 整树重生成（子树修不动 / 无 reject 明细 / LCA=根 时兜底）
            new_dag = planner.regenerate_with_feedback(
                ctx, prior_dag=dag, feedback_lines=feedback_lines)
            if new_dag is None:
                self.record(ctx, "dag_replan", f"第 {round_idx + 1} 轮重生成失败，停止")
                return True  # 已尝试过，标记触发
            dag = new_dag
            self.record(ctx, "dag_replan",
                        f"DAG 第 {round_idx + 1}/{replan_rounds} 轮整树重生成: "
                        f"{len(new_dag.nodes)} 节点, root={new_dag.root_id}")
            # 重生成后再评审一次，避免死循环（重写还拒 → 停）
            new_plan = new_dag.to_subgoal_plan()
            subgoals = new_plan.get("subgoals", [])
            if subgoals:
                # 用 placeholder 结果集触发下一轮评审（即用新 DAG 但旧求解结果视作未知）
                report2 = reviewer.review(ctx, new_dag, results_map={})
                if not report2.should_replan():
                    self.record(ctx, "dag_replan",
                                "重生成 DAG 通过评审，停止整树重构")
                    return True
                feedback_lines = report2.merge_from_hints().split("\n") \
                    if report2.merge_from_hints() else feedback_lines
        else:
            # 仅"跑满硬上限"这一既有退出路径才记录（同 _dag_replan_gate:1334 的
            # for...else 惯例）；新增的时间闸 break 提前退出时不冒领此记录。
            self.record(ctx, "dag_replan",
                        f"达到重生成硬上限 {replan_rounds} 轮，停止")
        return True

    @staticmethod
    def _is_value_choice(opts: list) -> bool:
        """判断是否为「求值选择型」（C 型）：选项都是**短数值/表达式候选**。

        这类题必须**先整体求解、再与选项比对** —— 逐项判定"选项 5 成立吗"
        是无意义的（选项不是命题，只是候选值）。official112 实测无此类题，
        但比赛题库可能有，故必须支持。

        判据（保守，宁可漏判不可误判）：每个选项 ①不含中文 ②长度 ≤15 ③含数字。
        空列表（提取失败）一律返回 False —— 绝不把"没提取到选项"当成求值型。
        """
        try:
            if not opts:
                return False
            for _l, _t in (opts or []):
                _s = (_t or "").strip()
                if not _s:
                    return False
                if re.search(r"[\u4e00-\u9fff]", _s):   # 含中文 → 命题/文字选项
                    return False
                if len(_s) > 15:                         # 过长 → 非候选取值
                    return False
                if not re.search(r"\d", _s):             # 无数字 → 排除
                    return False
            return True
        except Exception:  # noqa: BLE001
            return False

    def _plan_value_choice(self, ctx: TaskContext, opts: list) -> dict:
        """C 型（求值选择）规划：**先整体求解 → 再与选项比对匹配**。

        与 A/B 型的根本区别：A/B 型的选项是**待判定的命题**，逐项判定即可；
        C 型的选项是**候选数值**，必须先算出结果，再找出与之相等的选项。
        """
        self.record(ctx, "subgoal",
                    "选择题求值型规划：先整体求解 → 再匹配选项（{} 个选项）"
                    .format(len(opts)))
        return {
            "problem_analysis": {
                "question_type": "选择题",
                "subtype": "value_choice",
                "options": [{"label": l, "text": t} for l, t in opts],
            },
            "subgoals": [
                {
                    "id": 0,
                    "title": "整体求解",
                    "description": (
                        "**不要**看选项，先独立把题目要求的量算出来。\n"
                        "要求：写出完整算式与推导，最后一行给出『结果：<值>』。"
                    ),
                    "type": "compute",
                    "depends_on": [],
                    "expected_output": "结果：<值>",
                    "result": "",
                },
                {
                    "id": 1,
                    "title": "匹配选项",
                    "description": (
                        "把【整体求解】得到的结果与下面每个选项逐一比对"
                        "（必要时做数值/符号等价判断）：\n"
                        + "\n".join("  {}. {}".format(l, t) for l, t in opts)
                        + "\n最后一行输出『匹配选项：<字母>』；"
                          "若结果与多个选项等价，则全部写出（如 `AC`）。"
                    ),
                    "type": "verify",
                    "depends_on": [0],
                    "expected_output": "匹配选项：<字母>",
                    "result": "",
                },
            ],
            "merge_strategy": (
                "直接输出【匹配选项】给出的字母（连写，不要逗号/空格/解释）；"
                "若匹配失败，输出与结果最接近的选项字母。"
            ),
        }

    def _plan_choice_by_options(self, ctx: TaskContext) -> dict | None:
        """选择题专用规划：**每个选项一个独立判定子目标**（2026-09-13 用户要求）。

        为什么不让 LLM 规划：096 实测——提示词里早已写了"逐项独立判真"，但模型
        仍然直接综合出 `ACD`（漏判 D 单独成立、误判 A/C）⇒ **提示词不具约束力**。
        故改为代码确定性构造：选项数 N → N 个判定子目标，一个都不能少。

        边界：① 非选择题 → None（走原流程）；② 选项 < 2 → None（判据不足）；
        ③ 选项数 > max_subgoals → None（交回 LLM 规划，避免被截断丢项）。
        """
        try:
            import os as _os
            # 独立开关（项目惯例：每项优化一个开关，便于 A/B 与逐项审查）。
            # 默认 "1" = 启用（用户 2026-09-13 明确要求：选择题每个选项都判断）；
            # 置 "0" 可一键回退到 LLM 规划。
            if _os.environ.get("OBJECTIVE_ITEMWISE_PLAN", "1") == "0":
                return None
            if getattr(ctx, "question_type", "") != "选择题":
                return None
            from .question_type import extract_options
            opts = extract_options(ctx.problem or "") or []
            if len(opts) < 2:
                return None
            _max_sg = int(getattr(self.config, "max_subgoals", 6) or 6)
            # 基准子目标(1) + N 个判定子目标(N)；超过上限则回退 LLM 规划
            if len(opts) + 1 > _max_sg:
                return None
            # ---- 题型子类识别（2026-09-13 用户要求：解题逻辑必须随题型而变）----
            #   A 命题判定型（选项是独立陈述，多选）→ 基准 + 逐项判定 → 全选为真
            #   B 定义/事实选择型（选项是互斥候选，单选）→ 基准 + 逐项判定 → 取唯一
            #   C 求值选择型（选项是短数值候选）→ **必须先整体求解**，再与选项比对
            _q = ctx.problem or ""
            if self._is_value_choice(opts):
                return self._plan_value_choice(ctx, opts)
            _is_single = bool(_SINGLE_CHOICE_RE.search(_q))
            subgoals = []
            # ★ 子目标 0：判断基准 —— **只建一次、全员共享**。
            #   对治用户指出的"ab 项是 cd 项的基础"：若让每个选项各自重新推导基准，
            #   既浪费又易导致判定口径不一致（判 A 用一套理解、判 C 用另一套）。
            subgoals.append({
                "id": 0,
                "title": "建立判断基准",
                "description": (
                    "先**只**建立本题的判断依据，**不要**在这里判定任何选项。\n"
                    "⚠ **严禁**在本步输出 `\\boxed{...}`、『最终答案』『答案是』"
                    "『综上，选』等**最终答案形态**的内容 —— 本步只提供依据，"
                    "最终答案由后续汇总步骤给出。实测 #098 因本步违规吐 `\\boxed{D}`，"
                    "导致该选项判定子目标照抄基准、整个判定链失效。\n"
                    "按题目需要输出以下之一（或多项）：\n"
                    "· 涉及定义/定理 → 写出相关定义或定理的**完整原文**；\n"
                    "· 涉及对应关系（“X 变为 Y”“增大/减小”“系数/常数项”"
                    "“约束/目标”等）→ 写出**完整映射表**，把原对象的每个元素"
                    "与变换后的元素逐项对应；\n"
                    "· 涉及计算 → 先算出**核心结果**（写出算式与结果）；\n"
                    "· 涉及判定标准 → 写出教材/规范中的判定标准原文。\n"
                    "这段基准是后续所有选项判定的**共同依据**，务必准确、可核验。"
                ),
                "type": "derive",
                "depends_on": [],
                "expected_output": "判断依据（定义原文 / 映射表 / 核心结果 / 判定标准）",
                "result": "",
            })
            for _i, (_lab, _txt) in enumerate(opts, 1):
                subgoals.append({
                    "id": _i,
                    "title": "判定选项 {}".format(_lab),
                    "description": (
                        "基于【建立判断基准】得到的定义原文 / 映射表 / 核心结果，"
                        "**只**判定选项 {} 这一个选项的陈述是否成立，不要讨论其他选项。\n"
                        "选项 {}：{}\n\n"
                        "【判定规范 · 必须遵守】\n"
                        "A. 先判断该选项属于哪类陈述，再选对应方法：\n"
                        "   ① 定义/定理类 → 逐词比对定义或定理原文，不得凭印象；\n"
                        "   ② 计算/等式类 → 代入数值或符号**实际验算**，写出算式；\n"
                        "   ③ 存在/构造类 → 给出具体构造，或给出明确反例；\n"
                        "   ④ **对应关系类**（“X 变为 Y”“由 A 得到 B”“增大/减小”"
                        "“左端/右端”“系数/常数项”“约束/目标”“前件/后件”）→ "
                        "**必须先列出映射表**，把原对象的每个元素与变换后的元素逐项"
                        "对应，再核对该选项的表述是否与映射表一致；"
                        "严禁凭“大体相关 / 看起来对”判为正确。\n"
                        "B. 含绝对化措辞（一定/必然/都/仅/只能/唯一/所有）时，"
                        "必须给出**无反例的论证**或**具体反例**，不得只写“不一定”。\n"
                        "C. 依据必须可核验：写出定义/定理名称或原文，或给出算式/反例。\n\n"
                        "【输出格式】开头一行写“结论：正确”或“结论：错误”，"
                        "随后用 1–2 句给出依据。"
                    ).format(_lab, _lab, _txt),
                    "type": "verify",
                    "depends_on": [0],
                    "expected_output": "选项 {}：正确/错误 + 理由".format(_lab),
                    "result": "",
                })
            self.record(ctx, "subgoal",
                        "选择题逐项判定规划：{} 个选项 → {} 个判定子目标"
                        "（代码强制，未走 LLM 规划）".format(len(opts), len(subgoals)))
            return {
                "problem_analysis": {
                    "question_type": "选择题",
                    "options": [{"label": l, "text": t} for l, t in opts],
                },
                "subgoals": subgoals,
                "merge_strategy": (
                    ("【单选型】" if _is_single else "【多选型】")
                    + "逐项汇总（不得跳步）：\n"
                    + (
                        "本题问法指向**单选**（“哪一项 / 最合适 / 定义是 / "
                        "通常采用”等）：在所有『结论：正确』的选项中，选择"
                        "**最准确、最直接回答题干**的一个；若只有一个判对则直接"
                        "输出它；若多个判对，输出最贴合题干的那一个，"
                        "并说明为何排除其余。\n"
                        if _is_single else
                        "本题问法指向**多选**（“哪些 / 正确的有”等）：把所有"
                        "『结论：正确』的选项字母**连写**输出（如 `ABD`），"
                        "不要逗号/空格。\n"
                    )
                    + "复核要求：① 对每个被判『错误』的选项，回看其依据是否真的成立；"
                      "② 对含绝对化措辞却判『正确』的选项，确认确实无反例；"
                      "③ **对应关系类选项**（“X 变为 Y”式）必须已完成映射表核对，"
                      "未核对的不计入正确项；④ **禁止**跳过逐项判定直接给答案。"
                ),
            }
        except Exception as _e:  # noqa: BLE001
            logger.warning("选择题逐项判定规划失败，回退 LLM 规划: %s", _e)
            return None

    # ---------- 阶段一：规划 ----------
    def _plan_subgoals(self, ctx: TaskContext) -> dict | None:
        """调用 LLM 生成子目标规划 JSON"""
        # 2026-09-13 用户要求「选择题就每个选项都判断」：选择题**不走 LLM 规划**，
        # 由代码确定性构造 N 个判定子目标（每选项一个），一个都不漏。
        # 依据：096 实测——提示词已写"逐项独立判真"，模型仍直接综合出 ACD
        # （漏判 D、误判 A/C）⇒ 提示词不具约束力，必须**代码强制**。
        _choice_plan = self._plan_choice_by_options(ctx)
        if _choice_plan is not None:
            return _choice_plan
        # #27 Blueprint DAG（LEAP Stage 1）：use_blueprint_dag 开启时先由
        # BlueprintPlanner 生成 AND-OR DAG（依赖驱动分解），再转子目标序列；
        # 生成失败回退到原有 LLM 规划（不损失候选来源）。
        if getattr(self.config, "use_blueprint_dag", False) or \
                getattr(self.config, "use_blueprint", False):
            blueprint_plan = self._plan_from_blueprint(ctx)
            if blueprint_plan is not None:
                return blueprint_plan
            self.record(ctx, "blueprint", "Blueprint DAG 规划失败，回退到 LLM 子目标规划")
        domain = ctx.domain or ""
        domain_hint = get_domain_hint(domain) if domain else ""
        # v2.9 遗留：原 Lean 前置形式化注入（formal_spec/formal_gaps/leansearch
        # 定理检索）已随 2026-09-06 去 Lean 化移除——平台无 Lean，注入恒为空。
        problem_text = ctx.problem
        # 2026-09-12 客观题特化（三处同源注入之①：规划阶段）：
        # 子目标主路径 2.7 对**所有档位默认先行**（enable_subgoal_main_path 默认
        # True），客观题的答案完全可能由本路径产出——只在 solver 里注入等于没注入。
        # 拼接位置固定在"题目"占位符内部，**不追加到提示词末尾**（历史教训
        # algebra-075：末尾追加破坏收尾结构 → 模型进入续写模式、泄漏占位符）。
        try:
            from .question_type import objective_injection as _obj_inj
            problem_text = problem_text + _obj_inj(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            pass
        # 2026-09-13 B0：答案形态要求**前置注入**（生成阶段就告知，而非事后重问）。
        # 依据：事后闸门在 formatter（流程末段）实测全部"时间不足跳过"——
        # deadline 被 tier_budget 收紧到 1800s，跑到末段必然剩余不足。
        try:
            from .question_type import answer_form_requirement as _afr
            problem_text = problem_text + _afr(
                ctx.problem or "", getattr(ctx, "question_type", "") or "")
        except Exception:  # noqa: BLE001
            pass

        user_msg = SUBGOAL_PLAN_USER_TEMPLATE.format(
            domain_hint=domain_hint,
            problem=problem_text,
        )

        last_resp = None
        for attempt in range(2):  # v2.6.1：3→2 次（解析失败说明 LLM 输出结构异常，
            # 重试成功率低；省下时间给真正有意义的求解步骤）
            # v2.4.1：prefill「{"」引导直接输出规划 JSON，抑制 CoT
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": SUBGOAL_PLAN_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    '{"',
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch('{"', resp)
                last_resp = resp
            if resp is None:
                continue
            raw = self._extract_json(resp)
            if raw is None:
                logger.warning("SubGoal plan: JSON parse failed on attempt %d", attempt + 1)
                continue
            subgoals = self._parse_subgoal_plan(
                raw, int(getattr(self.config, "max_subgoals", 6) or 6))
            if subgoals is None:
                logger.warning("SubGoal plan: invalid subgoals on attempt %d", attempt + 1)
                continue
            return {
                "problem_analysis": raw.get("problem_analysis", {}),
                "subgoals": subgoals,
                "merge_strategy": raw.get("merge_strategy", ""),
            }

        # v2.6.1 兜底：LLM 反复输出不合规 JSON 时，不再返回 None（损失整个候选来源），
        # 而是构造一个最小可用 plan（单步求解整道题），让 SubGoalSolver 至少产出 1 个
        # 候选；同时把最后一次响应记到 trace 便于排查 LLM 实际输出形态。
        self.record(ctx, "subgoal",
                    f"子目标规划 2 次尝试均失败; 最后响应片段: {(last_resp or '<None>')[:200]};"
                    " 回退到单步求解整道题")
        return {
            "problem_analysis": {},
            "subgoals": [{
                "id": 1,
                "title": "完整求解",
                "description": ctx.problem,
                "type": "compute",
                "depends_on": [],
                "expected_output": "",
                "result": "",
            }],
            "merge_strategy": "直接给出最终答案",
        }

    # ---------- Blueprint DAG 规划（#27）----------
    def _plan_from_blueprint(self, ctx: TaskContext) -> dict | None:
        """用 BlueprintPlanner 生成 AND-OR DAG 并转为子目标规划。"""
        try:
            from .blueprint_planner import BlueprintPlannerAgent
        except Exception as e:  # noqa: BLE001
            logger.warning("BlueprintPlanner 导入失败: %s", e)
            return None
        planner = BlueprintPlannerAgent(self.client, self.config)
        dag = planner.generate_blueprint(ctx)
        if dag is None:
            return None
        # 老师 9/2 建议：骨架编排层 review（求解前规划质量门）。
        # 生成骨架后先提交 LLM 审查：子目标是否不适定 / 求解难度是否 >= 原问题；
        # 有问题 → 带评审反馈重新生成骨架 → 再 review 确认；
        # 通过后才进入下方语法审核（_audit_blueprint_tree）与子目标求解。
        if getattr(self.config, "enable_skeleton_review", True):
            dag = self._skeleton_review_loop(ctx, dag, planner)
            if dag is None:
                return None
        # 2026-09-08 求解前 DAG 强制评审门——默认关闭（dag_replan_gate=False）。
        # 45 题实证：门"拦得住、修不好"（21/45 触发强制重写、净正确率贡献≈0、
        # 总耗时 +23%、触发组人均 +245s），重写对方向性错误无济于事（comb-058
        # 差1 / geo-068 思路偏，重写 2 轮达硬上限仍错）。蓝图评审-重写循环的
        # 时间让给子目标求解与数值验证。A/B 复测时显式置 dag_replan_gate=True。
        # 门代码与 Lean 升级逻辑保留（_dag_replan_gate / _lean_dag_logic_check），
        # 不开时不产生任何调用开销。
        if getattr(self.config, "dag_replan_gate", False):
            dag = self._dag_replan_gate(ctx, dag)
            if dag is None:
                return None
        plan = dag.to_subgoal_plan()
        if not plan.get("subgoals"):
            logger.warning("Blueprint DAG 无可用叶子子目标")
            return None
        # 2026-09-06 去 Lean 化：原 LEAP Stage 2 整树 Lean 搭桥审核
        # （_audit_blueprint_tree / lean_translator / lean_refiner）已移除——
        # 平台无 Lean，整树翻译+编译只空转。骨架评审（上方 enable_skeleton_review）
        # 是 LLM 规划质量门，与 Lean 无关，保留。
        self.record(ctx, "blueprint",
                    f"Blueprint DAG → {len(plan['subgoals'])} 个子目标 "
                    f"(根={dag.root_id}, 节点={len(dag.nodes)})")
        return plan

    def _skeleton_review_loop(self, ctx: TaskContext, dag,
                              planner, max_rounds: int = 2):
        """骨架编排层评审循环（老师 9/2 建议：求解前规划质量门）。

        评审 → 不过 → 带评审反馈重生成骨架 → 再评审，最多 max_rounds 轮。
        结束条件：评审通过 / 预算不足 / LLM 降级 → 返回当前 DAG。
        评审是质量增强门（非正确性门）：失败降级放行，不阻断主流程。
        """
        max_rounds = int(getattr(self.config, "skeleton_review_max_rounds",
                                 max_rounds) or max_rounds)
        max_rounds = max(1, max_rounds)
        for round_idx in range(max_rounds):
            from .skeleton_reviewer import SkeletonReviewerAgent
            reviewer = SkeletonReviewerAgent(self.client, self.config)
            report = reviewer.review(ctx, dag)
            if not report.should_regenerate():
                if report.degraded:
                    self.record(ctx, "skeleton_review",
                                f"骨架评审降级/预算不足（round={round_idx + 1}），放行")
                else:
                    self.record(ctx, "skeleton_review",
                                f"骨架评审通过（round={round_idx + 1}），进入语法审核")
                return dag
            if ctx.gen_time_up():
                self.record(ctx, "skeleton_review",
                            "骨架重生成预算不足，保留当前骨架")
                return dag
            feedback_lines = report.feedback_lines()
            new_dag = planner.regenerate_with_feedback(
                ctx, prior_dag=dag, feedback_lines=feedback_lines)
            if new_dag is None:
                self.record(ctx, "skeleton_review",
                            f"第 {round_idx + 1} 轮骨架重生成失败，保留当前骨架")
                return dag
            dag = new_dag
            self.record(ctx, "skeleton_review",
                        f"骨架第 {round_idx + 1}/{max_rounds} 轮重生成: "
                        f"{len(dag.nodes)} 节点")
        self.record(ctx, "skeleton_review",
                    f"骨架评审达硬上限 {max_rounds} 轮，采用末轮骨架")
        return dag

    # ---------- 求解前 DAG 强制评审门（2026-09-08 改进建议1）----------
    def _dag_replan_gate(self, ctx, dag, max_rounds: int = 2):
        """求解前 DAG 强制评审门：拒绝率>40% 的蓝图不许带病进求解。

        蓝图经骨架评审通过后、转子目标求解前，再用 DagReviewer 评审一次
        （results_map={} 时按结构评审：启发式循环/粒度过粗 + LLM 评估叶子
        与分解节点）。should_replan（reject≥5 或 比例≥40% 或评审降级）
        → **强制**进入带反馈重规划循环（子树局部重写 → 整树重生成），
        直到评审通过或达硬上限/预算耗尽——不允许带着高拒绝率蓝图推进求解。
        错题实证：comb-032 48%、geo-051 50%、nt-031 41.7%、nt-037 47.6%、
        nt-077 45%、nt-096 60% 的蓝图审查已亮红灯并建议重规划，但实际
        修订轮数=0（后置 replan 受 stage budget 限制 + 修复结果从不落盘）。

        与候选入池后的 _review_and_maybe_replan（事后兜底）区别：
        - 本门在求解前，replan 产生的新 DAG 真正被消费（转 plan 求解）；
          旧方法即使 replan 成功也不写回 ctx.blueprint → 白跑。
        - 预算耗尽 / 评审降级且无 reject 明细 → 放行原 DAG（质量门不阻断）。
        返回最终 DAG（已写回 ctx.blueprint）。
        """
        from .dag_reviewer import DagReviewerAgent
        if dag is None:
            return None
        if isinstance(dag, dict):
            from .blueprint_planner import BlueprintDAG
            try:
                dag = BlueprintDAG.from_dict(dag)
            except Exception as exc:  # noqa: BLE001
                self.record(ctx, "dag_replan", f"DAG 解析失败: {exc}")
                return None
        if not dag.nodes:
            return dag
        rounds = int(getattr(self.config, "dag_replan_max_rounds",
                             max_rounds) or max_rounds)
        rounds = max(1, rounds)
        reviewer = DagReviewerAgent(self.client, self.config)
        planner = None  # 惰性导入（仅需 replan 时才建）
        for round_idx in range(rounds):
            if ctx.gen_time_up():
                self.record(ctx, "dag_replan",
                            f"求解前评审门预算耗尽（round={round_idx}），放行当前蓝图")
                break
            report = reviewer.review(ctx, dag, results_map={})
            # 门升级（2026-09-08）：Lean 逻辑层检测。仅当本轮评审已出现 reject
            # 信号（report.reject_count > 0）时，在首轮触发一次 Lean 声明编译：
            # - 编译失败的节点（含 LLM 漏判的叶子）硬升级为 reject —— Lean 抓
            #   可判定的逻辑/类型层错误（符号未定义/自引用/类型错/不成良构命题）；
            # - 方向/语义错误仍完全由 LLM 评审判，本检测绝不降低任何 reject；
            # - 成本受控：每题至多 1 次（见 _lean_dag_logic_check 守卫），
            #   无 reject 信号（评审直接放行）的题零 Lean 开销。
            # 2026-09-08 修复：**accept 叶子优先、reject 补位**。实测 reject 节点
            # 多为操作类陈述（"令 y=0…"/"平移分割…"/"建坐标系…"），无法闭合
            # 形式化 → 翻译模型按"宁缺毋滥"全给空串，整组 Lean 检查作废；且
            # reject 节点已被 LLM 判错（Lean 升级只是补证据）。真正增量在
            # "LLM 放行的叶子被 Lean 抓住"——故名额先给叶子，reject 仅补位。
            if (round_idx == 0 and report.reject_count > 0
                    and not ctx.is_time_critical()):
                cap = max(1, int(getattr(self.config, "dag_lean_max_nodes",
                                         6) or 6))
                leaves = [nid for nid in report.accepted_nodes()
                          if nid in dag.nodes
                          and not dag.nodes[nid].children]
                cand = list(leaves[:cap])
                if len(cand) < cap:
                    cand += [nid for nid in report.rejected_nodes()
                             if nid not in cand][:cap - len(cand)]
                lean_fails = self._lean_dag_logic_check(ctx, dag, cand)
                if lean_fails:
                    upgraded = self._merge_lean_rejects(report, lean_fails)
                    if upgraded:
                        self.record(ctx, "dag_replan",
                                    "求解前 Lean 逻辑错误升级 reject: "
                                    + ",".join(upgraded))
            if not report.should_replan():
                self.record(ctx, "dag_replan",
                            f"求解前 DAG 评审通过（round={round_idx + 1}），进入子目标求解")
                break
            # 评审降级且无明确 reject（LLM 预算跳过）→ 不盲重构，放行
            if report.degraded and report.reject_count == 0:
                self.record(ctx, "dag_replan",
                            "求解前评审降级（无 reject 明细），放行当前蓝图")
                break
            if planner is None:
                from .blueprint_planner import BlueprintPlannerAgent
                planner = BlueprintPlannerAgent(self.client, self.config)
            rejected = report.rejected_nodes()
            hints = report.merge_from_hints()
            feedback = hints.split("\n") if hints else []
            # Lean 逻辑诊断并入重规划反馈（若本轮有升级）
            lean_lines = []
            for _r in report.results.values():
                if not _r.is_reject:
                    continue
                for _iss in _r.issues:
                    _t = str(_iss)
                    if _t.startswith("lean_logic_error"):
                        lean_lines.append(
                            f"[{_r.node_id}] Lean 逻辑检查: "
                            f"{_t[len('lean_logic_error:'):].strip()}")
                        break
            if lean_lines:
                feedback = lean_lines + feedback
            if not feedback:
                feedback.append(
                    "请重新审视蓝图拆解：结论族须覆盖题目全部约束、不引入"
                    "题目未允许的假设，子目标须可独立求解且比原题简单")
            new_dag = None
            if rejected:
                lca = dag._lca(rejected)
                if lca is not None and lca != dag.root_id:
                    try:
                        new_dag = planner.regenerate_subtree(
                            ctx, prior_dag=dag, rejected_ids=rejected,
                            feedback_lines=feedback)
                    except Exception as exc:  # noqa: BLE001
                        self.record(ctx, "dag_replan", f"子树重写异常: {exc}")
                        new_dag = None
            if new_dag is None:
                try:
                    new_dag = planner.regenerate_with_feedback(
                        ctx, prior_dag=dag, feedback_lines=feedback)
                except Exception as exc:  # noqa: BLE001
                    self.record(ctx, "dag_replan", f"整树重生成异常: {exc}")
                    new_dag = None
            if new_dag is None:
                self.record(ctx, "dag_replan",
                            f"求解前第 {round_idx + 1}/{rounds} 轮重规划失败，"
                            "保留当前蓝图进入求解（重规划信号已记入 diag）")
                break
            dag = new_dag
            self.record(ctx, "dag_replan",
                        f"求解前 DAG 第 {round_idx + 1}/{rounds} 轮重规划: "
                        f"{len(dag.nodes)} 节点, root={dag.root_id}")
        else:
            self.record(ctx, "dag_replan",
                        f"求解前评审门达硬上限 {rounds} 轮，采用末轮蓝图进入求解")
        ctx.blueprint = dag.to_dict()
        return dag

    # ---------- 求解前门 Lean 逻辑层检测（2026-09-08 门升级，见 _dag_replan_gate）---
    def _lean_dag_logic_check(self, ctx: TaskContext, dag,
                              node_ids) -> dict:
        """Lean 作为「逻辑错误」机器检测器：把节点陈述翻译成 Lean Prop
        并编译（声明模式 allow_sorry）。返回 {node_id: 首条诊断}。

        可判定层：语句无法良构形式化 / 符号未定义 / 类型错 / 自引用 /
        不成闭合命题。方向与语义错误**不在此列**（仍由 DagReviewer LLM 判）。

        成本受控（勿拖累解题预算——上轮 45 题教训）：
        - 每题至多被调用 1 次（gate 首轮、且有 reject 信号时）；
        - 节点数 ≤ dag_lean_max_nodes（默认 6）；
        - 时间紧迫 / Lean 环境不可用 / 无 lake 工程 / LLM 翻译失败 → 一律
          返回 {}（记一条事件后静默放行，绝不阻断、绝不误判整图）。
        """
        try:
            if not getattr(self.config, "dag_replan_lean_check", True):
                return {}
            if not node_ids:
                return {}
            if ctx.is_time_critical() or ctx.gen_time_up():
                return {}
            from tools.lean_local.lean_bridge import LeanBridge
            from tools.lean_local.lean_bridge import _trash_lean_file
            from tools.lean_local.lean_bridge import _mathlib_import_block
            bridge = LeanBridge(self.client, self.config)
            if not bridge.lean_available:
                self.record(ctx, "dag_replan",
                            "求解前 Lean 逻辑检查跳过（Lean 环境不可用）")
                return {}
            work_dir = bridge._lean_project_dir or ""
            if not work_dir:
                self.record(ctx, "dag_replan",
                            "求解前 Lean 逻辑检查跳过（无 lake 工程）")
                return {}
            cap = max(1, int(getattr(self.config, "dag_lean_max_nodes", 6) or 6))
            targets = [nid for nid in node_ids
                       if nid in dag.nodes][:cap]
            if not targets:
                return {}
            stmts = {nid: (dag.nodes[nid].statement or "")[:300]
                     for nid in targets}
            from prompts.dag_lean_check import (
                DAG_LEAN_CHECK_SYSTEM, DAG_LEAN_CHECK_USER_TEMPLATE)
            from utils.prefill import prefill_messages, stitch
            user_msg = DAG_LEAN_CHECK_USER_TEMPLATE.format(
                problem=(ctx.problem or "")[:1200],
                statements=json.dumps(stmts, ensure_ascii=False))
            _PREFILL = '{"'
            resp = self.llm(ctx, prefill_messages(
                [{"role": "system", "content": DAG_LEAN_CHECK_SYSTEM},
                 {"role": "user", "content": user_msg}],
                _PREFILL), 0.0, 16384)
            if resp:
                resp = stitch(_PREFILL, resp)
            exprs = self._parse_lean_expr_map(resp, targets)
            if not exprs:
                self.record(ctx, "dag_replan",
                            "求解前 Lean 逻辑检查跳过（节点翻译为空/不可解析）")
                return {}
            # 组装单文件：import 头（兼容部分编译布局，用 _mathlib_import_block）
            # + 每节点一行 example（匿名声明）；行号即节点映射。
            head_lines = [ln for ln in _mathlib_import_block().split("\n")]
            code_lines = list(head_lines)
            if code_lines and code_lines[-1].strip():
                code_lines.append("")
            line_of: dict = {}
            for nid in targets:
                expr = exprs.get(nid, "")
                if not expr:
                    continue
                expr = expr.strip()
                if not expr:
                    continue
                code_lines.append(f"example : ({expr}) := by sorry")
                line_of[nid] = len(code_lines)
            if not line_of:
                return {}
            code = "\n".join(code_lines)
            fname = (f"daglogic_{os.getpid()}_"
                     f"{int(time.time() * 1000) % 1000000}.lean")
            result = bridge._compile(code, work_dir, lean_filename=fname,
                                     allow_sorry=True)
            try:
                _trash_lean_file(work_dir, fname)
            except Exception:  # noqa: BLE001
                pass
            if not result or result.get("ok"):
                # 编译全过（节点均可良构形式化）也留痕，便于评测区分
                # "Lean 检查已执行但无逻辑错误" 与 "检查根本没触发"
                self.record(ctx, "dag_replan",
                            f"求解前 Lean 逻辑检查通过 {len(line_of)} 节点（无编译错误）")
                return {}
            err_text = str(result.get("error", ""))
            return self._map_lean_errors(err_text, line_of)
        except Exception as exc:  # noqa: BLE001  任何异常：降级放行，绝不阻断
            # 2026-09-08 排查：原仅 logger.debug → 评测零痕迹，无法区分
            # "检查未执行" 与 "执行中异常被吞"。升级为 record 留痕（防静默失效）。
            logger.debug("求解前 Lean 逻辑检查异常（放行）: %s: %s",
                         type(exc).__name__, exc)
            self.record(ctx, "dag_replan",
                        f"求解前 Lean 逻辑检查异常（放行）: "
                        f"{type(exc).__name__}: {str(exc)[:120]}")
            return {}

    @staticmethod
    def _parse_lean_expr_map(resp, targets) -> dict:
        """解析翻译 LLM 的 JSON 输出 → {nid: expr}；失败/空返回 {}。"""
        if not resp:
            return {}
        text = str(resp).strip()
        # 剥 markdown 围栏
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            raw = json.loads(text[start:end + 1])
        except (TypeError, ValueError):
            raw = None
        if not isinstance(raw, dict):
            return {}
        out = {}
        for nid in targets:
            val = raw.get(nid)
            if isinstance(val, str) and val.strip():
                out[nid] = val.strip()
        return out

    @staticmethod
    def _map_lean_errors(err_text: str, line_of: dict) -> dict:
        """把 Lean 编译错误文本按行号映射回节点。行号在首个 example 之前
        （import/文件级错误）→ 视为环境问题，返回 {}（不误判节点）。"""
        if not err_text or not line_of:
            return {}
        min_line = min(line_of.values())
        node_fail: dict = {}
        msg_of_line: dict = {}
        for m in re.finditer(r":(\d+):(\d+):\s*(error|warning):\s*([^\n]*)",
                             err_text):
            line = int(m.group(1))
            if m.group(3) == "error" and line not in msg_of_line:
                msg_of_line[line] = m.group(4).strip()
        if any(line < min_line for line in msg_of_line):
            return {}                      # 文件级/import 错误 → 环境问题
        for nid, line in line_of.items():
            msg = msg_of_line.get(line)
            if msg:
                node_fail[nid] = msg[:160]
        return node_fail

    @staticmethod
    def _merge_lean_rejects(report, lean_fails: dict) -> list:
        """Lean 编译失败的节点硬升级为 reject（含 LLM 漏判/未评的），
        返回本轮新升级的 node_id 列表。已 reject 的节点保持不动。"""
        from .dag_reviewer import DagReviewResult
        ups = []
        for nid, err in lean_fails.items():
            issue = f"lean_logic_error: {err}"
            r = report.results.get(nid)
            if r is None:
                report.results[nid] = DagReviewResult(
                    node_id=nid, verdict="reject", quality_score=0.2,
                    issues=[issue],
                    reconstruction_hint=(
                        "该节点陈述存在可判定的形式化逻辑错误（Lean 编译失败），"
                        "请修正陈述中的符号/量词/类型错误或改换可形式化的表述"),
                    heuristic_only=False)
                ups.append(nid)
            elif not r.is_reject:
                r.verdict = "reject"
                try:
                    r.quality_score = min(float(r.quality_score or 0.0), 0.3)
                except (TypeError, ValueError):
                    r.quality_score = 0.3
                if issue not in list(r.issues):
                    r.issues.append(issue)
                ups.append(nid)
        return ups

    # ---------- 阶段二：逐步求解 ----------
    def _solve_subgoal(self, ctx: TaskContext, sg: dict,
                       plan_summary: str, prev_results: str,
                       extra_hint: str = "") -> str:
        """求解单个子目标，返回结果文本。

        v2.7：计算类子目标（compute/derive）求解后用 AnswerOracle 做客观
        sanity check，若结果明显非法（不可解析为数学表达式），带反馈重解一次，
        实现"每步 oracle 校验"（Plan-and-Execute + oracle-in-the-loop）。

        v2.10（2026-08-29）：use_lemma_accumulation 开启时，把已求得的
        引理列表注入子目标提示词（"已建立的结论"），让后续子目标直接复用，
        避免重复推导（D6 引理积累钥匙的真正落地点）。

        v2.11（2026-09-06 老师建议）：extra_hint 承载 0-LLM 校验（S1-lite）
        的失败反馈——截断/Lean 代码片编译错误，随重解请求带回，让模型
        带反馈修正后重新给出【本步结果】（验证-精炼下沉到子目标级）。
        """
        # 引理注入：已求得的子目标结论作为"前置引理"提供。
        # **必须放在提示词中部（最终指令之前），不能追加在末尾**——
        # 2026-08-29 A/B 实测：追加在末尾会改变提示词收尾结构，使模型
        # 进入"续写模式"，答案泄漏 `[续写]` 占位符（algebra-075 因此从对变错）。
        lemma_context = ""
        if self._use_lemma(ctx):
            lemmas = list(getattr(ctx, "lemma_repo", []) or [])
            if lemmas:
                lemma_block = "\n".join(f"- {l}" for l in lemmas[-8:])
                lemma_context = (
                    f"\n【已建立的结论（可直接引用，无需重新推导）】\n"
                    f"{lemma_block}\n")

        # ② 原子目标级 leansearch 独立检索（LeanSearch v2 论文）已随
        # 2026-09-06 去 Lean 化移除——平台无外网/无 Lean，检索恒空转。

        # 2026-09-12 客观题特化（三处同源注入之②：子目标逐步求解）——这是子目标
        # 链里**真正产出内容**的一步，客观题答案可能直接来自本步结果。
        _obj_inj = ""
        try:
            from .question_type import objective_injection as _oi
            _obj_inj = _oi(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            _obj_inj = ""
        # ★ 2026-09-14（#103「丢 E」真根因修复）：剥离题面的
        #   「Remember to put your final answer within \boxed{}.」指令。
        #   实测该句**112/112 题都有**（题库统一附加），它会随题面进入**每个
        #   中间子目标**的 prompt ⇒ ① 选项判定子目标全都输出 `\boxed{A}`；
        #   ② **最后一个选项**直接吐**最终答案**（#103「判定选项 E」→
        #   `\boxed{ABCD}`）⇒ 聚合层认不出它是 E 的判定 ⇒ 静默丢项。
        #   该指令只对**最终汇总**步骤有效（merge 仍用原题、保留 boxed 要求），
        #   故此处对子目标 prompt 使用剥离版题面。
        try:
            from .question_type import strip_answer_format_directive as _safd
            _prob_for_step = _safd(ctx.problem or "")
        except Exception:  # noqa: BLE001
            _prob_for_step = ctx.problem or ""
        user_msg = SUBGOAL_STEP_USER_TEMPLATE.format(
            problem=_prob_for_step + _obj_inj,
            subgoal_plan_summary=plan_summary,
            previous_results=prev_results,
            lemma_context=lemma_context,
            subgoal_id=sg["id"],
            subgoal_title=sg["title"],
            subgoal_type=sg["type"],
            subgoal_description=sg["description"],
            subgoal_expected_output=sg["expected_output"],
        )
        # v2.11：0-LLM 校验反馈（S1-lite）追加在提示词末尾；只有校验真没过才带
        # （空串 = 通过）。不追加在开头/中部，避免改变模板收尾结构（2026-08-29
        # 教训：提示词收尾被破坏会让模型进入续写模式、泄漏占位符）。
        if extra_hint:
            user_msg = user_msg + (
                f"\n\n[本步结果校验反馈] {extra_hint}\n"
                f"请修正后重新给出【本步结果】。"
            )

        step_result = self._call_step(ctx, user_msg, sg=sg)

        # 每步 oracle 校验：仅对计算类子目标（预期数值/表达式结果）做客观检查
        # 2026-09-03 老师：子目标是**简化求解**的，不是复杂化的。实测 deep 档
        # 每步 110s（主求解 60s + oracle 10-70s + 重试 60s）→ 8 步吃掉 882s，
        # 验证/Lean 闸门全没时间。oracle 是**同源自评**（价值低、耗时高），
        # 默认关闭（sub_goal_oracle_check=False 开启）。
        # 注意：这里**不是强制结束**——失败重试（_solve_subgoal 的上下文重试）
        # 仍保留，子目标一定会尽力做完（老师："强制结束就等于错误"）。
        sg_type = sg.get("type", "compute")
        if (getattr(self.config, "sub_goal_oracle_check", False)
                and sg_type in ("compute", "derive")
                and step_result
                and not step_result.startswith("[子目标")):
            oracle_fb = self._oracle_check_step(step_result)
            if oracle_fb and not ctx.gen_time_up():
                retry_msg = user_msg + (
                    f"\n\n[上一步结果客观校验未通过] {oracle_fb}\n"
                    f"请修正错误后重新给出【本步结果】。"
                )
                retry_result = self._call_step(ctx, retry_msg, sg=sg)
                if retry_result and not retry_result.startswith("[子目标"):
                    return retry_result
        return step_result

    def _use_lemma(self, ctx: TaskContext) -> bool:
        """按领域路由 lemma 累积（与 SolverAgent 同规则，2026-08-29）。

        A/B 实测 lemma 全开净 0.0pp、数论 +23pp → 数论域开、其他关。
        """
        if not getattr(self.config, 'use_lemma_accumulation', False):
            return False
        domains = list(getattr(self.config, 'lemma_domains', []) or [])
        if not domains:
            return True
        d = str(getattr(ctx, 'domain', '') or '')
        return any(k in d for k in domains)

    def _accumulate_lemma(self, ctx: TaskContext, sg: dict, result: str) -> None:
        """把已求得的子目标结论存入 ctx.lemma_repo（去重，单题内存）。

        只收有效结果（剔除占位符/失败标记），按「标题: 结论」存储，
        后续子目标与最终求解步骤通过提示词注入复用。
        """
        if not result or result.startswith("[子目标"):
            return
        title = (sg.get("title") or "").strip()
        text = str(result).strip()
        if not title or not text:
            return
        entry = f"{title}: {text}"
        if entry not in ctx.lemma_repo:
            ctx.lemma_repo.append(entry)

    def _call_step(self, ctx: TaskContext, user_msg: str,
                     sg: dict | None = None) -> str:
        """单步子目标求解调用（prefill「【本步结果】」答案前置，抑制 CoT）。

        2026-09-04 calc 纪律下沉：system 追加 <calc> 计算引导（与 solver 主链
        同款），响应回填 <calc> 块为精确值——子目标步骤不再靠模型心算。
        """
        _step_system = SUBGOAL_STEP_SYSTEM
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            _step_system = SUBGOAL_STEP_SYSTEM + _CALC_GUIDE
            # 方案 A：把 user_msg（含 previous_results / lemma_context）里已回填的
            # [计算] 精确值汇总前置——本步直接引用，不必翻长文、更不必重算。
            # 方案 B：并把生成前预计算的值（ctx.calc_prewarm_block）一并前置。
            _step_system = _step_system + _calc_results_block(
                user_msg, getattr(ctx, "calc_prewarm_block", None))
        # P2（2026-09-09）：纯计算子目标 → 追加专用协议段（system 级，
        # 不动 user 模板收尾结构，防续写模式）
        if (sg is not None and sg.get("calc_kind") == "terminal"
                and getattr(self.config, "subgoal_calc_router", False)):
            _step_system = _step_system + _TERMINAL_GUIDE
        resp = self._maybe_tool_llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _step_system},
                    {"role": "user", "content": user_msg},
                ],
                "【本步结果】",
            ),
            0.2, 32768,
        )
        if resp:
            resp = stitch("【本步结果】", resp)
        if resp is None:
            return "[子目标求解失败]"

        # 2026-09-04 calc_tool 回填：<calc>表达式</calc> → [计算] 表达式 = 精确值
        # （在提取【本步结果】之前，让精确结果参与结果提取；与 solver 同序）
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            resp, _resolved = resolve_all_calcs(resp)
            # P1-2（2026-09-09）：工具失败审计留痕（WARN:/ERROR: 回填）
            self.record_calc_successes(ctx, _resolved)
            if audit_calc_fallbacks is not None:
                for _ex, _rs in audit_calc_fallbacks(_resolved):
                    self.record(ctx, "calc_fallback",
                                f"<calc>{_ex}</calc> → {_rs}",
                                expr=_ex, reason=_rs)

        # 提取「本步结果」部分
        result_match = re.search(r"【本步结果】\s*\n?(.*?)(?:$|【)", resp, re.DOTALL)
        if result_match:
            return result_match.group(1).strip()
        # 如果没有标记，取最后 500 字符
        return resp.strip()[-500:]

    @staticmethod
    def _oracle_check_step(step_result: str) -> str:
        """用 AnswerOracle 对子目标结果做客观 sanity check，返回反馈（空=通过）。"""
        try:
            from .answer_oracle import AnswerOracle
            # 结果可解析为数学表达式 → 通过；否则视为非法（可能为幻觉/格式错误）
            if not AnswerOracle.is_parseable(step_result):
                return "该步结果无法解析为有效数学表达式"
        except Exception as exc:  # noqa: BLE001
            # 2026-09-04 审核：异常吞掉 = 子目标 sanity check 静默放行。留证据。
            logger.debug("子目标 sanity check 异常（放行）: %s: %s",
                         type(exc).__name__, exc)
        return ""

    # ------------------------------------------------------------------
    # S1-lite：子目标级 0-LLM 校验前移（2026-09-06 老师建议）
    # ------------------------------------------------------------------
    # 老师：lean 校验服务很多要排优先级；子目标宜独立、上下文少 → 校验可前移。
    # 落地形态（全部 0-LLM、秒级~21s、异常/环境缺失一律放行，绝不阻断）：
    #   L0  截断/空结果检查（全档，0 成本）——治"答案腰斩"型错误（L2 截断修复下沉）；
    #   L0P 占位/空转检测（全档，0 成本）——2026-09-07 禁网冒烟实证：PB-002 SG#2
    #       ='（无）'、SG#4='（子目标4 已求解）'、alg-060 SG#1='[计算] 1 = 1'，
    #       LLM 空转输出既非空也非截断、不带 lean 代码 → 旧 L0/L1 全放行流入 merge。
    #       短结果里出现占位词 / 重言式回填 → 视为未真正求解，带反馈重解。
    #   L1 Lean 代码片编译校验（仅 deep 档 + lean 环境可用，0 LLM 5-21s）——
    #     子目标结果若自带 lean 代码（```lean ... ``` 或 import 块），本地编译
    #     抓语法/类型错，禁网下纯本地（lean-lsp-mcp 禁网已验证 0 出网）。
    #     注：2026-09-07 冒烟实测子目标结果多为短结论行、极少带 lean fence，
    #     L1 触发面天然小；价值主要在 L0P 的占位拦截，L1 仅作兜底保留。
    # 不做：LLM 翻译整段子目标结果去 lean 化（翻译成本与整题 6.5 校验重复，列赛后）。

    _LEAN_FENCE = re.compile(
        r"```(?:lean4?|lean)?\s*\n(.*?)```", re.DOTALL)

    # L0P：短结果占位词（≤50 字符内命中才算，长结果里的行文不判）。
    # 只收高置信空转形态（宁漏勿误伤：如"方程无解""待定系数"是真结论）。
    # 2026-09-08：`[计算] X = X` 型**平凡 calc 回填**单列判据（见下）——
    # 旧注释担心 `[计算] 191/192 = 191/192` 是真分数验证无法与空转区分；
    # 但回填格式是 `[计算] expr = result`，**result 与 expr 逐字相同**意味着
    # 模型只是把结论原样丢给 <calc>（<calc>191/192</calc> 无任何运算发生），
    # 属 alg-060 SG#1='[计算] 1 = 1' 同型空转，可可靠判定。真运算（如
    # <calc>comb(50,3)</calc> → [计算] comb(50,3) = 19600）result≠expr 不受影响。
    _PLACEHOLDER_RE = re.compile(
        r"（无）|（略）|暂无|占位|空转|未求解|未给出"
        r"|子目标\s*\d+\s*已(?:求解|完成|给出)"
        r"|^同上$|^见上$"
    )
    # `[计算] X = X` 切分（左右各自归一后比较，见 _looks_placeholder）。
    # 2026-09-08 二次升级：SymPy 符号化简回填带空格（`1/(n + 1)`）或幂记号
    # 差异，旧 `\1` 逐字反引用会漏判"符号复读空转"（模型把 1/(n+1) 原样丢给
    # <calc> 当自证）；改为切出左右两侧后**去空白归一比较**——真运算
    # （comb(50,3) → 19600、integral 结果、sqrt(45) → 3*sqrt(5)）两侧不同，
    # 不受影响；无运算的复读（1/(n+1)=1/(n+1)、0=0）可靠拦截。
    _TRIVIAL_CALC_RE = re.compile(
        r"^\[计算\]\s*(?P<left>.+?)\s*=\s*(?P<right>.+?)\s*$", re.DOTALL)

    @classmethod
    def _looks_placeholder(cls, result: str) -> bool:
        """短结果占位/空转检测：占位词命中 或 平凡 calc 回填（无运算发生）。"""
        if not result:
            return False
        text = result.strip()
        # 平凡 calc 回填：整体就是一行 `[计算] X = X`（结果≤120 字符内判定）
        if len(text) <= 120:
            m = cls._TRIVIAL_CALC_RE.match(text)
            if m and m.group("left").strip():
                left = re.sub(r"\s+", "", m.group("left")).replace("^", "**")
                right = re.sub(r"\s+", "", m.group("right")).replace("^", "**")
                if left == right:          # 去空白后两侧相同 = 无运算发生
                    return True
        if len(text) > 50:            # 长结果视为有内容，不做占位词判定
            return False
        return bool(cls._PLACEHOLDER_RE.search(text))

    @classmethod
    def _extract_lean_code(cls, result: str) -> str:
        """从子目标结果提取 lean 代码片（fence 或裸 import 块）；无则空串。"""
        if not result:
            return ""
        m = cls._LEAN_FENCE.search(result)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # 无 fence：整段以 import 开头（疑似裸 lean 代码）时收整段
        head = result.strip()[:80]
        if head.startswith("import ") or head.startswith("import\n"):
            return result.strip()
        return ""

    def _subgoal_light_check(self, ctx: TaskContext, sg: dict,
                             result: str) -> str:
        """子目标结果 0-LLM 校验，返回反馈文本（空=通过）。异常全部放行。"""
        try:
            if not result or not result.strip():
                return "【本步结果】为空，请给出完整结果。"
            # L0P 占位/空转检测（全档，0 LLM）——2026-09-07 冒烟实证拦截项
            if self._looks_placeholder(result):
                return ("【本步结果】疑似占位/空转：仅给出“（无）”“已求解”等占位词，"
                        "或把结论原样丢给 <calc> 自证（如“[计算] 1 = 1”这类"
                        "表达式与结果相同的重言回填，没有任何运算发生）。"
                        "请真正求解：给出基于题目条件的推导与数值/表达式结论，"
                        "并用 <calc> 完成实际运算。")
            # L0C 裸数值断言打回（2026-09-09 P1-1，仅 calc_mandatory 开启）：
            # 2026-09-12 精准化：只回收**易错运算**的心算痕迹（开方/对数/组合数/
            # 幂/e/阶乘/三角/取模/求和积分），纯四则（加减乘除）允许自算。
            if (find_naked_numeric_asserts is not None
                    and getattr(self.config, "calc_mandatory", True)):
                _naked = find_naked_numeric_asserts(result)
                if _naked:
                    self.record(ctx, "subgoal_l0c",
                                f"L0C 打回裸数值断言: {_naked[0][:80]}")
                    return ("【本步结果】含未用 <calc> 工具的**易错运算**结果"
                            "（开方/根式、对数、组合数/阶乘、幂运算、自然常数 e "
                            "等必须由系统工具完成，**禁止心算——即使你确信数值"
                            "正确也必须让系统计算确认**；简单加减乘除可自算）：`"
                            + _naked[0][:60] +
                            "`。请把该行改写为 …<calc>表达式</calc>… 让系统回填"
                            "精确结果后继续。")
            # P2（2026-09-09）：纯计算子目标（terminal）轻校验——router 开启时
            # 结果必须已由 <calc> 回填或显式自算标注，防 terminal 走回推理/心算。
            if (sg.get("calc_kind") == "terminal"
                    and getattr(self.config, "subgoal_calc_router", False)):
                _head = result.strip()[:60]
                if not (result.startswith(("[计算]", "[自算]", "（子目标", "[子目标"))
                        or "<calc>" in result):
                    return ("【本子目标为纯计算子目标】请只给出一个 "
                            "<calc>表达式</calc>，系统回填的精确值即本步结论；"
                            f"当前结果（{_head}）不是回填形态，请改写为单个表达式。")
            # L0 截断检查（全档，0 LLM）
            from utils.extract import is_truncated_answer as _trunc
            if _trunc(result):
                return ("【本步结果】被截断（超出输出上限），"
                        "请压缩推理、只保留结论与关键计算，完整给出【本步结果】。")
        except Exception:  # noqa: BLE001
            pass
        # L1 lean 代码片编译（仅 deep 档 + lean 可用；禁网纯本地）
        try:
            if str(getattr(ctx, "tier", "") or "") != "deep":
                return ""
            if not getattr(self.config, "enable_subgoal_lean_check", True):
                return ""
            code = self._extract_lean_code(result)
            if not code:
                return ""
            from tools.lean_local.lean_bridge import LeanBridge
            from tools.lean_local.lean_bridge import _trash_lean_file
            bridge = LeanBridge(self.client, self.config)
            if not bridge.lean_available:
                return ""
            work_dir = bridge._lean_project_dir or ""
            if not work_dir:
                return ""          # 无 lake 工程 → 不尝试（避免直编找不到 Mathlib）
            fname = f"sg_check_{int(time.time() * 1000) % 1000000}.lean"
            r = bridge._compile(code, work_dir, lean_filename=fname)
            try:
                _trash_lean_file(work_dir, fname)
            except Exception:  # noqa: BLE001
                pass
            if not r.get("ok"):
                err = str(r.get("error", ""))[:200]
                return (f"本步给出的 Lean 代码编译失败（{err}）。"
                        "请修正代码（或改用数学表述，不必强制给 Lean）。")
        except Exception as exc:  # noqa: BLE001  校验失败放行，绝不阻断
            logger.debug("子目标 0-LLM 校验异常（放行）: %s: %s",
                         type(exc).__name__, exc)
        # L2/L3 数值断言验证（2026-09-08 去门后新钩子）：
        # L3 协议版优先——模型 <check> 显式声明的等式（sympy 判 + Lean 背书）；
        # L2 提取式兜底——无 <check> 时 0-LLM 提取纯数值/整式断言。
        # 失败 = 计算未通过验证 → 反馈带真值让 LLM 带错重解。0-LLM 构造；
        # 无数值断言零成本；异常/语法不支持一律放行不误报；每题限额防烧预算。
        try:
            _nv_fb = self._check_assert_verify(ctx, result)
            if not _nv_fb:
                _nv_fb = self._numeric_lean_verify(ctx, result)
            if _nv_fb:
                return _nv_fb
        except Exception:  # noqa: BLE001
            pass
        return ""

    # ---------- L2 数值/代数断言 Lean 验证（2026-09-08）----------
    _L2_EXPR_CHARS = re.compile(r"^[0-9a-zA-Z^*/+\-() ]+$")

    def _extract_lean_assert_pairs(self, result: str) -> list:
        """从子目标结果提取可 Lean 验证的等式断言。

        返回 [(lean_l, lean_r, kind)]，kind: "num"(ℚ norm_num) | "poly"(ℤ ring)。
        宁缺毋滥：只收两侧均为纯数值表达式（kind=num）或同一单变量整式
        （kind=poly，无除号）的断言；含多变量/除号/分数指数/LaTeX → 丢弃。
        """
        if not result:
            return []
        text = str(result)
        # 剥 LaTeX 内联/显示定界符
        text = re.sub(r"\\[a-zA-Z]+", " ", text)     # 去 \frac \sqrt 等命令
        text = text.replace("{", " ").replace("}", " ")
        text = text.replace("$", " ")
        text = text.replace("\\", " ")
        out = []
        for seg in text.split("\n"):
            if "=" not in seg:
                continue
            parts = [p.strip() for p in seg.split("=")]
            for i in range(len(parts) - 1):
                L, R = parts[i], parts[i + 1]
                # R 取到行尾（连环等号时一次只取相邻两段，宁可少验）
                L, R = L.strip(), R.strip()
                if not (1 <= len(L) <= 70 and 1 <= len(R) <= 70):
                    continue
                if not (self._L2_EXPR_CHARS.match(L)
                        and self._L2_EXPR_CHARS.match(R)):
                    continue
                # ^ 指数必须是非负整数（避免 13^(2/3) 这类 Lean 语法不支持）
                if re.search(r"\^[^0-9(]|\^$", L) or re.search(r"\^[^0-9(]|\^$", R):
                    continue
                # 宁缺毋滥：函数调用形态（g(0)/f(1)/sin(x)）与隐式乘
                # （2x / xx / x(3)）在 Lean 中不合法 → 一律丢弃不构造
                if (re.search(r"[a-zA-Z]\(", L) or re.search(r"[a-zA-Z]\(", R)
                        or re.search(r"\d[a-zA-Z]", L) or re.search(r"\d[a-zA-Z]", R)):
                    continue
                letters = sorted(set(re.findall(r"[a-zA-Z]", L + R)))
                if not letters:
                    # 纯数值（可含负号/分数/幂）→ ℚ norm_num
                    out.append((L, R, "num"))
                elif len(letters) == 1:
                    v = letters[0]
                    if "/" in (L + R):
                        continue              # 除号 → 非整式，ring 不适用
                    # 变量须独立出现（两侧不被其他字母邻接，如 xx 简写）
                    if (re.search(r"[a-zA-Z]" + v, L)
                            or re.search(v + r"[a-zA-Z]", L)
                            or re.search(r"[a-zA-Z]" + v, R)
                            or re.search(v + r"[a-zA-Z]", R)):
                        continue
                    out.append((L, R, "poly", v))
                # 多变量 → 跳过
        # 去重（保持序）
        seen, uniq = set(), []
        for t in out:
            key = tuple(t[:2])
            if key not in seen:
                seen.add(key)
                uniq.append(t)
        return uniq[:3]                       # 单次最多 3 条断言

    @staticmethod
    def _fix_lean_mul(expr: str) -> str:
        """把 NL 隐式乘转 Lean 显式 *：)(、)字母/数字、数字( → 显式乘。

        相邻括号/字母/数字在 Lean 里是函数应用（语法错或语义错），
        norm_num/ring 场景一律应视为乘号。
        """
        e = expr.strip()
        # 数字后紧跟左括号：2(x+1) → 2 * (x+1)（^ 后括号不动：2^(3) 罕见，宁可不转）
        e = re.sub(r"(?<=[0-9])\(", " * (", e)
        # 右括号后紧跟 ( / 字母 / 数字：)( → ) * (、)x → ) * x、)2 → ) * 2
        e = re.sub(r"\)(?=[0-9a-zA-Z(])", ") * ", e)
        # 折叠可能产生的重复乘号（"* * "）
        e = re.sub(r"\*\s*\*", "*", e)
        e = re.sub(r"\(\s*\*\s*\(", "(", e)
        return e.strip()

    def _numeric_lean_verify(self, ctx: TaskContext, result: str) -> str:
        """L2 数值断言 Lean 验证，返回反馈文本（空=通过/无可验断言/放行）。"""
        if not getattr(self.config, "enable_numeric_lean_verify", False):
            return ""
        if ctx.gen_time_up():
            return ""
        meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        cnt = int(meta.get("numeric_lean_count", 0) or 0)
        cap = max(1, int(getattr(self.config, "lean_numeric_max_per_q", 2) or 2))
        if cnt >= cap:
            return ""
        pairs = self._extract_lean_assert_pairs(result)
        if not pairs:
            return ""
        from tools.lean_local.lean_bridge import LeanBridge
        from tools.lean_local.lean_bridge import _trash_lean_file
        from tools.lean_local.lean_bridge import _mathlib_import_block
        bridge = LeanBridge(self.client, self.config)
        if not bridge.lean_available:
            return ""
        work_dir = bridge._lean_project_dir or ""
        if not work_dir:
            return ""
        code_lines = [ln for ln in _mathlib_import_block().split("\n")]
        if code_lines and code_lines[-1].strip():
            code_lines.append("")
        line_of = {}
        for idx, (L, R, kind, *rest) in enumerate(pairs):
            # 隐式乘（)(、)字母/数字、数字( ）→ 显式 *（Lean 中相邻即应用）
            L = self._fix_lean_mul(L)
            R = self._fix_lean_mul(R)
            if kind == "num":
                decl = f"example : ({L} : ℚ) = ({R} : ℚ) := by norm_num"
            else:
                v = rest[0]
                decl = f"example ({v} : ℤ) : {L} = {R} := by ring"
            code_lines.append(decl)
            line_of[idx] = len(code_lines)
        code = "\n".join(code_lines)
        fname = f"sgnum_{os.getpid()}_{int(time.time() * 1000) % 1000000}.lean"
        try:
            r = bridge._compile(code, work_dir, lean_filename=fname,
                                allow_sorry=True)
        finally:
            try:
                _trash_lean_file(work_dir, fname)
            except Exception:  # noqa: BLE001
                pass
        meta["numeric_lean_count"] = cnt + 1
        if not r or r.get("ok"):
            return ""
        err_text = str(r.get("error", ""))
        # 行号 → 断言映射；文件级错误（行号 < 首条 example）视为环境问题放行
        min_line = min(line_of.values())
        node_fail: dict = {}
        msg_of_line: dict = {}
        for m in re.finditer(r":(\d+):(\d+):\s*(error|warning):\s*([^\n]*)",
                             err_text):
            line = int(m.group(1))
            if m.group(3) == "error" and line not in msg_of_line:
                msg_of_line[line] = m.group(4).strip()
        if msg_of_line and min(msg_of_line) < min_line:
            return ""                          # import/文件级 → 环境问题
        for idx, ln in line_of.items():
            msg = msg_of_line.get(ln)
            if msg:
                node_fail[idx] = msg[:120]
        if not node_fail:
            return ""
        # 命中 ≥1 条断言：组装反馈（最多报 2 条）
        lines = []
        for idx in sorted(node_fail)[:2]:
            L, R = pairs[idx][0], pairs[idx][1]
            diag = node_fail[idx]
            lines.append(
                f"断言「{L} = {R}」未通过 Lean 验证"
                + (f"（{diag}）" if diag else ""))
        return ("【Lean 数值验证未通过】本步含以下计算断言，编译器未能确认成立，"
                "请逐条复核并修正数值/表达式后重新给出【本步结果】："
                + "；".join(lines) + "。"
                "（若表达式本身含 Lean 不支持的记号，请改写为等价的标准形式）")

    # ---------- L3 <check> 协议断言验证（2026-09-08 协议版）----------
    # 模型在【本步结果】用 <check>LHS = RHS</check> 显式声明待验证等式 →
    # 提取零歧义（解决提取式 2.8% 覆盖率问题）。判定：sympy 精确判定为主
    # （expand/simplify，确定性无浮点误差）→ 判"不成立"的再交 Lean
    # norm_num/ring 编译背书（mcp 后端）双确认 → 反馈带标准化简结果
    # （可行动），杜绝"只知道错、不知道对什么"的裸诊断。
    _CHECK_RE = re.compile(r"<check>(.*?)</check>", re.DOTALL)

    def _extract_check_asserts(self, result: str) -> list:
        """提取 <check> 协议断言 → [(L, R)]（宁缺毋滥）。"""
        if not result:
            return []
        out = []
        for m in self._CHECK_RE.finditer(str(result)):
            body = m.group(1).strip()
            if not body or len(body) > 160 or "=" not in body:
                continue
            parts = [p.strip() for p in body.split("=")]
            if len(parts) != 2:                    # 多 = → 丢弃
                continue
            L, R = parts
            if not (1 <= len(L) <= 70 and 1 <= len(R) <= 70):
                continue
            if not (self._L2_EXPR_CHARS.match(L)
                    and self._L2_EXPR_CHARS.match(R)):
                continue
            if (re.search(r"[a-zA-Z]\(", L) and not re.search(
                    r"^(sin|cos|tan|log|ln|exp|sqrt|abs|floor|ceil|min|max)\(",
                    L)):
                continue                          # 函数调用形态（sin 等除外）
            out.append((L, R))
        seen, uniq = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq[:4]

    @staticmethod
    def _strip_check_tags(text: str) -> str:
        """剥 <check>...</check> 验证标签：去标签保留内部内容（数学等式文本无害）。

        仅当标签完整闭合时剥除；不闭合的残留 <check> 一并删除防泄漏。
        """
        if not text or "<check>" not in text:
            return text
        t = re.sub(r"<check>(.*?)</check>", r"\1", str(text), flags=re.DOTALL)
        # 兜底：未闭合/孤立标签删除
        t = t.replace("<check>", "").replace("</check>", "")
        return t

    @staticmethod
    def _pow_to_python(s: str) -> str:
        """裸 ^ → **（先保护已有 **）。"""
        s = s.replace("**", "@@P@@")
        s = re.sub(r"\^", "**", s)
        return s.replace("@@P@@", "**")

    def _sympy_judge(self, L: str, R: str):
        """sympy 判定 L=R。返回 ("pass"|"fail"|"unknown", 说明/真值串)。

        判据（防误报红线）：
        - **赋值式跳过**：任一侧是单个未知变量（x = 5、s = 265/247）→
          这是"求解结果"而非"恒等断言"，无 ground truth 可验 → unknown
          放行（2026-09-08 smoke10 实证：模型大量用 <check>x = 值</check>
          声明赋值结果，误当恒等断言会误报把对的改错）；
        - 整式/数值（无除号无函数）→ expand(L-R)==0 才 pass；非 0 差为常数
          或含自由变量 → fail（多项式不恒等=断言错，无限域可靠）；
        - 含除号/函数 → 仅 simplify(L-R) 为 0 → pass、为非零常数 → fail，
          非常数一律 unknown（放行，绝不误报）。
        """
        try:
            from utils.sympy_tools import _try_parse
        except Exception:  # noqa: BLE001
            return "unknown", ""
        try:
            # 赋值式跳过：一侧是单个变量 v 且另一侧**不含 v**（x = 5、s = 265/247）
            # 才是"求解结果"；若另一侧也含 v（如 (x^2-1)/(x-1) = x）则是恒等
            # 断言，仍正常判定。
            _Lt, _Rt = L.strip(), R.strip()
            if (re.fullmatch(r"[a-zA-Z]", _Lt) and _Lt not in R) or (
                    re.fullmatch(r"[a-zA-Z]", _Rt) and _Rt not in L):
                return "unknown", ""
            L2, R2 = self._pow_to_python(L), self._pow_to_python(R)
            a, _ = _try_parse(L2)
            b, _ = _try_parse(R2)
            if a is None or b is None:
                return "unknown", ""
            import sympy as _sp
            has_frac = ("/" in L2 + R2) or bool(re.search(
                r"(sqrt|sin|cos|tan|log|ln|exp|abs|floor|ceil)\(", L2 + R2))
            if has_frac:
                d = _sp.simplify(a - b)
                if d == 0:
                    return "pass", ""
                if d.is_number and d != 0:
                    return "fail", f"左式实际值应为 {_sp.simplify(a)}"
                return "unknown", ""
            d = _sp.expand(a - b)
            if d == 0:
                return "pass", ""
            # 整式差非 0：确定性不恒等 → fail（语义化说明供反馈）
            if d.free_symbols:
                return "fail", f"两侧展开后相差 {_sp.simplify(d)}，并非恒等"
            return "fail", f"左式实际值应为 {_sp.simplify(a)}"
        except Exception:  # noqa: BLE001
            return "unknown", ""

    def _check_assert_verify(self, ctx: TaskContext, result: str) -> str:
        """<check> 协议验证入口，返回反馈文本（空=通过/无断言/放行）。"""
        if not getattr(self.config, "enable_numeric_lean_verify", False):
            return ""
        if ctx.gen_time_up():
            return ""
        meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        cnt = int(meta.get("numeric_lean_count", 0) or 0)
        cap = max(1, int(getattr(self.config, "lean_numeric_max_per_q", 2) or 2))
        if cnt >= cap:
            return ""
        pairs = self._extract_check_asserts(result)
        if not pairs:
            return ""
        fails = []                                 # (L, R, 说明)
        for L, R in pairs:
            v, info = self._sympy_judge(L, R)
            if v == "fail":
                fails.append((L, R, info))
        if not fails:
            return ""
        # Lean 背书（只对疑似错的断言编译，双确认防 sympy 边缘误报）
        confirmed = self._lean_backup_fails(fails)
        if not confirmed:
            return ""
        meta["numeric_lean_count"] = cnt + 1
        lines = []
        for L, R, info in confirmed:
            if info:
                lines.append(f"断言「{L} = {R}」不成立（{info}）")
            else:
                lines.append(f"断言「{L} = {R}」不成立（两侧并不恒等）")
        return ("【计算断言未通过验证】你声明的等式未通过客观验证（SymPy 精确"
                "判定 + Lean 编译器双重确认），请修正该步计算后重新给出【本步"
                "结果】：" + "；".join(lines) + "。")

    # P4（2026-09-09 老师"描述即完成/零代码"）：疑似错断言 → 生成**多条策略
    # 尝试**声明（norm_num/norm_num1/ring/ring_nf/nlinarith/omega/grind/aesop
    # 按形态选择），一次编译，组内任一策略闭合 → 剔除（防 sympy 误报）；
    # 组内全部失败 → 双确认该断言不成立。
    _SYNTAX_ERR_KW = ("unknown identifier", "unexpected token",
                      "unknown constant", "invalid")

    def _build_auto_proof(self, fails: list):
        """为疑似错断言构建多策略 Lean 声明（P4）。

        返回 (code_lines, group_of)：group_of[i] = fails[i] 各策略声明行号；
        形态不支持（含除号的变量式/超 3 变量）→ 该断言无组（调用方宁放行）。
        num = 纯数值（ℚ norm_num 系 + ring）；poly = 无除号整式（ℤ 策略族）。
        """
        try:
            from tools.lean_local.lean_bridge import _mathlib_import_block
        except Exception:  # noqa: BLE001
            return None
        code_lines = [ln for ln in _mathlib_import_block().split("\n")]
        if code_lines and code_lines[-1].strip():
            code_lines.append("")
        group_of: dict = {}
        for i, _it in enumerate(fails):
            L, R = str(_it[0]), str(_it[1])
            Lx, Rx = self._fix_lean_mul(L), self._fix_lean_mul(R)
            vars_ = sorted(set(re.findall(r"[a-zA-Z]", L + R)))
            if not vars_:
                head = f"example : ({Lx} : ℚ) = ({Rx} : ℚ)"
                decls = ["by norm_num", "by norm_num1", "by ring"]
            elif "/" not in (L + R) and len(vars_) <= 3:
                binds = " ".join(f"({v} : ℤ)" for v in vars_)
                head = f"example {binds} : {Lx} = {Rx}"
                decls = ["by ring", "by ring_nf", "by nlinarith",
                         "by omega", "by grind", "by aesop"]
            else:
                continue                       # Lean 无法背书 → 宁放行
            lines = []
            for d in decls:
                code_lines.append(f"{head} := {d}")
                lines.append(len(code_lines))
            group_of[i] = lines
        if not group_of:
            return None
        return code_lines, group_of

    def _lean_backup_fails(self, fails: list) -> list:
        """对疑似错的断言做 Lean 多策略编译背书（P4 自动证明链）。

        返回双确认的 (L, R, info) 子集；组内任一策略闭合（该行无 error）
        → 剔除（防 sympy 误报）；组内全部策略失败（每行均有 error）→ 确认
        不成立。Lean 不可用/文件级错误/断言含语法不支持记号 → 宁放行不反馈。
        """
        try:
            from tools.lean_local.lean_bridge import LeanBridge
            from tools.lean_local.lean_bridge import _trash_lean_file
            built = self._build_auto_proof(fails)
            if not built:
                return []
            code_lines, group_of = built
            bridge = LeanBridge(self.client, self.config)
            if not bridge.lean_available:
                return []
            work_dir = bridge._lean_project_dir or ""
            if not work_dir:
                return []
            code = "\n".join(code_lines)
            fname = (f"sgcheck_{os.getpid()}_"
                     f"{int(time.time() * 1000) % 1000000}.lean")
            try:
                r = bridge._compile(code, work_dir, lean_filename=fname,
                                    allow_sorry=True)
            finally:
                try:
                    _trash_lean_file(work_dir, fname)
                except Exception:  # noqa: BLE001
                    pass
            if not r or r.get("ok"):
                return []                            # 全部通过 → sympy 误报
            err_text = str(r.get("error", ""))
            first_decl = min(v[0] for v in group_of.values())
            msg_of_line = {}
            for m in re.finditer(
                    r":(\d+):(\d+):\s*error:\s*([^\n]*)", err_text):
                line = int(m.group(1))
                if line not in msg_of_line:
                    msg_of_line[line] = m.group(3).strip()
            if msg_of_line and min(msg_of_line) < first_decl:
                return []                            # import/文件级 → 环境问题
            confirmed = []
            for i, lines in group_of.items():
                errs = [msg_of_line[ln] for ln in lines if ln in msg_of_line]
                if len(errs) < len(lines):
                    continue                         # ≥1 策略闭合 → sympy 误报
                if any(any(k in e for k in self._SYNTAX_ERR_KW)
                       for e in errs):
                    continue                         # 语法类失败 → 不可信，放行
                confirmed.append(fails[i])
            return confirmed
        except Exception:  # noqa: BLE001  异常一律放行（不误报）
            return []


    # ---------- ③ 子目标交叉核对（2026-09-08 老师建议3）----------
    # 老师建议："子目标交叉核对机制"——不同子目标对同一量给出互相矛盾的结论
    # 时，系统要能发现并打回，而不是让矛盾静默流入最终合并（如 alg-060 型）。
    # 落地两方向（独立开关，可单开/同开做 A/B）：
    #   A 确定性冲突闸（0 LLM，subgoal_conflict_gate）：
    #     汇总全题子目标结果里的 <calc> 回填（[计算] X = v）+ <check> 协议断言
    #     + L2 已提取等式断言，同名单变量 LHS 出现**可判定不同的常数**值
    #     （x=1 vs x=2）→ 判显式矛盾，merge 提示词强制裁决后才许合并。
    #     已知盲区：隐含矛盾（alg-060：xy=25 与 D=2 不共用同一变量名，纯规则
    #     必漏）；非单变量 LHS（x^2=4 含 ± 分支）、近似舍入差异 → 宁漏勿误报。
    #   B LLM 交叉核对轮（merge 前 +1 次小调用，subgoal_crosscheck_llm）：
    #     把各子目标结论行单独抽出交给 LLM 集中裁决矛盾——能看隐含矛盾
    #     （alg-060 这型有机会看出，不保证）。预算不足自动跳过，不阻断 merge。
    _LHS_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    # 行内 [计算] 回填（允许前缀自然语言，如 "解得 [计算] x = 1"）：
    # RHS 截断到行尾或中英文句读/分号，防吞掉后续文字。
    _CALC_INLINE_RE = re.compile(
        r"\[计算\]\s*([^=\n，。；;,]+?)\s*=\s*([^\n，。；;,]+)")
    # 松散 ident = const 片段（纯文本结论 "解得 x = 1"）：前 2 个非空字符
    # 命中情形/条件标记（当/若/情形/情况/分支…）→ 跳过，防分支讨论误报。
    _LOOSE_EQ_RE = re.compile(
        r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s，。；;,+)(]+)")
    _CASE_MARK = set("当若情形况分")

    @staticmethod
    def _lookback_case_mark(text: str, pos: int) -> bool:
        """LHS 前 2 个非空白字符是否含情形/条件标记（当/若/情形…）。"""
        i = pos - 1
        n = 0
        while i >= 0 and n < 2:
            ch = text[i]
            if not ch.isspace():
                if ch in SubGoalSolverAgent._CASE_MARK:
                    return True
                n += 1
            i -= 1
        return False

    def _collect_claims(self, result: str) -> list:
        """从子目标结果汇总确定性等式断言 [(L, R)]（去重）。

        四来源并集：①<calc> 回填落地行/行内 `[计算] X = v`
        （resolve_all_calcs 格式，允许自然语言前缀）；②<check>…=…</check>
        协议块（L3）；③L2 提取式等式断言（_extract_lean_assert_pairs，
        宁缺毋滥）；④松散 `X = 常数` 文本片段（"解得 x = 1"），带情形/
        条件标记（当/若/情形…）的前缀跳过，防分支讨论误报。合并去重。
        """
        pairs: list = []
        if not result:
            return pairs
        text = str(result)
        for m in self._CALC_INLINE_RE.finditer(text):
            L = m.group(1).strip().rstrip("= ")
            R = m.group(2).strip()
            if L and R:
                pairs.append((L, R))
        for L, R in self._extract_check_asserts(text):
            pairs.append((L, R))
        for L, R, *_rest in self._extract_lean_assert_pairs(text):
            pairs.append((L, R))
        # 松散源只在**不含** [计算]/<check> 标记的行上跑（避免与专用源重复，
        # 且函数调用形 RHS（sqrt(…)）会在左括号处被截断成假断言）。
        for ln in text.split("\n"):
            if "[计算]" in ln or "<check>" in ln:
                continue
            for m in self._LOOSE_EQ_RE.finditer(ln):
                if self._lookback_case_mark(ln, m.start()):
                    continue
                L, R = m.group(1).strip(), m.group(2).strip()
                if L and R:
                    pairs.append((L, R))
        seen, uniq = set(), []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    @staticmethod
    def _rhs_const(s: str):
        """RHS 解析为常数则返回 sympy 值对象，否则 None（变量式/不可解析）。

        符号化字符串（`^`/`**` 幂、分数、根式）交给 sympy；带自由符号或
        解析失败 → None（不做常量比较，宁漏勿误报）。
        """
        try:
            from utils.sympy_tools import _try_parse
        except Exception:  # noqa: BLE001
            return None
        try:
            a, _ = _try_parse(s.replace("^", "**"))
        except Exception:  # noqa: BLE001
            return None
        if a is None:
            return None
        try:
            if getattr(a, "free_symbols", None):
                return None
        except Exception:  # noqa: BLE001
            return None
        return a

    def _cross_conflicts(self, subgoals: list[dict],
                         results_map: dict[int, str]) -> list:
        """确定性冲突闸（0 LLM）：同名单变量被给出不同常数 → 返回矛盾清单。

        判同值用 sympy 精确差化简（0.5 与 1/2、3*sqrt(5) 与 sqrt(45) 视为
        同值不报警）；同值不同写法不误报。返回人类可读行（空=无冲突）。
        """
        try:
            import sympy as _sp
        except Exception:  # noqa: BLE001
            return []
        claims: list = []
        for sg in subgoals:
            sid = sg.get("id")
            text = (results_map.get(sid) or sg.get("result") or "")
            for L, R in self._collect_claims(text):
                claims.append((sid, L, R))
        if not claims:
            return []
        var_map: dict = {}          # LHS规范化名 -> [(sid, 值对象, R原文)]
        for sid, L, R in claims:
            Lc = re.sub(r"\s+", "", str(L))
            if not self._LHS_IDENT_RE.match(Lc):
                continue            # 复合 LHS（x^2 / x+1 / S(1)…）不做常量冲突判定
            v = self._rhs_const(str(R))
            if v is None:
                continue
            var_map.setdefault(Lc, []).append((sid, v, str(R).strip()))
        conflicts: list = []
        for Lc, lst in var_map.items():
            groups: list = []       # 值分组（sympy 差化简判同）
            for sid, v, Rs in lst:
                for g in groups:
                    try:
                        if _sp.simplify(g[0][1] - v) == 0:
                            g.append((sid, v, Rs))
                            break
                    except Exception:  # noqa: BLE001  化简失败按不同值处理（宁报）
                        pass
                else:
                    groups.append([(sid, v, Rs)])
            if len(groups) < 2:
                continue
            # 只报**跨子目标**冲突：同一步内对同一量出现多值多为分支枚举
            # （"x=1 或 x=2"）或自我修正，不构成本机制目标（merge 自带矛盾
            # 检查兜底）；跨子目标对同一量的不同常数才是真正流毒信号。
            for g in groups:
                g.sort(key=lambda t: (str(t[0]), len(t[2])))
            base = min(groups, key=lambda g: (str(g[0][0]), len(g[0][2])))
            base_sid, _b_v, b_r0 = base[0]
            other = None
            for g in groups:
                if g is base:
                    continue
                cand = [t for t in g if t[0] != base_sid]
                if cand:
                    other = cand[0]
                    break
            if other is None:
                continue            # 所有不同取值都出自同一子目标 → 不报
            o_sid, _o_v, o_r = other
            conflicts.append(
                f"「{Lc}」在子目标 #{base_sid} 中取 {b_r0}，"
                f"而在子目标 #{o_sid} 中取 {o_r}——同一变量不能同时成立，"
                "必有至少一方错误（含推导/抄写错误），需裁决修正")
        return conflicts[:6]          # 单次最多报 6 条，防提示词膨胀

    def _llm_crosscheck(self, ctx: TaskContext, subgoals: list[dict],
                        results_map: dict[int, str],
                        plan_summary: str) -> str:
        """LLM 交叉核对轮：merge 前 +1 次小调用，返回矛盾裁决报告。

        只裁决矛盾（不求解/不合并/不给答案）；调用失败或预算不足返回空串
        （空串=未跑/无输出，由调用方与"未发现矛盾"区分）。~1-2K token。
        """
        if ctx.gen_time_up():
            return ""
        concl_lines = []
        for sg in subgoals:
            sid = sg.get("id")
            text = (results_map.get(sid) or sg.get("result") or "")
            text = re.sub(r"\s+", " ", str(text)).strip()
            if not text:
                continue
            title = re.sub(r"\s+", " ", str(sg.get("title") or "")).strip()
            concl_lines.append(f"# 子目标 {sid}"
                               + (f"「{title}」" if title else "")
                               + f"：{text[:200]}")
        if not concl_lines:
            return ""
        user_msg = SUBGOAL_CROSSCHECK_USER_TEMPLATE.format(
            problem=(str(getattr(ctx, "problem", "") or "")[:800]),
            subgoal_plan_summary=(str(plan_summary or "")[:600]),
            subgoal_conclusions="\n".join(concl_lines),
        )
        try:
            t0 = time.time()
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system",
                         "content": SUBGOAL_CROSSCHECK_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    "【矛盾列表】",
                ),
                0.0, 2048,
            )
            if resp:
                resp = stitch("【矛盾列表】", resp)
            self.record(ctx, "subgoal_crosscheck",
                        f"LLM 交叉核对轮耗时 {time.time() - t0:.0f}s"
                        + ("" if resp else "，返回空（不注入矛盾提示）"))
            return resp or ""
        except Exception as exc:  # noqa: BLE001  失败不阻断 merge
            logger.debug("LLM 交叉核对轮异常（跳过）: %s: %s",
                         type(exc).__name__, exc)
            return ""


    # ---------- 阶段三：合并 ----------
    def _merge_results(self, ctx: TaskContext, subgoals: list[dict],
                       plan_summary: str, results_map: dict[int, str],
                       merge_strategy: str) -> str:
        """调用 LLM 合并所有子目标结果。

        2026-09-04 calc 纪律下沉：合并阶段若需汇总计算（各子目标结果代入/
        化简求值），同样强制 <calc> 标记并由系统回填，杜绝 merge 心算错。
        2026-09-08 改进建议3+6：①蓝图最终结论注入 user 模板（merge 输出
        必须与蓝图结论对齐，防 alg-009/053/068 输出端数值漂移）；②merge 产出
        空转/占位/平凡 calc 回填（如 [计算] 0 = 0）时带反馈重试一次（alg-009
        merge 计划 = "[计算]0=0" 仍照常入候选的教训）。
        2026-09-08 老师建议3 交叉核对：merge 前先跑子目标交叉核对
        （A 确定性冲突闸 0-LLM + B LLM 交叉核对轮 +1 调用，各自独立开关），
        发现的矛盾强制注入 merge 提示词要求逐条裁决——不让子目标间矛盾
        静默流入最终合并（alg-060 型显式/隐含矛盾）。
        """
        all_results = self._format_all_results(results_map, subgoals)
        # 蓝图最终结论（root 节点 statement）：取 ctx.blueprint，兼容 dict/list 两种形态
        blueprint_conclusion = self._blueprint_conclusion(ctx)
        # 2026-09-12 客观题特化（三处同源注入之③：merge 合并）——merge 直接产出
        # 最终答案署名候选，特化纪律必须在这里也在场，否则"检测到了"却"没照做"。
        _obj_inj_m = ""
        try:
            from .question_type import objective_injection as _oi_m
            _obj_inj_m = _oi_m(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            _obj_inj_m = ""
        # 2026-09-13 B0：答案形态要求必须在 merge 阶段也在场（merge 直接产出最终答案）
        try:
            from .question_type import answer_form_requirement as _afr_m
            _obj_inj_m += _afr_m(
                ctx.problem or "", getattr(ctx, "question_type", "") or "")
        except Exception:  # noqa: BLE001
            pass
        user_msg = SUBGOAL_MERGE_USER_TEMPLATE.format(
            problem=(ctx.problem or "") + _obj_inj_m,
            subgoal_plan_summary=plan_summary,
            blueprint_conclusion=blueprint_conclusion,
            all_results=all_results,
            merge_strategy=merge_strategy or "将各子目标结果按逻辑顺序组合，得出原题的最终答案。",
        )
        # ③ 子目标交叉核对（2026-09-08 老师建议3）：合并前先核对，矛盾强制
        # 注入提示词要求逐条裁决（A 0-LLM 确定性冲突闸 + B LLM 交叉核对轮）。
        # 二者独立开关可单开/同开 A/B；任何一步失败/预算不足都不阻断 merge。
        conflict_note = ""
        try:
            enable_gate = bool(getattr(
                self.config, "subgoal_conflict_gate", False))
            enable_xllm = bool(getattr(
                self.config, "subgoal_crosscheck_llm", False))
            if enable_gate or enable_xllm:
                parts = []
                if enable_gate:
                    cfl = self._cross_conflicts(subgoals, results_map)
                    if cfl:
                        parts.append(
                            "【确定性冲突闸】系统自动核对各子目标对同一变量"
                            "的取值，发现以下显式矛盾（同名 LHS 出现不同常数"
                            "值，数学上不可能同时成立）：\n"
                            + "\n".join("  - " + c for c in cfl))
                        self.record(
                            ctx, "subgoal_crosscheck",
                            f"确定性冲突闸: 发现 {len(cfl)} 处同名不同值矛盾")
                    else:
                        self.record(
                            ctx, "subgoal_crosscheck",
                            "确定性冲突闸: 未发现显式矛盾")
                if enable_xllm:
                    rep = self._llm_crosscheck(
                        ctx, subgoals, results_map, plan_summary)
                    if rep and rep.strip():
                        # 剥掉"未发现矛盾"类措辞后仍有实质内容 → 视为报了
                        # 矛盾（防"除上述外未发现矛盾"混合措辞漏注入）
                        _resid = re.sub(
                            r"未发现(?:明显|任何)?矛盾|无矛盾|没有矛盾",
                            "", rep, flags=re.IGNORECASE)
                        if len(_resid.strip()) <= 40:
                            self.record(
                                ctx, "subgoal_crosscheck",
                                "LLM 交叉核对轮: 未发现矛盾")
                        else:
                            parts.append(
                                "【LLM 交叉核对】独立评审轮对各子目标结论的"
                                "矛盾裁决报告：\n" + rep.strip()[:800])
                            self.record(
                                ctx, "subgoal_crosscheck",
                                f"LLM 交叉核对轮: 报告潜在矛盾"
                                f"（{rep.strip()[:80]!r}）")
                if parts:
                    conflict_note = (
                        "\n\n【⚠ 系统交叉核对结果（最高优先级，必须先处理）】"
                        "合并前已发现子目标结论间存在潜在矛盾。你必须在"
                        "【矛盾检查】中**逐条裁决**：指出冲突双方各自的主张、"
                        "依据原题条件与 <calc> 数值复核判定哪一方错误、给出"
                        "修正后的取值；若实为不同对象/不同分支并不冲突，请"
                        "逐条说明理由。**禁止不处理矛盾就直接输出【最终答案】"
                        "。**\n" + "\n".join(parts))
        except Exception as exc:  # noqa: BLE001  交叉核对失败不阻断 merge
            logger.debug("子目标交叉核对异常（跳过）: %s: %s",
                         type(exc).__name__, exc)
        if conflict_note:
            user_msg = user_msg + conflict_note
        _merge_system = SUBGOAL_MERGE_SYSTEM
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            _merge_system = SUBGOAL_MERGE_SYSTEM + _CALC_GUIDE
            # 方案 A：各子目标结果（all_results）里已回填的 [计算] 精确值汇总前置，
            # 合并阶段直接引用（扫不到则空串，不注入）。
            # 方案 B：并上生成前预计算的值（ctx.calc_prewarm_block）。
            _merge_system = _merge_system + _calc_results_block(
                all_results, getattr(ctx, "calc_prewarm_block", None))

        for attempt in range(2):
            # v2.4.1：prefill「【最终答案】」答案前置，抑制 CoT
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": _merge_system},
                        {"role": "user", "content": user_msg},
                    ],
                    "【最终答案】",
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch("【最终答案】", resp)
            if resp is None:
                if attempt == 0:
                    self.record(ctx, "subgoal_merge",
                                "合并 LLM 调用失败，带反馈重试一次")
                    user_msg = user_msg + (
                        "\n\n[上一轮合并未返回有效文本] 请完整输出"
                        "【矛盾检查】【结论合并】【最终答案】。")
                    continue
                return self._fallback_from_last_subgoal(subgoals)

            # 2026-09-04 calc_tool 回填（先于答案提取，与 solver/_call_step 同序）
            if (resolve_all_calcs is not None
                    and getattr(self.config, 'enable_calc_tool', True)):
                resp, _resolved = resolve_all_calcs(resp)
                # P1-2（2026-09-09）：merge 内工具失败审计留痕（WARN:/ERROR:）
                self.record_calc_successes(ctx, _resolved)
                if audit_calc_fallbacks is not None:
                    for _ex, _rs in audit_calc_fallbacks(_resolved):
                        self.record(ctx, "calc_fallback",
                                    f"<calc>{_ex}</calc> → {_rs}",
                                    expr=_ex, reason=_rs)
                # P1-1（2026-09-09，calc_mandatory）：回填后仍有裸数值断言
                # （心算痕迹）→ 打回重写一次（attempt 0 限定，防死循环）
                if (attempt == 0
                        and find_naked_numeric_asserts is not None
                        and getattr(self.config, "calc_mandatory", True)):
                    _naked = find_naked_numeric_asserts(resp)
                    if _naked:
                        self.record(
                            ctx, "subgoal_merge",
                            f"merge 含未用 <calc> 的易错运算（{_naked[0][:50]}），"
                            "打回重试")
                        user_msg = user_msg + (
                            "\n\n[上一轮合并含未用 <calc> 的**易错运算**结果："
                            f"{_naked[0][:80]}]\n该类运算（开方/根式、对数、组合数/"
                            "阶乘、幂运算、自然常数 e 等）必须用 <calc> 标记由系统"
                            "回填精确结果，禁止心算；简单加减乘除可自算。"
                            "请改写后重新合并输出。")
                        continue

            # 优先提取「最终答案」
            answer = extract_final_answer(resp)
            if answer:
                # 2026-09-08：merge 空转（占位词 / [计算] X = X 平凡回填）→
                # 不允许带着空转结论入候选，带反馈重试一次
                if self._looks_placeholder(answer):
                    if attempt == 0:
                        self.record(
                            ctx, "subgoal_merge",
                            f"合并输出为空转/占位（{answer[:60]}），带反馈重试")
                        user_msg = user_msg + (
                            f"\n\n[上一轮合并输出为空转：{answer[:120]}]\n"
                            "你没有真正合并各子目标结果。请：①逐条做矛盾检查；"
                            "②基于各子目标结果与蓝图结论真实推导；"
                            "③用 <calc> 完成汇总计算后在【最终答案】给出结论。")
                        continue
                    return self._fallback_from_last_subgoal(subgoals)
                return answer
            if attempt == 0:
                self.record(ctx, "subgoal_merge",
                            "合并未提取到【最终答案】，带反馈重试一次")
                user_msg = user_msg + (
                    "\n\n[上一轮未找到【最终答案】段] 请在末尾用【最终答案】"
                    "明确给出结论（一个数值/表达式/集合），不要只给过程。")
                continue
            return smart_fallback_answer(resp) or self._fallback_from_last_subgoal(subgoals)
        return self._fallback_from_last_subgoal(subgoals)

    @staticmethod
    def _blueprint_conclusion(ctx: TaskContext) -> str:
        """从 ctx.blueprint 提取 root 节点结论文本（供 merge 输出对齐）。

        兼容 dict（{root_id, nodes}) 与 list（nodes 为 [ {...} ]）两种形态；
        提取失败返回占位文本（不阻断 merge）。
        """
        try:
            bp = getattr(ctx, "blueprint", None)
            if not bp:
                return "（无——按题目与子目标规划合并）"
            if not isinstance(bp, dict):
                return "（无——按题目与子目标规划合并）"
            root_id = bp.get("root_id") or ""
            nodes = bp.get("nodes") or []
            if isinstance(nodes, dict):
                node = nodes.get(root_id) if root_id else None
            else:  # list 形态：[{"id":..., "statement":...}, ...]
                node = None
                for n in nodes:
                    if isinstance(n, dict) and n.get("id") == root_id:
                        node = n
                        break
            stmt = (node or {}).get("statement") if isinstance(node, dict) else ""
            if stmt and str(stmt).strip():
                return str(stmt).strip()[:400]
            return "（蓝图无显式最终结论——按题目与子目标规划合并）"
        except Exception:  # noqa: BLE001  提取失败不阻断 merge
            return "（无——按题目与子目标规划合并）"

    # ---------- 辅助方法 ----------
    @staticmethod
    def _subgoal_stats(subgoals: list[dict]) -> dict:
        """S4-lite 独立性指标（老师 9/6：减少子目标数、降低上下文依赖）。

        返回 n_subgoals / dep_edges（依赖边总数）/ avg_indegree（平均入度，
        越小独立性越高，0 = 全独立）/ dep_free（零依赖子目标数）。
        进 diag 供 A/B 对照（S2 deps 模式是否真降了上下文与依赖）。
        """
        n = len(subgoals)
        edges = sum(len(sg.get("depends_on") or []) for sg in subgoals)
        dep_free = sum(
            0 if (sg.get("depends_on") or []) else 1 for sg in subgoals)
        return {
            "n_subgoals": n,
            "dep_edges": edges,
            "avg_indegree": round(edges / n, 2) if n else 0.0,
            "dep_free": dep_free,
        }

    @staticmethod
    def _format_plan_summary(subgoals: list[dict], merge_strategy: str) -> str:
        """格式化子目标规划摘要（用于后续步骤提示）"""
        lines = []
        for sg in subgoals:
            deps = f"依赖: {sg['depends_on']}" if sg["depends_on"] else "无依赖"
            lines.append(
                f"  #{sg['id']} [{sg['type']}] {sg['title']}"
                f"  → {sg['description']} ({deps})"
            )
        if merge_strategy:
            lines.append(f"\n合并策略: {merge_strategy}")
        return "\n".join(lines)

    @staticmethod
    def _format_previous_results(results_map: dict[int, str],
                                 subgoals: list[dict]) -> str:
        """格式化已求解的子目标结果（全量前序，subgoal_ctx_mode="all" 时用）"""
        if not results_map:
            return "（尚无前置结果）"
        lines = []
        for sg in subgoals:
            if sg["id"] in results_map:
                lines.append(f"  子目标 #{sg['id']}「{sg['title']}」结果: {results_map[sg['id']]}")
        return "\n".join(lines) if lines else "（尚无前置结果）"

    @staticmethod
    def _format_dep_results(results_map: dict[int, str],
                            subgoals: list[dict], sg: dict) -> str:
        """按 depends_on 只注入**直接依赖**的结果（老师 9/6 建议：子目标独立性、
        最小上下文依赖）。无依赖 / 依赖未解出 → 返回空串（零前序上下文），
        让独立子目标可并行、不被无关中间量污染。id 缺失容错：依赖未解出跳过。

        与 _format_previous_results 的区别：后者把**所有**已解子目标都塞进
        提示词（O(n²) 上下文膨胀）；本函数只带声明依赖的少数几条。
        """
        deps = [d for d in (sg.get("depends_on") or []) if d in results_map]
        if not deps:
            return ""
        title_map = {s.get("id"): (s.get("title") or "") for s in subgoals}
        lines = []
        for d in deps:
            _txt = str(results_map[d])
            _title = title_map.get(d, "")
            # 2026-09-14 P1：**切断"基准污染"链**。
            # 实测 #098 的基准子目标违规吐 `\boxed{D}`；而 #103 的「判定选项 E」
            # 直接输出 `\boxed{ABCD}`（照抄了基准的答案形态）⇒ 聚合层认不出 E。
            # 故：基准结果里若出现 `\boxed{...}`，注入下游**前**剥离外壳并加显式告警。
            if "基准" in _title and "\\boxed" in _txt:
                _txt = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", _txt)
                _txt = ("（⚠ 本基准曾误输出最终答案，其 `\\boxed` 外壳已被系统剥离；"
                        "请只把它当作**判断依据**，**不要照抄**为任何选项的答案）"
                        + _txt)
            lines.append(f"  子目标 #{d}「{_title}」结果: {_txt}")
        # 2026-09-14 P1：**依赖未产出时的降级**（实测 #110）。
        # #110 的基准子目标求解失败 ⇒ 注入字符数 = 0 ⇒ 依赖它的选项子目标
        # 拿到空上下文、整个判定链断掉（gold A / 模型 D）。
        # 故：声明的依赖**全部未解出**时不再返回空串，而是显式告知下游
        # "共享依据缺失，请独立完成"，避免静默断链。
        _declared = [d for d in (sg.get("depends_on") or [])]
        if _declared and not deps:
            _names = "、".join(
                "#{}「{}」".format(d, title_map.get(d, "")) for d in _declared)
            return ("  （⚠ 前置子目标 {} **未能产出有效结果**，本次无法提供共享依据；"
                    "请**基于题目本身独立完成**本步判定，"
                    "不要因缺少依据而放弃或空转）").format(_names)
        return "\n".join(lines)

    # 选项判定结论解析（2026-09-14 实测 #103/#107/#110 暴露的问题）。
    # 模型**经常不遵守**"开头写『结论：正确/错误』"的格式，实际输出的形态包括：
    #   「结论：正确 依据：…」/「选项 D：正确」/「X = Y」（等价判断，暗示正确）/
    #   直接复述基准（**无任何结论**）。
    # 聚合层若不能识别，就会**丢项**（#103 丢 E）或**误采纳**（#107 判 D 对却输出 C）。
    _VERDICT_PATTERNS = (
        (re.compile(r"结论\s*[:：]\s*(正确|成立|符合|是正确|对的)"), "正确"),
        (re.compile(r"结论\s*[:：]\s*(错误|不成立|不符合|不正确|是错)"), "错误"),
        (re.compile(r"选项\s*[A-E]\s*[:：]\s*(正确|成立|符合)"), "正确"),
        (re.compile(r"选项\s*[A-E]\s*[:：]\s*(错误|不成立|不符合)"), "错误"),
        (re.compile(r"^\s*(正确|成立|符合)\s*$", re.M), "正确"),
        (re.compile(r"^\s*(错误|不成立|不符合)\s*$", re.M), "错误"),
    )

    @classmethod
    def _extract_option_verdict(cls, text: str):
        """从选项子目标的结果里解析出「正确 / 错误」；解析不到返回 None。

        按**优先级**匹配（先"结论："和"选项X："这类强信号，再退到独立词）。
        解析不到 ⇒ 调用方应显式标注"判定缺失"，让合并层单独复核，
        **不得**默认当作"跳过"（那正是 #103 丢 E 的机制）。
        """
        t = str(text or "")
        if not t:
            return None
        # 先看强信号（"结论：" / "选项X："）
        for pat, verdict in cls._VERDICT_PATTERNS[:4]:
            if pat.search(t):
                return verdict
        # 再退到独立词（但同一结果里两种都有 ⇒ 歧义，返回 None）
        has_ok = bool(cls._VERDICT_PATTERNS[4][0].search(t))
        has_no = bool(cls._VERDICT_PATTERNS[5][0].search(t))
        if has_ok and not has_no:
            return "正确"
        if has_no and not has_ok:
            return "错误"
        return None

    @staticmethod
    def _format_all_results(results_map: dict[int, str],
                            subgoals: list[dict]) -> str:
        """格式化所有子目标结果"""
        lines = []
        for sg in subgoals:
            result = results_map.get(sg["id"], "（未求解）")
            _title = str(sg.get("title") or "")
            _txt = str(result)
            # 2026-09-14：聚合层不再依赖模型的格式自觉（实测 #103/#107/#110）——
            # 对「判定选项 X」子目标**解析结论并结构化前置**，使合并层无需理解
            # 自由文本即可汇总；解析不到则显式标注"判定缺失，需单独复核"。
            _m = re.match(r"^判定选项\s*([A-E])\s*$", _title.strip())
            if _m:
                _lab = _m.group(1)
                _v = SubGoalSolverAgent._extract_option_verdict(_txt)
                if _v:
                    _txt = "【系统解析：选项 {} = {}】{}".format(_lab, _v, _txt[:400])
                else:
                    _txt = (
                        "（⚠ 本步**未给出明确结论** —— 既无『结论：正确/错误』"
                        "也无『选项{}：正确/错误』，原文：{}；"
                        "合并时请**单独复核选项 {}**，"
                        "**不得**因其格式不规范而默认排除）"
                    ).format(_lab, _txt[:200], _lab)
            lines.append(f"子目标 #{sg['id']}「{_title}」: {_txt}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_from_last_subgoal(subgoals: list[dict]) -> str:
        """兜底：使用最后一个成功求解的子目标结果"""
        for sg in reversed(subgoals):
            if sg.get("result"):
                return sg["result"]
        return "无法求解"

    @staticmethod
    def _build_full_reasoning(subgoals: list[dict],
                              problem_analysis: dict,
                              final_answer: str) -> str:
        """构建完整的推理过程文本（用于展示和回溯）"""
        lines = ["# 子目标分解求解过程\n"]
        if problem_analysis:
            lines.append(f"## 问题分析\n领域: {problem_analysis.get('domain', 'N/A')}")
            lines.append(f"目标: {problem_analysis.get('core_objective', 'N/A')}\n")
        lines.append("## 子目标规划")
        for sg in subgoals:
            lines.append(f"  #{sg['id']} [{sg['type']}] {sg['title']}: {sg['description']}")
        lines.append("\n## 逐步求解")
        for sg in subgoals:
            lines.append(f"\n### 子目标 #{sg['id']}「{sg['title']}」")
            lines.append(f"结果: {sg.get('result', '未求解')}")
        lines.append(f"\n## 最终答案\n{final_answer}")
        return "\n".join(lines)
