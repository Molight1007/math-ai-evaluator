"""拉取 Omni-MATH（4428 题 / 奥赛级 / 带标准答案）并按项目题库格式落盘。

为什么需要它
------------
`official112_full.jsonl` 只有 112 题，且是**反复调参用过**的那 112 题 ——
在同一批题上连续比较，会同时带来两个问题：① 单题方差极大（同一配置跨日
3~4 分波动）② 隐性过拟合（针对这 112 题的特征调整，换题库就废）。
Omni-MATH 提供 4428 道竞赛级题目、33 个子域、10 个难度档，可用于
**无偏抽样**与 **OOD 验证**。

来源与许可
----------
HuggingFace `KbsdJames/Omni-MATH`（Apache-2.0），论文 arXiv:2410.07985。
原始字段：domain / difficulty / problem / solution / answer / source。

用法
----
    python tools/fetch_omni_math.py download --out 题库/omni_math/test.jsonl
    python tools/fetch_omni_math.py sample --src 题库/omni_math/test.jsonl \\
        --n 8 --seed 20261027 --out 题库/omni_math_sample8_20261027.jsonl

`sample` 的筛选条件（**先定规则再看结果，不看结果定规则**）：
    · 答案可判：长度 ≤ ``--max-answer-len``，且不含 `\\begin{` 环境
    · 题面可读：长度 ≤ ``--max-problem-len``（控制单题耗时）
    · 难度分层：按 difficulty 排序后**等距抽样**，避免全落到最难档
    · 固定 seed ⇒ 同一条命令永远得到同一批题（可复现、可写进报告）
"""

from __future__ import annotations

import argparse
import json
import re
import os
import random
import sys
import urllib.request

_INT_ANSWER_RE = re.compile(r"^[+-]?\d{1,4}$")

MIRROR = "https://hf-mirror.com"
REPO = "KbsdJames/Omni-MATH"
FILE = "test.jsonl"


def _download(out: str) -> int:
    url = f"{MIRROR}/datasets/{REPO}/resolve/main/{FILE}"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    print(f"下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mathpilot/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        f.write(r.read())
    n = sum(1 for _ in open(out, encoding="utf-8"))
    print(f"落盘 {out}  {n} 行  {os.path.getsize(out) / 1e6:.1f} MB")
    return n


def _to_record(i: int, raw: dict) -> dict:
    dom = str(raw.get("domain") or "")
    # 原始 domain 形如 "['Mathematics -> Algebra -> Other']" ⇒ 取三级以内路径
    dom = dom.strip("[]'\"")
    parts = [p.strip() for p in dom.split("->") if p.strip()]
    domain = " > ".join(parts[1:3]) if len(parts) > 1 else (parts[0] if parts else "")
    return {
        "id": f"omni-{i:04d}",
        "question": str(raw.get("problem") or "").strip(),
        "answer": str(raw.get("answer") or "").strip(),
        "domain": domain,
        "meta": {
            "source": "Omni-MATH",
            "origin": str(raw.get("source") or ""),
            "difficulty": float(raw.get("difficulty") or 0),
            "solution_chars": len(str(raw.get("solution") or "")),
        },
    }


def _load(src: str) -> list:
    rows = []
    with open(src, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            rows.append(_to_record(i, json.loads(line)))
    return rows


def _eligible(rec: dict, max_ans: int, max_prob: int) -> bool:
    a, q = rec["answer"], rec["question"]
    if not a or not q:
        return False
    if len(a) > max_ans or "\\begin{" in a:
        return False
    if len(q) > max_prob:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Omni-MATH 拉取 / 抽样")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download")
    d.add_argument("--out", default="题库/omni_math/test.jsonl")

    s = sub.add_parser("sample")
    s.add_argument("--src", default="题库/omni_math/test.jsonl")
    s.add_argument("--n", type=int, default=8)
    s.add_argument("--seed", type=int, default=20261027)
    s.add_argument("--max-answer-len", type=int, default=40)
    s.add_argument("--max-problem-len", type=int, default=1200)
    s.add_argument("--min-difficulty", type=float, default=0.0,
                   help="难度下限（Omni-MATH 标 1~10，TST 级约 7+）")
    s.add_argument("--max-difficulty", type=float, default=99.0)
    s.add_argument("--answer-form", default="any", choices=["any", "integer"],
                   help="integer = 只收纯整数答案（判分最可靠，不把归一化失败算成答错）")
    s.add_argument("--domains", default="",
                   help="用逗号分隔的顶层域做**均衡抽样**（如 Algebra,Geometry）；空 = 不分域")
    s.add_argument("--out", default="")

    args = ap.parse_args()

    if args.cmd == "download":
        _download(args.out)
        return 0

    if not os.path.isfile(args.src):
        print(f"FATAL: 找不到 {args.src}，先跑 download", file=sys.stderr)
        return 2
    rows = _load(args.src)
    ok = [r for r in rows if _eligible(r, args.max_answer_len, args.max_problem_len)]
    lo, hi = args.min_difficulty, args.max_difficulty
    ok = [r for r in ok if lo <= r["meta"]["difficulty"] <= hi]
    if args.answer_form == "integer":
        ok = [r for r in ok if _INT_ANSWER_RE.match(r["answer"])]
    print(f"总 {len(rows)} 题，符合条件 {len(ok)} 题")

    rng = random.Random(args.seed)
    groups = {}
    if args.domains:
        want = [d.strip() for d in args.domains.split(",") if d.strip()]
        for d in want:
            groups[d] = [r for r in ok if r["domain"].split(" > ")[0] == d]
        picked = []
        k = 0
        while len(picked) < args.n:
            for d in want:
                if len(picked) >= args.n:
                    break
                pool = groups.get(d) or []
                if not pool:
                    continue
                # 组内按难度分层：第 k 轮取第 k 个难度分位，避免整组落在同一档
                pool = sorted(pool, key=lambda r: (r["meta"]["difficulty"], r["id"]))
                idx = min(len(pool) - 1, int((k + 0.5) * len(pool) / max(1, (args.n + len(want) - 1) // len(want))))
                cand = pool[idx]
                while any(cand["id"] == p["id"] for p in picked) and idx + 1 < len(pool):
                    idx += 1
                    cand = pool[idx]
                if any(cand["id"] == p["id"] for p in picked):
                    groups[d] = []
                    continue
                picked.append(cand)
            k += 1
    else:
        # 难度分层：排序后等距取，避免全是最难档（单题耗时不可控）
        ok.sort(key=lambda r: (r["meta"]["difficulty"], r["id"]))
        step = max(1, len(ok) // args.n)
        picked, used = [], set()
        for k in range(args.n):
            lo_i = k * step
            hi_i = len(ok) if k == args.n - 1 else (k + 1) * step
            pool = ok[lo_i:hi_i] or ok
            cand = rng.choice(pool)
            while cand["id"] in used and len(used) < len(ok):
                cand = rng.choice(ok)
            used.add(cand["id"])
            picked.append(cand)

    out = args.out or f"题库/omni_math_sample{args.n}_{args.seed}.jsonl"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"抽样 {len(picked)} 题 → {out}")
    for r in picked:
        print(f"  {r['id']}  d={r['meta']['difficulty']:<4} {r['domain'][:28]:<30}"
              f" ans={r['answer'][:34]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
