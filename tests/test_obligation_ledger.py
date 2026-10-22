"""义务账本（蓝图倒推链反向投影）与 4.2 判据的测试。"""

import pytest

from agent.obligation_ledger import (
    build_ledger,
    has_obligation,
    normalize_oid,
    render_for_audit,
)
from agent.adversarial_verifier import AdversarialResult


def _bp():
    """最小可选蓝图：目标 ← n1/n2 ← n3（倒推：root 的 children 是它的前提）。"""
    return {
        "root_id": "root",
        "merge_strategy": "由 n1 的构造与 n2 的否定夹逼，取值现场确定",
        "nodes": [
            {"id": "root", "type": "and",
             "statement": "求满足条件的最小正整数",
             "children": ["n1", "n2"], "produces": "题目所求的最小正整数",
             "inputs": [], "node_role": "required"},
            {"id": "n1", "type": "and",
             "statement": "建立下界：给出可行构造",
             "children": ["n3"], "produces": "一个显式构造",
             "inputs": ["root"], "node_role": "required"},
            {"id": "n2", "type": "and",
             "statement": "证明比它更小的值都不行",
             "children": [], "produces": "反证结论",
             "inputs": ["root", "题面条件"], "node_role": "required"},
            {"id": "n3", "type": "and",
             "statement": "验证构造满足全部约束",
             "children": [], "produces": "满足性判定",
             "inputs": [], "node_role": "required"},
            {"id": "x1", "type": "and",
             "statement": "前瞻引理：可能用到的辅助不等式",
             "children": [], "produces": "一条辅助不等式",
             "inputs": [], "node_role": "anticipatory"},
        ],
    }


class TestBuildLedger:
    def test_no_blueprint(self):
        assert build_ledger(None) == {}
        assert build_ledger({}) == {}
        assert build_ledger({"nodes": []}) == {}

    def test_order_follows_backward_chain(self):
        lg = build_ledger(_bp())
        # 根目标是「目标 G」，不占义务编号
        assert [o["node"] for o in lg["obligations"]] == ["n1", "n2", "n3"]
        assert [o["oid"] for o in lg["obligations"]] == ["O1", "O2", "O3"]

    def test_for_oid_records_why_needed(self):
        lg = build_ledger(_bp())
        by_node = {o["node"]: o for o in lg["obligations"]}
        assert by_node["n1"]["for_oid"] == "G"      # 直接支撑目标
        assert by_node["n3"]["for_oid"] == "O1"     # 是 n1 的前提

    def test_anticipatory_excluded(self):
        lg = build_ledger(_bp())
        assert "x1" not in lg["node_to_oid"]
        assert lg["n_skipped"] == 1

    def test_deps_mapped_to_oid_and_problem_inputs_counted(self):
        lg = build_ledger(_bp())
        by_node = {o["node"]: o for o in lg["obligations"]}
        assert by_node["n2"]["from_problem"] == 1
        assert by_node["n1"]["deps"] == []          # 只依赖根（目标本身）

    def test_root_fallback_when_root_id_missing(self):
        bp = _bp()
        bp.pop("root_id")
        lg = build_ledger(bp)
        assert lg["root_id"] == "root"

    def test_merge_and_terminal_carried(self):
        lg = build_ledger(_bp())
        assert "夹逼" in lg["merge"]
        assert lg["terminal"] == "题目所求的最小正整数"


class TestRender:
    def test_empty_ledger_renders_nothing(self):
        assert render_for_audit(None) == ""
        assert render_for_audit({}) == ""

    def test_contains_ids_and_discipline(self):
        text = render_for_audit(build_ledger(_bp()))
        assert "目标 G" in text
        assert "O1" in text and "O3" in text
        assert "为建立 G 所需" in text
        assert "为建立 O1 所需" in text
        assert "obligation_id" in text
        assert "不得作为「跳步」" in text

    def test_truncated_under_cap(self):
        from agent.obligation_ledger import MAX_LEDGER_CHARS
        bp = {"root_id": "r", "nodes": [
            {"id": "r", "type": "and", "statement": "S" * 200,
             "children": ["n%d" % i for i in range(60)],
             "produces": "P", "inputs": [], "node_role": "required"}] +
            [{"id": "n%d" % i, "type": "and", "statement": "T" * 200,
              "children": [], "produces": "P", "inputs": [], "node_role": "required"}
             for i in range(60)]}
        text = render_for_audit(build_ledger(bp))
        assert len(text) <= MAX_LEDGER_CHARS


class TestRelabel:
    """statement 里的节点引用必须重标成义务编号，否则清单与正文对不上。"""

    def test_node_refs_relabeled(self):
        bp = _bp()
        bp["nodes"][1]["statement"] = "由 n3 的满足性判定，建立下界的可行构造"
        lg = build_ledger(bp)
        by_node = {o["node"]: o for o in lg["obligations"]}
        assert "n3" not in by_node["n1"]["statement"]
        assert "O3" in by_node["n1"]["statement"]

    def test_long_id_not_shadowed_by_prefix(self):
        from agent.obligation_ledger import _relabel
        assert _relabel("n10 与 n1", {"n1": "O1", "n10": "O2"}) == "O2 与 O1"

    def test_variable_n_untouched(self):
        from agent.obligation_ledger import _relabel
        assert _relabel("对任意 n 成立，n1 给出", {"n1": "O1"}) == "对任意 n 成立，O1 给出"


