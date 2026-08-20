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
        SUBGOAL_REVIEW_SYSTEM,
        SUBGOAL_REVIEW_USER_TEMPLATE,
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
        SUBGOAL_REVIEW_SYSTEM,
        SUBGOAL_REVIEW_USER_TEMPLATE,
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
        """从 LLM 输出中提取 JSON 对象（支持 ```json 代码块和纯 JSON）"""
        if not text:
            return None
        # 优先匹配 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            candidate = m.group(1).strip()
        else:
            # 尝试匹配 { ... } 的最外层
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                candidate = m.group(0).strip()
            else:
                return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 尝试修复常见错误：尾随逗号、单引号等
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                return json.loads(fixed)
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _parse_subgoal_plan(raw: dict) -> list[dict] | None:
        """验证并规范化子目标规划，返回按拓扑序排列的子目标列表"""
        subgoals = raw.get("subgoals", [])
        if not isinstance(subgoals, list) or len(subgoals) == 0:
            return None
        if len(subgoals) > 10:
            subgoals = subgoals[:10]  # 安全上限

        valid_types = {"compute", "prove", "derive", "verify"}
        seen_ids = set()
        parsed = []
        for sg in subgoals:
            sg_id = sg.get("id", len(parsed) + 1)
            if sg_id in seen_ids:
                continue
            seen_ids.add(sg_id)
            parsed.append({
                "id": sg_id,
                "title": str(sg.get("title", f"子目标{sg_id}")),
                "description": str(sg.get("description", "")),
                "type": sg.get("type", "compute") if sg.get("type") in valid_types else "compute",
                "depends_on": [d for d in sg.get("depends_on", []) if isinstance(d, int) and d in seen_ids],
                "expected_output": str(sg.get("expected_output", "")),
                "result": "",
            })
        return parsed if parsed else None

    # ---------- 主流程 ----------
    def run(self, ctx: TaskContext) -> TaskContext:
        """执行子目标规划 → 逐步求解 → 结论合并 全流程，结果追加到 ctx.candidates"""
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

        # 改造4：AND-OR DAG 递归深度上限（默认 2 层，受预算限制）
        # 硬性约束：改造 4 默认关闭，仅当 enable_dag_plan=True 时启用（失败回溯 + Reviewer 剪枝）
        enable_dag = bool(getattr(self.config, 'enable_dag_plan', False))
        max_depth = int(getattr(self.config, 'subgoal_max_depth', 2) or 2)

        for sg in subgoals:
            if not ctx.budget.can_spend(2):
                self.record(ctx, "subgoal", f"预算不足，跳过剩余子目标 (当前={sg['id']}/{len(subgoals)})")
                break

            prev_results = self._format_previous_results(results_map, subgoals)
            step_result = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results)

            # 改造4：子目标求解失败时，尝试递归分解（OR 节点回溯）——仅 enable_dag_plan 开启时
            if enable_dag and self._is_failed_result(step_result) and max_depth > 1:
                self.record(ctx, "subgoal_backtrack",
                            f"子目标 #{sg['id']} 求解失败，尝试递归分解（depth={max_depth}）")
                step_result = self._solve_with_backtrack(
                    ctx, sg, subgoal_plan_summary, prev_results, max_depth - 1)

            results_map[sg["id"]] = step_result
            sg["result"] = step_result

            self.record(ctx, "subgoal_step",
                       f"子目标 #{sg['id']}「{sg['title']}」求解完成: {step_result[:80]}")
            time.sleep(0.2)  # 速率限制间隔

        # 改造4：LLM Reviewer 过滤无前景子目标（LEAP 2.5），剪枝后更新结果
        # 改造4：LLM Reviewer 剪枝（LEAP 2.5）——仅 enable_dag_plan 开启时启用
        if enable_dag:
            subgoals = self._review_and_prune(ctx, subgoals, results_map)

        # 阶段三：结论合并
        if not ctx.budget.can_spend(1):
            self.record(ctx, "subgoal", "预算不足，跳过合并阶段")
            # 使用最后一个子目标的结果作为最终答案
            final_answer = self._fallback_from_last_subgoal(subgoals)
        else:
            final_answer = self._merge_results(ctx, subgoals, subgoal_plan_summary,
                                               results_map, merge_strategy)

        # 构造 Candidate
        full_reasoning = self._build_full_reasoning(subgoals, problem_analysis, final_answer)
        candidate = Candidate(
            id=len(ctx.candidates) + 1,
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
        domain = ctx.domain or ""
        domain_hint = get_domain_hint(domain) if domain else ""
        user_msg = SUBGOAL_PLAN_USER_TEMPLATE.format(
            domain_hint=domain_hint,
            problem=ctx.problem,
        )

        for attempt in range(2):
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

        self.record(ctx, "subgoal", "子目标规划两次尝试均失败")
        return None

    # ---------- 阶段二：逐步求解 ----------
    def _solve_subgoal(self, ctx: TaskContext, sg: dict,
                       plan_summary: str, prev_results: str) -> str:
        """求解单个子目标，返回结果文本"""
        user_msg = SUBGOAL_STEP_USER_TEMPLATE.format(
            problem=ctx.problem,
            subgoal_plan_summary=plan_summary,
            previous_results=prev_results,
            subgoal_id=sg["id"],
            subgoal_title=sg["title"],
            subgoal_type=sg["type"],
            subgoal_description=sg["description"],
            subgoal_expected_output=sg["expected_output"],
        )

        # v2.4.1：prefill「【本步结果】」让答案前置，抑制 CoT
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
            return f"[子目标 #{sg['id']} 求解失败]"

        # 提取「本步结果」部分
        result_match = re.search(r"【本步结果】\s*\n?(.*?)(?:$|【)", resp, re.DOTALL)
        if result_match:
            return result_match.group(1).strip()
        # 如果没有标记，取最后 500 字符
        return resp.strip()[-500:]

    # ---------- 改造4：AND-OR 回溯与 Reviewer 剪枝 ----------
    @staticmethod
    def _is_failed_result(result: str) -> bool:
        """判断子目标求解结果是否失败（空、含失败标记、或过短无实质内容）。"""
        if not result:
            return True
        if "求解失败" in result or "无法求解" in result or "无法解决" in result:
            return True
        if len(result.strip()) < 5:
            return True
        return False

    def _solve_with_backtrack(self, ctx: TaskContext, sg: dict,
                              plan_summary: str, prev_results: str,
                              depth: int) -> str:
        """OR 节点回溯：子目标直接求解失败时，递归分解成更小的子目标再求解。

        - AND 节点：原问题的分解（一次生成多个子目标）；
        - OR 节点：每个子目标有多条可选的更细分解路径，失败时尝试替代路径；
        - 深度受 ``depth``（预算/配置上限）约束，过深不再递归，直接返回失败。
        """
        if depth <= 0 or not ctx.budget.can_spend(2):
            return f"[子目标 #{sg['id']} 递归求解失败，已回溯]"
        # 把当前失败子目标当作一个小问题，尝试再次规划并求解（OR 替代路径）
        sub = self._plan_subgoal_again(ctx, sg)
        if sub is None:
            return f"[子目标 #{sg['id']} 无法进一步分解，已回溯]"
        # 递归求解更细子目标，取最后一个成功结果
        last = ""
        for i, mini in enumerate(sub):
            if not ctx.budget.can_spend(2):
                break
            prev = self._format_previous_results({}, [])
            r = self._solve_subgoal(ctx, mini, plan_summary, prev)
            if self._is_failed_result(r) and depth - 1 > 0:
                r = self._solve_with_backtrack(ctx, mini, plan_summary, prev, depth - 1)
            last = r if not self._is_failed_result(r) else last
        return last or f"[子目标 #{sg['id']} 回溯后仍失败]"

    def _plan_subgoal_again(self, ctx: TaskContext, sg: dict) -> list[dict] | None:
        """把单个失败子目标当作小问题重新规划（OR 节点替代分解路径）。"""
        domain = ctx.domain or ""
        domain_hint = get_domain_hint(domain) if domain else ""
        user_msg = SUBGOAL_PLAN_USER_TEMPLATE.format(
            domain_hint=domain_hint,
            problem=sg.get("description") or sg.get("title") or ctx.problem,
        )
        resp = self.llm(
            ctx,
            prefill_messages(
                [{"role": "system", "content": SUBGOAL_PLAN_SYSTEM},
                 {"role": "user", "content": user_msg}],
                '{"',
            ),
            0.2, 2048,
        )
        if resp:
            resp = stitch('{"', resp)
        raw = self._extract_json(resp) if resp else None
        if not raw:
            return None
        return self._parse_subgoal_plan(raw)

    def _review_subgoal(self, ctx: TaskContext, sg: dict) -> dict:
        """调用 LLM Reviewer 判断单个子目标是否有前景（LEAP 2.5）。"""
        user_msg = SUBGOAL_REVIEW_USER_TEMPLATE.format(
            problem=ctx.problem,
            subgoal_title=sg.get("title", ""),
            subgoal_description=sg.get("description", ""),
            subgoal_result=sg.get("result", "") or "（未求解）",
        )
        resp = self.llm(
            ctx,
            prefill_messages(
                [{"role": "system", "content": SUBGOAL_REVIEW_SYSTEM},
                 {"role": "user", "content": user_msg}],
                '{"',
            ),
            0.2, 1024,
        )
        if resp:
            resp = stitch('{"', resp)
        raw = self._extract_json(resp) if resp else None
        if raw is None:
            return {"keep": True, "reason": "review 失败，保守保留", "suggestion": ""}
        return {"keep": bool(raw.get("keep", True)),
                "reason": str(raw.get("reason", "")),
                "suggestion": str(raw.get("suggestion", ""))}

    def _review_and_prune(self, ctx: TaskContext, subgoals: list[dict],
                          results_map: dict) -> list[dict]:
        """对已求解子目标做 Reviewer 过滤，剪枝无前景子目标（LEAP 2.5）。

        若预算不足以逐个子目标 review，则整体跳过（保守兼容，不影响默认行为）。
        返回剪枝后的子目标列表。
        """
        if not subgoals:
            return subgoals
        # 预算不足时跳过 reviewer（保守兼容：默认不启用该增强开销）
        if not ctx.budget.can_spend(len(subgoals)):
            self.record(ctx, "subgoal_review", "预算不足，跳过 Reviewer 剪枝")
            return subgoals
        kept = []
        pruned = 0
        for sg in subgoals:
            verdict = self._review_subgoal(ctx, sg)
            if verdict.get("keep", True):
                # 有修正建议时，用建议覆盖 result 提示后续合并阶段
                if verdict.get("suggestion") and sg.get("result"):
                    sg["result"] = sg["result"] + f"\n[Reviewer 建议] {verdict['suggestion']}"
                kept.append(sg)
            else:
                pruned += 1
                self.record(ctx, "subgoal_prune",
                            f"子目标 #{sg['id']}「{sg['title']}」被 Reviewer 剪枝: {verdict.get('reason', '')}")
        if pruned:
            self.record(ctx, "subgoal_review",
                        f"Reviewer 过滤完成: 剪枝 {pruned} 个无前景子目标")
        return kept or subgoals  # 若全部被剪枝则保留原列表兜底

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
