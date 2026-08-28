# Git 上传能力配置指南

> 目标：让任何 AI 工具（Work Buddy、CodeBuddy、Claude 等）在"本机/沙箱"环境中能成功把本地代码推送到远程仓库（GitHub / GitCode / AtomGit）。
>
> 适用系统：Windows（PowerShell）、macOS / Linux（Bash）。本文以 Windows + PowerShell 为例，macOS/Linux 命令基本一致。

---

## 一、核心原理（先看这个）

**AI 无法凭空推送代码，推送必须由机器上的 `git` 程序完成，且必须有"身份凭据"。**

完整链路是：

```
AI 生成/修改代码
      ↓
AI 调用命令行执行 git（commit / push）
      ↓
git 用"凭据"向远程服务器证明身份
      ↓
服务器校验通过 → 代码写入远程仓库
```

任何一环缺失（没装 git / 没凭据 / 没权限 / 没网络），推送就会失败。**这不是 AI 能力问题，是环境配置问题。**

---

## 二、前置检查（3 步确认环境）

### 1. 确认 git 已安装

```powershell
git --version
```

有输出（如 `git version 2.47.0`）→ 已安装；提示"不是内部或外部命令"→ 先安装：

- Windows：https://git-scm.com/download/win （一路下一步即可）
- macOS：`brew install git`
- Linux：`sudo apt install git`

### 2. 确认网络可达远程仓库

```powershell
ping github.com          # GitHub（国内可能不通，属正常）
ping gitcode.com         # GitCode / AtomGit（国内通常可通）
```

> 注意：GitHub 在国内网络环境下经常超时，可改用 GitCode（AtomGit）或配置代理。网络不通时任何上传都会失败。

### 3. 配置基本身份（仅首次）

```powershell
git config --global user.name "你的名字或ID"
git config --global user.email "你的邮箱"
```

---

## 三、三种认证方式（任选其一即可）

### 方式 A：用"已登录的 git"（推荐，最省事）

在**本机终端**手动完成一次推送，让系统记住登录状态：

```powershell
# 1. 克隆仓库（会弹出浏览器/凭据窗口，完成一次登录）
git clone https://gitcode.com/<用户名>/<仓库名>.git

# 2. 进入目录、复制代码、提交、推送
cd <仓库名>
git add -A
git commit -m "init"
git push origin main
```

登录一次后，Windows 凭据管理器会记住账号，**以后任何 AI 在本机调用 `git push` 都无需再登录**。

验证是否已记住凭据：

```powershell
git config --global credential.helper
```

有输出（如 `manager`）即表示已启用凭据记住功能。

---

### 方式 B：用 Personal Access Token（适合 AI 在沙箱/隔离环境）

#### GitHub 生成 Token

1. 打开 GitHub → 右上角头像 → **Settings**
2. 左侧 **Developer settings** → **Personal access tokens** → **Tokens (classic)**
3. **Generate new token** → 勾选 `repo` 权限（建议勾选 `workflow` 如果你要推 GitHub Actions）
4. 生成后**立即复制保存**（只显示一次）

#### GitCode 生成 Token

1. 打开 gitcode.com → 登录 → 右上角头像 → **设置 / Settings**
2. 找到 **Access Tokens / 访问令牌** → **新建令牌**
3. 勾选 `projects`（仓库读写）权限 → 生成并复制保存

#### 把 Token 配置进远程地址

```powershell
# 方式1：直接拼进 URL（最简单，但 token 会明文存进 .git/config，注意别外泄）
git remote add origin https://<TOKEN>@github.com/<用户名>/<仓库名>.git
# GitCode 同理：
git remote add origin https://<TOKEN>@gitcode.com/<用户名>/<仓库名>.git

# 方式2：更安全——用凭据管理器保存（推荐）
git remote add origin https://<用户名>@github.com/<用户名>/<仓库名>.git
git push -u origin main
# 首次推送会提示输入用户名/密码 → 用户名填你的ID，密码粘贴 Token
```

#### 交给 AI 时怎么写

告诉 AI：

> 远程仓库地址（已含 Token）：`https://<TOKEN>@gitcode.com/<用户名>/<仓库名>.git`
> 请在克隆/推送时直接使用这个地址，不要问我要账号密码。

---

### 方式 C：用 SSH Key（适合长期使用）

#### 1. 生成密钥（已有可跳过）

```powershell
ssh-keygen -t ed25519 -C "你的邮箱"
# 一路回车，生成在 ~/.ssh/id_ed25519
```

#### 2. 添加公钥到平台

```powershell
cat ~/.ssh/id_ed25519.pub   # 复制输出的整段内容
```

- GitHub：Settings → **SSH and GPG keys** → New SSH key → 粘贴
- GitCode：设置 → **SSH 公钥** → 添加 → 粘贴

#### 3. 用 SSH 地址推送

```powershell
git remote add origin git@github.com:<用户名>/<仓库名>.git
git push -u origin main
```

---

## 四、AI 上传的标准操作流程（给 AI 的指令模板）

把下面这段话发给任何 AI，它就能在具备环境的情况下完成上传：

> 请帮我完成以下 Git 上传操作：
> 1. 当前代码在 `<本地目录路径>`（或已在本工作区）。
> 2. 目标远程仓库地址：`<https://<TOKEN>@gitcode.com/<用户名>/<仓库名>.git 或 git@...>`
> 3. 需要推送到分支：`main`
> 4. 提交信息：`<描述>`
>
> 请执行：
> ```
> git init
> git add -A
> git commit -m "<描述>"
> git branch -M main
> git remote add origin <远程地址>
> git push -u origin main
> ```
> 如果仓库已有内容，请先 `git pull origin main --allow-unrelated-histories` 再推送。

---

## 五、常见报错与解决

| 报错信息 | 原因 | 解决办法 |
|----------|------|----------|
| `Authentication failed` / `403` | 凭据错误或无权限 | 重新生成 Token；确认你是仓库成员/owner |
| `Repository not found` | 仓库地址拼错，或无权访问私有仓库 | 检查地址；确认账号有权限 |
| `failed to push some refs` | 远程已有你本地没有的提交 | 先 `git pull origin main --rebase` 再 push |
| `connect to github.com timed out` | GitHub 国内网络不通 | 换 GitCode；或配置代理 |
| `not a git repository` | 没在 git 仓库内执行 | 先 `git init` 或在正确目录执行 |
| `Please make sure you have the correct access rights` | SSH key 未添加/失效 | 重新添加公钥；确认用对了账号 |
| `remote: Invalid username or password` | 账号或 Token 输错 | 用户名填 ID，密码处粘贴 Token |

---

## 六、给"别人/另一个 AI"的完整交接话术（可直接复制）

> 想让你能上传代码到远程仓库，需要你运行的机器满足：
> 1. 已安装 git（`git --version` 有输出）。
> 2. 网络可访问目标仓库（GitHub 或 GitCode）。
> 3. 具备身份凭据之一：
>    - 本机已登录过（方式 A），或
>    - 提供了一个含 Token 的远程地址（方式 B），或
>    - 配置了 SSH key（方式 C）。
>
> 三者缺一，AI 都无法完成推送，请先按《Git 上传能力配置指南》配置环境，再让我执行上传。

---

## 附：本次实际案例（2026-08-23）

在 `d:\挑战杯` 项目上，从 GitHub `sq` 分支提取赛事提交版并推送到 GitCode 仓库 `gcw_newGj9Pg/csustshuxue` 的 main 分支，最终成功（commit `bc0aa64`，49 个文件）。成功的关键就是：**本机 git 已配置 gitcode 凭据 + 命令行可执行 + 网络可达**。
