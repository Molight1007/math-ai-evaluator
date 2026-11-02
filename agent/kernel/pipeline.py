"""六步内核的编排 —— 理解 → 规划 → 求解 → 裁决 → 投影 → 交付。

与旧链的结构差异（不是代码量差异）
----------------------------------
1. **依赖先解**：按拓扑序求解，上游没解完就不解下游。旧链按规划声明
   顺序跑，上游可能在下游之后才解，于是下游拿到的是「还没发生」的前提。
2. **环即失败**：循环依赖直接抛错，不靠「多跑几轮看看」。旧链跑满三轮
   实测判对 0 条，且占池空题 46% 的耗时。
3. **单轮**：不设轮数参数。多轮重解的成本实测是 4~5.7 倍放大，而 3 轮
   迭代的边际贡献是 0 —— 没有开关可打开，就不会有人偷偷打开。
4. **裁决与交付分离**：交付只查账本，不重算闭合。两套口径必然漂移。

★ 六步全部可注入：离线回放注入「历史节点 + 历史求解产出」，主流程注入
  真实的模型客户端与检查器。同一份编排逻辑，两条使用路径，不会各写一份。
"""

from dataclasses import dataclass, field, replace

from contracts.closure import CLOSURE_HARD
from contracts.proof_ledger import ADMIT_HARD, ProofLedger

from .deliver import Delivery, deliver
from .judge import judge
from .project import project_items, project_text
from .types import SolveOutcome

__all__ = ["Kernel", "KernelResult", "KernelError", "CycleError", "topo_order"]


class KernelError(Exception):
    """内核配置或输入错误 —— 显式失败，不静默降级。"""


class CycleError(KernelError):
    def __init__(self, nodes):
        self.nodes = tuple(nodes)
        super(CycleError, self).__init__(
            "规划存在循环依赖，涉及 %d 个节点：%s"
            % (len(self.nodes), ", ".join(self.nodes[:8])))


def topo_order(nodes, break_cycles=False):
    """按依赖排序。返回 (顺序, {nid: [未满足/未在计划里的依赖]})。

    环 → 默认 CycleError（显式失败）。
         break_cycles=True 时**破环**：环内互指的边记为未满足前提，
         节点仍参与排序但拿不到这些前提。这样一道题的局部规划缺陷
         不会让整题崩掉，同时**不掩盖**问题（帐本里那些边就是未放行）。
    未知依赖 → 记为外部前提，不参与排序，但账本后续会把它算成未放行。
    """
    by_id = {n.nid: n for n in nodes}
    if len(by_id) != len(nodes):
        raise KernelError("节点 id 重复：规划产物不合法")

    indeg = {}
    children = dict((nid, []) for nid in by_id)
    external = {}
    for n in nodes:
        deps = [d for d in (n.deps or ()) if d != n.nid]
        unknown = [d for d in deps if d not in by_id]
        known = sorted(set(d for d in deps if d in by_id))
        if unknown:
            external[n.nid] = unknown
        indeg[n.nid] = len(known)
        for d in known:
            children[d].append(n.nid)

    ready = [n.nid for n in nodes if indeg[n.nid] == 0]
    out = []
    while ready:
        cur = ready.pop(0)
        out.append(cur)
        for c in children[cur]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)

    if len(out) != len(by_id):
        stuck = set(n for n in by_id if n not in set(out))
        if not break_cycles:
            raise CycleError(sorted(stuck))
        # 破环：把环内互指的边摘掉，其余依赖保留，再排一次。
        broken = {}
        for nid in stuck:
            bad = [d for d in (by_id[nid].deps or ())
                   if d in stuck and d != nid]
            if bad:
                broken[nid] = bad
        trimmed = [replace(n, deps=tuple(
            d for d in (n.deps or ()) if not (d in stuck and d != n.nid)))
            for n in nodes]
        order, ext = topo_order(trimmed, break_cycles=False)
        for k, v in broken.items():
            ext.setdefault(k, [])
            ext[k].extend(v)
        return order, ext

    return tuple(out), external