class TestOidNormalize:
    @pytest.mark.parametrize("raw,want", [
        ("O3", "O3"), ("o3", "O3"), ("第3条", "O3"), ("义务3", "O3"),
        ("3", "O3"), ("O-2", "O2"), ("none", ""), ("", ""), ("无", ""),
    ])
    def test_normalize(self, raw, want):
        assert normalize_oid(raw) == want

    def test_normalize_against_ledger(self):
        lg = build_ledger(_bp())
        assert normalize_oid("O2", lg) == "O2"
        assert normalize_oid("O9", lg) == ""      # 账本里没有
        assert has_obligation(lg, "O1") is True
        assert has_obligation(lg, "none") is False
        assert has_obligation(None, "O1") is False


class TestOidNormalizeCompoundRefs:
    """复合引用：模型一次点两条义务时必须能解析。

    现场（2026-10-20 collab019_r1）：4.1 自审三次「义务指认失败 ⇒ 放行」，
    引用分别是 `O5/O7`、`O1/O2`、`O1/O2`。旧实现把输入里**所有**数字拼成一个数
    （`O5/O7` → digits `"57"` → `O57`），而 `O57` 必然不在账本内 ⇒ 判指认失败放行。
    其中 cid=0 随后被 4.2 跨模型以同一理由独立证伪 ⇒ 真错被误放行。
    """

    #: 01 号题的账本形态：O1/O2/O3/O5/O7 均真实存在
    LEDGER = {"node_to_oid": {"n1": "O1", "n2": "O2", "n3": "O3",
                              "n5": "O5", "n7": "O7"}}

    @pytest.mark.parametrize("raw,want", [
        ("O5/O7", "O5"),
        ("O1/O2", "O1"),
        ("O1,O2", "O1"),
        ("O1 与 O2", "O1"),
        ("第5条/第7条", "O5"),
        ("o5／o7", "O5"),          # 全角分隔符
        ("O9/O7", "O7"),           # 首个不在账本内 ⇒ 继续找下一个
        ("O9/O8", ""),             # 一条都对不上才算明确指认失败
        ("O57", ""),               # 单个假编号，口径不变
    ])
    def test_compound_ref(self, raw, want):
        assert normalize_oid(raw, self.LEDGER) == want

    def test_digits_never_concatenated(self):
        """回归锚点：`O5/O7` 不能被拼成 `O57`。"""
        assert normalize_oid("O5/O7", self.LEDGER) != "O57"
        assert normalize_oid("O1/O2", self.LEDGER) != "O12"

    def test_compound_counts_as_identified(self):
        """复合引用命中账本 ⇒ 算「明确指认」，不再走放行分支。"""
        assert has_obligation(self.LEDGER, "O5/O7") is True
        assert has_obligation(self.LEDGER, "O9/1") is True    # 1 → O1 存在
        assert has_obligation(self.LEDGER, "O9/O8") is False

    def test_without_ledger_returns_first_group(self):
        """无账本（不做存在性校验）时取第一个数字组，语义与带账本一致。"""
        assert normalize_oid("O5/O7") == "O5"
        assert normalize_oid("第3条、第4条") == "O3"


class TestActionableWithLedger:
    """硬类型 + 明确指认「不在任何义务上」⇒ 不淘汰；其余口径不变。"""

    @staticmethod
    def _r(**kw):
        base = dict(found=True, error_type="calculation_error",
                    error_step="第二行 121/125+25 算成 24", confidence=0.9)
        base.update(kw)
        return AdversarialResult(**base)

    def test_hard_error_unmapped_not_actionable(self):
        r = self._r(ledger_used=True, obligation_id="none", obligation_mapped=False)
        assert r.is_actionable is False

    def test_hard_error_mapped_actionable(self):
        r = self._r(ledger_used=True, obligation_id="O2", obligation_mapped=True)
        assert r.is_actionable is True

    def test_hard_error_blank_keeps_old_behavior(self):
        r = self._r(ledger_used=True, obligation_id="", obligation_mapped=False)
        assert r.is_actionable is True

    def test_without_ledger_unmapped_still_actionable(self):
        r = self._r(ledger_used=False, obligation_id="none", obligation_mapped=False)
        assert r.is_actionable is True

    def test_soft_still_not_actionable(self):
        r = self._r(error_type="skipped_step", obligation_id="O1",
                    obligation_mapped=True)
        assert r.is_actionable is False
        assert r.is_soft is True

    def test_no_evidence_not_actionable(self):
        r = self._r(error_step="", counterexample="", obligation_id="O1",
                    obligation_mapped=True, ledger_used=True)
        assert r.is_actionable is False

    def test_obligation_note(self):
        assert "已对上" in self._r(
            ledger_used=True, obligation_id="O1", obligation_mapped=True
        ).obligation_note
        assert self._r(ledger_used=False).obligation_note == ""
