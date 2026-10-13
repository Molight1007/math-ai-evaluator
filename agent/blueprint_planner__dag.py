"""BlueprintPlanner 的 DAG 数据结构与图算法（自 blueprint_planner.py 逐字搬出）。

2026-10-08 批 D-bp1：`agent/blueprint_planner.py` 超过 800 行上限，本模块承载其
**纯逻辑**簇（LEAP Stage 1 的 AND-OR DAG：节点/图/校验/拓扑→子目标计划），
与 LLM 调用无关，可独立单测：

- MAX_DAG_NODES / MAX_SUBGOALS：规模上限常量
- cap_subgoals_keep_last：两条路径共用的「保留收尾」截断（原 59-87 行）
- _flatten_produces：产出物字段摊平（原 90-110 行）
- BlueprintNode / BlueprintDAG：DAG 数据结构 + 校验 + 图算法 + 序列化

对外契约：`from agent.blueprint_planner import <X>` 仍可用（主文件跳板式
re-export，且为**同一对象** `is`）；本模块**不反向导入**主文件（无环）。
"""
import logging
import re                     # 2026-10-12 批次 3：`_as_id_list` 归一化模型给的 inputs
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("MathPilot")

# 安全上限：单题 DAG 节点总数（LEAP 论文子目标规模通常 < 30）
MAX_DAG_NODES = 50

# 子目标数上限：与 SubGoalSolver LLM 路径的 max_subgoals 保持一致
# （sub_goal_solver.py:218 `_parse_subgoal_plan(raw, max_subgoals=6)`，
#  调用处 sub_goal_solver.py:1086 取 `getattr(self.config, "max_subgoals", 6) or 6`）。
# blueprint 路径此前无上限 ⇒ 实测 n_subgoals p90=9 / max=17，28% 超 6，
# 多跑 3~11 次串行 32768-token 调用（每步约 86s）。
MAX_SUBGOALS = 6


def cap_subgoals_keep_last(items: list, max_n) -> tuple:
    """按上限截断子目标序列，**保留收尾子目标**。返回 (保留列表, 丢弃列表)。

    为什么不是 `items[:max_n]`（2026-09-15 修正）：

    - 子目标按**拓扑序**排列，最后一个通常是"合并结论 / 得出最终答案"那一步
      （`prompts/sub_goal.py` 明写"最后一个子目标通常是'合并结论'或'得出最终答案'"）；
    - 盲截尾部会把它丢掉 ⇒ **前面所有子目标都白解**（没有任何一步产出最终答案）。
      实测 n_subgoals p90=9 / max=17、28% 的题超上限，即近三成题目受此影响。

    保留策略：前 (max_n-1) 个 **+ 最后一个**。

    `max_n <= 0` 表示**不截断**——与 `SubGoalSolver._parse_subgoal_plan` 的
    2026-09-15 语义一致（旧写法 `int(x or 6)` 会把 0 吃成 6，"不截断"无法表达）。
    本函数是两条路径（blueprint / LLM 规划）**共用**的截断实现，避免语义再次分叉。
    """
    if max_n is None:
        max_n = MAX_SUBGOALS
    try:
        max_n = int(max_n)
    except (TypeError, ValueError):
        max_n = MAX_SUBGOALS
    seq = list(items or [])
    n = len(seq)
    if max_n <= 0 or n <= max_n:
        return seq, []
    if max_n == 1:
        return seq[-1:], seq[:-1]
    return seq[:max_n - 1] + seq[-1:], seq[max_n - 1:-1]


