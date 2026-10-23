# -*- coding: utf-8 -*-
"""子目标链复算式自检（2026-10-23）。

真实现场（official112-008）：sg5 把 `∑1/(…) ≥ (N-1)²/(N(N+1)-3) → 1`
推成 `D ≤ 777²/2`（应为 `777²/1`），凭空除了 2；sg8 又高估了构造的下确界。
第二模型独立复算后两处都命中，并给出正确结果 `777²`（= gold）。

本文件锁的是**机制契约**（不调真 LLM）：
  · 解析只认"指得出具体一步"的报错；
  · 无 key / 调用失败 / 输出不合法 ⇒ 返回空列表，绝不阻断主链；
  · `chain_from_trace` 同一 id 只保留最后一轮（最终答案来自最后一轮）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subgoal_selfcheck import (  # noqa: E402
    _parse, chain_from_trace, check_subgoal_chain, summarize)


def test_parse_takes_actionable_only():
    raw = ('```json\n{"suspects": ['
           '{"id": "4", "kind": "limit", "step": "极限算错", '
           '"expected": "777^2", "got": "777^2/2"},'
           '{"id": "9", "kind": "numeric", "step": "", "got": "x"}'
           ']}\n```')
    out = _parse(raw)
    assert len(out) == 1, "没有 step 的报错不算命中"
    assert out[0]["id"] == "4"
    assert out[0]["expected"] == "777^2"


def test_parse_garbage_returns_empty():
    for bad in ("", "no json here", "{broken", None):
        assert _parse(bad) == []


def test_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # 即使 .env 里有，也把环境变量清掉后仍应安全返回（.env 兜底会给值）
    r = check_subgoal_chain([{"id": "1", "title": "t"}], "problem")
    assert isinstance(r, list)


def test_empty_chain_returns_empty():
    assert check_subgoal_chain([], "p") == []


def test_chain_from_trace_keeps_last_round():
    trace = [
        {"id": 1, "title": "A1", "result": "本步结论: 值 = 1"},
        {"id": 2, "title": "B1", "result": "本步结论: 值 = 2"},
        {"id": 1, "title": "A2", "result": "本步结论: 值 = 111"},
        {"id": 2, "title": "B2", "result": "本步结论: 值 = 222"},
    ]
    chain = chain_from_trace(trace)
    assert [c["id"] for c in chain] == ["1", "2"], "顺序按首现、不重复"
    assert "111" in chain[0]["conclusion"], "同 id 保留最后一轮"
    assert "222" in chain[1]["conclusion"]


def test_chain_without_conclusion_line_still_has_basis():
    trace = [{"id": 3, "title": "T", "result": "直接写了一段推导，没有结论行"}]
    chain = chain_from_trace(trace)
    assert chain and chain[0]["basis"]


def test_summarize_shape():
    s = summarize([{"id": "4", "kind": "limit", "step": "极限算错",
                    "expected": "", "got": ""}])
    assert "1 处可疑" in s and "4" in s
    assert summarize([]) == ""


# --------------------------------------------------------------------------
# 注入合并提示词（用户 A 案：发现了就要用）
# --------------------------------------------------------------------------
def test_merge_prompt_carries_selfcheck_hint(monkeypatch):
    """自检结论必须进入 merge 的 user 提示词，且措辞是"请重新核算"而非"照抄"。"""
    import agent.subgoal_selfcheck as ssc
    from agent.sub_goal_solver__merge import _merge_results

    monkeypatch.setattr(ssc, "check_subgoal_chain",
                        lambda *a, **k: [{"id": "5", "kind": "limit",
                                          "step": "由 AM-HM 推出 777^2/2，极限算错",
                                          "expected": "D ≤ 777^2", "got": "777^2/2"}])
    monkeypatch.setattr(ssc, "chain_from_trace", lambda t: [])
    monkeypatch.setattr(ssc, "summarize", lambda s: "stub")

    seen = {}

    class _Orch:
        def __getattr__(self, n):
            # merge 还会调 _looks_placeholder / _merge_retry_hint 等；桩上统一给"否"
            return lambda *a, **k: False

        def record(self, *a, **k):
            pass

        def _prepare_merge_prompt(self, *a, **k):
            return ("BASE_USER", "SYS")

        def llm(self, ctx, msgs, *a, **k):
            seen["msgs"] = msgs
            return "【最终答案】\\boxed{777^2}"

    class _Ctx:
        subgoal_trace = []
        problem = "p"
        metadata = {}

        def __getattr__(self, n):
            return None

    _merge_results(_Orch(), _Ctx(), [], "", {}, "sum")

    blob = "\n".join(str(m.get("content", "")) for m in seen.get("msgs", []))
    assert "独立复核提示" in blob
    assert "777^2/2" in blob, "链里给出的错值要出现在提示里"
    assert "重新核算" in blob, "要求自行复算，不强制照抄"
    assert "BASE_USER" in blob, "原提示不能被覆盖"


def test_merge_without_suspects_keeps_prompt_clean(monkeypatch):
    """没有可疑项时不得注入任何复核段落。"""
    import agent.subgoal_selfcheck as ssc
    from agent.sub_goal_solver__merge import _merge_results

    monkeypatch.setattr(ssc, "check_subgoal_chain", lambda *a, **k: [])
    monkeypatch.setattr(ssc, "chain_from_trace", lambda t: [])
    monkeypatch.setattr(ssc, "summarize", lambda s: "")

    seen = {}

    class _Orch:
        def __getattr__(self, n):
            # merge 还会调 _looks_placeholder / _merge_retry_hint 等；桩上统一给"否"
            return lambda *a, **k: False

        def record(self, *a, **k):
            pass

        def _prepare_merge_prompt(self, *a, **k):
            return ("BASE_USER", "SYS")

        def llm(self, ctx, msgs, *a, **k):
            seen["msgs"] = msgs
            return "【最终答案】\\boxed{1}"

    class _Ctx:
        subgoal_trace = []
        problem = "p"
        metadata = {}

        def __getattr__(self, n):
            return None

    _merge_results(_Orch(), _Ctx(), [], "", {}, "sum")
    blob = "\n".join(str(m.get("content", "")) for m in seen.get("msgs", []))
    assert "独立复核提示" not in blob
