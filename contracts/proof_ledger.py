"""证明账本 —— 全链唯一数据契约：什么能进下游，由账本事实决定。

为什么要有它（2026-11-03）
--------------------------
旧链把「能不能继续」交给评审意见（五道 LLM 判 LLM），于是每修一个判据
缺陷都会暴露下一个 —— 因为判据本身不可靠，修完一个，剩下的错判才显得
出来。账本把这件事从「征求意见」改成「查事实」：一条义务只有几种确定
状态，下游能不能用，查表即可，不问模型。

★ 这是「重写内核」的地基，不是又一个补丁：旧链没有账本，所以每个阶段
  都得自己决定信不信上游；有了账本，六步内核里没有任何一步需要「相信」
  任何东西。

四条不可让渡的语义
------------------
1. **单调**：闭合一旦达成，后续轮次不得撤销。
   旧链每轮结果覆盖上一轮，结论在同一题内可以 66 → 946 → 66 来回翻
   （omni-3556 一次运行内三轮并存），等于没有结论。账本拒绝降级写入，
   并把被拒的降级**留痕**（不是静默丢弃 —— 静默会让「有结论」看起来
   比实际更稳）。

2. **目标不可改写**：某一 oid 首次声明「要证什么」之后，后续轮次不得
   改目标，只能改「证成了没有」。
   旧链允许每轮重解重写目标，这就是「把存在性问题拆成分类证明题」的
   机制（omni-3556：关组 6 步判对，开组 22 步造 3 个假引理）。偷换
   命题比答错更严重，所以这里显式记冲突。

3. **投影而非标记**：未放行的条目**物理上不在** `project()` 的返回里。
   只要它还在列表里，下游一定能「顺手」读到，加多少标记都拦不住。

4. **目标与证据分离**：`goal`（要证什么）与 `evidence`（谁判的、判成
   什么）分字段。旧链一个槽同时承载目标 / 猜想 / 结论，下游无从区分
   权威性。

放行严格度（三档，默认最严）
----------------------------
    hard  只放工具级闭合（唯一不可贿赂；L0 闸门）
    soft  再放「模型判对且有推导」（旧链的默认行为，作为回退档）
    any   全放（**只用于复现旧行为**，不得作为生产默认）

★ 默认必须是 hard：把 soft 当默认，等于把同源失效往下游搬一层，
  账本本身也就失去意义。
"""

from dataclasses import dataclass, field, replace

from .closure import (
    CLOSURE_HARD, CLOSURE_OPEN, CLOSURE_SOFT, CLOSURE_UNMAPPED,
    closure_of,
)

__all__ = [
    "ADMIT_ANY", "ADMIT_SOFT", "ADMIT_HARD", "ADMIT_LEVELS", "DEFAULT_ADMIT",
    "Obligation", "ProofLedger", "admit_status", "obligation_from_row",
]

ADMIT_ANY = "any"
ADMIT_SOFT = "soft"
ADMIT_HARD = "hard"
ADMIT_LEVELS = (ADMIT_ANY, ADMIT_SOFT, ADMIT_HARD)

DEFAULT_ADMIT = ADMIT_HARD

# 某档放行下允许进入下游的状态集合
_ALLOWED = {
    ADMIT_ANY: (CLOSURE_HARD, CLOSURE_SOFT, CLOSURE_OPEN, CLOSURE_UNMAPPED),
    ADMIT_SOFT: (CLOSURE_HARD, CLOSURE_SOFT),
    ADMIT_HARD: (CLOSURE_HARD,),
}

# 严格程度排序，用于「单调升级」判定。
# ★ UNMAPPED 最低：它表示「没有产物」，任何有结论的状态都比它强。
_RANK = {
    CLOSURE_UNMAPPED: 0,
    CLOSURE_OPEN: 1,
    CLOSURE_SOFT: 2,
    CLOSURE_HARD: 3,
}


def admit_status(level: str, status: str) -> bool:
    """某档放行下，该状态能否进入下游。未知档位一律不放行（显式失败）。"""
    return status in _ALLOWED.get(level, ())


@dataclass(frozen=True)
class Obligation:
    """账本的一条义务。

    oid    稳定标识（同一命题在多次重解里必须同名，否则账本退化成日志）
    goal   要证什么（提问形态；**一经声明不可改写**）
    deps   依赖的上游 oid
    status 闭合层级（contracts.closure 四级）
    reason 判定依据（人读）
    evidence 工具裁决原文（机器可复核的部分；HARD 必须非空）
    round  来自第几轮（0 = 首轮）
    """

    oid: str
    goal: str = ""
    claim: str = ""
    deps: tuple = ()
    status: str = CLOSURE_UNMAPPED
    reason: str = ""
    evidence: str = ""
    round: int = 0


def obligation_from_row(oid, row, goal="") -> Obligation:
    """从历史产物的一行（04_subgoal_results 的一条）构造义务。

    这样回放台与主流程共用同一套构造口径 —— 两处各写一份必然漂移。
    """
    status, why = closure_of(row)
    tool_ran = bool(row.get("tool_ran")) if isinstance(row, dict) else False
    deps = row.get("depends_on") or row.get("deps") or () if isinstance(
        row, dict) else ()
    if isinstance(deps, str):
        deps = (deps,)
    return Obligation(
        oid=str(oid),
        goal=goal or "",
        claim="%s" % ((row.get("conclusion") or row.get("claim")
                       or row.get("answer") or "")
                      if isinstance(row, dict) else ""),
        deps=tuple(str(d) for d in deps),
        status=status,
        reason=why,
        evidence=("%s" % (row.get("tool_verdict") or "")) if tool_ran else "",
        round=int(row.get("round") or 0) if isinstance(row, dict) else 0,
    )


