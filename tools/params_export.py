# -*- coding: utf-8 -*-
"""L0 参数层 —— 把「可编辑参数」导出成单份可 diff 的 params.json（build / check / diff）。

为什么需要它
============
三体架构（`docs/三体架构_v1.md`）把「参数层」定为 L0 地基：
自迭代智能体（L3）要提案、判定层（L4）要评审、账本（L5）要回灌，
前提都是**候选能用一个文件表示**。现在参数散在四处：

    ① `AgentConfig` 的 232 个字段（`user_agent__config*.py` 两个 dataclass）
    ② `SWITCHES` 120 个开关（`contracts/switch_registry.py`，默认值须与 ① 一致）
    ③ 65 个提示词文本常量（`prompts/*.py`）
    ④ `DEFAULT_AGENT_OVERRIDES`（`run_eval__engine.py`，评测基线，**与 ① 不同**）

⇒ 同一个参数有 2~3 处权威值，「改了不生效」「基线≠平台」都从这里长出来。
本工具把它们合成一份 `params.json`，并给每个单元打 **A / B / C 档**：

    A  机器可自动改：**标量**值 + 有真实读取点 + 在覆盖白名单内（改得动、看得见）
    B  必须人改：提示词文本 / 记忆条目 / 非标量结构值 / 死配置 / 未接线参数
    C  结构性，永不进候选池：阶段顺序、工具实现、467 处硬编码上下文切片

判定不是手填的，是**扫出来的**（`--why` 可看单个单元的判定依据）。

三条硬约束（都来自踩过的坑）
============================
1. **纯 AST，不 import 目标模块**：`tools/` 不得依赖 `agent/`（分层门禁
   `tools/check_layering.py`），且 import `AgentConfig` 会带起整条 agent 依赖链。
2. **读取点用 AST 判，不用文本匹配**：字符串里提到某个名字（注释、日志）不算读取。
   只有这三种算：`x.<name>` 属性访问、`"<name>"` 字面量（`get_bool("...")`、
   `_SPEC` 表）、`<name>=` 关键字实参。
3. **`DEFAULT_AGENT_OVERRIDES` 必须并入取值**：`run_eval` 的生效值 =
   dataclass 默认 ⊕ 该表。只取 dataclass 默认会让 params.json 与评测口径不一致
   （例：`verifier_voting_times` 声明 1、评测实跑 2）。

用法
====
    python tools/params_export.py build                  # 写 params.json
    python tools/params_export.py build --out /tmp/p.json
    python tools/params_export.py check                  # 结构 + 键位校验（不比对取值）
    python tools/params_export.py check --strict         # 连取值一起比对（基线刷新后应为 0 漂移）
    python tools/params_export.py show --tier A          # 列出 A 档（机器可改的候选空间）
    python tools/params_export.py show --why five_gate_falsify
    python tools/params_export.py diff params.json /tmp/cand.json   # 只报 A 档取值差异

⚠ 本文件不含任何题号 / 答案 / 数据集内容（R6）。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SCHEMA = "params/1"
DEFAULT_OUT = os.path.join(_ROOT, "params.json")

# 只有这些类型算「机器可改的标量」；其余（list/dict/tuple/Optional[list]）都是结构值
SCALAR_TYPES = {"bool", "int", "float", "str"}

# 参数层自身的开关（路径等）：是注册开关，但**不作为候选**（否则一条候选可以换掉基线文件）
_META_KEYS = {"params_json_path"}

# 运行时读取面（tests/ 刻意不算：只在测试里被读的字段 = 运行时死配置）
_CODE_ROOTS = ("agent", "utils", "tools", "cli", "contracts", "prompts", "deploy")
_SKIP_DIR_PARTS = (
    "__pycache__", ".workbuddy", "backups", "vendor", "lean", "tests",
    "data", "results", "output", "papers", "formal-imo", "imo_steps",
    "lean下载版", "lean-toolchain", "题库", "题库备份", "MagicMock", "ripgrep",
)

_TIER_DOC = {
    "A": "机器可自动改：标量 + 有真实读取点 + 在覆盖白名单内",
    "B": "必须人改：提示词文本/记忆条目/非标量值/死配置/未接线参数",
    "C": "结构性，永不进候选池：阶段顺序/工具实现/硬编码上下文切片",
}


# ---------------------------------------------------------------- 基础设施
def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _rel(path: str) -> str:
    return os.path.relpath(path, _ROOT).replace("\\", "/")


def _code_files() -> list:
    """运行时读取面的 .py 清单（排除测试/数据/第三方/文档树）。"""
    out = []
    for root in _CODE_ROOTS:
        base = os.path.join(_ROOT, root)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs
                       if d not in _SKIP_DIR_PARTS and not d.startswith("lean-")]
            for f in files:
                if f.endswith(".py"):
                    out.append(os.path.join(dirpath, f))
    for f in sorted(os.listdir(_ROOT)):
        if f.endswith(".py"):
            out.append(os.path.join(_ROOT, f))
    return out


def _assign_targets(node):
    """Assign / AnnAssign → 目标名列表；其它语句 → 空（避免 AttributeError 满天飞）。"""
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _decl_type(annotation: str) -> str:
    """把注解归一成裸类型名：Optional[int] → int；List[str] → list。"""
    a = annotation.strip()
    if a.startswith("Optional[") and a.endswith("]"):
        a = a[len("Optional["):-1].strip()
    return a.split("[")[0].strip()


def _is_scalar(annotation: str) -> bool:
    return _decl_type(annotation) in SCALAR_TYPES


def _literal(node):
    """能 literal_eval 就取真值，否则返回 (源码串)。"""
    try:
        return ast.literal_eval(node), True
    except (ValueError, SyntaxError, TypeError):
        try:
            return ast.unparse(node), False
        except Exception:  # noqa: BLE001  pragma: no cover
            return "", False


def _factory_default(node):
    """`field(default_factory=lambda: [...])` → 尽量取出工厂产出的字面量。"""
    if not isinstance(node, ast.Call):
        return None
    for kw in node.keywords:
        if kw.arg == "default_factory":
            body = kw.value
            if isinstance(body, ast.Lambda):
                body = body.body
            val, ok = _literal(body)
            return val if ok else None
    return None


# ---------------------------------------------------------------- 四处权威值
def scan_config() -> dict:
    """AgentConfig 全部字段：name → {type, default, default_src, source, cls}。

    ★ 扫描顺序 = **派生类先、基类后**，同名以先出现者为准 —— 这正是 dataclass
      的继承语义（子类重声明同名字段时，默认值取子类那份）。
      反过来（基类先）会在"子类重声明"时静默取到旧默认值。
    """
    out = {}
    for fname in ("user_agent__config.py", "user_agent__config_base.py"):
        src = _read(os.path.join(_ROOT, fname))
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign)
                        and isinstance(stmt.target, ast.Name)):
                    continue
                name = stmt.target.id
                if name in out:
                    continue
                typ = ast.unparse(stmt.annotation)
                if stmt.value is None:
                    val, ok = None, True
                else:
                    val, ok = _literal(stmt.value)
                    if not ok:
                        fv = _factory_default(stmt.value)
                        if fv is not None:
                            val, ok = fv, True
                out[name] = {
                    "type": typ,
                    "scalar": _is_scalar(typ),
                    "default": val if ok else None,
                    "default_src": ast.unparse(stmt.value) if stmt.value is not None else "",
                    "source": "%s::%s.%s" % (fname, node.name, name),
                    "cls": node.name,
                }
    return out


def scan_whitelist() -> set:
    """③ 覆盖白名单 `user_agent.py::_CONFIG_OVERRIDE_KEYS`（AST，不用正则）。"""
    src = _read(os.path.join(_ROOT, "user_agent.py"))
    if not src:
        return set()
    keys = set()
    for node in ast.parse(src).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "_CONFIG_OVERRIDE_KEYS"
                   for t in targets):
            continue
        if isinstance(node.value, (ast.Tuple, ast.List)):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    keys.add(elt.value)
    return keys


def scan_switches() -> dict:
    """① 开关注册表：name → {env, kind, default, source}。"""
    src = _read(os.path.join(_ROOT, "contracts", "switch_registry.py"))
    if not src:
        return {}
    out = {}
    for node in ast.parse(src).body:
        if not any(isinstance(t, ast.Name) and t.id == "SWITCHES"
                   for t in _assign_targets(node)):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            try:
                env, kind, default, doc = ast.literal_eval(v)
            except (ValueError, SyntaxError, TypeError):
                continue
            out[k.value] = {"env": env, "kind": kind, "default": default,
                            "doc": str(doc)[:160],
                            "source": "contracts/switch_registry.py::SWITCHES[%s]" % k.value}
    return out


def scan_eval_overrides() -> dict:
    """④ 评测基线 `run_eval__engine.py::DEFAULT_AGENT_OVERRIDES`。"""
    src = _read(os.path.join(_ROOT, "run_eval__engine.py"))
    if not src:
        return {}
    for node in ast.parse(src).body:
        if not any(isinstance(t, ast.Name) and t.id == "DEFAULT_AGENT_OVERRIDES"
                   for t in _assign_targets(node)):
            continue
        if isinstance(node.value, ast.Dict):
            try:
                return dict(ast.literal_eval(node.value))
            except (ValueError, SyntaxError, TypeError):
                return {}
    return {}


def build_usage_index(names: set) -> dict:
    """AST 判读取点：name → ["agent/base.py", ...]（属性访问 / 字符串字面量 / 关键字实参）。

    ★ 两处「登记≠读取」必须排除，否则死配置会被自己的登记处掩盖成活配置：
      · `user_agent.py::_CONFIG_OVERRIDE_KEYS`（覆盖白名单：列了名字不等于有人读）
      · `contracts/switch_registry.py::SWITCHES`（开关注册表：同理）
    """
    idx = {n: [] for n in names}
    for path in _code_files():
        src = _read(path)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        skip_ids = set()
        for node in ast.walk(tree):
            if any(isinstance(t, ast.Name) and t.id in ("_CONFIG_OVERRIDE_KEYS", "SWITCHES")
                   for t in _assign_targets(node)):
                skip_ids.update(id(x) for x in ast.walk(node))
        hit = set()
        for node in ast.walk(tree):
            if id(node) in skip_ids:
                continue
            if isinstance(node, ast.Attribute):
                if node.attr in names:
                    hit.add(node.attr)
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, str) and node.value in names:
                    hit.add(node.value)
            elif isinstance(node, ast.keyword):
                if node.arg in names:
                    hit.add(node.arg)
        rel = _rel(path)
        for n in hit:
            idx[n].append(rel)
    for n in idx:
        idx[n].sort()
    return idx


# ---------------------------------------------------------------- 判定与装配
def classify_flow(name: str, meta: dict, whitelist: set, refs: list) -> tuple:
    """flow 单元 → (tier, status, reason)。判据顺序即「改得动」的必要条件链。"""
    if name in _META_KEYS:
        return "B", "meta", "参数层自身的开关（路径等）：不作为候选，由人指定"
    if not meta["scalar"]:
        return "B", "struct", "非标量（%s）：候选无法用一行 JSON 表达，只能人改" % meta["type"]
    if not refs:
        return "B", "dead", "全仓 0 读取点（死配置）：改了不生效，须先删或先接线"
    if name not in whitelist:
        return "B", "unwired", "有读取点但不在覆盖白名单：kwargs/CLI 会被静默丢弃，须先接线"
    return "A", "ok", "标量 + 有读取点 + 在白名单：改它只动一个值"


def _module_const_text(path: str, name: str) -> str:
    """取模块级常量的**字面量本体**（AST，不执行模块）——B 档用它的指纹判"文本变没变"。

    普通字符串/隐式拼接走 literal_eval；f-string 等非字面量退化成 ast.unparse
    （归一化后的源码形态，同样"文本一改指纹就变"）。
    """
    src = _read(path)
    if not src:
        return ""
    try:
        tree = ast.parse(src)
    except SyntaxError:  # pragma: no cover
        return ""
    for node in tree.body:
        if not any(isinstance(t, ast.Name) and t.id == name
                   for t in _assign_targets(node)):
            continue
        try:
            lit = ast.literal_eval(node.value)
            return lit if isinstance(lit, str) else ""
        except (ValueError, SyntaxError, TypeError):
            try:
                return ast.unparse(node.value)
            except Exception:  # noqa: BLE001  pragma: no cover
                return ""
    return ""


def build() -> dict:
    """装配 params.json 文档（确定性输出：同一份代码 → 同一份字节）。"""
    config = scan_config()
    whitelist = scan_whitelist()
    switches = scan_switches()
    eval_ov = scan_eval_overrides()
    usage = build_usage_index(set(config) | {switches[s]["env"] for s in switches if "env" in switches[s]})

    a_entries, b_entries, c_entries = {}, {}, {}
    stats = {"dead": 0, "unwired": 0, "struct": 0}

    for name in sorted(config):
        meta = config[name]
        refs = [p for p in usage.get(name, []) if not p.endswith(meta["source"].split("::")[0])]
        tier, status, reason = classify_flow(name, meta, whitelist, refs)
        entry = {
            "tier": tier,
            "status": status,
            "type": meta["type"],
            "source": meta["source"],
            "reason": reason,
        }
        if name in switches:
            entry["env"] = switches[name]["env"]
            entry["switch_kind"] = switches[name]["kind"]
            entry["registry_default"] = switches[name]["default"]
        if tier == "A":
            declared = meta["default"]
            eff = eval_ov.get(name, declared)
            entry["value"] = eff
            entry["declared"] = declared
            entry["eval_override"] = eval_ov.get(name, None)
            entry["refs"] = refs
            a_entries[name] = entry
            continue
        if name in eval_ov:
            entry["eval_override"] = eval_ov[name]
        entry["refs"] = refs
        entry["default_src"] = meta["default_src"]
        b_entries["flow.%s" % name] = entry
        if status in stats:
            stats[status] += 1

    # ① 提示词 / ④ 记忆 / ③ 工具：从 eu_inventory 复用扫描结果（同一份事实来源）
    try:
        from tools.eu_inventory import (scan_context, scan_memory, scan_prompts,
                                        scan_tools)
    except ImportError:  # pragma: no cover  直接跑脚本时的回落
        sys.path.insert(0, os.path.join(_ROOT, "tools"))
        from eu_inventory import (scan_context, scan_memory, scan_prompts,  # type: ignore
                                  scan_tools)

    import hashlib

    def _sha(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

    for it in scan_prompts():
        const = it["source"].split("::")[-1]
        text = _module_const_text(os.path.join(_ROOT, it["source"].split("::")[0]), const)
        b_entries[it["id"]] = {
            "tier": "B",
            "status": "ok",
            "type": it["form"],
            "source": it["source"],
            "reason": "提示词文本：语义改动必须人审（机器只碰 A 档）",
            "chars": len(text) or it["extra"].get("chars", 0),
            "placeholders": it["extra"].get("placeholders", []),
            "sha1": _sha(text),
            "refs": [p for p in it["extra"].get("consumers", [])
                     if not p.startswith("prompts/")],
        }

    for it in scan_memory():
        b_entries[it["id"]] = {
            "tier": "B",
            "status": "ok",
            "type": "entry",
            "source": it["source"],
            "reason": "记忆条目文本：改一条即改行为，须人审",
            "name": it["extra"].get("name", ""),
            "qtypes": it["extra"].get("qtypes", ""),
            "refs": [p for p in it["extra"].get("consumers", [])
                     if not p.startswith("prompts/")],
        }

    for it in scan_tools():
        c_entries[it["id"]] = {
            "tier": "C",
            "status": "structural",
            "type": "function",
            "source": it["source"],
            "reason": "工具实现与签名：增删工具会改控制流拓扑，永不进候选池（描述文本由人改）",
            "exported": it["extra"].get("exported", False),
        }

    # ⑤ 上下文：467 处硬编码切片属**代码**，按 L0「只能存值」的口径不内联，
    #    只给计数与查询入口（明细见 tools/eu_inventory.py --dim context）。
    n_ctx = sum(1 for _ in scan_context())

    counts = {
        "A": len(a_entries),
        "B": len(b_entries),
        "C": len(c_entries),
        "dead": stats["dead"],
        "unwired": stats["unwired"],
        "struct": stats["struct"],
        "context_excluded": n_ctx,
        "total_in_file": len(a_entries) + len(b_entries) + len(c_entries),
    }
    return {
        "schema": SCHEMA,
        "about": "L0 参数层：A=机器可改的标量值（候选空间）；B=需人改；C=结构性。"
                 "候选 = 本文件 a 段的 diff。生成器 tools/params_export.py，勿手改。",
        "tiers": _TIER_DOC,
        "counts": counts,
        "sources": {
            "config": "user_agent__config_base.py + user_agent__config.py",
            "switches": "contracts/switch_registry.py::SWITCHES",
            "whitelist": "user_agent.py::_CONFIG_OVERRIDE_KEYS",
            "eval_baseline": "run_eval__engine.py::DEFAULT_AGENT_OVERRIDES",
            "prompt_memory_tool": "tools/eu_inventory.py",
        },
        "a": a_entries,
        "b": b_entries,
        "c": c_entries,
    }


# ---------------------------------------------------------------- 校验
def check(doc: dict, strict: bool = False) -> list:
    """结构 + 键位校验；strict 时连取值一起比对。返回问题清单（空 = 通过）。"""
    problems = []
    if doc.get("schema") != SCHEMA:
        problems.append("schema 不是 %s：%r" % (SCHEMA, doc.get("schema")))
    a = doc.get("a") or {}
    b = doc.get("b") or {}
    c = doc.get("c") or {}
    if not a:
        problems.append("a 段为空：A 档（机器可改空间）一个都没有，判定逻辑可疑")

    config = scan_config()
    whitelist = scan_whitelist()
    switches = scan_switches()
    eval_ov = scan_eval_overrides()
    usage = build_usage_index(set(a))

    for name, e in sorted(a.items()):
        if e.get("tier") != "A":
            problems.append("%s: a 段条目的 tier 不是 A（%r）" % (name, e.get("tier")))
        if name not in config:
            problems.append("%s: 不在 AgentConfig 声明里（模型可以发明参数 ⇒ 必须拒）" % name)
            continue
        if not config[name]["scalar"]:
            problems.append("%s: 类型 %s 不是标量，不能进 A 档" % (name, config[name]["type"]))
        if name not in whitelist:
            problems.append("%s: 不在覆盖白名单 ⇒ kwargs 会被静默丢弃" % name)
        if not [p for p in usage.get(name, [])
                if not p.endswith(config[name]["source"].split("::")[0])]:
            problems.append("%s: 0 读取点（死配置不能当候选）" % name)
        if name in switches:
            if switches[name]["default"] != config[name]["default"]:
                problems.append("%s: 注册表默认 %r ≠ 配置默认 %r（四件套漂移）"
                                % (name, switches[name]["default"], config[name]["default"]))
        if strict:
            want = eval_ov.get(name, config[name]["default"])
            got = e.get("value")
            if want != got:
                problems.append("%s: params.json 值 %r ≠ 当前生效值 %r（代码改了没重导出）"
                                % (name, got, want))

    counts = doc.get("counts") or {}
    for k, v in (("A", len(a)), ("B", len(b)), ("C", len(c))):
        if counts.get(k) != v:
            problems.append("counts.%s=%r 与实际条目数 %d 不一致" % (k, counts.get(k), v))

    for key in list(b) + list(c):
        e = b.get(key) or c.get(key) or {}
        if e.get("tier") not in ("B", "C"):
            problems.append("%s: b/c 段条目的 tier 非法（%r）" % (key, e.get("tier")))
    return problems


def diff_docs(old: dict, new: dict) -> list:
    """只比 a 段取值：返回 [(key, old, new)]。候选评审看的就是这个。"""
    ao, an = old.get("a") or {}, new.get("a") or {}
    out = []
    for k in sorted(set(ao) | set(an)):
        vo = (ao.get(k) or {}).get("value")
        vn = (an.get(k) or {}).get("value")
        if k not in ao or k not in an or vo != vn:
            out.append((k, vo, vn))
    return out


# ---------------------------------------------------------------- CLI
def _dump(doc: dict, path: str) -> None:
    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L0 参数层导出/校验（A/B/C 分档）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_b = sub.add_parser("build", help="重新生成 params.json")
    p_b.add_argument("--out", default=DEFAULT_OUT)

    p_c = sub.add_parser("check", help="校验结构/键位（--strict 连取值）")
    p_c.add_argument("--path", default=DEFAULT_OUT)
    p_c.add_argument("--strict", action="store_true")

    p_s = sub.add_parser("show", help="看 A 档清单 / 单个单元的判定依据")
    p_s.add_argument("--tier", default="A", choices=["A", "B", "C"])
    p_s.add_argument("--why", default="", help="某个 key，打印判定依据")
    p_s.add_argument("--path", default=DEFAULT_OUT)

    p_d = sub.add_parser("diff", help="比较两份 params.json 的 A 段取值")
    p_d.add_argument("old")
    p_d.add_argument("new")

    args = ap.parse_args(argv)

    if args.cmd == "build":
        doc = build()
        _dump(doc, args.out)
        c = doc["counts"]
        print("已写出 %s" % args.out)
        print("  A 机器可改 %d ｜ B 需人改 %d ｜ C 结构性 %d ｜ 文件内合计 %d"
              % (c["A"], c["B"], c["C"], c["total_in_file"]))
        print("  （另有 %d 处上下文硬编码切片属代码，未内联；见 tools/eu_inventory.py --dim context）"
              % c["context_excluded"])
        print("  其中 flow 维：死配置 %d ｜ 未接线 %d ｜ 非标量 %d"
              % (c["dead"], c["unwired"], c["struct"]))
        return 0

    if args.cmd == "check":
        doc = _load(args.path)
        probs = check(doc, strict=args.strict)
        if probs:
            print("❌ %d 个问题：" % len(probs))
            for p in probs:
                print("   -", p)
            return 1
        print("✅ 通过（%s%s）" % (args.path, "，含取值比对" if args.strict else ""))
        return 0

    if args.cmd == "show":
        doc = _load(args.path)
        seg = doc.get(args.tier.lower()) or {}
        if args.why:
            key = args.why
            hit = {k: v for k, v in seg.items() if k == key or k.startswith("flow." + key)}
            if not hit:
                for t in ("a", "b", "c"):
                    for k, v in (doc.get(t) or {}).items():
                        if k == key or k.endswith("." + key):
                            hit = {k: v}
            if not hit:
                print("未找到 %r" % key)
                return 1
            for k, v in hit.items():
                print(k)
                print(json.dumps(v, ensure_ascii=False, indent=1))
            return 0
        print("%s 档 %d 条：%s" % (args.tier, len(seg), _TIER_DOC[args.tier]))
        for k in sorted(seg):
            v = seg[k]
            extra = ("= %r" % v.get("value")) if args.tier == "A" else ("[%s]" % v.get("status"))
            print("  %-46s %s" % (k, extra))
        return 0

    if args.cmd == "diff":
        rows = diff_docs(_load(args.old), _load(args.new))
        if not rows:
            print("A 段无差异（两份文件的机器可改空间完全一致）")
            return 0
        print("A 段差异 %d 处：" % len(rows))
        for k, vo, vn in rows:
            print("  %-46s %r → %r" % (k, vo, vn))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
