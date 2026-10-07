# -*- coding: utf-8 -*-
"""验证族阶段（4.x）（2026-10-07 阶段C4：从 agent/orchestrator.py 的 Orchestrator.run 抽出）。

已抽出段：  · 4_verify（verify_stage）  · 4.5_oracle（oracle_review_stage）

**纯搬迁**：段内源码逐字搬入（仅去 8 空格缩进），调用点由 `run` 改为一行委托。
`run` 保留各自的 `self._stage_start(ctx, "<阶段名>")` 打点**原位不动**
（阶段名是稳定契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：
  · 4_verify 段：对 `run` 的依赖仅 `ctx` + `tier`（无 run 局部需传参）；
    **生产** `ver_result` / `tier_votes` 并返回给 `run`（二者被后续 4.5/4.6/5/5.5
    **只读**使用）——这是本段唯一的外泄点。段内其余绑定（`is_proof` /
    `_tier_vote_map` / `_p1_*` / `_pre_verify_n` / `_clean` / `_bc6` 等）段后零读取；
    `v`/`g`/`_c` 系推导式变量、`_keep_cand` 系段内嵌套函数（均非外泄）。
    段内引用 3 个 orchestrator 模块级符号（`_answer_fingerprint` / `_artifact_put`
    / `_re`）⇒ 在函数内**惰性 import**（单一来源仍在 orchestrator，不复制）。
    段内 `return` 仅属嵌套函数 `_keep_cand`；无 `yield`/`break`/`continue`。
  · 4.5 段：对 `run` 的依赖为 `ctx` + `tier` + **只读** `ver_result` / `tier_votes`
    （两者均由 4_verify 段赋值，本段只读透传）；段内**无任何局部绑定**、
    无 `return`/`yield`/`break`/`continue`。外部符号全部经 `self` 访问
    （`self._enhance_window_ok` / `self._oracle_review_best`）⇒ 无需模块级 import。
"""
from __future__ import annotations


