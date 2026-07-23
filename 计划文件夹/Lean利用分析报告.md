# Lean 形式化验证深度利用分析报告

> 基于知识库"书生ai"新增文献：
> - **LEAP** (Google DeepMind, arXiv 2606.03303)：通用 LLM + 智能体框架 → Putnam 满分
> - **Semantic Search Engine for Mathlib4** (北大, arXiv 2403.13310)：自然语言搜索 Mathlib4 定理

---

## 一、新文献核心发现

### 1. LEAP：通用 LLM 的证明能力被严重低估了

LEAP 最震撼的数据：

| 测试集 | 直接生成 | 树搜索 | LEAP（DAG） |
|--------|---------|--------|------------|
| Putnam 2025 (12题) | 0% | 33.3% | **100%** |
| Lean-IMO-Bench Basic | <10% | ~48% | **83.3%** |
| Lean-IMO-Bench Advanced | <10% | ~20% | **56.7%** |

**核心理念：不给模型微调，给它一个好用的脚手架（scaffolding）。**

### 2. Mathlib4 语义搜索：你不知道名字，照样能找到定理

`leansearch.net` 让你用**自然语言**搜索 mathlib4 中的定理。例如：
- 输入"施罗德-伯恩斯坦定理" → 返回 `Function.Embedding.schroeder_bernstein`
- 输入"皮亚诺余项的泰勒展开" → 返回 `Analysis/Calculus/Taylor.lean` 中的相关定理
- 召回率 Recall@10 达到 **91.3%**

---

## 二、当前项目 Lean 使用现状 vs LEAP

### 当前做法（测试工具/lean_verifier.py）

```
Intern-S 解题 → DeepSeek 转 Lean 代码 → Lean 编译验证 → DeepSeek 分析错误
     ↑_______________ 一次性转化，失败就结束 _______________↓
```

**问题：**

| 问题 | 说明 |
|------|------|
| 一次性转化 | 生成 Lean 代码 → 编译 → 失败 → 结束。**没有反馈修正循环** |
| 禁止 Mathlib | Prompt 明确禁止 `import Mathlib`，只能用 `native_decide`、`simp` 等基础策略 |
| 无分解机制 | 不对复杂定理做子引理分解，一次性生成整段证明 |
| 无引理缓存 | 每次独立转化，不缓存已证引理 |
| 竞赛版不用 Lean | `submit/user_agent.py` 完全没有任何 Lean 验证 |

### LEAP 的做法

```
定理输入
    ↓
直接证明尝试 → Lean 编译 → 成功 ✓
    ↓ 失败
蓝图分解（自然语言）
    ↓
形式化草图（允许 sorry）
    ↓
Lean 编译验证草图
    ↓
LLM 审查分解质量 → 不通过则回溯
    ↓ 通过
AND-OR DAG 记录依赖 → 递归处理子目标
    ↓
每个子目标独立尝试证明 → 结果写入 DAG 共享
    ↓
所有子目标完成 → 父目标自动完成 ✓
```

**核心差异：**
1. **反馈修正循环**：编译错误 → LLM 修正 → 再编译，直到通过
2. **蓝图分解**：大问题拆小问题，递归求解
3. **DAG 共享**：子引理证明后全局复用
4. **自然语言中间层**：先写"白话证明计划"，再翻成 Lean 代码

---

## 三、具体改进方案

### 方案 A：增强本地测试工具（可立即执行）

#### A1. 引入反馈修正循环

在 `lean_verifier.py` 的编译阶段后添加 Reviser：

```python
# 当前：编译失败 → 分析 → 结束
# 改进：编译失败 → 分析 → Reviser 修正 → 再编译（最多 N 次）

for attempt in range(MAX_REVISION_ROUNDS):
    ok, stderr = compile_lean(code)
    if ok:
        return success
    code = llm_revise(code, stderr)  # 根据编译错误自动修正
```

**预期效果**：转化成功率从当前的一次性生成提升 2-3 倍。

#### A2. 解除 Mathlib 禁令，引入语义搜索

当前 Prompt 禁止 `import Mathlib`，大大限制了证明能力。改进方案：

```python
# 阶段 0：语义搜索 → 找到相关定理
relevant_theorems = search_leansearch(natural_language_query)
# 阶段 0.5：将定理声明注入 Prompt
conversion_prompt += f"\nRelevant mathlib4 theorems:\n{relevant_theorems}"
# 阶段 1：转化 → 允许 import Mathlib
```

**关键**：Mathlib4 覆盖了分析、代数、拓扑、数论等几乎所有数学领域，禁止使用等于自废武功。

#### A3. 添加蓝图分解机制

借鉴 LEAP 的思路，在转化前增加"蓝图规划"步骤：

```python
# 解法蓝图：用自然语言写证明拆解计划
blueprint = llm_generate_blueprint(problem, reasoning)
# 例如："先证的引理 A，再利用引理 A 证的引理 B，最后合并得到的"

# 每个引理独立转化为 Lean 代码并验证
for lemma in blueprint.lemmas:
    lean_code = convert_to_lean(lemma)
    verify_lean(lean_code)
```

#### A4. 添加 AND-OR DAG 结构

```python
@dataclass
class ProofNode:
    type: Literal["OR", "AND"]   # OR=待证目标, AND=分解方案
    statement: str                 # 定理陈述
    lean_code: str = ""           # Lean 证明代码
    children: list[str] = []      # 子节点 ID
    status: str = "pending"       # pending/proved/failed

class ProofDAG:
    nodes: dict[str, ProofNode]
    proved_lemmas: dict[str, str]  # lemma_stmt → lean_code 缓存
```

### 方案 B：增强竞赛提交版（submit/user_agent.py）

