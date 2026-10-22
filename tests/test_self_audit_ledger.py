"""4.1 自审接入「蓝图义务账本」的测试（2026-10-20）。

对应来源：p0b5_r5 里 `official112-019` 的正确答案 `4` 被 4.1 以
「仅列出子目标而未给出任何实际推导」淘汰 —— 与 4.2 证伪门同一病灶
（拿"完整证明模板"当标准，把有意省略读成逻辑断裂）。

覆盖五层：
  1) 无蓝图 ⇒ 行为与老口径逐字一致（不注入、不设门）；
  2) 有蓝图 ⇒ prompt 里出现义务清单与纪律；
  3) 账本可用且指认 none ⇒ 放行（不淘汰，记 unmapped）；
  4) 账本可用且指认到真实义务 ⇒ 照常淘汰，记录 obligation_id；
  5) 账本可用但漏填 ⇒ **不惩罚**（按原行为淘汰，与 4.2 同口径）；
  6) 开关关闭 ⇒ 不注入、不设门。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate          # noqa: E402
from agent.self_auditor import self_audit_stage  # noqa: E402


def _bp():
    """最小可选蓝图：目标 ← n1/n2 ← n3。"""
    return {
        "root_id": "root",
        "merge_strategy": "由 n1 的构造与 n2 的否定夹逼",
        "nodes": [
            {"id": "root", "type": "and", "statement": "求最小正整数",
             "children": ["n1", "n2"], "produces": "题目所求的最小正整数",
             "inputs": [], "node_role": "required"},
            {"id": "n1", "type": "and", "statement": "建立下界：给出可行构造",
             "children": ["n3"], "produces": "一个显式构造",
             "inputs": ["root"], "node_role": "required"},
            {"id": "n2", "type": "and", "statement": "证明更小的值都不行",
             "children": [], "produces": "反证结论",
             "inputs": ["root", "题面条件"], "node_role": "required"},
            {"id": "n3", "type": "and", "statement": "验证构造满足全部约束",
             "children": [], "produces": "满足性判定",
             "inputs": [], "node_role": "required"},
        ],
    }


class _Stub:
    def __init__(self, replies=None, blueprint=None, ledger_switch=True):
        self.events = []
        self.replies = list(replies or [])
        self.calls = 0
        self.msgs = []
        self.config = type("Cfg", (), {"audit_obligation_ledger": ledger_switch})()
        self._blueprint = blueprint

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))

    def llm(self, ctx, messages, temp, max_tokens):
        self.calls += 1
        self.msgs.append(messages)
        if self.replies:
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return '{"logic_error": false, "error_desc": ""}'


class _Ctx:
    def __init__(self, cands, blueprint=None):
        self.problem = "测试题"
        self.candidates = cands
        if blueprint is not None:
            self.blueprint = blueprint


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理过程")


def _user_msg(stub):
    return stub.msgs[-1][-1]["content"]


# --------------------------------------------------- 1) 无蓝图：老口径不变
def test_no_blueprint_keeps_legacy_behavior():
    stub = _Stub(['{"logic_error": true, "error_desc": "结论与推理不符"}'])
    ctx = _Ctx([_c(1)])
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []
    assert ctx.self_audit["n_rejected"] == 1
    assert ctx.self_audit["ledger_used"] is False
    assert "本题应当建立的义务" not in _user_msg(stub)


# --------------------------------------------------- 2) 有蓝图：注入清单
def test_blueprint_injected_into_prompt():
    stub = _Stub(['{"logic_error": false, "error_desc": ""}'], blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    msg = _user_msg(stub)
    assert "本题应当建立的义务" in msg
    assert "目标 G：" in msg
    assert "O1" in msg and "O3" in msg
    assert "obligation_id" in msg
    assert ctx.self_audit["ledger_used"] is True


# --------------------------------------------------- 3) 指认 none ⇒ 放行
def test_unmapped_obligation_keeps_candidate():
    stub = _Stub(['{"logic_error": true, "error_desc": "只列子目标没有推导",'
                  ' "error_at": "整个解答", "obligation_id": "none"}'],
                 blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]      # 保留
    assert ctx.self_audit["n_rejected"] == 0
    assert ctx.self_audit["n_unmapped"] == 1
    assert ctx.self_audit_unmapped[0]["ref"] == "none"
    assert any("不在账本内" in m for _, m in stub.events)


def test_nonexistent_oid_keeps_candidate():
    # 账本只有 O1..O3，模型引用 O9 ⇒ 同样视为指认失败
    stub = _Stub(['{"logic_error": true, "error_desc": "x", "obligation_id": "O9"}'],
                 blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.self_audit["n_unmapped"] == 1


# --------------------------------------------------- 4) 指认真实义务 ⇒ 淘汰
def test_mapped_obligation_still_rejects():
    stub = _Stub(['{"logic_error": true, "error_desc": "前提误用",'
                  ' "error_at": "第2步", "obligation_id": "O2"}'],
                 blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []
    assert ctx.self_audit["n_rejected"] == 1
    rec = ctx.self_audit_rejected[0]
    assert rec["obligation_id"] == "O2"
    assert rec["ledger_used"] is True


def test_oid_format_tolerated():
    # 模型常写 `o2` / `第2条`，归一后仍算命中
    stub = _Stub(['{"logic_error": true, "error_desc": "前提误用",'
                  ' "obligation_id": "第2条"}'], blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    assert ctx.self_audit["n_rejected"] == 1
    assert ctx.self_audit_rejected[0]["obligation_id"] == "O2"


# --------------------------------------------------- 5) 漏填不惩罚
def test_missing_oid_not_penalized():
    stub = _Stub(['{"logic_error": true, "error_desc": "自相矛盾"}'],
                 blueprint=_bp())
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    assert ctx.candidates == []                       # 按原行为淘汰
    assert ctx.self_audit["n_rejected"] == 1
    assert ctx.self_audit["n_unmapped"] == 0
    assert ctx.self_audit_rejected[0]["obligation_id"] == ""


# --------------------------------------------------- 6) 开关关闭
def test_ledger_switch_off(monkeypatch):
    stub = _Stub(['{"logic_error": true, "error_desc": "跳步",'
                  ' "obligation_id": "none"}'],
                 blueprint=_bp(), ledger_switch=False)
    ctx = _Ctx([_c(1)], blueprint=_bp())
    self_audit_stage(stub, ctx)
    # 不注入 ⇒ 不含清单；也不设门 ⇒ 照原行为淘汰
    assert "本题应当建立的义务" not in _user_msg(stub)
    assert ctx.candidates == []
    assert ctx.self_audit["ledger_used"] is False


# --------------------------------------------------- 7) 提示词口径（读源守卫）
def test_prompt_no_longer_treats_omission_as_logic_error():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "prompts", "self_audit.py"),
               encoding="utf-8").read()
    assert "跳步「不是逻辑错误」" in src or "跳步」不是逻辑错误" in src
    assert "{obligations}" in src
    assert "obligation_id" in src
