# -*- coding: utf-8 -*-
"""领域分类链路回归测试（2026-09-21，云端 n=38 逐题复核驱动）。

云端快照实测 9/38 题的 `diag.domain` 被污染：
  · `本题类型：代数` × 8
  · `本题类型：函数方程（Functional Equations）` + 换行 + 盒子内容 × 1

根因（两处，同一函数）：
  ① `stitch()` 契约是**保留** prefill 前缀（供调用方解析），而分类器直接
     `resp.strip()` ⇒ 前缀进了领域名；
  ② 解析结果回写了 `domain` 变量，而该变量保存的是**关键词分类结果**，
     被下方「关键词低分兜底」复用 ⇒ 该分支会把 LLM 残料当领域名。

附带发现：`_KNOWN_DOMAINS` 缺 `代数`，与 `prompts/policy.py` 的
`DOMAIN_HINTS`（有 `代数` 键）违反文件自述的「保持一致」契约。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.classifier import (                                    # noqa: E402
    _KNOWN_DOMAINS, _parse_domain_reply,
)
from prompts.policy import DOMAIN_HINTS                           # noqa: E402
from utils.prefill import prefill_messages, stitch                # noqa: E402


# ---------------------------------------------------------------- 解析层
@pytest.mark.parametrize("raw,expect", [
    ("代数", "代数"),
    ("数论", "数论"),
    ("组合数学", "组合数学"),
    # 模型回「领域 + 解释」→ 只取首行
    ("代数\n\n这是因为题目含群结构", "代数"),
    # 尾随标点必须剥掉
    ("数论。", "数论"),
    ("几何，", "几何"),
    # 脏回复（把盒子/推理写进同一行）→ 首行超长(26 字) ⇒ 弃用
    ("函数方程（Functional Equations）\n\n\\boxed{函数方程}", ""),
    # 超长行 → 弃用（正规领域名最长 11 字）
    ("这是一个非常长的解释性句子根本不是领域名", ""),
    ("", ""),
    ("   ", ""),
])
def test_parse_domain_reply(raw, expect):
    assert _parse_domain_reply(stitch("本题类型：", raw)) == expect


def test_prefill_prefix_is_stripped():
    """★ 核心回归：stitch 保留前缀，解析层必须剥掉。"""
    assert _parse_domain_reply(stitch("本题类型：", "代数")) == "代数"
    assert _parse_domain_reply(stitch("本题类型：", "数论")) == "数论"


def test_parse_rejects_echo_only():
    """模型只回显前缀（空续写）→ 必须返回空，不得当领域名。"""
    assert _parse_domain_reply(stitch("本题类型：", "")) == ""


def test_parse_rejects_box_content():
    raw = "函数方程（Functional Equations）\n\n\\boxed{函数方程}"
    got = _parse_domain_reply(stitch("本题类型：", raw))
    assert "\\boxed" not in got
    assert "\n" not in got


# ---------------------------------------------------------------- 契约层
def test_known_domains_superset_of_hints():
    """`_KNOWN_DOMAINS` 的契约是与 `DOMAIN_HINTS` 键保持一致。

    只允许「KNOWN 有、HINTS 无」（无提示，无害），
    **不允许「HINTS 有、KNOWN 无」** —— 那会让模型答对也无法归一。
    """
    missing = set(DOMAIN_HINTS) - set(_KNOWN_DOMAINS)
    assert not missing, "以下领域在 DOMAIN_HINTS 里却不在 _KNOWN_DOMAINS：%s" % sorted(missing)


def test_daili_is_known():
    assert "代数" in _KNOWN_DOMAINS


# ---------------------------------------------------------------- 流程层
class _Cfg:
    enable_question_type = True
    enable_domain_hint = True


class _Ctx:
    def __init__(self, problem):
        self.problem = problem
        self.domain = None
        self.question_type = None


class _Agent:
    """最小桩：只注入 llm 返回，其余走真实 ClassifierAgent.run。"""

    def __init__(self, reply):
        self.config = _Cfg()
        self._reply = reply
        self.records = []

    def llm(self, ctx, messages, temperature, max_tokens):
        return self._reply

    def record(self, ctx, kind, msg, **kw):
        self.records.append((kind, msg))


def _run(reply, problem="设 G 为有限群，求其阶。"):
    from agent.classifier import ClassifierAgent
    stub = _Agent(reply)
    ctx = _Ctx(problem)
    ClassifierAgent.run(stub, ctx)
    return ctx


def test_run_strips_prefix_for_novel_domain():
    """LLM 答 `代数` ⇒ ctx.domain 必须是 `代数`，不得带前缀。"""
    ctx = _run("本题类型：代数")
    assert ctx.domain == "代数", ctx.domain


def test_run_falls_back_to_keyword_when_llm_junk():
    """LLM 回垃圾时，必须回落到**关键词**结果，而不是把垃圾写进 domain。"""
    # 「积分」命中数学分析关键词(score>=1) 但不 >=2；LLM 回一个非中文垃圾
    ctx = _run("本题类型：???", problem="计算下面的积分。")
    assert ctx.domain not in (None, "", "???"), ctx.domain
    assert "本题类型" not in str(ctx.domain)


def test_run_empty_reply_does_not_random_domain():
    """空续写（只回显前缀）⇒ 绝不允许随机命中某个已知领域。"""
    ctx = _run("本题类型：", problem="计算下面的积分。")
    assert "本题类型" not in str(ctx.domain)
