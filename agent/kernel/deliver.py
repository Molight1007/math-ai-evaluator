"""第 6 步 交付 —— 查账本给答案，猜的必须标成猜的。

旧链最后由「格式化 + 终答挑选」决定交什么，而那一步只能看到候选文本，
看不到「这个答案有没有被证过」。于是猜对的答案和证出的答案在输出上
一模一样 —— 评测侧无从区分，系统自己也无从区分。

这里把交付分成三档，**档位随答案一起输出**：

    proven     整题目标工具级闭合，答案是证出来的
    unproven   有答案但无闭合路径（可能对，但是猜的）
    none       连候选都没有，诚实报告失败

★ 为什么答案不能只有字符串：一旦只剩字符串，「猜的」这个事实就永久
  丢失了。而它恰恰是后续所有决策（要不要重解、要不要降级、评测怎么
  解读）的前提。
"""

from dataclasses import dataclass

from contracts.closure import CLOSURE_HARD
from contracts.proof_ledger import ADMIT_HARD, ProofLedger

__all__ = ["Delivery", "DELIVERY_PROVEN", "DELIVERY_UNPROVEN", "DELIVERY_NONE",
           "deliver"]

DELIVERY_PROVEN = "proven"
DELIVERY_UNPROVEN = "unproven"
DELIVERY_NONE = "none"


@dataclass(frozen=True)
class Delivery:
    answer: str = ""
    tier: str = DELIVERY_NONE
    basis: str = ""
    reason: str = ""

    @property
    def proven(self) -> bool:
        return self.tier == DELIVERY_PROVEN


def deliver(ledger: ProofLedger, root_oid="", guess="",
            level: str = ADMIT_HARD) -> Delivery:
    """从账本出口。priority: 已证目标 > 有结论未证 > 外部候选 > 无。

    ★ 这里**不重算**闭合，只查账本。重算就会出现「交付侧有一套判据、
      裁决侧有另一套」—— 两套口径必然漂移，项目已经因此吃过两次亏。
    """
    root = ledger.get(root_oid) if root_oid else None

    if root is not None and root.status == CLOSURE_HARD:
        claim = (root.claim or "").strip()
        if claim:
            return Delivery(answer=claim, tier=DELIVERY_PROVEN,
                            basis=root_oid, reason="目标工具级闭合")

    # 未闭合但有结论：答案可用，但必须标明是未证的
    if root is not None:
        claim = (root.claim or "").strip()
        if claim:
            return Delivery(answer=claim, tier=DELIVERY_UNPROVEN,
                            basis=root_oid,
                            reason="目标未闭合（%s）" % (root.reason or "unknown"))

    g = (guess or "").strip()
    if g:
        return Delivery(answer=g, tier=DELIVERY_UNPROVEN, basis="guess",
                        reason="无闭合路径，采用外部候选")

    return Delivery(answer="", tier=DELIVERY_NONE, basis="",
                    reason="未证且无候选")
