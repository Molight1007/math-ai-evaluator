# -*- coding: utf-8 -*-
"""契约测试：agent/lean_bridge.py（改造1）+ BugReport 扩展字段（改造2）。

覆盖：
  - LeanBridge.verify() 的 convert/analyze 映射；
  - 纯编译路径 _compile_lean（Lean 缺失/超时降级）；
  - Lean 环境缺失 → verdict='unknown' 降级；
  - BugReport 新增 repairable/suggestion 可选字段向后兼容；
  - 桥接工具函数（_strip_code_fence / _truncate_error_output / _parse_analysis_json）。
"""
import unittest
import json

from agent.base import BugReport, Finding
from agent.lean_bridge import (
    LeanBridge,
    detect_lean_environment,
    _compile_lean,
    _strip_code_fence,
    _truncate_error_output,
    _parse_analysis_json,
    _answer_embedded,
)


# ---------------------------------------------------------------------------
# Mock LLM 客户端（依赖注入，不走真实 API）
# ---------------------------------------------------------------------------
class MockClient:
    """按消息内容返回预设响应的 mock 客户端。"""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def chat(self, messages, temperature=0.0, max_tokens=0):
        self.calls.append(messages)
        # 只取 user/system 消息做 key 匹配（跳过 prefill 追加的 assistant 种子，
        # 否则种子消息成为最后一条导致 key 匹配失败返回空）
        user_msgs = [m for m in messages
                     if isinstance(m, dict) and m.get("role") != "assistant"]
        content = "\n".join(m.get("content", "") for m in user_msgs)
        for key, val in self.responses.items():
            if key in content:
                return val
        return ""


class _Budget:
    """极简 Budget 存根（只记录 spend 调用）。"""
    def __init__(self, max_calls=100):
        self.max_calls = max_calls
        self.used = 0

    def can_spend(self, n=1):
        return self.used + n <= self.max_calls

    def spend(self, n=1):
        self.used += n


class BugReportCompatTest(unittest.TestCase):
    """改造2：BugReport 扩展字段向后兼容。"""

    def test_default_fields_empty(self):
        r = BugReport()
        self.assertEqual(r.repairable, "")
        self.assertEqual(r.suggestion, "")
        self.assertFalse(r.is_valid())

    def test_roundtrip_with_new_fields(self):
        r = BugReport(
            findings=[Finding(location="S1", kind="Critical", severity=5,
                              desc="代换错误")],
            verdict="proof_invalid",
            repairable="partial",
            suggestion="第2步代换需改为 xx",
        )
        d = json.loads(r.to_json())
        self.assertEqual(d["repairable"], "partial")
        self.assertEqual(d["suggestion"], "第2步代换需改为 xx")
        r2 = BugReport.from_dict(d)
        self.assertEqual(r2.repairable, "partial")
        self.assertEqual(r2.suggestion, "第2步代换需改为 xx")
        self.assertEqual(len(r2.findings), 1)

    def test_old_json_still_parses(self):
        # 旧 JSON 不含新字段 → 默认空字符串
        r = BugReport.from_dict({"findings": [], "verdict": "unknown"})
        self.assertEqual(r.repairable, "")
        self.assertEqual(r.suggestion, "")

    def test_to_dict_omits_empty_new_fields(self):
        r = BugReport(verdict="proof_valid")
        d = r.to_dict()
        self.assertNotIn("repairable", d)
        self.assertNotIn("suggestion", d)