def verify_stage(self, ctx, tier: str):
    """4) 验证（投票数按档位：fast=1/standard=1/deep=3）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位。
    ★ 返回 `(ver_result, tier_votes)`：本段**生产**这两者，而 4.5_oracle /
    4.6_adv / 5_revise / 5.5_low_conf 段**只读**使用 ⇒ 由本函数返回、run 内解包
    （本段唯一的 run 局部绑定新增点；除此之外 run 局部零外泄，AST 实测）。
    P1 硬信号块随本段整体搬迁 ⇒ 仍在 `verifier.run` 之前、`tier_votes` 就绪之后、
    且在 `_stage_start("4_verify")` 计时窗口内（相对位置与计时窗口均不变）。
    """
    from .orchestrator import _answer_fingerprint, _artifact_put, _re

    # 4) 验证（投票数按档位：fast=1/standard=1/deep=3）
    # P0-4 修复：playoff 复算按时间宽裕度开关，deep 档且时间宽裕时启用
    #
    # 2026-08-31 修复 NameError：#45 移除题型分流时把 3.5 步的
    # `is_proof = ...` 赋值一起删了，但这里的 verifier.run 仍在用它 →
    # 每题抛 `name 'is_proof' is not defined`，整条流水线走异常兜底。
    # 说明：#45 要移除的是「**子目标触发** / **Lean 门禁**看题型」，
    # 验证器的 is_proof 是另一回事（verifier.py 用它决定单候选时的
    # 严格度），属于正当用途，必须保留。
    is_proof = (getattr(ctx, 'question_type', '') == '证明题'
                or getattr(ctx, 'domain', '') in ('证明', '证明题'))
    tier_votes = self.config.tier_voting_times.get(tier, 1)
    # ★ 2026-10-07 修「假开关 --voting_times」（问题总账 §2.6）：
    #   主路径此前**只**读 `tier_voting_times`，并把结果**显式**传给
    #   `verifier.run(voting_times=tier_votes)`；而 `verifier.run` 仅在
    #   `voting_times is None` 时才回退 `config.verifier_voting_times`
    #   ⇒ `run_eval.py --voting_times N`（→ `verifier_voting_times`）
    #   对主路径**完全无效**（旧注释所称"可调"只对非主路径成立）。
    #   现让主路径取「档位票数」与「用户配置」的**较大者**：
    #     · 默认配置下 `verifier_voting_times`(2) ≤ `tier_voting_times[deep]`(3)
    #       ⇒ **默认行为零变化**；
    #     · 用户 CLI 调大（如 `--voting_times 5`）⇒ 真正生效。
    #   与 `verifier._vote_profile` 既有的「以下限方式合并」同口径。
    #   ⚠ 仅当该 tier 在 `tier_voting_times` 里有显式条目时才合并，避免影响
    #     无条目档位的默认 1 票；调**小**不生效（档位计划票数是下限）。
    _tier_vote_map = getattr(self.config, "tier_voting_times", None) or {}
    if tier in _tier_vote_map:
        try:
            _user_votes = int(getattr(
                self.config, "verifier_voting_times", 0) or 0)
        except (TypeError, ValueError):
            _user_votes = 0
        if _user_votes > int(tier_votes):
            self.record(ctx, "verifier",
                        f"投票票数提升：用户配置 verifier_voting_times="
                        f"{_user_votes} > 档位 {tier_votes} → 采用 {_user_votes}"
                        f"（--voting_times 对主路径生效）")
            tier_votes = _user_votes

    # P1 v3（2026-09-11）：验证硬信号 → 强制重解（official112 头号靶点）。
    # 演进记录（三次实测定位）：
    #   v1：位于 4.6 对抗验证（363s）之后 + `gen_time_up()` 护栏 → 冒烟 4/4 未触发；
    #   v2：前移到 4_verify 之后 + 硬墙剩余护栏 → 复测仍未触发：002 到 4_verify
    #       结束已用 1201s、010 用 1110s（剩余 90s < 240s 门槛）。
    #   → 结论：**4_verify 结束时时间已耗尽**，护栏怎么调都晚。
    # v3 定位：3.6 候选筛选之后 / 4_verify 之前（tier_votes 已就绪）。典型时点
    #   约 600-700s，剩余 500s+，足够一轮重解（约 100-200s）。
    #   ver_result 此时尚未生成 → 传 {}；_deep_revise_loop 会走默认 feedback 并把
    #   audit_reject_feedback 中的硬信号拼入，正是所需的定向修正输入。
    # 信号源（均为该点之前已产生）：数值攻击证伪（蓝图阶段，写 blueprint_value_false）、
    #   AuditGate reject（3.6 阶段）。final_gate 在 6.5 才产生，晚于此处，不纳入。
    # ⚠ 2026-09-17（Audit-4）核实：`orchestrator.run()` 仅在
    #   `user_agent.solve()` 里被调用**一次**（无重试/升级循环）⇒ 本守卫的
    #   读(:此) 与写(下方) 同处一趟直线代码内，**当前恒为真分支（守卫无效）**。
    #   保留而不删除，是为将来 run() 被重入时仍能防重复触发；但**不得**把它
    #   当作"已生效的幂等保护"来依赖（原测试仅断言源码字符串含该名，锁不住行为）。
    if not getattr(ctx, "_p1_triggered", False):
        _p1_msgs = []
        if getattr(ctx, "blueprint_value_false", None):
            _p1_msgs.append(
                f"[数值攻击证伪] {str(ctx.blueprint_value_false)[:200]}")
        _p1_ag = [g for g in (getattr(ctx, "audit_gate", None) or [])
                  if isinstance(g, dict)
                  and (g.get("verdict") or "") == "reject"]
        if _p1_ag:
            _p1_msgs.append("[客观审核拒绝] " + str(
                _p1_ag[-1].get("reason") or "")[:200])
        # ★ 2026-09-11 修复：补上「3.6 阶段 Lean 候选级淘汰」信号。
        # 原因（v7 实测 014）：`final_gate` 的 proof_invalid 在 **6.5** 才产生，
        # 晚于本检查点（4_verify 之前）→ 结构上不可见，导致"有时间、有信号却
        # 不触发"。3.6 的候选级 LeanGate.apply 会写"淘汰 N 候选"记录，位于本点之前。
        # 2026-09-12 修复（消除脆耦合）：改用**结构化字段**取该信号。
        # 原实现是"在 trace 里匹配 content 是否含中文子串『淘汰』"—— 一旦
        # 有人改写那句日志文案（如"淘汰"→"筛除"），P1 会**静默地不再触发**
        # 且无任何报错（典型"改文案即功能失效"，且不可观测）。
        # 注意本块上面两个信号源（blueprint_value_false、audit_gate[].verdict）
        # 本来就是结构化字段，此处统一口径。
        # `ctx.lean_reject_feedback` 由 3.6 的 Lean 淘汰分支写入（同一时点之前）。
        _p1_lg = list(getattr(ctx, "lean_reject_feedback", None) or [])
        if _p1_lg:
            _p1_msgs.append(
                "[Lean 候选级验证淘汰] " + str(_p1_lg[-1])[:200])
        if (_p1_msgs and tier in ("deep", "standard")
                and not ctx.state.emergency
                and ctx.time_remaining() > 150):
            ctx._p1_triggered = True
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", []) or []) + _p1_msgs
            self.record(ctx, "revise",
                        "P1 硬信号触发强制重解"
                        f"（{len(_p1_msgs)} 条，tier={tier}，"
                        f"剩余 {ctx.time_remaining():.0f}s）")
            _p1_before = _answer_fingerprint(ctx)
            self._deep_revise_loop(ctx, {}, tier_votes, force=True)
            # G1（2026-09-11）：记录重解成效——此前只能看到"触发了"，
            # 看不到"改没改、改成什么样"，导致"触发但无效"无法量化。
            # ★ 2026-10-05：改用候选答案指纹（见 `_answer_fingerprint`）——
            #   原用 ctx.final_response，此处恒为 "" ⇒ 永远显示"答案未变化"。
            _p1_after = _answer_fingerprint(ctx)
            self.record(
                ctx, "revise",
                f"P1 重解成效：{'答案已变化' if _p1_after != _p1_before else '答案未变化'}"
                f"（{len(_p1_before)}→{len(_p1_after)} 字符）")
            # 2026-09-13（用户原则："无用功要保证检测并截断，但不得影响原有
            # 功能"）：把已记录的成效**变成决策依据** —— 重解后答案未变化时
            # 打标记，后续同源的 revise（4.6 对抗 / 5 全0票 / 5.5 低置信）
            # 不再对**同一个答案**重复重解。
            # 保守性：仅在"答案完全未变"时置位；一旦答案变化即视为有进展，
            # 标记在下一轮由 final_answer 变化自动失效（见下游判断）。
            if _p1_after == _p1_before:
                try:
                    ctx._revise_no_progress_answer = _p1_after
                except Exception as _e_np:  # noqa: BLE001
                    # ★ 2026-10-07 观测补齐（问题总账 §2.6「纯空吞异常」A 类）：
                    #   原为裸 `pass`。本标记是"无用功截断"的**唯一依据**——
                    #   置位失败 ⇒ 4.6/5/5.5 三个同源 revise 会对**同一个答案**
                    #   反复重解（历史实测单题 revise 轮数打到 6、白烧算力），
                    #   且无任何痕迹可归因。
                    self.record(ctx, "revise",
                                f"「重解无进展」标记置位失败"
                                f"（{type(_e_np).__name__}: {str(_e_np)[:120]}）"
                                f"→ 同源 revise 可能对同答案重复重解")
        else:
            # 2026-09-12 可观测性补强（Bug 4 跟进）：P1"0 触发"必须能区分
            # 是「**没有硬信号**」还是「**有时间但因档位/emergency/门槛被拦**」。
            # 此前两者在日志里都表现为"什么都没记"，导致无法定位。
            # 事件名用 `p1_check`（不写 `revise`）以免污染 revise 统计口径。
            _p1_why = []
            if not _p1_msgs:
                _p1_why.append(
                    "无硬信号（数值攻击证伪 / AuditGate reject / "
                    "3.6 Lean 候选级淘汰 三者皆空）")
            if tier not in ("deep", "standard"):
                _p1_why.append(f"档位 {tier} 不在 deep/standard")
            if ctx.state.emergency:
                _p1_why.append("处于 emergency 状态")
            if ctx.time_remaining() <= 150:
                _p1_why.append(
                    f"剩余 {ctx.time_remaining():.0f}s ≤ 150s 门槛")
            if _p1_why:
                self.record(ctx, "p1_check",
                            "P1 未触发：" + "；".join(_p1_why))

    # 2026-10-01：比赛期「候选池统一封顶 6」已按研究期标尺删除
    # （审计 A 级第 6 条）。原注释自述 `cap 8→6（deep 候选 4→3 配套，
    # 验证成本 -25%）` —— 属以成本为由裁剪候选粒度。研究期求正确率上限，
    # 不再截断候选；此处仅保留计数记录，便于观察候选规模与耗时关系。
    _pre_verify_n = len(ctx.candidates or [])
    if _pre_verify_n > 6:
        self.record(ctx, "control",
                    f"候选池 {_pre_verify_n} 个（已取消封顶，不再截断为 6）")
    # 2026-09-13：过滤「非答案形态」候选。
    # 096 实测：候选 answer 字段里混入 Markdown 标题 `### 选项A分析`，
    # 因其 len>3 且不含拒绝词，被计入选择题投票 ⇒ **污染投票分布**。
    # 只过滤**明确的行首结构标记**（标题/列表/引用/表格），
    # 不碰正文类长答案（统计学的论述题 gold 本就是长文本）。
    # ★★ 2026-09-18（审核发现）：原判据**只认 Markdown 行首标记**
    #   （`#`/`-`/`*`/`数字.`/`>`/`|`），而实测大量脏候选是「过程叙述」
    #   （`步骤11：搜索已知结论`、`继续找规律，目前 type B：2, 8, 10。`），
    #   于是 032 记录"过滤 5 → 4"只滤掉 `- ` 开头那一条，其余全部留存
    #   并进入投票 ⇒ **污染票型、进而被选为最终答案**。
    #   现改为**复用 formatter 的 `_looks_like_non_answer`**（单一判据来源，
    #   避免两处口径分叉），Markdown 标记作为兜底保留。
    try:
        try:
            from .formatter import _looks_like_non_answer as _nma36
        except Exception:  # noqa: BLE001
            _nma36 = None

        def _keep_cand(_c):
            _a = getattr(_c, "answer", "") or ""
            if _re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s|\|\s)", _a):
                return False
            if _nma36 is not None and _nma36(_a):
                return False
            return True

        _before36 = list(ctx.candidates or [])
        _clean = [_c for _c in _before36 if _keep_cand(_c)]
        if _clean and len(_clean) < len(_before36):
            self.record(ctx, "control",
                        "过滤非答案形态候选 {} → {}（复用 _looks_like_non_answer，"
                        "2026-09-18）".format(len(_before36), len(_clean)))
            ctx.candidates = _clean
        elif not _clean and _before36:
            # 全被滤掉时不清空池（保持与 M2 同一原则），只记录
            self.record(ctx, "control",
                        "候选池 %d 个全部呈非答案形态（未清空，保持 M2 原则，"
                        "2026-09-18）" % len(_before36))
    except Exception as _e_f36:  # noqa: BLE001
        # ★ 2026-10-07 观测补齐（问题总账 §2.6「纯空吞异常」A 类）：原为裸 `pass`。
        #   本块负责「过滤非答案形态候选（Markdown 标题/过程叙述）」，是 096 实测
        #   「污染票型→错答案」的对策。整块静默失败 ⇒ 脏候选**照进投票**且无痕迹，
        #   与"过滤后本就干净"不可区分。
        self.record(ctx, "control",
                    f"非答案形态候选过滤失败（{type(_e_f36).__name__}: "
                    f"{str(_e_f36)[:120]}）→ 脏候选可能进入投票")
    ver_result = self.verifier.run(
        ctx, problem=ctx.problem, candidates=ctx.candidates,
        use_clustering=True,
        use_scoring=self.config.use_scoring,
        is_proof=is_proof,
        use_playoff=(
            (tier == 'deep' and getattr(self.config, 'deep_use_playoff', True))
            or (tier != 'deep' and ctx.state.playoff_enabled)
        ),
        use_deterministic=getattr(self.config, 'enable_deterministic', True),
        use_rubric=getattr(self.config, 'use_rubric', False),
        use_challenge=getattr(self.config, 'use_challenge', False),
        voting_times=tier_votes,
    )
    ctx.verdicts = self._verdicts_from_ver_result(ver_result, ctx.candidates)
    ctx._best_cluster = ver_result.get("best_cluster")
    ctx._cluster_data = ver_result.get("cluster_data", [])

    # ★ 2026-10-02 hook 06：4_verify 后落盘 verdict（06_verdicts）。
    _bc6 = getattr(ctx, "_best_cluster", None)
    _artifact_put(ctx, "06_verdicts", {
        "verdicts": [
            {"id": v.id, "answer": getattr(v, "answer", ""),
             "confidence": getattr(v, "confidence", None),
             "correct_votes": getattr(v, "correct_votes", None),
             "total_votes": getattr(v, "total_votes", None),
             "feedback": getattr(v, "feedback", "")}
            for v in (getattr(ctx, "verdicts", None) or [])
        ],
        "cluster": (None if _bc6 is None else {
            "answer_norm": getattr(_bc6, "answer_norm", ""),
            "size": getattr(_bc6, "size", None),
            "confidence": getattr(_bc6, "confidence", None),
            "candidate_ids": getattr(_bc6, "candidate_ids", None),
        }),
    })
    return ver_result, tier_votes


