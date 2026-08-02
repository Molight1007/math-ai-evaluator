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

        for sg in subgoals:
            if not ctx.budget.can_spend(2):
                self.record(ctx, "subgoal", f"预算不足，跳过剩余子目标 (当前={sg['id']}/{len(subgoals)})")
                break

            prev_results = self._format_previous_results(results_map, subgoals)
            step_result = self._solve_subgoal(ctx, sg, subgoal_plan_summary, prev_results)
            results_map[sg["id"]] = step_result
            sg["result"] = step_result

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
            resp = self.llm(
                ctx,
                [
                    {"role": "system", "content": SUBGOAL_PLAN_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                0.2, 4096,
            )
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

        resp = self.llm(
            ctx,
            [
                {"role": "system", "content": SUBGOAL_STEP_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.2, 4096,
        )
        if resp is None:
            return f"[子目标 #{sg['id']} 求解失败]"

        # 提取「本步结果」部分
        result_match = re.search(r"【本步结果】\s*\n?(.*?)(?:$|【)", resp, re.DOTALL)
        if result_match:
            return result_match.group(1).strip()
        # 如果没有标记，取最后 500 字符
        return resp.strip()[-500:]

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

        resp = self.llm(
            ctx,
            [
                {"role": "system", "content": SUBGOAL_MERGE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.2, 4096,
        )
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
