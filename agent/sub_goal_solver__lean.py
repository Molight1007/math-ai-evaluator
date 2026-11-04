# -*- coding: utf-8 -*-
"""子目标求解器的 Lean / 断言校验职责簇
（2026-10-08 批2-D：从 agent/sub_goal_solver.py 逐字搬出 12 个方法）。

搬出后形如模块级函数：实例方法保留 `self` 首参（原方法体逐字不变），
静态方法去 `@staticmethod`（普通函数）。原文件 `sub_goal_solver.py` 在类内
保留 1 行**跳板**（`_x = _sgs_lean._x`），故 `self._x(...)` /
`SubGoalSolverAgent._x(...)` **契约逐字不变**。
与 agent/verifier__review.py（批6）同口径。

★ 2026-10-15（用户决策「把没有用和关掉开关的部分全删了」）：撤除
`_lean_dag_logic_check` / `_merge_lean_rejects` / `_parse_lean_expr_map` /
`_map_lean_errors` / `_extract_chain_lean_lines`（求解前 DAG 强制门的 Lean
逻辑层检测）—— 其唯一调用者是默认关闭的 `dag_replan_gate`；配套的
`prompts/dag_lean_check.py` 与 `tests/test_dag_lean_check.py` 一并删除。
剩余 8 个方法继续服务「数值断言 Lean 验证」链。

本模块**自洽**：只依赖 stdlib（os/re/time/logging）+ `TaskContext`。
"""
from __future__ import annotations
from contracts.policy import POLICY

import logging
import os
import re
import time

from .base import TaskContext

logger = logging.getLogger("MathPilot")


def _sp_symtab():
    """延迟获取符号表模块（避免本文件顶层依赖 sympy 影响无 sympy 环境）。"""
    from utils import symbol_table
    return symbol_table


def _zero_state(expr):
    """判断表达式是否恒等于 0，返回 True / False / None（判不出）。

    ★★ 2026-11-02：此前一律用 `expr == 0` 判，而这是**结构比较**。
      根因在 `utils/sympy_tools._try_parse` 用 `sympify(..., evaluate=False)` 解析，
      数字和会保留成**未求值的 Add**：

          expand(10 + 18*100 - 1810)  ->  -1800 + 1800
          (-1800 + 1800) == 0         ->  False      # 结构不等
          (-1800 + 1800).is_zero      ->  True       # 这才是对的问题

      后果是**只要断言左式写成乘积/幂的形态，即使算对也一律判「不成立」**。
      服务器 109 题次实测：闸门下 93% 的「上游不达标」是这一类假阳性，
      例如「18*100 + 10 = 1810」判词自己写着「左式实际值应为 1810」却判 fail。

    ★ 返回 None 而非 False：判不出时必须能区分「确定非零」与「算不出」，
      否则会把未知当错误（本项目「宁可放过」原则）。
    """
    try:
        if expr == 0:
            return True
        _z = getattr(expr, "is_zero", None)
        if _z is not None:
            return bool(_z)
        import sympy as _sp
        _s = _sp.simplify(expr)
        if _s == 0:
            return True
        if getattr(_s, "is_number", False):
            return False
        return None
    except Exception:  # noqa: BLE001
        return None


def _numeric_lean_verify(self, ctx: TaskContext, result: str) -> str:
    """L2 数值断言 Lean 验证，返回反馈文本（空=通过/无可验断言/放行）。"""
    if not POLICY['enable_numeric_lean_verify']:
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


def _is_single_symbol(s: str) -> bool:
    """这段文本是不是**一个符号**（x / T_max / x_k / Δ / λ）。

    ★ 2026-11-02：原来只认单个 ASCII 字母，导致 `T_max = 76`、`Δ = ...`、
      `x_k = ...` 这类**赋值式**被当成恒等断言去判，必然判「并非恒等」。
    """
    _s = (s or "").strip()
    if not _s:
        return False
    # 允许 Unicode 希腊字母等单字符符号，以及带下标的标识符
    return bool(re.fullmatch(r"[^\W\d]\w*", _s, flags=re.UNICODE))


