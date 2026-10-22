# -*- coding: utf-8 -*-
"""蓝图自审：局部子树重写（`regenerate_subtree`）接线回补 —— 2026-10-22。

背景：`regenerate_subtree` 实现完整，但**全仓无调用**（历史备份里
`sub_goal_solver.py` 有三处，重构时丢了接线）。

契约：
  · 自审拒绝率 ≥ 阈值时，走 `regenerate_subtree`（只重写 LCA 子树、其余保留）；
  · `regenerate_subtree` 内部**在 LCA 触根时自动退化为整树** ⇒ 与旧行为兼容；
  · 开关 `blueprint_subtree_regen=0` 回到纯整树重写；
  · 反馈行统一带 `[nid]` 前缀（子树路径靠它筛反馈）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_ROOT, "agent", "blueprint_planner.py"),
            encoding="utf-8").read()


def test_switch_default_on():
    from contracts.switch_registry import get_bool
    assert get_bool("blueprint_subtree_regen") is True


def test_self_review_calls_subtree_regen():
    """接线锚点：自审路径必须调用 `regenerate_subtree`（防再次丢失）。"""
    assert "self.regenerate_subtree(" in _SRC
    # 且仍在开关控制下（否则无法 A/B）
    assert "_subtree_regen_enabled()" in _SRC


def test_lca_root_falls_back_to_whole_tree():
    """LCA 触根必须退化为整树 —— 这是接回后仍安全的前提。"""
    assert "LCA=根，退化整树重生成" in _SRC
    assert "return self.regenerate_with_feedback(" in _SRC


def test_feedback_lines_carry_node_id_prefix():
    """反馈行带 `[nid]`：子树路径靠它过滤「位于该子树内」的反馈。"""
    assert 'lines.append("[%s] %s"' in _SRC


def test_whole_tree_kept_as_fallback():
    """开关关闭时仍走整树重写（不是两条路都砍掉）。"""
    assert 'extra_context="【自审（第 4 次）】"' in _SRC
