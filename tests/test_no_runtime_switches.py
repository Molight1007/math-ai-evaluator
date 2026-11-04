# -*- coding: utf-8 -*-
"""零开关门禁 —— 证明「118 个开关已收敛、之后不准再引入」。

替代关系（不是删测试掩盖失败，是测的对象换了）
================================================
  test_switch_registry_four_way_guard.py   四表同步        → 本文件：唯一权威 POLICY
  test_switch_lifecycle_guard.py           出口制/到期日   → 本文件：临时版本处置表
  test_switch_env_bridge.py                env→config 桥   → 本文件：禁止 env 读开关键
  test_decouple_stage_a_1007.py            shim re-export  → 本文件：禁止 import 已删模块

★ 扫描用 tokenize 跳过注释与 docstring：历史沿革文字允许保留作论证史料，
  但**任何活代码**里出现开关读取器/注册层即红。
"""
from __future__ import annotations

import io
import json
import os
import re
import tokenize
from pathlib import Path
from types import MappingProxyType

from contracts.policy import POLICY

ROOT = Path(__file__).resolve().parents[1]
LEDGER = json.loads((ROOT / "contracts" / "policy_ledger.json").read_text(
    encoding="utf-8"))
ITEMS = {x["field"]: x for x in LEDGER["items"]}
FIX = {k for k, v in ITEMS.items() if v["decision"] == "FIX"}

# 活代码里禁止出现的符号（注册表读者 / 注册层 / 覆盖链 / 兜底封装）
FORBIDDEN = re.compile(
    r"\b(?:get_bool|get_num|get_str|bind_config|bind_field|"
    r"apply_env_to_config|source_of|switch_registry|switch_lifecycle|"
    r"SWITCHES|LIFECYCLE|_CONFIG_OVERRIDE_KEYS|_sw_bool_or|_sw_num_or)\b")

SCAN_DIRS = ("agent", "utils", "contracts", "tools", "deploy", "cli")
SKIP_PARTS = ("__pycache__", ".git", "outputs", ".workbuddy", "tests")


def _prod_files():
    out = []
    for sub in SCAN_DIRS:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if any(x in p.parts for x in SKIP_PARTS):
                continue
            out.append(p)
    for p in ROOT.glob("*.py"):
        if p.name.startswith("replay_"):     # 评估床也扫，避免两套口径
            out.append(p)
        elif p.name.startswith("test_"):
            continue
        else:
            out.append(p)
    return sorted(set(out))


def _code_lines(path):
    """返回 (行号, 行文本)，跳过注释/字符串 token 覆盖的行。"""
    src = path.read_text(encoding="utf-8", errors="ignore")
    skip = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                for n in range(tok.start[0], tok.end[0] + 1):
                    skip.add(n)
    except (tokenize.TokenError, IndentationError):
        pass
    return [(i, ln) for i, ln in enumerate(src.splitlines(), 1)
            if i not in skip and ln.strip()]


def _eq(a, b):
    """台账是 JSON（只能存 list），策略表用 tuple 锁死不可变 ⇒ 按序列语义比。"""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return tuple(a) == tuple(b)
    return a == b


def test_policy_is_readonly_and_matches_ledger():
    """唯一权威表必须只读，且键集合恰好等于台账里 FIX 的 101 项。"""
    assert isinstance(POLICY, MappingProxyType)
    assert set(POLICY) == FIX, (
        "POLICY 与台账不一致 —— 新增策略项必须先写论证并登记台账")
    assert len(POLICY) == 101
    for k, v in POLICY.items():
        assert _eq(v, ITEMS[k]["effective"]), "%s 值偏离论证结论" % k


def test_no_switch_reader_in_live_code():
    """活代码里不得再有注册表读取器 / 注册层 / 覆盖链。"""
    bad = []
    for p in _prod_files():
        for i, ln in _code_lines(p):
            if FORBIDDEN.search(ln):
                bad.append("%s:%d: %s" % (p.relative_to(ROOT), i, ln.strip()[:110]))
    assert not bad, "发现开关残留：\n" + "\n".join(bad[:30])


def test_no_env_reads_switch_keys():
    """不得用环境变量改变任何历史开关的行为。"""
    env_keys = {v["env_key"] for v in ITEMS.values()}
    pat = re.compile(r"os\.environ(?:\.get|\[)|os\.getenv")
    bad = []
    for p in _prod_files():
        for i, ln in _code_lines(p):
            if pat.search(ln) and any(k in ln for k in env_keys):
                bad.append("%s:%d: %s" % (p.relative_to(ROOT), i, ln.strip()[:110]))
    assert not bad, "发现 env 覆盖行为：\n" + "\n".join(bad[:30])


