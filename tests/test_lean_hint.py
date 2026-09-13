"""Lean 编译错误「修法提示」共享实现契约（2026-09-12）。

背景：实测发现 Lean 通道的三个落点（2.6 前置形式化 / 3.6 候选淘汰 / 6.5 最终
闸门）此前都把"编译器能给的精确错误"降级成 LLM 概括话术，模型因此不知道改哪
一行。2.6 在 3 题上「2 轮重试 0 成功」的根因即此 —— 真实错误是
`Set.Fintype.card` 这个 API 不存在、以及把"值当类型"用，而反馈却让模型
"重新审题"。

本测试锁定共享实现 `lean_bridge.hint_for_compile_error` 的覆盖范围与兜底语义，
并确认 2.6 侧（`lean_pre_verifier._hint_for_error`）委托它且永不返回空。
"""

from tools.lean_local.lean_bridge import hint_for_compile_error as H
from tools.lean_local.lean_pre_verifier import _hint_for_error as H26


def test_covers_api_not_found():
    """带点号的未知标识符 = API 名 → 必须给出等价 Mathlib 名称。"""
    out = H("x.lean:5:10: error: unknown identifier 'Set.Fintype.card'")
    assert "不存在" in out and "Set.ncard" in out and "Finset.card" in out


def test_covers_undefined_symbol():
    """不带点号 → 当作题目未定义的符号，提示先确认/自定义。"""
    out = H("x.lean:6:3: error: unknown identifier 'foo_bar'")
    assert "未定义" in out and "abbrev" in out


def test_covers_type_mismatch():
    out = H("error: Application type mismatch: The argument board_size has type ℕ "
            "of sort Type but is expected to have type Type ?u.9")
    assert "值不是类型" in out and "Fin n" in out


def test_covers_syntax():
    out = H("x.lean:8:127: error: expected ';' or line break")
    assert "语法错误" in out and "let" in out


def test_covers_instance():
    out = H("error: failed to synthesize instance of type class OfNat Prop 19")
    assert "实例" in out and "DecidableEq" in out


def test_covers_module_import():
    assert "import" in H("error: unknown module prefix 'Foo.Bar'")


def test_unrecognized_returns_empty():
    """未识别 → 返回空串，由调用方兜底（保证可安全叠加到 LLM 描述之后）。"""
    assert H("totally unrecognized failure xyz") == ""
    assert H("") == ""
    assert H(None) == ""


def test_26_delegates_and_never_empty():
    """2.6 场景必须给非空反馈（委托共享实现 + 兜底文案）。"""
    for err in ["x.lean:5:10: error: unknown identifier 'Set.Fintype.card'",
                "error: expected ';' or line break",
                "totally unrecognized failure xyz"]:
        assert H26(err).strip(), err
    assert "Set.ncard" in H26("error: unknown identifier 'Set.Fintype.card'")
