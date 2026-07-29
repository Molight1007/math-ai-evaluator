from __future__ import annotations

import argparse
import contextlib
import json
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

from .clients.interns1_client import InternS1Client
from .control.hard_mode import build_hard_mode_policy
from .logging_utils import safe_trace_filename
from .pipeline import solve_question
from .schemas import MathQuestion, make_failure_result

_RETRY_STATUSES = {"fail", "partial"}
_MAX_JSONL_LINE_CHARS = 1_000_000
_MAX_RESUME_FILE_BYTES = 500_000_000


def _validate_real_mode_or_raise(real: bool) -> None:
    if not real:
        return
    InternS1Client(mock=False)._validate_real_mode_config()


def _validate_batch_paths(args: argparse.Namespace) -> None:
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if input_path == output_path:
        raise ValueError("batch input and output paths must be different")
    stats_value = getattr(args, "stats", None)
    if stats_value:
        stats_path = Path(stats_value).resolve()
        if stats_path in {input_path, output_path}:
            raise ValueError(
                "batch input, output, and stats paths must be different"
            )


@contextlib.contextmanager
def _open_batch_output(output_path: Path, mode: str) -> Iterator[TextIO]:
    if mode == "a":
        with output_path.open("a", encoding="utf-8") as handle:
            yield handle
        return
    if mode != "w":
        raise ValueError(f"unsupported output mode: {mode}")

    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open("x", encoding="utf-8") as handle:
            yield handle
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _load_resume_rows(
    output_path: Path, retry_failed: bool
) -> tuple[list[str], set[str], set[str]]:
    if not output_path.exists():
        return [], set(), set()
    if output_path.stat().st_size > _MAX_RESUME_FILE_BYTES:
        raise ValueError("existing resume output exceeds the file size limit")
    kept_lines: list[str] = []
    skip_ids: set[str] = set()
    retry_ids: set[str] = set()
    seen_ids: set[str] = set()
    with output_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if len(raw_line) > _MAX_JSONL_LINE_CHARS:
                raise ValueError(
                    f"existing resume output line {line_number} exceeds the size limit"
                )
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"existing resume output has invalid JSON at line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(
                    f"existing resume output line {line_number} is not an object"
                )
            qid = str(row.get("question_id", "")).strip()
            status = str(row.get("status", "")).strip()
            if not qid:
                raise ValueError(
                    f"existing resume output line {line_number} has no question_id"
                )
            if qid in seen_ids:
                raise ValueError(
                    f"existing resume output contains duplicate question_id: {qid}"
                )
            seen_ids.add(qid)
            if retry_failed and status in _RETRY_STATUSES:
                retry_ids.add(qid)
                continue
            kept_lines.append(line)
            skip_ids.add(qid)
    return kept_lines, skip_ids, retry_ids


def _read_trace_budget(trace_dir: str | Path, question_id: str) -> dict[str, int]:
    trace_path = Path(trace_dir) / safe_trace_filename(question_id)
    if not trace_path.exists():
        return {"model_calls": 0, "tool_calls": 0, "trace_found": 0}
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"model_calls": 0, "tool_calls": 0, "trace_found": 0}
    model_calls = trace.get("model_calls", [])
    tool_calls = trace.get("tool_calls", [])
    return {
        "model_calls": len(model_calls) if isinstance(model_calls, list) else 0,
        "tool_calls": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "trace_found": 1,
    }


def _int_stat(stats: dict[str, object], key: str) -> int:
    value = stats.get(key, 0)
    return value if isinstance(value, int) else 0


