# -*- coding: utf-8 -*-
"""任务列表 #1 回归守卫：题型判题并入 2.6 题意理解（2026-10-14）。

用户原话（任务列表 第 1 条）：
  「题型判断很简单，就是让大模型先判断题目属于什么类型，选择题，判断题，证明题，
    解答题等，这个**要和题意理解合并**」

本文件守住四件事：
  ① `agent/orchestrator.py` 不再有独立的 `_stage_start(ctx, "1.1_type_understanding")`；
  ② `pre_audit_stage`（2.6 题意理解）体首**先判题型**，且该调用早于 Lean 前置形式化；
  ③ 判题产出（question_type / type_decision / type_path）**契约不变**：
     `ctx.question_type` 必须始终是**中文题型**，类别键只用于索引 `TYPE_PATH_PLAN`；
  ④ 审计/报告阶段清单同步（1.1 退出**现行**清单，2.6 挂上「题意理解（含题型判题）」）。

★ 为什么用静态文本守卫 + 直调单函数，而不是端到端：
  `Orchestrator.run` 全链路依赖 LLM / Lean / 网络，跑不动；这类「改了 A 忘了 B」
  的错位用静态扫描最有效（沿用 tests/test_orchestrator_static.py 的既有风格）。
  `agent/question_type.py` 只依赖标准库，故用 importlib 直接加载 —— 避免
  `agent/__init__.py` 的第三方依赖把纯逻辑单测拖成集成测试。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _load_question_type():
    """直接加载 `agent/question_type.py`（绕开 agent 包的第三方依赖）。"""
    path = os.path.join(ROOT, "agent", "question_type.py")
    spec = importlib.util.spec_from_file_location("_qt_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QT = _load_question_type()


# ============================================================
# ① / ② 阶段编排：题型判题不再是独立阶段，而是题意理解的第一步
# ============================================================
class StagePunchTest(unittest.TestCase):
    """题型判题撤销独立阶段打点（任务 #1 的核心动作）。"""

    def setUp(self):
        self.orch = _read("agent/orchestrator.py")

    def test_no_standalone_type_understanding_stage_punch(self):
        self.assertNotIn(
            '_stage_start(ctx, "1.1_type_understanding")', self.orch,
            "题型判题已并入 2.6 题意理解 —— 不应再有独立的阶段打点")

    def test_understanding_stage_punch_kept(self):
        self.assertIn(
            '_stage_start(ctx, "2.6_pre_audit")', self.orch,
            "2.6 题意理解仍是阶段（题型判题并入其中，而非把 2.6 也删了）")

    def test_old_stage_helper_no_longer_called(self):
        self.assertNotIn(
            "type_understanding_stage(", self.orch,
            "旧阶段函数 type_understanding_stage 已改名/内联，不应再被调用")

    def test_stage_stop_list_dropped_type_understanding(self):
        """收尾统一 stop 的清单里不应再列 1.1。"""
        i_fin = self.orch.index("def _run_finalize(")
        body = self.orch[i_fin:i_fin + 2000]
        for line in body.splitlines():
            if "_stg in (" in line or line.strip().startswith('"1.1'):
                self.assertNotIn('"1.1_type_understanding"', line,
                                 "收尾 stop 清单仍含已撤销的 1.1")


class PreAuditStageTest(unittest.TestCase):
    """判题是题意理解的**第一步**（顺序语义）。"""

    def setUp(self):
        self.src = _read("agent/orchestrator__prep.py")

    def test_judge_helper_defined(self):
        self.assertIn("def judge_question_type(self, ctx) -> None:", self.src)

    def test_called_inside_pre_audit_stage(self):
        i_stage = self.src.index("def pre_audit_stage(")
        i_call = self.src.index("\n        judge_question_type(self, ctx)")
        self.assertGreater(i_call, i_stage, "判题必须在 pre_audit_stage 体内调用")

    def test_call_precedes_downstream_steps(self):
        """先判题型，再带着题型做【题意理解】与【派生题目目标】—— 顺序不可反。

        ★ 2026-10-14：原断言「判题早于 Lean 前置形式化（`lean_pre_verifier.run`）」
        随该调用点**撤出 2.6**而失效（详见 `orchestrator__prep.py` 内撤除说明）；
        顺序语义本身仍要守，故改为对**现存**下游步骤的顺序守卫。
        """
        i_call = self.src.index("\n        judge_question_type(self, ctx)")
        for later, label in (
                ("self.lean_pre_verifier.run_understanding_chain(ctx)", "题意理解"),
                ("ctx.problem_goal = _bpg(ctx)", "题目目标")):
            i_later = self.src.index(later, i_call)
            self.assertLess(i_call, i_later,
                            "题型判题必须早于%s" % label)

    def test_judgment_failure_never_blocks(self):
        """判题失败必须被 try 包住（增益机制，绝不阻断主链）。"""
        i_call = self.src.index("\n        judge_question_type(self, ctx)")
        head = self.src[max(0, i_call - 600):i_call]
        tail = self.src[i_call:i_call + 600]
        self.assertIn("try:", head, "judge_question_type 调用必须被 try 包裹")
        self.assertIn("except Exception", tail, "判题异常必须有 except 兜底")

    def test_contract_fields_still_written(self):
        """产出字段三件套不得因合并而丢。"""
        for frag in ('ctx.question_type = _dec["final"]',
                     "ctx.type_decision = _dec",
                     "ctx.type_path = _tpp("):
            self.assertIn(frag, self.src, f"判题产出字段丢失：{frag}")


