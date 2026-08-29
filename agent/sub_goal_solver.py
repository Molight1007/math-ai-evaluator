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

logger = logging.getLogger("MathPilot")


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
    def _parse_subgoal_plan(raw: dict) -> list[dict] | None:
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
        if len(subgoals) > 10:
            subgoals = subgoals[:10]  # 安全上限

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
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            self.record(ctx, "subgoal", "预算耗尽，跳过子目标求解")
            return ctx

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
            if not ctx.budget.can_spend(2):
                self.record(ctx, "subgoal", f"预算不足，跳过剩余子目标 (当前={sg['id']}/{len(subgoals)})")
                break

            prev_results = self._format_previous_results(results_map, subgoals)
            step_result = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results)
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
            if getattr(self.config, 'use_lemma_accumulation', False):
                self._accumulate_lemma(ctx, sg, step_result)

            self.record(ctx, "subgoal_step",
                       f"子目标 #{sg['id']}「{sg['title']}」求解完成: {step_result[:80]}")
            time.sleep(0.2)  # 速率限制间隔

        # 阶段三：结论合并
        if not ctx.budget.can_spend(1):
            self.record(ctx, "subgoal", "预算不足，跳过合并阶段")
            # 使用最后一个子目标的结果作为最终答案
            final_answer = self._fallback_from_last_subgoal(subgoals)
        else:
            final_answer = self._merge_results(ctx, subgoals, subgoal_plan_summary,
                                               results_map, merge_strategy)

        # v2.9：结构化输出最终整合方案
        ctx.subgoal_merge_plan = (
            f"合并策略: {merge_strategy or '将各子目标结果按逻辑顺序组合'}\n"
            f"最终答案: {final_answer}"
        )

        # 构造 Candidate
        full_reasoning = self._build_full_reasoning(subgoals, problem_analysis, final_answer)
        candidate = Candidate(
            id=len(ctx.candidates),
            answer=final_answer,
            reasoning=full_reasoning,
            revised=False,
        )
        ctx.candidates.append(candidate)
        self.record(ctx, "subgoal", "子目标求解完成，已生成候选解答")
        return ctx

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
        # v2.9：前置形式化验证通过后，把题目的形式化描述注入规划提示，
        # 帮助书生准确理解题意后再做子目标分解。
        problem_text = ctx.problem
        if getattr(ctx, "formal_spec", ""):
            problem_text = (ctx.problem + "\n\n[题目的形式化理解（已知条件→结论）]\n"
                            + ctx.formal_spec)
        # v2.9+：把 Lean 形式化编译发现的「缺口」注入规划提示，
        # 让 AI 优先把"缺失的定义/引理/模块/类型问题"拆成子目标
        # （即"根据 Lean 编译的逻辑，看缺哪些" → 帮助构建子目标）。
        gaps = getattr(ctx, "formal_gaps", [])
        if gaps:
            gap_lines = "\n".join(
                "  - [%s] %s: %s" % (g.get("kind", "other"), g.get("detail", ""),
                                     g.get("suggestion", ""))
                for g in gaps)
            problem_text = (problem_text
                            + "\n\n[Lean 形式化验证发现的缺口（建议优先作为子目标拆解）]\n"
                            + gap_lines)

        # #31 leansearch 试用：把与题目相关的 Mathlib 定理检索后注入规划提示，
        # 供书生在分解/证明子目标时参考（默认关闭，由 use_leansearch 启用）。
        if getattr(self.config, "use_leansearch", False):
            sr = self._search_mathlib_theorems(ctx, problem_text)
            if sr and sr.get("status") == "ok" and sr.get("results"):
                th_lines = "\n".join(
                    "  - %s (%s): %s" % (r["name"], r.get("kind", "?"),
                                         (r.get("snippet", "") or "")[:120])
                    for r in sr["results"])
                problem_text = (problem_text
                                + "\n\n[检索到的相关 Mathlib 定理（leansearch 试用，"
                                  "供子目标分解/证明参考）]\n" + th_lines)

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
                0.2, 2048,
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
            subgoals = self._parse_subgoal_plan(raw)
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
        plan = dag.to_subgoal_plan()
        if not plan.get("subgoals"):
            logger.warning("Blueprint DAG 无可用叶子子目标")
            return None
        # LEAP Stage 2（#26/#28）：生成 DAG 后做整树 Lean 搭桥审核（写 ctx.sketch_tree，
        # 供后续阶段消费；失败不阻断主流程）。仅当 Lean 前置验证启用时触发。
        if getattr(self.config, "enable_sketch_audit", True):
            self._audit_blueprint_tree(ctx, dag)
        self.record(ctx, "blueprint",
                    f"Blueprint DAG → {len(plan['subgoals'])} 个子目标 "
                    f"(根={dag.root_id}, 节点={len(dag.nodes)})")
        return plan

    def _audit_blueprint_tree(self, ctx: TaskContext, dag) -> None:
        """用 LeanTranslatorAgent 对 DAG 做整树翻译+审核（安全降级）。

        #32 迭代精炼：config.use_refiner 开启时，整树审核后再执行
        Stage 3 sorry 补全循环（含 OR 回溯 + lemma 记忆），结果写 ctx.refine_result。
        """
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            return
        try:
            from .lean_translator import LeanTranslatorAgent
            translator = LeanTranslatorAgent(self.client, self.config)
            result = translator.translate_and_audit(ctx, dag)
            ctx.sketch_tree = result
            self.record(ctx, "lean_translator",
                        f"Blueprint 整树审核: verdict={result.get('verdict')}; "
                        f"叶子={result.get('leaf_count')}, "
                        f"sorry={result.get('sorry_count')}")
            # 整树审核未通过 → 把缺口并入 formal_gaps，供下一轮子目标规划消费。
            # 此前 sketch_tree 只在 use_refiner=True 时被读（默认关），
            # 审核结论等于丢弃；并入 formal_gaps 可复用既有消费通路。
            if result.get("verdict") == "fail":
                gaps = [g for g in (result.get("gaps") or [])
                        if isinstance(g, dict) and g.get("detail")]
                if gaps:
                    existing = {g.get("detail") for g in ctx.formal_gaps}
                    added = 0
                    for g in gaps:
                        if g["detail"] not in existing:
                            ctx.formal_gaps.append(g)
                            existing.add(g["detail"])
                            added += 1
                    if added:
                        self.record(ctx, "blueprint_audit_reinject",
                                    f"整树审核未通过，{added} 条缺口并入 formal_gaps")
            # #32 Stage 3：sorry 迭代补全（可选开启）
            if getattr(self.config, "use_refiner", False):
                from .lean_refiner import LeanRefinerAgent
                refiner = LeanRefinerAgent(self.client, self.config)
                ctx.refine_result = refiner.refine_tree(ctx, dag, result)
                self.record(ctx, "lean_refiner",
                            f"Stage3 精炼: verdict={ctx.refine_result.get('verdict')}; "
                            f"done={ctx.refine_result.get('done')}, "
                            f"failed={ctx.refine_result.get('failed')}")
        except Exception as e:  # noqa: BLE001
            logger.warning("Blueprint 整树审核失败（降级）: %s", e)
            ctx.sketch_tree = {"verdict": "unknown", "error": str(e)[:200]}

    # ---------- leansearch 试用（#31）----------
    def _get_mathlib_searcher(self):
        """懒加载 MathlibTheoremSearcher（缓存于实例，避免重复扫描源码）。"""
        if getattr(self, "_mathlib_searcher", None) is None:
            try:
                from .lean_search import MathlibTheoremSearcher
                self._mathlib_searcher = MathlibTheoremSearcher()
            except Exception as e:  # noqa: BLE001
                logger.warning("MathlibTheoremSearcher 初始化失败: %s", e)
                self._mathlib_searcher = False  # 标记失败，避免重复尝试
        return self._mathlib_searcher or None

    def _search_mathlib_theorems(self, ctx: TaskContext, query: str, limit: int = 5):
        """试用 leansearch：检索与查询相关的 Mathlib 定理（安全降级返回 None）。"""
        searcher = self._get_mathlib_searcher()
        if searcher is None:
            return None
        try:
            return searcher.search(query, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.warning("Mathlib 定理检索失败: %s", e)
            return None

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
        if getattr(self.config, 'use_lemma_accumulation', False):
            lemmas = list(getattr(ctx, "lemma_repo", []) or [])
            if lemmas:
                lemma_block = "\n".join(f"- {l}" for l in lemmas[-8:])
                lemma_context = (
                    f"\n【已建立的结论（可直接引用，无需重新推导）】\n"
                    f"{lemma_block}\n")

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
        sg_type = sg.get("type", "compute")
        if (sg_type in ("compute", "derive")
                and step_result
                and not step_result.startswith("[子目标")):
            oracle_fb = self._oracle_check_step(step_result)
            if oracle_fb and ctx.budget is not None and ctx.budget.can_spend(1):
                retry_msg = user_msg + (
                    f"\n\n[上一步结果客观校验未通过] {oracle_fb}\n"
                    f"请修正错误后重新给出【本步结果】。"
                )
                retry_result = self._call_step(ctx, retry_msg)
                if retry_result and not retry_result.startswith("[子目标"):
                    return retry_result
        return step_result

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
        """单步子目标求解调用（prefill「【本步结果】」答案前置，抑制 CoT）。"""
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": SUBGOAL_STEP_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                "【本步结果】",
            ),
            0.2, 2048,
        )
        if resp:
            resp = stitch("【本步结果】", resp)
        if resp is None:
            return "[子目标求解失败]"

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
        except Exception:  # noqa: BLE001
            pass
        return ""

    # ---------- 阶段三：合并 ----------
    def _merge_results(self, ctx: TaskContext, subgoals: list[dict],
                       plan_summary: str, results_map: dict[int, str],
                       merge_strategy: str) -> str:
        """调用 LLM 合并所有子目标结果"""
        all_results = self._format_all_results(results_map, subgoals)
        user_msg = SUBGOAL_MERGE_USER_TEMPLATE.format(
            problem=ctx.problem,
            subgoal_plan_summary=plan_summary,
            all_results=all_results,
            merge_strategy=merge_strategy or "将各子目标结果按逻辑顺序组合，得出原题的最终答案。",
        )

        # v2.4.1：prefill「【最终答案】」答案前置，抑制 CoT
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": SUBGOAL_MERGE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                "【最终答案】",
            ),
            0.2, 2048,
        )
        if resp:
            resp = stitch("【最终答案】", resp)
        if resp is None:
            return self._fallback_from_last_subgoal(subgoals)

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
