#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""研究版（无时间限制 + 联网可用）评测启动器
=============================================

**为什么需要这个脚本**
----------------------
`run_eval.py` 与 `user_agent.py` 的**默认配置是"赛期受限档"**，用于对齐平台约束：

    max_time_per_question = 1100s
    tier_budget           = {fast:120, standard:540, deep:1150}
    paper_target_time     = 8438s（按 45 题卷折算）
    enable_web_search     = False   ← 联网工具关闭
    use_leansearch        = False   ← 联网定理检索关闭
    verifier_deep_final_enabled = False

比赛已结束，本仓库进入**研究阶段**，目标是**正确率**而非平台得分。
研究阶段的口径是「**无时间限制、无 token 限制、允许联网**」——
这组配置**不在代码默认值里**，只能由命令行传入。

本脚本就是把这组配置**固化下来**，让任何人 clone 后一条命令即可复现研究档。

用法
----
    # 1) 准备密钥（见 SETUP.md 第二节）
    #    OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL
    python run_research.py --test_file 题库/official112_本地测试题库/official112_full.jsonl \
                           --output results/research_run.jsonl

    # 单题、详细日志
    python run_research.py --test_file tests.jsonl --output r.jsonl --verbose

    # 显式覆盖研究档的某一项（放在 `--` 之后，用户参数优先）
    python run_research.py --test_file tests.jsonl --output r.jsonl -- \
        --max_time_per_question 3600

设计约束
--------
- **路径无关**：仓库根由 `__file__` 反推，不硬编码任何绝对路径
- **密钥不落库**：只从环境变量 / 仓库根 `.env` 读取
- **不改默认值**：`run_eval.py` / `user_agent.py` 的默认保持与平台约束对齐，
  研究档只作为**显式选择**存在（避免污染赛期提交语义）
