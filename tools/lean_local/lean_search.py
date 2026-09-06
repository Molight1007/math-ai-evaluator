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

import json
import logging
import os
import re
import time

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

# LeanSearch v2 官方开源语料（非形式化描述 JSONL，gzip）的仓库内默认路径。
# 2026-08-31：平台无外网 → 官方 API 失效；语料 50MB gzip 随仓库走，
# 离线 BM25 级检索（非形式化描述），零 GPU、零外网。
# 来源：https://huggingface.co/datasets/FrenzyMath/lsv2-mathlib-v4.28.0-rc1-jsonl
#       （Apache 2.0；Mathlib v4.28.0-rc1 全量声明 310579 条，100% 带描述）
_CORPUS_PATH_CANDIDATES = (
    "data/lsv2/lsv2-mathlib-v4.28.0-rc1.jsonl.gz",
    "data/lsv2/lsv2-mathlib-v4.28.0-rc1.jsonl",
    "deploy/lsv2-mathlib-v4.28.0-rc1.jsonl.gz",
)

# 语料中保留的 user-facing 声明类型（丢弃 constructor/recursor 等编译器产物）
_CORPUS_KEEP_KINDS = {"theorem", "definition", "instance",
                      "abbrev", "opaque", "axiom"}

# ----------------------------------------------------------------------
# 查询规范化（2026-08-29 修复"中文/LaTeX 查询返回空"）
# ----------------------------------------------------------------------
# 关键词打分器只认 mathlib 风格的英文标识符；子目标求解传进来的却是
# 中文/LaTeX 自然语言 → tokenize 后要么为空要么全是无关词，命中率为 0。
# 这里做规则映射（零 LLM 成本）：把常见 LaTeX 指令与中文数学术语替换为
# 英文关键词，让打分器真正有机会命中。注意分词器要求 token ≥3 字符，
# 所以关键词一律 >=3（如 nonneg/less/greater 而非 ge/le）。
_QUERY_REWRITES = [
    # --- LaTeX 指令 ---
    (r"\\geq\b", " nonneg greater "), (r"\s>=\s*", " greater "),
    (r"\\leq\b|\\le\b", " less "), (r"\s<=\s*", " less "),
    (r"\\neq\b", " not_eq "), (r"\\ne\b", " not_eq "),
    (r"\\sum\b", " sum "), (r"\\prod\b", " product "),
    (r"\\int\b", " integral "), (r"\\frac\b", " div "),
    (r"\\sqrt\b", " sqrt "), (r"\\cdot\b|\\times\b", " mul "),
    (r"\\in\b", " mem "), (r"\\infty\b", " infinity "),
    (r"(\w)\^2\b", r"\1 sq "), (r"(\w)\^\{?(\d+)\}?", r"\1 pow \2 "),
    # --- 中文数学术语（映射到 mathlib 常见标识符片段）---
    ("整除", " divides dvd "), ("素数", " prime "), ("质数", " prime "),
    ("奇数", " odd "), ("偶数", " even "),
    ("不等式", " inequality "), ("证明", " prove "),
    ("求和", " sum "), ("积分", " integral "), ("极限", " limit "),
    ("导数", " derivative "), ("多项式", " polynomial "),
    ("矩阵", " matrix "), ("集合", " set "), ("子集", " subset "),
    ("实数", " real "), ("整数", " integer "), ("自然数", " nat "),
    ("复数", " complex "), ("有理数", " rational "),
    ("函数", " function "), ("方程", " equation "), ("三角", " trig "),
    ("对数", " log "), ("指数", " exp "), ("模", " mod "),
    ("同余", " congruent "), ("最大公约", " gcd "), ("最小公倍", " lcm "),
    ("平方", " sq "), ("非负", " nonneg "), ("正数", " positive "),
    ("负数", " negative "), ("严格", " strict "),
]

# 过泛词：命中它们不代表相关（real/integer 会命中一堆无关定理）
_WEAK_KEYWORDS = frozenset({
    "real", "integer", "int", "nat", "complex", "rational",
    "set", "subset", "function", "equation", "matrix",
    "mem", "div", "log", "exp", "mod", "sum", "product", "limit",
})


