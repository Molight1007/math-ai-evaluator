# -*- coding: utf-8 -*-
"""验证器「带推理的最终复核」单元测试（2026-09-15）。

背景（实测证据）
----------------
2026-09-15 的 10 题评测暴露出**验证器偏松**：
- 5 道**错题**（086/091/099/101/103）的**全部候选都是全票 A**；
- AuditGate 候选审核 **100% `unknown`**（等价于从不否决）；
- LeanGate 对 086 判 `valid`（假阳性），对 091/097/099 判 `lenient_pass` 降级放行。
⇒ **三道闸门对错答零否决**。

机理：常规投票用 `prefill_messages(..., "VERDICT: ")` 强制单行输出，
代码注释自述实测 **0.8s vs 不 prefill 的 70.2s（140×）** —— 0.8 秒不可能完成
系统提示词要求的"独立重算 + 逐条攻击" ⇒ 投票退化成"看一眼就点头"。

本模块测试新增的 `_deep_final_review`：**不 prefill**、只对最终选定答案做一次、
可否决；默认关（未 A/B 前行为不变）。

覆盖:
- `_last_verdict_ab`: 取**最后**一个 VERDICT、CoT 中间假设句不误判、无 VERDICT 返回 None
- `_deep_final_review`: 开关矩阵、超时跳过、异常降级、trace 埋点
- 否决接入：判 B 时把簇置信度压到 <0.5（复用既有 revise 通道）
- 配置项与白名单存在性
"""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from agent.base import TaskContext
from agent.verifier import VerifierAgent, _last_verdict_ab


def make_ctx(problem="probe", deadline=None):
    return TaskContext(problem=problem, metadata={}, deadline=deadline)


def make_verifier(**cfg):
    base = {
        "verifier_deep_final_enabled": True,
        "verifier_deep_final_min_remaining": 150.0,
        "verifier_deep_review_max_tokens": 4096,
    }
    base.update(cfg)
    return VerifierAgent(client=object(), config=SimpleNamespace(**base))


class LastVerdictTest(unittest.TestCase):
    """必须取**最后**一个 VERDICT —— 带 CoT 时中间会有假设句。"""

    def test_simple_a(self):
        self.assertIs(_last_verdict_ab("VERDICT: A"), True)

    def test_simple_b(self):
        self.assertIs(_last_verdict_ab("VERDICT: B（计算错）"), False)

    def test_takes_last_not_first(self):
        text = ("先看看：如果前提不成立则 VERDICT: B。\n"
                "但独立重算后一致，最终 VERDICT: A")
        self.assertIs(_last_verdict_ab(text), True)

    def test_takes_last_reverse_order(self):
        text = "初步 VERDICT: A\n复核后 VERDICT: B（前提不成立）"
        self.assertIs(_last_verdict_ab(text), False)

    def test_boxed_variant(self):
        self.assertIs(_last_verdict_ab("VERDICT: \\boxed{A}"), True)

    def test_full_width_colon(self):
        self.assertIs(_last_verdict_ab("VERDICT：B"), False)

    def test_no_verdict_returns_none(self):
        self.assertIsNone(_last_verdict_ab("我认为这个解答基本没问题"))
        self.assertIsNone(_last_verdict_ab(""))
        self.assertIsNone(_last_verdict_ab(None))


FAKE_REASONING = (
    "第 1 步 · 独立重算：我重新计算了该题，得到的关键中间结果是 R，自己的最终答案与候选一致。\n"
    "第 2 步 · 逐项比对：候选答案的各项与我的结果逐项相同，未发现差异。\n"
    "第 3 步 · 方法/定理适用性核查：解答使用了定理 T，其适用条件为有限集合，"
    "题目满足该条件；未发现硬套、也未发现有额外假设被遗漏。\n"
)


def fake_output(verdict_line: str, pad: int = 260) -> str:
    """构造**足够长**的伪复核输出。

    ⚠ 必须长于 `verifier_deep_review_min_chars`（默认 200），否则会被"未完成复核"
    护栏拦掉——实战中确实出现过模型只吐 12 字（一行 VERDICT）的情况，
    护栏就是为它设的。测试桩必须模拟"真的写了检查过程"的正常情形。
    """
    body = FAKE_REASONING
    while len(body) < pad:
        body += "补充核查：逐条对照定义与题设条件，未发现不一致之处。\n"
    return body + "\n" + verdict_line


