"""Local debug entry point for batch running JSONL samples."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from user_agent import ReasoningAgent


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from .env into os.environ (no overwrite)."""
    env_path = Path(path)
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


class FakeClient:
    """Fake client for local testing without API."""

    def chat(self, messages, temperature=0.2, max_tokens=4096):
        return "分析：这是测试。\n最终答案：42"


def load_jsonl(path: str) -> list:
    """Load JSONL file, one JSON object per line."""
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def skip_if_exists(output_path: Path) -> bool:
    """Return True if output exists and is non-empty."""
    if not output_path.exists():
        return False
    try:
        content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            return False
        data = json.loads(content)
        return bool(data.get("final_response", "").strip())
    except (json.JSONDecodeError, OSError):
        return False


def run_one(agent: ReasoningAgent, item: dict) -> dict:
    """Run agent on one item."""
    idx = item.get("idx", 0)
    problem = item.get("problem", "")
    metadata = {k: v for k, v in item.items() if k not in ("problem", "answer")}
    try:
        result = agent.solve(problem=problem, metadata=metadata)
        return {
            "idx": idx,
            "status": "success",
            "final_response": result.get("final_response", ""),
            "trace": result.get("trace", []),
        }
    except Exception as e:
        return {
            "idx": idx,
            "status": "error",
            "final_response": "无法确定",
            "error": {"type": type(e).__name__, "message": str(e)[:500]},
            "trace": [],
        }


def save_result(output_dir: Path, idx: int, result: dict) -> None:
    """Save result to output_dir/{idx}.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{idx}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def create_local_client(use_fake: bool):
    """Create client for local debugging against 书生 ChatAPI."""
    if use_fake:
        return FakeClient()

    load_dotenv()
    # Re-import after dotenv so config picks up env vars
    import importlib

    import config as config_mod

    importlib.reload(config_mod)

    api_key = config_mod.INTERN_API_KEY
    base_url = config_mod.INTERN_API_BASE
    model = config_mod.INTERN_MODEL

    if not api_key:
        print("Warning: INTERN_API_KEY not set, using FakeClient.", file=sys.stderr)
        return FakeClient()

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)

        class LocalClient:
            def chat(self, messages, temperature=0.2, max_tokens=4096):
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content

        print(f"Using 书生 API: model={model}, base={base_url}", file=sys.stderr)
        return LocalClient()
    except ImportError:
        print("Warning: openai not installed, using FakeClient.", file=sys.stderr)
        return FakeClient()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Local math agent runner")
    parser.add_argument(
        "--input_file",
        default="sample_data/dev.jsonl",
        help="Input JSONL file path",
    )
    parser.add_argument(
        "--output_dir",
        default="sample_outputs",
        help="Output directory for results",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of problems to run (0 = all)",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Use FakeClient instead of real API",
    )
    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    items = load_jsonl(str(input_path))
    if args.limit > 0:
        items = items[: args.limit]

    client = create_local_client(use_fake=args.fake)
    agent = ReasoningAgent(client=client)

    ran = 0
    skipped = 0
    for item in items:
        idx = item.get("idx", ran)
        output_path = output_dir / f"{idx}.json"
        if skip_if_exists(output_path):
            skipped += 1
            continue
        result = run_one(agent, item)
        save_result(output_dir, idx, result)
        ran += 1
        print(f"[{idx}] {result['status']}: {result['final_response'][:80]}")

    print(f"Done. ran={ran}, skipped={skipped}, total={len(items)}")


if __name__ == "__main__":
    main()
