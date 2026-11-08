"""L2 第 3 步 · EMPTY 不信任实验（E41，单变量）。

## 为什么改这一处

回看 `L2逐步探针_20261107/` 四路的 21 条 EMPTY：**20 条的理由是「目标已被前面
的 xxx 闭合」**，而其中每一条上一步的编译结果都是 `UNSOLVED`，trace 里的 goal
也仍然非空。⇒ EMPTY 不是「模型不会下手」，是**模型谎报完成**。

而 v3 循环拿到空 tactic 就直接终止 —— 明明手上握着反证（刚编译过的前缀仍未
解决目标），却信了模型的自报。

## 改了什么（只有这一处）

`if not tactic:` 分支：先驳回，把「编译器刚说还有目标没解决 + 目标原文」当成
证据回给模型，让它续写；不消耗步骤数，最多 `--empty-rejects` 轮（默认 2），
仍然空才判 `EMPTY_CONFIRMED`（真放弃）。

★ 提示词、Lean4 语法表、编译错误反馈轮数、检索通道 **一律不动** —— 对照臂就是
  `l2_step_probe_b_fix.json`（逐步 + 语法表 + 编译反馈 = 2/18，其中 8 条 EMPTY）。
★ `--empty-rejects 0` 可复现旧行为（stop 仍写 EMPTY），用于同机再验一次基线。
"""
import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

LEAN = "/home/ubuntu/mathpilot/deploy/lean-4.31.0-linux/bin/lean"
ENV_LEAN_PATH = "/home/ubuntu/mathpilot/deploy/mathlib-olean"
WORK = "/tmp/l2probe/step"
GOALS = "/tmp/l2probe/l2_goals.json"

PREFIX = "TACTIC:\n"
SORRY_TAIL = re.compile(r":=\s*by\s+sorry\b")
FENCE = re.compile(r"```(?:lean|json)?\s*(.*?)```", re.S)
ANY_ERR = re.compile(r":\d+:\d+: error:")
BANNED = re.compile(r"\b(sorry|admit)\b")
UNSOLVED = re.compile(r"error:\s*unsolved goals\s*\n")
NEW_DIAG = re.compile(r"^\S+:\d+:\d+:\s*(?:error|warning)")

SIMPLE = [
    ("s01", "example : (2:Nat) + 2 = 4 := by sorry"),
    ("s02", "example : ∀ n : Nat, n + 0 = n := by sorry"),
    ("s03", "example : (3:Nat) * 4 = 12 := by sorry"),
    ("s04", "example : ∀ a b : Nat, a + b = b + a := by sorry"),
    ("s05", "example : (5:Int) - 3 = 2 := by sorry"),
    ("s06", "example : ∀ x : ℝ, x + 0 = x := by sorry"),
    ("s07", "example : ∃ n : Nat, n = 7 := by sorry"),
    ("s08", "example : (2:Nat)^10 = 1024 := by sorry"),
    ("s09", "example : ∀ n : Nat, n ≤ n + 1 := by sorry"),
    ("s10", "example : (1:ℝ)/2 + 1/2 = 1 := by sorry"),
]

SYSTEM = r"""你是 Lean 4 + Mathlib 定理证明器。你正在做**逐步交互式**证明。

★★ 这是 Lean 4，**不是 Lean 3**。下列 Lean 3 写法在 Lean 4 里会报 `unknown tactic`，一律禁止：

| Lean 3（禁止） | Lean 4（必须改用） |
|---|---|
| `refl` | `rfl` |
| `existsi x` | `use x` |
| `cases h with x h` | `obtain ⟨x, h⟩ := h` |
| `cases h with x y h1 h2` | `obtain ⟨x, y, h1, h2⟩ := h` |
| `induction n with k ih` | `induction n with \| zero => ... \| succ k ih => ...` |
| `by_contradiction h` | `by_contra h` |
| `split` 拆 if/match | `by_cases h : p` 或 `rcases` |

Lean 4 里这些是可用的：`intro`、`exact`、`apply`、`rw`、`simp`、`omega`、
`norm_num`、`linarith`、`nlinarith`、`ring`、`positivity`、`gcongr`、`have`、
`obtain`、`rcases`、`by_cases`、`by_contra`、`use`、`constructor`、`calc`。

规则：
- 我会给你当前目标状态和已写的证明前缀。
- 你**只写下一个 tactic 步骤**（一行或一个小的 case 分支），不要写完整证明。
- 写完后我会编译并把新的目标状态再给你。
- 绝对不能用 sorry 或 admit。

★ 检索通道（重要）：你不必凭记忆猜引理名。若你**不确定**当前该用哪个 Mathlib 引理，
可以先**只**输出：

SEARCH:
<关键词，例如 dvd_factorial 或 mul_div_cancel>

我会在本地 Mathlib 源码里检索，把命中的声明名与文件路径给你，你再写 tactic。
检索**不计入**步骤数，但每题有次数上限；用完必须直接写 tactic。
输出 SEARCH 的那一轮**不要**同时写 TACTIC。

严格按此格式输出，不要写任何别的内容：

TACTIC:
<下一个 tactic 步骤>
REASON:
<一句中文说明>

如果当前目标已经被前面的步骤闭合，TACTIC: 写 EMPTY。"""