def _as_id_list(value) -> list:
    """把模型给的 `inputs` 归一化为 id 字符串列表（宽容形态）。

    为什么需要（2026-10-12 批次 3）：`inputs` 由模型自由生成，实测有
    `["n1","n2"]` / `"n1"` / `"n1, n2"` / `[{"id": "n1"}]` 等形态，
    直接 `list()` 会得到脏数据 ⇒ 下游 R1/R2 校验失真。统一在此归一化（单一来源）。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for v in value:
            # ⚠ 必须先判 None：`str(None)` == "None" 会造出垃圾 id 污染下游校验
            #   （2026-10-12 单测实测抓到）。
            if v is None:
                continue
            if isinstance(v, dict):
                v = v.get("id") or v.get("node") or v.get("ref") or ""
            s = str(v).strip()
            if s and s.lower() != "none":
                out.append(s)
        return out
    return [p.strip() for p in re.split(r"[,\s、;；]+", str(value)) if p.strip()]


def _flatten_produces(value) -> str:
    """把模型声明的「产出物」字段摊平成单行文本（2026-10-06，子目标交付重写 A）。

    为什么需要：`produces` 由模型自由生成，实测有三种形态——
      · 字符串：`"一条关于下界估计的单项不等式"`
      · dict（本提示词 `inputs` 是同款结构，模型会串用）：
        `{"object": "下界不等式", "use": "供 n3 使用"}`
      · list：`["不等式 A", "不等式 B"]`
    摊平失败一律返回 ""（宁可 expected_output 为空，也不塞入非文本垃圾）。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = [str(v).strip() for v in value.values() if str(v).strip()]
        return "；".join(parts)
    if isinstance(value, (list, tuple)):
        parts = [_flatten_produces(v) for v in value]
        return "；".join(p for p in parts if p)
    return str(value).strip()


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BlueprintNode:
    """AND-OR DAG 中的单个节点。

    node_type: "and"（所有 children 都必须证）| "or"（任一 child 可证）
    children: 子节点 id 列表；空列表 = 叶子（原子子目标）
    node_role: "required"（默认，进主求解链）| "anticipatory"（前瞻引理）
        —— LEAP §2.3 / Figure 2 的"前瞻引理规划"（Anticipatory Lemma Planning）：
        蓝图生成时可能提议**当前 sketch 不需要、但后续证明步骤可能用到**的
        辅助引理；这些引理挂在图记忆中（Figure 2 用虚线边标注），
        **不阻塞当前 AND 节点的完成**。
        论文消融（Table 6）：DAG vs 朴素树 +10.0pp(Basic)/+16.7pp(Advanced)，
        归因两条机制之一就是前瞻引理被下游子目标复用；增益集中在难类别
        （Advanced 代数 75→100、数论 66.6→100）。
        ⚠ 落地（2026-09-15）：anticipatory 节点**不进 `to_subgoal_plan()` 的
        求解链**，只写入引理记忆（ctx.lemma_repo），供下游子目标提示词引用。
    """
    id: str
    node_type: str                      # "and" | "or"
    statement: str                      # 该节点的数学陈述（自然语言 / Lean 陈述）
    children: list = field(default_factory=list)
    rationale: str = ""                 # 分解依据（可选，用于 trace 与审查）
    node_role: str = "required"         # "required" | "anticipatory"
    # ★★ 2026-10-06（子目标交付重写 A）：`produces` = 该节点**产出什么可核验对象**
    #   （提示词 prompts/blueprint.py:89-101 一直要求模型逐节点声明，示例见 :179
    #   "一条关于下界估计的单项不等式"）。但**此前本 dataclass 根本没有该字段、
    #   `_parse_blueprint_json`/`from_dict` 也不读它** ⇒ 字段被静默丢弃，
    #   最终 `to_subgoal_plan`（:306）只能把 `expected_output` 硬编码成 ""。
    #   实测（smoke10 2026-10-06）：10 题中 8 题走蓝图路径 ⇒ 73 个子目标里
    #   **59 个 expected_output 为空（81%）**，step 提示词里"期望输出：{空}"
    #   ⇒ 模型没有"该产出什么"的约束 ⇒ 64/73（88%）交付 <120 字。
    #   本字段即该缺口的落点：解析 → 下传 → `expected_output`。
    produces: str = ""
    # ★ 2026-10-12 批次 3（用户 D19/S4）：`inputs` + `method` **真正落到节点上**。
    #   背景：`prompts/blueprint.py:88-106` **早就要求**模型输出 `inputs`（消费哪些
    #   前序节点的结论）与 `produces`，但 `parse_blueprint` 从不读 `inputs`、
    #   `to_subgoal_plan` 也不透传 ⇒ 求解侧拿不到「这一步需要什么」⇒
    #   **断链（inputs 对不上 produces）无法机械检测**（项目铁律早就要求）。
    inputs: list = field(default_factory=list)   # 消费的前序节点 id 列表
    method: str = ""                            # 怎么求（公式/手段），可空

    @property
    def is_anticipatory(self) -> bool:
        """是否前瞻引理（不进主求解链，只入引理记忆）。"""
        return str(self.node_role or "").strip().lower() == "anticipatory"


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
    def to_subgoal_plan(self, max_subgoals: int | None = None,
                        with_deps: bool = True,
                        or_expand_all: bool = False) -> dict:
        """把 DAG 转成 SubGoalSolver 兼容的子目标规划。

        规则：
        - AND 节点 → 展开所有 children（全部必须求解）
        - OR 节点 → 默认取第一个 child（策略分支，先尝试主分支）；
          传入 `or_expand_all=True` 时展开**全部**备选分支。
          该项为 2026-09-20 新增，默认 False 以保持历史行为（须 A/B 后定默认）。
        - 叶子节点 → 作为原子子目标
        - 输出按拓扑序排列，depends_on 依据 DAG **依赖锥**（见 `_preceding_leaves`）
        - ★ 前瞻引理（node_role="anticipatory"）**不进求解链**：
          只收集到返回值的 `anticipatory_lemmas` 字段，供调用方写入引理记忆
          （LEAP §2.3：挂图但不阻塞当前节点；见 BlueprintNode.node_role 说明）

        max_subgoals: 子目标数上限。None → MAX_SUBGOALS（默认 6）；
        **<=0 表示不截断**（与 SubGoalSolver._parse_subgoal_plan 同语义）。
        超限时**保留收尾子目标**（见 cap_subgoals_keep_last），
        depends_on 按存活节点重算（`d in order` 过滤），索引仍然有效。

        with_deps: False 时**不产出**依赖边（depends_on 全空）。
        默认 True=修复后的正确行为；设为 False 可复现旧行为做 A/B 对照。
        ★ 2026-09-15 修复：旧实现用 `_ancestors(nid) & selected` 计算依赖，
        而祖先全是**内部节点**、`selected` 只含**叶子**，交集恒为空 ⇒
        `depends_on` 结构性恒空、DAG 结构完全没传到求解器
        （2026-09-10 那批 112 题实测 dep_edges **全部为 0**）。
        """
        if not self.nodes:
            return {"problem_analysis": {}, "subgoals": [], "merge_strategy": "",
                    "anticipatory_lemmas": []}

        # 1) 展开：从根出发，收集需要求解的叶子（AND 全展开，OR 取第一个分支）
        selected: set = set()      # 被选中的叶子节点 id
        expanded: set = set()      # 已展开的非叶节点 id（防重复）
        order: list = []           # 展开顺序（用于稳定拓扑）
        anticipatory: list = []    # ★ 前瞻引理节点（收集陈述，不入 order）

        # ★ 前瞻引理是"旁挂"的（不挂在任何节点的 children 里，见提示词规格），
        #   因此**不能**靠从 root 的 DFS 发现——必须全量扫描。
        #   （2026-09-15 实测踩到：只扫可达节点时 anticipatory_lemmas 恒为空。）
        #   同时把这些节点从展开的入口排除，避免万一被登记为 child 时混入求解链。
        anti_ids: set = set()
        for nid, nd in self.nodes.items():
            if nd.is_anticipatory:
                anti_ids.add(nid)
                anticipatory.append({
                    "id": nid,
                    "statement": nd.statement,
                    "rationale": nd.rationale,
                })

        def expand(nid: str) -> None:
            node = self.nodes[nid]
            if nid in expanded:
                return
            # ★ 前瞻引理：不展开、不进求解链（论文语义 = 挂图但不阻塞当前节点）
            if nid in anti_ids:
                expanded.add(nid)
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
            else:  # or 节点
                # 2026-09-20：原实现恒取 `children[0]`（注释称"主策略分支"），
                # 使 OR 节点在语义上退化为 AND 的单分支 ⇒ 蓝图路径**结构性不存在
                # "独立求解分支"**（另一条策略路径永不求解）。这正是"子目标链
                # 锁定错值"的上游结构原因，比提示词层规则更根本。
                # ⚠ 展开全部分支会显著改变子目标规模，属**行为变更**，须 A/B 验证，
                #   故做成开关：默认 False = 保持历史行为；置 True 才展开全部 children。
                if or_expand_all:
                    for c in node.children:
                        expand(c)
                else:
                    expand(node.children[0])

        if self.root_id in self.nodes:
            expand(self.root_id)

        # 1.5) 子目标数上限（2026-09-15 修正两处）
        #   ① 去掉 `or` 陷阱：旧写法 `int(max_subgoals or MAX_SUBGOALS)` 把 0
        #      （=不截断）吃成默认 6 ⇒ 与 SubGoalSolver 0915 修好的语义不一致，
        #      同一个 knobs 在两条路径上行为不同。
        #   ② 去掉盲截尾部：改由 cap_subgoals_keep_last 保留收尾子目标
        #      （盲截会丢掉"合并结论/得出最终答案"那一步，导致全链白解）。
        order, _dropped = cap_subgoals_keep_last(order, max_subgoals)
        if _dropped:
            logger.warning(
                "Blueprint 子目标数超上限，截断 %d 个（保留收尾子目标）：丢弃 %s",
                len(_dropped), _dropped)

        # 2) 构造子目标：拓扑序（父先于子）
        #    用展开顺序近似：expand 是前序 DFS，父节点先于子节点被访问。
        #    子目标按 order 排列即满足"依赖在前"。
        subgoals = []
        # 位置索引（子目标编号从 1 开始），避免在循环里反复 order.index()
        _pos = {nid: i for i, nid in enumerate(order, 1)}
        for idx, nid in enumerate(order, 1):
            node = self.nodes[nid]
            # 依赖：nid 的**依赖锥** = 必须早于它求解的叶子集合（见 _preceding_leaves）。
            if with_deps:
                deps = [p for d, p in _pos.items()
                        if d in self._preceding_leaves(nid, selected) and p != idx]
            else:
                deps = []
            deps.sort()
            subgoals.append({
                "id": idx,
                "title": f"子目标{idx}: {self._short(node.statement)}",
                "description": node.statement,
                "type": self._infer_type(node.statement),
                "depends_on": deps,
                # ★★ 2026-10-06（子目标交付重写 A）：原实现**硬编码空串** ⇒ 蓝图
                #   路径（实测 smoke10 8/10 题走此路径）下每个子目标的
                #   `expected_output` 都是 ""，step 提示词里"期望输出："恒为空
                #   ⇒ 模型没有"该产出什么可核验对象"的约束 ⇒ 73 个子目标里
                #   59 个（81%）该字段为空、64 个（88%）交付 <120 字。
                #   现取节点声明的 `produces`（可核验对象）；模型没写时才为空。
                "expected_output": str(node.produces or "").strip(),
                # ★ 2026-10-12 批次 3：把节点声明的 `inputs`（节点 id）映射为**子目标
                #   序号**后下传 —— 求解侧由此知道「这一步需要哪些前序结论」，
                #   断链才可被机械检测（`validate_inputs` 的求解侧对应物）。
                "inputs": sorted(_pos[d] for d in (getattr(node, "inputs", None) or [])
                                 if d in _pos and _pos[d] != idx),
                "inputs_raw": [str(d) for d in (getattr(node, "inputs", None) or [])],
                "method": str(getattr(node, "method", "") or "").strip(),
                "result": "",
            })
        return {
            "problem_analysis": self.problem_analysis,
            "subgoals": subgoals,
            "merge_strategy": self.merge_strategy,
            "anticipatory_lemmas": anticipatory,   # ★ 前瞻引理（供引理记忆消费）
        }

    def validate_inputs(self, selected=None) -> dict:
        """R1/R2 机械校验（零 LLM，2026-10-12 批次 3）：`inputs` 引用是否有效。

        - **R2 断链**：`inputs` 里的 id 必须**存在**于本图，且必须是本节点的
          **祖先或已枚举的旁挂引理**（即它得先被求出来）——否则该步所需的前置
          结论无人提供，链路断裂。
        - **R1 叶子判据**：叶子节点的 `inputs` 若引用非空 ⇒ 说明它其实依赖前序
          结论，**不应是叶子**（形态学上正是 K11「子目标空壳」的成因）。

        返回 ``{"ok": bool, "broken": [...], "leaky_leaves": [...], "n": int}``。
        只报告、不阻断（上层据 `gap_kind` 分流处置，见 sub_goal_solver__planner）。
        """
        broken, leaky = [], []
        for nid, nd in (self.nodes or {}).items():
            refs = [str(r) for r in (getattr(nd, "inputs", None) or []) if str(r)]
            for r in refs:
                if r not in self.nodes:
                    broken.append({"id": nid, "ref": r, "reason": "引用不存在的节点"})
                elif r == nid:
                    broken.append({"id": nid, "ref": r, "reason": "自引用"})
            # R1：真叶子（无 children）却声明了非自引用的 inputs ⇒ 形态可疑
            if not nd.children:
                ext = [r for r in refs if r != nid and r in self.nodes]
                if ext:
                    leaky.append({"id": nid, "refs": ext[:5],
                                  "reason": "叶子节点依赖前序结论（应继续分解）"})
        return {"ok": not broken and not leaky, "broken": broken,
                "leaky_leaves": leaky, "n": len(self.nodes or {})}

    def _preceding_leaves(self, nid: str, selected: set) -> set:
        """依赖锥：必须在 `nid` **之前**求解的叶子节点集合（2026-09-15 新增）。

        定义（与拓扑序语义一致）：自 `nid` 沿父边**上溯到根**，对路径上的每个祖先 A，
        取 A 的 children 中**排在"通往 nid 的那个孩子"之前**的兄弟 C，
        把 C 子树下所有被选中的叶子计入依赖。

        ★ 为什么不能沿用 `_ancestors(nid) & selected`：
        祖先集合里全是**内部节点**（因为只有非叶节点才可能有 children），
        而 `selected` 只收录**叶子**，两者交集**恒为空** ⇒ `depends_on` 结构性恒空，
        整张 DAG 的结构信息完全没传到求解器。实测佐证：2026-09-10 那批 112 题
        `subgoal_stats.dep_edges` **全部为 0**（111 道走蓝图 + 1 道不走）。

        例（AND(g)→[n1(AND)→[n1a,n1b], n2(OR)→[n2a,n2b]]，OR 取首分支）：
            展开顺序 n1a, n1b, n2a ⇒ 依赖锥分别为 {}、{n1a}、{n1a,n1b}
            （策略 A 位于 n2 之下，必须晚于 n1 整棵子树的两步）。
        """
        if not self.nodes:
            return set()
        parents: dict = {}
        for pid, node in self.nodes.items():
            for c in node.children:
                parents.setdefault(c, []).append(pid)

        deps: set = set()
        visited: set = set()
        frontier = [nid]
        while frontier:
            cur = frontier.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for pid in parents.get(cur, []):
                pnode = self.nodes.get(pid)
                if pnode is None:
                    continue
                try:
                    pos = pnode.children.index(cur)
                except ValueError:      # 父边与 children 不一致（脏数据）→ 视作排在最后
                    pos = len(pnode.children)
                for sib in pnode.children[:pos]:
                    deps |= self._subtree_ids(sib) & selected
                frontier.append(pid)
        deps.discard(nid)               # 自依赖不合法
        return deps

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

    # ---------------- 子树级局部重写（#34 第二级，LEAP 2.5） ----------------
    def _subtree_ids(self, root_id: str) -> set:
        """返回以 root_id 为根的子树内全部节点 id（含 root 自身）。"""
        out, stack = set(), [root_id]
        while stack:
            nid = stack.pop()
            if nid in out:
                continue
            out.add(nid)
            node = self.nodes.get(nid)
            if node:
                stack.extend(node.children)
        return out

    def _lca(self, node_ids) -> Optional[str]:
        """最低公共祖先：所有 node 的祖先集合（含自身）交集中深度最大的。

        深度用祖先数衡量（祖先越多 = 越深）。用于"只重写 reject 节点所在子树"：
        以 LCA 为子树根重写，保证覆盖所有被拒节点、又最小化波及范围。
        """
        ids = [n for n in node_ids if n in self.nodes]
        if not ids:
            return None
        common = set(self._ancestors(ids[0])) | {ids[0]}
        for nid in ids[1:]:
            common &= (self._ancestors(nid) | {nid})
        if not common:
            return None
        return max(common, key=lambda n: len(self._ancestors(n)))

    def _prune_subtree(self, root_id: str) -> "BlueprintDAG":
        """摘除 root_id 的整棵子树（root 自身保留为'待重分解'锚点）。

        返回裁剪后的 DAG：root_id 保留但其 children 清空（等待 LLM 重新分解），
        子树内其余节点全部删除；其余节点与边原样保留。
        """
        subtree = self._subtree_ids(root_id)
        nodes = {}
        for nid, node in self.nodes.items():
            if nid in subtree and nid != root_id:
                continue  # 摘除
            # 过滤子引用：被摘除的节点从 children 中移除；root_id 自身保留
            kept_children = [
                c for c in node.children
                if c not in subtree or c == root_id]
            nodes[nid] = BlueprintNode(
                id=nid, node_type=node.node_type, statement=node.statement,
                children=kept_children if nid != root_id else [],
                rationale=node.rationale,
                produces=node.produces,     # ★ 2026-10-06：产出物必须随裁剪保留
            )
        return BlueprintDAG(
            nodes=nodes, root_id=self.root_id,
            merge_strategy=self.merge_strategy,
            problem_analysis=self.problem_analysis,
        )

    def _graft_subtree(self, root_id: str,
                       new_dag: "BlueprintDAG",
                       id_prefix: str = "r") -> Optional["BlueprintDAG"]:
        """把新分解的子树接到 root_id 下（子树级局部重写最后一步）。

        new_dag：LLM 重新分解的子树（根节点 statement 应 ≈ root_id 的 statement）。
        返回拼接后的完整 DAG；结构非法返回 None。

        id 冲突处理：新子树非根节点统一加 id_prefix 前缀，避免与现存节点撞名。
        """
        if new_dag is None or not new_dag.nodes or new_dag.root_id not in new_dag.nodes:
            return None
        new_root = new_dag.nodes[new_dag.root_id]
        # 收集新子树的非根节点，加前缀重命名（children 同步重写）
        renamed: dict = {}
        for nid, node in new_dag.nodes.items():
            if nid == new_dag.root_id:
                continue
            new_id = f"{id_prefix}_{nid}"
            renamed[new_id] = BlueprintNode(
                id=new_id, node_type=node.node_type, statement=node.statement,
                children=[f"{id_prefix}_{c}" if c in new_dag.nodes else c
                          for c in node.children],
                rationale=node.rationale,
                produces=node.produces,     # ★ 2026-10-06：产出物随子树嫁接保留
            )
        # 先摘除 root_id 的旧子树（root 保留为锚点），避免旧节点残留
        base = self._prune_subtree(root_id) if root_id in self.nodes else self
        # 深拷贝现存节点，避免污染入参 DAG
        nodes = {}
        for nid, node in base.nodes.items():
            nodes[nid] = BlueprintNode(
                id=nid, node_type=node.node_type, statement=node.statement,
                children=list(node.children), rationale=node.rationale,
                produces=node.produces,     # ★ 2026-10-06：产出物随深拷贝保留
            )
        if root_id not in nodes:
            return None
        # root_id 的 children 换成新根的子节点（新根自身不落盘，仅作为分解锚点）
        nodes[root_id].children = [
            f"{id_prefix}_{c}" if c in new_dag.nodes else c
            for c in new_root.children]
        nodes.update(renamed)
        merged = BlueprintDAG(
            nodes=nodes, root_id=self.root_id,
            merge_strategy=self.merge_strategy,
            problem_analysis=self.problem_analysis,
        )
        ok, _ = merged.validate()
        return merged if ok else None

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
                 "children": n.children, "rationale": n.rationale,
                 "node_role": n.node_role, "produces": n.produces}
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
                # 缺省 required：旧 DAG 序列化（无该字段）行为不变
                node_role=nd.get("node_role", nd.get("role", "required")) or "required",
                # ★ 2026-10-06：产出物（可核验对象）；旧序列化无该字段 → ""（不破坏）
                produces=str(nd.get("produces", nd.get("output", "")) or ""),
            )
        return cls(
            nodes=nodes,
            root_id=data.get("root_id", data.get("root", "")),
            merge_strategy=data.get("merge_strategy", ""),
            problem_analysis=data.get("problem_analysis", {}),
        )
