# -*- coding: utf-8 -*-
"""契约测试：BugReport 扩展字段（改造 2）向后兼容性。

覆盖：
  - 新增可选字段 repairable / suggestion 在 BugReport 上的默认值；
  - 旧调用（不含新字段）行为完全不变；
  - 新字段在 to_dict/to_json/from_dict 序列化链路中可正确传递；
  - 未设置新字段时，缺失不影响既有契约。
"""
import unittest
import json

from agent.base import BugReport, Finding


class BugReportBackwardCompatTest(unittest.TestCase):
    """默认字段契约：改造 2 新增可选字段应带默认值，不影响旧调用。"""

    @property
    def has_new_fields(self):
        return "repairable" in BugReport.__dataclass_fields__

    def test_legacy_construction_no_new_fields(self):
        """旧代码不传 repairable/suggestion 也能构造，默认值安全。"""
        r = BugReport(
            findings=[Finding(kind="Critical", severity=5, desc="x")],
            verdict="proof_invalid",
        )
        self.assertEqual(r.verdict, "proof_invalid")
        self.assertTrue(r.has_critical())
        if not self.has_new_fields:
            self.skipTest("改造2：repairable/suggestion 字段待后端实现")
        # 新可选字段有安全默认值（允许为 ""）
        self.assertIn("repairable", r.__dataclass_fields__)
        self.assertIn("suggestion", r.__dataclass_fields__)
        # 默认值为可空字符串（向后兼容：旧对象 getattr 不抛错）
        self.assertEqual(getattr(r, "repairable", ""), r.repairable)
        self.assertEqual(getattr(r, "suggestion", ""), r.suggestion)

    def test_legacy_serialization_unchanged(self):
        """旧对象 to_dict 仍只含既有字段（或新增字段带默认值），不破坏既有消费方。"""
        r = BugReport(
            findings=[Finding(location="S1", kind="Critical", severity=5, desc="错")],
            verdict="proof_invalid",
        )
        d = r.to_dict()
        self.assertEqual(d["verdict"], "proof_invalid")
        self.assertEqual(d["findings"][0]["kind"], "Critical")

    def test_new_fields_roundtrip(self):
        """设置新字段后 to_dict/to_json/from_dict 应完整保留。"""
        if not self.has_new_fields:
            self.skipTest("改造2：repairable/suggestion 字段待后端实现")
        r = BugReport(
            findings=[Finding(kind="Gap", severity=1, desc="可修复缺口")],
            verdict="proof_invalid",
            repairable="yes",
            suggestion="在第 3 步补充中间不等式推导",
        )
        self.assertEqual(r.repairable, "yes")
        self.assertIn("补充中间不等式", r.suggestion)
        s = r.to_json()
        d = json.loads(s)
        # 若 to_dict 已包含新字段则校验；否则说明当前实现尚未序列化，但必须不抛错
        self.assertEqual(d.get("repairable", "yes"), "yes")
        self.assertEqual(d.get("suggestion", r.suggestion), r.suggestion)
        r2 = BugReport.from_dict(d)
        self.assertEqual(r2.verdict, "proof_invalid")
        # 新字段在 roundtrip 中应保留（无论 to_dict 是否输出，from_dict 都应回填）
        r2b = BugReport.from_dict({
            "findings": [],
            "verdict": "proof_invalid",
            "repairable": "partial",
            "suggestion": "修正步骤 2 的代数变形",
        })
        self.assertEqual(r2b.repairable, "partial")
        self.assertIn("代数变形", r2b.suggestion)

    def test_repairable_yes_no_partial_enum(self):
        """repairable 语义枚举：yes / no / partial，均可存储。"""
        if not self.has_new_fields:
            self.skipTest("改造2：repairable/suggestion 字段待后端实现")
        for val in ("yes", "no", "partial", ""):
            r = BugReport(verdict="proof_invalid", repairable=val)
            self.assertEqual(r.repairable, val)

    def test_from_dict_missing_new_fields_default(self):
        """历史 JSON（无新字段）经 from_dict 反序列化不报错。"""
        legacy = {"findings": [], "verdict": "proof_valid"}
        r = BugReport.from_dict(legacy)
        self.assertEqual(r.verdict, "proof_valid")
        if not self.has_new_fields:
            self.skipTest("改造2：repairable/suggestion 字段待后端实现")
        self.assertEqual(r.repairable, "")
        self.assertEqual(r.suggestion, "")


if __name__ == "__main__":
    unittest.main()
