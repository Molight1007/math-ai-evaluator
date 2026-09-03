"""
LeanTranslatorAgent —— LEAP Stage 2：Blueprint DAG → Lean 4 骨架（#26/#28）
================================================================================

把 Blueprint DAG 的每个**叶子节点**（原子子目标）翻译为 Lean 4 定理声明
（证明用 ``sorry`` 占位），合并成整棵 Lean 骨架文件，用声明模式编译审核：

- 全部声明 well-typed（除 sorry 外无错）→ verdict="ok"（整树搭桥成功）
- 某叶子声明类型/语法错误 → verdict="fail" + 结构化 gaps（该节点就是待修子目标）
- Lean 不可用 / 超时 / 翻译失败 → verdict="unknown"（安全降级）

与既有资产的关系：
- LeanBridge.audit_sketch：审核**单棵自然语言骨架**（LLM 重新理解整棵树）
- 本模块：直接消费 **Blueprint DAG** 的节点陈述（依赖驱动，不重新理解），
  sorry 与叶子节点一一对应，审核粒度到"哪个叶子节点不严谨"

对外接口：
- build_declaration(node_id, statement)：纯函数，Lean 陈述直包 / 非 Lean 返回 None
- translate_node(ctx, node, problem)：LLM 翻译单节点（容错解析）
- translate_and_audit(ctx, dag)：整树翻译 + 编译审核（主入口）
- run(ctx)：从 ctx.blueprint 取 DAG 执行，写 ctx.sketch_tree
"""

import json
import logging
import re
from typing import Optional

from .base import BaseAgent, TaskContext
from .blueprint_planner import BlueprintDAG, extract_json
# 复用 lean_bridge 的 import 归一化（full 聚合入口 / core 具体模块导入自适应，
# 2026-09-01：core 闭包缺 Mathlib/Tactic.olean 聚合入口，硬编码会导致验证全降级）
from .lean_bridge import _mathlib_import_block, _prepend_mathlib_import

logger = logging.getLogger("MathPilot")

# 判定"看起来已是 Lean 陈述"的启发式标记
_LEAN_HINTS = (
    " : ", "→", "∀", "∃", ":=", "theorem", "lemma", "def ", " ℝ", " ℤ", " ℕ",
    "^", "*", "+", "≤", "≥", "=",
)

# 简单类型名（用于声明命名 sanitize）
_INVALID_NAME_CHARS = re.compile(r"[^0-9A-Za-z_]")


def sanitize_node_id(node_id: str) -> str:
    """把节点 id 转成合法的 Lean 标识符（node_ 前缀 + 字母数字下划线）。"""
    s = _INVALID_NAME_CHARS.sub("_", str(node_id))
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "x"
    if s[0].isdigit():
        s = "n" + s
    return "node_" + s


def build_declaration(node_id: str, statement: str) -> Optional[str]:
    """把叶子节点陈述包装为 Lean 定理声明（证明 sorry 占位）。

    若 statement 看起来已是 Lean 表达式（含类型标注/量词/运算符），
    直接包装：``theorem <name> : <stmt> := by sorry``；
    否则返回 None（需要 LLM 翻译）。
    """
    stmt = (statement or "").strip()
    if not stmt:
        return None
    # 去掉可能的证明体（LLM 有时会带 := by ...）
    body_start = stmt.find(":=")
    if body_start != -1:
        stmt = stmt[:body_start].strip()
    # 去掉可能的前缀 `theorem ... :`（若已是完整声明）
    m = re.match(r"^(?:theorem|lemma)\s+\w+\s*:\s*([\s\S]+)$", stmt)
    if m:
        stmt = m.group(1).strip()
    stmt = stmt.strip().rstrip(".")
    if not stmt:
        return None
    if not _looks_lean(stmt):
        return None
    name = sanitize_node_id(node_id)
    return "theorem %s : %s := by\n  sorry" % (name, stmt)


def _looks_lean(stmt: str) -> bool:
    """启发式判断陈述是否已含 Lean 类型信息（量词/箭头/类型名/运算符）。"""
    s = stmt.strip()
    if len(s) < 2:
        return False
    return any(h in s for h in _LEAN_HINTS)


def count_sorries(lean_code: str) -> int:
    """统计 Lean 代码中的 sorry 占位数。"""
    if not lean_code:
        return 0
    return len(re.findall(r"\bsorry\b", lean_code))


def extract_declaration_names(lean_code: str) -> list:
    """提取代码中所有 theorem/lemma 声明名。"""
    if not lean_code:
        return []
    return re.findall(r"^(?:theorem|lemma)\s+(\w+)", lean_code, re.MULTILINE)


