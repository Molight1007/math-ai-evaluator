# -*- coding: utf-8 -*-
"""实验臂配置的不变式测试（2026-09-21）。

背景：本项目已**四次**踩同一类坑 —— 注释/CLI 承诺了一个开关，但该键
① 未在 `AgentConfig` 声明，或 ② 不在 `ReasoningAgent.__init__` 的覆盖白名单内
⇒ kwargs 覆盖被**静默丢弃**，开关是「假的」。

`deploy/run_112.py` 的 `ARMS` 引入后，这类风险会随臂数量增长。
本测试把「臂里出现的每个键都必须三层齐备」固化为**不变式**：
  ① 在 `AgentConfig` 中已声明
  ② 在 `ReasoningAgent.__init__` 的覆盖白名单内
  ③ `setattr` 后能读到新值

⚠ 注意 `enable_skeleton_review` 的反例形态：它有注解承诺
`--enable_skeleton_review`，但 `run_eval.py` 里**不存在**该 argparse
⇒ 本测试额外校验「臂键必须可经 DEFAULT_AGENT_OVERRIDES 注入」（①②③已覆盖）。
"""
import ast
import importlib.util
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RUN112 = REPO / "deploy" / "run_112.py"


def _load_run112():
    """载入启动器模块（其 main() 有 __main__ 守卫，不会执行）。

    注意：该模块顶层会 `os.chdir(REPO)`，故保存并恢复 cwd，避免污染其它测试。
    """
    cwd0 = os.getcwd()
    try:
        spec = importlib.util.spec_from_file_location("_run112_test", str(RUN112))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd0)


