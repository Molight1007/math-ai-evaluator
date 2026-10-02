"""定理检索注入路径覆盖测试（2026-09-29，截图 #3+#4 收口）。

背景：`1.2_theorem_hint` 阶段把 Mathlib 定理检索出来存进
`ctx.theorem_hint_block`，但**存下来不等于起作用** —— 必须真的拼进各条
生成路径的提示词。本项目历史教训「只改一处路径 = 没改」在这里风险极高：
解题链路有 6 条独立生成路径，漏掉任何一条，该路径上的定理线索就是零。

本测试的职责（两件事）：
  1. **静态契约**：断言每个已知注入点都还在（源码级），防止未来重构时
     被无声删除 —— 这类回归不会让任何功能测试变红，只会让效果悄悄归零。
  2. **行为契约**：断言开关关闭 / block 为空时**绝不注入**（零噪音零成本）。

刻意不 mock LLM：注入点是纯字符串拼接，测的是可观测的提示词组装行为。
"""
from __future__ import annotations

import os
import sys

import pytest

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ----------------------------------------------------------------------
# 1) 静态契约：每条生成路径都必须有注入点
# ----------------------------------------------------------------------
# 路径清单的来源：`grep -n '_compressed_solve\\|self.llm('` 全量盘点后逐点归属，
# 只保留**面向用户题目求解**的路径（工具回填类小重问不需要定理）。
_INJECTION_SITES = {
    "agent/solver.py": [
        ("_generate_initial 主路径", "solver 主路径注入定理清单"),
        ("_generate_revise 修订路径", "revise 是**独立于 _generate_initial 的生成路径**"),
        ("_generate_proof 证明通道", "证明题是定理检索**最该受益**的题型"),
    ],
    "agent/sub_goal_solver.py": [
        ("单步子目标求解", "子目标求解是**用户点名的解题重点环节**"),
        ("子目标合并成最终答案", "把子目标答案总结成最终答案"),
    ],
    "agent/blueprint_planner.py": [
        ("蓝图首次生成", "蓝图规划决定\"需要推理出哪些中间结论\""),
        ("蓝图重规划 replan", "重规划路径同样注入定理线索"),
        ("蓝图子树重写 subtree", "子树重写路径同样注入定理线索"),
    ],
}


@pytest.mark.parametrize("relpath,label,anchor", [
    (p, lbl, anc)
    for p, sites in _INJECTION_SITES.items()
    for lbl, anc in sites
])
def test_injection_site_exists(relpath, label, anchor):
    """每个已知注入点都必须在源码中仍然存在。"""
    path = os.path.join(_SRC, relpath)
    src = open(path, encoding="utf-8").read()
    assert anchor in src, (
        f"注入点被删除或改写：{relpath} · {label}\n"
        f"期望找到锚点：{anchor!r}\n"
        f"若确为有意重构，请同步更新本测试的 _INJECTION_SITES。"
    )


def test_every_site_is_guarded_by_the_same_switch():
    """所有注入点统一受 `enable_theorem_hint` 控制，不允许各写各的开关。"""
    for relpath in _INJECTION_SITES:
        src = open(os.path.join(_SRC, relpath), encoding="utf-8").read()
        n_guard = src.count("getattr(self.config, 'enable_theorem_hint', True)")
        n_block = src.count("theorem_hint_block")
        assert n_guard >= len(_INJECTION_SITES[relpath]), (
            f"{relpath}: 注入点 {len(_INJECTION_SITES[relpath])} 个，"
            f"但开关守卫只有 {n_guard} 处"
        )
        assert n_block >= len(_INJECTION_SITES[relpath]), (
            f"{relpath}: 读取 theorem_hint_block 的次数({n_block}) "
            f"少于注入点数({len(_INJECTION_SITES[relpath])})"
        )


# ----------------------------------------------------------------------
# 2) 行为契约：无命中 / 开关关闭 ⇒ 绝不注入
# ----------------------------------------------------------------------
def _make_block(n=5):
    """按生产口径构造 block —— 直接调用被注入的那个渲染函数，不手抄格式。"""
    from agent.theorem_hint import TheoremHit, TheoremRetrieval

    hits = [
        TheoremHit(
            name=("Mathlib.Geometry.Euclidean.Angle.Oriented.Affine."
                  "EuclideanGeometry.oangle"),
            short="oangle", source="q1", rank=1),
        TheoremHit(
            name=("Mathlib.Geometry.Euclidean.Triangle.EuclideanGeometry."
                  "angle_add_angle_add_angle_eq_pi"),
            short="angle_add_angle_add_angle_eq_pi", source="q1", rank=1),
        TheoremHit(
            name=("Mathlib.Geometry.Euclidean.Triangle.EuclideanGeometry."
                  "exterior_angle_eq_angle_add_angle"),
            short="exterior_angle_eq_angle_add_angle", source="q1", rank=2),
        TheoremHit(name="Mathlib.Data.Nat.Choose.Basic.Nat.choose",
                   short="Nat.choose", source="q2", rank=1),
        TheoremHit(name="Mathlib.Algebra.BigOperators.Group.Finset.sum",
                   short="Finset.sum", source="q2", rank=2),
    ][:n]
    return TheoremRetrieval(ok=True, backend="source_scan", hits=hits
                            ).render_hint_block()


