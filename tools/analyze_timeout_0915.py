# -*- coding: utf-8 -*-
"""超时题表现特征分析（复算脚本）· 2026-09-15

产出《超时题表现特征分析_0915.md》中的全部表格。

数据源
------
results/_112_core_table.jsonl              112 题逐题结果（含 elapsed_sec / tier / qtype）
results/official112_local_0910_rejudged.jsonl  完整产物（含 diag：38 个埋点字段）

运行
----
    D:/python/python.exe tools/analyze_timeout_0915.py
"""
import json
import os
import statistics as st
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(REPO, 'results', '_112_core_table.jsonl')
FULL = os.path.join(REPO, 'results', 'official112_local_0910_rejudged.jsonl')
TH = 1000          # "超时"阈值（秒）


def load():
    core = [json.loads(l) for l in open(CORE, encoding='utf-8') if l.strip()]
    full = {}
    for l in open(FULL, encoding='utf-8'):
        l = l.strip()
        if l:
            r = json.loads(l)
            full[r['id']] = r
    recs = []
    for c in core:
        f = full.get(c['id'], {})
        dg = f.get('diag') or {}
        te = dg.get('tier_evidence') or {}
        sgs = dg.get('subgoal_stats') or {}
        ag = dg.get('audit_gate') or []
        vd = [a.get('verdict') for a in ag
              if isinstance(a, dict) and a.get('step') == 'candidate_audit']
        recs.append({
            'id': c['id'], 'sec': float(c['elapsed_sec'] or 0),
            'correct': bool(c['correct']), 'tier': c['tier'] or '?',
            'qtype': c['qtype'] or '?', 'domain': c['domain'] or '(空)',
            'qlen': len(f.get('question') or ''),
            'n_cand': dg.get('n_candidates') or 0,
            'n_sg': sgs.get('n_subgoals') or 0,
            'skips': dg.get('budget_skips') or 0,
            'placeholder': bool(dg.get('placeholder')),
            'n_unk': sum(1 for v in vd if v == 'unknown'),
            'n_verd': len(vd),
            'static': te.get('static'), 'llm': te.get('llm'),
            'stages': dg.get('stage_timers') or {},
        })
    return recs


