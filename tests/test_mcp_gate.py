# -*- coding: utf-8 -*-
"""mcp 门控与「最小工程根标记」单测（2026-09-12）。

覆盖 2026-09-12 平台暴露的问题：闭包形态（Mathlib/*.olean + LEAN_PATH）下
lean-lsp-mcp 因缺 `lean-toolchain` / `lakefile.*` 而**结构性不可达**。
"""
import pytest

from tools.lean_local.lean_bridge import (
    _ensure_min_lake_project, _is_lake_workdir, _is_mcp_project_root,
    _mcp_gate_ok, _min_toolchain_content,
)


def _mk_closure(tmp_path):
    """构造「Mathlib 闭包」形态目录（含 .olean，无任何工程标记）。"""
    d = tmp_path / "closure"
    (d / "Mathlib").mkdir(parents=True)
    (d / "Mathlib" / "Tactic.olean").write_text("", encoding="utf-8")
    return d


def test_mcp_project_root_needs_toolchain_and_lakefile(tmp_path):
    d = _mk_closure(tmp_path)
    assert _is_mcp_project_root(str(d)) is False
    (d / "lakefile.toml").write_text('name = "x"\n', encoding="utf-8")
    assert _is_mcp_project_root(str(d)) is False        # 仍缺 lean-toolchain
    (d / "lean-toolchain").write_text("leanprover/lean4:v4.31.0\n",
                                      encoding="utf-8")
    assert _is_mcp_project_root(str(d)) is True


def test_autolake_fills_all_required_files(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    d = _mk_closure(tmp_path)
    assert _is_lake_workdir(str(d)) is False            # 补之前：非 lake 工程
    assert _mcp_gate_ok(str(d)) is True                 # 自动补齐后放行
    for fn in ("lakefile.toml", "lean-toolchain", "lake-manifest.json"):
        assert (d / fn).is_file(), f"缺少 {fn}"
    assert (d / "lean-toolchain").read_text(encoding="utf-8").strip()


def test_autolake_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    d = _mk_closure(tmp_path)
    assert _mcp_gate_ok(str(d)) is True
    before = (d / "lean-toolchain").read_text(encoding="utf-8")
    assert _mcp_gate_ok(str(d)) is True
    assert (d / "lean-toolchain").read_text(encoding="utf-8") == before


def test_autolake_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LEAN_MCP_AUTOLAKE", "0")
    d = _mk_closure(tmp_path)
    assert _mcp_gate_ok(str(d)) is False
    assert not (d / "lakefile.toml").exists()           # 严格模式零写入


def test_no_write_when_not_closure(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    d = tmp_path / "plain"
    d.mkdir()
    assert _ensure_min_lake_project(str(d)) is False
    assert list(d.iterdir()) == []                      # 不在任意目录乱写


def test_no_write_when_mathlib_has_no_olean(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    d = tmp_path / "empty_ml"
    (d / "Mathlib").mkdir(parents=True)
    assert _ensure_min_lake_project(str(d)) is False
    assert [p.name for p in d.iterdir()] == ["Mathlib"]


def test_existing_lake_project_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    d = tmp_path / "real"
    d.mkdir()
    (d / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
    (d / "lean-toolchain").write_text("leanprover/lean4:v4.31.0\n",
                                      encoding="utf-8")
    assert _mcp_gate_ok(str(d)) is True
    assert not (d / "lakefile.toml").exists()           # 已有工程 → 不干预


def test_toolchain_content_env_override(monkeypatch):
    monkeypatch.setenv("LEAN_TOOLCHAIN", "leanprover/lean4:v9.9.9")
    assert _min_toolchain_content().strip() == "leanprover/lean4:v9.9.9"


def test_toolchain_content_fallback_nonempty(monkeypatch):
    monkeypatch.delenv("LEAN_TOOLCHAIN", raising=False)
    assert _min_toolchain_content().strip()


@pytest.mark.parametrize("missing", ["", None])
def test_gate_on_empty_path(missing, monkeypatch):
    monkeypatch.delenv("LEAN_MCP_AUTOLAKE", raising=False)
    assert _mcp_gate_ok(missing) is False
    assert _is_mcp_project_root(missing) is False
