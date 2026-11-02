"""第 5 步 投影 —— 下游能看到什么。

这是新内核唯一新增的一层，也是整个重写的落点。

旧链的每个阶段都从「节点全文」拼上下文，于是未验证的猜测、被替换的旧
结论、写错的目标全都顺着流下去。加多少检查都是在出口拦水 —— 只要它还在
文本里，下游就一定能读到。

这里改成**删条目**：未放行的义务不出现在渲染结果里。没有标记可绕过，
因为没有东西可标记。

★ 硬约束：主流程里「上游已知」这一块内容，**只能**由本模块产出。
  任何一处绕过它去拼上下文，等价于把这一层删掉，而这件事在判对率上
  看不出来（噪声 12.6pp 盖得住），所以必须靠检查而不是靠自觉。
"""

from contracts.proof_ledger import ADMIT_HARD, ProofLedger

__all__ = ["project_text", "project_items", "PROJECTION_MARK"]

PROJECTION_MARK = "【已闭合结论】"


def project_items(ledger: ProofLedger, level: str = ADMIT_HARD):
    """放行条目（结构化）。账本已经保证未放行者不在返回里。"""
    return ledger.project(level)


def project_text(ledger: ProofLedger, level: str = ADMIT_HARD,
                 limit: int = 40) -> str:
    """渲染成下游可用的文本块。

    空账本返回空串 —— **不写「暂无」之类的占位**：占位会让下游误以为
    「已经查过了，确实没有」，而实际情况可能是「这一层根本没跑」。
    空就是空。
    """
    items = project_items(ledger, level)
    if not items:
        return ""
    lines = [PROJECTION_MARK]
    for it in items[:limit]:
        lines.append("- [%s] 目标：%s" % (it.get("oid", ""), it.get("goal", "")))
        claim = (it.get("claim") or "").strip()
        if claim:
            lines.append("  结论：%s" % claim)
        ev = (it.get("evidence") or "").strip()
        if ev:
            lines.append("  依据：%s" % ev.replace("\n", " ")[:200])
    return "\n".join(lines)
