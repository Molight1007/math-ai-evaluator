# -*- coding: utf-8 -*-
"""4.2 AI 对抗证伪（五道审核链第 2 道）单测 —— 2026-10-14。

覆盖：机检/LLM 两层淘汰、故障保留纪律、开关关闭、池空留痕、接线锚点。
证伪器与对抗器均以注入桩替代（`adv_gate_falsifier` / `adv_verifier`），不触发真实 LLM。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.adversarial_gate import adversarial_gate_stage  # noqa: E402


# ----------------------------------------------------- 桩
class _Res:
    def __init__(self, incorrect=False, reason="", witness="", oracle_type=""):
        self.is_incorrect = incorrect
        self.reason = reason
        self.witness = witness
        self.oracle_type = oracle_type


class _PRes:
    def __init__(self, actionable=False, skipped="", error_type="",
                 confidence=0.6, feedback=""):
        self.is_actionable = actionable
        self.skipped = skipped
        self.error_type = error_type
        self.confidence = confidence
        self._fb = feedback

    def to_feedback(self):
        return self._fb


class _Falsifier:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def falsify(self, ctx, c, problem=""):
        self.calls.append(getattr(c, "id", None))
        r = self.seq.pop(0) if self.seq else _Res()
        if isinstance(r, Exception):
            raise r
        return r


class _Prober:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def probe(self, ctx, c, tier="deep"):
        self.calls.append(getattr(c, "id", None))
        r = self.seq.pop(0) if self.seq else _PRes()
        if isinstance(r, Exception):
            raise r
        return r


class _Stub:
    def __init__(self, falsifier=None, prober=None):
        self.events = []
        self.client = None

        class _C:  # config 桩
            pass
        self.config = _C()
        self.adv_gate_falsifier = falsifier or _Falsifier()
        self.adv_verifier = prober or _Prober()

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "测试题"
        self.candidates = cands
        self.metadata = {}


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理")


# ----------------------------------------------------- 1) 机检证伪
def test_machine_falsified_rejected_and_probe_skipped():
    f = _Falsifier([_Res(incorrect=True, reason="回带不成立", witness="f(2)=5≠7",
                         oracle_type="sympy")])
    p = _Prober()
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [2]         # 1 被判错淘汰
    assert p.calls == [2]                                # 机检已判错的候选不再 LLM 探测
    assert ctx.adversarial_gate["n_machine"] == 1
    assert ctx.adversarial_gate_rejected[0]["witness"] == "f(2)=5≠7"
    assert any("对抗证伪·机检" in fb for fb in ctx.audit_reject_feedback)
    # 既有契约：机检被证伪答案进 _falsified_answers
    assert ctx._falsified_answers == ["48"]
    assert ctx.metadata["falsified_answers"] == ["48"]


# ----------------------------------------------------- 2) LLM 对抗
def test_llm_probe_falsified_rejected():
    f = _Falsifier([_Res(), _Res()])
    p = _Prober([
        _PRes(actionable=True, error_type="前提不成立", confidence=0.8,
              feedback="[对抗式审查] 检出「前提不成立」"),
        _PRes(),
    ])
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [2]
    assert ctx.adversarial_gate["n_llm"] == 1
    assert any("对抗证伪·LLM" in fb for fb in ctx.audit_reject_feedback)
    # LLM 对抗不作机检证伪 ⇒ 不进 _falsified_answers
    assert not getattr(ctx, "_falsified_answers", None)


# ----------------------------------------------------- 3) 故障与跳过纪律
def test_faults_keep_candidates():
    f = _Falsifier([RuntimeError("boom"), _Res()])
    p = _Prober([_PRes(skipped="empty_reasoning"), _PRes()])
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    # 候选 1：机检异常 + 探测跳过 ⇒ 保留；候选 2：全通过 ⇒ 保留
    assert [c.id for c in ctx.candidates] == [1, 2]
    assert ctx.adversarial_gate["n_rejected"] == 0
    assert ctx.adversarial_gate["n_failed"] == 1
    assert ctx.adversarial_gate["n_skipped"] == 1


# ----------------------------------------------------- 4) 开关与空池
def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_FALSIFY", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert stub.adv_gate_falsifier.calls == []
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    adversarial_gate_stage(stub, ctx, "deep")
    assert any("候选池为空" in m for _, m in stub.events)


def test_all_rejected_pool_empty_recorded():
    f = _Falsifier([_Res(incorrect=True, reason="r", witness="w")])
    stub = _Stub(f, _Prober())
    ctx = _Ctx([_c(1)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert ctx.candidates == []
    assert any(k == "pool_empty" for k, _ in stub.events)


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    adversarial_gate_stage(stub, _Boom(), "deep")  # 不得抛异常
    assert any("异常" in m for _, m in stub.events)


# ----------------------------------------------------- 5) 按来源分组统计（不写死枚举）
def test_cross_model_rejections_counted(monkeypatch):
    """跨模型淘汰必须进分项（2026-10-20 collab019_r1：淘汰 3 只报到 1）。

    现场：`cid=0`/`cid=8` 走 cross_model、`cid=12` 走 llm，日志却写
    「证伪淘汰 3（机检 0 / LLM 1）」——分项和 1 ≠ 总数 3，跨模型这条主力被漏计。
    """
    import agent.adversarial_gate as ag
    import agent.cross_model_check as cmc

    monkeypatch.setattr(ag, "_sw_get_bool", lambda name: True)
    monkeypatch.setattr(cmc, "cross_check", lambda **kw: {
        "verdict": "wrong", "evidence": "下界假设 Natasha 不干扰 2×2 块",
        "model": "deepseek-v3"})

    stub = _Stub(_Falsifier([_Res(), _Res()]), _Prober([_PRes(), _PRes()]))
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")

    g = ctx.adversarial_gate
    assert g["n_rejected"] == 2
    assert g["n_cross_model"] == 2
    assert g["n_by"] == {"cross_model": 2}
    # 核心不变量：分项和必须等于淘汰总数
    assert g["n_machine"] + g["n_llm"] + g["n_cross_model"] == g["n_rejected"]
    msg = [m for _, m in stub.events if "4.2 对抗证伪" in m][-1]
    assert "跨模型 2" in msg


def test_mixed_sources_sum_to_total(monkeypatch):
    """机检 + LLM + 跨模型混合时，三项之和仍等于淘汰总数。"""
    import agent.adversarial_gate as ag
    import agent.cross_model_check as cmc

    monkeypatch.setattr(ag, "_sw_get_bool", lambda name: True)
    monkeypatch.setattr(cmc, "cross_check", lambda **kw: {"verdict": "wrong",
                                                          "evidence": "e"})

    # c1 机检判错；c2 LLM 可行动；c3 两道放行 ⇒ 跨模型判错
    stub = _Stub(
        _Falsifier([_Res(incorrect=True, reason="r", witness="w"), _Res(), _Res()]),
        _Prober([_PRes(actionable=True, error_type="跳步", feedback="[对抗式审查] x"),
                 _PRes()]))
    ctx = _Ctx([_c(1), _c(2), _c(3)])
    adversarial_gate_stage(stub, ctx, "deep")

    g = ctx.adversarial_gate
    assert g["n_rejected"] == 3
    assert g["n_by"] == {"machine": 1, "llm": 1, "cross_model": 1}
    assert sum(g["n_by"].values()) == g["n_rejected"]


def test_report_summary_lists_all_sources():
    """报表 4.2 摘要必须列出全部分组（旧版只印机检/LLM，跨模型不可见）。"""
    from cli.test_report import _fmt_falsify_by
    assert _fmt_falsify_by({"n_rejected": 3,
                            "n_by": {"cross_model": 2, "llm": 1}}) == "跨模型2/LLM1"
    # 历史结果文件没有 n_by ⇒ 退回两项口径，不报错
    assert _fmt_falsify_by({"n_rejected": 3, "n_machine": 0,
                            "n_llm": 1}) == "机检0/LLM1"
    assert _fmt_falsify_by({}) == "机检—/LLM—"


# ----------------------------------------------------- 6) 接线锚点（读源守卫）
def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_au = src.index('self._stage_start(ctx, "4.1_self_audit")')
    i_fa = src.index('self._stage_start(ctx, "4.2_falsify")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_au < i_fa < i_fmt
    assert '"4.2_falsify",' in src
