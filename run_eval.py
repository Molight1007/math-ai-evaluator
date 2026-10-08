#!/usr/bin/env python
from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
# 2026-10-08 拆分：判分族搬到 run_eval__scoring.py 后，本文件已不再直接读开关
#   （判分族的 `_sw_bool` 在 scoring 模块就地 import）；此行保留作**契约面**
#   （`run_eval._sw_bool` 仍可解析），故标 noqa。
try:
    from agent.switch_registry import (  # noqa: F401
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (  # noqa: F401
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
# -*- coding: utf-8 -*-
"""
MathPilot 本地评测脚本 —— 仅用于本地开发调试，非平台正式评测调用入口。
平台只调用 user_agent.py 的 ReasoningAgent.solve()，不会执行此文件。
支持 JSONL 题库批量评测、答案规范化匹配、领域细分统计、断点续跑。

本文件为本地版（题库注册表）与赛事版（答案提取增强 / A/B 能力开关）的合并版：
- 保留本地题库注册表: --bank 新高数 / 1000题高数 / 高数a / IMO-AnswerBench / IMO-ProofBench / all
- 引入赛事版答案匹配增强: _extract_equals_candidates 结论提取、LaTeX 符号归一化
- 引入赛事版 A/B 能力开关: --voting_times / --use_scoring / --revise_rounds / --use_proof / ...

用法:
    python run_eval.py --test_file tests.jsonl --output results.jsonl
    python run_eval.py --test_file tests.jsonl --concurrency 4 --resume results.jsonl
    python run_eval.py --bank 新高数 --output results.jsonl
    python run_eval.py --bank 1000题高数 --concurrency 4
    python run_eval.py --bank all --concurrency 4
"""

import argparse
import json
import logging
import os
import re  # noqa: F401  （拆分后本文件不再直接用 re；保留作契约面）
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("MathPilot.Eval")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from user_agent import ReasoningAgent
from utils.llm_client import LLMClient

# ===========================================================================
# 题库注册表
# ===========================================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DATA = os.path.join(PROJECT_ROOT, "sample_data")

# 题库名称 → 文件路径映射
BANK_REGISTRY: Dict[str, str] = {
    # ---- 自建题库 ----
    "新高数": os.path.join(SAMPLE_DATA, "新高数.jsonl"),
    "1000题高数": os.path.join(SAMPLE_DATA, "1000题高数.jsonl"),
    "高数a": os.path.join(SAMPLE_DATA, "高数a.jsonl"),
    # ---- IMO-Bench (Google DeepMind 公开基准) ----
    "IMO-AnswerBench": os.path.join(SAMPLE_DATA, "IMO-AnswerBench.jsonl"),
    "IMO-ProofBench": os.path.join(SAMPLE_DATA, "IMO-ProofBench.jsonl"),
}

def resolve_bank(bank_name: str):
    """解析题库名称，返回 JSONL 文件路径。支持 'all' 返回所有题库路径。"""
    if bank_name == "all":
        return [p for _, p in BANK_REGISTRY.items() if os.path.exists(p)]
    if bank_name in BANK_REGISTRY:
        path = BANK_REGISTRY[bank_name]
        if os.path.exists(path):
            return path
        else:
            logger.error(f"题库 '{bank_name}' 的文件不存在: {path}")
            return None
    return None

def list_banks():
    """列出所有已注册的题库。"""
    print("\n已注册的题库:")
    print("-" * 60)
    for name, path in BANK_REGISTRY.items():
        if os.path.exists(path):
            count = sum(1 for _ in open(path, "r", encoding="utf-8"))
            size_kb = os.path.getsize(path) / 1024
            print(f"  {name:<15} {count:>5} 题  {size_kb:>8.1f} KB  ({path})")
        else:
            print(f"  {name:<15} [文件缺失] ({path})")
    print("-" * 60)
    print("用法: python run_eval.py --bank <题库名> [其他参数]")
    print("       python run_eval.py --bank all [其他参数]  # 评测所有题库")
    print()


# ===========================================================================
# 2026-10-08 拆分 re-export（保对外契约 · 同一对象）
# ---------------------------------------------------------------------------
# 判分族 → run_eval__scoring.py / run_eval__classify.py；
# 评测引擎 + 埋点快照 → run_eval__engine.py。以下**原位 re-export** ⇒ 全仓
# `from run_eval import answers_match / EvalEngine / ...` 一行都不用改。
# ===========================================================================
from run_eval__scoring import (  # noqa: F401
    _LATEX_SYMBOL_MAP, _FUNC_CMDS, _FRAC_ALIASES, _LAYOUT_CMDS,
    _FRAC_ONLY_RE, _FRAC_LATEX_RE, _DIVISIBLE_RE, _FUNC_PREFIX_RE,
    _NO_SOLUTION_WORDS, _SPLIT_SEP_RE,
    _clean_answer, _norm_candidate, _extract_equals_candidates, _extract_boxed,
    _laTeX_to_py_frac, _try_float_compare, _frac_pair, _try_fraction_compare,
    _try_sympy_reduce_match, _matches_one, _letter_combo_match,
    _option_letter_match, answers_match, _match_gold_process_tail,
    _match_stripped_func_prefix, _match_divisibility, _match_no_solution,
    _normalize_ellipsis, _strip_set_braces, _split_multi, _alpha_equivalent,
    _poly_equal, _item_match, _multi_value_match, _strip_latex_cmds,
)
from run_eval__classify import (  # noqa: F401
    _EMPTY_DELIM, _NUMERIC, _UNRESOLVED_SYM, _STEP_MARK, _MD_HEADER,
    _classify_error,
)



def _llm_call_snapshot() -> dict:
    """LLM 调用计数的全局快照（用于算单题增量）。失败时返回空统计，绝不打断评测。

    来源：`utils.llm_client.get_truncation_stats()` —— 每次响应结束计数一次，
    流式/非流式两条路径都覆盖（含真实 finish_reason 口径的截断数）。
    """
    try:
        from utils.llm_client import get_truncation_stats
        st = get_truncation_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "truncated": int(st.get("truncated", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "truncated": 0}


def _mcp_call_snapshot() -> dict:
    """Lean MCP 诊断调用的全局快照（用于算单题增量）。

    ★ 2026-09-16 用户要求「这些工具的调用的效果也都记录」。
    来源：`tools.lean_local.lean_bridge.mcp_stats()`（calls / ok / fail / seconds）。
    **判读口径**（这是回答"到底用了 MCP 还是 bridge"的关键证据）：
      · `calls>0, ok>0`      → MCP 真正生效；
      · `calls>0, fail==calls` → MCP **每次都失败** ⇒ 实际由 bridge 完成（0916 轮即此）；
      · `calls==0`           → 根本没走 MCP。
    失败时返回零值，绝不打断评测。
    """
    try:
        from tools.lean_local.lean_bridge import mcp_stats
        st = mcp_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "ok": int(st.get("ok", 0) or 0),
                "fail": int(st.get("fail", 0) or 0),
                "seconds": float(st.get("seconds", 0.0) or 0.0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0}


def _web_call_snapshot() -> dict:
    """通用联网搜索的全局快照（用于算单题增量）。

    来源：`tools.web_search.web_search_stats()`（calls/ok/fail/seconds/results）。
    与 `_mcp_call_snapshot` 同口径 ⇒ 逐题 `tool_calls` 可并列比较
    "Lean MCP 调用" 与 "联网搜索调用" 的实际效果。
    """
    try:
        from tools.web_search import web_search_stats
        st = web_search_stats() or {}
        return {"calls": int(st.get("calls", 0) or 0),
                "ok": int(st.get("ok", 0) or 0),
                "fail": int(st.get("fail", 0) or 0),
                "seconds": float(st.get("seconds", 0.0) or 0.0),
                "results": int(st.get("results", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0, "results": 0}


# ===========================================================================
# 评测引擎
# ===========================================================================

# 本地评测默认参数。
#
# 重要（2026-08-28 修正）：此前这份配置是"全开"版本，与 user_agent.py 的平台默认
# 不一致（samples 3 vs 2、calls 40 vs 150、time 1100 vs 1200、scoring/lemma 开关相反），
# 导致本地测出来的数字不能代表平台表现。当时已把大部分键对齐平台默认值。
#
# ★★ 2026-09-16 更正（用户：「现在的测试和比赛没关系，比赛已经结束了」）：
#   上面那句"**现已全部对齐平台默认值，保证本地基线 == 平台基线**"**已不成立**，
#   实测仍有 **3 个键与 AgentConfig 默认不同**（本条改前没有任何注释说明）：
#     · `tier_budget`              本地 {fast 120, standard 540, deep 1150}
#                                 vs 配置 {300, 750, 1150}
#     · `use_lemma_accumulation`   本地 False  vs 配置 True
#     · `verifier_voting_times`    本地 2      vs 配置 1
#   ⇒ **本地基线 ≠ 平台基线**。比赛已结束，**不再以"对齐平台"为目标**：
#   本地这份就是**研究阶段基线**，有意与平台版解耦（平台版已冻结不再维护）。
#   ⚠ 引用历史 A/B 结论时，须注意它们分别是在哪一套基线下取得的。
# 需要临时偏离本地基线时，请用 CLI 显式指定（如 `--tier_budget`、`--voting_times`）。
DEFAULT_AGENT_OVERRIDES: Dict[str, Any] = {
    # ---- 对齐 user_agent.py:64 / :72 ----
    "policy_sample_times": 2,
    "verifier_voting_times": 2,
    # ---- 对齐 user_agent.py:84 / :94 ----
    "max_total_calls": 150,
    # 2026-09-03 老师："先让它完成题目，看对不对；先改对再节约时间"。
    # 本地评测单题时限放宽到 3600s（1h 封顶防意外挂死），让每题自然跑完
    # 全部环节（子目标/求解/验证/Lean 闸门），不被 1200s 截断。比赛平台
    # 时限是平台侧约束（官方 Client 托管），与本文件无关。
    # 2026-09-04 平台教训（14.29% 归因）：放开单题时限 → 时间爆炸 → 64 题被
    # 时间墙切掉 invalid。改回比赛档 1200s（deep 档上限）——超时截断宁可 invalid
    # 也不拖垮整卷。
    # 2026-09-14 实测落实：1200 → 1150 → **1100**，与提交配置
    # `user_agent.py::AgentConfig.max_time_per_question` 对齐。
    # 依据：同批错题实测两次超限（并发3 轮 1164.7s / 并发1 轮 **1211s > 1200 越墙**）。
    # ⚠ **只改这一处硬限**；`tier_budget.deep` 仍为 1150（档位预算管资源分配，
    #   压它会提前掐断本可在 1200s 内跑完的题）。
    # 2026-10-01 按用户决策：研究期不限时，此值仅作挂死兜底，不参与调度决策；
    #   调度侧已不再有任何按剩余时间降级的逻辑（soft_budget/gen_deadline/verify_only 触发路径已删）。
    "max_time_per_question": 86400,
    # ---- 对齐 user_agent.py:101 / :105 / :106 ----
    "max_workers": 3,
    # 9/4：平台不限 token → 本地 override 同步放开（防截断腰斩；上探 65536 对齐 AgentConfig）
    "max_answer_tokens": 65536,
    "revise_sample_times": 2,
    # 2026-10-01：原值 1 会把自纠错回环整体压到 1 轮（审计 A 级第 7 条）。
    # 与 `user_agent.py:293` 声明的 5 分叉 ⇒ 口径不一致且属比赛期省时裁剪。
    # 研究期求正确率上限，对齐配置声明值 5。
    "max_revise_rounds": 5,
    # ---- 对齐 user_agent.py（2026-10-01 按用户决策默认开，研究期不省资源）----
    "use_scoring": True,
    "use_proof_channel": True,
    # 2026-10-01：原先这里把 `use_lemma_accumulation` 压回 False，与
    # `AgentConfig.use_lemma_accumulation = True` 自相矛盾（跑 eval 时被静默关闭）。
    # 已移除该 override，改为继承配置默认值（仍可经 CLI 显式传参覆盖）。
    # 2026-09-29：`by_enable_fast_path` 已随快车道删除（死开关，无行为作用）。
    # ---- 统一档位预算（2026-09-29）----
    # 三档（fast/standard/deep）已按用户决策收敛为**单一档位**，取值 = 原 deep 最强配置。
    # 原 `{fast:120, standard:540, deep:1150}` 与 `paper_*` 全卷调度参数随
    # PaperPacer 删除；全卷不再有时间总量控制（研究阶段云端评测不限时）。
    # 单题唯一约束是下方 `max_time_per_question` 硬墙。
    "tier_budget": {"deep": 86400.0},
    # 统一档位其余参数（与 user_agent.py __post_init__ 保持一致）
    "tier_sample_times": {"deep": 3},
    "tier_voting_times": {"deep": 3},
    "tier_max_completions": {"deep": 2},
    "tier_max_calls": {"deep": 100},
    # 前置验证最多 2 次尝试（原默认 2 轮 = 3 次，每次 21s 编译 + LLM 调用，
    # 单题可烧掉 3-5 分钟；preverify 是「检查理解」不是「写论文」，1 轮足够）
    # 2026-09-11：#13 前置验证修复——轮数 1→2（即最多 3 轮尝试）。
    # 依据：112 题实测 13 题 preverify fail，全部是「形式化代码编译错误」
    # （臆造 API/类型不匹配/语法错/引用未定义谓词），而原配置仅 2 轮机会；
    # 配合 prompt 增补的「常见错误规避」清单，给修正留出足够轮次。
    "preverify_max_rounds": 2,
    # 2026-09-11（B1 独立化）：启用"子目标数值断言的 Lean 核验"。
    # 此前该开关默认 False → B1 只能靠 P2 数值化间接触发，覆盖面过窄（实测 0/10）。
    # 打开后由 _numeric_lean_verify 对子目标里的数值断言做 Lean 复核
    # （走当前后端 mcp；每题次数受 lean_numeric_max_per_q 限制，默认 2 → 成本可控）。
    "enable_numeric_lean_verify": True,
}


class EvalEngine:
    def __init__(self, concurrency: int = 1, resume: bool = False,
                 api_key: str = "", base_url: str = "", model: str = "",
                 verbose: bool = False, agent_overrides: Optional[Dict[str, Any]] = None):
        self.concurrency = concurrency
        self.resume = resume
        self.verbose = verbose
        # 创建 LLM 客户端（通过环境变量或参数配置）
        self.llm_client = LLMClient(
            api_key=api_key or None,
            base_url=base_url or None,
            model=model or None,
        )
        # 配置覆盖：先取本地评测默认值，再叠加 CLI 传入的 A/B 开关
        overrides = dict(DEFAULT_AGENT_OVERRIDES)
        if agent_overrides:
            overrides.update(agent_overrides)
        # 保存生效覆盖（小样本自适应要用），避免二次重建时丢失
        self._effective_overrides = overrides
        self.agent = ReasoningAgent(self.llm_client, **overrides)
        # ★ 2026-10-02 中间结果存储层接线：本轮评测 run_id（一轮一个目录：
        #   results/<run_id>/<qid>/）。显式设定后由 artifact_store 统一取用；
        #   平台直调（不经本脚本）时回退进程级稳定默认值。失败不阻断评测。
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        try:
            from agent.artifact_store import set_run_id as _set_run_id
            _set_run_id(self.run_id)
        except Exception:  # noqa: BLE001
            try:
                from artifact_store import set_run_id as _set_run_id
                _set_run_id(self.run_id)
            except Exception:  # noqa: BLE001
                pass
        logger.info("EvalEngine init: %s, overrides=%s", self.llm_client, overrides)
        self.domain_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "correct": 0}
        )

    def load_tests(self, filepath: str) -> List[Dict[str, Any]]:
        tests = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"第 {line_no} 行 JSON 解析失败")
                    continue
                if "question" not in item and "problem" not in item:
                    logger.warning(f"第 {line_no} 行缺少 question/problem")
                    continue
                # 统一规范化字段名（本地题库兼容：problem/question、subject/domain、idx/id）
                if "question" not in item:
                    item["question"] = item["problem"]
                if "domain" not in item and "subject" in item:
                    item["domain"] = item["subject"]
                if "id" not in item and "idx" in item:
                    item["id"] = item["idx"]
                item["_line_no"] = line_no
                tests.append(item)
        logger.info(f"加载 {len(tests)} 道测试题")
        return tests

    def solve_one(self, test: Dict[str, Any]) -> Dict[str, Any]:
        question = test["question"]
        gold = test.get("answer", "")
        domain = test.get("domain", "unknown")
        pid = test.get("id", str(test.get("_line_no", "?")))
        start = time.time()
        # ★ 2026-09-16 用户要求「极为详细的数据」：记录本题的 LLM 调用增量。
        # 全局计数器是进程累计的，必须做前后快照求差才等于"本题用了多少次"。
        _llm_before = _llm_call_snapshot()
        _mcp_before = _mcp_call_snapshot()
        _web_before = _web_call_snapshot()
        # ★★ 2026-09-16 修既有 bug（由 tests/test_result_detail_export.py 抓到）：
        # `result` 原先**只在 try 内赋值**，一旦 `agent.solve()` 抛异常，
        # 紧随其后的 `isinstance(result, dict)` 会抛 `UnboundLocalError`
        # ⇒ 整个 `solve_one` 崩溃、**该题在结果里彻底消失**（不是记为错，是丢失），
        # 批量评测时可能直接打断整轮。此处先给默认值。
        result: Dict[str, Any] = {}
        try:
            result = self.agent.solve(question, {})
            elapsed = time.time() - start
            pred_answer = result.get("final_response", "") if isinstance(result, dict) else ""
            response = result.get("final_response", "") if isinstance(result, dict) else str(result) if result else ""
        except Exception as e:
            logger.error(f"题目 {pid} 求解异常: {e}", exc_info=True)
            elapsed = time.time() - start
            pred_answer = ""
            response = f"ERROR: {e}"
            result = {}
        _llm_after = _llm_call_snapshot()
        llm_calls = {k: (_llm_after.get(k, 0) - _llm_before.get(k, 0))
                     for k in set(_llm_before) | set(_llm_after)}
        # ★ 工具级埋点（用户 2026-09-16 要求）：本题 Lean MCP 的调用次数/成功/失败/耗时。
        _mcp_after = _mcp_call_snapshot()
        mcp_calls = {
            "calls": _mcp_after["calls"] - _mcp_before["calls"],
            "ok": _mcp_after["ok"] - _mcp_before["ok"],
            "fail": _mcp_after["fail"] - _mcp_before["fail"],
            "seconds": round(_mcp_after["seconds"] - _mcp_before["seconds"], 2),
        }
        # 派生判读：MCP 是否真正生效（否则实际由 bridge 完成）
        if mcp_calls["calls"] == 0:
            mcp_calls["verdict"] = "未走 MCP"
        elif mcp_calls["ok"] > 0:
            mcp_calls["verdict"] = "MCP 生效"
        else:
            mcp_calls["verdict"] = "MCP 全部失败 → 实际由 bridge 完成"
        # ★ 联网搜索埋点（用户 2026-09-16 要求「这些工具的调用的效果也都记录」）
        _web_after = _web_call_snapshot()
        web_calls = {
            "calls": _web_after["calls"] - _web_before["calls"],
            "ok": _web_after["ok"] - _web_before["ok"],
            "fail": _web_after["fail"] - _web_before["fail"],
            "results": _web_after["results"] - _web_before["results"],
            "seconds": round(_web_after["seconds"] - _web_before["seconds"], 2),
        }
        web_calls["verdict"] = ("未调用" if web_calls["calls"] == 0
                                else "成功" if web_calls["ok"] > 0
                                else "全部失败")
        is_correct = answers_match(pred_answer, gold) if pred_answer and gold else None
        if not gold:
            is_correct = None
        # 错误分类：仅对判错样本分类（#6/#11/#16），用于定位瓶颈与决定优化投向
        error_class = ""
        if is_correct is False:
            error_class = _classify_error(pred_answer, gold)
        # Mathlib 使用证据（2026-08-29）：AI 检索/验证用到的定理 + 使用统计
        used_theorems = []
        if isinstance(result, dict):
            used_theorems = list(result.get("used_theorems") or [])
        usage_stats = {}
        if isinstance(result, dict):
            usage_stats = result.get("mathlib_usage_stats") or {}
        # 逐步归因诊断（2026-09-02）：orchestrator 已打包各阶段中间状态，
        # 这里落盘为结果行 diag 字段（错题可定位到理解/蓝图/子目标/验证等环节）
        diag = {}
        if isinstance(result, dict):
            diag = result.get("diag") or {}
        # ★ 2026-09-16 用户要求「极为详细的数据：大模型的解答过程 / 时间消耗 / 各环节效果」。
        # 此前只落盘 response[:2000] 与有限 diag，**候选的解答过程、全量事件流都没导出**
        # ⇒ 事后无法复盘"模型到底怎么想的、在哪一步跑偏"。以下四项把过程完整留痕：
        #   · response_full  最终回答**全文**（不再截断）
        #   · candidates     每个候选的 answer + **reasoning（解答过程）** + 得票
        #   · trace          全量事件流（各 agent/step 的顺序与内容）
        #   · verdicts/cluster 验证裁决与共识簇
        #   · llm_calls      本题 LLM 调用次数（全局计数前后快照之差）
        # ⚠ 体积可控：单题约几十 KB，10 题 ~1MB（此前每行只存 2KB 摘要）。
        cand_out: list = []
        verd_out: list = []
        cluster_out = None
        trace_out: list = []
        if isinstance(result, dict):
            _verds = result.get("verdicts") or []
            for i, c in enumerate(result.get("candidates") or []):
                if not isinstance(c, dict):
                    continue
                v = _verds[i] if i < len(_verds) and isinstance(_verds[i], dict) else {}
                cand_out.append({
                    "id": c.get("id", i),
                    "answer": c.get("answer", ""),
                    "reasoning": c.get("reasoning", ""),     # ★ 解答过程
                    "revised": bool(c.get("revised")),
                    "confidence": v.get("confidence"),
                    "correct_votes": v.get("correct_votes"),
                    "total_votes": v.get("total_votes"),
                    "feedback": v.get("feedback", ""),
                })
            for v in _verds:
                if isinstance(v, dict):
                    verd_out.append({
                        "id": v.get("id"),
                        "answer": v.get("answer", ""),
                        "confidence": v.get("confidence"),
                        "correct_votes": v.get("correct_votes"),
                        "total_votes": v.get("total_votes"),
                    })
            cluster_out = result.get("cluster")
            trace_out = result.get("trace") or []
        return {
            "id": pid, "domain": domain,
            "question": question, "gold": gold,
            "predicted": pred_answer, "response": response[:2000],
            # ★ 最终回答全文（不截断）
            "response_full": response,
            "correct": is_correct, "elapsed_sec": round(elapsed, 2),
            "error_class": error_class,
            # #1/#2 证据链：实际用到的 Mathlib 定理（leansearch 命中/编译通过）
            "used_theorems": used_theorems,
            "mathlib_usage_stats": usage_stats,
            # 逐步归因诊断（可空：老结果文件无此字段）
            "diag": diag,
            # ★ 2026-09-16 新增：过程留痕（候选解答过程 / 事件流 / 裁决 / 调用次数）
            "candidates": cand_out,
            "verdicts": verd_out,
            "cluster": cluster_out,
            "trace": trace_out,
            "llm_calls": llm_calls,
            # ★ 工具级埋点：Lean MCP + 通用联网搜索（calls/ok/fail/seconds + 派生判读）
            "tool_calls": {"lean_mcp": mcp_calls, "web_search": web_calls},
        }

    def run(self, test_file: str, output_file: str) -> Dict[str, Any]:
        tests = self.load_tests(test_file)
        done_ids = set()
        results = []
        if self.resume and os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            r = json.loads(line)
                            done_ids.add(r.get("id"))
                            results.append(r)
                            domain = r.get("domain", "unknown")
                            self.domain_stats[domain]["total"] += 1
                            if r.get("correct"):
                                self.domain_stats[domain]["correct"] += 1
                        except json.JSONDecodeError:
                            pass
            logger.info(f"断点续跑：跳过 {len(done_ids)} 道已完成")
        pending = [t for t in tests if str(t.get("id", t.get("_line_no"))) not in done_ids]
        logger.info(f"待评测: {len(pending)} / 总计: {len(tests)}")
        # ---- 2026-09-29：小样本自适应块已删除 ----
        # 原逻辑在"待评测题数 < 全卷题数"时重建 agent，调整 PaperPacer 的
        # `paper_total_questions` / `paper_target_time`，以免小卷被误判"卷面落后"
        # 而收紧单题预算。PaperPacer 已整体删除（全卷无时间总量控制）⇒ 该
        # workaround 失去存在前提，整块移除。
        with ThreadPoolExecutor(max_workers=max(1, self.concurrency)) as executor:
            future_map = {executor.submit(self.solve_one, t): t for t in pending}
            for future in as_completed(future_map):
                row = future.result()
                results.append(row)
                domain = row.get("domain", "unknown")
                self.domain_stats[domain]["total"] += 1
                if row.get("correct"):
                    self.domain_stats[domain]["correct"] += 1
                # 增量落盘（2026-08-28 新增）：每题完成立即追加写盘。
                # 此前全部跑完才写一次文件，中途 Ctrl-C / 杀进程 / 超时
                # 会丢掉所有已完成题目的结果。增量写 + --resume 断点续跑，
                # 保证任何时刻中断都能保留进度。
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.sort(key=lambda r: str(r.get("id", "")))
        with open(output_file, "w", encoding="utf-8") as f:
            for row in results:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info(f"结果已写入 {output_file}")
        return self._build_summary(results)

    def _build_summary(self, results: List[Dict]) -> Dict[str, Any]:
        total = len(results)
        scored = [r for r in results if r["correct"] is not None]
        correct = sum(1 for r in scored if r["correct"])
        accuracy = correct / len(scored) if scored else 0.0
        avg_elapsed = sum(r.get("elapsed_sec", 0) for r in results) / max(total, 1)
        summary = {
            "total": total, "scored": len(scored),
            "correct": correct, "accuracy": round(accuracy, 4),
            "avg_elapsed_sec": round(avg_elapsed, 2),
            "per_domain": {},
        }
        for domain, stats in sorted(self.domain_stats.items()):
            tot = stats["total"]
            cor = stats["correct"]
            summary["per_domain"][domain] = {
                "total": tot, "correct": cor,
                "accuracy": round(cor / tot, 4) if tot else 0.0,
            }

        # 错误分类分布（#6/#11/#16）——决定下一轮资源投向的核心依据
        wrong = [r for r in results if r.get("correct") is False]
        err_dist: Dict[str, int] = {}
        for r in wrong:
            k = r.get("error_class") or "unclassified"
            err_dist[k] = err_dist.get(k, 0) + 1
        n_wrong = len(wrong)
        summary["error_distribution"] = {
            "wrong_total": n_wrong,
            "counts": err_dist,
            "ratios": {k: round(v / n_wrong, 4) for k, v in err_dist.items()} if n_wrong else {},
        }
        # 决策提示：按计划 §2 P0.5 的决策规则给出建议，避免每次人工判读
        ratio = summary["error_distribution"]["ratios"]
        # 非推理类（不需要提升推理能力就能修）：空输出 + 抽取失败 + 答案未定型
        cheap = (ratio.get("empty_output", 0.0)
                 + ratio.get("extract_failed", 0.0)
                 + ratio.get("format_unresolved", 0.0))
        if n_wrong:
            if cheap >= 0.25:
                summary["recommendation"] = (
                    f"先做答案定型（Phase 1-A）：非推理类错误占比 {cheap:.0%}，"
                    "不动推理即可提分，风险最低")
            elif ratio.get("value_wrong", 0.0) >= 0.55:
                summary["recommendation"] = (
                    f"主攻答案题推理深度：value_wrong 占比 {ratio['value_wrong']:.0%}，"
                    "瓶颈在推理能力，投多候选/投票/revise")
            else:
                summary["recommendation"] = (
                    "天花板在推理深度，投 deep 通道扩容（多候选 + 预算生效）")
        return summary


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="MathPilot 本地评测工具")
    parser.add_argument("--test_file", default="", help="JSONL 测试文件路径")
    parser.add_argument("--bank", default="", help="题库名称（如 新高数、1000题高数、高数a、IMO-AnswerBench、all）")
    parser.add_argument("--list_banks", action="store_true", help="列出所有已注册题库")
    parser.add_argument("--output", default="eval_results.jsonl", help="输出结果文件")
    parser.add_argument("--concurrency", type=int, default=2, help="并发数")
    parser.add_argument("--resume", action="store_true", help="断点续跑")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    parser.add_argument("--api_key", default="", help="LLM API Key（或设置 OPENAI_API_KEY 环境变量）")
    parser.add_argument("--base_url", default="", help="LLM Base URL（或设置 OPENAI_BASE_URL 环境变量）")
    parser.add_argument("--model", default="", help="模型名（或设置 LLM_MODEL 环境变量）")
    # ---- A/B 能力开关（None 表示使用本地评测默认值）----
    parser.add_argument("--voting_times", type=int, default=None, help="verifier_voting_times（每个候选验证票数）")
    parser.add_argument("--verifier_deep_final_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="verifier_deep_final_enabled（带推理的最终复核，默认 false）")
    # ★ 2026-09-16 审计修复：以下两个键此前**只有 getattr 兜底**，
    #   AgentConfig 未声明、白名单未列、CLI 也没有 ⇒ 注释承诺的
    #   "回退/AB 开关"实际不可用（假开关）。现补全三处。
    parser.add_argument("--enable_question_type_hint", type=str, default=None,
                        choices=["true", "false"],
                        help="全题型强制注入题型特化纪律（默认 false；"
                             "仅客观题默认由 objective_tactic_enabled 控制）")
    parser.add_argument("--verify_reserve_seconds", type=float, default=None,
                        help="生成侧预留秒数（_gen_deadline = deadline − 此值）；"
                             "0/缺省 = 按档位默认（deep 540 / 其他 480）")
    parser.add_argument("--enable_web_search", type=str, default=None,
                        choices=["true", "false"],
                        help="启用联网搜索工具（web_search，默认 false；"
                             "经原生 tool_calls 调用，效果见 tool_calls.web_search）")
    parser.add_argument("--verifier_deep_final_min_remaining", type=float, default=None,
                        help="verifier_deep_final_min_remaining（剩余秒数低于此值则跳过复核）")
    # ★ 2026-09-15 审计补漏：以下两键原先**只有配置与白名单、没有 CLI 参数**
    # ⇒ 命令行根本传不进去（与"有 CLI 没白名单"是同一类坑的镜像）。
    parser.add_argument("--verifier_deep_review_temperature", type=float, default=None,
                        help="verifier_deep_review_temperature（复核采样温度，默认 0.0）")
    parser.add_argument("--verifier_deep_review_min_chars", type=int, default=None,
                        help="verifier_deep_review_min_chars（复核最短输出字数，低于此值视为未完成；0=关闭该护栏）")
    # ★ 2026-09-17 补：该键此前**有 AgentConfig 声明、有白名单、有读取点，却唯独没有 CLI**
    #   （同批的 temperature/min_chars 都有）⇒ 属审核列的"半假开关"，
    #   命令行无法调。实测需要它：默认 16384 过大，深复核产出 26k–42k 字符、
    #   VERDICT 出现 0 次且出现复读退化（两样本 chars 完全相同=26749）。
    parser.add_argument("--verifier_deep_review_max_tokens", type=int, default=None,
                        help="verifier_deep_review_max_tokens（复核单次最大 token，默认 16384；"
                             "建议 ≤6144 以缩短退化窗口）")
    # 2026-09-16 投票方差（候选分歧 → 提高票数 + 非零温度）
    parser.add_argument("--verifier_diversify_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="verifier_diversify_enabled（候选有分歧时提高票数+温度，默认 true）")
    parser.add_argument("--verifier_disagreement_votes", type=int, default=None,
                        help="verifier_disagreement_votes（有分歧时的每候选票数，默认 3）")
    parser.add_argument("--verifier_disagreement_temperature", type=float, default=None,
                        help="verifier_disagreement_temperature（有分歧时的采样温度，默认 0.7）")
    parser.add_argument("--use_scoring", type=str, default=None, choices=["true", "false"], help="use_scoring（验证器多维评分）")
    parser.add_argument("--revise_rounds", type=int, default=None, help="max_revise_rounds（自纠错回环轮数）")
    parser.add_argument("--use_proof", type=str, default=None, choices=["true", "false"], help="use_proof_channel（证明题专用通道）")
    parser.add_argument("--use_blueprint", type=str, default=None, choices=["true", "false"], help="use_blueprint（蓝图分解）")
    parser.add_argument("--blueprint_deps_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="blueprint_deps_enabled（DAG 依赖边；false=复现'依赖恒空'旧行为做 A/B）")
    parser.add_argument("--blueprint_or_expand_all", type=str, default=None,
                        choices=["true", "false"],
                        help="blueprint_or_expand_all（OR 节点是否展开全部备选分支；"
                             "默认 false=只取 children[0]，true 会放大子目标规模）")
    # 2026-09-13：为 A/B 对比新增两个开关（此前只能改代码才能切换）。
    # 背景：`3.3_improve`(单Agent自审自改) 与 `3.4_collab`(三Agent协作改进)
    # 语义重叠，需要实测"哪个更高效"才能决定舍去哪一个。
    parser.add_argument("--enable_self_improve", type=str, default=None,
                        choices=["true", "false"],
                        help="enable_self_improve（3.3 Step2 无条件自改进）")
    parser.add_argument("--enable_collaborative_deep", type=str, default=None,
                        choices=["true", "false"],
                        help="enable_collaborative_deep（3.4 deep档三Agent协作）")
    parser.add_argument("--enable_dag_replan", type=str, default=None, choices=["true", "false"],
                        help="enable_dag_replan（DAG 动态评审+重生成闭环）")
    # 2026-09-08：求解前 DAG 强制门独立开关（默认关=去掉门）
    parser.add_argument("--dag_replan_gate", type=str, default=None, choices=["true", "false"], help="dag_replan_gate（求解前 DAG 强制评审门，默认 false）")
    # 2026-09-08：L2 子目标数值/代数断言 Lean 验证（lean-lsp-mcp norm_num/ring）
    parser.add_argument("--enable_numeric_lean_verify", type=str, default=None, choices=["true", "false"], help="enable_numeric_lean_verify（子目标数值断言 Lean 验证）")
    parser.add_argument("--lean_numeric_max_per_q", type=int, default=None, help="lean_numeric_max_per_q（每题数值 Lean 验证限额，默认 2）")
    # 2026-09-10 L2：独立符号建模核验关卡（A/B 用）
    # 2026-10-01：`--calc_mandatory` / `--calc_hard_only` / `--subgoal_calc_router` /
    #   `--tool_calc_enabled` / `--answer_selfcheck_enabled` 随 `<calc>` 板块删除。
    parser.add_argument("--symbolic_crosscheck_enabled", type=str, default=None, choices=["true", "false"], help="symbolic_crosscheck_enabled（L2：独立符号建模求真值 → 与答案比对，不符则打回）")
    # 2026-09-12 符号化方程求解通道：模型只交方程（组）+ 目标，数值由本地工具算
    parser.add_argument("--symbolic_solve_enabled", type=str, default=None, choices=["true", "false"], help="symbolic_solve_enabled（数值剥离→模型符号建模→工具求解，模型不参与计算）")
    parser.add_argument("--symbolic_solve_feedback", type=str, default=None, choices=["true", "false"], help="symbolic_solve_feedback（工具值与答案分歧时回传工具结果给模型定稿）")
    parser.add_argument("--symbolic_solve_adopt", type=str, default=None, choices=["true", "false"], help="symbolic_solve_adopt（方案④：工具求解成功后答案直接取工具值，模型不参与计算）")
    # 2026-09-29：`--use_fast_path` 已删除（快车道机制整体移除）
    parser.add_argument("--max_total_calls", type=int, default=None, help="max_total_calls（单题 LLM 调用预算）")
    # ---- 2026-09-13 诊断模式：时间限制放开（默认不传 = 保持比赛口径，行为不变）----
    # 用途：服务端高延迟时（实测单次 LLM 60–180s），比赛口径会让每题被"预算不足"
    # 中途截断（budget_skips 飙升），**看不到完整的失败路径**。诊断跑分时放开，
    # 只为定位"错在哪一步"；⚠ 放宽口径的成绩**不得对外报数**。
    parser.add_argument("--max_time_per_question", type=int, default=None,
                        help="单题壁钟上限秒（诊断用；不传=1200 比赛口径）")
    parser.add_argument("--tier_budget", type=str, default=None,
                        help="统一档位预算 'f,s,d'（2026-09-29 后只取最后一段作 deep 值；"
                             "不传=1150）")
    # 2026-09-29：`--paper_target_time` / `--deep_quota_ratio` / `--paper_total_questions`
    # 三个参数随 PaperPacer 删除（已无任何消费者）。
    # ---- 2026-09-15 赛后无约束评测：补齐此前**没有 CLI 入口**的旋钮 ----
    # 背景：上述 4 个诊断参数只覆盖了一部分约束，`max_total_time_seconds` /
    # 子目标阶段预算 / `max_subgoals` / `improve_min_remaining` / `deep_quota_ratio`
    # 此前只能改代码，导致"解除比赛限制"做不彻底（改了单题上限，全卷仍被 20700 卡）。
    # 全部默认 None = 不传即保持比赛口径，行为与改动前逐字节一致。
    parser.add_argument("--max_total_time_seconds", type=int, default=None,
                        help="Agent 总运行上限秒（诊断用；不传=20700 比赛口径）")
    parser.add_argument("--subgoal_stage_budget_sec", type=float, default=None,
                        help="deep 档子目标阶段预算秒（诊断用；不传=750）")
    parser.add_argument("--subgoal_stage_budget_sec_std", type=float, default=None,
                        help="standard/fast 档子目标阶段预算秒（诊断用；不传=450）")
    parser.add_argument("--max_subgoals", type=int, default=None,
                        help="子目标规划数上限（诊断用；不传=6 比赛口径；<=0 表示不截断）")
    # ---- LeanSearch 引理检索（2026-09-15 重启；A/B 用）----
    parser.add_argument("--use_leansearch", type=str, default=None,
                        choices=["true", "false"],
                        help="use_leansearch（LeanSearch 引理检索总开关，默认关）")
    parser.add_argument("--leansearch_top_k", type=int, default=None,
                        help="leansearch_top_k（每次检索返回条数，默认 5；老师 #46 要求扫 3/5/10）")
    parser.add_argument("--leansearch_max_calls_per_q", type=int, default=None,
                        help="leansearch_max_calls_per_q（单题检索次数上限，默认 2）")
    parser.add_argument("--leansearch_inject_verifier", type=str, default=None,
                        choices=["true", "false"],
                        help="leansearch_inject_verifier（方案 A：把定理原文注入验证器，默认 true）")
    parser.add_argument("--improve_min_remaining", type=float, default=None,
                        help="3.3 改进停手预留秒（诊断用；不传=300；0=关闭该护栏）")
    # 2026-09-29（截图 #7）：无条件自改进 A/B 抓手 —— 遍数（1/2）与缺陷过滤开关。
    parser.add_argument("--self_improve_rounds", type=int, default=None,
                        help="3.3 Step2 自改进遍数（默认 1；设 2 做「一遍 vs 两遍」A/B）")
    parser.add_argument("--self_improve_conditional", type=str, default=None,
                        choices=["true", "false"],
                        help="3.3 是否只改有缺陷候选（默认 false = 真无条件）")
    # 2026-09-29（截图 #3+#4）：领域→定理检索 A/B 抓手（有定理 vs 无定理）。
    parser.add_argument("--enable_theorem_hint", type=str, default=None,
                        choices=["true", "false"],
                        help="1.6 领域→Mathlib 定理检索并注入（默认 true）")
    parser.add_argument("--theorem_hint_max_queries", type=int, default=None,
                        help="1.6 单题最多发几次 leansearch 检索（默认 2）")
    # 2026-09-29：--deep_quota_ratio / --paper_total_questions 随 PaperPacer 删除。
    # ---- 2026-10-07 开关注册制补齐（fix-switch-debt）：9 条此前**漏加白名单**的
    #      A/B 开关补 CLI 入口（原只有 AgentConfig 字段 + 读取点，命令行传不进 ⇒
    #      「回退路径在代码层面不存在」）。全部 default=None ⇒ 不传即保持类默认，
    #      行为与改动前逐字一致。9 键均经 grep 确认有**真实消费点**（非死配置），
    #      故全部面向命令行；无「不该有 CLI」的排除项。
    parser.add_argument("--accept_confidence", type=float, default=None,
                        help="AcceptGate 可接受置信度阈值（默认 0.6；"
                             "orchestrator._update_accept_gate）")
    parser.add_argument("--enable_deterministic", type=str, default=None,
                        choices=["true", "false"],
                        help="确定性硬否决：SymPy 回验 fail 淘汰候选、unknown 放行"
                             "（默认 true；orchestrator）")
    parser.add_argument("--enable_answer_falsifier", type=str, default=None,
                        choices=["true", "false"],
                        help="候选答案证伪器（默认 true；answer_falsifier/orchestrator）")
    parser.add_argument("--audit_gate_skip_non_proof", type=str, default=None,
                        choices=["true", "false"],
                        help="6.5 AuditGate 对非证明题早退、不再产 unknown 噪音"
                             "（默认 true；audit_gate）")
    parser.add_argument("--enable_subgoal_main_path", type=str, default=None,
                        choices=["true", "false"],
                        help="子目标细化作为主路径（默认 true；orchestrator）")
    parser.add_argument("--inject_mathlib_to_solver", type=str, default=None,
                        choices=["true", "false"],
                        help="把 LeanSearch 检索到的 Mathlib 定理注入解题侧引理记忆"
                             "（默认 true；sub_goal_solver）")
    parser.add_argument("--objective_tactic_enabled", type=str, default=None,
                        choices=["true", "false"],
                        help="客观题特化解法纪律（默认 true；solver/sub_goal_solver）")
    parser.add_argument("--symbolic_max_tokens", type=int, default=None,
                        help="独立符号建模复核单次 max_tokens（默认 8192；solver）")
    parser.add_argument("--symbolic_solve_max_tokens", type=int, default=None,
                        help="符号化方程求解建模单次 max_tokens（默认 8192；solver）")
    args = parser.parse_args()

    if args.list_banks:
        list_banks()
        return

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 解析 test_file：--bank 优先
    test_files: List[str] = []
    if args.bank:
        resolved = resolve_bank(args.bank)
        if resolved is None:
            print(f"错误: 未知题库 '{args.bank}'。使用 --list_banks 查看可用题库。")
            sys.exit(1)
        if isinstance(resolved, list):
            test_files = resolved
        else:
            test_files = [resolved]
    elif args.test_file:
        test_files = [args.test_file]
    else:
        print("错误: 请指定 --test_file 或 --bank。使用 --list_banks 查看可用题库。")
        sys.exit(1)

    # 收集 A/B 能力开关
    overrides: Dict[str, Any] = {}
    if args.voting_times is not None:
        overrides["verifier_voting_times"] = args.voting_times
    if args.verifier_deep_final_enabled is not None:
        overrides["verifier_deep_final_enabled"] = (
            args.verifier_deep_final_enabled == "true")
    # ★ 2026-09-16 审计补全：让这两个键的 CLI 真正生效
    #   （此前只有 getattr 兜底，注释承诺的回退/AB 开关是假的）
    if getattr(args, "enable_question_type_hint", None) is not None:
        overrides["enable_question_type_hint"] = (
            args.enable_question_type_hint == "true")
    if getattr(args, "verify_reserve_seconds", None) is not None:
        overrides["verify_reserve_seconds"] = args.verify_reserve_seconds
    if getattr(args, "enable_web_search", None) is not None:
        overrides["enable_web_search"] = (args.enable_web_search == "true")
    if args.verifier_deep_final_min_remaining is not None:
        overrides["verifier_deep_final_min_remaining"] = (
            args.verifier_deep_final_min_remaining)
    if args.verifier_deep_review_temperature is not None:
        overrides["verifier_deep_review_temperature"] = (
            args.verifier_deep_review_temperature)
    if args.verifier_deep_review_min_chars is not None:
        overrides["verifier_deep_review_min_chars"] = (
            args.verifier_deep_review_min_chars)
    if getattr(args, "verifier_deep_review_max_tokens", None) is not None:
        overrides["verifier_deep_review_max_tokens"] = (
            args.verifier_deep_review_max_tokens)
    if args.verifier_diversify_enabled is not None:
        overrides["verifier_diversify_enabled"] = (
            args.verifier_diversify_enabled == "true")
    if args.verifier_disagreement_votes is not None:
        overrides["verifier_disagreement_votes"] = args.verifier_disagreement_votes
    if args.verifier_disagreement_temperature is not None:
        overrides["verifier_disagreement_temperature"] = (
            args.verifier_disagreement_temperature)
    if args.use_scoring is not None:
        overrides["use_scoring"] = args.use_scoring == "true"
    if args.revise_rounds is not None:
        overrides["max_revise_rounds"] = args.revise_rounds
    if args.use_proof is not None:
        overrides["use_proof_channel"] = args.use_proof == "true"
    if args.use_blueprint is not None:
        overrides["use_blueprint"] = args.use_blueprint == "true"
    if args.blueprint_deps_enabled is not None:
        overrides["blueprint_deps_enabled"] = (
            args.blueprint_deps_enabled == "true")
    if args.blueprint_or_expand_all is not None:
        overrides["blueprint_or_expand_all"] = (
            args.blueprint_or_expand_all == "true")
    if args.enable_dag_replan is not None:
        overrides["enable_dag_replan"] = args.enable_dag_replan == "true"
    if args.enable_self_improve is not None:
        overrides["enable_self_improve"] = args.enable_self_improve == "true"
    if args.enable_collaborative_deep is not None:
        overrides["enable_collaborative_deep"] = \
            args.enable_collaborative_deep == "true"
    if args.dag_replan_gate is not None:
        overrides["dag_replan_gate"] = args.dag_replan_gate == "true"
    if args.enable_numeric_lean_verify is not None:
        overrides["enable_numeric_lean_verify"] = \
            args.enable_numeric_lean_verify == "true"
    if args.lean_numeric_max_per_q is not None:
        overrides["lean_numeric_max_per_q"] = args.lean_numeric_max_per_q
    # 2026-09-10 L2 独立符号建模核验关卡
    if args.symbolic_crosscheck_enabled is not None:
        overrides["symbolic_crosscheck_enabled"] = args.symbolic_crosscheck_enabled == "true"
    # 2026-09-12 符号化方程求解通道
    if args.symbolic_solve_enabled is not None:
        overrides["symbolic_solve_enabled"] = args.symbolic_solve_enabled == "true"
    if args.symbolic_solve_feedback is not None:
        overrides["symbolic_solve_feedback"] = args.symbolic_solve_feedback == "true"
    if args.symbolic_solve_adopt is not None:
        overrides["symbolic_solve_adopt"] = args.symbolic_solve_adopt == "true"
    if args.max_total_calls is not None:
        overrides["max_total_calls"] = args.max_total_calls
    # 2026-09-13 诊断模式：时间限制放开
    if args.max_time_per_question is not None:
        overrides["max_time_per_question"] = args.max_time_per_question
    if args.tier_budget:
        # 2026-09-29：统一档位 —— CLI 仍兼容 `f,s,d` 三段写法（取 deep 段，
        # 保持 `run_research.py` 的 "86400,86400,86400" 等既有调用可用），
        # 也支持单段 "1150" 直写。
        _tb = [float(x) for x in args.tier_budget.split(",")]
        if len(_tb) == 3:
            overrides["tier_budget"] = {"deep": _tb[2]}
        elif len(_tb) == 1:
            overrides["tier_budget"] = {"deep": _tb[0]}
    # 2026-09-15 赛后无约束评测：补齐 7 个旋钮（默认 None ⇒ 不改变比赛口径）
    if args.max_total_time_seconds is not None:
        overrides["max_total_time_seconds"] = args.max_total_time_seconds
    if args.subgoal_stage_budget_sec is not None:
        overrides["subgoal_stage_budget_sec"] = args.subgoal_stage_budget_sec
    if args.subgoal_stage_budget_sec_std is not None:
        overrides["subgoal_stage_budget_sec_std"] = args.subgoal_stage_budget_sec_std
    if args.max_subgoals is not None:
        overrides["max_subgoals"] = args.max_subgoals
    # ---- LeanSearch 引理检索（2026-09-15 重启）----
    if args.use_leansearch is not None:
        overrides["use_leansearch"] = args.use_leansearch == "true"
    if args.leansearch_top_k is not None:
        overrides["leansearch_top_k"] = args.leansearch_top_k
    if args.leansearch_max_calls_per_q is not None:
        overrides["leansearch_max_calls_per_q"] = args.leansearch_max_calls_per_q
    if args.leansearch_inject_verifier is not None:
        overrides["leansearch_inject_verifier"] = (
            args.leansearch_inject_verifier == "true")
    if args.improve_min_remaining is not None:
        overrides["improve_min_remaining"] = args.improve_min_remaining
    if args.self_improve_rounds is not None:
        overrides["self_improve_rounds"] = args.self_improve_rounds
    if args.self_improve_conditional is not None:
        overrides["self_improve_conditional"] = (
            args.self_improve_conditional == "true")
    if args.enable_theorem_hint is not None:
        overrides["enable_theorem_hint"] = args.enable_theorem_hint == "true"
    if args.theorem_hint_max_queries is not None:
        overrides["theorem_hint_max_queries"] = args.theorem_hint_max_queries
    # 2026-09-29：--deep_quota_ratio / --paper_total_questions 随 PaperPacer 删除。
    # ---- 2026-10-07 开关注册制补齐（fix-switch-debt）：9 条 A/B 开关的 CLI → 覆盖 ----
    if args.accept_confidence is not None:
        overrides["accept_confidence"] = args.accept_confidence
    if args.enable_deterministic is not None:
        overrides["enable_deterministic"] = args.enable_deterministic == "true"
    if args.enable_answer_falsifier is not None:
        overrides["enable_answer_falsifier"] = args.enable_answer_falsifier == "true"
    if args.audit_gate_skip_non_proof is not None:
        overrides["audit_gate_skip_non_proof"] = (
            args.audit_gate_skip_non_proof == "true")
    if args.enable_subgoal_main_path is not None:
        overrides["enable_subgoal_main_path"] = (
            args.enable_subgoal_main_path == "true")
    if args.inject_mathlib_to_solver is not None:
        overrides["inject_mathlib_to_solver"] = (
            args.inject_mathlib_to_solver == "true")
    if args.objective_tactic_enabled is not None:
        overrides["objective_tactic_enabled"] = (
            args.objective_tactic_enabled == "true")
    if args.symbolic_max_tokens is not None:
        overrides["symbolic_max_tokens"] = args.symbolic_max_tokens
    if args.symbolic_solve_max_tokens is not None:
        overrides["symbolic_solve_max_tokens"] = args.symbolic_solve_max_tokens

    engine = EvalEngine(
        concurrency=args.concurrency, resume=args.resume,
        api_key=args.api_key, base_url=args.base_url, model=args.model,
        verbose=args.verbose, agent_overrides=overrides,
    )

    # 支持多题库评测
    all_summaries = []
    base_output = args.output
    for i, test_file in enumerate(test_files):
        # 多题库时自动命名输出文件
        if len(test_files) > 1:
            bank_name = os.path.splitext(os.path.basename(test_file))[0]
            stem, ext = os.path.splitext(base_output)
            output_file = f"{stem}_{bank_name}{ext}"
        else:
            output_file = base_output

        print(f"\n{'='*60}")
        print(f"题库 [{i+1}/{len(test_files)}]: {os.path.basename(test_file)}")
        print(f"输出文件: {output_file}")
        print(f"{'='*60}")

        summary = engine.run(test_file, output_file)
        all_summaries.append((test_file, summary))

    # 打印汇总报告
    for test_file, summary in all_summaries:
        print("\n" + "=" * 60)
        print(f"MathPilot 评测报告 - {os.path.basename(test_file)}")
        print("=" * 60)
        print(f"题目总数:   {summary['total']}")
        print(f"可判分题:   {summary['scored']}")
        print(f"正确数:     {summary['correct']}")
        print(f"准确率:     {summary['accuracy']:.2%}")
        print(f"平均耗时:   {summary['avg_elapsed_sec']} 秒")
        print("-" * 60)
        print(f"{'领域':<25} {'总数':<6} {'正确':<6} {'准确率':<8}")
        print("-" * 60)
        for domain, stats in summary.get("per_domain", {}).items():
            print(f"{domain:<25} {stats['total']:<6} {stats['correct']:<6} {stats['accuracy']:<8.2%}")
        print("=" * 60)

    # 多题库时打印总汇总
    if len(all_summaries) > 1:
        total_q = sum(s['total'] for _, s in all_summaries)
        total_correct = sum(s['correct'] for _, s in all_summaries)
        total_scored = sum(s['scored'] for _, s in all_summaries)
        print("\n" + "=" * 60)
        print("全部题库汇总")
        print("=" * 60)
        print(f"题库数:     {len(all_summaries)}")
        print(f"题目总数:   {total_q}")
        print(f"可判分题:   {total_scored}")
        print(f"正确数:     {total_correct}")
        print(f"总准确率:   {total_correct/total_scored:.2%}" if total_scored else "总准确率:   N/A")
        print("=" * 60)

    # ---- LeanSearch 检索埋点落盘（2026-09-15，老师 #44）----
    # 只在**真正发生过检索**时写文件，避免生成空文件误导后续聚合。
    # 输出：每行一个事件（call / adopted），末尾一行 summary，便于离线按题统计漏斗。
    try:
        from tools.lean_local.lean_search import get_stats as _ls_stats
        _ls = _ls_stats()
        _ls_sum = _ls.summary()
        if _ls_sum.get("calls"):
            _ls_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "results", "leansearch_calls.jsonl")
            if _ls.flush(_ls_path):
                print("LeanSearch 埋点已落盘:", _ls_path)
                print("  汇总:", json.dumps(_ls_sum, ensure_ascii=False))
            else:
                print("LeanSearch 埋点落盘失败（不影响评测结果）")
    except Exception as _e:  # noqa: BLE001
        print("LeanSearch 埋点落盘跳过:", str(_e)[:160])


if __name__ == "__main__":
    main()