@dataclass
class ProofLedger:
    """单调账本。

    只接受「升级」写入；降级与改目标都被拒绝并留痕。
    ledger 内部不判断「结论对不对」—— 那是检查器的事，账本只记录结果。
    这样检查器可以整体替换（符号 / 形式 / 未来别的），账本语义不变。
    """

    _items: dict = field(default_factory=dict)
    # 被拒绝的降级写入：(既有条目, 试图写入的条目)
    _regressions: list = field(default_factory=list)
    # 被拒绝的改目标写入：(既有 goal, 新 goal, oid)
    _retargets: list = field(default_factory=list)

    # ---------------------------------------------------------------- 写入
    def record(self, ob: Obligation) -> bool:
        """写入一条义务。返回是否被接受。

        - 首次出现：接受
        - 状态上升：接受（保留首次声明的 goal / deps）
        - 状态不变或下降：拒绝；下降写入留痕
        - goal 与既有不同：拒绝改目标并留痕（**即便状态在上升**）
        """
        old = self._items.get(ob.oid)
        if old is None:
            self._items[ob.oid] = ob
            return True

        # 改目标：先拦，优先于状态判定 —— 目标被换掉之后，
        # 「状态上升」这件事本身就没有意义了（可能是在证另一个命题）。
        if ob.goal and old.goal and ob.goal.strip() != old.goal.strip():
            self._retargets.append((old.goal, ob.goal, ob.oid))
            return False

        new_rank = _RANK.get(ob.status, -1)
        old_rank = _RANK.get(old.status, -1)
        if new_rank > old_rank:
            self._items[ob.oid] = replace(
                ob,
                goal=old.goal or ob.goal,
                # 结论随升级更新：状态变了，说明「证成了什么」也有了新说法。
                # 目标不能改，结论可以 —— 但只在升级时接受。
                claim=ob.claim or old.claim,
                deps=old.deps or ob.deps,
            )
            return True
        if new_rank < old_rank:
            self._regressions.append((old, ob))
        return False

    def record_rows(self, rows, oid_of=None) -> int:
        """批量写入（回放台用）。返回被接受条数。"""
        n = 0
        for i, row in enumerate(rows or []):
            oid = oid_of(row, i) if oid_of else (row.get("sid")
                                                 or row.get("id") or i)
            if self.record(obligation_from_row(oid, row)):
                n += 1
        return n

    # ---------------------------------------------------------------- 查询
    def get(self, oid) -> Obligation:
        return self._items.get(str(oid))

    def all(self) -> list:
        return list(self._items.values())

    def admit(self, level: str = DEFAULT_ADMIT) -> frozenset:
        """某档下可进入下游的 oid 集合。"""
        return frozenset(
            ob.oid for ob in self._items.values()
            if admit_status(level, ob.status))

    def project(self, level: str = DEFAULT_ADMIT) -> tuple:
        """投影：只返回放行条目。

        ★ 返回 tuple 而非 list 是刻意的：调用方不能就地 append 塞回去。
        ★ 未放行者**不在结果里** —— 这是「先证明、再声明」的实现。
        """
        return tuple(
            {"oid": ob.oid, "goal": ob.goal, "claim": ob.claim,
             "status": ob.status, "evidence": ob.evidence}
            for ob in self._items.values()
            if admit_status(level, ob.status))

    def blocked_by(self, level: str = DEFAULT_ADMIT) -> dict:
        """哪些义务因为**依赖未放行**而不可执行 —— 闸门断点的归因。

        返回 {oid: [未放行的依赖 oid, ...]}；不含自身未闭合者。
        """
        open_set = self.admit(level)
        out = {}
        for ob in self._items.values():
            miss = [d for d in ob.deps if d not in open_set]
            if miss:
                out[ob.oid] = miss
        return out

    def unresolved_goals(self) -> tuple:
        """未闭合目标的清单 —— 下游提示词该拿到的「还缺什么」。"""
        return tuple(
            {"oid": ob.oid, "goal": ob.goal, "reason": ob.reason}
            for ob in self._items.values()
            if ob.status != CLOSURE_HARD)

    # ---------------------------------------------------------------- 诊断
    def stats(self) -> dict:
        c = {CLOSURE_HARD: 0, CLOSURE_SOFT: 0,
             CLOSURE_OPEN: 0, CLOSURE_UNMAPPED: 0}
        for ob in self._items.values():
            c[ob.status] = c.get(ob.status, 0) + 1
        return {
            "n": len(self._items),
            "hard": c[CLOSURE_HARD],
            "soft": c[CLOSURE_SOFT],
            "open": c[CLOSURE_OPEN],
            "unmapped": c[CLOSURE_UNMAPPED],
            "regressions": len(self._regressions),
            "retargets": len(self._retargets),
        }

    def regressions(self) -> tuple:
        """被拒绝的降级写入 —— **必须能查**：它是「同一题内结论反复翻」
        的唯一证据来源，丢了就永远算不出结论漂移率。"""
        return tuple((o.oid, o.status, n.status, n.round)
                     for o, n in self._regressions)

    def retargets(self) -> tuple:
        """被拒绝的改目标 —— 「偷换命题」的证据来源。"""
        return tuple(self._retargets)
