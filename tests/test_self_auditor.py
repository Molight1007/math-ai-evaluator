# -*- coding: utf-8 -*-
"""4.1 AI 自审逻辑错误（五道审核链第 1 道）单测 —— 2026-10-14。

覆盖三层：
  1) ``parse_self_audit_json`` 容错解析（围栏 / 前后杂文 / 字符串布尔值 / 负例）；
  2) ``self_audit_stage`` 判定纪律：淘汰/保留/不可解析/LLM 故障/开关关闭；
  3) 阶段接线锚点：orchestrator 序列 4.0 → 4.1 → 3.6（读源守卫）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.self_auditor import (  # noqa: E402
    parse_self_audit_json,
    self_audit_stage,
)


# ----------------------------------------------------- 1) 容错解析（纯函数）
def test_parse_plain_json():
    d = parse_self_audit_json(
        '{"logic_error": true, "error_desc": "前提不成立", "error_at": "第2步"}')
    assert d["logic_error"] is True
    assert d["error_desc"] == "前提不成立"
    assert d["error_at"] == "第2步"


def test_parse_fenced_and_prose():
    fenced = '```json\n{"logic_error": false, "error_desc": ""}\n```'
    assert parse_self_audit_json(fenced)["logic_error"] is False
    prose = '好的，审查结果如下：\n{"logic_error": true, "error_desc": "循环论证"}\n希望有帮助'
    assert parse_self_audit_json(prose)["logic_error"] is True


def test_parse_string_truthy():
    assert parse_self_audit_json(
        '{"logic_error": "是", "error_desc": "x"}')["logic_error"] is True
    assert parse_self_audit_json(
        '{"logic_error": "false", "error_desc": ""}')["logic_error"] is False


def test_parse_negative():
    assert parse_self_audit_json("") == {}
    assert parse_self_audit_json("完全不是 JSON") == {}
    assert parse_self_audit_json('{"foo": 1}') == {}     # 缺 logic_error 键
    assert parse_self_audit_json('{"logic_error": true') == {}  # 半截 JSON


# ----------------------------------------------------- 2) 阶段判定纪律（桩）
class _Stub:
    def __init__(self, replies=None):
        self.events = []
        self.replies = list(replies or [])
        self.calls = 0

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))

    def llm(self, ctx, messages, temp, max_tokens):
        self.calls += 1
        if self.replies:
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return '{"logic_error": false, "error_desc": ""}'


class _Ctx:
    def __init__(self, cands):
        self.problem = "测试题"
        self.candidates = cands


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理过程")


def test_reject_logic_error():
    stub = _Stub([
        '{"logic_error": true, "error_desc": "结论与推理不符", "error_at": "最后一步"}',
        '{"logic_error": false, "error_desc": ""}',
    ])
    ctx = _Ctx([_c(1), _c(2)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [2]           # 1 被淘汰
    assert ctx.self_audit["n_rejected"] == 1
    assert ctx.self_audit["rejected_ids"] == [1]
    assert ctx.self_audit_rejected[0]["error_desc"] == "结论与推理不符"
    assert any("自审逻辑错误" in fb for fb in ctx.audit_reject_feedback)
    assert stub.calls == 2


def test_logic_error_without_desc_keeps_candidate():
    # 纪律：logic_error=true 但无具体描述 ⇒ 保留（无依据不淘汰）
    stub = _Stub(['{"logic_error": true, "error_desc": ""}'])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_rejected"] == 0


def test_unparsed_and_llm_fail_keep_candidates():
    stub = _Stub(["不是 JSON", RuntimeError("timeout")])
    ctx = _Ctx([_c(1), _c(2)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1, 2]        # 全部保留
    assert ctx.self_audit["n_unparsed"] == 1
    assert ctx.self_audit["n_llm_fail"] == 1


def test_uses_answer_norm_when_present():
    c = _c(1)
    c.answer_norm = "48"
    stub = _Stub()
    ctx = _Ctx([c])
    self_audit_stage(stub, ctx)
    assert stub.calls == 1
    # 正常路径不动候选
    assert ctx.candidates == [c]


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert stub.calls == 0
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    self_audit_stage(stub, ctx)
    assert stub.calls == 0


def test_all_rejected_pool_empty_recorded():
    stub = _Stub(['{"logic_error": true, "error_desc": "严重逻辑错误"}'])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []
    assert any(k == "pool_empty" for k, _ in stub.events)


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    self_audit_stage(stub, _Boom())  # 不得抛异常
    assert any("异常" in m for _, m in stub.events)


# ----------------------------------------------------- 3) 接线锚点（读源守卫）
def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_norm = src.index('self._stage_start(ctx, "4.0_normalize")')
    i_audit = src.index('self._stage_start(ctx, "4.1_self_audit")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_norm < i_audit < i_fmt
    assert '"4.1_self_audit",' in src
