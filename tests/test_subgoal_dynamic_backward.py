# -*- coding: utf-8 -*-
"""求解期动态倒推（`agent/sub_goal_solver__backward.py`）的单元与端到端测试。

覆盖（2026-10-15，用户「2 与 3 之间建一个环」）：
  · 缺前提判定（显式 `<need_premise>` 标记 / 失败关键词兜底 / 正常结果不误触发）
  · 动态子目标 **独立 id 空间**（不与整数序号冲突、跨父目标唯一）
  · 动态子目标字段齐全（`_build_trace_item` 是**直接索引**这些键，缺一个就 KeyError）
  · 开关关闭 / 深度上限 / 模型判定「不缺前提」时**原样返回**（不拆解）
  · 端到端：缺前提 → 倒推 → 解前提 → 回填 `results_map` → 重解原目标
  · 递归：前提自己缺前提时同法再倒推一层，受 `subgoal_backward_max_depth` 封顶
"""
from __future__ import annotations

import types

from agent.sub_goal_solver__backward import (
    sg_dynamic_backward,
    sg_missing_premise,
    _make_premise_sg,
    _new_backward_id,
    _render_backward_block,
)


# ---------------------------------------------------------------- 测试替身
class _FakeCtx:
    problem = "已知 f 在 [0,1] 上连续，求最大值。"
    deadline = 0
    trace = None

    def __init__(self):
        self.trace = []
        self.subgoal_trace = []

    def is_time_critical(self):
        return False


class _FakeAgent:
    """最小可用的 SubGoalSolverAgent 替身。

    `_solve_subgoal` 按「子目标 id → 第几次求解」的脚本返回，用来复现
    「原目标先失败 → 前提求解成功 → 原目标重解成功」的完整链。
    """

    def __init__(self, script=None, premise_json=None, cfg=None):
        _cfg = {"subgoal_dynamic_backward": True, "subgoal_backward_max_depth": 2}
        _cfg.update(cfg or {})
        self.config = types.SimpleNamespace(**_cfg)
        self._script = script or {}
        self._calls = {}
        self._premise_json = premise_json
        self.llm_calls = []
        self.records = []

    def record(self, ctx, step, content, **extra):
        self.records.append((step, content))

    def _looks_placeholder(self, result):
        return not result or result in ("", "占位")

    def _strip_check_tags(self, s):
        return s

    def _build_trace_item(self, sg, res, reused=False):
        # 关键：与生产同口径地**直接索引**这些键 —— 缺字段即在此暴露 KeyError
        return {"id": sg["id"], "title": sg["title"], "description": sg["description"],
                "type": sg["type"], "depends_on": sg["depends_on"],
                "expected_output": sg["expected_output"], "result": res}

    def _solve_subgoal(self, ctx, sg, plan_summary, prev_results, extra_hint=""):
        n = self._calls.get(sg["id"], 0)
        self._calls[sg["id"]] = n + 1
        outs = self._script.get(sg["id"]) or []
        if n < len(outs):
            return outs[n]
        return outs[-1] if outs else f"结论[{sg['id']}]"

    def llm(self, ctx, messages, temperature, max_tokens):
        self.llm_calls.append(messages)
        return self._premise_json


def _sg(sid=3, title="子目标3: 求最大值"):
    return {"id": sid, "title": title, "description": "求 f 的最大值",
            "type": "derive", "depends_on": [], "expected_output": ""}


_OK_JSON = ('{"ok": true, "premise": "f 在 [0,1] 上可导", '
            '"why": "缺它无法求极值", "tool": "sympy"}')
_NO_JSON = '{"ok": false, "reason": "失败原因是算错，不是缺前提"}'


# ---------------------------------------------------------------- 判定函数
def test_missing_premise_explicit_marker_ignores_failed_flag():
    """显式标记：即使结果"看起来正常"也要触发（模型主动声明）。"""
    got = sg_missing_premise("推导……<need_premise>f 在 0 处连续</need_premise>", False)
    assert got == "f 在 0 处连续"


def test_missing_premise_keyword_requires_failed():
    """关键词兜底**必须** failed 同时成立，否则正常语句里的"不成立"会误触发。"""
    assert sg_missing_premise("[子目标 3] 缺少必要前提", True)
    assert sg_missing_premise("该假设不成立，故取另一支", False) == ""


def test_missing_premise_normal_result_is_empty():
    assert sg_missing_premise("本步结论: 值 = 42", False) == ""
    assert sg_missing_premise("", True) == ""


# ---------------------------------------------------------------- id 空间
def test_backward_id_independent_space():
    """动态 id 是字符串（`3B1`），与整数序号天然不冲突 ⇒ results_map 零错位。"""
    ctx = _FakeCtx()
    a = _new_backward_id(ctx, 3)
    b = _new_backward_id(ctx, 3)
    c = _new_backward_id(ctx, 5)
    assert a == "3B1" and b == "3B2" and c == "5B3"
    assert all(isinstance(x, str) for x in (a, b, c))


