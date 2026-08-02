---
name: intern-s1-optimized独立化
overview: 在当前项目下创建独立的 intern_s1_optimized/ 子目录，将书生AI推理模块完整独立复制出来，保持与原有评测工具的兼容性。不做任何优化，只确保独立出来的代码能被测试器正常调用。为后续优化预留扩展点。
todos:
  - id: create-dir-and-copy
    content: 创建 intern_s1_optimized/ 目录，完整复制 config.py 和 models.py
    status: completed
  - id: copy-llm-client
    content: 复制 llm_client.py，将 import 路径改为相对导入（from .config import LLMConfig）
    status: completed
    dependencies:
      - create-dir-and-copy
  - id: copy-intern-s1
    content: 复制 intern_s1.py，将 import 路径改为相对导入（from .config import get_config 等）
    status: completed
    dependencies:
      - copy-llm-client
  - id: create-init
    content: 创建 __init__.py，导出 run_inference 函数
    status: completed
    dependencies:
      - copy-intern-s1
  - id: modify-main
    content: 修改 测试工具/main.py，增加 --optimized 命令行开关，支持一键切换调用独立版 run_inference
    status: completed
    dependencies:
      - create-init
  - id: verify-integration
    content: 验证独立版可被测试器正常调用：检查 import 链、运行语法检查、确认功能一致
    status: completed
    dependencies:
      - modify-main
---

## 用户需求

将书生AI推理模块从测试工具中**原封不动地独立复制**到 `intern_s1_optimized/` 目录，不修改任何推理逻辑，保持功能完全一致（单轮推理）。确保独立出来的模块能被 `main.py` 测试器正常调用，为后续用户自行优化预留清晰的代码结构。

## 核心要求

- 纯复制 + 结构调整，不做任何推理策略优化
- 独立目录自包含，不依赖 `测试工具/` 下的任何模块
- 对外暴露 `run_inference(problem: Problem) -> InferenceResult` 相同签名
- `main.py` 增加 `--optimized` 开关，可一键切换调用独立版
- 原测试工具不动

## 技术方案

### 整体策略

最简单的做法：将 `测试工具/` 下的4个核心文件（intern_s1.py、llm_client.py、config.py、models.py）完整复制到 `intern_s1_optimized/` 目录，修改内部 import 路径为自引用，确保模块自包含。然后在 `main.py` 中通过条件 import 切换原版和独立版。

### 文件操作清单

1. **创建 `intern_s1_optimized/` 目录**
2. **复制 `llm_client.py`**：将 `from config import LLMConfig` 改为 `from .config import LLMConfig`（相对导入）
3. **复制 `config.py`**：完整复制，`load_dotenv` 路径适配（读同一个 `~/.math_evaluator/.env`）
4. **复制 `models.py`**：完整复制，不需要修改
5. **复制 `intern_s1.py`**：将 `from config import get_config` 改为 `from .config import get_config`，其他导入同样改为相对导入
6. **创建 `__init__.py`**：导出 `run_inference`
7. **修改 `main.py`**：增加 `--optimized` 参数，条件导入

### 关键设计决策

- **使用相对导入（`from .config import ...`）** 确保独立目录自包含，不依赖 `测试工具/`
- **共享同一套 `.env` 配置**：独立版读取相同的 `~/.math_evaluator/.env`，用户无需重复配置
- **main.py 通过 sys.path 切换**：`--optimized` 时将 `intern_s1_optimized/` 的父目录加入 sys.path，然后 `from intern_s1_optimized.intern_s1 import run_inference`

### 目录结构

```
d:\挑战杯\
├── intern_s1_optimized/          # [NEW] 书生AI独立版
│   ├── __init__.py               # [NEW] 包初始化，导出 run_inference
│   ├── intern_s1.py              # [NEW] 推理入口（从测试工具复制，改import为相对导入）
│   ├── llm_client.py             # [NEW] LLM客户端（从测试工具复制，改import为相对导入）
│   ├── config.py                 # [NEW] 配置管理（从测试工具完整复制）
│   └── models.py                 # [NEW] 数据模型（从测试工具完整复制）
│
└── 测试工具/
    └── main.py                   # [MODIFY] 增加 --optimized 开关
```