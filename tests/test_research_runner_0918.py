# -*- coding: utf-8 -*-
"""研究版启动器 `run_research.py` 的回归测试（2026-09-18）。

背景：代码默认值是**赛期受限档**（单题 1100s、联网关），
研究档（无时间限制 + 联网）只由命令行传入 ⇒ 必须有脚本固化，否则
"clone 下来跑的不是我们研究时的配置"。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ---- 研究档参数必须齐全（值取自项目实际使用的那组）----
REQUIRED = {
    "--max_time_per_question": "86400",
    "--tier_budget": "86400,86400,86400",
    "--paper_target_time": "86400000",
    "--max_total_time_seconds": "86400000",
    "--enable_web_search": "true",
    "--use_leansearch": "true",
    "--verifier_deep_final_enabled": "true",
    "--verifier_diversify_enabled": "true",
}


def test_research_args_cover_all_required():
    import run_research as R
    a = R.RESEARCH_ARGS
    for k, v in REQUIRED.items():
        assert k in a, "研究档缺参数 %s" % k
        assert a[a.index(k) + 1] == v, "%s 的值应为 %s" % (k, v)


def test_research_runner_is_path_independent():
    """仓库根必须由 `__file__` 反推，不得硬编码盘符。"""
    src = _src("run_research.py")
    assert 'sys.path.insert(0, REPO)' in src
    assert "os.path.dirname(os.path.abspath(__file__))" in src
    for bad in ("D:\\挑战杯", "D:/挑战杯", "C:\\Users"):
        assert bad not in src, "硬编码路径: %s" % bad


def test_research_runner_has_no_hardcoded_secret():
    src = _src("run_research.py")
    assert "sk-" not in src, "脚本内不得出现密钥"
    assert "OPENAI_API_KEY" in src          # 只做"未设置则提示"


def test_research_runner_banner_reads_from_argv():
    """横幅数值必须从 argv 反查（本项目曾因硬编码横幅印出假信息）。"""
    src = _src("run_research.py")
    assert "def _argval(" in src
    assert src.count("_argval(") >= 6


def test_research_profile_differs_from_code_defaults():
    """研究档不得等于代码默认值 —— 否则这个脚本毫无意义。"""
    import re
    ua = _src("user_agent.py")
    m = re.search(r"max_time_per_question:\s*int\s*=\s*(\d+)", ua)
    assert m and m.group(1) == "1100", "代码默认单题上限应为 1100"
    assert REQUIRED["--max_time_per_question"] != m.group(1)
    m2 = re.search(r"enable_web_search:\s*bool\s*=\s*(\w+)", ua)
    assert m2 and m2.group(1) == "False", "代码默认联网应为关"
    assert REQUIRED["--enable_web_search"] == "true"


def test_web_search_and_leansearch_defaults_stay_off():
    """研究档只由 CLI 传入 ⇒ 不得顺手改代码默认值（会污染平台提交语义）。"""
    ua = _src("user_agent.py")
    assert "enable_web_search: bool = False" in ua
    assert "use_leansearch: bool = False" in ua
    rv = _src("run_eval.py")
    # run_eval 自带基线里也不能出现联网开启
    assert '"enable_web_search": True' not in rv
    assert '"use_leansearch": True' not in rv


def test_docs_mention_the_two_profiles():
    for rel in ("SETUP.md", "README.md"):
        s = _src(rel)
        assert "run_research.py" in s, "%s 未提到研究版启动器" % rel
    s = _src("SETUP.md")
    assert "1100s" in s and "86400" in s
