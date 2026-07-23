# Lean 4 环境使用指南（挑战杯项目）

> 本指南让你像用 PyCharm 编译 Python 一样，在 Cursor / VS Code 里写、编译、运行 Lean 4。

---

## 一、环境已就绪（无需重装）

| 组件 | 状态 | 位置 |
|------|------|------|
| Lean 编译器 | ✅ v4.31.0 | `C:\Users\35174\.elan\bin\lean.exe` |
| Lake 构建工具 | ✅ v5.0.0 | `C:\Users\35174\.elan\bin\lake.exe` |
| 版本管理器 elan | ✅ | `C:\Users\35174\.elan\bin\elan.exe` |
| Cursor 编辑器 | ✅ | `C:\Users\35174\AppData\Local\Programs\cursor` |
| Lean 4 扩展 | ✅ v0.0.237 | Cursor 扩展 `leanprover.lean4` |

> 验证：在终端输入 `lean --version` 应显示 `Lean (version 4.31.0, ...)`。

---

## 二、方式一：Cursor 编辑器（推荐，最像 PyCharm）

1. 用 Cursor 打开本工作区文件夹 `D:\挑战杯`
   ```
   cursor "D:\挑战杯"
   ```
2. 打开任意 `.lean` 文件（如 `hello.lean`）。
3. **保存即自动编译**：Cursor 会在后台启动 Lean 语言服务器（LSP），
   实时显示：
   - ✅ 绿色对勾 = 编译通过
   - ❌ 红色波浪线 + 悬停提示 = 报错位置与原因
   - 右侧 InfoView 面板：显示证明目标（goal）、战术状态
4. 运行可执行入口：在文件里写好 `def main : IO Unit := ...` 后，
   用方式二的一键脚本运行，或终端执行 `lake build && lake exe <项目名>`。

> 首次打开 `.lean` 时，Cursor 右下角会提示 "Lean: server starting..."，
> 约几秒后变绿即可开始编写。`.vscode/settings.json` 已配好 elan 工具链路径。

---

## 三、方式二：一键命令行（类似 `python xxx.py`）

已为你生成 `D:\挑战杯\leanrun.bat`：

```bat
leanrun hello.lean
```

即可「编译 + 运行」单文件 Lean 程序，效果等同于 `python hello.py`。

---

## 四、编译你的项目 test_mathlib（依赖 mathlib）

`test_mathlib` 是一个完整 Lake 项目（含 mathlib 等依赖），编译方式：

```bat
cd D:\挑战杯\test_mathlib
lake build            REM 编译整个项目（首次会下载 mathlib 等依赖并编译，较慢）
lake exe test_mathlib REM 运行生成的可执行文件
```

> ⚠️ 首次 `lake build` 需要联网拉取 mathlib 社区依赖（batteries / aesop /
> proofwidgets 等），且 mathlib 编译量大，可能耗时 10~30 分钟。
> 后续构建会利用缓存，速度很快。
>
> 若出现 git 凭据弹窗卡住，执行：
> ```bat
> set GIT_TERMINAL_PROMPT=0
> lake update
> ```

---

## 五、常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `lean` 不是内部命令 | PATH 未含 elan | 重启终端；确认 `C:\Users\35174\.elan\bin` 在 PATH |
| Cursor 打开 `.lean` 无反应 | 未装 Lean 4 扩展 | `cursor --install-extension leanprover.lean4` |
| `lake update` 卡住 | git 凭据弹窗等待 | `set GIT_TERMINAL_PROMPT=0` 后重试 |
| 中文路径报错 | 个别旧版本 lake 对中文敏感 | 项目放在纯英文路径；工作区用 `D:\挑战杯` 已验证可行 |

---

## 六、与 Python 的关键区别（必读）

| 行为 | Python | Lean 4 |
|------|--------|--------|
| 运行 | `python x.py` 直接解释执行 | `lean --run x.lean` 先编译再运行 |
| 编译检查 | 运行时才报错 | 保存即静态检查，错误实时标红 |
| 类型 | 动态类型 | 强依赖类型 / 证明即程序 |
| 包管理 | pip | lake（含 `lakefile.toml`） |
| 交互 | REPL / Jupyter | Lean InfoView（目标面板） |

Lean 的「编译」本质是**类型检查 + 证明验证**，比 Python 严格得多——
写错类型或证明不成立会立刻报红，这正是它适合数学验证的原因。
