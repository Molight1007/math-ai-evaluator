# -*- coding: utf-8 -*-
"""4.6 重写反馈的**优先级整理**（2026-10-23）。

实测背景（val1_r1_1022）：4 条淘汰理由平铺喂给重写模型，其中 cross_model 那条
**已经写出了正确上界**——

    由 AM-HM 该和 ≥ (N-1)²/(N(N+1)-3) → 1，故 D ≤ M = 777² = 603729

但它排第 4 位，还和「构造证明有误 / 与义务 O5 矛盾」混在一起；另有一条理由正文为空。
结果两轮重写仍给 `777²/2`（= 正确答案的一半）。

新契约：
  ① 空壳理由丢弃（前缀之外无实质内容）；
  ② 含数值/不等式/反例的理由**置顶**并标注「优先采信」；
  ③ 其余理由单列，显式降级为「参考」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.rewrite_gate import _collect_error_brief  # noqa: E402

# 真实语境（来自 val1_r1_1022 的 diag）
_QUANT = ("上界过松。取前N项并按a_i=x_i^2排序，记对应指标为p_k，则由相邻值条件得"
          "D∑1/(p_k+p_{k+1})≤M。由AM-HM该和≥(N-1)^2/(N(N+1)-3)→1，故D≤M=777^2=603729，"
          "而答案给出2M=1207458，超过上界")
_VAGUE = ("解答在子目标 1 中明确指出推导结果与义务 O5 要求的结论矛盾，"
          "无法逻辑自洽地建立上界，且证明过程未完成。")


class _Ctx:
    def __init__(self, errors, rej):
        self.pool_empty_errors = errors
        self.self_audit_rejected = rej
        self.adversarial_gate_rejected = []
        self.math_check_rejected = []


def _build():
    errors = [
        {"stage": "4.2_falsify", "kind": "x", "error": _VAGUE},
        {"stage": "4.2_falsify", "kind": "y", "error": _QUANT},
        {"stage": "4.2_falsify", "kind": "z", "error": ""},   # 空壳（实测确有）
    ]
    rej = [{"id": 0, "answer": "603729/2",
            "error_desc": "The construction claims that for all m<n ... fails for m>1 (e.g. m=4 gives 0.45<0.5)"}]
    return _collect_error_brief(_Ctx(errors, rej))


def test_quantitative_reason_is_hoisted():
    """含正确上界的那条必须排到「优先采信」段，且位置在其余理由之前。"""
    out = _build()
    i_quant = out.find("603729")
    i_vague = out.find("无法逻辑自洽地建立上界")
    assert i_quant >= 0, "定量理由丢失"
    assert i_quant < i_vague, "定量理由必须排在结论性描述之前"


def test_hoist_header_present():
    out = _build()
    assert "优先采信" in out
    assert "可信度较低" in out


def test_empty_reason_dropped():
    """空壳理由（只有前缀没有正文）不得进反馈。"""
    out = _build()
    # 3 条输入里有 1 条是空 error ⇒ 输出里不应出现两个连续的空条目
    for line in out.split("\n"):
        if line.startswith("- [") and line.rstrip().endswith("]"):
            raise AssertionError("空壳理由未被过滤: %r" % line)


def test_no_quant_falls_back_to_plain_list():
    """没有定量理由时退回普通清单，不硬造分段。"""
    out = _collect_error_brief(_Ctx([{"stage": "4.1", "error": _VAGUE}], []))
    assert "优先采信" not in out
    assert "无法逻辑自洽地建立上界" in out