class DeepFinalReviewTest(unittest.TestCase):

    def test_disabled_returns_empty_and_no_llm_call(self):
        v = make_verifier(verifier_deep_final_enabled=False)
        with mock.patch.object(v, "_deep_llm") as m:
            self.assertEqual(v._deep_final_review(make_ctx(), "p", None), "")
            m.assert_not_called()

    def test_no_cluster_returns_empty(self):
        v = make_verifier()
        with mock.patch.object(v, "_deep_llm") as m:
            self.assertEqual(v._deep_final_review(make_ctx(), "p", None), "")
            m.assert_not_called()

    def test_skip_when_time_critical(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 1)      # 只剩 1s
        cluster = SimpleNamespace(answer_norm="42")
        with mock.patch.object(v, "_deep_llm") as m:
            self.assertEqual(v._deep_final_review(ctx, "p", cluster), "")
            m.assert_not_called()
        self.assertTrue(any(t.get("step") == "deep_review" for t in ctx.trace))

    def test_returns_raw_and_records_verdict(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        cluster = SimpleNamespace(answer_norm="42")
        with mock.patch.object(v, "_deep_llm",
                               return_value=fake_output("VERDICT: B（方法不适用）")):
            raw = v._deep_final_review(ctx, "p", cluster)
        self.assertIn("VERDICT: B", raw)
        ev = [t for t in ctx.trace if t.get("step") == "deep_review"]
        self.assertTrue(ev)
        self.assertEqual(ev[-1]["verdict"], "B")
        self.assertEqual(ev[-1]["error_type"], "方法不适用")

    def test_a_verdict_has_no_error_type(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        cluster = SimpleNamespace(answer_norm="42")
        with mock.patch.object(v, "_deep_llm",
                               return_value=fake_output("VERDICT: A")):
            v._deep_final_review(ctx, "p", cluster)
        ev = [t for t in ctx.trace if t.get("step") == "deep_review"][-1]
        self.assertEqual(ev["verdict"], "A")
        self.assertEqual(ev["error_type"], "")

    def test_short_output_rejected_as_incomplete(self):
        """★ 实测场景（2026-09-15）：模型只吐 12 字（一行 `VERDICT: A`），
        一个字的检查过程都没有。**必须判为"未完成复核"**，
        绝不能当成"检查通过"——否则"没做检查"与"检查通过"无法区分。

        当时的根因是复用了投票模板，而它写着"在心里完成即可，不输出"+
        "请只输出 VERDICT"。现已改用专用复核提示词（VERIFIER_DEEP_REVIEW_*）。
        """
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        cluster = SimpleNamespace(answer_norm="42")
        with mock.patch.object(v, "_deep_llm", return_value="VERDICT: A"):
            self.assertEqual(v._deep_final_review(ctx, "p", cluster), "",
                             "12 字的输出必须被拒（否则会把'没检查'当'通过'）")
        ev = [t for t in ctx.trace if t.get("step") == "deep_review"][-1]
        self.assertNotIn("verdict", ev)
        self.assertIn("未按要求输出检查过程", ev.get("content", ""))

    def test_min_chars_zero_disables_guard(self):
        v = make_verifier(verifier_deep_review_min_chars=0)
        ctx = make_ctx(deadline=time.time() + 900)
        with mock.patch.object(v, "_deep_llm", return_value="VERDICT: B（计算错）"):
            raw = v._deep_final_review(ctx, "p", SimpleNamespace(answer_norm="42"))
        self.assertNotEqual(raw, "")

    def test_llm_exception_degrades_silently(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        cluster = SimpleNamespace(answer_norm="42")
        with mock.patch.object(v, "_deep_llm", side_effect=RuntimeError("boom")):
            self.assertEqual(v._deep_final_review(ctx, "p", cluster), "")

    def test_empty_answer_returns_empty(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        with mock.patch.object(v, "_deep_llm") as m:
            self.assertEqual(
                v._deep_final_review(ctx, "p", SimpleNamespace(answer_norm="")), "")
            m.assert_not_called()

    def test_prompt_allows_reasoning_no_prefill(self):
        """★ 关键：复核必须**不 prefill**，否则又退回 0.8s 的无推理分类。"""
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        seen = {}

        def _spy(_ctx, messages, temperature, max_tokens):
            seen["messages"] = messages
            return "VERDICT: A"

        with mock.patch.object(v, "_deep_llm", side_effect=_spy):
            v._deep_final_review(ctx, "p", SimpleNamespace(answer_norm="42"))
        # 传入的是完整的 system+user，而不是被 prefill 截断的五元素列表
        roles = [m["role"] for m in seen["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertIn("VERDICT", seen["messages"][1]["content"])


class VetoWiringTest(unittest.TestCase):
    """判 B ⇒ 簇置信度压到 <0.5（复用既有低置信度→revise 通道）。"""

    def test_cluster_confidence_collapses(self):
        from agent.verifier import AnswerCluster
        c = AnswerCluster("42")
        c.vote_correct, c.vote_total = 3, 3
        self.assertGreaterEqual(c.confidence, 0.5)
        # 模拟 run() 里的否决动作
        c.vote_correct = 0
        c.vote_total = max(1, c.vote_total)
        self.assertLess(c.confidence, 0.5)

    def test_feedback_marks_deep_rejection(self):
        from agent.verifier import _extract_error_type
        raw = "逐条核对……\nVERDICT: B（前提不成立, 方法不适用）"
        fb = ("【带推理复核判错｜错误类型：%s】%s" % (
            _extract_error_type(raw) or "未标注", raw.strip()))[:1500]
        self.assertIn("带推理复核判错", fb)
        self.assertIn("前提不成立", fb)


class DeepLlmStreamingTest(unittest.TestCase):
    """复核必须优先走**流式**。

    实测依据（2026-09-15）：同样内容的 prefill 单行版 1.3–3.6s 返回，
    而"允许推理（不 prefill）"版**两例均在 120s 全局超时处失败、输出 0 字**
    ⇒ 非流式路径对"要跑完整推理"的调用必然失败，功能等于不可用。
    """

    def test_prefers_streaming(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        seen = {}

        class _Cli:
            def chat(self, messages, temperature, max_tokens, stream=False):
                seen["stream"] = stream
                return "推理……\nVERDICT: B（前提不成立）"

        v.client = _Cli()
        out = v._deep_llm(ctx, [{"role": "user", "content": "x"}], 0.0, 4096)
        self.assertTrue(seen.get("stream"), "必须传 stream=True")
        self.assertIn("VERDICT: B", out)

    def test_falls_back_when_client_lacks_stream(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)

        class _OldCli:
            def chat(self, messages, temperature, max_tokens):
                return "VERDICT: A"

        v.client = _OldCli()
        with mock.patch.object(v, "llm", return_value="VERDICT: A"):
            self.assertEqual(
                v._deep_llm(ctx, [{"role": "user", "content": "x"}], 0.0, 4096),
                "VERDICT: A")

    def test_stream_exception_falls_back_to_plain(self):
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)

        class _BoomCli:
            def chat(self, messages, temperature, max_tokens, stream=False):
                raise RuntimeError("stream broken")

        v.client = _BoomCli()
        with mock.patch.object(v, "llm", return_value="VERDICT: B") as m:
            out = v._deep_llm(ctx, [{"role": "user", "content": "x"}], 0.0, 4096)
            self.assertEqual(out, "VERDICT: B")
            m.assert_called_once()

    def test_non_callable_client_uses_plain_path(self):
        v = make_verifier()
        v.client = object()          # 无 chat 方法
        ctx = make_ctx(deadline=time.time() + 900)
        with mock.patch.object(v, "llm", return_value="VERDICT: A"):
            self.assertEqual(
                v._deep_llm(ctx, [{"role": "user", "content": "x"}], 0.0, 4096),
                "VERDICT: A")


class DiagExportTest(unittest.TestCase):
    """★ 复核判定必须能在结果文件里看到（第一轮实测吃了亏）。

    086 的 `4_verify` 从十几秒涨到 249 秒（说明复核跑了），但导出里
    `n_reject_votes=0`、`error_types={}` —— 因为否决是通过**压低簇置信度**
    表达的、不产生新的 Verdict，所以那一轮**无法判断复核判了 A 还是 B**。
    """

    def test_counts_veto(self):
        from agent.orchestrator import _summarize_deep_review
        ctx = SimpleNamespace(trace=[
            {"step": "deep_review", "verdict": "B",
             "error_type": "前提不成立", "chars": 900}])
        s = _summarize_deep_review(ctx)
        self.assertTrue(s["ran"])
        self.assertEqual(s["verdict"], "B")
        self.assertEqual(s["error_type"], "前提不成立")

    def test_skipped_reason_surfaced(self):
        from agent.orchestrator import _summarize_deep_review
        ctx = SimpleNamespace(trace=[
            {"step": "deep_review", "content": "剩余 120s < 150s，跳过带推理复核"}])
        s = _summarize_deep_review(ctx)
        self.assertFalse(s["ran"])
        self.assertIn("跳过", s["skipped"])

    def test_no_entry(self):
        from agent.orchestrator import _summarize_deep_review
        s = _summarize_deep_review(SimpleNamespace(trace=[]))
        self.assertFalse(s["ran"])
        self.assertEqual(s["verdict"], "")

    def test_report_helper_renders(self):
        import importlib.util
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "gen_test_report.py")
        spec = importlib.util.spec_from_file_location("_gtr", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn("A（通过）", mod.deep_review_summary(
            {"deep_review": {"ran": True, "verdict": "A"}}))
        self.assertIn("B（否决）", mod.deep_review_summary(
            {"deep_review": {"ran": True, "verdict": "B",
                             "error_type": "方法不适用"}}))
        self.assertIn("未运行", mod.deep_review_summary(
            {"deep_review": {"ran": False, "skipped": "时间不足"}}))


class VoteDiversifyTest(unittest.TestCase):
    """★ 投票方差（2026-09-16）：候选有分歧时必须提高票数 + 启用非零温度。

    实测依据：standard 档 `verifier_voting_times=1` 且 `_vote_one` 温度**硬编码 0.0**
    ⇒ 每题只有一次分类判断，多票也无方差；后果是 6 道错题中 5 道的**全部候选全票 A**。
    """

    def _v(self, **cfg):
        base = {"verifier_diversify_enabled": True,
                "verifier_voting_times": 1, "verifier_temperature": 0.0,
                "verifier_disagreement_votes": 3,
                "verifier_disagreement_temperature": 0.7}
        base.update(cfg)
        return VerifierAgent(client=object(), config=SimpleNamespace(**base))

    def test_agreement_keeps_baseline(self):
        v = self._v()
        ctx = make_ctx()
        n, t = v._vote_profile(ctx, [{"answer": "42"}, {"answer": "42"}])
        self.assertEqual(n, 1)
        self.assertEqual(t, 0.0)

    def test_disagreement_raises_votes_and_temperature(self):
        v = self._v()
        ctx = make_ctx()
        n, t = v._vote_profile(ctx, [{"answer": "42"}, {"answer": "43"}])
        self.assertEqual(n, 3)
        self.assertGreater(t, 0.0)
        self.assertTrue(any(x.get("step") == "vote_diversify" for x in ctx.trace))

    def test_never_lowers_baseline_votes(self):
        v = self._v(verifier_voting_times=5)
        n, _ = v._vote_profile(make_ctx(), [{"answer": "a"}, {"answer": "b"}])
        self.assertEqual(n, 5, "分歧时不得把已有的多票降下来")

    def test_switch_off(self):
        v = self._v(verifier_diversify_enabled=False)
        n, t = v._vote_profile(make_ctx(), [{"answer": "a"}, {"answer": "b"}])
        self.assertEqual((n, t), (1, 0.0))

    def test_empty_answers_no_crash(self):
        v = self._v()
        self.assertEqual(v._vote_profile(make_ctx(), []), (1, 0.0))
        self.assertEqual(v._vote_profile(make_ctx(), None), (1, 0.0))
        self.assertEqual(v._vote_profile(make_ctx(), [{"answer": ""}]), (1, 0.0))

    def test_object_candidates_supported(self):
        v = self._v()
        n, t = v._vote_profile(
            make_ctx(), [SimpleNamespace(answer="AB"), SimpleNamespace(answer="AD")])
        self.assertEqual(n, 3)
        self.assertGreater(t, 0.0)

    def test_vote_one_uses_passed_temperature(self):
        """`_vote_one` 必须真的把温度传给 LLM（此前硬编码 0.0）。"""
        v = make_verifier()
        ctx = make_ctx(deadline=time.time() + 900)
        seen = {}

        def _spy(_ctx, messages, temperature, max_tokens):
            seen["t"] = temperature
            return "VERDICT: A"

        with mock.patch.object(v, "llm", side_effect=_spy):
            v._vote_one(ctx, "p", "cand", temperature=0.7)
        self.assertAlmostEqual(seen["t"], 0.7)

    def test_tier_votes_are_not_downgraded(self):
        """★ 2026-09-16 自审发现的回归：deep 档的 3 票曾被压回 1 票。

        `run()` 里 `voting_times = _d_votes` 无条件覆盖调用方传入的档位票数，
        而 `_vote_profile` 只读 `config.verifier_voting_times`(=1)
        ⇒ 与 `tier_voting_times[deep]=3` 的设计矛盾。
        修法：`_vote_profile(..., base_votes=...)` **以下限方式合并**。
        """
        v = VerifierAgent(client=object(), config=SimpleNamespace(
            verifier_diversify_enabled=True, verifier_voting_times=1,
            verifier_temperature=0.0, verifier_disagreement_votes=3,
            verifier_disagreement_temperature=0.7))
        ctx = make_ctx()
        # 候选一致（原本会让票数掉到 base=1）
        n, _ = v._vote_profile(ctx, [{"answer": "x"}, {"answer": "x"}],
                               base_votes=3)
        self.assertEqual(n, 3, "档位票数不得被 base=1 覆盖")
        # 分歧时取较大者
        n2, t2 = v._vote_profile(ctx, [{"answer": "x"}, {"answer": "y"}],
                                 base_votes=3)
        self.assertEqual(n2, 3)
        self.assertGreater(t2, 0.0)
        # 不传 base_votes 时退回 config（向后兼容）
        n3, _ = v._vote_profile(ctx, [{"answer": "x"}, {"answer": "x"}])
        self.assertEqual(n3, 1)


class VerdictParseOrderTest(unittest.TestCase):
    """★ 2026-09-16 实测 bug：复核输出 4 万字符却**无 VERDICT** ⇒ 判定"无法解析"。

    根因：旧模板要求「四步写完后，**最后**单独一行给 VERDICT」，
    而 `verifier_deep_review_max_tokens=16384` 会被推理吃满 ⇒ 截断在 VERDICT 之前。
    实测两题 chars=43960 / 37633，均为"无法解析"。

    修复：改为**判定置顶**（VERDICT 写在第一行），解析器改为
    "前 400 字符内有 VERDICT 就取首个，否则取末尾"。
    """

    def _f(self):
        from agent.verifier import _last_verdict_ab
        return _last_verdict_ab

    def test_verdict_first_is_taken(self):
        f = self._f()
        txt = "VERDICT: B（计算错）\n第1步…\n第2步…"
        self.assertIs(f(txt), False)

    def test_verdict_first_wins_over_later_hypothetical(self):
        """判定置顶后，推理里若再出现 VERDICT（假设句），不得覆盖首个。"""
        f = self._f()
        txt = ("VERDICT: A\n第1步 · 重算…\n"
               "注意：若这一步错了，则 VERDICT: B\n第2步…")
        self.assertIs(f(txt), True)

    def test_legacy_verdict_last_still_works(self):
        """向后兼容：旧格式（判定在末尾）仍应正确解析。"""
        f = self._f()
        txt = "第1步…\n第2步…\n第3步…\nVERDICT: B（方法不适用）"
        self.assertIs(f(txt), False)

    def test_truncated_no_verdict_returns_none(self):
        """被截断、完全没有 VERDICT ⇒ None（上层判为"未完成复核"）。"""
        f = self._f()
        self.assertIsNone(f("第1步 · 我重新计算了这道题" * 200))
        self.assertIsNone(f(""))
        self.assertIsNone(f(None))

    def test_boxed_variant(self):
        f = self._f()
        self.assertIs(f("VERDICT: \\boxed{A}\n…"), True)

    def test_fullwidth_colon(self):
        f = self._f()
        self.assertIs(f("VERDICT：B（漏项）\n…"), False)


class ConfigWiringTest(unittest.TestCase):

    def test_agent_config_fields(self):
        from user_agent import AgentConfig
        c = AgentConfig()
        self.assertIs(c.verifier_deep_final_enabled, False)   # 默认关
        self.assertEqual(c.verifier_deep_final_min_remaining, 150.0)
        self.assertEqual(c.verifier_deep_review_max_tokens, 16384)

    def test_kwargs_override_reaches_config(self):
        from user_agent import ReasoningAgent
        a = ReasoningAgent(object(), verifier_deep_final_enabled=True,
                           verifier_deep_final_min_remaining=200.0)
        self.assertTrue(a.config.verifier_deep_final_enabled)
        self.assertEqual(a.config.verifier_deep_final_min_remaining, 200.0)

    def test_blueprint_deps_field_default_on(self):
        from user_agent import AgentConfig
        self.assertIs(AgentConfig().blueprint_deps_enabled, True)


if __name__ == "__main__":
    unittest.main()
