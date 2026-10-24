# -*- coding: utf-8 -*-
"""RRSI 泄漏筛查（规则 D）：改动 diff 里是否把"某道题"编码进了 harness。

为什么需要
----------
RRSI 论文（2026-10-06）指出 harness 自改进的头号过拟合途径是
**benchmark-specific fitting**：把 evolve 集的特有模式（题号、题面、答案、
特定分支）写进 harness，evolve 分很好看，换题就失效。论文的应对是
"在评估**之前**由 critic 读 diff 拒收"——一旦泄漏候选拿到虚高分，
后续几轮都会被它带偏，事后无法纠正。

本项目 10-20~10-22 的教训正对应这条：为 `number_theory-075` 连续打三轮
补丁，判断依据始终只有那一题。本脚本把"读 diff 拒收"从人工 checklist
变成可执行门禁。

查什么
------
1. **题号字面量**：`official112-019` / `imo-bench-*` / `number_theory-075` 之类。
2. **标准答案字面量**：题库 `answer` 字段（长度 ≥4）出现在新增代码里。
3. **题面片段**（`--deep`）：题干中长度 ≥12 的连续片段出现在新增代码里。
   默认关闭——数学题面常有通用开头（"设函数 f(x)"），误报率高。

豁免
----
`tests/`、`outputs/`、`results/` 下的改动不查（夹具测试**本来就该**引用题号），
只查 harness 本体：`agent/ prompts/ tools/ cli/ contracts/` 等。

用法
----
    python tools/harness_lint.py                      # 工作区未提交改动
    python tools/harness_lint.py --staged             # 暂存区
    python tools/harness_lint.py --range main..HEAD   # 指定区间
    python tools/harness_lint.py --file agent/x.py    # 直接查单个文件（不计行号豁免）
    python tools/harness_lint.py --bank 题库/official112_本地测试题库/official112_full.jsonl --deep

退出码：0 无泄漏；1 命中泄漏；2 用法/环境错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# 题号字面量。只认"系列名 + 编号"的组合，避免把 `official112` 这种
# 单独出现的目录名当成泄漏（那是正常的题库路径）。
_BANK_ID_RE = re.compile(
    r"(?:official\d+|imo-bench|number[_-]theory|algebra|geometry|combinatorics)"
    r"[-_]?\d{2,}",
    re.I,
)

# 不查的路径前缀（夹具测试引用题号是合理的；产物目录不是 harness）
_EXEMPT_PREFIXES = ("tests/", "outputs/", "results/", "sample_outputs/",
                    "测试工具/", "赛事提交版/", "题库/", "论文实践/")

# 不查的后缀：文档/报告本来就要点名某道题（交接文档、评测报告），
# 它们不是可执行的 harness 逻辑，泄漏不到模型行为里。
_EXEMPT_SUFFIXES = (".md", ".jsonl", ".txt", ".csv")

_MIN_ANSWER_LEN = 4      # 短答案（"4"、"0"）噪音太大，不查
_MIN_SNIPPET_LEN = 12    # 题面片段最小长度


def _git(*args: str) -> str:
    """跑 git 并把失败转化成可读的 RuntimeError（不静默吞掉）。

    `core.quotepath=false` 是必需的：默认会把中文路径转义成 `\\344\\272...`，
    命中报告里根本看不出是哪个文件。
    """
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                             capture_output=True, timeout=60)
    except FileNotFoundError as exc:                      # 没有 git
        raise RuntimeError("找不到 git：%s" % exc) from exc
    if out.returncode != 0:
        raise RuntimeError("git %s 失败：%s"
                           % (" ".join(args),
                              out.stderr.decode("utf-8", "replace")[:300]))
    return out.stdout.decode("utf-8", "replace")


def _added_lines(diff_text: str):
    """从 unified diff 里抽新增行 → [(新文件路径, 新文件行号, 行内容)]。

    只看 `+` 行且跳过 `+++` 头。行号靠 `@@ -a,b +c,d @@` 里的 c 递推；
    `-U0` 保证没有上下文行干扰。
    """
    cur, lineno = None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            cur = None if path == "/dev/null" else path[2:] if path.startswith("b/") else path
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
            continue
        if cur is None:
            continue
        if raw.startswith("+"):
            yield cur, lineno, raw[1:]
            lineno += 1
        elif raw.startswith("-"):
            continue                       # 删除行不改变新文件行号
        else:
            lineno += 1                    # 上下文行（-U0 下很少）


def _load_bank(path: str):
    """读题库 jsonl → [(id, answer_str, question_str)]。字段缺失跳过。"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue                    # 坏行跳过（题库里确有），不算错误
            rows.append((str(r.get("id") or ""),
                         str(r.get("answer") or ""),
                         str(r.get("question") or "")))
    return rows


