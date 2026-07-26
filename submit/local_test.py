"""
本地测试脚本 — 模拟平台评测环境。

用法:
    # 设置 API Key
    set INTERN_API_KEY=sk-xxxx你的密钥xxxx
    # 或 Linux/Mac:
    export INTERN_API_KEY=sk-xxxx你的密钥xxxx

    # 运行测试
    python local_test.py --input sample_data/dev.jsonl --output outputs/

说明:
    - 本脚本仅用于本地调试，模拟平台 Runner 的调用流程
    - 会创建一个本地 InternChatClient 注入 agent
    - 正式评测时平台使用自己的 Runner，agent 代码与此脚本无关
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# ---- 日志 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("local_test")


# ============================================================
# InternChatClient — 本地模拟平台 Client
# 与平台注入的 client 接口保持一致: chat(messages, temp, max_tokens) -> str
# ============================================================
class InternChatClient:
    """
    本地测试用的 Intern-S API 客户端。

    接口与平台注入的 client 保持一致：
        client.chat(messages, temperature, max_tokens) -> str
    """

    def __init__(self, timeout: int = 120, retry: int = 3):
        self.api_key = os.getenv("INTERN_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "未设置 INTERN_API_KEY 环境变量。\n"
                "请执行: set INTERN_API_KEY=sk-xxxx你的密钥xxxx"
            )
        # 自动补全 Bearer 前缀
        if not self.api_key.startswith("Bearer "):
            self.api_key = f"Bearer {self.api_key}"

        self.base_url = os.getenv(
            "INTERN_API_BASE",
            "https://chat.intern-ai.org.cn/api/v1/chat/completions",
        )
        self.model = os.getenv("INTERN_MODEL", "intern-s2-preview")
        self.timeout = timeout
        self.retry = retry

    def chat(
        self,
        messages: list,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """调用 Intern-S API，返回模型回复文本"""
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        last_error = None
        for attempt in range(self.retry):
            try:
                req = urllib.request.Request(
                    self.base_url,
                    data=payload,
                    headers={
                        "Authorization": self.api_key,
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                if attempt < self.retry - 1:
                    wait = 2 ** attempt
                    logger.warning("API call failed (attempt %d/%d), retry in %ds: %s",
                                 attempt + 1, self.retry, wait, e)
                    time.sleep(wait)

        raise RuntimeError(f"API call failed after {self.retry} retries: {last_error}")


# ============================================================
# 加载题目
# ============================================================
def load_problems(input_file: str) -> list[dict]:
    """从 JSONL 文件加载题目"""
    problems = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            problems.append(item)
    logger.info("Loaded %d problems from %s", len(problems), input_file)
    return problems


# ============================================================
# 保存结果
# ============================================================
def save_result(output_dir: str, idx, result: dict):
    """保存单题结果到 outputs/{idx}.json"""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{idx}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="MathPilot 本地测试脚本")
    parser.add_argument(
        "--input", "--input_file",
        type=str, default="sample_data/dev.jsonl",
        help="输入 JSONL 文件路径（默认: sample_data/dev.jsonl）",
    )
    parser.add_argument(
        "--output", "--output_dir",
        type=str, default="outputs/",
        help="输出目录（默认: outputs/）",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="并发数（默认: 1，本地测试建议串行）",
    )
    parser.add_argument(
        "--samples", type=int, default=4,
        help="候选解答采样数（默认: 4）",
    )
    parser.add_argument(
        "--votes", type=int, default=2,
        help="每个候选的投票次数（默认: 2）",
    )
    parser.add_argument(
        "--no-domain-hint", action="store_true",
        help="禁用领域提示增强",
    )
    args = parser.parse_args()

    # 检查输入文件
    if not os.path.isfile(args.input):
        logger.error("Input file not found: %s", args.input)
        logger.info("请先准备题目数据 JSONL 文件，格式: {\"idx\": 0, \"problem\": \"题目文本\"}")
        sys.exit(1)

    # 创建 client
    logger.info("Creating InternChatClient...")
    try:
        client = InternChatClient()
        logger.info("Client created: model=%s", client.model)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    # 创建 agent
    from user_agent import ReasoningAgent
    agent = ReasoningAgent(
        client=client,
        policy_sample_times=args.samples,
        verifier_voting_times=args.votes,
        enable_domain_hint=not args.no_domain_hint,
    )
    logger.info("Agent created: samples=%d, votes=%d, domain_hint=%s",
                args.samples, args.votes, not args.no_domain_hint)

    # 加载题目
    problems = load_problems(args.input)

    # 评测
    logger.info("Starting evaluation (%d problems)...", len(problems))
    total_start = time.time()
    correct_count = 0

    for i, item in enumerate(problems):
        idx = item.get("idx", i)
        problem_text = item.get("problem", "")
        reference_answer = item.get("answer", None)

        # 断点续跑：已有结果则跳过
        existing = os.path.join(args.output, f"{idx}.json")
        if os.path.isfile(existing) and os.path.getsize(existing) > 0:
            logger.info("[%s] Already done, skipping", idx)
            continue

        logger.info("[%s] Solving... (%d/%d)", idx, i + 1, len(problems))
        t0 = time.time()

        try:
            result = agent.solve(problem_text, {"idx": idx})
            latency = round(time.time() - t0, 2)

            # 构建完整输出
            output = {
                "idx": idx,
                "status": "success",
                "final_response": result.get("final_response", ""),
                "trace": result.get("trace", []),
                "latency_seconds": latency,
            }

            # 如果有参考答案，进行简单比对
            if reference_answer:
                predicted = str(result.get("final_response", "")).strip()
                expected = str(reference_answer).strip()
                is_match = predicted == expected
                output["reference_answer"] = expected
                output["match"] = is_match
                if is_match:
                    correct_count += 1
                status = "✓" if is_match else "✗"
                logger.info("[%s] %s Answer: '%s' (expected: '%s') in %.1fs",
                           idx, status, predicted, expected, latency)
            else:
                logger.info("[%s] Done in %.1fs: '%s'",
                           idx, latency, output["final_response"][:80])

            save_result(args.output, idx, output)

        except Exception as e:
            latency = round(time.time() - t0, 2)
            logger.error("[%s] Error: %s", idx, e)

            output = {
                "idx": idx,
                "status": "error",
                "final_response": "",
                "error": {
                    "type": type(e).__name__,
                    "message": str(e),
                },
                "trace": [],
                "latency_seconds": latency,
            }
            save_result(args.output, idx, output)

    total_time = round(time.time() - total_start, 2)
    logger.info("=" * 50)
    logger.info("Evaluation complete: %d problems in %.1fs", len(problems), total_time)
    if reference_answer:
        logger.info("Accuracy: %d/%d (%.1f%%)",
                   correct_count, len(problems),
                   100 * correct_count / len(problems) if problems else 0)
    logger.info("Outputs saved to: %s", args.output)


if __name__ == "__main__":
    main()
