# -*- coding: utf-8 -*-
"""DAG 动态闭环端到端冒烟（Step 5，真实 LLM 版）

验证目标（老师 #34「dag 框架错了要重新构建，一点点改蓝图直至正确」）：
    1. 蓝图画错时（多 case 漏分支 / 缺 anticipatory lemma / 子目标不等价）
       DagReviewer 能给出 reject
    2. should_replan 判定正确（reject>=3 或 占比>=40%）
    3. regenerate_with_feedback 重生成的新蓝图**修正了原错误**
    4. 重生成后再次评审通过 → 闭环终止（不死循环）

两种运行模式：
    python tools/smoke_dag_replan.py            # mock LLM（无 key 也能跑，验证机制）
    python tools/smoke_dag_replan.py --real     # 真实 LLM（需 INTERN_API_KEY 有效）

mock 模式脚本化剧情：
    - 第一轮蓝图：故意画错（子目标粒度粗、含循环依赖、漏 case）
    - DagReviewer 评审 → reject >= 3 → should_replan=True
    - regenerate_with_feedback → 输出修正版 DAG（补齐 case、无循环、粒度细）
    - 第二轮评审 → accept → 闭环结束

退出码：0=闭环正确；1=任一环节失败（供 CI/手动检查）
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG
from agent.dag_reviewer import DagReviewerAgent
from agent.sub_goal_solver import SubGoalSolverAgent


# ============================================================
# Mock LLM 客户端：可编程剧情
# ============================================================
class MockClient:
    """按调用序号返回预设响应。记录调用历史供断言。"""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = []  # (index, message_text)
        self._idx = 0

    def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
        text = messages[-1]["content"] if messages else ""
        self.calls.append((self._idx, text))
        if self._idx >= len(self.script):
            # 脚本耗尽：返回一个明显可解析的兜底
            return self._fallback(text)
        resp = self.script[self._idx]
        self._idx += 1
        return resp

    def _fallback(self, text: str) -> str:
        # 兜底：给一个空 EJSON，让下游走保守路径（accept），不崩
        return '{"verdict": "accept", "quality_score": 0.5, "issues": [], "reconstruction_hint": ""}'


# ============================================================
# 剧情脚本
# ============================================================
# 剧情：题目「求所有满足条件的函数 f」——标准解需要分 case + 引理。
# 第一轮蓝图是错的：根节点只有一个子目标（粒度粗），且子目标 A 依赖自身（循环）。
BAD_BLUEPRINT = {
    "root_id": "g",
    "nodes": [
        {"id": "g", "kind": "and", "children": ["n1"], "statement": "求所有满足条件的函数 f", "status": "pending"},
        {"id": "n1", "kind": "or", "children": [], "statement": "猜一个解并验证", "status": "pending"},
    ],
    "edges": [("g", "n1")],
}

# 修正版蓝图：分 case（c=0 / c≠0）+ 引理节点，粒度细、无循环
GOOD_BLUEPRINT = {
    "root_id": "g",
    "nodes": [
        {"id": "g", "kind": "and", "children": ["lemma1", "case1", "case2"],
         "statement": "求所有满足条件的函数 f", "status": "pending"},
        {"id": "lemma1", "kind": "leaf", "children": [],
         "statement": "证明 f(0)=0 且 f 为奇函数（关键引理）", "status": "pending"},
        {"id": "case1", "kind": "or", "children": [],
         "statement": "case 1: 常数函数 f≡c，验证 c 的取值", "status": "pending"},
        {"id": "case2", "kind": "or", "children": [],
         "statement": "case 2: 非常数解 f(x)=kx+b，验证 k,b", "status": "pending"},
    ],
    "edges": [("g", "lemma1"), ("g", "case1"), ("g", "case2")],
}

# 评审脚本：第 1 次评审 reject（粒度粗 + 循环）→ 第 2 次评审 accept
REVIEW_BAD = json.dumps({
    "verdict": "reject",
    "quality_score": 0.2,
    "issues": [
        "子目标 n1 粒度过粗：'猜一个解并验证' 无法独立证明",
        "子目标 n1 存在循环风险：依赖自身",
        "缺少对 f(0) 取值的分情况讨论",
    ],
    "reconstruction_hint": "请将问题分解为：① 证明关键引理 f(0)=0；② 分常数/非常数两种 case 讨论；③ 每个 case 可独立验证",
}, ensure_ascii=False)

REVIEW_GOOD = json.dumps({
    "verdict": "accept",
    "quality_score": 0.85,
    "issues": [],
    "reconstruction_hint": "",
}, ensure_ascii=False)


def build_mock_script() -> list:
    """mock 剧情：评审(拒绝) → 重生成(修正) → 评审(通过)。"""
    return [REVIEW_BAD, json.dumps(GOOD_BLUEPRINT, ensure_ascii=False), REVIEW_GOOD]


# ============================================================
# 端到端验证
# ============================================================
def run_mock_smoke() -> bool:
    """mock 模式：验证闭环机制，不需要 API key。"""
    print("=" * 60)
    print("[mock] DAG 动态闭环冒烟（无真实 LLM）")
    print("=" * 60)

    cfg = _make_config()
    client = MockClient(build_mock_script())

    ctx = _make_ctx("mock")
    ctx.blueprint = BlueprintDAG.from_dict(BAD_BLUEPRINT)
    # 模拟子目标求解结果：失败信号（子目标没能得到有效结论）
    ctx.subgoal_trace.append({
        "id": "n1", "title": "猜一个解并验证",
        "description": "猜测并验证函数形式",
        "type": "deduction", "depends_on": [],
        "expected_output": "全部满足条件的函数",
        "result": "[子目标求解失败：粒度太粗，无法独立证明]",
    })

    reviewer = DagReviewerAgent(client, cfg)
    solver = SubGoalSolverAgent(client, cfg)

    # ---- Step 1: 首轮评审（期望 reject）----
    report1 = reviewer.review(ctx, ctx.blueprint, results_map={"n1": "[失败]"})
    print(f"\n[1] 首轮评审: reject={report1.reject_count}, "
          f"ratio={report1.reject_ratio:.2f}, "
          f"should_replan={report1.should_replan()}")
    if not report1.should_replan():
        print("  ✗ 失败：坏蓝图未被判为重生成")
        return False
    print("  ✓ 坏蓝图被正确判定为 should_replan")

    # ---- Step 2: 触发整树重生成（期望拿到修正版）----
    from agent.blueprint_planner import BlueprintPlannerAgent
    planner = BlueprintPlannerAgent(client, cfg)
    hints = report1.merge_from_hints()
    print(f"\n[2] 评审 hint 聚合: {hints[:60]}...")
    new_dag = planner.regenerate_with_feedback(
        ctx, prior_dag=ctx.blueprint, feedback_lines=hints.split("\n"))
    if new_dag is None:
        print("  ✗ 失败：整树重生成返回 None")
        return False
    print(f"  ✓ 重生成 DAG: {len(new_dag.nodes)} 节点, root={new_dag.root_id}")
    ok, err = new_dag.validate()
    if not ok:
        print(f"  ✗ 失败：新 DAG 校验不过: {err}")
        return False
    print("  ✓ 新 DAG 结构校验通过")

    # ---- Step 3: 重生成后再评审（期望 accept，闭环终止）----
    report2 = reviewer.review(ctx, new_dag, results_map={})
    print(f"\n[3] 二次评审: reject={report2.reject_count}, "
          f"should_replan={report2.should_replan()}")
    if report2.should_replan():
        print("  ✗ 失败：修正版蓝图仍被判为重生成（死循环风险）")
        return False
    print("  ✓ 修正版蓝图通过评审，闭环正常终止")

    # ---- Step 4: 断言修正版蓝图确实解决了原缺陷 ----
    stmts = {n["statement"] for n in new_dag.to_dict()["nodes"]}
    has_case = any("case" in s.lower() or "情况" in s for s in stmts)
    has_lemma = any("引理" in s or "f(0)" in s for s in stmts)
    if not (has_case and has_lemma):
        print(f"  ✗ 失败：修正版未包含 case/引理节点: {stmts}")
        return False
    print("  ✓ 修正版蓝图含分 case 与引理节点（对应原缺陷）")

    print("\n[mock] 全部通过：坏蓝图 → 评审拒绝 → 重生成修正 → 评审通过 → 终止")
    return True


def run_real_smoke() -> bool:
    """真实 LLM 模式：用 eval_dag/problems.jsonl 前 2 题验证闭环。"""
    import time
    from tools.leap_eval import make_client  # noqa: E402

    api_key = os.environ.get("INTERN_API_KEY", "")
    if not api_key:
        print("[real] 缺 INTERN_API_KEY，无法跑真实 LLM")
        print("[real] 提示：本地 key 已 401 失效（平台 Client 托管后），"
              "需要有效 key 才能跑本模式")
        return False

    print("=" * 60)
    print("[real] DAG 动态闭环真实 LLM 冒烟")
    print("=" * 60)
    client = make_client("intern")
    cfg = _make_config()
    bench_path = os.path.join(_ROOT, "eval_dag", "problems.jsonl")
    with open(bench_path, encoding="utf-8") as f:
        problems = [json.loads(ln) for ln in f if ln.strip()][:2]

    all_ok = True
    for p in problems:
        ctx = _make_ctx(p["id"])
        print(f"\n--- {p['id']} ---")
        # 蓝图生成
        from agent.blueprint_planner import BlueprintPlannerAgent
        planner = BlueprintPlannerAgent(client, cfg)
        dag = planner.generate_blueprint(ctx)
        if dag is None:
            print(f"  ✗ 蓝图生成失败: {p['id']}")
            all_ok = False
            continue
        print(f"  蓝图: {len(dag.nodes)} 节点")
        # 评审
        reviewer = DagReviewerAgent(client, cfg)
        report = reviewer.review(ctx, dag, results_map={})
        print(f"  评审: reject={report.reject_count}, "
              f"should_replan={report.should_replan()}")
        # 重生成（若判定）
        if report.should_replan():
            hints = report.merge_from_hints() or "请细化子目标、消除循环、保证可独立证明"
            new_dag = planner.regenerate_with_feedback(
                ctx, prior_dag=dag, feedback_lines=hints.split("\n"))
            if new_dag is None:
                print("  ✗ 重生成失败")
                all_ok = False
            else:
                print(f"  ✓ 重生成: {len(new_dag.nodes)} 节点")
        time.sleep(0.5)

    print(f"\n[real] 完成，all_ok={all_ok}")
    return all_ok


# ============================================================
# 工具
# ============================================================
def _make_config():
    from user_agent import AgentConfig
    cfg = AgentConfig()
    # 显式开启 DAG 相关开关（与生产配置一致）
    cfg.use_blueprint = True
    cfg.use_blueprint_dag = True
    cfg.enable_dag_replan = True
    cfg.dag_replan_max_rounds = 2
    return cfg


def _make_ctx(pid: str) -> TaskContext:
    return TaskContext(
        problem="求所有满足条件 f(x+y)=f(x)+f(y) 的函数 f: R→R（mock 题）",
        metadata={"problem_id": pid},
        domain="Algebra",
        budget=Budget(max_calls=500),
        start_time=0.0, deadline=0.0, total_start_time=0.0, total_deadline=0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="DAG 动态闭环冒烟")
    ap.add_argument("--real", action="store_true",
                    help="真实 LLM 模式（需有效 INTERN_API_KEY）")
    args = ap.parse_args()
    ok = run_real_smoke() if args.real else run_mock_smoke()
    print(f"\n退出码: {0 if ok else 1}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
