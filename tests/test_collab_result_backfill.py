# -*- coding: utf-8 -*-
"""协作路径「结果回填」回归测试（2026-10-20）。

背景：`subgoal_collab_mode` 默认 True，但协作路径只写 `results_map`、
**从不写 `sg["result"]`**，而 `_build_full_reasoning` 恰恰只读后者 ⇒
候选的 `reasoning` 是蓝图骨架（每一步 `结果: ` 全空），而这个 reasoning
正是 4.1 自审 / 4.2 证伪 / 4.4 计算检测的**唯一输入**。

实测证据（soft019_r1）：唯一幸存候选 reasoning 998 字，5 个子目标结果全空，
4.1 判「only lists subgoals but provides no actual arguments」——描述属实。

本文件锁住四件事：
  ① `write_step` 把完整文本写进两个容器（`sg["result"]` + `results_map`）；
  ② 协作路径两个写入点（正常 / 复用命中）都回填 `sg["result"]`；
  ③ `_build_full_reasoning` / `_fallback_from_last_subgoal` 走唯一读入口；
  ④ `results_map` 与 `sg["result"]` 同值（不再有「一个存残片、一个存全文」的分叉）。

注：原 ① 是测 `compose_step_text`（v1 补丁的三节拼回），该函数已删除——
它是过渡产物且生产零调用，留着会诱导新代码用「三节投影」重建文本。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subgoal_collab import solve_subgoals_collab, split_blocks  # noqa: E402
from agent.subgoal_result import parse_sections, read_step  # noqa: E402
from agent.sub_goal_solver__format import (  # noqa: E402
    _build_full_reasoning, _fallback_from_last_subgoal,
)

_OUT = ("## 逻辑推导\n若 a+b=c 则先代入 b=2 得 a+2=c，故 a=c-2\n"
        "## 计算\n3 + 2 = 5\n## 结论\n本步结论: 值 = 5")


# ---------------------------------------------------------------- ① 分节与回填
def test_write_step_keeps_all_sections():
    """完整文本必须原样保留（含模型多写的节），不能只留三节。"""
    raw = _OUT + "\n## 反例\nb=3 时结论不成立"
    sg, rmap = {"id": 1}, {}
    from agent.subgoal_result import write_step
    write_step(sg, rmap, raw)
    assert "反例" in sg["result"], "模型多写的节被丢失 ⇒ 又是 split_blocks 那种降级"
    # 两容器同值：这是「唯一写入口」的契约，读点因此不需要任何 or 兜底
    assert sg["result"] == rmap[1]


def test_write_step_missing_sections_falls_back_to_raw():
    """模型没按板块输出 ⇒ 整段原文，不能返回空串。"""
    raw = "直接给出一段没有分节的推导，答案是 7"
    sg, rmap = {"id": 3}, {}
    from agent.subgoal_result import write_step
    write_step(sg, rmap, raw)
    assert sg["result"] == raw
    assert rmap[3] == raw


def test_write_step_empty():
    from agent.subgoal_result import write_step
    sg, rmap = {"id": 1}, {}
    write_step(sg, rmap, "")
    assert sg["result"] == ""


def test_split_blocks_unchanged_contract():
    """改动的兼容底线：`results_map` 用的结论节形态必须原样不动。"""
    b = split_blocks(_OUT)
    assert b["result"].startswith("本步结论: 值 = 5")
    assert "逻辑推导" not in b["result"]


# ---------------------------------------------------------------- ② 解释文本组装
def _sg(i, result=""):
    return {"id": str(i), "type": "compute", "title": "子目标%s" % i,
            "description": "d%s" % i, "result": result}


def test_build_full_reasoning_reads_sg_result():
    sgs = [_sg(1, "完整推导文本A"), _sg(2, "完整推导文本B")]
    out = _build_full_reasoning(sgs, None, "\\boxed{5}")
    assert "完整推导文本A" in out and "完整推导文本B" in out
    # 没有任何一行是空结果（`结果: ` 前缀本身必然出现，查的是空值行）
    assert not [ln for ln in out.splitlines() if ln.strip() == "结果:"]


def test_build_full_reasoning_falls_back_to_results_map():
    """`sg["result"]` 漏写时用 `results_map` 兜底（与 merge 同口径）。"""
    sgs = [_sg(1, ""), _sg(2, "")]
    rmap = {"1": "rmap结论A", "2": "rmap结论B"}
    out = _build_full_reasoning(sgs, None, "\\boxed{5}", rmap)
    assert "rmap结论A" in out and "rmap结论B" in out


def test_build_full_reasoning_marks_unsolved_only_when_both_empty():
    sgs = [_sg(1, ""), _sg(2, "")]
    out = _build_full_reasoning(sgs, None, "\\boxed{5}")
    assert out.count("结果: 未求解") == 2
    # 传空 dict 与不传等价（不能因 {} 为假而崩）
    assert "未求解" in _build_full_reasoning(sgs, None, "x", {})


# ---------------------------------------------------------------- ③ 答案兜底
def test_fallback_answer_uses_results_map():
    sgs = [_sg(1, ""), _sg(2, "")]
    assert _fallback_from_last_subgoal(sgs) == "无法求解"
    assert _fallback_from_last_subgoal(sgs, {"1": "4", "2": "4"}) == "4"


def test_fallback_answer_prefers_last_nonempty():
    sgs = [_sg(1, "结果一"), _sg(2, "")]
    assert _fallback_from_last_subgoal(sgs, {"2": "rmap兜底"}) == "rmap兜底"


def test_fallback_answer_conclusion_before_result():
    """结论契约（`conclusion`）仍优先于 result —— 避免整段推导被当终答。"""
    sg = _sg(1, "本步结论: 值 = 5\n依据: …\n验算: 很长的一段验算")
    sg["conclusion"] = "5"
    assert _fallback_from_last_subgoal([sg]) == "5"


# ---------------------------------------------------------------- ④ 端到端
class _Ctx:
    def __init__(self):
        self.problem = "测试题"
        self.subgoal_trace = []


class _Solver:
    """stub：`_solve_subgoal` 直接返回预置的板块文本，不走 LLM。"""

    def __init__(self, replies, regen_rounds=3):
        self.replies = list(replies)
        self.events = []
        self.config = SimpleNamespace(policy_max_tokens=2048,
                                      subgoal_reuse_done=True,
                                      subgoal_collab_regen_rounds=regen_rounds)
        self.client = None

    def llm(self, ctx, messages, temp, max_tokens):
        return self.replies.pop(0) if self.replies else ""

    def _solve_subgoal(self, ctx, sg, plan_summary, prev_results,
                       extra_hint=""):
        return self.replies.pop(0) if self.replies else ""

    def _strip_check_tags(self, out):
        return out

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))

    def _build_trace_item(self, sg, step_result, reused=False):
        return {"id": sg.get("id"), "result": step_result, "reused": reused}

    def _restore_contract(self, sg, snap):
        pass


def _end_to_end(monkeypatch, n_rounds=1):
    """★ `_rounds()` 读 config.regen_rounds，必须同步传给 _Solver，否则
    replies 序列会错位（子目标拿到的是下一段规划文本）。"""
    monkeypatch.setenv("SUBGOAL_REGEN_SELF_REVIEW", "0")
    replies = ["## 下一个子目标计划\n计划0\n## 蓝图补充\n无"]      # 预取
    for _ in range(2):
        replies += [_OUT] * n_rounds                              # 求解 ×N
        replies += ['{"pass": true, "issues": []}']               # 审核
        replies += ["## 下一个子目标计划\n计划1\n## 蓝图补充\n无"]  # 预取下一步
    s = _Solver(replies, regen_rounds=n_rounds)
    ctx = _Ctx()
    subgoals = [{"id": "s1", "title": "子目标1", "description": "d1", "type": "t"},
                {"id": "s2", "title": "子目标2", "description": "d2", "type": "t"}]
    results_map = {}
    solve_subgoals_collab(s, ctx, subgoals, "计划摘要", results_map)
    return subgoals, results_map


def test_collab_writes_sg_result(monkeypatch):
    """★ 核心回归：协作跑完后 `sg["result"]` 非空，且与 `results_map` **同值**。

    `results_map` 不再是"只放结论节"的残片投影 —— 存储一律完整，压缩交给
    读者侧的 `clip()`（见 `subgoal_result.py` 的分层说明）。
    """
    subgoals, results_map = _end_to_end(monkeypatch, n_rounds=1)
    for sg in subgoals:
        assert sg.get("result"), "子目标 %s 的 result 为空 ⇒ reasoning 必为骨架" % sg["id"]
        assert "## 逻辑推导" in sg["result"]
        assert "## 结论" in sg["result"]
        # 存储保留**原文**：必须能被 parse_sections 再解析，否则下游取不到节
        assert parse_sections(sg["result"]).get("逻辑推导")
        # 唯一写入口保证两容器同值
        assert results_map[sg["id"]] == sg["result"]


def test_collab_reasoning_not_skeleton(monkeypatch):
    """端到端断言：拼出来的 reasoning 里没有任何一行是「结果: 」空的。"""
    subgoals, results_map = _end_to_end(monkeypatch, n_rounds=1)
    out = _build_full_reasoning(subgoals, None, "\\boxed{5}", results_map)
    for line in out.splitlines():
        assert line.strip() != "结果:", "reasoning 出现空结果行"
    assert "先代入 b=2" in out              # 逻辑节确实进了 reasoning
    # 嵌入文本的 `## 标题` 必须降级为 `**标题**`，否则会被解析成文档级标题
    assert "## 结论" not in out
    assert out.count("**结论**") >= 2


def test_collab_reuse_uses_cached_text(monkeypatch):
    """复用命中的是缓存里的文本，且两容器同值（不再区分 `full` 键）。"""
    monkeypatch.setenv("SUBGOAL_REGEN_SELF_REVIEW", "0")
    s = _Solver([])
    ctx = _Ctx()
    sg = {"id": "s1", "title": "T", "description": "D", "type": "t"}
    ctx._subgoal_done = {"T|D|t": {"result": "缓存完整文本", "contract": {}}}
    results_map = {}
    solve_subgoals_collab(s, ctx, [sg], "摘要", results_map)
    assert results_map["s1"] == "缓存完整文本"
    assert sg["result"] == "缓存完整文本"


def test_collab_empty_cache_not_reused(monkeypatch):
    """★ 空缓存**不算命中**：复用是优化，不能成为把空壳灌回去的通道。"""
    monkeypatch.setenv("SUBGOAL_REGEN_SELF_REVIEW", "0")
    replies = ["## 下一个子目标计划\n计划0\n## 蓝图补充\n无", _OUT,
               '{"pass": true, "issues": []}', ""]
    s = _Solver(replies, regen_rounds=1)
    ctx = _Ctx()
    sg = {"id": "s1", "title": "T", "description": "D", "type": "t"}
    ctx._subgoal_done = {"T|D|t": {"result": "", "contract": {}}}
    results_map = {}
    solve_subgoals_collab(s, ctx, [sg], "摘要", results_map)
    assert results_map["s1"], "空缓存被当成命中 ⇒ 该步等于没有求解"
    assert "本步结论: 值 = 5" in results_map["s1"]
    assert read_step(sg, results_map) == results_map["s1"]


def test_collab_reuse_restores_full_text(monkeypatch):
    """复用命中（缓存来自旧结构、无 `full` 键）不能把空壳重新灌进去。"""
    monkeypatch.setenv("SUBGOAL_REGEN_SELF_REVIEW", "0")
    s = _Solver([])
    ctx = _Ctx()
    sg = {"id": "s1", "title": "T", "description": "D", "type": "t"}
    ctx._subgoal_done = {"T|D|t": {"result": "缓存结论", "contract": {}}}
    results_map = {}
    solve_subgoals_collab(s, ctx, [sg], "摘要", results_map)
    assert results_map["s1"] == "缓存结论"
    assert sg.get("result") == "缓存结论"   # 旧缓存无 full ⇒ 退回 result，至少非空
