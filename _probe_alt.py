"""探测备用端点（chat.intern-ai.org.cn / Intern-S2-Preview-397B）的 prefill 可靠性。"""
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

url = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
headers = {"Authorization": "Bearer " + env["INTERN_S1_API_KEY"],
           "Content-Type": "application/json"}

CASES = [
    ("classify", [
        {"role": "system", "content": "你是数学题分类专家，只输出领域名。"},
        {"role": "user", "content": "解方程：x^2-5x+6=0"},
        {"role": "assistant", "content": "本题类型："}], 64, 0.01),
    ("solve", [
        {"role": "system", "content": "你是数学解题专家，按四章节输出解答。"},
        {"role": "user", "content": "解方程：x^2-5x+6=0，求 x。"},
        {"role": "assistant", "content": "## 问题分析\n"}], 2048, 0.1),
    ("verdict", [
        {"role": "system", "content": "你是评审专家，只输出 VERDICT: A 或 B。"},
        {"role": "user", "content": "x=2 是 x^2-5x+6=0 的解吗？"},
        {"role": "assistant", "content": "VERDICT: "}], 64, 0.0),
    ("rubric", [
        {"role": "system", "content": "你是评审专家，输出 JSON。"},
        {"role": "user", "content": "判断 x=2 是否是 x^2-5x+6=0 的解。"},
        {"role": "assistant", "content": '{"verdict":"'}], 256, 0.0),
]


def probe(messages, label, max_tokens, temperature, timeout=60):
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers,
                          json={"model": "Intern-S2-Preview-397B", "messages": messages,
                                "temperature": temperature, "max_tokens": max_tokens},
                          timeout=timeout)
        dt = time.time() - t0
        if r.status_code == 200:
            c = r.json()["choices"][0]["message"].get("content", "")
            print(f"[{label}] OK {dt:.1f}s content={c[:70]!r} (len={len(c)})")
            return len(c) > 0
        print(f"[{label}] HTTP {r.status_code} {dt:.1f}s {r.text[:120]}")
        return False
    except requests.exceptions.Timeout:
        print(f"[{label}] TIMEOUT {timeout}s")
        return False
    except Exception as e:
        print(f"[{label}] {type(e).__name__}: {str(e)[:120]}")
        return False


ok = 0
for label, msgs, mt, temp in CASES:
    for i in range(2):  # 每种形态测 2 次看稳定性
        if probe(msgs, f"{label}#{i + 1}", mt, temp):
            ok += 1
print(f"\n备用端点 prefill 成功率: {ok}/{len(CASES) * 2}")
