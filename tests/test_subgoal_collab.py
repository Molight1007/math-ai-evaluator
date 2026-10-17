# -*- coding: utf-8 -*-
"""子目标三角色协作求解 单测（2026-10-15 用户定案 · 第一版）。

覆盖：板块解析 / 3 遍迭代（在现有基础上再生成）/ 预取规划 / 审核（工具③
复算；无 client 时工具①安全跳过）/ 结果写入兼容 / 蓝图补充留痕。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subgoal_collab import (  # noqa: E402
    _rounds, planning_agent, review_agent, solve_agent, solve_subgoals_collab,
    split_blocks,
)

_OUT1 = ("## 逻辑推导\n因为 a+b=c 的推导步骤×××\n"
         "## 计算\n2 + 3 = 5\n## 结论\n和为 5")
_OUT2 = ("## 逻辑推导\n完善后的推导\n## 计算\n2 + 3 = 5\n## 结论\n和为 5（完善版）")


def test_split_blocks():
    b = split_blocks(_OUT1)
    assert "推导步骤" in b["logic"]
    assert "2 + 3" in b["calc"]
    assert b["result"].startswith("和为 5")
    # 无分节 → 整段进 result
    assert split_blocks("随便一段话")["result"] == "随便一段话"


class _Ctx:
    def __init__(self):
        self.problem = "测试题"
        self.subgoal_trace = []


class _Solver:
    def __init__(self, replies):
        self.replies = list(replies)
        self.events = []
        self.config = SimpleNamespace(policy_max_tokens=2048,
                                      subgoal_reuse_done=True,
                                      subgoal_collab_regen_rounds=3)
        self.client = None
        self.calls = 0

    def llm(self, ctx, messages, temp, max_tokens):
        self.calls += 1
        return self.replies.pop(0) if self.replies else "## 结论\n兜底"

    def _solve_subgoal(self, ctx, sg, plan_summary, prev_results,
                       extra_hint=""):
        """★ F1 修复后 solve_agent 走此入口（复用旧链单步求解）。"""
        self.last_hint = extra_hint
        self.last_plan = plan_summary
        return self.replies.pop(0) if self.replies else "## 结论\n兜底"

    def _strip_check_tags(self, out):
        return out

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))

    def _build_trace_item(self, sg, step_result, reused=False):
        return {"id": sg.get("id"), "result": step_result, "reused": reused}

    def _restore_contract(self, sg, snap):
        pass


def test_rounds_config():
    s = _Solver([])
    assert _rounds(s) == 3
    s.config.subgoal_collab_regen_rounds = 1
    assert _rounds(s) == 1
    s.config.subgoal_collab_regen_rounds = 99
    assert _rounds(s) == 5              # 上限


def test_solve_agent_regen_prompt():
    """rnd>0 时必须把「上一轮产出」经 extra_hint 带回（在现有基础上再生成，
    不推倒重来）——★ F1 修复后经 `_solve_subgoal` 的 extra_hint 通道。"""
    s = _Solver([])
    ctx = _Ctx()
    _r = solve_agent(s, ctx, {"title": "t", "description": "d"}, "plan",
                     prev="上一轮内容ABC", rnd=1)
    assert _r                              # 返回非空
    assert "上一轮内容ABC" in s.last_hint
    assert "不要推倒重来" in s.last_hint
    # rnd=0 时不带"上一轮"段
    s2 = _Solver(["## 结论\nX"])
    solve_agent(s2, _Ctx(), {"title": "t"}, "plan", prev="", rnd=0)
    assert "上一轮产出" not in s2.last_hint


def test_review_agent_calc_catch():
    """工具③ 抓出计算错误（2+3=6 不一致）。"""
    s = _Solver([])
    ctx = _Ctx()
    bad = ("## 逻辑推导\n略\n## 计算\n2 + 3 = 6\n## 结论\n和为 6")
    r = review_agent(s, ctx, {"title": "t"}, bad)
    assert r["pass"] is False
    assert any("计算错误" in x for x in r["issues"])
    assert r["tool_report"].get("calc", {}).get("n_bad") == 1


def test_review_agent_ok_path():
    s = _Solver(['{"pass": true, "issues": []}'])
    ctx = _Ctx()
    r = review_agent(s, ctx, {"title": "t"}, _OUT1)
    assert r["pass"] is True and r["issues"] == []


def test_extract_unicode_operators():
    """★ 审核 S1：Unicode 运算符（× ÷ −）须归一化为 ASCII 后提取——
    否则 `20 × 3 = 60` 会被劈成假等式（3 = 60）误报"算错"。"""
    from agent.math_check_gate import _extract_numeric_equations as E
    assert E("20 × 3 = 60") == [("20 * 3", "60")]
    assert E("100 ÷ 4 = 25") == [("100 / 4", "25")]
    assert E("5 − 2 = 3") == [("5 - 2", "3")]
    # 真错算仍被抓（不是被归一化掩盖）
    from tools.agent_toolkit import calc_verify
    eqs = E("20 × 3 = 61")
    r = calc_verify([{"expr": a, "claimed": b} for a, b in eqs])
    assert r["n_bad"] == 1


def test_planning_agent_prefetch_and_blueprint():
    s = _Solver(["## 下一个子目标计划\n先求值再代入\n## 蓝图补充\n补充：新条件 k>0"])
    ctx = _Ctx()
    plan = planning_agent(s, ctx, {"title": "sg2", "description": "d"},
                          "刚完成 sg1 结论 5", "蓝图摘要")
    assert "先求值再代入" in plan
    assert ctx.subgoal_blueprint_updates[0]["update"].startswith("补充")


def test_solve_subgoals_collab_end_to_end(monkeypatch):
    """端到端（stub）：2 个子目标 → 每个 3 遍求解 + 预取规划 + 结果写入。

    ★ 2026-10-17：本用例关闭「生成前自审」（自审有独立单测）——否则每次
    迭代会多消耗一次 LLM 回复、打乱 replies 序列。
    """
    monkeypatch.setenv("SUBGOAL_REGEN_SELF_REVIEW", "0")
    # llm 调用序列：规划(预取) → sg1 求解×3 → [审核 LLM] → 规划 → sg2 求解×3 → 审核 …
    replies = [
        "## 下一个子目标计划\n计划0\n## 蓝图补充\n无",   # 预取
        _OUT1, _OUT2, _OUT2,                              # sg1 ×3
        '{"pass": true, "issues": []}',                   # sg1 审核 LLM
        "## 下一个子目标计划\n计划1\n## 蓝图补充\n无",     # sg1 后规划
        _OUT1, _OUT2, _OUT2,                              # sg2 ×3
        '{"pass": true, "issues": []}',                   # sg2 审核 LLM
        "",                                               # sg2 后规划（无下一个）
    ]
    s = _Solver(replies)
    ctx = _Ctx()
    subgoals = [{"id": "s1", "title": "子目标1", "description": "d1", "type": "t"},
                {"id": "s2", "title": "子目标2", "description": "d2", "type": "t"}]
    results_map = {}
    n = solve_subgoals_collab(s, ctx, subgoals, "计划摘要", results_map)
    assert n > 0
    assert set(results_map) == {"s1", "s2"}
    assert "完善版" in results_map["s1"]     # 采用了第 3 遍（迭代版）产物
    assert len(ctx.subgoal_trace) == 2
    assert ctx.subgoal_collab_diag["regen_rounds"] == 3
    assert ctx.subgoal_collab_diag["n_subgoals"] == 2


def test_solve_subgoals_collab_reuse_cache():
    """复用缓存命中 → 零 LLM 调用（与旧循环同口径）。"""
    s = _Solver([])
    ctx = _Ctx()
    sg = {"id": "s1", "title": "T", "description": "D", "type": "t"}
    fp = "T|D|t"
    ctx._subgoal_done = {fp: {"result": "缓存结论", "contract": {}}}
    results_map = {}
    solve_subgoals_collab(s, ctx, [sg], "摘要", results_map)
    assert results_map["s1"] == "缓存结论"
    # 仅预取规划的一次 LLM（无求解调用）；再断言未出现"①求解"事件
    assert not any("①求解" in m for _, m in s.events)


def test_quick_self_review_no_issue():
    """自审输出「无」⇒ 返回空串（不干扰迭代）。"""
    from agent.subgoal_collab import quick_self_review
    s = _Solver(["无"])
    assert quick_self_review(s, _Ctx(), {"title": "t"}, "上一轮解答") == ""


def test_quick_self_review_returns_issues():
    from agent.subgoal_collab import quick_self_review
    s = _Solver(["- 第2步：把 a^2+b^2 误当作 (a+b)^2"])
    out = quick_self_review(s, _Ctx(), {"title": "t"}, "上一轮解答")
    assert "第2步" in out


def test_solve_agent_injects_prev_issues():
    """3 遍迭代时，自审问题必须进入 extra_hint（用户：先审核再生成）。"""
    s = _Solver(["## 结论\nX"])
    solve_agent(s, _Ctx(), {"title": "t"}, "plan", prev="旧产出",
                rnd=1, prev_issues="- 第3步符号错")
    assert "自审发现的上一轮问题" in s.last_hint
    assert "第3步符号错" in s.last_hint
