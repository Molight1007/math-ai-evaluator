"""P1 冒烟测试（临时脚本，验证后可删除）"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.deterministic import DeterministicChecker
from agent.formatter import FormatterAgent

c = DeterministicChecker(samples=50, attempts=200)

results = []

# 1) 恒等式代入采样
r1 = c.verify_by_substitution("x^2+2x+1=(x+1)^2", samples=50)
results.append(("恒等式(x+1)^2", r1["verdict"], r1["evidence"]))

# 2) 反例搜索：n^2>=n 找不到反例
r2 = c.search_counterexample("n^2>=n", attempts=200)
results.append(("n^2>=n 无反例", "NOT found" if not r2["found"] else "FOUND(BUG)", str(r2)))

# 3) 反例搜索：n^2<n 应找到反例
r3 = c.search_counterexample("n^2<n", attempts=500)
results.append(("n^2<n 有反例", "found" if r3["found"] else "NOT found(BUG)", str(r3.get("counterexample"))))

# 4) 反例搜索：x^2>=0（实数恒真，无反例）
r4 = c.search_counterexample("x^2>=0", attempts=200)
results.append(("x^2>=0 无反例", "NOT found" if not r4["found"] else "FOUND(BUG)", str(r4)))

# 5) check_answer 方程代入：正确答案 / 错误答案
r5a = c.check_answer(None, "解方程：x^2-5x+6=0", "2")
r5b = c.check_answer(None, "解方程：x^2-5x+6=0", "5")
results.append(("方程 ans=2", r5a["verdict"], r5a["evidence"]))
results.append(("方程 ans=5", r5b["verdict"], r5b["evidence"]))

# 6) 定义式不误杀
r6 = c.check_answer(None, "已知函数 f(x)=x^2-5x+6，求 f(2) 的值", "0")
results.append(("定义式不误杀", r6["verdict"], r6["evidence"]))

# 7) 数值回溯
results.append(("backtrack 1/3", str(c.numerical_backtrack("1/3")), ""))

# 8) Formatter._judger_friendly
f = FormatterAgent._judger_friendly
results.append(("jf 因此答案是42", repr(f("因此答案是：42")), ""))
results.append(("jf boxed", repr(f(r"$\boxed{3}$")), ""))
results.append(("jf (A)", repr(f("(A)")), ""))
results.append(("jf 故选 B", repr(f("故选 B")), ""))
results.append(("jf spaces", repr(f("2   3  4")), ""))
results.append(("jf long mixed", repr(f("答案是 42，其中计算过程省略" * 30)), ""))

for name, verdict, extra in results:
    print(f"{name:<16} -> {verdict}  {extra}")

# 通过/失败汇总
fails = [n for n, v, _ in results if "BUG" in v or v in ("fail",)]
print("\nFAILS:", fails if fails else "无")
