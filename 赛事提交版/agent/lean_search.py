# -*- coding: utf-8 -*-
"""Mathlib 定理检索（leansearch 试用，#31）。

老师要求：求解子目标关键在定理的 Mathlib 搜索；以前给的 leansearch 是否需要用上，
**先试试再决定**。本模块即该「试用」的工程落地。

试用后端（零依赖、可直接跑）：
    - 本地源码扫描：扫描本地 mathlib4 源码树中的 theorem/lemma/def 声明，
      按查询词重叠度排序返回候选定理。无需外部索引服务，立刻可用。

升级路径（预留，暂未启用）：
    - LeanSearchClient 语义索引：若未来部署 leansearch 索引服务，可替换
      ``search()`` 内部后端为语义检索，接口不变。

设计原则：始终安全降级——后端不可用 / 检索异常时返回 ``status="unavailable"``，
绝不向上抛异常阻断主流程。
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("MathPilot")

# 候选 mathlib 源码根目录（按机器实际位置探测）
_CANDIDATE_ROOTS = [
    "D:/mathlib4-last_bump_for_v4.31.0",
    "D:/mathlib4-last_bump_for_v4.31.0/Mathlib",
    "/mathlib4-last_bump_for_v4.31.0",
    "D:/挑战杯/lean下载版/test_mathlib/Mathlib",
    "D:/挑战杯/lean下载版/test_mathlib",
]

# 声明行匹配：theorem / lemma / def 开头，捕获 种类 + 名称
_DECL_HEAD = re.compile(
    r"^\s*(theorem|lemma|def)\s+([A-Za-z_][\w'.]*)")

# 终止一段声明的标志（出现则视为声明头结束）
_DECL_TERMINATORS = re.compile(
    r"^\s*(?:theorem|lemma|def|example|instance|class|structure|/-|import|open)\b")

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_'.]*")


class MathlibTheoremSearcher:
    """从本地 mathlib 源码检索与查询相关的定理/引理/定义（试用版）。"""

    def __init__(self, roots: list[str] | None = None, max_files: int = 4000):
        self._roots = [r for r in (roots or _CANDIDATE_ROOTS) if r and os.path.isdir(r)]
        self._max_files = max(30, int(max_files))
        self._cache: list[dict] | None = None  # (name, kind, snippet, file, line)
        self._root_used: str = self._roots[0] if self._roots else ""

    # ------------------------------------------------------------------
    # 后端状态
    # ------------------------------------------------------------------
    def status(self) -> dict:
        """返回后端可用性与统计信息（供上层决定是否启用 leansearch）。"""
        if not self._roots:
            return {"available": False, "reason": "未找到本地 mathlib 源码目录",
                    "candidate_roots": _CANDIDATE_ROOTS}
        decls = self._load_declarations()
        return {"available": True, "root": self._root_used,
                "indexed_declarations": len(decls)}

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> dict:
        """检索与 query 相关的 Mathlib 定理/引理/定义。

        返回::
            {"status": "ok"|"unavailable", "query": str, "root": str,
             "results": [{"name","kind","file","line","snippet"}]}

        - 后端不可用 / 异常 → status="unavailable"，results=[]（安全降级）。
        """
        if not self._roots:
            return {"status": "unavailable",
                    "reason": "未找到本地 mathlib 源码目录", "results": []}
        try:
            decls = self._load_declarations()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lean_search] 加载 mathlib 声明失败: %s", exc)
            return {"status": "unavailable", "reason": str(exc)[:200], "results": []}

        tokens = self._tokenize(query)
        if not tokens:
            return {"status": "ok", "root": self._root_used, "results": []}

        scored: list[tuple[int, dict]] = []
        for d in decls:
            score = self._score(d, tokens)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)

        results = [
            {"name": d["name"], "kind": d["kind"], "file": d["file"],
             "line": d["line"], "snippet": d["snippet"]}
            for _, d in scored[:max(1, int(limit))]
        ]
        return {"status": "ok", "root": self._root_used, "results": results}

    # ------------------------------------------------------------------
    # 内部：声明加载 + 评分
    # ------------------------------------------------------------------
    def _load_declarations(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        decls: list[dict] = []
        scanned = 0
        for root in self._roots:
            mathlib_dir = os.path.join(root, "Mathlib") if os.path.isdir(
                os.path.join(root, "Mathlib")) else root
            for dirpath, _dirs, files in os.walk(mathlib_dir):
                for fn in files:
                    if not fn.endswith(".lean"):
                        continue
                    if scanned >= self._max_files:
                        break
                    scanned += 1
                    self._collect_file(os.path.join(dirpath, fn), decls)
                if scanned >= self._max_files:
                    break
            if decls:  # 第一个能扫到声明的根即作为主源
                self._root_used = root
                break
        self._cache = decls
        logger.info("[lean_search] 已索引 %d 条 mathlib 声明（root=%s）",
                    len(decls), self._root_used)
        return decls

    def _collect_file(self, path: str, out: list[dict]) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except Exception:  # noqa: BLE001
            return
        i = 0
        n = len(lines)
        while i < n:
            m = _DECL_HEAD.match(lines[i])
            if not m:
                i += 1
                continue
            kind, name = m.group(1), m.group(2)
            # 拼接声明头，直到出现 := / where / 终止符 / 窗口上限
            snippet_parts = [lines[i].strip()]
            j = i + 1
            while j < n and j < i + 6:
                nxt = lines[j]
                if _DECL_TERMINATORS.match(nxt):
                    break
                snippet_parts.append(nxt.strip())
                low = nxt.lower()
                if ":=" in nxt or "where" in low:
                    break
                j += 1
            snippet = " ".join(p for p in snippet_parts if p)[:200]
            out.append({"name": name, "kind": kind,
                        "snippet": snippet, "file": path, "line": i + 1})
            i = j if j > i else i + 1

    @staticmethod
    def _tokenize(query: str) -> list[str]:
        toks = []
        for t in _TOKEN_RE.findall(query or ""):
            t = t.lower()
            if len(t) >= 3 and t not in ("theorem", "lemma", "def"):
                toks.append(t)
        return toks

    @staticmethod
    def _score(d: dict, tokens: list[str]) -> int:
        name_low = d["name"].lower()
        snip_low = d["snippet"].lower()
        score = 0
        for t in tokens:
            if t in name_low:
                score += 3
            elif t in snip_low:
                score += 1
        # 名称子串命中额外加权
        for t in tokens:
            if t and t in name_low:
                score += 1
        return score
