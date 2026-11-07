#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命题级探针：自然语言证明 -> 抽取中间结论 -> 逐条形式化 -> 只验可陈述性。

设计三条硬约束（对应 E37/E38 的教训）：
1) 每条中间结论必须**自包含**（变量与前提全部显式），否则无法单独判定；
2) 只判"可陈述"（rc==0，allow sorry），不判"可证"——后者是另一层；
3) 每条命题独立编译、独立定位失败，不依赖前一条是否成功。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

LEAN = os.environ.get("LEAN_BIN", "/home/ubuntu/mathpilot/deploy/lean-4.31.0-linux/bin/lean")
LEAN_PATH = os.environ.get("LEAN_PATH", "/home/ubuntu/mathpilot/deploy/mathlib-olean")
WORK = os.environ.get("PROP_WORK", "/tmp/l2probe/prop")

SYS1 = """你是数学证明专家。你会用中文写严格的证明，并把证明里用到的每个中间结论单独列出来。

规则：
- 先写完整的中文证明。
- 再把证明里**每一个独立的中间结论**编号列出。
- 每条中间结论必须是**自包含**的：写清它需要的所有前提（"设…，若…，则…"），
  不要出现"由上式""代入(3)"这类依赖上下文的说法。
- 每条只陈述**结论本身**，不要写推导过程。
- 不要合并两条结论，也不要写"证明思路"这种非命题内容。"""

SYS2 = """你是 Lean 4 + Mathlib 的形式化专家。你只做一件事：把一条中文数学命题翻译成 Lean 4 命题。

要求：
- 用 `example ... : ... := by sorry` 的形式，只陈述命题，不证明。
- **自包含**：所有出现的符号都要显式声明类型（如 `(x y z : ℝ)`），所有前提都要作为假设列出（如 `(hx : 0 < x)`）。
- 不要引入命题里没有的额外假设。
- 实数用 ℝ，整数用 ℤ，自然数用 ℕ；幂用 `^`；不要用 Mathlib 里不存在的自定义记号。
- 只输出代码块，不要任何解释。"""


def call_llm(base, key, model, messages, prefill="", max_tokens=2048, timeout=300, retries=3):
    url = base.rstrip("/") + "/chat/completions"
    msgs = list(messages)
    if prefill:
        msgs.append({"role": "assistant", "content": prefill})
    payload = {"model": model, "messages": msgs, "temperature": 0.0,
               "max_tokens": max_tokens, "stream": False}
    data = json.dumps(payload).encode("utf-8")
    last = ""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                obj = json.loads(r.read().decode("utf-8"))
            ch = obj["choices"][0]
            txt = ch["message"]["content"] or ""
            if txt.startswith(prefill):
                txt = txt[len(prefill):]
            return prefill + txt, ch.get("finish_reason", ""), obj.get("usage", {}) or {}
        except Exception as e:  # noqa: BLE001
            last = str(e)[:300]
            time.sleep(2 + i * 3)
    raise RuntimeError("llm failed: " + last)


def split_conclusions(text):
    """从模型输出里抠出编号的中间结论列表。"""
    body = text or ""
    marker = "中间结论"
    i = body.find(marker)
    if i >= 0:
        body = body[i:]
    items, cur = [], None
    for line in body.splitlines():
        m = re.match(r"^\s*(\d{1,2})\s*[.、)．]\s*(.+)$", line)
        if m:
            if cur:
                items.append(cur.strip())
            cur = m.group(2).strip()
        elif cur is not None and line.strip():
            cur += " " + line.strip()
    if cur:
        items.append(cur.strip())
    out = []
    for it in items:
        it = it.strip().strip("*").strip()
        if len(it) < 6:
            continue
        out.append(it)
    return out


def extract_code(text):
    body = text or ""
    m = re.search(r"```(?:lean|Lean)?\s*\n([\s\S]*?)```", body)
    code = m.group(1) if m else body
    lines = [l for l in code.splitlines()]
    keep = []
    started = False
    for l in lines:
        s = l.strip()
        if not started and (s.startswith("example") or s.startswith("theorem")
                            or s.startswith("lemma") or s.startswith("import")):
            started = True
        if started:
            keep.append(l)
    if not keep:
        keep = [l for l in lines if l.strip()]
    return "\n".join(keep).strip()


ERR_RE = re.compile(r"error(?:\([^)]*\))?:\s*[^\n]*")