def _float_stat(stats: dict[str, object], key: str) -> float:
    value = stats.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def cmd_solve(args: argparse.Namespace) -> int:
    _validate_real_mode_or_raise(args.real)
    hard_mode_policy = None
    if args.hard_mode:
        hard_mode_policy = build_hard_mode_policy(
            enabled=True, level=args.hard_mode_level
        )
    result = solve_question(
        MathQuestion(question=args.question, question_id=args.question_id),
        mock=not args.real,
        enable_tools=args.enable_tools,
        save_trace=not args.no_trace,
        trace_dir=args.trace_dir,
        run_mode=args.mode,
        hard_mode_policy=hard_mode_policy,
    )
    print(result.model_dump_json(ensure_ascii=False))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    _validate_real_mode_or_raise(args.real)
    _validate_batch_paths(args)
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    kept_lines: list[str] = []
    skip_ids: set[str] = set()
    retry_ids: set[str] = set()
    if args.resume:
        kept_lines, skip_ids, retry_ids = _load_resume_rows(
            output_path, args.retry_failed
        )
    mode = "a" if args.resume and not args.retry_failed else "w"
    batch_started = time.perf_counter()
    stats: dict[str, object] = {
        "input": str(input_path),
        "output": str(output_path),
        "mode": args.mode,
        "real": bool(args.real),
        "enable_tools": bool(args.enable_tools),
        "trace_dir": str(args.trace_dir),
        "resume": bool(args.resume),
        "retry_failed": bool(args.retry_failed),
        "input_count": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "retry_failed_count": len(retry_ids),
        "kept_existing_count": len(kept_lines),
        "error_count": 0,
        "status_counts": {},
        "total_elapsed_seconds": 0.0,
        "average_elapsed_seconds": 0.0,
        "total_model_calls": 0,
        "total_tool_calls": 0,
        "trace_found_count": 0,
    }
    status_counts: dict[str, int] = {}
    with (
        input_path.open("r", encoding="utf-8") as fin,
        _open_batch_output(output_path, mode) as fout,
    ):
        if mode == "w" and kept_lines:
            fout.write("\n".join(kept_lines) + "\n")
        for idx, line in enumerate(fin):
            if not line.strip():
                continue
            stats["input_count"] = _int_stat(stats, "input_count") + 1
            raw = {}
            item_started = time.perf_counter()
            try:
                if len(line) > _MAX_JSONL_LINE_CHARS:
                    raise ValueError(
                        "input JSONL line length limit exceeded"
                    )
                raw = json.loads(line)
                q = MathQuestion.model_validate(raw)
                if q.question_id in skip_ids:
                    stats["skipped_count"] = _int_stat(stats, "skipped_count") + 1
                    continue
                result = solve_question(
                    q,
                    mock=not args.real,
                    enable_tools=args.enable_tools,
                    save_trace=not args.no_trace,
                    trace_dir=args.trace_dir,
                    run_mode=args.mode,
                )
            except Exception as exc:
                qid = (
                    str(raw.get("question_id", f"line_{idx}"))
                    if isinstance(raw, dict)
                    else f"line_{idx}"
                )
                question = str(raw.get("question", "")) if isinstance(raw, dict) else ""
                result = make_failure_result(
                    question_id=qid, question=question, error_message=str(exc)
                )
                stats["error_count"] = _int_stat(stats, "error_count") + 1
            fout.write(result.model_dump_json(ensure_ascii=False) + "\n")
            elapsed = time.perf_counter() - item_started
            stats["processed_count"] = _int_stat(stats, "processed_count") + 1
            stats["total_elapsed_seconds"] = (
                _float_stat(stats, "total_elapsed_seconds") + elapsed
            )
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
            if not args.no_trace:
                budget = _read_trace_budget(args.trace_dir, result.question_id)
                stats["total_model_calls"] = (
                    _int_stat(stats, "total_model_calls") + budget["model_calls"]
                )
                stats["total_tool_calls"] = (
                    _int_stat(stats, "total_tool_calls") + budget["tool_calls"]
                )
                stats["trace_found_count"] = (
                    _int_stat(stats, "trace_found_count") + budget["trace_found"]
                )
    total_elapsed = time.perf_counter() - batch_started
    processed = _int_stat(stats, "processed_count")
    stats["wall_elapsed_seconds"] = total_elapsed
    stats["average_elapsed_seconds"] = (
        _float_stat(stats, "total_elapsed_seconds") / processed if processed else 0.0
    )
    stats["average_model_calls_per_item"] = (
        _int_stat(stats, "total_model_calls") / processed if processed else 0.0
    )
    stats["status_counts"] = dict(sorted(status_counts.items()))
    if args.stats:
        stats_path = Path(args.stats)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(str(output_path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="math_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    solve_p = sub.add_parser("solve")
    solve_p.add_argument("--question", required=True)
    solve_p.add_argument("--question-id", default="cli_q")
    solve_p.add_argument("--real", action="store_true", default=False)
    solve_p.add_argument("--enable-tools", action="store_true", default=False)
    solve_p.add_argument("--trace-dir", default="outputs/traces")
    solve_p.add_argument("--no-trace", action="store_true", default=False)
    solve_p.add_argument(
        "--mode", choices=["full", "fast", "tool-first"], default="full"
    )
    solve_p.add_argument("--hard-mode", action="store_true", default=False)
    solve_p.add_argument(
        "--hard-mode-level",
        choices=["off", "light", "standard", "strict"],
        default="standard",
    )
    solve_p.set_defaults(func=cmd_solve)
    batch_p = sub.add_parser("batch")
    batch_p.add_argument("--input", required=True)
    batch_p.add_argument("--output", required=True)
    batch_p.add_argument("--real", action="store_true", default=False)
    batch_p.add_argument("--enable-tools", action="store_true", default=False)
    batch_p.add_argument("--trace-dir", default="outputs/traces")
    batch_p.add_argument("--no-trace", action="store_true", default=False)
    batch_p.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Skip question_ids already present in the output file.",
    )
    batch_p.add_argument(
        "--retry-failed",
        action="store_true",
        default=False,
        help="With --resume, keep successful rows and rerun fail/partial rows.",
    )
    batch_p.add_argument(
        "--mode", choices=["full", "fast", "tool-first"], default="full"
    )
    batch_p.add_argument(
        "--stats",
        default=None,
        help="Optional JSON path for batch budget/runtime statistics.",
    )
    batch_p.set_defaults(func=cmd_batch)
    return parser


def main() -> int:
    load_dotenv(override=False)
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
