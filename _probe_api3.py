"""API 探测 v3：thinking_mode 参数 + 备用端点/模型。"""
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

key = env["INTERN_S1_API_KEY"]

ENDPOINTS = [
    ("puyu/intern-s1", env["INTERN_S1_BASE_URL"].rstrip("/") + "/chat/completions", env["INTERN_S1_MODEL"]),
    ("alt/Intern-S2", "https://chat.intern-ai.org.cn/api/v1/chat/completions", "Intern-S2-Preview-397B"),
]

MSG = [
    {"role": "system", "content": "你是数学题分类专家，只输出领域名。"},
    {"role": "user", "content": "解方程：x^2-5x+6=0"},
    {"role": "assistant", "content": "本题类型："},
]


def probe(url, model, label, timeout=90, **extra):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    payload = {"model": model, "messages": MSG, "temperature": 0.01, "max_tokens": 64}
    payload.update(extra)
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        dt = time.time() - t0
        if r.status_code == 200:
            d = r.json()
            c = d["choices"][0]["message"].get("content", "")
            print(f"[{label}] OK {dt:.1f}s content={c[:60]!r}")
            return True
        print(f"[{label}] HTTP {r.status_code} {dt:.1f}s {r.text[:150]}")
        return False
    except requests.exceptions.Timeout:
        print(f"[{label}] TIMEOUT {timeout}s")
        return False
    except Exception as e:
        print(f"[{label}] {type(e).__name__}: {str(e)[:150]}")
        return False


for name, url, model in ENDPOINTS:
    probe(url, model, f"{name} 默认")
    probe(url, model, f"{name} thinking_mode=false", thinking_mode=False)