def test_policy_is_never_written():
    """运行期不允许写回策略表（含 update / setdefault / del）。"""
    bad = []
    for p in _prod_files():
        if p == ROOT / "contracts" / "policy.py":
            continue        # 唯一定义处，不算「运行期写回」
        for i, ln in _code_lines(p):
            if re.search(r"POLICY\s*(?:\[[^\]]+\]\s*=|\.update\(|\.setdefault\(|=)", ln) \
                    or re.search(r"del\s+POLICY\[", ln):
                bad.append("%s:%d: %s" % (p.relative_to(ROOT), i, ln.strip()[:110]))
    assert not bad, "发现写回：\n" + "\n".join(bad[:30])


def test_dropped_items_left_no_registration():
    """DELETE / REMOVE_FEATURE 项不得残留在四表宿主里。"""
    dropped = {k for k, v in ITEMS.items() if v["decision"] != "FIX"}
    hosts = [ROOT / "user_agent__config.py", ROOT / "user_agent__config_base.py",
             ROOT / "user_agent.py", ROOT / "agent" / "param_usage.py"]
    # 只看「登记形态」：字段声明 / 白名单 token / _SPEC 条目首行。
    # 历史注释里提到旧名字属论证史料，不算残留登记。
    token_pats = [
        (k, re.compile(r'["\']%s["\']|^\s*\("%s",' % (re.escape(k), re.escape(k)), re.M))
        for k in dropped
    ]
    bad = []
    for p in hosts:
        lines = p.read_text(encoding="utf-8").splitlines()
        for k, pat in token_pats:
            for i, ln in enumerate(lines, 1):
                s = ln.strip()
                if s.startswith("#") or s.startswith('"""'):
                    continue
                if pat.search(ln) or re.match(r"^\s*%s\s*:" % re.escape(k), ln):
                    bad.append("%s:%d 仍登记 %s" % (p.relative_to(ROOT), i, k))
                    break
    assert not bad, "已删项仍留尾巴：\n" + "\n".join(bad[:30])


def test_every_temporary_version_is_disposed():
    """★ 临时版本必须证明「回退 / 应用 / 删除」三者之一，不许留尾巴。"""
    rows = LEDGER["temporary_versions"]
    allowed = {"applied", "removed", "reverted", "out_of_tree"}
    assert rows
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), "临时版本登记重复（同一事项只准一条结论）"
    for r in rows:
        assert r.get("disposition") in allowed, "临时版本未处置：%s" % r.get("name")
        assert str(r.get("evidence") or "").strip(), "临时版本缺证据：%s" % r.get("name")
    # 同一事项不许同时存在「回退」与「应用」两条互相矛盾的结论
    fr = [r for r in rows if r["name"].startswith("FIVE_GATE_REWRITE")]
    assert len(fr) == 1 and fr[0]["disposition"] == "applied", \
        "4.6 关闭只保留一条 applied 结论（10-31 决策，434 题次证据）"


def test_server_verification_is_recorded():
    """服务器真实数据上的留出集复核必须存在且干净，防止只在本地自证。"""
    sv = LEDGER["validation"]["server_verification"]
    rep = sv["replay_on_server_data"]
    assert rep["verdict"] == "NO_UNEXPLAINED_DIFF"
    assert rep["rc"] == 0
    assert rep["unexplained_value_diffs"] == []
    assert rep["unexplained_legacy_fields"] == []
    assert rep["rows"] == LEDGER["validation"]["report"]["rows"], \
        "本地与服务器用了不同题次数，不能互相印证"
    assert sv["deleted_modules_not_importable"] is True
    assert sv["cloud_run_env_rewrite_export_removed"] is True


def test_every_item_has_a_decision_and_rationale():
    """118 个开关逐条有结论与理由，不允许「暂时保留」。"""
    assert len(ITEMS) == 118
    for k, v in ITEMS.items():
        assert v["decision"] in {"FIX", "DELETE", "REMOVE_FEATURE"}, k
        assert str(v.get("rationale") or "").strip(), k
        assert "暂时保留" not in v["rationale"], k


