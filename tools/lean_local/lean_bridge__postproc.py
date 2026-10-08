"""桥接文本后处理工具（自 `tools/lean_local/lean_bridge.py` 逐字搬出）。

职责：注入 client 返回的归一化 / anti-hack 病理过滤 / Markdown 代码围栏剥离 /
编译错误输出截断与特征提示 / 错误分析 JSON 解析 / 最终答案锚定校验。

★ 2026-10-08 拆分（`lean_bridge.py` 上帝类拆分）：本模块由原文件**逐字搬出**，
  原文件改为 re-export（`from tools.lean_local.lean_bridge import X` 契约不变）。
  ★ 分层约束：本模块**零 `agent` 依赖**（不 import agent/*），
    不加深仓库已知的 tools→agent 倒置债务。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("MathPilot")


_MAX_ERROR_CHARS = 5000                # 编译错误输出截断上限（防 token 爆炸）


def _truncate_error_output(text: str, limit: int = _MAX_ERROR_CHARS) -> str:
    """截断编译错误输出，防止提示词 token 爆炸。

    2026-09-11 增强（用户要求"把错误情况完整汇报给大模型"）：
      原实现是粗暴的 ``text[:limit]`` —— 而 Lean 的**修复建议 `Try this: ...` 往往
      在输出末尾**，粗暴截断会把它丢掉（等于把最有价值的修正线索扔掉）。
      现改为：超限时优先保留 `error:` 行与 `Try this:` 建议行，构成精简版；
      精简版仍超限才二次截断。
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    keep = []
    for ln in text.splitlines():
        s = ln.strip()
        if ": error" in s or s.startswith("Try this") or "Try this:" in s:
            keep.append(s)
    if keep:
        compact = "\n".join(keep)
        if len(compact) <= limit:
            return (compact
                    + f"\n... [原文 {len(text)} 字符，已保留 error / Try this 关键行]")
        return compact[:limit] + "\n... [关键行亦超限，已截断]"
    return text[:limit] + "\n... [已截断，共 %d 字符]" % len(text)


# =====================================================================
# 桥接工具函数
# =====================================================================

