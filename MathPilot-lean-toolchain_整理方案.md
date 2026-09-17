# MathPilot-lean-toolchain 整理方案（Lean/Mathlib/lean-lsp-mcp 软件发行仓）

> 生成：2026-09-06 晚 | 状态：双仓形态落地，Linux 适配本地制备完成（线 A 全绿，零 push）
> **2026-09-07 09:30 更新：线 A（无权限段）全部完成**——发行仓 Linux 树 955M + wheels-linux 7 +
> setup_linux.sh/install_mcp_linux.sh + 双平台契约文档；gitcode_sync 双仓登记；静态验证 25/25。
> 剩余均为线 B（需 push 权限）：B1 发行仓 Linux 适配 → B2 主仓 → B3 gitcode_sync（平台源，最优先）。
> 计划：`docs/平台Lean调用落地计划_20260907.md`；执行清单：`docs/A6改动分类清单_20260907.md`。
> gitcode 仓：`csust-qiming-math/MathPilot-lean-toolchain`（代码仓 + LFS，Initial commit a0302826）
> **2026-09-06 18:40 修订：用户拍板「直接文件树上 LFS，不 zip」——mathlib 完整文件树 2.3G
> + lean 完整 toolchain 3G 全树直传（每文件独立 LFS 对象）；zip 仅为本地中间产物，不入仓**

---

## 一、背景与目标

gitcode 官方建议：Lean / Mathlib 这类大型软件工具应放入独立 LFS 仓库托管，再由
MathPilot 代码仓调用。本方案把 Lean 4.31.0 工具链、Mathlib olean 闭包、
lean-lsp-mcp 0.30.0 统一整理进该 LFS 仓，并在本地搭建完整调用配置
（解压布局 / PATH / LEAN_PATH / LEAN_MCP_PYTHON / LEAN_BACKEND），保证
本地评测、论文实践、评审演示可一键重建可运行 Lean 环境。

## 二、本地资产实测盘点（2026-09-06 晚）

| 资产 | 位置 | 体积 | 处置 |
|---|---|---|---|
| Lean 4.31.0 Windows 工具链 | `~/.elan/toolchains/leanprover--lean4---v4.31.0` | 3.0G | ✅ **完整全树直传 LFS**（用户拍板） |
|  └ bin/（lean/lake/leanc/clang/lld + 全 dll） | | 377M | ✅ 含在完整树内 |
|  └ lib/lean/Lean 树（编译器库 1.3G）+ Init/Std/Lake + .a 静态库（534M） | | 2.6G | ✅ 含在完整树内 |
| Mathlib full 闭包 `data/mathlib-closure` | 29290 文件 2346MB / 2929 olean | 2.3G | ✅ **完整文件树直传 LFS**（用户拍板） |
| Mathlib core 闭包 `data/mathlib-closure-core`（920 olean 695M，实际探测优先） | | 695M | 不入仓（full 已覆盖，避免双份） |
| lean-lsp-mcp 0.30.0（MIT，依赖 leanclient/mcp/orjson） | `~/leanlsp-venv` | 93M venv | ✅ wheels 离线包入仓（用户拍板） |
| Linux Lean 发行版 zip `deploy/lean-4.31.0-linux.zip` | 832M | 832M | ❌ 本次不上传（用户拍板；平台已去 Lean，仅演示潜在用） |

**风险提示（已告知用户）**：全树直传 ≈ 5.3G+ LFS 对象、近 3 万次 LFS 传输、
`libLean.a` 单文件 315M（GitCode LFS 单文件上限未验证）、上传耗时 1-3h+。
olean 文件跨平台通用（同 lean 版本）。

## 三、用户拍板的四项决策（2026-09-06）

1. **lean-lsp-mcp 形态**：wheels 离线包（pip download 全依赖，任意机 --no-index 重建）——不用 venv（绝对路径绑定，移动即坏）
2. **Linux 物料**：本次**暂不上传**
3. **Mathlib 闭包**：**full 2.3G 全量**（覆盖更多 tactic/模块）
4. **主仓衔接**：**git submodule**（挂 vendor/lean-toolchain）

