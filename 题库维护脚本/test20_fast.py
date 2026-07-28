# -*- coding: utf-8 -*-
"""20题快速验证 - DeepSeek解题 vs 题库参考答案"""
import asyncio, json, time, sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "测试工具"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.expanduser("~"), ".math_evaluator", ".env"), override=True)
import httpx

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

with open("test_20.json", encoding="utf-8") as f:
    problems = json.load(f)

print(f"测试 {len(problems)} 道题, DeepSeek解题 + 对比答案\n")

async def solve_one(client, p, sem):
    async with sem:
        q = p.get("question", "")
        ref = p.get("reference_answer", "")
        try:
            resp = await client.post(DEEPSEEK_URL, json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "你是数学解题专家。只输出最终答案，不要任何解释。选择题只输出字母A/B/C/D，计算题输出最简表达式或数值，证明题简述结论。"},
                    {"role": "user", "content": f"题目：{q}"}
                ],
                "temperature": 0.1, "max_tokens": 256,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"})
            ans = resp.json()["choices"][0]["message"]["content"].strip()
            
            # 评判
            resp2 = await client.post(DEEPSEEK_URL, json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "你是判断题专家。判断两个数学答案是否等价。只输出 true 或 false。"},
                    {"role": "user", "content": f"参考答案：{ref}\n模型答案：{ans}\n这两个答案是否等价？"}
                ],
                "temperature": 0, "max_tokens": 10,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"})
            match = "true" in resp2.json()["choices"][0]["message"]["content"].strip().lower()
            
            return {
                "id": p["id"],
                "question": q[:60],
                "reference": ref[:60],
                "model_answer": ans[:80],
                "match": match,
            }
        except Exception as e:
            return {"id": p["id"], "question": q[:60], "reference": ref[:60], "model_answer": f"ERROR: {e}", "match": False}

async def main():
    sem = asyncio.Semaphore(20)
    t0 = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [solve_one(client, p, sem) for p in problems]
        results = await asyncio.gather(*tasks)
    
    correct = sum(1 for r in results if r["match"])
    print(f"\n{'='*60}")
    for i, r in enumerate(results):
        status = "OK" if r["match"] else "FAIL"
        print(f"{i+1:2d}. [{status}] {r['id']}")
        print(f"    题目: {r['question']}...")
        print(f"    参考: {r['reference']}")
        print(f"    模型: {r['model_answer']}")
        print(f"    {'OK' if r['match'] else 'FAIL'}")
    
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"结果: {correct}/{len(problems)} 正确 ({correct/len(problems)*100:.0f}%)")
    print(f"耗时: {elapsed:.1f}s")

    # 保存
    with open("测试结果/test20_result.json", "w", encoding="utf-8") as f:
        json.dump({"correct": correct, "total": len(problems), "elapsed": elapsed, "results": results}, f, ensure_ascii=False, indent=2)
    
    return correct, len(problems)

correct, total = asyncio.run(main())