def oracle_review_stage(self, ctx, tier: str, ver_result, tier_votes) -> None:
    """4.5 deep 档 AnswerOracle 客观复核 best_cluster（区别于投票同源自评）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位；`ver_result` / `tier_votes` 为
    4_verify 段算出、本段**只读**使用（透传给 `self._oracle_review_best`）。
    返回 None；结果写回 `ctx`。
    """
    # 4.5) deep 档：AnswerOracle 客观复核 best_cluster（区别于投票同源自评）
    # 2026-09-06 超时修复（验证暴露残留洞）：oracle 复核单次可达 300s+，
    # 原只在内部查 is_time_critical（deadline-60s）→ algebra-003 修复后
    # verify 提前完成反而给 oracle 打开 365s 烧穿窗口（elapsed 1402s）。
    # oracle 是"4_verify 之后的复核增强"，到生成侧软截止即弃——
    # verify 已投过票，放弃复核不损失主验证，只少一层 deep 深查。
    # ★ 2026-09-17（Audit-3）：口径统一为 `is_time_critical()`（真实剩余时间）。
    # `gen_time_up()` 是**生成**侧软截止（deadline − verify_reserve）；4.5 Oracle
    # 属"4_verify 之后的复核"，用生成时钟闸它是口径错配，与已修好的 5.5 不一致。
    # 真正的耗时护栏是本行的 `_enhance_window_ok`（要求剩余 ≥ 360+tail+30），
    # 故换时钟不会重新打开烧穿窗口。
    if (tier == 'deep'
            and getattr(ctx, '_best_cluster', None) is not None
            and not ctx.is_time_critical()
            and self._enhance_window_ok(ctx, "oracle")):
        self._oracle_review_best(ctx, ver_result, tier_votes)


