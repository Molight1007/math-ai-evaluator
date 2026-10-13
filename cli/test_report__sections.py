# -*- coding: utf-8 -*-
"""`cli/test_report.py` 的**报告分节**（2026-10-09 拆分 批6-2）。

从 `cli/test_report.py` 逐字搬出 10 个 `sec_*` 分节函数（报告二/三/四/五/六/七/
八/九/十及总览）。共享常量与工具从 `cli.test_report__common` 取。

依赖方向：本模块**不反向导入** `cli/test_report` ⇒ 无包级环。

⚠ `sec_stage_dashboard` / `_stage_dashboard_rows` / `_stage_reached`（四维仪表盘）
**留在 `cli/test_report.py` 原位** —— 被 `tests/test_stage_dashboard_0930.py`
直接 `from cli.test_report import ...`，属对外契约，不搬。
"""
from __future__ import annotations

import collections
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:  # noqa: E402
    sys.path.insert(0, ROOT)

from cli.test_report__common import (  # noqa: E402
    MECH_EXPECT,
    STAGE_ORDER_test_report,
    TOOL_LIMITS,
    TOOL_SWITCHES,
    _num_or_zero,
    fmt,
    hhmmss,
    local_attribution,
    med,
    pct,
)
from cli.deepseek_error_analyst import (  # noqa: E402
    _as_dict,
    _as_list,
    classify_validity,
)
from tools.gen_test_report import safe  # noqa: E402


