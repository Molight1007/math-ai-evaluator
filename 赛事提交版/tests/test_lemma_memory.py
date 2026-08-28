# -*- coding: utf-8 -*-
"""LemmaMemory（#30）单元测试。"""
import json
import os
import tempfile
import unittest

from agent.lemma_memory import LemmaMemory, _norm_key
from agent.base import TaskContext, Budget


class LemmaMemoryTest(unittest.TestCase):
    def test_add_and_lookup(self):
        mem = LemmaMemory()
        self.assertTrue(mem.add("sq_nonneg", "∀ x : ℝ, x ^ 2 ≥ 0", proof="by positivity"))
        # 查重：同名规范化后不重复
        self.assertFalse(mem.add("sq_nonneg", "重复", proof=""))
        self.assertFalse(mem.add("  Sq_Nonneg ", "带空格同名"))
        self.assertFalse(mem.add("", "空名"))
        self.assertFalse(mem.add("x", ""))
        self.assertEqual(len(mem), 1)

        hits = mem.lookup("nonneg")
        self.assertEqual(len(hits), 1)
        hits2 = mem.lookup("x ^ 2")
        self.assertEqual(len(hits2), 1)
        self.assertEqual(mem.lookup("不存在"), [])

    def test_add_many(self):
        mem = LemmaMemory()
        added = mem.add_many([
            {"name": "a", "statement": "1 + 1 = 2"},
            {"name": "a", "statement": "重复"},
            {"name": "b", "statement": "2 + 2 = 4"},
            {"name": "c"},  # 无 statement
        ])
        self.assertEqual(added, 2)
        self.assertEqual(len(mem), 2)

    def test_serialization_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "lemmas.json")
            mem = LemmaMemory()
            mem.add("l1", "1 = 1", proof="rfl", source="test")
            self.assertTrue(mem.save(path))
            mem2 = LemmaMemory(path)  # 构造时自动载入
            self.assertEqual(len(mem2), 1)
            self.assertEqual(mem2.get("l1")["statement"], "1 = 1")
            self.assertEqual(mem2.get("l1")["proof"], "rfl")
            # to_json 可解析
            self.assertIsInstance(json.loads(mem2.to_json()), list)

    def test_load_invalid_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json{{{")
            mem = LemmaMemory(path)
            self.assertEqual(len(mem), 0)

    def test_ctx_interop(self):
        mem = LemmaMemory()
        ctx = TaskContext(problem="p", metadata={},
                          budget=Budget(max_calls=10),
                          lemma_repo=["引理A：1+1=2", "引理B：x≥0"])
        self.assertEqual(mem.import_from_ctx(ctx), 2)
        ctx.lemma_repo = []
        mem.export_to_ctx(ctx)
        self.assertEqual(len(ctx.lemma_repo), 2)

    def test_format_for_prompt(self):
        mem = LemmaMemory()
        self.assertEqual(mem.format_for_prompt(), "")
        mem.add("sq_nonneg", "∀ x : ℝ, x ^ 2 ≥ 0", proof="by positivity")
        text = mem.format_for_prompt()
        self.assertIn("sq_nonneg", text)
        self.assertIn("已证", text)


if __name__ == "__main__":
    unittest.main()