@dataclass
class KernelResult:
    delivery: Delivery = None
    ledger: ProofLedger = field(default_factory=ProofLedger)
    order: tuple = ()
    external_deps: dict = field(default_factory=dict)
    judgements: list = field(default_factory=list)
    note: str = ""

    # -------------------------------------------------------------- 诊断
    def diag(self) -> dict:
        led = self.ledger
        return {
            "kernel": "v2",
            "order": list(self.order),
            "external_deps": dict(self.external_deps),
            "ledger": led.stats(),
            "regressions": list(led.regressions()),
            "retargets": list(led.retargets()),
            "judgements": [{"nid": j.nid, "status": j.status,
                            "by": j.by, "reason": j.reason}
                           for j in self.judgements],
            "delivery": {"tier": self.delivery.tier if self.delivery else "",
                         "basis": self.delivery.basis if self.delivery else "",
                         "reason": self.delivery.reason if self.delivery else ""},
            "projected": len(project_items(led, ADMIT_HARD)),
            "note": self.note,
        }


class Kernel(object):
    """六步编排。所有步骤均可注入，缺省时按需报错（不静默降级）。"""

    def __init__(self, understand=None, plan=None, solve=None,
                 checker=None, admit=ADMIT_HARD, break_cycles=False):
        self._understand = understand
        self._plan = plan
        self._solve = solve
        self._checker = checker
        self._admit = admit
        # ★ 默认不破环：规划产出循环依赖是**缺陷**，默认应当显式失败。
        #   回放历史产物时开，因为要统计「有多少题存在环」，不能直接崩。
        self._break_cycles = break_cycles

    # ------------------------------------------------------ 离线：只跑 4~6
    def run_solved(self, nodes, outcomes, root_oid="", note=""):
        """用已有的节点与求解产出跑裁决/投影/交付。

        回放台走这条路：零模型调用，能回答「换成新内核，这批题会怎样」。
        outcomes: {nid: SolveOutcome | [SolveOutcome, ...]}
        """
        order, external = topo_order(nodes, self._break_cycles)
        led = ProofLedger()
        judged = []
        for nid in order:
            node = next(n for n in nodes if n.nid == nid)
            outs = outcomes.get(nid)
            if outs is None:
                outs = []
            elif isinstance(outs, SolveOutcome):
                outs = [outs]
            for out in outs:
                j = judge(node, out, self._checker)
                judged.append(j)
                led.record(node.as_obligation(
                    j.status, reason=j.reason, evidence=j.evidence,
                    round=getattr(out, "round", 0),
                    claim=getattr(out, "claim", "")))
        d = deliver(led, root_oid=root_oid, level=self._admit)
        return KernelResult(delivery=d, ledger=led, order=order,
                            external_deps=external, judgements=judged,
                            note=note)

    # ------------------------------------------------------ 在线：六步全跑
    def run(self, problem, metadata=None):
        if self._understand is None or self._plan is None or self._solve is None:
            raise KernelError(
                "在线模式需要注入 understand / plan / solve 三步；"
                "离线回放请用 run_solved（不注入即可）")

        spec = self._understand(problem, metadata or {})
        nodes = list(self._plan(spec, problem) or [])
        if not nodes:
            raise KernelError("规划产物为空 —— 宁可显式失败，不要静默交白卷")

        order, external = topo_order(nodes, self._break_cycles)
        by_id = {n.nid: n for n in nodes}
        led = ProofLedger()
        judged = []

        for nid in order:
            node = by_id[nid]
            # ★ 上游已知只从投影来 —— 这是第 5 步唯一允许的用法
            ctx_text = project_text(led, self._admit)
            out = self._solve(node, ctx_text)
            if out is None:
                out = SolveOutcome(nid=nid)
            j = judge(node, out, self._checker)
            judged.append(j)
            led.record(node.as_obligation(
                j.status, reason=j.reason, evidence=j.evidence,
                claim=getattr(out, "claim", "")))

        root = order[-1] if order else ""
        d = deliver(led, root_oid=root, level=self._admit)
        return KernelResult(delivery=d, ledger=led, order=order,
                            external_deps=external, judgements=judged)
