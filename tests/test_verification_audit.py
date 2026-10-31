# -*- coding: utf-8 -*-
"""`agent/verification_audit.py` 的回归测试。

样本全部取自**真实跑批产物**（`results/20261028-215738/qfaed7d35` 与
`results/20261027-232401/qfaed7d35` 的 `04_subgoal_results.jsonl`），
不是构造的理想句 —— 这条流水线上「构造样本全过、真实样本全漏」已经发生过。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.verification_audit import (  # noqa: E402
    audit_step, conclusion_refuted, conclusion_value, note_step,
    pass_conflicts, scan_false_claims, verify_note_for_merge,
)

# ── 真阳性样本：omni-3556 E09 组第 6 步原文（节选） ──────────────────────
_STEP6 = """本步结论: 值 = 666
本步依据: 子目标5结论（n=666满足条件）及本步合并

由子目标5已验证 $n=666$ 满足 $666\\mid2^{666}+2$ 且 $100\\le666\\le1997$。
- 整除：$666 = 2\\cdot3^2\\cdot37$，且已分别验证 $2^{666}+2\\equiv0\\pmod2$、$\\pmod3$、$\\pmod9$、$\\pmod{37}$，由中国剩余定理得 $666\\mid2^{666}+2$。
"""

# ── 真阳性样本：同题第 5 步（头部 666，正文最后判定它不成立） ─────────────
_STEP5 = """本步结论: 值 = 666
本步依据: 子目标4结论

取 $k=111$，则 $n=6\\cdot111=666$，满足 $100\\le 666\\le 1997$。验证 $666\\mid 2^{666}+2$。
- 模 $9$：$2^{666}\\equiv 1\\pmod 9$，于是 $2^{666}+2\\equiv 3\\not\\equiv 0\\pmod 9$。等等，模 $9$ 不满足。
尝试 $n=666$ 已失败。
"""

# ── 真阴性样本：同题第 2 轮第 3 步（946 各模验证真的通过） ───────────────
_STEP_OK = """本步结论: 值 = 946
本步依据: 子目标2结论

验证 $946\\mid 2^{946}+2$。$946=2\\cdot11\\cdot43$。
- 模 $11$：$2^{10}\\equiv 1\\pmod{11}$，$946\\equiv 6\\pmod{10}$，故 $2^{946}\\equiv 2^6=64\\equiv 9\\pmod{11}$，$9+2=11\\equiv 0\\pmod{11}$。
- 模 $43$：$2^{7}\\equiv -1\\pmod{43}$，$946\\equiv 22\\pmod{42}$，$2^{946}\\equiv -2\\pmod{43}$，$-2+2\\equiv 0\\pmod{43}$。
故 $946\\mid 2^{946}+2$ 成立，$946$ 满足题设全部条件。
"""

# ── 真阴性样本：「否定式 / 待验目标 / 代码块」三种不该判的形态 ─────────────
_STEP_NEG = """本步结论: 判定 = 真

现验证 $7\\mid 2^{946}+2$。已知 $\\operatorname{ord}_7(2)=3$，$946\\equiv 1\\pmod 3$，
故 $2^{946}\\equiv 2\\pmod 7$，于是 $2^{946}+2\\equiv 4\\pmod 7$。
因 $4\\not\\equiv0\\pmod7$，故 $7\\nmid 2^{946}+2$，$n=946$ 不满足模7条件。
"""

_STEP_CODE = """本步结论: 判定 = 真

证法如下：

```lean
example (m : ℕ) (h : m ∣ 2 ^ (2 * m - 1) + 1) : (5 * m) ∣ 2 ^ (10 * m - 1) + 1 := by
  have h7 : 5 ∣ 2 ^ (10 * m - 1) + 1 := by norm_num
```

