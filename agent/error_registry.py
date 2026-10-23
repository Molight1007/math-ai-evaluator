# -*- coding: utf-8 -*-
"""错误指纹库：把每次跑出来的错误**结构化沉淀**，支撑两件事。

  ① **防复发**：新版本跑的时候，用历史错误签名去比对，一旦重现立刻报警。
  ② **回归判据**：拿历史错误的现场（run 目录）用新代码重跑对应阶段，
     看是否还犯同一个错 —— 比"跑整套 112 题"便宜两个数量级。

为什么用指纹
------------
同一个错误在不同题、不同数字下会以不同文字出现（`(m+n)D ≤ 777²`
与 `(m+n)D ≤ 888²` 是同一个错）。因此入库前先**归一化**：
去数字、去空白、统一符号、截断长串 —— 只保留"错误的形状"。

数据位置
--------
``results/_error_registry/registry.db``（sqlite，标准库，无第三方依赖）。

用法
----
    from agent.error_registry import record, query, stats, mark_fixed

    record(kind="obligation_invalid", signature="(m+n)D ≤ 777^2",
           stage="2.7_blueprint", qid="official112-008", run_id="val1_r1_1022",
           detail="代入 gold D=777² 得 m+n≤1，与 m<n 正整数矛盾",
           detector="gold_substitute", fix="义务生成后代入 gold 自检")
    stats()                      # 按类型统计
    query(status="open")         # 未修复的
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(_ROOT, "results", "_error_registry")
DB_PATH = os.path.join(DB_DIR, "registry.db")

# 错误类型登记表（新增类型必须登记，避免统计口径漂移）
KINDS = {
    "obligation_invalid": "义务/断言自相矛盾，或无法由题面推出",
    "false_reject": "正确候选被检测环节误杀",
    "false_accept": "错误候选被放行",
    "empty_output": "环节产出为空（模型空返回 / 解析成空）",
    "stage_inert": "机制被触发但零产出（开关/门空转）",
    "answer_leak": "蓝图/子目标锁死待求量（K11）",
    "tool_unavailable": "工具/环境不可用（Lean、检索等）",
    "silent_failure": "失败被包装成成功（ok=True 但无结果）",
    "timeout_hang": "超时漫长 / 卡死",
    "format_error": "答案形态不合法（含描述性文字等）",
    "subgoal_error": "子目标链的数值/量级/代换错误（第二模型复算检出）",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS errors (
    fingerprint TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    stage       TEXT,
    signature   TEXT,
    detail      TEXT,
    detector    TEXT,
    fix         TEXT,
    qid         TEXT,
    run_id      TEXT,
    status      TEXT DEFAULT 'open',
    n_occurrences INTEGER DEFAULT 1,
    first_seen  TEXT,
    last_seen   TEXT
);
CREATE INDEX IF NOT EXISTS idx_kind ON errors(kind);
CREATE INDEX IF NOT EXISTS idx_status ON errors(status);
CREATE INDEX IF NOT EXISTS idx_stage ON errors(stage);
"""

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")


def normalize(text: str, keep_len: int = 120) -> str:
    """把错误文本归一成"形状"：去数字、压空白、小写、截断。

    去数字是关键 —— 同类错误换个数字不该变成两条记录。
    """
    t = str(text or "").strip().lower()
    t = _NUM_RE.sub("#", t)
    t = _WS_RE.sub(" ", t)
    t = t.replace("$", "").replace("\\\\", "\\")
    return t[:keep_len]


def fingerprint(kind: str, signature: str) -> str:
    return hashlib.sha1(("%s|%s" % (kind, normalize(signature))).encode()) \
        .hexdigest()[:16]


def _connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.executescript(_SCHEMA)
    return conn


def record(kind: str, signature: str, *, stage: str = "", qid: str = "",
           run_id: str = "", detail: str = "", detector: str = "",
           fix: str = "") -> str:
    """记录一条错误（同指纹自动累加计数并刷新 last_seen）。返回指纹。"""
    if kind not in KINDS:
        raise ValueError("未登记的错误类型: %s（请在 KINDS 里登记）" % kind)
    fp = fingerprint(kind, signature)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.execute("SELECT n_occurrences, status FROM errors "
                           "WHERE fingerprint=?", (fp,))
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE errors SET n_occurrences=n_occurrences+1, last_seen=?, "
                "status=CASE WHEN status='fixed' THEN 'regressed' ELSE status END "
                "WHERE fingerprint=?", (now, fp))
        else:
            conn.execute(
                "INSERT INTO errors (fingerprint,kind,stage,signature,detail,"
                "detector,fix,qid,run_id,status,n_occurrences,first_seen,last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?,'open',1,?,?)",
                (fp, kind, stage, normalize(signature), detail[:1000],
                 detector, fix, qid, run_id, now, now))
        conn.commit()
    finally:
        conn.close()
    return fp


def query(kind: str = "", status: str = "", stage: str = "", limit: int = 200):
    """按条件查错误（返回 dict 列表）。"""
    sql = "SELECT * FROM errors WHERE 1=1"
    args = []
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if status:
        sql += " AND status=?"
        args.append(status)
    if stage:
        sql += " AND stage LIKE ?"
        args.append("%" + stage + "%")
    sql += " ORDER BY n_occurrences DESC, last_seen DESC LIMIT ?"
    args.append(int(limit))
    conn = _connect()
    try:
        cols = [d[0] for d in conn.execute(sql, args).description]
        return [dict(zip(cols, r)) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def mark_fixed(fp: str, note: str = "") -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE errors SET status='fixed', fix=? WHERE fingerprint=?",
                     (note or "fixed", fp))
        conn.commit()
    finally:
        conn.close()


