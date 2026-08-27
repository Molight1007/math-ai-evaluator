# -*- coding: utf-8 -*-
"""Mathlib 离线定理检索器（leansearch 轻量版，不依赖网络 API）。

从 mathlib 源码提取 theorem/lemma/def 声明 → 索引（JSON 缓存）→
给定查询返回 top-k 定理（名字 + 类型签名 + 模块路径）。

供 LeanBridge 转化阶段注入 prompt，治 Intern-S2 不知道用哪个
Mathlib 定理/模块的问题（对应老师要求 #31 评估 leansearch 检索）。
"""
import json
import os
import re
import time

_DECL_RE = re.compile(
    r"\b(?:theorem|lemma|def)\s+([A-Za-z_][A-Za-z0-9_.']*)\s*"
    r"((?:.|\n)*?)(?=:=)",
    re.M)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*")  # 不含下划线：prime_two 拆成 prime/two


class MathlibRetriever:
    """Mathlib 定理检索器。索引懒加载（有缓存用缓存，无则构建）。"""

    def __init__(self, mathlib_dir: str, index_path: str = ""):
        self.mathlib_dir = mathlib_dir
        self.index_path = index_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs", "mathlib_index.json")
        self._docs: list = []
        self._loaded = False

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    def build_index(self, progress_every: int = 500) -> int:
        """扫描 mathlib 源码，提取声明。返回声明条数。"""
        t0 = time.time()
        docs = []
        n_files = 0
        for root, _, files in os.walk(self.mathlib_dir):
            for fn in files:
                if not fn.endswith(".lean"):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, self.mathlib_dir)
                if not rel.startswith("Mathlib"):
                    continue
                module = rel[:-5].replace("\\", ".").replace("/", ".")
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                n_files += 1
                for m in _DECL_RE.finditer(text):
                    name = m.group(1)
                    sig = re.sub(r"\s+", " ", m.group(2)).strip()
                    docs.append({
                        "name": name,
                        "sig": sig[:220],
                        "module": module,
                        "file": rel,
                    })
                if n_files % progress_every == 0:
                    print("  扫描 %d 文件，已提取 %d 条..." % (n_files, len(docs)),
                          flush=True)
        self._docs = docs
        self._loaded = True
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False)
        print("索引构建完成: %d 条声明 / %d 文件, %.1fs -> %s"
              % (len(docs), n_files, time.time() - t0, self.index_path))
        return len(docs)

    def load_index(self) -> None:
        if not self._loaded:
            if os.path.exists(self.index_path):
                try:
                    with open(self.index_path, encoding="utf-8") as f:
                        self._docs = json.load(f)
                    self._loaded = True
                    print("索引加载: %d 条 (%s)" % (len(self._docs), self.index_path))
                except Exception:
                    self.build_index()
            else:
                self.build_index()

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = 8) -> list:
        """给定查询（自然语言或 Lean 片段），返回 top-k 定理 dict。"""
        self.load_index()
        if not self._docs:
            return []
        q_words = set(_TOKEN_RE.findall(query.lower()))
        if not q_words:
            return []
        scored = []
        for d in self._docs:
            name = d["name"].lower()
            hay = (name + " " + d["sig"].lower())
            h_words = set(_TOKEN_RE.findall(hay))
            inter = q_words & h_words
            score = len(inter)
            # 名字命中权重高（Nat.prime_two 查询 "prime two" 命中名字）
            name_tokens = set(_TOKEN_RE.findall(name))
            name_hit = len(q_words & name_tokens)
            score += name_hit * 3
            # 名字覆盖全部查询词时：名字越短越相关（prime_two 优于长名字）
            if name_hit and name_hit >= len(q_words):
                score += 8 - len(name_tokens) * 0.3
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:k]]

    def format_results(self, results: list) -> str:
        """把检索结果格式化为注入 prompt 的文本。"""
        if not results:
            return ""
        lines = ["可用 Mathlib 定理（模块路径已给出，import 对应模块即可）："]
        for d in results:
            sig = d["sig"] or "<无签名>"
            lines.append("- %s : %s   (import %s)"
                         % (d["name"], sig[:120], d["module"]))
        return "\n".join(lines)


# ----------------------------------------------------------------------
# 模块级默认实例（懒加载）
# ----------------------------------------------------------------------
_DEFAULT_MATHLIB_DIR = "E:/mathlib4-last_bump_for_v4.31.0"
_default_retriever = None


def get_retriever(mathlib_dir: str = "") -> MathlibRetriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = MathlibRetriever(
            mathlib_dir or _DEFAULT_MATHLIB_DIR)
    return _default_retriever


if __name__ == "__main__":
    import sys
    r = MathlibRetriever("E:/mathlib4-last_bump_for_v4.31.0")
    if "--rebuild" in sys.argv:
        r.build_index()
    else:
        r.load_index()
        for q in ["prime two", "2 is prime", "even number", "sum of squares"]:
            print("查询: %s" % q)
            for d in r.search(q, k=3):
                print("  - %s : %s" % (d["name"], (d["sig"] or "")[:60]))
            print()
