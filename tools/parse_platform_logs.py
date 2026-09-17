# -*- coding: utf-8 -*-
"""平台评测日志批量解析器 · 2026-09-15

平台日志（`C:/Users/<user>/Downloads/eval_log_*.log`）能获取什么信息？
本脚本把日志里的全部可用字段抽出并横向对比。

日志结构（以 eval_log_bc30b6c... 为例，533 行）
------------------------------------------------
  行 1–213    环境准备：lagent 版本 / pip / gcc / z3 / clone 仓库 / 依赖安装
  行 162      ★ `Commit ID: <sha>` —— 平台实际拉取的提交（验证"跑的是哪个版本"）
  行 214–215  `accuracy value is: 0.25` → `converted to a percentage score: 25`
  行 216–234  `=== summary ： {...}`        判分侧汇总
  行 235–531  `=== run_summary的值为：{...}` 运行侧汇总（含 client_usage）
  行 532      `model evaluation completed successfully`

拿不到的东西
------------
逐题结果（哪题对/错、每题耗时、error.type / error.message、推理链）
⇒ 只落在平台输出目录的逐题 JSON `{idx}.json`，日志里没有。

运行
----
    D:/python/python.exe tools/parse_platform_logs.py
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

SRC_DIRS = [r'C:\Users\35174\Downloads', r'C:\Users\35174\Desktop']
TS = re.compile(r'^(\d{4}-\d\d-\d\dT[\d:.]+)Z ?')


def load_clean(path):
    raw = open(path, encoding='utf-8', errors='replace').read().split('\n')
    out, stamps = [], []
    for l in raw:
        m = TS.match(l)
        if m:
            stamps.append(m.group(1))
            out.append(l[m.end():])
        else:
            out.append(l)
    return out, stamps


def grab(lines, marker):
    for i, l in enumerate(lines):
        if marker in l:
            buf, depth, started = [], 0, False
            for l2 in lines[i:]:
                for ch in l2:
                    if ch == '{':
                        depth += 1
                        started = True
                    elif ch == '}':
                        depth -= 1
                if started:
                    buf.append(l2)
                if started and depth == 0:
                    break
            s = '\n'.join(buf)
            try:
                return json.loads(s[s.index('{'):])
            except Exception:
                return None
    return None


def parse(path):
    lines, stamps = load_clean(path)
    rec = {'file': os.path.basename(path), 'lines': len(lines)}
    for l in lines:
        m = re.match(r'Commit ID:\s*([0-9a-f]{7,40})', l.strip())
        if m:
            rec['commit'] = m.group(1)[:12]
            break
    sm = grab(lines, '=== summary')
    rs = grab(lines, 'run_summary')
    if sm:
        for k in ('total', 'graded', 'correct', 'incorrect', 'invalid',
                  'accuracy', 'valid_accuracy', 'skipped', 'degraded',
                  'infra_error_count', 'runner_status', 'deadline_seconds'):
            rec[k] = sm.get(k)
        rec['failed_n'] = len(sm.get('failed') or [])
        rec['infra_errors_n'] = len(sm.get('infra_errors') or [])
    if rs:
        rec['record_count'] = rs.get('record_count')
        rec['success'] = rs.get('success')
        rec['error'] = rs.get('error')
        rec['manifest_complete'] = rs.get('manifest_complete')
        rec['expected_indices_n'] = len(rs.get('expected_indices') or [])
        cu = rs.get('client_usage') or {}
        rec.update({('cu_' + k): v for k, v in cu.items()})
    # 耗时
    if stamps:
        try:
            t0 = datetime.fromisoformat(stamps[0].replace('Z', ''))
            t1 = datetime.fromisoformat(stamps[-1].replace('Z', ''))
            rec['wall_hours'] = round((t1 - t0).total_seconds() / 3600, 2)
        except Exception:
            pass
    return rec


def main():
    files = []
    for d in SRC_DIRS:
        if os.path.isdir(d):
            files += glob.glob(os.path.join(d, 'eval_log_*.log'))
    files = sorted(set(files), key=os.path.getmtime)

    print('=' * 130)
    print('平台评测日志：能获取的信息全貌（共 %d 份）' % len(files))
    print('=' * 130)

    recs = [parse(f) for f in files]

    print('\n【一】运行标识与环境（来自日志头部）')
    print('%-46s %-14s %8s %8s' % ('日志文件', '被测提交', '行数', '墙钟h'))
    print('-' * 82)
    for r in recs:
        print('%-46s %-14s %8d %8s'
              % (r['file'][:46], r.get('commit', '?'), r['lines'],
                 r.get('wall_hours', '?')))

    print('\n【二】判分汇总 summary —— 分数与三类结果')
    print('%-46s %6s %5s %6s %6s %7s %8s %9s'
          % ('日志文件', 'total', 'corr', 'incorr', 'invalid', 'score', 'valid_acc', 'infra_err'))
    print('-' * 100)
    for r in recs:
        va = r.get('valid_accuracy')
        print('%-46s %6s %5s %6s %6s %7s %8s %9s'
              % (r['file'][:46], r.get('total'), r.get('correct'),
                 r.get('incorrect'), r.get('invalid'),
                 ('%.2f' % (r['accuracy'] * 100)) if r.get('accuracy') is not None else '?',
                 ('%.1f%%' % (va * 100)) if va is not None else '?',
                 r.get('infra_error_count')))

    print('\n【三】运行汇总 run_summary —— LLM 调用强度')
    print('%-46s %7s %6s %6s %7s %7s %7s %9s'
          % ('日志文件', 'record', 'succ', 'err', 'req', 'retry', 'trunc', 'total_tok'))
    print('-' * 102)
    for r in recs:
        tok = r.get('cu_total_tokens')
        print('%-46s %7s %6s %6s %7s %7s %7s %9s'
              % (r['file'][:46], r.get('record_count'), r.get('success'),
                 r.get('error'), r.get('cu_request_count'),
                 r.get('cu_retry_count'), r.get('cu_truncated_count'),
                 ('%.2fM' % (tok / 1e6)) if tok else '?'))

    print('\n【四】可派生的指标（由上面字段算出）')
    print('%-46s %9s %11s %10s %10s %9s'
          % ('日志文件', '覆盖率', '题均请求', '题均tok', '重试率', '截断率'))
    print('-' * 100)
    for r in recs:
        n = r.get('total') or 0
        inv = r.get('invalid')
        cov = '%6.1f%%' % ((n - inv) / n * 100) if (n and inv is not None) else '?'
        rq = '%.1f' % (r['cu_request_count'] / n) if (n and r.get('cu_request_count')) else '?'
        tk = '%.0f' % (r['cu_total_tokens'] / n) if (n and r.get('cu_total_tokens')) else '?'
        rt = ('%.2f%%' % (r['cu_retry_count'] / r['cu_attempt_count'] * 100)
              if r.get('cu_attempt_count') else '?')
        tc = ('%.2f%%' % (r['cu_truncated_count'] / r['cu_request_count'] * 100)
              if r.get('cu_request_count') else '?')
        print('%-46s %9s %11s %10s %10s %9s' % (r['file'][:46], cov, rq, tk, rt, tc))

    print('\n【五】关键字段：deadline_seconds 与 manifest')
    for r in recs:
        print('  %-46s deadline=%s  manifest=%s  runner=%s  exit=%s'
              % (r['file'][:46], r.get('deadline_seconds'),
                 r.get('manifest_complete'), r.get('runner_status'),
                 r.get('runner_exit_code')))

    print('\n【六】日志里**没有**的东西')
    print('  · 逐题结果：哪题对 / 哪题错 / 每题耗时 —— 日志只有汇总计数')
    print('  · 每题的 error.type / error.message —— 落在平台输出目录的逐题 JSON {idx}.json')
    print('  · 模型推理链、候选数、阶段耗时 —— 本地评测才有（diag 字段）')
    print('  · failed / infra_errors 本次为空列表 ⇒ 平台不把选手侧超时算作环境故障')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
