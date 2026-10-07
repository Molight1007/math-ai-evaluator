# -*- coding: utf-8 -*-
"""阶段 B1 契约验证：`contracts/` 下沉 + `agent/base.py` re-export。

方案 §B2 的口径是「**保契约、改实现**」：
把被 `tools/` 反向依赖的**纯数据**下沉到 `contracts/`，在原处 re-export
⇒ 下游所有 `from agent.base import Budget/Finding/BugReport` **一行都不用改**，
且拿到的仍是**同一个对象**（`is` 相等）。

本文件把这三条契约钉住：
  ① `agent.base` 仍可导出 Budget/Finding/BugReport，且 `is` 同一对象；
  ② `tools/lean_local/{lean_bridge,lean_gate}` 也拿到**同一对象**（改从 contracts 导入后不串味）；
  ③ `TaskContext` 在 tools 侧是 `contracts.protocols` 的 Protocol（注解级解耦），
     而 agent 侧实体仍在 `agent.base`。
"""
from __future__ import annotations

import unittest


class ReExportContractTest(unittest.TestCase):
    def test_agent_base_reexports_same_objects(self) -> None:
        from agent import base as ab
        from contracts import types as ct
        for name in ("Budget", "Finding", "BugReport"):
            self.assertTrue(hasattr(ab, name), "agent.base 缺 %s（契约破坏）" % name)
            self.assertIs(getattr(ab, name), getattr(ct, name),
                          "agent.base.%s 与 contracts.types.%s 不是同一对象" % (name, name))

    def test_lean_local_gets_same_objects(self) -> None:
        from contracts import types as ct
        from tools.lean_local import lean_bridge as lb
        self.assertIs(lb.BugReport, ct.BugReport)
        self.assertIs(lb.Finding, ct.Finding)
        from tools.lean_local import lean_gate as lg
        self.assertIs(lg.Budget, ct.Budget)

    def test_taskcontext_split(self) -> None:
        # tools 侧用 Protocol（contracts），agent 侧实体不变
        from contracts import protocols as cp
        from agent import base as ab
        self.assertTrue(hasattr(cp, "TaskContext"))
        self.assertIsNot(cp.TaskContext, ab.TaskContext)
        from tools.lean_local import lean_pre_verifier as lpv
        self.assertIs(lpv.TaskContext, cp.TaskContext)
        # agent 实体仍是真类（未被改动语义）
        self.assertTrue(isinstance(ab.TaskContext, type))


if __name__ == "__main__":
    unittest.main()
