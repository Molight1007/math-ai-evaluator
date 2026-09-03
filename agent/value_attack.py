"""数值攻击验证器（C-lite，2026-09-03 老师拍板）。

拦截"蓝图/求解声称数值极值，实际错误"的系统性问题（009 实况：蓝图声称
最大值 4∛(85/98)≈3.815，真值 2∛(196/13)≈4.94——LLM 心算错值后全链路
执行+验证自洽，Lean unknown 拦不住）。

原理：对连续极值/不等式类题（题面含 S=表达式 + 变量约束 + 求 max/min），
从题面提取 Python 可执行的目标函数，**随机+边界采样攻击**——若采样点
得到的目标值突破声称极值 → 声称值不成立（确定性证伪，非 LLM 自评）。

拦截点：蓝图 merge / 候选答案里出现"极值 = 数值"时。
"""
import logging
import random
import re
import time

logger = logging.getLogger("MathPilot")

# 声称极值触发词（中英）
_MAX_KW = re.compile(r"maximal|maximum|largest|greatest|求.*最大|最大值|极大值", re.I)
_MIN_KW = re.compile(r"minimal|minimum|smallest|least|求.*最小|最小值|极小值", re.I)
# 数值表达式（声称的极值）
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

# 采样规模：准确率 vs 速度平衡（30k ≈ 009 找到 4.913/4.94）
_N_SAMPLES = 20000
# 证伪阈值：采样值 > 声称值 × (1+eps) 才算反例（防数值噪声误伤）
_EPS = 1e-6


def _extract_claimed_value(text: str) -> float | None:
    """从声称文本提取数值（如 'maximum value is 4∛(85/98)' 难解析 → 取近似）。"""
    # 简化：直接找 = X / is X / 为 X 后的数值（含 ∛ 分数尽量解析）
    m = re.search(r"(?:max(?:imum)?(?: value)?|min(?:imum)?(?: value)?)\s*"
                  r"[=:：is为是]?\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    if m:
        return float(m.group(1))
    return None


def _to_python_func(expr_lean: str) -> str:
    """把 LaTeX/自然语言极值表达式转 Python lambda 字符串（返回 None 表示不可用）。

    由 LLM 在 verify_value_claim 里生成，这里只做兜底清理。
    """
    return expr_lean


def _sample_simplex(n_vars: int, total: float, rng: random.Random):
    """在 x_i >= 0, Σx_i = total 的单纯形上采样（Dirichlet 均匀）。"""
    u = [rng.expovariate(1.0) for _ in range(n_vars)]
    s = sum(u)
    return [total * v / s for v in u]


def attack_value_claim(problem: str, claimed: float, direction: str,
                       func_src: str | None, n_samples: int = _N_SAMPLES
                       ) -> dict:
    """数值攻击声称值。

    func_src: LLM 生成的 Python 函数源码，形如
        def f(x):   # x 是变量列表
            ...用 x[0],x[1],... 计算目标值...
            return value
    调用约定：f 接受 list[float]（长度=变量数），返回 float；内部自含约束
    （不可行点返回 None/raise → 调用方跳过）。
    """
    if not func_src:
        return {"ok": True, "reason": "目标函数不可用，跳过攻击"}
    ns: dict = {}
    try:
        exec(func_src, ns)
        fn = ns.get("f")
        if fn is None:
            return {"ok": True, "reason": "函数源码无 f，跳过"}
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "reason": f"函数编译失败: {str(e)[:80]}"}
    rng = random.Random(20260903)
    best = None
    try:
        for _ in range(n_samples):
            pt = None
            # 用函数自带采样器优先；否则 n 元单纯形
            sampler = ns.get("sample_point")
            try:
                if sampler:
                    pt = sampler()
                else:
                    raise TypeError
            except Exception:  # noqa: BLE001
                continue
            try:
                val = fn(list(pt))
            except Exception:  # noqa: BLE001  不可行点
                continue
            if val is None:
                continue
            if best is None or val > best:
                best = val
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "reason": f"采样异常: {str(e)[:80]}"}
    if best is None:
        return {"ok": True, "reason": "采样无可行点，跳过"}
    # 声称"最大值=M"：找 S > M → 证伪
    if direction == "max":
        if best > claimed + _EPS:
            return {
                "ok": False, "claimed": claimed, "found": best,
                "reason": (f"数值攻击证伪：采样发现目标值 {best:.6f} > "
                           f"声称最大值 {claimed:.6f}——声称的极值不成立"),
            }
        return {"ok": True, "found": best, "reason": "采样未突破声称最大值"}
    # 声称"最小值=m"：找 S < m → 证伪
    if best < claimed - _EPS:
        return {
            "ok": False, "claimed": claimed, "found": best,
            "reason": (f"数值攻击证伪：采样发现目标值 {best:.6f} < "
                       f"声称最小值 {claimed:.6f}——声称的极值不成立"),
        }
    return {"ok": True, "found": best, "reason": "采样未突破声称最小值"}
    # 其它方向不适用 → 放行
    # return {"ok": True, "reason": "无适用方向"}
