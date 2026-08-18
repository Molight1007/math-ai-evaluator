"""API 关键路径探测 v2：分类/求解/rubric 三种 prefill 形态（各 120s 超时）。"""
import json
import os
import time

import requests

env = {}
env_path = os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env")
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

url = env["INTERN_S1_BASE_URL"].rstrip("/") + "/chat/completions"
headers = {"Authorization": "Bearer " + env["INTERN_S1_API_KEY"],
           "Content-Type": "application/json"}


def probe(payload, label, timeout=120):
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        dt = time.time() - t0
        if r.status_code == 200:
            d = r.json()
            c = d["choices"][0]["message"].get("content", "")
            print(f"[{label}] OK {dt:.1f}s content={c[:60]!r}")
            return True
        print(f"[{label}] HTTP {r.status_code} {dt:.1f}s {r.text[:120]}")
        return False
    except requests.exceptions.Timeout:
        print(f"[{label}] TIMEOUT {timeout}s")
        return False
    except Exception as e:
        print(f"[{label}] {type(e).__name__}: {str(e)[:120]}")
        return False


# 1) 分类（prefill 本题类型：）
probe({"model": env["INTERN_S1_MODEL"],
       "messages": [{"role": "system", "content": "你是数学题分类专家，只输出领域名。"},
                    {"role": "user", "content": "解方程：x^2-5x+6=0"},
                    {"role": "assistant", "content": "本题类型："}],
       "temperature": 0.01, "max_tokens": 64}, "classify")

# 2) 求解（prefill ## 问题分析）
probe({"model": env["INTERN_S1_MODEL"],
       "messages": [{"role": "system", "content": "你是数学解题专家，按四章节输出解答。"},
                    {"role": "user", "content": "解方程：x^2-5x+6=0，求 x。"},
                    {"role": "assistant", "content": "## 问题分析\n"}],
       "temperature": 0.1, "max_tokens": 2048}, "solve")

# 3) rubric 判分（prefill {）
probe({"model": env["INTERN_S1_MODEL"],
       "messages": [{"role": "system", "content": "你是评审专家，输出 JSON。"},
                    {"role": "user", "content": "判断 x=2 是否是 x^2-5x+6=0 的解。"},
                    {"role": "assistant", "content": '{"verdict":"'}],
       "temperature": 0.0, "max_tokens": 256}, "rubric")
