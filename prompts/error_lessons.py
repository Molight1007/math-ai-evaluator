# -*- coding: utf-8 -*-
"""易错点记忆库（error lessons，2026-09-06 A 档轻量经验注入）。

把项目历轮评测/归因沉淀的「同类题常错点」做成检查清单片段，按题型与
题干关键词匹配后注入 solver 生成 / revise 提示，让 LLM 交付前自查。
与 B 档（自动入库+命中统计）共用同一数据源，未来可平滑升级。

防误伤三原则（历史教训：theorem_memory 无写入方变死代码、正则判据静默
失效——宁缺毋滥）：
1. 只匹配**命中关键词/题型**才注入，无命中返回空串 = 零噪音；
2. 表述为「自查清单」，绝不暗示答案内容（防把模型带偏）；
3. 输出规范类易错（截断/占位符/拒答/超时）已由代码层防护，**不注入**，
   避免 prompt 膨胀干扰正常输出。

来源：
- E-check  <- comb-032 51vs43 / geom-051 25vs29（数值代回错）
- E-form   <- algebra-003 2x³ 漏 +c（求函数题解族不完整）
- E-eq     <- nt-031 与 5(l-1)² 不等价（形变后不自检等价）
- E-extreme<- 009 心算极值 3.815 真值 4.94（全链自洽错值）
"""

from __future__ import annotations

import re as _re

# domain 判定用子串（题库 domain 有中英两套：Algebra/代数/NumberTheory/数论/…）
_ANSWER_QRY_DOMAINS = (
    "algebra", "代数", "number", "数论", "combin", "组合",
    "geometry", "几何", "equation", "方程", "calculus", "微积分",
    "analysis", "分析", "函数",
)

LESSONS = [
    {
        "id": "E-check",
        "name": "数值答案代回自检",
        # 解答题统一注入；证明题走整题推理，不适用"数值代回"检查清单
        "qtypes": ("解答题", "计算题"),
        "domains": _ANSWER_QRY_DOMAINS,
        "text": (
            "若最终答案包含具体数值/点/集合，交付前将其代回原题条件独立"
            "复核一次（必要时换一种算法重算），确认没有算错或代错。"
        ),
    },
    {
        "id": "E-form",
        "name": "解族完整性（常数项/参数）",
        "qtypes": ("解答题",),
        "domains": _ANSWER_QRY_DOMAINS,
        # 求函数/通解/一般形式/Find all → 检查是否漏任意常数项/参数及其范围
        "re_problem": r"(find all|求所有|通解|一般解|一般形式|general\s*solution|"
                      r"all\s*functions|函数\s*[:：]|f\s*\([^)]*\)\s*[:：])",
        "text": (
            "若题目求函数/解族/一般形式，交付前确认解族完整：是否遗漏任意"
            "常数项或参数（如 +c、n∈Z）、是否声明参数取值范围、边界情形"
            "（如零函数/退化情形）是否单独说明。"
        ),
    },
    {
        "id": "E-eq",
        "name": "符号形变等价自检",
        "qtypes": ("解答题", "证明题"),
        "domains": ("algebra", "代数", "number", "数论", "combin", "组合",
                    "equation", "方程", "calculus", "微积分", "analysis", "分析"),
        "text": (
            "若对表达式做了配方/换元/化简等形变，交付前将变形前后做符号展开"
            "对比（或取 2-3 个具体参数值代入两边核对），确保真正等价——"
            "仅『看起来像』不算数。"
        ),
    },
    {
        "id": "E-extreme",
        "name": "极值/最值声称先数值验证",
        "qtypes": ("解答题", "证明题"),
        "domains": ("algebra", "代数", "geometry", "几何", "calculus", "微积分",
                    "analysis", "分析", "equation", "方程"),
        "re_problem": r"(最大|最小|极大|极小|极值|最值|max|min|extreme|最大值|最小值)",
        "text": (
            "若题目涉及最大值/最小值/极值，先对声称的极值点做数值采样或代入"
            "边界验证，再下结论——心算错值后全链路自洽是高风险错误。"
        ),
    },
]


def match_lessons(domain: str = "", question_type: str = "",
                  problem: str = "") -> str:
    """按题型/领域/题干关键词返回命中的易错自查清单（无命中返回空串）。

    返回的文本为提示片段，调用方自行决定拼接位置与开关（enable_error_lessons）。
    """
    hits: list[dict] = []
    dom_l = (domain or "").lower()  # domain 中英混排、大小写不一，统一小写匹配
    for lesson in LESSONS:
        qts = lesson.get("qtypes") or ()
        if qts and question_type not in qts:
            continue
        doms = lesson.get("domains") or ()
        if doms and not any(k in dom_l for k in doms):
            continue
        rx = lesson.get("re_problem")
        if rx and not _re.search(rx, problem or "", _re.IGNORECASE):
            continue
        hits.append(lesson)
    if not hits:
        return ""
    lines = "\n".join(f"- {lesson['text']}" for lesson in hits)
    return (
        "【历史易错自查清单】（同类题曾反复出错，交付前逐条对照，"
        "不要盲从、以实际推理为准）：\n" + lines
    )


def lesson_ids(domain: str = "", question_type: str = "",
               problem: str = "") -> list[str]:
    """返回命中的 lesson id 列表（诊断/日志用）。"""
    out = []
    dom_l = (domain or "").lower()
    for lesson in LESSONS:
        qts = lesson.get("qtypes") or ()
        if qts and question_type not in qts:
            continue
        doms = lesson.get("domains") or ()
        if doms and not any(k in dom_l for k in doms):
            continue
        rx = lesson.get("re_problem")
        if rx and not _re.search(rx, problem or "", _re.IGNORECASE):
            continue
        out.append(lesson["id"])
    return out