class HelperTest(unittest.TestCase):
    """桥接工具函数。"""

    def test_strip_code_fence(self):
        raw = "```lean\ntheorem x : True := by trivial\n```"
        self.assertEqual(_strip_code_fence(raw), "theorem x : True := by trivial")

    def test_strip_code_fence_no_fence(self):
        self.assertEqual(_strip_code_fence("theorem x : True := by trivial"),
                         "theorem x : True := by trivial")

    def test_truncate_error_output(self):
        long = "e" * 6000
        out = _truncate_error_output(long)
        self.assertLess(len(out), 5100)
        self.assertIn("已截断", out)
        self.assertEqual(_truncate_error_output(""), "")
        self.assertEqual(_truncate_error_output("abc"), "abc")

    def test_parse_analysis_json(self):
        raw = '前置文本 {"error_category": "logic_error", "repairable": "no"} 后置'
        d = _parse_analysis_json(raw)
        self.assertIsNotNone(d)
        self.assertEqual(d["error_category"], "logic_error")
        self.assertIsNone(_parse_analysis_json("no json here"))

    def test_answer_embedded_numeric(self):
        # 纯数字答案：代码必须包含该数字原值（数字边界）
        self.assertTrue(_answer_embedded(
            "example : (1 + 2 : ℕ) = 3 := by norm_num", "3"))
        self.assertFalse(_answer_embedded(
            "example : (1 + 2 : ℕ) = 3 := by norm_num", "4"))
        # 边界：3 不能匹配 13 / 33
        self.assertFalse(_answer_embedded(
            "example : (13 : ℕ) = 13 := by norm_num", "3"))
        self.assertTrue(_answer_embedded(
            "example : (13 : ℕ) = 13 := by norm_num", "13"))

    def test_answer_embedded_token(self):
        # 含字母 token 的答案：代码必须引用至少一个答案 token
        self.assertTrue(_answer_embedded(
            "example : (x : ℚ) ^ 2 = 1 := by nlinarith", "x=1或x=-1"))
        self.assertFalse(_answer_embedded(
            "example : (1 + 2 : ℚ) = 3 := by norm_num", "x=1或x=-1"))
        # 纯中文/符号答案：无法代码侧校验，放行
        self.assertTrue(_answer_embedded(
            "example : (2 : ℚ) ≤ 3 := by norm_num", "无解"))


class LeanEnvTest(unittest.TestCase):
    """Lean 环境检测（本环境大概率无 lake，仅验证返回结构不抛异常）。"""

    def test_detect_returns_dict(self):
        env = detect_lean_environment("definitely_not_existing_bin_xyz")
        self.assertIn("available", env)
        self.assertIn("version", env)
        self.assertIn("error", env)
        # 不存在的可执行文件 → 不可用
        self.assertFalse(env["available"])


class LeanCompileTest(unittest.TestCase):
    """纯编译路径（_compile_lean）在 Lean 缺失时的降级。"""

    def test_compile_lean_missing_binary(self):
        # Lean 环境缺失 → 返回 ok=False 且含错误信息，不抛异常
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            res = _compile_lean("theorem x : True := by trivial", d,
                                lean_executable="nonexistent_bin_xyz",
                                timeout=5.0)
            self.assertFalse(res["ok"])
            self.assertTrue(res["error"])


