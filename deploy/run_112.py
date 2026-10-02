#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_112.py — 服务器端 112 题全量评测启动器。

与本地 `C:\\Users\\35174\\_run_solution10_0916.py` 的配置**逐项对齐**，只改路径：
  · 时间：max_time_per_question=86400 / tier_budget=86400（单档）/
          max_total_time_seconds=86400000（= 无实际上限，不跳过不中断）
          ★ 2026-09-29：全卷时间池已彻底删除，`--paper_target_time` /
            `--paper_total_questions` 不再传入（单题只受硬顶约束）
  · 复核：verifier_deep_final_enabled + verifier_diversify_enabled 均开
  · 检索：use_leansearch=true，LEANSEARCH_CORPUS_PATH 指向官方语料
  · 深复核 token 上限 6144（16384 实测会退化复读）
  · 并发固定 1（实测并发 2 会让 Lean/Mathlib 实例叠加 → 内存耗尽 → MCP 回落）

用法（在仓库根）：
    .venv/bin/python -u deploy/run_112.py
    .venv/bin/python -u deploy/run_112.py --test-file 题库/xxx.jsonl --out results/yyy.jsonl

环境变量来自 .env + deploy/cloud_run.env（本脚本自动 source 两者）。
"""
from __future__ import annotations

import argparse
import io
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

DEFAULT_TEST = "题库/official112_本地测试题库/official112_full.jsonl"

# ============================================================================
# 实验臂（AB arms）
# ----------------------------------------------------------------------------
# 2026-09-21 研究口径：**以"最大化解题能力"为目标**，不再以"省时间"为由削减机制。
# 选臂方式：环境变量 `MP_ARM`（也写进 `.env` 或用 `MP_ARM=arm2 ...` 前缀）。
#   ⇒ **同一条启动方式，只多一个环境变量**，不引入新的运行流程。
#
# 为什么走 `DEFAULT_AGENT_OVERRIDES` 注入而不是 CLI：
#   以下键**没有 argparse**（`run_eval.py` 里 grep 不到；`enable_skeleton_review`
#   的注释曾承诺 `--enable_skeleton_review`，但该参数实际不存在）：
#     max_subgoals_by_tier / tier_sample_times / tier_voting_times /
#     tier_max_completions / enable_skeleton_review
#   启动器对 `max_answer_tokens` 已用同一手法绕开（见本文件下方），此处沿用。
#   ⚠ 注入点必须在 `import run_eval` **之后**、`run_eval.main()` **之前**
#     —— EvalEngine 在 __init__ 里 `dict(DEFAULT_AGENT_OVERRIDES)` 做快照。
#   ⚠ 键必须同时满足：①在 AgentConfig 声明 ②在覆盖白名单内（四层检查）。
#     本字典所有键均已核对通过。
# ============================================================================
ARMS: dict = {
    # 臂 0：基线 = 现状配置（24 项机制关闭），不做任何改动
    "baseline": {},

    # ★ 臂 2（当前选定）：蓝图结构修复 + 评审链恢复
    # 依据：dag_replan_gate(09-08)、enable_skeleton_review(09-13)、
    #   enable_dag_replan(09-13) 被判「无效」的证据，**全部采于**
    #   `blueprint_deps_enabled` 修复(09-15)**之前** —— 当时 DAG 依赖边恒空、
    #   OR 节点退化为 AND 单分支 ⇒ 评审员很可能是在**正确报警**，
    #   「评审链无效」这一结论被上游结构缺陷**混杂**了。
    #   `blueprint_or_expand_all` 的注释自述：OR 退化「正是子目标链锁定错值的
    #   上游结构原因（比提示词层规则更根本）」。
    "arm2": {
        "blueprint_or_expand_all": True,
        "dag_replan_gate": True,
        "enable_dag_replan": True,
        "enable_skeleton_review": True,
    },

    # 臂 1：standard 档升配（standard 覆盖 89/112 题却只有 **1 票**验证）
    # ⚠ 未验证；且与「deep 18.8% < standard 31.8%」的档位倒挂数据**方向相反**
    "arm1": {
        "tier_voting_times": {"fast": 1, "standard": 3, "deep": 3},
        "tier_sample_times": {"fast": 1, "standard": 3, "deep": 3},
        "tier_max_completions": {"fast": 0, "standard": 2, "deep": 2},
        "max_subgoals_by_tier": {"standard": 16, "deep": 16},
    },

    # 臂 3：符号求解与交叉校验（正面打 55.4% 的推理/计算错误）
    # ⚠ 未验证；`symbolic_solve_enabled` 开启前需先做剥离正确性核验（既有遗留项）
    # 2026-10-01：原 `calc_mandatory` / `calc_hard_only` / `tool_calc_enabled`
    #   三键随 `<calc>` 计算工具板块整体删除，已移除。
    "arm3": {
        "symbolic_crosscheck_enabled": True,
        "symbolic_solve_enabled": True,
    },
}


def resolve_arm(cli: str | None = None):
    """选臂 → (臂名, 覆盖字典)。未知臂名直接 FATAL，不静默兜底。

    优先级：``--arm`` 参数 > ``MP_ARM`` 环境变量 > ``baseline``。
    为什么要 CLI：``tools/cloud.py run`` 只支持 ``--launcher_args "<参数>"``，
    **无法给远端进程设置环境变量**，故臂名必须能从命令行传。
    """
    name = str(cli or os.environ.get("MP_ARM") or "baseline").strip()
    if name not in ARMS:
        print("FATAL: 未知 MP_ARM=%r。可选：%s"
              % (name, ", ".join(sorted(ARMS))), flush=True)
        raise SystemExit(2)
    return name, dict(ARMS[name])



def load_env_file(path: Path) -> None:
    """把 KEY=VALUE 读进 os.environ（不覆盖已存在的值）。"""
    if not path.is_file():
        print(f"WARN: 缺少 {path}", flush=True)
        return
    for raw in io.open(path, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # 展开 ${VAR} 引用（cloud_run.env 里用了）
        if "$" in v:
            v = os.path.expandvars(v)
        os.environ.setdefault(k, v)


def source_shell_env(path: Path) -> None:
    """用 bash 求值一个 shell 环境文件，导出成 KEY=VALUE 行再吸收。

    需要的理由：cloud_run.env 里写了 export X="$Y" 这类**变量引用**，
    纯 Python 解析不出。用 bash source 后 env 打印最可靠。
    """
    if not path.is_file():
        return
    cmd = f'set -a; . ./.env 2>/dev/null; . "{path}" 2>/dev/null; env'
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=str(ROOT),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except FileNotFoundError:
        print("WARN: 没有 bash，跳过 shell 环境解析", flush=True)
        return
    if r.returncode != 0:
        print(f"WARN: source {path.name} 返回 {r.returncode}: "
              f"{(r.stderr or '').strip()[:200]}", flush=True)
    for line in (r.stdout or "").splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k and not k.startswith("_"):
            os.environ[k] = v


def preflight_quota_check() -> str:
    """★ 2026-09-22：启动前**配额预检（熔断）**。返回 "" = 可启动，否则返回中止原因。

    背景（实测代价）：2026-09-21 那轮因账号输入 token 配额耗尽，最终跑出 **0/112**
    —— 108 题落盘占位符「未给出有效解答。」，而占位符会被判分器**计为错误**
    ⇒ 既烧掉约 5 小时，又**静默污染正确率**。

    本预检在**创建输出文件之前**用一次最小请求探活：
      · 明确命中 `-20080`（超过输入 tokens 配额）⇒ 中止，**不产生任何产物**；
      · 其它情况（网络抖动 / 其它 4xx / 超时）⇒ **放行**，避免误伤正常启动。
    """
    import urllib.error
    import urllib.request
    base = (os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("LLM_MODEL") or "Intern-S2-Preview-397B"
    if not base or not key:
        return ""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        return ("配额超限 -20080：" + body[:200]) if "-20080" in body else ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return ("配额超限 -20080：" + body[:200]) if "-20080" in body else ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="服务器端 112 题评测启动器")
    ap.add_argument("--test-file", default=DEFAULT_TEST)
    ap.add_argument("--out", default="")
    ap.add_argument("--tag", default="cloud112")
    ap.add_argument("--concurrency", default="1")
    ap.add_argument("--arm", default=None,
                    help="实验臂名（优先于 MP_ARM 环境变量）。可选：%s"
                         % ", ".join(sorted(ARMS)))
    args = ap.parse_args()

    # ---- 环境：.env（DEEPSEEK_*）→ lean-env.sh（PATH + LEAN_PATH）→ cloud_run.env ----
    load_env_file(ROOT / ".env")
    # ★ 必须 source：setup_lean.sh 生成的 lean-env.sh 提供
    #   · PATH  —— 让 lean / lake 可被 MCP 与 bridge 找到
    #   · LEAN_PATH —— Mathlib 闭包
    #   缺它会导致 MCP 起不来 + bridge 找不到 olean。
    source_shell_env(ROOT / "deploy" / "lean-env.sh")
    source_shell_env(ROOT / "deploy" / "cloud_run.env")

    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_BASE_URL"):
        print("FATAL: 缺少 OPENAI_API_KEY / OPENAI_BASE_URL。"
              "检查 .env 是否有 DEEPSEEK_*，以及 deploy/cloud_run.env 是否映射正确。",
              flush=True)
        return 2

    # ★ 2026-09-22：启动前**配额预检（熔断）** —— 配额耗尽时直接不启动。
    #   放在这里是因为此刻**尚未创建任何产物**（输出文件 / 日志 / env 快照都在后面），
    #   中止后不会留下半成品，也不会占用 tmux 会话。
    _pre = preflight_quota_check()
    if _pre:
        print("FATAL: 启动前配额预检未通过，已中止本轮（未创建任何产物）。", flush=True)
        print("       原因：" + _pre, flush=True)
        print("       处置：等账号输入 token 配额恢复后再跑。"
              "配额耗尽时跑下去只会落盘占位符，而占位符会被判分器计为错误，"
              "既烧时间又静默污染正确率。", flush=True)
        return 3

    if not os.path.isfile(args.test_file):
        print(f"FATAL: 题单不存在 {args.test_file}", flush=True)
        return 2

    # ---- 实验臂（必须在 banner 之前解析，好把臂名打进日志）----
    arm_name, arm_overrides = resolve_arm(args.arm)

    out = args.out or f"results/{args.tag}_{time.strftime('%m%d_%H%M')}.jsonl"
    log = out[:-6] + ".log" if out.endswith(".jsonl") else out + ".log"
    env_snap = (out[:-6] + ".env") if out.endswith(".jsonl") else out + ".env"
    Path("results").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # ---- 断点/重跑：输出已存在就归档，绝不删除（沿用本地习惯）----
    if os.path.exists(out):
        arch = out[:-6] + f"_中断{int(time.time())}.jsonl"
        os.replace(out, arch)
        print(f"!! 输出已存在，已归档为 {arch}", flush=True)

    # ---- 日志 Tee ----
    logf = io.open(log, "w", encoding="utf-8", buffering=1)

    class Tee:
        def __init__(self, *s):
            self.s = s

        def write(self, x):
            for st in self.s:
                try:
                    st.write(x)
                except Exception:  # noqa: BLE001
                    pass

        def flush(self):
            for st in self.s:
                try:
                    st.flush()
                except Exception:  # noqa: BLE001
                    pass

    sys.stdout, sys.stderr = Tee(sys.__stdout__, logf), Tee(sys.__stderr__, logf)

    # ---- 环境快照（值脱敏）----
    with io.open(env_snap, "w", encoding="utf-8") as fh:
        for k in sorted(os.environ):
            if not any(k.startswith(p) for p in
                       ("OPENAI_", "LLM_", "LEAN_", "DEEPSEEK_", "PYTHON")):
                continue
            v = os.environ[k]
            if any(x in k for x in ("KEY", "TOKEN", "SECRET")):
                v = v[:6] + "***"
            fh.write(f"{k}={v}\n")

    n_questions = sum(1 for _ in io.open(args.test_file, encoding="utf-8"))

    # ---- 实验臂快照：让每份结果**自描述**，便于跨臂对照 ----
    arm_snap = (out[:-6] if out.endswith(".jsonl") else out) + ".arm.json"
    with io.open(arm_snap, "w", encoding="utf-8") as _fh:
        json.dump({
            "arm": arm_name,
            "overrides": arm_overrides,
            "test_file": args.test_file,
            "n_questions": n_questions,
            "concurrency": str(args.concurrency),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "out": out,
        }, _fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"臂快照 {arm_snap}", flush=True)

    # ---- run_eval 的命令行（与本地逐项对齐）----
    sys.argv = [
        "run_eval.py",
        "--test_file", args.test_file,
        "--output", out,
        "--concurrency", str(args.concurrency),
        # 时间：无实际上限，不跳过、不中断、不终止
        "--max_time_per_question", "86400",
        # ★★ 2026-09-29：档位已统一为单档（一律取原 deep 最强配置），
        #   `--tier_budget` 只需给**单段**值（旧的三段式 f,s,d 仍兼容，取末段）。
        #   全卷时间池（PaperPacer）与 `--paper_target_time` / `--paper_total_questions`
        #   已按用户要求**彻底删除** —— 云端不再有全卷总量控制，单题只受上方的
        #   86400s 硬顶约束（适合不限时研究评测）。
        "--tier_budget", "86400",
        "--max_total_time_seconds", "86400000",
        # 两项复核机制
        "--verifier_deep_final_enabled", "true",
        "--verifier_diversify_enabled", "true",
        # ★★ 2026-09-21 参数审查实测（105 条 deep_review 样本）：
        #   原值 6144 只有代码默认值（16384）的 37%。实测输出长度
        #   中位 7409 tokens、p90 8755、max 9827 ⇒ **72%（76/105）的深度评审
        #   输出被截断**，等于"判对/判错"的结论根本没写完就被砍掉。
        #   提到 16384 后超限样本 0 / 105。
        "--verifier_deep_review_max_tokens", "16384",
        # 检索
        "--use_leansearch", "true",
        # ★★ 2026-09-21 参数审查实测（44 题）：`hits` **恒等于 5 = top_k**，
        #   `unique` 亦恒等于 5 ⇒ 100% 饱和。饱和说明条数是被"截"出来的，
        #   而不是"恰好只有 5 条相关"。代码默认 5；
        #   run_eval.py:1515 载「老师 #46 要求扫 3/5/10」⇒ 本轮取 10。
        "--leansearch_top_k", "10",
        "--enable_web_search", "true",
        "--verbose",
    ]

    def argval(flag, default="-"):
        try:
            return sys.argv[sys.argv.index(flag) + 1]
        except (ValueError, IndexError):
            return default

    print("=" * 74, flush=True)
    print(f"START  云端 112 题全量评测（无时间上限 / 并发 {argval('--concurrency')}）", flush=True)
    print(f"题单   {args.test_file}  共 {n_questions} 题", flush=True)
    print(f"输出   {out}", flush=True)
    print(f"日志   {log}", flush=True)
    print(f"环境   {env_snap}（值已脱敏）", flush=True)
    print(f"时间   max_time_per_question={argval('--max_time_per_question')}s  "
          f"tier_budget={argval('--tier_budget')}", flush=True)
    print(f"       max_total_time_seconds={argval('--max_total_time_seconds')}"
          f"（单档统一：无全卷时间池，单题只受硬顶约束）", flush=True)
    print(f"并发   {argval('--concurrency')}", flush=True)
    print(f"实验臂 MP_ARM={arm_name}  覆盖 {len(arm_overrides)} 项"
          + ("" if arm_overrides else "（baseline：不改任何机制）"), flush=True)
    for _ak in sorted(arm_overrides):
        print(f"       {_ak} = {arm_overrides[_ak]!r}", flush=True)
    print(f"开关   deep_final={argval('--verifier_deep_final_enabled')}  "
          f"diversify={argval('--verifier_diversify_enabled')}  "
          f"leansearch={argval('--use_leansearch')}  "
          f"web_search={argval('--enable_web_search')}", flush=True)
    # ★ 2026-09-21 参数审查：把本轮两个改动量显式打出来，便于启动时逐项核验
    print(f"检索   leansearch_top_k={argval('--leansearch_top_k')}  "
          f"deep_review_max_tokens={argval('--verifier_deep_review_max_tokens')}"
          f"（旧值 5 / 6144）", flush=True)
    # ★ MCP 增强三项（0921 由"为省时间默认关"改为一律开，见 cloud_run.env）
    print(f"MCP增强 goal_loc={os.environ.get('LEAN_MCP_GOAL_LOC', '0')}  "
          f"multi_attempt={os.environ.get('LEAN_MCP_MULTI_ATTEMPT', '0')}  "
          f"hover_check={os.environ.get('LEAN_MCP_HOVER_CHECK', '0')}", flush=True)
    print(f"LLM    base={os.environ['OPENAI_BASE_URL']}  "
          f"model={os.environ.get('LLM_MODEL')}  "
          f"timeout={os.environ.get('LLM_TIMEOUT')}  "
          f"retry={os.environ.get('LLM_RETRY_ON_TIMEOUT')}", flush=True)
    print(f"语料   {os.environ.get('LEANSEARCH_CORPUS_PATH')}  "
          f"存在={os.path.isfile(os.environ.get('LEANSEARCH_CORPUS_PATH', ''))}", flush=True)
    print(f"LEAN   PATH={'有' if os.environ.get('LEAN_PATH') else '无'}  "
          f"ALLOW_NET={os.environ.get('LEAN_MCP_ALLOW_NET')}", flush=True)
    # MCP 通道是否真能生效（决定性：找不到执行器就会静默回落 bridge）
    try:
        sys.path.insert(0, str(ROOT))
        from tools.lean_local.lean_bridge import _detect_mcp_proxy_python
        _mp = _detect_mcp_proxy_python()
    except Exception as e:  # noqa: BLE001
        _mp = f"(探测异常 {type(e).__name__})"
    print(f"MCP    执行器={'★ ' + _mp if _mp else '❌ 未找到 → 会回落 bridge'}  "
          f"AUTOLAKE={os.environ.get('LEAN_MCP_AUTOLAKE', '1(默认)')}", flush=True)
    print(f"       lean={'✓ ' + os.environ['LEAN_PATH'] if os.environ.get('LEAN_PATH') else '❌ 无 LEAN_PATH'}",
          flush=True)
    print("=" * 74, flush=True)

    import run_eval
    # ★★ 2026-09-21 用户指示"放开"：默认档位 8192 → 32768（4x）。
    #   依据（本次实测，44 题基线 1946 次配对调用）：
    #     · 8192 档 max completion = 23818 字符（≈2.9 字符/token）= 顶到上限，
    #       说明确有输出被截断；单次调用耗时 max 277.3s，300s 余量仅 7.9%。
    #     · 生成速率 ≈ 85.6 字符/秒 ⇒ 32768 token 理论需 1110s。
    #   ⚠️ 0918 报告"必须 8192、勿用 65536"在当时成立，但根因是**上限与读超时
    #      长度不匹配**（那时 LLM_TIMEOUT≈120s，65536 需 2221s ⇒ 必然超时），
    #      不是 8192 有魔力。故本项必须与 `LLM_TIMEOUT` 成对调整：
    #      cloud_run.env 已同步把 LLM_TIMEOUT 300 → 1800（余量比 1.62）。
    #      **切勿只改这里不改 LLM_TIMEOUT** —— 下方已有护栏自动告警。
    #   ⚠️ 本仓 `run_eval.py` **没有** `--max_answer_tokens` 这个 CLI 参数
    #   （override 映射表在 1550–1667 行，逐项看过，确实没有），所以只能在启动器里
    #   改模块默认值。`AB_OVERRIDES` 是另一台机器 `run_prog.py` 的机制，本仓不认。
    #   改默认值必须在 `run_eval.main()` **之前**：EvalEngine 在 __init__ 里
    #   `dict(DEFAULT_AGENT_OVERRIDES)` 拷贝快照。
    _mat = int(os.environ.get("MAX_ANSWER_TOKENS", "32768"))
    _old_mat = run_eval.DEFAULT_AGENT_OVERRIDES.get("max_answer_tokens")
    run_eval.DEFAULT_AGENT_OVERRIDES["max_answer_tokens"] = _mat
    # ---- 余量比护栏（0921）：token 上限与读超时必须匹配，否则长输出必读超时 ----
    #   余量比 = LLM_TIMEOUT / 理论生成耗时；理论耗时按实测速率 85.6 字符/秒、
    #   2.9 字符/token 估算。8192+300s 时该比值仅 1.08（已贴死）。
    _to = int(os.environ.get("LLM_TIMEOUT", "120"))
    _need = int(_mat * 2.9 / 85.6) or 1
    _ratio = _to / _need
    print(f"口径   max_answer_tokens: 默认 {_old_mat} → 实际 {_mat}"
          f" / LLM_TIMEOUT={_to}s（余量比 {_ratio:.2f}，理论需 {_need}s；"
          f"可用 MAX_ANSWER_TOKENS 覆盖）", flush=True)
    if _ratio < 1.2:
        print(f"⚠️  余量比 {_ratio:.2f} < 1.2：长输出可能读超时 → "
              f"`Candidate empty response`。请同步抬高 LLM_TIMEOUT"
              f"（env 里 export LLM_TIMEOUT=<秒>）。", flush=True)

    # ---- 实验臂注入（必须在 EvalEngine 建实例之前）----
    for _k, _v in arm_overrides.items():
        _b = run_eval.DEFAULT_AGENT_OVERRIDES.get(_k, "<未设置>")
        run_eval.DEFAULT_AGENT_OVERRIDES[_k] = _v
        print(f"臂     {_k}: {_b!r} → {_v!r}", flush=True)

    try:
        run_eval.main()
    except KeyboardInterrupt:
        print("!! 被中断（结果已增量落盘，可 resume）", flush=True)
    print(f"DONE   {time.strftime('%F %T')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
