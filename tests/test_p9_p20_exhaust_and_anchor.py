# -*- coding: utf-8 -*-
"""P-9 / P-20 回归测试（2026-09-17）。

覆盖：
  ① 穷尽性段落判据 **两处口径一致**：`sub_goal_solver._exhaust_missing_sections`
     与 `orchestrator._parse_exhaust_result` 必须给出相同结论，防止漂移
     （本仓库已有「口径不一」的历史教训，见 formatter 的 `_REFUSAL_RE` 注释）。
  ② 规划结论的「答案形态」剥离 `_strip_answer_forms`。
  ③ merge 模板必须携带「合并纪律」且可被 `.format()` 正确渲染
     （模板里出现裸花括号会直接抛 KeyError，属高危）。
"""

import pytest

from agent.sub_goal_solver import (
    _exhaust_missing_sections,
    _strip_answer_forms,
)


# ---------------------------------------------------------------- ①
FULL_OK = (
    "解族清单: 常数解 / 线性解 / 周期解\n"
    "逐族判定: 常数解 存在；线性解 存在；周期解 不存在（反证略）\n"
    "前序结论复核: 前序找到的解属线性解族，同族还有 a_n = n+1\n"
    "结论: EXHAUSTIVE: no\n"
    "遗漏解族: a_n = n + c"
)
MISS_ALL = "a_n = n for all n >= 0"
MISS_VERDICT = "解族清单: A\n逐族判定: …\n前序结论复核: …"
MISS_LIST = "逐族判定: …\n前序结论复核: …\n结论: EXHAUSTIVE: yes"


@pytest.mark.parametrize("text", [FULL_OK, MISS_ALL, MISS_VERDICT, MISS_LIST, ""])
def test_exhaust_judgement_matches_orchestrator(text):
    """两处实现必须对同一文本给出相同结论（missing 集合 == complete 取反）。"""
    from agent.orchestrator import _parse_exhaust_result

    missing = _exhaust_missing_sections(text)
    parsed = _parse_exhaust_result([{"title": "解族穷尽性检查", "result": text}])

    assert parsed["found"] is True
    # 口径：缺段列表为空 <=> 解析器认为 complete
    assert (not missing) == bool(parsed["complete"]), (
        "口径漂移！missing=%r 而 complete=%r（文本=%r）"
        % (missing, parsed["complete"], text[:60])
    )


def test_exhaust_full_is_complete():
    assert _exhaust_missing_sections(FULL_OK) == []


def test_exhaust_missing_all_reports_four():
    assert sorted(_exhaust_missing_sections(MISS_ALL)) == sorted(
        ["解族清单", "逐族判定", "前序结论复核", "EXHAUSTIVE"])


def test_exhaust_verdict_is_case_insensitive():
    t = "解族清单: A\n逐族判定: B\n前序结论复核: C\n结论: exhaustive : YES"
    assert _exhaust_missing_sections(t) == []


# ---------------------------------------------------------------- ②
def test_strip_answer_forms_removes_boxed_and_final_answer():
    t = r"Area formula gives S=1/2. 最终答案: \boxed{1/2}"
    out = _strip_answer_forms(t)
    assert "\\boxed" not in out
    assert "最终答案" not in out
    assert "Area formula" in out          # 策略本身必须保留


def test_strip_answer_forms_keeps_plan_numbers():
    """策略里的规划数值（如 d=50）属正常描述，**不得**被删（防信息丢失）。"""
    t = "Upper bound (d=50 always works) plus lower bound (d=49 fails)"
    assert _strip_answer_forms(t) == t


def test_strip_answer_forms_handles_empty_and_nonstr():
    assert _strip_answer_forms("") == ""
    assert _strip_answer_forms(None) == ""


def test_strip_answer_forms_removes_english_answer_clause():
    t = "We combine n1 and n2. The answer is 506."
    out = _strip_answer_forms(t)
    assert "The answer is" not in out
    assert "We combine n1 and n2." in out


def test_strip_answer_forms_keeps_natural_answer_sentence():
    """「答案为 X」是**自然语句**（规划结论常见），不得被当成形态标记剥掉。

    回归来源：首版把 `答案(是|为)` 纳入模式，导致既有测试断言
    『证明最终答案为 42』存在时失败 —— 合法结论被削掉。
    """
    for t in ("证明最终答案为 42",
              "该步答案为 42，需在后续子目标中验证",
              "答案为 42 或 43 尚待排除"):
        assert _strip_answer_forms(t) == t, t


# ---------------------------------------------------------------- ③
def test_merge_template_has_discipline_and_formats():
    from prompts.sub_goal import SUBGOAL_MERGE_USER_TEMPLATE as T

    rendered = T.format(
        problem="P", subgoal_plan_summary="S",
        blueprint_conclusion="C", all_results="A", merge_strategy="M",
    )
    assert "合并纪律" in rendered, "merge 模板必须声明规划结论为待验证假设"
    assert "待验证假设" in rendered
    # 注意：模板中「各子目标结果」被【】包裹且原文有换行，故用去空白后的子串断言
    assert "结果为准" in rendered.replace("\n", "")
    # 渲染后不应残留未替换的占位符
    for ph in ("{problem}", "{all_results}", "{merge_strategy}",
               "{blueprint_conclusion}", "{subgoal_plan_summary}"):
        assert ph not in rendered


def test_merge_template_no_bare_braces():
    """模板里除已知占位符外不得有裸花括号（否则 .format() 抛错）。"""
    import re
    from prompts.sub_goal import SUBGOAL_MERGE_USER_TEMPLATE as T

    fields = set(re.findall(r"\{(\w+)\}", T))
    assert fields == {"problem", "subgoal_plan_summary",
                      "blueprint_conclusion", "all_results",
                      "merge_strategy"}, fields


# ---------------------------------------------------------------- ④ 集成
def _make_solver():
    from types import SimpleNamespace

    from agent.sub_goal_solver import SubGoalSolverAgent

    cfg = SimpleNamespace(
        max_total_calls=20, max_time_per_question=300,
        max_total_time_seconds=21000, policy_max_tokens=2048,
        enable_calc_tool=False, calc_mandatory=False,
    )
    return SubGoalSolverAgent(client=None, config=cfg)


def _make_ctx():
    from agent.base import TaskContext

    return TaskContext(problem="求所有可能取值", metadata={})


def test_light_check_rejects_incomplete_exhaust_subgoal():
    """集成：缺段的『解族穷尽性检查』**必须被轻校验打回**（P-9 的核心）。

    003 实测：`exhaust_result.complete=false`（四段全缺）却无人处理，
    答案照旧提交（只给 2026、漏 2030）。本测试锁死"打回"这一行为。
    """
    agent = _make_solver()
    fb = agent._subgoal_light_check(
        _make_ctx(), {"title": "解族穷尽性检查", "type": "verify"},
        "a_n = n for all n >= 0")
    assert fb, "缺段的穷尽性检查必须返回反馈，否则不会触发重解"
    assert "解族清单" in fb


def test_light_check_accepts_complete_exhaust_subgoal():
    agent = _make_solver()
    fb = agent._subgoal_light_check(
        _make_ctx(), {"title": "解族穷尽性检查", "type": "verify"}, FULL_OK)
    assert fb == "", fb


def test_light_check_leaves_other_subgoals_alone():
    """非『解族穷尽性检查』的子目标不受该规则影响（防误伤）。"""
    agent = _make_solver()
    fb = agent._subgoal_light_check(
        _make_ctx(), {"title": "求解", "type": "solve"}, "x = 42")
    assert fb == "", fb
