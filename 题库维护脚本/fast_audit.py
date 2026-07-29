# -*- coding: utf-8 -*-
"""
极速题库审核填充 - 高并发 + DeepSeek 批量审核
用法: python fast_audit.py [--fill-only] [--audit-only]
"""
import asyncio, json, os, re, sqlite3, sys, time, traceback
from dataclasses import dataclass
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "测试工具"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env"), override=True)
import httpx

# ===== 配置 =====
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DB_PATH = "d:/挑战杯/题库/示例题库.db"
OUT_DIR = "d:/挑战杯/题库审核日志"
FILL_CONCURRENCY = 30       # 填充并发数
AUDIT_BATCH_SIZE = 10       # 审核每批题数
AUDIT_CONCURRENCY = 8       # 审核批次并发数

PROMPT_FILL = """你是数学解题专家。请给出以下题目的最终答案。
规则：
1. 只输出最终答案，绝对不要输出推理过程。
2. 选择题只输出一个字母（A/B/C/D）。
3. 填空题/计算题输出最简数学表达式或数值。
4. 证明题简述关键结论。
题目："""

PROMPT_AUDIT_SYS = """你是数学答案审核专家。判断每道题的参考答案是否正确。
对每道题输出JSON（不要markdown代码块）：
{"problem_id":"...","is_correct":true/false,"correct_answer":"正确或修正后的答案","explanation":"简短理由"}
判断标准：独立重算后对比。选择题答案必须是A/B/C/D之一。数值/表达式错误、不完整都判false。"""

@dataclass
class Result:
    pid: str = ""
    bank_name: str = ""
    old_answer: str = ""
    new_answer: str = ""
    action: str = ""  # filled / confirmed / corrected / failed / skipped
    explanation: str = ""

def load_no_answer():
    """加载无答案题目"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems WHERE reference_answer IS NULL OR reference_answer=''")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def load_has_answer():
    """加载有答案题目 + 规则初筛标记"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems WHERE reference_answer IS NOT NULL AND reference_answer!=''")
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        ans = (d.get("reference_answer") or "").strip()
        is_sus = False
        reason = ""
        if ans.lower() in {"null","none","undefined","nan","无","略","n/a"}:
            is_sus = True; reason = "占位符"
        elif len(ans) < 2:
            is_sus = True; reason = "过短"
        elif len(ans) > 500 and "证明" not in (d.get("domain") or ""):
            is_sus = True; reason = "过长"
        elif re.search(r"无法求解|Cannot|Error|Parse error", ans, re.I):
            is_sus = True; reason = "错误模式"
        d["_suspicious"] = is_sus
        d["_reason"] = reason
        rows.append(d)
    conn.close()
    return rows

async def fill_one(client: httpx.AsyncClient, p: dict, sem: asyncio.Semaphore) -> Result:
    async with sem:
        q = (p.get("question") or "")[:1000]
        pid = p.get("problem_id","")
        try:
            resp = await client.post(DEEPSEEK_URL, json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role":"system","content":"你是一个数学解题专家，只输出最终答案。"},
                    {"role":"user","content": f"{PROMPT_FILL}\n{q}"}
                ],
                "temperature": 0.1, "max_tokens": 256,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"})
            data = resp.json()
            ans = data["choices"][0]["message"]["content"].strip()
            # 提取精简
            ans = re.sub(r'^最终答案[：:]\s*','', ans)
            ans = re.sub(r'^答案[为是][：:]\s*','', ans)
            return Result(pid=pid, bank_name=p.get("bank_name",""), old_answer="", new_answer=ans, action="filled", explanation="DeepSeek")
        except Exception as e:
            return Result(pid=pid, bank_name=p.get("bank_name",""), old_answer="", new_answer="", action="failed", explanation=str(e)[:100])

async def fill_all(problems: list[dict]) -> list[Result]:
    print(f"[fill] {len(problems)} 道无答案题, 并发={FILL_CONCURRENCY}")
    sem = asyncio.Semaphore(FILL_CONCURRENCY)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [fill_one(client, p, sem) for p in problems]
        results = []
        done_cnt = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done_cnt += 1
            if done_cnt % 50 == 0 or done_cnt == len(tasks):
                print(f"  [fill] {done_cnt}/{len(tasks)} (成功={sum(1 for x in results if x.action=='filled')}, 失败={sum(1 for x in results if x.action=='failed')})")
    return results

