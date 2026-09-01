# LeanSearch v2 方法可用性评估（逐条）

> 编制：2026-08-31　论文：*LeanSearch v2: Global Premise Retrieval for Lean 4 Theorem Proving*
> （arXiv:2605.13137v2，Gao et al.）　本地副本：`papers/LeanSearch_v2.pdf`
> 判定口径：**能用 = 已落地或可在 9/12 冻结前落地；不能用 = 超算力/超约束/不可替代**。

---

## 总览：论文两大模式

```
Standard mode（标准模式）  ← 已通过官方 API 使用（leansearch.net）
    └─ 非形式化语料 + embedding–reranker 流水线
Reasoning mode（推理模式） ← 核心可借鉴部分
    └─ sketch 生成 → 子查询 → filter(可空集) → judge → 反馈修订（≤3 轮）
```

---

## 一、Standard mode（标准模式）

| # | 方法组件 | 我们能否用 | 判定与理由 |
|---|---|---|---|
| S1 | **本地依赖提取（Jixia）**：从 Mathlib 提取声明+依赖图 | ❌ 不用 | 官方已开源成品语料（HF JSONL），无需自建 |
| S2 | **自底向上层级非形式化**：Qwen3-32B 把声明转自然语言，依赖感知 | ✅ **能用（官方开源成品）** | **2026-08-31 修正**：官方发布现成语料 `FrenzyMath/lsv2-mathlib-v4.28.0-rc1-jsonl`（每条声明：kind/签名/非形式化描述/依赖，Apache 2.0）。**不用自己跑 Qwen3-32B**，直接下载解析即可当离线知识库/RAG 用 |
| S3 | **Qwen3-Embedding-8B 编码检索**：query/语料 cosine 相似度取 top-50 | ✅ 能用（间接） | **官方 API 已封装**，我们 `lean_search.py:235` 调的 `leansearch.net/search` 就是它；另官方也开源预嵌入 cuVS 索引（`...-cuvs`） |
| S4 | **Qwen3-Reranker-8B 重排** top-50 | ✅ 能用（间接） | 同上，官方 API 内部完成；无领域微调 → 通用性好，可放心信任 |
| S5 | **kind-aware 提示**（definition 类特殊处理） | ✅ 能用（间接） | 官方 API 内部；我们不感知细节 |
| S6 | **自建全套（S1-S5）** | ❌ 不能用 | 本地 serve 需 **≥2 块 GPU**（embedding 8B + reranker 8B）+ cuVS 索引；与官方 API 重复，没必要 |

**标准模式小结：**
- **语料本身：能用**（官方 HF 开源 JSONL，Apache 2.0）
- **检索服务：直接用官方 API**（官方部署版 reranker 是 4B 成本变体，够用）
- **本地复刻：不需要**（2 GPU + cuVS，重复建设）
- ⚠ **版本约束**：语料是 **Mathlib v4.28.0-rc1**，本地是 v4.31.0——命中定理名可能改名/删除，
  这是「命中≠编译通过」（今日 33 命中 0 采用）的可能原因之一，需配名字映射策略。

---

## 二、Reasoning mode（推理模式）——核心可借鉴部分

| # | 方法组件 | 我们能否用 | 判定与理由 |
|---|---|---|---|
| R1 | **Sketch 生成器**（论文用 Claude Sonnet 4.5）：定理 → 逐步证明提纲，每步含检索 query，不写 Lean 代码 | ✅ 能用（已落地部分） | 对应我们的 `blueprint_planner` / `sub_goal_solver`；**"子目标级独立查询"已落地**（8/29 4087a5e ②） |
| R2 | **每步子查询发标准模式** | ✅ 已落地 | 同上 |
| R3 | **Document filter（可返回空集）**：LLM 逐个候选判定相关/不相关，无用时返回 ∅ | ⚠️ **部分能用——只落地了空集信号，没落地逐候选判定** | 8/29 只实现了"检索无结果时告知空集"（4087a5e ①）；**"对返回的 top-k 逐条判相关/不相关"没有做**，检索结果直接注入求解上下文 |
| R4 | **Feasibility judge**：汇总所有步的过滤结果，判断整个 sketch 是否可被库支撑（二值） | ⚠️ 部分可用 | 未实现"judge 判断可支撑性"；我们只有预算版反思循环（见 R5） |
| R5 | **反思修订循环**：judge 拒绝 → 结构化反馈（哪步失败、为何）→ sketch reviser 修订，**最多 3 轮** | ✅ 能用（预算版已落地） | 对应 `deep_revise_rounds 1→2`（4087a5e ③）；论文 3 轮、我们 2 轮（预算约束） |
| R6 | **输出池化**：按 nDCG 折扣合并各步结果 + 去重 | ⚠️ 未落地 | 我们现在 top-k=5 直接注入，**没有"按步合并+去重+rank 折扣"** |
| R7 | **用 Claude Sonnet 4.5 / Kimi K2 做 sketch/filter/judge** | ❌ 不能 | 模型限定 Intern-S，只能用 Intern 替代（预算版已做） |