def check(kind: str, signature: str) -> dict | None:
    """防复发检查：这个错误以前是否出现过？返回历史记录或 None。"""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM errors WHERE fingerprint=?",
                           (fingerprint(kind, signature),))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def stats() -> dict:
    """按类型 / 状态统计，供报告与看板使用。"""
    conn = _connect()
    try:
        by_kind = {r[0]: r[1] for r in conn.execute(
            "SELECT kind, COUNT(*) FROM errors GROUP BY kind").fetchall()}
        by_status = {r[0]: r[1] for r in conn.execute(
            "SELECT status, COUNT(*) FROM errors GROUP BY status").fetchall()}
        total = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        top = [dict(zip(("kind", "stage", "signature", "n_occurrences"),
                        r)) for r in conn.execute(
            "SELECT kind, stage, signature, n_occurrences FROM errors "
            "ORDER BY n_occurrences DESC LIMIT 10").fetchall()]
        return {"total": total, "by_kind": by_kind,
                "by_status": by_status, "top": top}
    finally:
        conn.close()


def seed_known_errors() -> int:
    """把 2026-10-22/23 全量测试中确认的错误写入库（幂等）。

    这些都是**有实证**的：现场在 `results/` 与 `D:/mathpilot_work/cloud_snap/`。
    """
    items = [
        dict(kind="obligation_invalid", signature="因此 (m+n)D \\le 777^2 不成立",
             stage="2.7_blueprint", qid="official112-008", run_id="val1_r1_1022",
             detail="义务 O5 断言 (m+n)D ≤ 777²，代入 gold D=777² 得 m+n ≤ 1，"
                    "与 m<n 正整数矛盾（应写作 |x_n²−x_m²| ≤ 777²）",
             detector="gold_substitute", fix="义务生成后代入 gold 做矛盾自检"),
        dict(kind="false_reject", signature="否定义务 O5 关键不等式 ⇒ 判逻辑错误淘汰",
             stage="4.1_self_audit", qid="official112-008", run_id="val1_r1_1022",
             detail="候选指出 O5 不成立（正确），4.1 按「必须满足义务」判错淘汰",
             detector="stage_probe", fix="候选反驳义务时标义务可疑，不直接判错"),
        dict(kind="answer_leak", signature="subgoal_merge_plan 直接写最终答案 \\boxed{...}",
             stage="2.7_subgoal", qid="official112-008", run_id="val1_r1_1022",
             detail="merge 产出 \\boxed{777²/2}，下游 3_solve 只是围绕它生成变体",
             detector="diag_scan", fix="merge 只输出路径，数值留给 3_solve"),
        dict(kind="silent_failure", signature="mcp run_code ok=True items=[] raw=Error executing tool",
             stage="4.4_math_check", qid="official112-008", run_id="val1_r1_1022",
             detail="Lean LSP 因 lake 不在 PATH 起不来，失败被包装成 ok=True",
             detector="cloud_repro", fix="PATH 加 lean bin；ok=True 且 items 空时按 raw 改判"),
        dict(kind="tool_unavailable", signature="Failed to start Lean language server: No such file or directory: 'lake'",
             stage="4.3_lean_check", qid="*", run_id="val1_r1_1022",
             detail="Lean 通道全程未工作，4.3/leansearch 全空",
             detector="cloud_repro", fix="deploy/cloud_run.env 加 PATH"),
        dict(kind="format_error", signature="候选 answer 是推理句/元话语（- 依赖：子问题1的上界）",
             stage="3_solve", qid="official112-008", run_id="val1_r1_1022",
             detail="6 个候选里 3 个 answer 不是答案",
             detector="stage_probe --dry-run", fix="require_answer_in_pool 已开，需查为何仍入池"),
        dict(kind="stage_inert", signature="leansearch calls=0 且 theorem_hint queries 是题干散句",
             stage="2.5_theorem_hint", qid="official112-008", run_id="val1_r1_1022",
             detail="检索查询从英文题干截句，且 stage_usage 为空，机制空转",
             detector="diag_scan", fix="查询从蓝图/子目标生成"),
        dict(kind="timeout_hang", signature="LLM_TIMEOUT=3330 导致单题 2h21m 零产出",
             stage="llm_client", qid="*", run_id="val3_r1_1022",
             detail="服务端不回时死等 55 分钟，且重试翻倍",
             detector="wchan+log", fix="LLM_TIMEOUT=900, RETRY=0"),
    ]
    n = 0
    for it in items:
        record(**it)
        n += 1
    return n


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        print("写入 %d 条已知错误" % seed_known_errors())
    s = stats()
    print("库: %s" % DB_PATH)
    print("总计 %d 条 | 状态 %s" % (s["total"], s["by_status"]))
    print("按类型:")
    for k, v in sorted(s["by_kind"].items(), key=lambda x: -x[1]):
        print("  %-22s %d" % (k, v))
    print("\nTop:")
    for it in s["top"]:
        print("  [%s] %-20s %s ×%d" % (it["kind"], it["stage"],
                                       str(it["signature"])[:60], it["n_occurrences"]))
