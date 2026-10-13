# -*- coding: utf-8 -*-
"""子目标求解器的 Lean / 断言校验职责簇
（2026-10-08 批2-D：从 agent/sub_goal_solver.py 逐字搬出 12 个方法）。

搬出后形如模块级函数：实例方法保留 `self` 首参（原方法体逐字不变），
静态方法去 `@staticmethod`（普通函数）。原文件 `sub_goal_solver.py` 在类内
保留 1 行**跳板**（`_x = _sgs_lean._x`），故 `self._x(...)` /
`SubGoalSolverAgent._x(...)`（含 tests/test_dag_lean_check.py）**契约逐字不变**。
与 agent/verifier__review.py（批6）同口径。

本模块**自洽**：只依赖 stdlib（json/os/re/time/logging）+ `TaskContext`。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from .base import TaskContext

logger = logging.getLogger("MathPilot")


def _lean_dag_logic_check(self, ctx: TaskContext, dag,
                          node_ids) -> dict:
    """Lean 作为「逻辑错误」机器检测器：把节点陈述翻译成 Lean Prop
        并编译（声明模式 allow_sorry）。返回 {node_id: 首条诊断}。

        可判定层：语句无法良构形式化 / 符号未定义 / 类型错 / 自引用 /
        不成闭合命题。方向与语义错误**不在此列**（仍由 DagReviewer LLM 判）。

        成本受控（勿拖累解题预算——上轮 45 题教训）：
        - 每题至多被调用 1 次（gate 首轮、且有 reject 信号时）；
        - 节点数 ≤ dag_lean_max_nodes（默认 6）；
        - 时间紧迫 / Lean 环境不可用 / 无 lake 工程 / LLM 翻译失败 → 一律
          返回 {}（记一条事件后静默放行，绝不阻断、绝不误判整图）。
        """
    try:
        _t0 = time.perf_counter()
        if not getattr(self.config, "dag_replan_lean_check", True):
            # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return {}。
            self.record(ctx, "dag_replan",
                        "求解前 Lean 逻辑检查已跳过：开关 dag_replan_lean_check=0")
            return {}
        if not node_ids:
            return {}
        if ctx.is_time_critical() or ctx.gen_time_up():
            self.record(ctx, "dag_replan",
                        "求解前 Lean 逻辑检查已跳过：当前处于时间紧迫/生成侧截止")
            return {}
        from tools.lean_local.lean_bridge import LeanBridge
        from tools.lean_local.lean_bridge import _trash_lean_file
        from tools.lean_local.lean_bridge import _mathlib_import_block
        bridge = LeanBridge(self.client, self.config)
        if not bridge.lean_available:
            self.record(ctx, "dag_replan",
                        "求解前 Lean 逻辑检查跳过（Lean 环境不可用）")
            return {}
        work_dir = bridge._lean_project_dir or ""
        if not work_dir:
            self.record(ctx, "dag_replan",
                        "求解前 Lean 逻辑检查跳过（无 lake 工程）")
            return {}
        cap = max(1, int(getattr(self.config, "dag_lean_max_nodes", 50) or 50))
        targets = [nid for nid in node_ids
                   if nid in dag.nodes][:cap]
        if not targets:
            return {}
        stmts = {nid: (dag.nodes[nid].statement or "")[:300]
                 for nid in targets}
        from prompts.dag_lean_check import (
            DAG_LEAN_CHECK_SYSTEM, DAG_LEAN_CHECK_USER_TEMPLATE)
        from utils.prefill import prefill_messages, stitch
        user_msg = DAG_LEAN_CHECK_USER_TEMPLATE.format(
            problem=(ctx.problem or "")[:1200],
            statements=json.dumps(stmts, ensure_ascii=False))
        _PREFILL = '{"'
        resp = self.llm(ctx, prefill_messages(
            [{"role": "system", "content": DAG_LEAN_CHECK_SYSTEM},
             {"role": "user", "content": user_msg}],
            _PREFILL), 0.0, 16384)
        if resp:
            resp = stitch(_PREFILL, resp)
        exprs = self._parse_lean_expr_map(resp, targets)
        if not exprs:
            self.record(ctx, "dag_replan",
                        "求解前 Lean 逻辑检查跳过（节点翻译为空/不可解析）")
            return {}
        # 组装单文件：import 头（兼容部分编译布局，用 _mathlib_import_block）
        # + 每节点一行 example（匿名声明）；行号即节点映射。
        head_lines = [ln for ln in _mathlib_import_block().split("\n")]
        code_lines = list(head_lines)
        _chain_merged = [False]   # 合并标记（只并一次）
        if code_lines and code_lines[-1].strip():
            code_lines.append("")
        line_of: dict = {}
        for nid in targets:
            expr = exprs.get(nid, "")
            if not expr:
                continue
            expr = expr.strip()
            if not expr:
                continue
            # ★ 2026-10-13（§3.6.4 **合并编译**）：把「终态链 Lean」并入同一文件 ——
            #   一次编译既查节点，也查「蓝图是否偏离终态链」。只并一次，且去重防重名。
            if not _chain_merged[0]:
                _chain_merged[0] = True
                _uc = _extract_chain_lean_lines(ctx)
                if _uc:
                    code_lines.extend(_uc)
                    code_lines.append("")
            code_lines.append(f"example : ({expr}) := by sorry")
            line_of[nid] = len(code_lines)
        if not line_of:
            return {}
        code = "\n".join(code_lines)
        fname = (f"daglogic_{os.getpid()}_"
                 f"{int(time.time() * 1000) % 1000000}.lean")
        result = bridge._compile(code, work_dir, lean_filename=fname,
                                 allow_sorry=True)
        try:
            _trash_lean_file(work_dir, fname)
        except Exception:  # noqa: BLE001
            pass
        if not result or result.get("ok"):
            # 编译全过（节点均可良构形式化）也留痕，便于评测区分
            # "Lean 检查已执行但无逻辑错误" 与 "检查根本没触发"
            self.record(ctx, "dag_replan",
                        f"求解前 Lean 逻辑检查通过 {len(line_of)} 节点"
                        f"（无编译错误，耗时 {time.perf_counter() - _t0:.1f}s）")
            return {}
        self.record(ctx, "dag_replan",
                    f"求解前 Lean 逻辑检查：{len(line_of)} 节点编译，"
                    f"耗时 {time.perf_counter() - _t0:.1f}s"
                    f"（含把陈述翻译成 Lean 的 LLM 调用 + 编译）")
        err_text = str(result.get("error", ""))
        return self._map_lean_errors(err_text, line_of)
    except Exception as exc:  # noqa: BLE001  任何异常：降级放行，绝不阻断
        # 2026-09-08 排查：原仅 logger.debug → 评测零痕迹，无法区分
        # "检查未执行" 与 "执行中异常被吞"。升级为 record 留痕（防静默失效）。
        logger.debug("求解前 Lean 逻辑检查异常（放行）: %s: %s",
                     type(exc).__name__, exc)
        self.record(ctx, "dag_replan",
                    f"求解前 Lean 逻辑检查异常（放行）: "
                    f"{type(exc).__name__}: {str(exc)[:120]}")
        return {}


def _numeric_lean_verify(self, ctx: TaskContext, result: str) -> str:
    """L2 数值断言 Lean 验证，返回反馈文本（空=通过/无可验断言/放行）。"""
    if not getattr(self.config, "enable_numeric_lean_verify", False):
        return ""
    if ctx.gen_time_up():
        return ""
    meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    cnt = int(meta.get("numeric_lean_count", 0) or 0)
    cap = max(1, int(getattr(self.config, "lean_numeric_max_per_q", 2) or 2))
    if cnt >= cap:
        return ""
    pairs = self._extract_lean_assert_pairs(result)
    if not pairs:
        return ""
    from tools.lean_local.lean_bridge import LeanBridge
    from tools.lean_local.lean_bridge import _trash_lean_file
    from tools.lean_local.lean_bridge import _mathlib_import_block
    bridge = LeanBridge(self.client, self.config)
    if not bridge.lean_available:
        return ""
    work_dir = bridge._lean_project_dir or ""
    if not work_dir:
        return ""
    code_lines = [ln for ln in _mathlib_import_block().split("\n")]
    if code_lines and code_lines[-1].strip():
        code_lines.append("")
    line_of = {}
    for idx, (L, R, kind, *rest) in enumerate(pairs):
        # 隐式乘（)(、)字母/数字、数字( ）→ 显式 *（Lean 中相邻即应用）
        L = self._fix_lean_mul(L)
        R = self._fix_lean_mul(R)
        if kind == "num":
            decl = f"example : ({L} : ℚ) = ({R} : ℚ) := by norm_num"
        else:
            v = rest[0]
            decl = f"example ({v} : ℤ) : {L} = {R} := by ring"
        code_lines.append(decl)
        line_of[idx] = len(code_lines)
    code = "\n".join(code_lines)
    fname = f"sgnum_{os.getpid()}_{int(time.time() * 1000) % 1000000}.lean"
    try:
        r = bridge._compile(code, work_dir, lean_filename=fname,
                            allow_sorry=True)
    finally:
        try:
            _trash_lean_file(work_dir, fname)
        except Exception:  # noqa: BLE001
            pass
    meta["numeric_lean_count"] = cnt + 1
    if not r or r.get("ok"):
        return ""
    err_text = str(r.get("error", ""))
    # 行号 → 断言映射；文件级错误（行号 < 首条 example）视为环境问题放行
    min_line = min(line_of.values())
    node_fail: dict = {}
    msg_of_line: dict = {}
    for m in re.finditer(r":(\d+):(\d+):\s*(error|warning):\s*([^\n]*)",
                         err_text):
        line = int(m.group(1))
        if m.group(3) == "error" and line not in msg_of_line:
            msg_of_line[line] = m.group(4).strip()
    if msg_of_line and min(msg_of_line) < min_line:
        return ""                          # import/文件级 → 环境问题
    for idx, ln in line_of.items():
        msg = msg_of_line.get(ln)
        if msg:
            node_fail[idx] = msg[:120]
    if not node_fail:
        return ""
    # 命中 ≥1 条断言：组装反馈（最多报 2 条）
    lines = []
    for idx in sorted(node_fail)[:2]:
        L, R = pairs[idx][0], pairs[idx][1]
        diag = node_fail[idx]
        lines.append(
            f"断言「{L} = {R}」未通过 Lean 验证"
            + (f"（{diag}）" if diag else ""))
    return ("【Lean 数值验证未通过】本步含以下计算断言，编译器未能确认成立，"
            "请逐条复核并修正数值/表达式后重新给出【本步结果】："
            + "；".join(lines) + "。"
            "（若表达式本身含 Lean 不支持的记号，请改写为等价的标准形式）")


def _extract_lean_assert_pairs(self, result: str) -> list:
    """从子目标结果提取可 Lean 验证的等式断言。

        返回 [(lean_l, lean_r, kind)]，kind: "num"(ℚ norm_num) | "poly"(ℤ ring)。
        宁缺毋滥：只收两侧均为纯数值表达式（kind=num）或同一单变量整式
        （kind=poly，无除号）的断言；含多变量/除号/分数指数/LaTeX → 丢弃。
        """
    if not result:
        return []
    text = str(result)
    # 剥 LaTeX 内联/显示定界符
    text = re.sub(r"\\[a-zA-Z]+", " ", text)     # 去 \frac \sqrt 等命令
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("$", " ")
    text = text.replace("\\", " ")
    out = []
    for seg in text.split("\n"):
        if "=" not in seg:
            continue
        parts = [p.strip() for p in seg.split("=")]
        for i in range(len(parts) - 1):
            L, R = parts[i], parts[i + 1]
            # R 取到行尾（连环等号时一次只取相邻两段，宁可少验）
            L, R = L.strip(), R.strip()
            if not (1 <= len(L) <= 70 and 1 <= len(R) <= 70):
                continue
            if not (self._L2_EXPR_CHARS.match(L)
                    and self._L2_EXPR_CHARS.match(R)):
                continue
            # ^ 指数必须是非负整数（避免 13^(2/3) 这类 Lean 语法不支持）
            if re.search(r"\^[^0-9(]|\^$", L) or re.search(r"\^[^0-9(]|\^$", R):
                continue
            # 宁缺毋滥：函数调用形态（g(0)/f(1)/sin(x)）与隐式乘
            # （2x / xx / x(3)）在 Lean 中不合法 → 一律丢弃不构造
            if (re.search(r"[a-zA-Z]\(", L) or re.search(r"[a-zA-Z]\(", R)
                    or re.search(r"\d[a-zA-Z]", L) or re.search(r"\d[a-zA-Z]", R)):
                continue
            letters = sorted(set(re.findall(r"[a-zA-Z]", L + R)))
            if not letters:
                # 纯数值（可含负号/分数/幂）→ ℚ norm_num
                out.append((L, R, "num"))
            elif len(letters) == 1:
                v = letters[0]
                if "/" in (L + R):
                    continue              # 除号 → 非整式，ring 不适用
                # 变量须独立出现（两侧不被其他字母邻接，如 xx 简写）
                if (re.search(r"[a-zA-Z]" + v, L)
                        or re.search(v + r"[a-zA-Z]", L)
                        or re.search(r"[a-zA-Z]" + v, R)
                        or re.search(v + r"[a-zA-Z]", R)):
                    continue
                out.append((L, R, "poly", v))
            # 多变量 → 跳过
    # 去重（保持序）
    seen, uniq = set(), []
    for t in out:
        key = tuple(t[:2])
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq[:3]                       # 单次最多 3 条断言


def _lean_backup_fails(self, fails: list) -> list:
    """对疑似错的断言做 Lean 多策略编译背书（P4 自动证明链）。

        返回双确认的 (L, R, info) 子集；组内任一策略闭合（该行无 error）
        → 剔除（防 sympy 误报）；组内全部策略失败（每行均有 error）→ 确认
        不成立。Lean 不可用/文件级错误/断言含语法不支持记号 → 宁放行不反馈。
        """
    try:
        from tools.lean_local.lean_bridge import LeanBridge
        from tools.lean_local.lean_bridge import _trash_lean_file
        built = self._build_auto_proof(fails)
        if not built:
            return []
        code_lines, group_of = built
        bridge = LeanBridge(self.client, self.config)
        if not bridge.lean_available:
            return []
        work_dir = bridge._lean_project_dir or ""
        if not work_dir:
            return []
        code = "\n".join(code_lines)
        fname = (f"sgcheck_{os.getpid()}_"
                 f"{int(time.time() * 1000) % 1000000}.lean")
        try:
            r = bridge._compile(code, work_dir, lean_filename=fname,
                                allow_sorry=True)
        finally:
            try:
                _trash_lean_file(work_dir, fname)
            except Exception:  # noqa: BLE001
                pass
        if not r or r.get("ok"):
            return []                            # 全部通过 → sympy 误报
        err_text = str(r.get("error", ""))
        first_decl = min(v[0] for v in group_of.values())
        msg_of_line = {}
        for m in re.finditer(
                r":(\d+):(\d+):\s*error:\s*([^\n]*)", err_text):
            line = int(m.group(1))
            if line not in msg_of_line:
                msg_of_line[line] = m.group(3).strip()
        if msg_of_line and min(msg_of_line) < first_decl:
            return []                            # import/文件级 → 环境问题
        confirmed = []
        for i, lines in group_of.items():
            errs = [msg_of_line[ln] for ln in lines if ln in msg_of_line]
            if len(errs) < len(lines):
                continue                         # ≥1 策略闭合 → sympy 误报
            if any(any(k in e for k in self._SYNTAX_ERR_KW)
                   for e in errs):
                continue                         # 语法类失败 → 不可信，放行
            confirmed.append(fails[i])
        return confirmed
    except Exception:  # noqa: BLE001  异常一律放行（不误报）
        return []


def _sympy_judge(self, L: str, R: str):
    """sympy 判定 L=R。返回 ("pass"|"fail"|"unknown", 说明/真值串)。

        判据（防误报红线）：
        - **赋值式跳过**：任一侧是单个未知变量（x = 5、s = 265/247）→
          这是"求解结果"而非"恒等断言"，无 ground truth 可验 → unknown
          放行（2026-09-08 smoke10 实证：模型大量用 <check>x = 值</check>
          声明赋值结果，误当恒等断言会误报把对的改错）；
        - 整式/数值（无除号无函数）→ expand(L-R)==0 才 pass；非 0 差为常数
          或含自由变量 → fail（多项式不恒等=断言错，无限域可靠）；
        - 含除号/函数 → 仅 simplify(L-R) 为 0 → pass、为非零常数 → fail，
          非常数一律 unknown（放行，绝不误报）。
        """
    try:
        from utils.sympy_tools import _try_parse
    except Exception:  # noqa: BLE001
        return "unknown", ""
    try:
        # 赋值式跳过：一侧是单个变量 v 且另一侧**不含 v**（x = 5、s = 265/247）
        # 才是"求解结果"；若另一侧也含 v（如 (x^2-1)/(x-1) = x）则是恒等
        # 断言，仍正常判定。
        _Lt, _Rt = L.strip(), R.strip()
        if (re.fullmatch(r"[a-zA-Z]", _Lt) and _Lt not in R) or (
                re.fullmatch(r"[a-zA-Z]", _Rt) and _Rt not in L):
            return "unknown", ""
        L2, R2 = self._pow_to_python(L), self._pow_to_python(R)
        a, _ = _try_parse(L2)
        b, _ = _try_parse(R2)
        if a is None or b is None:
            return "unknown", ""
        import sympy as _sp
        has_frac = ("/" in L2 + R2) or bool(re.search(
            r"(sqrt|sin|cos|tan|log|ln|exp|abs|floor|ceil)\(", L2 + R2))
        if has_frac:
            d = _sp.simplify(a - b)
            if d == 0:
                return "pass", ""
            if d.is_number and d != 0:
                return "fail", f"左式实际值应为 {_sp.simplify(a)}"
            return "unknown", ""
        d = _sp.expand(a - b)
        if d == 0:
            return "pass", ""
        # 整式差非 0：确定性不恒等 → fail（语义化说明供反馈）
        if d.free_symbols:
            return "fail", f"两侧展开后相差 {_sp.simplify(d)}，并非恒等"
        return "fail", f"左式实际值应为 {_sp.simplify(a)}"
    except Exception:  # noqa: BLE001
        return "unknown", ""


def _check_assert_verify(self, ctx: TaskContext, result: str) -> str:
    """<check> 协议验证入口，返回反馈文本（空=通过/无断言/放行）。"""
    if not getattr(self.config, "enable_numeric_lean_verify", False):
        return ""
    if ctx.gen_time_up():
        return ""
    meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    cnt = int(meta.get("numeric_lean_count", 0) or 0)
    cap = max(1, int(getattr(self.config, "lean_numeric_max_per_q", 2) or 2))
    if cnt >= cap:
        return ""
    pairs = self._extract_check_asserts(result)
    if not pairs:
        return ""
    fails = []                                 # (L, R, 说明)
    for L, R in pairs:
        v, info = self._sympy_judge(L, R)
        if v == "fail":
            fails.append((L, R, info))
    if not fails:
        return ""
    # Lean 背书（只对疑似错的断言编译，双确认防 sympy 边缘误报）
    confirmed = self._lean_backup_fails(fails)
    if not confirmed:
        return ""
    meta["numeric_lean_count"] = cnt + 1
    lines = []
    for L, R, info in confirmed:
        if info:
            lines.append(f"断言「{L} = {R}」不成立（{info}）")
        else:
            lines.append(f"断言「{L} = {R}」不成立（两侧并不恒等）")
    return ("【计算断言未通过验证】你声明的等式未通过客观验证（SymPy 精确"
            "判定 + Lean 编译器双重确认），请修正该步计算后重新给出【本步"
            "结果】：" + "；".join(lines) + "。")


def _extract_check_asserts(self, result: str) -> list:
    """提取 <check> 协议断言 → [(L, R)]（宁缺毋滥）。"""
    if not result:
        return []
    out = []
    for m in self._CHECK_RE.finditer(str(result)):
        body = m.group(1).strip()
        if not body or len(body) > 160 or "=" not in body:
            continue
        parts = [p.strip() for p in body.split("=")]
        if len(parts) != 2:                    # 多 = → 丢弃
            continue
        L, R = parts
        if not (1 <= len(L) <= 70 and 1 <= len(R) <= 70):
            continue
        if not (self._L2_EXPR_CHARS.match(L)
                and self._L2_EXPR_CHARS.match(R)):
            continue
        if (re.search(r"[a-zA-Z]\(", L) and not re.search(
                r"^(sin|cos|tan|log|ln|exp|sqrt|abs|floor|ceil|min|max)\(",
                L)):
            continue                          # 函数调用形态（sin 等除外）
        out.append((L, R))
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:4]


def _merge_lean_rejects(report, lean_fails: dict) -> list:
    """Lean 编译失败的节点硬升级为 reject（含 LLM 漏判/未评的），
        返回本轮新升级的 node_id 列表。已 reject 的节点保持不动。"""
    from .dag_reviewer import DagReviewResult
    ups = []
    for nid, err in lean_fails.items():
        issue = f"lean_logic_error: {err}"
        r = report.results.get(nid)
        if r is None:
            report.results[nid] = DagReviewResult(
                node_id=nid, verdict="reject", quality_score=0.2,
                issues=[issue],
                reconstruction_hint=(
                    "该节点陈述存在可判定的形式化逻辑错误（Lean 编译失败），"
                    "请修正陈述中的符号/量词/类型错误或改换可形式化的表述"),
                heuristic_only=False)
            ups.append(nid)
        elif not r.is_reject:
            r.verdict = "reject"
            try:
                r.quality_score = min(float(r.quality_score or 0.0), 0.3)
            except (TypeError, ValueError):
                r.quality_score = 0.3
            if issue not in list(r.issues):
                r.issues.append(issue)
            ups.append(nid)
    return ups


def _parse_lean_expr_map(resp, targets) -> dict:
    """解析翻译 LLM 的 JSON 输出 → {nid: expr}；失败/空返回 {}。"""
    if not resp:
        return {}
    text = str(resp).strip()
    # 剥 markdown 围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        raw = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        raw = None
    if not isinstance(raw, dict):
        return {}
    out = {}
    for nid in targets:
        val = raw.get(nid)
        if isinstance(val, str) and val.strip():
            out[nid] = val.strip()
    return out


def _map_lean_errors(err_text: str, line_of: dict) -> dict:
    """把 Lean 编译错误文本按行号映射回节点。行号在首个 example 之前
        （import/文件级错误）→ 视为环境问题，返回 {}（不误判节点）。"""
    if not err_text or not line_of:
        return {}
    min_line = min(line_of.values())
    node_fail: dict = {}
    msg_of_line: dict = {}
    for m in re.finditer(r":(\d+):(\d+):\s*(error|warning):\s*([^\n]*)",
                         err_text):
        line = int(m.group(1))
        if m.group(3) == "error" and line not in msg_of_line:
            msg_of_line[line] = m.group(4).strip()
    if any(line < min_line for line in msg_of_line):
        return {}                      # 文件级/import 错误 → 环境问题
    for nid, line in line_of.items():
        msg = msg_of_line.get(line)
        if msg:
            node_fail[nid] = msg[:160]
    return node_fail


def _build_auto_proof(self, fails: list):
    """为疑似错断言构建多策略 Lean 声明（P4）。

        返回 (code_lines, group_of)：group_of[i] = fails[i] 各策略声明行号；
        形态不支持（含除号的变量式/超 3 变量）→ 该断言无组（调用方宁放行）。
        num = 纯数值（ℚ norm_num 系 + ring）；poly = 无除号整式（ℤ 策略族）。
        """
    try:
        from tools.lean_local.lean_bridge import _mathlib_import_block
    except Exception:  # noqa: BLE001
        return None
    code_lines = [ln for ln in _mathlib_import_block().split("\n")]
    if code_lines and code_lines[-1].strip():
        code_lines.append("")
    group_of: dict = {}
    for i, _it in enumerate(fails):
        L, R = str(_it[0]), str(_it[1])
        Lx, Rx = self._fix_lean_mul(L), self._fix_lean_mul(R)
        vars_ = sorted(set(re.findall(r"[a-zA-Z]", L + R)))
        if not vars_:
            head = f"example : ({Lx} : ℚ) = ({Rx} : ℚ)"
            decls = ["by norm_num", "by norm_num1", "by ring"]
        elif "/" not in (L + R) and len(vars_) <= 3:
            binds = " ".join(f"({v} : ℤ)" for v in vars_)
            head = f"example {binds} : {Lx} = {Rx}"
            decls = ["by ring", "by ring_nf", "by nlinarith",
                     "by omega", "by grind", "by aesop"]
        else:
            continue                       # Lean 无法背书 → 宁放行
        lines = []
        for d in decls:
            code_lines.append(f"{head} := {d}")
            lines.append(len(code_lines))
        group_of[i] = lines
    if not group_of:
        return None
    return code_lines, group_of


def _fix_lean_mul(expr: str) -> str:
    """把 NL 隐式乘转 Lean 显式 *：)(、)字母/数字、数字( → 显式乘。

        相邻括号/字母/数字在 Lean 里是函数应用（语法错或语义错），
        norm_num/ring 场景一律应视为乘号。
        """
    e = expr.strip()
    # 数字后紧跟左括号：2(x+1) → 2 * (x+1)（^ 后括号不动：2^(3) 罕见，宁可不转）
    e = re.sub(r"(?<=[0-9])\(", " * (", e)
    # 右括号后紧跟 ( / 字母 / 数字：)( → ) * (、)x → ) * x、)2 → ) * 2
    e = re.sub(r"\)(?=[0-9a-zA-Z(])", ") * ", e)
    # 折叠可能产生的重复乘号（"* * "）
    e = re.sub(r"\*\s*\*", "*", e)
    e = re.sub(r"\(\s*\*\s*\(", "(", e)
    return e.strip()

def _extract_chain_lean_lines(ctx) -> list:
    """抽出「题意理解链」的 Lean 片段（去 import、防重名），供**合并编译**用（§3.6.4）。

    合并目的：一次编译同时检查 ① 蓝图节点陈述是否 well-typed；② 蓝图是否**偏离**理解链。
    安全处理（否则合并会**破坏**原有检查）：
      · 去掉片段里的 import 行（本文件已 import Mathlib）；
      · 顶层声明加 uchain_ 前缀，避免与蓝图节点重名；
      · 上限 60 行（防爆）。
    """
    import re as _re_uc
    uc = getattr(ctx, "understanding_chain", None)
    if not isinstance(uc, dict):
        return []
    code = str(uc.get("lean_code") or "").strip()
    if not code:
        return []
    out = []
    for ln in code.split("\n"):
        t = ln.strip()
        if not t or t.startswith("import "):
            continue
        m = _re_uc.match(r"^(lemma|theorem|def|example)\s+([A-Za-z_][A-Za-z0-9_'.]*)", t)
        if m and not m.group(2).startswith("uchain_"):
            t = t.replace(m.group(2), "uchain_" + m.group(2).split(".")[-1], 1)
        out.append(t)
    return out[:60]
