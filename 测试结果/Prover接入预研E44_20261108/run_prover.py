# -*- coding: utf-8 -*-
"""E44 · 调用 OpenAI 兼容的 prover endpoint（探针，不在生产链上）

用法（拿到 endpoint 后）：
  python run_prover.py --endpoint http://127.0.0.1:8080/v1 \
      --model Goedel-Prover-V2-8B --key "" --n 1 --temperature 0 \
      --out replies.json

输入固定取 L2 B 组 18 题的 formal_sig（同输入，满足 E14 协议①）。
输出 replies.json：每条含 tag/qid/name/prompt/reply/status/latency。

★ 这不是策略开关：endpoint/model 是外部资源地址，由调用方显式传入；
  项目 POLICY 101 项、env 覆盖链一律不动。
"""
import argparse
import json
import os
import time

import requests

from prover_gate import build_prompt, to_formal_statement

HERE = os.path.dirname(os.path.abspath(__file__))
B_JSON = os.path.join(HERE, "..", "L2逐步探针_20261108",
                      "l2_step_probe_b_base2.json")


def load_inputs(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    out = []
    for i, r in enumerate(rows, 1):
        name = "probe_%s" % str(r.get("tag") or ("q%02d" % i))
        stmt = to_formal_statement(r["formal_sig"], name)
        out.append({"tag": r.get("tag"), "qid": r.get("qid"),
                    "name": name, "sig": r["formal_sig"],
                    "statement": stmt, "prompt": build_prompt(stmt)})
    return out


def call(endpoint, model, key, prompt, temperature, max_tokens, timeout):
    url = endpoint.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    t0 = time.time()
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    lat = round(time.time() - t0, 2)
    if r.status_code != 200:
        return "", "HTTP_%s: %s" % (r.status_code, r.text[:200]), lat
    d = r.json()
    try:
        return d["choices"][0]["message"]["content"], "OK", lat
    except (KeyError, IndexError, TypeError):
        return "", "BAD_RESPONSE: %s" % json.dumps(d)[:200], lat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", default="Goedel-Prover-V2-8B")
    ap.add_argument("--key", default="")
    ap.add_argument("--inputs", default=B_JSON)
    ap.add_argument("--out", default=os.path.join(HERE, "replies.json"))
    ap.add_argument("--n", type=int, default=1, help="每题采样条数")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（smoke）")
    args = ap.parse_args()

    items = load_inputs(args.inputs)
    if args.limit:
        items = items[:args.limit]
    rows = []
    for k in range(args.n):
        for it in items:
            reply, status, lat = call(
                args.endpoint, args.model, args.key, it["prompt"],
                args.temperature, args.max_tokens, args.timeout)
            rows.append(dict(it, sample=k, reply=reply, status=status,
                             latency_sec=lat))
            print("[%s s%d] %s %s (%.1fs)" %
                  (status, k, it["tag"], it["name"], lat), flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"endpoint": args.endpoint, "model": args.model,
                   "temperature": args.temperature, "n": args.n,
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    print("wrote %s (%d rows)" % (args.out, len(rows)))


if __name__ == "__main__":
    main()
