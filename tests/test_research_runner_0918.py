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
    txt = io.open(os.path.join(ROOT, rel), encoding="utf-8",
                  errors="replace").read()
    # 2026-10-08：`AgentConfig`（配置类）已逐字搬到 user_agent__config.py。
    # 读 user_agent.py 的源码级守卫改为读「主文件 + 抽取模块」并集 ——
    # 断言字面量与守卫意图均不变（非放宽判据），与 orchestrator 并集同口径。
    if rel.replace("\\", "/") == "user_agent.py":
        import glob
        for p in sorted(glob.glob(os.path.join(ROOT, "user_agent__*.py"))):
            txt += "\n" + io.open(p, encoding="utf-8",
                                  errors="replace").read()
    return txt


# ---- 研究档参数必须齐全（值取自项目实际使用的那组）----
REQUIRED = {
    "--max_time_per_question": "86400",
    "--tier_budget": "86400,86400,86400",
    # 2026-09-29：--paper_target_time 随 PaperPacer 删除（无人消费该参数）
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


def test_research_profile_matches_code_defaults_now():
    """2026-10-01 研究期决策：类默认值也放开 ⇒ 默认已与研究档一致。

    原测试要求"研究档 != 代码默认"（防研究档无意义）。现用户决策把默认值
    直接改成研究级（不限时/联网开），故改为断言"默认值已是研究级"。
    """
    import re
    ua = _src("user_agent.py")
    m = re.search(r"max_time_per_question:\s*int\s*=\s*(\d+)", ua)
    assert m and int(m.group(1)) >= 86400, "代码默认单题上限应为研究级(>=86400)"
    m2 = re.search(r"enable_web_search:\s*bool\s*=\s*(\w+)", ua)
    assert m2 and m2.group(1) == "True", "代码默认联网应为开（2026-10-01 研究期）"
    assert REQUIRED["--enable_web_search"] == "true"


def test_web_search_default_on_and_leansearch_default_on():
    """2026-10-01：联网搜索默认开（用户决策）；
    ★ 2026-10-12（用户决策 Q3）：「必须使用 leansearch，改为 true」⇒ LeanSearch
    类默认值 False → True。

    ⚠ 这是**决策变更**，不是放宽既有判据：旧断言锁定的是「赛期受限档默认 +
    未验证不上」，用户 2026-10-12 明确把 LeanSearch 纳入研究期必用清单。
    （`run_eval` 基线仍不得硬写 `"use_leansearch": True`，该断言原样保留。）
    """
    ua = _src("user_agent.py")
    assert "enable_web_search: bool = True" in ua
    assert "use_leansearch: bool = True" in ua
    rv = _src("run_eval.py")
    # run_eval 自带基线里不能出现 LeanSearch 开启（未在本次清单内）
    assert '"use_leansearch": True' not in rv


def test_docs_mention_the_two_profiles():
    for rel in ("SETUP.md", "README.md"):
        s = _src(rel)
        assert "run_research.py" in s, "%s 未提到研究版启动器" % rel
    s = _src("SETUP.md")
    assert "1100s" in s and "86400" in s