FIX_SYSTEM = SYSTEM + """

★★ 现在进入**修正模式**：上一步 tactic 编译失败，你要修的就是那一步。
不要改变前面的证明前缀，只重写当前这一步。"""


def stitch(prefix, completion):
    body = completion if isinstance(completion, str) else str(completion or "")
    if not prefix:
        return body
    s = body.lstrip()
    if s.startswith(prefix):
        return s
    head = body[:len(prefix) + 40]
    if prefix in head:
        return body[body.index(prefix):]
    return prefix + body


def call_llm(base, key, model, prompt, max_tokens=1024, timeout=180, retries=3,
             system=None):
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": PREFIX},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    last = ""
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            ch = body["choices"][0]
            return (stitch(PREFIX, ch["message"].get("content") or ""),
                    ch.get("finish_reason"), body.get("usage") or {})
        except urllib.error.HTTPError as e:
            last = "HTTP %s %s" % (e.code, e.read()[:200].decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:200])
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


SEARCH_BIN = "/home/ubuntu/leanlsp-venv/bin/python"
PROXY = "/home/ubuntu/mathpilot/tools/lean_local/lean_mcp_proxy.py"
LEAN_PROJECT = "/home/ubuntu/mathpilot/deploy/mathlib-olean"
MAX_SEARCH = 5
UNKNOWN_ID = re.compile(r"unknown (?:identifier|constant)\s+'([^'\n]+)'")


def _has_olean(file_rel):
    """检索命中的模块必须真有 olean，否则模型引用了也编不过。

    ★ 实测：Mathlib v4.31.0 源码 8169 个模块，本机 olean 闭包只有 7589 个，
      633 个模块「有源码无 olean」（集中在 Algebra/Category 范畴论/层论）。
      不设这道闸，检索会返回不可用的名字 —— 比不检索更糟。
    """
    if not file_rel:
        return False
    p = file_rel[:-5] if file_rel.endswith(".lean") else file_rel
    if p.startswith("/"):
        return os.path.isfile(p + ".olean")
    return os.path.isfile(os.path.join(LEAN_PROJECT, p + ".olean"))


def local_search(query, limit=8):
    """调 lean-lsp-mcp 的 local_search，在 Mathlib 源码里检索声明。"""
    req = json.dumps({"id": 1, "op": "local_search",
                      "query": query, "limit": limit})
    env = dict(os.environ)
    env["LEAN_PROJECT_PATH"] = LEAN_PROJECT
    env["LEAN_PATH"] = ENV_LEAN_PATH
    try:
        r = subprocess.run([SEARCH_BIN, PROXY], input=req + "\n",
                           capture_output=True, text=True, timeout=180, env=env)
    except Exception:  # noqa: BLE001
        return []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            inner = json.loads(d.get("raw") or "{}")
        except Exception:  # noqa: BLE001
            continue
        raw_items = inner.get("items") or []
        items = [m for m in raw_items if _has_olean(m.get("file", ""))]
        if len(items) != len(raw_items):
            print("[search] %-24s kept %d/%d（过滤掉无 olean 的模块）"
                  % (query, len(items), len(raw_items)))
        return items
    return []


def fmt_hits(items):
    if not items:
        return "  (无命中)"
    return "\n".join("  - %s (%s)   %s" % (m.get("name"), m.get("kind"),
                                           m.get("file", ""))
                     for m in items[:8])


