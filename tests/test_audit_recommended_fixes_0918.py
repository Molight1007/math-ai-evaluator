# -*- coding: utf-8 -*-
"""2026-09-18 按审核建议应用的 4 项修改的回归测试。

  ① `formatter.py` 的第 4 个 `ctx.final_response` 直写点纳入非答案闸门
  ② `3.6` 候选过滤改用 `_looks_like_non_answer`（原只认 Markdown 行首标记）
  ③ `web_search` 提示词加「禁止在正文手写 <tool_call>」
  ④ 文本通道补埋点 `toolcall_text_detected`（让"想调用却被协议挡住"可见）
"""
import io
import os

from agent.base import Candidate, TaskContext
from agent.formatter import _looks_like_non_answer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ============ ① formatter 的第 4 个直写点 ============
def test_formatter_sink_guarded():
    src = _src("agent/formatter.py")
    # 不得再有裸写
    assert "ctx.final_response = format_response(answer)" not in src, \
        "formatter 仍是裸写（第 4 个漏网直写点）"
    assert "_fr_txt = format_response(answer)" in src
    assert "not _looks_like_non_answer(_fr_txt)" in src


def test_all_four_bare_writes_now_guarded():
    """审计确认的 4 个直写点必须全部纳管。"""
    o = _src("agent/orchestrator.py")
    f = _src("agent/formatter.py")
    for bare in ("ctx.final_response = _fresh.answer",
                 "ctx.final_response = _next.answer",
                 "ctx.final_response = direct_answer"):
        assert bare not in o, bare
    assert "ctx.final_response = format_response(answer)" not in f
    assert "def _set_final_response" in o


# ============ ② 3.6 过滤复用判据 ============
PROSE_CAND = [
    "步骤11：搜索已知结论",
    "继续找规律，目前 type B：2, 8, 10。",
    "让我搜索 $x^4 + 5$ 的分裂域次数。",
    "在答案中，通常接受 $Q(\\sqrt[4]{-5}, i)$ 或明确写出。",
]
LEGIT_CAND = [r"\boxed{2026}", "506", r"\boxed{有限差分法}",
              r"\boxed{\dfrac{1}{2}}", "2026, 2030"]


def test_36_filter_would_drop_prose_candidates():
    """3.6 过滤现在复用 `_looks_like_non_answer` ⇒ 过程叙述候选应被剔除。"""
    for a in PROSE_CAND:
        assert _looks_like_non_answer(a) is True, a


def test_36_filter_keeps_legit_candidates():
    for a in LEGIT_CAND:
        assert _looks_like_non_answer(a) is False, a


def test_36_filter_uses_single_source_of_truth():
    src = _src("agent/orchestrator.py")
    assert "from .formatter import _looks_like_non_answer as _nma36" in src
    assert "_keep_cand" in src
    # 全被滤掉时不得清空池（与 M2 同原则）
    assert "候选池 %d 个全部呈非答案形态（未清空" in src


# ============ ③ 提示词 ============
def test_web_search_hint_warns_against_text_toolcall():
    src = _src("agent/base.py")
    i = src.find("【可用工具】你还有函数 web_search(query)")
    assert i > 0
    seg = src[i:i + 900]
    assert "严禁" in seg and "<tool_call>" in seg, "未加禁止手写工具标记的提示"


# ============ ④ 文本通道埋点 ============
def test_text_channel_records_detection():
    src = _src("agent/base.py")
    i = src.find('self.record(ctx, "toolcall_text_detected"')
    assert i > 0, "文本通道仍无埋点 ⇒ 想调用未调用不可见"
    # 必须在「无 tool_calls」分支内、`return last_text` 之前
    j = src.find("return last_text", i - 2000)
    assert i < j or j < 0


def test_text_branch_still_returns_text():
    """埋点不得改变行为：文本分支仍应原样返回文本。"""
    src = _src("agent/base.py")
    assert "                if last_text and last_text.strip():\n                    return last_text" in src
