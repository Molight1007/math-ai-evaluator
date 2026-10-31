# -*- coding: utf-8 -*-
"""开关注册「出口」审计 CLI（2026-10-31）。

用法
====
    python tools/switch_lifecycle_audit.py              # 人读报告
    python tools/switch_lifecycle_audit.py --json       # 机读（给 CI / 报告）
    python tools/switch_lifecycle_audit.py --strict     # 有错误即退出码 1
    python tools/switch_lifecycle_audit.py --today 2026-11-20   # 模拟日期（验证宽限）

为什么要有它
============
`contracts/switch_registry.py` 只管**入口**（四处同步），没有任何机制管**出口**。
结果（133 个历史开关 / 103 个题次全量回放）：真正删掉 11 个（8%），现存 101 个
值从未变过，doc 自称「可做 A/B」的 26 个里真正验证过的只有 4 个（2 个还是环境兜底）。

本工具把「该给结论了」变成会响的东西：`contracts/switch_lifecycle.audit()` 的
``errors`` 非空即退出码 1（配合 `--strict`）。与
`tests/test_switch_lifecycle_guard.py` 共用同一个 audit()，**两处口径永不漂移**。

分层：本文件在 `tools/`，只允许 import `contracts/`（零依赖层），不得 import `agent/`。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from contracts import switch_lifecycle as sl  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="开关出口审计：过期未决 / 登记不全 / 幽灵条目")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非人读报告")
    ap.add_argument("--strict", action="store_true", help="存在 errors 时退出码 1")
    ap.add_argument("--today", default=None, help="模拟今天（YYYY-MM-DD），用于验证宽限期")
    ap.add_argument("--limit", type=int, default=200, help="每节最多列几条")
    args = ap.parse_args(argv)

    today = None
    if args.today:
        today = sl._parse_date(args.today)
        if today is None:
            print("--today 格式非法：%s（应为 YYYY-MM-DD）" % args.today, file=sys.stderr)
            return 2

    report = sl.audit(today=today)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(sl.format_report(report, limit=args.limit))

    if args.strict and report["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
