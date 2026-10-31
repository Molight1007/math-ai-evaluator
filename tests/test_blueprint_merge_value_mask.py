"""2.7「归并不带值」掩码（`blueprint_merge_value_mask`）测试。

覆盖（2026-10-27，用户：「先改 2、3 部分」+「避免过拟合」）：
  ① 纯函数 `mask_assigned_values` 的**命中**形态（实测泄漏原句）；
  ② **不命中**形态（符号等式、无值的归并句、被截断的关系式）；
  ③ `to_subgoal_plan` 只掩**收尾节点**、不碰中间节点（夹逼骨架要保留）；
  ④ `merge_strategy` 被掩，且 `ctx.blueprint`（`to_dict`）**原文保留**；
  ⑤ 开关关闭时逐字透传。

★ 判据只依赖**结构位置 + 句式**（`prompts/blueprint.py` 已明令"归并不带值"），
  不含任何题库文本、题号或具体数值清单 ⇒ 换题库不需改测试、也不会失效。
"""
import pytest

from agent.blueprint_planner import parse_blueprint
from agent.value_mask import MASK_PLACEHOLDER, mask_assigned_values


# --------------------------------------------------------------------------
# ① 命中
# --------------------------------------------------------------------------
@pytest.mark.parametrize("src,expect", [
    # 002 实测原句：gold = 1/2
    ("由 n1 给出 T = (√5-1)/2 的可行性证明",
     "由 n1 给出 T =" + MASK_PLACEHOLDER + " 的可行性证明"),
    # 002 另一次运行：φ 形式
    ("由 n1 给出 T=φ-1 可行的证明",
     "由 n1 给出 T=" + MASK_PLACEHOLDER + " 可行的证明"),
    # 002 的 LaTeX 分式
    (r"证明 T = \frac{\sqrt{5}-1}{2} 可行",
     "证明 T =" + MASK_PLACEHOLDER + " 可行"),
    # 001 实测原句：gold = 2-2m
    ("三者合并即得 T(m) = -4，具体值现场给出",
     "三者合并即得 T(m) =" + MASK_PLACEHOLDER + "，具体值现场给出"),
    # 无等号的边界断言
    ("由 n1 给出下界 -4（所有元组的两两和 ≥ -4）",
     "由 n1 给出下界 " + MASK_PLACEHOLDER + "（所有元组的两两和 ≥ -4）"),
    # prompt 反例原句
    ("由 n1、n2 得最终答案 1012",
     "由 n1、n2 得最终答案 " + MASK_PLACEHOLDER),
])
def test_masks_assigned_values(src, expect):
    out, n = mask_assigned_values(src)
    assert out == expect
    assert n == 1


def test_masks_multiple_spots():
    out, n = mask_assigned_values(
        "由 n1 给出下界 -4，由 n2 给出上界 -4，合并得 T(m) = -4")
    assert n == 3
    assert out.count(MASK_PLACEHOLDER) == 3


# --------------------------------------------------------------------------
# ② 不命中
# --------------------------------------------------------------------------
@pytest.mark.parametrize("src", [
    # 符号等式（定义式）—— 属关系，不是"值"
    "由 n1 给出必要条件 n ≥ 2^{n-1}",
    # 归并句里没有值（prompt 的正例写法）
    "由 n1 的构造与 n2 的不可能性证明夹逼，得出题目所求的最小取值",
    # 免责声明里的"结果"后面没有值
    "具体数值由 n1/n2/n3 的结果现场给出，本处不预设",
    "最终答案由 n3b 的结果给出",
    # 被截断的关系式：`= 2k` 的 `k` 属于表达式，不能只掩 `2`
    "由 n² - n = 2k 可知",
    # 空串
    "",
])
def test_keeps_non_values(src):
    out, n = mask_assigned_values(src)
    assert n == 0
    assert out == src.strip()


def test_truncated_relation_not_masked():
    """`= 2k` 不能被切成 `= 2` 再留下 `k`（会破坏等式）。"""
    out, n = mask_assigned_values("有 n² - n = 2k 成立")
    assert n == 0
    assert "2k" in out


# --------------------------------------------------------------------------
# ③④ 接线
# --------------------------------------------------------------------------
def _raw(final_stmt="由 n1、n2 得最终答案 (√5-1)/2"):
    return {
        "root_id": "g",
        "merge_strategy": "由 n1 给出 T = (√5-1)/2 可行，由 n2 给出上界，夹逼即得最小 T。",
        "nodes": [
            {"id": "g", "statement": "求最小实数 T",
             "children": ["n1", "n2", "final"]},
            # 中间节点：夹逼骨架必须保留具体候选值
            {"id": "n1", "statement": "证明 T = (√5-1)/2 可行"},
            {"id": "n2", "statement": "证明任意更小 T 不可行"},
            {"id": "final", "statement": final_stmt, "children": []},
        ],
    }


def test_final_node_masked_middle_kept():
    plan = parse_blueprint(_raw()).to_subgoal_plan(0)
    by_id = {s["id"]: s for s in plan["subgoals"]}
    # 收尾节点（拓扑序最后一步）被掩
    assert MASK_PLACEHOLDER in by_id[3]["description"]
    assert "(√5-1)/2" not in by_id[3]["description"]
    # 中间节点原文保留（夹逼骨架要写出候选值才能表达"证哪个可行"）
    assert by_id[1]["description"] == "证明 T = (√5-1)/2 可行"
    assert by_id[2]["description"] == "证明任意更小 T 不可行"


def test_merge_strategy_masked_but_stored_verbatim():
    dag = parse_blueprint(_raw())
    plan = dag.to_subgoal_plan(0)
    assert MASK_PLACEHOLDER in plan["merge_strategy"]
    assert "(√5-1)/2" not in plan["merge_strategy"]
    # 存储不降级：序列化出去的原文一字未改
    assert "(√5-1)/2" in dag.to_dict()["merge_strategy"]


def test_plan_keys_unchanged():
    """`to_subgoal_plan` 的三键契约不因掩码而扩张（诊断走 logger）。"""
    assert set(parse_blueprint(_raw()).to_subgoal_plan(0)) == {
        "subgoals", "merge_strategy", "anticipatory_lemmas"}


def test_switch_off_passes_through(monkeypatch):
    monkeypatch.setenv("BLUEPRINT_MERGE_VALUE_MASK", "0")
    plan = parse_blueprint(_raw()).to_subgoal_plan(0)
    assert "(√5-1)/2" in plan["merge_strategy"]
    assert "(√5-1)/2" in {s["id"]: s for s in plan["subgoals"]}[3]["description"]