## 四、LFS 仓结构（本地发布目录 D:\lean_toolchain_release —— 直接文件树）

```
MathPilot-lean-toolchain/
├── README.md / VERSION / .gitattributes / 调用约定.md
├── lean/
│   └── lean-4.31.0/                 # 完整 toolchain 树（3.0G）：bin/ lib/ src/ include/ share/
│       ├── bin/lean.exe …           # lean/lake/leanc/clang/lld + 全 dll
│       └── lib/lean/…               # Init/Std/Lean/Lake olean 树 + .a 静态库（完整）
├── mathlib/
│   └── closure-full/                # full 闭包完整文件树（29290 文件 2.3G）
│       ├── Mathlib/ Batteries/ Aesop/ LeanSearchClient/ ImportGraph/ …
├── lean-lsp-mcp/
│   ├── wheels/*.whl                 # lean-lsp-mcp==0.30.0 + 依赖锁版本（45 个 18M）
│   ├── requirements-lock.txt
│   └── install_mcp_windows.ps1
└── scripts/
    ├── setup_windows.ps1            # 生成 lean-env.ps1 + 探针自验
    └── probe_lean.lean              # norm_num/ring/linarith/nlinarith/positivity/omega
```

LFS 追踪：`*.olean *.olean.private *.exe *.dll *.ir *.ilean *.hash *.server *.a` → LFS
（大二进制）；`*.whl` → LFS；文本（.lean/.md/.ps1/配置）走普通 git。
中间产物（lean zip 181M / closure zip 699M）仅本地留存，不入仓。

## 五、调用配置约定（对齐 tools/lean_local/lean_bridge.py 现有探测，主仓零代码改动）

| 项 | 值 | 消费方 |
|---|---|---|
| lean 可执行 | `<toolchain>/lean/bin/lean.exe`（先 PATH，后显式） | lean_bridge `detect_lean_environment` |
| LEAN_PATH | `<root>/mathlib/closure-full`（闭包解压目录） | lean 直编模块搜索 |
| LEAN_MCP_PYTHON | lean-lsp-mcp venv 的 python.exe | lean_bridge MCP 后端启动 |
| LEAN_BACKEND | `bridge` / `mcp` | lean_bridge 后端切换 |
| LEAN_PROJECT_PATH / LEAN_LOG_LEVEL / LEAN_MCP_GOAL_LOC | 按需 | MCP 后端 |

主仓挂载：`git submodule add https://gitcode.com/csust-qiming-math/MathPilot-lean-toolchain vendor/lean-toolchain`
（子模块只读引用发行物；本地执行 `scripts/setup_windows.ps1` 后 lean 环境就绪）

## 六、执行与验证记录

- [x] lean-lsp-mcp wheels：45 个 18M + requirements-lock.txt（45 行）
- [x] lean 完整 3G 树复制（bin 377M + lib 2.6G + src/include/share，14627 文件，robocopy /MT
      补齐 173 个被锁跳过的 src 文件，源目标逐文件大小比对一致）
- [x] closure 完整文件树解压（29290 文件 / 2929 olean / 2.3G，robust 覆盖式）
- [x] **探针验证通过**：release `lean/lean-4.31.0/bin/lean.exe` + LEAN_PATH=closure-full，
      norm_num/ring/linarith/nlinarith/positivity/omega 全部 exit=0
      （注：闭包不含 Mathlib.Data.Nat.Prime——BFS 闭包边界内模块才可用，探针已收敛）
- [x] 中间产物清理（lean zip 181M / closure zip 699M 已删；lean/windows 冗余子集 gitignore 排除）
- [x] LFS 仓 git init + commit 2c137e97（41495 LFS 对象 / 43971 文件暂存）
- [x] **克隆一致性冒烟通过（云端=本地验收）**：git clone --no-local 强制走真实传输
      （41495 LFS 对象 / 5.10 GiB 全部从源传输，非硬链接）→ 克隆副本 git lfs fsck **OK**
      → 克隆副本跑探针 **exit=0** → lean --version 4.31.0 一致。证明云端拉取与本地无能力差异
