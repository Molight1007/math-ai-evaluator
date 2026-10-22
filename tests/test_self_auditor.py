# -*- coding: utf-8 -*-
"""4.1 AI 自审逻辑错误（五道审核链第 1 道）单测 —— 2026-10-14。

覆盖三层：
  1) ``parse_self_audit_json`` 容错解析（围栏 / 前后杂文 / 字符串布尔值 / 负例）；
  2) ``self_audit_stage`` 判定纪律：淘汰/保留/不可解析/LLM 故障/开关关闭；
  3) 阶段接线锚点：orchestrator 序列 4.0 → 4.1 → 3.6（读源守卫）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.self_auditor import (  # noqa: E402
    parse_self_audit_json,
    self_audit_stage,
)


@pytest.fixture(autouse=True)
def _single_vote(monkeypatch):
    """默认把 4.1 采样次数压到 1（=旧行为），让「调用次数」类断言保持可比。

    ★ 2026-10-22：4.1 改为多次采样（默认 3），多票行为由文件末尾的
      ``test_votes_*`` 单独覆盖，避免每条旧用例都被采样次数污染。
    """
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT_VOTES", "1")


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
    # ★ 2026-10-22：reasoning 必须是「可被引证」的真实文本 —— 证据落地校验
    #   会核对 error_at 是否逐字出现在这里（旧夹具 "推理过程" 无法引证）。
    return Candidate(id=i, answer=ans,
                     reasoning="先验证小值，得到 n+1 必须整除 2，因此 n 只能取 1。")


def test_reject_logic_error():
    stub = _Stub([
        '{"logic_error": true, "error_desc": "结论与推理不符",'
        ' "error_at": "得到 n+1 必须整除 2"}',
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


def test_llm_fail_keeps_candidate():
    # 首次调用就抛异常 ⇒ 计 llm_fail、保留候选（绝不因基础设施故障淘汰）
    stub = _Stub([RuntimeError("timeout")])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_llm_fail"] == 1
    assert ctx.self_audit["n_unparsed"] == 0


def test_unparsed_twice_marks_unverified():
    # 两次都不成 JSON ⇒ 保留但打 unverified（不再视为"通过"）
    stub = _Stub(["不是 JSON", "还是不是 JSON"])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_unparsed"] == 1
    assert getattr(ctx.candidates[0], "verify_audit", "") == "unparsed"


def test_ungrounded_evidence_keeps_candidate():
    # ★ 2026-10-22 证据落地门：error_at 编造（原文没有这句）⇒ 不得据此淘汰
    stub = _Stub(['{"logic_error": true, "error_desc": "第二步错了",'
                  ' "error_at": "原文根本不存在的这一句话"}'])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_ungrounded"] == 1
    assert ctx.self_audit["n_rejected"] == 0


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
    stub = _Stub(['{"logic_error": true, "error_desc": "严重逻辑错误",'
                  ' "error_at": "因此 n 只能取 1"}'])
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


# -------------------------------------- 4) 多次采样（2026-10-22 实测修复）
# 背景：同一个错误候选连跑 3 次，判定是「留 / 杀 / 留」⇒ 单次采样不可靠。
# 契约：采 N 次，**任一次**给出带落地证据的逻辑错即淘汰；全部 clean 才保留。
_ERR = ('{"logic_error": true, "error_desc": "结论与推理不符",'
        ' "error_at": "得到 n+1 必须整除 2"}')
_CLEAN = '{"logic_error": false, "error_desc": ""}'


def test_votes_any_error_rejects(monkeypatch):
    """第 1 票 clean、第 2 票 error ⇒ 命中即淘汰（这正是单次采样漏掉的样本）。"""
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT_VOTES", "3")
    stub = _Stub([_CLEAN, _ERR])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []
    assert stub.calls == 2
    assert ctx.self_audit["votes"] == 3
    assert ctx.self_audit["n_weak"] == 1      # 弱证据（非首票命中）单列


def test_votes_all_clean_keeps_candidate(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT_VOTES", "3")
    stub = _Stub([_CLEAN, _CLEAN, _CLEAN])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert stub.calls == 3
    assert ctx.self_audit["n_rejected"] == 0


def test_votes_first_error_short_circuits(monkeypatch):
    """首票就命中 ⇒ 只调 1 次（不浪费后续采样）。"""
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT_VOTES", "3")
    stub = _Stub([_ERR, _ERR, _ERR])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []
    assert stub.calls == 1
    assert ctx.self_audit["n_weak"] == 0


def test_votes_ungrounded_evidence_still_keeps(monkeypatch):
    """多票里即使有一次判错，但证据编造（不在原文里）⇒ 仍不淘汰。"""
    monkeypatch.setenv("FIVE_GATE_SELF_AUDIT_VOTES", "3")
    bad = ('{"logic_error": true, "error_desc": "第二步错了",'
           ' "error_at": "原文根本没有这一句"}')
    stub = _Stub([_CLEAN, bad, _CLEAN])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_ungrounded"] >= 0
