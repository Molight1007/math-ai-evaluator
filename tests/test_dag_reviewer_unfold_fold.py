# -*- coding: utf-8 -*-
"""
DagReviewer · unfold-fold 同义子目标回归测试（LEAP Figure 3 / §5.3）
====================================================================

**为什么需要这个测试**

LEAP 论文（arXiv:2606.03303v2）§5.3 / Figure 3 记录了一类**编译器查不出、
但会让 agent 无限分解到预算耗尽**的失败模式：

    把祖父目标的定义**展开（unfold）**创建一个新引理，
    又**折叠（fold）**回与父目标**语法同义**的陈述。

形式上是合法的 Lean 代码（所以编译器 accept），但分解没有任何推进。
论文消融（Putnam 2025 A5）：**去掉 LLM 评审器后跑 8 轮 rollout 仍失败；
有评审器时 2 轮成功** —— 评审器是这条路的唯一过滤器。

**本测试锁定什么**

MathPilot 的防线有两层，本测试**两层都锁**：

1. `_heuristic_screen` 的词袋 Jaccard（阈值 0.70）—— 抓**近逐字重述**；
2. `DagReviewerAgent` 的 LLM 评审 —— 抓**改写式**循环（换词不换义）。

⚠ 实测（2026-09-15）确认两层分工是必要的，不能只靠启发式：

    真实错题中的改写式 unfold-fold（换词、换表述）Jaccard 实测落在
    0.31 ~ 0.58 区间，**全部低于 0.70 阈值** ⇒ 启发式放行，必须靠 LLM 层拦。
    只有近逐字重述才会被启发式抓到（Jaccard ≈ 1.0）。

任一层的退化都会让坏分解静默通过 —— 这正是本回归测试要防的。

锚点：`agent/dag_reviewer.py`（_heuristic_screen / _llm_review_node）、
     `prompts/dag_review.py`（循环维度第 3 条明写 LEAP 5.3 该实例）
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.base import TaskContext, Budget
from agent.blueprint_planner import BlueprintDAG, BlueprintNode
from agent.dag_reviewer import (
    DagReviewerAgent, _token_overlap,
    CIRCULARITY_TOKEN_OVERLAP, MIN_STATEMENT_CHARS,
)


# ============================================================
# 测试脚手架
# ============================================================

def make_ctx(problem="证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除") -> TaskContext:
    return TaskContext(
        problem=problem,
        metadata={},
        budget=Budget(max_calls=50),
        start_time=0.0,
        deadline=999.0,
        total_start_time=0.0,
        total_deadline=9999.0,
    )


def make_config(**over):
    base = dict(
        use_blueprint_dag=True,
        enable_sketch_audit=False,
        use_leansearch=False,
        theorem_memory_enable=False,
        theorem_memory_path="",
        theorem_memory_top_k=5,
        dag_review_max_nodes=30,
        dag_review_reject_thr=0.40,
    )
    base.update(over)
    return SimpleNamespace(**base)


def make_mock_client(resp_map=None, default_resp=""):
    """mock LLM client：按 messages 末段内容查表返回，否则用 default。"""
    if resp_map is None:
        resp_map = {}
    client = MagicMock()

    def chat(messages, **kw):
        last_user = next((m["content"] for m in reversed(messages)
                          if m.get("role") == "user"), "")
        for key, val in resp_map.items():
            if key in last_user:
                return val
        return default_resp
    client.chat = chat
    return client


# 「展开定义」的中间节点默认陈述 —— 必须与 leaf **不同措辞**，
# 否则 p 与 leaf 的词袋相似度会虚高（实测 0.91），把启发式触发点
# 从"leaf vs 祖父"错误地转移到"leaf vs 父"。那是 fixture 造出来的假象。
DEFAULT_UNFOLD = "把目标改写为可由整除性分解的形式，待补全中间命题"


def make_unfold_fold_dag(grand_statement: str,
                         folded_statement: str,
                         unfolded_statement: str = "") -> BlueprintDAG:
    """构造「unfold 再 fold」形态的 DAG：

        g (AND, root) = 祖父目标
          └── p (AND) = 父目标 = "展开定义"这一步（措辞与 leaf 不同）
                └── leaf = 折叠回祖父陈述的"子目标"

    论文 Figure 3 的形态：leaf 与祖父 g 语法同义 ⇒ 分解零推进。

    ⚠ fixture 纪律：p 的陈述必须**独立于** folded_statement 书写。
    若把 folded 加个尾巴当 p（`folded + "（展开后）"`），
    p 与 leaf 的 Jaccard 会飙到 0.9+，启发式会因"与祖辈 p 相似"而触发 ——
    看起来测试通过，但验的是错的东西（真正该拦的是 leaf vs 祖父）。
    """
    nodes = {
        "g": BlueprintNode("g", "and", grand_statement, ["p"]),
        "p": BlueprintNode(
            "p", "and", unfolded_statement or DEFAULT_UNFOLD, ["leaf"]),
        # ★ 循环节点：折回祖父陈述
        "leaf": BlueprintNode("leaf", "and", folded_statement, []),
    }
    return BlueprintDAG(nodes=nodes, root_id="g")


REJECT_JSON = json.dumps({
    "verdict": "reject",
    "quality_score": 0.2,
    "issues": ["circular_risk:与祖辈目标语法同义，未真正简化"],
    "reconstruction_hint": "换一个真正推进证明的中间命题，不要展开再折回原陈述",
})

ACCEPT_JSON = json.dumps({
    "verdict": "accept",
    "quality_score": 0.9,
    "issues": [],
    "reconstruction_hint": "",
})


# ============================================================
# 第 1 层 · 启发式（近逐字重述）
# ============================================================

class TestHeuristicCatchesVerbatimFold(unittest.TestCase):
    """近逐字折回 → 词袋 Jaccard 超阈值 → 启发式直出 reject。"""

    def setUp(self):
        self.config = make_config()
        self.ctx = make_ctx()
        self.client = make_mock_client()
        self.agent = DagReviewerAgent(self.client, self.config)

    def test_identical_fold_is_rejected(self):
        """leaf 与祖父陈述完全相同 → 必须 reject（Figure 3 最极端形态）。

        这是 LEAP 论文点名的形态："fold 回 syntactically identical 的父目标陈述"。
        """
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        dag = make_unfold_fold_dag(grand, folded_statement=grand)

        results = self.agent._heuristic_screen(dag)
        self.assertIn("leaf", results,
                      "与祖父完全同义的子目标必须被启发式拦下")
        self.assertEqual(results["leaf"].verdict, "reject")
        self.assertTrue(any("circular_risk" in i for i in results["leaf"].issues),
                        f"issues 应含 circular_risk，实际 {results['leaf'].issues}")
        self.assertTrue(results["leaf"].heuristic_only,
                        "该节点应走启发式直出，不消耗 LLM")

    def test_near_verbatim_fold_is_rejected(self):
        """加个尾巴但语义不变（仅多"证明"二字）→ 仍须被拦。

        对应论文里"展开定义后折回"的常见写法：
        statement 措辞略有出入，但词袋几乎全同。
        """
        grand = "证明 x^3-3x+1 在区间 [0,1] 内恰有一个实根"
        folded = "证明 x^3-3x+1 在区间 [0,1] 内恰有一个实根。"  # 仅加句号
        dag = make_unfold_fold_dag(grand, folded_statement=folded)

        results = self.agent._heuristic_screen(dag)
        self.assertIn("leaf", results)
        self.assertEqual(results["leaf"].verdict, "reject")

    def test_realistic_paraphrase_escapes_heuristic(self):
        """★ 记录启发式的**已知边界**：改写式循环会漏网。

        实测（2026-09-15）：换词不换义的 unfold-fold，
        Jaccard 落在 0.31~0.58，**低于 0.70 阈值**。

        本测试把这个事实钉住 —— 不是为了"通过"，
        而是提醒：**启发式放行 ≠ 分解健康**，必须靠 LLM 层兜底。
        如果哪天有人调低阈值让这里变成"被抓到"，说明阈值语义变了，
        需要同步复核。

        对应真实错题：comb-032 / nt-031 等蓝图审查亮红灯但启发式未响。
        """
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        # 改写式折回：换词、换表述，但说的是同一件事
        folded = "说明 n(n+1)(n+2) 这个乘积含有因子 2 与因子 3 从而可被 6 整除"
        sim = _token_overlap(grand, folded)
        self.assertLess(sim, CIRCULARITY_TOKEN_OVERLAP,
                        f"改写式循环实测应低于阈值，实际 {sim:.3f}")

        dag = make_unfold_fold_dag(grand, folded_statement=folded)
        results = self.agent._heuristic_screen(dag)
        self.assertNotIn("leaf", results,
                         "改写式循环不该被启发式抓到（这是已知边界，交给 LLM 层）")


# ============================================================
# 第 2 层 · LLM 评审（改写式循环）
# ============================================================

class TestLLMReviewerCatchesParaphrasedFold(unittest.TestCase):
    """启发式漏网的改写式循环，必须由 LLM 评审拦下。"""

    def setUp(self):
        self.config = make_config()
        self.ctx = make_ctx()
        self.client = make_mock_client(default_resp=REJECT_JSON)
        self.agent = DagReviewerAgent(self.client, self.config)

    def test_llm_rejects_paraphrased_fold(self):
        """改写式折回 → LLM 返回 reject → 报告计入 reject。"""
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        folded = "说明 n(n+1)(n+2) 这个乘积含有因子 2 与因子 3 从而可被 6 整除"
        dag = make_unfold_fold_dag(grand, folded_statement=folded)

        # 直接验 _llm_review_node（不经 review 的降级/预算路径）
        res = self.agent._llm_review_node(self.ctx, dag, dag.nodes["leaf"], {})
        self.assertEqual(res.verdict, "reject")
        self.assertTrue(any("circular" in i.lower() for i in res.issues),
                        f"issues 应体现循环风险，实际 {res.issues}")
        self.assertFalse(res.heuristic_only, "该节点必须走了 LLM")

    def test_full_review_flow_surfaces_unfold_fold(self):
        """整图 review 流程：unfold-fold 节点出现在 rejected_nodes()。"""
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        folded = "说明 n(n+1)(n+2) 这个乘积含有因子 2 与因子 3 从而可被 6 整除"
        dag = make_unfold_fold_dag(grand, folded_statement=folded)

        report = self.agent.review(self.ctx, dag, results_map={})
        self.assertIn("leaf", report.rejected_nodes(),
                      "unfold-fold 节点必须出现在 reject 列表")
        self.assertGreaterEqual(report.reject_count, 1)

    def test_reconstruction_hint_returned(self):
        """reject 必须带回可用的 reconstruction_hint（供重写消费）。"""
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        dag = make_unfold_fold_dag(grand, folded_statement=grand)
        res = self.agent._llm_review_node(self.ctx, dag, dag.nodes["leaf"], {})
        self.assertEqual(res.verdict, "reject")
        self.assertTrue(res.reconstruction_hint.strip(),
                        "reject 必须给出 reconstruction_hint")


# ============================================================
# 健康对照组（防"全部 reject"式的过度拦截）
# ============================================================

class TestHealthyDecompositionNotOverRejected(unittest.TestCase):
    """真分解不能被误杀 —— 防止为了拦循环而把健康 DAG 全部拒掉。"""

    def setUp(self):
        self.config = make_config()
        self.ctx = make_ctx()
        self.client = make_mock_client(default_resp=ACCEPT_JSON)
        self.agent = DagReviewerAgent(self.client, self.config)

    def test_genuine_decomposition_passes(self):
        """真正的分解（引入新对象、新命题）→ 启发式不响、LLM accept。"""
        grand = "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除"
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and", grand, ["n1", "n2"]),
            "n1": BlueprintNode(
                "n1", "and", "证明连续三个整数中必有一个是偶数", []),
            "n2": BlueprintNode(
                "n2", "and", "证明连续三个整数中必有一个是 3 的倍数", []),
        }, root_id="g")

        # 启发式：不该命中
        hres = self.agent._heuristic_screen(dag)
        self.assertNotIn("n1", hres)
        self.assertNotIn("n2", hres)

        # LLM：accept
        report = self.agent.review(self.ctx, dag, results_map={})
        self.assertEqual(report.reject_count, 0,
                         f"真分解不该被拒，实际 {report.rejected_nodes()}")
        self.assertIn("n1", report.accepted_nodes())
        self.assertIn("n2", report.accepted_nodes())

    def test_short_statement_still_flagged(self):
        """粒度过粗（字数 < MIN_STATEMENT_CHARS）仍须被拦 —— 别修循环时弄丢这条。"""
        dag = BlueprintDAG(nodes={
            "g": BlueprintNode("g", "and",
                               "证明对任意正整数 n，n(n+1)(n+2) 能被 6 整除",
                               ["ok", "bad"]),
            "ok": BlueprintNode("ok", "and",
                                "证明连续三个整数中必有一个是偶数", []),
            "bad": BlueprintNode("bad", "and", "证", []),
        }, root_id="g")
        hres = self.agent._heuristic_screen(dag)
        self.assertIn("bad", hres)
        self.assertTrue(any("under_specified" in i for i in hres["bad"].issues))
        self.assertLess(len("证"), MIN_STATEMENT_CHARS)


if __name__ == "__main__":
    unittest.main()