def test_premise_sg_fields_complete():
    """`_build_trace_item` / `_prepare_step_prompt` 直接索引这些键，必须齐全。"""
    ctx = _FakeCtx()
    p = _make_premise_sg(ctx, _sg(), "f 可导", "sympy", "why")
    for k in ("id", "title", "description", "type", "depends_on", "expected_output"):
        assert k in p
    assert p["tool"] == "sympy"
    assert p["dynamic"] is True and p["backward_from"] == 3
    # 能直接喂给 trace 构造器（真索引一遍，缺键即 KeyError）
    item = _FakeAgent()._build_trace_item(p, "r")
    assert item["id"] == p["id"]


# ---------------------------------------------------------------- 主流程
def test_disabled_returns_unchanged():
    agent = _FakeAgent(premise_json=_OK_JSON,
                       cfg={"subgoal_dynamic_backward": False})
    out = sg_dynamic_backward(agent, _FakeCtx(), _sg(),
                              "<need_premise>x</need_premise>", None, {})
    assert out == "<need_premise>x</need_premise>"
    assert not agent.llm_calls          # 关了就一次 LLM 都不该发


def test_depth_cap_stops_recursion():
    agent = _FakeAgent(premise_json=_OK_JSON)
    out = sg_dynamic_backward(agent, _FakeCtx(), _sg(),
                              "<need_premise>x</need_premise>", None, {},
                              depth=3)          # > max(2)
    assert out == "<need_premise>x</need_premise>"
    assert not agent.llm_calls


def test_no_premise_signal_passes_through():
    """正常结果（无标记、非失败）不该触发倒推。"""
    agent = _FakeAgent(premise_json=_OK_JSON)
    out = sg_dynamic_backward(agent, _FakeCtx(), _sg(), "本步结论: 值 = 42", None, {})
    assert out == "本步结论: 值 = 42"
    assert not agent.llm_calls


def test_model_says_not_missing_premise_keeps_original():
    """二次闸门：模型判定"不缺前提" ⇒ 放弃倒推、维持原结果。"""
    agent = _FakeAgent(premise_json=_NO_JSON)
    ctx, rm = _FakeCtx(), {}
    out = sg_dynamic_backward(agent, ctx, _sg(),
                              "<need_premise>x</need_premise>", None, rm)
    assert out == "<need_premise>x</need_premise>"
    assert rm == {} and ctx.subgoal_trace == []


def test_end_to_end_premise_filled_and_retried():
    """端到端：原目标失败 → 倒推前提 → 解前提 → 回填 results_map → 重解成功。

    ★ `script` 的索引语义：`sg_dynamic_backward` 对**原目标**的首次调用就是
      "回填后重解"（传入的 `step_result` 是**已经失败**的结果）⇒ script[3][0]
      必须是**重解的成功结果**。
    """
    agent = _FakeAgent(script={3: ["结论: 最大值 = 7"]}, premise_json=_OK_JSON)
    # 前提 3B1 不在 script 里 ⇒ 走默认返回
    ctx, rm = _FakeCtx(), {}
    out = sg_dynamic_backward(agent, ctx, _sg(),
                              "[子目标 3] 缺少必要前提，无法推进",
                              "plan-summary", "已有结论", results_map=rm)
    assert "最大值 = 7" in out                       # 重解结果被采纳
    assert "3B1" in rm                              # 前提结论已回填运行时表
    assert any(t["id"] == "3B1" for t in ctx.subgoal_trace)
    assert any("倒推出前提" in c for _, c in agent.records)


def test_recursive_backward_one_more_level():
    """递归：前提自己缺前提 ⇒ 同法再倒推一层（depth 未超限）。

    链路：3 缺前提 → 倒推 3B1 → 3B1 也缺前提 → 再倒推 3B1B2 → 解 3B1B2
          → 回填重解 3B1（成功）→ 回填重解 3（成功）。
    """
    agent = _FakeAgent(
        script={3: ["结论: 完成 = 1"],
                "3B1": ["[子目标 3B1] 缺少前提", "结论: 前提已补"]},
        premise_json=_OK_JSON)
    ctx, rm = _FakeCtx(), {}
    out = sg_dynamic_backward(agent, ctx, _sg(), "[子目标 3] 缺少前提",
                              "plan-summary", "", results_map=rm)
    assert out == "结论: 完成 = 1"
    assert "3B1" in rm and "3B1B2" in rm       # 两级动态子目标都落了运行时表
    assert rm["3B1"] == "结论: 前提已补"


def test_render_backward_block_lists_results():
    ctx = _FakeCtx()
    p = _make_premise_sg(ctx, _sg(), "f 可导", "llm")
    p["result"] = "f' 存在"
    blk = _render_backward_block([p])
    assert "本步新增前提" in blk and "f' 存在" in blk
    assert _render_backward_block([]) == ""
