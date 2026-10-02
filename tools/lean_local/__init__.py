# -*- coding: utf-8 -*-
"""tools.lean_local —— Lean 形式化集成层。

⚠ 2026-09-20 更正：本包**不是归档**，而是主链的活跃组件。
此前 docstring（以及同目录 README.md）声称"平台链路（agent/）已无 Lean 集成、
本包归档" —— 与代码事实完全相反：
  · agent/orchestrator.py 在每次评测中都会构造并调用 LeanGate / LeanPreVerifier
    （见 orchestrator.py 的 __init__ 与 2.6 / 3.6 / 6.5 三处闸门）；
  · agent/verifier.py 经本包的 lean_search 做 Mathlib 定理检索；
  · deploy/_manifest.tsv 中有 26 行在打包本目录。

能力清单：
  · lean_bridge           Lean 编译/verify/verify_answer/formalize + 环境探测 + MCP 代理池
  · lean_gate             候选级与最终答案的硬验证闸门
  · lean_search           Mathlib 语义检索（官方 API / 离线语料 / 源码扫描三级后端）
  · lean_pre_verifier     题目前置形式化（2.6 位，默认关闭）
  · lean_mcp_proxy        spawn lean-lsp-mcp 的 JSONL 子进程代理
  · theorem_memory        跨题定理命中统计（写侧已接，读侧暂无调用方）
  · lean_refiner / lean_translator
                          LEAP Stage2/3 实现，**目前无生产调用点**（供研究线使用）
"""
