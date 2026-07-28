"""临时测试脚本：从题库随机抽取 20 题运行评测。"""
import asyncio, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from main import run_evaluation_from_bank


async def main():
    start = time.time()
    try:
        html = await run_evaluation_from_bank(
            '1000题高数', count=20, concurrency=5, multi_agent=False
        )
        elapsed = time.time() - start
        print(f"\n{'='*60}")
        print(f"测试完成！耗时 {elapsed:.1f}s")
        print(f"HTML 报告: {html}")
        print(f"{'='*60}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