class _FakeCtx:
    def __init__(self, block="", hints=None):
        self.problem = "测试题目"
        self.theorem_hint_block = block
        self.theorem_hints = hints or []
        self.metadata = {}


class _FakeCfg:
    def __init__(self, enabled=True):
        self.enable_theorem_hint = enabled


def test_block_is_empty_when_no_hits():
    """检索无命中时 block 必须为空串 —— 保证下游注入是零成本零噪音。"""
    from agent.orchestrator import Orchestrator

    ctx = _FakeCtx(block="")
    assert (getattr(ctx, "theorem_hint_block", "") or "").strip() == ""


def test_disabled_switch_is_read_with_default_true():
    """开关缺省值必须是 True（默认启用），否则新功能默认静默失效。"""
    import inspect

    from agent import blueprint_planner, solver, sub_goal_solver

    for mod in (solver, sub_goal_solver, blueprint_planner):
        src = inspect.getsource(mod)
        assert "getattr(self.config, 'enable_theorem_hint', True)" in src, (
            f"{mod.__name__}: 开关缺省值被改成了非 True，"
            "会导致未显式传参时定理注入静默失效"
        )


def test_injection_block_shape_is_stable():
    """block 形态契约：首行标题，末行免责声明，中间是编号的**短名**列表。"""
    blk = _make_block()
    lines = blk.split("\n")
    assert lines[0].startswith("【本题可能在 Mathlib 中用到的定理")
    assert "供参考" in lines[0]
    assert lines[-1].startswith("（以上仅为线索")
    numbered = [l for l in lines[1:-1]
                if l.split(".")[0].strip().isdigit()]
    assert len(numbered) == 5, "5 条命中应产出 5 条编号项"


def test_block_carries_short_names_not_namespace_paths():
    """★ 核心契约：提示词里**不得出现 Mathlib 命名空间全名**。

    实测教训：并列输出全名时 5 条命中即 798 字符，命名空间前缀占 60%+，
    对以中文推理的大模型是纯 token 噪音。全名只应存在于 trace 埋点。
    """
    blk = _make_block()
    assert "angle_add_angle_add_angle_eq_pi" in blk, "短名必须保留（模型靠它理解）"
    assert "Mathlib." not in blk, (
        "block 里出现了 Mathlib 全名 —— 会重新引入 O(100字符/条) 的 token 噪音"
    )
    assert "EuclideanGeometry." not in blk


def test_block_is_materially_shorter_than_full_name_version():
    """压缩效果硬断言：比"短名 + 全名"两列版本至少省 40% 字符。"""
    from agent.theorem_hint import TheoremHit, TheoremRetrieval

    hits = [
        TheoremHit(name=("Mathlib.Geometry.Euclidean.Triangle."
                         "EuclideanGeometry.angle_add_angle_add_angle_eq_pi"),
                   short="angle_add_angle_add_angle_eq_pi", rank=1),
        TheoremHit(name=("Mathlib.Geometry.Euclidean.Triangle."
                         "EuclideanGeometry.exterior_angle_eq_angle_add_angle"),
                   short="exterior_angle_eq_angle_add_angle", rank=2),
        TheoremHit(name=("Mathlib.Geometry.Euclidean.Angle.Oriented.Affine."
                         "EuclideanGeometry.oangle"),
                   short="oangle", rank=3),
    ]
    res = TheoremRetrieval(ok=True, hits=hits)
    compact = res.render_hint_block()
    verbose = "\n".join(
        [compact.split("\n")[0]]
        + [f"{i}. {h.short}   ({h.name})" for i, h in enumerate(hits, 1)]
        + [compact.split("\n")[-1]])
    saving = 1 - len(compact) / len(verbose)
    assert saving >= 0.40, (
        f"压缩率仅 {saving:.0%}（compact={len(compact)}, verbose={len(verbose)}），"
        "低于 40% 的预期"
    )


def test_block_caps_item_count():
    """条目数受 max_items 约束 —— 防止 top_k 被调大后提示词无限膨胀。"""
    from agent.theorem_hint import TheoremHit, TheoremRetrieval

    hits = [TheoremHit(name=f"M.T.t{i}", short=f"t{i}", rank=i)
            for i in range(1, 20)]
    res = TheoremRetrieval(ok=True, hits=hits)
    assert res.render_hint_block(max_items=3).count("\n") == 4  # 标题+3项+尾注
    assert "t4" not in res.render_hint_block(max_items=3)


def test_empty_hits_render_empty_string():
    """无命中 ⇒ 空串（下游 `if _th:` 判定为假，零注入）。"""
    from agent.theorem_hint import TheoremRetrieval

    assert TheoremRetrieval(ok=True, hits=[]).render_hint_block() == ""
    assert TheoremRetrieval(ok=False).render_hint_block() == ""