- 横幅里的数值**从 `sys.argv` 反查**，杜绝"印的与实际不一致"
"""
import io
import os
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)

# ---------------------------------------------------------------- 研究档配置
# 取值理由：
#   · 86400s（24h）语义上等于"不限"，但避免进程因单次调用挂死而永久占住
#   · tier_budget 与研究档单题上限对齐 ⇒ paper_pacer 的收紧分支恒不触发
#     （`单题预算 = min(tier_cap, max(sustainable×系数, min_soft))`，
#      sustainable = 并发 × 剩余target / 剩余题数；target 极大 ⇒ 恒取 tier_cap）
#   · 连带效果（都是研究阶段想要的）：
#       `is_time_critical()`（剩余<120s）与 `emergency`（ratio>0.95）**永不触发**
#       ⇒ 5.5 复核 / 4.5 oracle 等所有时间守卫全部放开，不再被时间掐掉
RESEARCH_ARGS = [
    "--max_time_per_question", "86400",
    "--tier_budget", "86400,86400,86400",
    "--paper_target_time", "86400000",
    "--max_total_time_seconds", "86400000",
    # 联网（研究阶段允许）
    "--enable_web_search", "true",
    "--use_leansearch", "true",
    # 深度复核与研究期开关
    "--verifier_deep_final_enabled", "true",
    "--verifier_diversify_enabled", "true",
    "--verifier_deep_review_max_tokens", "6144",
    "--verbose",
]

# 仓库根 `.env` 的键 → 代码实际读取的环境变量
# （`utils/llm_client.py` 是**主链路**，读 OPENAI_*；根 `llm_client.py` 读 INTERN_*）
ENV_MAP = {
    "INTERN_API_KEY": "OPENAI_API_KEY",
    "INTERN_API_BASE": "OPENAI_BASE_URL",
    "INTERN_MODEL": "LLM_MODEL",
}


def load_dotenv(path: str) -> dict:
    """极简 .env 解析（不引入额外依赖）。返回解析到的键值。"""
    out = {}
    if not os.path.exists(path):
        return out
    try:
        for line in io.open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:  # noqa: BLE001
        print("[warn] 读取 .env 失败（忽略）: %s" % e)
    return out


def prepare_env() -> None:
    raw = load_dotenv(os.path.join(REPO, ".env"))
    # 补齐缺失项（**不覆盖**已显式设置的环境变量，便于 CI / 临时覆盖）
    for src, dst in ENV_MAP.items():
        if raw.get(src):
            os.environ.setdefault(dst, raw[src])
            os.environ.setdefault(src, raw[src])
    for k, v in raw.items():
        os.environ.setdefault(k, v)
    # Lean 相关：研究阶段允许 MCP 联网检索；Mathlib 冷启动需抬高超时地板
    os.environ.setdefault("LEAN_MCP_ALLOW_NET", "1")
    os.environ.setdefault("LEAN_MCP_TIMEOUT_FLOOR", "300")
    os.environ.setdefault("LLM_TIMEOUT", "300")
    os.environ.setdefault("LLM_RETRY_ON_TIMEOUT", "1")
    # LeanSearch 本地语料（可选；不存在时自动走在线 API）
    if not os.environ.get("LEANSEARCH_CORPUS_PATH"):
        for cand in (os.path.join(REPO, "data", "mathlib_informal", "data.jsonl"),
                     os.path.join(REPO, "data", "leansearch", "data.jsonl")):
            if os.path.exists(cand):
                os.environ["LEANSEARCH_CORPUS_PATH"] = cand
                break


def _argval(flag: str, default: str = "-") -> str:
    """从 sys.argv 反查实际生效值（杜绝横幅与实际不一致）。"""
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except (ValueError, IndexError):
        return default


def main() -> int:
    user_args = sys.argv[1:]
    prepare_env()

    # 研究档在前、用户参数在后 ⇒ 用户可**显式覆盖**研究档的某一项
    sys.argv = ["run_eval.py"] + RESEARCH_ARGS + user_args

    print("=" * 70, flush=True)
    print("MathPilot 研究版启动器（无时间限制 + 联网可用）", flush=True)
    print("=" * 70, flush=True)
    print("单题上限      : %ss（默认档 1100s）"
          % _argval("--max_time_per_question"), flush=True)
    print("档位预算      : %s（默认档 120,540,1150）"
          % _argval("--tier_budget"), flush=True)
    print("全卷目标/总限  : %s / %s（默认档 8438 / 20700）"
          % (_argval("--paper_target_time"), _argval("--max_total_time_seconds")),
          flush=True)
    print("联网          : web_search=%s  leansearch=%s（默认档均为 false）"
          % (_argval("--enable_web_search"), _argval("--use_leansearch")),
          flush=True)
    print("深度复核      : deep_final=%s  diversify=%s"
          % (_argval("--verifier_deep_final_enabled"),
             _argval("--verifier_diversify_enabled")), flush=True)
    print("题单          : %s" % _argval("--test_file", "（未指定！）"), flush=True)
    print("输出          : %s" % _argval("--output", "eval_results.jsonl"), flush=True)
    print("并发          : %s（本机 15 GB 内存，建议 1；见 README）"
          % _argval("--concurrency", "2"), flush=True)
    print("-" * 70, flush=True)
    print("环境: LEAN_MCP_ALLOW_NET=%s  LEAN_MCP_TIMEOUT_FLOOR=%s"
          % (os.environ.get("LEAN_MCP_ALLOW_NET"),
             os.environ.get("LEAN_MCP_TIMEOUT_FLOOR")), flush=True)
    print("      LLM_TIMEOUT=%s  LLM_RETRY_ON_TIMEOUT=%s"
          % (os.environ.get("LLM_TIMEOUT"),
             os.environ.get("LLM_RETRY_ON_TIMEOUT")), flush=True)
    print("      OPENAI_BASE_URL=%s  LLM_MODEL=%s"
          % (os.environ.get("OPENAI_BASE_URL") or "（未设置！）",
             os.environ.get("LLM_MODEL") or "（未设置）"), flush=True)
    if not os.environ.get("OPENAI_API_KEY"):
        print("      ⚠ OPENAI_API_KEY 未设置 —— 主链路会回落到 http://localhost:8000/v1 "
              "并整批失败。请见 SETUP.md 第二节。", flush=True)
    print("=" * 70, flush=True)

    import run_eval
    run_eval.main()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