# ---------------------------------------------------------------- 防过拟合门禁
# 用户口径：「结果不能只根据分数评判」。这里锁死的是**验证协议本身**：
# 留出集、分层、单变量对照、人工抽验、零无解释差异，缺一即红。
def test_holdout_protocol_is_recorded_and_clean():
    """留出集报告必须存在、分层、有人工抽验，且无无解释差异。"""
    val = LEDGER["validation"]
    rep = val["report"]
    assert rep["verdict"] == "NO_UNEXPLAINED_DIFF", "留出集仍有未解释差异"
    assert rep["unexplained_value_diffs"] == []
    assert rep["unexplained_legacy_fields"] == []
    assert rep["rows"] == rep["dev_rows"] + rep["holdout_rows"]
    assert rep["holdout_rows"] > 0, "没有留出集就不能声称做了等价性验证"
    assert len(rep["strata_10_15"]) == 2, "必须按 10-15 分层，不许平均成一个数"
    assert rep["manual_spot_check_count"] >= 8, "判据改动必须配人工抽验"
    assert rep["holdout_match_rate"] > rep["holdout_match_rate_before_fix"], \
        "单变量对照没有体现修正效果，须复核修正依据是否真是结构证据"
    principles = " ".join(val["principle"])
    assert "回归通过数不是效果量" in principles
    assert "留出集不参与取值决策" in principles


def test_every_value_diff_has_a_disposition():
    """每个真取值差都必须写明 applied / reverted 及其独立证据。"""
    val = LEDGER["validation"]
    disp = val["value_dispositions"]
    for k in val["report"]["value_diff_fields"]:
        rec = disp.get(k) or {}
        assert rec.get("disposition") in {"applied", "reverted"}, k
        assert str(rec.get("evidence") or "").strip(), k
    assert len(val["corrections"]) == 2, "两处取值订正都要有结构证据"
    for c in val["corrections"]:
        assert str(c.get("structural_evidence") or "").strip(), c["field"]
    # ★ 二次复核教训锁死：数据截断点不能推翻有独立证据的生产决策。
    fr = disp["five_gate_rewrite"]
    assert fr["disposition"] == "applied", \
        "4.6 关闭是 10-31 已应用决策，不得按「快照 0 次生效」判回退"
    assert "434 题次" in fr["evidence"] and "10-31" in fr["evidence"]


def test_retired_fields_have_no_live_references():
    """已退役历史字段不得再被生产代码引用（AST 口径，注释史料不算）。"""
    import sys
    sys.path.insert(0, str(ROOT))
    from replay_policy_equivalence import _code_refs
    names = set(LEDGER["validation"]["historical_retired_fields"])
    refs = _code_refs(names)
    bad = {k: v for k, v in refs.items() if v}
    assert not bad, "已退役字段仍有活引用：\n%s" % json.dumps(
        bad, ensure_ascii=False)[:1000]


def test_test_migration_is_accounted():
    """★ 反查测试迁移台账：退役的必须是旧契约用例，改写的功能用例必须还在。

    这条门禁专门防「靠删测试刷绿」：台账里的每个名字都要能在磁盘上核对，
    且改写用例一条都不许消失。
    """
    import ast
    mig = LEDGER["test_migration"]
    assert len(mig["retired"]) > 0 and len(mig["adapted"]) > 0

    def _names(rel):
        p = ROOT / rel
        if not p.exists():
            return set()
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        return {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for row in mig["retired"]:
        assert row["name"] not in _names(row["file"]), \
            "台账声称退役但仍存在：%s::%s" % (row["file"], row["name"])
        assert str(row.get("reason") or "").strip(), row["name"]
    for row in mig["adapted"] + mig["known_environment_fail"]:
        assert row["name"] in _names(row["file"]), \
            "功能用例被误删：%s::%s" % (row["file"], row["name"])
    principles = " ".join(mig["principle"])
    assert "回归失败数下降不作为本轮效果量" in principles
    assert "功能断言能保留的一律改写" in principles


def test_tail_cleanup_actually_happened():
    """台账里声称清掉的尾巴必须真的不在了。"""
    src = (ROOT / "agent" / "param_usage__extract.py").read_text(
        encoding="utf-8", errors="ignore")
    assert '_cfg_get(cfg, "deep_max_rework"' not in src, \
        "参数用量提取器仍在读已删字段"
    assert not (ROOT / "cli" / "smoke_dag_replan.py").exists()
