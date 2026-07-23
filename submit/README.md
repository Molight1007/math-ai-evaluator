# MathPilot — 数学智能体竞赛提交项目

> **赛题：** 基于 Intern-S 系列大模型的数学智能体设计与推理创新  
> **发榜单位：** 上海人工智能实验室  
> **比赛平台：** AtomGit  

---

## 项目结构

```
├── user_agent.py          # ★ 智能体主入口（平台强制契约）
├── requirements.txt       # 依赖清单
├── local_test.py          # 本地测试脚本（不计入提交评分）
├── prompts/               # 提示词模板
│   ├── __init__.py
│   ├── policy.py          # 解题策略 + 18 领域增强
│   └── verifier.py        # 候选解答验证
├── utils/                 # 工具函数
│   ├── __init__.py
│   └── extract.py         # 答案提取/格式化/序列化
└── sample_data/           # 样例数据
    └── dev.jsonl          # 本地调试用样例
```

## 快速开始

```bash
# 1. 设置 API Key
set INTERN_API_KEY=sk-xxxx你的密钥xxxx

# 2. 运行本地测试
python local_test.py --input sample_data/dev.jsonl --output outputs/

# 3. 调整参数
python local_test.py --samples 6 --votes 3 --no-domain-hint
```

## 平台调用方式（正式评测）

```python
from user_agent import ReasoningAgent
agent = ReasoningAgent(client=official_client)
result = agent.solve(problem, metadata)  # -> {"final_response": "...", "trace": [...]}
```

## 智能体策略

| 阶段 | 操作 | 模型调用次数 |
|------|------|:--:|
| 题型分类 | 18 领域自动识别 | 1 |
| 多候选生成 | 同一题多次采样（默认 4 次） | 4 |
| 验证投票 | 每个候选 2 次独立投票 | 8 |
| 最优选择 | 按置信度排序取最高 | 0 |
| **总计** | | **13 次/题** |

## 自检清单

- [x] `user_agent.py` 可正常 import
- [x] `ReasoningAgent` 类可正常实例化
- [x] `solve()` 返回合规 `{"final_response": "...", "trace": [...]}` 结构
- [x] 无硬编码 API Key
- [x] 无绝对路径
- [x] 全部依赖写入 `requirements.txt`
- [x] `final_response` 非空保证
- [x] 返回值 JSON 可序列化
- [ ] 本地真实测试（需要 API Key）
- [ ] 推送至 AtomGit main 分支
