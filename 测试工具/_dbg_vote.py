# -*- coding: utf-8 -*-
"""验证 run_inference_multi_vote 的投票聚合逻辑（mock 采样，不调用真实 API）。"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import intern_s1
from models import Problem, InferenceResult


async def main():
    # 用 mock 的 _run_inference_with_sample 模拟 3 个采样
    async def fake_sample(problem, sample_index, temperature):
        answers = {
            0: r"\boxed{\frac{1}{2}}",
            1: "0.5",
            2: r"$\frac{1}{2}$",
        }
        return InferenceResult(
            problem_id=problem.id, question=problem.question,
            answer=answers.get(sample_index, ""),
            reasoning=f"sample {sample_index} reasoning",
            raw_response="raw",
            tokens_used=100 + sample_index,
            latency_seconds=1.0 + sample_index,
        )

    intern_s1._run_inference_with_sample = fake_sample

    problem = Problem(id="p1", question="Compute 1/2", reference_answer="0.5")
    winner = await intern_s1.run_inference_multi_vote(problem, num_samples=3)

    lines = []
    lines.append(f"winner.answer = {winner.answer!r}")
    lines.append(f"winner.sample_index = {winner.sample_index}")
    lines.append(f"winner.vote_info = {winner.vote_info}")
    lines.append(f"winner.tokens_used = {winner.tokens_used} (expected {100 + 101 + 102})")
    lines.append(f"winner.latency_seconds = {winner.latency_seconds}")
    keys = list(winner.vote_info["vote_counts"].keys())
    lines.append(f"vote_counts keys = {keys}")

    assert winner.answer in ("0.5", r"\frac{1}{2}", r"$\frac{1}{2}$")
    assert len(keys) == 1, keys
    assert winner.vote_info["vote_counts"][keys[0]] == 3
    assert winner.vote_info["num_samples"] == 3
    assert winner.vote_info["tie_broken"] is False
    assert winner.tokens_used == 100 + 101 + 102, winner.tokens_used
    lines.append("[PASS] run_inference_multi_vote aggregate")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dbg_vote_out.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


asyncio.run(main())