class ReportWiringTest(unittest.TestCase):
    """审计 / 报告 的阶段清单同步（否则统计口径与实现脱节）。"""

    def test_stage_audit_dropped_1_1_and_renamed_2_6(self):
        src = _read("tools/stage_audit.py")
        self.assertNotIn('("1.1_type_understanding", "题型判题"', src,
                         "审计清单仍把 1.1 当现行阶段")
        self.assertIn("题意理解（含题型判题）", src, "2.6 中文名未反映合并")

    def test_stage_audit_keeps_2_6_judgement(self):
        src = _read("tools/stage_audit.py")
        self.assertIn('elif key == "2.6_pre_audit":', src,
                      "历史 jsonl 仍需按名分派渲染 2.6")

    def test_dashboard_has_no_1_1_row(self):
        src = _read("cli/test_report.py")
        self.assertNotIn('("1.1_type_understanding", "① 题型判题"', src,
                         "四维表仍有独立的 1.1 行")
        self.assertIn('("2.6_pre_audit", "① 题意理解（含题型判题）"', src,
                      "四维表 ① 行未反映合并")


# ============================================================
# ③ 判题逻辑本身：中文契约 vs 类别键（2026-10-14 随附修复）
# ============================================================
class NamespaceTest(unittest.TestCase):
    """`ctx.question_type` 恒为中文；类别键只用于索引分流表。"""

    def test_type_key_accepts_both_namespaces(self):
        self.assertEqual(QT.type_key("证明题"), "proof")
        self.assertEqual(QT.type_key("proof"), "proof")
        self.assertEqual(QT.type_key("PROOF"), "proof")
        self.assertEqual(QT.type_key(""), "")
        self.assertEqual(QT.type_key("未知题型"), "")

    def test_qt_of_key_round_trip(self):
        for qt, key in QT.QT_TO_KEY.items():
            self.assertEqual(QT.qt_of_key(key), qt)
            self.assertEqual(QT.qt_of_key(qt), qt)

    def test_type_path_plan_accepts_chinese(self):
        """★ 修复点：传中文题型也要拿到**专属**计划，而不是默认计划。"""
        self.assertEqual(QT.type_path_plan("选择题")["answer_form"], "option")
        self.assertEqual(QT.type_path_plan("choice")["answer_form"], "option")
        self.assertEqual(QT.type_path_plan("证明题")["answer_form"], "proof")
        self.assertEqual(QT.type_path_plan("证明题")["lean"], True)
        self.assertEqual(QT.type_path_plan("选择题")["lean"], False)

    def test_unknown_type_falls_back_to_default(self):
        d = QT.type_path_plan("")
        self.assertEqual(d["lean"], True)
        self.assertEqual(d["answer_form"], "")