def compile_stmt(code, tag):
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, tag + ".lean")
    full = "import Mathlib.Tactic\n\n" + (code or "").strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(full)
    env = dict(os.environ)
    env["LEAN_PATH"] = LEAN_PATH
    t0 = time.time()
    try:
        r = subprocess.run([LEAN, path], capture_output=True, env=env, timeout=300)
        raw = (r.stderr or b"").decode("utf-8", "replace") + (r.stdout or b"").decode("utf-8", "replace")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"rc": -9, "statable": False, "first_error": "TIMEOUT",
                "compile_sec": round(time.time() - t0, 2), "tail": ""}
    errs = ERR_RE.findall(raw)
    return {
        "rc": rc,
        "statable": rc == 0,
        "first_error": (errs[0][:300] if errs else ""),
        "n_errors": len(errs),
        "compile_sec": round(time.time() - t0, 2),
        "tail": raw[-600:],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goals", default="/tmp/l2probe/l2_goals.json")
    ap.add_argument("--qids", default="", help="逗号分隔，留空取前 3 个 qid")
    ap.add_argument("--max-props", type=int, default=10)
    ap.add_argument("--out", default="/tmp/l2probe/l2_prop_probe.json")
    args = ap.parse_args()

    base = os.environ.get("OPENAI_BASE_URL", "")
    key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "Intern-S2-Preview-397B")
    if not base or not key:
        print("缺少 OPENAI_BASE_URL / OPENAI_API_KEY", file=sys.stderr)
        return 2

    goals = [g for g in json.load(open(args.goals, encoding="utf-8")) if g.get("compile_ok")]
    by_q = {}
    for g in goals:
        by_q.setdefault(g["qid"], g)
    want = [q.strip() for q in args.qids.split(",") if q.strip()] or list(by_q)[:3]
    print("题目:", want)

    results = []
    for qid in want:
        it = by_q[qid]
        q = it["question"]
        print("=" * 70)
        print(qid, "|", q[:90].replace("\n", " "))
        prompt = ("题目：\n%s\n\n"
                  "请给出完整证明，并按系统要求列出全部中间结论。" % q)
        try:
            reply, fin, usage = call_llm(base, key, model,
                                         [{"role": "system", "content": SYS1},
                                          {"role": "user", "content": prompt}],
                                         prefill="【证明】\n", max_tokens=4096)
        except Exception as e:  # noqa: BLE001
            print("  LLM 失败:", e)
            results.append({"qid": qid, "error": str(e)[:300]})
            continue
        props = split_conclusions(reply)[:args.max_props]
        print("  抽到中间结论: %d 条, finish=%s" % (len(props), fin))

        rec = {"qid": qid, "question": q, "finish_reason": fin,
               "usage": usage, "reply": reply[:4000], "props": []}
        for k, p in enumerate(props, 1):
            fp = ("题目：\n%s\n\n下面这条命题需要翻译成 Lean 4：\n\"%s\"\n\n"
                  "注意：把它写成自包含的 example，补全所有变量声明和前提假设，"
                  "用 `:= by sorry` 结尾。" % (q, p))
            try:
                cre, cfin, _ = call_llm(base, key, model,
                                        [{"role": "system", "content": SYS2},
                                         {"role": "user", "content": fp}],
                                        prefill="```lean\n", max_tokens=1024)
                code = extract_code(cre)
            except Exception as e:  # noqa: BLE001
                code, cfin = "", "ERROR:" + str(e)[:120]
            chk = compile_stmt(code, "%s_p%02d" % (qid[:12], k))
            rec["props"].append({"idx": k, "nl": p, "lean": code,
                                 "finish": cfin, **chk})
            print("   p%-2d %-10s %s" % (k, "STATABLE" if chk["statable"] else "FAIL",
                                         (chk["first_error"] or "")[:90]))
            print("       NL: %s" % p[:110])
        ok = sum(1 for x in rec["props"] if x.get("statable"))
        rec["statable_rate"] = "%d/%d" % (ok, len(rec["props"]))
        results.append(rec)
        print("  小计: %s 可陈述" % rec["statable_rate"])

    json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = sum(len(r.get("props", [])) for r in results)
    ok = sum(1 for r in results for p in r.get("props", []) if p.get("statable"))
    print("=" * 70)
    print("总计: %d/%d 可陈述" % (ok, tot))
    print("结果已写:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
