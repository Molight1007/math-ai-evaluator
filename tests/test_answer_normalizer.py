# -*- coding: utf-8 -*-
"""4.0 答案规范化前置（五道审核链第 0 道）单测 —— 2026-10-14。

覆盖三层：
  1) ``classify_answer_kind`` 纯函数：六类形态分流（含负例）；
  2) ``normalize_stage``：挂载 / 抢救改写 / 证明题分流 / 汇总留痕 / 开关关闭；
  3) 阶段接线锚点：orchestrator 序列与收尾清单含 ``4.0_normalize``（读源守卫）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.answer_normalizer import (  # noqa: E402
    classify_answer_kind,
    normalize_stage,
)


# ----------------------------------------------------- 1) 形态分类（纯函数）
def test_classify_numeric():
    for s in ("48", "-3", "0.5", "2/3", "1e5", "25%"):
        assert classify_answer_kind(s) == "numeric", s


def test_classify_symbolic():
    for s in ("2*x+1", "sqrt(3)/2", "x^2-1", "(x+1)(x-1)", "pi/2"):
        assert classify_answer_kind(s) == "symbolic", s


def test_classify_multi():
    assert classify_answer_kind("1, 2, 3") == "multi"
    assert classify_answer_kind("A, B") == "multi"
    # 负例：长论述里的逗号不是多答案
    assert classify_answer_kind("步骤1，先设未知数，再列方程，最后求解并检验") != "multi"


def test_classify_text_and_unparseable():
    assert classify_answer_kind("该方程无解") == "text"
    assert classify_answer_kind("") == "unparseable"
    # Markdown 标题 / 过程叙述 → 非答案形态
    assert classify_answer_kind("### 选项A分析") == "unparseable"
    assert classify_answer_kind("步骤11：搜索已知结论") == "unparseable"


def test_classify_proof():
    assert classify_answer_kind("任意数值", is_proof=True) == "proof"
    # 空串优先于证明题（无内容可验）
    assert classify_answer_kind("", is_proof=True) == "unparseable"


# ----------------------------------------------------- 2) 阶段函数（桩）
class _Stub:
    def __init__(self):
        self.events = []
        self.config = type("_C", (), {"pool_empty_clear": True})()

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands, question_type="", domain=""):
        self.candidates = cands
        self.question_type = question_type
        self.domain = domain


def test_normalize_stage_attaches_fields():
    stub, ctx = _Stub(), _Ctx([Candidate(id=1, answer="48", reasoning="r")])
    normalize_stage(stub, ctx)
    c = ctx.candidates[0]
    assert c.answer_norm == "48"
    assert c.answer_kind == "numeric"
    # ★ 契约：不改 c.answer（旧链行为零变化）
    assert c.answer == "48"
    assert ctx.answer_normalize["n"] == 1
    assert ctx.answer_normalize["kinds"] == {"numeric": 1}
    assert any(k == "answer_normalize" for k, _ in stub.events)


def test_normalize_stage_salvages_sentence_form():
    # 「先抢救、再判定」内核：句子形态含明确最终值 ⇒ 抽出该值
    stub, ctx = _Stub(), _Ctx(
        [Candidate(id=1, answer="所以最小 d 是 48。", reasoning="r")])
    normalize_stage(stub, ctx)
    c = ctx.candidates[0]
    assert c.answer_norm == "48", c.answer_norm
    assert c.answer_kind == "numeric"
    assert ctx.answer_normalize["n_salvaged"] == 1
    # 原 answer 不被改写
    assert c.answer == "所以最小 d 是 48。"


def test_normalize_stage_proof_routing():
    stub, ctx = _Stub(
        ), _Ctx([Candidate(id=1, answer="由归纳法可证", reasoning="r")],
                question_type="证明题")
    normalize_stage(stub, ctx)
    assert ctx.candidates[0].answer_kind == "proof"
    assert ctx.answer_normalize["is_proof"] is True


def test_normalize_stage_empty_pool():
    stub, ctx = _Stub(), _Ctx([])
    normalize_stage(stub, ctx)
    assert not hasattr(ctx, "answer_normalize") or not ctx.answer_normalize
    assert any("候选池为空" in m for _, m in stub.events)


def test_unparseable_candidates_removed():
    # 2026-10-14：不可判形态（Markdown/过程叙述/空答案）在 4.0 即剔除
    # （承接旧链 4_verify `_verify_filter_candidates` 的过滤职责）
    stub, ctx = _Stub(), _Ctx([
        Candidate(id=1, answer="### 选项A分析", reasoning="r"),
        Candidate(id=2, answer="48", reasoning="r"),
    ])
    normalize_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [2]
    assert any("剔除不可判形态候选" in m for _, m in stub.events)


def test_all_unparseable_pool_cleared_by_default():
    stub, ctx = _Stub(), _Ctx([
        Candidate(id=1, answer="### 标题", reasoning="r"),
        Candidate(id=2, answer="步骤11：搜索已知结论", reasoning="r"),
    ])
    normalize_stage(stub, ctx)
    assert ctx.candidates == []          # pool_empty_clear=True（默认）⇒ 清空
    assert any("已清空" in m for _, m in stub.events)


def test_all_unparseable_kept_when_switch_off():
    stub, ctx = _Stub(), _Ctx([Candidate(id=1, answer="### 标题", reasoning="r")])
    stub.config.pool_empty_clear = False
    normalize_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert any("保留原池" in m for _, m in stub.events)


def test_normalize_stage_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_NORMALIZE", "0")
    stub, ctx = _Stub(), _Ctx([Candidate(id=1, answer="48", reasoning="r")])
    normalize_stage(stub, ctx)
    c = ctx.candidates[0]
    assert not hasattr(c, "answer_norm")
    assert any("开关关闭" in m for _, m in stub.events)


def test_normalize_stage_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

    stub = _Stub()
    normalize_stage(stub, _Boom())  # 不得抛异常（增益环节绝不阻断主链）
    assert any("异常" in m for _, m in stub.events)


# ----------------------------------------------------- 3) 接线锚点（读源守卫）
def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    # 阶段序列：3.4_collab 之后、6_format 之前调用（规范化先于一切检测）
    i_collab = src.index('self._stage_start(ctx, "3.4_collab")')
    i_norm = src.index('self._stage_start(ctx, "4.0_normalize")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_collab < i_norm < i_fmt
    # 收尾清单同样登记（否则阶段计时永不 stop）
    assert '"4.0_normalize",' in src
