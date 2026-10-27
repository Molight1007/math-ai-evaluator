# -*- coding: utf-8 -*-
"""三体架构图生成器 —— 图上每个节点的状态与数字都从**当前产物**读，不手抄。

为什么要有生成器
================
手画的架构图必然过期：改一次代码，图上还是上周的状态；更糟的是没人知道
"图上说未实现"到底是真没写还是忘了改图。所以把「节点内容」写成数据、
把「节点状态」尽量从产物推（params.json / 账本 / 标定 / 候选目录），
每次 30 秒重出一次，图和代码就不会分叉。

输出：`docs/架构图_三体.html`（单文件、可点击钻取、支持搜索/深浅色/导出 SVG）。

用法
====
    python tools/gen_three_body_diagram.py
    python tools/gen_three_body_diagram.py --out /tmp/x.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "docs", "架构图_三体.html")

# ---------------------------------------------------------------- 视觉常量
W, LANE_W, LANE_H = 1620, 1540, 178
X0 = 40
BOX_H, GAP = 112, 40
COL = {"ok": "#2f9e44", "warn": "#e8a33d", "bad": "#e03131"}
LABEL = {"ok": "已落地", "warn": "部分", "bad": "未做"}


# ---------------------------------------------------------------- 产物探测
def _counts() -> dict:
    out = {"A": 0, "B": 0, "C": 0, "ctx": 0, "ledger": 0, "cands": 0,
           "cal": "无", "delta": None}
    try:
        with open(os.path.join(_ROOT, "params.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        out.update(A=d["counts"]["A"], B=d["counts"]["B"], C=d["counts"]["C"],
                   ctx=d["counts"].get("context_excluded", 0))
    except (OSError, ValueError, KeyError):
        pass
    led = os.path.join(_ROOT, "results", "_edit_ledger", "ledger.jsonl")
    if os.path.isfile(led):
        with open(led, encoding="utf-8") as fh:
            out["ledger"] = sum(1 for line in fh if line.strip())
    cdir = os.path.join(_ROOT, "results", "_candidates")
    if os.path.isdir(cdir):
        out["cands"] = len([f for f in os.listdir(cdir) if f.endswith(".json")])
    cal = os.path.join(_ROOT, "results", "_calibration", "gates.json")
    if os.path.isfile(cal):
        try:
            with open(cal, encoding="utf-8") as fh:
                d = json.load(fh)
            out["cal"] = d.get("source") or "?"
            out["delta"] = d.get("delta_pp")
        except (OSError, ValueError):
            out["cal"] = "损坏"
    return out


# ---------------------------------------------------------------- 节点内容
def lanes(c: dict) -> list:
    """六个泳道。状态是**当前代码/产物**的实况，不是设计意图。"""
    return [
        {"k": "L0", "c": "#5f6b85", "t": "L0 参数层 · 三者共享的地基（可 diff 的唯一表示）",
         "nodes": [
             {"t": "params.json", "s": "%d 条：A%d/B%d/C%d" % (c["A"] + c["B"] + c["C"], c["A"], c["B"], c["C"]),
              "st": "ok",
              "d": ["做什么：把散在四处的可编辑面抽成一份可 diff 的 JSON，候选就是它的 patch。",
                    "现状：已落地。tools/params_export.py 纯 AST 生成（不 import agent，守分层），"
                    "确定性输出（同一份代码两次导出逐字节相同），check --strict 零漂移。",
                    "为什么不是 777 条：另有 %d 处上下文硬编码切片，属代码不属值 —— "
                    "按 L0「只能存值」的口径刻意不内联（明细走 tools/eu_inventory.py --dim context）。" % c["ctx"],
                    "怎么用：跑评测时设 MP_PARAMS_JSON=<path>，注入层次 DEFAULT < 参数层 < CLI；"
                    "manifest 记 params_layer{sha,n_a,shadowed,dropped,env_win}。",
                    "三条硬失败：文件/schema 错、键不在白名单、注入后回读不一致 ⇒ 启动即崩（防测的是旧参数）。"]},
             {"t": "A·B·C 档位", "s": "A%d 机器可改 / B%d 需人改 / C%d 结构性" % (c["A"], c["B"], c["C"]),
              "st": "ok",
              "d": ["A 档 = 标量 + 已声明 + 在覆盖白名单 + **有真实读取点**（AST 判 x.name / \"name\" / name=，"
                    "并排除白名单与 SWITCHES 两处「登记≠读取」的自指）。",
                    "B 档 %d 个：63 提示词文本 + 8 记忆条目 + 9 个非标量结构值 + 1 个元开关（参数层自己的路径）。" % c["B"],
                    "C 档 %d 个：4 个工具模块 + smt_check（实现与签名）。" % c["C"],
                    "判定可复算：python tools/params_export.py show --why <key> 会打印它为什么在这一档。"]},
             {"t": "环节卡 14 张", "s": "输入 / 输出 / 五维 / 失败语义", "st": "ok",
              "d": ["做什么：每个阶段一张契约 —— 读 ctx 哪些字段、写哪些字段、五维各是什么、失败怎么处理。",
                    "现状：tools/stage_card.py 可从 AST 复算，docs/环节卡_v1.md 是它的产物（本地）。",
                    "⚠ 交代：stage_card.py 至今**未纳入 git**（10-25 建的）；本轮只补了它的依赖 eu_inventory.py。",
                    "为什么保留：定位粒度是「哪个环节的哪一维」，这是自动化闭环里 L2 的落点。"]},
             {"t": "参数注册表", "s": "SWITCHES ⊂ AgentConfig，两套登记仍在", "st": "warn",
              "d": ["现状：SWITCHES 121 个开关全部落在 AgentConfig 214 个字段里，反向仍有字段没进注册表。",
                    "已经有守卫：tests/test_switch_registry_four_way_guard.py 钉住「四处同步 + 默认值逐字一致」，"
                    "谁只改一处测试立刻变红。",
                    "决策口径已统一：谁能被机器改、改到什么域，一律看 params.json 的 A 段，不再两处各说一套。",
                    "未做：把两张表并成一张 —— 会动主链且收益低，先不动。"]},
         ]},
        {"k": "L1", "c": "#1d9e75", "t": "L1 主智能体 · 在线答题（本轮一行未改）",
         "nodes": [
             {"t": "题意理解 2.6", "s": "题型 / 领域 / problem_goal", "st": "ok",
              "d": ["做什么：判断题型与领域，产出 problem_goal 与 lean_applicable，供下游分流。",
                    "现状：在跑。无独立探针，出问题只能跑全链 —— 这是自动化最想补的一块。",
                    "本轮未动：L0 的三层注入对它是透明的（配置从 params.json 来，逻辑不变）。"]},
             {"t": "蓝图 DAG", "s": "倒推分解，禁止锁值", "st": "ok",
              "d": ["做什么：从目标倒推建 AND-OR 图，再交给子目标链求解。",
                    "关键约束：提示词已写死禁令 —— 不得在 merge_strategy / statement 写最终答案。",
                    "缺口：禁令**只有提示词约束，代码里没有后置校验**（dag_reviewer 只查简单化/可行/无循环）。",
                    "历史：曾以为锁值落在 merge_strategy，实测 98 份蓝图只命中 1 份 ⇒ 假设被数据推翻。"]},
             {"t": "子目标求解 2.7", "s": "17 模块 / 8065 行", "st": "ok",
              "d": ["做什么：把蓝图节点变成子目标，逐个求解后合并。",
                    "结构：subgoal_main_path 只有 57 行（薄壳），真实实现散在 sub_goal_solver* 系列。",
                    "历史归因：占 16/99（error_stage=2.7_subgoal_main）。",
                    "缺口：无独立探针，验证一次要跑全链（单题实测 ~1087 秒，重题到过 5.7 小时）。"]},
             {"t": "候选生成 3_solve", "s": "solver* 10 模块", "st": "ok",
              "d": ["做什么：生成候选解答池，是五道链的输入。",
                    "历史归因：错在 3_solve 最多（36/99），且 58.6% 的错题是 gold 根本没进池。",
                    "含义：主要瓶颈在「生成不出来」，不在「选错」。"]},
             {"t": "五道链 4.1–4.5", "s": "自审 / 证伪 / Lean / 计算 / 投票", "st": "ok",
              "d": ["做什么：五道非补偿审核 —— 4.1 自审逻辑、4.2 对抗证伪、4.3 Lean 代回、4.4 计算检测、4.5 投票。",
                    "现状：开关 five_gate_* 默认全 True；每道都有独立探针（tools/stage_probe.py --stage 4.x），分钟级可复跑。",
                    "这是全链最可实验的一段，也是唯一已有局部测试的地方。"]},
             {"t": "终答 6_format", "s": "形态校验 + 数值化（20 行）", "st": "warn",
              "d": ["做什么：把选中答案格式化为最终输出，做答案形态闸门与数值化。",
                    "现状：format_stage 仅 20 行，控制流一栏是空的 —— 唯一没有任何参数化的环节。",
                    "缺口：无探针、无开关，出问题查不到。"]},
         ]},
        {"k": "L2", "c": "#c2751a", "t": "L2 检测智能体 · 事后定位（4 节点里 1 个已落地）",
         "nodes": [
             {"t": "读一条轨迹摘要点", "s": "digest：一条轨迹 → 一段摘要", "st": "bad",
              "d": ["图形状：派只读小助手，只看一条出错轨迹，交回 ≤6000 字结构化摘要。",
                    "现状：**未做**。三个原因：① 强依赖 LLM + 真实轨迹，而轨迹只有云端评测在产；"
                    "② 只影响「提案提得准不准」，不影响闭环跑通；③ diag 各阶段字段形态不统一，"
                    "现在做出来的摘要只会是套话。",
                    "前置：先把分阶段产物粒度统一，再上 digest。"]},
             {"t": "把多份摘要归成问题", "s": "analyze：多份摘要 → 问题清单", "st": "bad",
              "d": ["图形状：汇总摘要 → 三类问题（丢分原因 / 缺的能力 / 对的做法），禁写题号与答案。",
                    "现状：**未做**，原因同上（依赖 digest 先成立）。",
                    "替代：目前「错在哪」靠 tools/analyze_errors.py 的自动归因（99 条历史），只到环节一级。"]},
             {"t": "看它猜得准不准", "s": "命中率 / 未预料的退步", "st": "ok",
              "d": ["做什么：提案时说会影响哪些题，事后核对 —— 真变了吗？有没有没料到反而变差的？",
                    "现状：**本轮落地** tools/attribution.py。输入预测 + 改动前后两份评测结果，"
                    "输出命中率、预测了但没变、**未预料的退步**（后者比命中率重要）。",
                    "题集不一致时只比共同题并显式报出来，不偷偷比较不同题集。",
                    "⚠ 待你定：提案器的 predicted_affected 现在是自然语言（R6 禁题号）⇒ 无法机核；"
                    "建议拆成 predicted_domains（按领域机核）+ predicted_note（人看）。"]},
             {"t": "定位到具体参数", "s": "哪个环节 → 哪一类 → 哪个参数", "st": "warn",
              "d": ["图形状：三级定位（14 个阶段 → 五维 → 具体 EU）。",
                    "现状：只有**第一级**能算（错题归因里 76/99 能定到阶段）；五维 0 条、EU 0 条。",
                    "已备件：EU 表 757 个单元（tools/eu_inventory.py）+ 14 张环节卡，缺的是「错题 → 五维」这一跳。"]},
         ]},
        {"k": "L3", "c": "#6b4fbb", "t": "L3 自迭代智能体 · 只提案（不评测、不判准入、不碰 B/C 档）",
         "nodes": [
             {"t": "读账本", "s": "历史 / 未试清单 / 剪枝目标（%d 条）" % c["ledger"], "st": "warn",
              "d": ["做什么：读每次改动的组件/假设/ΔS/ΔC/是否采纳/拒绝原因，以及从未改过的参数。",
                    "现状：tools/edit_ledger.py 已建且升到 v2（bundle / outcome / 未测量区分），"
                    "但**账本仍是空的：%d 条**。没有任何一次真实改动被记过。" % c["ledger"],
                    "含义：提案器现在只能凭「未试清单」提，没有历史可参考 —— 这一项要等第一次真实闭环。"]},
             {"t": "提案", "s": "只出 A 档候选（critic 回喂 3 轮）", "st": "warn",
              "d": ["做什么：读 A 段（含值域）+ 账本状态 + 未试清单 → LLM 出候选 JSON。",
                    "现状：**代码就绪** tools/propose.py。出完先过 critic，被拒就把违规回喂重提（有界 3 轮）。",
                    "⚠ 诚实交代：真 LLM 路径**一次都没跑过**，只用 --dry-run 的确定性桩验证过链路；"
                    "本地没配 OPENAI_BASE_URL / LLM_MODEL。",
                    "可看提示词：python tools/propose.py --print-prompt（21.6 KB，含 205 个键与值域）。"]},
             {"t": "候选 = JSON diff", "s": "落 results/_candidates（当前 %d 份）" % c["cands"], "st": "warn",
              "d": ["做什么：候选不是代码改动，是 params.json 的 patch，可 diff、可回滚、可被 critic 秒审。",
                    "现状：机制就绪（含 bundle 记「一个候选捆了几个 edit」），但**没有产出过真实候选**"
                    "（results/_candidates 当前 %d 份）。" % c["cands"],
                    "组件标签由 JSON key 天然给出 ⇒ 不需要 RRSI 那套「从代码 diff 猜组件」的逻辑。"]},
         ]},
        {"k": "L4", "c": "#3d7eff", "t": "L4 判定层 · 提案者不是选择者（critic → 评测 → δ → 四道门）",
         "nodes": [
             {"t": "critic 三条硬规则", "s": "白名单 / 值域 / 禁题号答案", "st": "ok",
              "d": ["现状：**已落地** contracts/params_guard.py。确定性、毫秒级、不花钱（结构化编辑面才有这待遇）。",
                    "R1 key 必须在 A 段（发明参数注进去也会被白名单静默丢弃 ⇒ 假 A/B）。",
                    "R2 类型一致（显式区分 bool 与 int）+ 语义域：205 个 A 键里 195 个有语义域"
                    "（温度 [0,2]、比例/置信度 [0,1]、计数 ≥0）；另卡 JSON 形状（有字段声明成 str 其实存 JSON）。",
                    "R3 禁题号/标准答案/数据集痕迹；正常中文描述里的「答案」不误杀。17 条守卫测试。"]},
             {"t": "评测 k 次", "s": "缺失 trial 记 0、infra 单列", "st": "warn",
              "d": ["做什么：在题库子集上跑候选，得到 Ŝ 与 Ĉ。",
                    "现状：**聚合口径已落地** contracts/trials.py —— 缺失 trial 记 r=0 且分母不减"
                    "（否则少跑几题就能抬均分）、基础设施失败整题剔除并单列、pass@k 与 pass^k 分开报。",
                    "缺口：run_eval 仍然 k=1 ⇒ 口径就绪、**数据没有**。要让 k≥2 得改 run_eval，成本 ×k。"]},
             {"t": "δ 校准", "s": "δ = z × sd(null ΔS)，z=2", "st": "warn",
              "d": ["做什么：反复评测**未改动的**基线，用两次评测的散布定噪声带。",
                    "现状：**工具已落地** tools/calibrate.py（N 次重复，或单次+题内 bootstrap），"
                    "写 gates.json 时 δ 标 source=measured、β 标 beta_source=rrsi-borrowed（两者不许混为一谈）。",
                    "缺口：**δ 数值没有**。当前 results/_calibration 不存在（标定来源：%s）。" % c["cal"],
                    "不做的后果：四道门第一道是空的，所有「涨了 3 分」都分不清是改进还是抖动。"]},
             {"t": "四道门", "s": "floor → cost → guard → argmax", "st": "ok",
              "d": ["现状：**已落地** contracts/selection.py + tools/gates.py，16 条守卫。",
                    "顺序硬约束：① 噪声地板 S' ≥ S*−δ（不过直接拒，后面不看）② 成本规则 "
                    "（ΔS>δ 用 ΔC ≤ β0+β1·ΔS；ΔS≤δ 用 w_s·ΔS−w_c·ΔC+w_n·ν>0）③ 领域守卫（可插入纯函数，"
                    "没给记 skipped）④ argmax 按 (ΔS,−ΔC,ν) 字典序，不用加权和。",
                    "★ 现在的实际行为：δ 未标定 ⇒ **拒绝一切候选**（这是刻意的，防给后续轮次喂噪声）。",
                    "β1 单位是「每 +1pp 允许加百分之几成本」，分与 pp 差 100 倍，抄错会放松 100 倍。"]},
         ]},
        {"k": "L5", "c": "#5f6b85", "t": "L5 账本与回灌 · 一编辑一行 + 更新单元有效性",
         "nodes": [
             {"t": "一编辑一行", "s": "bundle / outcome / 未测量区分", "st": "ok",
              "d": ["现状：**已落地**，schema 升到 edit_ledger/2。",
                    "一条 edit 一行（不是一候选一行）：一个候选捆 3 个编辑就写 3 行，共享同一组 ΔS/ΔC，另存 bundle=3。",
                    "未测量区分：gate 失败（critic 拒 / smoke 失败 / 评测无效）记 delta_metric=None ⇒ UNMEASURED，"
                    "**不进已试集、不进收益窗口、不算接受率分母**。",
                    "measured 由 delta_metric is not None 派生（两处存真值必漂移）。v1 老记录读时自动补齐。"]},
             {"t": "回灌", "s": "effective / ineffective / untested / untried", "st": "ok",
              "d": ["现状：**本轮落地** tools/backfill.py。账本 → 每单元状态，喂回下一轮提案。",
                    "四态：已测且被采纳 = effective；测过但都没采纳 = ineffective（剪枝候选，关闭不删）；"
                    "只有 gate 失败 = untested（重新排队，**不算试过**）；无记录 = untried（探索配额）。",
                    "★ 与图上原说法不同：**不回写 params.json**，改写 results/_edit_ledger/effectiveness.json —— "
                    "params.json 是 params_export 的生成物，只能有一个写者，否则下次 build 就冲掉。",
                    "当前：A 段 %d 个单元全部 untried（账本 0 条）。" % c["A"]]},
         ]},
    ]


# ---------------------------------------------------------------- 渲染
def _wrap(text: str, max_units: int) -> list:
    """按显示宽度折行（中文算 2，ASCII 算 1），最多 3 行。"""
    def units(s):
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)
    lines, cur = [], ""
    for ch in text:
        if units(cur + ch) > max_units and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def render(c: dict) -> str:
    data = lanes(c)
    n_all = sum(len(l["nodes"]) for l in data)
    n_ok = sum(1 for l in data for nd in l["nodes"] if nd["st"] == "ok")
    n_warn = sum(1 for l in data for nd in l["nodes"] if nd["st"] == "warn")
    n_bad = n_all - n_ok - n_warn

    parts = []
    add = parts.append
    add('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    add('<meta name="viewport" content="width=device-width,initial-scale=1">')
    add('<title>MathPilot 三体架构（按代码现状重画）</title><style>')
    add(":root{--bg:#fff;--ink:#1f2430;--mut:#7b8499;--panel:#f6f8fb;--line:#e3e7ee;--accent:#3d7eff}")
    add("body.dark{--bg:#0e1420;--ink:#e8eefc;--mut:#8a97b4;--panel:#151d2c;--line:#26314a;--accent:#4cc9f0}")
    add("*{box-sizing:border-box}")
    add("body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,"
        "BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}")
    add("#bar{position:sticky;top:0;z-index:9;display:flex;gap:8px;align-items:center;padding:10px 16px;"
        "background:var(--panel);border-bottom:1px solid var(--line)}")
    add("#bar input,#bar button{font:inherit;font-size:13px;padding:6px 10px;border-radius:8px;"
        "border:1px solid var(--line);background:var(--bg);color:var(--ink)}")
    add("#bar input{cursor:text;min-width:220px}#bar button{cursor:pointer}#bar button:hover{border-color:var(--accent)}")
    add(".sp{flex:1}")
    add("#hint{padding:8px 16px;font-size:12.5px;color:var(--mut);border-bottom:1px solid var(--line)}")
    add("#main{display:flex;align-items:flex-start}")
    add("#wrap{flex:1;overflow:auto;padding:10px 16px 40px}")
    add("svg{max-width:100%;height:auto;display:block}")
    add("#side{width:360px;flex:0 0 360px;border-left:1px solid var(--line);background:var(--panel);"
        "padding:16px;position:sticky;top:49px;max-height:calc(100vh - 49px);overflow:auto}")
    add("#side h3{margin:0 0 6px;font-size:15px;font-weight:600}")
    add("#side .tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;margin-bottom:10px}")
    add("#side ul{margin:8px 0 0;padding-left:18px}#side li{margin:6px 0;font-size:13px}")
    add(".node{cursor:pointer}.node .nb{transition:stroke-width .12s}")
    add(".node:hover .nb{stroke-width:2.4}.node.sel .nb{stroke-width:3;stroke:var(--accent)}")
    add("svg.dim .node{opacity:.22}svg.dim .node.hit{opacity:1}.nlabel{font-weight:600}")
    add("</style></head><body>")
    add('<div id="bar"><input id="q" placeholder="搜索节点…（输入即高亮）"><span class="sp"></span>'
        '<button id="theme">深浅色 T</button><button id="exp">导出 SVG E</button></div>')
    add('<div id="hint"><b>怎么读</b>：六条泳道自上而下 = L0 参数层 → L1 主智能体 → L2 检测 → L3 自迭代 → '
        'L4 判定 → L5 账本。右上角圆点 = <b style="color:#2f9e44">●</b> 已落地　'
        '<b style="color:#e8a33d">●</b> 部分　<b style="color:#e03131">●</b> 未做。'
        '<b>点任意节点 → 右侧看详情</b>（做什么 / 现状 / 缺口 / 实测数字）。</div>')

    lane_y = 118
    lanes_y = []
    for ln in data:
        lanes_y.append(lane_y)
        lane_y += LANE_H + 8
    height = lanes_y[-1] + LANE_H + 40

    add('<div id="main"><div id="wrap">')
    add('<svg id="dg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif">' % (W, height))
    add('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8b94a7"/></marker></defs>')
    add('<rect width="%d" height="%d" fill="#fbfcfe"/>' % (W, height))
    add('<text x="40" y="42" font-size="20" font-weight="700" fill="#1f2430">'
        'MathPilot 三体架构 · 修订 3（按代码现状重画，2026-10-27）</text>')
    add('<text x="40" y="68" font-size="12.5" fill="#7b8499">'
        'L1 答题 ｜ L2 定位 ｜ L3 只提案 ｜ L4 判准入 ｜ L0 与 L5 是共享地基　·　'
        '%d 节点：<tspan fill="#2f9e44" font-weight="600">%d 已落地</tspan> ｜ '
        '<tspan fill="#e8a33d" font-weight="600">%d 部分</tspan> ｜ '
        '<tspan fill="#e03131" font-weight="600">%d 未做</tspan> ｜ '
        '<tspan fill="#e03131" font-weight="600">真实闭环 0 次</tspan>　'
        '（账本 %d 条 · 候选 %d 份 · δ %s）</text>'
        % (n_all, n_ok, n_warn, n_bad, c["ledger"], c["cands"],
           "已标定" if c["delta"] else "未标定"))

    for ln, ly in zip(data, lanes_y):
        add('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" fill-opacity="0.06"/>'
            % (X0, ly, LANE_W, LANE_H, ln["c"]))
        add('<rect x="%d" y="%d" width="4" height="%d" rx="2" fill="%s"/>' % (X0, ly, LANE_H, ln["c"]))
        add('<text x="%d" y="%d" font-size="13" font-weight="600" fill="%s">%s</text>'
            % (X0 + 16, ly + 24, ln["c"], ln["t"]))

        nodes = ln["nodes"]
        n = len(nodes)
        bw = min(220.0, (LANE_W - GAP * (n - 1) - 20) / n)
        total = bw * n + GAP * (n - 1)
        x = X0 + (LANE_W - total) / 2
        for nd in nodes:
            bx, by = round(x, 1), ly + 44
            col = COL[nd["st"]]
            detail = "|".join(nd["d"]).replace('"', "&quot;")
            add('<g class="node" data-t="%s" data-s="%s" data-st="%s" data-d="%s" data-c="%s">'
                % (nd["t"], nd["s"], nd["st"], detail, col))
            add('<rect class="nb" x="%s" y="%d" width="%s" height="%d" rx="9" fill="#ffffff" '
                'stroke="%s" stroke-width="1.4"/>' % (bx, by, round(bw, 1), BOX_H, col))
            add('<circle cx="%s" cy="%d" r="4.5" fill="%s"/>' % (round(bx + bw - 22, 1), by + 14, col))
            add('<text class="nlabel" x="%s" y="%d" font-size="13.5" fill="#1f2430">%s</text>'
                % (round(bx + 14, 1), by + 30, nd["t"]))
            # 11.5px 字号下：1 个 ASCII 单位 ≈ 5.75px（中文占 2 单位 ≈ 11.5px）
            for i, line in enumerate(_wrap(nd["s"], int((bw - 28) / 5.75))):
                add('<text x="%s" y="%d" font-size="11.5" fill="#6b7488">%s</text>'
                    % (round(bx + 14, 1), by + 52 + i * 18, line))
            add('<text x="%s" y="%d" font-size="11.5" font-weight="600" fill="%s">%s</text>'
                % (round(bx + 14, 1), by + 98, col, nd.get("label") or LABEL[nd["st"]]))
            add("</g>")
            x += bw + GAP

    for i in range(len(lanes_y) - 1):
        y1 = lanes_y[i] + LANE_H
        add('<line x1="810" y1="%d" x2="810" y2="%d" stroke="#8b94a7" stroke-width="1.6" '
            'marker-end="url(#ah)"/>' % (y1, y1 + 8))
    add("</svg></div>")

    add('<div id="side"><h3>点一个节点</h3>'
        '<div class="tag" style="background:#eef2f8;color:#7b8499">详情会显示在这里</div>'
        '<p style="font-size:13px;color:#7b8499">绿=已落地，黄=部分/待补，红=未做。'
        '所有数字由 <code>tools/gen_three_body_diagram.py</code> 从 params.json / 账本 / 标定 / 候选目录现读。</p></div></div>')

    add("<script>")
    add("const side=document.getElementById('side'),svg=document.getElementById('dg');")
    add("document.querySelectorAll('.node').forEach(n=>{n.addEventListener('click',()=>{")
    add("document.querySelectorAll('.node').forEach(x=>x.classList.remove('sel'));n.classList.add('sel');")
    add("const d=n.dataset,parts=d.d.split('|');")
    add("side.innerHTML='<h3>'+d.t+'</h3>'")
    add("+'<div class=\"tag\" style=\"background:'+d.c+'1a;color:'+d.c+'\">'+d.s+'　·　'+d.st+'</div>'")
    add("+'<ul>'+parts.map(p=>'<li>'+p+'</li>').join('')+'</ul>';});});")
    add("const q=document.getElementById('q');q.addEventListener('input',()=>{")
    add("const v=q.value.trim();")
    add("if(!v){svg.classList.remove('dim');document.querySelectorAll('.node').forEach(n=>n.classList.remove('hit'));return;}")
    add("svg.classList.add('dim');document.querySelectorAll('.node').forEach(n=>{")
    add("const hit=(n.dataset.t+n.dataset.s+n.dataset.d).includes(v);n.classList.toggle('hit',hit);});});")
    add("document.getElementById('theme').onclick=()=>document.body.classList.toggle('dark');")
    add("document.getElementById('exp').onclick=()=>{const b=new Blob([svg.outerHTML],{type:'image/svg+xml'});")
    add("const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='三体架构.svg';a.click();};")
    add("</script></body></html>")
    return "\n".join(parts), (n_all, n_ok, n_warn, n_bad)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 docs/架构图_三体.html")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    c = _counts()
    html, stat = render(c)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html + "\n")
    print("已生成 %s" % args.out)
    print("  节点 %d：已落地 %d ｜ 部分 %d ｜ 未做 %d" % stat)
    print("  产物读数：账本 %d 条 ｜ 候选 %d 份 ｜ δ %s"
          % (c["ledger"], c["cands"], c["delta"] or "未标定"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
