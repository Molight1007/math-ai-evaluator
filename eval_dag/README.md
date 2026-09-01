# eval_dag — 手工 DAG 启发型题集（Step 4）

> 目的：验证 **动态 DAG 闭环**（DagReviewer 评审 + 整树重生成，老师要求 #34）在
> 「蓝图容易画错、但重生成能救回」的场景下的增益。与本地 45 题基准互补。

## 为什么是这 12 道

DAG 蓝图对这三类题最容易画错，且错误类型正好能被评审/重生成机制捕获：

| 特征 | 含义 | 蓝图错误形态 | 动态闭环救回方式 |
|---|---|---|---|
| `multi_case` | 证明需分情况讨论（函数方程先定 f(0)/常数，再推一般形式） | 蓝图漏 OR 分支 / 分支条件错误 | 子目标失败 → 评审 reject → 整树重生成补分支 |
| `lemma_needed` | 需先证一个辅助引理（anticipatory lemma）才能推进主证明 | 蓝图缺 AND 依赖节点 | 主证明卡死 → 评审提示缺依赖 → 重生成插入引理节点 |
| `equiv_trap` | 中间有易错等价变换（平方/开方/取倒数/代换） | 分解出的子目标本身不等价 | 叶子验证失败 → 评审识别为错误分解 → 重生成修正 |

## 题单（12 题，全部有 gold 答案可判分）

| problem_id | domain | DAG 特征 | gold 答案摘要 |
|---|---|---|---|
| imo-bench-algebra-003 | Algebra | multi_case, lemma_needed | g(x)=2x³+c, −2x³+c |
| imo-bench-algebra-006 | Algebra | multi_case | P(x)=−1, x+1 |
| imo-bench-algebra-013 | Algebra | multi_case, equiv_trap | Q(x)=−2, 2x−2 |
| imo-bench-algebra-025 | Algebra | multi_case | A(x)=1−x, 1+2x, 1−x² |
| imo-bench-algebra-029 | Algebra | lemma_needed, equiv_trap | g(x)=⅓((2x)^a+(2x)^−a) |
| imo-bench-algebra-017 | Algebra | equiv_trap, multi_case | (−∞,0)∪{1/2} |
| imo-bench-algebra-027 | Algebra | equiv_trap | (−∞,−4)∪(−4,−8/3) |
| imo-bench-algebra-028 | Algebra | lemma_needed, multi_case | (−∞,0] |
| imo-bench-algebra-008 | Algebra | lemma_needed, multi_case | −2023/2024² |
| PB-Basic-005 | Algebra | multi_case, lemma_needed | P(x)=x⁴+ax²+6, x² |
| PB-Basic-007 | Algebra | multi_case, equiv_trap | n=2, (a0,a1,a2)=(−1,1,−1) |
| imo-bench-combinatorics-064 | Combinatorics | multi_case, lemma_needed | 无正整数解 |

特征覆盖：`multi_case` 10 / `lemma_needed` 6 / `equiv_trap` 5（一题可多特征）。

## 使用方式

```bash
# A 组（对照组）：本地 45 题静态 DAG（当前用户_agent 配置）
# B 组（实验组）：动态 DAG 闭环开启

# 直接跑评测（run_eval.py 读 jsonl，判分用 answers_match）
python run_eval.py --test_file eval_dag/problems.jsonl --output results/dag_dynamic.jsonl --concurrency 3
```

A/B 干净对照（静态 vs 动态 DAG，`--enable_dag_replan` 开关已加入 run_eval.py）：

```bash
# off：静态 DAG（旧行为，蓝图画错即失败，不评审不重生成）
python run_eval.py --test_file eval_dag/problems.jsonl \
  --output results/dag_off.jsonl --use_blueprint true --enable_dag_replan false

# on：动态 DAG（DagReviewer 评审 + 整树重生成闭环）
python run_eval.py --test_file eval_dag/problems.jsonl \
  --output results/dag_on.jsonl --use_blueprint true --enable_dag_replan true
```

对照设计（沿用配对判定纪律：net≥3 且 a≥2b 才开，只信 ≥5pp 差异）：
- **off**：关闭 DagReviewer 重生成（= 旧行为，一次蓝图画错就失败）
- **on**：开启评审 + 整树重生成
- 统计 12 题正确数 / 逐题 gained / lost / 净收益

## 与主基准的关系

- 本地 45 题：总体能力（Step2 self-improve 等全局杠杆的验证场）
- eval_dag 12 题：**定向验证 DAG 动态化**（老师 #34 的验收场）
- 平台提交前：先本地 45 题 A/B 确认无回退，再 eval_dag 确认 DAG 增益

## 来源

题目全部取自本地题库（IMO-ProofBench / IMO-AnswerBench），**非新编**，保证答案权威。
gold 答案与 run_eval.py `answers_match` 判分兼容（已自检 12/12）。
