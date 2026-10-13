# -*- coding: utf-8 -*-
"""Lean 环境 / 定理检索职责簇（2026-10-09 批15：从 agent/orchestrator.py 逐字搬出）。

搬出方法：_ensure_lean_modules / _lean_active / _lean_applicable /
_retrieve_theorem_hints

**搬迁说明**：
  · _lean_active / _lean_applicable / _retrieve_theorem_hints **逐字搬**；
  · _ensure_lean_modules 有一处**显式 shim**（非逐字，team-lead 批准）：它读主模块全局
    `_LEAN_MODULES_OK`/`LeanGate`/`LeanPreVerifier`/`_load_lean_modules`，且在
    `_load_lean_modules()` **之后会再次读取**（自愈语义）⇒ 用顶层 import 快照会让第二次
    读拿到旧值、自愈失效。故函数内**惰性 `from . import orchestrator as _orch`** + 把这 4
    个符号改为 `_orch.<名>`（**每次调用实时读取**，兼容 tests/test_lean_channel.py:37 对
    `agent.orchestrator._LEAN_MODULES_OK` 的 monkeypatch）。
"""
from __future__ import annotations

import logging

try:
    from agent.switch_registry import get_bool as _sw_bool
except ImportError:
    from switch_registry import get_bool as _sw_bool

logger = logging.getLogger("MathPilot")


def _ensure_lean_modules(self) -> None:
    """首用时自愈 Lean 模块（见 :func:`_load_lean_modules`）。

        顶部 import 若被循环导入阻断（``_LEAN_MODULES_OK=False``），此处重试
        导入并补建 ``lean_gate`` / ``lean_pre_verifier`` 实例——把「静默永久
        禁用」变成「首用自愈」。已就绪时零成本直接返回。
        """
    from . import orchestrator as _orch  # noqa: F401 （惰性；实时读取主模块全局，兼容 monkeypatch）
    if _orch._LEAN_MODULES_OK and _orch.LeanGate is not None:
        if self.lean_gate is None:
            try:
                self.lean_gate = _orch.LeanGate(self.client, self.config)
            except Exception as _e:  # noqa: BLE001
                logger.warning("LeanGate 重建失败: %s", _e)
        if self.lean_pre_verifier is None and _orch.LeanPreVerifier is not None:
            try:
                self.lean_pre_verifier = _orch.LeanPreVerifier(self.client, self.config)
            except Exception as _e:  # noqa: BLE001
                logger.warning("LeanPreVerifier 重建失败: %s", _e)
        return
    if not _orch._load_lean_modules():
        return
    try:
        if self.lean_gate is None and _orch.LeanGate is not None:
            self.lean_gate = _orch.LeanGate(self.client, self.config)
        if self.lean_pre_verifier is None and _orch.LeanPreVerifier is not None:
            self.lean_pre_verifier = _orch.LeanPreVerifier(self.client, self.config)
        logger.info("Lean 双通道已自愈启用（此前被循环导入静默禁用）")
    except Exception as _e:  # noqa: BLE001
        logger.warning("Lean 双通道自愈后实例化失败，保持禁用: %s", _e)


def _lean_active(self) -> bool:
    """Lean 通道是否启用：总开关开 + lean 模块在 + Lean 环境可用（结果缓存）。

        探测 = LeanGate 懒加载的 LeanBridge.lean_available（跑一次
        `lean --version`，进程内只探一次）。任何异常都视为不可用 → 回落
        AuditGate，绝不让 lean 探测本身拖垮/阻断评测。
        环境变量 LEAN_VERIFY=0（或 false/no/off）可一键关闭 lean 通道
        （单测经 tests/conftest.py 统一置 0；评测 A/B 对照也可用它）。
        """
    self._ensure_lean_modules()          # 2026-09-10：治循环导入静默禁用
    _env_off = "0" if not _sw_bool("lean_verify") else "1"
    if _env_off in ("0", "false", "no", "off"):
        return False
    if not getattr(self.config, "enable_lean_verify", True):
        return False
    if self.lean_gate is None:
        return False
    if self._lean_probe is None:
        try:
            _b = self.lean_gate._bridge_inst
            self._lean_probe = bool(_b is not None and _b.lean_available)
        except Exception:  # noqa: BLE001
            self._lean_probe = False
        if not self._lean_probe:
            logger.warning("Lean 环境不可用，检测链回落 AuditGate（AI 判分）")
    return bool(self._lean_probe)


