# -*- coding: utf-8 -*-
"""蓝图**节点契约**回归测试（2026-10-15，用户要求「子目标承接 + 每个子目标设定工具」）。

覆盖两条主线：
  A. 工具指派：提示词声明 `tool` → 解析归一（`_normalize_tool`）→ 落到节点
     → `to_subgoal_plan` 下传 → 求解侧能取到对应工具指令。
  B. 承接关系：`inputs[i].use`（把上游哪个结论当成本步的什么条件）→ `inputs_use`
     → 下传为子目标**序号** → `inputs_from`（含上游产出物/标题）
     → `_render_succession_block` 渲染成可注入的前提块。

并守住两个**此前静默丢字段**的老缺陷（回归面）：
  · `from_dict` 不读 inputs/method ⇒ 子树重写回路丢承接信息；
  · `_prune_subtree` / `_graft_subtree` 只保留 produces ⇒ 裁剪/嫁接丢角色与工具。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.blueprint_planner__dag import (  # noqa: E402
    BlueprintDAG, BlueprintNode, TOOL_WHITELIST,
    _normalize_tool, _input_use_map)
from agent.blueprint_planner import parse_blueprint  # noqa: E402
from agent.sub_goal_solver__solve import (  # noqa: E402
    _render_succession_block, _prepare_step_prompt)
from prompts.sub_goal import SUBGOAL_TOOL_INSTRUCTIONS  # noqa: E402


# ============================================================
# A. 工具指派
# ============================================================

def test_normalize_tool_accepts_whitelist():
    for t in TOOL_WHITELIST:
        assert _normalize_tool(t) == t


def test_normalize_tool_maps_aliases():
    assert _normalize_tool("Lean4") == "lean"
    assert _normalize_tool("  LEAN ") == "lean"
    assert _normalize_tool("符号计算") == "sympy"
    assert _normalize_tool("norm_num") == "numeric"
    assert _normalize_tool("叙述") == "llm"


def test_normalize_tool_unknown_is_empty_not_guess():
    """无法识别 ⇒ ""（未指派），**绝不做猜测性映射**。

    猜错会把叙述型步骤送进编译器，白白浪费一次重解。
    """
    for bad in ("", None, "garbage", "随便写点什么", "tool"):
        assert _normalize_tool(bad) == ""


def test_normalize_tool_list_picks_first_recognized():
    assert _normalize_tool(["lean", "sympy"]) == "lean"
    assert _normalize_tool(["???", "sympy"]) == "sympy"
    assert _normalize_tool(["???", "???"]) == ""


def test_tool_instructions_cover_whitelist():
    """四白名单键都必须在指令表里有条目（"llm" 允许为空串 = 不追加）。"""
    for t in TOOL_WHITELIST:
        assert t in SUBGOAL_TOOL_INSTRUCTIONS
    # lean/sympy/numeric 必须有实质指令；llm 是默认路径，显式留空
    for t in ("lean", "sympy", "numeric"):
        assert len(SUBGOAL_TOOL_INSTRUCTIONS[t].strip()) > 50
    assert SUBGOAL_TOOL_INSTRUCTIONS["llm"] == ""


def test_parse_blueprint_reads_tool():
    raw = {"root_id": "g", "nodes": [
        {"id": "g", "type": "and", "statement": "根", "children": ["a"]},
        {"id": "a", "type": "and", "statement": "证命题 P", "children": [],
         "tool": "Lean4"},
    ]}
    d = parse_blueprint(raw)
    assert d is not None
    assert d.nodes["a"].tool == "lean"


def test_parse_blueprint_reads_inputs_use():
    raw = {"root_id": "g", "nodes": [
        {"id": "g", "type": "and", "statement": "根", "children": ["a"]},
        {"id": "a", "type": "and", "statement": "甲", "children": [],
         "inputs": [{"id": "g", "use": "用根节点的范围约定"}]},
    ]}
    d = parse_blueprint(raw)
    assert d.nodes["a"].inputs_use == {"g": "用根节点的范围约定"}


def test_input_use_map_shapes():
    assert _input_use_map([{"id": "n1", "use": "u1"}]) == {"n1": "u1"}
    # 纯字符串形态没有 use 可抽 ⇒ 退化为空串（不是丢掉该 id）
    assert _input_use_map(["n2"]) == {"n2": ""}
    assert _input_use_map(None) == {}
    # dict 形态的 use 也摊平（模型会用 produces 那套结构串用）
    assert _input_use_map([{"id": "n3", "use": {"a": "b"}}]) == {"n3": "b"}


# ============================================================
# B. 承接关系
# ============================================================

def _chain_dag():
    """g → [n1(sympy), n2(lean, 承接 n1)]。"""
    return BlueprintDAG(
        nodes={
            "g": BlueprintNode(id="g", node_type="and", statement="根",
                               children=["n1", "n2"]),
            "n1": BlueprintNode(id="n1", node_type="and", statement="求驻点",
                                children=[], produces="f 的全部驻点集合",
                                tool="sympy"),
            "n2": BlueprintNode(
                id="n2", node_type="and", statement="由 n1 的驻点判定极小值",
                children=[], inputs=["n1"],
                inputs_use={"n1": "把 n1 求得的驻点作为本步逐一判定的取值"},
                produces="命题「f 在某驻点取极小」的真假", tool="lean"),
        },
        root_id="g")


def test_to_subgoal_plan_downpasses_tool():
    p = _chain_dag().to_subgoal_plan()
    assert [s["tool"] for s in p["subgoals"]] == ["sympy", "lean"]


def test_to_subgoal_plan_maps_inputs_use_to_index():
    p = _chain_dag().to_subgoal_plan()
    assert p["subgoals"][1]["inputs_use"] == {
        "1": "把 n1 求得的驻点作为本步逐一判定的取值"}
    assert p["subgoals"][0]["inputs_use"] == {}


def test_to_subgoal_plan_builds_inputs_from():
    """`inputs_from` 必须带上上游的**产出物与标题**，否则渲染不出承接前提。"""
    p = _chain_dag().to_subgoal_plan()
    frm = p["subgoals"][1]["inputs_from"]
    assert len(frm) == 1
    assert frm[0]["id"] == 1
    assert frm[0]["produces"] == "f 的全部驻点集合"
    assert "求驻点" in frm[0]["title"]
    assert "驻点" in frm[0]["use"]


def test_declared_input_merges_into_depends_on():
    """声明的 inputs 必须并进 depends_on —— 求解侧只认 depends_on 注入前序结果。

    若声明了"我要用 n1 的结论"却不在 depends_on 里 ⇒ 上游结果**根本不会被注入**
    ⇒ 承接关系名存实亡。
    """
    p = _chain_dag().to_subgoal_plan()
    assert p["subgoals"][1]["depends_on"] == [1]


def test_depends_on_never_points_forward():
    """承接必须是**前序**条件：反向引用会被丢弃，否则拓扑序被破坏成环。"""
    d = BlueprintDAG(
        nodes={
            "g": BlueprintNode(id="g", node_type="and", statement="根",
                               children=["n1", "n2"]),
            "n1": BlueprintNode(id="n1", node_type="and", statement="甲",
                                children=[], inputs=["n2"]),  # 反向声明
            "n2": BlueprintNode(id="n2", node_type="and", statement="乙",
                                children=[]),
        }, root_id="g")
    p = d.to_subgoal_plan()
    assert p["subgoals"][0]["depends_on"] == []
    assert p["subgoals"][0]["inputs_use"] == {}


def test_with_deps_false_keeps_legacy_depends_on():
    """`with_deps=False` 是 A/B 对照组：不产出任何依赖边（含声明的 inputs）。"""
    p = _chain_dag().to_subgoal_plan(with_deps=False)
    assert all(s["depends_on"] == [] for s in p["subgoals"])


def test_render_succession_block():
    p = _chain_dag().to_subgoal_plan()
    block = _render_succession_block(p["subgoals"][1])
    assert "【本步承接前提" in block
    assert "承接子目标 #1" in block
    assert "f 的全部驻点集合" in block
    assert "作为本步逐一判定的取值" in block
    # 无上游 ⇒ 不渲染（不得塞一个空壳块进提示词）
    assert _render_succession_block(p["subgoals"][0]) == ""
    assert _render_succession_block({}) == ""


# ============================================================
# 回归面：此前**静默丢字段**的两条老缺陷
# ============================================================

def test_from_dict_roundtrip_keeps_contract_fields():
    """`to_dict` → `from_dict` 是一条真实回路（子树重写 / dag_reviewer）。

    此前 `from_dict` **根本不读** inputs / method / tool / inputs_use ⇒
    重写后的子树静默丢掉承接与工具指派。
    """
    d = _chain_dag()
    d2 = BlueprintDAG.from_dict(d.to_dict())
    assert d2.nodes["n1"].tool == "sympy"
    assert d2.nodes["n2"].tool == "lean"
    assert d2.nodes["n2"].inputs == ["n1"]
    assert d2.nodes["n2"].inputs_use == {
        "n1": "把 n1 求得的驻点作为本步逐一判定的取值"}


def test_prune_subtree_keeps_contract_fields():
    d = _chain_dag()
    pruned = d._prune_subtree("n2")
    assert pruned.nodes["n1"].tool == "sympy"
    assert pruned.nodes["n1"].inputs_use == {}
    # 角色也必须保留（此前丢失会把 anticipatory 节点混进求解链）
    assert pruned.nodes["n1"].node_role == "required"


def test_graft_subtree_remaps_input_ids_with_prefix():
    """子树嫁接会给节点加前缀重命名 ⇒ `inputs` / `inputs_use` 的**键必须同步加前缀**。

    不同步 ⇒ 重写后的承接关系指向已被换掉的旧 id ⇒ 静默断链。
    """
    base = _chain_dag()
    new = BlueprintDAG(
        nodes={
            "r": BlueprintNode(id="r", node_type="and", statement="重分解",
                               children=["x1", "x2"]),
            "x1": BlueprintNode(id="x1", node_type="and", statement="子一",
                                children=[]),
            "x2": BlueprintNode(id="x2", node_type="and", statement="子二",
                                children=[], inputs=["x1"],
                                inputs_use={"x1": "用子一的结论"},
                                tool="lean"),
        }, root_id="r")
    grafted = base._graft_subtree("n2", new, id_prefix="r")
    assert grafted is not None
    x2 = grafted.nodes["r_x2"]
    assert x2.tool == "lean"
    assert x2.inputs == ["r_x1"], "inputs 的 id 必须随重命名加前缀"
    assert x2.inputs_use == {"r_x1": "用子一的结论"}, "inputs_use 的键同理"


# ============================================================
# C. 求解侧兑现：承接前提块是否真的进了 step 提示词
# ============================================================

def _stub_solver(**cfg):
    """轻量替身：只满足 `_prepare_step_prompt` 用到的三个契约面。

    ⚠ 方法必须在**类体外**绑定 —— 类体作用域读不到函数体内的局部名
       （`_prepare_step_prompt = _prepare_step_prompt` 会 NameError）。
    """
    import types

    class _S:
        def __init__(self):
            self.config = types.SimpleNamespace(
                use_lemma_accumulation=False, objective_tactic_enabled=False,
                **cfg)
            self.records = []

        def record(self, ctx, kind, text):
            self.records.append((kind, text))

        def _use_lemma(self, ctx):
            return False

    _S._prepare_step_prompt = _prepare_step_prompt
    return _S()


def test_step_prompt_injects_succession_block():
    from agent.base__types import TaskContext
    p = _chain_dag().to_subgoal_plan()
    sg = p["subgoals"][1]
    ctx = TaskContext(problem="求 f 的极小值", metadata={})
    s = _stub_solver()
    msg = s._prepare_step_prompt(ctx, sg, "规划摘要", "  子目标 #1 结果: x=1", "")
    assert "【本步承接前提" in msg, "承接前提块必须真的进入 step 提示词"
    assert "把 n1 求得的驻点作为本步逐一判定的取值" in msg
    # 位置：承接块在【前面步骤的结果】区**顶部**（先于上游结果原文）
    assert msg.index("【本步承接前提") < msg.index("子目标 #1 结果")


def test_step_prompt_without_inputs_from_is_unchanged():
    """无承接声明 ⇒ 提示词不得凭空多出一块（零回归面）。"""
    from agent.base__types import TaskContext
    p = _chain_dag().to_subgoal_plan()
    sg = p["subgoals"][0]
    ctx = TaskContext(problem="求 f 的极小值", metadata={})
    msg = _stub_solver()._prepare_step_prompt(
        ctx, sg, "规划摘要", "  （尚无前置结果）", "")
    assert "【本步承接前提" not in msg


def test_step_prompt_masks_asserted_values_in_succession_block():
    """承接块含上游 `produces`，同样可能是被写死的待求量 ⇒ 必须过 K11 掩码。

    这是本次**新增的注入面**：此前 title/description 有守卫，但承接块是新管道，
    不补掩码就等于给 K11（唯一过半根因 41.4%）开了一条新的泄漏通道。
    """
    from agent.base__types import TaskContext
    from agent.sub_goal_solver import _k11_mask_on
    if not _k11_mask_on():
        return          # 掩码关闭时本用例不适用
    p = _chain_dag().to_subgoal_plan()
    sg = p["subgoals"][1]
    # 把上游产出物改写成一个**内嵌断言数值**的形态（蓝图违反禁令的典型写法）
    sg["inputs_from"][0]["produces"] = "最小值为 4030"
    ctx = TaskContext(problem="求 f 的极小值", metadata={})
    s = _stub_solver()
    msg = s._prepare_step_prompt(ctx, sg, "规划摘要", "", "")
    assert "4030" not in msg, "承接前提块里的断言数值必须被屏蔽，不得注入提示词"
    assert any(k == "blueprint_lock_guard" for k, _ in s.records), \
        "屏蔽发生时应留痕（否则无法判断守卫生效与否）"
