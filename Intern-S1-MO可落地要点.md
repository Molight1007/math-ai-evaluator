# Intern-S1-MO 可落地要点（对标 88.39 分标杆）

> 编制：2026-08-31　来源：arXiv:2512.10739v3（上海 AI Lab）
> 目的：gitcode 上找不到「梁子/clrh」的公开仓库，**这是唯一能反推高分做法的公开资料**。
> 原则：**只抄结构，不抄数值**——他们的单题预算是我们的几十倍，直接抄轮数会当场超时。

---

## 0. 先看清楚对方的预算（决定什么能抄）

| | Intern-S1-MO（论文实测） | 我们（比赛约束） |
|---|---|---|
| 单题 token | **≈512K**（64K 的 8 倍） | 受 112 题 / 6.5h 约束，约数万级 |
| CMO 实测 | 每天 4.5h 做 **3 题**（≈1.5h/题） | 6.5h 做 **112 题**（≈3.5min/题） |
| 主搜索 | 256-shot 并行 × 最多 12 轮 | 并发 3，单题最多 1200s |
| 修订循环 | 8-shot × **24 轮** | `deep_revise_rounds = 2` |
| 引理验证 | 8-shot 并行 | 无（本次批跑才首次有埋点） |

**结论：轮数、shots、修订次数一律不能抄。** 能抄的是**三条结构性做法**，
它们与预算大小无关，且都能在 9/12 冻结前完成。

---

## 1. 【强推·低成本】验证器输出「第一个错误步骤的索引」

**论文做法**（A.3 Lemma Verify）：

> “identify the **index of the first incorrect step**. The index starts at 0 for the
> first step. If the proof is entirely correct, you should output **-1**.”
> 输出格式：`\box{STEPk}`（如 `\box{STEP2}`），全对为 `\box{STEP-1}`。

**为什么这条最值钱**：我们现在的验证器输出的是"通过/不通过 + 错误类别"，
是**整体性判断**；模型拿到反馈后不知道该改哪一步，只能重写，重写又引入新错误
（这正是"revise 越改越差"的来源，缺陷诊断里 `attempts≥4 → 30%` 的部分原因）。

改成**定位到步号**之后：
- revise 可以"只改第 k 步及其之后"，保留前面正确的推导
- 可以直接统计"错误集中在第几步"，反推是理解错还是计算错（补 #11/#16 的二分类）

**落地位置**：`agent/verifier.py` + `agent/adversarial_verifier.py`
（对抗验证器已有 6 类 checklist，把输出从「有错/没错」升级为「首个错误步号 + 类别」）。

**成本**：约 0.5 人天。**建议排进第一梯队，紧接 #16 之后。**

---

## 2. 【强推·低成本】「部分结果」轮 + 输出即停

**论文做法**（A.1 Lemma Search 的 Guiding Principles）：

> “If you cannot provide a complete solution, you must provide any significant
> **partial results** that you can prove with full rigor.”
> “Do not guess or provide solutions with logical gaps.”
> “After outputting the lemmas, you should **end your response immediately**.”

**我们的差距**：现在每一轮都被要求产出完整答案。做不出来的题会硬凑一个答案，
既浪费 token 又会污染候选池（缺陷诊断：`incomplete` 错误、`答案>60 字符`抽到推理文本）。

**落地**：给 solver 加一条 `partial` 通道——
- 提示词允许声明「本轮只给出已严格证明的部分结论」
- 声明 partial 时**不再要求 `\boxed{}` 最终答案**，改为输出引理块后立刻结束
- orchestrator 识别 partial → 把引理并入 lemma_memory → 进入下一轮，而不是判失败

**成本**：约 1 人天（要动 solver 提示词 + orchestrator 的候选判定）。
风险：可能与 #51 答案定型冲突，需要 partial 路径显式豁免 boxed 要求。

---

## 3. 【推荐·低成本】引理去重：只收「新」引理

**论文做法**（A.2 Summarizer 的 Novelty 原则）：

> “Extract **only** lemmas first introduced or proven within the Model's Thinking
> Process. **Do not include** lemmas from the Provided Lemmas if the model utilises them.”
> 修正版与原引理**共享编号**，加后缀 `-fixed`。

**我们的差距**：`lemma_memory` 现在没有"新颖性"过滤，同一条不等式可能在多轮里
被反复入库，把上下文撑大——而上下文一大，模型细节注意力就衰减（#18 关注的正是这个）。

**落地**：入库前做一次查重（lexical overlap + 语义相似，论文用的就是这个组合，
不需要 embedding，字符串归一化 + 符号重写就能覆盖大部分）。

**成本**：约 0.5 人天。**可与 #13 跨题记忆合并做**——跨题记忆更需要去重，
否则题库跑一轮下来引理库会爆炸。

---

## 4. 【记录·暂不做】明确超出当前条件的部分

| 论文做法 | 为什么现在不做 |
|---|---|
| OREAL-H 强化学习训练 | 需要训练算力与数据管线，9/15 前不可能；可写进论文的 future work |
| 256-shot 并行搜索 × 12 轮 | 单题预算差两个数量级，照抄必定超时 |
| 8-shot × 24 轮修订 | 同上；我们 `deep_revise_rounds=2` 是预算约束下的合理值 |
| Conjugate Reward（n=4, k=4 → 0.996） | 属于 RL 奖励建模，与推理时无关 |
| 引理依赖图（Lemma Dependency Graph） | 用于 RL 的信用分配；若放弃 RL，收益有限 |

---

## 5. 一个可以直接写进材料的对照点

论文里有两个数字可以直接拿来做**答辩叙事**：

- **引理压缩比 ≈ 64:1** —— 说明"把推理历史压成引理"不是锦上添花，
  而是突破上下文限制的**必要手段**（他们靠它把 64K 拉到等效 512K）。
  我们已有 `lemma_memory`，这条可以直接对标。
- **IMO2025 剩余错误**：“remaining gaps mainly stem from problems requiring
  **highly customized transformations or impromptu key constructions**” ——
  即连 SOTA 也承认剩下的题靠"灵光一现"，不是系统搜索能解决的。
  这可以用来解释我们为什么不应该追求 100%，而应该**把能拿的分拿稳**。

---

## 6. 建议的插入位置（不打断今天的批跑）

> ⚠ 以下均为**代码改动**，必须等今天三组批跑结束后再做，否则会破坏 A/B 可比性。

| 序 | 动作 | 来源 | 成本 | 建议截止 |
|---|---|---|---|---|
| 1 | 验证器输出首个错误步号 `\box{STEPk}` | 本文 §1 | 0.5 人天 | 9/3 |
| 2 | 引理新颖性去重 | 本文 §3 | 0.5 人天 | 9/5（并入 #13） |
| 3 | solver 的 partial 轮 + 输出即停 | 本文 §2 | 1 人天 | 9/8（需与 #51 协调） |

三者都完成后，用今天的 **A_base 组作为对照基线**再跑一轮 30 题验证增益。
