"""蓝图叶子级形式化下传（`blueprint_lean_sig`）测试。

覆盖（2026-10-15，用户：「把 lean 内化到蓝图构建里面」）：
  ① `_flatten_formal_sig` 归一（剥围栏 / 摊平 / 空值）；
  ② `BlueprintNode.formal_sig` 的解析 → 序列化往返 → 子树拷贝三链路不丢；
  ③ `to_subgoal_plan` 下传，且开关关闭时不下传；
  ④ `_compose_formal_sig` 六种输出形态（只回证明体 / 回完整声明 / 无签名 / 多行 / `:= sorry` / 带 import）；
  ⑤ `_call_step` 按有无签名切换**互斥**的工具指令。
"""
from types import SimpleNamespace

from agent.blueprint_planner__dag import (
    BlueprintDAG, BlueprintNode, _flatten_formal_sig,
)
from agent.sub_goal_solver__lean import _compose_formal_sig
from agent.sub_goal_solver__solve import _call_step
from prompts.sub_goal import SUBGOAL_LEAN_SIG_TEMPLATE, SUBGOAL_TOOL_INSTRUCTIONS


SIG = "example : (2:Nat)^10 = 1024 := by sorry"


# --------------------------------------------------------------------------
# ① 归一
# --------------------------------------------------------------------------
def test_flatten_formal_sig_strips_lean_fence():
    assert _flatten_formal_sig("```lean\ntheorem a : 1 = 1 := by sorry\n```") \
        == "theorem a : 1 = 1 := by sorry"


def test_flatten_formal_sig_flattens_and_trims():
    assert _flatten_formal_sig("  theorem a : P  ") == "theorem a : P"
    assert _flatten_formal_sig(None) == ""
    assert _flatten_formal_sig({"sig": "theorem b : Q"}) == "theorem b : Q"
    assert _flatten_formal_sig(["theorem c : R"]) == "theorem c : R"


# --------------------------------------------------------------------------
# ② 字段链路
# --------------------------------------------------------------------------
def _dag():
    return BlueprintDAG(
        nodes={
            "g": BlueprintNode(id="g", node_type="and", statement="目标",
                               children=["n1", "n2"], tool="llm"),
            "n1": BlueprintNode(id="n1", node_type="and", statement="证不等式",
                                children=[], tool="lean", formal_sig=SIG),
            "n2": BlueprintNode(id="n2", node_type="and", statement="算数值",
                                children=[], tool="sympy",
                                formal_sig="不该出现的签名"),
        },
        root_id="g", merge_strategy="m")


def test_roundtrip_preserves_formal_sig():
    d = _dag()
    d2 = BlueprintDAG.from_dict(d.to_dict())
    assert d2.nodes["n1"].formal_sig == SIG
    assert any("formal_sig" in nd for nd in d.to_dict()["nodes"])


def test_to_subgoal_plan_propagates_formal_sig():
    sgs = _dag().to_subgoal_plan()["subgoals"]
    by_tool = {s["tool"]: s for s in sgs}
    assert by_tool["lean"]["formal_sig"] == SIG
    # 蓝图本来就没给 sympy 节点签名（解析侧只保留 tool=lean 的），此处传空
    assert by_tool["sympy"]["formal_sig"] == ""


def test_switch_off_drops_formal_sig(monkeypatch):
    monkeypatch.setenv("BLUEPRINT_LEAN_SIG", "0")
    sgs = _dag().to_subgoal_plan()["subgoals"]
    assert all(s["formal_sig"] == "" for s in sgs)


# --------------------------------------------------------------------------
# ③ 解析：非 lean 节点的签名必须被丢弃
# --------------------------------------------------------------------------
def test_parse_keeps_sig_only_for_lean_nodes(monkeypatch):
    pytest = __import__("pytest")
    bp = pytest.importorskip("agent.blueprint_planner")
    raw = {"root_id": "g", "nodes": [
        {"id": "g", "type": "and", "statement": "目标", "children": ["a", "b"]},
        {"id": "a", "type": "and", "statement": "证明题", "children": [],
         "tool": "lean", "formal_sig": "```lean\n" + SIG + "\n```"},
        {"id": "b", "type": "and", "statement": "计算题", "children": [],
         "tool": "sympy", "formal_sig": SIG},
    ]}
    dag = bp.parse_blueprint(raw)
    assert dag is not None
    assert dag.nodes["a"].formal_sig == SIG
    assert dag.nodes["b"].formal_sig == ""


# --------------------------------------------------------------------------
# ④ 拼接
# --------------------------------------------------------------------------
def test_compose_proof_body_only():
    assert _compose_formal_sig(SIG, "norm_num") == \
        "example : (2:Nat)^10 = 1024 := by\n  norm_num"


def test_compose_full_declaration_unchanged():
    full = "example : (2:Nat)^10 = 1024 := by norm_num"
    assert _compose_formal_sig(SIG, full) == full


def test_compose_empty_sig_passthrough():
    assert _compose_formal_sig("", "norm_num") == "norm_num"


def test_compose_multiline_body_indented():
    out = _compose_formal_sig("theorem t : P := by sorry",
                              "have h : Q := by simp\nomega")
    assert out == "theorem t : P := by\n  have h : Q := by simp\n  omega"


def test_compose_sorry_without_by():
    assert _compose_formal_sig("example : P := sorry", "trivial") == \
        "example : P := by\n  trivial"


def test_compose_code_with_import_not_rewritten():
    code = "import Mathlib.Tactic\nexample : (2:Nat)^10 = 1024 := by norm_num"
    assert _compose_formal_sig(SIG, code) == code


# --------------------------------------------------------------------------
# ⑤ 求解侧指令注入（两条指令互斥）
# --------------------------------------------------------------------------
class _Agent:
    """`_call_step` 的最小替身：拦下 system 提示词，不发真实请求。"""

    def __init__(self):
        self.config = SimpleNamespace(enable_theorem_hint=False)
        self.systems = []

    def _multi_agent_n(self, ctx):
        return 1

    def _maybe_tool_llm(self, ctx, messages, temperature, max_tokens):
        self.systems.append(messages[0]["content"])
        return "【本步结果】\n结论: 完成"

    def _strip_tool_residue(self, text):
        return text

    def _apply_conclusion_contract(self, sg, result, raw_text=None):
        return None


def _ctx():
    return SimpleNamespace(theorem_hint_block="", metadata={})


def test_call_step_injects_signature_prompt():
    a = _Agent()
    sg = {"tool": "lean", "formal_sig": SIG}
    _call_step(a, _ctx(), "user", sg)
    sys_prompt = a.systems[0]
    assert "命题已由蓝图给定" in sys_prompt
    assert SIG in sys_prompt
    # 互斥：不得同时出现「自行写整段 Lean」那条指令
    assert SUBGOAL_TOOL_INSTRUCTIONS["lean"].strip() not in sys_prompt


def test_call_step_plain_instruction_without_sig():
    a = _Agent()
    sg = {"tool": "lean"}
    _call_step(a, _ctx(), "user", sg)
    sys_prompt = a.systems[0]
    assert SUBGOAL_TOOL_INSTRUCTIONS["lean"].strip() in sys_prompt
    assert "命题已由蓝图给定" not in sys_prompt


def test_lean_sig_template_has_single_placeholder():
    """模板只能有一个 `{formal_sig}` 占位符（多一个会在 format 时炸）。"""
    assert SUBGOAL_LEAN_SIG_TEMPLATE.count("{formal_sig}") == 1
    assert SUBGOAL_LEAN_SIG_TEMPLATE.format(formal_sig="X").count("X") == 1