async def audit_batch(client: httpx.AsyncClient, batch: list[dict], sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        try:
            parts = [f"题目ID: {p['problem_id']}\n题目: {p.get('question','')[:500]}\n参考答案: {p.get('reference_answer','')[:300]}" for p in batch]
            prompt = "请审核以下题目答案：\n\n" + "\n\n---\n\n".join(parts) + "\n\n输出JSON数组。"
            resp = await client.post(DEEPSEEK_URL, json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role":"system","content": PROMPT_AUDIT_SYS},
                    {"role":"user","content": prompt}
                ],
                "temperature": 0.1, "max_tokens": 4096,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"})
            content = resp.json()["choices"][0]["message"]["content"]
            # 提取JSON
            m = re.search(r'\[[\s\S]*\]', content)
            if m:
                return json.loads(m.group())
            return [{"problem_id": p["problem_id"], "is_correct": None, "correct_answer": p.get("reference_answer",""), "explanation": "解析失败"} for p in batch]
        except Exception as e:
            return [{"problem_id": p["problem_id"], "is_correct": None, "correct_answer": p.get("reference_answer",""), "explanation": str(e)[:100]} for p in batch]

async def audit_all(problems: list[dict]) -> list[Result]:
    # 只审可疑题 + 10%正常题抽样
    suspicious = [p for p in problems if p.get("_suspicious")]
    normal = [p for p in problems if not p.get("_suspicious")]
    import random; random.seed(42)
    sampled = random.sample(normal, max(0, int(len(normal) * 0.1)))
    to_audit = suspicious + sampled
    print(f"[audit] 有答案={len(problems)}, 可疑={len(suspicious)}, 抽样={len(sampled)}, 总计={len(to_audit)}")

    batches = [to_audit[i:i+AUDIT_BATCH_SIZE] for i in range(0, len(to_audit), AUDIT_BATCH_SIZE)]
    print(f"[audit] {len(batches)} 批, 并发={AUDIT_CONCURRENCY}")

    sem = asyncio.Semaphore(AUDIT_CONCURRENCY)
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [audit_batch(client, b, sem) for b in batches]
        all_judgements = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            judgements = await coro
            all_judgements.extend(judgements)
            done += 1
            if done % 5 == 0 or done == len(tasks):
                print(f"  [audit] {done}/{len(tasks)} 批完成")
    
    jmap = {j["problem_id"]: j for j in all_judgements}
    results = []
    for p in to_audit:
        pid = p["problem_id"]
        j = jmap.get(pid, {})
        old = p.get("reference_answer","")
        is_correct = j.get("is_correct")
        if is_correct is None:
            action = "skipped"
            new_ans = old
            expl = j.get("explanation","解析失败")
        elif is_correct:
            action = "confirmed"
            new_ans = old
            expl = j.get("explanation","正确")
        else:
            action = "corrected"
            new_ans = j.get("correct_answer", old)
            expl = j.get("explanation","需修正")
        results.append(Result(pid=pid, bank_name=p.get("bank_name",""), old_answer=old, new_answer=new_ans, action=action, explanation=expl))
    return results

def apply_results(results: list[Result]):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updated = 0
    for r in results:
        if r.action in ("filled", "corrected") and r.new_answer:
            cur.execute("UPDATE problems SET reference_answer=? WHERE bank_name=? AND problem_id=?",
                       (r.new_answer, r.bank_name, r.pid))
            if cur.rowcount > 0:
                updated += 1
    conn.commit()
    conn.close()
    print(f"[apply] 更新 {updated} 条记录")

def save_log(results: list[Result], note=""):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUT_DIR, f"audit_log_{ts}.json")
    data = {
        "timestamp": ts, "note": note,
        "summary": dict(Counter(r.action for r in results)),
        "filled": [{"pid":r.pid,"answer":r.new_answer} for r in results if r.action=="filled"],
        "corrected": [{"pid":r.pid,"old":r.old_answer,"new":r.new_answer,"reason":r.explanation} for r in results if r.action=="corrected"],
        "failed": [{"pid":r.pid,"reason":r.explanation} for r in results if r.action=="failed"],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[log] {path}")
    return path

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fill-only", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    t0 = time.time()
    all_results = []

    if not args.audit_only:
        no_ans = load_no_answer()
        print(f"=== 阶段1: 填充无答案 ({len(no_ans)} 道) ===")
        if no_ans:
            fill_results = await fill_all(no_ans)
            all_results.extend(fill_results)
            apply_results(fill_results)
            print(f"  filled={sum(1 for r in fill_results if r.action=='filled')}, failed={sum(1 for r in fill_results if r.action=='failed')}")
        else:
            print("  无答案题目为空，跳过")

    if not args.fill_only:
        has_ans = load_has_answer()
        print(f"\n=== 阶段2: 审核答案 ({len(has_ans)} 道) ===")
        if has_ans:
            audit_results = await audit_all(has_ans)
            all_results.extend(audit_results)
            apply_results(audit_results)
            c = Counter(r.action for r in audit_results)
            print(f"  confirmed={c.get('confirmed',0)}, corrected={c.get('corrected',0)}, skipped={c.get('skipped',0)}")
        else:
            print("  无有答案题目，跳过")

    save_log(all_results)
    elapsed = time.time() - t0
    print(f"\n=== 完成! 总耗时 {elapsed:.1f}s ===")

if __name__ == "__main__":
    asyncio.run(main())
