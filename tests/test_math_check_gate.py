# -*- coding: utf-8 -*-
"""4.4 数学工具计算检测（五道审核链第 4 道）单测 —— 2026-10-14。

覆盖：fail 淘汰 / unknown 放行 / 全拒回退保留 / 异常放行 / answer_norm 优先 /
开关关闭 / 接线锚点。DeterministicChecker 以注入桩替代（`self.math_check_det`）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.math_check_gate import math_check_stage  # noqa: E402


class _Det:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def check_answer(self, ctx, problem, answer, domain=None):
        self.calls.append(answer)
        r = self.seq.pop(0) if self.seq else {"verdict": "unknown"}
        if isinstance(r, Exception):
            raise r
        return r


class _Stub:
    def __init__(self, det=None):
        self.events = []
        self.config = type("_C", (), {})()
        self.math_check_det = det or _Det()

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "求 x"
        self.domain = ""
        self.candidates = cands


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理")


def test_fail_rejected_unknown_kept():
    det = _Det([
        {"verdict": "fail", "method": "substitution", "evidence": "回带不成立"},
        {"verdict": "unknown", "method": "parse", "evidence": "无法解析"},
        {"verdict": "pass", "method": "substitution", "evidence": "回带成立"},
    ])
    stub = _Stub(det)
    ctx = _Ctx([_c(1), _c(2), _c(3)])
    math_check_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [2, 3]
    assert ctx.math_check["n_rejected"] == 1
    assert ctx.math_check["n_unknown"] == 1
    assert ctx.math_check_rejected[0]["method"] == "substitution"
    assert any("计算检测" in fb for fb in ctx.audit_reject_feedback)


def test_all_fail_clears_pool_no_fallback():
    """★ 2026-10-18（p0b5_r4：010/013/017 三题受害）：全算错不再回退。

    原「全 fail ⇒ 回退保留」会把工具③已证明算错的候选放回投票池
    （010 的正确结果 2 被算出，却因回退选了 0）。用户口径「不要隐藏错误」
    ⇒ 全拒即清空池、把证据写进 audit_reject_feedback 供 4.6 重写使用。
    """
    det = _Det([
        {"verdict": "fail", "method": "substitution", "evidence": "e1"},
        {"verdict": "fail", "method": "parse", "evidence": "e2"},
    ])
    stub = _Stub(det)
    ctx = _Ctx([_c(1), _c(2)])
    math_check_stage(stub, ctx)
    assert ctx.candidates == []                          # 不回退
    assert ctx.math_check["all_rejected_fallback"] is False
    assert ctx.math_check["rejected_ids"] == [1, 2]
    assert any("全部算错" in m for _, m in stub.events)
    fb = getattr(ctx, "audit_reject_feedback", None) or []
    assert any("计算检测" in str(x) for x in fb)          # 证据进重写反馈


def test_exception_treated_unknown():
    det = _Det([RuntimeError("boom")])
    stub = _Stub(det)
    ctx = _Ctx([_c(1)])
    math_check_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.math_check["n_rejected"] == 0


def test_answer_norm_preferred():
    det = _Det([{"verdict": "pass", "method": "substitution", "evidence": "ok"}])
    stub = _Stub(det)
    c = _c(1, ans="所以最小 d 是 48。")
    c.answer_norm = "48"
    ctx = _Ctx([c])
    math_check_stage(stub, ctx)
    assert det.calls == ["48"]


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_MATH_CHECK", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    math_check_stage(stub, ctx)
    assert stub.math_check_det.calls == []
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    math_check_stage(stub, ctx)
    assert stub.math_check_det.calls == []


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    math_check_stage(stub, _Boom())
    assert any("异常" in m for _, m in stub.events)


def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_lc = src.index('self._stage_start(ctx, "4.3_lean_check")')
    i_mc = src.index('self._stage_start(ctx, "4.4_math_check")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_lc < i_mc < i_fmt
    assert '"4.4_math_check",' in src


# ===================================================== 2026-10-21 工具③证据快照
# 背景：med2_r1 上 4.4 把 13 个候选全清空，但 trace 只留判词、candidate.reasoning
# 不落盘 ⇒ 事后无法区分「真算错」和「提取误伤」。以下用例锁死「证据必须可归因」。

from agent.math_check_gate import (  # noqa: E402
    _SNAP_ITEMS_MAX, _build_calc_snapshot, _extract_numeric_equations)


def _c_r(i, reasoning, ans="4"):
    return Candidate(id=i, answer=ans, reasoning=reasoning)


def test_snapshot_records_extracted_items():
    """算错的候选：快照必须留下「提取到哪条式子、实际值多少」。"""
    stub = _Stub()
    ctx = _Ctx([_c_r(7, "由 20 × 3 = 60，且 2 + 2 = 5，故答案为 4")])
    math_check_stage(stub, ctx)
    assert ctx.candidates == []                       # 工具③淘汰
    snap = ctx.math_calcverify_gate
    assert snap["n_checked"] == 1 and snap["n_rejected"] == 1
    cand = snap["candidates"][0]
    assert cand["id"] == 7 and cand["n_items"] == 2
    assert cand["n_eq"] == 2 and cand["n_ineq"] == 0
    assert cand["n_bad"] == 1 and cand["n_ok"] == 1
    bad = [x for x in cand["items"] if not x["ok"]]
    assert len(bad) == 1
    assert bad[0]["expr"].replace(" ", "") == "2+2"
    assert bad[0]["claimed"] == "5" and bad[0]["actual"] == "4"
    assert "算错" in bad[0]["detail"]


def test_snapshot_clean_candidate_kept():
    """式子全对 ⇒ 放行，快照仍留痕（n_bad=0），便于对比到底哪类题被误杀。"""
    det = _Det([{"verdict": "pass", "method": "substitution", "evidence": "ok"}])
    ctx = _Ctx([_c_r(1, "我们有 20 × 3 = 60，答案 4")])
    math_check_stage(_Stub(det), ctx)
    assert [c.id for c in ctx.candidates] == [1]
    cand = ctx.math_calcverify_gate["candidates"][0]
    assert cand["n_items"] == 1 and cand["n_bad"] == 0 and cand["n_ok"] == 1


def test_no_extract_counted():
    """提取不到式子时要显式计数，不能静默当成「检查过且通过」。"""
    det = _Det([{"verdict": "pass", "method": "substitution", "evidence": "ok"}])
    ctx = _Ctx([_c_r(1, "推理"), _c_r(2, "另一段推理")])
    math_check_stage(_Stub(det), ctx)
    mc = ctx.math_check
    assert mc["n_cv_no_extract"] == 2
    assert ctx.math_calcverify_gate["n_no_extract"] == 2
    assert ctx.math_calcverify_gate["candidates"] == []


def test_n_by_method_autogroups():
    """淘汰来源自动分组（不写死枚举）：calc_verify 与 substitution 各 1。

    ⚠ 注意执行顺序：`check_answer` 在工具③**之前**对每个候选都会调一次，
      所以检测桩按候选顺序消费 —— cid=1 的返回值被工具③淘汰后丢弃。
    """
    det = _Det([{"verdict": "unknown"},
                {"verdict": "fail", "method": "substitution", "evidence": "e"}])
    ctx = _Ctx([_c_r(1, "2 + 2 = 5"), _c_r(2, "推理")])
    math_check_stage(_Stub(det), ctx)
    assert ctx.math_check["n_by_method"] == {"calc_verify": 1, "substitution": 1}
    assert ctx.math_check["n_rejected"] == 2


def test_snapshot_items_bounded():
    """快照条数有上限，但 n_items 报真实提取总数（不能把截断当前提）。"""
    _n = _SNAP_ITEMS_MAX + 4          # 必须超过上限才测得到截断
    items = [{"expr": "1+%d" % i, "claimed": str(i + 1)} for i in range(_n)]
    rv = {"n_ok": _n, "n_bad": 0, "n_err": 0,
          "results": [{"expr": it["expr"], "claimed": it["claimed"],
                       "actual": it["claimed"], "ok": True, "detail": "一致"}
                      for it in items]}
    snap = _build_calc_snapshot(3, "numeric", items, rv)
    assert snap["n_items"] == _n and len(snap["items"]) == _SNAP_ITEMS_MAX


def test_snapshot_keeps_bad_items_when_truncated():
    """裁剪必须保语义：坏证据优先保留（mc075 实测 5 条坏证据被 `rows[:8]` 截掉）。"""
    items = [{"expr": "1+%d" % i, "claimed": str(i + 1)} for i in range(_SNAP_ITEMS_MAX + 4)]
    results = [{"expr": it["expr"], "claimed": it["claimed"],
                "actual": it["claimed"], "ok": True, "detail": "一致"}
               for it in items]
    # 末尾两条是坏证据（最容易在下标截断中被丢）
    for k in (-1, -2):
        results[k] = {"expr": items[k]["expr"], "claimed": items[k]["claimed"],
                      "actual": "999", "ok": False, "detail": "**算错**：正确结果是 999"}
    snap = _build_calc_snapshot(3, "numeric", items,
                                {"n_ok": len(items) - 2, "n_bad": 2, "n_err": 0,
                                 "results": results})
    assert len(snap["items"]) == _SNAP_ITEMS_MAX
    assert sum(1 for x in snap["items"] if not x["ok"]) == 2


def test_evidence_fallback_when_detail_lacks_keywords(monkeypatch):
    """判词不含「算错/不成立」时也要留证据（原实现会记空字符串）。"""
    import importlib
    # 包 `__init__` 把 `calc_verify` 这个名字再导出成函数，`import ... as` 会拿到
    # 函数而非模块 ⇒ 必须走 importlib 拿模块本体。
    _mod = importlib.import_module("tools.agent_toolkit.calc_verify")

    def _fake(items, **kw):
        # `**kw` 收 `constraints`（4.4 现会把题干前提传进来）
        return {"ok": False, "n_ok": 0, "n_bad": 1, "n_err": 0,
                "results": [{"expr": items[0]["expr"],
                             "claimed": items[0]["claimed"],
                             "actual": "?", "ok": False,
                             "detail": "自定义不一致判词"}]}

    monkeypatch.setattr(_mod, "calc_verify", _fake)
    ctx = _Ctx([_c_r(1, "2 + 2 = 5")])
    math_check_stage(_Stub(), ctx)
    assert ctx.candidates == []
    assert ctx.math_check_rejected[0]["evidence"] == "自定义不一致判词"


def test_snapshot_exported_in_diag():
    """diag 导出必须带上快照，否则结果文件里看不到（等于白加埋点）。"""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "diag_export.py"), encoding="utf-8").read()
    assert '"math_calcverify_gate"' in src


def test_extract_separates_equations_from_inequalities():
    """等式与不等式分别计数——「哪一类在误杀」是归因的关键分支。"""
    eqs = _extract_numeric_equations("于是 20 * 3 = 60")
    assert eqs and eqs[0][0].replace(" ", "") == "20*3"


def test_report_summary_shows_method_breakdown():
    """报表摘要必须点出「淘汰来自哪条通道」，否则归因会认错环节。"""
    from cli.test_report import _fmt_math_by
    s = _fmt_math_by({"n_rejected": 9, "n_unknown": 0, "n_cv_no_extract": 0,
                      "n_by_method": {"calc_verify": 9}})
    assert "逐式复算9" in s and "淘汰=9" in s
    # 旧结果文件没有 n_by_method ⇒ 退回两项口径
    assert _fmt_math_by({"n_rejected": 1, "n_unknown": 2}) == "淘汰=1（无法判定2）"
    assert _fmt_math_by({}) == "淘汰=—（无法判定—）"


# ============================================ 2026-10-21 提取层重写（mc075_r1 根因）
# 下面五条原文全部取自 `diag.subgoal_trace[3].candidates[0]` 的真实推理 ——
# 旧提取器在这五条上分别产出：链式错位片段 / 假不等式 / 截断右值，
# 导致 `P(x)=x-4`（正确答案）被判「算错」淘汰。

from agent.math_check_gate import (  # noqa: E402
    _extract_inequalities, _normalize_math)
from tools.agent_toolkit.calc_verify import calc_verify as _cv  # noqa: E402


def _verify(txt):
    eqs = _extract_numeric_equations(txt)
    ineqs = _extract_inequalities(txt)
    items = [{"expr": a, "claimed": b} for a, b in eqs]
    items += [{"expr": a, "claimed": b, "op": o} for a, b, o in ineqs]
    if not items:
        return items, {"n_ok": 0, "n_bad": 0, "n_err": 0}
    return items, _cv(items)


def test_chain_equations_verified_not_sliced():
    """★ 本轮核心：`a=b=c=d` 必须**逐对判等**，不能被切成错位片段判「算错」。"""
    for txt in ("$D(1)=0!-6(-1)^0=1-6=-5$",
                "$D(2)=1!-6(-1)^1=1+6=7$",
                r"$D(4)=6-6(-1)^3=6+6=12=2^2\cdot3$"):
        items, rv = _verify(txt)
        assert items, txt
        assert rv["n_bad"] == 0, (txt, items, rv)


def test_chain_yields_adjacent_pairs():
    """链式的相邻对是「按运算符双向扩段」的天然产物，不需要链式特判。"""
    eqs = _extract_numeric_equations(r"$6+6=12=2^2\cdot3$")
    assert ("6+6", "12") in eqs and ("12", "2^2*3") in eqs


def test_xml_tag_not_taken_as_inequality():
    """`</check>` 里的 `<` 不得被当小于号（旧实现产出 `('12','/check','lt')`）。"""
    items, rv = _verify("<check>D(3) = 2 - 6 = -4</check>")
    assert [i for i in items if i.get("op")] == []
    assert rv["n_bad"] == 0


def test_cross_punctuation_not_glued():
    """两个独立命题不能被焊成一条假式子（旧实现：`('5  x^2-1','0','ge')`）。"""
    ineqs = _extract_inequalities("由 2 + 2 = 5，另 x^2-1 >= 0")
    assert ("x^2-1", "0", "ge") in ineqs
    assert not any("5  x" in a or "5 x" in a for a, _, _ in ineqs)


def test_latex_command_does_not_truncate_rhs():
    """`12=2^2\\cdot3` 的右值必须完整（旧实现只取到 `2`）。"""
    assert ("12", "2^2*3") in _extract_numeric_equations(r"于是 12=2^2\cdot3")


def test_real_mistake_still_rejected():
    """★ 防「修成漏检」：真算错的式子必须仍判 n_bad（否则工具③成摆设）。"""
    _, rv = _verify("由 20 × 3 = 60，且 2 + 2 = 5，故答案为 4")
    assert rv["n_bad"] == 1


def test_assignment_not_extracted():
    """`x = 3` 是赋值不是算术，提取器必须拒收。"""
    assert _extract_numeric_equations("设 x = 3") == []


def test_pure_condition_not_extracted():
    """题面条件 `n >= 2` 不提取（否则候选会因"违反条件"被误杀）。"""
    assert _extract_inequalities("其中 n >= 2") == []


def test_symbolic_inequality_still_detected():
    """017 型能力不能丢：符号不等式仍要提取并判出反例。"""
    ineqs = _extract_inequalities("由 a^2+3b^2 >= 4|a||b|^3 可得")
    assert ineqs and ineqs[0][2] == "ge"
    _, rv = _verify("由 a^2+3b^2 >= 4|a||b|^3 可得")
    assert rv["n_bad"] == 1


def test_conditional_inequality_not_false():
    """★ 2026-10-21：前提为 `q>=1` 的真命题 `q^2-1 >= 0` 不得被判 False。

    旧实现「全正区」取样是 `Rational(1..5, 1..3)`，含 1/2 这类小于 1 的正
    有理数 ⇒ q=1/2 时 -0.75 < 0 ⇒ 直接判 False ⇒ 候选被淘汰（实测误杀）。
    """
    from tools.agent_toolkit.calc_verify import _verify_inequality
    assert _verify_inequality("q^2-1", "0", "ge") is not False


def test_numeric_inequality_counterexample_kept():
    """防「修成漏检」：**两侧共享变量**的代数关系仍须靠代值抓反例（017 型）。

    ★ 2026-10-26 换样本（原断言是 `_verify_inequality("x^2","4","ge") is False`）：
      单侧符号 vs 纯常量属于**界限陈述**（见下条测试），量词缺失时不可判假。
      原断言把「存在反例」当成「断言为假」，只在命题隐含全称量词时才成立——
      对 `a^2+3b^2 >= 4|a||b|^3` 这种双侧共享变量的代数关系成立，对
      `x^2 >= 4` / `|f| <= 1` 不成立。017 型的检出能力由本条守住。
    """
    from tools.agent_toolkit.calc_verify import _verify_inequality
    assert _verify_inequality("a^2+3*b^2", "4*Abs(a)*Abs(b)^3", "ge") is False


def test_bound_statement_is_not_judged_false():
    """★ 2026-10-26 离线回放床实测：`|f| <= 1` 型**界限陈述**不得判假。

    两侧不共享自由符号 ⇒ 一侧是纯数值/另一侧是符号，量词未知
    （可能是「存在 M 使 …」，不是「对任意 …」）。代值 f=2 得到的反例
    只是工具凭空假设的函数，不构成反例。

    实测代价（official112-088 / 094，候选 **全部** 被判死 ⇒ 池清空 ⇒ 4.6 重写）：
      088 原文：`定义 f(x)=1 若 x∈E，f(x)=0 若 x∉E。则 f 有界（$|f| \\leq 1$），
                但 f 不可测` —— 完全正确（gold=AB），被判「不等式不成立」。
      094 原文：Cauchy 数列有界性 `|a_n| <= M` —— 完全正确（gold=BCD），同判死。
    """
    from tools.agent_toolkit.calc_verify import _verify_inequality
    assert _verify_inequality("Abs(f)", "1", "le") is None
    assert _verify_inequality("Abs(a)", "M", "le") is None
    assert _verify_inequality("x^2", "4", "ge") is None


def test_bound_statement_salvaged_by_premise():
    """界限陈述一旦题设交代了取值域 ⇒ 恢复代值判定（约束覆盖即合法）。"""
    from agent.math_check_gate import _extract_conditions
    from tools.agent_toolkit.calc_verify import _verify_inequality
    c = _extract_conditions(r"let $x \ge 2$ be an integer")
    assert _verify_inequality("x^2", "4", "ge") is None                # 无前提 ⇒ 不判
    assert _verify_inequality("x^2", "4", "ge", constraints=c) is not False


def test_inequality_sampling_is_deterministic():
    """正整数区改为确定性枚举 —— 同一候选两次运行必须同结论（可复现）。"""
    from tools.agent_toolkit.calc_verify import _verify_inequality
    rs = {_verify_inequality("q^2-1", "0", "ge") for _ in range(5)}
    assert len(rs) == 1


def test_extract_conditions_bilingual():
    """题干前提中英文都要提成单符号 —— 英文段会把散文吞进来（`'let  d'`）。"""
    from agent.math_check_gate import _extract_conditions
    for txt in (r"let $d \ge 2$ be its degree, and $q \ge 1$ be prime",
                "设次数 $d \\ge 2$，且 $q \\ge 1$ 为素数"):
        cs = _extract_conditions(txt)
        assert {"expr": "d", "op": "ge", "claimed": "2"} in cs
        assert {"expr": "q", "op": "ge", "claimed": "1"} in cs


def test_extract_conditions_rejects_propositions():
    """带运算的段是命题不是前提（`d-1 >= 0` 不得被修剪成条件 `1 >= 0`）。"""
    from agent.math_check_gate import _extract_conditions
    assert _extract_conditions("由 d-1 >= 0 可得") == []


def test_conditional_inequality_respects_premise():
    """★ 前提 d>=2 时 `x^(d-1) >= x` 不得被 d=1 的越界反例判死（实测误杀 3 次）。"""
    from agent.math_check_gate import _extract_conditions
    from tools.agent_toolkit.calc_verify import _verify_inequality
    c = _extract_conditions(r"let $d \ge 2$ be its degree")
    assert c == [{"expr": "d", "op": "ge", "claimed": "2"}]
    assert _verify_inequality("x^(d-1)", "x", "ge") is False          # 无前提
    assert _verify_inequality("x^(d-1)", "x", "ge", constraints=c) is not False


def test_premise_does_not_weaken_real_counterexample():
    """约束只过滤越界点：`x^(d-1)>=x` 在 d>=2 下为真，但无前提时 d=1 仍是反例。

    ★ 2026-10-26 换样本（原样本 `x^2>=4` 是界限陈述，现归 None，见上条测试）。
      本条守的是「constraints 只裁剪越界点、不削弱双侧共享变量的真反例」。
    """
    from agent.math_check_gate import _extract_conditions
    from tools.agent_toolkit.calc_verify import _verify_inequality
    c = _extract_conditions(r"let $d \ge 2$ be its degree")
    assert _verify_inequality("x^(d-1)", "x", "ge") is False
    assert _verify_inequality("x^(d-1)", "x", "ge", constraints=c) is not False


def test_normalize_separates_chinese_by_sentinel():
    """中文用哨兵隔断（不是空格）——用空格会把相邻两句的算式粘成一段。"""
    s = _normalize_math("$a=1$，故 b=2")
    assert "$" not in s and "\x00" in s



# ---------------------------------------------------------------- 2026-10-22
# mc075 实测：三条**正确答案**（P(x)=x-4）被 4.4 淘汰，池空后重写仍全灭，
# 最终输出「未给出有效解答」。三类根因各留一条夹具，防回退。
def test_neq_is_not_factorial_marker():
    """`\\neq` 不能归一成 `!=`：`!` 是段内合法字符，会把右值扩成 `6!`。

    实测原文 `$k=2$：$6(-1)^2=6\\neq 1!=1$` 被切成 `6(-1)^2` = `6!`
    ⇒ sympy 算 6 vs 720 ⇒ 整条正确候选被判"算错"。
    """
    eqs = _extract_numeric_equations(r"检验 $k=2$：$6(-1)^2=6\neq 1!=1$")
    assert ("6(-1)^2", "6") in eqs
    assert not any("!" in r for _, r in eqs), eqs


def test_factorial_then_equals_is_parsed_as_factorial():
    """`2!=2` / `(4-1)!=6` 是「阶乘 + 等号」，不是不等号。"""
    s = _normalize_math("2!=2 且 (4-1)!=6")
    assert "factorial(2)" in s and "<>" not in s


def test_true_neq_still_separates_operands():
    """真不等号仍要切断：`a != b` 不得被粘连成一个段。"""
    assert "<>" in _normalize_math("a != b")


def test_undefined_function_call_rejected_from_inequality():
    """`Abs(P(q)) > q` 里 `P(q)` 是函数应用，sympy 当乘法 `P*q` ⇒ 代值结论无意义。"""
    assert _extract_inequalities("由 $|P(q)|>q$ 导致矛盾") == []
    # 白名单函数与 017 型符号不等式不受影响
    assert _extract_inequalities("由 a^2+3b^2 >= 4|a||b|^3 可得")


def test_negated_sentence_is_not_treated_as_claim():
    """`$1!=-6(-1)=6$ 不成立` 是模型在否定该等式，不能当"声称成立"判 bad。

    否定作用于整句：链式拆出的**每一对**都要丢弃（只判"右值后紧跟否定词"
    会漏掉链中间那对，实测残留 `factorial(1)=-6(-1)`）。
    """
    eqs = _extract_numeric_equations(r"对 $k=1$：$1!=-6(-1)=6$ 不成立；$k=2$：$2!=-6(1)=-6$ 不成立")
    assert eqs == []


def test_negation_marker_does_not_swallow_next_sentence():
    """否定词只作用于本句，下一句的等式照常提取。"""
    eqs = _extract_numeric_equations(r"$1!=9$ 不成立；$2+2=4$ 成立")
    assert ("2+2", "4") in eqs and ("1", "9") not in eqs


# ---------------------------------------------------------------- 2026-10-26
# 离线回放床（replay_calc_gate.py）在历史 reasoning 上扫出的两条**假证据**：
# 判死的理由是「算错」，但实际是提取器把数值切坏了。答案也恰好是错的，
# 所以 hard_kill 抓不到 —— 但只要同类出现在答案正确的候选上就是硬误杀。
def test_thousands_separator_is_stripped():
    """`1,018,080` 的千分位逗号不在段字符集里 ⇒ 右值只抓到 `1`。

    实测原文：`- = 1008 * 1010 = 1,018,080`
    旧提取：`('1008 * 1010', '1')` ⇒ sympy 算 1018080 ≠ 1 ⇒ 判「算错」。
    """
    eqs = _extract_numeric_equations("- = 1008 * 1010 = 1,018,080")
    assert ("1008 * 1010", "1018080") in eqs
    assert not any(r == "1" for _, r in eqs), eqs
    # 逗号作并列分隔（后有空格）不得被吞
    assert _normalize_math("得到 1, 2, 3 三个值").count(",") == 2


def test_unknown_latex_command_does_not_truncate_operand():
    """未识别的 LaTeX 命令（`\\beta`）里 `\\` 不在段字符集 ⇒ 右值在 `Abs(` 处截断。

    实测原文：`5^{1/4} = |\\beta|`
    旧提取：`('5^(1/4)', 'Abs')` ⇒ 判「算错：正确结果是 5**(1/4)（声称 Abs）」。
    修法把命令转成名字，该段含裸字母 ⇒ 整条拒收（少一条证据，不误判）。
    """
    r = r"故 $5^{1/4} = |\beta|$，且 $\alpha = 3$"
    assert _extract_numeric_equations(r) == []
    # 白名单命令不受影响
    assert ("2^2* 3", "12") in _extract_numeric_equations(r"所以 $2^2\cdot 3 = 12$")
    assert _extract_numeric_equations(r"由 $\frac{1}{2}+\frac{1}{3} = \frac{5}{6}$")


# ---------------------------------------------------------------- 2026-10-26
# 回放床 + 人工标注（results/calc_gate_labels_1026.json）定位的四类形态。
# 34 条判死里这四类占 19 条，且全部是「工具读错」而不是「模型算错」。
def test_markdown_list_bullet_is_not_unary_minus():
    """`- $100\\times 18=1800$` 的 `- ` 是列表符号，不是负号。

    旧提取：`('-  100* 18', '1800')` ⇒ sympy 算 -1800 ≠ 1800 ⇒ 判算错
    ⇒ 消灭正确候选（同题 5 条候选全灭）。34 条判死里 10 条是这个形态。
    """
    assert ("100* 18", "1800") in _extract_numeric_equations(r"- $100\times 18=1800$")
    # 真负号不受影响：`-5`（不贴空格）仍是负号
    assert ("-5", "-5") in _extract_numeric_equations("-5 = -5")
    assert ("1 - 6", "-5") in _extract_numeric_equations("1 - 6 = -5")


def test_nth_root_is_kept_whole():
    """`\\sqrt[4]{5}` 的 `[4]` 旧实现原样留下 ⇒ 左段在 `[` 处截断。

    实测原文 `(\\sqrt[4]{5})^2 = \\sqrt{5}` 旧提取成 `('2', 'sqrt(5)')`
    ⇒ 判「算错：2 ≠ √5」⇒ 消灭正确候选。34 条判死里 5 条是这个族。
    """
    eqs = _extract_numeric_equations(r"(\sqrt[4]{5})^2 = \sqrt{5}")
    assert eqs and eqs[0][1] == "sqrt(5)"
    assert "sqrt" not in eqs[0][0].split("^")[0] or "5" in eqs[0][0], eqs
    assert ("((8)^(1/(3)))", "2") in _extract_numeric_equations(r"\sqrt[3]{8} = 2")


def test_remainder_notation_does_not_produce_false_alarm():
    """`1010 \\div 3 = 336 余 2`：余数不是等号右值，机械复算表达不了。

    旧提取：`('1010 / 3', '336')` ⇒ 336.67 ≠ 336 ⇒ 判算错。整句丢弃。
    `\\text{ 余 }` 写法同样要接住（`\\text{}` 剥除会让信号消失）。
    """
    assert _extract_numeric_equations("1010 ÷ 3 = 336 余 2") == []
    assert _extract_numeric_equations(r"故 1010 \div 3 = 336 \text{ 余 } 2") == []
    # 普通 `\\text{}` 里的说明文字仍照常剥成空格，不影响同句其它算式
    assert ("2+2", "5") in _extract_numeric_equations(r"先算 \text{这一步}，然后 2+2=5")


def test_base_subscript_is_not_stripped():
    """`8 = 1000_2` 的 `_2` 是二进制记法，下标剥离会把它抹成 `8 = 1000`。

    Unicode 下标记法 `1000₂` 同义，且在段字符集之外（会截断左段）。
    两者都整句丢弃 —— 不做进制求值（要另建一套字面量语义）。
    """
    assert _extract_numeric_equations("8 = 1000_2") == []
    assert _extract_numeric_equations("8 = 1000₂") == []


def test_classifier_between_numbers_is_not_a_separator():
    """`17个100=1700` 的「个」是量词，不是分隔符（语义是 17×100）。

    只认**量词表**：`60，且 2+2=5` 是两个独立命题，后者是真错误必须留检
    （放宽到任意中文时，`test_real_mistake_still_rejected` 立刻失败）。
    """
    assert _extract_numeric_equations("17个100=1700") == []
    assert _extract_numeric_equations("17 个 100 = 1700") == []
    # 独立命题不受影响：真错误仍被提取
    assert ("2 + 2", "5") in _extract_numeric_equations("由 2 + 2 = 5，且 20 × 3 = 60")
    assert ("2+2", "5") in _extract_numeric_equations("第2次 2+2=5")