def adversarial_stage(self, ctx, tier: str, ver_result, tier_votes) -> None:
    """4.6 对抗式验证（正向通过后主动证伪，抓漏检）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`）；
    `ctx` 为 `TaskContext`，`tier` 为当前档位；`ver_result` / `tier_votes` 为
    4_verify 段算出、本段**只读**使用（透传 `self._deep_revise_loop`）。
    返回 None；结果写回 `ctx`。
    """
    # 4.6) 对抗式验证（#16）：正向通过后主动证伪，抓漏检。
    #      仅当"确有候选被正向判对"时才跑——正向全错的会走 revise，
    #      再证伪一次是纯浪费（每轮调用都吃预算，见 #43 归因）。
    _any_correct = any(
        getattr(v, 'correct_votes', 0) > 0 for v in (ctx.verdicts or []))
    if _any_correct:
        # 2026-09-04 修复：对抗检出错误 → 立即触发定向修正（原反馈滞留 bug）。
        # 原实现仅把反馈塞进 audit_reject_feedback（曾名 lean_reject_feedback），
        # 而 5（全 0 票）/5.5（置信<0.5）触发条件都看投票共识 → 验证器自信
        # 通过时对抗检出的错误无人消费、答案带错提交（与 4.5 Oracle 判错即
        # revise 不对称）。误报风险由 Step4 _review_bug_feedback 复核兜底，
        # 死循环由 revise_round 全局上限 5 + 时间检查防护。
        if self._adversarial_probe(ctx, tier):
            self._deep_revise_loop(ctx, ver_result, tier_votes)
