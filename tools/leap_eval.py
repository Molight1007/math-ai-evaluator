# -*- coding: utf-8 -*-
"""LEAP 三阶段端到端跑分脚本（工具）

用法示例（在项目根目录 D:/挑战杯 下运行）：
    python tools/leap_eval.py --backend intern --problems PB-Basic-001 --out eval_out
    python tools/leap_eval.py --backend deepseek --limit 3 --out eval_out_ds

参数：
    --backend  intern | deepseek     模型后端（书生 / DeepSeek）
    --model    覆盖模型名（默认读环境变量）
    --problems 逗号分隔 Problem ID（如 PB-Basic-001,PB-Basic-002）；缺省随机取
    --limit    N                       最多跑 N 题（与 --problems 互斥时按序取）
    --leansearch                         启用 Mathlib 定理检索（#31）
    --no-refiner                         关闭 Stage 3 迭代精炼
    --out      输出目录（默认 eval_out）

环境变量：
    书生：INTERN_API_KEY / INTERN_API_BASE / INTERN_MODEL（默认 Intern-S2-Preview-397B）
    DeepSeek：DEEPSEEK_API_KEY / DEEPSEEK_API_BASE / DEEPSEEK_MODEL（默认 deepseek-v4-flash）

单题流程（对应 LEAP 三阶段 + 老师 #26-#33）：
    LeanPreVerifier（前置形式化+骨架审核 #28）
    → BlueprintPlanner（AND-OR DAG #27）
    → LeanTranslator（叶子→Lean 声明+sorry 整树审核 #26/#28）
    → LeanRefiner（sorry 迭代补全+OR 回溯+lemma 记忆 #29/#30/#32/#33）
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintPlannerAgent
from agent.lean_translator import LeanTranslatorAgent
from agent.lean_refiner import LeanRefinerAgent
from agent.lean_pre_verifier import LeanPreVerifier
from user_agent import AgentConfig

DEFAULT_BENCH = os.path.join(_ROOT, "superhuman", "imobench", "lean_proof_bench.csv")

# ============================================================
# 模型客户端（OpenAI 兼容，统一 chat 接口）
# ============================================================

class OpenAICompatClient:
    """OpenAI 兼容聊天客户端（书生 / DeepSeek 通用）。

    min_max_tokens：推理模型（DeepSeek）先输出长思考过程再给答案，
    max_tokens 太小会被推理占满导致 content 为空，故设下限放大。
    """

    def __init__(self, api_key: str, api_base: str, model: str,
                 timeout: int = 180, retry: int = 3,
                 min_max_tokens: int = 0):
        self.authorization = (api_key if api_key.startswith("Bearer ")
                              else f"Bearer {api_key}")
        self.api_base = api_base
        self.model = model
        self.timeout = timeout
        self.retry = retry
        self.min_max_tokens = min_max_tokens

    def chat(self, messages=None, temperature=0.0, max_tokens=256, **kw) -> str:
        import requests
        max_tokens = max(max_tokens, self.min_max_tokens)
        payload = {
            "model": self.model,
            "messages": messages or [],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update({k: v for k, v in kw.items() if v is not None})
        last_err = None
        for _ in range(self.retry):
            try:
                resp = requests.post(
                    self.api_base, headers={
                        "Authorization": self.authorization,
                        "Content-Type": "application/json",
                    }, json=payload, timeout=self.timeout)
                data = resp.json()
                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}: {data}"
                    continue
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict))
                return str(content or "")
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                time.sleep(1)
        raise RuntimeError(f"LLM 调用失败: {last_err}")


def _load_project_env() -> None:
    """加载项目 .env 中缺失/过期的环境变量。

    环境变量中可能残留旧 key（如过期的 INTERN_API_KEY），允许 .env 覆盖
    API key 类变量，保证脚本始终使用 .env 中的有效凭据。
    """
    env_path = os.path.join(_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and (k not in os.environ
                            or k in ("INTERN_API_KEY", "DEEPSEEK_API_KEY")):
                os.environ[k] = v


def _norm_base(base: str) -> str:
    """把 API base 归一化为完整 chat/completions 端点（兼容 .env 惯例）。"""
    base = (base or "").strip().rstrip("/")
    if not base:
        return base
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def make_client(backend: str, model: str = "") -> OpenAICompatClient:
    """按后端构造客户端（读环境变量，缺失时回退项目 .env）。"""
    _load_project_env()
    backend = (backend or "intern").lower()
    if backend == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")
        return OpenAICompatClient(
            api_key=api_key,
            api_base=_norm_base(os.environ.get(
                "DEEPSEEK_API_BASE",
                "https://api.deepseek.com/v1/chat/completions")),
            model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            min_max_tokens=16384,  # 推理模型：reasoning 占 token，需留足空间给 content
        )
    # 书生（Intern-S 系列）
    api_key = os.environ.get("INTERN_API_KEY", "")
    if not api_key:
        raise RuntimeError("缺少 INTERN_API_KEY 环境变量")
    return OpenAICompatClient(
        api_key=api_key,
        api_base=_norm_base(os.environ.get(
            "INTERN_API_BASE",
            "https://chat.intern-ai.org.cn/api/v1/chat/completions")),
        model=model or os.environ.get("INTERN_MODEL", "Intern-S2-Preview-397B"),
    )


# ============================================================
# 数据加载
# ============================================================

def load_bench(path: str = "") -> List[Dict]:
    """读取 lean_proof_bench.csv，返回 [{id, problem, lean_statement}]。"""
    path = path or DEFAULT_BENCH
    if not os.path.exists(path):
        raise FileNotFoundError(f"基准文件不存在: {path}")
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "id": (row.get("Problem ID") or "").strip(),
                "problem": (row.get("Problem") or "").strip(),
                "lean_statement": (row.get("Lean Statement") or "").strip(),
                "category": (row.get("Category") or "").strip(),
                "level": (row.get("Level") or "").strip(),
            })
    return [r for r in rows if r["id"] and r["problem"]]


# ============================================================
# 单题三阶段
# ============================================================

# 裸模型模式提示词（B 对照：无框架，直接让 LLM 写 Lean 证明）
BARE_PROMPT_SYSTEM = """你是一位精通 Lean 4 形式化证明的数学专家。请把数学问题用 Lean 4 完整证明。

