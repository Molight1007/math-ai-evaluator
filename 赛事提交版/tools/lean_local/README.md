# tools/lean_local —— Lean 系工具归档（去 Lean 化，2026-09-06）

## 背景

平台无 Lean 可执行文件（历史归因实证）。2026-09-06 起，平台检测链彻底去 Lean：

- 原 `agent/lean_gate.py`（答案硬验证）→ 由 `agent/audit_gate.py`（AuditGate 多级瀑布：
  Level0 程序硬核验 → Level1 反例 → Level2 LLM rubric → Level3 playoff）顶替
- 原 `agent/lean_pre_verifier.py`（前置形式化）→ orchestrator 2.6 位改走
  `audit_gate.confirm_understanding`
- 其余 Lean 集成点（sub_goal_solver / blueprint_planner / user_agent 配置）一并摘除

**Lean 的本地价值保留**：老师核心关切 #1 = 用 Lean+Mathlib 对 AI 解答做形式化自动
验证（本地证据链，占材料分）。故全部 Lean 代码**物理迁出 agent/prompts/tests**，
归档到此包，线下仍可跑。

## 内容

| 原位置 | 现位置 |
|---|---|
| agent/lean_bridge.py …（7 文件） | tools/lean_local/*.py |
| prompts/lean_pre_verify.py、lean_refiner.py、lean_translator.py | tools/lean_local/prompts/ |
| tests/test_lean_*.py（9）+ test_sketch_audit + test_theorem_call_stats + validate_mathlib | tools/lean_local/tests/ |
| tools/leap_eval.py（LEAP 三阶段 Lean 端到端跑分） | tools/lean_local/leap_eval.py |

## 运行前提（全部在仓库根目录 D:/挑战杯 下执行）

1. 本地 Lean 工具链 + Mathlib 闭包就绪：
   - 自动探测 `D:/mathlib4-last_bump_for_v4.31.0`、`<root>/lean下载版/test_mathlib`、
     `<root>/data/mathlib-closure`
   - 依赖 `agent/`（base/blueprint_planner/answer_oracle 等）与 `utils/`、
     `<root>/prompts` 无关（prompts 已一并归档）
2. import 已改为绝对路径（`tools.lean_local.*` / `agent.*`），因此**必须**在仓库
   根目录运行（仓库根在 sys.path 上）。

## 常用命令

```bash
# 归档测试（多数需 Lean 环境；无 Lean 时自动 skip）
python -m pytest tools/lean_local/tests/test_lean_bridge.py -q

# Mathlib 闭包就绪性探测
python tools/lean_local/tests/validate_mathlib.py

# LEAP 三阶段 Lean 端到端跑分（需有效 API key）
python tools/lean_local/leap_eval.py --backend intern --limit 3 --out eval_out
```

## 注意

- 归档模块读配置一律 `getattr(cfg, ...)` 兜底；平台 `AgentConfig` 已删除 lean 字段，
  归档工具需要时自行 `setattr`（见 leap_eval.py main 的写法）。
- 本包不进入平台部署闭包；赛事提交版 / gitcode_sync 同步时保持与主仓库一致
  （去 Lean 后两份镜像同样不携带 lean 模块）。