def sec_overview(recs, meta, files, env):
    L = ["# %s 评测报告" % meta["run"], ""]
    L.append("生成时间：%s ｜ 报告口径：一次测试一个文档（用户 2026-09-22 确立）"
             % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("")

    L.append("## 一、测试的具体数据")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    arm = meta.get("arm") or {}
    # ★ 2026-10-12 修（判读失真 #5）：arm.json 的 `overrides` 常为空（启动器不写），
    #   真正生效的覆盖在**日志 `EvalEngine init`**（skill §5.2 的权威口径）。
    #   此前只显示 arm ⇒ 表1 显示 "{}" 而表14/16 显示「24 键」，两处自相矛盾。
    _arm_ov = arm.get("overrides") or {}
    _log_ov = meta.get("overrides") or {}
    _ov_cell = (json.dumps(_arm_ov, ensure_ascii=False) if _arm_ov
                else "%s（来源：日志 overrides，共 %d 键）"
                % (json.dumps(_log_ov, ensure_ascii=False), len(_log_ov)))
    rows = [
        ("会话名", meta["run"]),
        ("起始时间", arm.get("started_at") or "—"),
        ("结束时间", meta.get("ended_at") or "—"),
        ("实验臂", str(arm.get("arm") or "—")),
        ("并发", str(arm.get("concurrency") or "—")),
        ("题单", str(arm.get("test_file") or os.path.basename(files.get("testset") or ""))),
        ("题目数", str(len(recs))),
        ("报告文件名", "%s（日期口径：起始日；来源 %s）"
         % (files.get("fname") or "—", files.get("date_src") or "—")),
        ("override", _ov_cell),
        ("LLM 模型", env.get("LLM_MODEL") or "—"),
        ("LLM_TIMEOUT", env.get("LLM_TIMEOUT") or "—"),
        ("结果文件", os.path.basename(files["results"])),
        ("日志", os.path.basename(files["log"]) if files.get("log") else "—"),
        ("监控采样", os.path.basename(files["monitor"]) if files.get("monitor") else "—"),
        ("检错结果", os.path.basename(files["audit"]) if files.get("audit") else "未跑"),
    ]
    for k, v in rows:
        L.append("| %s | %s |" % (k, safe(v, 160)))
    L.append("")

    # 有效性闸门
    vc = collections.Counter(classify_validity(r)[0] for r in recs)
    n_ok = len(recs)
    n_clean = vc.get("clean", 0)
    L.append("### 有效性闸门（先判这一项，否则后面的数字不能看）")
    L.append("")
    L.append("判定口径：占位符或缺 trace ⇒ 不可用；LLM 失败步占比 ≥50% ⇒ 无效；"
             "≥2% ⇒ 退化（结论需打折）；<2% ⇒ 干净。")
    L.append("")
    L.append("| 状态 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k in ("clean", "degraded", "invalid", "unknown"):
        if vc.get(k):
            L.append("| %s | %d | %s%% |" % (k, vc[k], fmt(pct(vc[k], n_ok))))
    L.append("")
    if vc.get("invalid", 0) or vc.get("unknown", 0):
        L.append("> ⚠ **本轮存在 %d 题无效 / %d 题无法判定**：正确率读数受基础设施影响，"
                 "不得直接当作模型能力结论。" % (vc.get("invalid", 0), vc.get("unknown", 0)))
        L.append("> 可用样本数为 **%d 题**（干净 + 退化）。" % (n_clean + vc.get("degraded", 0)))
        L.append("")
    return L, vc


def sec_result(recs, core):
    n = len(recs)
    ok = sum(1 for r in recs if r.get("correct"))
    L = ["## 二、总体结果", ""]
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append("| 完成题数 | %d |" % n)
    L.append("| 正确题数 | %d |" % ok)
    L.append("| 正确率 | %s%% |" % fmt(pct(ok, n), 2))
    ec = collections.Counter(str(r.get("error_class") or ("正确" if r.get("correct") else "未标注"))
                             for r in recs)
    L.append("| 错误分类 | %s |" % safe("、".join("%s %d" % (k, v) for k, v in ec.most_common()), 300))
    if core:
        cm = {str(r.get("id")): r for r in core}
        inter = [r for r in recs if str(r.get("id")) in cm]
        if inter:
            won = sum(1 for r in inter if r.get("correct") and not cm[str(r.get("id"))].get("correct"))
            lost = sum(1 for r in inter if not r.get("correct") and cm[str(r.get("id"))].get("correct"))
            L.append("| 与 core 表配对（同题 %d） | 赢 %d / 输 %d / net %d |" % (len(inter), won, lost, won - lost))
    L.append("")
    return L


def sec_perq_time(recs):
    L = ["## 三、每题消耗的时间", ""]
    el = [_num_or_zero(r.get("elapsed_sec")) for r in recs]
    buckets = {"<450s": 0, "450–700s": 0, ">700s": 0}
    for r in recs:
        e = _num_or_zero(r.get("elapsed_sec"))
        if e < 450:
            buckets["<450s"] += 1
        elif e <= 700:
            buckets["450–700s"] += 1
        else:
            buckets[">700s"] += 1
    ok_b = collections.Counter()
    for r in recs:
        if r.get("correct"):
            e = _num_or_zero(r.get("elapsed_sec"))
            ok_b["<450s" if e < 450 else ("450–700s" if e <= 700 else ">700s")] += 1
    L.append("总计 %s ｜ 单题均值 %ss ｜ 中位 %ss ｜ 最长 %ss"
             % (hhmmss(sum(el)), fmt(sum(el) / len(el) if el else 0, 0),
                fmt(med(el), 0), fmt(max(el) if el else 0, 0)))
    L.append("")
    L.append("| 分时桶 | 题数 | 其中正确 | 正确率 |")
    L.append("|---|---|---|---|")
    for k in ("<450s", "450–700s", ">700s"):
        L.append("| %s | %d | %d | %s%% |" % (k, buckets[k], ok_b[k], fmt(pct(ok_b[k], buckets[k]))))
    L.append("")
    L.append("| 题号 | 耗时 | 头号阶段 | 该阶段占比 | 判定 | 候选数 |")
    L.append("|---|---|---|---|---|---|")
    for r in recs:
        st = _as_dict(r.get("diag")).get("stage_timers")
        top, tp = "—", 0.0
        if isinstance(st, dict) and st:
            k = max(st, key=lambda x: _num_or_zero(st[x]))
            top = k
            tp = pct(_num_or_zero(st[k]), sum(_num_or_zero(v) for v in st.values()))
        L.append("| %s | %s | %s | %s%% | %s | %d |" % (
            safe(r.get("id"), 40), hhmmss(r.get("elapsed_sec")), safe(top, 28),
            fmt(tp), "正确" if r.get("correct") else "错误",
            len(_as_list(r.get("candidates")))))
    L.append("")
    # ★ 2026-10-12 修：原文是**硬编码的 2026-09 旧结论**（「<450s 正确率最高、>700s
    #   基本为 0」），会被新数据直接反驳（本轮 10 题全在 >700s 桶、且有正确题）
    #   ⇒ 改为按本轮数据陈述 + 样本量告警，不再外推。
    _parts = ["%s %s%%（%d题）" % (k, fmt(pct(ok_b[k], buckets[k])), buckets[k])
              for k in ("<450s", "450–700s", ">700s") if buckets[k]]
    if _parts:
        L.append("> 本轮分时桶正确率：%s。样本量小，**不据此外推「延长求解时间有无收益」**"
                 "（判据见 skill §4.4：单次差异是噪声）。" % "、".join(_parts))
    else:
        L.append("> 本轮无分时数据。")
    L.append("")
    return L


def sec_stage_time(recs):
    L = ["## 四、各环节消耗的时间", ""]
    agg = collections.defaultdict(list)
    for r in recs:
        st = _as_dict(r.get("diag")).get("stage_timers")
        if isinstance(st, dict):
            for k, v in st.items():
                agg[k].append(_num_or_zero(v))
    if not agg:
        L.append("（本轮 diag 无 stage_timers，无法统计）")
        L.append("")
        return L
    total = sum(sum(v) for v in agg.values())
    keys = [k for k in STAGE_ORDER_test_report if k in agg] + [k for k in sorted(agg) if k not in STAGE_ORDER_test_report]
    L.append("| 阶段 | 累计 | 占比 | 中位 | 最大 | 非零题数 |")
    L.append("|---|---|---|---|---|---|")
    for k in keys:
        v = agg[k]
        nz = sum(1 for x in v if x > 0)
        L.append("| %s | %s | %s%% | %ss | %ss | %d/%d |" % (
            safe(k, 30), hhmmss(sum(v)), fmt(pct(sum(v), total)), fmt(med(v), 0),
            fmt(max(v), 0), nz, len(v)))
    L.append("")
    top = max(keys, key=lambda k: sum(agg[k]))
    zero = [k for k in keys if sum(agg[k]) == 0]
    L.append("- 头号阶段：**%s**（占比 %s%%）。" % (safe(top, 30), fmt(pct(sum(agg[top]), total))))
    if zero:
        L.append("- 全程零耗时阶段：%s（要么未被触发，要么被早退跳过）。" % safe("、".join(zero), 200))
    L.append("")
    return L


def sec_stage_error(recs, audit, judge):
    L = ["## 五、各环节哪里错了", ""]
    amap = {}
    for a in audit:
        amap[str(a.get("id"))] = a
    rows = []
    by_stage = collections.Counter()
    by_type = collections.Counter()
    src_tag = "DeepSeek 检错" if amap else "本地启发式"
    for r in recs:
        if r.get("correct"):
            continue
        rid = str(r.get("id"))
        a = amap.get(rid)
        if a:
            an = _as_dict(a.get("analysis"))
            st = str(an.get("error_stage") or "—")
            ty = str(an.get("error_type") or "—")
            note = str(an.get("root_cause") or "")
            gic = an.get("gold_in_candidates")
        else:
            st, ty, note, gic = local_attribution(r, judge)
        by_stage[st] += 1
        by_type[ty] += 1
        # ★ 2026-10-12 修（判读失真 #1 的配套）：统一渲染成 是/否/—。
        #   此前本地归因分支恒写 "—"，等于**该列一直是空的**却照下"求解失败"结论。
        gic_txt = "是" if gic is True else ("否" if gic is False else "—")
        rows.append((rid, st, ty, gic_txt, note))
    L.append("归因来源：**%s**（%d 道错题；DeepSeek 覆盖 %d 道，其余用本地启发式补齐）。"
             % (src_tag, len(rows), len(amap)))
    L.append("")
    L.append("### 按错误类型")
    L.append("")
    L.append("| 类型 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k, v in by_type.most_common():
        L.append("| %s | %d | %s%% |" % (safe(k, 30), v, fmt(pct(v, len(rows)))))
    L.append("")
    L.append("### 按错误环节")
    L.append("")
    L.append("| 环节 | 题数 | 占比 |")
    L.append("|---|---|---|")
    for k, v in by_stage.most_common():
        L.append("| %s | %d | %s%% |" % (safe(k, 40), v, fmt(pct(v, len(rows)))))
    L.append("")
    L.append("### 逐题归因")
    L.append("")
    L.append("| 题号 | 环节 | 类型 | gold 在候选池 | 根因（摘要） |")
    L.append("|---|---|---|---|---|")
    for rid, st, ty, gic, note in rows:
        L.append("| %s | %s | %s | %s | %s |" % (
            safe(rid, 36), safe(st, 34), safe(ty, 20), safe(gic, 12), safe(note, 200)))
    L.append("")
    return L, by_stage, by_type, rows


def sec_unmet(recs, vc):
    L = ["## 六、哪里没有达到预期目标", ""]
    n = len(recs)
    valid = [r for r in recs if classify_validity(r)[0] in ("clean", "degraded")]
    n_invalid = n - len(valid)
    L.append("### 机制触发普查（分母 = 有效题数 %d，而非总题数）" % len(valid))
    L.append("")
    if n_invalid:
        L.append("> ⚠ 本轮 **%d 题无效**（占位符 / 配额耗尽）。机制埋点的非空数天然不会超过有效题数，"
                 "因此本表的判读基准取「有效题数」，否则会得出「机制没触发」的假结论。"
                 % n_invalid)
        L.append("")
    L.append("| 机制 | 期望 | 全轮存在 | 有效题中非空 | 非空率 | 结论 | 说明 |")
    L.append("|---|---|---|---|---|---|---|")
    silent = []
    over = []
    for key, exp, desc in MECH_EXPECT:
        exist = 0
        for r in recs:
            if key in _as_dict(r.get("diag")):
                exist += 1
        nonempty = sum(1 for r in valid if _as_dict(r.get("diag")).get(key))
        ratio = pct(nonempty, len(valid)) if valid else 0.0
        if exp == "异常":
            verdict = "命中 %d 题" % nonempty if nonempty else "正常"
            if nonempty:
                over.append((key, nonempty, desc))
        elif exp == "必" and valid and ratio < 20.0:
            verdict = "★疑似未达预期"
            silent.append((key, nonempty, len(valid), desc))
        else:
            verdict = "—"
        L.append("| %s | %s | %d | %d | %s%% | %s | %s |" % (
            safe(key, 34), exp, exist, nonempty, fmt(ratio), verdict, safe(desc, 60)))
    L.append("")
    if silent:
        L.append("**疑似未达预期（必触发项在有效题中命中率 <20%%）**：")
        L.append("")
        for k, ne, nv, desc in silent:
            L.append("- `%s`（%s）：有效题 %d 题中仅 %d 题非空 —— 需逐项确认是「开关关着」"
                     "「门控不可达」还是「真的没触发」。" % (k, safe(desc, 40), nv, ne))
        L.append("")
    if silent:
        L.append("**疑似未达预期（必触发项却几乎为空）**：")
        L.append("")
        for k, ne, ex, desc in silent:
            L.append("- `%s`（%s）：存在 %d 题、非空仅 %d 题 —— 需逐项确认是「开关关着」"
                     "「门控不可达」还是「真的没触发」。" % (k, safe(desc, 40), ex, ne))
        L.append("")
    if over:
        L.append("**异常信号命中（>0 即需查）**：")
        L.append("")
        for k, ne, desc in over:
            L.append("- `%s`（%s）：%d 题命中。" % (k, safe(desc, 40), ne))
        L.append("")

    # 闸门有效性
    lg = collections.Counter()
    ag = collections.Counter()
    for r in recs:
        d = _as_dict(r.get("diag"))
        for g in _as_list(d.get("lean_gate")):
            if isinstance(g, dict):
                lg[str(g.get("verdict"))] += 1
        for g in _as_list(d.get("audit_gate")):
            if isinstance(g, dict):
                if g.get("step") == "candidate_audit":
                    ag[str(g.get("verdict"))] += 1
    L.append("### 闸门有效性")
    L.append("")
    L.append("| 闸门 | 判定分布 | 判读 |")
    L.append("|---|---|---|")
    tot = sum(lg.values())
    unk = lg.get("unknown", 0)
    L.append("| LeanGate | %s | %s |" % (
        safe("、".join("%s %d" % (k, v) for k, v in lg.most_common()), 120),
        ("★ unknown 占 %s%% ⇒ 该闸门基本没有判别力" % fmt(pct(unk, tot))) if tot and pct(unk, tot) > 80 else "有区分度"))
    tot2 = sum(ag.values())
    L.append("| AuditGate | %s | %s |" % (
        safe("、".join("%s %d" % (k, v) for k, v in ag.most_common()), 120),
        ("★ 恒 unknown ⇒ 对解答题结构性零输出" if tot2 and ag.get("unknown", 0) == tot2 else "有区分度")))
    L.append("")
    return L


def sec_tools(recs, env, log_path, ov, defs):
    L = ["## 七、哪些工具没有使用起来", ""]
    n = len(recs)
    tt = sum(len(_as_list(_as_dict(r.get("diag")).get("toolcall_text_detected"))) for r in recs)
    ls_calls = 0
    ls_capped = 0
    for r in recs:
        ls = _as_dict(_as_dict(r.get("diag")).get("leansearch"))
        ls_calls += int(_num_or_zero(ls.get("calls")))
        if ls.get("top_k_capped") is True:
            ls_capped += 1
    L.append("### 通道使用量")
    L.append("")
    L.append("| 通道 | 观测值 | 判读 |")
    L.append("|---|---|---|")
    L.append("| 工具调用被文本通道吞掉 | %d 条 | %s |" % (
        tt, "★ 存在被吞掉的调用（写了 <tool_call> 但原生 tool_calls 为空，未执行未回填）" if tt else "正常"))
    L.append("| LeanSearch 检索 | %d 次 | %s |" % (
        ls_calls, "★ 未调用" if ls_calls == 0 else "已调用"))
    L.append("| LeanSearch top_k 饱和题数 | %d / %d | %s |" % (
        ls_capped, n, "★ 命中数恒等于 top_k，检索未被有效利用" if ls_capped > 0.5 * n else "—"))
    L.append("")
    # ★ 2026-09-30（截图 #10）：**统一工具门面遥测**。
    #   用户诉求「调用工具的方法有没有写成规范性的类函数，需要 Lean 检测时
    #   直接调用，适配各阶段」⇒ 落地为 `agent/tool_gateway.py`。
    #   本表回答的是**另一个问题**：走门面的调用，**失败原因分布是什么**。
    #   口径红线（必须写在报告里，否则读者会把全零读成"没调用工具"）：
    #     本表只统计走 ToolGateway 的调用；既有调用点尚未全部迁移。
    gw_total = 0
    gw_by_tool: dict = {}
    gw_by_reason: dict = {}
    for r in recs:
        g = _as_dict(_as_dict(r.get("diag")).get("tool_gateway"))
        gw_total += int(_num_or_zero(g.get("total")))
        for k, v in (_as_dict(g.get("by_tool")) or {}).items():
            gw_by_tool[k] = gw_by_tool.get(k, 0) + int(_num_or_zero(v))
        for k, v in (_as_dict(g.get("by_reason")) or {}).items():
            gw_by_reason[k] = gw_by_reason.get(k, 0) + int(_num_or_zero(v))
    L.append("### 统一工具门面遥测（ToolGateway，2026-09-30 截图 #10）")
    L.append("")
    if gw_total == 0:
        L.append("本轮**没有调用走统一门面**（`agent/tool_gateway.py`）。")
        L.append("")
        L.append("> ⚠ 这**不等于**「本轮没调用工具」—— 既有调用点"
                 "（orchestrator 自建 LeanGate / answer_falsifier 自建 LeanBridge 等）"
                 "尚未全部迁移到门面，其调用量见上表。")
    else:
        L.append("门面累计调用 **%d** 次。**按工具**：" % gw_total)
        L.append("")
        L.append("| 工具 | 调用次数 |")
        L.append("|---|---|")
        for k, v in sorted(gw_by_tool.items(), key=lambda kv: -kv[1]):
            L.append("| %s | %d |" % (safe(k, 40), v))
        L.append("")
        L.append("**按原因码**（★ 归因关键：三态必须分开看）：")
        L.append("")
        L.append("| 原因码 | 次数 | 含义 | 该往哪修 |")
        L.append("|---|---|---|---|")
        _reason_cn = {
            "ok": ("成功", "—"),
            "disabled": ("配置开关关闭", "查 overrides，确认是否为预期关闭"),
            "unavailable": ("环境缺失（无 Lean / 无 mathlib）", "装环境，**不是**代码问题"),
            "not_applicable": ("题面不适用（豁免题）", "正常，交 AuditGate 兜底"),
            "budget": ("时间/预算不足未发起", "看是否被上游阶段吃光"),
            "timeout": ("发起了但超时", "调超时阈值或看 Lean 编译是否卡死"),
            "error": ("调用抛异常", "**查代码**（环境正常但调用炸了）"),
            "empty": ("调用成功但结果为空", "看输入是否为空/查询是否过窄"),
            "unknown": ("工具明确答复无法判定", "增强工具或换后端"),
            "reject": ("工具明确判否（如编译失败）", "看被否的具体内容"),
        }
        for k, v in sorted(gw_by_reason.items(), key=lambda kv: -kv[1]):
            _cn, _fix = _reason_cn.get(k, (k, "—"))
            L.append("| %s | %d | %s | %s |" % (safe(k, 24), v, _cn, _fix))
        L.append("")
        L.append("> **判读要点**：`unavailable` 与 `error` **修法完全相反** ——"
                 "前者是环境没装，后者是环境正常但代码调用出错。"
                 "把二者混为一谈会让优化方向走反。")
    L.append("")
    L.append("### 相关开关（**权威口径 = 日志 EvalEngine init 的 overrides**）")
    L.append("")
    L.append("只看 `.env` 会误判：多数开关是 AgentConfig 字段，不写进环境变量。")
    L.append("")
    L.append("| 开关 | 运行值 | 来源 | 影响的工具 |")
    L.append("|---|---|---|---|")
    for k, desc in TOOL_SWITCHES:
        if k in ov:
            v, src = str(ov[k]), "overrides"
        elif k in defs:
            v, src = str(defs[k]), "代码默认"
        else:
            v, src = "未设置", "—"
        flag = ""
        if v in ("False", "0", "None") and src != "—":
            flag = " ★关闭"
        L.append("| %s | %s%s | %s | %s |" % (
            k, safe(v, 20), flag, src, safe(desc, 46)))
    L.append("")
    if ov:
        L.append("本轮 overrides 共 %d 键；未列入 overrides 的开关按代码默认值执行。" % len(ov))
        L.append("")
    L.append("> 判读要点：「★关闭」且该开关确有代码读取点 ⇒ 对应工具在本轮**不可用**；"
             "但需先确认「是人为关闭」还是「门控不可达」，二者修法完全不同。"
             "另注意：**代码注释常与真实默认值脱节**，一律以本表运行值为准。")
    L.append("")
    if ov:
        L.append("### 本轮运行配置全量（日志 overrides，%d 键）" % len(ov))
        L.append("")
        L.append("| 上限类配置 | 运行值 | 说明 |")
        L.append("|---|---|---|")
        for k, desc in TOOL_LIMITS:
            v = str(ov[k]) if k in ov else (str(defs[k]) if k in defs else "未设置")
            L.append("| %s | %s | %s |" % (k, safe(v, 22), safe(desc, 46)))
        L.append("")
        L.append("| 键 | 值 |")
        L.append("|---|---|")
        for k in sorted(ov):
            L.append("| %s | %s |" % (safe(k, 40), safe(ov[k], 70)))
        L.append("")
    if log_path and os.path.exists(log_path):
        try:
            txt = io.open(log_path, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            txt = ""
        pats = [
            ("走 mcp", "Lean MCP 通道调用"),
            ("回落 bridge", "回落 bridge（应尽量为 0）"),
            ("ok=False", "MCP 返回 ok=False（Lean 编译错误，属正常语义）"),
            ("sorryAx", "检出 sorryAx"),
            ("hover", "hover 查证"),
            ("multi_attempt", "multi-attempt 找到策略"),
            ("限流", "限流提示"),
            ("LLM 调用失败", "LLM 调用失败"),
            ("-20080", "配额超限 -20080"),
            ("-20048", "请求过频 -20048"),
        ]
        if txt:
            L.append("### 日志侧证据")
            L.append("")
            L.append("| 事件 | 计数 |")
            L.append("|---|---|")
            for pat, label in pats:
                L.append("| %s | %d |" % (safe(label, 40), txt.count(pat)))
            L.append("")
    return L


def sec_reasoning_vs_calc(recs, judge, amap):
    L = ["## 八、大模型的推理错误与计算错误出在哪里", ""]
    ERRL = ["前提不成立", "循环论证", "方向反了", "方法不适用", "跳步"]
    reason_rows = []
    calc_rows = []
    by_label = collections.Counter()
    for r in recs:
        if r.get("correct"):
            continue
        d = _as_dict(r.get("diag"))
        ec = str(r.get("error_class") or "")
        et = _as_dict(d.get("error_types"))
        labels = [k for k, v in et.items() if _num_or_zero(v) > 0]
        for k in labels:
            by_label[k] += 1
        tt = len(_as_list(d.get("toolcall_text_detected")))
        if ec in ("value_wrong", "expr_wrong") or tt > 0:
            calc_rows.append((str(r.get("id")), ec or "—", tt))
        if labels:
            reason_rows.append((str(r.get("id")), "、".join(labels), ec or "—"))

    L.append("### 推理错误（策略层：方向、前提、方法、跳步）")
    L.append("")
    if by_label:
        L.append("| 错误标签 | 命中题数 |")
        L.append("|---|---|")
        for k, v in by_label.most_common():
            L.append("| %s | %d |" % (safe(k, 20), v))
        L.append("")
    else:
        L.append("（本轮未产出推理错误标签）")
        L.append("")
    L.append("| 题号 | 推理错误标签 | error_class |")
    L.append("|---|---|---|")
    for rid, lab, ec in reason_rows[:60]:
        L.append("| %s | %s | %s |" % (safe(rid, 36), safe(lab, 40), safe(ec, 20)))
    L.append("")

    L.append("### 计算错误（执行层：数值算错、运算未执行）")
    L.append("")
    L.append("| 题号 | error_class | 被吞掉的工具调用 |")
    L.append("|---|---|---|")
    for rid, ec, tt in calc_rows[:60]:
        L.append("| %s | %s | %d |" % (safe(rid, 36), safe(ec, 20), tt))
    L.append("")
    if calc_rows:
        L.append("> ★ 上表中「被吞掉的工具调用 > 0」的题，其计算错误**不是模型算错**，"
                 "而是**模型写了调用但工具没被执行**——属基础设施/通道问题，不是能力问题。")
        L.append("")

    L.append("### 求解 vs 选答（错题第一分诊）")
    L.append("")
    # ★ 2026-10-12 修（判读失真 #1 的配套）：原来**只有 DeepSeek 检错**（amap 非空）时
    #   才出这张分诊表；没跑检错时整节缺失，只留一句硬编码旧统计（且写成 `96.7%%`）。
    #   现改为：无 DeepSeek 时用**本地启发式**（与「五、逐题归因」同源）计算分诊。
    gic_false = gic_true = 0
    if amap:
        gic_false = sum(1 for a in amap.values()
                        if _as_dict(a.get("analysis")).get("gold_in_candidates") is False)
        gic_true = sum(1 for a in amap.values()
                       if _as_dict(a.get("analysis")).get("gold_in_candidates") is True)
        _src = "DeepSeek 检错"
    else:
        for r in recs:
            if r.get("correct"):
                continue
            _gic = local_attribution(r, judge)[3]
            if _gic is False:
                gic_false += 1
            elif _gic is True:
                gic_true += 1
        _src = "本地启发式（选择池 = diag.pick_diag.divergent_clusters）"
    L.append("分诊来源：**%s**。" % _src)
    L.append("")
    L.append("| 分诊 | 题数 | 含义 |")
    L.append("|---|---|---|")
    L.append("| gold 不在选择池 | %d | 求解失败：答案从未被算出 |" % gic_false)
    L.append("| gold 在选择池却答错 | %d | 选答/终答失败：算出来了却没用上 |" % gic_true)
    L.append("")
    L.append("> 这一分诊决定改进方向：前者要动求解与蓝图，后者才要动闸门与选答。"
             "（参考：历史三轮 150 道错题中约 96.7% 属「求解失败」—— 以**本轮**表为准。）")
    L.append("")
    return L


def sec_infra(recs, monitor, log_path):
    L = ["## 九、基础设施与资源", ""]
    if monitor and os.path.exists(monitor):
        try:
            rows = [l.strip().split(",") for l in io.open(monitor, encoding="utf-8", errors="replace") if l.strip()]
            hdr = rows[0]
            idx = {k: i for i, k in enumerate(hdr)}
            data = [r for r in rows[1:] if len(r) == len(hdr)]
            def col(name):
                return [_num_or_zero(r[idx[name]]) for r in data] if name in idx else []
            mem = col("mem_used_pct")
            avail = col("mem_avail_mb")
            sw = col("swap_used_mb")
            cpu = col("cpu_pct")
            lp = col("lean_procs")
            lr = col("lean_rss_mb")
            L.append("| 指标 | 峰值 / 最低 | 中位 | 判读 |")
            L.append("|---|---|---|---|")
            L.append("| 内存占用 | %s%% | %s%% | %s |" % (
                fmt(max(mem) if mem else 0), fmt(med(mem)),
                "非瓶颈" if mem and max(mem) < 80 else "★ 需关注"))
            L.append("| 可用内存最低 | %s MB | %s MB | — |" % (
                fmt(min(avail) if avail else 0, 0), fmt(med(avail), 0)))
            L.append("| swap 占用峰值 | %s MB | %s MB | %s |" % (
                fmt(max(sw) if sw else 0, 0), fmt(med(sw), 0),
                "正常" if sw and max(sw) < 200 else "★ 偏高"))
            L.append("| CPU 中位 | — | %s%% | 资源不是瓶颈 |" % fmt(med(cpu)))
            L.append("| lean 进程峰值 | %s | %s | — |" % (
                fmt(max(lp) if lp else 0, 0), fmt(med(lp), 0)))
            L.append("| lean RSS 峰值 | %s MB | %s MB | 累加值含共享页重复计 |" % (
                fmt(max(lr) if lr else 0, 0), fmt(med(lr), 0)))
            L.append("| 采样点数 | %d | — | — |" % len(data))
            L.append("")
        except Exception as e:  # noqa: BLE001
            L.append("（监控 CSV 解析失败：%s）" % safe(str(e), 120))
            L.append("")
    else:
        L.append("（无监控 CSV）")
        L.append("")

    # 失败信号
    n_err = 0
    q80 = q48 = 0
    to = 0
    for r in recs:
        tr = _as_list(r.get("trace"))
        for t in tr:
            if isinstance(t, dict) and t.get("step") == "llm_error":
                n_err += 1
        s = json.dumps(_as_dict(r.get("diag")), ensure_ascii=False)
        if "-20080" in s:
            q80 += 1
        if "-20048" in s:
            q48 += 1
        # ★ 2026-10-12 修（判读失真 #4）：原判据 `"timeout" in s.lower()` 是**整段 diag
        #   子串扫** —— 参数说明 / URL / note 里出现 "timeout" 都命中 ⇒ 本轮把 3/3 全
        #   误报成「疑似超时」（还与同表下方「日志侧 超时=0」自相矛盾）。
        #   改为结构化判定：trace 步骤名含 timeout、或穷尽检查 reason 明说超时。
        _steps = [str(_as_dict(t).get("step", "")).lower() for t in tr]
        _reason = str(_as_dict(_as_dict(r.get("diag")).get("exhaust_result")).get("reason") or "")
        if any("timeout" in x for x in _steps) or ("超时" in _reason):
            to += 1
    L.append("| 失败信号 | 题数 / 次数 |")
    L.append("|---|---|")
    L.append("| LLM 调用失败步（trace） | %d |" % n_err)
    L.append("| 出现配额超限 -20080 | %d 题 |" % q80)
    L.append("| 出现限流 -20048 | %d 题 |" % q48)
    L.append("| 疑似超时 | %d 题 |" % to)
    L.append("")
    if log_path and os.path.exists(log_path):
        try:
            txt = io.open(log_path, encoding="utf-8", errors="replace").read()
            L.append("| 日志计数 | 次数 |")
            L.append("|---|---|")
            for pat in ("-20080", "-20048", "LLM 调用失败", "超时", "MCP", "编译失败"):
                L.append("| %s | %d |" % (safe(pat, 20), txt.count(pat)))
            L.append("")
        except Exception:  # noqa: BLE001
            pass
    return L


def sec_conclusion(recs, vc, by_type, amap):
    L = ["## 十、结论与下一步", ""]
    n = len(recs)
    ok = sum(1 for r in recs if r.get("correct"))
    usable = vc.get("clean", 0) + vc.get("degraded", 0)
    L.append("1. 完成 %d 题、正确 %d 题（%s%%）；可用样本 %d 题（干净 %d、退化 %d）。"
             % (n, ok, fmt(pct(ok, n), 2), usable, vc.get("clean", 0), vc.get("degraded", 0)))
    if vc.get("invalid", 0) or vc.get("unknown", 0):
        L.append("2. ⚠ 本轮有 %d 题无效 / %d 题无法判定 ⇒ **正确率读数不可用作能力结论**，"
                 "应先修复基础设施再重跑。" % (vc.get("invalid", 0), vc.get("unknown", 0)))
    if by_type:
        top = by_type.most_common(1)[0]
        L.append("3. 错题主导类型：**%s**（%d 题，占错题的 %s%%）。"
                 % (safe(top[0], 20), top[1],
                    fmt(pct(top[1], sum(by_type.values())))))
    L.append("")
    L.append("> 本报告由 `cli/test_report.py` 自动生成，"
             "一次测试一个文档；文件名 = 日期-题目数量-正确的题数。")
    L.append("")
    return L
