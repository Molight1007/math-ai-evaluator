# -*- coding: utf-8 -*-
"""收敛后仍需成立的解耦不变式（从 test_decouple_stage_a_1007.py 迁来的有效部分）。

被删掉的两条：「开关可覆盖」「shim 与实现同一状态」——测的对象已不存在。
保留并补强的三条：契约层零依赖、utils 不拉 agent、config 只是 POLICY 的投影。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_policy_module_has_no_project_imports():
    """contracts/policy.py 只能依赖标准库，保证 replay/工具链都能安全导入。"""
    tree = ast.parse((ROOT / "contracts" / "policy.py").read_text(encoding="utf-8"))
    mods = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods.append(n.module or "")
    assert mods and all(m.split(".")[0] in {"types", "__future__"} for m in mods), mods


def test_utils_llm_client_does_not_pull_agent():
    """层级门禁：utils/ 不得反向依赖 agent/（收敛后仍然成立）。"""
    code = ("import sys; import utils.llm_client; "
            "print('AGENT_LOADED' if 'agent' in sys.modules else 'CLEAN')")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert "CLEAN" in r.stdout, r.stdout[-400:]


def test_config_fields_are_projections_of_policy():
    """AgentConfig 里 101 个策略字段必须逐字来自唯一权威表，杜绝第二条来源。"""
    sys.path.insert(0, str(ROOT))
    from contracts.policy import POLICY
    from user_agent__config import AgentConfig
    cfg = AgentConfig()
    for k, v in POLICY.items():
        assert hasattr(cfg, k), "config 缺策略字段 %s" % k
        assert getattr(cfg, k) == v, "%s: config=%r 但 POLICY=%r" % (
            k, getattr(cfg, k), v)
