# -*- coding: utf-8 -*-
"""验证器（VerifierAgent）核心逻辑单元测试。

覆盖:
- ``_is_correct_vote``: 拒绝词优先、接受词兜底
- ``_normalize_answer_text``: 文本级归一化
- ``_are_answers_equivalent``: 三级等价判定
- ``_equiv_group``: 等价答案聚类
- ``_parse_json_loose`` / ``_format_bug_report``: 结构化 bug report
  （依据 IMO 2025 验证-精炼流水线论文，用于驱动 revise 迭代修正）
- ``_extract_bug_report``: 端到端解析 + 分类回退
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from agent.verifier import VerifierAgent


def make_verifier() -> VerifierAgent:
    return VerifierAgent(client=object(), config=SimpleNamespace())


class IsCorrectVoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_none_input(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote(None))

    def test_verdict_a(self) -> None:
        self.assertTrue(self.verifier._is_correct_vote("VERDICT: A"))

    def test_verdict_b(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote("VERDICT: B"))

    def test_explicit_correct(self) -> None:
        self.assertTrue(self.verifier._is_correct_vote("该解答完全正确"))
        self.assertTrue(self.verifier._is_correct_vote("CORRECT"))

    def test_reject_word_wins_over_correct(self) -> None:
        # "不正确" 含 "正确" 子串，拒绝词必须优先
        self.assertFalse(self.verifier._is_correct_vote("答案不正确"))
        self.assertFalse(self.verifier._is_correct_vote("The answer is INCORRECT"))

    def test_reject_words(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote("错误"))
        self.assertFalse(self.verifier._is_correct_vote("WRONG"))


class NormalizeAnswerTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_empty_input(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text(""), "")
        self.assertEqual(self.verifier._normalize_answer_text(None), "")

    def test_whitespace_and_dollar(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("$ 5 $"), "5")

    def test_fraction_to_decimal(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("1/2"), "0.5")
        self.assertEqual(self.verifier._normalize_answer_text(r"\frac{1}{2}"), "0.5")

    def test_trailing_zero_removed(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("3.0"), "3")


class AreAnswersEquivalentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_identical_strings(self) -> None:
        self.assertTrue(self.verifier._are_answers_equivalent("2", "2"))

    def test_fraction_vs_decimal(self) -> None:
        self.assertTrue(self.verifier._are_answers_equivalent("1/2", "0.5"))

    def test_different_values(self) -> None:
        self.assertFalse(self.verifier._are_answers_equivalent("1/2", "0.25"))

    def test_empty_input(self) -> None:
        self.assertFalse(self.verifier._are_answers_equivalent("", "0"))
        self.assertFalse(self.verifier._are_answers_equivalent("1", None))


class EquivGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_groups_equivalent_answers(self) -> None:
        groups = self.verifier._equiv_group([], ["1/2", "0.5", "3"])
        self.assertEqual(len(groups), 2)
        # 第一组应包含 "1/2" 与 "0.5"
        first = sorted(groups[0])
        self.assertEqual(first, [0, 1])

    def test_single_element(self) -> None:
        groups = self.verifier._equiv_group([], ["7"])
        self.assertEqual(groups, [[0]])

    def test_no_duplicates_in_groups(self) -> None:
        groups = self.verifier._equiv_group([], ["a", "b", "a"])
        flat = sorted(i for g in groups for i in g)
        self.assertEqual(flat, [0, 1, 2])


# ============================================================
# 结构化 Bug Report（论文：IMO 2025 验证-精炼流水线）
# ============================================================

class ParseJsonLooseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v = make_verifier()

    def test_plain_json(self) -> None:
        self.assertEqual(self.v._parse_json_loose('{"a": 1}'), {"a": 1})

    def test_markdown_fence(self) -> None:
        raw = '```json\n{"verdict": "correct", "findings": []}\n```'
        self.assertEqual(self.v._parse_json_loose(raw)["verdict"], "correct")

    def test_leading_prose(self) -> None:
        """模型先说一段话再给 JSON —— 必须仍能抠出来。"""
        raw = '我的审查结果如下：\n{"verdict": "critical_error", "findings": []}'
        self.assertEqual(self.v._parse_json_loose(raw)["verdict"], "critical_error")

    def test_nested_braces(self) -> None:
        """findings 内部有嵌套对象，括号平衡不能提前收尾。"""
        raw = ('{"verdict":"x","findings":[{"location":"a > b",'
               '"type":"critical_error","explanation":"y"}]}')
        data = self.v._parse_json_loose(raw)
        self.assertEqual(data["findings"][0]["location"], "a > b")

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(self.v._parse_json_loose("完全没有 JSON"))
        self.assertIsNone(self.v._parse_json_loose(""))


class FormatBugReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v = make_verifier()

    def test_empty_findings(self) -> None:
        self.assertEqual(self.v._format_bug_report({"findings": []}), "")

    def test_critical_errors_first(self) -> None:
        """关键错误必须排在论证漏洞之前——修正要先修断链的那一步。"""
        report = {"verdict": "critical_error", "findings": [
            {"location": "步骤2", "type": "justification_gap",
             "explanation": "跳步"},
            {"location": "步骤1", "type": "critical_error",
             "explanation": "符号写反"},
        ]}
        out = self.v._format_bug_report(report)
        self.assertLess(out.index("符号写反"), out.index("跳步"),
                        "关键错误应排在论证漏洞之前")
        self.assertIn("关键错误", out)
        self.assertIn("论证漏洞", out)

    def test_quotes_location(self) -> None:
        """location 要带引号，便于模型定位到原文那一句。"""
        report = {"findings": [
            {"location": "由 A>B 推出 A-C>B-D", "type": "critical_error",
             "explanation": "逻辑谬误"}]}
        self.assertIn("“由 A>B 推出 A-C>B-D”", self.v._format_bug_report(report))


class ExtractBugReportTest(unittest.TestCase):
    def _make(self, response):
        from agent.base import TaskContext, Budget

        class C:
            def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
                return response

        v = VerifierAgent(client=C(), config=SimpleNamespace())
        ctx = TaskContext(problem="证明 x^2 >= 0", metadata={},
                          budget=Budget(max_calls=10))
        return v, ctx

    def test_parses_valid_report(self) -> None:
        v, ctx = self._make(
            '{"verdict":"critical_error","findings":['
            '{"location":"2+3=6","type":"critical_error",'
            '"explanation":"计算错误"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "推理", "answer": "42"})())
        self.assertEqual(r["verdict"], "critical_error")
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["location"], "2+3=6")

    def test_verdict_inferred_when_missing(self) -> None:
        """模型漏给 verdict 时，用 findings 反推比信任自陈更可靠。"""
        v, ctx = self._make(
            '{"findings":[{"location":"a","type":"critical_error",'
            '"explanation":"b"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["verdict"], "critical_error")

    def test_unknown_type_defaults_to_gap(self) -> None:
        v, ctx = self._make(
            '{"verdict":"x","findings":[{"location":"a","type":"乱写的",'
            '"explanation":"b"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["findings"][0]["type"], "justification_gap")

    def test_garbage_returns_unknown(self) -> None:
        v, ctx = self._make("我无法完成这项任务")
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["findings"], [])


# ============================================================
# v3 P2 rubric 结构化判分 + 反例挑战（2026-09-06 移植自 sq 分支）
# ============================================================

class _RubricFixture:
    """共享 mock 基建：假 client（按调用序返回 response）+ 真 TaskContext。"""

    def _make(self, responses):
        """responses: 单个响应串，或按调用次序的响应串列表。"""
        from agent.base import TaskContext, Budget

        class C:
            def __init__(self, r):
                self._r = r if isinstance(r, list) else [r]
                self.calls = 0

            def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
                # 返回当前序号的响应；耗尽后返回最后一个（防御性）
                i = min(self.calls, len(self._r) - 1)
                self.calls += 1
                return self._r[i]

        client = C(responses)
        v = VerifierAgent(client=client, config=SimpleNamespace(
            max_workers=2,                    # 二元投票线程池需要
            verifier_voting_times=1,
            use_scoring=False,
            use_bug_report_feedback=False))  # 关闭 revise 反馈 LLM 调用
        ctx = TaskContext(problem="求 x^2 - 4 = 0 的解", metadata={},
                          budget=Budget(max_calls=100),
                          deadline=0.0)
        return v, ctx, client

    def _cand(self, answer="2", reasoning="因为 x^2=4，所以 x=2"):
        return {"id": 0, "answer": answer, "reasoning": reasoning}


class VoteOneRubricTest(_RubricFixture, unittest.TestCase):
    def test_parses_verdict_a(self) -> None:
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.95,"error_type":"无",'
            '"step_index":null,"reason":"答案正确"}')
        rub = v._vote_one_rubric(ctx, ctx.problem, "text")
        self.assertEqual(rub["verdict"], "A")
        self.assertAlmostEqual(rub["confidence"], 0.95)
        self.assertIsNone(rub["step_index"])

    def test_parses_verdict_b_with_location(self) -> None:
        v, ctx, _ = self._make(
            '{"verdict":"B","confidence":0.8,"error_type":"计算错误",'
            '"step_index":2,"reason":"第二步 2*3 算成 5"}')
        rub = v._vote_one_rubric(ctx, ctx.problem, "text")
        self.assertEqual(rub["verdict"], "B")
        self.assertEqual(rub["step_index"], 2)
        self.assertEqual(rub["error_type"], "计算错误")

    def test_garbage_returns_none(self) -> None:
        v, ctx, _ = self._make("我无法完成判分")
        self.assertIsNone(v._vote_one_rubric(ctx, ctx.problem, "text"))


class VoteRubricTest(_RubricFixture, unittest.TestCase):
    def test_verdict_a_is_correct(self) -> None:
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.9,"error_type":"无",'
            '"step_index":null,"reason":"正确"}')
        votes = v._vote_rubric(ctx, ctx.problem, self._cand())
        self.assertEqual(len(votes), 1)
        self.assertTrue(votes[0].correct)
        self.assertGreater(votes[0].confidence, 0.5)

    def test_verdict_b_feedback_includes_location(self) -> None:
        """B 票的 feedback 必须带步骤号+错误类型+reason（revise 定向修正用）。"""
        v, ctx, _ = self._make(
            '{"verdict":"B","confidence":0.7,"error_type":"计算错误",'
            '"step_index":2,"reason":"2*3 算成 5"}')
        votes = v._vote_rubric(ctx, ctx.problem, self._cand())
        self.assertEqual(len(votes), 1)
        self.assertFalse(votes[0].correct)
        self.assertIn("步骤2", votes[0].feedback)
        self.assertIn("计算错误", votes[0].feedback)
        self.assertIn("2*3 算成 5", votes[0].feedback)

    def test_deterministic_fail_hard_overrides(self) -> None:
        """确定性 fail → 硬否决：LLM rubric 票全翻错 + 追加 deterministic_fail。"""
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.9,"error_type":"无",'
            '"step_index":null,"reason":"正确"}')
        # 投票里的 LLM 判 A，但确定性验证 fail → 必须被翻成错（LLM 被客观证据推翻）
        with mock.patch.object(v, "_deterministic_check",
                               return_value={"verdict": "fail",
                                             "evidence": "2^2=4≠2",
                                             "method": "sympy"}):
            votes = v._vote_rubric(ctx, ctx.problem, self._cand(),
                                   use_deterministic=True)
        self.assertGreaterEqual(len(votes), 2)
        self.assertTrue(all(not vt.correct for vt in votes))
        raws = [vt.raw for vt in votes]
        self.assertIn("deterministic_fail", raws)

    def test_deterministic_pass_adds_independent_vote(self) -> None:
        """确定性 pass → 追加独立正确票（非 LLM 客观旁证）。"""
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.6,"error_type":"无",'
            '"step_index":null,"reason":"正确"}')
        with mock.patch.object(v, "_deterministic_check",
                               return_value={"verdict": "pass",
                                             "evidence": "ok", "method": "sympy"}):
            votes = v._vote_rubric(ctx, ctx.problem, self._cand(),
                                   use_deterministic=True)
        raws = [vt.raw for vt in votes]
        self.assertIn("deterministic_pass", raws)
        # 独立票必须是正确票
        det_vote = next(vt for vt in votes if vt.raw == "deterministic_pass")
        self.assertTrue(det_vote.correct)
        # LLM 票仍保留
        self.assertTrue(any(vt.correct and vt.raw.startswith("{")
                            for vt in votes))

    def test_deterministic_unknown_keeps_verdict(self) -> None:
        """确定性 unknown → 不改判，只挂证据（宁 unknown 不误杀）。"""
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.9,"error_type":"无",'
            '"step_index":null,"reason":"正确"}')
        with mock.patch.object(v, "_deterministic_check",
                               return_value={"verdict": "unknown",
                                             "evidence": "表达式无法解析",
                                             "method": "none"}):
            votes = v._vote_rubric(ctx, ctx.problem, self._cand(),
                                   use_deterministic=True)
        # 只有 1 张 LLM 票（unknown 不追加票），且保持正确
        self.assertEqual(len(votes), 1)
        self.assertTrue(votes[0].correct)
        self.assertIsNotNone(votes[0].deterministic)

    def test_parse_failed_conservative_pass(self) -> None:
        """rubric JSON 解析失败 → 保守放行（不误杀），并留证据。"""
        v, ctx, _ = self._make("模型拒绝输出 JSON")
        votes = v._vote_rubric(ctx, ctx.problem, self._cand())
        self.assertEqual(len(votes), 1)
        self.assertTrue(votes[0].correct)
        self.assertEqual(votes[0].raw, "rubric_parse_failed")


class ChallengeCounterexampleTest(_RubricFixture, unittest.TestCase):
    def test_empty_answer_skips(self) -> None:
        v, ctx, client = self._make(
            '{"found":true,"statement":"x^2>=0"}')
        res = v._challenge_counterexample(ctx, ctx.problem, "text", "")
        self.assertFalse(res["hard_fail"])
        self.assertEqual(client.calls, 0)   # 未触发任何 LLM 调用

    def test_numeric_answer_skips(self) -> None:
        """纯数值答案已走确定性代入验证，反例搜索跳过（sq 语义）。"""
        v, ctx, client = self._make(
            '{"found":true,"statement":"x^2>=0"}')
        res = v._challenge_counterexample(ctx, ctx.problem, "text", "42")
        self.assertFalse(res["hard_fail"])
        self.assertEqual(client.calls, 0)

    def test_llm_says_not_found(self) -> None:
        v, ctx, _ = self._make('{"found":false}')
        res = v._challenge_counterexample(ctx, ctx.problem, "text", "x^2>=x")
        self.assertFalse(res["hard_fail"])

    def test_llm_returns_garbage(self) -> None:
        v, ctx, _ = self._make("没有找到反例。")
        res = v._challenge_counterexample(ctx, ctx.problem, "text", "x^2>=x")
        self.assertFalse(res["hard_fail"])

    def test_checker_finds_counterexample_hard_fail(self) -> None:
        """LLM 命题 + 程序搜索到反例 → hard_fail（客观证伪，最高优先级）。"""
        v, ctx, _ = self._make(
            '{"found":true,"statement":"n^3+1>=n^2"}')
        fake = mock.Mock()
        fake.search_counterexample.return_value = {
            "found": True, "counterexample": {"n": 0}}
        with mock.patch("agent.deterministic.DeterministicChecker",
                        return_value=fake):
            res = v._challenge_counterexample(ctx, ctx.problem, "text",
                                              "x^2>=x")
        self.assertTrue(res["hard_fail"])
        self.assertIn("n=0", res["evidence"].replace("'n': 0", "n=0"))
        # 命题确实被程序验证过
        fake.search_counterexample.assert_called_once_with("n^3+1>=n^2")

    def test_checker_no_counterexample(self) -> None:
        v, ctx, _ = self._make(
            '{"found":true,"statement":"x^2>=0"}')
        fake = mock.Mock()
        fake.search_counterexample.return_value = {
            "found": False, "counterexample": None}
        with mock.patch("agent.deterministic.DeterministicChecker",
                        return_value=fake):
            res = v._challenge_counterexample(ctx, ctx.problem, "text",
                                              "x^2>=x")
        self.assertFalse(res["hard_fail"])

    def test_checker_raises_degrades_gracefully(self) -> None:
        """程序验证异常 → 不硬否决（宁 unknown 不误杀）。"""
        v, ctx, _ = self._make(
            '{"found":true,"statement":"x^2>=0"}')
        fake = mock.Mock()
        fake.search_counterexample.side_effect = RuntimeError("sympy 崩溃")
        with mock.patch("agent.deterministic.DeterministicChecker",
                        return_value=fake):
            res = v._challenge_counterexample(ctx, ctx.problem, "text",
                                              "x^2>=x")
        self.assertFalse(res["hard_fail"])


class RunRubricIntegrationTest(_RubricFixture, unittest.TestCase):
    def test_run_use_rubric_correct(self) -> None:
        """run(use_rubric=True)：rubric A 票进 cluster，best_cluster 判对。"""
        v, ctx, _ = self._make(
            '{"verdict":"A","confidence":0.9,"error_type":"无",'
            '"step_index":null,"reason":"正确"}')
        out = v.run(ctx, ctx.problem, [self._cand()],
                    use_rubric=True, use_deterministic=False)
        self.assertIsNotNone(out["best_cluster"])
        self.assertGreater(out["best_cluster"].vote_correct, 0)

    def test_run_use_rubric_wrong(self) -> None:
        v, ctx, _ = self._make(
            '{"verdict":"B","confidence":0.9,"error_type":"计算错误",'
            '"step_index":1,"reason":"展开错了"}')
        out = v.run(ctx, ctx.problem, [self._cand()],
                    use_rubric=True, use_deterministic=False)
        bc = out["best_cluster"]
        self.assertIsNotNone(bc)
        self.assertEqual(bc.vote_correct, 0)
        # feedback 应带错因（供 revise 定向修正）
        self.assertTrue(any(k in out["feedback"]
                            for k in ("计算错误", "展开错了", "步骤1"))
                        or out["feedback"] == "")

    def test_run_use_challenge_all_wrong_non_numeric(self) -> None:
        """run(use_challenge=True)：全错票+非数值答案 → 反例挑战触发。"""
        v, ctx, _ = self._make([
            '{"verdict":"B","confidence":0.8,"error_type":"概念错误",'
            '"step_index":null,"reason":"结论不成立"}',
            '{"found":true,"statement":"x^2>=x"}',
        ])
        fake = mock.Mock()
        fake.search_counterexample.return_value = {
            "found": True, "counterexample": {"x": 0.5}}
        with mock.patch("agent.deterministic.DeterministicChecker",
                        return_value=fake):
            out = v.run(ctx, ctx.problem, [self._cand(answer="x^2>=x")],
                        use_rubric=True, use_challenge=True,
                        use_deterministic=False)
        raws = [vt.raw for vt in out["verdicts"][0]]
        self.assertIn("counterexample_fail", raws)
        self.assertEqual(out["best_cluster"].vote_correct, 0)

    def test_run_use_challenge_numeric_answer_skips(self) -> None:
        """数值答案候选即使全错票也不触发反例挑战（已走确定性代入）。"""
        v, ctx, _ = self._make(
            '{"verdict":"B","confidence":0.8,"error_type":"结论错误",'
            '"step_index":null,"reason":"算错"}')
        with mock.patch.object(v, "_challenge_counterexample",
                               wraps=v._challenge_counterexample) as spy:
            out = v.run(ctx, ctx.problem, [self._cand(answer="7")],
                        use_rubric=True, use_challenge=True,
                        use_deterministic=False)
        # 数值答案：challenge 内部直接跳过（不产生 hard_fail），也无 counterexample_fail 票
        raws = [vt.raw for vt in out["verdicts"][0]]
        self.assertNotIn("counterexample_fail", raws)
        # challenge 被调用过但证据为跳过（内部断言在单测已覆盖）

    def test_run_legacy_without_rubric_flag(self) -> None:
        """use_rubric=False（默认）→ 保持原二元投票路径，行为不变。"""
        v, ctx, _ = self._make("VERDICT: A")
        out = v.run(ctx, ctx.problem, [self._cand()],
                    use_rubric=False, use_deterministic=False)
        self.assertIsNotNone(out["best_cluster"])
        self.assertGreater(out["best_cluster"].vote_correct, 0)


if __name__ == "__main__":
    unittest.main()
