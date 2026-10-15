# -*- coding: utf-8 -*-
"""智能体工具集（4 个常用工具）单测 —— 2026-10-15 用户定稿板块。

覆盖：门面导出 / calc_verify（真实 SymPy）/ to_lean（桩 client）/
leansearch（桩网络）/ lean_check（桩 runner，五类 verdict）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- 门面
def test_facade_exports():
    from tools.agent_toolkit import calc_verify, lean_check, leansearch, to_lean
    assert all(callable(f) for f in (lean_check, leansearch, calc_verify, to_lean))


# ---------------------------------------------------------------- ③ calc_verify
def test_calc_verify_ok_and_wrong():
    from tools.agent_toolkit import calc_verify
    r = calc_verify([
        {"expr": "2+2", "claimed": "4"},
        {"expr": "1/3 + 1/6", "claimed": "1/2"},
        {"expr": "19.9 + (10 - sqrt(9.9))**2", "claimed": "20"},   # 016 实况错算
    ])
    assert r["ok"] is False and r["n_ok"] == 2 and r["n_bad"] == 1
    bad = [x for x in r["results"] if not x["ok"]][0]
    assert "66.8" in bad["actual"]                 # 正确答案返回
    assert "算错" in bad["detail"]


def test_calc_verify_symbolic_equivalence():
    from tools.agent_toolkit import calc_verify
    r = calc_verify([{"expr": "sin(x)**2 + cos(x)**2", "claimed": "1"},
                     {"expr": "(a+b)**2", "claimed": "a**2 + 2*a*b + b**2"}])
    assert r["ok"] is True and r["n_ok"] == 2


def test_calc_verify_no_claim_and_unparsable():
    from tools.agent_toolkit import calc_verify
    r = calc_verify(["7*6"])                        # 单条字符串
    assert r["ok"] is True and r["results"][0]["actual"] == "42"
    r2 = calc_verify([{"expr": "__import__('os')", "claimed": "1"}])
    assert r2["n_err"] == 1 and r2["ok"] is False   # 防护命中 ⇒ 无法验证
    r3 = calc_verify([])
    assert r3["ok"] is True and r3["results"] == []


# ---------------------------------------------------------------- ④ to_lean
class _StubClient:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, temperature=0.0, max_tokens=1000):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_to_lean_parses_fence_and_notes():
    from tools.agent_toolkit import to_lean
    txt = ("```lean4\n-- 翻译注记：sqrt 记号按 ℝ≥0 处理\n"
           "theorem demo_sq (n : ℕ) : 2 ∣ n + n := by sorry\n```")
    r = to_lean("两个 n 的和是偶数", client=_StubClient(txt))
    assert r["ok"] and "theorem demo_sq" in r["lean_code"]
    assert r["decl_name"] == "demo_sq" and "ℝ≥0" in r["notes"]


def test_to_lean_missing_client_and_empty():
    from tools.agent_toolkit import to_lean
    assert to_lean("陈述").get("error", "").startswith("llm-client-missing")
    assert to_lean("").get("error") == "empty-statement"
    r = to_lean("x", client=_StubClient(RuntimeError("boom")))
    assert r["ok"] is False and "boom" in r["error"]


# ---------------------------------------------------------------- ② leansearch
def _lex_mod():
    """拿真模块对象。

    ⚠ 门面 `__init__` 用 `from .leansearch import leansearch` 导出函数后，
    包属性 `tools.agent_toolkit.leansearch` 是**函数**（标准门面行为）⇒
    必须走 importlib（sys.modules 直接命中模块），不能用属性链。
    """
    import importlib
    return importlib.import_module("tools.agent_toolkit.leansearch")


def test_leansearch_online(monkeypatch):
    from tools.agent_toolkit import leansearch
    monkeypatch.setattr(_lex_mod(), "_lex_search",
                        lambda q, k, t: [
                            {"name": "Mathlib.X.even_add", "short_name": "even_add",
                             "module": "Mathlib.X", "statement": "",
                             "informal": "偶数之和为偶数", "source": ""}])
    r = leansearch("even sum", top_k=3)
    assert r["ok"] and r["backend"] == "leanexplore"
    assert "even_add" in r["direction"]


def test_leansearch_offline_fallback(monkeypatch):
    from tools.agent_toolkit import leansearch

    def _boom(q, k, t):
        raise OSError("net down")
    monkeypatch.setattr(_lex_mod(), "_lex_search", _boom)
    monkeypatch.setattr(_lex_mod(), "_offline_search",
                        lambda q, k: [
                            {"name": "Nat.even_two", "short_name": "even_two",
                             "module": "M", "statement": "", "informal": "",
                             "source": ""}])
    r = leansearch("q")
    assert r["ok"] and r["backend"] == "offline" and "net down" in r["error"]


def test_leansearch_all_fail(monkeypatch):
    from tools.agent_toolkit import leansearch

    def _boom(q, k, t=0):
        raise OSError("down")
    monkeypatch.setattr(_lex_mod(), "_lex_search", _boom)
    monkeypatch.setattr(_lex_mod(), "_offline_search",
                        lambda q, k: _boom())
    r = leansearch("q")
    assert r["ok"] is False and r["backend"] == "unavailable"
    assert leansearch("")["error"] == "empty-query"


# ---------------------------------------------------------------- ① lean_check
_CODE_OK = "theorem t : 1 + 1 = 2 := by norm_num"


def _post(cases):
    from tools.agent_toolkit import lean_check
    out = []
    for kw, runner in cases:
        out.append(lean_check(lean_code=kw, runner=runner))
    return out


def test_lean_check_ok():
    [r] = _post([(_CODE_OK, lambda c, w, t: {"ok": True})])
    assert r["ok"] and r["verdict"] == "ok" and r["missing"] == []


def test_lean_check_proof_incomplete_lists_sorry():
    code = "theorem t : 1 + 1 = 2 := by\n  sorry"
    [r] = _post([(code, lambda c, w, t: {"ok": True})])
    assert r["ok"] and r["verdict"] == "proof_incomplete"
    assert r["missing"] and r["missing"][0]["step"] == "L2"


def test_lean_check_statement_error_parses_diagnostics():
    err = "demo.lean:3:8: error: unknown identifier 'foo'"
    [r] = _post([(_CODE_OK, lambda c, w, t: {"ok": False, "error": err})])
    assert r["verdict"] == "statement_error"
    assert r["errors"][0]["step"] == "L3" and "foo" in r["errors"][0]["detail"]


def test_lean_check_proof_failed_classified():
    err = "demo.lean:2:2: error: unsolved goals\n⊢ 1 + 1 = 3"
    [r] = _post([(_CODE_OK, lambda c, w, t: {"ok": False, "error": err})])
    assert r["verdict"] == "proof_failed"


def test_lean_check_env_missing_is_unknown():
    [r] = _post([(_CODE_OK, lambda c, w, t: {"ok": False, "error": "mcp-env-missing"})])
    assert r["verdict"] == "unknown" and "lean-env-unavailable" in r["error"]


def test_lean_check_fake_ok_is_unknown():
    """★ 实测教训：proxy 的 ok=True 只表示"MCP 调用完成"；
    LSP 起不来时仍 ok=True、错误藏在 raw —— 绝不能误报成"代码 ok"。"""
    fake = {"ok": True, "raw": ("Error executing tool lean_run_code: "
                                "Failed to start Lean language server at 'X': "
                                "Language server closed the connection"),
            "items": [], "goal": None, "error": ""}
    [r] = _post([(_CODE_OK, lambda c, w, t: fake)])
    assert r["verdict"] == "unknown" and r["ok"] is False
    assert "lean-env-unavailable" in r["error"]


def test_lean_check_items_diagnostics_are_errors():
    """LSP 正常时诊断在 items → 错误点（severity 容错解析）。"""
    ok_with_items = {"ok": True, "raw": "", "error": "", "goal": None,
                     "items": [{"severity": "error", "line": 2,
                                "message": "unsolved goals ⊢ 1 + 1 = 3"}]}
    [r] = _post([(_CODE_OK, lambda c, w, t: ok_with_items)])
    assert r["verdict"] == "proof_failed"
    assert r["errors"][0]["step"] == "L2"


def test_lean_check_needs_translation_without_client():
    from tools.agent_toolkit import lean_check
    r = lean_check(reasoning="一段推理", client=None)
    assert r["verdict"] == "needs_translation"
    r2 = lean_check()
    assert r2["error"].startswith("empty-input")


def test_lean_check_runner_exception_safe():
    def _boom(c, w, t):
        raise RuntimeError("lsp dead")
    [r] = _post([(_CODE_OK, _boom)])
    assert r["verdict"] == "unknown" and "runner-exception" in r["error"]
