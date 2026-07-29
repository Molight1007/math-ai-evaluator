import asyncio
import os
import sys

sys.path.insert(0, r'd:/挑战杯/测试工具')
os.chdir(r'd:/挑战杯/测试工具')

from main import run_evaluation_from_bank

async def main():
    html = await run_evaluation_from_bank(
        bank_name='1000题高数',
        count=20,
        concurrency=3,
        multi_agent=False,
    )
    print('HTML report:', html)

if __name__ == '__main__':
    asyncio.run(main())
