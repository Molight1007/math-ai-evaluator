# MathPilot 智能体升级架构设计

> **设计目标**：在封闭单模型环境（平台只注入 Intern-S 一个 client）下，把"错题→盲目重写"升级为
> **搜索 → 判分 → 错因反馈 → 定向修订** 的闭环，系统性提升 Intern-S 的"写题能力"（最终答案准确率）。
>
> **设计来源**：
> - **解题策略借鉴 Intern-MO**（[Long-horizon Reasoning Agent for Olympiad-Level Mathematical Problem Solving, arXiv 2512.10739](https://ar5iv.labs.arxiv.org/html/2512.10739)）：多候选多样性、rubric 判分、错因反馈修订、自验证闭环；
> - **编排理念借鉴 DeepSeek Harness**（[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[架构解读](https://www.leiphone.com/category/ai/u43j44fx6Rly10nI.html)）：阶段化工作流、专业子智能体、共享状态、trace 即产品。
> - **不抄代码、抄机制**：全部用现有纯 Python 架构轻量实现，平台沙箱零新依赖。

---

## 0. 现状盘点（先对齐事实）

### 0.1 平台侧硬约束（官方规则，不可突破）

| 约束 | 值 | 对本设计的含义 |
|---|---|---|
| 模型 | 仅平台注入的 Intern-S client | **无第二个模型**，双引擎判分不可行，只能任务视角多样性 |
| 并发 | 3（独立题目进程） | 题间无共享状态，题内可多线程 |
| 单题硬限 | 1200s | 现有默认 300s 软预算，必须保住 |
| Agent 总时限 | 6h（21000s） | PaperPacer 全卷时间池已实现 |
| 限流 | RPM 30 / TPM 150000 | 单题 LLM 调用 ≤ 档位预算（fast 6 / standard 15 / deep 30） |
| 判分 | 官方 Judger 黑盒 | final_response 格式直接影响匹配成功率 |
| 提交源 | `赛事提交版/` 独立副本 | **所有改造以赛事提交版为准**，根目录 `agent/` 只做本地实验 |

### 0.2 现有流水线（赛事提交版）

```
入口 solve(problem, metadata)
 └─ PaperPacer(时间池) → Classifier(关键词优先+LLM兜底)
    → 快车道(SymPy短路) → DifficultyRouter(难度分档)
    → Solver(温度分层采样3候选 / 证明通道 / 子目标分解)
    → 截断续写 → Verifier(每候选1票 + 等价聚类共识 + 条件playoff)
    → 全0票兜底直答 → Formatter(选簇+终检修复) → final_response
```

**现状短板（对应本设计要补的洞）**：

| # | 短板 | 证据 |
|---|---|---|
| S1 | **候选多样性不足**：温度分层（0.1/0.3/0.5）+ 弱扰动提示，同一模型三份输出大概率同构 | solver.py `_STRATIFIED_TEMPS` |
| S2 | **判分粗糙**：二元 VERDICT A/B，无置信度分级、无错因结构化输出 | verifier.py `_vote_one` / prompts/verifier.py |
| S3 | **修订盲目**：revise 提示词只带"错误列表"，不带错因定位与修正方向；且 `feedback` 提取链路已被注释关闭 | verifier.py L500 `feedback: ""`；prompts/revise.py |
| S4 | **同源一起错无解**：判分器与解题器同一模型同一视角，一起错时投票形同虚设 | verifier.py 注释自认痛点 |
| S5 | **确定性验证缺失**：SymPy 只用于快车道求解，没有用于**答案验证**（代入采样/反例） | utils/sympy_tools.py 用途单一 |
| S6 | **输出格式赌运气**：final_response 依赖模型自觉，黑盒 Judger 匹配率不稳定 | formatter.py 靠正则修补 |

---

## 1. 总体架构：阶段机 + 专业子智能体（DSH 编排 × Intern-MO 策略）

### 1.1 阶段机（借鉴 DSH workflow 的阶段化）

```
INIT → CLASSIFY → FAST_PATH ──命中→ FINALIZE → EXIT
                     │
                     ▼
                  SOLVE(多视角采样) → COMPLETE(续写)
                     │
                     ▼
                  JUDGE(rubric判分 + 确定性验证 + 低温复算)   ◀── 核心改造
                     │
                     ▼
                  ARBITRATE(决策表)
                   ├─ accept ───────────────→ FINALIZE → EXIT
                   ├─ revise(错因定向修订) ──→ SOLVE(修订视角) ─→ JUDGE(复审)  [≤ max_revise_rounds]
                   ├─ arbitrate(分歧仲裁) ───→ JUDGE(仲裁轮)
                   └─ fallback(兜底直答) ────→ FINALIZE → EXIT
```

- 每个阶段有**进入条件**（预算/档位/时间剩余）与**出口记录**（trace 结构化）；
- 阶段不新增文件级复杂性：仍在 `Orchestrator.run()` 内显式编排，只是把隐式 if 分支升级为可观测的阶段记录。

### 1.2 专业子智能体分工（借鉴 DSH 子智能体理念）

| 子智能体 | 职责 | 状态 |
|---|---|---|
| Classifier | 题型/领域识别 | 现有，不动 |
| DifficultyRouter | 难度分档 fast/standard/deep | 现有（赛事提交版），复用 |
| PaperPacer | 全卷时间池 + 动态预算帽 | 现有（赛事提交版），复用 |
| **Solver** | 多视角采样 + 错因定向修订 | **改造** |
| **Verifier** | rubric 判分 + 确定性验证 + 共识聚类 | **改造** |
| **DeterministicChecker**（新） | SymPy 代入采样 / 反例验证 / 数值回溯（0 LLM 预算） | **新增** |
| **Arbitrator**（并入 Orchestrator） | 决策表：采纳/重解/仲裁/兜底 | **新增逻辑** |
| Formatter | 选优 + 黑盒 Judger 友好输出 | **改造** |

---

## 2. 模块接口设计

> 全部遵循现有规范：`BaseAgent` 子类、`TaskContext` 黑板、`Budget` 预算、`record()` trace。
> 新增模块均**零 LLM 调用**或**全 prefill 秒回**。

### 2.1 新增 `agent/deterministic.py` —— 确定性验证通道（S5 的解）

```python
class DeterministicChecker:
    """确定性验证通道：纯本地计算，不消耗 LLM 预算、不触发限流。

    设计来源：DeepSeek-Harness 的 code-runner 判分哲学 + Intern-MO 的自验证。
    """

    def check_answer(self, ctx: TaskContext, problem: str, answer: str,
                     domain: str | None = None) -> dict:
        """对候选答案做确定性旁证，返回:
        {"verdict": "pass"|"fail"|"unknown",
         "confidence": float,          # 0~1，仅旁证强度
         "evidence": str,              # 可读证据（代入采样结果/反例/回溯链）
         "method": str}                # substitution|counterexample|numerical_backtrack
        """

    def verify_by_substitution(self, expr: str, variables: dict,
                               samples: int = 100, tol: float = 1e-6) -> bool:
        """表达式代入采样验证：随机采样变量组，逐组数值核对左右式/等式成立。"""

    def search_counterexample(self, statement: str, variable_ranges: dict,
                              attempts: int = 200) -> dict:
        """反例搜索：对候选答案声称的一般性命题尝试数值反例。
        返回 {"found": bool, "counterexample": dict|None, "attempts": int}"""

    def numerical_backtrack(self, answer: str) -> str | None:
        """数值回溯：把候选答案代回问题中的关键等式，输出可复现的数值链。"""
```

接入点：`Verifier.run()` 在 rubric 判分**之前/之后**并行执行（线程池），结果作为投票旁证——
- `pass` → 该候选判分置信度 +0.2（封顶 1.0）；
- `fail`（真反例）→ **直接否决该候选**（绕过 LLM 判分，0 预算、100% 可复现）。

### 2.2 改造 `agent/verifier.py` —— rubric 判分 + 错因反馈（S2、S3 的解）

```python
# 新增：结构化判分（替代/增强二元投票）
def _vote_one_rubric(self, ctx, problem: str, candidate_text: str) -> dict | None:
    """一次 rubric 判分，prefill '{"' 引导 JSON，秒级返回。

    输出 schema（新增 prompts/verifier.py::VERIFIER_RUBRIC_*）：
    {"verdict": "A"|"B",                      # 正确/错误（A=接受）
     "confidence": 0.0~1.0,                   # 判分者自评置信度
     "error_type": "计算错误|概念错误|逻辑错误|结论错误|截断|无",
     "step_index": 3|None,                    # 出错步骤序号（可定位）
     "reason": "一句话错因（供 revise 定向修订）"}
    """

# 新增：反例挑战视角（任务视角多样性之一）
def _challenge_counterexample(self, ctx, problem: str, candidate_answer: str) -> str:
    """让模型生成一个潜在反例 → 交给 DeterministicChecker.search_counterexample 程序验证。
    只对'判分置信度低'或'0 票'的候选触发（预算守卫）。"""

# 改造：run() 主流程
def run(self, ctx, problem, candidates, use_clustering=True,
        use_scoring=False, is_proof=False, use_playoff=False,
        use_rubric=True, use_deterministic=True) -> dict:
    """流程：
    1) 每个候选并行执行 rubric 判分（1 次/候选，JSON prefill）
    2) 并行执行 DeterministicChecker（0 预算）→ 旁证加权 / 反例否决
    3) 对低置信度候选触发 playoff 低温复算（预算守卫，沿用现有）
    4) 等价聚类共识（沿用 AnswerCluster，不改）
    5) 输出 {cluster_data, verdicts(含 rubric 明细), best_cluster, feedback(错因)}
    """
```

### 2.3 改造 `agent/solver.py` —— 多视角采样 + 错因定向修订（S1、S3 的解）

```python
# 新增：视角采样提示库（替代纯温度分层）
_VIEW_HINTS = [
    ("direct",      ""),                                        # 视角0：直接求解
    ("substitute",  "提示：考虑换元/设未知数/参数化，先化简再求解。"),   # 视角1：换元
    ("geometric",   "提示：尝试从几何/图形/构造的角度重新理解问题。"),   # 视角2：几何
    ("algebraic",   "提示：尝试代数变形/因式分解/对称性简化。"),         # 视角3：代数
    ("backward",    "提示：尝试从目标倒推，先确定结论形式再找路径。"),   # 视角4：倒推
]
# 候选 i 使用 _VIEW_HINTS[i % len(_VIEW_HINTS)]，温度按视角微调
# 效果：同模型、同题、不同解题路径 → 错误模式去相关（弱独立采样）

# 改造：修订提示词（prompts/revise.py）
def _generate_revise(self, ctx: TaskContext) -> None:
    """REVISE_USER_TEMPLATE 升级为结构化错因注入：
    【错因定位】错误步骤序号 + 错误类型 + 一句错因
    【修正方向】验证器给出的正确方向提示
    【要求】新解答必须显式回应每条错因（"针对错因1：我改用..."）
    修订候选数 revise_sample_times=2，一个走原视角、一个换视角重解。
    """
```

### 2.4 改造 `agent/orchestrator.py` —— 阶段机 + 仲裁决策表（S4 的解）

```python
def _arbitrate(self, ctx: TaskContext, judge_result: dict) -> str:
    """决策表：返回 'accept' | 'revise' | 'arbitrate' | 'fallback'

    | 条件 | 决策 |
    |------|------|
    | 最佳簇置信度 ≥ 0.8 且确定性验证 pass | accept |
    | 最佳簇置信度 ≥ 0.6，无确定性 fail，预算/时间紧张 | accept（保产出） |
    | 最佳簇置信度 < 0.6 且 revise 轮次未耗尽 | revise（错因定向） |
    | 两候选簇势均力敌（|conf差|<0.2 且同规模）| arbitrate（低温复算+确定性验证裁决）|
    | 全部 0 票 或 预算耗尽 | fallback（沿用现有 direct_solve 兜底）|
    """
```

阶段记录：每个阶段 `self.record(ctx, "phase", ...)` 写入 `phase` 字段，构成"阶段机 trace"（trace 即产品）。

### 2.5 改造 `agent/formatter.py` —— 黑盒 Judger 友好输出（S6 的解）

```python
def _judger_friendly(self, answer: str) -> str:
    """输出规范化（纯规则，0 LLM 预算）：
    1. 最终答案单行前置（剥离解释段）
    2. 数值答案统一为最简形式（分数/小数/根式按题目语境保留一种）
    3. 表达式答案去多余空格、统一 LaTeX（\boxed 保留）
    4. 选项题输出纯选项字母
    """
```

**为什么重要**：官方 Judger 大概率是规则匹配（类似 `run_eval.py::answers_match`），
final_response 里混推理文字 = 匹配失败。这一步是**零成本提分项**，最先做。

### 2.6 新增 prompts：`prompts/verifier.py` 扩展

```python
VERIFIER_RUBRIC_SYSTEM   # 结构化判分：独立重算→对比→定位错因→输出JSON
VERIFIER_RUBRIC_TEMPLATE # 含【题目】【候选解答】【判分JSON schema】
VERIFIER_CHALLENGE_SYSTEM # 反例挑战：构造一个能推翻候选答案的具体数值反例
VERIFIER_CHALLENGE_TEMPLATE
```

---

## 3. 调用预算分配（最关键的一张表）

沿用赛事提交版 tier 系统：`tier_max_calls = {fast: 6, standard: 15, deep: 30}`。
**核心思想：预算不平均花，把"判分 + 修订"作为主战场，候选生成只保多样性下限。**

### 3.1 standard 档 15 次调用分配表

| 环节 | 调用数 | 说明 |
|---|---|---|
| 分类 | 0~1 | 关键词命中则 0（常见）；否则 LLM 兜底 1 |
| 快车道 | 0~1 | SymPy 求解成功即短路退出（常见 0） |
| **求解（视角采样）** | 3 | 3 个视角候选，1 次/候选（retry 走预算余量） |
| 截断续写 | 0~1 | 只续写最有希望 1 个（沿用现有） |
| **rubric 判分** | 3 | 每候选 1 次 JSON prefill（秒回，0.8s 级） |
| 确定性验证 | **0** | DeterministicChecker 纯本地 |
| 错因反馈 | 0~1 | 仅"最佳候选判错"或"聚类分歧"时触发 1 次 |
| **定向修订** | 2 | revise 2 个候选（原视角 + 换视角） |
| 修订复审 | 0~1 | 对修订候选 1 次 rubric |
| 预留 | 1~3 | playoff 低温复算 / 分歧仲裁 / 兜底直答 |

**合计 9~14 次，余量留应急**。相比现状（求解3 + 投票3 + 续写1 ≈ 7~8 次），
新增约 3~6 次全部是 **prefill 秒回型**（rubric/反馈/复审），单次 < 5s，不威胁 300s 软预算。

### 3.2 deep 档 30 次分配（难题）

| 环节 | 调用数 |
|---|---|
| 分类/路由/快车道 | 0~2 |
| 求解（视角采样，deep 3~4 视角） | 4 |
| 子目标分解 | 3 |
| 截断续写（deep 2 个） | 2 |
| rubric 判分（每候选 2~3 票，deep 投票=3） | 6~9 |
| 确定性验证 | 0 |
| 错因反馈 + 定向修订（2 轮） | 2 + 4 |
| 修订复审（2 轮 × 1~2） | 2~4 |
| playoff / 仲裁 / 兜底 | 2~4 |
| **合计** | **≤ 30** |

### 3.3 fast 档 6 次（应急/简单题）

分类 0~1 + 求解 2 + rubric 2 + 兜底 1 ≈ 6。跳过修订/复审/确定性（确定性可保留，0 预算）。

### 3.4 预算守卫（沿用 + 强化）

- `Budget.can_spend()` 现有机制不动；
- **新增"保答案预留"**：任何档位最后 1 次调用永远留给 `direct_solve` 兜底，杜绝预算耗尽无输出；
- PaperPacer 应急模式（总预算 >75%）：强制 fast 档、关闭修订/复审（现有 `_emergency` 逻辑扩展）。

---

## 4. 关键机制详解

### 4.1 任务视角多样性（替代不可行的模型多样性）

封闭环境没有第二个模型，"同源一起错"的解法是**让错误模式去相关**：

| 机制 | 错误模式 | 去相关对象 |
|---|---|---|
| 视角采样（换元/几何/代数/倒推） | 单一路径的局部错误 | 候选间 |
| rubric 判分（独立重算再对比） | 解题器的自我确认偏差 | 判分 vs 解题 |
| 低温复算 playoff | 高温度采样的随机错误 | 候选 vs 复算 |
| 反例挑战 + 程序验证 | LLM 判分盲区（"看起来对"） | 判分 vs 硬证据 |
| 确定性代入采样 | 符号错误/计算错误 | 一切 LLM 判断 |

### 4.2 rubric 判分 JSON schema 与置信度融合

```
候选最终置信度 = 0.60 × rubric_verdict + 0.25 × 确定性旁证 + 0.15 × playoff 复算
```
- rubric `A` + 确定性 pass + 复算一致 → 置信度 ≈ 0.95 → accept
- rubric `B` + 确定性 fail → 置信度 ≈ 0 → 否决
- rubric `A` 但确定性 unknown + 复算不一致 → 置信度 ≈ 0.55 → 走仲裁
- 多票时（deep 档）按票统计，沿用 `AnswerCluster` 共识。

### 4.3 错因定向修订闭环（对比现状）

```
现状：verifier 判 B → revise 只知道"错了" → 模型盲重写（S3）
升级：verifier 判 B + error_type + step_index + reason
     → revise prompt 注入【错因定位】【修正方向】
     → 模型必须逐条回应错因 → 复审 rubric 确认是否修复
```

每轮修订产出"修订前后 diff"记录进 trace（trace 即产品，答辩可展示闭环过程）。

### 4.4 仲裁决策表（已在上文 2.4，执行顺序）

仲裁轮不新增"模型间辩论"（封闭环境无第二模型），而是 **三证据汇审**：
rubric 置信度 + 确定性验证 + 低温复算，三者投票，多数决。

---

## 5. 与现有代码的映射表（改造清单）

| 文件 | 改动 | 类型 | 风险 |
|---|---|---|---|
| `agent/deterministic.py` | 新增，纯本地 | 新增 | 低（零 LLM） |
| `agent/verifier.py` | 新增 `_vote_one_rubric`/`_challenge_counterexample`；`run()` 接线 deterministic；恢复 feedback 输出 | 改造 | 中（默认关，A/B 开） |
| `agent/solver.py` | `_VIEW_HINTS` 视角采样替换温度分层；`_generate_revise` 错因结构化 | 改造 | 中 |
| `agent/orchestrator.py` | 阶段机记录 + `_arbitrate` 决策表 + 保答案预留 | 改造 | 中 |
| `agent/formatter.py` | `_judger_friendly` 输出规范化 | 改造 | 低（纯规则） |
| `prompts/verifier.py` | 新增 RUBRIC/CHALLENGE 提示词 | 新增 | 低 |
| `prompts/revise.py` | 错因结构化模板 | 改造 | 低 |
| `user_agent.py` | AgentConfig 新增开关：`use_rubric` / `use_deterministic` / `use_view_sampling` / `judger_friendly`（默认 False，A/B 验证后逐个开） | 改造 | 低（向后兼容） |
| `run_eval.py` | 无改动（复用本地评测验证效果） | — | — |

**同步纪律**：先在根目录 `agent/` 实验（改完跑 `run_eval.py --bank 新高数` 对比），
验证通过后再把**同构改动**同步进 `赛事提交版/`（含其独有的 router/pacer/tier 接线），
提交前跑 `赛事提交版/tests/` 全量回归。

---

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 新增调用威胁时间预算 | 全部新调用走 prefill（实测 rubric 单次 ~1-3s）；决策表保答案预留；PaperPacer 应急降档 |
| 判分器仍可能胡判 | rubric 结构化强制"独立重算→对比→定位"，配确定性旁证加权，非唯一裁决源 |
| 视角采样候选同质化 | 视角提示 + 温度联合扰动；修订轮换视角；deep 档 3~4 视角 |
| 反例搜索误杀（模型给错反例） | 反例必须经程序数值验证才生效（`search_counterexample`），LLM 只负责"生成候选反例"不负责"判定" |
| 改动破坏平台契约 | 所有新开关默认 False；`ReasoningAgent`/`solve` 签名不动；`赛事提交版/tests/test_runner_contract.py` 回归 |
| 黑盒 Judger 匹配规则不明 | `_judger_friendly` 输出多形态兼容（纯数值 + `\boxed` + 选项字母），参考 `run_eval.py::answers_match` 的多级匹配逻辑反推 |

---

## 7. 实施路线（每步可 A/B，可回滚）

| Phase | 内容 | 验证方式 | 风险 |
|---|---|---|---|
| **P0 基线** | 现有赛事提交版跑 `run_eval.py --bank 新高数`，记录准确率/耗时基线 | 基线数据 | — |
| **P1 零风险合入** | `formatter._judger_friendly` + `deterministic.py`（默认开，不耗预算） | A/B 对比准确率 | 低 |
| **P2 判分升级** | verifier rubric + 错因反馈 + 确定性旁证（`use_rubric`/`use_deterministic` 开） | A/B：新高数 + IMO-AnswerBench | 中 |
| **P3 求解升级** | solver 视角采样 + revise 定向修订 + orchestrator 决策表 | A/B：三题库全量 | 中 |
| **P4 同步提交版** | 同构改动同步进 `赛事提交版/` + 全量测试回归 | 提交前自查清单 | 低 |
| **P5 冲刺** | 按 A/B 数据微调阈值（置信度门限/视角组合/修订轮数），跑 IMO-ProofBench 验证证明通道 | 最终榜单分数 | 中 |

**A/B 纪律**：每个 Phase 只开一个开关；`--bank 新高数`（~100 题）小样本快筛 → 全量三题库确认；
耗时增幅 > 20% 且准确率无增益的改动直接回滚（沿用 README 中 A/B 结论的记录方式）。

---

## 8. 一句话总结

> **像 Intern-MO 那样想（多视角搜索 + rubric 判分 + 错因定向修订），
> 像 DeepSeek Harness 那样组织（阶段机 + 专业子智能体 + trace 即产品），
> 用 SymPy 硬验证兜底（确定性通道，0 预算），
> 一切改造默认关、逐项 A/B、验证后同步进赛事提交版。**

---

*设计基于：赛事提交版 v2.5（difficulty_router + paper_pacer + tier 系统）、根目录 agent/ v2.4.1、官方规则 2026-08-15 版。*
