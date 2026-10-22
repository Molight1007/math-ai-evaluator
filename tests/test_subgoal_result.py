# -*- coding: utf-8 -*-
"""`agent/subgoal_result.py` 单测（2026-10-20）。

该层承担三件事，全部在这里锁住：
  ① **通用分节**：不写死「逻辑推导/计算/结论」，模型多写一节不许丢；
  ② **唯一读写**：`write_step` 写两容器同值，`read_step`/`read_conclusion`
     是唯一取数口径，读点不再各自 `a or b`；
  ③ **保语义裁剪**：`clip` 超预算时优先保留结论节（`[:n]` 会切掉它）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subgoal_result import (  # noqa: E402
    cached_contract, cached_text, clip, compose_text, conclusion_of,
    demote_headings, parse_sections, read_conclusion, read_step, section,
    section_of, split_blocks, write_step,
)

_FULL = ("## 逻辑推导\n由 a+b=c 且 b=2 得 a=c-2\n"
         "## 计算\n3 + 2 = 5\n"
         "## 结论\n本步结论: 值 = 5\n本步依据: 代入求和")


# ------------------------------------------------------------------ 通用分节
def test_parse_sections_keeps_all_and_order():
    secs = parse_sections(_FULL)
    assert list(secs) == ["逻辑推导", "计算", "结论"]
    assert "a=c-2" in secs["逻辑推导"]


def test_parse_sections_keeps_unknown_sections():
    """★ 模型多写的节必须保留 —— 写死三节的解析器会把它们扔掉。"""
    txt = _FULL + "\n## 反例验证\n取 c=2 时 a=0，成立"
    secs = parse_sections(txt)
    assert "反例验证" in secs and "c=2" in secs["反例验证"]


def test_parse_sections_same_name_merged():
    txt = "## 结论\n第一段\n## 结论\n第二段"
    assert parse_sections(txt)["结论"] == "第一段\n第二段"


def test_parse_sections_ignores_deeper_headings():
    """`### xxx` 是三级标题，不能当成节名（否则 reasoning 的嵌层会被切碎）。"""
    secs = parse_sections("## 结论\n### 子目标 #1\n内容")
    assert list(secs) == ["结论"]
    assert "### 子目标 #1" in secs["结论"]


def test_parse_sections_no_heading_returns_empty():
    assert parse_sections("一整段没有分节的文字") == {}


def test_section_and_section_of_aliases():
    """调用方只说语义类别，别名知识留在本层（别在业务代码里枚举节名）。"""
    txt = "## 推导\n用反证法\n## 验算\n2+3=5\n## 结果\n5"
    assert "反证法" in section(txt, "推导")
    secs = parse_sections(txt)
    assert "反证法" in section_of(secs, "logic")      # 别名「推导」
    assert "2+3=5" in section_of(secs, "calc")        # 别名「验算」
    assert section_of(secs, "result") == "5"          # 别名「结果」
    assert section_of(secs, "unknown") == ""


def test_split_blocks_is_projection_not_storage():
    b = split_blocks(_FULL)
    assert set(b) == {"logic", "calc", "result"}
    assert b["result"].startswith("本步结论")
    # 无分节 ⇒ 整段进 result（旧契约）
    assert split_blocks("裸文本")["result"] == "裸文本"


def test_compose_text_marks_and_keeps_order():
    t = compose_text(parse_sections(_FULL))
    assert t.index("**逻辑推导**") < t.index("**计算**") < t.index("**结论**")


# ------------------------------------------------------------------ 读写一致
def test_write_step_writes_both_containers_same_value():
    sg, rmap = {"id": "s1"}, {}
    text = write_step(sg, rmap, _FULL)
    assert sg["result"] == text == rmap["s1"]
    # 存储是原文 ⇒ 可再解析（用 compose_text 存会变成 **节名**，再也解析不回来）
    assert parse_sections(sg["result"]).get("计算")


def test_write_step_exposes_structured_view():
    sg, rmap = {"id": "s1"}, {}
    write_step(sg, rmap, _FULL)
    assert sg["step_sections"]["结论"].startswith("本步结论")


def test_write_step_tolerates_missing_id():
    sg = {}
    assert write_step(sg, {}, "内容") == "内容"
    assert sg["result"] == "内容"


def test_read_step_prefers_sg_then_map():
    assert read_step({"id": 1, "result": "A"}, {1: "B"}) == "A"
    assert read_step({"id": 1}, {1: "B"}) == "B"
    assert read_step({"id": 1}, None) == ""
    assert read_step({"id": 1, "result": "A"}, {}) == "A"


def test_read_conclusion_priority():
    # ① 结构化契约最优先
    sg = {"id": 1, "conclusion": "5", "result": _FULL}
    assert read_conclusion(sg) == "5"
    # ② 无契约 ⇒ 取「结论」节（不是整段推导）
    sg2 = {"id": 2, "result": _FULL}
    assert read_conclusion(sg2).startswith("本步结论")
    assert "逻辑推导" not in read_conclusion(sg2)
    # ③ 无分节 ⇒ 整段
    assert read_conclusion({"id": 3, "result": "裸答案"}) == "裸答案"


def test_cached_text_and_contract_normalize_once():
    assert cached_text({"result": "R", "contract": {"ok": 1}}) == "R"
    assert cached_text("裸字符串") == "裸字符串"
    assert cached_text(None) == ""
    assert cached_contract({"contract": {"ok": 1}}) == {"ok": 1}
    assert cached_contract("裸字符串") == {}
    assert cached_contract({"contract": "not-a-dict"}) == {}


# ------------------------------------------------------------------ 保语义裁剪
def test_clip_no_budget_returns_as_is():
    assert clip(_FULL, 0) == _FULL
    assert clip(_FULL, 10 ** 6) == _FULL


def test_clip_keeps_conclusion_when_over_budget():
    """★ 硬切会先丢掉末尾结论；clip 必须把结论整段留下。"""
    out = clip(_FULL, 40)
    assert "本步结论: 值 = 5" in out
    assert len(out) <= 40 + 60          # 允许 note 开销


def test_clip_hard_cut_fallback_without_conclusion():
    txt = "## 逻辑推导\n" + "长" * 200
    out = clip(txt, 50)
    assert out.startswith("## 逻辑推导")
    assert "已按预算截断" in out


def test_demote_headings():
    out = demote_headings(_FULL)
    assert "## 逻辑推导" not in out
    assert "**逻辑推导**" in out
    assert "**结论**" in out
    # 三级标题不动（它本来就该是子级）
    assert "### 子目标" in demote_headings("### 子目标 #1\n内容")


def test_conclusion_of():
    assert conclusion_of(_FULL).startswith("本步结论")
    assert conclusion_of("没有分节") == ""