def normalize_query(query: str) -> tuple[str, list[str]]:
    """把中文/LaTeX 查询规范化为 mathlib 风格英文关键词串（纯规则，零成本）。

    返回 (augmented_query, strong_tokens)：
    - augmented_query：可送入 tokenizer 的增强串
    - strong_tokens：映射产生的**强信号词**（prime/sq/gcd 等），
      检索方只保留命中这些词的结果，把"real/integer"这类泛词造成的
      噪声命中直接滤掉（2026-08-29 实测：无过滤时 real 命中一堆无关定理）。
    """
    if not query:
        return "", []
    out = " " + query + " "
    strong: list[str] = []
    for pat, repl in _QUERY_REWRITES:
        hit = re.sub(pat, repl, out, flags=re.IGNORECASE)
        if hit != out:
            out = hit
            # 提取替换词里的"强信号"（剔除过泛词）
            for w in re.findall(r"[A-Za-z]{3,}", repl):
                if w not in _WEAK_KEYWORDS:
                    strong.append(w)
    return out, sorted(set(strong))


# ------------------------------------------------------------------
# #44 定理调用埋点（2026-08-30）
# ------------------------------------------------------------------
class TheoremCallStats:
    """定理检索调用埋点收集器（老师要求 #44）。

    老师原话：核实是否「调用次数频繁但调用的定理个数并不多」。
    因此埋点必须能回答四个问题，缺一不可：

    ==========  ======================================================
    维度        含义
    ==========  ======================================================
    calls       调用次数
    hits        命中条数（检索返回的原始结果数，累加）
    unique      去重后条数（按定理全名去重，跨调用累计）
    adopted     最终被采用条数（定理真正进入证明时由上层回记）
    ==========  ======================================================

    同时记录分后端调用次数、空结果次数、累计耗时，用于回答 #40
    「定理检索的开销与有效性」。

    落盘为 JSONL（每行一个事件 + 末尾一行汇总），便于离线聚合：
    ``tools/`` 下脚本可直接按题统计漏斗。
    """

    def __init__(self, storage_path: str = ""):
        self.storage_path = storage_path
        self.calls = 0                      # 调用次数
        self.hits = 0                       # 命中条数（累加）
        self.empty_calls = 0                # 空结果调用次数
        self.total_ms = 0.0                 # 累计耗时（毫秒）
        self.unique_names: set[str] = set()  # 去重后定理名
        self.adopted_names: set[str] = set()  # 最终被采用定理名
        self._by_backend: dict[str, int] = {}
        self._events: list[dict] = []

    # -- 写入侧 -------------------------------------------------------
    def record(self, query: str, backend: str, results: list,
               elapsed_ms: float = 0.0) -> None:
        """记录一次检索调用。results 为归一化后的结果列表。"""
        self.calls += 1
        n = len(results or [])
        self.hits += n
        if n == 0:
            self.empty_calls += 1
        self.total_ms += max(0.0, float(elapsed_ms))
        self._by_backend[backend] = self._by_backend.get(backend, 0) + 1
        for r in results or []:
            name = (r or {}).get("name") or ""
            if name:
                self.unique_names.add(name)
        self._events.append({
            "type": "call", "query": (query or "")[:300], "backend": backend,
            "hits": n, "elapsed_ms": round(elapsed_ms, 1),
            "names": [(r or {}).get("name", "") for r in (results or [])][:20],
        })

    def note_adopted(self, names) -> None:
        """回记「最终被采用」的定理（#44 的第四维）。

        由上层在定理真正写入证明 / 通过 Lean 编译时调用；只接受名字，
        因为检索侧无法判断定理是否真的被用上。
        """
        if isinstance(names, str):
            names = [names]
        for n in names or []:
            if n:
                self.adopted_names.add(n)
        if names:
            self._events.append({"type": "adopted", "names": list(names)[:50]})

    # -- 读取侧 -------------------------------------------------------
    def summary(self) -> dict:
        """返回聚合统计（可 JSON 序列化）。"""
        return {
            "calls": self.calls,
            "hits": self.hits,
            "unique": len(self.unique_names),
            "adopted": len(self.adopted_names),
            "empty_calls": self.empty_calls,
            "total_ms": round(self.total_ms, 1),
            "avg_ms_per_call": round(self.total_ms / self.calls, 1) if self.calls else 0.0,
            "by_backend": dict(self._by_backend),
            # 核心比值：回答老师「调用频繁但定理个数不多」
            "hits_per_call": round(self.hits / self.calls, 2) if self.calls else 0.0,
            "unique_per_call": round(len(self.unique_names) / self.calls, 2) if self.calls else 0.0,
            "adopted_ratio": round(len(self.adopted_names) / max(1, len(self.unique_names)), 3),
        }

    def flush(self, path: str = "") -> bool:
        """把事件流与汇总写入 JSONL；失败返回 False（绝不抛异常阻断主流程）。"""
        target = path or self.storage_path
        if not target:
            return False
        try:
            with open(target, "a", encoding="utf-8") as fh:
                for ev in self._events:
                    fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
                fh.write(json.dumps({"type": "summary", **self.summary()},
                                    ensure_ascii=False) + "\n")
            self._events = []
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lean_search] 埋点落盘失败: %s", str(exc)[:120])
            return False


