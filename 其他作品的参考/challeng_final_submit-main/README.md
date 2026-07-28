# Intern-S Math Agent

挑战杯人工智能赛道初赛项目：基于 Intern-S 系列模型的数学智能体设计与推理创新。

## 官方入口

评测平台从仓库根目录的 `user_agent.py` 加载智能体：

```python
from user_agent import ReasoningAgent

agent = ReasoningAgent(client=official_client)
result = agent.solve(problem, metadata)
```

`solve` 返回可 JSON 序列化字典，并保证 `final_response` 为非空字符串。平台提供的 official client 通过公开的 `chat(messages, temperature, max_tokens)` 接口注入；仓库不包含 API key，也不依赖本机绝对路径。

## 解题流程

1. 对题目进行领域和题型路由。
2. 对结构明确、可独立验算的题目优先使用本地确定性工具。
3. 其余题目调用平台提供的 Intern-S official client。
4. 对候选答案执行格式化、验证、证明结构检查和必要的纠错。
5. 返回最终答案以及经过脱敏的简要 `trace`。

本地 `client=None` 时使用 mock client，仅用于无网络冒烟测试；正式评测始终使用平台注入的 official client。

## 环境

- Python 3.10 或更高版本
- 依赖版本见 `requirements.txt`

```bash
pip install -r requirements.txt
```

## 本地验证

```bash
python -m pytest -q
python -m ruff check src tests
python -m pyright
```

当前发布快照已通过：

- 382 项 pytest 回归测试
- Ruff 静态检查
- Pyright 类型检查（0 errors）
- 根目录 `user_agent.py` official-client 协议仿真

本地测试结果不代表官方隐藏测试集成绩。

## 仓库结构

```text
user_agent.py             官方评测入口
requirements.txt          运行依赖
pyproject.toml             包与 Python 版本配置
configs/                   运行配置和提示词
skills/                    数学技能说明
src/math_agent/            智能体实现
tests/                     回归与安全测试
PRELIMINARY_SUBMISSION.md  初赛提交信息与检查清单
```

本发布仓库不包含本地题库、标准答案、历史 API 输出、trace、备份、缓存或密钥。
