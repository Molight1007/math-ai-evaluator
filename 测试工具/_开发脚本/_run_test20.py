"""20 题正式测试 — 逐题评判模式（可靠）"""
import asyncio, os, sys, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')

from main import run_evaluation_from_bank

async def main():
    html = await run_evaluation_from_bank(
        '1000题高数', count=20, concurrency=10, multi_agent=False
    )
    print(f"\nDONE: {html}")

asyncio.run(main())
