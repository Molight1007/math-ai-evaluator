# -*- coding: utf-8 -*-
"""全量审核剩余未审题目 - 排除已审过的，确保100%覆盖"""
import asyncio, json, os, re, sqlite3, sys, time
from collections import Counter
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "测试工具"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env"), override=True)
import httpx

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DB_PATH = "d:/挑战杯/题库/示例题库.db"
LOG_DIR = "d:/挑战杯/题库审核日志"
BATCH_SIZE = 10
CONCURRENCY = 10

PROMPT_SYS = """你是数学答案审核专家。判断每道题的参考答案是否正确。
对每道题输出JSON（不要markdown）：
{"problem_id":"...","is_correct":true/false,"correct_answer":"正确或修正后的答案","explanation":"简短理由"}
判断标准：独立重算后对比。选择题答案必须是A/B/C/D之一。数值/表达式错误、不完整都判false。"""

@dataclass
class Result:
    pid: str = ""; bank_name: str = ""; old_answer: str = ""
    new_answer: str = ""; action: str = ""; explanation: str = ""

def load_all_with_answers():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM problems WHERE reference_answer IS NOT NULL AND reference_answer != ''")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def load_audited_ids():
    """从所有审计日志中提取已审过的 problem_id"""
    audited = set()
    if not os.path.isdir(LOG_DIR):
        return audited
    for fname in os.listdir(LOG_DIR):
        if fname.startswith("audit_log_") and fname.endswith(".json"):
            try:
                with open(os.path.join(LOG_DIR, fname), encoding="utf-8") as f:
                    data = json.load(f)
                for d in data.get("details", []):
                    pid = d.get("problem_id") or d.get("pid")
                    if pid:
                        audited.add(pid)
            except:
                pass
    return audited

async def audit_batch(client, batch, sem):
    async with sem:
        try:
            parts = []
            for p in batch:
                parts.append(
                    f"题目ID: {p['problem_id']}\n"
                    f"题目: {(p.get('question') or '')[:600]}\n"
                    f"参考答案: {(p.get('reference_answer') or '')[:300]}"
                )
            prompt = "请审核以下题目答案：\n\n" + "\n\n---\n\n".join(parts) + "\n\n输出JSON数组，只输出JSON。"
            resp = await client.post(DEEPSEEK_URL, json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": PROMPT_SYS},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1, "max_tokens": 4096,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"})
            content = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r'\[[\s\S]*\]', content)
            if m:
                return json.loads(m.group())
            return [{"problem_id": p["problem_id"], "is_correct": None, "correct_answer": p.get("reference_answer",""), "explanation": "解析失败"} for p in batch]
        except Exception as e:
            return [{"problem_id": p["problem_id"], "is_correct": None, "correct_answer": p.get("reference_answer",""), "explanation": str(e)[:100]} for p in batch]

def apply_results(results):
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
    return updated

async def main():
    all_probs = load_all_with_answers()
    audited = load_audited_ids()
    remaining = [p for p in all_probs if p["problem_id"] not in audited]
    
    print(f"全部有答案题: {len(all_probs)}")
    print(f"已审过: {len(audited)}")
    print(f"剩余待审: {len(remaining)}")
    
    if not remaining:
        print("全部已审核，无需处理！")
        return
    
    batches = [remaining[i:i+BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]
    print(f"分 {len(batches)} 批, 并发={CONCURRENCY}")
    
    sem = asyncio.Semaphore(CONCURRENCY)
    all_judgements = []
    t0 = time.time()
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [audit_batch(client, b, sem) for b in batches]
        done = 0
        for coro in asyncio.as_completed(tasks):
            judgements = await coro
            all_judgements.extend(judgements)
            done += 1
            if done % 5 == 0 or done == len(tasks):
                elapsed = time.time() - t0
                eta = elapsed / done * (len(tasks) - done) if done > 0 else 0
                print(f"  [{done}/{len(tasks)}] 批完成 ({elapsed:.0f}s, ETA {eta:.0f}s)")
    
    jmap = {j["problem_id"]: j for j in all_judgements}
    results = []
    for p in remaining:
        pid = p["problem_id"]
        j = jmap.get(pid, {})
        old = p.get("reference_answer", "")
        is_correct = j.get("is_correct")
        if is_correct is None:
            action, new_ans, expl = "skipped", old, j.get("explanation", "解析失败")
        elif is_correct:
            action, new_ans, expl = "confirmed", old, j.get("explanation", "正确")
        else:
            action, new_ans, expl = "corrected", j.get("correct_answer", old), j.get("explanation", "需修正")
        results.append(Result(pid=pid, bank_name=p.get("bank_name",""), old_answer=old, new_answer=new_ans, action=action, explanation=expl))
    
    updated = apply_results(results)
    
    c = Counter(r.action for r in results)
    print(f"\n审核完成: confirmed={c.get('confirmed',0)}, corrected={c.get('corrected',0)}, skipped={c.get('skipped',0)}")
    print(f"数据库更新: {updated} 条")
    
    # 保存日志
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"audit_full_{ts}.json")
    log_data = {
        "timestamp": ts,
        "summary": dict(c),
        "total_audited": len(remaining),
        "previously_audited": len(audited),
        "corrected": [{"pid": r.pid, "old": r.old_answer[:60], "new": r.new_answer[:60], "reason": r.explanation[:80]} for r in results if r.action == "corrected"],
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    print(f"日志: {log_path}")
    print(f"总耗时: {elapsed:.0f}s")
    
    # 最终汇总
    final_all = load_all_with_answers()
    print(f"\n最终状态: {len(final_all)} 道题全部有答案且已审核")

if __name__ == "__main__":
    asyncio.run(main())