def parse_reply(text):
    body = text or ""
    si = body.find("SEARCH:")
    ti = body.find("TACTIC:")
    if si >= 0 and (ti < 0 or si < ti):
        q = re.split(r"(?m)^\s*(?:TACTIC|REASON)\s*:", body[si + 7:],
                     maxsplit=1)[0].strip()
        return {"search": q, "tactic": "", "reason": "", "raw": body[:500]}
    i = ti
    if i >= 0:
        body = body[i + len("TACTIC:"):]
    parts = re.split(r"(?m)^\s*REASON\s*:", body, maxsplit=1)
    tactic = parts[0]
    reason = parts[1].strip() if len(parts) > 1 else ""
    m = FENCE.search(tactic)
    if m:
        tactic = m.group(1)
    tactic = tactic.strip()
    if tactic.upper().startswith("EMPTY"):
        tactic = ""
    return {"search": "", "tactic": tactic, "reason": reason[:400],
            "raw": body[:500]}


def build_code(sig, tactics):
    body = "import Mathlib.Tactic\n\n" + sig.strip()
    body = SORRY_TAIL.sub(":= by", body)
    if tactics:
        body += "\n" + "\n".join("  " + t.lstrip() if not t.startswith("  ") else t
                                 for t in tactics)
    return body + "\n"


def compile_check(code, tag):
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, "%s.lean" % tag)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    env = dict(os.environ)
    env["LEAN_PATH"] = ENV_LEAN_PATH
    t0 = time.time()
    try:
        r = subprocess.run([LEAN, path], capture_output=True, timeout=600, env=env)
        raw = (r.stderr or b"").decode("utf-8", "replace") + \
              (r.stdout or b"").decode("utf-8", "replace")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "brief": "TIMEOUT", "goal": "", "error": "",
                "compile_sec": round(time.time() - t0, 2)}
    el = round(time.time() - t0, 2)
    has_sorry = ("declaration uses `sorry`" in raw or
                 "declaration uses 'sorry'" in raw)
    if rc == 0 and not has_sorry and not ANY_ERR.search(raw):
        return {"status": "CLOSED", "brief": "OK", "goal": "", "error": "",
                "compile_sec": el}
    m = UNSOLVED.search(raw)
    if m:
        goal_lines = []
        for ln in raw[m.end():].splitlines():
            if NEW_DIAG.match(ln):
                break
            goal_lines.append(ln)
        goal = "\n".join(goal_lines).strip()
        return {"status": "UNSOLVED", "brief": "unsolved", "goal": goal,
                "error": "", "compile_sec": el, "raw_tail": raw[-800:]}
    err_lines = [ln for ln in raw.splitlines() if "error:" in ln]
    brief = err_lines[0][:200] if err_lines else ("rc=%s" % rc)
    return {"status": "ERROR", "brief": brief, "goal": "", "error": raw[-2000:],
            "compile_sec": el}


