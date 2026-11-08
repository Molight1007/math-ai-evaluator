# -*- coding: utf-8 -*-
"""严格编译判据 —— 供后续 Lean 探针复用的参考实现（E43，11-08）

背景
----
`测试结果/L2逐步探针_20261107/l2_step_probe.py::compile_check` 的判据顺序是：

    if rc == 0 and not has_sorry and not ANY_ERR:  -> CLOSED
    if UNSOLVED.search(raw):                      -> UNSOLVED   # ★ 直接 return
    err_lines = ...                               -> ERROR

而 Lean 在**致命错误之后做错误恢复，仍会输出 `unsolved goals`**，所以只要
出现过 unknown constant / Application type mismatch / 缩进散架，探针也会
返回 UNSOLVED，把非法步当成合法步 append 进前缀继续往下走。
E42 在 283 个去重 goal state 上量到 139 个（49.1%）前缀本身非法。

另外两个缺陷（同源）：
  * `ANY_ERR = r":\\d+:\\d+: error:"` 只认 `error: `，漏掉 Lean 4.31 的
    `error(lean.unknownIdentifier): ` 格式；
  * `UNSOLVED = r"error:\\s*unsolved goals\\s*\\n"` 同样只认一种格式。

本模块的修复（**单变量**：只调换判据顺序 + 放宽诊断正则）
------------------------------------------------------------
  * 状态集合**不变**：仍是 {CLOSED, UNSOLVED, ERROR, TIMEOUT}。
    硬错误归到 `ERROR` 而不是新增状态 —— 否则旧调用方 `run_one` 不认识
    新状态，会把它当 UNSOLVED 继续 append，反而更糟。
  * 判据顺序：先收集全部诊断 → 有非 unsolved-goals 的 error 就 ERROR；
    然后才判 CLOSED；最后只剩 unsolved goals 才 UNSOLVED。
  * 诊断正则同时兼容 `error: ` 与 `error(lean.xxx): `。

★ 本模块是**纯函数、零依赖**（不 import 项目任何包，不跑 Lean），
  可单测；不修改 11-07 那份历史探针（史料不回改）。
"""
import re

__all__ = ["DIAG_RE", "UNSOLVED_RE", "SORRY_RE", "STATES",
           "collect_diags", "classify_compile", "compile_check"]

# 同时兼容 `error: ` 与 `error(lean.unknownIdentifier): `；warning 也收（sorry 警告）
DIAG_RE = re.compile(
    r"^.*?:(\d+):\d+: (error|warning)(?:\([^)]*\))?: ?(.*)$")
UNSOLVED_RE = re.compile(r"^\s*unsolved goals\b", re.I)
SORRY_RE = re.compile(r"declaration uses [`']sorry", re.I)
# 与 v3 探针完全相同的状态集合（不新增、不删减）
STATES = frozenset({"CLOSED", "UNSOLVED", "ERROR", "TIMEOUT"})


def collect_diags(raw):
    """返回 (hard_errors, unsolved_errors, has_sorry)。

    hard_errors     : 非 unsolved-goals 的 error 消息列表
    unsolved_errors : unsolved goals 类 error 消息列表
    has_sorry       : 出现 `declaration uses 'sorry'` 警告
    """
    hard, unsolved, sorry = [], [], False
    for line in str(raw or "").splitlines():
        m = DIAG_RE.match(line)
        if not m:
            continue
        sev, msg = m.group(2), m.group(3)
        if sev == "warning":
            if SORRY_RE.search(msg):
                sorry = True
            continue
        (unsolved if UNSOLVED_RE.search(msg) else hard).append(msg)
    if SORRY_RE.search(str(raw or "")):
        sorry = True
    return hard, unsolved, sorry


def classify_compile(returncode, raw, timed_out=False):
    """严格判据。返回 {status, brief, goal, error}（形状与旧 compile_check 一致）。

    ★ 顺序是全部：`ERROR` > `UNSOLVED` > `CLOSED`。
      `CLOSED` 必须同时满足 rc==0、零 error、零 sorry —— 三者缺一不可；
      尤其「有 unsolved goals」本身就说明没证完，不能因为 rc 侥幸为 0 就 CLOSED。
    """
    if timed_out:
        return {"status": "TIMEOUT", "brief": "TIMEOUT", "goal": "",
                "error": ""}
    hard, unsolved, sorry = collect_diags(raw)
    if hard or sorry:
        brief = (hard[0] if hard else "declaration uses 'sorry'")[:200]
        return {"status": "ERROR", "brief": brief, "goal": "",
                "error": str(raw or "")[-2000:]}
    # 只保留第一条 unsolved goals 之后、下一条诊断之前的 goal 文本
    goal_lines, started = [], False
    for line in str(raw or "").splitlines():
        dm = DIAG_RE.match(line)
        if dm and started:
            break
        if dm and dm.group(2) == "error" and UNSOLVED_RE.search(dm.group(3)):
            started = True
            continue
        if started:
            goal_lines.append(line)
    if unsolved:
        return {"status": "UNSOLVED", "brief": "unsolved", "goal":
                "\n".join(goal_lines).strip(), "error": ""}
    if returncode == 0:
        return {"status": "CLOSED", "brief": "OK", "goal": "", "error": ""}
    return {"status": "ERROR", "brief": "rc=%s（无诊断）" % returncode,
            "goal": "", "error": str(raw or "")[-2000:]}


def compile_check(code, tag, runner=None, work_dir=None, timeout=600):
    """drop-in 替换 v3 探针的同名函数（签名/返回形状完全一致）。

    后续探针只需把

        from ... import compile_check   # 旧
    换成

        from compile_check_strict import compile_check

    即可获得严格判据，**不需要改 run_one 的任何一行**（状态集合未变）。

    runner: 可选注入，形如 runner(path, timeout) -> (returncode, raw, timed_out)。
            不传则用本机 `LEAN` / `ENV_LEAN_PATH` 环境变量跑 subprocess。
            ★ 注入是为了让本函数可单测，不引入任何项目包依赖。
    """
    import os
    import subprocess
    import time

    started = time.time()
    if runner is not None:
        rc, raw, timed_out = runner(code, tag, timeout)
    else:
        wd = work_dir or os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                      "l2probe_strict")
        os.makedirs(wd, exist_ok=True)
        path = os.path.join(wd, "%s.lean" % tag)
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        env = dict(os.environ)
        if os.environ.get("ENV_LEAN_PATH"):
            env["LEAN_PATH"] = os.environ["ENV_LEAN_PATH"]
        lean = os.environ.get("LEAN", "lean")
        try:
            p = subprocess.run([lean, path], capture_output=True,
                               timeout=timeout, env=env)
            rc = p.returncode
            raw = ((p.stderr or b"").decode("utf-8", "replace") +
                   (p.stdout or b"").decode("utf-8", "replace"))
            timed_out = False
        except subprocess.TimeoutExpired:
            rc, raw, timed_out = 1, "", True
    out = classify_compile(rc, raw, timed_out=timed_out)
    out["compile_sec"] = round(time.time() - started, 2)
    return out
