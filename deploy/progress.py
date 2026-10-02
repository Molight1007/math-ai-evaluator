# -*- coding: utf-8 -*-
"""progress.py — 评测进度速览（服务器端运行，只读，不改任何东西）。

用法（在仓库根）：
    .venv/bin/python deploy/progress.py                 # 自动找最新的 cloud*.jsonl
    .venv/bin/python deploy/progress.py <结果.jsonl>

输出：已完成/正确数、正确率、逐题耗时与判定、当前进行中的题、累计 LLM 调用、
      以及资源曲线摘要（最低可用内存 / 最多 Lean 进程 / Lean 峰值 RSS）。
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def newest_progress(pattern: str) -> str:
    fs = [f for f in glob.glob(pattern) if os.path.isfile(f)]
    return max(fs, key=os.path.getmtime) if fs else ""


def running_tag() -> str:
    """从 tmux 推断正在跑的会话名（= --tag）。

    ★ 为什么需要：多会话并存时，按 mtime 取"最新 jsonl"会拿到已被停止的旧会话
    （旧会话的 jsonl 反而是最后写入的）⇒ progress 会显示过期数据（实测踩到）。
    """
    try:
        out = subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout
    except Exception:  # noqa: BLE001
        return ""
    names = [l.split(":")[0].strip() for l in out.splitlines() if ":" in l]
    return names[0] if len(names) == 1 else ""


def pick_by_tag(tag: str, kind: str) -> str:
    """按会话 tag 精确匹配产物（kind: jsonl / log / monitor）。"""
    if not tag:
        return ""
    if kind == "monitor":
        for pat in (f"logs/monitor_{tag}_v*.csv", f"logs/monitor_{tag}.csv"):
            f = newest_progress(pat)
            if f:
                return f
        return ""
    f = newest_progress(f"results/{tag}*.{kind}")
    return f


def main() -> int:
    tag = ""
    jsonl = ""
    args = [a for a in sys.argv[1:]]
    if args and args[0].startswith("--tag="):
        tag = args[0].split("=", 1)[1]
    elif args and not args[0].startswith("-"):
        jsonl = args[0]
    if not tag and not jsonl:
        tag = running_tag()
    if not jsonl:
        jsonl = pick_by_tag(tag, "jsonl") if tag else newest_progress("results/cloud*.jsonl")
    if not jsonl:
        print(f"还没有任何结果 jsonl（会话 {tag or '?'} 的第 1 题尚未完成）")
        jsonl = ""
    logf = pick_by_tag(tag, "log") if tag else \
        ((jsonl[:-6] + ".log") if jsonl.endswith(".jsonl") else "")

    print("=" * 78)
    print("MathPilot 云端评测进度")
    print("=" * 78)
    print(f"现在        {time.strftime('%F %T')}")
    print(f"会话 tag    {tag or '(未识别——无 tmux 会话或未指定)'}")
    print(f"结果文件    {jsonl or '(无)'}")

    # ---------- 进度与正确率 ----------
    rows = []
    if jsonl and os.path.isfile(jsonl):
        for line in open(jsonl, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass

    total = 112
    n = len(rows)
    ok = sum(1 for r in rows if r.get("correct"))
    print(f"已完成      {n} / {total}   ({n / total * 100:.1f}%)")
    print(f"正确        {ok}   ({ok / n * 100:.1f}% of 已完成)" if n else "正确        0")

    if rows:
        els = sorted(float(r.get("elapsed_sec") or 0) for r in rows)
        avg = sum(els) / len(els)
        med = els[len(els) // 2]
        print(f"单题耗时    均 {avg:.0f}s / 中位 {med:.0f}s / 最长 {els[-1]:.0f}s")
        reached = sum(1 for e in els if e >= 1000)
        print(f"贴墙预警    ≥1000s 的题 {reached} 道")
        # 错误分类
        cls = {}
        for r in rows:
            k = r.get("error_class") or ("正确" if r.get("correct") else "?")
            cls[k] = cls.get(k, 0) + 1
        print("分类        " + " · ".join(f"{k}={v}" for k, v in
                                        sorted(cls.items(), key=lambda x: -x[1])))

    # ---------- 当前进行中的题 ----------
    print("-" * 78)
    if logf and os.path.isfile(logf):
        sz = os.path.getsize(logf)
        last = ""
        with open(logf, "rb") as fh:
            try:
                fh.seek(max(0, sz - 4000))
                last = fh.read().decode("utf-8", "replace")
            except OSError:
                pass
        tail = [l for l in last.splitlines() if l.strip()]
        calls = sum(1 for l in open(logf, encoding="utf-8", errors="replace")
                    if "LLM chat OK" in l)
        print(f"日志        {logf}")
        print(f"             {sz} 字节   累计 LLM 调用 {calls} 次")
        # 当前题号（run_eval 会打 [i/N] 或 题号）
        ids = re.findall(r"\[(\d+)\s*/\s*(\d+)\]", last)
        if ids:
            print(f"当前题      [{ids[-1][0]}/{ids[-1][1]}]")
        for l in tail[-3:]:
            print("   " + l.strip()[:120])
    else:
        print("日志        尚未生成")

    # ---------- 已完成的题清单 ----------
    if rows:
        print("-" * 78)
        print(f"{'题号':<20}{'结果':<6}{'耗时s':>8}  错误分类")
        for r in rows[-15:]:
            mark = "✓" if r.get("correct") else "✗"
            print(f"{str(r.get('id'))[:19]:<20}{mark:<6}"
                  f"{float(r.get('elapsed_sec') or 0):>8.0f}  {r.get('error_class') or ''}")
        if len(rows) > 15:
            print(f"(仅显示最近 15 道，共 {len(rows)} 道)")

    # ---------- 资源曲线 ----------
    print("-" * 78)
    mon = (pick_by_tag(tag, "monitor") if tag
           else (newest_progress("logs/monitor_cloud*_v2.csv") or newest_progress("logs/monitor_cloud*.csv")))
    if mon and os.path.isfile(mon):
        minav = None
        mxlean = mxrss = mxpct = 0
        cnt = 0
        with open(mon, encoding="utf-8", errors="replace") as fh:
            next(fh, None)
            for line in fh:
                f = line.strip().split(",")
                if len(f) < 13:
                    continue
                cnt += 1
                try:
                    av = float(f[3]); lp = float(f[7]); rss = float(f[8]); pc = float(f[4])
                except ValueError:
                    continue
                minav = av if minav is None else min(minav, av)
                mxlean = max(mxlean, lp); mxrss = max(mxrss, rss); mxpct = max(mxpct, pc)
        print(f"资源曲线    {mon}   {cnt} 个采样点")
        print(f"            最低可用内存 {minav:.0f} MB · 最多 Lean 进程 {mxlean:.0f} · "
              f"Lean 峰值 RSS 合计 {mxrss:.0f} MB · 内存占用峰值 {mxpct:.0f}%")
        if minav is not None and minav < 1500:
            print("            ⚠️ 可用内存曾低于 1.5 GB —— 留意 OOM 风险")
    else:
        print("资源曲线    尚未生成")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