def _sympy_judge(self, L: str, R: str, symtab=None):
    """sympy 判定 L=R。返回 ("pass"|"fail"|"unknown", 说明/真值串)。

        判据（防误报红线）：
        - **赋值式跳过**：任一侧是单个符号（x = 5、T_max = 76、Δ = -4a+5）→
          这是"求解结果/定义"而非"恒等断言"，无 ground truth 可验 → unknown
          放行（2026-09-08 smoke10 实证：模型大量用 <check>x = 值</check>
          声明赋值结果，误当恒等断言会误报把对的改错）；
        - 整式/数值（无除号无函数）→ expand(L-R) 为 0 才 pass；差是**非零常数**
          → fail；
        - ★ 差含自由符号 → 先用 `symtab`（本题已定义符号）代入再判；代入后仍是
          非零常数 → fail；仍含**未定义**符号 → unknown，且原因里写出缺哪些符号；
        - 含除号/函数 → 仅 simplify(L-R) 为 0 → pass、为非零常数 → fail，
          非常数一律 unknown（放行，绝不误报）。

        ★★ 2026-11-02 口径修正（推翻同日早些时候「有自由符号即 fail」的判断）
        ----------------------------------------------------------------
        当时的理由是「多项式恒等性在 expand 后可判定，带自由符号就不是零多项式
        ⇒ 断言必错」。这个推理只对**恒等断言**成立，而推导里的 `等式 = L = R`
        绝大多数**不是恒等断言**，是「在该配置下 L 等于 R」。

        服务器 63 题次实测：重判后仍判 fail 的 51 行里 50 行是这一类，典型：
            T_max - 76              # T_max 是前面步骤定义的量
            -4*a + Δ - 5            # Δ 是定义过的常量
            x**2 + y**2 + z**2 - 3  # 这是**题设条件**，不是恒等式
            -x_k**2 + y_k           # 下标符号别名
        判据里没有符号表，**无法区分「自由变量」与「前面已定义的常量」**，
        于是任何用到已定义量的正确步骤都会被判死。

        ★★ 2026-11-03 修正那个修正
        ---------------------------
        当时处置成「含符号一律 unknown 放行」—— 这是用**删除判据**解决**信息缺失**，
        实测在 112 行里直接放弃了 35 次判定。而定义本来就在盘上（前序步骤结论行、
        本步依据、题设）。改为：**能代入就代入后再判，不能代入才 unknown，且原因
        写明缺哪个符号**。`symtab` 为 None 时行为与「放行」一致，但原因可区分，
        供 A/B 对照逐条量化「救回多少」。

        ★★★ 2026-11-03 实测**负结果** —— `symtab` 禁止接进生产链路
        ----------------------------------------------------------
        干净 A/B（63 题次 / 112 行，两臂同一份代码、只翻 symtab 一个变量；
        两臂的符号表都从历史原始数据独立构建，不是拿自己的判定结果喂自己）：
            undecided -> correct   3
            undecided -> incorrect 5
            反向退化（确定判词变判不出）0
        但**逐条抽验这 8 条，只有 1 条经得起检验**（`a = m(m+1)` ⇒
        `4a+1 = (2m+1)^2` 成立），其余 7 条是**符号表污染**造成的误判：

            P(x) = x - 4     判「实际值应为 x」      把函数名当常量（P = 1）
            a+b+c = 10       判「实际值应为 2」      a=1,b=1 抄自某特例分支
            x^2 = 3-y^2-z^2  判不成立               x=0 / z=x^3 是错误绑定

        根因有两层：① 用正则从散文里抽「某符号 = 某式」本身不可靠，抽错一条
        就毒化后续所有判定；② 数学推导里同一符号在不同分支/不同子目标下含义
        可以不同，**「全局单一符号表」在语义上就不成立**（分类讨论是常规写法）。

        ⇒ 因此 `symtab` 只作**回放/诊断入口**，生产链路一律不传（默认 None，
        行为与改动前完全一致）。真要做得对，绑定必须来自受控句式（`设/记/令`）
        或结构化字段，并且按分支作用域隔离 —— 不是事后从散文里挖。
        """
    try:
        from utils.sympy_tools import _try_parse
    except Exception:  # noqa: BLE001
        return "unknown", ""
    try:
        # 赋值式跳过：一侧是单个符号 v 且另一侧**不含 v**（x = 5、T_max = 76）
        # 才是"求解结果/定义"；若另一侧也含 v（如 (x^2-1)/(x-1) = x）则是恒等
        # 断言，仍正常判定。
        _Lt, _Rt = L.strip(), R.strip()
        if (_is_single_symbol(_Lt) and _Lt not in R) or (
                _is_single_symbol(_Rt) and _Rt not in L):
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
            _zs = _zero_state(d)
            if _zs is True:
                return "pass", ""
            if getattr(d, "free_symbols", None) and symtab:
                d2, _unres, _used = _sp_symtab().substitute(d, symtab)
                d2 = _sp.simplify(d2)
                if _zero_state(d2) is True:
                    return "pass", "代入已定义符号（%s）后成立" % _sp_symtab().describe(_used)
                if not getattr(d2, "free_symbols", None):
                    return "fail", ("代入已定义符号后左式实际值应为 %s"
                                    % _sp.simplify(_sp_symtab().substitute(a, symtab)[0]))
                return "unknown", ("代入后仍含未定义符号 %s"
                                   % ",".join(sorted(_unres))[:60])
            if _zs is False and d.is_number:
                return "fail", f"左式实际值应为 {_sp.simplify(a)}"
            return "unknown", ""
        d = _sp.expand(a - b)
        if _zero_state(d) is True:
            return "pass", ""
        if d.free_symbols:
            # ★ 2026-11-03：不再一律放行 —— 先拿本题已定义符号代入，能判就判。
            if symtab:
                d2, _unres, _used = _sp_symtab().substitute(d, symtab)
                d2 = _sp.expand(d2)
                if _zero_state(d2) is True:
                    return "pass", ("两侧相差在代入已定义符号（%s）后为零"
                                    % _sp_symtab().describe(_used))
                if not d2.free_symbols:
                    return "fail", ("代入已定义符号后左式实际值应为 %s"
                                    % _sp.simplify(_sp_symtab().substitute(a, symtab)[0]))
                return "unknown", ("两侧相差 %s（代入后仍含未定义符号 %s，无定义可代入）"
                                   % (_sp.simplify(d2),
                                      ",".join(sorted(_unres))[:60] or "?"))
            return "unknown", f"两侧相差 {_sp.simplify(d)}（含符号，无符号表不可判）"
        if _zero_state(d) is False:
            return "fail", f"左式实际值应为 {_sp.simplify(a)}"
        return "unknown", ""
    except Exception:  # noqa: BLE001
        return "unknown", ""


