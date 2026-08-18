"""答案匹配升级验证：对已有快筛数据离线测试升级版匹配逻辑。

先验证收益与误报（零误报原则：原来判对的必须仍然对），确认后再落进 run_eval.py。
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import _clean_answer, _laTeX_to_py_frac, _try_float_compare, _try_fraction_compare, _extract_equals_candidates


# ============================================================
# 升级版清洗（在 _clean_answer 基础上增强）
# ============================================================
def _clean_answer_v2(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    # 剥行内公式包裹 \( \) 和 \[ \]
    t = re.sub(r"\\[\(\[]", "", t)
    t = re.sub(r"\\[\)\]]", "", t)
    # \dfrac / \tfrac / \cfrac → \frac（统一分数命令）
    t = re.sub(r"\\(?:dfrac|tfrac|cfrac)", r"\\frac", t)
    # 剥 \left \right 定界符
    t = re.sub(r"\\left", "", t)
    t = re.sub(r"\\right", "", t)
    # 原有逻辑
    t = t.replace("$", "").replace(" ", "")
    t = t.replace("\\displaystyle", "")
    t = t.replace("\\,", "").replace("\\;", "").replace("\\!", "")
    # 中文字符→英文标点归一（仅尾部/分隔，不改变数字）
    t = t.replace("，", ",").replace("。", ".").replace("；", ";")
    # 去尾部标点（. ; , ！ ？ 等）
    t = re.sub(r"[.;;,!！?？:：\s]+$", "", t)
    # 去开头"答："式前缀
    t = re.sub(r"^(?:答[案为是]?[:：]|答案[为是]?|结果为?[:：]?|解[:：]?)", "", t)
    for cmd, uni in _LATEX_SYMBOL_MAP_V2.items():
        t = t.replace(cmd, uni)
    return t


_LATEX_SYMBOL_MAP_V2 = {
    r"\pi": "π", r"\infty": "∞", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
    r"\Delta": "Δ", r"\lambda": "λ", r"\sqrt": "√",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\pm": "±",
}


def _norm_candidate_v2(text: str) -> str:
    """升级版候选规范化：增强清洗 + 分数转换 + 隐式乘法（供 SymPy）。"""
    return _laTeX_to_py_frac(_clean_answer_v2(text))


def _try_sympy_equal_v2(a: str, b: str) -> bool:
    """SymPy 代数等价（升级清洗后）。"""
    try:
        from utils.sympy_tools import are_expressions_equal
        return are_expressions_equal(a, b)
    except Exception:
        return False


def matches_v2(pred: str, gold: str) -> bool:
    """升级版多级匹配。"""
    if not pred or not gold:
        return False
    pf = _norm_candidate_v2(pred)
    gf = _norm_candidate_v2(gold)
    if not pf or not gf:
        return False
    # 1) 字符串相等（增强清洗后）
    if pf == gf:
        return True
    # 2) 分数等价
    if _try_fraction_compare(pf, gf):
        return True
    # 3) 浮点近似
    if _try_float_compare(pf, gf):
        return True
    # 4) SymPy 代数等价（增强清洗后）
    if _try_sympy_equal_v2(pf, gf):
        return True
    # 5) pred 是推导文本：提取 '= X' 结论匹配
    for cand in _extract_equals_candidates(pred):
        c = _norm_candidate_v2(cand)
        if c and (c == gf or _try_fraction_compare(c, gf) or _try_float_compare(c, gf)
                  or _try_sympy_equal_v2(c, gf)):
            return True
    # 6) 文本答案：去除所有标点/空白后比较（"条件收敛" vs "条件收敛。"）
    pf_text = re.sub(r"[^\w\u4e00-\u9fff\-+]", "", pf)
    gf_text = re.sub(r"[^\w\u4e00-\u9fff\-+]", "", gf)
    if pf_text and pf_text == gf_text and len(pf_text) >= 2:
        return True
    return False


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "outputs/ab_newbase30.jsonl"
    rows = load(path)
    orig_correct = sum(1 for r in rows if r.get("correct"))
    new_correct = 0
    flips = []          # 错→对（改进）
    regressions = []    # 对→错（误报，必须为零）
    for r in rows:
        pred, gold = r.get("predicted", "") or "", r.get("gold", "") or ""
        orig = bool(r.get("correct"))
        new = matches_v2(pred, gold) if (pred and gold) else orig
        if new:
            new_correct += 1
        if orig != new:
            if new:
                flips.append((r.get("id"), r.get("domain"), pred[:50], gold[:50]))
            else:
                regressions.append((r.get("id"), pred[:50], gold[:50]))

    print(f"原匹配: {orig_correct}/{len(rows)} ({orig_correct/len(rows):.0%})")
    print(f"升级匹配: {new_correct}/{len(rows)} ({new_correct/len(rows):.0%})")
    print(f"改进(错→对): {len(flips)} 题 | 误报(对→错): {len(regressions)} 题")
    print()
    print("=== 改进明细 ===")
    for pid, dom, pred, gold in flips:
        print(f"  + {str(pid)[:28]} [{dom}]")
        print(f"      pred={pred!r}")
        print(f"      gold={gold!r}")
    if regressions:
        print("\n!!! 误报（需要修）:")
        for pid, pred, gold in regressions:
            print(f"  - {pid}: {pred!r} vs {gold!r}")
    else:
        print("\n零误报 ✓")


if __name__ == "__main__":
    main()