def _snippets(question: str):
    """取题面的首/中/尾三个窗口作为泄漏指纹。太短的题不取样。"""
    q = " ".join(question.split())
    if len(q) < _MIN_SNIPPET_LEN * 2:
        return []
    out = [q[:_MIN_SNIPPET_LEN], q[len(q) // 2:len(q) // 2 + _MIN_SNIPPET_LEN]]
    if len(q) > _MIN_SNIPPET_LEN * 2:
        out.append(q[-_MIN_SNIPPET_LEN:])
    return [s for s in out if len(s) >= _MIN_SNIPPET_LEN]


def _exempt(path: str) -> bool:
    p = path.replace("\\", "/")
    return p.startswith(_EXEMPT_PREFIXES) or p.endswith(_EXEMPT_SUFFIXES)


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RRSI 泄漏筛查：diff 是否把某道题编码进了 harness")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--staged", action="store_true", help="查暂存区（--cached）")
    src.add_argument("--range", default="", help="git diff 区间，如 a..b")
    src.add_argument("--file", default="", help="直接查单个文件（无行号）")
    ap.add_argument("--bank", default="", help="题库 jsonl，用于查标准答案/题面泄漏")
    ap.add_argument("--deep", action="store_true",
                    help="同时查题面片段（误报率较高，默认关闭）")
    args = ap.parse_args(argv)

    # ① 取新增行
    try:
        if args.file:
            text = open(args.file, encoding="utf-8", errors="replace").read()
            lines = [(args.file, i + 1, ln) for i, ln in enumerate(text.splitlines())]
        else:
            diff_args = ["diff", "-U0"]
            if args.staged:
                diff_args.append("--cached")
            if args.range:
                diff_args.append(args.range)
            lines = list(_added_lines(_git(*diff_args)))
    except (RuntimeError, OSError) as exc:
        print("[RRSI-D] 无法读取改动：%s" % exc, file=sys.stderr)
        return 2

    scanned = [(p, n, t) for p, n, t in lines if not _exempt(p)]
    print("[RRSI-D] 泄漏筛查")
    print("  新增行 %d，受检 %d（豁免 tests/ outputs/ results/ 等）"
          % (len(lines), len(scanned)))
    if not scanned:
        print("  PASS：没有需要检查的新增行")
        return 0

    hits = []
    # ② 题号字面量
    for path, no, text in scanned:
        for m in _BANK_ID_RE.finditer(text):
            hits.append((path, no, "题号字面量 `%s`" % m.group(0), text.strip()[:90]))

    # ③ 答案 / 题面（需要题库）
    if args.bank:
        if not os.path.isfile(args.bank):
            print("[RRSI-D] 题库不存在：%s" % args.bank, file=sys.stderr)
            return 2
        bank = _load_bank(args.bank)
        print("  题库 %d 题，答案字面量下限 %d 字符%s"
              % (len(bank), _MIN_ANSWER_LEN, "，题面片段开启" if args.deep else ""))
        for path, no, text in scanned:
            for qid, ans, q in bank:
                a = ans.strip()
                if len(a) >= _MIN_ANSWER_LEN and a in text:
                    hits.append((path, no, "标准答案字面量（%s）" % qid, text.strip()[:90]))
                if args.deep:
                    for s in _snippets(q):
                        if s in text:
                            hits.append((path, no, "题面片段（%s）" % qid, s))
                            break
    else:
        print("  （未给 --bank，只查题号；答案/题面泄漏查不到）")

    if not hits:
        print("  PASS：未发现 benchmark-specific 泄漏")
        return 0

    print("  FAIL：%d 处命中，评估前必须先清理" % len(hits))
    for path, no, why, ctx in hits:
        print("    %s:%d  %s" % (path, no, why))
        if ctx:
            print("      > %s" % ctx)
    print("  依据：RRSI 规则 D —— 泄漏候选一旦拿到虚高分，后续几轮都会被带偏，")
    print("        所以筛查必须在评估之前完成。")
    return 1


if __name__ == "__main__":
    sys.exit(run())
