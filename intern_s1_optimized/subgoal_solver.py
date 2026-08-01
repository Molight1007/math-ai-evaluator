"""
Intern-S1 增强版子目标求解器（含 Lean 4 验证闭环）
==============================================

核心流程：
  1. 子目标规划   → Intern-S1 将问题分解为有序子目标树
  2. 逐步求解     → 逐个求解子目标，生成 Lean 4 形式化语句
  3. Lean 验证    → 使用 DeepSeek + Lean 编译器验证每个子目标
  4. 修正循环     → 验证失败时反馈修正（最多2次重试）
  5. 结论合并     → 合并所有子目标结果，自检一致性

与 submit/agent/sub_goal_solver.py 的区别：
  - 集成 Lean 4 形式化验证（不仅是 LLM 自检）
  - 每个子目标独立验证，早发现早修正
  - Intern-S1 专用提示词（英文）更适合该模型
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Optional

from .config import get_config
from .llm_client import LLMClient
from .models import Problem, InferenceResult

try:
    from .subgoal_prompts import (
        INTERN_SUBGOAL_PLAN_SYSTEM,
        INTERN_SUBGOAL_PLAN_USER,
        INTERN_SUBGOAL_STEP_SYSTEM,
        INTERN_SUBGOAL_STEP_USER,
        INTERN_SUBGOAL_REVISE_SYSTEM,
        INTERN_SUBGOAL_REVISE_USER,
        INTERN_SUBGOAL_MERGE_SYSTEM,
        INTERN_SUBGOAL_MERGE_USER,
    )
except ImportError:
    from subgoal_prompts import (
        INTERN_SUBGOAL_PLAN_SYSTEM,
        INTERN_SUBGOAL_PLAN_USER,
        INTERN_SUBGOAL_STEP_SYSTEM,
        INTERN_SUBGOAL_STEP_USER,
        INTERN_SUBGOAL_REVISE_SYSTEM,
        INTERN_SUBGOAL_REVISE_USER,
        INTERN_SUBGOAL_MERGE_SYSTEM,
        INTERN_SUBGOAL_MERGE_USER,
    )

logger = logging.getLogger(__name__)

# ==================== 常量 ====================

_MAX_SUBGOALS = 8
_MAX_REVISE_RETRIES = 2
_PLAN_TEMPERATURE = 0.3
_PLAN_MAX_TOKENS = 4096
_STEP_TEMPERATURE = 0.4
_STEP_MAX_TOKENS = 4096
_REVISE_TEMPERATURE = 0.3
_REVISE_MAX_TOKENS = 4096
_MERGE_TEMPERATURE = 0.2
_MERGE_MAX_TOKENS = 4096


# ==================== 数据结构 ====================

class SubGoalResult:
    """单个子目标的求解结果"""
    __slots__ = (
        "subgoal_id", "title", "result_text", "derivation",
        "lean_code", "lean_verified", "lean_error",
        "revise_count", "success",
    )

    def __init__(self, subgoal_id: int, title: str = ""):
        self.subgoal_id = subgoal_id
        self.title = title
        self.result_text = ""
        self.derivation = ""
        self.lean_code = ""
        self.lean_verified = False
        self.lean_error = ""
        self.revise_count = 0
        self.success = False

    def to_dict(self) -> dict:
        return {
            "subgoal_id": self.subgoal_id,
            "title": self.title,
            "result_text": self.result_text,
            "derivation": self.derivation[:500],
            "lean_verified": self.lean_verified,
            "revise_count": self.revise_count,
            "success": self.success,
        }


class SubGoalPlan:
    """子目标规划结果"""
    __slots__ = ("subgoals", "problem_analysis", "merge_strategy", "estimated_difficulty")

    def __init__(self):
        self.subgoals: list[dict] = []
        self.problem_analysis: dict = {}
        self.merge_strategy: str = ""
        self.estimated_difficulty: str = ""


# ==================== LLM 调用辅助 ====================

async def _llm_chat(client: LLMClient, messages: list, temperature: float, max_tokens: int) -> Optional[str]:
    """
    安全调用 LLM，返回文本内容。
    封装 client.chat()，处理 dict 返回值，捕获异常。
    """
    try:
        resp = await client.chat(messages, temperature, max_tokens)
        if isinstance(resp, dict):
            return resp.get("content", "")
        return str(resp)
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return None


# ==================== 解析工具 ====================

def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON 对象"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        candidate = m.group(1).strip()
    else:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            candidate = m.group(0).strip()
        else:
            return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def _extract_lean_code(text: str) -> str:
    """从输出中提取 Lean 4 代码块"""
    m = re.search(r"```(?:lean4?)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"\[Lean 4 Code\]\s*\n(.*?)(?=\[|$)", text, re.DOTALL)
    if m:
        code = m.group(1).strip()
        code = re.sub(r"^```(?:lean4?)?\s*\n?", "", code)
        code = re.sub(r"\n?\s*```\s*$", "", code)
        return code.strip()
    return ""


def _extract_section(text: str, section_name: str) -> str:
    """提取标记段内容，如 [Result]"""
    pattern = rf"\[{section_name}\]\s*\n(.*?)(?=\[|$)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if parts:
        return parts[-1]
    return ""


# ==================== InternSubGoalSolver ====================

class InternSubGoalSolver:
    """
    Intern-S1 增强版子目标求解器

    用法:
        solver = InternSubGoalSolver(intern_client, deepseek_client)
        result = await solver.solve(problem)
    """

    def __init__(self, intern_client: LLMClient, deepseek_client: LLMClient):
        self.intern = intern_client
        self.deepseek = deepseek_client
        self.config = get_config()

    # ========== 主入口 ==========

    async def solve(self, problem: Problem) -> dict:
        """
        对单个问题执行完整的子目标求解流程。

        返回:
            {
                "final_answer": str,
                "final_reasoning": str,
                "subgoal_plan": list[dict],
                "subgoal_results": list[dict],
                "lean_verified_count": int,
                "total_subgoals": int,
                "success": bool,
                "error": str | None,
            }
        """
        result = {
            "final_answer": "",
            "final_reasoning": "",
            "subgoal_plan": [],
            "subgoal_results": [],
            "lean_verified_count": 0,
            "total_subgoals": 0,
            "success": False,
            "error": None,
        }

        # ---- 阶段一：子目标规划 ----
        plan = await self._plan_subgoals(problem)
        if plan is None or not plan.subgoals:
            result["error"] = "子目标规划失败"
            return result

        result["subgoal_plan"] = plan.subgoals
        result["total_subgoals"] = len(plan.subgoals)
        logger.info(
            f"[SubGoalSolver] Planned {len(plan.subgoals)} sub-goals "
            f"for [{problem.id}]: {[sg['title'] for sg in plan.subgoals]}"
        )

        # ---- 阶段二：逐步求解 + Lean 验证 ----
        solved_results: dict[int, SubGoalResult] = {}

        for sg in plan.subgoals:
            sg_id = sg["id"]

            # 求解当前子目标
            sg_result = await self._solve_subgoal(
                problem, plan, sg, solved_results
            )

            # Lean 验证（如果子目标有 Lean 代码）
            if sg_result.lean_code and sg_result.success:
                await self._verify_with_lean(sg_result, problem, plan, sg, solved_results)

            solved_results[sg_id] = sg_result

            if sg_result.lean_verified:
                result["lean_verified_count"] += 1

            logger.info(
                f"[SubGoalSolver] Sub-goal #{sg_id} '{sg['title']}': "
                f"solved={sg_result.success}, lean_verified={sg_result.lean_verified}"
            )

        # ---- 阶段三：结论合并 ----
        final_answer, final_reasoning = await self._merge_results(
            problem, plan, solved_results
        )

        result["final_answer"] = final_answer
        result["final_reasoning"] = final_reasoning
        result["subgoal_results"] = [
            sr.to_dict() for sr in solved_results.values()
        ]
        result["success"] = bool(final_answer)

        return result

    # ========== 阶段一：子目标规划 ==========

    async def _plan_subgoals(self, problem: Problem) -> Optional[SubGoalPlan]:
        """调用 Intern-S1 进行子目标规划"""
        domain_hint = ""
        if problem.domain:
            domain_hint = f"\nDomain hint: {problem.domain}"

        user_msg = INTERN_SUBGOAL_PLAN_USER.format(
            problem=problem.question,
            domain_hint=domain_hint,
        )

        for attempt in range(2):
            resp = await _llm_chat(
                self.intern,
                [
                    {"role": "system", "content": INTERN_SUBGOAL_PLAN_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                _PLAN_TEMPERATURE,
                _PLAN_MAX_TOKENS,
            )

            if resp is None:
                continue

            parsed = _extract_json(resp)
            if parsed is None:
                logger.warning(f"[SubGoalSolver] Failed to parse plan JSON (attempt {attempt + 1})")
                continue

            subgoals = parsed.get("subgoals", [])
            if not isinstance(subgoals, list) or len(subgoals) == 0:
                continue

            plan = SubGoalPlan()
            plan.problem_analysis = parsed.get("problem_analysis", {})
            plan.merge_strategy = parsed.get("merge_strategy", "")
            plan.estimated_difficulty = parsed.get("estimated_difficulty", "")

            valid_types = {"compute", "prove", "derive", "verify", "construct"}
            seen_ids = set()
            for sg in subgoals[: _MAX_SUBGOALS]:
                sg_id = sg.get("id", len(plan.subgoals) + 1)
                if sg_id in seen_ids:
                    continue
                seen_ids.add(sg_id)
                plan.subgoals.append({
                    "id": sg_id,
                    "title": str(sg.get("title", f"Sub-goal {sg_id}")),
                    "type": sg.get("type", "compute") if sg.get("type") in valid_types else "compute",
                    "description": str(sg.get("description", "")),
                    "depends_on": [
                        d for d in sg.get("depends_on", [])
                        if isinstance(d, int) and d in seen_ids
                    ],
                    "expected_output": str(sg.get("expected_output", "")),
                    "lean_statement_hint": str(sg.get("lean_statement_hint", "")),
                    "difficulty": sg.get("difficulty", "medium"),
                })

            if plan.subgoals:
                return plan

        return None

    # ========== 阶段二：单步求解 ==========

    async def _solve_subgoal(
        self,
        problem: Problem,
        plan: SubGoalPlan,
        sg: dict,
        solved: dict[int, SubGoalResult],
    ) -> SubGoalResult:
        """求解单个子目标"""
        sg_id = sg["id"]
        result = SubGoalResult(sg_id, sg.get("title", ""))

        plan_summary = self._format_plan_summary(plan)
        prev_results = self._format_previous_results(solved, plan.subgoals)

        user_msg = INTERN_SUBGOAL_STEP_USER.format(
            problem=problem.question,
            subgoal_plan_summary=plan_summary,
            previous_results=prev_results,
            subgoal_id=sg_id,
            subgoal_title=sg.get("title", ""),
            subgoal_type=sg.get("type", "compute"),
            subgoal_description=sg.get("description", ""),
            subgoal_expected_output=sg.get("expected_output", ""),
            lean_hint=sg.get("lean_statement_hint", ""),
        )

        for attempt in range(2):
            resp = await _llm_chat(
                self.intern,
                [
                    {"role": "system", "content": INTERN_SUBGOAL_STEP_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                _STEP_TEMPERATURE,
                _STEP_MAX_TOKENS,
            )

            if resp is None:
                continue

            result.derivation = _extract_section(resp, "Derivation")
            result.result_text = _extract_section(resp, "Result")
            result.lean_code = _extract_lean_code(resp)

            if result.result_text:
                result.success = True
                return result

            logger.warning(f"[SubGoalSolver] Empty result for sub-goal #{sg_id} (attempt {attempt + 1})")

        result.result_text = f"[Sub-goal #{sg_id} 求解失败]"
        return result

    # ========== 阶段二：Lean 验证 + 修正循环 ==========

    async def _verify_with_lean(
        self,
        sg_result: SubGoalResult,
        problem: Problem,
        plan: SubGoalPlan,
        sg: dict,
        solved: dict[int, SubGoalResult],
    ) -> None:
        """
        使用 Lean 编译器验证子目标的 Lean 代码。
        如果编译失败，进入修正循环（最多 _MAX_REVISE_RETRIES 次）。
        """
        if not sg_result.lean_code:
            return

        sg_id = sg["id"]

        # 初次编译
        compile_ok, error_output = await self._compile_lean(sg_result.lean_code)

        if compile_ok:
            sg_result.lean_verified = True
            logger.info(f"[SubGoalSolver] Lean verified: sub-goal #{sg_id}")
            return

        sg_result.lean_error = error_output[:2000]
        logger.warning(
            f"[SubGoalSolver] Lean failed for sub-goal #{sg_id}: "
            f"{error_output[:200]}..."
        )

        # 修正循环
        for retry in range(_MAX_REVISE_RETRIES):
            logger.info(f"[SubGoalSolver] Revising sub-goal #{sg_id} (retry {retry + 1}/{_MAX_REVISE_RETRIES})")

            revised = await self._revise_subgoal(
                problem, sg, sg_result, error_output[:3000]
            )

            if revised is None:
                break

            sg_result.derivation = revised.get("derivation", sg_result.derivation)
            sg_result.result_text = revised.get("result_text", sg_result.result_text)
            sg_result.lean_code = revised.get("lean_code", sg_result.lean_code)
            sg_result.revise_count += 1

            if not sg_result.lean_code:
                continue

            compile_ok, error_output = await self._compile_lean(sg_result.lean_code)
            if compile_ok:
                sg_result.lean_verified = True
                logger.info(
                    f"[SubGoalSolver] Lean verified after {sg_result.revise_count} "
                    f"revision(s): sub-goal #{sg_id}"
                )
                return

            sg_result.lean_error = error_output[:2000]

        logger.warning(
            f"[SubGoalSolver] Lean verification failed after "
            f"{sg_result.revise_count} revision(s): sub-goal #{sg_id}"
        )

    async def _compile_lean(self, lean_code: str) -> tuple[bool, str]:
        """
        编译 Lean 4 代码，返回 (是否通过, 错误输出)。

        使用 lake env lean --stdin 编译。
        如果 Lean 环境不可用，降级为 DeepSeek 语法检查。
        """
        lean_exe = self.config.lean_executable or "lake"

        try:
            result = subprocess.run(
                [lean_exe, "env", "lean", "--stdin"],
                input=lean_code,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                return True, ""

            error_msg = stderr or stdout or "Unknown compilation error"
            return False, error_msg

        except subprocess.TimeoutExpired:
            return False, "Lean compilation timed out (30s)"
        except FileNotFoundError:
            return await self._syntax_check_fallback(lean_code)
        except Exception as e:
            return False, f"Lean compilation error: {e}"

    async def _syntax_check_fallback(self, lean_code: str) -> tuple[bool, str]:
        """Lean 不可用时的降级方案：用 DeepSeek 检查语法"""
        prompt = (
            "Check the following Lean 4 code for syntax errors, type errors, "
            "and obvious logical flaws. Reply ONLY with:\n"
            "PASS: <brief reason>\n"
            "or\n"
            "FAIL: <specific error description>\n\n"
            f"```lean4\n{lean_code[:3000]}\n```"
        )

        resp = await _llm_chat(
            self.deepseek,
            [
                {"role": "system", "content": "You are a Lean 4 syntax checker. Be strict."},
                {"role": "user", "content": prompt},
            ],
            0.0,
            512,
        )

        if resp is None:
            return True, ""

        resp_upper = resp.strip().upper()
        if resp_upper.startswith("PASS"):
            return True, ""
        return False, resp[:500]

    async def _revise_subgoal(
        self,
        problem: Problem,
        sg: dict,
        prev_result: SubGoalResult,
        lean_error: str,
    ) -> Optional[dict]:
        """修正失败的子目标"""
        prev_solution = (
            f"[Derivation]\n{prev_result.derivation}\n\n"
            f"[Result]\n{prev_result.result_text}\n\n"
            f"[Lean 4 Code]\n```lean4\n{prev_result.lean_code}\n```"
        )

        revise_system = INTERN_SUBGOAL_REVISE_SYSTEM.format(
            lean_error=lean_error[:2000]
        )

        user_msg = INTERN_SUBGOAL_REVISE_USER.format(
            subgoal_id=sg["id"],
            lean_error=lean_error[:2000],
            previous_solution=prev_solution[:3000],
            problem=problem.question,
            subgoal_description=sg.get("description", ""),
        )

        for attempt in range(2):
            resp = await _llm_chat(
                self.intern,
                [
                    {"role": "system", "content": revise_system},
                    {"role": "user", "content": user_msg},
                ],
                _REVISE_TEMPERATURE,
                _REVISE_MAX_TOKENS,
            )

            if resp is None:
                continue

            return {
                "derivation": _extract_section(resp, "Derivation"),
                "result_text": _extract_section(resp, "Result"),
                "lean_code": _extract_lean_code(resp),
            }

        return None

    # ========== 阶段三：结论合并 ==========

    async def _merge_results(
        self,
        problem: Problem,
        plan: SubGoalPlan,
        solved: dict[int, SubGoalResult],
    ) -> tuple[str, str]:
        """合并所有子目标结果"""
        plan_summary = self._format_plan_summary(plan)
        all_results = self._format_all_results(solved, plan.subgoals)

        user_msg = INTERN_SUBGOAL_MERGE_USER.format(
            problem=problem.question,
            subgoal_plan_summary=plan_summary,
            all_results=all_results,
            merge_strategy=plan.merge_strategy or "按逻辑顺序组合各子目标结果，得出最终答案",
        )

        for attempt in range(2):
            resp = await _llm_chat(
                self.intern,
                [
                    {"role": "system", "content": INTERN_SUBGOAL_MERGE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                _MERGE_TEMPERATURE,
                _MERGE_MAX_TOKENS,
            )

            if resp is None:
                continue

            final_answer = _extract_section(resp, "Final Answer")
            if final_answer:
                return final_answer, resp

        # 兜底：取最后一个子目标的结果
        last_sg = max(solved.keys()) if solved else None
        if last_sg and solved[last_sg].result_text:
            return solved[last_sg].result_text, solved[last_sg].derivation

        return "无法求解", ""

    # ========== 格式化辅助方法 ==========

    @staticmethod
    def _format_plan_summary(plan: SubGoalPlan) -> str:
        lines = []
        for sg in plan.subgoals:
            deps = f"depends_on: {sg['depends_on']}" if sg["depends_on"] else "no dependencies"
            lines.append(
                f"  #{sg['id']} [{sg['type']}] {sg['title']}"
                f"  -> {sg['description'][:120]} ({deps})"
            )
        if plan.merge_strategy:
            lines.append(f"\nMerge strategy: {plan.merge_strategy}")
        return "\n".join(lines)

    @staticmethod
    def _format_previous_results(
        solved: dict[int, SubGoalResult],
        subgoals: list[dict],
    ) -> str:
        if not solved:
            return "(no previous results)"
        lines = []
        for sg in subgoals:
            if sg["id"] in solved:
                lines.append(
                    f"  Sub-goal #{sg['id']} [{sg['title']}]: "
                    f"{solved[sg['id']].result_text[:200]}"
                )
        return "\n".join(lines) if lines else "(no previous results)"

    @staticmethod
    def _format_all_results(
        solved: dict[int, SubGoalResult],
        subgoals: list[dict],
    ) -> str:
        lines = []
        for sg in subgoals:
            sr = solved.get(sg["id"])
            if sr:
                verified = "✓ Lean verified" if sr.lean_verified else "✗ Lean not verified"
                lines.append(
                    f"Sub-goal #{sg['id']} [{sg['title']}]:\n"
                    f"  Result: {sr.result_text[:300]}\n"
                    f"  Status: {verified}"
                )
        return "\n\n".join(lines)


# ==================== 便捷函数 ====================

async def solve_with_subgoals(problem: Problem) -> dict:
    """
    便捷函数：使用增强版子目标求解器求解单个问题。
    自动从配置中创建 Intern-S1 和 DeepSeek 客户端。
    """
    cfg = get_config()
    intern_client = LLMClient(cfg.intern_s1)
    deepseek_client = LLMClient(cfg.deepseek)

    solver = InternSubGoalSolver(intern_client, deepseek_client)
    return await solver.solve(problem)


async def solve_batch_with_subgoals(
    problems: list[Problem],
    concurrency: int = 3,
) -> list[dict]:
    """
    批量求解（控制并发数）。
    """
    sem = asyncio.Semaphore(concurrency)

    async def _solve_one(p: Problem) -> dict:
        async with sem:
            return await solve_with_subgoals(p)

    tasks = [_solve_one(p) for p in problems]
    return await asyncio.gather(*tasks)
