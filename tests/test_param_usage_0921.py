# -*- coding: utf-8 -*-
"""可调参数实测记录（param_usage）单测 —— 2026-09-21。

覆盖两处新增：
  ① `agent/param_usage.py`：上限 vs 实测表的采集与聚合；
  ② `utils/llm_client.py`：截断台账的 `by_max_tokens` / `by_site` 分解。

设计要点（决定了下面这些断言为什么长这样）：
  · `used=None` 必须与 `used=0` 区分 —— 前者是"没有埋点"，后者是"真的用了 0 次"；
  · **近似口径绝不能冒充"撞顶"** —— 拿 `len(ctx.candidates)=6` 去比
    `policy_sample_times=2` 会得出 `capped=True`，那是假信号，会把调参带错方向；
  · 任何缺字段 / 空对象都不得抛异常（埋点搞挂主流程的代价更大）。
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace as NS

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agent.param_usage import (  # noqa: E402
    SCHEMA, collect_param_usage, aggregate)
from agent.orchestrator import _summarize_leansearch  # noqa: E402
from utils.llm_client import (  # noqa: E402
    _mark_response, truncation_breakdown, get_truncation_stats)


# ---------------------------------------------------------------- 夹具
def _cfg(**kw):
    base = dict(
        leansearch_max_calls_per_q=2, leansearch_top_k=5,
        max_subgoals=6, max_subgoals_by_tier={"standard": 8, "deep": 16},
        lean_gate_unknown_stop=2, max_revise_rounds=5, deep_revise_rounds=2,
        preverify_max_rounds=2, skeleton_review_max_rounds=2, collab_max_rounds=3,
        self_improve_max=2, policy_sample_times=2, verifier_voting_times=1,
        verifier_disagreement_votes=3, max_total_calls=150,
        max_answer_tokens=65536, verifier_deep_review_max_tokens=6144,
        adversarial_max_tokens=640,
    )
    base.update(kw)
    return NS(**base)


def _ctx(**kw):
    base = dict(
        tier="standard", trace=[], subgoal_stats=None, subgoal_trace=[],
        budget=None, candidates=[], verdicts=[], n_candidates=None,
        n_verdicts=None, revise_round=0, mathlib_usage_stats={},
        used_theorems=[], audit_gate=[], lean_gate=[],
        preverify_trace={}, skeleton_review_report={},
    )
    base.update(kw)
    return NS(**base)


# ================================================================
# ① 采集：不得抛异常，且 used=None 与 0 可区分
# ================================================================
class TestCollectRobustness:
    def test_empty_ctx_does_not_raise(self):
        pu = collect_param_usage(NS(), NS())
        assert pu["schema"] == SCHEMA
        assert pu["items"], "空 ctx 也应有完整键表"
        assert all(v["used"] is None for v in pu["items"].values())
        assert set(pu["gaps"]) == set(pu["items"]), "全无埋点 ⇒ gaps 应覆盖全部"

    def test_object_with_exploding_attrs_does_not_raise(self):
        class Boom:
            def __getattr__(self, item):
                raise RuntimeError("boom")

        pu = collect_param_usage(Boom(), Boom())
        assert pu["items"], "异常属性也必须被吞吐"

    def test_used_zero_is_not_none(self):
        """`revise_round=0` 是"确实 0 轮"，不能与"无埋点"混为一谈。"""
        pu = collect_param_usage(_ctx(revise_round=0), _cfg())
        e = pu["items"]["max_revise_rounds"]
        assert e["used"] == 0 and e["capped"] is False
        assert "max_revise_rounds" not in pu["gaps"]


# ================================================================
# ② 用户点名的四项：cap 与 used 都必须是真实口径
# ================================================================
class TestNamedParams:
    def test_leansearch_calls(self):
        pu = collect_param_usage(_ctx(_leansearch_calls=2), _cfg())
        e = pu["items"]["leansearch_max_calls_per_q"]
        assert (e["cap"], e["used"], e["capped"]) == (2, 2, True)

    def test_leansearch_calls_fallback_to_trace(self):
        """没有 `_leansearch_calls` 计数器时，用 trace 里成功的检索条数兜底。"""
        tr = [{"step": "leansearch", "n_hits": 3},
              {"step": "leansearch", "content": "跳过"}]
        pu = collect_param_usage(_ctx(trace=tr), _cfg())
        assert pu["items"]["leansearch_max_calls_per_q"]["used"] == 1

    def test_leansearch_top_k_uses_max_hits(self):
        tr = [{"step": "leansearch", "n_hits": 3},
              {"step": "leansearch", "n_hits": 5}]
        pu = collect_param_usage(_ctx(trace=tr), _cfg())
        e = pu["items"]["leansearch_top_k"]
        assert e["used"] == 5 and e["capped"] is True

    def test_subgoals_prefers_tier_table_over_flat(self):
        """deep 档必须取 max_subgoals_by_tier['deep']=16，而不是扁平 6。"""
        ctx = _ctx(tier="deep", subgoal_stats={"n_subgoals": 16})
        e = collect_param_usage(ctx, _cfg())["items"]["max_subgoals"]
        assert e["cap"] == 16, "档位字典未生效 ⇒ 与代码消费逻辑不一致"
        assert e["used"] == 16 and e["capped"] is True

    def test_subgoals_falls_back_to_flat_when_tier_absent(self):
        ctx = _ctx(tier="fast", subgoal_stats={"n_subgoals": 3})
        e = collect_param_usage(ctx, _cfg())["items"]["max_subgoals"]
        assert e["cap"] == 6, "档位表不含该档 ⇒ 应回退扁平值"

    def test_unknown_streak_is_a_streak_not_a_total(self):
        """`lean_gate_unknown_stop` 是**连续**口径：中间插一个 reject 要断开。"""
        ctx = _ctx(audit_gate=[
            {"step": "final_gate", "verdict": "unknown"},
            {"step": "final_gate", "verdict": "reject"},   # 断开
            {"step": "final_gate", "verdict": "unknown"},
            {"step": "final_gate", "verdict": "unknown"},
        ])
        e = collect_param_usage(ctx, _cfg())["items"]["lean_gate_unknown_stop"]
        assert e["used"] == 2, "最长连击应为 2（后两个），不是 unknown 总数 3"
        assert e["capped"] is True

    def test_gate_rework_uses_gate_tried(self):
        """deep 档重做上限 = 3（`DEEP_MAX_REWORK` 默认值），standard = 2。"""
        ctx = _ctx(tier="deep", _gate_tried=["a", "b"])
        e = collect_param_usage(ctx, _cfg())["items"]["gate_max_rework"]
        assert (e["cap"], e["used"], e["capped"]) == (3, 2, False)

    def test_gate_rework_counts_one_note(self):
        """`_gate_tried` 为空时回退到 final_gate 事件数（注释里写明是下界口径）。"""
        ctx = _ctx(audit_gate=[{"step": "final_gate", "verdict": "reject"},
                               {"step": "final_gate", "verdict": "reject"}])
        e = collect_param_usage(ctx, _cfg())["items"]["gate_max_rework"]
        assert e["used"] == 2
        assert "final_gate" in e["src"], "回退口径应体现在 src 里"

    def test_gate_rework_standard_cap_is_2(self):
        ctx = _ctx(tier="standard", _gate_tried=["a"])
        e = collect_param_usage(ctx, _cfg())["items"]["gate_max_rework"]
        assert e["cap"] == 2


# ================================================================
# ③ 近似口径绝不冒充"撞顶"（本次最关键的防错）
# ================================================================
class TestExactVsApprox:
    @pytest.mark.parametrize("name", [
        "policy_sample_times", "self_improve_max",
        "verifier_voting_times", "verifier_disagreement_votes",
        "collab_max_rounds",
    ])
    def test_approx_never_reports_capped(self, name):
        # 故意让代理值(6/12) 远大于 cap(1~3)：若实现偷懒就会误报 capped=True
        ctx = _ctx(candidates=[object()] * 6, n_candidates=6,
                   verdicts=[object()] * 12, n_verdicts=12,
                   trace=[{"step": "deep_review"}])
        pu = collect_param_usage(ctx, _cfg())
        e = pu["items"][name]
        assert e["exact"] is False
        assert e["capped"] is None, "%s 是代理口径，不得判撞顶" % name
        assert name in pu["approx"]

    def test_token_caps_have_no_used(self):
        pu = collect_param_usage(_ctx(), _cfg())
        for k in ("max_answer_tokens", "verifier_deep_review_max_tokens",
                  "adversarial_max_tokens"):
            assert pu["items"][k]["cap"] is not None
            assert pu["items"][k]["used"] is None
            assert k in pu["gaps"], "token 口径无实测 ⇒ 必须进 gaps 提醒补埋点"

    def test_exact_false_when_under_cap(self):
        pu = collect_param_usage(_ctx(budget=NS(used_calls=88)), _cfg())
        e = pu["items"]["max_total_calls"]
        assert e["exact"] is True and e["capped"] is False


# ================================================================
# ④ aggregate：纯算术，可复算
# ================================================================
class TestAggregate:
    def test_aggregate_basic(self):
        a = collect_param_usage(_ctx(subgoal_stats={"n_subgoals": 16},
                                    budget=NS(used_calls=100)), _cfg())
        b = collect_param_usage(_ctx(subgoal_stats={"n_subgoals": 4},
                                    budget=NS(used_calls=200)), _cfg())
        ag = aggregate([a, b])
        assert ag["n_questions"] == 2
        assert ag["items"]["max_subgoals"]["used"] == {
            "n": 2, "mean": 10.0, "max": 16, "min": 4}
        assert ag["items"]["max_total_calls"]["used"]["max"] == 200

    def test_aggregate_ignores_garbage(self):
        ag = aggregate([None, "x", {}, {"items": "not-a-dict"}])
        assert ag["n_questions"] == 0 and ag["items"] == {}


# ================================================================
# ⑤ _summarize_leansearch 的新口径
# ================================================================
class TestSummarizeLeansearch:
    def test_new_fields(self):
        tr = [
            {"step": "leansearch", "n_hits": 5, "elapsed_ms": 10.0,
             "names": ["A.b", "A.c"], "root": "/r"},
            {"step": "leansearch", "n_hits": 4, "names": ["A.c"], "root": "/r"},
            {"step": "leansearch",
             "content": "已达单题检索次数上限（2），跳过"},
        ]
        out = _summarize_leansearch(_ctx(trace=tr), _cfg())
        assert out["calls"] == out["n_queries"] == 2
        assert out["per_query"] == [5, 4]
        assert out["hits"] == 9 and out["unique"] == 2
        assert out["top_k"] == 5 and out["top_k_capped"] is True
        assert out["max_calls_per_q"] == 2 and out["calls_capped"] is True
        assert out["skipped_call_cap"] == 1

    def test_backward_compatible_single_arg(self):
        """旧调用点 `_summarize_leansearch(ctx)` 必须仍然可用。"""
        out = _summarize_leansearch(_ctx())
        assert out["calls"] == 0 and out["top_k"] is None
        assert out["top_k_capped"] is False and out["calls_capped"] is False

    def test_time_critical_skip_counted(self):
        tr = [{"step": "leansearch", "content": "时间紧张，跳过引理检索（注入为空）"}]
        out = _summarize_leansearch(_ctx(trace=tr), _cfg())
        assert out["skipped_time_critical"] == 1 and out["n_queries"] == 0


# ================================================================
# ⑥ llm_client 截断台账分解
# ================================================================
class TestTruncationBreakdown:
    def test_by_max_tokens_and_by_site_accumulate(self):
        before = truncation_breakdown()
        b_bmt = dict(before["by_max_tokens"])
        b_bs = dict(before["by_site"])

        def _outer():                       # 造一个非 llm_client 的调用帧
            _mark_response("m", "length", 32768)

        _outer()
        _mark_response("m", "stop", 100)    # 非截断 ⇒ 不计入分解
        _mark_response("m", "length", 6144)

        after = truncation_breakdown()
        assert after["by_max_tokens"].get("32768", 0) == b_bmt.get("32768", 0) + 1
        assert after["by_max_tokens"].get("6144", 0) == b_bmt.get("6144", 0) + 1
        assert after["truncated"] == before["truncated"] + 2
        assert after["calls"] == before["calls"] + 3
        # site 应指向本测试文件（栈里第一处非 llm_client 的帧）
        sites = [k for k in after["by_site"] if k not in b_bs]
        assert sites, "应新增至少一个 site"
        assert any("test_param_usage_0921" in s for s in sites), \
            "site 应指向真实调用点，实际=%r" % sites

    def test_breakdown_returns_copies(self):
        bd = truncation_breakdown()
        bd["by_max_tokens"]["__poison__"] = 1
        bd["by_site"]["__poison__"] = 1
        assert "__poison__" not in truncation_breakdown()["by_max_tokens"]
        assert "__poison__" not in truncation_breakdown()["by_site"]

    def test_get_truncation_stats_still_has_legacy_keys(self):
        st = get_truncation_stats()
        assert "calls" in st and "truncated" in st

    def test_site_capture_never_raises(self):
        from utils.llm_client import _capture_truncation_site
        assert isinstance(_capture_truncation_site(), str)


# ================================================================
# ⑦ 接线守卫：diag 里必须真有这两个块
# ================================================================
class TestWiringGuards:
    def test_collect_diag_exports_param_usage(self):
        import inspect
        import agent.orchestrator as o
        src = inspect.getsource(o.Orchestrator._collect_diag)
        assert '"param_usage": collect_param_usage(ctx, self.config)' in src
        assert '"leansearch": _summarize_leansearch(ctx, self.config)' in src

    def test_orchestrator_imports_symbol(self):
        import agent.orchestrator as o
        assert hasattr(o, "collect_param_usage")


# ================================================================
# ⑧ 报告脚本（tools/param_usage_report.py）的防错逻辑
# ================================================================
def _rep():
    import importlib
    return importlib.import_module("tools.param_usage_report")


class TestReportScript:
    def test_verdict_flags_approx_before_capped(self):
        """代理口径必须先于撞顶判定返回 —— 否则会给出错误的调参建议。"""
        r = _rep()
        it = {"used": {"n": 4, "mean": 6.0, "max": 6}, "cap": 2,
              "capped_rate": 0.0, "exact": False}
        assert "代理口径" in r.verdict_of(it)
        it2 = dict(it, exact=True, capped_rate=0.75)
        assert "频繁撞顶" in r.verdict_of(it2)

    def test_parse_truncations_old_format_degrades(self):
        """老日志（无 site= 字段）必须被识别为"无 site"，不能算成 `?` 调用点。"""
        import io as _io
        import tempfile
        r = _rep()
        d = tempfile.mkdtemp()
        p = os.path.join(d, "old.log")
        with _io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("2026-09-20 21:00:00 [MathPilot.LLMClient] WARNING: "
                    "LLM response truncated (finish_reason=length, model=m, "
                    "max_tokens=8192)\n")
            f.write("2026-09-21 17:20:15 [MathPilot.LLMClient] WARNING: "
                    "LLM response truncated (finish_reason=length, model=m, "
                    "max_tokens=6144, site=Solver@base.py:757 <- solver.py:1437)\n")
        tr = r.parse_truncations(p)
        assert tr["by_max_tokens"] == {"8192": 1, "6144": 1}
        sites = list(tr["by_site"])
        assert any("无 site 字段" in s for s in sites), sites
        assert any("Solver@base.py:757" in s for s in sites), sites

    def test_leansearch_rate_denominator_excludes_missing_field(self):
        """缺 `top_k_capped` 字段的老结果不得被算成"未撞顶"（假阴性）。"""
        r = _rep()
        old = [{"diag": {"leansearch": {"calls": 1, "hits": 5, "unique": 5}}}]
        st = r._leansearch_stats(old, top_k=5)
        assert st["top_k_capped_rate"] is None, "无字段 ⇒ 撞顶率必须是 None 而非 0"
        assert st["top_k_capped_n"] == 0
        # 但推测口径仍应报 100% 饱和
        assert st["hits_at_top_k_rate"] == 1.0
        new = [{"diag": {"leansearch": {"calls": 1, "n_queries": 1, "hits": 5,
                                       "top_k_capped": True, "calls_capped": False,
                                       "per_query": [5]}}}]
        st2 = r._leansearch_stats(new, top_k=5)
        assert st2["top_k_capped_rate"] == 1.0 and st2["top_k_capped_n"] == 1
        assert st2["calls_capped_rate"] == 0.0

    def test_end_to_end_synthetic(self):
        """完整跑一遍 build_report：含参数表 + 检索节 + 截断节。"""
        r = _rep()
        pu = collect_param_usage(
            _ctx(tier="deep", subgoal_stats={"n_subgoals": 16},
                 budget=NS(used_calls=120)), _cfg())
        rows = [{"id": "q1", "correct": True,
                 "diag": {"leansearch": {"calls": 1, "n_queries": 1, "hits": 5,
                                        "unique": 3, "per_query": [5],
                                        "top_k_capped": True, "calls_capped": False},
                          "param_usage": pu}}]
        md = r.build_report(rows, r.aggregate([pu]),
                            {"by_max_tokens": {"6144": 2}, "by_site": {"X@a.py:1": 2},
                             "n_lines": 2, "path": "x.log", "exists": True},
                            "x.jsonl", "x.log")
        assert "逐参数：实测 vs 上限" in md
        assert "max_subgoals" in md and "6144" in md
        assert "```" not in md, "md 不得含围栏代码块"