- [x] 脚本修正（9/6 19:40）：ps1 全 ASCII 化（PowerShell 5.1 无 BOM UTF-8 中文注释按 GBK
      解码致语法崩）；requirements-lock.txt 前缀改仓根相对路径 `lean-lsp-mcp/wheels/`
- [x] **lean-lsp-mcp 离线重建实测通过**：install_mcp_windows.ps1 从 45 wheels 全装
      （lean-lsp-mcp 0.30.0/leanclient 0.13.2/mcp 2.0.0…）+ `import OK`
- [x] **setup_windows.ps1 实测通过**：生成 lean-env.ps1 + 探针 PASSED
- [x] **push 成功（9/6 21:26）**：LFS 41494/41494（5.5GB @1.7MB/s，1h13m）→ force update
      `a0302826...830a6149 main->main`（远端占位 commit 仅模板 LICENSE/README，本地补 LICENSE 后
      force 覆盖）。GitCode 控制台显示**仓库 9.97 GB** / 上限约 100 GiB——
      那条 `lfs_repo 5.1 GiB exceeds 5.0 GiB` 是**个人免费 LFS 配额告警线**（不是硬上限）：
      **push 实测 5.2 GiB 已超线仍成功 = 告警不阻断**。100 GiB 仓库总上限内可继续推 LFS；
      5 GiB quota 仅作**监控项**。发版可追溯仍建议走新版本化仓库（属主动策略，非配额所迫）
- [x] **远端真 clone 终验通过（9/6 22:00 收尾）**：后台 eygdWu 从 GitCode 网络下载 5.3G
      （1h17m）→ commit 830a6149 → `git lfs fsck` **OK** → 探针 **exit=0** →
      olean 计数 2929+2421 与本地一致 → `lean --version` 4.31.0 一致。
      **结论：云端=本地无能力差异，本会话复跑探针 exit=0 复核通过**
- [x] **主仓 submodule 登记 vendor/lean-toolchain（9/7 早）**：gitlink 160000→830a6149 已入 index +
      .gitmodules 已建 + superhuman 损坏 gitlink 已移除登记（git rm --cached，工作树数据保留
      imobench csv，.gitignore 补 superhuman/ 防误加）。
      **配置完成 + 双仓调用验证通过（9/7 8:05）**：
      - commit：`chore: 挂载 vendor/lean-toolchain submodule…`（4 files）
      - vendor 工作树已填充：robocopy remote_test → vendor（43972 文件 / 5.13G / 24s），
        vendor 内探针 exit=0、olean 2929、git status 干净（reset 修复 --no-checkout 空 index）
      - `git submodule init` 后 status = `830a6149 vendor/lean-toolchain (heads/main)`（已初始化+已 checkout）
      - lean_bridge vendor 探测路径源码确认（L87-90/L148-149）；本地探测链 elan→lean下载版→vendor
        后备，任一命中即用
      - 本地调用链验证 7/7（`docs/C方案本地调用链验证_20260907.md`）
- [x] **gitcode_sync 双仓登记（9/7 线 A）**：.gitmodules + vendor gitlink(160000→830a6149) 入 index
      （AD 状态正常，commit 时生效；sync_mirrors 不含 vendor/.gitmodules，不会被镜像覆盖）
- [x] **发行仓 Linux 适配本地制备（9/7 线 A，未 push）**：lean/lean-4.31.0-linux/（955M 解压树，
      ELF 头验证）+ wheels-linux/（7 manylinux）+ requirements-linux.lock（44 行）+ setup_linux.sh +
      install_mcp_linux.sh + VERSION/README/调用约定.md 双平台更新
- [x] **双仓静态验证 25/25（9/7）**：`C:\Users\35174\platform_sim_check.py`
      （资产/登记/探测链/契约四组断言；报告 `docs/平台双仓静态验证_20260907.md`）