def _normalize_bridge_response(resp: Any) -> str:
    """把注入 client 的返回统一成字符串（与 user_agent 归一化保持一致）。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, bytes):
        try:
            return resp.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    if isinstance(resp, dict):
        for key in ("content", "text", "output", "result"):
            if key in resp and resp[key]:
                return _normalize_bridge_response(resp[key])
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            choice = resp["choices"][0]
            if isinstance(choice, dict):
                if "message" in choice:
                    return _normalize_bridge_response(choice["message"])
                if "text" in choice:
                    return str(choice["text"])
            return _normalize_bridge_response(choice)
        if "message" in resp:
            return _normalize_bridge_response(resp["message"])
        return ""
    for attr in ("content", "text", "response"):
        try:
            val = getattr(resp, attr, None)
            if val is not None:
                return _normalize_bridge_response(val)
        except Exception:  # noqa: BLE001
            pass
    try:
        s = str(resp)
        return s if s and s != "None" else ""
    except Exception:  # noqa: BLE001
        return ""


# =====================================================================
# Anti-hack 预处理（2026-09-01 SU-01 优化 1，论文 §3.3）
# ---------------------------------------------------------------------
# SU-01 在 refined RL 把「格式病理」输出替换为安全 fallback，防止模型靠
# 模板泄漏/重复等骗过验证器。MathPilot 等价物：翻译/分析阶段 LLM 输出
# 出现 chat-template token 泄漏、thinking 分隔符不平衡、严重重复时，
# 直接返回 fallback（后续 Lean 编译必失败，但显式失败好过垃圾进编译器）。
# 只影响 _llm_call 的统一出口，调用方行为可预期（编译失败 → 走错误路径）。
# =====================================================================
_SAFE_FALLBACK = "I cannot provide a solution due to generation pathology."

_CHAT_TEMPLATE_LEAK_PATS = [
    r"<\|im_start\|>", r"<\|im_end\|>", r"<\|im_sep\|>",
    r"<\|assistant\|>", r"<\|user\|>", r"<\|system\|>",
    r"<s>", r"</s>", r"<\|endoftext\|>",
    r"chat_template",
]


def _anti_hack_guard(text: str) -> str:
    """SU-01 §3.3 三检查：chat-template 泄漏 / thinking 分隔符不平衡 / 严重重复。

    命中任一 → 返回 _SAFE_FALLBACK；正常文本原样返回。
    """
    if not text:
        return text
    # 1) chat-template token 泄漏（模型吐出了模板而非内容）
    if any(re.search(p, text) for p in _CHAT_TEMPLATE_LEAK_PATS):
        logger.warning("[LeanBridge] anti-hack: chat-template 泄漏 → fallback")
        return _SAFE_FALLBACK
    # 2) thinking 分隔符不平衡（prefill 已抑制思维块；出现即病理）
    if text.count("<thinking>") != text.count("</thinking>"):
        logger.warning(
            "[LeanBridge] anti-hack: thinking 分隔符不平衡 "
            "(open=%d close=%d) → fallback",
            text.count("<thinking>"), text.count("</thinking>"),
        )
        return _SAFE_FALLBACK
    # 3) 严重重复：≥12 行文本中，同一行出现 ≥50% 次数
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 12:
        from collections import Counter
        top_line, top_cnt = Counter(lines).most_common(1)[0]
        if top_cnt >= len(lines) * 0.5:
            logger.warning(
                "[LeanBridge] anti-hack: 严重重复 (line=%r x%d) → fallback",
                top_line[:40], top_cnt,
            )
            return _SAFE_FALLBACK
    return text


def _strip_code_fence(text: str) -> str:
    """去除 LLM 返回的 Markdown 代码围栏（```lean ... ```），只保留代码体。"""
    if not text:
        return ""
    m = re.search(r"```(?:lean)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def hint_for_compile_error(err: str) -> str:
    """按 Lean 编译器错误的**文本特征**给出具体可执行的修法（确定性，不依赖 LLM）。

    2026-09-12 新增（实测驱动）：Lean 通道的三个落点（2.6 前置形式化 / 3.6 候选
    淘汰 / 6.5 最终闸门）此前都把"编译器能给的精确错误"降级成 LLM 的概括话术，
    模型拿到后不知道改哪一行。实测 2.6 在 3 题上「2 轮重试 0 成功」的根因即此：
    真实错误是 `Set.Fintype.card` 这个 API 不存在、以及把"值当类型"用，而反馈却
    让模型「重新审题」。

    返回空串 = 未识别出特征（调用方自行兜底），因此可安全叠加到既有描述之后。
    """
    e = (err or "").lower()
    if not e:
        return ""
    if ("unknown identifier" in e or "unknown constant" in e
            or "unknown namespace" in e or "unknown declaration" in e
            or "unknown theorem" in e):
        m = re.search(
            r"unknown\s+(?:identifier|constant|namespace|declaration|theorem|"
            r"axiom)[^A-Za-z0-9_]*([A-Za-z_][A-Za-z0-9_.]*)", err)
        name = (m.group(1) if m else "")
        if "." in name:
            return ("**未知标识符**：`%s` 在 Mathlib 中不存在。这是 **API 名**，请改用"
                    "等价的标准名称——例如「集合的元素个数」应写 `Set.ncard` / "
                    "`Finset.card`（**没有 `Set.Fintype.card` 这个名字**）。" % name)
        return ("**未知标识符**：`%s` 未定义。请先确认题目是否给出了该符号；若未给出，"
                "请改用 Mathlib 已有记号，或先用 `def`/`abbrev` 把它定义出来。"
                % (name or "该名字"))
    if "type mismatch" in e or "has type" in e or "expected to have type" in e:
        return ("**类型不匹配**：Lean 里**值不是类型**。`def n : Nat := 2025` 定义的是"
                "**值**，不能当类型用——表示 n 个元素请用 `Fin n`，例如 "
                "`Finset (Fin 2025 × Fin 2025)`。数值字面量出现在需要 `Prop` 的位置"
                "也不可用，请显式标注类型（如 `(19 : ℕ)`）。")
    if ("expected" in e or "unexpected token" in e or "invalid syntax" in e
            or "line break" in e or "unknown token" in e):
        return ("**语法错误**：① theorem 的**结论位不能直接写 `let ... in`**——请把结论"
                "写成明确的命题，中间定义放进 `by` 块用 `have`/`let`；② 集合字面量 "
                "`{x | P x}` **必须先声明类型**（如 `(S : Set ℕ) := {x | ...}`），"
                "不能直接接 `.card`。")
    if "failed to synthesize" in e or "instance" in e:
        return ("**类型类实例推断失败**：多为类型标注缺失或用错。请为数值/集合显式标注"
                "类型，并确认结构具备所需实例（如 `Finset` 的元素类型需 "
                "`DecidableEq`）。")
    if "unknown module prefix" in e:
        return "**缺少模块导入**：请补上对应 `import`（如 `import Mathlib`）。"
    return ""


def _analyze_formal_gaps(compile_error: str) -> list:
    """从 Lean 形式化声明的编译错误中抽取结构化「缺口」（子目标候选）。

    用于题目前置形式化：编译失败往往说明 AI 对题意理解存在缺口
    （未定义的量/引理、类型不匹配、缺少模块导入等）。把这些缺口结构化，
    供 SubGoalSolver 直接转化为「需要先证明/补充什么」的子目标
    —— 即"根据 Lean 编译的逻辑，看缺哪些"。

    返回 ``list[dict]``，元素:
        {"kind": str, "detail": str, "suggestion": str}
    kind ∈ {"missing_definition","missing_lemma","missing_module",
            "type_mismatch","other"}
    """
    if not compile_error:
        return []
    # 2026-09-11（#13 前置验证修复）：先剔除 warning 行再抽取缺口。
    # 依据：112 题实测 019 —— 编译输出**仅有 linter warning**（变量未引用），
    # 却被兜底分支记成 gap（kind="other"），制造"假缺口"。warning 不构成
    # "题意理解缺口"，不应进入 gaps（也不应影响 fail/ok 判定）。
    compile_error = "\n".join(
        ln for ln in compile_error.splitlines()
        if ": warning:" not in ln and not ln.strip().startswith("warning:"))
    if not compile_error.strip():
        return []
    gaps: list = []
    seen = set()

    # 1) unknown identifier / declaration / theorem … → 缺失定义或引理
    # 2026-09-02 bug 修复：过滤英文介词/停用词（to/from/of/with…）——
    # LLM 翻译英文题面时把介词当 Lean 标识符，产生幽灵 missing_definition
    # （11 题全中 "missing_definition 'to'" 的噪声源），绝非真缺口。
    _EN_STOPWORDS = {
        "to", "from", "of", "with", "by", "for", "at", "in", "on", "into",
        "onto", "that", "which", "where", "when", "then", "than", "and",
        "or", "not", "the", "a", "an", "is", "are", "be", "we", "have",
        "such", "all", "any", "each", "if", "as", "so", "but", "also",
        "this", "these", "those", "there", "it", "its", "can", "will",
        "does", "do", "has", "what", "why", "how", "let", "define",
        "over", "under", "between", "about", "after", "before",
    }
    for m in re.finditer(
        r"unknown (?:identifier|declaration|theorem|constant|axiom)"
        r"\s*[:'\"\s]*([A-Za-z_][A-Za-z0-9_'.]*)",
        compile_error,
    ):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        # 英文介词/停用词 → 翻译噪声，跳过（不产生 gap）
        # 正则字符类含 ' 和 .，name 可能带尾部引号（如 to'）→ 先剥
        _core = name.strip("'\".")
        if _core in _EN_STOPWORDS or _core.lower() in _EN_STOPWORDS:
            continue
        # 启发式：首字母大写或含 '.' 多半是引理/定理；否则是定义/量
        is_lemma = name[0].isupper() or "." in name
        gaps.append({
            "kind": "missing_lemma" if is_lemma else "missing_definition",
            "detail": name,
            "suggestion": (
                "需要引用/先证明引理「%s」（可能题目未给出该结论，需作为子目标建立）"
                % name) if is_lemma else (
                "需要定义量/函数「%s」（检查题目是否给出该符号及其含义）" % name),
        })

    # 2) unknown module prefix → 缺失 import（如 Mathlib 未加载）
    for m in re.finditer(r"unknown module prefix '([^']+)'", compile_error):
        mod = m.group(1)
        if mod in seen:
            continue
        seen.add(mod)
        gaps.append({
            "kind": "missing_module",
            "detail": mod,
            "suggestion": "形式化缺少模块导入 `import %s`（需先建立该库依赖）" % mod,
        })

    # 3) type mismatch → 逻辑缺口（量/类型不兼容），取首处即可，避免噪声
    m = re.search(r"type mismatch", compile_error)
    if m:
        snippet = _truncate_error_output(compile_error[m.start():m.start() + 400], 300)
        gaps.append({
            "kind": "type_mismatch",
            "detail": snippet,
            "suggestion": "类型不匹配：对题意中量的类型/结构理解可能有误，需核对定义与已知条件的类型。",
        })

    # 4) 兜底：有错误但未命中以上模式 → 给一个通用缺口
    if not gaps:
        gaps.append({
            "kind": "other",
            "detail": _truncate_error_output(compile_error, 300),
            "suggestion": "形式化声明无法编译通过，需重新核对题意理解与符号定义。",
        })
    return gaps


def _parse_analysis_json(raw: str) -> Optional[dict]:
    """从 LLM 返回文本解析错误分析 JSON，失败返回 None。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _unwrap_answer(answer: str) -> str:
    """剥最终答案的 LaTeX 外壳（\\boxed{...} 可多层嵌套），露出数值核心。

    2026-09-07（#52 模板化）：LLM 最终答案常带 \\boxed{} / \\dfrac{} 壳，
    ``_answer_embedded`` 的纯数字 fullmatch 对带壳答案失效 → 壳下数字漏检，
    自证代码绕过锚定、到编译后 _cc 交叉核对才被拦（nt-093 答对 3000 却
    proof_invalid 实证）。先剥壳再核对，口径与 _cross_check 统一。
    """
    core = (answer or "").strip()
    for _ in range(5):
        m = re.fullmatch(r"\\boxed\{(.*)\}", core, re.S)
        if not m:
            break
        core = m.group(1).strip()
    return core