# 全局默认收集器：上层与测试可直接取用，无需逐层传参
_DEFAULT_STATS = TheoremCallStats()


def get_stats() -> TheoremCallStats:
    """返回全局默认埋点收集器（#44）。"""
    return _DEFAULT_STATS


class Lsv2Corpus:
    """LeanSearch v2 官方开源语料离线检索后端（2026-08-31）。

    语料 = 31 万条 Mathlib 声明的**非形式化自然语言描述**（Qwen3-32B 生成、
    Apache 2.0 开源）。平台无外网时官方 API 失效，语料 gzip（50MB）随仓库
    git clone 落盘，这里做轻量词法检索（informal_name×3 / 描述×2 /
    名称×1 / 签名×1 加权），零 GPU、零外网、零 LLM 调用。

    质量预期：词法检索 < 官方 API（embedding+reranker, nDCG@10=0.62），
    但远强于「本地源码扫描」（扫声明行、零语义），且是平台端唯一可选。
    """

    def __init__(self, path: str = ""):
        self._path = path or self._default_path()
        self._docs: list[dict] | None = None
        self._index: dict[str, list[tuple[int, int]]] | None = None

    # ------------------------------------------------------------------
    # 路径 / 可用性
    # ------------------------------------------------------------------
    @staticmethod
    def _default_path() -> str:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in _CORPUS_PATH_CANDIDATES:
            p = os.path.join(root, rel)
            if os.path.exists(p):
                return p
        return ""

    def available(self) -> bool:
        return bool(self._path and os.path.exists(self._path))

    def path(self) -> str:
        return self._path

    # ------------------------------------------------------------------
    # 加载（懒加载：首次 search 时解压 + 建索引，约 30-60s / 一次）
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self._docs is not None:
            return
        import gzip
        import json as _json
        opener = gzip.open if self._path.endswith(".gz") else open
        docs: list[dict] = []
        index: dict[str, list[tuple[int, int]]] = {}
        with opener(self._path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = _json.loads(line)
                except ValueError:
                    continue
                if d.get("kind") not in _CORPUS_KEEP_KINDS:
                    continue
                name_parts = d.get("name") or []
                mod_parts = d.get("module_name") or []
                short = name_parts[-1] if name_parts else ""
                full = ".".join([*mod_parts, *name_parts]) if mod_parts else short
                doc = {
                    "name": short,
                    "full": full,
                    "kind": d.get("kind", "theorem"),
                    "file": ".".join(mod_parts) if mod_parts else "",
                    "line": 0,
                    "informal_name": (d.get("informal_name") or "")[:120],
                    "informal_description": (d.get("informal_description") or "")[:400],
                    "signature": (d.get("signature") or "")[:200],
                }
                doc_id = len(docs)
                docs.append(doc)
                # 倒排索引：字段加权（informal_name 最重 → 名称 → 签名）
                seen: set[tuple[str, int]] = set()
                for text, weight in (
                        (doc["informal_name"], 3),
                        (doc["informal_description"], 2),
                        (doc["name"], 1),
                        (doc["signature"], 1)):
                    for t in _TOKEN_RE.findall(text or ""):
                        t = t.lower()
                        if len(t) >= 3 and t not in ("theorem", "lemma", "def"):
                            seen.add((t, weight))
                for t, w in seen:
                    index.setdefault(t, []).append((doc_id, w))
        self._docs = docs
        self._index = index
        logger.info("[lean_search] 语料加载完成：%d 条声明（%s）",
                    len(docs), self._path)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> dict:
        if not self.available():
            return {"status": "unavailable",
                    "reason": "语料文件不存在（%s）" % self._path,
                    "results": []}
        try:
            self._load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lean_search] 语料加载失败: %s", str(exc)[:120])
            return {"status": "unavailable", "reason": str(exc)[:200],
                    "results": []}

        tokens = [t for t in (MathlibTheoremSearcher._tokenize(query))]
        if not tokens:
            return {"status": "ok", "query": query, "root": self._path,
                    "results": [], "corpus": True}

        scores: dict[int, int] = {}
        for t in tokens:
            for doc_id, w in self._index.get(t, []):
                scores[doc_id] = scores.get(doc_id, 0) + w
        if not scores:
            return {"status": "ok", "query": query, "root": self._path,
                    "results": [], "corpus": True}

        # informal_name 命中额外加权（语义标题比正文更接近查询意图）
        tokens_low = set(tokens)
        for doc_id, doc in enumerate(self._docs):
            iname = (doc["informal_name"] or "").lower()
            if iname and any(t in iname for t in tokens_low):
                scores[doc_id] = scores.get(doc_id, 0) + 2

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:max(1, limit)]
        results = []
        for doc_id, _score in ranked:
            d = self._docs[doc_id]
            # meta：论文口径的"metadata"（kind + 签名 + 非形式化名），
            # 供 R3 filter 与注入使用；snippet 保留非形式化描述（易读）。
            results.append({
                "name": d["full"] or d["name"],
                "kind": d["kind"], "file": d["file"], "line": 0,
                "snippet": (d["informal_description"] or d["signature"])[:200],
                "meta": "%s | %s | %s" % (
                    d["kind"], d["full"] or d["name"],
                    (d["signature"] or d["informal_name"])[:140]),
            })
        return {"status": "ok", "query": query, "root": self._path,
                "results": results, "corpus": True}


