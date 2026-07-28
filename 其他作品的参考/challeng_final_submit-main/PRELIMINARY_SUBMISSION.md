# 挑战杯初赛提交说明

## 题目信息

- 题目名称：基于 Intern-S 系列模型的数学智能体设计与推理创新
- 队伍名称：**待按挑战杯官网报名名称填写**
- 仓库地址：https://github.com/3294682143-gif/challeng_final_submit
- 分支名称：`main`
- commit hash：使用本次最终推送产生的固定 commit SHA
- 选择使用的模型：`intern-s1`
- 官网代码包建议名称：`challeng_final_submit-<commit-short-sha>.zip`

## 评测入口

```python
from user_agent import ReasoningAgent

agent = ReasoningAgent(client=official_client)
result = agent.solve(problem, metadata)
```

入口实现满足以下约定：

- 构造函数接受平台提供的 `client` 以及额外参数。
- `solve(problem, metadata)` 返回字典。
- `final_response` 始终为非空字符串。
- 返回值可 JSON 序列化。
- 运行路径基于 `__file__` 相对定位。
- 不读取标准答案，不包含或记录 API key。

## 运行环境

- Python 3.10+
- 安装命令：`pip install -r requirements.txt`
- 平台 client 调用接口：`chat(messages, temperature, max_tokens)`

## 提交前验证

- pytest：382 passed
- Ruff：passed
- Pyright：0 errors、0 warnings
- official-client 协议仿真：passed
- `user_agent.py` 导入和初始化：passed
- `final_response` 非空及 JSON 序列化：passed
- 硬编码 API key / token：未发现
- 用户绝对路径：未发现

## 发布范围

本仓库只保留官方入口、运行源码、配置、skills、依赖说明和回归测试。以下研发产物未提交：

- 本地题库与答案集
- 历史 API 结果和评测输出
- trace、日志、缓存和临时文件
- 代码备份及旧压缩包

## 官网提交前仍需人工确认

1. 将上方队伍名称替换为挑战杯官网中的正式报名名称。
2. 在判分系统和邮件正文中填写本次推送返回的完整 commit SHA。
3. 确认判分系统选择的模型与本说明一致。
4. 使用同一 commit 下载或生成 zip，确保附件与 commit SHA 对应。