由于 $m$ 为奇数，$5 \\mid m$ 时结论成立。
"""


def test_false_congruence_caught():
    """第 6 步两条「已分别验证」是假的（mod 9 余 3、mod 37 余 1）。"""
    claims = scan_false_claims(_STEP6)
    assert any("mod 9" in c for c in claims), claims
    assert any("mod 37" in c for c in claims), claims
    # mod 2 与 mod 3 是真的，不得报
    assert not any("mod 2 " in c or "(mod 2)" in c for c in claims), claims
    assert not any("(mod 3)" in c for c in claims), claims


def test_false_divisibility_caught():
    """`666 ∣ 2^666+2` 实算余 408 ⇒ 必报。"""
    claims = scan_false_claims(_STEP6)
    assert any("∣ 2^{666}+2" in c for c in claims), claims


def test_true_verification_not_flagged():
    """946 的各模验证是真通过的，一条都不许报（误报比漏报贵得多）。"""
    a = audit_step(_STEP_OK)
    assert a["false_claims"] == [], a["false_claims"]
    assert a["conclusion"] == "946"
    assert a["conclusion_refuted"] is False


def test_negated_target_not_flagged():
    """`\\nmid` / `\\not\\equiv` 出现的段是「验证后否定」，不是假断言。"""
    a = audit_step(_STEP_NEG)
    assert a["false_claims"] == [], a["false_claims"]


def test_lean_code_block_not_flagged():
    """Lean 代码块里 `5 ∣ 2 ^ (10*m-1) + 1` 是证法目标，不是数学断言。

    实测坑：不剥代码块会把 `5 ∣ 2 ^ (10 * m - 1) + 1` 截成 `5 ∣ 2` 判假。
    """
    a = audit_step(_STEP_CODE)
    assert a["false_claims"] == [], a["false_claims"]


def test_symbolic_not_judged():
    """含自由符号的式子一律不判（「未给定」不是「假」）。"""
    assert scan_false_claims("断言 $n \\mid 2^{n}+2$，$m \\mid 2^{2m-1}+1$。") == []


def test_huge_exponent_safe():
    """不得因超大指数炸掉（2^2^100 直接拒判，不计算）。"""
    assert scan_false_claims("$2^{2^{100}}\\equiv 0\\pmod 7$。") == []


def test_conclusion_value_only_numeric():
    assert conclusion_value("本步结论: 值 = 666\n本步依据: x") == "666"
    assert conclusion_value("本步结论: 等式 = 2^{65}+1 = 36893") is None
    assert conclusion_value("本步结论: 判定 = 真") is None
    assert conclusion_value("没有结论头") is None


def test_conclusion_refuted_adjacent_only():
    """只认「V 紧邻否定词」；正文里讨论别的值不构成矛盾。"""
    assert conclusion_refuted(_STEP5, "666") is True
    assert conclusion_refuted(_STEP_OK, "946") is False
    # 别的值被否定，与本步结论无关
    assert conclusion_refuted("假设 $n=66$ 不满足。故取 $n=946$。", "946") is False


class _Ctx:
    def __init__(self):
        self.trace = []


def _feed(ctx, rows):
    for r in rows:
        note_step(ctx, {"id": r[0], "title": r[1], "result": r[2]})


def test_pass_conflict_detected():
    """实测：同一题 3 轮，末步结论 66 / 946 / 946 ⇒ 报 2 条冲突。"""
    ctx = _Ctx()
    _feed(ctx, [
        (1, "第一轮第1步", "本步结论: 值 = 330"),
        (2, "第一轮末步", "本步结论: 值 = 66"),
        (1, "第二轮第1步", "本步结论: 值 = 330"),
        (2, "第二轮末步", "本步结论: 值 = 946"),
        (1, "第三轮第1步", "本步结论: 值 = 330"),
        (2, "第三轮末步", "本步结论: 值 = 946"),
    ])
    cfl = pass_conflicts(ctx)
    assert len(cfl) == 2, cfl
    assert all("66" in c and "946" in c for c in cfl), cfl


def test_pass_conflict_same_value_no_alert():
    """各轮末步结论一致 ⇒ 不报（否则每道题都会被报一次）。"""
    ctx = _Ctx()
    _feed(ctx, [
        (1, "第1步", "本步结论: 值 = 946"),
        (2, "末步", "本步结论: 值 = 946"),
        (1, "第1步", "本步结论: 值 = 946"),
        (2, "末步", "本步结论: 值 = 946"),
    ])
    assert pass_conflicts(ctx) == []


def test_merge_note_mentions_arithmetic_failure():
    ctx = _Ctx()
    note_step(ctx, {"id": 1, "title": "构造并验证", "result": _STEP6})
    note = verify_note_for_merge(ctx)
    assert "算术复核失败" in note
    assert "mod 9" in note
    # 必须明确「这是算出来的，不是意见」
    assert "非评审意见" in note or "精确" in note


def test_merge_note_empty_when_clean():
    ctx = _Ctx()
    note_step(ctx, {"id": 1, "title": "验证", "result": _STEP_OK})
    assert verify_note_for_merge(ctx) == ""


def test_switch_off_short_circuits(monkeypatch):
    """开关关闭 ⇒ 调用方不应记账（这里验 `enabled()` 的读取口径）。"""
    import agent.verification_audit as va

    monkeypatch.setenv("STEP_VERIFICATION_AUDIT", "0")
    try:
        from contracts.switch_registry import reset_overrides  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    assert va.enabled(None) is False
    monkeypatch.setenv("STEP_VERIFICATION_AUDIT", "1")
    assert va.enabled(None) is True
