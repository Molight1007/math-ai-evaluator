"""P1「验证硬信号 → 强制重解」块的静态契约（防重构回归）。

演进（2026-09-11）：
  v1：触发点在 4.6 对抗验证（363s）之后 + 软截止护栏 → 冒烟 4/4 未触发；
  v2：前移到 4_verify 之后 + 硬墙剩余护栏 → 复测仍未触发（002 到 4_verify 结束已用
      1201s、010 用 1110s，剩余 90s < 240s 门槛）→ 证明 4_verify 结束时时间已耗尽；
  v3：前移到 3.6 之后 / 4_verify 之前（tier_votes 已就绪，典型时点 600-700s，剩余 500s+）。

本测试用源码静态检查锁定 v3 的关键修正。检查对象为**可执行代码行**（注释不计，
否则注释里的历史说明会误判）。
行为级验证依赖冒烟 / 全量 A/B（见 后续优化计划_0910.md）。
"""
import os


def _src() -> str:
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py")
    return open(p, encoding="utf-8").read()


def _p1_code() -> str:
    """取 P1 块的可执行代码（按块边界截断 + 剔除注释）。

    边界：从 "P1 v" 标记到 `ver_result = self.verifier.run(` 之前——
    不可用固定长度窗口（会越界把后续阶段的时间条件算进来，造成误判）。
    """
    src = _src()
    i = src.find("P1 v")
    assert i > 0, "找不到 P1 块（可能被重构或删除）"
    j = src.find("ver_result = self.verifier.run(", i)
    seg = src[i:j] if j > i else src[i:i + 2800]
    lines = []
    for line in seg.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def test_p1_block_before_verify():
    """v3 前移：P1 块必须在**真正的验证计算** verifier.run 之前。

    注意：`_stage_start(ctx, "4_verify")` 只是阶段计时标记（在 P1 之前），
    真正消耗时间的是 verifier.run；v1/v2 均因触发点晚于验证计算而时间耗尽。
    """
    src = _src()
    i_p1 = src.find("P1 v")
    i_vrun = src.find("ver_result = self.verifier.run(")
    assert i_p1 > 0 and i_vrun > 0, "锚点缺失"
    assert i_p1 < i_vrun, "P1 块必须在 verifier.run（验证计算）之前（v3 前移修正）"


def test_p1_uses_hard_wall_remaining():
    """护栏：可执行代码必须用硬墙剩余，不得用软截止。

    门槛 150s 的由来：v4 实证 standard 档 verify_reserve 仅 180s，
    而初版门槛 240s > 180s → 结构上永不可能触发；故降至 150s
    （低于任何档位的预留量，保证"检测到即可处置"）。
    """
    code = _p1_code()
    assert "ctx.time_remaining() > 150" in code, "护栏必须是 ctx.time_remaining() > 150"
    assert "gen_time_up()" not in code, "护栏不得用 gen_time_up()（v1 失效原因）"


def test_p1_signals_exclude_final_gate():
    """信号源不得含 final_gate（6.5 才产生，晚于 P1 位置）。"""
    assert "final_gate" not in _p1_code(), "final_gate 晚于 P1 位置，不应纳入"


def test_p1_includes_lean_candidate_signal():
    """信号源必须含「3.6 阶段 Lean 候选级淘汰」记录。

    v7 实测 014：有时间（剩余 363s）、有 `proof_invalid` 信号，却未触发——
    因为 `proof_invalid` 出自 6.5 的 final_gate，晚于本检查点（4_verify 之前）。
    改用 3.6 候选级 LeanGate.apply 的"淘汰 N 候选"记录后，信号才可见。
    """
    code = _p1_code()
    # 2026-09-12 变更：该信号源已从「在 trace 里匹配中文子串『淘汰』」改为
    # **结构化字段** `ctx.lean_reject_feedback`（由 3.6 的 Lean 淘汰分支写入）。
    # 原因：原写法一旦有人改写日志文案就会让 P1 静默失效且无报错。
    assert "lean_reject_feedback" in code, \
        "信号源需含 3.6 阶段 Lean 候选淘汰记录（v7 实测 014 的修复）"


def test_p1_idempotent_guard_present():
    """P1 需幂等标记，防同一题重复触发。"""
    assert "_p1_triggered" in _p1_code(), "缺少幂等标记 _p1_triggered"


def test_p1_keeps_tier_and_emergency_guard():
    """档位放宽到 deep|standard，但保留紧急态护栏。"""
    code = _p1_code()
    assert 'tier in ("deep", "standard")' in code, "档位应放宽到 deep|standard"
    assert "ctx.state.emergency" in code, "应保留 emergency 护栏"


def test_p1_passes_placeholder_ver_result():
    """v3：ver_result 尚未生成，调用必须传占位（避免 NameError）。"""
    assert "_deep_revise_loop(ctx, {}, tier_votes" in _p1_code(), \
        "v3 位置在 4_verify 之前，必须传 {} 作为 ver_result 占位"


def test_p1_forces_revise_past_soft_deadline():
    """P1 调用必须传 force=True。

    根因（10 题实测 002，第 8 轮迭代才定位）：P1 外部条件（剩余 >150s）通过并调用了
    重解，但 `_deep_revise_loop` 第一步检查 `gen_time_up()`（生成侧软截止
    = deadline − verify_reserve = 720s），而当时已用 814s → 必为 True → **第一轮即退出**，
    重解从未真正执行。应急重解只应受硬墙约束。
    """
    code = _p1_code()
    assert "force=True" in code, "P1 调用 _deep_revise_loop 必须传 force=True（应急重解跳过软截止）"