class LeanTranslatorAgent(BaseAgent):
    """LEAP Stage 2：Blueprint DAG 整树 → Lean 4 骨架 + 编译审核。"""

    name = "LeanTranslator"

    def __init__(self, client, config):
        super().__init__(client, config)
        self._bridge = None

    def _bridge_inst(self, ctx: TaskContext):
        """懒加载绑定当前题预算的 LeanBridge。"""
        try:
            from .lean_bridge import LeanBridge
            return LeanBridge(self.client, self.config, ctx.budget)
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanTranslator: LeanBridge 构造失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 单节点翻译
    # ------------------------------------------------------------------
    def translate_node(self, ctx: TaskContext, node_id: str,
                       statement: str, problem: str = "") -> Optional[str]:
        """把单个叶子节点翻译为 Lean 定理声明；失败返回 None。

        优先直包（statement 已是 Lean）；否则调用 LLM（带 2 次重试）。
        """
        direct = build_declaration(node_id, statement)
        if direct:
            return direct
        try:
            from prompts.lean_translator import (
                LEAN_NODE_TRANSLATE_SYSTEM, LEAN_NODE_TRANSLATE_USER_TEMPLATE)
        except ImportError:
            from submit.prompts.lean_translator import (
                LEAN_NODE_TRANSLATE_SYSTEM, LEAN_NODE_TRANSLATE_USER_TEMPLATE)
        user_msg = LEAN_NODE_TRANSLATE_USER_TEMPLATE.format(
            problem=problem or ctx.problem, node_statement=statement,
            node_id=node_id)
        for _ in range(2):
            raw = self.llm(
                ctx,
                [
                    {"role": "system", "content": LEAN_NODE_TRANSLATE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                0.0, 32768,
            )
            if not raw:
                continue
            parsed = extract_json(raw)
            if not parsed or parsed.get("error"):
                continue
            decl = str(parsed.get("lean_declaration", "") or "").strip()
            if not decl:
                continue
            return _strip_fence(decl)
        return None

    # ------------------------------------------------------------------
    # 整树翻译 + 审核
    # ------------------------------------------------------------------
    def translate_and_audit(self, ctx: TaskContext,
                            dag: BlueprintDAG) -> dict:
        """整树翻译 + 声明模式编译审核。返回结果 dict（不抛异常）。"""
        result = {
            "verdict": "unknown", "lean_code": "", "error": "",
            "gaps": [], "per_node": {}, "leaf_count": 0,
            "sorry_count": 0, "node_count": len(dag.nodes),
        }
        # 1) 收集叶子节点
        leaves = [n for n in dag.nodes.values() if not n.children]
        result["leaf_count"] = len(leaves)
        if not leaves:
            result["error"] = "DAG 无叶子节点"
            return result

        # 2) 每叶子 → Lean 声明（直包优先，LLM 兜底）
        declarations = []
        for leaf in leaves:
            decl = self.translate_node(ctx, leaf.id, leaf.statement, ctx.problem)
            result["per_node"][leaf.id] = {
                "ok": bool(decl),
                "declaration": decl or "",
                "error": "" if decl else "翻译失败",
            }
            if decl:
                declarations.append(decl)
        if not declarations:
            result["error"] = "所有叶子节点翻译失败"
            return result

        lean_code = _mathlib_import_block() + "\n\n" + "\n\n".join(declarations) + "\n"
        result["lean_code"] = lean_code
        result["sorry_count"] = count_sorries(lean_code)

        # 3) 声明模式编译（allow_sorry）：除 sorry 外必须 well-typed
        bridge = self._bridge_inst(ctx)
        if bridge is None:
            result["error"] = "LeanBridge 初始化失败"
            return result
        try:
            project_dir = bridge._lean_project_dir
            use_mathlib = bridge._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(lean_code)
                               if use_mathlib else lean_code)
            if project_dir:
                lean_file = "sketch_tree_%d_%d.lean" % (
                    __import__("os").getpid(),
                    int(__import__("time").monotonic() * 1e6))
                comp = bridge._compile(code_to_compile, project_dir,
                                       lean_filename=lean_file, allow_sorry=True)
                try:
                    __import__("os").remove(
                        __import__("os").path.join(project_dir, lean_file))
                except OSError:
                    pass
            else:
                import tempfile
                from .lean_bridge import _compile_lean
                with tempfile.TemporaryDirectory(prefix="lean_tree_") as work_dir:
                    comp = _compile_lean(
                        code_to_compile, work_dir,
                        lean_executable=bridge._lean_executable,
                        timeout=float(getattr(self.config, "preverify_timeout", 60.0) or 60.0),
                        allow_sorry=True,
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning("LeanTranslator: 编译异常（降级 unknown）: %s", e)
            result["error"] = str(e)[:200]
            return result

        if comp.get("ok"):
            result["verdict"] = "ok"
            return result
        # 4) 编译失败：抽取缺口（定位到具体叶子）
        from .lean_bridge import _analyze_formal_gaps
        result["gaps"] = _analyze_formal_gaps(comp.get("error", ""))
        result["error"] = comp.get("error", "整树声明编译失败")[:2000]
        result["verdict"] = "fail"
        return result

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, ctx: TaskContext) -> TaskContext:
        """从 ctx.blueprint 取 DAG，执行整树翻译+审核，写 ctx.sketch_tree。"""
        if not ctx.blueprint:
            ctx.sketch_tree = {"verdict": "unknown", "error": "无 Blueprint DAG"}
            return ctx
        try:
            dag = BlueprintDAG.from_dict(ctx.blueprint)
            ok, errors = dag.validate()
            if not ok:
                ctx.sketch_tree = {"verdict": "unknown",
                                   "error": "DAG 校验失败: %s" % "; ".join(errors[:5])}
                return ctx
        except Exception as e:  # noqa: BLE001
            ctx.sketch_tree = {"verdict": "unknown", "error": str(e)[:200]}
            return ctx
        result = self.translate_and_audit(ctx, dag)
        ctx.sketch_tree = result
        self.record(ctx, "lean_translator",
                    f"整树搭桥: verdict={result.get('verdict')}; "
                    f"叶子={result.get('leaf_count')}, "
                    f"sorry={result.get('sorry_count')}, "
                    f"缺口={len(result.get('gaps', []))}")
        return ctx


# =====================================================================
# 工具函数
# =====================================================================

def _strip_fence(text: str) -> str:
    """去除 Markdown 代码围栏。"""
    if not text:
        return ""
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", text)
    return (m.group(1).strip() if m else text.strip())