def _answer_embedded(lean_code: str, answer: str) -> bool:
    """校验书生生成的验证代码是否真正锚定了 USER 最终答案。

    防止「书生自己重算、无视 USER 最终答案」的假验证（验证自己算的结果
    而非审核答案）：
    - 先剥 \\boxed{} 壳（#52，2026-09-07）——带壳答案的壳下数字不再漏检；
    - 纯数字答案（含小数）：代码必须包含该数字原值（数字边界，防 3 匹配 13）；
    - 含字母 token 的答案（如 x=1、3n+1）：代码必须引用至少一个答案 token；
    - 其他形态（中文句里的数字、分数 LaTeX）：提取全部数字（排除 0/1/2
      通用小整数）→ 代码须含至少一个（数字边界）；无有效数字则退化 token 检查；
    - 纯中文/符号答案（无数字无 token）：无法代码侧校验，靠提示词 error
      路径兜底放行。
    """
    core = _unwrap_answer(answer)
    if not core:
        return False
    # 纯数字（整数/小数）→ 数字锚定（带边界，保留小值如 2 的精确检查）
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", core):
        pat = r"(?<![0-9])" + re.escape(core) + r"(?![0-9])"
        return re.search(pat, lean_code or "") is not None
    # ★ 2026-09-17（L2）：**分数答案专项锚定**。
    # 实测 official112-070 的候选 `\boxed{\frac{1}{2}}`：剥 boxed 后 core=`\frac{1}{2}`，
    # 而下方通用数字核对取出的集合是 {"1","2"} − {"0","1","2"} = **∅**（通用小整数被
    # 排除）⇒ 必然退化到 token 检查、而代码里没有 `frac` ⇒ 判「未锚定」
    # ⇒ 该题 2 条候选白走 `convert_to_lean_failed`。
    # 故对分数形态单独核对：代码须出现 `a/b`、`\frac{a}{b}` 或 `\dfrac{a}{b}`。
    _mf = (re.fullmatch(r"\\(?:d|t)?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", core)
           or re.fullmatch(r"([+-]?\d+)\s*/\s*([+-]?\d+)", core))
    if _mf:
        _a, _b2 = _mf.group(1).strip(), _mf.group(2).strip()
        _code = lean_code or ""
        for _form in ("%s/%s" % (_a, _b2),
                      "\\frac{%s}{%s}" % (_a, _b2),
                      "\\dfrac{%s}{%s}" % (_a, _b2),
                      "(%s/%s)" % (_a, _b2),
                      "%s / %s" % (_a, _b2)):
            if _form in _code:
                return True
        return False
    # 非纯数字形态：提取数字核对（排除 0/1/2 通用小整数的假匹配）
    ans_nums = set(re.findall(r"\d+", core)) - {"0", "1", "2"}
    if ans_nums:
        code = lean_code or ""
        for n in ans_nums:
            if re.search(r"(?<![0-9])" + re.escape(n) + r"(?![0-9])", code):
                return True
        return False
    # 含字母 token 的答案 → 代码必须引用至少一个答案 token
    ans_tokens = set(re.findall(r"[A-Za-z_]\w*", core))
    if ans_tokens:
        code_tokens = set(re.findall(r"[A-Za-z_]\w*", lean_code or ""))
        return bool(ans_tokens & code_tokens)
    # 纯中文/符号答案 → 无法校验，放行（靠提示词约束）
    return True
