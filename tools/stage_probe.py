# -*- coding: utf-8 -*-
"""分阶段探针：从一次真实 run 的现场重建 ctx，**只跑指定阶段**。

为什么需要它
------------
全量跑一道 IMO 题要 5.7 小时（实测 val1_r1_1022），其中 46.6% 花在 4.6 重写。
但排查"4.1 为什么把这条判错"这类问题，只需要 4.1 的输入（候选 + 题面 + 子目标）。
本工具用 run 目录里已落盘的分阶段产物重建现场，把单阶段测试压缩到分钟级。

产物来源（`results/<run_id>/<qid>/`）
--------------------------------------
    01_understanding.json   题型 / 领域 / problem_goal / lean_applicable
    02_blueprint.json       蓝图
    03_subgoals.json        子目标计划
    04_subgoal_results.jsonl 子目标结果（含多轮重写）
    05_candidates.json      候选（id / answer / reasoning）
    07_lean.json            Lean 结果
    08_final.json           最终输出

用法
----
    python tools/stage_probe.py --run-dir <dir> --list
    python tools/stage_probe.py --run-dir <dir> --stage 4.1
    python tools/stage_probe.py --run-dir <dir> --stage 4.1 --cand 0      # 只测第 0 个候选
    python tools/stage_probe.py --run-dir <dir> --stage 4.2 --dry-run     # 只回放，不调模型
    python tools/stage_probe.py --run-dir <dir> --stage 4.1 --no-llm      # 用桩模型

⚠ 会真实调用 LLM（除 --dry-run / --no-llm），产生费用与耗时。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

STAGES = {
    "4.1": "self_audit（AI 自审：逻辑错误淘汰）",
    "4.2": "adversarial_gate（对抗证伪 + 跨模型）",
    "4.4": "math_check（数学工具计算检测）",
    "4.5": "vote（多答案判断 + 投票）",
}


# ------------------------------------------------------------------ 现场重建
def load_env() -> dict:
    env = {}
    path = os.path.join(_ROOT, ".env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def find_q_dir(run_dir: str) -> str:
    """run_dir 可以是 run 根目录，也可以直接是 <qid> 目录。"""
    run_dir = os.path.abspath(run_dir)
    if os.path.isfile(os.path.join(run_dir, "05_candidates.json")):
        return run_dir
    for name in sorted(os.listdir(run_dir)):
        p = os.path.join(run_dir, name)
        if os.path.isdir(p) and os.path.isfile(
                os.path.join(p, "05_candidates.json")):
            return p
    raise SystemExit("在 %s 下找不到含 05_candidates.json 的题目目录" % run_dir)


def load_json(qdir: str, name: str, default=None):
    p = os.path.join(qdir, name)
    if not os.path.isfile(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def load_jsonl(qdir: str, name: str) -> list:
    p = os.path.join(qdir, name)
    if not os.path.isfile(p):
        return []
    out = []
    for line in open(p, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass
    return out


def build_ctx(qdir: str, problem: str, u: dict, cands: list, sg_trace: list):
    """构造 TaskContext（只填本工具需要的字段）。"""
    from agent.base import TaskContext
    ctx = TaskContext(problem=problem, metadata={})
    try:
        ctx.blueprint = load_json(qdir, "02_blueprint.json", {}) or {}
        ctx.subgoal_trace = sg_trace
        ctx.candidates = cands
        md = getattr(ctx, "metadata", None) or {}
        md.update({
            "question_type": (u or {}).get("question_type", ""),
            "domain": (u or {}).get("domain", ""),
            "problem_goal": (u or {}).get("problem_goal") or {},
            "lean_applicable": (u or {}).get("lean_applicable", True),
        })
        ctx.metadata = md
        # 让 is_time_critical() 恒为 False：探针不应被超时逻辑干扰
        ctx.deadline = 0
        ctx.start_time = time.time()
        ctx.max_time_per_question = 0
    except Exception as exc:  # noqa: BLE001
        raise SystemExit("构造 TaskContext 失败: %s" % exc)
    return ctx


def build_candidates(raw: list, only=None):
    from agent.base import Candidate
    out = []
    for i, c in enumerate(raw):
        if only is not None and i != only:
            continue
        if not isinstance(c, dict):
            continue
        out.append(Candidate(id=c.get("id", i),
                             answer=c.get("answer", "") or "",
                             reasoning=c.get("reasoning", "") or ""))
    return out


# ------------------------------------------------------------------ 轻量 orch
class ProbeOrch:
    """只提供阶段函数用到的成员：config / client / record / llm。"""

    def __init__(self, use_llm: bool):
        from user_agent__config import AgentConfig
        self.config = AgentConfig()
        self.records: list = []
        self.client = None
        self.n_llm = 0
        if use_llm:
            from utils.llm_client import LLMClient
            env = load_env()
            self.client = LLMClient(
                api_key=env.get("INTERN_API_KEY", ""),
                base_url=env.get("INTERN_API_BASE", ""),
                model=env.get("INTERN_MODEL", ""), timeout=900)

    def record(self, ctx, step, msg, **kw):
        self.records.append((step, str(msg)[:300]))

    def llm(self, ctx, messages, temperature=0.0, max_tokens=4096):
        if self.client is None:
            raise RuntimeError("stub 模式下不应调用 llm")
        self.n_llm += 1
        return self.client.chat(messages=messages, temperature=temperature,
                                max_tokens=max(16384, max_tokens))


def _stub_llm(orch):
    """把 llm 替换成"什么都不判"的桩（只验证管线不验证判断）。"""
    orch.llm = lambda *a, **k: "{}"


# ------------------------------------------------------------------ 各阶段
def run_stage(stage: str, orch: ProbeOrch, ctx):
    if stage == "4.1":
        from agent.self_auditor import self_audit_stage
        self_audit_stage(orch, ctx)
    elif stage == "4.2":
        from agent.adversarial_gate import adversarial_gate_stage
        adversarial_gate_stage(orch, ctx, "deep")
    elif stage == "4.4":
        from agent.math_check_gate import math_check_stage
        math_check_stage(orch, ctx)
    elif stage == "4.5":
        from agent.final_selector import vote_stage  # 名称不符时给出提示
        vote_stage(orch, ctx)
    else:
        raise SystemExit("未支持的阶段: %s（支持 %s）" % (stage, ", ".join(STAGES)))


def summarize(ctx) -> dict:
    cands = getattr(ctx, "candidates", None) or []
    return {
        "候选数": len(cands),
        "候选答案": [str(getattr(c, "answer", ""))[:40] for c in cands],
    }


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="分阶段探针：只跑一个环节")
    ap.add_argument("--run-dir", default="", help="run 目录或 <qid> 目录")
    ap.add_argument("--stage", default="", help="4.1 / 4.2 / 4.4 / 4.5")
    ap.add_argument("--problem-file", default="", help="题面文本文件（不给则用占位）")
    ap.add_argument("--cand", type=int, default=None, help="只测第 N 个候选")
    ap.add_argument("--dry-run", action="store_true", help="只回放现场，不调模型")
    ap.add_argument("--no-llm", action="store_true", help="用桩模型（验证管线）")
    ap.add_argument("--list", action="store_true", help="列出可用阶段")
    args = ap.parse_args(argv)

    if args.list:
        for k, v in STAGES.items():
            print("  %-4s %s" % (k, v))
        return 0
    if not args.run_dir:
        ap.error("必须给 --run-dir")
    if not args.stage:
        ap.error("必须给 --stage（或 --list 查看）")

    qdir = find_q_dir(args.run_dir)
    u = load_json(qdir, "01_understanding.json", {}) or {}
    raw_c = load_json(qdir, "05_candidates.json", []) or []
    sg = load_jsonl(qdir, "04_subgoal_results.jsonl")

    problem = ""
    if args.problem_file and os.path.isfile(args.problem_file):
        problem = open(args.problem_file, encoding="utf-8").read()

    cands = build_candidates(raw_c, args.cand)
    print("现场: %s" % qdir)
    print("  子目标结果 %d 条 | 候选 %d 个%s"
          % (len(sg), len(cands),
             "（只测第 %d 个）" % args.cand if args.cand is not None else ""))
    print("  题型=%s 领域=%s lean_applicable=%s"
          % (u.get("question_type"), u.get("domain"), u.get("lean_applicable")))

    if args.dry_run:
        print("\n[dry-run] 候选清单：")
        for c in cands:
            print("  id=%s answer=%r" % (c.id, str(c.answer)[:60]))
        return 0

    ctx = build_ctx(qdir, problem, u, cands, sg)
    orch = ProbeOrch(use_llm=not args.no_llm)
    if args.no_llm:
        _stub_llm(orch)

    before = summarize(ctx)
    t0 = time.time()
    try:
        run_stage(args.stage, orch, ctx)
    except Exception:  # noqa: BLE001
        print("\n[阶段异常]")
        traceback.print_exc()
        return 2
    dt = time.time() - t0
    after = summarize(ctx)

    print("\n=== 阶段 %s 执行完毕（%.1fs，LLM 调用 %d 次）==="
          % (args.stage, dt, orch.n_llm))
    print("  候选：%d → %d" % (before["候选数"], after["候选数"]))
    if after["候选答案"]:
        print("  存活答案：")
        for a in after["候选答案"]:
            print("    - %s" % a)
    else:
        print("  存活答案：（无，全部被淘汰）")
    print("\n  阶段留痕（%d 条）：" % len(orch.records))
    for step, msg in orch.records[:40]:
        print("    [%s] %s" % (step, msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
