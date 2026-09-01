"""agent/calc_tool.py 单元测试（2026-09-01 新增净化容错）。

覆盖：
- 正常路径（纯表达式精确求值）
- 污染路径（中文/等号尾巴 → 净化重试）
- 不可净化路径（变量 → 保持 ERROR，不误伤）
- 多块混合回填
"""

from agent.calc_tool import safe_eval, extract_calc_blocks, resolve_all_calcs, _clean_expr


def test_safe_eval_pure():
    assert safe_eval("comb(50,3) * 2**10") == "20070400"
    assert safe_eval("1/2 + 1/3") == "5/6"
    assert safe_eval("3*7-1") == "20"
    assert safe_eval("fact(5)") == "120"


def test_safe_eval_errors():
    assert safe_eval("x+1").startswith("ERROR:")          # 变量拒绝
    assert safe_eval("").startswith("ERROR:")             # 空
    assert safe_eval("1/0").startswith("ERROR:")          # 除零


def test_clean_expr_strips_cn_and_tail():
    assert _clean_expr("3/6 + 2/6 + 1/6 约分后") == "3/6+2/6+1/6"
    assert _clean_expr("3*7-1=20") == "3*7-1"
    assert _clean_expr("1/2，然后 1/3") == "1/21/3"      # 剥中文后残留，无意义但仍安全
    assert _clean_expr("comb(50, 3) × 2") == "comb(50,3)2"  # 全角×被剥，ASCII 语法保留


def test_resolve_all_calcs_cleanup_retry():
    # 中文污染 → 净化重试成功
    out, resolved = resolve_all_calcs("结果是 <calc>3/6 + 2/6 + 1/6 约分后</calc>")
    assert resolved[0][1] == "1"
    assert "[计算] 3/6+2/6+1/6 = 1" in out
    # 等号尾巴 → 净化重试成功
    out, resolved = resolve_all_calcs("算 <calc>3*7-1=20</calc> 对吧")
    assert resolved[0][1] == "20"
    assert "= 20" in out


def test_resolve_all_calcs_uncleanable_keeps_error():
    # 变量不可净化 → 保留 ERROR，不误伤成错误值
    out, resolved = resolve_all_calcs("求 <calc>x+1</calc>")
    assert resolved[0][1].startswith("ERROR:")
    assert "ERROR" in out


def test_resolve_all_calcs_multi_blocks():
    text = "A=<calc>comb(50,3)</calc> B=<calc>1/2+1/3</calc>"
    out, resolved = resolve_all_calcs(text)
    assert len(resolved) == 2
    assert resolved[0][1] == "19600"
    assert resolved[1][1] == "5/6"
    assert "A=[计算] comb(50,3) = 19600" in out
    assert "B=[计算] 1/2+1/3 = 5/6" in out


def test_extract_blocks_order():
    assert extract_calc_blocks("<calc>1</calc> a <calc>2</calc>") == ["1", "2"]
