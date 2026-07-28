# 数学智能体比赛项目

基于 Intern-S / Intern-S1 的数学解题智能体，面向挑战杯人工智能赛道——基于 Intern-S1 的数学智能体设计与推理创新。

## 1. 项目目标

本项目用于挑战杯人工智能赛道数学智能体比赛。

目标是实现一个符合比赛接口要求的 Python Agent：

```python
class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        ...

    def solve(self, problem: str, metadata: dict) -> dict:
        ...
```

返回格式：

```python
{
  "final_response": "...",
  "trace": [...]
}
```

强调：

- `final_response` 必须是非空字符串；
- `trace` 可选，但当前项目会返回；
- `user_agent.py` 是比赛平台强制入口；
- 正式评测由平台传入 `official_client`；
- `user_agent.py` **不读取 API Key**，不创建本地 client。

平台评测流程概览：

1. 从 AtomGit 参赛仓库 `main` 分支拉取代码；
2. 安装 `requirements.txt`；
3. `from user_agent import ReasoningAgent`；
4. `agent = ReasoningAgent(client=official_client)`；
5. `result = agent.solve(problem, metadata)`；
6. 读取 `result["final_response"]` 判分。

## 2. 当前能力

- **Router**：规则 + 可选 LLM 题型 / 领域分类；
- **Planner**：生成简短解题计划；
- **SymPy tool_hints**：轻量符号提示，失败安全降级；
- **Solver 多候选**：按难度生成 1–3 个候选解答；
- **Voting**：答案规范化、等价分组、多数投票加分；
- **Verifier**：投票评分 + 可选 LLM 验证微调；
- **Refiner**：低分 / 需修正时单次反思；
- **trace 清洗与脱敏**：截断、JSON 可序列化、API Key 脱敏；
- **专项 prompt 路由**：按 `subject` / `problem_type` 选择代数、分析、概率等策略。

## 3. 项目结构

```text
.
├── user_agent.py              # 比赛强制入口 ReasoningAgent
├── main.py                    # 本地批量调试 runner
├── config.py                  # 配置（无 API Key）
├── requirements.txt           # Python 依赖
├── agents/                    # 编排与各子模块
│   ├── reasoning_agent_core.py
│   ├── router.py
│   ├── planner.py
│   ├── solver.py
│   ├── verifier.py
│   └── refiner.py
├── prompts/                   # 提示词模板与题型路由
│   ├── base_prompts.py
│   ├── solver_prompts.py
│   ├── domain_prompts.py
│   └── ...
├── tools/                     # 抽取、规范化、SymPy、投票等
│   ├── answer_extractor.py
│   ├── answer_normalizer.py
│   ├── sympy_tools.py
│   ├── voting.py
│   └── math_utils.py
├── schemas/                   # 结果结构与 trace 安全
│   └── result_schema.py
├── tests/                     # pytest 单元 / 集成测试
├── sample_data/               # 本地样例 JSONL
└── sample_outputs/            # 本地运行输出
```

目录职责：

| 路径 | 职责 |
|------|------|
| `user_agent.py` | 平台唯一强制入口 |
| `agents/` | 分类、规划、求解、验证、修正编排 |
| `prompts/` | 提示词与专项路由 |
| `tools/` | 答案处理、符号工具、投票 |
| `schemas/` | 统一成功/失败结果与 trace 安全 |
| `tests/` | 接口与模块回归测试 |
| `main.py` | 本地调试 runner（正式评测不依赖） |

## 4. 核心流程

```text
problem
  ↓
ReasoningAgent.solve()
  ↓
MathReasoningAgentCore
  ↓
Router.classify()
  ↓
Planner.create_plan()
  ↓
build_tool_hints()
  ↓
Solver.generate_candidates()   # 含专项 prompt 路由
  ↓
Verifier.verify_candidates()   # 含 voting
  ↓
Refiner.refine()               # optional
  ↓
normalize_final_response()
  ↓
return {"final_response": ..., "trace": ...}
```

典型 `trace` 步骤：

`input → classify → plan → tool_hints → candidates → verify → [refine] → solve → finalize`

## 5. 本地运行

```bash
pip install -r requirements.txt

python -m pytest

rm -f sample_outputs/*.json
python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs --limit 1
```

FakeClient 模式（无需 API）：

```bash
python main.py --input_file sample_data/dev.jsonl --output_dir sample_outputs --limit 1 --fake
```

说明：若 `sample_outputs/{idx}.json` 已存在且非空，runner 会跳过该题（断点续跑）。强制重跑前请先清空输出。

## 6. 本地 Intern API 配置

本地调试可使用环境变量或 `.env`：

```bash
export INTERN_API_KEY="your_key"
export INTERN_API_BASE="https://chat.intern-ai.org.cn/api/v1/"
export INTERN_MODEL="intern-s1"
```

注意：

- **不要把 `.env` 提交到 Git**（已在 `.gitignore`）；
- 也可使用被 ignore 的 `config.local.py` / `config_local.py`；
- `user_agent.py` 不读取 API Key；
- 正式评测使用平台 `official_client`；
- README / 代码中不得写入真实 Key。

## 7. 测试

当前测试覆盖 import、solve 格式、答案抽取、规范化、router、planner、solver、verifier、refiner、SymPy、voting、result_schema、domain prompts 等。

```bash
python -m pytest
```

当前应通过 **87** 项（以本地最新 `pytest` 输出为准）。
