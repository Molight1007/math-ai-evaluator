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
    )
    from submit.prompts.policy import get_domain_hint
    from submit.utils.extract import extract_final_answer, smart_fallback_answer
    from submit.utils.prefill import prefill_messages, stitch

# calc_tool（2026-09-04 下沉）：与 Solver 主链同款确定性计算器。
# 子目标步骤/合并原先完全靠模型心算（无 <calc> 纪律、无回填），
# 是数值错的高发且无防线处。此处导入与 solver.py:39-45 同构。
try:
    from .calc_tool import resolve_all_calcs
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from calc_tool import resolve_all_calcs
    except ImportError:
        resolve_all_calcs = None

logger = logging.getLogger("MathPilot")

# 计算纪律引导（与 solver._CALC_GUIDE 同文案，2026-09-04 下沉子目标/合并）。
# 追加到 STEP/MERGE 的 system 提示词（不追加 user 末尾——v2.10 教训：
# 收尾结构后追加会诱发模型"续写模式"）。
_CALC_GUIDE = (
    "\n\n计算环节请用 <calc>表达式</calc> 标记（例如 <calc>comb(50,3)*2**10</calc>、"
    "<calc>1/2+1/3</calc>、<calc>3*7-1</calc>），系统会自动精确求值并回填结果。"
    "涉及数值计算时务必使用该标记，不要心算。\n"
    "**<calc> 与 </calc> 之间必须且只能是纯数学表达式**"
    "（数字、+ - * / ** % //、括号、函数 comb/perm/fact/gcd/lcm/abs），"
    "禁止出现任何中文、文字解释、句号或换行——出现非表达式字符会直接导致计算失败。"
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

        self.record(ctx, "subgoal", f"子目标规划完成: {len(subgoals)} 个子目标",
                    subgoal_titles=[sg["title"] for sg in subgoals],
                    merge_strategy=merge_strategy)

        # 阶段二：逐步求解每个子目标
        subgoal_plan_summary = self._format_plan_summary(subgoals, merge_strategy)
        results_map = {}  # subgoal_id → result_text

        for sg in subgoals:
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

            prev_results = self._format_previous_results(results_map, subgoals)
            step_result = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results)
            # 2026-09-02 老师方案 B：蓝图评审 OK 但子目标失败 → 重做子目标
            # （不重画蓝图）。一次失败常是瞬时 LLM 错误/预算抖动，带已解
            # 子目标上下文重试一次；仍失败才记为占位（留给外层占位符兜底）。
            # 2026-09-04 阶段预算：重试 = 一次完整 LLM 轮（60-110s），
            # 阶段预算剩余不足时不再重试（省下的时间留给 merge 收尾）。
            if step_result.startswith("[子目标") and _stage_left() > 120:
                self.record(ctx, "subgoal",
                            f"子目标 #{sg['id']}「{sg['title']}」失败，带上下文重试一次")
                prev_results2 = self._format_previous_results(results_map, subgoals)
                retry = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results2)
                if retry and not retry.startswith("[子目标"):
                    step_result = retry
            elif step_result.startswith("[子目标") and _stage_left() <= 120:
                self.record(ctx, "subgoal",
                            f"子目标 #{sg['id']}「{sg['title']}」失败，"
                            f"阶段预算剩余 {_stage_left():.0f}s 不足，放弃重试，强制收尾")
            results_map[sg["id"]] = step_result
            sg["result"] = step_result
            # v2.9：结构化输出每步子目标的过程与中间结果
            ctx.subgoal_trace.append({
                "id": sg["id"],
                "title": sg["title"],
                "description": sg["description"],
                "type": sg["type"],
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
        self.record(ctx, "subgoal", "子目标求解完成，已生成候选解答")
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
            if not ctx.budget or not True:
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
        self.record(ctx, "dag_replan",
                    f"达到重生成硬上限 {replan_rounds} 轮，停止")
        return True

    # ---------- 阶段一：规划 ----------
    def _plan_subgoals(self, ctx: TaskContext) -> dict | None:
        """调用 LLM 生成子目标规划 JSON"""
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

    # ---------- 阶段二：逐步求解 ----------
    def _solve_subgoal(self, ctx: TaskContext, sg: dict,
                       plan_summary: str, prev_results: str) -> str:
        """求解单个子目标，返回结果文本。

        v2.7：计算类子目标（compute/derive）求解后用 AnswerOracle 做客观
        sanity check，若结果明显非法（不可解析为数学表达式），带反馈重解一次，
        实现"每步 oracle 校验"（Plan-and-Execute + oracle-in-the-loop）。

        v2.10（2026-08-29）：use_lemma_accumulation 开启时，把已求得的
        引理列表注入子目标提示词（"已建立的结论"），让后续子目标直接复用，
        避免重复推导（D6 引理积累钥匙的真正落地点）。
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

        user_msg = SUBGOAL_STEP_USER_TEMPLATE.format(
            problem=ctx.problem,
            subgoal_plan_summary=plan_summary,
            previous_results=prev_results,
            lemma_context=lemma_context,
            subgoal_id=sg["id"],
            subgoal_title=sg["title"],
            subgoal_type=sg["type"],
            subgoal_description=sg["description"],
            subgoal_expected_output=sg["expected_output"],
        )

        step_result = self._call_step(ctx, user_msg)

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
                retry_result = self._call_step(ctx, retry_msg)
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

    def _call_step(self, ctx: TaskContext, user_msg: str) -> str:
        """单步子目标求解调用（prefill「【本步结果】」答案前置，抑制 CoT）。

        2026-09-04 calc 纪律下沉：system 追加 <calc> 计算引导（与 solver 主链
        同款），响应回填 <calc> 块为精确值——子目标步骤不再靠模型心算。
        """
        _step_system = SUBGOAL_STEP_SYSTEM
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            _step_system = SUBGOAL_STEP_SYSTEM + _CALC_GUIDE
        resp = self.llm(
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
            resp = resolve_all_calcs(resp)[0]

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

    # ---------- 阶段三：合并 ----------
    def _merge_results(self, ctx: TaskContext, subgoals: list[dict],
                       plan_summary: str, results_map: dict[int, str],
                       merge_strategy: str) -> str:
        """调用 LLM 合并所有子目标结果。

        2026-09-04 calc 纪律下沉：合并阶段若需汇总计算（各子目标结果代入/
        化简求值），同样强制 <calc> 标记并由系统回填，杜绝 merge 心算错。
        """
        all_results = self._format_all_results(results_map, subgoals)
        user_msg = SUBGOAL_MERGE_USER_TEMPLATE.format(
            problem=ctx.problem,
            subgoal_plan_summary=plan_summary,
            all_results=all_results,
            merge_strategy=merge_strategy or "将各子目标结果按逻辑顺序组合，得出原题的最终答案。",
        )
        _merge_system = SUBGOAL_MERGE_SYSTEM
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            _merge_system = SUBGOAL_MERGE_SYSTEM + _CALC_GUIDE

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
            return self._fallback_from_last_subgoal(subgoals)

        # 2026-09-04 calc_tool 回填（先于答案提取，与 solver/_call_step 同序）
        if (resolve_all_calcs is not None
                and getattr(self.config, 'enable_calc_tool', True)):
            resp = resolve_all_calcs(resp)[0]

        # 优先提取「最终答案」
        answer = extract_final_answer(resp)
        if answer:
            return answer
        return smart_fallback_answer(resp) or self._fallback_from_last_subgoal(subgoals)

    # ---------- 辅助方法 ----------
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
        """格式化已求解的子目标结果"""
        if not results_map:
            return "（尚无前置结果）"
        lines = []
        for sg in subgoals:
            if sg["id"] in results_map:
                lines.append(f"  子目标 #{sg['id']}「{sg['title']}」结果: {results_map[sg['id']]}")
        return "\n".join(lines) if lines else "（尚无前置结果）"

    @staticmethod
    def _format_all_results(results_map: dict[int, str],
                            subgoals: list[dict]) -> str:
        """格式化所有子目标结果"""
        lines = []
        for sg in subgoals:
            result = results_map.get(sg["id"], "（未求解）")
            lines.append(f"子目标 #{sg['id']}「{sg['title']}」: {result}")
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