class MergeTypeDecisionTest(unittest.TestCase):
    """交叉校验：比较用类别键，产出用中文题型。"""

    def test_rule_strong_signal_actually_blocks_llm(self):
        """★ 回归核心：规则判为选择题时，LLM 不得覆盖（原实现此守卫恒假）。"""
        d = QT.merge_type_decision("选择题", "solution", 0.99)
        self.assertEqual(d["final"], QT.QT_CHOICE)
        self.assertEqual(d["final_key"], "choice")
        self.assertEqual(d["reason"], "规则强信号优先")
        self.assertTrue(d["overrides"])

        d2 = QT.merge_type_decision("判断题", "proof", 0.99)
        self.assertEqual(d2["final"], QT.QT_JUDGE)

    def test_agreement_is_recognised_as_agreement(self):
        """★ 回归核心：两侧命名空间不同但语义相同 ⇒ 必须判为"一致"（原实现恒判覆盖）。"""
        d = QT.merge_type_decision("解答题", "solution", 0.9)
        self.assertEqual(d["reason"], "一致或无 LLM 结果")
        self.assertEqual(d["overrides"], [])
        self.assertEqual(d["final"], QT.QT_SOLUTION)

    def test_llm_override_returns_chinese_contract(self):
        """★ 回归核心：LLM 覆盖后 final 必须是**中文**（否则下游中文判定整段失效）。"""
        d = QT.merge_type_decision("解答题", "fill_blank", 0.9)
        self.assertEqual(d["final"], QT.QT_FILL)
        self.assertEqual(d["final_key"], "fill_blank")
        self.assertNotEqual(d["final"], "fill_blank",
                            "final 泄漏成类别键会把下游中文契约判定全部打哑")

    def test_low_confidence_keeps_rule(self):
        d = QT.merge_type_decision("解答题", "proof", 0.5)
        self.assertEqual(d["final"], QT.QT_SOLUTION)
        self.assertEqual(d["reason"], "LLM 置信不足（<0.6）⇒ 保留规则判定")

    def test_empty_llm_keeps_rule(self):
        d = QT.merge_type_decision("证明题", "", 0.0)
        self.assertEqual(d["final"], QT.QT_PROOF)
        self.assertEqual(d["reason"], "一致或无 LLM 结果")

    def test_final_always_in_chinese_namespace(self):
        """穷举：任何 (rule, llm, conf) 组合下 final 都必须是中文题型或空串。"""
        ok = set(QT.QT_TO_KEY) | {""}
        for r in list(QT.QT_TO_KEY) + ["", "未知"]:
            for l in list(QT.QT_TO_KEY) + ["proof", "solution", "choice",
                                           "boolean", "fill_blank", "", "乱码"]:
                for c in (0.0, 0.5, 0.6, 0.99):
                    fin = QT.merge_type_decision(r, l, c)["final"]
                    self.assertIn(fin, ok, f"final={fin!r} 越出中文命名空间")


class ParseTypeJsonTest(unittest.TestCase):
    def test_normalises_english_key(self):
        d = QT.parse_type_json('{"type": "proof", "confidence": 0.8}')
        self.assertEqual(d["type"], "proof")

    def test_normalises_chinese_answer(self):
        """模型偶尔回中文题型 ⇒ 归一为类别键，下游不必分支。"""
        d = QT.parse_type_json('{"type": "证明题", "confidence": 0.8}')
        self.assertEqual(d["type"], "proof")

    def test_regex_fallback_chinese(self):
        d = QT.parse_type_json("这道题是选择题，选 A")
        self.assertEqual(d["type"], "choice")

    def test_garbage_returns_empty(self):
        self.assertEqual(QT.parse_type_json("完全无关的一句话"), {})
        self.assertEqual(QT.parse_type_json(""), {})


# ============================================================
# ④ 报告：合并后 ① 行同时呈现「题型判题」与「Lean 前置理解」
# ============================================================
class MergedDashboardRowTest(unittest.TestCase):
    """2.6 行的结果/达标必须**同时**反映并入进来的题型判题。"""

    def _rows(self, recs):
        from cli.test_report import _stage_dashboard_rows
        return {r[0]: r for r in _stage_dashboard_rows(recs)}

    def _rec(self, verdict, type_final):
        diag = {"stage_timers": {"2.6_pre_audit": 12.0}}
        if type_final is not None:
            diag["type_decision"] = {"final": type_final}
        if verdict is not None:
            diag["preverify_trace"] = {"verdict": verdict}
        return {"diag": diag, "candidates": []}

    def test_raw_shows_both_type_and_verdict(self):
        rows = self._rows([self._rec("pass", "证明题")])
        self.assertIn("type=证明题", rows["2.6_pre_audit"][5])
        self.assertIn("verdict=pass", rows["2.6_pre_audit"][5])

    def test_missing_type_decision_is_not_pass(self):
        """判题未产出 ⇒ 本行不达标（合并后判题是本阶段的必产证据）。"""
        rows = self._rows([self._rec("pass", None)])
        self.assertIn("0/1", rows["2.6_pre_audit"][6])

    def test_verdict_fail_is_not_pass(self):
        rows = self._rows([self._rec("fail", "证明题")])
        self.assertIn("0/1", rows["2.6_pre_audit"][6])

    def test_type_ok_without_verdict_still_counts(self):
        """Lean 前置被跳过（无 verdict）但判题完成 ⇒ 计入达标。"""
        rows = self._rows([self._rec(None, "解答题")])
        self.assertIn("1/1", rows["2.6_pre_audit"][6])
        self.assertIn("verdict=—", rows["2.6_pre_audit"][5])

    def test_pass_criterion_mentions_type_decision(self):
        """达标判据栏必须写明「题型判题完成（type_decision 非空）」。"""
        rows = self._rows([self._rec("pass", "证明题")])
        self.assertIn("type_decision 非空", rows["2.6_pre_audit"][7])


if __name__ == "__main__":
    sys.exit(unittest.main())