要求：
1. 直接输出**完整可编译的 Lean 代码**（以 `import Mathlib` 开头）
2. 证明必须完整，**不得使用 sorry 占位**
3. 只输出代码，不要额外解释
4. 优先使用 Mathlib 现成 tactic：omega / norm_num / ring / linarith / aesop / simp 等"""

BARE_PROMPT_USER = """请用 Lean 4 完整证明以下数学问题。

============================================================
题目：
{problem}
============================================================

输出完整 Lean 4 证明代码（import Mathlib 开头，无 sorry）。"""


def _extract_lean_code(text: str) -> str:
    """从 LLM 输出提取 Lean 代码（去围栏；取含 import Mathlib 的段落）。"""
    if not text:
        return ""
    import re
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", text)
    body = m.group(1).strip() if m else text.strip()
    # 若输出含多余解释，取 import 之后的部分
    idx = body.find("import Mathlib")
    if idx != -1:
        body = body[idx:]
    return body.strip()


def run_bare(client, cfg: AgentConfig, item: Dict) -> Dict:
    """裸模型基线：直接让 LLM 写 Lean 证明，严格编译验证（无迭代）。"""
    t0 = time.time()
    messages = [
        {"role": "system", "content": BARE_PROMPT_SYSTEM},
        {"role": "user", "content": BARE_PROMPT_USER.format(
            problem=item["problem"])},
    ]
    try:
        raw = client.chat(messages, temperature=0.2, max_tokens=8192)
    except Exception as e:  # noqa: BLE001
        return {"problem_id": item["id"], "mode": "bare",
                "compiled": False, "sorries": -1,
                "error": f"LLM 调用失败: {str(e)[:200]}",
                "elapsed_s": round(time.time() - t0, 1)}
    lean_code = _extract_lean_code(raw)
    if not lean_code:
        return {"problem_id": item["id"], "mode": "bare",
                "compiled": False, "sorries": -1,
                "error": "未提取到 Lean 代码",
                "elapsed_s": round(time.time() - t0, 1)}
    from agent.lean_refiner import LeanRefinerAgent
    from agent.lean_translator import count_sorries
    refiner = LeanRefinerAgent(client, cfg)
    ctx = TaskContext(problem=item["problem"], metadata={},
                      domain="proof", budget=None)
    comp = refiner._compile_code(ctx, lean_code, allow_sorry=False)
    return {
        "problem_id": item["id"], "mode": "bare",
        "compiled": bool(comp.get("ok")),
        "sorries": count_sorries(lean_code),
        "error": (comp.get("error", "") or "")[:200] if not comp.get("ok") else "",
        "lean_code_len": len(lean_code),
        "elapsed_s": round(time.time() - t0, 1),
    }

def run_single(client, cfg: AgentConfig, item: Dict,
               use_refiner: bool = True) -> Dict:
    """单题 LEAP 三阶段端到端。返回结构化结果。"""
    problem = item["problem"]
    # 用 csv 的 Lean Statement 作为形式化基线（若有）
    lean_hint = item.get("lean_statement", "")
    ctx = TaskContext(
        problem=problem,
        metadata={"problem_id": item["id"], "category": item.get("category", "")},
        domain="proof",
        budget=Budget(max_calls=1500),
        start_time=time.time(),
        deadline=time.time() + 1200,
        total_start_time=0.0,
        total_deadline=0.0,
    )
    steps = {}

    # Stage 0/2 前置：形式化 + 骨架审核（#28）
    t0 = time.time()
    try:
        preverifier = LeanPreVerifier(client, cfg)
        preverifier.run(ctx)
        steps["preverify"] = {
            "verdict": (ctx.preverify_trace or {}).get("verdict", "unknown"),
            "formal_spec": (ctx.formal_spec or "")[:200],
            "sketch_audit": (ctx.sketch_audit or {}).get("verdict", "unknown"),
        }
    except Exception as e:  # noqa: BLE001
        steps["preverify"] = {"verdict": "error", "error": str(e)[:200]}

    # Stage 1：Blueprint DAG（#27）
    dag_data = None
    try:
        planner = BlueprintPlannerAgent(client, cfg)
        dag = planner.generate_blueprint(ctx)
        dag_data = dag.to_dict() if dag else None
        steps["blueprint"] = {
            "ok": bool(dag),
            "nodes": len(dag.nodes) if dag else 0,
            "root": dag.root_id if dag else "",
            "valid": dag.validate()[0] if dag else False,
        }
    except Exception as e:  # noqa: BLE001
        steps["blueprint"] = {"ok": False, "error": str(e)[:200]}

    # Stage 2：整树搭桥（#26/#28）
    if dag_data:
        try:
            dag = BlueprintDAG.from_dict(dag_data)
            translator = LeanTranslatorAgent(client, cfg)
            sketch_tree = translator.translate_and_audit(ctx, dag)
            ctx.sketch_tree = sketch_tree  # 关键：写回黑板，Stage 3 依赖它
            steps["stage2"] = {
                "verdict": sketch_tree.get("verdict"),
                "leaves": sketch_tree.get("leaf_count"),
                "sorries": sketch_tree.get("sorry_count"),
                "gaps": len(sketch_tree.get("gaps", [])),
            }
        except Exception as e:  # noqa: BLE001
            steps["stage2"] = {"verdict": "error", "error": str(e)[:200]}

    # Stage 3：迭代精炼（#29/#30/#32/#33）
    if use_refiner and dag_data and ctx.sketch_tree:
        try:
            dag = BlueprintDAG.from_dict(ctx.blueprint)
            refiner = LeanRefinerAgent(client, cfg)
            refine = refiner.refine_tree(ctx, dag, ctx.sketch_tree)
            steps["stage3"] = {
                "verdict": refine.get("verdict"),
                "done": refine.get("done"),
                "failed": refine.get("failed"),
                "backtracks": refine.get("backtracks"),
                "llm_calls": refine.get("llm_calls"),
            }
        except Exception as e:  # noqa: BLE001
            steps["stage3"] = {"verdict": "error", "error": str(e)[:200]}

    return {
        "problem_id": item["id"],
        "elapsed_s": round(time.time() - t0, 1),
        "llm_hint_lean": lean_hint[:120],
        "steps": steps,
    }


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="LEAP 三阶段端到端跑分")
    ap.add_argument("--backend", default="intern", choices=["intern", "deepseek"])
    ap.add_argument("--model", default="", help="覆盖模型名")
    ap.add_argument("--mode", default="framework",
                    choices=["framework", "bare"],
                    help="framework=三阶段智能体；bare=裸模型直接写 Lean 证明")
    ap.add_argument("--problems", default="", help="逗号分隔 Problem ID")
    ap.add_argument("--limit", type=int, default=0, help="最多跑 N 题")
    ap.add_argument("--bench", default="", help="lean_proof_bench.csv 路径")
    ap.add_argument("--leansearch", action="store_true", help="启用 #31 定理检索")
    ap.add_argument("--no-refiner", action="store_true", help="关闭 Stage 3")
    ap.add_argument("--out", default="eval_out", help="输出目录")
    args = ap.parse_args()

    client = make_client(args.backend, args.model)
    print(f"[backend] {args.backend} model={client.model}")
    print(f"[bench]  {args.bench or DEFAULT_BENCH}")

    items = load_bench(args.bench)
    if args.problems:
        wanted = {p.strip() for p in args.problems.split(",") if p.strip()}
        items = [it for it in items if it["id"] in wanted]
        print(f"[select] 指定 {len(items)} 题: {sorted(wanted)}")
    elif args.limit > 0:
        items = items[:args.limit]
        print(f"[select] 取前 {len(items)} 题")
    else:
        random.shuffle(items)
        print(f"[select] 随机 {len(items)} 题")

    cfg = AgentConfig(
        use_blueprint=True,
        enable_sketch_audit=True,
        use_leansearch=args.leansearch,
        use_refiner=not args.no_refiner,
    )

    os.makedirs(args.out, exist_ok=True)
    results = []
    for idx, item in enumerate(items, 1):
        print(f"\n=== [{idx}/{len(items)}] {item['id']} ===")
        if args.mode == "bare":
            r = run_bare(client, cfg, item)
            results.append(r)
            print(f"  bare: compiled={r.get('compiled')}, "
                  f"sorries={r.get('sorries')}, {r.get('error', '')[:80]}")
        else:
            r = run_single(client, cfg, item, use_refiner=not args.no_refiner)
            results.append(r)
            print(f"  steps: {json.dumps(r['steps'], ensure_ascii=False)[:300]}")

    # 汇总
    total = len(results)
    print("\n========== 汇总 ==========")
    print(f"题目数: {total}  模式: {args.mode}  后端: {args.backend}")
    if args.mode == "bare":
        compiled = sum(1 for r in results if r.get("compiled"))
        zero_sorry = sum(1 for r in results if r.get("sorries") == 0)
        print(f"Lean 编译通过（无 sorry）: {compiled}/{total}")
        print(f"零 sorry 输出: {zero_sorry}/{total}")
        avg_time = sum(r.get("elapsed_s", 0) for r in results) / max(1, total)
        print(f"平均单题耗时: {avg_time:.1f}s")
    else:
        ok_stage3 = sum(1 for r in results
                        if r["steps"].get("stage3", {}).get("verdict") == "ok")
        ok_stage2 = sum(1 for r in results
                        if r["steps"].get("stage2", {}).get("verdict") == "ok")
        ok_blueprint = sum(1 for r in results
                           if r["steps"].get("blueprint", {}).get("ok"))
        print(f"Blueprint DAG 生成成功: {ok_blueprint}/{total}")
        print(f"Stage2 整树审核 ok: {ok_stage2}/{total}")
        print(f"Stage3 精炼 ok: {ok_stage3}/{total}")
        avg_time = sum(r["elapsed_s"] for r in results) / max(1, total)
        print(f"平均单题耗时: {avg_time:.1f}s")

    out_json = os.path.join(args.out, f"leap_eval_{args.backend}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"backend": args.backend, "model": client.model,
                   "results": results}, f, ensure_ascii=False, indent=1)
    print(f"\n结果已保存: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
