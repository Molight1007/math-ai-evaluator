# -*- coding: utf-8 -*-
"""tools.lean_local —— Lean 形式化集成层。

⚠ 2026-09-20 更正：本包**不是归档**，而是主链的活跃组件。
此前 docstring（以及同目录 README.md）声称"平台链路（agent/）已无 Lean 集成、
本包归档" —— 与代码事实完全相反：
  · agent/orchestrator.py 在每次评测中都会构造 LeanGate（3.6 / 6.5 两处闸门）
    与 LeanPreVerifier；★ 2026-10-14：**LeanPreVerifier 的 2.6 前置形式化调用点
    已撤除**（三条原始理由全失效，且无 Lean 环境时从未跑过 ⇒ 零行为变化）——
    本包中它的 `run_understanding_chain()`（题意理解）**仍是 2.6 的本体**，
    `run()`（前置形式化）改由本地 `cli/leap_eval.py` 独立调用；
  · agent/verifier.py 经本包的 lean_search 做 Mathlib 定理检索；
  · deploy/_manifest.tsv 中有 26 行在打包本目录。

能力清单：
  · lean_bridge           Lean 编译/verify/verify_answer/formalize + 环境探测 + MCP 代理池
  · lean_gate             候选级与最终答案的硬验证闸门
  · lean_search           Mathlib 语义检索（官方 API / 离线语料 / 源码扫描三级后端）
  · lean_pre_verifier     题意理解（`run_understanding_chain`，2.6 本体）
                          ＋ 题目前置形式化（`run`，★ 2026-10-14 起仅供
                          cli/leap_eval.py 本地证据链，不在主流水线）
  · lean_mcp_proxy        spawn lean-lsp-mcp 的 JSONL 子进程代理
  · theorem_memory        跨题定理命中统计（写侧已接，读侧暂无调用方）
  · lean_refiner / lean_translator
                          LEAP Stage2/3 实现，**目前无生产调用点**（供研究线使用）
"""