def main():
    recs = load()
    hot = [r for r in recs if r['sec'] >= TH]
    cool = [r for r in recs if r['sec'] < TH]

    print('=' * 74)
    print('一、耗时分布（%d 题）' % len(recs))
    print('=' * 74)
    s = sorted(r['sec'] for r in recs)
    print('min %.0f | p25 %.0f | 中位 %.0f | p75 %.0f | p90 %.0f | max %.0f'
          % (s[0], s[len(s)//4], s[len(s)//2], s[len(s)*3//4],
             s[int(len(s)*0.9)], s[-1]))
    print('\n%-14s %6s %8s %9s' % ('耗时区间', '题数', '正确数', '正确率'))
    for lo, hi in [(0, 300), (300, 600), (600, 900), (900, 1000),
                   (1000, 1100), (1100, 1e9)]:
        g = [x for x in recs if lo <= x['sec'] < hi]
        nc = sum(1 for x in g if x['correct'])
        lbl = '%d-%ds' % (lo, hi) if hi < 1e8 else '>=1100s'
        print('%-14s %6d %8d %8s' % (lbl, len(g), nc,
                                     '%.1f%%' % (nc/len(g)*100) if g else '-'))

    print('\n阈值 %ds → 超时组 %d 题 / 其余 %d 题' % (TH, len(hot), len(cool)))

    def rate(g):
        return '%.1f%%' % (sum(1 for x in g if x['correct'])/len(g)*100)

    def dist(g, k):
        return ' / '.join('%s:%d' % (a, b) for a, b in Counter(x[k] for x in g).most_common(4))

    print('\n' + '=' * 74)
    print('二、超时组 vs 其余 —— 特征对比')
    print('=' * 74)
    rows = [
        ('题数', str(len(hot)), str(len(cool))),
        ('正确率', rate(hot), rate(cool)),
        ('平均耗时', '%.0fs' % st.mean(x['sec'] for x in hot),
         '%.0fs' % st.mean(x['sec'] for x in cool)),
        ('tier 分布', dist(hot, 'tier'), dist(cool, 'tier')),
        ('qtype 分布', dist(hot, 'qtype'), dist(cool, 'qtype')),
        ('domain 分布', dist(hot, 'domain'), dist(cool, 'domain')),
        ('平均题面长度', '%.0f 字符' % st.mean(x['qlen'] for x in hot),
         '%.0f 字符' % st.mean(x['qlen'] for x in cool)),
        ('平均候选数', '%.2f' % st.mean(x['n_cand'] for x in hot),
         '%.2f' % st.mean(x['n_cand'] for x in cool)),
        ('平均子目标数', '%.2f' % st.mean(x['n_sg'] for x in hot),
         '%.2f' % st.mean(x['n_sg'] for x in cool)),
        ('平均 budget_skips', '%.2f' % st.mean(x['skips'] for x in hot),
         '%.2f' % st.mean(x['skips'] for x in cool)),
        ('static 难度均值', '%.2f' % st.mean(x['static'] for x in hot if x['static'] is not None),
         '%.2f' % st.mean(x['static'] for x in cool if x['static'] is not None)),
        ('llm 难度均值', '%.2f' % st.mean(x['llm'] for x in hot if x['llm'] is not None),
         '%.2f' % st.mean(x['llm'] for x in cool if x['llm'] is not None)),
    ]
    for a, b, c in rows:
        print('  %-22s | %-30s | %-30s' % (a, b, c))

    print('\n' + '=' * 74)
    print('三、阶段耗时（超时组 vs 其余，秒）')
    print('=' * 74)
    keys = set()
    for r in recs:
        keys |= set(r['stages'].keys())

    def avg(g, k):
        v = [x['stages'].get(k) for x in g if isinstance(x['stages'].get(k), (int, float))]
        return st.mean(v) if v else 0.0

    st_rows = sorted(((k, avg(hot, k), avg(cool, k)) for k in keys), key=lambda t: -t[1])
    print('%-26s %10s %10s %10s' % ('阶段', '超时组', '其余', '差值'))
    for k, h, c in st_rows[:16]:
        print('%-26s %10.1f %10.1f %+10.1f' % (k, h, c, h - c))

    print('\n' + '=' * 74)
    print('四、裁决状态（audit_gate verdict）—— 检验其可否作止损信号')
    print('=' * 74)
    for lbl, g in [('超时组', hot), ('其余', cool)]:
        tot = sum(x['n_verd'] for x in g)
        unk = sum(x['n_unk'] for x in g)
        allu = sum(1 for x in g if x['n_verd'] and x['n_unk'] == x['n_verd'])
        print('  %-6s verdict=%d  unknown=%d (%.1f%%)  全 unknown 题=%d/%d (%.1f%%)'
              % (lbl, tot, unk, unk/tot*100 if tot else 0,
                 allu, len(g), allu/len(g)*100))

    print('\n' + '=' * 74)
    print('五、信号阈值扫描（基线超时率 %.1f%%）' % (len(hot)/len(recs)*100))
    print('=' * 74)

    def scan(key, cuts, label):
        print('\n--- %s ---' % label)
        print('  %-14s %6s %9s %9s' % ('区间', '题数', '超时率', '正确率'))
        for lo, hi in cuts:
            g = [x for x in recs if x[key] is not None and lo <= x[key] < hi]
            if not g:
                continue
            print('  %-14s %6d %8.1f%% %8.1f%%'
                  % ('%g~%g' % (lo, hi) if hi < 1e8 else '>=%g' % lo, len(g),
                     sum(1 for x in g if x['sec'] >= TH)/len(g)*100,
                     sum(1 for x in g if x['correct'])/len(g)*100))

    scan('qlen', [(0, 200), (200, 400), (400, 800), (800, 1e9)], '信号1 题面长度（开题前可得）')
    scan('static', [(0, 3), (3, 4), (4, 4.5), (4.5, 99)], '信号2 static 难度（开题前可得）')
    scan('llm', [(0, 3), (3, 4), (4, 4.5), (4.5, 99)], '信号3 LLM 自评难度（开题前可得）')
    scan('n_sg', [(0, 5), (5, 7), (7, 9), (9, 99)], '信号4 子目标数（2.7 阶段可得）')

    print('\n' + '=' * 74)
    print('六、★ 反向检验：正确题的耗时分布（判断早停是否误杀）')
    print('=' * 74)
    ok = sorted(x['sec'] for x in recs if x['correct'])
    print('  正确题 %d 道：min %.0f | 中位 %.0f | max %.0f' % (len(ok), ok[0], ok[len(ok)//2], ok[-1]))
    for lo, hi in [(0, 600), (600, 900), (900, 1100), (1100, 1e9)]:
        n = sum(1 for v in ok if lo <= v < hi)
        lbl = '%d-%ds' % (lo, hi) if hi < 1e8 else '>=1100s'
        print('    %-12s %2d 题' % (lbl, n))
    print('  ⇒ <900s 的正确题仅 %d 道 / %d（早停会砍掉其余）'
          % (sum(1 for v in ok if v < 900), len(ok)))

    print('\n' + '=' * 74)
    print('七、高难度信号题的早停代价')
    print('=' * 74)
    hard = [x for x in recs if x['qlen'] >= 400 and (x['static'] or 0) >= 4]
    fh = [x for x in hard if x['sec'] < TH]
    sh = [x for x in hard if x['sec'] >= TH]
    print('  高难度信号题 %d 道' % len(hard))
    if fh:
        print('    <%ds 结束 %d 道，正确 %d 道（%.1f%%）'
              % (TH, len(fh), sum(x['correct'] for x in fh),
                 sum(x['correct'] for x in fh)/len(fh)*100))
    print('    >=%ds  %d 道，正确 %d 道（%.1f%%）—— 早停将全部损失'
          % (TH, len(sh), sum(x['correct'] for x in sh),
             sum(x['correct'] for x in sh)/len(sh)*100 if sh else 0))


if __name__ == '__main__':
    main()
