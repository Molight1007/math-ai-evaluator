# -*- coding: utf-8 -*-
"""分层门禁 ``tools/check_layering.py`` 的**接入测试**（缺陷 3 修复）。

本文件防的三件事
----------------
1. **门禁没被任何测试接入**（改动前 `grep -rn check_layering tests/` = 0 处）⇒
   门禁烂掉/被改成恒 PASS 也没人发现。本文件把「跑真实门禁 + 断言真 FAIL/PASS」
   固化为用例。
2. **相对 import 隐形**（缺陷 1）：`utils/a.py` 写 `from ..agent.x import y` 在修复前
   提取器返回空集 ⇒ 真·跨层违规门禁 PASS。这里用 tmp_path 合成树证明它**被报**。
3. **cli/ 不在禁令 / 不在环检测**（缺陷 2）：下层四包 import cli、或层间成环，
   现在必须 FAIL。

判据是"**能失败**"：把 `tools/check_layering.py` 里新增的 cli 检查注释掉，
本文件的 `test_downstream_must_not_import_cli` 会变红（判别力自证，见任务报告）。

合成用例**不碰真实仓库**：全部在 `tmp_path` 造最小包树，通过 `main(root)` 直接跑。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

GATE = os.path.join(REPO, "tools", "check_layering.py")


def _load_gate():
    """按文件路径加载门禁模块（不复用 sys.modules 缓存，保证每次是新实例）。"""
    spec = importlib.util.spec_from_file_location("check_layering_gate_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_tree(root, files):
    """按 {相对路径: 内容} 造一棵最小包树。"""
    for rel, content in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) 真实仓库：门禁必须真跑、真 PASS，且输出含关键锚点
# ---------------------------------------------------------------------------
def test_real_repo_gate_passes():
    r = subprocess.run(
        [sys.executable, "tools/check_layering.py"],
        cwd=REPO, capture_output=True, text=True,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, "真实仓库门禁未通过：\n%s" % out
    # 同时断言两个锚点：防止脚本被改成"恒 PASS 且不打印环检查"还蒙混过关。
    assert "包级环（扣豁免后）" in out, out
    assert "PASS" in out, out


# ---------------------------------------------------------------------------
# 2) 缺陷 1 阳性对照：utils 用**相对 import** 跨到 agent ⇒ 提取器产出 agent 且门禁 FAIL
# ---------------------------------------------------------------------------
_UTILS_REL_AGENT = {
    "utils/__init__.py": "",
    "utils/a.py": "from ..agent.formatter import X\n",
    "agent/__init__.py": "",
    "agent/formatter.py": "",
}


def test_relative_import_resolved_to_absolute_package(tmp_path):
    """提取器必须把 `from ..agent.x` 解析成绝对包名 `agent`（而不是空集）。"""
    _write_tree(tmp_path, _UTILS_REL_AGENT)
    mod = _load_gate()
    roots = mod._imported_roots(str(tmp_path / "utils" / "a.py"), str(tmp_path))
    assert "agent" in roots, "相对 import 未被解析成绝对包（缺陷 1 复发）：%r" % (roots,)


def test_relative_cross_layer_violation_is_reported(tmp_path, capsys):
    """utils/ 用相对 import 跨到 agent/ ⇒ 门禁必须 FAIL（修复前会 PASS）。"""
    _write_tree(tmp_path, _UTILS_REL_AGENT)
    mod = _load_gate()
    rc = mod.main(str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1, "跨层违规未被报出，门禁仍 PASS：\n%s" % out
    assert "utils/a.py" in out, out
    assert "utils 不得 import agent/tools" in out, out


# ---------------------------------------------------------------------------
# 3) 缺陷 2a：下层四包不得 import cli ⇒ 门禁 FAIL
# ---------------------------------------------------------------------------
_AGENT_IMPORTS_CLI = {
    "agent/__init__.py": "",
    "agent/b.py": "from cli.x import y\n",
    "cli/__init__.py": "",
    "cli/x.py": "y = 1\n",
}


def test_downstream_must_not_import_cli(tmp_path, capsys):
    """agent/b.py 里 `from cli.x import y` ⇒ 门禁必须 FAIL（判别力自证靶点）。"""
    _write_tree(tmp_path, _AGENT_IMPORTS_CLI)
    mod = _load_gate()
    rc = mod.main(str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1, "下层 import cli 未被报出：\n%s" % out
    assert "不得 import cli" in out, out
    assert "agent/b.py" in out, out


def test_cli_extractor_sees_cli(tmp_path):
    _write_tree(tmp_path, _AGENT_IMPORTS_CLI)
    mod = _load_gate()
    roots = mod._imported_roots(str(tmp_path / "agent" / "b.py"), str(tmp_path))
    assert "cli" in roots, roots


# ---------------------------------------------------------------------------
# 4) 缺陷 2b：层间（相对 import 形成）的包级环必须被环检测报出
# ---------------------------------------------------------------------------
_LAYER_CYCLE = {
    "utils/__init__.py": "",
    "utils/u.py": "from ..tools.t import x\n",
    "tools/__init__.py": "",
    "tools/t.py": "from ..utils.u import y\n",
}


def test_package_cycle_detected(tmp_path, capsys):
    """utils↔tools 两个包用相对 import 互指 ⇒ 环检测必须报出 utils → tools → utils。"""
    _write_tree(tmp_path, _LAYER_CYCLE)
    mod = _load_gate()
    rc = mod.main(str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1, "包级环未被报出：\n%s" % out
    assert "utils → tools → utils" in out, out


# ---------------------------------------------------------------------------
# 5) 阴性对照：干净的分层树 ⇒ PASS
# ---------------------------------------------------------------------------
_CLEAN = {
    "contracts/__init__.py": "",
    "contracts/types.py": "X = 1\n",
    "utils/__init__.py": "",
    "utils/u.py": "from contracts.types import X\n",
    "tools/__init__.py": "",
    "tools/t.py": "from utils.u import X\n",
    "agent/__init__.py": "",
    "agent/a.py": "from utils.u import X\n",
    "cli/__init__.py": "",
    "cli/c.py": "from agent.a import X\n",
}


def test_clean_tree_passes(tmp_path, capsys):
    _write_tree(tmp_path, _CLEAN)
    mod = _load_gate()
    rc = mod.main(str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0, "干净树被判 FAIL（误伤）：\n%s" % out
    assert "结果：PASS" in out, out


# ---------------------------------------------------------------------------
# 6) 解析器边界：相对层级越过仓库根 ⇒ 退回 own（保守，不造幻影边）
# ---------------------------------------------------------------------------
def test_relative_resolver_overflow_returns_none(tmp_path):
    _write_tree(tmp_path, {"utils/__init__.py": "", "utils/a.py": "from ...x import y\n"})
    mod = _load_gate()
    assert mod._resolve_relative(str(tmp_path / "utils" / "a.py"), str(tmp_path), 3, "x") is None
    # 提取器整体退回 own ⇒ 不算跨层
    assert mod._imported_roots(str(tmp_path / "utils" / "a.py"), str(tmp_path)) == set()