class LeanBridgeVerifyTest(unittest.TestCase):
    """LeanBridge.verify() 各路径。"""

    def test_lean_env_missing_degrades_unknown(self):
        # Lean 环境缺失 → verify() 返回 verdict='unknown'，不抛异常
        client = MockClient()
        bridge = LeanBridge(client, config=None)
        # 手动把环境缓存标记为不可用，避免依赖真实 lean 环境
        bridge._lean_env_cache = {"available": False, "version": "", "error": ""}
        report = bridge.verify("problem", "reasoning", timeout=5.0)
        self.assertIsNotNone(report)
        self.assertEqual(report.verdict, "unknown")
        self.assertEqual(report.findings, [])
        # 不应触发任何 LLM 调用
        self.assertEqual(client.calls, [])

    def test_convert_returns_empty_degrades_unknown(self):
        client = MockClient(responses={"": ""})  # 不匹配任何内容 → 返回空
        bridge = LeanBridge(client, config=None)
        # 强制环境可用（跳过真实检测）
        bridge._lean_env_cache = {"available": True, "version": "v4", "error": ""}
        report = bridge.verify("p", "r", timeout=5.0)
        self.assertEqual(report.verdict, "unknown")

    def test_compile_error_maps_logic_error(self):
        # 编译失败 + 分析判定 logic_error → verdict='proof_invalid' + Critical Finding
        client = MockClient({
            "待形式化的推理": "```lean\ntheorem x : True := by sorry\n```",
            "编译错误": json.dumps({
                "error_category": "logic_error",
                "repairable": "no",
                "suggestion": "第2步推导不成立",
                "critical_desc": "中间步骤存在循环论证",
            }),
        })
        bridge = LeanBridge(client, config=None)
        # 强制环境可用，但编译用不存在的 binary 使编译必失败 → 走 analyze
        bridge._lean_env_cache = {"available": True, "version": "v4", "error": ""}
        # 覆盖 _compile 为必失败（兼容 project_dir 分支的 lean_filename 参数）
        bridge._compile = lambda code, work_dir, **kw: {
            "ok": False, "error": "syntax error at line 1"}
        report = bridge.verify("p", "推理", timeout=5.0)
        self.assertIsNotNone(report)
        self.assertEqual(report.verdict, "proof_invalid")
        self.assertTrue(report.has_critical())
        self.assertEqual(report.repairable, "no")
        self.assertEqual(report.suggestion, "第2步推导不成立")

    def test_compile_error_maps_translation_unknown(self):
        # 纯翻译错误 → verdict='unknown'（降级）
        client = MockClient({
            "待形式化的推理": "code",
            "编译错误": json.dumps({
                "error_category": "translation_error",
                "repairable": "yes",
                "suggestion": "把 `by rfl` 改成 `by omega`",
                "critical_desc": "",
            }),
        })
        bridge = LeanBridge(client, config=None)
        bridge._lean_env_cache = {"available": True, "version": "v4", "error": ""}
        bridge._compile = lambda code, work_dir, **kw: {
            "ok": False, "error": "type mismatch"}
        report = bridge.verify("p", "r", timeout=5.0)
        self.assertEqual(report.verdict, "unknown")
        self.assertEqual(report.repairable, "yes")
        self.assertEqual(report.suggestion, "把 `by rfl` 改成 `by omega`")

    def test_compile_pass_returns_valid(self):
        # 编译通过且无 sorry → verdict='proof_valid'
        client = MockClient({"待形式化的推理": "theorem x : True := by trivial"})
        bridge = LeanBridge(client, config=None)
        bridge._lean_env_cache = {"available": True, "version": "v4", "error": ""}
        bridge._compile = lambda code, work_dir, **kw: {"ok": True, "error": ""}
        report = bridge.verify("p", "r", timeout=5.0)
        self.assertEqual(report.verdict, "proof_valid")
        self.assertTrue(report.is_valid())

    def test_budget_spent(self):
        # 计入 Budget：一次 verify 至少触发 LLM 调用（convert）
        client = MockClient({"待形式化的推理": "theorem x : True := by trivial"})
        budget = _Budget(max_calls=10)
        bridge = LeanBridge(client, config=None, budget=budget)
        bridge._lean_env_cache = {"available": True, "version": "v4", "error": ""}
        bridge._compile = lambda code, work_dir, **kw: {"ok": True, "error": ""}
        bridge.verify("p", "r", timeout=5.0)
        self.assertGreaterEqual(budget.used, 1)


class SolverProofDefaultTest(unittest.TestCase):
    """改造3硬性约束：enable_lean_verify 默认 False，证明通道不调用 Lean。"""

    def test_default_off_no_lean_call(self):
        from agent.solver import SolverAgent
        from agent.base import TaskContext, Budget
        from types import SimpleNamespace

        class SolverClient:
            def chat(self, messages=None, temperature=None, max_tokens=None, **kw):
                # 返回足够长的证明过程，避免被 <30 长度阈值拦截
                return ("证明过程。Step 1: 明确命题。Step 2: 由已知条件推导。"
                        "Step 3: 归纳证明。\n【最终答案】: 42")

        cfg = SimpleNamespace(
            enable_lean_verify=False,
            use_proof_channel=True,
            policy_sample_times=2,
            use_blueprint=False,
            use_lemma_accumulation=False,
            max_answer_tokens=8192,
            policy_max_tokens=8192,
            max_tokens_cap=8192,
            policy_temperature=0.3,
            revise_sample_times=2,
        )
        ctx = TaskContext(
            problem="证明 p",
            metadata={},
            domain="proof",
            deadline=0,  # 测试 fixture 伪 deadline（epoch）→ 不启用时间预算
            budget=Budget(max_calls=100),
        )
        solver = SolverAgent(SolverClient(), cfg)
        cand = solver._generate_proof(ctx)
        self.assertIsNotNone(cand)
        # 默认开关下不应产生 lean_verify trace
        lean_steps = [t for t in ctx.trace if t.get("step") == "lean_verify"]
        self.assertEqual(len(lean_steps), 0)


if __name__ == "__main__":
    unittest.main()
