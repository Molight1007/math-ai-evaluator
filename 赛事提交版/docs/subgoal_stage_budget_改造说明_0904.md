# subgoal 阶段预算改造说明（2026-09-04）

## 背景（数据驱动）

preverify 提速后（bridge 平均 393s → mcp 平均 ~89s），省下的 ~300s
**没有流向 solve/验证/闸门，而是全被子目标阶段贪婪 re-plan/re-review 吃掉**：

- bridge 18 题：sub 529-717s（正确 3 题 sub 全在 661-717s）
- mcp 轮（新代码、无本改造）：sub 780-1112s

后果：merge 被挤进 `is_time_critical` 区 → 走 fallback 而非真合并。
**060 实证**：bridge sub 717s 对（答案 2617/2618）；mcp sub 1111s 错
（答案停在 S(1)..S(12) 枚举，未合成最终最大值）——不是推理错了，
是**没时间收尾**。

## 改造内容（agent/sub_goal_solver.py，三副本已同步）

### 第一层：子目标阶段固定上限（默认 750s）

- 配置：`subgoal_stage_budget_sec`（默认 750.0，0=放弃固定上限）
- 依据：bridge 正确题 sub ≤717s → 750s 保住已知正确深度；
  mcp 失控题 780-1112s → 刹住
- 触发点（均在 `run()` 内）：
  1. 子目标循环：预算用尽 → 停解新子目标（**不 return**，保留已解结果）
  2. 失败重试：`_stage_left() <= 120s` → 放弃重试（重试=一次完整 LLM 60-110s）
  3. 阶段四 DAG replan：预算用尽 → 跳过（候选已入池，replan 是"改进"非"产出"）

### 第二层：deadline 前强制收尾（tail reserve，默认 90s）

- 配置：`subgoal_tail_reserve_sec`（默认 90.0，0=关闭）
- `_subgoal_stage_end = min(stage_start + budget, ctx.deadline - 90)`
- 给 6_format + 6.5_lean_gate 留底线时间（各 ~30-45s）
- **与固定预算解耦独立**：即便 `subgoal_stage_budget_sec=0`，
  deadline-90 的硬约束依然生效（"保证体系跑得完"的底线）

### merge 强制真跑

- 阶段三 merge：即使 stage 预算已用尽，只要全局未 `is_time_critical`
  就**必须真 merge**（合成最终结论），不再 fallback 到最后一个子目标
- 保护：预算已尽且一个子目标都没解出 → 跳过空 merge（防垃圾候选）

### 并发安全（关键）

- 时钟挂 **ctx**（每题独立），**不挂 self**：
  EvalEngine 的 agent 是共享单例，ThreadPoolExecutor 并发 2 时
  同一实例同时服务多题，self 属性会竞态
- ctx._subgoal_stage_start 供 orchestrator 多次调用 run()（2.7 /
  deep 3_solve / 3.5）共享，避免"每次调用重置预算"把总时间再吃一遍

## 预期效果

- sub 阶段从 780-1112s → ≤750s（或 deadline-90 更紧）
- merge 有真时间合成最终答案（治 060 型 extract_failed）
- 后续 3_solve/lean 验证/6.5 闸门从"只剩 60-100s"恢复到 ~300s

## 验证

- tests/test_sub_goal_solver.py 新增 StageBudgetTest 5 例：
  固定预算写 ctx / tail reserve 封顶 / 双关停用 / 时钟跨 run 共享
- 全套 306 tests PASS（含既有 29 例 sub_goal 相关）
- 三副本（主项目/赛事提交版/gitcode_sync）哈希一致

## 待 A/B 验证（本轮 mcp 评测跑完后）

- 等当前 mcp 基线轮（无 subgoal 上限）跑完 → 与 bridge 3/18 对比
- 再开"mcp + subgoal 上限"轮 → 验证正确率是否保住/提升、总时长回落
- 观察点：060/068（bridge 对 → mcp 错）是否修复