class MathlibTheoremSearcher:
    """从本地 mathlib 源码检索与查询相关的定理/引理/定义（试用版）。"""

    def __init__(self, roots: list[str] | None = None, max_files: int = 4000,
                 use_official: bool = True,
                 api_url: str = "https://leansearch.net/search",
                 corpus_path: str = ""):
        self._roots = [r for r in (roots or _CANDIDATE_ROOTS) if r and os.path.isdir(r)]
        self._max_files = max(30, int(max_files))
        self._cache: list[dict] | None = None  # (name, kind, snippet, file, line)
        self._root_used: str = self._roots[0] if self._roots else ""
        # 官方语义搜索（2026-08-29）：优先官方 API，失败一次即降级本地（本次进程内）
        self._use_official = bool(use_official)
        self._api_url = api_url
        # 官方开源语料离线后端（2026-08-31）：平台无外网时的检索源
        self._corpus = Lsv2Corpus(corpus_path)
        # #44 埋点：默认挂全局收集器，便于跨调用累计「去重后条数」
        self.stats: TheoremCallStats = _DEFAULT_STATS

    # ------------------------------------------------------------------
    # 官方 LeanSearch API（语义检索，论文《A Semantic Search Engine for Mathlib4》）
    # ------------------------------------------------------------------
    def _official_search(self, query: str, limit: int = 5) -> dict | None:
        """调用官方语义搜索 API；成功返回归一化结果，失败/不可达返回 None。

        失败一次后 self._use_official=False（本次进程不再尝试，避免无外网
        平台每次检索白等 10s 超时）。
        """
        import json as _json
        import urllib.request as _ur
        try:
            payload = _json.dumps({"query": [query], "n_results": limit}).encode("utf-8")
            # 必须带浏览器 UA：服务器对默认 urllib UA 返回 403
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"),
            }
            req = _ur.Request(self._api_url, data=payload,
                              headers=headers, method="POST")
            with _ur.urlopen(req, timeout=10) as resp:
                raw = _json.loads(resp.read().decode("utf-8"))
            # 官方返回: [[{result: {module_name, kind, name, signature, ...}}]]
            items = raw[0] if raw and isinstance(raw, list) else []
            results = []
            for it in items:
                r = it.get("result") if isinstance(it, dict) else None
                if not r:
                    continue
                name_parts = r.get("name") or []
                mod_parts = r.get("module_name") or []
                short = name_parts[-1] if name_parts else ""
                full = ".".join([*mod_parts, *name_parts]) if mod_parts else short
                results.append({
                    "name": full or short,
                    "kind": r.get("kind", "theorem"),
                    "file": ".".join(mod_parts) if mod_parts else "",
                    "line": 0,
                    "snippet": (r.get("signature") or
                                r.get("informal_description") or "")[:200],
                })
            if results:
                return {"status": "ok", "query": query, "root": self._api_url,
                        "results": results[:limit], "official": True}
            return {"status": "ok", "query": query, "root": self._api_url,
                    "results": [], "official": True}
        except Exception as exc:  # noqa: BLE001
            logger.info("[lean_search] 官方 API 不可用，降级本地检索: %s", str(exc)[:120])
            self._use_official = False  # 本次进程不再重试
            return None

    # ------------------------------------------------------------------
    # 后端状态
    # ------------------------------------------------------------------
    def status(self) -> dict:
        """返回后端可用性与统计信息（供上层决定是否启用 leansearch）。"""
        if self._corpus.available():
            return {"available": True, "root": "corpus:" + self._corpus.path(),
                    "corpus": True, "indexed_declarations": 310579,
                    "official": self._use_official}
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
        """检索入口（#44 埋点包装层）。

        在原检索逻辑之外只做三件事：计时 → 记录埋点 → 原样返回。
        任何埋点异常都被吞掉，绝不因统计逻辑影响检索主流程。
        """
        t0 = time.perf_counter()
        try:
            res = self._search_impl(query, limit=limit)
        except Exception:  # noqa: BLE001
            # 埋点仍要记录这次失败调用，但异常照常上抛（不改变原语义）
            self._record(query, [], t0, backend="error")
            raise
        self._record(query, res.get("results") or [], t0,
                     backend=("official" if res.get("official")
                              else "corpus" if res.get("corpus") else "local"))
        return res

    def _record(self, query: str, results: list, t0: float, backend: str) -> None:
        """记录一次调用埋点；失败静默（统计不可靠也好过主流程中断）。"""
        try:
            self.stats.record(query, backend, results,
                              elapsed_ms=(time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[lean_search] 埋点记录失败（已忽略）: %s", str(exc)[:120])

    def _search_impl(self, query: str, limit: int = 5) -> dict:
        """检索与 query 相关的 Mathlib 定理/引理/定义（原 search 实现）。

        2026-08-29 升级：**官方 LeanSearch API 优先、本地关键词降级**。
        - 官方服务（leansearch.net，语义检索，论文《A Semantic Search Engine
          for Mathlib4》）质量远高于本地关键词打分器（实测 "gcd divides" →
          EuclideanDomain.gcd_dvd，带 signature/证明）。
        - 平台无外网/超时/异常 → 自动降级本地关键词（现状逻辑），不影响可用性。

        返回::
            {"status": "ok"|"unavailable", "query": str, "root": str,
             "results": [{"name","kind","file","line","snippet"}]}
        """
        # 优先级：官方 API（语义检索）→ 开源语料（离线非形式化检索）→ 源码扫描
        # 2026-08-31：平台无外网 → 官方 API 必失败 → 语料（仓库内 gzip）成为主力；
        #             本地有网 → 官方 API 优先，语料兜底。
        if getattr(self, "_use_official", True):
            sr = self._official_search(query, limit=limit)
            if sr is not None:
                return sr
            # 官方不可达 → 本次降级（不反复尝试，见 _official_search 内部标记）

        if self._corpus.available():
            cr = self._corpus.search(query, limit=limit)
            if cr.get("results"):
                return cr
            # 语料可用但零命中：继续走源码扫描（本地有 mathlib 时仍可能命中）

        if not self._roots:
            return {"status": "unavailable",
                    "reason": "未找到本地 mathlib 源码目录", "results": []}
        try:
            decls = self._load_declarations()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lean_search] 加载 mathlib 声明失败: %s", exc)
            return {"status": "unavailable", "reason": str(exc)[:200], "results": []}

        aug, strong = normalize_query(query)
        tokens = self._tokenize(aug)
        if not tokens:
            return {"status": "ok", "root": self._root_used, "results": []}

        # 强信号过滤（2026-08-29）：映射词（prime/sq/gcd 等）存在时，
        # 只保留名称/摘要命中强词的结果——噪声命中（real/integer 泛词）直接滤掉。
        scored: list[tuple[int, dict]] = []
        for d in decls:
            score = self._score(d, tokens)
            if score <= 0:
                continue
            if strong:
                name_low = d["name"].lower()
                snip_low = d["snippet"].lower()
                if not any(w in name_low or w in snip_low for w in strong):
                    continue
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
