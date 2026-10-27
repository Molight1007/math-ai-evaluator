# -*- coding: utf-8 -*-
"""收尾子目标「最终答案唯一锚点」契约（2026-10-27）。

背景（180 个候选逐条回溯 answer 来源，见 `prompts/sub_goal.py::
SUBGOAL_FINAL_ANSWER_ANCHOR` 的注释）：
  · 仅 59.4% 的 `answer` 来自 `\\boxed{}`；
  · 22.8%（41 条）是从 reasoning **任意位置**抓的片段，实测混着
    `</tool_call>` / `步骤8：重新思考` / 英文思考串 —— 完全不是答案；
  · 16.1% 靠「最终答案」关键词命中，形态不固定。

本组用例锁住三件事（改动一旦退化，这里必红）：
  ① **只有**收尾子目标追加锚点契约 —— 中间步加了会白抬成本；
  ② 开关 `subgoal_final_answer_anchor=0` 时**一律不追加**（A/B 底线）；
  ③ 契约文案本身必须含**固定字面量**「最终答案:」与 `\\boxed{` ——
     提取侧就按这个锚点找，文案改字会直接断链。
"""
from types import SimpleNamespace

from agent.sub_goal_solver__solve import _call_step
from prompts.sub_goal import SUBGOAL_FINAL_ANSWER_ANCHOR


class _Agent:
    """`_call_step` 的最小替身：只拦 system 提示词，不发真实请求。"""

    def __init__(self):
        self.config = SimpleNamespace(enable_theorem_hint=False)
        self.systems = []

    def _multi_agent_n(self, ctx):
        return 1

    def _maybe_tool_llm(self, ctx, messages, temperature, max_tokens):
        self.systems.append(messages[0]["content"])
        return "【本步结果】\n最终答案: \\boxed{42}"

    def _strip_tool_residue(self, text):
        return text

    def _apply_conclusion_contract(self, sg, result, raw_text=None):
        return None


def _ctx():
    return SimpleNamespace(theorem_hint_block="", metadata={})


_ANCHOR_MARK = "收尾要求"      # 契约块标题里的稳定片段


def test_anchor_injected_for_final_step():
    """收尾步（`_is_final_step=True`）必须带上锚点契约。"""
    a = _Agent()
    _call_step(a, _ctx(), "user", {"id": "9", "_is_final_step": True})
    assert _ANCHOR_MARK in a.systems[0]
    assert "最终答案:" in a.systems[0]


def test_anchor_not_injected_for_middle_step():
    """中间步（无标记 / False）绝不追加 —— 它们只当引理用。"""
    a = _Agent()
    _call_step(a, _ctx(), "user", {"id": "2", "_is_final_step": False})
    _call_step(a, _ctx(), "user", {"id": "3"})
    assert len(a.systems) == 2
    for s in a.systems:
        assert _ANCHOR_MARK not in s


def test_anchor_switch_off_injects_nothing(monkeypatch):
    """开关关 ⇒ 收尾步也不追加（A/B 基线必须与改动前逐字一致）。"""
    from agent import sub_goal_solver as _sgs

    monkeypatch.setattr(_sgs, "_final_answer_anchor_on", lambda: False)
    a = _Agent()
    _call_step(a, _ctx(), "user", {"id": "9", "_is_final_step": True})
    assert _ANCHOR_MARK not in a.systems[0]


def test_anchor_switch_registered_default_on():
    """开关必须登记且默认 True（四表门禁之外的**值**断言）。"""
    from contracts.switch_registry import SWITCHES
    from user_agent__config import AgentConfig

    assert "subgoal_final_answer_anchor" in SWITCHES
    _env, _kind, _default = SWITCHES["subgoal_final_answer_anchor"][:3]
    assert _kind == "bool"
    assert _default is True
    assert getattr(AgentConfig, "subgoal_final_answer_anchor", None) is True


def test_anchor_text_has_stable_literal():
    """契约文案里「最终答案:」与 `\\boxed{` 是**提取锚点的字面量**，不得改写。"""
    assert "最终答案:" in SUBGOAL_FINAL_ANSWER_ANCHOR
    assert "\\boxed{" in SUBGOAL_FINAL_ANSWER_ANCHOR
    # 锚点行必须是「最终答案:」顶格形式（后接 \boxed），不能写成装饰性句式
    assert "最终答案: \\boxed{" in SUBGOAL_FINAL_ANSWER_ANCHOR


def test_anchor_text_is_static_no_format_placeholder():
    """文案是**纯静态文本**：追加路径只做字符串拼接，不做 format。

    若有人给它加了 `{x}` 占位符却仍按拼接使用，会静默保留花括号进提示词。
    这里锁住：除 `\\boxed{` / `\\{` 这类 LaTeX 花括号外，没有 format 字段。
    """
    stripped = (SUBGOAL_FINAL_ANSWER_ANCHOR
                .replace("\\boxed{", "")
                .replace("\\{", ""))
    import re
    # format 字段形如 {name} / {0}；LaTeX 里的 {答案} 之类中文/尖括号不算
    assert not re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", stripped)