**竞赛约束**：只能使用平台注入的 `client`，不能调用本地编译器。但 LEAP 的思路仍然可以借用！

#### B1. 将 Lean 形式化融入推理链（不编译，只形成化思维）

```python
def solve(self, problem, metadata):
    # 当前：纯 LLM 解题 + 投票
    # 改进：加入 Lean 形式化思维环节
    
    # 步骤 1：自然语言解题（同现在）
    candidates = self._generate_candidates(problem)
    
    # 步骤 2：让 LLM 将最优解的推理形式化为 Lean 陈述
    # （不要求编译通过，只要求形式化思考）
    lean_statements = self._formalize_candidates(problem, candidates)
    
    # 步骤 3：用 Lean 形式的推理做二次验证
    # （LLM 扮演"类型检查器"，逐行检查推理的类型一致性）
    verification = self._type_check_reasoning(problem, candidates, lean_statements)
    
    # 步骤 4：综合投票结果和类型检查结果做最终决策
    return self._select_best(candidates, verification)
```

#### B2. 引入"蓝图分解"策略提示词

修改 `prompts/policy.py`，让 LLM 采用"分解-证明-汇总"的工作流：

```python
POLICY_SYSTEM = """
你是一位数学解题专家。请按以下步骤解题：

1. 【问题分析】理解问题，识别关键条件和目标
2. 【蓝图分解】如果问题复杂，先拆分为子问题（子引理），再逐一解决
3. 【逐步推理】对每个子引理，给出严格的数学推导
4. 【汇总结论】将所有子结论合并，得到最终答案

对每个推导步骤，请确保：
- 类型一致性（输入输出类型匹配）
- 条件充分性（前提条件是否被满足）
- 边界覆盖（是否遗漏特殊情况）

输出格式：
【蓝图】子问题 1: ... ; 子问题 2: ...
【子问题1解答】...
【子问题2解答】...
【最终答案】...
"""
```

#### B3. 利用语义搜索的思路增强领域知识

虽然竞赛中不能联网搜索，但可以将 mathlib4 的核心定理知识预置在 Prompt 中：

```python
# 在 prompts/policy.py 中添加
MATHLIB_THEOREM_HINTS = {
    "代数": "常用定理: 拉格朗日定理、同态基本定理、中国剩余定理...",
    "数论": "常用定理: 费马小定理、欧拉定理、二次互反律、素数定理...",
    "几何": "常用定理: 勾股定理、余弦定理、托勒密定理、Menelaus定理...",
    "分析": "常用定理: 中值定理、泰勒定理、控制收敛定理、Fubini定理...",
}
```

### 方案 C：中长期架构升级

#### C1. 混合架构：竞赛版 + 本地版

```
┌──────────────────────────────────────────────┐
│              竞赛提交版 (submit/)              │
│  user_agent.py                               │
│  ├── 纯 LLM 解题（蓝图分解策略）              │
│  ├── 自然语言自我验证                         │
│  └── 无外部依赖                               │
└──────────────────────────────────────────────┘
                      ↓ 推理结果
┌──────────────────────────────────────────────┐
│          本地验证版 (测试工具/)                 │
│  lean_verifier.py (升级版)                    │
│  ├── 自然语言 → Lean 4 转化 (DeepSeek/V3)     │
│  ├── 反馈修正循环 (Reviser)                   │
│  ├── Mathlib4 语义搜索                        │
│  ├── 蓝图分解 + AND-OR DAG                    │
│  └── Lean 编译 + sorry 检测                   │
└──────────────────────────────────────────────┘
```

#### C2. 精简 Lean 调用接口

```python
# 本地验证的统一接口
class LeanProofEngine:
    async def verify(self, problem: str, reasoning: str) -> LeanResult:
        """单次验证：推理 → Lean 代码 → 编译 → 结果"""
    
    async def decompose_and_prove(self, problem: str) -> ProofDAG:
        """蓝图分解 + 逐步证明"""
    
    async def search_theorems(self, query: str) -> list[Theorem]:
        """语义搜索 mathlib4"""
```

---

## 四、优先级建议

| 优先级 | 改进项 | 影响 | 工作量 |
|--------|--------|------|--------|
| 🔴 P0 | 竞赛版添加蓝图分解 Prompt | 可能提升 10-20% 得分 | 1-2h |
| 🔴 P0 | 解除 Mathlib 禁令 | 大幅扩展可证明范围 | 0.5h |
| 🟡 P1 | 添加反馈修正循环 (Reviser) | 转化成功率 ×2-3 | 2-3h |
| 🟡 P1 | 添加蓝图分解到 lean_verifier | 复杂题验证率提升 | 3-4h |
| 🟢 P2 | 集成语义搜索 (leansearch.net) | 减少定理查找时间 | 1-2h |
| 🟢 P2 | AND-OR DAG 证明树 | 系统性提升复杂题 | 4-6h |

---

## 五、总结

LEAP 这篇论文给我们最重要的启示是：

> **通用大模型在形式数学上的"差"不是因为模型不够强，而是因为没有给它合适的工具和流程。**
> 同样的 Intern-S 模型，配上蓝图分解 + 反馈修正 + DAG 共享 → 就可以从 0% 跃升到 100%。

目前项目最大的机会点：
1. **本地测试工具**：引入反馈修正循环和蓝图分解，让 Lean 验证从"一次性尝试"变成"迭代收敛"
2. **竞赛提交版**：将 LEAP 的"分解-证明-汇总"思维模式嵌入 Prompt，即使没有编译器，也能提升推理的结构化程度
3. **知识库**：利用 Mathlib4 语义搜索，让 LLM 在证明时能"回忆起"正确的定理，而不是从零推导
