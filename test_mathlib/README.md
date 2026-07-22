# test_mathlib

Lean 4 形式化验证测试用例与 CI 配置。

## 环境说明

- **Lean 工具链未纳入版本库**：`lean4-toolchain/`（约 1.2 GB）体积过大，未上传到 GitHub。
  请按 `lean-toolchain` 文件声明的版本 `leanprover/lean4:v4.31.0` 自行安装 Lean 4。
- **依赖自动拉取**：`lake-packages/`（mathlib、batteries、aesop、Qq、Cli 等 13 个社区包）
  不会进入版本库，执行 `lake build` 后会依据 `lake-manifest.json` 自动下载并编译。
- **编译产物忽略**：`*.olean` / `*.ilean` / `*.ir` 等编译产物已在 `.gitignore` 中忽略。

## 构建

```bash
lake build        # 自动拉取依赖并编译
lake exe TestMathlib   # 运行测试
```

## CI

`.github/workflows/lean_action_ci.yml` 使用社区 Lean Action 在云端自动完成
工具链安装、依赖拉取与编译，无需本地准备工具链。