**推理模式小结：我们落地了 R1/R2/R5，缺 R3（逐候选 filter）与 R4（judge）与 R6（池化）——而 R3/R4 恰恰是论文 reasoning mode 的核心。**

---

## 三、与"33 命中 0 采用"的直接对应（重要）

论文 reasoning mode 的成败关键在 **filter → judge → 反馈** 闭环：

> “The filter may return an empty set: when no candidate is genuinely useful… This empty
> signal allows the judge to distinguish ‘the retriever found support’ from ‘the retriever
> found nothing useful’.”

而我们当前实现 = **只取 top-k 直接注入，没有任何"这条候选真有用吗"的判定**。结果：
- 今日 A_base 实测：检索触发 5/30、命中 33 条、**编译通过 0 条**（adopted=0）
- 高度吻合：**注入的是未过滤的低相关候选**，模型拿到也没法用，Lean 编译全挂

**可执行的改进方向（低成本、直接对应 R3）**：
> 给 top-k 加一个**轻量 filter**：用一次 Intern LLM 调用，对每个候选输出「相关/不相关」，
> 不相关的丢弃（或显式告知空集），只把相关的注入。`#46` 的"命中"定义顺势升级为
> **「filter 后仍保留」才算命中**——与论文的 ∅ 信号语义对齐。

---

## 四、不能用清单（超约束，明确排除）

| # | 组件 | 为什么不能用 |
|---|---|---|
| U1 | 自建非形式化 Mathlib 语料（Qwen3-32B 批处理） | 全量 Mathlib 数十万声明，算力/时间超约束 |
| U2 | 自建 embedding + reranker（Qwen3-8B×2 + 索引） | 资源超约束；官方 API 已提供，重复建设 |
| U3 | 复刻 MathlibQR（946 查询）/ MathlibMPR（69 定理专家标注） | 无专家标注资源；官方 API 已用其成果 |
| U4 | Claude Sonnet 4.5 / Kimi K2 作 sketch/filter/judge | 比赛模型固定 Intern-S，只能 Intern 替代 |
| U5 | 论文下游"固定 prover 循环"对比（20% vs 16% vs 4%） | 需 Lean prover 端到端集成；**比赛平台无 Lean**，仅本地可测（#47 正在规划） |

---

## 五、行动建议（按性价比）

| 优先级 | 动作 | 对应组件 | 成本 |
|---|---|---|---|
| 1 | **补 R3 轻量 filter**（top-k 逐条相关/不相关判定，不相关丢弃/空集） | R3 | 0.5 人天 |
| 2 | 修 #44 `total_ms` 埋点缺口（检索耗时占比才能算） | 工具 | 0.25 人天 |
| 3 | 跑 #47 证明题基准（60 题，`build_proof_bench`） | 验证 | 1 轮批跑 |
| 4 | #46 top-k 定参（把"命中"升级为"filter 后保留"） | R3+R6 | 随 1 一起 |
| 5 | R6 按步合并去重池化 | R6 | 0.5 人天（若 1/3 显示有增益再做） |
| 6 | R4 judge 可支撑性判断 | R4 | 1 人天（依赖 1/3 结果，非必需） |

> 先补 R3（filter），因为它是**论文 reasoning mode 与"零采用"数据之间的唯一缺口**，
> 且成本最低。R4/R6 视 R3 后的数据再定。