def _check_assert_verify(self, ctx: TaskContext, result: str) -> str:
    """<check> 协议验证入口，返回反馈文本（空=通过/无断言/放行）。"""
    if not POLICY['enable_numeric_lean_verify']:
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


# ============================================================
# ★ 2026-10-15（用户要求「蓝图为每一个子目标设定工具，比如证明就用 lean」）
#   工具指派的**兑现层**：把蓝图在节点上声明的 `tool` 变成真正的机器核验。
# ============================================================
# 背景：声明本身只是数据（`BlueprintNode.tool` → `sg["tool"]`），
#   `prompt/工具指令` 只保证模型**产出对应形态**；本组函数负责**真跑一次工具**：
#     lean    → 本文件 `_lean_block_verify`（本地 Lean 4 实编译，子目标级**首个**入口）
#     sympy   → `_sympy_verify_pairs`（SymPy 判等式真伪）
#     numeric → 既有 `_numeric_lean_verify`（Lean norm_num / ring）
#     llm     → 无机器核验（默认叙述路径）
# 失败一律**反馈给模型重解一次**（与 S1-lite 同口径），绝不直接丢弃结果 ——
#   本项目铁律：校验失败要带反馈修正，不是把对的改错。
_LEAN_FENCE_RE = re.compile(r"```lean\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# 签名尾部占位证明：`:= by sorry` / `:= sorry` / `by sorry`（宽容匹配）
_SIG_SORRY_TAIL_RE = re.compile(
    r"(?::=)?\s*(?:by\s+)?sorry\s*[.\s]*$", re.IGNORECASE)
# 完整 Lean 声明的标志（模型已自行写全 ⇒ 不再拼接签名）
_LEAN_DECL_RE = re.compile(
    r"^\s*(?:import|theorem|lemma|example|def|abbrev|instance|namespace|open|"
    r"section|variable)\b", re.MULTILINE)


def _compose_formal_sig(formal_sig: str, code: str) -> str:
    """把蓝图给的**签名**与求解侧给出的**证明体**拼成可编译的 Lean 代码。

    背景（2026-10-15，用户：「把 lean 内化到蓝图构建里面」）：
      蓝图在 `tool=lean` 的叶子上给出 `formal_sig`（形如
      `example : (2:ℕ)^10 = 1024 := by sorry`），求解环节按指令把 `sorry`
      换成证明脚本。但模型的输出形态不唯一，两种都要能编译：

      ① 回**完整声明**（`example … := by norm_num`）—— 直接原样返回；
      ② 只回**证明体**（如 `norm_num` 或几行 tactic）—— 与签名拼成
         `example … := by <证明体>`。

    判定：「代码里是否已有 Lean 声明/导入关键字」（`_LEAN_DECL_RE`）——
      · 有 ⇒ 形态 ①，原样返回，**绝不重复拼接**（否则会出现两个声明）；
      · 无 ⇒ 形态 ②，剥掉签名尾部的 `sorry` 占位后拼接。

    ⚠ 任何异常 / 空签名一律返回原 `code`（**静默回落**，绝不阻断编译）。
    """
    if not formal_sig or not code:
        return code
    try:
        if _LEAN_DECL_RE.search(code):
            return code
        head = _SIG_SORRY_TAIL_RE.sub("", formal_sig).rstrip()
        if not head:
            return code
        body = "\n".join("  " + ln if ln.strip() else ln
                         for ln in code.replace("\r\n", "\n").split("\n"))
        if head.endswith(":="):
            return head + " by\n" + body
        return head + " := by\n" + body
    except Exception:  # noqa: BLE001  拼接失败 ≠ 本步出错 → 回落原代码
        return code


# ---------------------------------------------------------------------------
# 形式签名三道门的生产接线（2026-11-04 E31）
# 契约层只给判定，不给放行；这里是把判定接到「能不能写 pass」的唯一写点。
# ★ 不设开关：没有影子/真判的切换项，判定结果直接进闭合准入。
# ---------------------------------------------------------------------------
def _sig_of(sg) -> str:
    return str((sg or {}).get("formal_sig") or "").strip()


def _init_sig_gate(sg) -> None:
    """tool=lean 且有签名 ⇒ 先落「形态 + 门 B」判定；未过者不准写 pass。

    ★ 无签名时闸门**不适用**：该子目标走「求解侧自写整段 Lean」的旧路径，
      不写 `sig_gate_allowed`，保持原有工具级闭合口径 —— 闸门只管「蓝图
      声称已形式化」的那批，不把别处真跑过的工具也一起否掉。
    """
    sig = _sig_of(sg)
    if not sig or not isinstance(sg, dict):
        return
    try:
        from contracts.formal_sig_gate import evaluate, gate_fields
        sg.update(gate_fields(evaluate(sig)))
    except Exception:  # noqa: BLE001  契约层不可用 ⇒ 显式否决，绝不静默放行
        sg["sig_gate_allowed"] = False
        sg["sig_gate_stage"] = "UNAVAILABLE"
        sg["sig_gate_reasons"] = ["契约层门禁不可用"]


def _verdict_text_of(sg) -> str:
    """从已落盘字段重建 `tool_verdict` 文本（不重算判定，避免口径漂移）。"""
    try:
        from contracts.formal_sig_gate import verdict_text
        return verdict_text({
            "stage": sg.get("sig_gate_stage", "UNAVAILABLE"),
            "allowed": sg.get("sig_gate_allowed", False),
            "reasons": sg.get("sig_gate_reasons", []),
            "prop": sg.get("sig_gate_prop", ""),
        })
    except Exception:  # noqa: BLE001
        return "unknown: sig_gate=UNAVAILABLE"


def _commit_sig_gate(sg, sig, compile_result, proof_code) -> None:
    """门 A + 门 C 有结果后，三道门合成并落盘（唯一写点）。"""
    if not isinstance(sg, dict) or not sig:
        return
    try:
        from contracts.formal_sig_gate import evaluate, gate_fields
        sg.update(gate_fields(evaluate(sig, compile_result, proof_code)))
    except Exception:  # noqa: BLE001
        sg["sig_gate_allowed"] = False
        sg["sig_gate_stage"] = "UNAVAILABLE"
        sg["sig_gate_reasons"] = ["契约层门禁不可用"]


def _compile_stated(bridge, work_dir, sig, fname):
    """门 A：保留 `:= by sorry` 原样编译，只判命题能否被 elaborate。

    返回 ``(returncode, full_err)``；编译器不可用 ⇒ None ⇒ `evaluate()` 记
    UNVERIFIED（没验 ≠ 验过）。★ 与 `classify_stated` 的输入口径一致，
    不复用「把 sorry 换成自动策略」那张床的分类函数。
    """
    if not sig:
        return None
    try:
        from tools.lean_local.lean_bridge import (
            _prepend_mathlib_import, _trash_lean_file)
        code = sig
        try:
            if bridge._mathlib_ready():
                code = _prepend_mathlib_import(sig)
        except Exception:  # noqa: BLE001
            pass
        r = bridge._compile(code, work_dir, lean_filename=fname,
                            allow_sorry=True)
        try:
            _trash_lean_file(work_dir, fname)
        except Exception:  # noqa: BLE001
            pass
        if not isinstance(r, dict):
            return None
        return (0 if r.get("ok") else 1, str(r.get("error") or ""))
    except Exception:  # noqa: BLE001
        return None


def _tool_declared_verify(self, ctx: TaskContext, sg: dict, result: str) -> str:
    """按蓝图声明的 `tool` 跑一次机器核验，返回反馈文本（空=通过/未执行/放行）。

    返回空串（**静默放行**，不产生额外开销）的情形：
      ① 开关 `blueprint_tool_exec` 关闭；② 本步结果为空 / 已是失败标记 / 时间到；
      ③ `tool` 为空或 `llm`（默认叙述路径，本就无机器核验）；
      ④ 本步没产出该工具可消费的形态（没写 lean 块 / 没写等式断言）；
      ⑤ 该工具在本机不可用（无本地 Lean / 无 SymPy）或已达每题核验上限。

    ★ 可观测：顺带把 `sg["tool_ran"]` / `sg["tool_verdict"]` 写回本子目标
      （`tool_verdict`：""=未声明或未执行；"pass"=有可核验形态且未报失败
      ——**含工具不可用时的静默放行**；"fail"=工具确实报了失败）。
    """
    def _mark(ran: bool, failed: bool) -> None:
        try:
            sg["tool_ran"] = bool(ran)
            # ★ E31 真判：三道门否决优先于「工具说通过」。带 sorry 的证明
            #   编译能通过、工具也会报成功，只有这里能把它挡在 pass 之外。
            if sg.get("sig_gate_allowed") is False:
                sg["tool_verdict"] = _verdict_text_of(sg)
            else:
                sg["tool_verdict"] = "fail" if failed else ("pass" if ran else "")
        except Exception:  # noqa: BLE001  可观测字段写失败不影响主流程
            pass

    try:
        if not POLICY['blueprint_tool_exec']:
            _mark(False, False)
            return ""
    except Exception:  # noqa: BLE001
        pass
    if not result or str(result).startswith("[子目标") or ctx.gen_time_up():
        _mark(False, False)
        return ""
    tool = str((sg or {}).get("tool") or "").strip().lower()
    if not tool or tool == "llm":
        _mark(False, False)
        return ""
    if tool == "numeric":
        if not self._extract_lean_assert_pairs(result):
            _mark(False, False)
            return ""
        # ★ 2026-10-15（审核修复 F5）：开关关 = **未核验**（≠ pass）——原实现
        #   无论是否真跑都 _mark(True, ...) ⇒ "没跑"被标成 pass（假信号）。
        if not POLICY['enable_numeric_lean_verify']:
            _mark(False, False)
            return ""
        _meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        _cnt0 = int(_meta.get("numeric_lean_count", 0) or 0)
        _fb = self._numeric_lean_verify(ctx, result)
        _meta2 = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        _cnt1 = int(_meta2.get("numeric_lean_count", 0) or 0)
        _did = _cnt1 > _cnt0        # 计数未增 = 未实际执行（时间到/超上限/桥不可用）
        _mark(_did, bool(_fb) if _did else False)
        return _fb
    if tool == "sympy":
        if not self._extract_check_asserts(result):
            # 结论契约行 `本步结论: 等式 = L = R` 也算可核验形态
            m = re.search(r"本步结论:\s*等式\s*=\s*(.+)", str(result or ""))
            if not m:
                _mark(False, False)
                return ""
            if len([p for p in m.group(1).split("=") if p.strip()]) != 2:
                _mark(False, False)
                return ""
        _fb = _sympy_verify_pairs(self, result)
        _mark(True, bool(_fb))
        return _fb
    if tool == "lean":
        # ★ E31：先落「形态 + 门 B」判定，后续由 _lean_block_verify 用
        #   门 A（可陈述编译）与门 C（证明凭证）覆盖成最终 verdict。
        _init_sig_gate(sg)
        if not _LEAN_FENCE_RE.search(str(result or "")):
            _mark(False, False)
            return ""
        # ★ 2026-10-15（审核 F6）：环境不可用等「未真跑」⇒ tool_ran=False
        #   （不再把"没核验"标成 pass —— 同 F5 口径）。
        try:
            sg.pop("tool_not_run_reason", None)
        except Exception:  # noqa: BLE001
            pass
        _fb = _lean_block_verify(self, ctx, result, sg)
        _ran = not bool(sg.get("tool_not_run_reason"))
        _mark(_ran, bool(_fb) if _ran else False)
        return _fb
    _mark(False, False)
    return ""


def _sympy_verify_pairs(self, result: str) -> str:
    """SymPy 核验本步的等式断言（tool=sympy 的兑现）。返回反馈；空=通过/无可验。

    断言来源（两处，按优先级）：
      ① `<check>L = R</check>`（`_extract_check_asserts`）
      ② 结论契约行 `本步结论: 等式 = L = R`
    ★ 只把 `_sympy_judge` 判为 **fail** 的算问题 —— `unknown`（含赋值式
      `x = 5`）按该函数既定的防误报红线一律放行，绝不据此打回。
    """
    pairs = list(self._extract_check_asserts(result) or [])
    if not pairs:
        m = re.search(r"本步结论:\s*等式\s*=\s*(.+)", str(result or ""))
        if m:
            parts = [p.strip() for p in m.group(1).strip().split("=")]
            if len(parts) == 2 and parts[0] and parts[1]:
                pairs = [(parts[0], parts[1])]
    if not pairs:
        return ""
    bad = []
    for L, R in pairs[:4]:
        try:
            verdict, info = self._sympy_judge(L, R)
        except Exception:  # noqa: BLE001  判定异常 → 放行，不误伤
            continue
        if verdict == "fail":
            bad.append("「%s = %s」%s" % (L, R, "（%s）" % info if info else ""))
    if not bad:
        return ""
    return ("【SymPy 符号核验未通过】蓝图把本步指派为符号计算，以下等式经 SymPy "
            "判定**不成立**，请重新推导并修正后给出【本步结果】："
            + "；".join(bad) + "。"
            "（若该式本就是本步求得的赋值结果而非恒等断言，请改写成恒等式或"
            "直接说明结论，不要用等式断言的形式声明它）")


def _lean_block_verify(self, ctx: TaskContext, result: str,
                       sg: dict | None = None) -> str:
    """编译本步产出的 ```lean 代码块（tool=lean 的兑现）。返回反馈；空=通过/放行。

    ★ 这是子目标级 Lean 验证的**首个入口**：此前 Lean 只在 4.3 整题/候选级跑，
      子目标粒度上"声明用 Lean 证明"没有任何执行落点。

    ★★ 2026-10-15（用户：「把 lean 内化到蓝图构建里面」——叶子级形式化下传）：
      传入 `sg` 后，若该子目标带着蓝图给的 `formal_sig`，则**拼接后再编译** ——
      求解侧只回证明体（或回完整声明）都能编译（见 `_compose_formal_sig`）。
      同时补上 **Mathlib import 归一化**：模型惯写 `import Mathlib.Tactic`，而本机
      Mathlib 是**部分编译布局**（无聚合入口 olean）⇒ 不归一化必然编译失败
      （此前 `_mathlib_ready()` 在本机恒 False 掩盖了该缺口，见 lean_bridge__env）。

    三重静默放行（缺任一即返回 ""，绝不误伤正常结果）：
      · 本机无 Lean（`bridge.lean_available` 为假，平台侧常见）；
      · 本步没产出 `lean` 代码块（模型判定为"无法形式化"，见工具指令第 3 条）；
      · 每题编译次数达上限（`blueprint_lean_max_per_q`，默认 2）—— 防止证明类
        子目标密集时把单题预算烧在编译器上。
    ⚠ `allow_sorry=True`（与既有 `_numeric_lean_verify` 同口径）：`sorry` 只作
      警告、不当错误，避免因模型写了 `by sorry` 就把本步整段否掉 —— 真正要拦的
      是**语法/类型/战术失败**这类硬错误。
    """
    blocks = _LEAN_FENCE_RE.findall(str(result or ""))
    if not blocks:
        return ""
    code = "\n".join(blocks).strip()
    _sig = _sig_of(sg)
    # ★ 2026-10-15：与蓝图签名拼接（求解侧只回证明体时也能成完整声明）
    code = _compose_formal_sig(_sig, code)
    # ★ 2026-11-04（E31）门 C 改为**真判**：`_compose_formal_sig` 已剥掉
    #   签名尾部的 `:= by sorry`，最终 code 里再出现 sorry 只可能来自求解侧
    #   证明体 ⇒ 由 `_commit_sig_gate` 里的 `proof_credential` 判掉，
    #   再由外层 `_mark` 拒绝写 pass。这里不再单独留影子字段。
    if not code or len(code) > 8000:
        return ""
    meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    cnt = int(meta.get("sg_lean_count", 0) or 0)
    cap = max(1, int(getattr(self.config, "blueprint_lean_max_per_q", 2) or 2))
    if cnt >= cap:
        if isinstance(sg, dict):
            sg["tool_not_run_reason"] = "lean-cap"
        return ""
    try:
        from tools.lean_local.lean_bridge import LeanBridge
        from tools.lean_local.lean_bridge import _trash_lean_file
    except Exception:  # noqa: BLE001
        if isinstance(sg, dict):
            sg["tool_not_run_reason"] = "lean-bridge-import"
        return ""
    try:
        bridge = LeanBridge(self.client, self.config)
    except Exception:  # noqa: BLE001
        if isinstance(sg, dict):
            sg["tool_not_run_reason"] = "lean-bridge-init"
        return ""
    if not getattr(bridge, "lean_available", False):
        # ★ 2026-10-15（审核 F6）：环境不可用 = **未核验**（≠ pass）——
        #   打标记供外层 _mark 判「未跑」，不再静默标 pass。
        if isinstance(sg, dict):
            sg["tool_not_run_reason"] = "lean-unavailable"
        return ""
    work_dir = getattr(bridge, "_lean_project_dir", "") or ""
    if not work_dir:
        if isinstance(sg, dict):
            sg["tool_not_run_reason"] = "lean-no-workdir"
        return ""
    # 带签名时本步要跑两次编译（门 A 判命题、主编译判证明）⇒ 计数同步 +2，
    # 让 `blueprint_lean_max_per_q` 的上限仍然管得住真实开销。
    meta["sg_lean_count"] = cnt + (2 if _sig else 1)
    fname = "sglean_%d_%d.lean" % (os.getpid(),
                                   int(time.time() * 1000) % 1000000)
    fname_sig = "sgstated_%d_%d.lean" % (os.getpid(),
                                         int(time.time() * 1000) % 1000000)
    # ★ 2026-10-15：Mathlib import 归一化 —— 模型惯写 `import Mathlib.Tactic`，
    #   而本机/部分编译布局下**没有**聚合入口 olean ⇒ 必须改写为可用的具体模块
    #   导入集（`CORE_MATHLIB_IMPORTS`），否则本步必然编译失败。
    #   守卫与 `LeanBridge.verify*` 一致：仅当 Mathlib 就绪时才归一化。
    try:
        from tools.lean_local.lean_bridge import _prepend_mathlib_import
        if bridge._mathlib_ready():
            code = _prepend_mathlib_import(code)
    except Exception:  # noqa: BLE001  归一化不可用 → 用原代码（不阻断）
        pass
    # ★ E31 门 A：签名**原样**编译（保留 := by sorry），只判命题可陈述。
    #   与主编译分开跑，绝不把「策略不够」和「命题写不出」混成一类。
    _stated = _compile_stated(bridge, work_dir, _sig, fname_sig)
    try:
        r = bridge._compile(code, work_dir, lean_filename=fname,
                            allow_sorry=True)
    except Exception:  # noqa: BLE001  编译器异常 ≠ 本步出错 → 放行
        _commit_sig_gate(sg, _sig, _stated, code)
        return ""
    finally:
        try:
            _trash_lean_file(work_dir, fname)
        except Exception:  # noqa: BLE001
            pass
    # ★ E31 三道门合成：门 A 的编译结果 + 门 C 的最终代码，一次写进闭合准入。
    #   compile_result 为 None（Lean 不可用）⇒ UNVERIFIED ⇒ 不认，绝不静默放行。
    _commit_sig_gate(sg, _sig, _stated, code)
    if not r or r.get("ok"):
        return ""
    err_text = str(r.get("error", "") or "")
    msgs = []
    for m in re.finditer(r":(\d+):(\d+):\s*error:\s*([^\n]*)", err_text):
        line = "第 %s 行：%s" % (m.group(1), m.group(3).strip()[:160])
        if line not in msgs:
            msgs.append(line)
    if not msgs:
        return ""      # 无结构化 error 行 ⇒ 视为环境噪声，放行
    return ("【Lean 编译未通过】蓝图把本步指派为形式化证明，你给出的 Lean 代码"
            "在本机编译器上未能通过，请修正后重新给出【本步结果】："
            + "；".join(msgs[:3]) + "。"
            "（若本步命题确实无法形式化，请按工具指令写明「本步无法形式化：原因」"
            "并给出普通数学证明，不要反复提交编译不过的代码）")
