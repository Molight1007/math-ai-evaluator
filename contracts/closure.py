"""闭合判定与「已闭合集合」投影 —— 单一权威源（契约层，零依赖）。

为什么单独成一个模块（2026-11-02）
----------------------------------
闭合判定此前只存在于回放床脚本里。现在 agent 侧也要用它（下游只能从
「已闭合集合」取前提），如果各写一份，两套口径必然漂移 —— 而口径一漂，
所有历史对比全部作废（项目已因口径反复吃过亏：值断言率 4.5% vs 32.4%，
差 7 倍；闭合率 0% 与 90% 被平均成 34%）。

★ 放契约层而不是 utils：契约层零依赖，回放床脚本（要求纯标准库、不拉
  进 LLM 客户端）与主流程可以**共用同一份**，两边不会各写一个版本。

四级闭合，严格程度递减
----------------------
    HARD_CLOSED   外部检查器真跑过且未判失败（`tool_ran=True`）
                  —— **唯一不可贿赂的**：不依赖任何模型意见
    SOFT_CLOSED   模型判定为正确，且有推导正文（LLM 判 LLM）
    OPEN          判定为错 / 未判定 / 无对应产物
    UNMAPPED      根本没有对应产物（早期批次没有子目标文件）

★ UNMAPPED 必须单列、**不计入闭合率分母**：把「没产物」算成「未闭合」，
  会让闭合率虚高或虚低，且掩盖数据缺失本身。

★ 只要 HARD_CLOSED 才允许进入下游上下文（「先证明、再声明」的落点）。
  SOFT_CLOSED 是模型意见，把它当事实只是把同源失效往下游搬了一层。
"""

__all__ = [
    "CLOSURE_HARD", "CLOSURE_SOFT", "CLOSURE_OPEN", "CLOSURE_UNMAPPED",
    "FAIL_WORDS", "closure_of", "is_hard_closed", "project_closed",
]

CLOSURE_HARD = "HARD_CLOSED"
CLOSURE_SOFT = "SOFT_CLOSED"
CLOSURE_OPEN = "OPEN"
CLOSURE_UNMAPPED = "UNMAPPED"

# 工具裁决里的失败词。
# ★ 沿用历史口径（含「错」），**不得**单方面收紧 —— 收紧会改变已归档的
#   回放结论，必须整批重跑并留痕。
#
# ★★ 2026-11-02 补三个词（"unsolved" / "sorry" / "admit"）：
#   这不是收紧，是**修一个假成功漏洞**。形式检查器的失败输出常写作
#   "unsolved goals ⊢ False"（实测见 2+2=5 的验证），其中不含 fail/error，
#   旧词表会把它判成硬闭合。更危险的是 `sorry`：带 sorry 的证明**编译能通过**，
#   若不识别，一个根本没证的骨架会被当成「已闭合」流进下游 ——
#   这正是「先证明、再声明」要防的那件事。
#   对历史结论的影响：归档回放里 `tool_ran` 无一条为真，故本改动
#   **不改变** HARD_CLOSED=0 / R5=109/109 的结论（已在重跑中核对）。
FAIL_WORDS = (
    "fail", "error", "失败", "错", "unknown", "timeout",
    "unsolved", "sorry", "admit",
)


def closure_of(item) -> tuple:
    """返回 (闭合层级, 依据文本)。

    item 是子目标结果条目（dict）；None / 空 ⇒ UNMAPPED。
    """
    if not item:
        return CLOSURE_UNMAPPED, "no_subgoal"
    tool_ran = item.get("tool_ran")
    tv = ("%s" % (item.get("tool_verdict") or "")).lower()
    if tool_ran is True and not any(w in tv for w in FAIL_WORDS):
        return CLOSURE_HARD, "tool_ran=True"
    ov = item.get("objective_verdict")
    has_drv = item.get("has_derivation")
    if ov == "correct" and has_drv is not False:
        return CLOSURE_SOFT, "objective_verdict=correct"
    return CLOSURE_OPEN, "objective_verdict=%s has_derivation=%s" % (ov, has_drv)


def is_hard_closed(item) -> bool:
    """是否工具级闭合（唯一可进下游的层级）。"""
    return closure_of(item)[0] == CLOSURE_HARD


def project_closed(items, key=None) -> list:
    """只保留工具级闭合的条目 —— 「先证明、再声明」的投影实现。

    items: 可迭代的条目（dict 或含 dict 的容器）
    key:   若条目是包装结构，用 key 取出真正用于判定的 dict

    返回**新列表**，顺序不变。未闭合者不是被标记，而是**不在结果里** ——
    这是刻意的：只要它还在列表里，下游就一定能「顺手」读到它，
    加多少标记都拦不住。
    """
    out = []
    for it in items or []:
        probe = it.get(key) if (key and isinstance(it, dict)) else it
        if is_hard_closed(probe):
            out.append(it)
    return out
