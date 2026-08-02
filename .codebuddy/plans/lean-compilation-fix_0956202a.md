---
name: lean-compilation-fix
overview: 修复 Lean 编译流程，使 DeepSeek 生成的 Lean 代码能真正被编译和验证。包括：修改编译策略（用 lean 直接编译单文件而非 lake build）、创建自动化编译脚本、添加环境配置说明。
todos:
  - id: add-lean-path-config
    content: 在 config.py 中新增 LEAN_PATH 配置项和 get_lean_path() 辅助函数，自动检测 mathlib 的 .olean 目录
    status: completed
  - id: rewrite-compile-function
    content: 重写 lean_verifier.py 的 _compile_lean() 函数，改用 lean.exe --make 直接编译单个文件，正确设置 LEAN_PATH 环境变量
    status: completed
    dependencies:
      - add-lean-path-config
  - id: create-compile-script
    content: 创建 Windows 批处理脚本 编译Lean代码.bat，支持拖入 .lean 文件一键编译并显示结果
    status: completed
  - id: create-env-guide
    content: 创建 Lean环境配置说明.md 文档，说明如何下载安装 Lean 4 编译器以及本项目已预配置的环境
    status: completed
---

## 用户需求

用户发现测试器中 DeepSeek 判错后能将书生 AI 的推理过程转化为 Lean 语言代码，但转化后的代码无法被真正编译验证（显示编译通过是假阳性）。用户希望：

1. **修复编译问题**：让生成的 Lean 代码能被实际编译，获得真实的编译结果
2. **创建自动化脚本**：一键编译 Lean 代码的批处理/Shell 脚本
3. **环境配置指南**：告知需要下载什么编译器，如何配置

## 核心功能

- 修改 `lean_verifier.py` 的编译逻辑，使用 `lean.exe` 直接编译单个文件替代 `lake build`
- 自动设置 `LEAN_PATH` 指向 mathlib 编译产物目录，确保 `import Mathlib` 正确解析
- 创建 Windows 批处理脚本 `编译Lean代码.bat`，支持拖入 .lean 文件一键编译
- 创建环境配置说明文档，指引用户下载和配置 Lean 4 编译器

## 技术方案

### 问题根因

当前 `lean_verifier.py` 的 `_compile_lean()` 函数（第 387-477 行）将代码写入 `test_mathlib/TestMathlib/Verify.lean` 后调用 `lake build`。但 `lake build` 只编译 lakefile.toml 声明的依赖树中的模块——`TestMathlib.lean` 只 import 了 `Basic.lean`，`Verify.lean` 从未被编译。`compile_passed: true` 是假阳性。

### 解决方案：改用 lean.exe 直接编译

使用 `lean.exe` 直接编译单个 `.lean` 文件，设置 `LEAN_PATH` 环境变量指向 mathlib 的 `.olean` 编译产物目录。这样 `lean` 可以独立编译 Verify.lean 并正确解析 `import Mathlib`。

**优势**：

- 不需要修改 lakefile.toml，不需要动态注册模块
- 编译结果直接反映 Verify.lean 的真实语法/类型错误
- 比 lake build 更快（不需要增量编译检查整个项目）
- 并发安全：多道题同时编译不会相互干扰

### 技术细节

**LEAN_PATH 设置**：

- mathlib 的 `.olean` 文件在 `lake-packages/mathlib/build/lib/`
- 需要将此路径加入 `LEAN_PATH` 环境变量
- 项目自身的 `build/lib/` 也需要加入（用于 Mathlib 自身依赖）

**编译命令**：

```
lean.exe --make Verify.lean
```

`--make` 标志会生成 `.olean` 文件，同时输出编译错误到 stdout/stderr。

### 实现架构

```
_compile_lean() 修改后的流程:
  1. 清理代码 (已存在 _build_lean_code_safe)
  2. 写入 Verify.lean 到临时目录
  3. 设置 LEAN_PATH 环境变量
  4. 调用 lean.exe --make Verify.lean
  5. 解析编译输出，过滤错误信息
  6. 返回 {passed, output, timeout, latency}
```

### 关键修改点

| 文件 | 修改内容 |
| --- | --- |
| `测试工具/lean_verifier.py` | 重写 `_compile_lean()` 函数，用 lean.exe 替代 lake build |
| `测试工具/config.py` | 新增 `LEAN_PATH` 配置项和 `get_lean_path()` 函数 |
| `编译Lean代码.bat` | 新建：一键编译脚本 |
| `Lean环境配置说明.md` | 新建：环境配置文档 |


### 性能与可靠性

- 编译超时保持 60 秒不变
- 并发编译通过 asyncio.Semaphore 控制（已存在）
- 编译完成后清理临时文件（已存在）
- 错误输出截断至 5000 字符（已存在）
- mathlib 的 `.olean` 文件已在本地，无需网络

### 向后兼容

- `_compile_lean()` 函数签名不变
- 返回值格式不变 `{passed, output, timeout, latency}`
- 现有调用方（`_run_full_lean_pipeline`、`main.py`）无需修改