def _whitelist():
    """从 `ReasoningAgent.__init__` 里抽取 kwargs 覆盖白名单（ast，非正则）。"""
    tree = ast.parse((REPO / "user_agent.py").read_bytes().decode("utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ReasoningAgent":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "__init__":
                    for sub in ast.walk(fn):
                        if isinstance(sub, ast.For) and isinstance(sub.iter, ast.Tuple):
                            for elt in sub.iter.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    keys.add(elt.value)
    return keys


@pytest.fixture(scope="module")
def run112():
    return _load_run112()


@pytest.fixture(scope="module")
def arms(run112):
    return run112.ARMS


@pytest.fixture(scope="module")
def whitelist():
    return _whitelist()


class TestArmKeyContract:
    """每个臂键都必须三层齐备（否则是「假开关」）。"""

    def test_arms_not_empty(self, arms):
        assert arms, "ARMS 不应为空"
        assert "baseline" in arms, "必须保留 baseline 臂"

    def test_baseline_is_empty(self, arms):
        assert arms["baseline"] == {}, "baseline 臂必须为空（不改任何机制）"

    def test_every_arm_key_is_declared(self, arms):
        from user_agent import AgentConfig
        declared = set(AgentConfig.__dataclass_fields__)
        missing = [(a, k) for a, ov in arms.items() for k in ov if k not in declared]
        assert not missing, "以下臂键未在 AgentConfig 声明：%r" % missing

    def test_every_arm_key_is_whitelisted(self, arms, whitelist):
        missing = [(a, k) for a, ov in arms.items() for k in ov if k not in whitelist]
        assert not missing, (
            "以下臂键不在 ReasoningAgent 覆盖白名单 ⇒ kwargs 会被静默丢弃：%r" % missing)

    def test_every_arm_key_actually_applies(self, arms):
        from user_agent import AgentConfig
        bad = []
        for a, ov in arms.items():
            for k, v in ov.items():
                cfg = AgentConfig()
                try:
                    setattr(cfg, k, v)
                    if getattr(cfg, k) != v:
                        bad.append((a, k, "setattr 后值不一致"))
                except Exception as exc:  # noqa: BLE001
                    bad.append((a, k, "%s: %s" % (type(exc).__name__, exc)))
        assert not bad, "以下臂键无法应用：%r" % bad


class TestResolveArm:
    """resolve_arm 的取值语义。"""

    def test_default_is_baseline(self, run112, monkeypatch):
        monkeypatch.delenv("MP_ARM", raising=False)
        name, ov = run112.resolve_arm()
        assert name == "baseline"
        assert ov == {}

    def test_known_arm_resolves(self, run112, monkeypatch):
        monkeypatch.setenv("MP_ARM", "arm2")
        name, ov = run112.resolve_arm()
        assert name == "arm2"
        assert ov == run112.ARMS["arm2"]

    def test_resolves_to_a_copy_not_the_constant(self, run112, monkeypatch):
        """必须返回副本：调用方随后会往 dict 里写，不能污染 ARMS 常量。"""
        monkeypatch.setenv("MP_ARM", "arm2")
        _, ov = run112.resolve_arm()
        assert ov is not run112.ARMS["arm2"]

    def test_whitespace_tolerated(self, run112, monkeypatch):
        monkeypatch.setenv("MP_ARM", "  arm2  ")
        assert run112.resolve_arm()[0] == "arm2"

    def test_unknown_arm_fails_loudly(self, run112, monkeypatch):
        """未知臂名必须 FATAL —— 绝不静默回落到 baseline（否则会跑错配置还以为跑了臂）。"""
        monkeypatch.setenv("MP_ARM", "__bogus__")
        with pytest.raises(SystemExit):
            run112.resolve_arm()

    def test_cli_arg_takes_precedence_over_env(self, run112, monkeypatch):
        """`--arm` 优先于 `MP_ARM`：cloud.py 只能传命令行参数，传不到环境变量。"""
        monkeypatch.setenv("MP_ARM", "arm1")
        assert run112.resolve_arm("arm2")[0] == "arm2"

    def test_cli_arg_used_when_env_absent(self, run112, monkeypatch):
        monkeypatch.delenv("MP_ARM", raising=False)
        assert run112.resolve_arm("arm2")[0] == "arm2"
        assert run112.resolve_arm("  arm2  ")[0] == "arm2"

    def test_cli_unknown_arm_also_fails_loudly(self, run112, monkeypatch):
        monkeypatch.delenv("MP_ARM", raising=False)
        with pytest.raises(SystemExit):
            run112.resolve_arm("__bogus__")

    def test_arm_cli_is_registered_in_argparse(self):
        """端到端确认 `--arm` 真的注册进了 argparse。

        为什么必须真跑一次：`tools/cloud.py run` 只支持
        `--launcher_args "<参数>"` 来传臂名，**无法设远端环境变量**。
        若 `--arm` 没注册，启动时会直接 argparse 报错 —— 那是在浪费一次
        26 小时的服务器排队等待之后才发现的。故此检查必须前移到这里。
        """
        import subprocess
        r = subprocess.run(
            [sys.executable, str(RUN112), "--help"],
            capture_output=True, text=True, cwd=str(REPO), timeout=120)
        assert r.returncode == 0, "启动器 --help 失败：%s" % (r.stderr or "")[:400]
        assert "--arm" in r.stdout, "启动器未注册 --arm 参数"
        for a in ("baseline", "arm2"):
            assert a in r.stdout, "--arm 的 help 未列出臂名 %s" % a


class TestArmSemantics:
    """锁定各臂的预期语义（防止被误改）。"""

    def test_arm2_is_blueprint_structural_fix(self, arms):
        """臂 2 = 蓝图结构修复 + 评审链恢复，四项全 True。"""
        assert arms["arm2"] == {
            "blueprint_or_expand_all": True,
            "dag_replan_gate": True,
            "enable_dag_replan": True,
            "enable_skeleton_review": True,
        }

    def test_arm2_keys_default_to_false(self):
        """臂 2 的作用必须真的是「False → True」；若默认已 True 则臂是空转。"""
        from user_agent import AgentConfig
        cfg = AgentConfig()
        for k in ("blueprint_or_expand_all", "dag_replan_gate",
                  "enable_dag_replan", "enable_skeleton_review"):
            assert getattr(cfg, k) is False, (
                "%s 类默认已是 True，臂 2 将空转（应改臂定义或改默认）" % k)
