"""
LeanRefinerAgent —— LEAP Stage 3：迭代精炼（#29/#32/#33）
============================================================

对 Blueprint DAG 整树翻译（LeanTranslatorAgent 产物）中的每个 ``sorry``
做迭代补全：

1. 定位未完成叶子（sketch_tree.per_node 里 translation 成功但证明缺失的节点）
2. LLM 生成证明（注入：题目陈述 + 该叶子 Lean 声明 + 已证引理（LemmaMemory）
   + 检索到的 Mathlib 定理（leansearch）+ 引导直接调用 Mathlib tactic）
3. ``lake env lean`` 编译：成功 → 该节点标记 done；失败 → 编译错误回填，
   带反馈重试（有限轮）；重试耗尽 → OR 分支回溯（切换到 DAG 中该节点的
   兄弟 OR 策略），重新翻译+补全
4. 输出：per_node 状态 + 最终 lean_code（尽量少 sorry）+ 统计

对应老师要求：
- #29 子目标→子智能体（动态创建+回溯）：每个叶子一个精炼子任务；OR 分支失败回溯
- #32 推理闭环：搜定理→informal 推理→翻译 Lean→Lean 审核
- #33 AI 主动用 Mathlib：提示词引导 norm_num/ring/omega/linarith 等 tactic
- #30 lemma 记忆：已证叶子入 LemmaMemory，供后续节点引用
"""

import json
import logging
import os
import re
import time

from .base import BaseAgent, TaskContext
from .blueprint_planner import BlueprintDAG, extract_json
from .lemma_memory import LemmaMemory

logger = logging.getLogger("MathPilot")

# 单节点补全最大重试轮数（每次重试 1 次 LLM 调用 + 1 次编译）
MAX_REFINE_ATTEMPTS = 3
# 整题精炼 LLM 调用预算上限（防止成本失控，对应计划"单题硬上限"）
MAX_REFINE_LLM_CALLS = 1500


def extract_sorry_blocks(lean_code: str) -> list:
    """提取 Lean 代码中每个定理声明的 sorry 占位（用于定位待补全点）。

    返回 [{theorem, statement}]：每个含 sorry 的 theorem 名。
    """
    if not lean_code:
        return []
    names = re.findall(r"^(?:theorem|lemma)\s+(\w+)[\s\S]*?by\s*\n?\s*sorry", lean_code, re.MULTILINE)
    return [{"theorem": n} for n in names]


def strip_sorry_block(lean_code: str, theorem: str) -> str:
    """移除指定定理的完整声明（从 theorem 行到其 by sorry 结尾），返回剩余代码。"""
    if not lean_code:
        return lean_code
    pattern = re.compile(
        r"^(?:theorem|lemma)\s+%s[\s\S]*?by\s*\n?\s*sorry\s*\n?" % re.escape(theorem),
        re.MULTILINE)
    return pattern.sub("", lean_code)


def replace_sorry_with_proof(lean_code: str, theorem: str, proof: str) -> str:
    """把指定定理的 ``by sorry`` 替换为 LLM 给出的证明体。"""
    if not lean_code:
        return lean_code
    proof = (proof or "").strip()
    # 去掉可能的代码围栏与多余换行
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", proof)
    if m:
        proof = m.group(1).strip()
    # 若 LLM 返回了完整定理声明，只取其证明体
    m2 = re.match(r"^.*?:= by\s*([\s\S]+)$", proof, re.DOTALL)
    if m2:
        proof = m2.group(1).strip()
    # 替换 "by\n  sorry"（兼容 "by sorry" / "by\n  sorry" / ":= by\n  sorry"）
    pattern = re.compile(
        r"((?:theorem|lemma)\s+%s[\s\S]*?:=\s*)\n?\s*by\s*\n?\s*sorry" % re.escape(theorem),
        re.MULTILINE)
    if not pattern.search(lean_code):
        return lean_code
    indent = "  "
    body = "\n".join(indent + line if line.strip() else line
                     for line in proof.splitlines())
    return pattern.sub(lambda m: m.group(1) + "by\n" + body, lean_code)


