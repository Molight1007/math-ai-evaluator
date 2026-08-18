"""最小 API 探活：读 ~/.math_evaluator/.env 的 key，发 1 次 tiny 请求（max_tokens=16）。
不打印 key 内容。用于隔离「端点/key 问题」与「大调用慢问题」。"""
import json
import os
import time
import sys

import requests

# 读配置（仅本地，不输出 key 值）
env = {}
env_path = os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env")
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

api_key = env.get("INTERN_S1_API_KEY", "")
base_url = env.get("INTERN_S1_BASE_URL", "")
model = env.get("INTERN_S1_MODEL", "")
print(f"endpoint: {base_url}/chat/completions")
print(f"model:    {model}")
print(f"key:      {'已设置(' + str(len(api_key)) + '字符)' if api_key else '未设置'}")

url = f"{base_url.rstrip('/')}/chat/completions"
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

def probe(payload, label, timeout=60):
    t0 = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        dt = time.time() - t0
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "")
            usage = data.get("usage", {})
            print(f"[{label}] OK {dt:.1f}s | content={content[:60]!r} | usage={usage}")
            return True
        print(f"[{label}] HTTP {resp.status_code} {dt:.1f}s | {resp.text[:200]}")
        return False
    except requests.exceptions.Timeout:
        print(f"[{label}] TIMEOUT after {timeout}s")
        return False
    except Exception as e:
        print(f"[{label}] ERROR {type(e).__name__}: {str(e)[:200]}")
        return False

# 1) 纯小调用（无 prefill）
probe({"model": model, "messages": [{"role": "user", "content": "1+1=?"}],
       "temperature": 0.0, "max_tokens": 16}, "tiny")

# 2) 带 assistant prefill 的小调用（复现 agent 主路径形态）
probe({"model": model,
       "messages": [{"role": "system", "content": "你只输出结果。"},
                    {"role": "user", "content": "1+1=?"},
                    {"role": "assistant", "content": "2"}],
       "temperature": 0.0, "max_tokens": 16}, "prefill")

# 3) 分类任务小调用（agent 首调形态）
probe({"model": model,
       "messages": [{"role": "system", "content": "你是数学题分类专家，只输出领域名。"},
                    {"role": "user", "content": "解方程：x^2-5x+6=0"},
                    {"role": "assistant", "content": "本题类型："}],
       "temperature": 0.01, "max_tokens": 64}, "classify")
