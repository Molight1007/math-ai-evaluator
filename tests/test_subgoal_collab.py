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
    """rnd>0 时必须带上「上一轮产出」（在现有基础上再生成，不推倒重来）。"""
    s = _Solver(["## 结论\nX"])
    ctx = _Ctx()
    msg_holder = {}

    def _fake_llm(ctx2, messages, temp, max_tokens):
        msg_holder["sys"] = messages[0]["content"]
        msg_holder["user"] = messages[1]["content"]
        return "## 结论\nY"

    s.llm = _fake_llm
    solve_agent(s, ctx, {"title": "t", "description": "d"}, "plan",
                prev="上一轮内容ABC", rnd=1)
    assert "上一轮内容ABC" in msg_holder["user"]
    assert "现有基础" in msg_holder["sys"]


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


def test_planning_agent_prefetch_and_blueprint():
    s = _Solver(["## 下一个子目标计划\n先求值再代入\n## 蓝图补充\n补充：新条件 k>0"])
    ctx = _Ctx()
    plan = planning_agent(s, ctx, {"title": "sg2", "description": "d"},
                          "刚完成 sg1 结论 5", "蓝图摘要")
    assert "先求值再代入" in plan
    assert ctx.subgoal_blueprint_updates[0]["update"].startswith("补充")


def test_solve_subgoals_collab_end_to_end():
    """端到端（stub）：2 个子目标 → 每个 3 遍求解 + 预取规划 + 结果写入。"""
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