def run_one(it, base, key, model, max_steps=10, fix_rounds=2, search=True,
            empty_rejects=2):
    tactics = []
    trace = []
    search_ctx = []
    searches = []
    n_search = 0
    rejects = 0
    for step in range(1, max_steps + 1):
        code = build_code(it["formal_sig"], tactics)
        chk = compile_check(code, "%s_s%02d" % (it["tag"], step))
        if chk["status"] == "CLOSED":
            return {"pass": True, "steps": step - 1, "trace": trace,
                    "final_code": code, "stop": "CLOSED"}
        if chk["status"] == "TIMEOUT":
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": code, "stop": "TIMEOUT", "brief": "TIMEOUT"}
        if chk["status"] == "ERROR":
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": code, "stop": "COMPILE_ERROR",
                    "brief": chk["brief"], "error": chk.get("error", "")}
        # UNSOLVED: 把 goal 喂给模型
        goal = chk["goal"]
        current_proof = "\n".join("  " + t for t in tactics) if tactics else "(空)"
        base_prompt = ("当前目标状态：\n\n%s\n\n"
                       "已写的证明前缀：\n\n%s\n\n" % (goal, current_proof))
        llm_el = 0.0
        while True:
            prompt = base_prompt
            if search_ctx:
                prompt += ("已检索到的 Mathlib 声明（可直接引用）：\n\n%s\n\n"
                           % "\n\n".join(search_ctx))
            prompt += "请只写下一个 tactic 步骤。"
            t0 = time.time()
            try:
                reply, finish, usage = call_llm(base, key, model, prompt)
                parsed = parse_reply(reply)
                llm_err = ""
            except Exception as e:  # noqa: BLE001
                reply, finish, usage = "", "ERROR", {}
                parsed = {"search": "", "tactic": "", "reason": "", "raw": ""}
                llm_err = str(e)[:300]
            llm_el = round(llm_el + (time.time() - t0), 2)
            q = (parsed.get("search") or "").strip()
            if not q or llm_err or not search or n_search >= MAX_SEARCH:
                break
            n_search += 1
            hits = local_search(q)
            search_ctx.append("查询 `%s`：\n%s" % (q, fmt_hits(hits)))
            searches.append({"query": q, "n": len(hits)})
        tactic = parsed["tactic"]
        banned = bool(BANNED.search(tactic))
        rec = {"step": step, "goal": goal[:500], "tactic": tactic,
               "reason": parsed["reason"], "llm_sec": llm_el,
               "finish_reason": finish, "banned": banned,
               "llm_error": llm_err, "fixes": [], "searches": list(searches)}
        trace.append(rec)
        if llm_err:
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": code, "stop": "LLM_ERROR", "brief": llm_err}
        if not tactic:
            # ★ E41 单变量：不信任模型自报「已闭合」。
            #   此处必然刚编译过「前缀」（本步开头 status=UNSOLVED、goal 非空），
            #   证据在手 ⇒ 把目标原文回给模型，让它续写；不消耗步骤数。
            while rejects < empty_rejects and goal.strip():
                rejects += 1
                rp = (base_prompt +
                      "你上一步回答 EMPTY，理由是：%s\n\n"
                      "但我把当前证明前缀（不含新步骤）交给 Lean 编译，它仍然报"
                      "「unsolved goals」，也就是目标**还没有**闭合：\n\n%s\n\n"
                      "请不要再说 EMPTY。只写一个能推进当前目标的 tactic 步骤。"
                      % ((parsed.get("reason") or "(空)")[:200], goal))
                try:
                    rreply, rfinish, _ = call_llm(base, key, model, rp)
                    rparsed = parse_reply(rreply)
                except Exception as e:  # noqa: BLE001
                    rreply, rfinish = "", "ERROR:%s" % str(e)[:80]
                    rparsed = {"search": "", "tactic": "", "reason": "", "raw": ""}
                rec.setdefault("rejects", []).append(
                    {"round": rejects,
                     "claim": (parsed.get("reason") or "")[:200],
                     "new_tactic": (rparsed.get("tactic") or "")[:200],
                     "finish_reason": rfinish})
                parsed = rparsed
                tactic = rparsed.get("tactic") or ""
                rec["tactic"] = tactic
                rec["reason_after_reject"] = (rparsed.get("reason") or "")[:400]
            if not tactic:
                return {"pass": False, "steps": step, "trace": trace,
                        "final_code": code,
                        "stop": "EMPTY_CONFIRMED" if rejects else "EMPTY",
                        "brief": "EMPTY_CONFIRMED" if rejects else "EMPTY",
                        "rejects": rejects}
        if banned:
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": code, "stop": "BANNED", "brief": "BANNED"}

        # ★ 验证这一步：编译 tactics + [tactic]；ERROR 则把错误喂回修同一个 step
        cand_code = build_code(it["formal_sig"], tactics + [tactic])
        vchk = compile_check(cand_code, "%s_s%02d_v0" % (it["tag"], step))
        rounds = 0
        while vchk["status"] == "ERROR" and rounds < fix_rounds:
            rounds += 1
            err_raw = vchk.get("error") or ""
            auto_txt = ""
            if search:
                mnew = UNKNOWN_ID.search(err_raw)
                if mnew:
                    nm = mnew.group(1)
                    hits = local_search(nm)
                    auto_txt = ("\n\nMathlib 里与 `%s` 相近的真实声明：\n\n%s\n\n"
                                "请从中挑出正确的名字使用。"
                                % (nm, fmt_hits(hits)))
                    rec.setdefault("searches_auto", []).append(
                        {"query": nm, "n": len(hits)})
            fix_prompt = (base_prompt + auto_txt +
                          "你刚写的这一步：\n\n```lean\n%s\n```\n\n"
                          "编译失败，错误原文：\n\n```\n%s\n```\n\n"
                          "请**只重写这一步**（不要改前缀，不要写完整证明）。"
                          % (tactic, err_raw[:1200]))
            try:
                freply, ffinish, _ = call_llm(base, key, model, fix_prompt,
                                              system=FIX_SYSTEM)
                fparsed = parse_reply(freply)
            except Exception as e:  # noqa: BLE001
                fparsed = {"tactic": "", "reason": "", "raw": ""}
                ffinish = "ERROR:%s" % str(e)[:80]
            ftac = fparsed["tactic"]
            rec["fixes"].append({"round": rounds, "tactic": ftac,
                                 "error_before": (vchk.get("brief") or "")[:200],
                                 "finish_reason": ffinish})
            if not ftac or BANNED.search(ftac):
                break
            tactic = ftac
            cand_code = build_code(it["formal_sig"], tactics + [tactic])
            vchk = compile_check(cand_code,
                                 "%s_s%02d_v%d" % (it["tag"], step, rounds))
        rec["tactic"] = tactic
        rec["verify"] = vchk["status"]
        if vchk["status"] == "ERROR":
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": cand_code, "stop": "COMPILE_ERROR",
                    "brief": vchk["brief"], "error": vchk.get("error", "")}
        if vchk["status"] == "TIMEOUT":
            return {"pass": False, "steps": step, "trace": trace,
                    "final_code": cand_code, "stop": "TIMEOUT", "brief": "TIMEOUT"}
        if vchk["status"] == "CLOSED":
            return {"pass": True, "steps": step, "trace": trace,
                    "final_code": cand_code, "stop": "CLOSED"}
        tactics.append(tactic)
    code = build_code(it["formal_sig"], tactics)
    chk = compile_check(code, "%s_final" % it["tag"])
    return {"pass": chk["status"] == "CLOSED", "steps": max_steps, "trace": trace,
            "final_code": code, "stop": "MAX_STEPS", "brief": chk["brief"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="a", choices=["a", "b", "all"])
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--suffix", default="", help="输出文件名后缀，区分不同 prompt 版本")
    ap.add_argument("--fix-rounds", type=int, default=2,
                    help="单步编译失败后把错误喂回修正的轮数（0 = 不反馈）")
    ap.add_argument("--no-search", action="store_true",
                    help="关闭 Mathlib 检索通道（对照臂）")
    ap.add_argument("--empty-rejects", type=int, default=2,
                    help="EMPTY 后驳回续写的轮数（0 = 复现旧行为，直接终止）")
    args = ap.parse_args()

    base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("INTERN_API_BASE")
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("INTERN_API_KEY")
    model = os.environ.get("LLM_MODEL") or os.environ.get("INTERN_MODEL")
    if not (base and key and model):
        raise SystemExit("CONFIG_INCOMPLETE base/key/model")
    print("model =", model, "| prefill =", repr(PREFIX), flush=True)

    items = []
    if args.group in ("a", "all"):
        items += [{"tag": t, "formal_sig": s,
                   "goal_state": s.split(" := by")[0]
                   .replace("example : ", "⊢ ").replace("example ", "⊢ "),
                   "goal_nl": "(自检样本)"} for t, s in SIMPLE]
    if args.group in ("b", "all"):
        with open(GOALS, encoding="utf-8") as f:
            g = [x for x in json.load(f) if x.get("compile_ok")]
        items += [{"tag": "q%02d" % x["no"], "formal_sig": x["formal_sig"],
                   "goal_state": x["goal_state"], "goal_nl": x.get("goal_nl", ""),
                   "no": x["no"], "qid": x.get("qid", "")} for x in g]

    rows = []
    for idx, it in enumerate(items):
        t0 = time.time()
        r = run_one(it, base, key, model, max_steps=args.max_steps,
                    fix_rounds=args.fix_rounds, search=not args.no_search,
                    empty_rejects=args.empty_rejects)
        el = round(time.time() - t0, 2)
        row = dict(it)
        row.update(r)
        row["total_sec"] = el
        rows.append(row)
        status = "PASS" if r["pass"] else r["stop"]
        print("[%02d/%02d] %s %s steps=%d %ss" %
              (idx + 1, len(items), it["tag"], status, r["steps"], el),
              flush=True)

    out = "/tmp/l2probe/l2_step_probe_%s%s.json" % (args.group, args.suffix)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    p = sum(1 for r in rows if r.get("pass"))
    print("PASS %d / %d = %.0f%%" % (p, len(rows), 100.0 * p / len(rows)))
    print("WROTE", out)


if __name__ == "__main__":
    main()
