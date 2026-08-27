# -*- coding: utf-8 -*-
"""解析两份评测报告 JSON，输出每题的关键信息与分析汇总"""
import json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def show(path, label):
    data = load(path)
    print("=" * 100)
    print(f"### {label}  ({path})")
    print("=" * 100)
    # 探测结构
    if isinstance(data, dict):
        print("顶层keys:", list(data.keys()))
        items = data.get('results') or data.get('items') or data.get('data') or []
        if not items and isinstance(data, dict):
            # 尝试找包含题目列表的key
            for k, v in data.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    items = v
                    break
    elif isinstance(data, list):
        items = data
    else:
        items = []
    print(f"共 {len(items)} 题")
    for i, it in enumerate(items):
        pid = it.get('problem_id') or it.get('id') or f"Q{i}"
        domain = it.get('domain', '')
        q = it.get('question', '')
        ref = it.get('reference_answer', '')
        ans = it.get('intern_answer', '')
        correct = it.get('is_correct', it.get('correct', ''))
        err = it.get('error_type', '')
        conf = it.get('confidence', '')
        judge_exp = it.get('judge_explanation', '')
        qs = q.replace('\n', ' ')[:100]
        ans_s = ans.replace('\n', ' ')[:120]
        print(f"\n[{i+1}] {pid} | {domain} | correct={correct} | err={err} | conf={conf}")
        print(f"  Q: {qs}")
        print(f"  A: {ans_s}")
        if judge_exp:
            print(f"  Judge: {judge_exp[:200]}")

if __name__ == '__main__':
    show(r'd:\挑战杯\测试结果\原始输出和推理过程\report_20260820_155956.json', '报告1: 155956 (AnswerBench)')
    show(r'd:\挑战杯\测试结果\原始输出和推理过程\report_20260820_190112.json', '报告2: 190112 (ProofBench)')
