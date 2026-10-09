# -*- coding: utf-8 -*-
"""委托跳板「两份签名一致性」守卫（全仓自生成）。

本清单从哪来
------------
2026-10 的仓库大拆分把大文件里的代码段搬到 ``xxx__yyy.py`` 子模块，并在原位留
**一行同名委托**。本文件在**运行时**用 ``ast`` 重新扫出全仓这套委托，不硬编码
任何易过期的清单 —— 将来新增委托会被自动纳入断言。

两种委托形态（均要求「跳板名 == 目标函数名」）：

  ① def 式   ``def foo(self, ...): return _mod.foo(self, ...)``
              （集中在 ``agent/orchestrator.py`` 与 ``agent/verifier.py``）
  ② 赋值式   ``foo = _mod.foo`` / ``foo = staticmethod(_mod.foo)`` /
              ``foo = classmethod(_mod.foo)``
              （集中在 ``agent/sub_goal_solver.py``、``agent/deterministic.py``、
                ``tools/lean_local/lean_gate.py``）

为什么两份签名必须一致
----------------------
def 式委托**天然有两份形参表**：跳板 ``def foo(self, ctx, ans='')`` 与实现
``def foo(owner, ctx, ans='')``。二者靠**位置**逐个传参，一旦有人在实现侧把某个
形参改名（或在中间插入新形参、去掉默认值），跳板侧不改就会在**调用期**
``TypeError`` 或**参数错位**（静默把 A 当 B），而普通导入/语法检查都拦不住。
本文件把「跳板签名（归一化首参后）== 实现签名」固化为断言。

本文件防的是什么错
------------------
・实现在子模块里改了形参名 / 加删形参 / 改默认值 / 加删 ``*args``、``**kwargs``，
  跳板没同步 ⇒ 断言变红（附跳板 文件:行、目标 文件:行、两边签名文本对比）。
・扫描逻辑失效、返回空集 ⇒ 由 ``COUNT_FLOOR`` + ``WHITELIST`` 锚点断言兜住，
  不让"扫不到 ⇒ 全绿"的静默假阳性发生。

判据是"**能失败**"：把某个实现的形参改名后本文件会变红（已实测，见任务报告）。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 扫描范围：生产代码。
# 排除：任务点名的 tests/、tools/lean_local/tests/、_pytest_tmp_*、.workbuddy/、
# vendor/、docs/、与lean相关的插件/、备份目录，外加**仓内别的项目/参考材料**
# （papers、formal-imo、imo_steps、superhuman、lean-lsp-mcp、论文实践 等）与
# 纯数据/产物目录。scripts/、deploy/ 属本仓自有代码，**纳入扫描**。
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDE_DIRS = {
    # "tests" 按目录名匹配，同时覆盖根 tests/ 与 tools/lean_local/tests/。
    "tests", ".workbuddy", "vendor", "docs", "与lean相关的插件", ".git",
    "node_modules",
    "__pycache__", ".pytest_cache", "题库", "题库备份", "papers", "formal-imo",
    "imo_bench_eval", "imo_steps", "lean-lsp-mcp", "superhuman", "测试结果",
    "论文实践", "results", "output", "sample_data", "MagicMock", "proj",
    ".codebuddy", ".cw_skill", ".pytmp_probe", ".pytmp_probe_step2", "lean下载版",
    "ripgrep-14.1.1-x86_64-pc-windows-msvc",
    "ripgrep-14.1.1-x86_64-unknown-linux-musl",
}

# 临时脚本前缀（根目录遗留的分析脚本，非生产代码）。
_EXCLUDE_FILE_PREFIXES = ("pytmp_",)

# 断言不用硬编码清单；只锁一个保守下限（实测 144 条，留足余量）+ 几个"确定存在"
# 的样本，防止扫描失效时静默全绿。
COUNT_FLOOR = 120

# 白名单：(相对路径, 跳板名)。覆盖两种形态与 5 个主要拆分文件。
WHITELIST = {
    ("agent/orchestrator.py", "_has_usable_candidate"),      # def 式
    ("agent/orchestrator.py", "_deep_revise_loop"),          # def 式（带默认值）
    ("agent/orchestrator.py", "_looks_like_answer"),         # def 式 @staticmethod
    ("agent/sub_goal_solver.py", "_merge_results"),          # 赋值式（普通）
    ("agent/sub_goal_solver.py", "_is_value_choice"),        # 赋值式 staticmethod
    ("agent/sub_goal_solver.py", "_parse_step_contract"),    # 赋值式 classmethod
    ("agent/verifier.py", "_vote"),                          # def 式（self↔owner）
    ("agent/deterministic.py", "_numerically_zero"),         # 赋值式 staticmethod
    ("tools/lean_local/lean_gate.py", "_cache_get"),         # 赋值式 staticmethod
}

# 2026-10-09 盘点结论：仓库当前**没有**签名不一致的委托。留空集合是为了把
# "将来新增的不一致"直接变红；若某项确属历史遗留、需显式豁免，在此登记并注明原因。
# 形如：{("agent/xxx.py", "foo", "target.mod")}
KNOWN_SIGNATURE_MISMATCH: set[tuple[str, str, str]] = set()


# ---------------------------------------------------------------------------
# AST 扫描器
# ---------------------------------------------------------------------------
def _list_prod_files() -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(_ROOT):
        dirs[:] = [
            d for d in dirs
            if not (d in _EXCLUDE_DIRS or d.startswith("_pytest_tmp")
                    or d == "__pycache__")
        ]
        for name in names:
            if not name.endswith(".py"):
                continue
            if name.startswith(_EXCLUDE_FILE_PREFIXES):
                continue
            files.append(Path(root) / name)
    return files


def _module_name(path: Path) -> str:
    rel = path.relative_to(_ROOT).as_posix()
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _package_of(path: Path) -> str:
    rel = path.relative_to(_ROOT).as_posix()
    if rel.endswith("/__init__.py"):
        return rel[: -len("/__init__.py")].replace("/", ".")
    return str(Path(rel).parent).replace("\\", "/").replace("/", ".").strip(".")


def _file_for_module(mod: str) -> Path | None:
    rel = mod.replace(".", "/")
    cand = _ROOT / (rel + ".py")
    if cand.exists():
        return cand
    cand = _ROOT / rel / "__init__.py"
    if cand.exists():
        return cand
    return None


def _collect_module_aliases(tree: ast.AST, path: Path) -> dict[str, str]:
    """{局部别名: 绝对模块名}。仅收「所指为仓库内文件」的模块引用。"""
    aliases: dict[str, str] = {}
    pkg = _package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".") if pkg else []
                up = node.level - 1
                base_parts = parts[: len(parts) - up] if up else parts
                mod = ".".join(base_parts + ([base] if base else []))
            else:
                mod = base
            for a in node.names:
                if a.name == "*":
                    continue
                if node.module is None and a.asname:
                    # from . import xxx as alias  → xxx 是子模块
                    aliases[a.asname] = (mod + "." + a.name) if mod else a.name
                elif node.module is not None:
                    guess = (mod + "." + a.name) if mod else a.name
                    # from pkg import name —— 只有当 name 能解析成仓库内文件时才算模块
                    if _file_for_module(guess):
                        aliases[a.asname or a.name] = guess
    return aliases


def _is_module_alias(name: ast.AST, aliases: dict[str, str]) -> bool:
    return isinstance(name, ast.Name) and name.id in aliases


def _scan_file(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    aliases = _collect_module_aliases(tree, path)
    rel = path.relative_to(_ROOT).as_posix()
    records: list[dict] = []

    def add(jump: str, lineno: int, kind: str, deco: str | None,
            alias: ast.Name, attr: str, owner: str | None) -> None:
        target_mod = aliases[alias.id]
        if _file_for_module(target_mod) is None:
            return  # 目标是仓外（stdlib/第三方）——非本守卫范畴
        records.append({
            "file": rel,
            "lineno": lineno,
            "kind": kind,
            "deco": deco,                 # staticmethod / classmethod / None
            "jump": jump,
            "owner_class": owner,
            "owner_module": _module_name(path),
            "target_module": target_mod,
            "target_name": attr,
        })

    def scan_body(body: list[ast.stmt], owner: str | None) -> None:
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # ① def 式：函数体只有一条 `return _mod.same_name(...)`
                if len(st.body) == 1 and isinstance(st.body[0], ast.Return):
                    call = st.body[0].value
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == st.name
                            and _is_module_alias(call.func.value, aliases)):
                        deco = next(
                            (d.id for d in st.decorator_list
                             if isinstance(d, ast.Name)
                             and d.id in ("staticmethod", "classmethod")),
                            None)
                        add(st.name, st.lineno, "def", deco,
                            call.func.value, call.func.attr, owner)
            elif (isinstance(st, ast.Assign) and len(st.targets) == 1
                    and isinstance(st.targets[0], ast.Name)):
                nm = st.targets[0].id
                val = st.value
                deco = None
                attr_node: ast.Attribute | None = None
                if (isinstance(val, ast.Attribute)
                        and isinstance(val.value, ast.Name)):
                    attr_node = val
                elif (isinstance(val, ast.Call)
                        and isinstance(val.func, ast.Name)
                        and val.func.id in ("staticmethod", "classmethod")
                        and len(val.args) == 1
                        and isinstance(val.args[0], ast.Attribute)
                        and isinstance(val.args[0].value, ast.Name)):
                    deco = val.func.id
                    attr_node = val.args[0]
                if attr_node is not None and attr_node.attr == nm \
                        and _is_module_alias(attr_node.value, aliases):
                    add(nm, st.lineno, "assign", deco,
                        attr_node.value, attr_node.attr, owner)

    scan_body(tree.body, None)                      # 模块级
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scan_body(node.body, node.name)         # 类体
    return records


def _scan_all() -> list[dict]:
    records: list[dict] = []
    for path in _list_prod_files():
        records.extend(_scan_file(path))
    return records


_ALL = _scan_all()


def _record_id(rec: dict) -> str:
    return f"{rec['file']}:{rec['lineno']}:{rec['jump']}"


# ---------------------------------------------------------------------------
# 运行时解析两侧对象 + 签名比较
# ---------------------------------------------------------------------------
def _unwrap_static(obj):
    if isinstance(obj, (staticmethod, classmethod)):
        return obj.__func__, isinstance(obj, classmethod)
    return obj, False


def _jump_signature(rec: dict):
    """返回 (函数对象, 是否有接收者 self/cls)。"""
    mod = importlib.import_module(rec["owner_module"])
    if rec["owner_class"] is None:
        raw = getattr(mod, rec["jump"])
        func, _ = _unwrap_static(raw)
        return func, False
    cls = getattr(mod, rec["owner_class"])
    raw = inspect.getattr_static(cls, rec["jump"])   # 不触发描述符绑定
    func, is_class = _unwrap_static(raw)
    if isinstance(raw, staticmethod):
        return func, False                            # 静态：首参是实参，不是接收者
    if is_class:
        return func, True                             # 类方法：cls 为接收者
    if rec["kind"] == "assign":
        return func, True                             # 普通别名 → 实例方法（self）
    first = next(iter(inspect.signature(func).parameters), None)
    return func, first in ("self", "cls")


def _target_function(rec: dict):
    mod = importlib.import_module(rec["target_module"])
    return getattr(mod, rec["target_name"])


def _param_specs(func, receiver: bool):
    """可比参数表：[(kind, name, default_repr)]，首参为接收者时归一化其名。"""
    sig = inspect.signature(func)
    specs = []
    for i, p in enumerate(sig.parameters.values()):
        name = p.name
        if i == 0 and receiver and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD):
            name = "<recv>"
        dflt = ("<empty>" if p.default is inspect.Parameter.empty
                else repr(p.default))
        specs.append((p.kind.name, name, dflt))
    return tuple(specs)


def _sig_text(func, receiver: bool) -> str:
    return ", ".join(
        f"{name}{'' if dflt == '<empty>' else '=' + dflt}"
        for _kind, name, dflt in _param_specs(func, receiver))


# ---------------------------------------------------------------------------
# 锚点断言：防扫描真空
# ---------------------------------------------------------------------------
def test_delegation_count_floor():
    assert len(_ALL) >= COUNT_FLOOR, (
        f"扫描到的委托条数 {len(_ALL)} < 下限 {COUNT_FLOOR} —— "
        "扫描逻辑可能失效/被误改，本守卫正在静默失效，必须排查"
    )


def test_delegation_whitelist_present():
    found = {(r["file"], r["jump"]) for r in _ALL}
    missing = WHITELIST - found
    assert not missing, (
        f"白名单里确定存在的委托在扫描结果中缺失：{sorted(missing)} —— "
        "要么扫描逻辑失效（返回空/漏扫），要么这些委托被改动"
    )


# ---------------------------------------------------------------------------
# 核心：逐条断言「跳板签名 == 实现签名」
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rec", _ALL, ids=[_record_id(r) for r in _ALL])
def test_delegation_signature_matches(rec):
    jump_key = (rec["file"], rec["jump"], rec["target_module"])
    try:
        jump_fn, received = _jump_signature(rec)
        tgt_fn = _target_function(rec)
    except Exception as exc:  # noqa: BLE001
        # 解析不到 = 委托目标已改名/删除，本身就是要拦的错；KNOWN 集合可豁免。
        if jump_key in KNOWN_SIGNATURE_MISMATCH:
            pytest.skip(f"已知不一致（豁免）：{exc}")
        pytest.fail(
            f"委托两侧无法解析：{rec['file']}:{rec['lineno']} {rec['jump']} → "
            f"{rec['target_module']}.{rec['target_name']}（{type(exc).__name__}: {exc}）"
        )

    # 两侧都按「跳板是否带接收者」归一化 —— 静态/普通函数首参是实参，不归一化。
    jump_specs = _param_specs(jump_fn, received)
    target_specs = _param_specs(tgt_fn, received)

    if jump_specs != target_specs:
        detail = (
            f"\n  跳板 : {rec['file']}:{rec['lineno']} "
            f"{rec['jump']}({_sig_text(jump_fn, received)})"
            f"\n  实现 : {rec['target_module']}.{rec['target_name']}"
            f"({_sig_text(tgt_fn, received)})"
            f"\n  形态 : {rec['kind']}"
            + (f" @{rec['deco']}" if rec["deco"] else "")
            + (f" (owner={rec['owner_class']})" if rec["owner_class"] else "")
        )
        if jump_key in KNOWN_SIGNATURE_MISMATCH:
            pytest.skip(f"已知签名不一致（豁免）{detail}")
        pytest.fail(
            "委托跳板与实现签名不一致（两份签名必须逐参一致，首参名可不同）："
            + detail
        )
