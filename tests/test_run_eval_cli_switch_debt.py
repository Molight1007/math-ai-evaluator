# -*- coding: utf-8 -*-
"""`run_eval.py` CLI 入口守卫（2026-10-07，fix-switch-debt）。

背景
----
B 项补齐了 9 条此前**漏加白名单**的 A/B 开关（`AgentConfig` 有字段、有读取点，
但既不在覆盖白名单、也没有 CLI 参数）⇒ 相关开关的「回退路径在代码层面不存在」。
白名单侧已由 `tests/test_arm_config_0921.py` / `test_mechanism_switches_0921.py`
覆盖；本文件补上**CLI 侧**的不变式：

  ① 这 9 个键都必须在 `run_eval.main()` 里注册 `--<key>` 的 `add_argument`；
  ② 都必须被写进 `overrides["<key>"]`（否则传了参数也只是摆设）。

⚠ 用 AST 而非 subprocess `--help`：`run_eval.py` 顶层 import 较重（user_agent /
llm_client），且本仓库有多处子进程被沙箱策略拦截的先例；AST 静态、快、确定。
"""
from __future__ import annotations

import ast
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
RUN_EVAL = REPO / "run_eval.py"

# 9 条 fix-switch-debt 补齐的 CLI 键（见 run_eval.py 的 add_argument 块注释）。
NINE = (
    "accept_confidence",
    "enable_deterministic",
    "enable_answer_falsifier",
    "audit_gate_skip_non_proof",
    "enable_subgoal_main_path",
    "inject_mathlib_to_solver",
    "objective_tactic_enabled",
    "symbolic_max_tokens",
    "symbolic_solve_max_tokens",
)


def _tree():
    return ast.parse(RUN_EVAL.read_bytes().decode("utf-8"))


def _cli_options() -> set:
    """收集 `add_argument("<opt>", ...)` 的首个字符串参数（即 CLI 选项名）。"""
    opts = set()
    for node in ast.walk(_tree()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            opts.add(node.args[0].value)
    return opts


def _override_keys() -> set:
    """收集对 `overrides[...]` 的字符串下标写入键。"""
    keys = set()
    for node in ast.walk(_tree()):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "overrides"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            keys.add(node.slice.value)
    return keys


def test_nine_switches_have_cli_flags():
    opts = _cli_options()
    missing = ["--" + k for k in NINE if ("--" + k) not in opts]
    assert not missing, "以下开关缺 CLI 入口 ⇒ 命令行传不进：%r" % missing


def test_nine_switches_flow_into_overrides():
    keys = _override_keys()
    missing = [k for k in NINE if k not in keys]
    assert not missing, (
        "以下开关虽有 CLI 参数但未写入 overrides ⇒ 传了也是摆设：%r" % missing)


def test_nine_switches_default_none_keeps_behavior():
    """全部 `default=None` ⇒ 不传即保持类默认，行为与改动前逐字一致。"""
    defaults = {}
    for node in ast.walk(_tree()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("--")):
            name = node.args[0].value[2:]
            if name not in NINE:
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            dv = kw.get("default")
            defaults[name] = (dv.value
                              if isinstance(dv, ast.Constant) else "<non-const>")
    bad = {k: v for k, v in defaults.items() if v is not None}
    assert not bad, "这 9 个键必须 default=None（否则会改变既有默认行为）：%r" % bad
    assert set(defaults) == set(NINE), (
        "未解析到的键：%r" % (set(NINE) - set(defaults)))
