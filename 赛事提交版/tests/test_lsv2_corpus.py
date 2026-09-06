# -*- coding: utf-8 -*-
"""LeanSearch v2 官方语料离线后端测试（Lsv2Corpus，2026-08-31）。

背景：平台无外网 → 官方 API 失效；语料 gzip（50MB）随仓库走，离线
词法检索非形式化描述。本测试用**自构造小样本 jsonl.gz** 验证逻辑，
不依赖 50MB 真实语料（真实语料质量见 17:15 冒烟：31 万条 100% 描述）。
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile

import pytest

from agent.lean_search import Lsv2Corpus, MathlibTheoremSearcher


def _write_sample(path: str) -> None:
    """构造 4 条声明的 gzip 语料（覆盖权重场景）。"""
    rows = [
        {"name": ["addGroup_aut"], "module_name": ["Mathlib", "Algebra", "Group", "End"],
         "kind": "instance", "type": "",
         "signature": "∀ A, AddGroup A → Group (AddAut A)",
         "informal_name": "Additive automorphisms form a group",
         "informal_description": "For any additive structure A, the set of additive "
                                 "automorphisms of A forms a group under composition.",
         "index": 0, "value": ""},
        {"name": ["sum_divisors_le"], "module_name": ["Mathlib", "NumberTheory"],
         "kind": "theorem", "type": "",
         "signature": "∑ d | n, d ≤ n * (n + 1) / 2",
         "informal_name": "Divisor sum bound",
         "informal_description": "The sum of the divisors of n is at most n times "
                                 "(n+1)/2 for any positive natural number n.",
         "index": 1, "value": ""},
        {"name": ["cyclic_of_prime_card"], "module_name": ["Mathlib", "GroupTheory"],
         "kind": "theorem", "type": "",
         "signature": "∀ G [Group G], Nat.card G = p → IsCyclic G",
         "informal_name": "Groups of prime cardinality are cyclic",
         "informal_description": "Any finite group whose cardinality is a prime number "
                                 "is cyclic.",
         "index": 2, "value": ""},
        # 编译器产物：应被 _CORPUS_KEEP_KINDS 过滤掉
        {"name": ["_proof_1"], "module_name": ["Mathlib", "Hidden"],
         "kind": "constructor", "type": "",
         "signature": "dummy",
         "informal_name": "hidden",
         "informal_description": "compiler generated constructor, should be filtered",
         "index": 3, "value": ""},
    ]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture()
def corpus(tmp_path) -> Lsv2Corpus:
    p = os.path.join(str(tmp_path), "sample.jsonl.gz")
    _write_sample(p)
    return Lsv2Corpus(p)


def test_available(tmp_path):
    p = os.path.join(str(tmp_path), "x.jsonl.gz")
    _write_sample(p)
    assert Lsv2Corpus(p).available()
    assert not Lsv2Corpus(os.path.join(str(tmp_path), "none.jsonl.gz")).available()


def test_keep_kinds_filtered(corpus):
    """constructor 等编译器产物不入索引。"""
    corpus._load()
    docs = corpus._docs
    assert len(docs) == 3  # 第 4 条 constructor 被过滤
    kinds = {d["kind"] for d in docs}
    assert "constructor" not in kinds


def test_search_hits_relevant(corpus):
    """非形式化描述命中：查询"divisors of n"应命中 divisor 定理。"""
    res = corpus.search("the sum of the divisors of a number n", limit=2)
    assert res["status"] == "ok"
    assert res["corpus"] is True
    names = [r["name"] for r in res["results"]]
    assert any("sum_divisors_le" in n for n in names), names


def test_search_weights_informal_name(corpus):
    """informal_name 权重 3 > 描述权重 2：名字命中应排前。"""
    res = corpus.search("prime cardinality cyclic group", limit=3)
    top = res["results"][0]["name"]
    assert "cyclic_of_prime_card" in top, res["results"]


def test_search_no_hit_returns_empty(corpus):
    res = corpus.search("zzzqqqyyy nonexistent", limit=3)
    assert res["status"] == "ok"
    assert res["results"] == []


def test_search_meta_field_present(corpus):
    """每条结果带论文口径的 meta（kind | name | signature）。"""
    res = corpus.search("group automorphism", limit=1)
    assert res["results"]
    meta = res["results"][0]["meta"]
    assert "instance" in meta or "theorem" in meta
    assert "|" in meta


def test_empty_query_returns_ok(corpus):
    res = corpus.search("", limit=3)
    assert res["status"] == "ok"
    assert res["results"] == []


def test_repeated_search_caches_index(corpus):
    """第二次查询不再重新加载（_docs 缓存）。"""
    corpus.search("group", limit=1)
    first_docs = corpus._docs
    corpus.search("divisor", limit=1)
    assert corpus._docs is first_docs


def test_searcher_uses_corpus_backend(corpus, monkeypatch):
    """MathlibTheoremSearcher 接入语料：官方不可达 → 语料命中。"""
    s = MathlibTheoremSearcher(
        roots=[],  # 无本地 mathlib，模拟平台沙盒
        use_official=False,  # 无外网
        corpus_path=corpus.path(),
    )
    res = s.search("divisors of a natural number", limit=2)
    assert res["status"] == "ok"
    assert res.get("corpus") is True
    assert len(res["results"]) >= 1