class LeanRefinerAgent(BaseAgent):
    """LEAP Stage 3：sorry 迭代补全 + OR 分支回溯。"""

    name = "LeanRefiner"

    def __init__(self, client, config):
        super().__init__(client, config)
        self._bridge = None
        self.memory = LemmaMemory(
            storage_path=str(getattr(config, "lemma_storage_path", "")))
        self._llm_calls = 0

    # ------------------------------------------------------------------
    # 编译
    # ------------------------------------------------------------------
    def _bridge_inst(self, ctx: TaskContext):
        try:
            from .lean_bridge import LeanBridge
            return LeanBridge(self.client, self.config, ctx.budget)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanRefiner: LeanBridge 构造失败: %s", e)
            return None

    def _compile_code(self, ctx: TaskContext, lean_code: str,
                      allow_sorry: bool = True) -> dict:
        """编译 Lean 代码（默认 import Mathlib；allow_sorry 控制是否允许 sorry）。"""
        from .lean_translator import _prepend_mathlib_import
        bridge = self._bridge_inst(ctx)
        if bridge is None:
            return {"ok": False, "error": "LeanBridge 初始化失败"}
        code = _prepend_mathlib_import(lean_code)
        try:
            project_dir = bridge._lean_project_dir
            use_mathlib = bridge._mathlib_ready()
            code = _prepend_mathlib_import(code) if use_mathlib else code
            if project_dir:
                lean_file = "refine_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = bridge._compile(code, project_dir,
                                       lean_filename=lean_file, allow_sorry=allow_sorry)
                try:
                    os.remove(os.path.join(project_dir, lean_file))
                except OSError:
                    pass
                return comp
            import tempfile
            from .lean_bridge import _compile_lean
            with tempfile.TemporaryDirectory(prefix="lean_refine_") as work_dir:
                return _compile_lean(
                    code, work_dir, lean_executable=bridge._lean_executable,
                    timeout=float(getattr(self.config, "preverify_timeout", 60.0) or 60.0),
                    allow_sorry=allow_sorry)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanRefiner: 编译异常: %s", e)
            return {"ok": False, "error": str(e)[:200]}

    # ------------------------------------------------------------------
    # 单节点补全
    # ------------------------------------------------------------------
    def _prompt_refine(self, ctx: TaskContext, theorem: str,
                       statement: str, problem: str, error_feedback: str,
                       lemma_block: str, theorem_block: str) -> str:
        """调用 LLM 生成证明（返回证明体文本；失败返回空串）。"""
        if self._llm_calls >= MAX_REFINE_LLM_CALLS:
            return ""
        try:
            from prompts.lean_refiner import (
                LEAN_REFINE_SYSTEM, LEAN_REFINE_USER_TEMPLATE)
        except ImportError:
            from submit.prompts.lean_refiner import (
                LEAN_REFINE_SYSTEM, LEAN_REFINE_USER_TEMPLATE)
        user_msg = LEAN_REFINE_USER_TEMPLATE.format(
            problem=problem, theorem=theorem, statement=statement,
            lemma_block=lemma_block, theorem_block=theorem_block,
            error_feedback=error_feedback)
        raw = self.llm(
            ctx,
            [
                {"role": "system", "content": LEAN_REFINE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.2, 2048,
        )
        self._llm_calls += 1
        if not raw:
            return ""
        # 尝试解析 JSON（lean_proof 字段）；否则整段当证明体
        parsed = extract_json(raw)
        if parsed:
            proof = str(parsed.get("lean_proof", parsed.get("proof", "")) or "")
            if proof:
                return proof.strip()
        return raw.strip()

    def refine_one(self, ctx: TaskContext, theorem: str,
                   statement: str, lean_code: str, problem: str = "") -> dict:
        """迭代补全单个 theorem 的 sorry。返回 {ok, lean_code, attempts, error}。

        每轮从**原始带 sorry 的代码**出发（编译失败不保留失败产物），
        用错误反馈驱动 LLM 修正，保证每轮都能定位到 sorry 块。
        """
        lemma_block = self.memory.format_for_prompt(limit=8)
        # #31 leansearch：检索相关 Mathlib 定理注入补全提示
        theorem_block = ""
        if getattr(self.config, "use_leansearch", False):
            sr = self._search_mathlib(ctx, statement + " " + problem)
            if sr and sr.get("results"):
                theorem_block = "\n".join(
                    "  - %s (%s): %s" % (r["name"], r.get("kind", "?"),
                                         (r.get("snippet", "") or "")[:120])
                    for r in sr["results"])

        base_code = lean_code
        error_feedback = ""
        for attempt in range(MAX_REFINE_ATTEMPTS):
            proof = self._prompt_refine(
                ctx, theorem, statement, problem, error_feedback,
                lemma_block, theorem_block)
            if not proof:
                return {"ok": False, "lean_code": base_code,
                        "attempts": attempt + 1, "error": "LLM 未返回证明"}
            new_code = replace_sorry_with_proof(base_code, theorem, proof)
            if new_code == base_code:
                return {"ok": False, "lean_code": base_code,
                        "attempts": attempt + 1, "error": "无法定位 sorry 块"}
            # allow_sorry 必须显式传 False：_compile_code 的默认值是 True，
            # 沿用默认值时模型回一句 `by sorry` 也会被判"编译通过"，
            # 整个 Stage 3 精炼判定形同虚设（与 leap_eval.py 对照组口径一致）。
            comp = self._compile_code(ctx, new_code, allow_sorry=False)
            if comp.get("ok"):
                return {"ok": True, "lean_code": new_code,
                        "attempts": attempt + 1, "error": ""}
            error_feedback = comp.get("error", "编译失败")[:1500]
        return {"ok": False, "lean_code": base_code,
                "attempts": MAX_REFINE_ATTEMPTS,
                "error": error_feedback or "编译未通过"}

    # ------------------------------------------------------------------
    # 整树精炼（含 OR 分支回溯）
    # ------------------------------------------------------------------
    def refine_tree(self, ctx: TaskContext, dag: BlueprintDAG,
                    sketch_tree: dict) -> dict:
        """对整树做迭代精炼。

        对每个待补全叶子：先主分支（DAG OR 节点的第一个 child）精炼，
        失败后切换到 OR 兄弟分支（重新翻译+补全）。
        """
        result = {
            "verdict": "unknown", "per_node": {}, "lean_code": "",
            "done": 0, "failed": 0, "llm_calls": 0, "backtracks": 0,
        }
        leaf_code = sketch_tree.get("lean_code", "")
        if not leaf_code:
            result["error"] = "无整树 Lean 代码（先执行 Stage 2 搭桥）"
            return result

        # 叶子节点（翻译成功、含 sorry 的）
        leaves = [n for n in dag.nodes.values() if not n.children]
        pending = []
        for leaf in leaves:
            pn = (sketch_tree.get("per_node") or {}).get(leaf.id, {})
            if pn.get("ok") and pn.get("declaration"):
                pending.append(leaf)

        result["lean_code"] = leaf_code
        for leaf in pending:
            theorem = "node_" + re.sub(r"[^0-9A-Za-z_]", "_", str(leaf.id)).strip("_")
            status = self._refine_with_backtrack(
                ctx, dag, leaf, theorem, result, pending)
            result["per_node"][leaf.id] = status
            if status.get("ok"):
                result["done"] += 1
            else:
                result["failed"] += 1

        result["llm_calls"] = self._llm_calls
        result["verdict"] = ("ok" if result["failed"] == 0
                             else "partial" if result["done"] > 0 else "fail")
        return result

    def _refine_with_backtrack(self, ctx, dag, leaf, theorem, result, pending):
        """单叶子精炼，含 OR 分支回溯。"""
        # 找该叶子的 OR 祖先分支（若叶子属于 OR 节点，可回溯到兄弟分支）
        or_siblings = self._find_or_siblings(dag, leaf.id)
        candidates = [leaf.id] + [s for s in or_siblings if s != leaf.id]

        for idx, node_id in enumerate(candidates):
            node = dag.nodes[node_id]
            decl = self._build_decl_for_node(node_id, node.statement)
            if not decl:
                continue
            if idx > 0:
                result["backtracks"] += 1
                self.record(ctx, "lean_refiner",
                            f"OR 回溯: 叶子 {leaf.id} → 分支 {node_id}")
            # 用一个精简代码（只含该节点声明）精炼
            r = self.refine_one(ctx, "node_" + re.sub(r"[^0-9A-Za-z_]", "_", str(node_id)).strip("_"),
                                node.statement, decl + "\n", ctx.problem)
            if r.get("ok"):
                # 成功后入 lemma 记忆（#30）
                self.memory.add(
                    "node_" + re.sub(r"[^0-9A-Za-z_]", "_", str(node_id)).strip("_"),
                    node.statement, proof="lean_proof", source="refiner")
                self.record(ctx, "lean_refiner",
                            f"叶子 {node_id} 补全成功（第 {idx + 1} 个候选分支）")
                return {"ok": True, "node_id": node_id,
                        "attempts": r.get("attempts", 0), "error": ""}
        return {"ok": False, "node_id": leaf.id,
                "attempts": 0, "error": "所有候选分支精炼失败"}

    def _build_decl_for_node(self, node_id: str, statement: str) -> str:
        """为节点构造可精炼的 Lean 声明（复用 translator 的直包逻辑）。"""
        from .lean_translator import build_declaration
        decl = build_declaration(node_id, statement)
        if decl:
            return decl
        return "theorem node_%s : True := by\n  sorry" % re.sub(
            r"[^0-9A-Za-z_]", "_", str(node_id)).strip("_")

    def _find_or_siblings(self, dag: BlueprintDAG, leaf_id: str) -> list:
        """找到包含 leaf 的 OR 节点的所有兄弟分支（不含 leaf 自身所属路径）。"""
        siblings = []
        for node in dag.nodes.values():
            if node.node_type == "or" and leaf_id in node.children:
                siblings.extend(node.children)
        # 去重、保持顺序
        seen, out = set(), []
        for s in siblings:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    # ------------------------------------------------------------------
    # leansearch（#31）
    # ------------------------------------------------------------------
    def _search_mathlib(self, ctx: TaskContext, query: str, limit: int = 5):
        try:
            from .lean_search import MathlibTheoremSearcher
            if getattr(self, "_searcher", None) is None:
                self._searcher = MathlibTheoremSearcher()
            return self._searcher.search(query, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.warning("Mathlib 定理检索失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext) -> TaskContext:
        """从 ctx.blueprint + ctx.sketch_tree 执行 Stage 3 精炼，写 ctx.refine_result。"""
        if not ctx.blueprint or not ctx.sketch_tree:
            ctx.refine_result = {"verdict": "unknown",
                                 "error": "缺少 blueprint 或 sketch_tree"}
            return ctx
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            ctx.refine_result = {"verdict": "unknown", "error": "预算不足"}
            return ctx
        try:
            dag = BlueprintDAG.from_dict(ctx.blueprint)
        except Exception as e:  # noqa: BLE001
            ctx.refine_result = {"verdict": "unknown", "error": str(e)[:200]}
            return ctx
        self.memory.import_from_ctx(ctx)
        result = self.refine_tree(ctx, dag, ctx.sketch_tree)
        self.memory.export_to_ctx(ctx)
        ctx.refine_result = result
        self.record(ctx, "lean_refiner",
                    f"Stage3 精炼: verdict={result.get('verdict')}; "
                    f"done={result.get('done')}, failed={result.get('failed')}, "
                    f"回溯={result.get('backtracks')}, LLM={result.get('llm_calls')}")
        return ctx