def _lean_applicable(self, ctx) -> bool:
    """按题 Lean 适用性（2026-09-10 用户要求「所有题都要用 Lean，除非非常
        简单的题」）。

        判定值由 1.1) 步骤落盘到 ``ctx.metadata["lean_applicable"]``（见
        :func:`agent.question_type.lean_applicable`）。此处只读，用于把
        **整题豁免**的题（答案不是数学对象：选项字母 / 判断值 / 概念文字）
        从 Lean 通道改路由到 AuditGate —— 即「豁免 Lean，但不豁免检测」，
        而不是让它们裸奔输出。

        缺省语义：metadata 无该键（旧结果、手搓 ctx、单测 fixture）→ 视为
        适用，保持既有行为完全不变。
        """
    md = getattr(ctx, "metadata", None)
    if isinstance(md, dict) and md.get("lean_applicable") is False:
        return False
    return True


def _retrieve_theorem_hints(self, ctx) -> None:
    """1.6) 用 leansearch 到 Mathlib 检索本题该用的定理，写入 ctx。

        写出的字段（供下游各阶段按需取用，**不改变任何既有分支**）：
          · ``ctx.theorem_hints``      : list[str] 命中的 Mathlib 全名
          · ``ctx.theorem_hint_block`` : str 注入提示词用的文本块（可为空）
          · ``ctx.theorem_hint_trace`` : dict 完整埋点（query/命中/耗时/后端）

        ★ 用户要求「调用工具的方法要写成规范性的类函数，需要使用 Lean 检测时
          直接调用那个函数，适配每一阶段」⇒ 检索逻辑**全部收敛在**
          ``agent.theorem_hint.retrieve_theorems_for_question()`` 一个入口，
          本方法只做「调用 + 落盘 + 埋点」，不含任何检索细节。
          换后端/换 query 策略只改 theorem_hint.py，本处不动。

        ★ 失败与超时一律降级（不阻断主流程）：检索只是**增益**，不是门禁。
        """
    try:
        from .theorem_hint import (retrieve_theorems_for_question,
                                   match_against_ground_truth)
    except Exception as e:  # noqa: BLE001
        logger.warning("[1.6_theorem_hint] 模块导入失败，跳过: %s", e)
        return

    # ★ 2026-10-13（用户 A1）：**LLM 辅助 query** —— 让大模型先给出检索方向，
    #   再交检索器出事实（LLM 不直接吐定理名，防幻觉）。失败 ⇒ 完全回退规则 query。
    _extra_q = []
    if getattr(self.config, "enable_theorem_query_llm", True):
        try:
            from .theorem_hint import (THEOREM_QUERY_LLM_SYSTEM as _QS,
                                       parse_llm_queries as _PQ)
            _raw_q = self.llm(ctx, [
                {"role": "system", "content": _QS},
                {"role": "user", "content": "题目：%s\n领域：%s" % (
                    ctx.problem or "", getattr(ctx, "domain", "") or "未知")},
            ], 0.2, 512)
            _extra_q = _PQ(_raw_q)
            self.record(ctx, "theorem_hint",
                        "LLM 辅助 query：%s" % (_extra_q or "（空，回退规则 query）"))
        except Exception as _e_q:  # noqa: BLE001  检索是增益，绝不阻断
            self.record(ctx, "theorem_hint",
                        "LLM 辅助 query 失败（回退规则 query）: %s" % str(_e_q)[:100])

    try:
        res = retrieve_theorems_for_question(
            ctx.problem or "",
            domain=getattr(ctx, "domain", "") or "",
            question_type=getattr(ctx, "question_type", "") or "",
            config=self.config,
            max_queries=int(getattr(
                self.config, "theorem_hint_max_queries", 2) or 2),
            top_k=int(getattr(self.config, "leansearch_top_k", 5) or 5),
            extra_queries=_extra_q,
        )
    except Exception as e:  # noqa: BLE001  # 兜底：接口内已 try，此处再保险
        self.record(ctx, "theorem_hint",
                    f"定理检索异常（跳过，不阻断）: {type(e).__name__}: {e}")
        return

    ctx.theorem_hints = list(res.names)
    md = res.to_dict()
    # 与题库预标注比对（若 metadata 里带了该题标注；云端/离线注入时才有）
    gt = None
    try:
        _md = getattr(ctx, "metadata", None)
        if isinstance(_md, dict):
            gt = _md.get("theorem_gt")
    except Exception:  # noqa: BLE001
        gt = None
    if gt:
        try:
            md["gt_match"] = match_against_ground_truth(res, gt)
        except Exception as e:  # noqa: BLE001
            md["gt_match"] = {"error": f"{type(e).__name__}: {e}"}
    ctx.theorem_hint_trace = md
    # ★ 2026-10-12（批次 5 剩余，用户 §5.2）：保留**全量**检索结果，
    #   供 `render_for_stage()` 按环节重新渲染（分环节条数）。
    ctx.theorem_hint_result = md
    # 分环节条数：config 里是 **JSON 字符串**（注册表无 dict 类型）⇒ 在此解析。
    # 解析失败/为空 ⇒ 用 `theorem_hint` 模块内的默认表（避免「配置写错就静默失效」）。
    try:
        import json as _json_th
        from .theorem_hint import DEFAULT_TOPK_BY_STAGE as _DEF_TOPK
        _raw_topk = str(getattr(
            self.config, "theorem_hint_top_k_by_stage", "") or "").strip()
        _parsed = _json_th.loads(_raw_topk) if _raw_topk else {}
        ctx._theorem_topk_by_stage = (dict(_parsed) if isinstance(_parsed, dict)
                                      else dict(_DEF_TOPK))
        if not ctx._theorem_topk_by_stage:
            ctx._theorem_topk_by_stage = dict(_DEF_TOPK)
    except Exception:  # noqa: BLE001  解析失败 ⇒ 回退默认表，绝不阻断
        try:
            from .theorem_hint import DEFAULT_TOPK_BY_STAGE as _DEF_TOPK2
            ctx._theorem_topk_by_stage = dict(_DEF_TOPK2)
        except Exception:  # noqa: BLE001
            ctx._theorem_topk_by_stage = {}

    # 注入块：★ 2026-09-29 改为调用 `TheoremRetrieval.render_hint_block()`。
    # 原先在此处**内联拼装**「短名 + 全名」两列，实测 5 条命中即 798 字符，
    # 其中 Mathlib 命名空间前缀占 60%+，对中文推理的大模型是纯 token 噪音。
    # 现收敛为「短名列表」——拼装口径统一由 theorem_hint 模块负责（符合用户
    # 「调工具的方法要写成规范性的类函数」），本处不再持有任何渲染细节。
    # 全名仍完整保留在 `ctx.theorem_hint_trace` 里（见下），供 Lean 侧/A-B 归因。
    try:
        ctx.theorem_hint_block = res.render_hint_block(
            max_items=int(getattr(self.config, "leansearch_top_k", 5) or 5),
            max_chars=int(getattr(
                self.config, "theorem_hint_block_max_chars", 2500) or 0))
    except Exception as e:  # noqa: BLE001  渲染失败不阻断
        logger.warning("[1.6_theorem_hint] 渲染注入块失败，跳过注入: %s", e)
        ctx.theorem_hint_block = ""

    self.record(
        ctx, "theorem_hint",
        f"定理检索 {'命中 ' + str(len(res.hits)) + ' 条' if res.ok else '未跑通'}"
        f"（{res.elapsed:.1f}s，后端 {res.backend or '-'}）"
        + (f"；{res.reason}" if res.reason else ""),
        n_hits=len(res.hits), elapsed=round(res.elapsed, 2),
        backend=res.backend)
