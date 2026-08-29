"""
BlueprintPlanner —— LEAP Stage 1：Blueprint DAG 分解（#27）
==============================================================

将数学问题分解为 AND-OR 有向无环图（DAG），作为子目标求解的依据：

- **AND 节点**：所有子节点都必须证明/求解（分解关系，取与）
- **OR 节点**：任一子节点证明成功即可（策略分支，取或）
- **叶子节点**：无子节点的原子子目标（"可直接证明"粒度）

与 SubGoalSolver 的关系：
- SubGoalSolver 原有流程：LLM 一步生成"有序子目标列表"（线性切块）
- 本模块：先由 LLM 生成 AND-OR DAG（依赖驱动分解），再转成
  SubGoalSolver 兼容的子目标序列（拓扑序 + 依赖关系）

设计参考：
- LEAP 论文（Po-Nien Kung et al. 2026）：Blueprint DAG 分解阶段
- 老师 8/26 要求 #27：依赖驱动的分解，而非简单切块

对外接口：
- BlueprintNode / BlueprintDAG：数据结构 + 校验 + 转换（纯逻辑，可单测）
- BlueprintPlannerAgent.generate_blueprint(ctx)：LLM 生成 DAG 并校验
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseAgent, TaskContext

try:
    from prompts.blueprint import (
        BLUEPRINT_DAG_SYSTEM,
        BLUEPRINT_DAG_USER_TEMPLATE,
    )
    from utils.prefill import prefill_messages, stitch
except ImportError:  # 提交包（submit/）路径兜底
    from submit.prompts.blueprint import (
        BLUEPRINT_DAG_SYSTEM,
        BLUEPRINT_DAG_USER_TEMPLATE,
    )
    from submit.utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot")

# 安全上限：单题 DAG 节点总数（LEAP 论文子目标规模通常 < 30）
MAX_DAG_NODES = 50


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BlueprintNode:
    """AND-OR DAG 中的单个节点。

    node_type: "and"（所有 children 都必须证）| "or"（任一 child 可证）
    children: 子节点 id 列表；空列表 = 叶子（原子子目标）
    """
    id: str
    node_type: str                      # "and" | "or"
    statement: str                      # 该节点的数学陈述（自然语言 / Lean 陈述）
    children: list = field(default_factory=list)
    rationale: str = ""                 # 分解依据（可选，用于 trace 与审查）


@dataclass
class BlueprintDAG:
    """AND-OR 蓝图：节点集合 + 根节点 + 合并策略。"""
    nodes: dict                          # id -> BlueprintNode
    root_id: str
    merge_strategy: str = ""
    problem_analysis: dict = field(default_factory=dict)

    # ---------------- 校验 ----------------
    def validate(self) -> tuple[bool, list[str]]:
        """校验 DAG 合法性。返回 (是否合法, 错误列表)。"""
        errors = []
        if not self.nodes:
            return False, ["DAG 为空"]
        if self.root_id not in self.nodes:
            errors.append(f"根节点 {self.root_id} 不存在")
        if len(self.nodes) > MAX_DAG_NODES:
            errors.append(f"节点数 {len(self.nodes)} 超过上限 {MAX_DAG_NODES}")
        for nid, node in self.nodes.items():
            if node.node_type not in ("and", "or"):
                errors.append(f"节点 {nid} 类型非法: {node.node_type}")
            if not node.statement.strip():
                errors.append(f"节点 {nid} 缺少 statement")
            for c in node.children:
                if c not in self.nodes:
                    errors.append(f"节点 {nid} 的子节点 {c} 不存在（悬空引用）")
        # 无环检测（DFS）
        if self.root_id in self.nodes:
            cycle = self._find_cycle()
            if cycle:
                errors.append(f"DAG 存在环: {' -> '.join(cycle)}")
        return (not errors), errors

    def _find_cycle(self) -> Optional[list]:
        """DFS 检测环，返回环路径（无环返回 None）。"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        stack_trace = []

        def dfs(nid):
            color[nid] = GRAY
            stack_trace.append(nid)
            for c in self.nodes[nid].children:
                if c not in self.nodes:
                    continue  # 悬空引用已在 validate 前面报告
                if color[c] == GRAY:
                    idx = stack_trace.index(c)
                    return stack_trace[idx:] + [c]
                if color[c] == WHITE:
                    cycle = dfs(c)
                    if cycle:
                        return cycle
            stack_trace.pop()
            color[nid] = BLACK
            return None

        for nid in self.nodes:
            if color[nid] == WHITE:
                cycle = dfs(nid)
                if cycle:
                    return cycle
        return None

    # ---------------- 转子目标 ----------------
    def to_subgoal_plan(self) -> dict:
        """把 DAG 转成 SubGoalSolver 兼容的子目标规划。

        规则：
        - AND 节点 → 展开所有 children（全部必须求解）
        - OR 节点 → 取第一个可证 child（策略分支，先尝试主分支）
        - 叶子节点 → 作为原子子目标
        - 输出按拓扑序排列，depends_on 依据 DAG 父子关系
        """
        if not self.nodes:
            return {"problem_analysis": {}, "subgoals": [], "merge_strategy": ""}

        # 1) 展开：从根出发，收集需要求解的叶子（AND 全展开，OR 取第一个分支）
        selected: set = set()      # 被选中的叶子节点 id
        expanded: set = set()      # 已展开的非叶节点 id（防重复）
        order: list = []           # 展开顺序（用于稳定拓扑）

        def expand(nid: str) -> None:
            node = self.nodes[nid]
            if nid in expanded:
                return
            expanded.add(nid)
            if not node.children:
                if nid not in selected:
                    selected.add(nid)
                    order.append(nid)
                return
            if node.node_type == "and":
                for c in node.children:
                    expand(c)
            else:  # or：取第一个 child（主策略分支）
                expand(node.children[0])

        if self.root_id in self.nodes:
            expand(self.root_id)

        # 2) 构造子目标：拓扑序（父先于子）
        #    用展开顺序近似：expand 是前序 DFS，父节点先于子节点被访问。
        #    子目标按 order 排列即满足"依赖在前"。
        subgoals = []
        for idx, nid in enumerate(order, 1):
            node = self.nodes[nid]
            # 依赖：该叶子在 DAG 中的祖先（已展开且在 order 中排在前面）
            deps = self._ancestors(nid) & selected
            deps = [order.index(d) + 1 for d in order if d in deps]
            subgoals.append({
                "id": idx,
                "title": f"子目标{idx}: {self._short(node.statement)}",
                "description": node.statement,
                "type": self._infer_type(node.statement),
                "depends_on": deps,
                "expected_output": "",
                "result": "",
            })
        return {
            "problem_analysis": self.problem_analysis,
            "subgoals": subgoals,
            "merge_strategy": self.merge_strategy,
        }

    def _ancestors(self, nid: str) -> set:
        """返回 nid 的所有祖先节点 id。"""
        parents = {}
        for pid, node in self.nodes.items():
            for c in node.children:
                parents.setdefault(c, []).append(pid)
        result, stack = set(), list(parents.get(nid, []))
        while stack:
            p = stack.pop()
            if p in result:
                continue
            result.add(p)
            stack.extend(parents.get(p, []))
        return result

    @staticmethod
    def _short(text: str, limit: int = 40) -> str:
        t = " ".join(text.split())
        return t if len(t) <= limit else t[:limit] + "…"

    @staticmethod
    def _infer_type(statement: str) -> str:
        """根据陈述措辞推断子目标类型（compute/prove/derive/verify）。"""
        s = statement.lower()
        if any(k in s for k in ("证明", "prove", "show that", "theorem", "证得")):
            return "prove"
        if any(k in s for k in ("计算", "compute", "求值", "solve", "化简", "calculate")):
            return "compute"
        if any(k in s for k in ("推导", "derive", "推出", "化简得")):
            return "derive"
        if any(k in s for k in ("验证", "verify", "检验", "检查")):
            return "verify"
        return "compute"

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return {
            "root_id": self.root_id,
            "merge_strategy": self.merge_strategy,
            "problem_analysis": self.problem_analysis,
            "nodes": [
                {"id": n.id, "type": n.node_type, "statement": n.statement,
                 "children": n.children, "rationale": n.rationale}
                for n in self.nodes.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlueprintDAG":
        nodes = {}
        for nd in data.get("nodes", []):
            nodes[nd["id"]] = BlueprintNode(
                id=nd["id"],
                node_type=nd.get("type", nd.get("node_type", "and")),
                statement=nd.get("statement", nd.get("description", "")),
                children=list(nd.get("children", [])),
                rationale=nd.get("rationale", ""),
            )
        return cls(
            nodes=nodes,
            root_id=data.get("root_id", data.get("root", "")),
            merge_strategy=data.get("merge_strategy", ""),
            problem_analysis=data.get("problem_analysis", {}),
        )


# ============================================================
# JSON 提取（与 SubGoalSolverAgent 同款平衡括号算法）
# ============================================================

def extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON 对象（平衡括号匹配，防 LaTeX 花括号干扰）。

    增强容错：
    - 优先 ```json 代码块
    - 逐 { 平衡括号匹配
    - 失败后兜底：取全文中最长的一段可解析 JSON（处理夹杂说明文字的场景）
    """
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    def _try_parse(candidate: str):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
            except json.JSONDecodeError:
                return None

    best, best_len = None, 0
    # 关键改动（2026-08-28）：不再「命中第一个平衡片段就返回」。
    # 实测 Intern 会输出形如
    #   {"domain": "...", "key_constraints": [...]}, "root_id": "g", "nodes": [...]
    # 这种把嵌套字段摊平、并提前闭合花括号的内容——此时第一个平衡片段
    # 只是前面那段元数据碎片，root_id / nodes 全被丢掉，
    # 表现为「Blueprint: DAG 结构非法」。改为收集全部候选并取最长者：
    # 完整 DAG 的长度远大于任何前言碎片，这样能把正确主体捞回来。
    best_parsed, best_parsed_len = None, 0
    for i, c in enumerate(text):
        if c != '{':
            continue
        depth, j, in_str, esc = 1, i + 1, False, False
        while j < len(text):
            ch = text[j]
            if esc:
                esc = False
            elif in_str and ch == '\\':
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        parsed = _try_parse(text[i:j + 1])
                        if parsed is not None and (j - i) > best_parsed_len:
                            best_parsed, best_parsed_len = parsed, j - i
                        elif parsed is None and (j - i) > best_len:
                            # 解析失败也记录最长候选（兜底用）
                            best, best_len = text[i:j + 1], j - i
                        break
            j += 1
    if best_parsed is not None:
        return best_parsed
    # 兜底：最长候选 + 容错（去注释/去多余逗号后重试）
    if best:
        cleaned = re.sub(r"//[^\n]*", "", best)
        parsed = _try_parse(cleaned)
        if parsed is not None:
            return parsed
    return None


def parse_blueprint(raw: dict) -> Optional[BlueprintDAG]:
    """从 LLM 输出 dict 构造 BlueprintDAG（宽容字段名），非法返回 None。

    兼容的字段名：
    - root: root / root_id / root_node
    - nodes: nodes / blueprint / dag / subgoals / children_map
    - 节点 type: type / kind / node_type；children: children / deps / subgoals / child_ids
    """
    if not isinstance(raw, dict):
        return None
    root_id = str(raw.get("root_id", raw.get("root",
                  raw.get("root_node", ""))) or "")
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list):
        for k in ("blueprint", "dag", "subgoals", "children_map"):
            v = raw.get(k)
            if isinstance(v, list) and v:
                nodes_raw = v
                break
    if not isinstance(nodes_raw, list) or not nodes_raw:
        return None

    nodes = {}
    for nd in nodes_raw:
        if not isinstance(nd, dict):
            continue
        nid = str(nd.get("id", nd.get("node_id", nd.get("name", ""))) or "")
        if not nid:
            continue
        ntype = str(nd.get("type", nd.get("kind",
                    nd.get("node_type", "and")))).lower()
        if ntype not in ("and", "or"):
            ntype = "and"
        statement = str(nd.get("statement",
                       nd.get("description",
                       nd.get("task", nd.get("content", "")))))
        children = nd.get("children", nd.get("deps",
                    nd.get("subgoals", nd.get("child_ids", []))))
        if not isinstance(children, list):
            children = []
        children = [str(c) for c in children]
        nodes[nid] = BlueprintNode(
            id=nid,
            node_type=ntype,
            statement=statement,
            children=children,
            rationale=str(nd.get("rationale", nd.get("reason", ""))),
        )
    if not nodes:
        return None
    if not root_id:
        # 兜底：取"根"特征——没有被任何节点引用的节点；多个则取第一个
        referenced = {c for n in nodes.values() for c in n.children}
        candidates = [nid for nid in nodes if nid not in referenced]
        root_id = candidates[0] if candidates else next(iter(nodes))

    return BlueprintDAG(
        nodes=nodes,
        root_id=root_id,
        merge_strategy=str(raw.get("merge_strategy", "")),
        problem_analysis=raw.get("problem_analysis", {}),
    )


# ============================================================
# BlueprintPlannerAgent
# ============================================================

class BlueprintPlannerAgent(BaseAgent):
    """LEAP Stage 1：生成并校验 Blueprint DAG（#27）。"""

    name = "BlueprintPlanner"

    def run(self, ctx: TaskContext) -> TaskContext:
        """生成 Blueprint DAG 并转为子目标规划（写入 ctx.blueprint_plan）。

        作为独立 Agent 被调用时使用；SubGoalSolver 内部直接调
        generate_blueprint() 更高效（避免重复实例化）。
        """
        dag = self.generate_blueprint(ctx)
        if dag is not None:
            ctx.blueprint_plan = dag.to_subgoal_plan()
            self.record(ctx, "blueprint",
                        f"Blueprint DAG → {len(ctx.blueprint_plan['subgoals'])} 个子目标")
        return ctx

    def generate_blueprint(self, ctx: TaskContext,
                           max_attempts: int = 3) -> Optional[BlueprintDAG]:
        """调用 LLM 生成 AND-OR DAG 并校验；成功返回 DAG，失败返回 None。

        结果同时写入 ctx.blueprint（dict 序列化），供后续阶段消费。
        """
        # 预算闸门
        if ctx.budget is not None and not ctx.budget.can_spend(1):
            self.record(ctx, "blueprint", "预算耗尽，跳过蓝图生成")
            return None

        problem_text = ctx.problem
        if getattr(ctx, "formal_spec", ""):
            problem_text = (ctx.problem + "\n\n[题目的形式化理解（已知条件→结论）]\n"
                            + ctx.formal_spec)
        gaps = getattr(ctx, "formal_gaps", [])
        if gaps:
            gap_lines = "\n".join(
                "  - [%s] %s: %s" % (g.get("kind", "other"), g.get("detail", ""),
                                     g.get("suggestion", ""))
                for g in gaps)
            problem_text = (problem_text
                            + "\n\n[Lean 形式化验证发现的缺口（建议优先作为 DAG 子目标）]\n"
                            + gap_lines)
        # #31 leansearch：检索定理注入蓝图生成提示
        if getattr(self.config, "use_leansearch", False):
            sr = self._search_mathlib_theorems(ctx, problem_text)
            if sr and sr.get("status") == "ok" and sr.get("results"):
                th_lines = "\n".join(
                    "  - %s (%s): %s" % (r["name"], r.get("kind", "?"),
                                         (r.get("snippet", "") or "")[:120])
                    for r in sr["results"])
                problem_text = (problem_text
                                + "\n\n[检索到的相关 Mathlib 定理（供 DAG 节点证明参考）]\n"
                                + th_lines)

        # 跨题定理记忆注入（2026-08-29）：本域"编译验证通过"的高频定理，
        # 跳过重复检索/翻译试错——复用性高的定理直接可用。
        if getattr(self.config, "theorem_memory_enable", True):
            known = self._known_domain_theorems(ctx)
            if known:
                problem_text = (problem_text
                                + "\n\n[本域已验证可用的 Mathlib 定理"
                                  "（可直接引用，勿重复检索）]\n"
                                + "\n".join(f"  - {t}" for t in known))

        user_msg = BLUEPRINT_DAG_USER_TEMPLATE.format(problem=problem_text)
        last_resp = None
        # prefill 种子前缀必须**锚定到顶层包装**，不能只用 '{"'。
        # 实测两种失败形态：
        #   1) 无 prefill：Intern 先吐长思维块吃满 token，JSON 被腰斩
        #      → 「Blueprint: JSON 解析失败」（eval_A 0/3 的原始根因）
        #   2) 仅用 '{"'：模型认为已进入对象内部，直接吐 nodes 数组的元素，
        #      丢掉 root_id / nodes 外层包装 → 「Blueprint: DAG 结构非法」
        # 锚定到 `{"root_id": "g", "nodes": [` 后，模型会接着写节点数组，
        # 结构完整（实测 13 节点、validate 零错误）。
        _PREFILL = '{"root_id": "g", "nodes": ['
        for attempt in range(max_attempts):
            # 必须用 prefill：Intern 系列无短种子时会先输出长思维块，
            # 把 token 预算吃满后 JSON 被腰斩（finish_reason=length），
            # 表现为「Blueprint: JSON 解析失败」重试 3 次全败——这是 eval_A 0/3 的根因。
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": BLUEPRINT_DAG_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    _PREFILL,
                ),
                0.2, 6144,
            )
            if resp:
                resp = stitch(_PREFILL, resp)
                last_resp = resp
            if not resp:
                continue
            raw = extract_json(resp)
            if raw is None:
                logger.warning("Blueprint: JSON 解析失败 (attempt %d)", attempt + 1)
                continue
            dag = parse_blueprint(raw)
            if dag is None:
                logger.warning("Blueprint: DAG 结构非法 (attempt %d)", attempt + 1)
                continue
            ok, errors = dag.validate()
            if not ok:
                logger.warning("Blueprint: 校验失败 (attempt %d): %s",
                               attempt + 1, "; ".join(errors[:5]))
                # 记录错误供 trace，然后重试
                self.record(ctx, "blueprint",
                            f"DAG 校验失败: {'; '.join(errors[:5])}")
                continue
            # 成功：写入 ctx.blueprint
            ctx.blueprint = dag.to_dict()
            self.record(ctx, "blueprint",
                        f"Blueprint DAG 生成成功: {len(dag.nodes)} 节点, "
                        f"根={dag.root_id}")
            return dag

        self.record(ctx, "blueprint",
                    f"蓝图生成 {max_attempts} 次尝试均失败; "
                    f"最后响应片段: {(last_resp or '<None>')[:200]}")
        return None

    # ---- leansearch 复用（与 SubGoalSolverAgent 同款懒加载）----
    def _get_mathlib_searcher(self):
        if getattr(self, "_mathlib_searcher", None) is None:
            try:
                from .lean_search import MathlibTheoremSearcher
                self._mathlib_searcher = MathlibTheoremSearcher()
            except Exception as e:  # noqa: BLE001
                logger.warning("MathlibTheoremSearcher 初始化失败: %s", e)
                self._mathlib_searcher = False
        return self._mathlib_searcher or None

    def _known_domain_theorems(self, ctx: TaskContext) -> list[str]:
        """读取本域高频"已验证可用"定理（跨题定理记忆，供 DAG 生成复用）。"""
        try:
            from .theorem_memory import TheoremMemory
            mem = TheoremMemory(
                str(getattr(self.config, "theorem_memory_path", "")))
            top_k = int(getattr(self.config, "theorem_memory_top_k", 5))
            return mem.top_theorems(ctx.domain or "", k=top_k)
        except Exception:  # noqa: BLE001
            return []

    def _search_mathlib_theorems(self, ctx: TaskContext, query: str, limit: int = 5):
        searcher = self._get_mathlib_searcher()
        if searcher is None:
            return None
        self.note_mathlib_search(ctx)
        try:
            sr = searcher.search(query, limit=limit)
            # 记录实际命中的定理名（#1/#2 证据链：AI 用了哪些 Mathlib 定理）
            if sr and sr.get("results"):
                self.add_used_theorems(
                    ctx, [r["name"] for r in sr["results"]])
            return sr
        except Exception as e:  # noqa: BLE001
            logger.warning("Mathlib 定理检索失败: %s", e)
            return None