- [ ] ⏸ 待用户回权限环境（线 B，见 `docs/平台Lean调用落地计划_20260907.md`）：
      ①在制品/论文实践 commit 分组裁决（`docs/A6改动分类清单_20260907.md`）
      ②push vendor 发行仓 Linux 适配（B1）③push 主仓 gitcode/github（B2）
      ④gitcode_sync 同步 + .gitmodules commit + push（B3，平台实际拉取源，最优先）
      ⑤平台答复 Q1-Q4 → 模式决策收敛（B5）

## 七之补、平台能否调用（2026-09-06 结论 → 9/6 晚 C 方案适配中）

**上传的工具「本身可用」已全链验证 ✅；「平台能否调用」处于 C 方案适配中（用户 9/6 晚拍板：默认支持双仓引用，继续适配）**。

历史归因与当前状态分层记录：

1. **历史事实（0905 归因文件）**：平台容器此前无 Lean 可执行文件（历史归因实证）、无外网
   （无法 clone/LFS 下载）、官方 Client 托管；2026-09-06 平台检测链已去 Lean
   （lean_gate→audit_gate，见 tools/lean_local/README.md），平台走 AI 判分。
2. **⚠️ 此前的"平台为 Linux"是假设**：官网规则全文无 OS 描述，deploy/README.md 中"评测容器
   （Linux）"系我方假设，咨询模板第 4 问仍将 OS 列为待确认项。**平台 OS 从未被官方确认**。
3. **C 方案（平台直接调用 Lean 验证）可行性待平台答复 4 问**（见 `docs/平台C方案咨询_20260906.md`）：
   ①评测是否支持多仓引用（唯一官方机制=只拉绑定 main 分支，无第二仓库）②提交包内附带
   可执行文件是否合规 ③提交包体积上限 ④评测容器 OS。
   用户已拍板**默认按"支持双仓引用"继续适配**（主仓 submodule 挂 vendor/lean-toolchain）。

→ 本 LFS 仓价值（双轨）：**C 方案适配的依赖仓 + 版本化软件发行 + 评审/材料可复现证据**（材料分 40%）：
老师/评委在有 Lean 的机器上 `git clone` + `setup_windows.ps1` 即可一键复现本地证据链。
若平台答复后 C 方案不可行，则回归"本地证据链 + 材料"路线，本仓仍是核心资产。


## 七、风险与回退

- **GitCode 容量实测结论（2026-09-06 二次修正）**：仓库总上限 ≈ 100 GiB（硬约束）；**5 GiB 是个人免费
  LFS 配额告警线（软告警，push 实测超线仍成功，不阻断）**。当前 9.97 GB（LFS 对象 5.2 GB + working
  tree 5.9 GB）远在 100 GiB 内。
  - **后续策略**：①5 GiB quota 仅作**监控项**（每次 push 后核对 `git lfs fsck` 即可），无需为配额
    刻意压缩或拆分；②发版可追溯仍走新版本化仓库（如 `MathPilot-lean-toolchain-v431`，属主动策略）；
    ③仅在单仓增长接近 100 GiB 时，才用 `git lfs migrate` 把小文件合并进 git 普通对象腾空间
- **libLean.a 单文件 315 MB**：GitCode LFS 单文件上限未实测确认——若 push 被限，回退方案：
  lean 换 zip 单对象（181MB）、closure 换 zip 单对象（699MB）→ 总量 <1GB 但失去"clone 即用"优势
- 几万小文件逐个 LFS 上传慢 → push 前可用 `git lfs migrate` 只把 >1MB 文件 LFS 化、小文件走
  普通 git（hash 等缓存文件几 KB，无需 LFS），显著减少对象数
- zip 解压/复制中途文件锁（杀软）→ robust 重试已就位
- closure-full 目录曾被进程占用（WinError 32）→ 若再次发生需定位占用进程（explorer/杀软）
